"""
src/video_reviewer.py — Kiểm duyệt Video thành phẩm tự động (Kỹ thuật + Gemini Vision Contact Sheet).

Bước 1 (Kỹ thuật bằng code):
  - Xác minh file có đủ video + audio stream hợp lệ.
  - Xác minh tổng thời lượng nằm trong biên độ hợp lệ (~5 phút).
  - Quét FFmpeg `silencedetect` đảm bảo không có khoảng lặng chết bất thường (> 3.2s).
Bước 2 (Gemini Vision Contact Sheet):
  - Gửi 1 ảnh lưới (1 frame / 15 giây) kèm kịch bản để đánh giá đồng bộ hình - chữ,
    phát hiện chữ bị tràn/vỡ font, và đảm bảo các frame không bị lặp giống hệt nhau.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import config
from src.vertex_client import VertexAIClient
from src.video_renderer import generate_contact_sheet

logger = logging.getLogger("video_reviewer")


@dataclass
class VideoReviewResult:
    passed: bool
    duration_sec: float
    technical_issues: List[str] = field(default_factory=list)
    vision_issues: List[str] = field(default_factory=list)
    bad_scene_indices: List[int] = field(default_factory=list)
    summary: str = ""


def _probe_video_streams(video_path: Path) -> Dict[str, Any]:
    """Kiểm tra metadata video & audio bằng ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(video_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def _detect_abnormal_silence(video_path: Path, max_gap_sec: float) -> List[float]:
    """Dùng FFmpeg silencedetect phát hiện các khoảng lặng chết bất thường."""
    cmd = [
        "ffmpeg",
        "-i",
        str(video_path),
        "-af",
        f"silencedetect=noise=-45dB:d={max_gap_sec}",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    durations = [
        float(m.group(1))
        for m in re.finditer(r"silence_duration:\s*([0-9.]+)", proc.stderr)
    ]
    return durations


def run_technical_check(video_path: Path) -> tuple[bool, float, List[str]]:
    """Kiểm tra kỹ thuật tự động: thời lượng, stream audio/video, khoảng lặng bất thường."""
    issues: List[str] = []
    if not video_path.exists() or video_path.stat().st_size < 500_000:
        return False, 0.0, ["File video không tồn tại hoặc dung lượng quá nhỏ (< 500KB)."]

    meta = _probe_video_streams(video_path)
    streams = meta.get("streams", [])
    has_video = any(s.get("codec_type") == "video" for s in streams)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)

    if not has_video:
        issues.append("Thiếu video stream trong file MP4.")
    if not has_audio:
        issues.append("Thiếu audio stream trong file MP4.")

    duration = float(meta.get("format", {}).get("duration", 0.0))
    if duration < config.MIN_VIDEO_DURATION_SEC:
        issues.append(
            f"Video quá ngắn ({duration:.1f}s < {config.MIN_VIDEO_DURATION_SEC:.0f}s)."
        )
    elif duration > config.MAX_VIDEO_DURATION_SEC:
        issues.append(
            f"Video quá dài ({duration:.1f}s > {config.MAX_VIDEO_DURATION_SEC:.0f}s)."
        )

    silence_gaps = _detect_abnormal_silence(video_path, config.MAX_SILENCE_GAP_SEC)
    if silence_gaps:
        issues.append(
            f"Phát hiện {len(silence_gaps)} khoảng lặng bất thường (> {config.MAX_SILENCE_GAP_SEC}s): "
            f"{[round(g, 2) for g in silence_gaps]}"
        )

    return len(issues) == 0, duration, issues


def review_final_video(
    video_path: Path,
    script: Dict[str, Any],
    vertex: VertexAIClient,
    workdir: Path,
) -> VideoReviewResult:
    """Chạy toàn bộ quy trình kiểm duyệt Kỹ thuật + Gemini Vision Contact Sheet."""
    tech_ok, duration, tech_issues = run_technical_check(video_path)

    # Tạo 1 tấm Contact Sheet duy nhất (1 frame mỗi 15 giây)
    contact_sheet_path = workdir / "review_contact_sheet.jpg"
    generate_contact_sheet(video_path, contact_sheet_path)

    scenes_digest = [
        {
            "scene_id": s["scene_id"],
            "quote_overlay": s.get("quote_overlay", ""),
            "narration_preview": s.get("narration", "")[:110],
        }
        for s in script.get("scenes", [])
    ]

    interval_sec = getattr(config, "CONTACT_SHEET_INTERVAL_SEC", 10)
    if getattr(config, "VIDEO_VISUAL_MODE", "") == "stickman_whiteboard":
        vision_prompt = (
            f"Bạn đang xem ảnh lưới Contact Sheet (trích xuất 1 frame mỗi {interval_sec} giây theo thứ tự từ trái sang phải, "
            "từ trên xuống dưới) của một video Studio Vector Whiteboard 2D.\n\n"
            f"- Tiêu đề video: {script.get('title')}\n"
            f"- Thời lượng thực tế: {duration:.1f} giây\n"
            f"- Danh sách phân cảnh: {json.dumps(scenes_digest, ensure_ascii=False)}\n\n"
            "MÔ TẢ ĐỊNH DẠNG CHUẨN CỦA VIDEO NÀY (ĐÂY LÀ THIẾT KẾ CHỦ ĐÍCH, KHÔNG PHẢI LỖI):\n"
            "- Mỗi khung hình có nền studio đồng nhất, 1 thẻ sân khấu bo góc chứa nhân vật linh vật 2D (Cú Mèo / Mèo / Cáo / Shiba / Người que) + biểu tượng ẩn dụ, "
            "thẻ đếm nhịp (1/4, 2/4...) ở góc trên phải, và hộp Caption chữ Việt sắc nét có thanh nhấn màu nổi bật ở bên dưới.\n"
            "- Vì các beat dùng chung bố cục khung thẻ cố định để mắt người xem tập trung vào hình và caption bên trong, "
            "đừng đánh lỗi 'lặp khung hình' chỉ vì đường viền thẻ giống nhau — hãy kiểm tra phần hình vẽ và chữ bên trong thẻ.\n\n"
            "HÃY KIỂM TRA 4 TIÊU CHÍ CHẤT LƯỢNG:\n"
            "1. Toàn bộ các ô đều hiển thị hình minh họa nhân vật 2D / ẩn dụ rõ nét, KHÔNG bị màn hình đen hoặc khung trắng trống rỗng?\n"
            "2. Nhân vật linh vật 2D và biểu tượng không bị lỗi hiển thị, vỡ hình hoặc cắt mất đầu/thân bất thường?\n"
            "3. Chữ trong hộp Caption phía dưới và các nhãn minh họa rõ ràng, đọc được, không bị ký tự rác đè chéo lên nhau?\n"
            "4. Các khung hình nối tiếp có sự biến đổi nội dung/bố cục hợp lý theo mạch kể chuyện không?\n\n"
            "Trả về JSON đúng cấu trúc:\n"
            "{\n"
            '  "passed": true/false,\n'
            '  "vision_issues": ["Mô tả ngắn gọn từng lỗi nghiêm trọng nếu có"],\n'
            '  "bad_scene_indices": [],\n'
            '  "summary": "Tóm tắt đánh giá chất lượng hình ảnh trong 1 câu"\n'
            "}\n"
            "Chỉ trả `passed: false` khi thực sự có khung hình bị đen/trống, vỡ hình nghiêm trọng hoặc chữ chồng chéo không đọc được."
        )
    else:
        vision_prompt = (
            f"Bạn đang xem ảnh lưới Contact Sheet (trích xuất 1 frame mỗi {interval_sec} giây theo thứ tự từ trái sang phải, "
            "từ trên xuống dưới) của một video Triết lý Khắc kỷ 2D.\n\n"
            f"- Tiêu đề video: {script.get('title')}\n"
            f"- Phong cách yêu cầu: {config.VISUAL_STYLE_PROMPT}\n"
            f"- Thời lượng thực tế: {duration:.1f} giây\n"
            f"- Danh sách phân cảnh: {json.dumps(scenes_digest, ensure_ascii=False)}\n\n"
            "HÃY KIỂM TRA KHẮT KHE 5 TIÊU CHÍ HÌNH VẼ:\n"
            "1. Hình ảnh có đồng bộ phong cách 2D tối giản và khớp sát nội dung từng phân cảnh không?\n"
            "2. Nhân vật có bị méo mặt, biến dạng tay/ngón tay, thừa chi hoặc bố cục rối rắm khó hiểu không?\n"
            "3. Chữ trích dẫn (quote_overlay) có bị tràn khung, cắt chữ, chồng đè lên hình hoặc lỗi font không?\n"
            "4. Có hiện tượng nhiều ô liên tiếp bị lặp hình giống hệt nhau hoặc bị khung trống/màn hình đen không?\n"
            "5. Có văn bản rác/ký tự tiếng Anh méo mó do AI tự vẽ đè vào trong tranh không?\n\n"
            "Trả về JSON đúng cấu trúc:\n"
            "{\n"
            '  "passed": true/false,\n'
            '  "vision_issues": ["Mô tả ngắn gọn từng lỗi nếu có"],\n'
            '  "bad_scene_indices": [1, 5],\n'
            '  "summary": "Tóm tắt đánh giá chất lượng hình ảnh trong 1 câu"\n'
            "}\n"
            "Lưu ý: `bad_scene_indices` là danh sách `scene_id` (đánh số từ 1) cần tự động vẽ lại ảnh/overlay. "
            "Chỉ trả `passed: true` và `bad_scene_indices: []` khi toàn bộ hình vẽ sạch, rõ nét, không lỗi."
        )

    vision_data = vertex.review_contact_sheet(
        contact_sheet_path=contact_sheet_path,
        prompt=vision_prompt,
        system_instruction="Bạn là Giám sát Chất lượng Video (QA Lead) công tâm và chính xác.",
        task_name="final_video_vision_qa",
    )

    vision_ok = bool(vision_data.get("passed", False))
    vision_issues = [str(x) for x in vision_data.get("vision_issues", [])]
    bad_scenes = [
        int(i)
        for i in vision_data.get("bad_scene_indices", [])
        if isinstance(i, (int, float)) and 1 <= int(i) <= len(script.get("scenes", []))
    ]

    overall_passed = tech_ok and vision_ok
    result = VideoReviewResult(
        passed=overall_passed,
        duration_sec=duration,
        technical_issues=tech_issues,
        vision_issues=vision_issues,
        bad_scene_indices=bad_scenes,
        summary=str(vision_data.get("summary", "")),
    )

    logger.info(
        "[VIDEO QA] Passed=%s | Duration=%.1fs | TechIssues=%d | VisionIssues=%d | BadScenes=%s",
        result.passed,
        result.duration_sec,
        len(result.technical_issues),
        len(result.vision_issues),
        result.bad_scene_indices,
    )
    return result
