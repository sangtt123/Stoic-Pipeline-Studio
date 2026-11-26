"""
src/studio_art_engine.py — Bộ dựng hình minh họa Vector chuẩn Studio (Editorial Flat-Vector Explainer Engine).

Bản đồng bộ 1:1 với hệ thống dựng hình của Web Studio (Local Test):
- Tầng 1 (AI Art Director trong vertex_client.py): Chỉ 1 lần gọi LLM JSON nhẹ cho mỗi phân cảnh
  để đạo diễn toàn bộ 3–4 visual_beats (bố cục, tư thế, biểu cảm, đạo cụ ẩn dụ, hiệu ứng, caption ngắn).
- Tầng 2 (Module này): Dựng SVG hình học chuẩn xác với nhân vật người que mặc áo sơ mi cà vạt,
  32+ biểu tượng ẩn dụ nhiều lớp, khung sân khấu bo góc nền trắng sạch + bóng đổ nhẹ, thẻ đếm nhịp 1/4
  góc trên phải và hộp Caption chữ Việt sắc nét tách biệt hoàn toàn bên dưới (0% đè hình, 0% chữ rác,
  0% lỗi ngón tay/khuôn mặt, 0% lỗi 429 tạo ảnh raster).
- Cuối cùng rasterize SVG sang PNG 1920x1080 (hoặc 1080x1920 / 1280x720) siêu nét bằng `rsvg-convert`
  (hoặc `cairosvg` dự phòng).
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from html import escape as html_escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import config

logger = logging.getLogger("studio_art_engine")

STUDIO_COMPOSITIONS: Tuple[str, ...] = (
    "character_left_prop_right",
    "prop_left_character_right",
    "center_metaphor",
    "split_comparison",
    "cause_effect_flow",
    "two_characters_interaction",
    "character_on_pedestal",
    "checklist_steps",
)

STUDIO_POSES: Tuple[str, ...] = (
    "standing_calm",
    "standing_confident",
    "slumped_sad",
    "overwhelmed_head",
    "pointing_accuse",
    "shield_stance",
    "meditating_zen",
    "thinking_chin",
    "walking_forward",
    "climbing_up",
    "blocking_noise",
    "presenting_idea",
    "arms_crossed_steady",
    "victory_raised",
)

STUDIO_EXPRESSIONS: Tuple[str, ...] = (
    "calm",
    "confident",
    "sad",
    "angry",
    "stressed",
    "shocked",
    "thinking",
    "peaceful",
    "determined",
    "hurt",
)

STUDIO_PROPS: Tuple[str, ...] = (
    "boulder_wind",
    "criticism_arrows",
    "mind_shield",
    "storm_cloud",
    "sunrise_horizon",
    "hourglass",
    "balance_scale",
    "brain_focus",
    "mountain_peak",
    "broken_chains",
    "compass",
    "lightbulb",
    "target_bullseye",
    "phone_distraction",
    "clock_time",
    "stoic_scroll",
    "temple_pillar",
    "stairs_growth",
    "mirror_self",
    "brick_wall",
    "flame_forge",
    "anchor_waves",
    "heart_calm",
    "laurel_crown",
    "checklist_board",
    "crowd_chatter",
    "battery_power",
    "key_padlock",
    "crossroads",
    "growing_tree",
    "mask_duality",
    "speech_calm",
)

STUDIO_OVERLAYS: Tuple[str, ...] = (
    "none",
    "big_x_crossout",
    "checkmark_badge",
    "curved_arrow_right",
    "upward_growth_arrow",
    "shield_aura",
    "spark_emphasis",
)

FONT_FAMILY = "'DejaVu Sans', 'Noto Sans', 'Segoe UI', Arial, sans-serif"


@dataclass
class StudioThemeColors:
    bg_color: str = "#EEF2F7"
    ink_color: str = "#0F172A"
    accent_color: str = "#2563EB"
    surface_fill: str = "#FFFFFF"


@dataclass
class StudioShotBlueprint:
    composition: str
    character_pose: str
    character_expression: str
    primary_prop: str
    overlay_effect: str
    caption: str
    secondary_pose: Optional[str] = None
    secondary_expression: Optional[str] = None
    secondary_prop: Optional[str] = None
    sub_phrase: str = ""
    left_badge: Optional[str] = None
    right_badge: Optional[str] = None
    chapter_header: Optional[str] = None
    step_items: Optional[List[str]] = None
    beat_index: Optional[int] = None
    total_beats: Optional[int] = None


def resolve_studio_theme() -> StudioThemeColors:
    """Lấy bảng màu Studio đồng bộ từ config (hỗ trợ nền sáng và nền tối)."""

    def _safe_hex(val: str, fallback: str) -> str:
        s = str(val or "").strip()
        return s.upper() if re.fullmatch(r"#[0-9a-fA-F]{6}", s) else fallback

    bg = _safe_hex(getattr(config, "WHITEBOARD_BG_COLOR", "#EEF2F7"), "#EEF2F7")
    ink = _safe_hex(getattr(config, "WHITEBOARD_INK_COLOR", "#0F172A"), "#0F172A")
    accent = _safe_hex(getattr(config, "WHITEBOARD_ACCENT_COLOR", "#2563EB"), "#2563EB")

    r, g, b = int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16)
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
    surface = "#1D293D" if luminance < 0.46 else "#FFFFFF"
    return StudioThemeColors(
        bg_color=bg,
        ink_color=ink,
        accent_color=accent,
        surface_fill=surface,
    )


def _escape_xml(text: Any) -> str:
    return html_escape(str(text or ""), quote=True)


def _pick_enum(raw: Any, allowed: Sequence[str], fallback: str) -> str:
    if isinstance(raw, str):
        norm = raw.strip().lower()
        if norm in allowed:
            return norm
    return fallback


def _wrap_text_lines(text: str, max_chars: int, max_lines: int) -> List[str]:
    cleaned = re.sub(r"\s+", " ", re.sub(r"[&<>]", " ", str(text or ""))).strip()
    if not cleaned:
        return []
    words = cleaned.split(" ")
    lines: List[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}" if current else word
        if len(candidate) > max_chars and current:
            lines.append(current)
            current = word
            if len(lines) >= max_lines:
                break
        else:
            current = candidate
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines


def _render_multiline_text(
    lines: List[str],
    x: int,
    start_y: int,
    line_height: int,
    font_size: int,
    fill: str,
    font_weight: str = "700",
    anchor: str = "middle",
) -> str:
    return "\n".join(
        f'<text x="{x}" y="{start_y + idx * line_height}" text-anchor="{anchor}" '
        f'font-family="{FONT_FAMILY}" font-size="{font_size}" font-weight="{font_weight}" '
        f'fill="{fill}">{_escape_xml(line)}</text>'
        for idx, line in enumerate(lines)
    )


def infer_semantic_blueprint(
    phrase: str,
    short_label: str,
    image_prompt: str = "",
    chapter_header: Optional[str] = None,
    layout_type: Optional[str] = None,
    beat_index: Optional[int] = None,
    total_beats: Optional[int] = None,
) -> StudioShotBlueprint:
    """Bộ phân tích ngữ nghĩa tiếng Việt & tiếng Anh dự phòng thông minh."""
    text = f"{phrase} {short_label} {image_prompt}".lower()
    idx = beat_index or 0

    def _make(**kwargs: Any) -> StudioShotBlueprint:
        return StudioShotBlueprint(
            sub_phrase=phrase,
            chapter_header=chapter_header,
            beat_index=beat_index,
            total_beats=total_beats,
            **kwargs,
        )

    if re.search(r"(đá tảng|hòn đá|tảng đá|boulder|rock|wind|luồng gió|gió thổi)", text):
        return _make(
            composition="center_metaphor",
            character_pose="arms_crossed_steady",
            character_expression="calm",
            primary_prop="boulder_wind",
            overlay_effect="shield_aura",
            caption=short_label or "Gió qua đá tảng",
        )

    if re.search(r"(chê bai|chỉ trích|công kích|phán xét|xúc phạm|criticism|insult|pointing|shout|gossip|nói xấu|phản bội)", text):
        return _make(
            composition="two_characters_interaction",
            character_pose="standing_calm",
            character_expression="calm",
            secondary_pose="pointing_accuse",
            secondary_expression="angry",
            primary_prop="criticism_arrows",
            overlay_effect="none",
            left_badge="Lời công kích",
            right_badge="Giữ bình tĩnh",
            caption=short_label or "Khi bị công kích",
        )

    if re.search(r"(đau khổ|đau đớn|buồn|tổn thương|gục ngã|sụp đổ|tuyệt vọng|sad|suffer|pain|slumped|hurt|cry)", text):
        is_negated = bool(re.search(r"(thay vì|đừng|không|avoid|instead|stop|no longer|crossed out)", text))
        return _make(
            composition="character_left_prop_right",
            character_pose="slumped_sad",
            character_expression="sad",
            primary_prop="storm_cloud",
            overlay_effect="big_x_crossout" if is_negated else "none",
            caption=short_label or ("Không đau khổ" if is_negated else "Nỗi đau nội tâm"),
        )

    if re.search(r"(tâm trí|vững vàng|bình tĩnh|khiên|lá chắn|phòng thủ|shield|calm mind|steady|inner peace|bất biến|tĩnh tại)", text):
        return _make(
            composition="character_on_pedestal",
            character_pose="shield_stance",
            character_expression="confident",
            primary_prop="mind_shield",
            overlay_effect="shield_aura",
            caption=short_label or "Tâm trí vững vàng",
        )

    if re.search(r"(căng thẳng|lo âu|áp lực|quá tải|hoảng loạn|stress|anxious|overwhelm|panic|chaos)", text):
        return _make(
            composition="prop_left_character_right",
            character_pose="overwhelmed_head",
            character_expression="stressed",
            primary_prop="storm_cloud",
            overlay_effect="big_x_crossout",
            caption=short_label or "Áp lực và lo âu",
        )

    if re.search(r"(kiểm soát|cân bằng|nhị phân|lựa chọn|ngã rẽ|control|balance|scale|dichotomy|choice)", text):
        return _make(
            composition="split_comparison",
            character_pose="standing_confident",
            character_expression="determined",
            primary_prop="balance_scale",
            secondary_prop="crossroads",
            overlay_effect="checkmark_badge",
            left_badge="Ngoài tầm kiểm soát",
            right_badge="Trong tay bạn",
            caption=short_label or "Kiểm soát nội tâm",
        )

    if re.search(r"(thời gian|đồng hồ|cát|trì hoãn|hôm nay|hiện tại|time|hourglass|clock|procrastin|deadline)", text):
        return _make(
            composition="character_left_prop_right",
            character_pose="thinking_chin",
            character_expression="determined",
            primary_prop="hourglass",
            overlay_effect="spark_emphasis",
            caption=short_label or "Giá trị thời gian",
        )

    if re.search(r"(điện thoại|mạng xã hội|dopamine|xao nhãng|ồn ào|phone|social media|distract|noise|scroll)", text):
        return _make(
            composition="prop_left_character_right",
            character_pose="blocking_noise",
            character_expression="determined",
            primary_prop="phone_distraction",
            overlay_effect="big_x_crossout",
            caption=short_label or "Cắt bỏ xao nhãng",
        )

    if re.search(r"(tập trung|não bộ|suy nghĩ|nhận thức|tư duy|focus|brain|mind|clarity|thought|cognitive)", text):
        return _make(
            composition="character_left_prop_right",
            character_pose="presenting_idea",
            character_expression="confident",
            primary_prop="brain_focus",
            overlay_effect="spark_emphasis",
            caption=short_label or "Rèn luyện tâm trí",
        )

    if re.search(r"(kỷ luật|bước|tiến lên|phát triển|mục tiêu|đỉnh cao|climb|stairs|goal|growth|mountain|target)", text):
        return _make(
            composition="cause_effect_flow",
            character_pose="climbing_up",
            character_expression="determined",
            primary_prop="stairs_growth",
            secondary_prop="mountain_peak",
            overlay_effect="upward_growth_arrow",
            caption=short_label or "Tiến từng bước vững",
        )

    if re.search(r"(tự do|xiềng xích|buông bỏ|thoát khỏi|rời đi|chain|freedom|let go|break free)", text):
        return _make(
            composition="center_metaphor",
            character_pose="victory_raised",
            character_expression="peaceful",
            primary_prop="broken_chains",
            overlay_effect="spark_emphasis",
            caption=short_label or "Tự do từ bên trong",
        )

    if re.search(r"(khắc kỷ|marcus|seneca|epictetus|triết lý|cổ đại|sách|stoic|scroll|pillar|wisdom)", text):
        return _make(
            composition="character_left_prop_right",
            character_pose="presenting_idea",
            character_expression="calm",
            primary_prop="stoic_scroll",
            secondary_prop="temple_pillar",
            overlay_effect="spark_emphasis",
            caption=short_label or "Triết lý cổ xưa",
        )

    if re.search(r"(thử thách|nghịch cảnh|rào cản|vượt qua|lửa|obstacle|wall|fire|adversity|forge)", text):
        return _make(
            composition="cause_effect_flow",
            character_pose="walking_forward",
            character_expression="determined",
            primary_prop="brick_wall",
            secondary_prop="flame_forge",
            overlay_effect="curved_arrow_right",
            caption=short_label or "Vượt qua nghịch cảnh",
        )

    if re.search(r"(thiền|thở|im lặng|tĩnh lặng|bình an|meditat|breathe|silence|stillness|anchor)", text):
        return _make(
            composition="character_on_pedestal",
            character_pose="meditating_zen",
            character_expression="peaceful",
            primary_prop="anchor_waves",
            overlay_effect="shield_aura",
            caption=short_label or "Tĩnh lặng nội tâm",
        )

    if re.search(r"(tổng kết|danh sách|3 bước|4 nguyên lý|áp dụng|thực hành|summary|checklist|steps)", text) or layout_type in ("summary_list", "three_branches"):
        return _make(
            composition="checklist_steps",
            character_pose="presenting_idea",
            character_expression="confident",
            primary_prop="checklist_board",
            overlay_effect="checkmark_badge",
            caption=short_label or "Áp dụng ngay hôm nay",
        )

    cycle_defaults = [
        ("character_left_prop_right", "thinking_chin", "thinking", "compass", "spark_emphasis"),
        ("split_comparison", "arms_crossed_steady", "determined", "balance_scale", "curved_arrow_right"),
        ("center_metaphor", "standing_confident", "calm", "lightbulb", "upward_growth_arrow"),
        ("character_on_pedestal", "standing_confident", "confident", "laurel_crown", "checkmark_badge"),
    ]
    comp, pose, expr, prop, ov = cycle_defaults[abs(idx) % len(cycle_defaults)]
    return _make(
        composition=comp,
        character_pose=pose,
        character_expression=expr,
        primary_prop=prop,
        overlay_effect=ov,
        caption=short_label or "Góc nhìn Khắc kỷ",
    )


def normalize_studio_blueprint(
    raw: Optional[Dict[str, Any]],
    phrase: str,
    short_label: str,
    image_prompt: str = "",
    chapter_header: Optional[str] = None,
    layout_type: Optional[str] = None,
    beat_index: Optional[int] = None,
    total_beats: Optional[int] = None,
) -> StudioShotBlueprint:
    """Chuẩn hóa JSON từ AI Art Director thành blueprint hợp lệ 100%."""
    inferred = infer_semantic_blueprint(
        phrase=phrase,
        short_label=short_label,
        image_prompt=image_prompt,
        chapter_header=chapter_header,
        layout_type=layout_type,
        beat_index=beat_index,
        total_beats=total_beats,
    )
    if not raw or not isinstance(raw, dict):
        return inferred

    raw_steps = raw.get("step_items")
    step_items: Optional[List[str]] = None
    if isinstance(raw_steps, list):
        cleaned_steps = [
            re.sub(r"[&<>]", " ", str(x or "")).strip()[:34]
            for x in raw_steps
            if str(x or "").strip()
        ][:3]
        if cleaned_steps:
            step_items = cleaned_steps

    caption = (
        re.sub(r"[&<>]", " ", str(raw.get("caption") or short_label or inferred.caption))
        .strip()[:44]
        or inferred.caption
    )
    left_badge = (
        re.sub(r"[&<>]", " ", str(raw.get("left_badge"))).strip()[:22]
        if raw.get("left_badge")
        else inferred.left_badge
    )
    right_badge = (
        re.sub(r"[&<>]", " ", str(raw.get("right_badge"))).strip()[:22]
        if raw.get("right_badge")
        else inferred.right_badge
    )

    return StudioShotBlueprint(
        composition=_pick_enum(raw.get("composition"), STUDIO_COMPOSITIONS, inferred.composition),
        character_pose=_pick_enum(raw.get("character_pose"), STUDIO_POSES, inferred.character_pose),
        character_expression=_pick_enum(raw.get("character_expression"), STUDIO_EXPRESSIONS, inferred.character_expression),
        secondary_pose=(
            _pick_enum(raw.get("secondary_pose"), STUDIO_POSES, inferred.secondary_pose or "pointing_accuse")
            if raw.get("secondary_pose")
            else inferred.secondary_pose
        ),
        secondary_expression=(
            _pick_enum(raw.get("secondary_expression"), STUDIO_EXPRESSIONS, inferred.secondary_expression or "angry")
            if raw.get("secondary_expression")
            else inferred.secondary_expression
        ),
        primary_prop=_pick_enum(raw.get("primary_prop"), STUDIO_PROPS, inferred.primary_prop),
        secondary_prop=(
            _pick_enum(raw.get("secondary_prop"), STUDIO_PROPS, inferred.secondary_prop or "sunrise_horizon")
            if raw.get("secondary_prop")
            else inferred.secondary_prop
        ),
        overlay_effect=_pick_enum(raw.get("overlay_effect"), STUDIO_OVERLAYS, inferred.overlay_effect),
        caption=caption,
        sub_phrase=phrase,
        left_badge=left_badge,
        right_badge=right_badge,
        chapter_header=chapter_header,
        step_items=step_items,
        beat_index=beat_index,
        total_beats=total_beats,
    )


def _render_face_expression(expression: str, ink: str, accent: str, surface: str) -> str:
    if expression == "angry":
        return f"""
        <path d="M-24 -94 L-7 -86 M24 -94 L7 -86" stroke="{ink}" stroke-width="4.5" stroke-linecap="round"/>
        <circle cx="-14" cy="-78" r="4.5" fill="{ink}"/>
        <circle cx="14" cy="-78" r="4.5" fill="{ink}"/>
        <path d="M-16 -56 Q0 -69 16 -56" fill="{accent}" fill-opacity="0.22" stroke="{ink}" stroke-width="4" stroke-linecap="round"/>
        <path d="M26 -110 L35 -101 M35 -110 L26 -101" stroke="{accent}" stroke-width="3.2" stroke-linecap="round"/>
        """
    if expression in ("sad", "hurt"):
        return f"""
        <path d="M-24 -88 Q-15 -94 -7 -90 M24 -88 Q15 -94 7 -90" fill="none" stroke="{ink}" stroke-width="3.6" stroke-linecap="round"/>
        <circle cx="-14" cy="-78" r="4.2" fill="{ink}"/>
        <circle cx="14" cy="-78" r="4.2" fill="{ink}"/>
        <path d="M-15 -54 Q0 -66 15 -54" fill="none" stroke="{ink}" stroke-width="4" stroke-linecap="round"/>
        <path d="M-20 -68 Q-24 -58 -19 -54 Q-14 -58 -20 -68 Z" fill="{accent}" fill-opacity="0.8"/>
        """
    if expression == "stressed":
        return f"""
        <path d="M-23 -93 L-8 -88 M23 -93 L8 -88" stroke="{ink}" stroke-width="3.8" stroke-linecap="round"/>
        <circle cx="-14" cy="-78" r="5" fill="{surface}" stroke="{ink}" stroke-width="3.2"/>
        <circle cx="-14" cy="-78" r="2" fill="{ink}"/>
        <circle cx="14" cy="-78" r="5" fill="{surface}" stroke="{ink}" stroke-width="3.2"/>
        <circle cx="14" cy="-78" r="2" fill="{ink}"/>
        <path d="M-16 -57 Q-8 -63 0 -57 Q8 -51 16 -57" fill="none" stroke="{ink}" stroke-width="3.8" stroke-linecap="round"/>
        <path d="M32 -95 Q38 -84 32 -78 Q26 -84 32 -95 Z" fill="{accent}"/>
        """
    if expression == "shocked":
        return f"""
        <path d="M-23 -96 Q-14 -103 -6 -96 M6 -96 Q14 -103 23 -96" fill="none" stroke="{ink}" stroke-width="3.5" stroke-linecap="round"/>
        <circle cx="-14" cy="-80" r="5.5" fill="{surface}" stroke="{ink}" stroke-width="3.2"/>
        <circle cx="-14" cy="-80" r="2.2" fill="{ink}"/>
        <circle cx="14" cy="-80" r="5.5" fill="{surface}" stroke="{ink}" stroke-width="3.2"/>
        <circle cx="14" cy="-80" r="2.2" fill="{ink}"/>
        <ellipse cx="0" cy="-57" rx="9" ry="11" fill="{accent}" fill-opacity="0.2" stroke="{ink}" stroke-width="3.8"/>
        """
    if expression == "peaceful":
        return f"""
        <path d="M-22 -78 Q-14 -72 -6 -78 M6 -78 Q14 -72 22 -78" fill="none" stroke="{ink}" stroke-width="4" stroke-linecap="round"/>
        <path d="M-13 -58 Q0 -49 13 -58" fill="none" stroke="{ink}" stroke-width="3.8" stroke-linecap="round"/>
        """
    if expression == "thinking":
        return f"""
        <path d="M-22 -91 Q-14 -96 -6 -91 M7 -94 L22 -91" fill="none" stroke="{ink}" stroke-width="3.5" stroke-linecap="round"/>
        <circle cx="-13" cy="-79" r="4.2" fill="{ink}"/>
        <circle cx="15" cy="-79" r="4.2" fill="{ink}"/>
        <path d="M-9 -57 Q2 -55 12 -60" fill="none" stroke="{ink}" stroke-width="3.8" stroke-linecap="round"/>
        """
    if expression == "determined":
        return f"""
        <path d="M-23 -91 L-7 -88 M23 -91 L7 -88" stroke="{ink}" stroke-width="4.2" stroke-linecap="round"/>
        <circle cx="-14" cy="-78" r="4.5" fill="{ink}"/>
        <circle cx="14" cy="-78" r="4.5" fill="{ink}"/>
        <line x1="-13" y1="-57" x2="13" y2="-57" stroke="{ink}" stroke-width="4.2" stroke-linecap="round"/>
        """
    if expression == "confident":
        return f"""
        <path d="M-22 -92 Q-14 -97 -6 -92 M6 -92 Q14 -97 22 -92" fill="none" stroke="{ink}" stroke-width="3.6" stroke-linecap="round"/>
        <circle cx="-14" cy="-79" r="4.6" fill="{ink}"/>
        <circle cx="-12.5" cy="-80.5" r="1.4" fill="{surface}"/>
        <circle cx="14" cy="-79" r="4.6" fill="{ink}"/>
        <circle cx="15.5" cy="-80.5" r="1.4" fill="{surface}"/>
        <path d="M-16 -60 Q0 -46 16 -60" fill="none" stroke="{ink}" stroke-width="4.2" stroke-linecap="round"/>
        """
    return f"""
    <circle cx="-14" cy="-79" r="4.5" fill="{ink}"/>
    <circle cx="-12.5" cy="-80.5" r="1.3" fill="{surface}"/>
    <circle cx="14" cy="-79" r="4.5" fill="{ink}"/>
    <circle cx="15.5" cy="-80.5" r="1.3" fill="{surface}"/>
    <path d="M-13 -59 Q0 -50 13 -59" fill="none" stroke="{ink}" stroke-width="4" stroke-linecap="round"/>
    """


def _render_studio_character(
    x: int,
    y: int,
    pose: str,
    expression: str,
    theme: StudioThemeColors,
    scale: float = 1.0,
    flip_x: bool = False,
    accent_tie: bool = True,
) -> str:
    ink = theme.ink_color
    accent = theme.accent_color
    surface = theme.surface_fill
    tie_color = accent if accent_tie else ink
    sx = -scale if flip_x else scale

    if pose == "meditating_zen":
        return f"""<g transform="translate({x}, {y}) scale({sx}, {scale})">
      <ellipse cx="0" cy="146" rx="88" ry="15" fill="{ink}" fill-opacity="0.12"/>
      <circle cx="0" cy="-25" r="120" fill="{accent}" fill-opacity="0.06" stroke="{accent}" stroke-width="2.5" stroke-dasharray="10 8"/>
      <path d="M-24 92 Q-78 104 -68 132 Q-42 146 8 134" fill="none" stroke="{ink}" stroke-width="11" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M24 92 Q78 104 68 132 Q42 146 -8 134" fill="none" stroke="{ink}" stroke-width="11" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M-32 8 Q0 -6 32 8 L38 96 Q0 108 -38 96 Z" fill="{surface}" stroke="{ink}" stroke-width="5" stroke-linejoin="round"/>
      <polygon points="0,4 -7,34 0,60 7,34" fill="{tie_color}"/>
      <path d="M-30 22 Q-66 56 -56 106 L-34 114" fill="none" stroke="{ink}" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M30 22 Q66 56 56 106 L34 114" fill="none" stroke="{ink}" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/>
      <circle cx="-32" cy="114" r="7" fill="{surface}" stroke="{ink}" stroke-width="4"/>
      <circle cx="32" cy="114" r="7" fill="{surface}" stroke="{ink}" stroke-width="4"/>
      <rect x="-8" y="-32" width="16" height="32" rx="6" fill="{surface}" stroke="{ink}" stroke-width="4.5"/>
      <circle cx="0" cy="-76" r="46" fill="{surface}" stroke="{ink}" stroke-width="5.2"/>
      <path d="M-36 -104 Q-14 -132 18 -124 Q38 -118 42 -96 Q16 -112 -14 -108 Q-28 -106 -36 -104 Z" fill="{ink}"/>
      {_render_face_expression(expression, ink, accent, surface)}
    </g>"""

    head_shift_x = 0
    head_shift_y = 0
    torso_skew = ""
    left_arm = "M-32 18 L-68 68 L-58 104"
    right_arm = "M32 18 L68 68 L58 104"
    left_hand = (-58, 104)
    right_hand = (58, 104)
    legs_svg = f"""
    <path d="M-16 102 L-24 166 L-40 168" fill="none" stroke="{ink}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
    <path d="M16 102 L24 166 L42 168" fill="none" stroke="{ink}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
    """
    extra_prop = ""

    if pose == "standing_confident":
        left_arm = "M-32 18 L-66 56 L-34 84"
        right_arm = "M32 18 L66 56 L34 84"
        left_hand = (-34, 84)
        right_hand = (34, 84)
        legs_svg = f"""
        <path d="M-16 102 L-32 166 L-50 168" fill="none" stroke="{ink}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M16 102 L32 166 L50 168" fill="none" stroke="{ink}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
        """
    elif pose == "slumped_sad":
        head_shift_x = 12
        head_shift_y = 14
        torso_skew = "rotate(8, 0, 60)"
        left_arm = "M-26 26 L-44 82 L-30 124"
        right_arm = "M30 28 L46 84 L38 126"
        left_hand = (-30, 124)
        right_hand = (38, 126)
    elif pose == "overwhelmed_head":
        head_shift_y = 6
        left_arm = "M-32 18 L-66 -26 L-44 -76"
        right_arm = "M32 18 L66 -26 L44 -76"
        left_hand = (-44, -76)
        right_hand = (44, -76)
        extra_prop = f"""
        <path d="M-64 -116 Q-42 -136 -20 -122 M20 -124 Q44 -140 66 -116" fill="none" stroke="{accent}" stroke-width="4" stroke-linecap="round"/>
        <path d="M-56 -138 L-44 -128 M56 -138 L44 -128 M0 -144 L0 -132" stroke="{accent}" stroke-width="4" stroke-linecap="round"/>
        """
    elif pose == "pointing_accuse":
        head_shift_x = 8
        torso_skew = "rotate(6, 0, 70)"
        left_arm = "M-30 22 L-56 64 L-32 82"
        right_arm = "M32 16 L84 8 L122 4"
        left_hand = (-32, 82)
        right_hand = (122, 4)
        legs_svg = f"""
        <path d="M-16 102 L-36 166 L-54 168" fill="none" stroke="{ink}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M16 102 L38 166 L58 168" fill="none" stroke="{ink}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
        """
        extra_prop = f"""
        <path d="M62 -98 L82 -108 M66 -78 L90 -80 M62 -58 L82 -50" stroke="{accent}" stroke-width="4.5" stroke-linecap="round"/>
        """
    elif pose == "shield_stance":
        left_arm = "M-32 20 L-58 64 L-38 92"
        right_arm = "M32 18 L76 32 L92 14"
        left_hand = (-38, 92)
        right_hand = (92, 14)
        extra_prop = f"""
        <path d="M88 -34 L132 -20 L128 42 Q108 78 88 92 Q68 78 64 42 L68 -20 Z" fill="{surface}" stroke="{accent}" stroke-width="6" stroke-linejoin="round"/>
        <path d="M88 -14 L112 -5 L110 34 Q98 56 88 66 Q78 56 76 34 L78 -5 Z" fill="{accent}" fill-opacity="0.18"/>
        <path d="M77 24 L86 34 L104 12" fill="none" stroke="{accent}" stroke-width="5.5" stroke-linecap="round" stroke-linejoin="round"/>
        """
    elif pose == "thinking_chin":
        left_arm = "M-32 22 L-54 70 L-22 80"
        right_arm = "M32 20 L58 18 L18 -34"
        left_hand = (-22, 80)
        right_hand = (18, -34)
        extra_prop = f"""
        <circle cx="64" cy="-110" r="6" fill="{accent}" fill-opacity="0.4"/>
        <circle cx="80" cy="-126" r="9" fill="{accent}" fill-opacity="0.65"/>
        """
    elif pose == "walking_forward":
        torso_skew = "rotate(5, 0, 70)"
        left_arm = "M-30 22 L-62 58 L-48 92"
        right_arm = "M32 20 L68 48 L88 26"
        left_hand = (-48, 92)
        right_hand = (88, 26)
        legs_svg = f"""
        <path d="M-12 102 L-48 158 L-66 154" fill="none" stroke="{ink}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M16 102 L48 164 L68 166" fill="none" stroke="{ink}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
        """
    elif pose == "climbing_up":
        torso_skew = "rotate(7, 0, 60)"
        left_arm = "M-30 22 L-58 48 L-44 82"
        right_arm = "M32 16 L76 -16 L96 -42"
        left_hand = (-44, 82)
        right_hand = (96, -42)
        legs_svg = f"""
        <path d="M-14 102 L-38 166 L-56 168" fill="none" stroke="{ink}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M16 100 L54 124 L42 158 L62 158" fill="none" stroke="{ink}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
        """
    elif pose == "blocking_noise":
        left_arm = "M-32 20 L-60 66 L-44 96"
        right_arm = "M32 16 L84 6 L108 -18"
        left_hand = (-44, 96)
        right_hand = (108, -18)
        extra_prop = f"""
        <path d="M118 -40 L118 8" stroke="{accent}" stroke-width="6" stroke-linecap="round"/>
        <path d="M132 -32 L132 0" stroke="{accent}" stroke-width="4" stroke-linecap="round" stroke-opacity="0.55"/>
        """
    elif pose == "presenting_idea":
        left_arm = "M-32 22 L-56 70 L-42 102"
        right_arm = "M32 16 L82 -6 L112 -32"
        left_hand = (-42, 102)
        right_hand = (112, -32)
    elif pose == "arms_crossed_steady":
        left_arm = "M-32 18 L-54 58 L22 52"
        right_arm = "M32 18 L54 58 L-22 64"
        left_hand = (22, 52)
        right_hand = (-22, 64)
    elif pose == "victory_raised":
        left_arm = "M-32 16 L-72 -26 L-64 -76"
        right_arm = "M32 16 L72 -26 L64 -76"
        left_hand = (-64, -76)
        right_hand = (64, -76)
        extra_prop = f"""
        <path d="M-92 -94 L-78 -86 M92 -94 L78 -86 M0 -144 L0 -128" stroke="{accent}" stroke-width="4.5" stroke-linecap="round"/>
        """
    else:
        left_arm = "M-32 20 L-58 68 L-48 102"
        right_arm = "M32 20 L68 54 L92 38"
        left_hand = (-48, 102)
        right_hand = (92, 38)

    return f"""<g transform="translate({x}, {y}) scale({sx}, {scale})">
    <ellipse cx="0" cy="172" rx="68" ry="12" fill="{ink}" fill-opacity="0.12"/>
    {legs_svg}
    <g transform="{torso_skew}">
      <path d="{left_arm}" fill="none" stroke="{ink}" stroke-width="9" stroke-linecap="round" stroke-linejoin="round"/>
      <circle cx="{left_hand[0]}" cy="{left_hand[1]}" r="7.5" fill="{surface}" stroke="{ink}" stroke-width="4"/>
      <path d="M-34 8 Q0 -6 34 8 L28 104 Q0 112 -28 104 Z" fill="{surface}" stroke="{ink}" stroke-width="5.2" stroke-linejoin="round"/>
      <path d="M-14 4 L0 20 L14 4" fill="none" stroke="{ink}" stroke-width="3.5" stroke-linejoin="round"/>
      <polygon points="0,14 -8,44 0,76 8,44" fill="{tie_color}"/>
      <path d="{right_arm}" fill="none" stroke="{ink}" stroke-width="9" stroke-linecap="round" stroke-linejoin="round"/>
      <circle cx="{right_hand[0]}" cy="{right_hand[1]}" r="7.5" fill="{surface}" stroke="{ink}" stroke-width="4"/>
      <g transform="translate({head_shift_x}, {head_shift_y})">
        <rect x="-8" y="-32" width="16" height="34" rx="6" fill="{surface}" stroke="{ink}" stroke-width="4.5"/>
        <circle cx="0" cy="-76" r="46" fill="{surface}" stroke="{ink}" stroke-width="5.2"/>
        <path d="M-38 -102 Q-18 -134 18 -126 Q38 -120 44 -94 Q18 -110 -12 -106 Q-28 -104 -38 -102 Z" fill="{ink}"/>
        {_render_face_expression(expression, ink, accent, surface)}
      </g>
      {extra_prop}
    </g>
  </g>"""


def _render_studio_prop(prop: str, x: int, y: int, scale: float, theme: StudioThemeColors) -> str:
    bg = theme.bg_color
    ink = theme.ink_color
    accent = theme.accent_color
    surface = theme.surface_fill
    inner = ""

    if prop == "boulder_wind":
        inner = f"""
        <ellipse cx="10" cy="108" rx="130" ry="18" fill="{ink}" fill-opacity="0.14"/>
        <path d="M-195 -46 C-125 -46 -95 -112 -10 -116 C65 -120 120 -78 188 -82" fill="none" stroke="{accent}" stroke-width="6.5" stroke-linecap="round"/>
        <path d="M168 -96 L192 -82 L170 -68" fill="none" stroke="{accent}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M-185 8 C-132 8 -108 -68 -14 -76 C70 -84 128 -26 178 -30" fill="none" stroke="{accent}" stroke-width="5" stroke-linecap="round" stroke-opacity="0.72"/>
        <path d="M-168 58 C-124 58 -106 34 -88 18" fill="none" stroke="{accent}" stroke-width="4.5" stroke-linecap="round" stroke-dasharray="12 10"/>
        <path d="M126 32 C154 32 178 24 196 10" fill="none" stroke="{accent}" stroke-width="4.5" stroke-linecap="round"/>
        <polygon points="-108,104 -92,-6 -34,-74 48,-66 104,-4 116,104" fill="{surface}" stroke="{ink}" stroke-width="6" stroke-linejoin="round"/>
        <polygon points="-34,-74 14,-8 -12,104 -108,104 -92,-6" fill="{ink}" fill-opacity="0.09"/>
        <polygon points="48,-66 104,-4 116,104 42,104 54,18" fill="{ink}" fill-opacity="0.15"/>
        <path d="M-34 -74 L14 -8 L-12 104 M48 -66 L14 -8 L98 28" fill="none" stroke="{ink}" stroke-width="4" stroke-linejoin="round"/>
        <path d="M-54 36 L-26 22 M36 56 L72 44" stroke="{ink}" stroke-width="3.5" stroke-linecap="round" stroke-opacity="0.6"/>
        """
    elif prop == "criticism_arrows":
        inner = f"""
        <g transform="translate(-52, -74)">
          <rect x="-78" y="-34" width="156" height="62" rx="14" fill="{surface}" stroke="{ink}" stroke-width="5"/>
          <polygon points="62,24 94,38 72,8" fill="{surface}" stroke="{ink}" stroke-width="5" stroke-linejoin="round"/>
          <path d="M-46 -6 L-36 12 M-28 -10 L-28 8 M-28 16 L-28 18 M-6 -8 L12 10 M12 -8 L-6 10 M32 -12 L26 12 M44 -12 L38 12" stroke="{accent}" stroke-width="5" stroke-linecap="round"/>
        </g>
        <g transform="translate(-82, 24)">
          <rect x="-66" y="-28" width="132" height="52" rx="12" fill="{surface}" stroke="{ink}" stroke-width="4.5"/>
          <polygon points="50,18 78,30 58,4" fill="{surface}" stroke="{ink}" stroke-width="4.5" stroke-linejoin="round"/>
          <line x1="-38" y1="-4" x2="28" y2="-4" stroke="{ink}" stroke-width="4.5" stroke-linecap="round"/>
          <line x1="-38" y1="10" x2="8" y2="10" stroke="{accent}" stroke-width="4.5" stroke-linecap="round"/>
        </g>
        <path d="M-128 -14 L94 -14" stroke="{accent}" stroke-width="6.5" stroke-linecap="round"/>
        <polygon points="114,-14 84,-28 90,-14 84,0" fill="{accent}"/>
        <path d="M-104 82 L76 48" stroke="{accent}" stroke-width="5.5" stroke-linecap="round"/>
        <polygon points="96,44 66,36 74,48 70,62" fill="{accent}"/>
        """
    elif prop == "mind_shield":
        inner = f"""
        <circle cx="0" cy="-2" r="118" fill="{accent}" fill-opacity="0.08" stroke="{accent}" stroke-width="3" stroke-dasharray="10 8"/>
        <circle cx="0" cy="-2" r="94" fill="none" stroke="{accent}" stroke-width="2.5" stroke-opacity="0.45"/>
        <path d="M0 -98 L82 -66 L74 28 Q56 84 0 112 Q-56 84 -74 28 L-82 -66 Z" fill="{surface}" stroke="{ink}" stroke-width="6" stroke-linejoin="round"/>
        <path d="M0 -76 L62 -52 L56 22 Q42 64 0 88 Q-42 64 -56 22 L-62 -52 Z" fill="{accent}" fill-opacity="0.14" stroke="{accent}" stroke-width="4.5" stroke-linejoin="round"/>
        <circle cx="0" cy="0" r="28" fill="{surface}" stroke="{accent}" stroke-width="4.5"/>
        <path d="M-12 0 L-3 10 L15 -10" fill="none" stroke="{accent}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>
        """
    elif prop == "storm_cloud":
        inner = f"""
        <ellipse cx="0" cy="108" rx="92" ry="12" fill="{ink}" fill-opacity="0.1"/>
        <path d="M-86 14 Q-114 14 -114 -16 Q-114 -44 -86 -48 Q-76 -88 -34 -92 Q8 -96 32 -66 Q66 -74 90 -46 Q116 -38 112 -8 Q110 14 82 14 Z" fill="{surface}" stroke="{ink}" stroke-width="6" stroke-linejoin="round"/>
        <path d="M-82 14 Q-108 14 -108 -14 Q-108 -36 -84 -42 Q-74 -78 -34 -82 Q4 -86 28 -58" fill="{ink}" fill-opacity="0.08"/>
        <polygon points="6,14 -24,62 2,62 -14,108 32,48 6,48 22,14" fill="{accent}" stroke="{ink}" stroke-width="3.5" stroke-linejoin="round"/>
        <line x1="-68" y1="34" x2="-82" y2="74" stroke="{ink}" stroke-width="4.5" stroke-linecap="round"/>
        <line x1="-42" y1="42" x2="-54" y2="82" stroke="{ink}" stroke-width="4.5" stroke-linecap="round"/>
        <line x1="56" y1="34" x2="42" y2="74" stroke="{ink}" stroke-width="4.5" stroke-linecap="round"/>
        <line x1="82" y1="40" x2="70" y2="76" stroke="{ink}" stroke-width="4.5" stroke-linecap="round"/>
        """
    elif prop == "sunrise_horizon":
        inner = f"""
        <circle cx="0" cy="24" r="76" fill="{accent}" fill-opacity="0.16" stroke="{accent}" stroke-width="5"/>
        <path d="M0 -88 L0 -64 M-82 -52 L-64 -34 M82 -52 L64 -34 M-112 18 L-88 18 M112 18 L88 18" stroke="{accent}" stroke-width="5.5" stroke-linecap="round"/>
        <path d="M-136 68 Q-58 18 14 58 Q74 26 136 68 L136 102 L-136 102 Z" fill="{surface}" stroke="{ink}" stroke-width="5.5" stroke-linejoin="round"/>
        <path d="M-136 86 Q-36 52 54 84 Q102 68 136 86" fill="none" stroke="{ink}" stroke-width="4" stroke-linecap="round"/>
        """
    elif prop == "hourglass":
        inner = f"""
        <ellipse cx="0" cy="112" rx="76" ry="12" fill="{ink}" fill-opacity="0.12"/>
        <rect x="-76" y="-102" width="152" height="18" rx="6" fill="{ink}"/>
        <rect x="-76" y="84" width="152" height="18" rx="6" fill="{ink}"/>
        <path d="M-58 -84 C-58 -24 -12 -14 -8 0 C-12 14 -58 24 -58 84 L58 84 C58 24 12 14 8 0 C12 -14 58 -24 58 -84 Z" fill="{surface}" stroke="{ink}" stroke-width="5.5" stroke-linejoin="round"/>
        <path d="M-36 -48 L36 -48 Q16 -14 0 -8 Q-16 -14 -36 -48 Z" fill="{accent}" fill-opacity="0.82"/>
        <line x1="0" y1="-6" x2="0" y2="54" stroke="{accent}" stroke-width="4.5" stroke-dasharray="6 5" stroke-linecap="round"/>
        <path d="M-44 82 Q0 32 44 82 Z" fill="{accent}" fill-opacity="0.88"/>
        """
    elif prop == "balance_scale":
        inner = f"""
        <ellipse cx="0" cy="108" rx="82" ry="12" fill="{ink}" fill-opacity="0.12"/>
        <rect x="-46" y="92" width="92" height="14" rx="5" fill="{ink}"/>
        <line x1="0" y1="-78" x2="0" y2="94" stroke="{ink}" stroke-width="7" stroke-linecap="round"/>
        <circle cx="0" cy="-78" r="12" fill="{accent}" stroke="{ink}" stroke-width="4.5"/>
        <line x1="-102" y1="-58" x2="102" y2="-58" stroke="{ink}" stroke-width="6.5" stroke-linecap="round"/>
        <path d="M-92 -58 L-120 18 L-64 18 Z" fill="none" stroke="{ink}" stroke-width="3.8" stroke-linejoin="round"/>
        <path d="M-126 18 Q-92 48 -58 18 Z" fill="{surface}" stroke="{ink}" stroke-width="5"/>
        <path d="M92 -58 L64 18 L120 18 Z" fill="none" stroke="{ink}" stroke-width="3.8" stroke-linejoin="round"/>
        <path d="M58 18 Q92 48 126 18 Z" fill="{accent}" fill-opacity="0.24" stroke="{accent}" stroke-width="5"/>
        <circle cx="92" cy="4" r="13" fill="{accent}"/>
        """
    elif prop == "brain_focus":
        inner = f"""
        <circle cx="0" cy="0" r="102" fill="{accent}" fill-opacity="0.08" stroke="{accent}" stroke-width="3" stroke-dasharray="10 8"/>
        <path d="M-8 -76 C-56 -78 -86 -42 -78 -4 C-94 24 -70 72 -26 70 L-8 70 Z" fill="{surface}" stroke="{ink}" stroke-width="5.5" stroke-linejoin="round"/>
        <path d="M8 -76 C56 -78 86 -42 78 -4 C94 24 70 72 26 70 L8 70 Z" fill="{surface}" stroke="{ink}" stroke-width="5.5" stroke-linejoin="round"/>
        <path d="M-54 -28 Q-32 -40 -22 -18 M-58 20 Q-34 8 -22 32 M54 -28 Q32 -40 22 -18 M58 20 Q34 8 22 32" fill="none" stroke="{ink}" stroke-width="4" stroke-linecap="round"/>
        <circle cx="0" cy="-2" r="26" fill="{surface}" stroke="{accent}" stroke-width="5"/>
        <circle cx="0" cy="-2" r="10" fill="{accent}"/>
        """
    elif prop == "mountain_peak":
        inner = f"""
        <ellipse cx="0" cy="104" rx="132" ry="14" fill="{ink}" fill-opacity="0.12"/>
        <polygon points="-132,100 -42,-42 46,100" fill="{surface}" stroke="{ink}" stroke-width="5.5" stroke-linejoin="round"/>
        <polygon points="-28,100 54,-82 136,100" fill="{surface}" stroke="{ink}" stroke-width="6" stroke-linejoin="round"/>
        <polygon points="54,-82 28,-22 54,-34 80,-22" fill="{accent}" fill-opacity="0.22" stroke="{ink}" stroke-width="4" stroke-linejoin="round"/>
        <line x1="54" y1="-82" x2="54" y2="-126" stroke="{ink}" stroke-width="5" stroke-linecap="round"/>
        <polygon points="54,-126 102,-112 54,-96" fill="{accent}" stroke="{ink}" stroke-width="3.5" stroke-linejoin="round"/>
        <path d="M-84 100 Q-18 54 14 68 Q46 80 54 -14" fill="none" stroke="{accent}" stroke-width="5" stroke-dasharray="10 8" stroke-linecap="round"/>
        """
    elif prop == "broken_chains":
        inner = f"""
        <g transform="translate(-62, 0) rotate(-18)">
          <rect x="-56" y="-22" width="68" height="44" rx="22" fill="none" stroke="{ink}" stroke-width="11"/>
          <rect x="-6" y="-22" width="54" height="44" rx="22" fill="none" stroke="{ink}" stroke-width="11"/>
        </g>
        <g transform="translate(62, 0) rotate(18)">
          <rect x="-48" y="-22" width="54" height="44" rx="22" fill="none" stroke="{ink}" stroke-width="11"/>
          <rect x="-12" y="-22" width="68" height="44" rx="22" fill="none" stroke="{ink}" stroke-width="11"/>
        </g>
        <path d="M0 -76 L0 -36 M-28 -56 L-12 -30 M28 -56 L12 -30 M0 36 L0 76 M-26 56 L-10 32 M26 56 L10 32" stroke="{accent}" stroke-width="6.5" stroke-linecap="round"/>
        """
    elif prop == "compass":
        inner = f"""
        <ellipse cx="0" cy="112" rx="76" ry="12" fill="{ink}" fill-opacity="0.12"/>
        <circle cx="0" cy="0" r="96" fill="{surface}" stroke="{ink}" stroke-width="6"/>
        <circle cx="0" cy="0" r="78" fill="none" stroke="{ink}" stroke-width="2.5" stroke-dasharray="4 10"/>
        <path d="M0 -88 L0 -70 M0 70 L0 88 M-88 0 L-70 0 M70 0 L88 0" stroke="{ink}" stroke-width="5" stroke-linecap="round"/>
        <polygon points="0,-64 18,0 0,14 -18,0" fill="{accent}" stroke="{ink}" stroke-width="4" stroke-linejoin="round"/>
        <polygon points="0,64 18,0 0,-14 -18,0" fill="{surface}" stroke="{ink}" stroke-width="4" stroke-linejoin="round"/>
        <circle cx="0" cy="0" r="9" fill="{ink}"/>
        """
    elif prop == "lightbulb":
        inner = f"""
        <path d="M0 -122 L0 -96 M-84 -86 L-66 -68 M84 -86 L66 -68 M-112 -16 L-86 -16 M112 -16 L86 -16" stroke="{accent}" stroke-width="6" stroke-linecap="round"/>
        <path d="M-42 36 C-68 12 -74 -34 -52 -64 C-26 -96 26 -96 52 -64 C74 -34 68 12 42 36 L34 64 L-34 64 Z" fill="{surface}" stroke="{ink}" stroke-width="6" stroke-linejoin="round"/>
        <circle cx="0" cy="-20" r="36" fill="{accent}" fill-opacity="0.18"/>
        <path d="M-16 64 L-16 10 Q0 -8 16 10 L16 64" fill="none" stroke="{accent}" stroke-width="5" stroke-linecap="round"/>
        <rect x="-32" y="66" width="64" height="16" rx="6" fill="{ink}"/>
        <rect x="-24" y="86" width="48" height="14" rx="6" fill="{ink}"/>
        """
    elif prop == "target_bullseye":
        inner = f"""
        <circle cx="-12" cy="6" r="92" fill="{surface}" stroke="{ink}" stroke-width="6"/>
        <circle cx="-12" cy="6" r="62" fill="{accent}" fill-opacity="0.15" stroke="{ink}" stroke-width="5"/>
        <circle cx="-12" cy="6" r="32" fill="{accent}" stroke="{ink}" stroke-width="4.5"/>
        <circle cx="-12" cy="6" r="10" fill="{surface}"/>
        <line x1="98" y1="-88" x2="-4" y2="0" stroke="{ink}" stroke-width="6.5" stroke-linecap="round"/>
        <polygon points="-10,6 16,-4 4,-18" fill="{ink}"/>
        <path d="M84 -76 L108 -74 M94 -84 L96 -108 M72 -66 L96 -64" stroke="{accent}" stroke-width="5.5" stroke-linecap="round"/>
        """
    elif prop == "phone_distraction":
        inner = f"""
        <rect x="-56" y="-96" width="112" height="196" rx="20" fill="{surface}" stroke="{ink}" stroke-width="6"/>
        <rect x="-42" y="-68" width="84" height="136" rx="8" fill="{bg}" stroke="{ink}" stroke-width="3"/>
        <line x1="-18" y1="-82" x2="18" y2="-82" stroke="{ink}" stroke-width="4.5" stroke-linecap="round"/>
        <circle cx="0" cy="84" r="7" fill="{ink}"/>
        <g transform="translate(68, -68)">
          <rect x="-32" y="-22" width="64" height="40" rx="12" fill="{accent}" stroke="{ink}" stroke-width="4"/>
          <circle cx="-12" cy="-2" r="4" fill="{surface}"/><circle cx="0" cy="-2" r="4" fill="{surface}"/><circle cx="12" cy="-2" r="4" fill="{surface}"/>
        </g>
        <g transform="translate(-74, -22)">
          <circle cx="0" cy="0" r="24" fill="{accent}" stroke="{ink}" stroke-width="4"/>
          <path d="M0 -10 L0 3 M0 10 L0 12" stroke="{surface}" stroke-width="5" stroke-linecap="round"/>
        </g>
        <g transform="translate(74, 24)">
          <circle cx="0" cy="0" r="22" fill="{surface}" stroke="{accent}" stroke-width="4.5"/>
          <path d="M-8 0 L0 -8 L8 0 L0 10 Z" fill="{accent}"/>
        </g>
        """
    elif prop == "clock_time":
        inner = f"""
        <ellipse cx="0" cy="110" rx="76" ry="12" fill="{ink}" fill-opacity="0.12"/>
        <circle cx="0" cy="0" r="94" fill="{surface}" stroke="{ink}" stroke-width="6.5"/>
        <path d="M0 -78 L0 -64 M0 64 L0 78 M-78 0 L-64 0 M64 0 L78 0" stroke="{ink}" stroke-width="5" stroke-linecap="round"/>
        <path d="M0 0 L0 -54 M0 0 L44 22" stroke="{ink}" stroke-width="7" stroke-linecap="round"/>
        <path d="M0 -64 A64 64 0 0 1 58 28" fill="none" stroke="{accent}" stroke-width="7" stroke-linecap="round"/>
        <circle cx="0" cy="0" r="10" fill="{accent}" stroke="{ink}" stroke-width="3.5"/>
        """
    elif prop == "stoic_scroll":
        inner = f"""
        <rect x="-78" y="-76" width="156" height="156" rx="10" fill="{surface}" stroke="{ink}" stroke-width="5.5"/>
        <rect x="-92" y="-92" width="184" height="24" rx="12" fill="{surface}" stroke="{ink}" stroke-width="5.5"/>
        <rect x="-92" y="68" width="184" height="24" rx="12" fill="{surface}" stroke="{ink}" stroke-width="5.5"/>
        <line x1="-46" y1="-34" x2="46" y2="-34" stroke="{ink}" stroke-width="5" stroke-linecap="round"/>
        <line x1="-46" y1="-8" x2="46" y2="-8" stroke="{ink}" stroke-width="5" stroke-linecap="round"/>
        <line x1="-46" y1="18" x2="22" y2="18" stroke="{ink}" stroke-width="5" stroke-linecap="round"/>
        <circle cx="44" cy="36" r="20" fill="{accent}" stroke="{ink}" stroke-width="4"/>
        <path d="M36 36 L42 42 L54 30" fill="none" stroke="{surface}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
        """
    elif prop == "temple_pillar":
        inner = f"""
        <ellipse cx="0" cy="110" rx="92" ry="12" fill="{ink}" fill-opacity="0.12"/>
        <rect x="-76" y="84" width="152" height="20" rx="5" fill="{surface}" stroke="{ink}" stroke-width="5.5"/>
        <rect x="-62" y="66" width="124" height="18" rx="4" fill="{surface}" stroke="{ink}" stroke-width="5"/>
        <rect x="-48" y="-66" width="96" height="132" fill="{surface}" stroke="{ink}" stroke-width="5.5"/>
        <line x1="-22" y1="-56" x2="-22" y2="56" stroke="{ink}" stroke-width="3.5" stroke-linecap="round"/>
        <line x1="0" y1="-56" x2="0" y2="56" stroke="{ink}" stroke-width="3.5" stroke-linecap="round"/>
        <line x1="22" y1="-56" x2="22" y2="56" stroke="{ink}" stroke-width="3.5" stroke-linecap="round"/>
        <rect x="-78" y="-92" width="156" height="26" rx="6" fill="{accent}" fill-opacity="0.18" stroke="{ink}" stroke-width="5.5"/>
        """
    elif prop == "stairs_growth":
        inner = f"""
        <ellipse cx="0" cy="108" rx="116" ry="12" fill="{ink}" fill-opacity="0.12"/>
        <path d="M-108 100 L-108 58 L-54 58 L-54 16 L0 16 L0 -26 L54 -26 L54 -68 L108 -68 L108 100 Z" fill="{surface}" stroke="{ink}" stroke-width="5.5" stroke-linejoin="round"/>
        <path d="M-96 24 Q-16 -24 88 -98" fill="none" stroke="{accent}" stroke-width="7.5" stroke-linecap="round"/>
        <polygon points="104,-108 72,-102 88,-82" fill="{accent}"/>
        """
    elif prop == "mirror_self":
        inner = f"""
        <ellipse cx="0" cy="108" rx="76" ry="12" fill="{ink}" fill-opacity="0.12"/>
        <rect x="-70" y="-96" width="140" height="194" rx="70" fill="{surface}" stroke="{ink}" stroke-width="6.5"/>
        <rect x="-54" y="-80" width="108" height="162" rx="54" fill="{accent}" fill-opacity="0.12" stroke="{accent}" stroke-width="4"/>
        <line x1="-26" y1="-44" x2="14" y2="-8" stroke="{surface}" stroke-width="7" stroke-linecap="round"/>
        <line x1="-24" y1="-12" x2="4" y2="14" stroke="{surface}" stroke-width="5" stroke-linecap="round"/>
        <circle cx="0" cy="24" r="24" fill="{surface}" stroke="{ink}" stroke-width="4.5"/>
        """
    elif prop == "brick_wall":
        inner = f"""
        <rect x="-106" y="-44" width="212" height="142" rx="8" fill="{surface}" stroke="{ink}" stroke-width="5.5"/>
        <line x1="-106" y1="4" x2="106" y2="4" stroke="{ink}" stroke-width="4.5"/>
        <line x1="-106" y1="52" x2="106" y2="52" stroke="{ink}" stroke-width="4.5"/>
        <line x1="-36" y1="-44" x2="-36" y2="4" stroke="{ink}" stroke-width="4.5"/>
        <line x1="36" y1="-44" x2="36" y2="4" stroke="{ink}" stroke-width="4.5"/>
        <line x1="0" y1="4" x2="0" y2="52" stroke="{ink}" stroke-width="4.5"/>
        <line x1="-70" y1="4" x2="-70" y2="52" stroke="{ink}" stroke-width="4.5"/>
        <line x1="70" y1="4" x2="70" y2="52" stroke="{ink}" stroke-width="4.5"/>
        <line x1="-36" y1="52" x2="-36" y2="98" stroke="{ink}" stroke-width="4.5"/>
        <line x1="36" y1="52" x2="36" y2="98" stroke="{ink}" stroke-width="4.5"/>
        <path d="M-112 -64 Q0 -132 104 -64" fill="none" stroke="{accent}" stroke-width="7" stroke-linecap="round"/>
        <polygon points="122,-54 90,-54 102,-78" fill="{accent}"/>
        """
    elif prop == "flame_forge":
        inner = f"""
        <ellipse cx="0" cy="108" rx="76" ry="12" fill="{ink}" fill-opacity="0.12"/>
        <path d="M0 -106 C48 -58 76 -12 64 46 C54 88 26 102 0 102 C-34 102 -68 78 -68 32 C-68 -18 -26 -54 0 -106 Z" fill="{accent}" fill-opacity="0.22" stroke="{ink}" stroke-width="6" stroke-linejoin="round"/>
        <path d="M0 -42 C24 -12 36 16 28 52 C22 76 10 86 0 86 C-18 86 -34 72 -34 44 C-34 18 -14 -10 0 -42 Z" fill="{accent}" stroke="{ink}" stroke-width="4.5" stroke-linejoin="round"/>
        <circle cx="0" cy="54" r="12" fill="{surface}"/>
        """
    elif prop == "anchor_waves":
        inner = f"""
        <path d="M-126 78 Q-92 52 -58 78 Q-24 104 10 78 Q44 52 78 78 Q106 96 128 78" fill="none" stroke="{accent}" stroke-width="6.5" stroke-linecap="round"/>
        <path d="M-114 104 Q-80 82 -46 104 Q-12 124 22 104 Q56 82 90 104" fill="none" stroke="{accent}" stroke-width="4.5" stroke-linecap="round" stroke-opacity="0.6"/>
        <circle cx="0" cy="-78" r="18" fill="{surface}" stroke="{ink}" stroke-width="6"/>
        <line x1="0" y1="-60" x2="0" y2="66" stroke="{ink}" stroke-width="8" stroke-linecap="round"/>
        <line x1="-42" y1="-34" x2="42" y2="-34" stroke="{ink}" stroke-width="7" stroke-linecap="round"/>
        <path d="M-64 16 C-62 56 -32 72 0 72 C32 72 62 56 64 16" fill="none" stroke="{ink}" stroke-width="8" stroke-linecap="round"/>
        <polygon points="-68,8 -80,30 -50,26" fill="{ink}"/>
        <polygon points="68,8 80,30 50,26" fill="{ink}"/>
        """
    elif prop == "heart_calm":
        inner = f"""
        <circle cx="0" cy="0" r="100" fill="{accent}" fill-opacity="0.08" stroke="{accent}" stroke-width="4"/>
        <path d="M0 58 C-78 8 -86 -54 -44 -68 C-20 -76 -4 -58 0 -44 C4 -58 20 -76 44 -68 C86 -54 78 8 0 58 Z" fill="{surface}" stroke="{ink}" stroke-width="6" stroke-linejoin="round"/>
        <path d="M-38 -2 L-16 -2 L-6 -24 L8 18 L18 -2 L38 -2" fill="none" stroke="{accent}" stroke-width="5.5" stroke-linecap="round" stroke-linejoin="round"/>
        """
    elif prop == "laurel_crown":
        inner = f"""
        <path d="M-16 88 C-86 68 -104 -18 -54 -76" fill="none" stroke="{ink}" stroke-width="6" stroke-linecap="round"/>
        <path d="M16 88 C86 68 104 -18 54 -76" fill="none" stroke="{ink}" stroke-width="6" stroke-linecap="round"/>
        <ellipse cx="-78" cy="18" rx="18" ry="9" transform="rotate(-32 -78 18)" fill="{accent}" fill-opacity="0.28" stroke="{ink}" stroke-width="3.5"/>
        <ellipse cx="-82" cy="-22" rx="18" ry="9" transform="rotate(-6 -82 -22)" fill="{accent}" fill-opacity="0.28" stroke="{ink}" stroke-width="3.5"/>
        <ellipse cx="-62" cy="-58" rx="16" ry="8" transform="rotate(28 -62 -58)" fill="{accent}" fill-opacity="0.28" stroke="{ink}" stroke-width="3.5"/>
        <ellipse cx="78" cy="18" rx="18" ry="9" transform="rotate(32 78 18)" fill="{accent}" fill-opacity="0.28" stroke="{ink}" stroke-width="3.5"/>
        <ellipse cx="82" cy="-22" rx="18" ry="9" transform="rotate(6 82 -22)" fill="{accent}" fill-opacity="0.28" stroke="{ink}" stroke-width="3.5"/>
        <ellipse cx="62" cy="-58" rx="16" ry="8" transform="rotate(-28 62 -58)" fill="{accent}" fill-opacity="0.28" stroke="{ink}" stroke-width="3.5"/>
        <polygon points="0,-54 14,-16 54,-16 22,8 34,46 0,22 -34,46 -22,8 -54,-16 -14,-16" fill="{accent}" stroke="{ink}" stroke-width="4.5" stroke-linejoin="round"/>
        """
    elif prop == "checklist_board":
        inner = f"""
        <rect x="-78" y="-92" width="156" height="192" rx="16" fill="{surface}" stroke="{ink}" stroke-width="5.5"/>
        <rect x="-34" y="-108" width="68" height="28" rx="8" fill="{accent}" stroke="{ink}" stroke-width="4.5"/>
        <circle cx="-44" cy="-34" r="14" fill="{accent}" fill-opacity="0.2" stroke="{accent}" stroke-width="4"/>
        <path d="M-50 -34 L-45 -29 L-36 -39" fill="none" stroke="{accent}" stroke-width="4" stroke-linecap="round"/>
        <line x1="-16" y1="-34" x2="52" y2="-34" stroke="{ink}" stroke-width="6" stroke-linecap="round"/>
        <circle cx="-44" cy="16" r="14" fill="{accent}" fill-opacity="0.2" stroke="{accent}" stroke-width="4"/>
        <path d="M-50 16 L-45 21 L-36 11" fill="none" stroke="{accent}" stroke-width="4" stroke-linecap="round"/>
        <line x1="-16" y1="16" x2="46" y2="16" stroke="{ink}" stroke-width="6" stroke-linecap="round"/>
        <circle cx="-44" cy="66" r="14" fill="{accent}" fill-opacity="0.2" stroke="{accent}" stroke-width="4"/>
        <path d="M-50 66 L-45 71 L-36 61" fill="none" stroke="{accent}" stroke-width="4" stroke-linecap="round"/>
        <line x1="-16" y1="66" x2="36" y2="66" stroke="{ink}" stroke-width="6" stroke-linecap="round"/>
        """
    elif prop == "crowd_chatter":
        inner = f"""
        <g opacity="0.9">
          <circle cx="-68" cy="10" r="24" fill="{surface}" stroke="{ink}" stroke-width="5"/>
          <path d="M-104 92 C-104 54 -32 54 -32 92 Z" fill="{surface}" stroke="{ink}" stroke-width="5"/>
          <circle cx="68" cy="10" r="24" fill="{surface}" stroke="{ink}" stroke-width="5"/>
          <path d="M32 92 C32 54 104 54 104 92 Z" fill="{surface}" stroke="{ink}" stroke-width="5"/>
          <circle cx="0" cy="-4" r="28" fill="{surface}" stroke="{ink}" stroke-width="5.5"/>
          <path d="M-42 96 C-42 50 42 50 42 96 Z" fill="{surface}" stroke="{ink}" stroke-width="5.5"/>
        </g>
        <rect x="-86" y="-92" width="76" height="38" rx="12" fill="{accent}" fill-opacity="0.2" stroke="{accent}" stroke-width="4"/>
        <line x1="-68" y1="-73" x2="-28" y2="-73" stroke="{accent}" stroke-width="4.5" stroke-linecap="round"/>
        <rect x="14" y="-84" width="76" height="38" rx="12" fill="{surface}" stroke="{ink}" stroke-width="4"/>
        <line x1="32" y1="-65" x2="72" y2="-65" stroke="{ink}" stroke-width="4.5" stroke-linecap="round"/>
        """
    elif prop == "battery_power":
        inner = f"""
        <rect x="-92" y="-50" width="172" height="100" rx="16" fill="{surface}" stroke="{ink}" stroke-width="6"/>
        <rect x="80" y="-22" width="18" height="44" rx="6" fill="{ink}"/>
        <rect x="-76" y="-34" width="42" height="68" rx="6" fill="{accent}"/>
        <rect x="-24" y="-34" width="42" height="68" rx="6" fill="{accent}" fill-opacity="0.72"/>
        <rect x="28" y="-34" width="36" height="68" rx="6" fill="{accent}" fill-opacity="0.35"/>
        """
    elif prop == "key_padlock":
        inner = f"""
        <path d="M-44 -20 L-44 -58 C-44 -90 44 -90 44 -58 L44 -20" fill="none" stroke="{ink}" stroke-width="9" stroke-linecap="round"/>
        <rect x="-68" y="-24" width="136" height="114" rx="18" fill="{surface}" stroke="{ink}" stroke-width="6"/>
        <circle cx="0" cy="24" r="16" fill="{accent}"/>
        <rect x="-6" y="34" width="12" height="28" rx="4" fill="{accent}"/>
        """
    elif prop == "crossroads":
        inner = f"""
        <ellipse cx="0" cy="108" rx="68" ry="12" fill="{ink}" fill-opacity="0.12"/>
        <rect x="-10" y="-88" width="20" height="196" rx="6" fill="{surface}" stroke="{ink}" stroke-width="5.5"/>
        <polygon points="10,-64 -84,-64 -108,-42 -84,-20 10,-20" fill="{surface}" stroke="{ink}" stroke-width="5" stroke-linejoin="round"/>
        <polygon points="-10,-2 84,-2 108,20 84,42 -10,42" fill="{accent}" fill-opacity="0.22" stroke="{accent}" stroke-width="5.5" stroke-linejoin="round"/>
        <path d="M18 20 L66 20 M54 10 L68 20 L54 30" fill="none" stroke="{accent}" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
        """
    elif prop == "growing_tree":
        inner = f"""
        <ellipse cx="0" cy="108" rx="92" ry="12" fill="{ink}" fill-opacity="0.12"/>
        <path d="M-12 104 L-8 14 L8 14 L12 104 Z" fill="{surface}" stroke="{ink}" stroke-width="5.5"/>
        <path d="M-12 104 Q-44 106 -64 114 M12 104 Q44 106 64 114" fill="none" stroke="{ink}" stroke-width="4.5" stroke-linecap="round"/>
        <circle cx="0" cy="-36" r="56" fill="{accent}" fill-opacity="0.18" stroke="{ink}" stroke-width="5.5"/>
        <circle cx="-46" cy="-4" r="38" fill="{surface}" stroke="{ink}" stroke-width="5"/>
        <circle cx="46" cy="-4" r="38" fill="{surface}" stroke="{ink}" stroke-width="5"/>
        <path d="M0 16 L0 -44 M0 -8 L-28 -26 M0 -16 L28 -32" stroke="{ink}" stroke-width="4.5" stroke-linecap="round"/>
        """
    elif prop == "mask_duality":
        inner = f"""
        <g transform="translate(-44, 14) rotate(-14)">
          <path d="M-46 -56 Q0 -70 46 -56 L42 18 Q0 64 -42 18 Z" fill="{surface}" stroke="{ink}" stroke-width="5.5" stroke-linejoin="round"/>
          <path d="M-24 -14 L-8 -8 M24 -14 L8 -8" stroke="{ink}" stroke-width="4.5" stroke-linecap="round"/>
          <path d="M-18 24 Q0 10 18 24" fill="none" stroke="{ink}" stroke-width="4.5" stroke-linecap="round"/>
        </g>
        <g transform="translate(46, -12) rotate(10)">
          <path d="M-46 -56 Q0 -70 46 -56 L42 18 Q0 64 -42 18 Z" fill="{accent}" fill-opacity="0.18" stroke="{accent}" stroke-width="5.5" stroke-linejoin="round"/>
          <circle cx="-16" cy="-12" r="4.5" fill="{ink}"/>
          <circle cx="16" cy="-12" r="4.5" fill="{ink}"/>
          <path d="M-16 18 Q0 32 16 18" fill="none" stroke="{ink}" stroke-width="4.5" stroke-linecap="round"/>
        </g>
        """
    else:  # speech_calm
        inner = f"""
        <rect x="-98" y="-66" width="196" height="118" rx="22" fill="{surface}" stroke="{ink}" stroke-width="5.5"/>
        <polygon points="-44,52 -74,88 -12,52" fill="{surface}" stroke="{ink}" stroke-width="5.5" stroke-linejoin="round"/>
        <path d="M-58 -8 Q-36 -28 -14 -8 Q8 12 30 -8 Q52 -28 66 -8" fill="none" stroke="{accent}" stroke-width="6" stroke-linecap="round"/>
        <line x1="-54" y1="22" x2="38" y2="22" stroke="{ink}" stroke-width="5" stroke-linecap="round"/>
        """

    return f'<g transform="translate({x}, {y}) scale({scale})">{inner}</g>'


def _render_overlay_effect(effect: str, x: int, y: int, theme: StudioThemeColors) -> str:
    accent = theme.accent_color
    surface = theme.surface_fill
    if effect == "big_x_crossout":
        return f"""<g transform="translate({x}, {y})">
        <circle cx="0" cy="0" r="64" fill="{accent}" fill-opacity="0.12"/>
        <path d="M-46 -46 L46 46 M46 -46 L-46 46" stroke="{accent}" stroke-width="14" stroke-linecap="round"/>
      </g>"""
    if effect == "checkmark_badge":
        return f"""<g transform="translate({x}, {y})">
        <circle cx="0" cy="0" r="38" fill="{accent}"/>
        <path d="M-16 1 L-4 13 L18 -12" fill="none" stroke="{surface}" stroke-width="7.5" stroke-linecap="round" stroke-linejoin="round"/>
      </g>"""
    if effect == "curved_arrow_right":
        return f"""<g transform="translate({x}, {y})">
        <path d="M-78 16 Q0 -34 72 8" fill="none" stroke="{accent}" stroke-width="9" stroke-linecap="round"/>
        <polygon points="94,16 56,-8 64,28" fill="{accent}"/>
      </g>"""
    if effect == "upward_growth_arrow":
        return f"""<g transform="translate({x}, {y})">
        <path d="M-54 46 L48 -42" stroke="{accent}" stroke-width="9" stroke-linecap="round"/>
        <polygon points="64,-54 28,-46 50,-22" fill="{accent}"/>
      </g>"""
    if effect == "shield_aura":
        return f"""<g transform="translate({x}, {y})">
        <circle cx="0" cy="0" r="145" fill="none" stroke="{accent}" stroke-width="3.5" stroke-dasharray="14 10" stroke-opacity="0.55"/>
      </g>"""
    if effect == "spark_emphasis":
        return f"""<g transform="translate({x}, {y})">
        <path d="M0 -34 L0 -14 M0 14 L0 34 M-34 0 L-14 0 M14 0 L34 0 M-22 -22 L-10 -10 M22 22 L10 10 M22 -22 L10 -10 M-22 22 L-10 10" stroke="{accent}" stroke-width="5" stroke-linecap="round"/>
      </g>"""
    return ""


def render_studio_shot_svg(
    blueprint: StudioShotBlueprint,
    theme: StudioThemeColors,
    aspect_ratio: str = "16:9",
) -> str:
    """Dựng 1 khung hình Studio Vector SVG sắc nét (đồng nhất 100% với Local Preview)."""
    is_vertical = aspect_ratio == "9:16"
    vb_w = 720 if is_vertical else 1280
    vb_h = 1280 if is_vertical else 720

    bg = theme.bg_color
    ink = theme.ink_color
    accent = theme.accent_color
    surface = theme.surface_fill
    cx = round(vb_w / 2)

    backdrop_decor = f"""
    <rect width="{vb_w}" height="{vb_h}" fill="{bg}"/>
    <circle cx="{round(vb_w * 0.14)}" cy="{round(vb_h * 0.18)}" r="{140 if is_vertical else 190}" fill="{accent}" fill-opacity="0.05"/>
    <circle cx="{round(vb_w * 0.86)}" cy="{round(vb_h * 0.78)}" r="{160 if is_vertical else 210}" fill="{ink}" fill-opacity="0.04"/>
    """

    header_clean = re.sub(r"[&<>]", " ", str(blueprint.chapter_header or "")).strip()[:48]
    header_svg = ""
    if header_clean:
        header_svg = f"""
    <g id="studio-header">
      <rect x="{cx - 320}" y="22" width="640" height="50" rx="25" fill="{surface}" stroke="{ink}" stroke-width="3"/>
      <text x="{cx}" y="55" text-anchor="middle" font-family="{FONT_FAMILY}" font-size="24" font-weight="700" fill="{ink}">{_escape_xml(header_clean)}</text>
    </g>"""

    beat_counter_svg = ""
    if blueprint.beat_index is not None and blueprint.total_beats is not None and blueprint.total_beats > 1:
        beat_counter_svg = (
            f'<rect x="{vb_w - 118}" y="24" width="84" height="36" rx="18" fill="{accent}" fill-opacity="0.14" stroke="{accent}" stroke-width="2.5"/>'
            f'<text x="{vb_w - 76}" y="48" text-anchor="middle" font-family="{FONT_FAMILY}" font-size="18" font-weight="800" fill="{accent}">{blueprint.beat_index + 1}/{blueprint.total_beats}</text>'
        )

    stage_x = 44 if is_vertical else 68
    stage_y = 94 if header_clean else 62
    stage_w = vb_w - stage_x * 2
    stage_h = 790 if is_vertical else 482
    stage_mid_x = round(stage_x + stage_w / 2)
    stage_mid_y = round(stage_y + stage_h / 2)

    stage_frame_svg = f"""
    <rect x="{stage_x + 8}" y="{stage_y + 8}" width="{stage_w}" height="{stage_h}" rx="28" fill="{ink}" fill-opacity="0.08"/>
    <rect x="{stage_x}" y="{stage_y}" width="{stage_w}" height="{stage_h}" rx="28" fill="{surface}" stroke="{ink}" stroke-width="4"/>
    <line x1="{stage_x + 42}" y1="{stage_y + stage_h - 54}" x2="{stage_x + stage_w - 42}" y2="{stage_y + stage_h - 54}" stroke="{ink}" stroke-width="2.5" stroke-opacity="0.18" stroke-linecap="round"/>
    """

    char_scale = 0.96 if is_vertical else 1.04
    prop_scale = 0.94 if is_vertical else 1.06

    beat1_svg = ""
    beat2_svg = ""
    beat3_svg = ""

    comp = blueprint.composition
    if comp == "center_metaphor":
        beat1_svg = _render_studio_prop(
            blueprint.primary_prop, stage_mid_x, stage_mid_y - 4, 1.24 if is_vertical else 1.38, theme
        )
        if blueprint.overlay_effect != "none":
            ov_x = stage_mid_x if blueprint.overlay_effect == "shield_aura" else stage_mid_x + (145 if is_vertical else 225)
            ov_y = stage_mid_y - 4 if blueprint.overlay_effect == "shield_aura" else stage_mid_y - 95
            beat2_svg = _render_overlay_effect(blueprint.overlay_effect, ov_x, ov_y, theme)
        if blueprint.right_badge:
            beat3_svg = (
                f'<rect x="{stage_mid_x - 165}" y="{stage_y + 26}" width="330" height="44" rx="22" fill="{accent}" fill-opacity="0.14" stroke="{accent}" stroke-width="3"/>'
                f'<text x="{stage_mid_x}" y="{stage_y + 56}" text-anchor="middle" font-family="{FONT_FAMILY}" font-size="22" font-weight="800" fill="{accent}">{_escape_xml(blueprint.right_badge)}</text>'
            )
        else:
            beat3_svg = (
                f'<circle cx="{stage_mid_x - 245}" cy="{stage_y + 56}" r="10" fill="{accent}" fill-opacity="0.28"/>'
                f'<circle cx="{stage_mid_x + 245}" cy="{stage_y + 56}" r="10" fill="{accent}" fill-opacity="0.28"/>'
            )

    elif comp == "prop_left_character_right":
        left_x = stage_mid_x if is_vertical else stage_x + round(stage_w * 0.30)
        left_y = stage_y + round(stage_h * 0.28) if is_vertical else stage_mid_y - 8
        right_x = stage_mid_x if is_vertical else stage_x + round(stage_w * 0.72)
        right_y = stage_y + round(stage_h * 0.72) if is_vertical else stage_mid_y + 24
        beat1_svg = _render_studio_prop(blueprint.primary_prop, left_x, left_y, prop_scale, theme)
        ov_eff = "curved_arrow_right" if blueprint.overlay_effect == "none" else blueprint.overlay_effect
        ov_x = left_x if blueprint.overlay_effect == "big_x_crossout" else stage_mid_x
        ov_y = left_y if blueprint.overlay_effect == "big_x_crossout" else stage_mid_y - 12
        beat2_svg = _render_overlay_effect(ov_eff, ov_x, ov_y, theme)
        beat3_svg = _render_studio_character(
            right_x, right_y, blueprint.character_pose, blueprint.character_expression, theme, scale=char_scale, flip_x=not is_vertical
        )

    elif comp == "split_comparison":
        panel_gap = 36
        panel_w = stage_w - 64 if is_vertical else round((stage_w - 96 - panel_gap) / 2)
        panel_h = round((stage_h - 112) / 2) if is_vertical else stage_h - 76
        left_px = stage_x + 32 if is_vertical else stage_x + 48
        left_py = stage_y + 38
        right_px = stage_x + 32 if is_vertical else left_px + panel_w + panel_gap
        right_py = left_py + panel_h + 34 if is_vertical else stage_y + 38
        left_mid_x = round(left_px + panel_w / 2)
        left_mid_y = round(left_py + panel_h / 2)
        right_mid_x = round(right_px + panel_w / 2)
        right_mid_y = round(right_py + panel_h / 2)
        left_tag = blueprint.left_badge or "Phản ứng cũ"
        right_tag = blueprint.right_badge or "Bản lĩnh mới"

        beat1_svg = f"""
        <rect x="{left_px}" y="{left_py}" width="{panel_w}" height="{panel_h}" rx="20" fill="{bg}" stroke="{ink}" stroke-width="3.5" stroke-dasharray="10 6"/>
        <rect x="{left_mid_x - 120}" y="{left_py + 18}" width="240" height="40" rx="20" fill="{surface}" stroke="{ink}" stroke-width="3"/>
        <text x="{left_mid_x}" y="{left_py + 45}" text-anchor="middle" font-family="{FONT_FAMILY}" font-size="20" font-weight="700" fill="{ink}">{_escape_xml(left_tag)}</text>
        {_render_studio_prop(blueprint.primary_prop, left_mid_x, left_mid_y + 22, 0.72 if is_vertical else 0.88, theme)}
        """
        beat2_svg = f"""
        {_render_overlay_effect("big_x_crossout", left_mid_x + round(panel_w * 0.28), left_py + 88, theme)}
        <circle cx="{stage_mid_x}" cy="{stage_mid_y}" r="34" fill="{accent}" stroke="{surface}" stroke-width="5"/>
        <path d="M{stage_mid_x - 12} {stage_mid_y} L{stage_mid_x + 12} {stage_mid_y} M{stage_mid_x + 2} {stage_mid_y - 10} L{stage_mid_x + 14} {stage_mid_y} L{stage_mid_x + 2} {stage_mid_y + 10}" fill="none" stroke="{surface}" stroke-width="5.5" stroke-linecap="round" stroke-linejoin="round"/>
        """
        beat3_svg = f"""
        <rect x="{right_px}" y="{right_py}" width="{panel_w}" height="{panel_h}" rx="20" fill="{accent}" fill-opacity="0.08" stroke="{accent}" stroke-width="4"/>
        <rect x="{right_mid_x - 120}" y="{right_py + 18}" width="240" height="40" rx="20" fill="{accent}"/>
        <text x="{right_mid_x}" y="{right_py + 45}" text-anchor="middle" font-family="{FONT_FAMILY}" font-size="20" font-weight="800" fill="{surface}">{_escape_xml(right_tag)}</text>
        {_render_studio_character(right_mid_x, right_mid_y + 34, blueprint.character_pose, blueprint.character_expression, theme, scale=0.72 if is_vertical else 0.84)}
        """

    elif comp == "cause_effect_flow":
        left_x = stage_mid_x if is_vertical else stage_x + round(stage_w * 0.24)
        left_y = stage_y + round(stage_h * 0.24) if is_vertical else stage_mid_y + 18
        right_x = stage_mid_x if is_vertical else stage_x + round(stage_w * 0.76)
        right_y = stage_y + round(stage_h * 0.74) if is_vertical else stage_mid_y - 4
        beat1_svg = _render_studio_character(
            left_x, left_y, blueprint.character_pose, blueprint.character_expression, theme, scale=char_scale * 0.96
        )
        mid_label = blueprint.left_badge or "Chuyển hóa"
        beat2_svg = f"""
        {_render_overlay_effect("curved_arrow_right", stage_mid_x, stage_mid_y + 10, theme)}
        <rect x="{stage_mid_x - 106}" y="{stage_mid_y - 82}" width="212" height="42" rx="21" fill="{accent}" fill-opacity="0.14" stroke="{accent}" stroke-width="3"/>
        <text x="{stage_mid_x}" y="{stage_mid_y - 54}" text-anchor="middle" font-family="{FONT_FAMILY}" font-size="21" font-weight="800" fill="{accent}">{_escape_xml(mid_label)}</text>
        """
        beat3_svg = _render_studio_prop(
            blueprint.secondary_prop or blueprint.primary_prop, right_x, right_y, prop_scale, theme
        )

    elif comp == "two_characters_interaction":
        left_x = stage_mid_x - 135 if is_vertical else stage_x + round(stage_w * 0.23)
        right_x = stage_mid_x + 135 if is_vertical else stage_x + round(stage_w * 0.77)
        char_y = stage_mid_y + 26
        beat1_svg = _render_studio_character(
            left_x,
            char_y,
            blueprint.secondary_pose or "pointing_accuse",
            blueprint.secondary_expression or "angry",
            theme,
            scale=0.82 if is_vertical else 0.96,
            accent_tie=False,
        )
        beat2_svg = _render_studio_prop(
            blueprint.primary_prop, stage_mid_x, stage_mid_y - 38, 0.62 if is_vertical else 0.84, theme
        )
        beat3_svg = _render_studio_character(
            right_x,
            char_y,
            blueprint.character_pose,
            blueprint.character_expression,
            theme,
            scale=0.82 if is_vertical else 0.98,
            flip_x=True,
            accent_tie=True,
        )

    elif comp == "character_on_pedestal":
        pedestal_y = stage_y + stage_h - 120
        beat1_svg = f"""
        <polygon points="{stage_mid_x - 210},{stage_y + stage_h - 52} {stage_mid_x - 148},{pedestal_y} {stage_mid_x + 148},{pedestal_y} {stage_mid_x + 210},{stage_y + stage_h - 52}" fill="{bg}" stroke="{ink}" stroke-width="5" stroke-linejoin="round"/>
        <line x1="{stage_mid_x - 110}" y1="{pedestal_y + 28}" x2="{stage_mid_x + 110}" y2="{pedestal_y + 28}" stroke="{accent}" stroke-width="5" stroke-linecap="round"/>
        """
        ov_eff = "shield_aura" if blueprint.overlay_effect == "none" else blueprint.overlay_effect
        beat2_svg = _render_overlay_effect(ov_eff, stage_mid_x, stage_mid_y - 26, theme)
        beat3_svg = (
            _render_studio_character(
                stage_mid_x,
                pedestal_y - 148,
                blueprint.character_pose,
                blueprint.character_expression,
                theme,
                scale=0.90 if is_vertical else 0.94,
            )
            + _render_studio_prop(
                blueprint.primary_prop,
                stage_mid_x + (175 if is_vertical else 275),
                stage_mid_y - 28,
                0.56 if is_vertical else 0.72,
                theme,
            )
        )

    elif comp == "checklist_steps":
        char_x = stage_mid_x if is_vertical else stage_x + round(stage_w * 0.22)
        char_y = stage_y + 195 if is_vertical else stage_mid_y + 24
        cards_x = stage_x + 42 if is_vertical else stage_x + round(stage_w * 0.43)
        cards_w = stage_w - 84 if is_vertical else round(stage_w * 0.52)
        card_start_y = stage_y + 395 if is_vertical else stage_y + 62
        step_labels = blueprint.step_items or [
            blueprint.left_badge or "1. Dừng lại 3 giây quan sát",
            blueprint.right_badge or "2. Tách sự thật khỏi cảm xúc",
            blueprint.caption or "3. Hành động điềm tĩnh, dứt khoát",
        ]
        beat1_svg = _render_studio_character(
            char_x, char_y, blueprint.character_pose, blueprint.character_expression, theme, scale=0.80 if is_vertical else 0.95
        )
        if not is_vertical:
            beat2_svg = (
                f'<path d="M{char_x + 115} {stage_mid_y - 10} L{cards_x - 24} {card_start_y + 46} '
                f'M{char_x + 115} {stage_mid_y - 10} L{cards_x - 24} {card_start_y + 174} '
                f'M{char_x + 115} {stage_mid_y - 10} L{cards_x - 24} {card_start_y + 302}" '
                f'stroke="{accent}" stroke-width="5" stroke-linecap="round" stroke-dasharray="10 8"/>'
            )
        rows: List[str] = []
        for s_idx, label in enumerate(step_labels[:3]):
            row_y = card_start_y + s_idx * 124
            clean_label = re.sub(r"^\d+\.\s*", "", label)
            rows.append(
                f'<rect x="{cards_x}" y="{row_y}" width="{cards_w}" height="96" rx="18" fill="{bg}" stroke="{ink}" stroke-width="4"/>'
                f'<circle cx="{cards_x + 46}" cy="{row_y + 48}" r="24" fill="{accent}"/>'
                f'<text x="{cards_x + 46}" y="{row_y + 57}" text-anchor="middle" font-family="{FONT_FAMILY}" font-size="24" font-weight="800" fill="{surface}">{s_idx + 1}</text>'
                f'<text x="{cards_x + 90}" y="{row_y + 57}" text-anchor="start" font-family="{FONT_FAMILY}" font-size="24" font-weight="700" fill="{ink}">{_escape_xml(clean_label[:30])}</text>'
            )
        beat3_svg = "\n".join(rows)

    else:  # character_left_prop_right
        left_x = stage_mid_x if is_vertical else stage_x + round(stage_w * 0.28)
        left_y = stage_y + round(stage_h * 0.30) if is_vertical else stage_mid_y + 24
        right_x = stage_mid_x if is_vertical else stage_x + round(stage_w * 0.72)
        right_y = stage_y + round(stage_h * 0.72) if is_vertical else stage_mid_y - 8
        beat1_svg = _render_studio_character(
            left_x, left_y, blueprint.character_pose, blueprint.character_expression, theme, scale=char_scale
        )
        if blueprint.overlay_effect != "none":
            ov_x = left_x if blueprint.overlay_effect == "big_x_crossout" else stage_mid_x
            ov_y = left_y - 22 if blueprint.overlay_effect == "big_x_crossout" else stage_mid_y - 10
            beat2_svg = _render_overlay_effect(blueprint.overlay_effect, ov_x, ov_y, theme)
        else:
            beat2_svg = f'<path d="M{left_x + 115} {stage_mid_y} L{right_x - 150} {stage_mid_y}" stroke="{accent}" stroke-width="5" stroke-dasharray="10 8" stroke-linecap="round"/>'
        beat3_svg = _render_studio_prop(blueprint.primary_prop, right_x, right_y, prop_scale, theme)

    caption_box_y = stage_y + stage_h + 22
    caption_box_h = vb_h - caption_box_y - 24
    caption_lines = _wrap_text_lines(blueprint.caption, 24 if is_vertical else 38, 2)
    caption_font_size = (30 if is_vertical else 32) if len(caption_lines) > 1 else (34 if is_vertical else 38)
    caption_text_start_y = (
        caption_box_y + round(caption_box_h / 2) - 6
        if len(caption_lines) > 1
        else caption_box_y + round(caption_box_h / 2) + 12
    )

    caption_box_svg = f"""
    <g id="studio-caption">
      <rect x="{stage_x}" y="{caption_box_y}" width="{stage_w}" height="{caption_box_h}" rx="20" fill="{surface}" stroke="{accent}" stroke-width="4"/>
      <rect x="{stage_x}" y="{caption_box_y}" width="16" height="{caption_box_h}" rx="8" fill="{accent}"/>
      {_render_multiline_text(caption_lines, cx, caption_text_start_y, 38, caption_font_size, ink, "800", "middle")}
    </g>"""

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vb_w} {vb_h}" width="{vb_w}" height="{vb_h}">
  {backdrop_decor}
  {header_svg}
  {beat_counter_svg}
  {stage_frame_svg}
  <g id="beat-1">{beat1_svg}</g>
  <g id="beat-2">{beat2_svg}</g>
  <g id="beat-3">{beat3_svg}</g>
  {caption_box_svg}
</svg>"""


def render_studio_thumbnail_svg(
    headline: str,
    subtitle: str,
    badge_label: str,
    blueprint: StudioShotBlueprint,
    theme: StudioThemeColors,
) -> str:
    """Dựng Thumbnail YouTube 1280x720 đồng bộ 100% phong cách Studio Explainer."""
    bg = theme.bg_color
    ink = theme.ink_color
    accent = theme.accent_color
    surface = theme.surface_fill

    head_lines = _wrap_text_lines(headline.upper(), 13, 3)
    sub_lines = _wrap_text_lines(subtitle, 30, 2)
    head_font_size = 62 if len(head_lines) >= 3 else 70
    head_line_height = 76 if len(head_lines) >= 3 else 84
    head_start_y = 236 if len(head_lines) >= 3 else 258

    head_svg = "\n  ".join(
        f'<text x="74" y="{head_start_y + idx * head_line_height}" font-family="{FONT_FAMILY}" '
        f'font-size="{head_font_size}" font-weight="800" '
        f'fill="{accent if (idx == len(head_lines) - 1 and len(head_lines) > 1) else ink}">{_escape_xml(line)}</text>'
        for idx, line in enumerate(head_lines)
    )

    divider_y = head_start_y + max(1, len(head_lines)) * head_line_height - 14
    sub_svg = "\n  ".join(
        f'<text x="74" y="{divider_y + 52 + idx * 38}" font-family="{FONT_FAMILY}" '
        f'font-size="27" font-weight="700" fill="{ink}" fill-opacity="0.88">{_escape_xml(line)}</text>'
        for idx, line in enumerate(sub_lines)
    )

    ov_svg = (
        _render_overlay_effect(blueprint.overlay_effect, 1086, 514, theme)
        if blueprint.overlay_effect != "none"
        else ""
    )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" width="1280" height="720">
  <rect width="1280" height="720" fill="{bg}"/>
  <circle cx="1140" cy="110" r="240" fill="{accent}" fill-opacity="0.08"/>
  <rect x="0" y="0" width="24" height="720" fill="{accent}"/>
  <rect x="74" y="68" width="196" height="54" rx="14" fill="{accent}"/>
  <text x="172" y="104" text-anchor="middle" font-family="{FONT_FAMILY}" font-size="26" font-weight="800" fill="{surface}">{_escape_xml(badge_label)}</text>
  {head_svg}
  <rect x="74" y="{divider_y}" width="184" height="9" rx="4.5" fill="{accent}"/>
  {sub_svg}
  <rect x="706" y="76" width="512" height="576" rx="28" fill="{ink}" fill-opacity="0.1"/>
  <rect x="696" y="66" width="512" height="576" rx="28" fill="{surface}" stroke="{ink}" stroke-width="5.5"/>
  <circle cx="952" cy="350" r="196" fill="{accent}" fill-opacity="0.07"/>
  {_render_studio_prop(blueprint.primary_prop, 1054, 242, 0.86, theme)}
  {_render_studio_character(854, 416, blueprint.character_pose, blueprint.character_expression, theme, scale=1.18)}
  {ov_svg}
</svg>"""


def rasterize_svg_to_png(
    svg_markup: str,
    output_path: Path,
    width: int,
    height: int,
) -> Path:
    """
    Chuyển đổi SVG Vector chuẩn Studio thành PNG sắc nét đúng độ phân giải mục tiêu
    (1920x1080 hoặc 1080x1920 hoặc 1280x720) bằng `rsvg-convert` (nhanh nhất trên Ubuntu),
    tự động dự phòng sang `cairosvg` nếu chưa cài `librsvg2-bin`.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rsvg_bin = shutil.which("rsvg-convert")
    if rsvg_bin:
        with tempfile.NamedTemporaryFile("w", suffix=".svg", encoding="utf-8", delete=False) as tf:
            tf.write(svg_markup)
            tmp_svg = Path(tf.name)
        try:
            proc = subprocess.run(
                [
                    rsvg_bin,
                    "-w",
                    str(width),
                    "-h",
                    str(height),
                    "-f",
                    "png",
                    "-o",
                    str(output_path),
                    str(tmp_svg),
                ],
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 1024:
                return output_path
            logger.warning("[SVG->PNG rsvg-convert warning] %s", proc.stderr.strip())
        finally:
            tmp_svg.unlink(missing_ok=True)

    try:
        import cairosvg  # type: ignore

        cairosvg.svg2png(
            bytestring=svg_markup.encode("utf-8"),
            write_to=str(output_path),
            output_width=width,
            output_height=height,
        )
        if output_path.exists() and output_path.stat().st_size > 1024:
            return output_path
    except Exception as cairo_err:
        logger.warning("[SVG->PNG cairosvg fallback failed] %s", cairo_err)

    raise RuntimeError(
        "Không tìm thấy công cụ rasterize SVG (rsvg-convert / cairosvg). "
        "Hãy cài `librsvg2-bin` hoặc `cairosvg`."
    )
