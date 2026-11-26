"""
src/drive_manager.py — Quản lý Google Drive API v3:
- Đọc/ghi đè `history_log.json` trong thư mục gốc GDRIVE_FOLDER_ID.
- Quét toàn bộ thư mục con hiện có trên Google Drive để lấy số thứ tự tiếp theo (bắt đầu từ 1).
- Tạo thư mục con đặt tên theo `<số thứ tự> - <chủ đề video>` (ví dụ: `1 - 4 Nguyên Lý Khắc Kỷ`).
- Upload đồng thời cả Video `.mp4` và Thumbnail `.png` vào đúng thư mục con đó.
"""

from __future__ import annotations

from contextlib import contextmanager
import io
import json
import logging
import re
import ssl
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, TypeVar

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload, MediaIoBaseUpload

import config
from src.gcp_auth import load_gcp_service_account

logger = logging.getLogger("drive_manager")
T = TypeVar("T")

_LEADING_NUMBER_RE = re.compile(r"^\s*(\d+)(?:[\s._\-–—]|$)")
_INVALID_FOLDER_CHARS_RE = re.compile(r'[/\\:*?"<>|\r\n\t]+')
_RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}


class DriveManager:
    """
    Wrapper an toàn cho Google Drive API v3 (xác thực qua file Service Account JSON).
    KHÔNG giữ kết nối Drive mở xuyên suốt phiên chạy: chỉ mở kết nối mới ngay trước
    mỗi lần đọc/upload và đóng ngay lập tức sau khi hoàn tất để tránh triệt để lỗi BrokenPipeError.
    """

    def __init__(self, folder_id: Optional[str] = None) -> None:
        self.folder_id = folder_id or config.GDRIVE_FOLDER_ID
        if not self.folder_id:
            raise EnvironmentError(
                "Thiếu biến môi trường GDRIVE_FOLDER_ID. Hãy chia sẻ thư mục Google Drive "
                "cho email Service Account (quyền Editor) và lưu Folder ID vào GitHub Secrets hoặc .env."
            )

        auth = load_gcp_service_account()
        self._credentials = auth.credentials

    @contextmanager
    def _open_service(self) -> Iterator[Any]:
        """Mở kết nối Google Drive mới đúng lúc cần dùng và luôn đóng ngay khi xong."""
        service = build("drive", "v3", credentials=self._credentials, cache_discovery=False)
        try:
            yield service
        finally:
            try:
                service.close()
            except Exception:
                pass

    def _run_drive_op(self, op_name: str, fn: Callable[[Any], T], max_attempts: int = 3) -> T:
        """
        Mở phiên kết nối Drive mới, thực thi tác vụ rồi đóng ngay lập tức.
        Nếu gặp lỗi mạng tạm thời hoặc HTTP 429/5xx thì tự động mở phiên mới và thử lại.
        """
        last_exc: Optional[Exception] = None
        for attempt in range(1, max_attempts + 1):
            try:
                with self._open_service() as service:
                    return fn(service)
            except HttpError as exc:
                last_exc = exc
                status = getattr(getattr(exc, "resp", None), "status", None)
                if status in _RETRYABLE_HTTP_CODES and attempt < max_attempts:
                    wait_sec = 2 * attempt
                    logger.warning(
                        "[DRIVE RETRY] %s gặp HTTP %s (lần %d/%d). Thử lại sau %ds...",
                        op_name,
                        status,
                        attempt,
                        max_attempts,
                        wait_sec,
                    )
                    time.sleep(wait_sec)
                    continue
                raise
            except (BrokenPipeError, ConnectionError, TimeoutError, ssl.SSLError, OSError) as exc:
                last_exc = exc
                if attempt < max_attempts:
                    wait_sec = 2 * attempt
                    logger.warning(
                        "[DRIVE RECONNECT] %s gặp lỗi kết nối '%s' (lần %d/%d). Thử lại sau %ds...",
                        op_name,
                        exc,
                        attempt,
                        max_attempts,
                        wait_sec,
                    )
                    time.sleep(wait_sec)
                    continue
                raise
        assert last_exc is not None
        raise last_exc

    @staticmethod
    def sanitize_folder_title(title: str, max_len: int = 72) -> str:
        """Làm sạch tên chủ đề để đặt tên thư mục Google Drive đẹp, giữ dấu tiếng Việt."""
        cleaned = _INVALID_FOLDER_CHARS_RE.sub(" ", (title or "").strip())
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-_")
        if len(cleaned) > max_len:
            cleaned = cleaned[:max_len].rsplit(" ", 1)[0].strip(" .-_")
        return cleaned or "Video Khắc Kỷ"

    @classmethod
    def format_numbered_folder_name(cls, seq_num: int, topic_title: str) -> str:
        """Định dạng tên thư mục chuẩn: `<số thứ tự> - <chủ đề video>` (bắt đầu từ 1)."""
        safe_title = cls.sanitize_folder_title(topic_title)
        return f"{max(1, int(seq_num))} - {safe_title}"

    def list_subfolders(self, parent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Liệt kê toàn bộ thư mục con trực tiếp trong thư mục đích (mở kết nối rồi đóng ngay)."""
        root_id = parent_id or self.folder_id
        query = (
            f"'{root_id}' in parents "
            "and mimeType = 'application/vnd.google-apps.folder' "
            "and trashed = false"
        )

        def _do_list(service: Any) -> List[Dict[str, Any]]:
            folders: List[Dict[str, Any]] = []
            page_token: Optional[str] = None
            while True:
                response = (
                    service.files()
                    .list(
                        q=query,
                        spaces="drive",
                        fields="nextPageToken, files(id, name, createdTime)",
                        supportsAllDrives=True,
                        includeItemsFromAllDrives=True,
                        pageSize=200,
                        pageToken=page_token,
                    )
                    .execute()
                )
                folders.extend(response.get("files", []))
                page_token = response.get("nextPageToken")
                if not page_token:
                    break
            return folders

        return self._run_drive_op("list_subfolders", _do_list)

    def get_next_folder_sequence(self) -> int:
        """
        Kiểm tra tất cả tên thư mục con hiện có trên Google Drive, tìm số thứ tự lớn nhất
        (dạng `1 - ...`, `2_...`, `15. ...`) và trả về số thứ tự kế tiếp (bắt đầu từ 1 nếu chưa có).
        """
        folders = self.list_subfolders()
        max_num = 0
        for f in folders:
            name = str(f.get("name", ""))
            match = _LEADING_NUMBER_RE.match(name)
            if match:
                num = int(match.group(1))
                if num > max_num:
                    max_num = num

        next_num = max_num + 1
        logger.info(
            "[DRIVE SEQ] Đã quét %d thư mục trên Drive (số lớn nhất=%d) -> Số thứ tự tiếp theo: %d",
            len(folders),
            max_num,
            next_num,
        )
        return next_num

    def get_or_create_subfolder(self, folder_name: str, parent_id: Optional[str] = None) -> str:
        """Tìm thư mục con theo tên (tránh trùng khi retry); nếu chưa có thì tạo mới rồi đóng kết nối."""
        root_id = parent_id or self.folder_id
        safe_name = folder_name.replace("'", "\\'")
        query = (
            f"name = '{safe_name}' and '{root_id}' in parents "
            "and mimeType = 'application/vnd.google-apps.folder' "
            "and trashed = false"
        )

        def _do_get_or_create(service: Any) -> str:
            response = (
                service.files()
                .list(
                    q=query,
                    spaces="drive",
                    fields="files(id, name)",
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    pageSize=5,
                )
                .execute()
            )
            existing = response.get("files", [])
            if existing:
                folder_id = existing[0]["id"]
                logger.info("[DRIVE FOLDER] Dùng lại thư mục sẵn có '%s' (id=%s).", folder_name, folder_id)
                return folder_id

            metadata = {
                "name": folder_name,
                "parents": [root_id],
                "mimeType": "application/vnd.google-apps.folder",
            }
            created = (
                service.files()
                .create(
                    body=metadata,
                    fields="id, name, webViewLink",
                    supportsAllDrives=True,
                )
                .execute()
            )
            folder_id = created["id"]
            logger.info(
                "[DRIVE FOLDER CREATED] '%s' -> id=%s | link=%s",
                folder_name,
                folder_id,
                created.get("webViewLink", "N/A"),
            )
            return folder_id

        return self._run_drive_op(f"get_or_create_subfolder({folder_name})", _do_get_or_create)

    def _find_file_in_folder(
        self,
        service: Any,
        filename: str,
        parent_id: Optional[str] = None,
    ) -> Optional[str]:
        """Tìm file_id của một file theo tên chính xác bên trong thư mục đích trên phiên Drive đang mở."""
        root_id = parent_id or self.folder_id
        safe_name = filename.replace("'", "\\'")
        query = (
            f"name = '{safe_name}' and '{root_id}' in parents "
            "and trashed = false"
        )
        response = (
            service.files()
            .list(
                q=query,
                spaces="drive",
                fields="files(id, name, modifiedTime)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                pageSize=5,
            )
            .execute()
        )
        files = response.get("files", [])
        if not files:
            return None
        return files[0]["id"]

    def download_json(self, filename: str) -> Optional[Dict[str, Any]]:
        """Mở kết nối Drive để tải file JSON rồi đóng ngay. Trả về None nếu file chưa tồn tại."""

        def _do_download(service: Any) -> Optional[Dict[str, Any]]:
            file_id = self._find_file_in_folder(service, filename)
            if not file_id:
                logger.info("[DRIVE] Không tìm thấy '%s' trên Drive. Sẽ khởi tạo mới.", filename)
                return None

            request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            buffer.seek(0)
            raw_text = buffer.read().decode("utf-8")
            data = json.loads(raw_text)
            logger.info("[DRIVE] Đã tải thành công '%s' (file_id=%s).", filename, file_id)
            return data

        return self._run_drive_op(f"download_json({filename})", _do_download)

    def upsert_json(self, filename: str, payload: Dict[str, Any]) -> str:
        """Mở kết nối Drive mới ngay khi chuẩn bị ghi đè/tạo JSON, xong đóng ngay lập tức."""
        json_bytes = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")

        def _do_upsert(service: Any) -> str:
            existing_id = self._find_file_in_folder(service, filename)
            media = MediaIoBaseUpload(
                io.BytesIO(json_bytes),
                mimetype="application/json",
                resumable=False,
            )
            if existing_id:
                updated = (
                    service.files()
                    .update(
                        fileId=existing_id,
                        media_body=media,
                        fields="id, name",
                        supportsAllDrives=True,
                    )
                    .execute()
                )
                logger.info("[DRIVE] Đã cập nhật ghi đè '%s' (file_id=%s) và đóng kết nối.", filename, updated["id"])
                return updated["id"]

            metadata = {
                "name": filename,
                "parents": [self.folder_id],
                "mimeType": "application/json",
            }
            created = (
                service.files()
                .create(
                    body=metadata,
                    media_body=media,
                    fields="id, name",
                    supportsAllDrives=True,
                )
                .execute()
            )
            logger.info("[DRIVE] Đã tạo mới '%s' trên Drive (file_id=%s) và đóng kết nối.", filename, created["id"])
            return created["id"]

        return self._run_drive_op(f"upsert_json({filename})", _do_upsert)

    def upload_file(
        self,
        local_path: Path,
        mime_type: str,
        remote_filename: Optional[str] = None,
        target_folder_id: Optional[str] = None,
    ) -> str:
        """Mở kết nối Drive mới ngay khi chuẩn bị upload tệp, tải xong đóng kết nối ngay lập tức."""
        if not local_path.exists():
            raise FileNotFoundError(f"Không tìm thấy tệp để upload: {local_path}")

        parent_id = target_folder_id or self.folder_id
        target_name = remote_filename or local_path.name
        metadata = {
            "name": target_name,
            "parents": [parent_id],
        }
        is_large = local_path.stat().st_size > 5 * 1024 * 1024

        def _do_upload(service: Any) -> Dict[str, Any]:
            media = MediaFileUpload(
                str(local_path),
                mimetype=mime_type,
                chunksize=10 * 1024 * 1024 if is_large else -1,
                resumable=is_large,
            )
            request = service.files().create(
                body=metadata,
                media_body=media,
                fields="id, name, webViewLink",
                supportsAllDrives=True,
            )
            if is_large:
                resp = None
                while resp is None:
                    status, resp = request.next_chunk()
                    if status:
                        logger.info("[DRIVE UPLOAD] '%s': %d%%", target_name, int(status.progress() * 100))
                return resp
            return request.execute()

        response = self._run_drive_op(f"upload_file({target_name})", _do_upload)
        file_id = response["id"]
        logger.info(
            "[DRIVE UPLOAD OK] '%s' -> parent=%s | file_id=%s | link=%s (đã đóng kết nối Drive)",
            target_name,
            parent_id,
            file_id,
            response.get("webViewLink", "N/A"),
        )
        return file_id

    def upload_video(
        self,
        local_path: Path,
        remote_filename: Optional[str] = None,
        target_folder_id: Optional[str] = None,
    ) -> str:
        """Upload file video .mp4 lên Google Drive (vào thư mục con của video nếu được truyền vào)."""
        return self.upload_file(
            local_path=local_path,
            mime_type="video/mp4",
            remote_filename=remote_filename,
            target_folder_id=target_folder_id,
        )

    def upload_thumbnail(
        self,
        local_path: Path,
        remote_filename: Optional[str] = None,
        target_folder_id: Optional[str] = None,
    ) -> str:
        """Upload file thumbnail .png (1280x720) vào cùng thư mục video trên Google Drive."""
        return self.upload_file(
            local_path=local_path,
            mime_type="image/png",
            remote_filename=remote_filename,
            target_folder_id=target_folder_id,
        )
