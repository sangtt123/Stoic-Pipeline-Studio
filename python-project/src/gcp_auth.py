"""
src/gcp_auth.py — Trung tâm xác thực 100% bằng file JSON Service Account của Google Cloud Console.

Tự động tìm file JSON theo thứ tự ưu tiên:
  1. Biến môi trường `GOOGLE_APPLICATION_CREDENTIALS` (đường dẫn file .json HOẶC nội dung JSON/Base64 dán trực tiếp)
  2. Biến môi trường `GCP_SA_KEY` / `GCP_SERVICE_ACCOUNT_JSON` / `GOOGLE_CREDENTIALS` (JSON thô hoặc Base64)
  3. Tự động quét file mặc định ở thư mục gốc dự án:
     `service-account-key.json`, `credentials.json`, `gcp-key.json`

Tự động đọc `project_id` ngay bên trong file JSON nên không cần nhập tay `GCP_PROJECT_ID`,
đồng thời cấp 1 đối tượng `Credentials` dùng chung cho cả Vertex AI, Cloud TTS và Google Drive.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from google.oauth2 import service_account

import config

logger = logging.getLogger("gcp_auth")

UNIFIED_GCP_SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/drive",
]

DEFAULT_JSON_CANDIDATES = (
    "service-account-key.json",
    "credentials.json",
    "gcp-key.json",
)


@dataclass(frozen=True)
class GCPServiceAccountContext:
    credentials: service_account.Credentials
    project_id: str
    client_email: str
    source_label: str


_cached_context: Optional[GCPServiceAccountContext] = None


def _parse_sa_text_robust(raw_text: str, source_label: str) -> Dict[str, Any]:
    """Parse Service Account JSON an toàn (hỗ trợ JSON thô, Base64, BOM và chuẩn hóa newline của private_key)."""
    candidate = raw_text.lstrip("\ufeff").strip()
    if not candidate:
        raise ValueError(
            f"Nguồn '{source_label}' đang RỖNG (0 ký tự). "
            "Hãy kiểm tra trên GitHub: Settings -> Secrets and variables -> Actions -> Repository secrets "
            "đã tạo đúng tên secret 'GCP_SA_KEY' và dán toàn bộ nội dung file JSON Service Account chưa."
        )

    if (candidate.startswith("'") and candidate.endswith("'")) or (
        candidate.startswith('"') and candidate.endswith('"') and '\\"type\\"' in candidate
    ):
        candidate = candidate[1:-1].strip()

    if not candidate.startswith("{") and len(candidate) > 80:
        try:
            decoded = (
                base64.b64decode(re.sub(r"\s+", "", candidate))
                .decode("utf-8")
                .lstrip("\ufeff")
                .strip()
            )
            if decoded.startswith("{"):
                candidate = decoded
        except Exception:
            pass

    parsed: Optional[Dict[str, Any]] = None
    for attempt in (
        candidate,
        candidate.replace("\r\n", "\n").replace("\n", "\\n"),
        candidate.replace('\\"', '"'),
    ):
        try:
            obj = json.loads(attempt)
            if isinstance(obj, dict):
                parsed = obj
                break
        except json.JSONDecodeError:
            continue

    if parsed is None:
        raise ValueError(
            f"Không thể đọc nội dung Service Account JSON từ '{source_label}' "
            f"(độ dài={len(candidate)} ký tự, ký tự đầu='{candidate[:1]}', ký tự cuối='{candidate[-1:]}'). "
            "Hãy mở file .json bằng Notepad/VS Code, copy toàn bộ từ dấu '{' đầu đến dấu '}' cuối "
            "và dán lại vào Repository Secret 'GCP_SA_KEY'."
        )

    if parsed.get("type") != "service_account":
        raise ValueError(
            f"Nguồn '{source_label}' không phải Google Cloud Service Account JSON hợp lệ "
            f'(thiếu trường "type": "service_account").'
        )

    private_key = str(parsed.get("private_key", ""))
    if "\\n" in private_key:
        parsed["private_key"] = private_key.replace("\\n", "\n")

    return parsed


def _parse_sa_info_from_file(path: Path) -> Dict[str, Any]:
    return _parse_sa_text_robust(path.read_text(encoding="utf-8"), str(path))


def load_gcp_service_account(force_reload: bool = False) -> GCPServiceAccountContext:
    """Nạp thông tin xác thực từ file Service Account JSON và tự trích xuất project_id."""
    global _cached_context
    if _cached_context is not None and not force_reload:
        return _cached_context

    sa_info: Optional[Dict[str, Any]] = None
    source_label = ""

    # 1. GOOGLE_APPLICATION_CREDENTIALS (file path HOẶC chuỗi JSON dán trực tiếp)
    env_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if env_path:
        p = Path(env_path)
        if not p.is_absolute():
            p = (Path(config.BASE_DIR) / p).resolve()
        if p.exists() and p.is_file():
            sa_info = _parse_sa_info_from_file(p)
            source_label = str(p)
        elif env_path.startswith("{") or len(env_path) > 120:
            sa_info = _parse_sa_text_robust(env_path, "env:GOOGLE_APPLICATION_CREDENTIALS")
            source_label = "env:GOOGLE_APPLICATION_CREDENTIALS"
        else:
            raise FileNotFoundError(
                f"Không tìm thấy file Service Account JSON tại GOOGLE_APPLICATION_CREDENTIALS='{p}'."
            )

    # 2. Nội dung JSON thô / Base64 từ biến môi trường (GitHub Actions Secret / Cloud Run)
    if sa_info is None:
        for env_name in ("GCP_SA_KEY", "GCP_SERVICE_ACCOUNT_JSON", "GOOGLE_CREDENTIALS"):
            raw_json = os.getenv(env_name, "").strip()
            if raw_json:
                sa_info = _parse_sa_text_robust(raw_json, f"env:{env_name}")
                source_label = f"env:{env_name}"
                break

    # 3. Tự động tìm file JSON chuẩn đặt tại thư mục gốc dự án
    if sa_info is None:
        base = Path(config.BASE_DIR)
        for filename in DEFAULT_JSON_CANDIDATES:
            candidate = base / filename
            if candidate.exists() and candidate.is_file():
                sa_info = _parse_sa_info_from_file(candidate)
                source_label = str(candidate)
                break

    if sa_info is None:
        raise FileNotFoundError(
            "Không tìm thấy file JSON Service Account của Google Cloud Console. "
            "Hãy đặt file khóa tại './service-account-key.json' hoặc khai báo biến "
            "`GOOGLE_APPLICATION_CREDENTIALS` / `GCP_SA_KEY`."
        )

    sa_project_id = str(sa_info.get("project_id", "")).strip()
    env_project_id = str(config.GCP_PROJECT_ID or "").strip()
    if sa_project_id and env_project_id and env_project_id != sa_project_id:
        logger.warning(
            "[GCP AUTH] GCP_PROJECT_ID từ môi trường khác với project_id bên trong Service Account JSON -> ưu tiên dùng project_id từ JSON ('%s').",
            sa_project_id,
        )
    project_id = sa_project_id or env_project_id
    if not project_id:
        raise ValueError(
            f"File Service Account JSON ({source_label}) không chứa trường 'project_id' "
            "và chưa cấu hình GCP_PROJECT_ID."
        )

    client_email = str(sa_info.get("client_email", "")).strip()
    credentials = service_account.Credentials.from_service_account_info(
        sa_info,
        scopes=UNIFIED_GCP_SCOPES,
    )

    _cached_context = GCPServiceAccountContext(
        credentials=credentials,
        project_id=project_id,
        client_email=client_email,
        source_label=source_label,
    )
    logger.info(
        "[GCP AUTH OK] Xác thực bằng JSON Service Account | Project='%s' | Email='%s' | Nguồn='%s'",
        project_id,
        client_email,
        source_label,
    )
    return _cached_context
