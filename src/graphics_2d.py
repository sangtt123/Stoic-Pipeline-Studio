"""
src/graphics_2d.py — Vẽ lớp đồ họa 2D trong suốt bằng Pillow (PIL).

Các lớp đồ họa bao gồm:
- Khung viền tối giản kiểu ấn phẩm biên tập (muted dark gold #C5A059) + tối góc nhẹ (vignette).
- Thanh tiến trình đọc (reading progress bar) chạy mượt theo phân cảnh.
- Chữ trích dẫn (kinetic-style quote typography) hỗ trợ đầy đủ tiếng Việt & tiếng Anh UTF-8.
- Hiệu ứng hạt bụi / nhiễu phim (film grain speckles) tinh tế.
"""

from __future__ import annotations

import logging
import os
import random
import textwrap
from pathlib import Path
from typing import Tuple

from PIL import Image, ImageDraw, ImageFont

import config

logger = logging.getLogger("graphics_2d")

# Màu sắc chủ đạo khớp với phong cách Khắc kỷ 2D
GOLD_ACCENT = (197, 160, 89, 215)
GOLD_SOFT = (197, 160, 89, 95)
TEXT_PRIMARY = (242, 238, 228, 245)
TEXT_SHADOW = (10, 12, 16, 215)
TRACK_BG = (255, 255, 255, 42)
SCRIM_DARK = (11, 14, 20, 168)

CANDIDATE_FONT_PATHS = [
    os.path.join(config.ASSETS_FONTS_DIR, "NotoSerif-Bold.ttf"),
    os.path.join(config.ASSETS_FONTS_DIR, "DejaVuSerif-Bold.ttf"),
    "/usr/share/fonts/truetype/noto/NotoSerif-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _load_unicode_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Tìm font Unicode hỗ trợ tiếng Việt có dấu trên Ubuntu GitHub Actions Runner."""
    for path in CANDIDATE_FONT_PATHS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
    logger.warning("[GRAPHICS] Không tìm thấy font TrueType Unicode; dùng font mặc định.")
    return ImageFont.load_default()


def _draw_subtle_vignette_and_grain(
    canvas: Image.Image, width: int, height: int, seed: int
) -> None:
    """Vẽ dải tối mềm trên/dưới để nổi chữ và rải hạt bụi nhiễu phim nhẹ."""
    draw = ImageDraw.Draw(canvas, "RGBA")

    # Dải scrim tối mềm ở phần dưới để quote luôn đạt tương phản cao (> 4.5:1)
    band_height = int(height * 0.28)
    for i in range(band_height):
        ratio = i / max(band_height, 1)
        alpha = int(175 * (ratio ** 1.6))
        y = height - band_height + i
        draw.line([(0, y), (width, y)], fill=(10, 13, 19, alpha))

    # Hạt bụi / film grain tinh tế
    rng = random.Random(seed)
    speckle_count = int((width * height) / 14000)
    for _ in range(speckle_count):
        x = rng.randint(0, width - 1)
        y = rng.randint(0, height - 1)
        alpha = rng.randint(12, 38)
        radius = 1 if rng.random() > 0.15 else 2
        draw.ellipse(
            [x, y, x + radius, y + radius],
            fill=(235, 224, 200, alpha),
        )


def render_scene_overlay(
    output_path: Path,
    resolution: Tuple[int, int],
    scene_index: int,
    total_scenes: int,
    quote_overlay: str = "",
) -> Path:
    """Tạo file PNG trong suốt (RGBA) chứa khung 2D, thanh tiến trình và câu trích dẫn."""
    width, height = resolution
    is_vertical = height > width

    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas, "RGBA")

    # Trong chế độ stickman_whiteboard, mỗi ảnh beat SVG đã có sẵn Stage Card trắng bo góc,
    # badge đếm nhịp 1/4 và hộp Caption nền trắng sắc nét ở đáy -> KHÔNG phủ scrim tối, viền vàng
    # hay hộp quote đè lên làm sai lệch giao diện Studio; chỉ vẽ thanh tiến trình siêu mảnh ở mép đáy.
    if getattr(config, "VIDEO_VISUAL_MODE", "") == "stickman_whiteboard":
        accent_rgb = _hex_to_rgb(
            getattr(config, "WHITEBOARD_ACCENT_COLOR", "#2563EB"), (37, 99, 235)
        )
        bar_margin_x = int(width * (44 / 720 if is_vertical else 68 / 1280))
        bar_y = height - (12 if is_vertical else 10)
        bar_h = 5 if is_vertical else 4
        bar_total_w = max(40, width - 2 * bar_margin_x)
        progress_ratio = max(0.03, min(1.0, (scene_index + 1) / max(total_scenes, 1)))
        bar_fill_w = int(bar_total_w * progress_ratio)

        draw.rounded_rectangle(
            [bar_margin_x, bar_y, bar_margin_x + bar_total_w, bar_y + bar_h],
            radius=3,
            fill=(*accent_rgb, 38),
        )
        draw.rounded_rectangle(
            [bar_margin_x, bar_y, bar_margin_x + max(6, bar_fill_w), bar_y + bar_h],
            radius=3,
            fill=(*accent_rgb, 215),
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(output_path, format="PNG")
        return output_path

    _draw_subtle_vignette_and_grain(canvas, width, height, seed=1000 + scene_index * 37)

    # 1. Khung viền biên tập tối giản (hairline border + góc nhấn muted gold)
    margin = int(min(width, height) * 0.036)
    draw.rectangle(
        [margin, margin, width - margin, height - margin],
        outline=GOLD_SOFT,
        width=2,
    )

    corner_len = int(min(width, height) * 0.032)
    corners = [
        # Trên trái
        [(margin, margin), (margin + corner_len, margin)],
        [(margin, margin), (margin, margin + corner_len)],
        # Trên phải
        [(width - margin - corner_len, margin), (width - margin, margin)],
        [(width - margin, margin), (width - margin, margin + corner_len)],
        # Dưới trái
        [(margin, height - margin), (margin + corner_len, height - margin)],
        [(margin, height - margin - corner_len), (margin, height - margin)],
        # Dưới phải
        [(width - margin - corner_len, height - margin), (width - margin, height - margin)],
        [(width - margin, height - margin - corner_len), (width - margin, height - margin)],
    ]
    for line_pts in corners:
        draw.line(line_pts, fill=GOLD_ACCENT, width=3)

    # 2. Thanh tiến trình tối giản ở đáy khung
    bar_margin_x = margin + int(width * 0.04)
    bar_y = height - margin - (36 if is_vertical else 26)
    bar_h = 6 if is_vertical else 5
    bar_total_w = width - 2 * bar_margin_x
    progress_ratio = max(0.03, min(1.0, (scene_index + 1) / max(total_scenes, 1)))
    bar_fill_w = int(bar_total_w * progress_ratio)

    draw.rectangle(
        [bar_margin_x, bar_y, bar_margin_x + bar_total_w, bar_y + bar_h],
        fill=TRACK_BG,
    )
    draw.rectangle(
        [bar_margin_x, bar_y, bar_margin_x + bar_fill_w, bar_y + bar_h],
        fill=GOLD_ACCENT,
    )

    # 3. Chữ trích dẫn (Quote Overlay) nếu phân cảnh có trích dẫn
    quote = quote_overlay.strip()
    if quote:
        font_size = 54 if is_vertical else 48
        font = _load_unicode_font(font_size)
        wrap_chars = 24 if is_vertical else 42
        wrapped_lines = textwrap.wrap(f'“{quote}”', width=wrap_chars)

        line_heights = []
        line_widths = []
        for line in wrapped_lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            line_widths.append(bbox[2] - bbox[0])
            line_heights.append(bbox[3] - bbox[1])

        line_spacing = int(font_size * 0.36)
        block_h = sum(line_heights) + line_spacing * max(0, len(wrapped_lines) - 1)
        block_w = max(line_widths) if line_widths else 0

        pad_x = 34
        pad_y = 22
        box_bottom = bar_y - (52 if is_vertical else 38)
        box_top = box_bottom - block_h - pad_y * 2
        box_left = int((width - block_w) / 2) - pad_x
        box_right = int((width + block_w) / 2) + pad_x

        # Nền tối bán trong suốt nhẹ giúp chữ luôn sắc nét trên mọi ảnh nền
        draw.rectangle(
            [box_left, box_top, box_right, box_bottom],
            fill=SCRIM_DARK,
            outline=GOLD_SOFT,
            width=1,
        )

        # Vẽ từng dòng chữ căn giữa với bóng mềm
        curr_y = box_top + pad_y
        for line, lw, lh in zip(wrapped_lines, line_widths, line_heights):
            tx = int((width - lw) / 2)
            draw.text((tx + 2, curr_y + 2), line, font=font, fill=TEXT_SHADOW)
            draw.text((tx, curr_y), line, font=font, fill=TEXT_PRIMARY)
            curr_y += lh + line_spacing

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, format="PNG")
    return output_path


def _hex_to_rgb(hex_color: str, fallback: Tuple[int, int, int]) -> Tuple[int, int, int]:
    clean = (hex_color or "").strip().lstrip("#")
    if len(clean) == 6:
        try:
            return (int(clean[0:2], 16), int(clean[2:4], 16), int(clean[4:6], 16))
        except ValueError:
            pass
    return fallback


def render_youtube_thumbnail(
    art_image_path: Path,
    output_path: Path,
    headline: str,
    subtitle: str = "",
    folder_number: int | None = None,
) -> Path:
    """
    Tạo ảnh Thumbnail YouTube chuẩn 1280x720 PNG có độ tương phản cao (High-CTR)
    đồng bộ màu nền thương hiệu (`WHITEBOARD_BG_COLOR`, `WHITEBOARD_INK_COLOR`, `WHITEBOARD_ACCENT_COLOR`).
    """
    width, height = 1280, 720
    bg_rgb = _hex_to_rgb(getattr(config, "WHITEBOARD_BG_COLOR", "#EEF2F7"), (238, 242, 247))
    ink_rgb = _hex_to_rgb(getattr(config, "WHITEBOARD_INK_COLOR", "#0F172A"), (15, 23, 42))
    accent_rgb = _hex_to_rgb(getattr(config, "WHITEBOARD_ACCENT_COLOR", "#2563EB"), (37, 99, 235))

    luminance = (0.299 * bg_rgb[0] + 0.587 * bg_rgb[1] + 0.114 * bg_rgb[2]) / 255.0
    is_dark = luminance < 0.46
    card_bg = (30, 41, 59) if is_dark else (255, 255, 255)
    badge_text_rgb = (15, 23, 42) if (0.299 * accent_rgb[0] + 0.587 * accent_rgb[1] + 0.114 * accent_rgb[2]) / 255.0 > 0.55 else (255, 255, 255)

    canvas = Image.new("RGB", (width, height), bg_rgb)
    draw = ImageDraw.Draw(canvas)

    # Dải nhấn dọc cạnh trái tạo nhận diện kênh nổi bật trên Feed YouTube
    draw.rectangle([0, 0, 22, height], fill=accent_rgb)

    # Vùng khung hình minh họa bên phải (44% chiều ngang)
    art_box_x1, art_box_y1 = 710, 62
    art_box_x2, art_box_y2 = 1222, 658
    art_w = art_box_x2 - art_box_x1
    art_h = art_box_y2 - art_box_y1

    # Đổ bóng nhẹ + khung viền sắc nét cho tranh minh họa
    shadow_color = (8, 12, 20) if is_dark else (203, 213, 225)
    draw.rounded_rectangle(
        [art_box_x1 + 10, art_box_y1 + 10, art_box_x2 + 10, art_box_y2 + 10],
        radius=20,
        fill=shadow_color,
    )
    draw.rounded_rectangle(
        [art_box_x1, art_box_y1, art_box_x2, art_box_y2],
        radius=20,
        fill=card_bg,
        outline=accent_rgb,
        width=5,
    )

    if art_image_path.exists():
        with Image.open(art_image_path) as raw_art:
            art_rgb = raw_art.convert("RGB")
            # Crop trung tâm theo tỷ lệ khung bên phải rồi resize mượt
            src_w, src_h = art_rgb.size
            target_ratio = (art_w - 16) / (art_h - 16)
            src_ratio = src_w / max(src_h, 1)
            if src_ratio > target_ratio:
                crop_w = int(src_h * target_ratio)
                left = (src_w - crop_w) // 2
                art_cropped = art_rgb.crop((left, 0, left + crop_w, src_h))
            else:
                crop_h = int(src_w / target_ratio)
                top = (src_h - crop_h) // 2
                art_cropped = art_rgb.crop((0, top, src_w, top + crop_h))

            art_resized = art_cropped.resize((art_w - 16, art_h - 16), Image.Resampling.LANCZOS)
            canvas.paste(art_resized, (art_box_x1 + 8, art_box_y1 + 8))

    # Nhãn tập số ở góc trên bên trái (ví dụ: TẬP #01)
    left_x = 68
    top_y = 66
    if folder_number is not None:
        badge_label = f"TẬP #{folder_number:02d}"
        badge_font = _load_unicode_font(30)
        b_box = draw.textbbox((0, 0), badge_label, font=badge_font)
        bw = (b_box[2] - b_box[0]) + 44
        bh = (b_box[3] - b_box[1]) + 24
        draw.rounded_rectangle(
            [left_x, top_y, left_x + bw, top_y + bh],
            radius=10,
            fill=accent_rgb,
        )
        draw.text((left_x + 22, top_y + 10), badge_label, font=badge_font, fill=badge_text_rgb)
        headline_top = top_y + bh + 34
    else:
        headline_top = top_y + 24

    # Tiêu đề chính cỡ lớn (High-CTR, dễ đọc trên điện thoại)
    clean_headline = (headline or "BẢN LĨNH KHẮC KỶ").strip().upper()
    headline_font_size = 74 if len(clean_headline) <= 32 else 62
    headline_font = _load_unicode_font(headline_font_size)
    wrap_chars = 14 if headline_font_size >= 72 else 17
    lines = textwrap.wrap(clean_headline, width=wrap_chars)[:4]

    curr_y = headline_top
    for idx, line in enumerate(lines):
        # Dòng cuối hoặc dòng 2 tô màu nhấn accent để kéo ánh nhìn
        line_color = accent_rgb if (len(lines) >= 2 and idx == len(lines) - 1) else ink_rgb
        bbox = draw.textbbox((0, 0), line, font=headline_font)
        lh = bbox[3] - bbox[1]
        draw.text((left_x, curr_y), line, font=headline_font, fill=line_color)
        curr_y += lh + 24

    # Đường gạch ngang nhấn + dòng phụ ngắn (nếu có)
    draw.rectangle([left_x, curr_y + 10, left_x + 220, curr_y + 18], fill=accent_rgb)
    if subtitle.strip():
        sub_font = _load_unicode_font(30)
        sub_lines = textwrap.wrap(subtitle.strip(), width=34)[:2]
        sub_y = curr_y + 38
        sub_color = (203, 213, 225) if is_dark else (51, 65, 85)
        for s_line in sub_lines:
            bbox = draw.textbbox((0, 0), s_line, font=sub_font)
            draw.text((left_x, sub_y), s_line, font=sub_font, fill=sub_color)
            sub_y += (bbox[3] - bbox[1]) + 12

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, format="PNG", optimize=True)
    logger.info("[THUMBNAIL] Đã xuất Thumbnail YouTube 1280x720: %s", output_path.name)
    return output_path

