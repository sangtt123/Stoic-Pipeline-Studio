"""
src/sketch_animator.py — Động cơ hoạt hình "Cây bút vẽ nét hiện hình" (Pen-Sketch Draw-On Engine).

Hoạt động 100% không giao diện trên CPU GitHub Actions Runner (không tốn phí Veo):
1. Phân tích đường nét (contours) thực tế của ảnh 2D Imagen bằng OpenCV (`Canny` + `findContours`).
2. Sắp xếp các nét vẽ theo thứ tự tự nhiên từ trọng tâm bố cục lan ra ngoài.
3. Giai đoạn 1 (0% -> 65% thời lượng câu thoại): Vẽ dần từng đường nét mực trên nền giấy vẽ
   kèm hình ảnh cây bút máy/ngòi vàng chuyển động bám sát đúng đầu nét `(x, y)` theo thời gian thực.
4. Giai đoạn 2 (65% -> 85%): Cây bút lướt rời khung hình, lớp đổ bóng màu (ink wash & chiaroscuro)
   hiện dần lên hoàn chỉnh khớp với nội dung lời thoại.
5. Giai đoạn 3 (85% -> 100%): Giữ khung hình hoàn chỉnh có lớp đồ họa 2D Pillow (viền, trích dẫn,
   thanh tiến trình) và xuất thẳng luồng frame thô vào FFmpeg stdin pipe (`-preset ultrafast -r 24`).
"""

from __future__ import annotations

import logging
import math
import os
import subprocess
from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw

import config

logger = logging.getLogger("sketch_animator")


def _fit_cover(img_bgr: np.ndarray, width: int, height: int) -> np.ndarray:
    """Cắt và co giãn ảnh lấp đầy chính xác khung hình mục tiêu (cover)."""
    ih, iw = img_bgr.shape[:2]
    scale = max(width / iw, height / ih)
    nw, nh = int(math.ceil(iw * scale)), int(math.ceil(ih * scale))
    resized = cv2.resize(img_bgr, (nw, nh), interpolation=cv2.INTER_AREA)
    x0 = max(0, (nw - width) // 2)
    y0 = max(0, (nh - height) // 2)
    return resized[y0 : y0 + height, x0 : x0 + width]


def _create_paper_canvas(width: int, height: int, theme: str) -> np.ndarray:
    """Tạo nền giấy vẽ có vân hạt tinh tế (dark_slate hoặc classic_parchment)."""
    rng = np.random.default_rng(42)
    noise = rng.integers(-6, 7, size=(height, width, 1), dtype=np.int16)

    if theme == "classic_parchment":
        # Giấy da cừu cổ điển (BGR)
        base = np.full((height, width, 3), (218, 232, 240), dtype=np.int16)
    else:
        # Nền than chì sâu Khắc kỷ (BGR)
        base = np.full((height, width, 3), (24, 18, 13), dtype=np.int16)

    paper = np.clip(base + noise, 0, 255).astype(np.uint8)
    return paper


def _create_fountain_pen_sprite(scale: float = 1.0) -> Tuple[np.ndarray, Tuple[int, int]]:
    """
    Tạo sprite cây bút máy cổ điển trong suốt (RGBA) bằng Pillow.
    Trả về (rgba_array, (tip_x, tip_y)) — trong đó đầu ngòi bút nằm chính xác ở (tip_x, tip_y).
    Nếu người dùng đặt file tùy chỉnh tại `assets/pen.png`, ưu tiên dùng file đó.
    """
    custom_pen = Path(config.BASE_DIR) / "assets" / "pen.png"
    if custom_pen.exists():
        pil_pen = Image.open(custom_pen).convert("RGBA")
        arr = np.asarray(pil_pen)
        # Mặc định giả định đầu ngòi ở góc dưới-trái
        return arr, (6, arr.shape[0] - 6)

    w = int(260 * scale)
    h = int(260 * scale)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")

    # Đầu ngòi bút nằm tại góc dưới trái (tip_x=14, tip_y=h-14), thân bút chéo lên góc trên phải
    tip = (int(14 * scale), int(h - 14 * scale))

    # Bóng đổ mềm dưới thân bút tạo chiều sâu 2D
    draw.polygon(
        [
            (tip[0] + int(8 * scale), tip[1] + int(6 * scale)),
            (int(64 * scale), int(h - 38 * scale)),
            (int(238 * scale), int(40 * scale)),
            (int(218 * scale), int(22 * scale)),
            (int(44 * scale), int(h - 56 * scale)),
        ],
        fill=(0, 0, 0, 75),
    )

    # Thân bút sơn mài đen obsidian
    draw.polygon(
        [
            (int(56 * scale), int(h - 46 * scale)),
            (int(232 * scale), int(30 * scale)),
            (int(214 * scale), int(12 * scale)),
            (int(38 * scale), int(h - 64 * scale)),
        ],
        fill=(22, 28, 38, 255),
        outline=(197, 160, 89, 210),
    )

    # Vòng khoen vàng đồng trang trí giữa thân bút
    draw.polygon(
        [
            (int(62 * scale), int(h - 52 * scale)),
            (int(76 * scale), int(h - 66 * scale)),
            (int(58 * scale), int(h - 84 * scale)),
            (int(44 * scale), int(h - 70 * scale)),
        ],
        fill=(197, 160, 89, 255),
    )

    # Ngòi bút vàng cổ điển thuôn nhọn về đúng điểm tip
    draw.polygon(
        [
            tip,
            (int(58 * scale), int(h - 44 * scale)),
            (int(40 * scale), int(h - 62 * scale)),
        ],
        fill=(216, 178, 98, 255),
        outline=(95, 72, 32, 255),
    )

    # Khe xẻ nhỏ trên ngòi bút máy
    draw.line(
        [tip, (int(42 * scale), int(h - 46 * scale))],
        fill=(30, 24, 18, 220),
        width=max(1, int(2 * scale)),
    )

    return np.asarray(img), tip


def _alpha_blit(
    dst_bgr: np.ndarray,
    sprite_rgba: np.ndarray,
    x: int,
    y: int,
) -> None:
    """Dán sprite RGBA (bút hoặc lớp phủ) lên khung hình BGR tại tọa độ (x, y) cực nhanh bằng NumPy."""
    dh, dw = dst_bgr.shape[:2]
    sh, sw = sprite_rgba.shape[:2]

    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(dw, x + sw)
    y2 = min(dh, y + sh)
    if x1 >= x2 or y1 >= y2:
        return

    sx1 = x1 - x
    sy1 = y1 - y
    sx2 = sx1 + (x2 - x1)
    sy2 = sy1 + (y2 - y1)

    roi = dst_bgr[y1:y2, x1:x2]
    patch = sprite_rgba[sy1:sy2, sx1:sx2]
    alpha = (patch[:, :, 3:4].astype(np.float32)) / 255.0
    patch_bgr = patch[:, :, [2, 1, 0]].astype(np.float32)

    blended = roi.astype(np.float32) * (1.0 - alpha) + patch_bgr * alpha
    dst_bgr[y1:y2, x1:x2] = blended.astype(np.uint8)


def _extract_ordered_stroke_paths(img_bgr: np.ndarray) -> List[np.ndarray]:
    """
    Trích xuất các đường nét mực (contours) từ ảnh 2D và sắp xếp thành lộ trình vẽ tự nhiên:
    ưu tiên những đường nét lớn ở vùng trung tâm chủ thể trước, sau đó đến chi tiết xung quanh.
    """
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(blurred, threshold1=45, threshold2=135)

    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)

    # Lọc bỏ điểm nhiễu quá nhỏ (< 12px) và sắp xếp ưu tiên nét dài & gần vùng trọng tâm
    h, w = gray.shape[:2]
    cx, cy = w * 0.5, h * 0.45

    scored = []
    for cnt in contours:
        length = cv2.arcLength(cnt, closed=False)
        if length < 14.0:
            continue
        pts = cnt.reshape(-1, 2)
        mean_x = float(np.mean(pts[:, 0]))
        mean_y = float(np.mean(pts[:, 1]))
        dist_center = math.hypot(mean_x - cx, mean_y - cy) / max(w, h)
        # Trọng số: vẽ các nét chính ở trung tâm trước, rồi quét từ trên-trái xuống dưới-phải
        priority = (dist_center * 0.55) + (mean_y / h) * 0.25 + (mean_x / w) * 0.20 - min(length / 1200.0, 0.35)
        scored.append((priority, pts))

    scored.sort(key=lambda item: item[0])

    # Giới hạn tối đa 320 nét tiêu biểu nhất để vừa sắc nét vừa vẽ nhanh trên CPU
    return [pts for _, pts in scored[:320]]


def render_pen_sketch_scene(
    image_path: Path,
    overlay_path: Path,
    audio_path: Path,
    output_clip_path: Path,
    duration_sec: float,
    resolution: Tuple[int, int],
) -> Path:
    """
    Render 1 phân cảnh hoàn chỉnh dạng "Cây bút chuyển động vẽ nét -> đổ bóng hiện hình".
    Pipe thẳng luồng khung hình vào FFmpeg (không ghi hàng trăm ảnh PNG tạm ra ổ đĩa).
    """
    width, height = resolution
    fps = config.VIDEO_FPS
    padded_duration = round(duration_sec + 0.35, 3)
    total_frames = max(1, int(math.ceil(padded_duration * fps)))

    draw_end_frame = max(1, int(total_frames * config.PEN_SKETCH_DRAW_RATIO))
    wash_end_frame = max(draw_end_frame + 1, int(total_frames * (config.PEN_SKETCH_DRAW_RATIO + config.PEN_SKETCH_WASH_RATIO)))

    raw_img = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if raw_img is None:
        raise FileNotFoundError(f"Không thể đọc ảnh nguồn: {image_path}")
    target_bgr = _fit_cover(raw_img, width, height)

    # Tải lớp phủ 2D Pillow (khung viền, thanh tiến trình, chữ trích dẫn)
    overlay_pil = Image.open(overlay_path).convert("RGBA").resize((width, height), Image.Resampling.LANCZOS)
    overlay_rgba = np.asarray(overlay_pil)

    theme = config.PEN_SKETCH_PAPER_THEME
    paper_bgr = _create_paper_canvas(width, height, theme)
    ink_color = (34, 30, 26) if theme == "classic_parchment" else (128, 178, 212)  # Đen mực hoặc vàng đồng sáng (BGR)

    # Trích xuất danh sách điểm nét vẽ liên tục
    strokes = _extract_ordered_stroke_paths(target_bgr)
    total_points = sum(len(s) for s in strokes)

    pen_scale = 1.0 if width >= 1280 else 0.78
    pen_rgba, (tip_x, tip_y) = _create_fountain_pen_sprite(scale=pen_scale)

    # Chuẩn bị bảng vẽ tích lũy (incremental sketch canvas)
    sketch_canvas = paper_bgr.copy()
    last_tip = (width // 2, height // 2)

    # Mở tiến trình FFmpeg nhận luồng video raw BGR24 qua stdin và ghép trực tiếp audio TTS
    output_clip_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg_cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "rawvideo",
        "-vcodec",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "-s",
        f"{width}x{height}",
        "-r",
        str(fps),
        "-i",
        "-",
        "-i",
        str(audio_path),
        "-filter_complex",
        f"[1:a]apad=pad_dur=0.35,atrim=0:{padded_duration:.3f},asetpts=PTS-STARTPTS[aout]",
        "-map",
        "0:v",
        "-map",
        "[aout]",
        "-c:v",
        "libx264",
        "-preset",
        config.FFMPEG_PRESET,
        "-tune",
        config.FFMPEG_TUNE,
        "-crf",
        config.FFMPEG_CRF,
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "44100",
        "-ac",
        "2",
        "-shortest",
        str(output_clip_path),
    ]

    proc = subprocess.Popen(
        ffmpeg_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    drawn_points = 0
    stroke_idx = 0
    point_idx = 0

    try:
        assert proc.stdin is not None
        for frame_idx in range(total_frames):
            if frame_idx < draw_end_frame and total_points > 0:
                # Giai đoạn 1: Bút vẽ dần các đường nét thực tế của bức tranh
                target_drawn = int(((frame_idx + 1) / draw_end_frame) * total_points)

                while drawn_points < target_drawn and stroke_idx < len(strokes):
                    curr_stroke = strokes[stroke_idx]
                    remaining_in_stroke = len(curr_stroke) - point_idx
                    budget = target_drawn - drawn_points
                    step_count = min(remaining_in_stroke, budget)

                    end_p = point_idx + step_count
                    segment = curr_stroke[max(0, point_idx - 1) : end_p]
                    if len(segment) >= 2:
                        cv2.polylines(
                            sketch_canvas,
                            [segment.reshape(-1, 1, 2)],
                            isClosed=False,
                            color=ink_color,
                            thickness=2,
                            lineType=cv2.LINE_AA,
                        )
                    last_tip = (int(curr_stroke[end_p - 1, 0]), int(curr_stroke[end_p - 1, 1]))
                    drawn_points += step_count
                    point_idx = end_p

                    if point_idx >= len(curr_stroke):
                        stroke_idx += 1
                        point_idx = 0

                frame = sketch_canvas.copy()

                # Rung nhẹ tự nhiên ở đầu ngòi bút khi đang đưa nét
                jitter_x = int(math.sin(frame_idx * 1.9) * 3.0)
                jitter_y = int(math.cos(frame_idx * 2.3) * 2.0)
                pen_x = last_tip[0] - tip_x + jitter_x
                pen_y = last_tip[1] - tip_y + jitter_y
                _alpha_blit(frame, pen_rgba, pen_x, pen_y)

            elif frame_idx < wash_end_frame:
                # Giai đoạn 2: Đổ bóng & màu hoàn chỉnh dần lên trên bản phác họa + bút lướt ra ngoài
                alpha = (frame_idx - draw_end_frame) / max(1, wash_end_frame - draw_end_frame)
                alpha = max(0.0, min(1.0, alpha))
                frame = cv2.addWeighted(sketch_canvas, 1.0 - alpha, target_bgr, alpha, 0.0)

                exit_x = int(last_tip[0] + (width - last_tip[0] + 120) * (alpha ** 1.4)) - tip_x
                exit_y = int(last_tip[1] - 90 * alpha) - tip_y
                _alpha_blit(frame, pen_rgba, exit_x, exit_y)
            else:
                # Giai đoạn 3: Khung hình hoàn chỉnh sắc nét
                frame = target_bgr.copy()

            # Ghép lớp phủ 2D Pillow (viền, chữ trích dẫn, thanh tiến trình) lên trên cùng
            _alpha_blit(frame, overlay_rgba, 0, 0)
            proc.stdin.write(frame.tobytes())

        proc.stdin.close()
        stderr_out = proc.stderr.read().decode("utf-8", errors="ignore") if proc.stderr else ""
        ret = proc.wait()
        if ret != 0:
            tail = "\n".join(stderr_out.splitlines()[-15:])
            raise RuntimeError(f"FFmpeg pen_sketch thất bại:\n{tail}")

    finally:
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()

    logger.info(
        "[PEN SKETCH OK] Clip='%s' | Strokes=%d | Duration=%.2fs",
        output_clip_path.name,
        len(strokes),
        padded_duration,
    )
    return output_clip_path
