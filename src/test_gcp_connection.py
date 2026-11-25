"""
src/test_gcp_connection.py — Script kiểm thử nhanh (10 giây) toàn bộ kết nối Google Cloud Console.

Chạy trước khi chạy pipeline đầy đủ để xác nhận:
  1. Công cụ hệ thống: ffmpeg, ffprobe, OpenCV (cv2), Pillow.
  2. Vertex AI LLM (location="global") + Auto-Fallback chain.
  3. Vertex AI Text Embedding (text-embedding-004).
  4. Google Cloud Text-to-Speech (Chirp 3 HD / Studio / Neural2) + đo duration.
  5. Quyền đọc/ghi thư mục Google Drive (GDRIVE_FOLDER_ID).
  6. (Tùy chọn --with-imagen) Kiểm thử tạo 1 ảnh 2D mẫu bằng Vertex AI Imagen.

Cách chạy:
  python -m src.test_gcp_connection
  python -m src.test_gcp_connection --with-imagen
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

import config
from src.drive_manager import DriveManager
from src.gcp_auth import load_gcp_service_account
from src.tts_generator import TTSGenerator
from src.vertex_client import VertexAIClient

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("test_gcp_connection")


def check_system_tools() -> None:
    """Kiểm tra FFmpeg, FFprobe và OpenCV trên máy chạy."""
    for bin_name in ("ffmpeg", "ffprobe"):
        if not shutil.which(bin_name):
            raise RuntimeError(f"Không tìm thấy '{bin_name}' trong PATH. Hãy cài FFmpeg trước.")
    subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    import cv2  # noqa: F401
    import PIL  # noqa: F401
    logger.info("[1/5 OK] FFmpeg, FFprobe, OpenCV và Pillow đã sẵn sàng.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Kiểm thử nhanh kết nối Google Cloud Console.")
    parser.add_argument(
        "--with-imagen",
        action="store_true",
        help="Chạy thêm bài test tạo 1 ảnh 2D mẫu bằng Vertex AI Imagen (tốn ~$0.02).",
    )
    args = parser.parse_args()

    logger.info("=== BẮT ĐẦU KIỂM THỬ GOOGLE CLOUD CONSOLE (XÁC THỰC BẰNG FILE JSON) ===")
    auth = load_gcp_service_account()
    logger.info(
        "[0/5 AUTH OK] File JSON hợp lệ | Project='%s' | Email='%s' | Nguồn='%s'",
        auth.project_id,
        auth.client_email,
        auth.source_label,
    )
    check_system_tools()

    vertex = VertexAIClient()

    # 2. Test Vertex AI LLM (global + auto-fallback)
    llm_res = vertex.generate_json(
        prompt='Trả về JSON: {"status": "ok", "stoic_quote": "1 câu Khắc kỷ ngắn dưới 10 từ"}',
        system_instruction="Trả về duy nhất JSON hợp lệ.",
        temperature=0.2,
        task_name="smoke_test_llm",
    )
    logger.info("[2/5 OK] Vertex AI LLM phản hồi: %s", llm_res)

    # 3. Test Vertex AI Embedding
    vec = vertex.embed_text("Stoic resilience and self-mastery", task_name="smoke_test_embedding")
    logger.info("[3/5 OK] Vertex AI Embedding hoạt động (số chiều vector = %d).", len(vec))

    # 4. Test Google Cloud Text-to-Speech
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        tts = TTSGenerator(language=config.LANGUAGE, vertex=vertex)
        sample_text = (
            "Người làm chủ được tâm trí mình sẽ giữ vững sự tĩnh lặng giữa bão giông."
            if config.LANGUAGE.startswith("vi")
            else "He who masters his own mind remains calm amidst the storm."
        )
        audio_path, dur = tts.synthesize_scene(sample_text, tmp / "test_voice")
        logger.info("[4/5 OK] Giọng đọc TTS hoạt động (%s · %.2fs).", audio_path.name, dur)

        if args.with_imagen:
            img_path = vertex.generate_image(
                prompt=f"Stoic marble bust of Marcus Aurelius. {config.VISUAL_STYLE_PROMPT}",
                output_path=tmp / "test_art.png",
                aspect_ratio=config.ASPECT_RATIO,
                task_name="smoke_test_imagen",
            )
            logger.info("[BONUS OK] Vertex AI Imagen 2D tạo ảnh thành công (%d bytes).", img_path.stat().st_size)

    # 5. Test Google Drive folder access
    drive = DriveManager()
    existing = drive.download_json(config.HISTORY_FILENAME)
    if existing is None:
        logger.info("[5/5 OK] Kết nối Google Drive thành công (chưa có history_log.json — sẽ tạo mới khi chạy Stage 1).")
    else:
        logger.info(
            "[5/5 OK] Kết nối Google Drive thành công (đã tìm thấy history_log.json với %d bản ghi).",
            len(existing.get("videos", [])),
        )

    logger.info("=== HOÀN TẤT: TOÀN BỘ API GOOGLE CLOUD CONSOLE ĐÃ SẴN SÀNG! ===")


if __name__ == "__main__":
    main()
