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
import xml.etree.ElementTree as ET
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
    "full_bleed_hook",
    "dark_contrast_insight",
    "quote_spotlight",
    "closeup_portrait",
    "timeline_progression",
    "stat_callout_card",
    "dialogue_debate",
    "ai_bespoke_scene",
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
    "kintsugi_bowl",
    "iceberg_depth",
    "domino_chain",
    "candle_darkness",
    "open_door_light",
    "magnifying_glass",
    "books_knowledge",
    "seedling_crack",
    "waves_boat",
    "weight_lifting",
    "social_likes_trap",
    "coin_value",
    "hamster_wheel",
    "wings_freedom",
    "radar_signal",
    "bridge_gap",
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

STUDIO_BACKDROPS: Tuple[str, ...] = (
    "clean",
    "grid_blueprint",
    "mountain_horizon",
    "city_skyline",
    "library_arch",
    "night_stars",
    "zen_ripples",
    "diagonal_rain",
)

STUDIO_CHARACTER_STYLES: Tuple[str, ...] = (
    "owl_philosopher",
    "cat_stoic",
    "fox_strategist",
    "shiba_sensei",
    "dragon_sage",
    "robot_zen",
    "stickman",
)

DEFAULT_STUDIO_CHARACTER_STYLE: str = "owl_philosopher"

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
    character_style: str = DEFAULT_STUDIO_CHARACTER_STYLE
    secondary_pose: Optional[str] = None
    secondary_expression: Optional[str] = None
    secondary_prop: Optional[str] = None
    stage_backdrop: str = "clean"
    focal_metric: Optional[str] = None
    custom_prop_svg: Optional[str] = None
    custom_scene_svg: Optional[str] = None
    sub_phrase: str = ""
    left_badge: Optional[str] = None
    right_badge: Optional[str] = None
    chapter_header: Optional[str] = None
    step_items: Optional[List[str]] = None
    beat_index: Optional[int] = None
    total_beats: Optional[int] = None


def resolve_studio_character_style(override: Optional[str] = None) -> str:
    """Lấy phong cách nhân vật 2D từ tham số hoặc config.STUDIO_CHARACTER_STYLE."""
    candidate = override if override else getattr(config, "STUDIO_CHARACTER_STYLE", DEFAULT_STUDIO_CHARACTER_STYLE)
    if isinstance(candidate, str):
        norm = candidate.strip().lower()
        if norm in STUDIO_CHARACTER_STYLES:
            return norm
    return DEFAULT_STUDIO_CHARACTER_STYLE


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
    character_style: Optional[str] = None,
) -> StudioShotBlueprint:
    """Bộ phân tích ngữ nghĩa tiếng Việt & tiếng Anh dự phòng thông minh."""
    text = f"{phrase} {short_label} {image_prompt}".lower()
    idx = beat_index or 0
    resolved_style = resolve_studio_character_style(character_style)

    def _make(**kwargs: Any) -> StudioShotBlueprint:
        return StudioShotBlueprint(
            character_style=resolved_style,
            sub_phrase=phrase,
            chapter_header=chapter_header,
            beat_index=beat_index,
            total_beats=total_beats,
            **kwargs,
        )

    if idx == 0 or re.search(r"(bí mật|sự thật|cái bẫy|cảnh báo|sai lầm|đừng bao giờ|nguy hiểm|secret|trap|warning|mistake|never ignore|shocking truth)", text):
        is_warn = bool(re.search(r"(cảnh báo|bẫy|sai lầm|trap|mistake|warning)", text))
        return _make(
            composition="full_bleed_hook",
            character_pose="pointing_accuse" if is_warn else "standing_confident",
            character_expression="determined" if is_warn else "confident",
            primary_prop="flame_forge" if is_warn else "lightbulb",
            overlay_effect="spark_emphasis",
            left_badge=chapter_header or "ĐIỂM MẤU CHỐT",
            caption=short_label or "Sự thật ít ai nói",
        )

    if re.search(r"(sợ hãi|hối tiếc|cái tôi|độc hại|ảo tưởng|bóng tối|thất bại|ghen tị|giận dữ|fear|regret|ego|toxic|illusion|dark|shadow|anger|failure)", text):
        return _make(
            composition="dark_contrast_insight",
            character_pose="arms_crossed_steady",
            character_expression="determined",
            primary_prop="mask_duality" if re.search(r"(cái tôi|ảo tưởng|ego|illusion)", text) else "broken_chains",
            overlay_effect="big_x_crossout",
            left_badge="CẦN NHẬN DIỆN",
            caption=short_label or "Góc khuất tâm lý",
        )

    if re.search(r"(câu nói|châm ngôn|nguyên tắc|marcus|seneca|epictetus|triết gia|quote|saying|maxim|ancient wisdom)", text):
        return _make(
            composition="quote_spotlight",
            character_pose="presenting_idea",
            character_expression="calm",
            primary_prop="stoic_scroll",
            overlay_effect="spark_emphasis",
            left_badge="TRIẾT LÝ KHẮC KỶ",
            caption=short_label or "Lời dạy cổ nhân",
        )

    if re.search(r"(tại sao|bạn có từng|cảm xúc|nội tâm|tự hỏi|gương|ánh nhìn|why|have you ever|emotion|feeling|self|mirror|reflect)", text):
        return _make(
            composition="closeup_portrait",
            character_pose="thinking_chin",
            character_expression="thinking" if re.search(r"(tại sao|tự hỏi|why|question)", text) else "calm",
            primary_prop="mirror_self",
            overlay_effect="spark_emphasis",
            caption=short_label or "Soi chiếu chính mình",
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

    if re.search(r"(khắc kỷ|triết lý|cổ đại|sách|stoic|scroll|pillar|wisdom)", text):
        return _make(
            composition="quote_spotlight",
            character_pose="presenting_idea",
            character_expression="calm",
            primary_prop="stoic_scroll",
            secondary_prop="temple_pillar",
            overlay_effect="spark_emphasis",
            left_badge="TRIẾT LÝ CỔ XƯA",
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

    if re.search(r"(nứt|tổn thương|vết sẹo|chữa lành|hàn gắn|kintsugi|scar|heal|fracture)", text):
        return _make(
            composition="center_metaphor",
            character_pose="standing_calm",
            character_expression="peaceful",
            primary_prop="kintsugi_bowl",
            overlay_effect="spark_emphasis",
            stage_backdrop="zen_ripples",
            caption=short_label or "Biến vết nứt thành vàng",
        )

    if re.search(r"(tảng băng|bề nổi|ẩn sâu|tiềm thức|iceberg|beneath|subconscious|hidden depth)", text):
        return _make(
            composition="character_left_prop_right",
            character_pose="thinking_chin",
            character_expression="thinking",
            primary_prop="iceberg_depth",
            overlay_effect="spark_emphasis",
            stage_backdrop="grid_blueprint",
            caption=short_label or "Phần chìm quyết định",
        )

    if re.search(r"(chuỗi|hệ quả|dây chuyền|domino|hiệu ứng|ripple|chain reaction)", text):
        return _make(
            composition="timeline_progression",
            character_pose="pointing_accuse",
            character_expression="determined",
            primary_prop="domino_chain",
            overlay_effect="curved_arrow_right",
            stage_backdrop="grid_blueprint",
            caption=short_label or "Phản ứng dây chuyền",
        )

    if re.search(r"(\b\d+%|\b3 giây\b|\b10x\b|\b90%\b|\b80%\b|thống kê|tỷ lệ|con số|stat|percent)", text):
        num_match = re.search(r"(\d+\s*%|3\s*giây|10x|#1)", text, flags=re.IGNORECASE)
        return _make(
            composition="stat_callout_card",
            character_pose="presenting_idea",
            character_expression="confident",
            primary_prop="radar_signal",
            overlay_effect="spark_emphasis",
            stage_backdrop="grid_blueprint",
            focal_metric=num_match.group(1).upper() if num_match else "90%",
            caption=short_label or "Con số biết nói",
        )

    if re.search(r"(tranh luận|đối thoại|hai luồng|mâu thuẫn|cãi vã|debate|versus|argument|dialogue)", text):
        return _make(
            composition="dialogue_debate",
            character_pose="arms_crossed_steady",
            character_expression="calm",
            secondary_pose="pointing_accuse",
            secondary_expression="angry",
            primary_prop="balance_scale",
            overlay_effect="none",
            left_badge="Cảm tính",
            right_badge="Lý trí",
            stage_backdrop="clean",
            caption=short_label or "Lý trí hay cảm tính",
        )

    if re.search(r"(mạng xã hội|like|bình luận|sống ảo|hào nhoáng|lượt xem|social|likes|followers|approval)", text):
        return _make(
            composition="dark_contrast_insight",
            character_pose="blocking_noise",
            character_expression="determined",
            primary_prop="social_likes_trap",
            overlay_effect="big_x_crossout",
            stage_backdrop="city_skyline",
            left_badge="BẪY HƯ DANH",
            caption=short_label or "Đừng sống vì nút Like",
        )

    if re.search(r"(guồng quay|lặp lại|bế tắc|chạy mãi|rat race|hamster|loop|burnout)", text):
        return _make(
            composition="prop_left_character_right",
            character_pose="walking_forward",
            character_expression="determined",
            primary_prop="hamster_wheel",
            overlay_effect="curved_arrow_right",
            stage_backdrop="city_skyline",
            caption=short_label or "Thoát khỏi vòng lặp",
        )

    cycle_defaults: List[Tuple[str, str, str, str, str, str, Optional[str]]] = [
        ("full_bleed_hook", "standing_confident", "confident", "compass", "spark_emphasis", "night_stars", None),
        ("closeup_portrait", "thinking_chin", "thinking", "magnifying_glass", "spark_emphasis", "zen_ripples", None),
        ("split_comparison", "arms_crossed_steady", "determined", "balance_scale", "curved_arrow_right", "grid_blueprint", None),
        ("timeline_progression", "walking_forward", "determined", "bridge_gap", "upward_growth_arrow", "mountain_horizon", None),
        ("dark_contrast_insight", "blocking_noise", "determined", "candle_darkness", "big_x_crossout", "night_stars", None),
        ("stat_callout_card", "presenting_idea", "confident", "kintsugi_bowl", "spark_emphasis", "grid_blueprint", "3 GIÂY"),
        ("quote_spotlight", "presenting_idea", "calm", "books_knowledge", "spark_emphasis", "library_arch", None),
        ("dialogue_debate", "standing_calm", "calm", "radar_signal", "none", "city_skyline", None),
        ("character_left_prop_right", "walking_forward", "determined", "open_door_light", "upward_growth_arrow", "mountain_horizon", None),
        ("center_metaphor", "standing_confident", "calm", "seedling_crack", "shield_aura", "zen_ripples", None),
        ("ai_bespoke_scene", "victory_raised", "confident", "wings_freedom", "spark_emphasis", "mountain_horizon", None),
        ("character_on_pedestal", "standing_confident", "confident", "laurel_crown", "checkmark_badge", "library_arch", None),
    ]
    comp, pose, expr, prop, ov, backdrop, metric = cycle_defaults[abs(idx) % len(cycle_defaults)]
    return _make(
        composition=comp,
        character_pose=pose,
        character_expression=expr,
        primary_prop=prop,
        overlay_effect=ov,
        stage_backdrop=backdrop,
        focal_metric=metric,
        caption=short_label or "Góc nhìn Khắc kỷ",
    )


def sanitize_custom_vector_fragment(raw_fragment: Any, theme: StudioThemeColors) -> Optional[str]:
    """Làm sạch & kiểm định an toàn đoạn vector SVG do AI tự vẽ (custom_prop_svg / custom_scene_svg)."""
    if not isinstance(raw_fragment, str):
        return None
    frag = raw_fragment.strip()
    if not frag or len(frag) < 16 or len(frag) > 6000:
        return None

    inner_svg = re.search(r"<svg\b[^>]*>([\s\S]*?)</svg>", frag, flags=re.IGNORECASE)
    if inner_svg:
        frag = inner_svg.group(1).strip()

    if re.search(r"<(?:script|foreignObject|iframe)\b|\son[a-z]+\s*=", frag, flags=re.IGNORECASE):
        return None

    frag = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", frag)
    frag = re.sub(r"<!--[\s\S]*?-->", "", frag)
    frag = re.sub(r"<style[\s\S]*?</style>", "", frag, flags=re.IGNORECASE)
    frag = re.sub(
        r"<(?:text|tspan|image|use|a)\b[\s\S]*?(?:/>|</(?:text|tspan|image|use|a)>)",
        "",
        frag,
        flags=re.IGNORECASE,
    )
    frag = re.sub(r"(?:xlink:)?href\s*=\s*[\"'][^\"']*[\"']", "", frag, flags=re.IGNORECASE)
    frag = re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;|#[0-9]+;|#x[0-9a-fA-F]+;)", "&amp;", frag)

    frag = re.sub(r"\{\{\s*INK\s*\}\}|__WB_INK__", theme.ink_color, frag, flags=re.IGNORECASE)
    frag = re.sub(r"\{\{\s*ACCENT\s*\}\}|__WB_ACCENT__", theme.accent_color, frag, flags=re.IGNORECASE)
    frag = re.sub(r"\{\{\s*SURFACE\s*\}\}|__WB_SURFACE__", theme.surface_fill, frag, flags=re.IGNORECASE)
    frag = re.sub(r"\{\{\s*BG\s*\}\}|__WB_BG__", theme.bg_color, frag, flags=re.IGNORECASE)

    allowed_tags = {"g", "path", "circle", "rect", "ellipse", "polygon", "polyline", "line"}
    primitive_tags = {"path", "circle", "rect", "ellipse", "polygon", "polyline", "line"}

    try:
        root = ET.fromstring(f"<g>{frag}</g>")
    except ET.ParseError:
        return None

    primitive_count = 0
    for elem in root.iter():
        tag_name = elem.tag.split("}", 1)[-1].lower()
        if tag_name not in allowed_tags:
            return None
        for attr_key in list(elem.attrib.keys()):
            attr_low = attr_key.split("}", 1)[-1].lower()
            if attr_low.startswith("on") or attr_low == "href":
                return None
        if tag_name in primitive_tags:
            primitive_count += 1

    if primitive_count < 2:
        return None
    return frag


def normalize_studio_blueprint(
    raw: Optional[Dict[str, Any]],
    phrase: str,
    short_label: str,
    image_prompt: str = "",
    chapter_header: Optional[str] = None,
    layout_type: Optional[str] = None,
    beat_index: Optional[int] = None,
    total_beats: Optional[int] = None,
    character_style: Optional[str] = None,
) -> StudioShotBlueprint:
    """Chuẩn hóa JSON từ AI Art Director thành blueprint hợp lệ 100%."""
    resolved_style = resolve_studio_character_style(
        character_style or (raw.get("character_style") if isinstance(raw, dict) else None)
    )
    inferred = infer_semantic_blueprint(
        phrase=phrase,
        short_label=short_label,
        image_prompt=image_prompt,
        chapter_header=chapter_header,
        layout_type=layout_type,
        beat_index=beat_index,
        total_beats=total_beats,
        character_style=resolved_style,
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
    focal_metric = (
        re.sub(r"[&<>]", " ", str(raw.get("focal_metric"))).strip()[:12]
        if raw.get("focal_metric")
        else inferred.focal_metric
    )
    custom_prop_svg = raw.get("custom_prop_svg") if isinstance(raw.get("custom_prop_svg"), str) else None
    custom_scene_svg = raw.get("custom_scene_svg") if isinstance(raw.get("custom_scene_svg"), str) else None

    return StudioShotBlueprint(
        composition=_pick_enum(raw.get("composition"), STUDIO_COMPOSITIONS, inferred.composition),
        character_pose=_pick_enum(raw.get("character_pose"), STUDIO_POSES, inferred.character_pose),
        character_expression=_pick_enum(raw.get("character_expression"), STUDIO_EXPRESSIONS, inferred.character_expression),
        character_style=resolved_style,
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
        stage_backdrop=(
            _pick_enum(raw.get("stage_backdrop"), STUDIO_BACKDROPS, inferred.stage_backdrop or "clean")
            if raw.get("stage_backdrop")
            else (inferred.stage_backdrop or "clean")
        ),
        focal_metric=focal_metric,
        custom_prop_svg=custom_prop_svg,
        custom_scene_svg=custom_scene_svg,
        caption=caption,
        sub_phrase=phrase,
        left_badge=left_badge,
        right_badge=right_badge,
        chapter_header=chapter_header,
        step_items=step_items,
        beat_index=beat_index,
        total_beats=total_beats,
    )


def _render_eye_brows_and_pupils(
    expression: str,
    ink: str,
    accent: str,
    surface: str,
    eye_y: int = -80,
) -> str:
    if expression == "angry":
        return f"""
        <path d="M-26 {eye_y - 14} L-7 {eye_y - 6} M26 {eye_y - 14} L7 {eye_y - 6}" stroke="{ink}" stroke-width="4.4" stroke-linecap="round"/>
        <circle cx="-15" cy="{eye_y}" r="4.6" fill="{ink}"/>
        <circle cx="15" cy="{eye_y}" r="4.6" fill="{ink}"/>
        <path d="M28 {eye_y - 32} L37 {eye_y - 23} M37 {eye_y - 32} L28 {eye_y - 23}" stroke="{accent}" stroke-width="3.2" stroke-linecap="round"/>
        """
    if expression in ("sad", "hurt"):
        return f"""
        <path d="M-25 {eye_y - 9} Q-16 {eye_y - 15} -7 {eye_y - 10} M25 {eye_y - 9} Q16 {eye_y - 15} 7 {eye_y - 10}" fill="none" stroke="{ink}" stroke-width="3.6" stroke-linecap="round"/>
        <circle cx="-15" cy="{eye_y}" r="4.2" fill="{ink}"/>
        <circle cx="15" cy="{eye_y}" r="4.2" fill="{ink}"/>
        <path d="M-21 {eye_y + 10} Q-25 {eye_y + 20} -20 {eye_y + 24} Q-15 {eye_y + 20} -21 {eye_y + 10} Z" fill="{accent}" fill-opacity="0.82"/>
        """
    if expression == "stressed":
        return f"""
        <path d="M-24 {eye_y - 14} L-8 {eye_y - 9} M24 {eye_y - 14} L8 {eye_y - 9}" stroke="{ink}" stroke-width="3.8" stroke-linecap="round"/>
        <circle cx="-15" cy="{eye_y}" r="5.2" fill="{surface}" stroke="{ink}" stroke-width="3.2"/>
        <circle cx="-15" cy="{eye_y}" r="2.1" fill="{ink}"/>
        <circle cx="15" cy="{eye_y}" r="5.2" fill="{surface}" stroke="{ink}" stroke-width="3.2"/>
        <circle cx="15" cy="{eye_y}" r="2.1" fill="{ink}"/>
        <path d="M34 {eye_y - 16} Q40 {eye_y - 5} 34 {eye_y + 1} Q28 {eye_y - 5} 34 {eye_y - 16} Z" fill="{accent}"/>
        """
    if expression == "shocked":
        return f"""
        <path d="M-24 {eye_y - 16} Q-15 {eye_y - 23} -7 {eye_y - 16} M7 {eye_y - 16} Q15 {eye_y - 23} 24 {eye_y - 16}" fill="none" stroke="{ink}" stroke-width="3.5" stroke-linecap="round"/>
        <circle cx="-15" cy="{eye_y}" r="6" fill="{surface}" stroke="{ink}" stroke-width="3.2"/>
        <circle cx="-15" cy="{eye_y}" r="2.2" fill="{ink}"/>
        <circle cx="15" cy="{eye_y}" r="6" fill="{surface}" stroke="{ink}" stroke-width="3.2"/>
        <circle cx="15" cy="{eye_y}" r="2.2" fill="{ink}"/>
        """
    if expression == "peaceful":
        return f"""
        <path d="M-23 {eye_y} Q-15 {eye_y + 6} -7 {eye_y} M7 {eye_y} Q15 {eye_y + 6} 23 {eye_y}" fill="none" stroke="{ink}" stroke-width="4" stroke-linecap="round"/>
        """
    if expression == "thinking":
        return f"""
        <path d="M-24 {eye_y - 12} Q-15 {eye_y - 18} -7 {eye_y - 12} M8 {eye_y - 14} L24 {eye_y - 11}" fill="none" stroke="{ink}" stroke-width="3.5" stroke-linecap="round"/>
        <circle cx="-14" cy="{eye_y}" r="4.3" fill="{ink}"/>
        <circle cx="16" cy="{eye_y}" r="4.3" fill="{ink}"/>
        """
    if expression == "determined":
        return f"""
        <path d="M-25 {eye_y - 12} L-7 {eye_y - 8} M25 {eye_y - 12} L7 {eye_y - 8}" stroke="{ink}" stroke-width="4.2" stroke-linecap="round"/>
        <circle cx="-15" cy="{eye_y}" r="4.6" fill="{ink}"/>
        <circle cx="15" cy="{eye_y}" r="4.6" fill="{ink}"/>
        """
    if expression == "confident":
        return f"""
        <path d="M-23 {eye_y - 13} Q-15 {eye_y - 18} -7 {eye_y - 13} M7 {eye_y - 13} Q15 {eye_y - 18} 23 {eye_y - 13}" fill="none" stroke="{ink}" stroke-width="3.6" stroke-linecap="round"/>
        <circle cx="-15" cy="{eye_y}" r="4.8" fill="{ink}"/>
        <circle cx="-13.5" cy="{eye_y - 1.5}" r="1.4" fill="{surface}"/>
        <circle cx="15" cy="{eye_y}" r="4.8" fill="{ink}"/>
        <circle cx="16.5" cy="{eye_y - 1.5}" r="1.4" fill="{surface}"/>
        """
    return f"""
    <circle cx="-15" cy="{eye_y}" r="4.6" fill="{ink}"/>
    <circle cx="-13.5" cy="{eye_y - 1.5}" r="1.4" fill="{surface}"/>
    <circle cx="15" cy="{eye_y}" r="4.6" fill="{ink}"/>
    <circle cx="16.5" cy="{eye_y - 1.5}" r="1.4" fill="{surface}"/>
    """


def _render_animal_mouth(expression: str, ink: str, accent: str, mouth_y: int = -52) -> str:
    if expression == "angry":
        return f'<path d="M-13 {mouth_y + 4} Q0 {mouth_y - 7} 13 {mouth_y + 4}" fill="{accent}" fill-opacity="0.22" stroke="{ink}" stroke-width="3.6" stroke-linecap="round"/>'
    if expression in ("sad", "hurt"):
        return f'<path d="M-12 {mouth_y + 5} Q0 {mouth_y - 5} 12 {mouth_y + 5}" fill="none" stroke="{ink}" stroke-width="3.6" stroke-linecap="round"/>'
    if expression == "stressed":
        return f'<path d="M-13 {mouth_y + 2} Q-6 {mouth_y - 3} 0 {mouth_y + 2} Q6 {mouth_y + 7} 13 {mouth_y + 2}" fill="none" stroke="{ink}" stroke-width="3.6" stroke-linecap="round"/>'
    if expression == "shocked":
        return f'<ellipse cx="0" cy="{mouth_y + 2}" rx="7.5" ry="9" fill="{accent}" fill-opacity="0.22" stroke="{ink}" stroke-width="3.5"/>'
    if expression == "determined":
        return f'<line x1="-11" y1="{mouth_y + 1}" x2="11" y2="{mouth_y + 1}" stroke="{ink}" stroke-width="3.8" stroke-linecap="round"/>'
    if expression == "thinking":
        return f'<path d="M-8 {mouth_y + 2} Q2 {mouth_y + 4} 11 {mouth_y - 2}" fill="none" stroke="{ink}" stroke-width="3.6" stroke-linecap="round"/>'
    return f'<path d="M-12 {mouth_y} Q-6 {mouth_y + 7} 0 {mouth_y + 1} Q6 {mouth_y + 7} 12 {mouth_y}" fill="none" stroke="{ink}" stroke-width="3.6" stroke-linecap="round" stroke-linejoin="round"/>'


def _render_mascot_head_and_face(
    character_style: str,
    expression: str,
    ink: str,
    accent: str,
    surface: str,
) -> str:
    if character_style == "owl_philosopher":
        eyes_svg = _render_eye_brows_and_pupils(expression, ink, accent, surface, -80)
        glasses_svg = (
            f"""
            <circle cx="-16" cy="-80" r="12" fill="none" stroke="{ink}" stroke-width="2.6" stroke-opacity="0.88"/>
            <circle cx="16" cy="-80" r="12" fill="none" stroke="{ink}" stroke-width="2.6" stroke-opacity="0.88"/>
            <line x1="-4" y1="-80" x2="4" y2="-80" stroke="{ink}" stroke-width="2.6"/>
            <line x1="-28" y1="-80" x2="-42" y2="-83" stroke="{ink}" stroke-width="2.4"/>
            <line x1="28" y1="-80" x2="42" y2="-83" stroke="{ink}" stroke-width="2.4"/>
            """
            if expression != "shocked"
            else ""
        )
        if expression == "shocked":
            beak_svg = (
                f'<polygon points="-7,-68 7,-68 0,-55" fill="{accent}" stroke="{ink}" stroke-width="3.2" stroke-linejoin="round"/>'
                f'<ellipse cx="0" cy="-55" rx="6" ry="7" fill="{accent}" fill-opacity="0.28" stroke="{ink}" stroke-width="3.2"/>'
            )
        elif expression == "angry":
            beak_svg = (
                f'<polygon points="-8,-68 8,-68 0,-54" fill="{accent}" stroke="{ink}" stroke-width="3.4" stroke-linejoin="round"/>'
                f'<line x1="-8" y1="-63" x2="8" y2="-63" stroke="{ink}" stroke-width="2.4" stroke-linecap="round"/>'
            )
        else:
            beak_svg = f'<polygon points="-7.5,-68 7.5,-68 0,-54" fill="{accent}" stroke="{ink}" stroke-width="3.2" stroke-linejoin="round"/>'

        return f"""
        <polygon points="-32,-106 -44,-138 -12,-116" fill="{surface}" stroke="{ink}" stroke-width="4.8" stroke-linejoin="round"/>
        <polygon points="32,-106 44,-138 12,-116" fill="{surface}" stroke="{ink}" stroke-width="4.8" stroke-linejoin="round"/>
        <polygon points="-28,-110 -37,-129 -17,-115" fill="{accent}" fill-opacity="0.32"/>
        <polygon points="28,-110 37,-129 17,-115" fill="{accent}" fill-opacity="0.32"/>
        <ellipse cx="0" cy="-76" rx="47" ry="43" fill="{surface}" stroke="{ink}" stroke-width="5.2"/>
        <path d="M-36 -84 Q-20 -106 0 -89 Q20 -106 36 -84 Q38 -49 0 -43 Q-38 -49 -36 -84 Z" fill="{ink}" fill-opacity="0.06" stroke="{ink}" stroke-width="2.4" stroke-opacity="0.35"/>
        {glasses_svg}
        {eyes_svg}
        {beak_svg}
        """

    if character_style == "cat_stoic":
        return f"""
        <polygon points="-39,-94 -36,-138 -9,-112" fill="{surface}" stroke="{ink}" stroke-width="5" stroke-linejoin="round"/>
        <polygon points="39,-94 36,-138 9,-112" fill="{surface}" stroke="{ink}" stroke-width="5" stroke-linejoin="round"/>
        <polygon points="-33,-100 -31,-127 -15,-111" fill="{accent}" fill-opacity="0.28"/>
        <polygon points="33,-100 31,-127 15,-111" fill="{accent}" fill-opacity="0.28"/>
        <ellipse cx="0" cy="-74" rx="47" ry="42" fill="{surface}" stroke="{ink}" stroke-width="5.2"/>
        <path d="M-38 -96 Q-18 -118 0 -100 Q18 -118 38 -96 Q16 -108 0 -92 Q-16 -108 -38 -96 Z" fill="{ink}" fill-opacity="0.88"/>
        <path d="M-54 -69 L-29 -67 M-56 -57 L-29 -59 M54 -69 L29 -67 M56 -57 L29 -59" stroke="{ink}" stroke-width="3" stroke-linecap="round"/>
        {_render_eye_brows_and_pupils(expression, ink, accent, surface, -78)}
        <polygon points="-5,-65 5,-65 0,-59" fill="{accent}" stroke="{ink}" stroke-width="2.4" stroke-linejoin="round"/>
        {_render_animal_mouth(expression, ink, accent, -53)}
        """

    if character_style == "fox_strategist":
        return f"""
        <polygon points="-40,-94 -38,-140 -10,-112" fill="{surface}" stroke="{ink}" stroke-width="5" stroke-linejoin="round"/>
        <polygon points="40,-94 38,-140 10,-112" fill="{surface}" stroke="{ink}" stroke-width="5" stroke-linejoin="round"/>
        <polygon points="-38,-118 -38,-140 -24,-125" fill="{ink}"/>
        <polygon points="38,-118 38,-140 24,-125" fill="{ink}"/>
        <polygon points="-32,-102 -30,-118 -16,-110" fill="{accent}" fill-opacity="0.32"/>
        <polygon points="32,-102 30,-118 16,-110" fill="{accent}" fill-opacity="0.32"/>
        <path d="M-47 -76 Q-43 -116 0 -116 Q43 -116 47 -76 Q53 -56 32 -44 Q12 -32 0 -32 Q-12 -32 -32 -44 Q-53 -56 -47 -76 Z" fill="{surface}" stroke="{ink}" stroke-width="5.2" stroke-linejoin="round"/>
        <path d="M-43 -76 Q-18 -64 0 -55 Q18 -64 43 -76 Q41 -112 0 -114 Q-41 -112 -43 -76 Z" fill="{accent}" fill-opacity="0.18"/>
        {_render_eye_brows_and_pupils(expression, ink, accent, surface, -79)}
        <ellipse cx="0" cy="-60" rx="5.5" ry="4" fill="{ink}"/>
        {_render_animal_mouth(expression, ink, accent, -50)}
        """

    if character_style == "shiba_sensei":
        return f"""
        <path d="M-38 -96 Q-43 -136 -25 -136 Q-12 -136 -8 -110 Z" fill="{surface}" stroke="{ink}" stroke-width="5" stroke-linejoin="round"/>
        <path d="M38 -96 Q43 -136 25 -136 Q12 -136 8 -110 Z" fill="{surface}" stroke="{ink}" stroke-width="5" stroke-linejoin="round"/>
        <path d="M-32 -102 Q-34 -124 -24 -124 Q-17 -124 -14 -108 Z" fill="{accent}" fill-opacity="0.32"/>
        <path d="M32 -102 Q34 -124 24 -124 Q17 -124 14 -108 Z" fill="{accent}" fill-opacity="0.32"/>
        <path d="M-46 -78 Q-44 -116 0 -116 Q44 -116 46 -78 Q52 -46 28 -36 Q0 -28 -28 -36 Q-52 -46 -46 -78 Z" fill="{surface}" stroke="{ink}" stroke-width="5.2" stroke-linejoin="round"/>
        <path d="M-44 -78 Q-42 -114 0 -114 Q42 -114 44 -78 Q22 -70 0 -76 Q-22 -70 -44 -78 Z" fill="{accent}" fill-opacity="0.18"/>
        <ellipse cx="0" cy="-56" rx="26" ry="18" fill="{surface}" stroke="{ink}" stroke-width="2.4" stroke-opacity="0.32"/>
        <circle cx="-15" cy="-93" r="3.4" fill="{accent}" fill-opacity="0.85"/>
        <circle cx="15" cy="-93" r="3.4" fill="{accent}" fill-opacity="0.85"/>
        {_render_eye_brows_and_pupils(expression, ink, accent, surface, -79)}
        <ellipse cx="0" cy="-64" rx="6.2" ry="4.3" fill="{ink}"/>
        {_render_animal_mouth(expression, ink, accent, -51)}
        """

    if character_style == "dragon_sage":
        return f"""
        <path d="M-24 -110 Q-42 -138 -52 -134 Q-42 -120 -30 -104" fill="{accent}" fill-opacity="0.28" stroke="{ink}" stroke-width="4.6" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M24 -110 Q42 -138 52 -134 Q42 -120 30 -104" fill="{accent}" fill-opacity="0.28" stroke="{ink}" stroke-width="4.6" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M-46 -78 Q-44 -116 0 -116 Q44 -116 46 -78 Q50 -46 26 -36 Q0 -28 -26 -36 Q-50 -46 -46 -78 Z" fill="{surface}" stroke="{ink}" stroke-width="5.2" stroke-linejoin="round"/>
        <path d="M-22 -114 L0 -96 L22 -114" fill="none" stroke="{accent}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M-38 -56 Q-54 -46 -58 -36 M38 -56 Q54 -46 58 -36" fill="none" stroke="{ink}" stroke-width="3.6" stroke-linecap="round"/>
        {_render_eye_brows_and_pupils(expression, ink, accent, surface, -79)}
        <circle cx="-6" cy="-63" r="2.2" fill="{ink}"/>
        <circle cx="6" cy="-63" r="2.2" fill="{ink}"/>
        {_render_animal_mouth(expression, ink, accent, -51)}
        """

    if character_style == "robot_zen":
        return f"""
        <line x1="0" y1="-116" x2="0" y2="-136" stroke="{ink}" stroke-width="4.6" stroke-linecap="round"/>
        <circle cx="0" cy="-140" r="6.5" fill="{accent}" stroke="{ink}" stroke-width="3.2"/>
        <rect x="-46" y="-116" width="92" height="80" rx="22" fill="{surface}" stroke="{ink}" stroke-width="5.2"/>
        <rect x="-35" y="-103" width="70" height="54" rx="14" fill="{ink}"/>
        {_render_eye_brows_and_pupils(expression, accent, surface, ink, -80)}
        {_render_animal_mouth(expression, surface, accent, -57)}
        """

    return f"""
    <circle cx="0" cy="-76" r="46" fill="{surface}" stroke="{ink}" stroke-width="5.2"/>
    <path d="M-38 -102 Q-18 -134 18 -126 Q38 -120 44 -94 Q18 -110 -12 -106 Q-28 -104 -38 -102 Z" fill="{ink}"/>
    {_render_face_expression(expression, ink, accent, surface)}
    """


def _render_mascot_tail_behind(
    character_style: str,
    is_meditating: bool,
    ink: str,
    accent: str,
    surface: str,
) -> str:
    y_offset = 20 if is_meditating else 0
    if character_style == "cat_stoic":
        return f"""<g transform="translate(0, {y_offset})">
        <path d="M-24 94 Q-72 92 -76 48 Q-78 24 -60 22" fill="none" stroke="{ink}" stroke-width="9" stroke-linecap="round"/>
        <circle cx="-60" cy="22" r="5.5" fill="{accent}"/>
        </g>"""
    if character_style == "fox_strategist":
        return f"""<g transform="translate(0, {y_offset})">
        <path d="M-22 98 Q-78 102 -84 54 Q-86 24 -56 18 Q-42 42 -34 76 Z" fill="{accent}" fill-opacity="0.22" stroke="{ink}" stroke-width="5" stroke-linejoin="round"/>
        <path d="M-76 34 Q-72 20 -56 18 Q-49 29 -56 42 Z" fill="{surface}" stroke="{ink}" stroke-width="3.5" stroke-linejoin="round"/>
        </g>"""
    if character_style == "shiba_sensei":
        return f"""<g transform="translate(0, {y_offset})">
        <path d="M-24 92 Q-68 88 -70 52 Q-70 30 -48 34 Q-36 38 -36 56" fill="none" stroke="{ink}" stroke-width="10" stroke-linecap="round"/>
        <circle cx="-48" cy="34" r="5" fill="{accent}" fill-opacity="0.8"/>
        </g>"""
    if character_style == "dragon_sage":
        return f"""<g transform="translate(0, {y_offset})">
        <path d="M-24 94 Q-78 90 -80 46 Q-80 22 -56 26" fill="none" stroke="{ink}" stroke-width="9" stroke-linecap="round"/>
        <polygon points="-58,18 -46,26 -58,34" fill="{accent}" stroke="{ink}" stroke-width="3" stroke-linejoin="round"/>
        </g>"""
    if character_style == "owl_philosopher" and not is_meditating:
        return f'<polygon points="-14,102 0,126 14,102" fill="{accent}" fill-opacity="0.25" stroke="{ink}" stroke-width="4" stroke-linejoin="round"/>'
    return ""


def _render_mascot_wing_trim(
    character_style: str,
    ink: str,
    accent: str,
    surface: str,
    tie_color: str,
) -> str:
    if character_style == "owl_philosopher":
        return f"""
        <path d="M-38 8 Q-18 -8 0 -2 Q18 -8 38 8 L44 50 Q20 38 0 54 Q-20 38 -44 50 Z" fill="{accent}" fill-opacity="0.16" stroke="{ink}" stroke-width="4" stroke-linejoin="round"/>
        <path d="M-34 8 L-45 27 L-30 35 M34 8 L45 27 L30 35" fill="none" stroke="{accent}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
        <circle cx="0" cy="14" r="7.5" fill="{tie_color}" stroke="{ink}" stroke-width="3"/>
        <path d="M-16 66 Q0 76 16 66" fill="none" stroke="{ink}" stroke-width="2.4" stroke-opacity="0.35" stroke-linecap="round"/>
        """
    if character_style == "cat_stoic":
        return f"""
        <path d="M-19 -28 Q0 -34 19 -28 L22 -2 Q0 8 -22 -2 Z" fill="{ink}" fill-opacity="0.88" stroke="{ink}" stroke-width="3.6" stroke-linejoin="round"/>
        <path d="M-24 4 L-10 42 L0 26 L10 42 L24 4" fill="none" stroke="{ink}" stroke-width="3.8" stroke-linejoin="round"/>
        <circle cx="15" cy="24" r="4.5" fill="{tie_color}"/>
        """
    if character_style == "fox_strategist":
        return f"""
        <path d="M-28 -14 L-16 -2 L0 -10 L16 -2 L28 -14 Q14 8 0 14 Q-14 8 -28 -14 Z" fill="{surface}" stroke="{ink}" stroke-width="3.8" stroke-linejoin="round"/>
        <path d="M-22 10 L0 54 L22 10" fill="none" stroke="{ink}" stroke-width="3.8" stroke-linejoin="round"/>
        <polygon points="0,20 -7,34 0,48 7,34" fill="{tie_color}"/>
        """
    if character_style == "shiba_sensei":
        return f"""
        <path d="M-24 2 L12 52 M24 2 L-12 52" fill="none" stroke="{ink}" stroke-width="4.2" stroke-linecap="round"/>
        <rect x="-29" y="56" width="58" height="14" rx="4" fill="{tie_color}" stroke="{ink}" stroke-width="3.4"/>
        """
    if character_style == "dragon_sage":
        return f"""
        <path d="M-26 2 L0 32 L26 2" fill="none" stroke="{accent}" stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round"/>
        <circle cx="0" cy="46" r="8" fill="{tie_color}" stroke="{ink}" stroke-width="3"/>
        """
    if character_style == "robot_zen":
        return f"""
        <rect x="-22" y="16" width="44" height="30" rx="8" fill="{accent}" fill-opacity="0.16" stroke="{ink}" stroke-width="3.4"/>
        <circle cx="0" cy="31" r="6" fill="{tie_color}"/>
        """
    return f"""
    <path d="M-14 4 L0 20 L14 4" fill="none" stroke="{ink}" stroke-width="3.5" stroke-linejoin="round"/>
    <polygon points="0,14 -8,44 0,76 8,44" fill="{tie_color}"/>
    """


def _render_mascot_neck_join(character_style: str, ink: str, surface: str) -> str:
    if character_style == "stickman":
        return f'<rect x="-8" y="-32" width="16" height="34" rx="6" fill="{surface}" stroke="{ink}" stroke-width="4.5"/>'
    return f'<path d="M-18 -38 Q0 -30 18 -38 L22 -4 Q0 6 -22 -4 Z" fill="{surface}" stroke="{ink}" stroke-width="4"/>'


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
    character_style: str = DEFAULT_STUDIO_CHARACTER_STYLE,
    waist_up: bool = False,
) -> str:
    ink = theme.ink_color
    accent = theme.accent_color
    surface = theme.surface_fill
    tie_color = accent if accent_tie else ink
    sx = -scale if flip_x else scale
    resolved_style = resolve_studio_character_style(character_style)
    head_svg = _render_mascot_head_and_face(resolved_style, expression, ink, accent, surface)
    wing_trim_svg = _render_mascot_wing_trim(resolved_style, ink, accent, surface, tie_color)
    neck_join_svg = _render_mascot_neck_join(resolved_style, ink, surface)

    if pose == "meditating_zen" and not waist_up:
        tail_svg = _render_mascot_tail_behind(resolved_style, True, ink, accent, surface)
        return f"""<g transform="translate({x}, {y}) scale({sx}, {scale})">
      <ellipse cx="0" cy="146" rx="88" ry="15" fill="{ink}" fill-opacity="0.12"/>
      <circle cx="0" cy="-25" r="120" fill="{accent}" fill-opacity="0.06" stroke="{accent}" stroke-width="2.5" stroke-dasharray="10 8"/>
      {tail_svg}
      <path d="M-24 92 Q-78 104 -68 132 Q-42 146 8 134" fill="none" stroke="{ink}" stroke-width="11" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M24 92 Q78 104 68 132 Q42 146 -8 134" fill="none" stroke="{ink}" stroke-width="11" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M-32 8 Q0 -6 32 8 L38 96 Q0 108 -38 96 Z" fill="{surface}" stroke="{ink}" stroke-width="5" stroke-linejoin="round"/>
      {wing_trim_svg}
      <path d="M-30 22 Q-66 56 -56 106 L-34 114" fill="none" stroke="{ink}" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M30 22 Q66 56 56 106 L34 114" fill="none" stroke="{ink}" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/>
      <circle cx="-32" cy="114" r="7" fill="{surface}" stroke="{ink}" stroke-width="4"/>
      <circle cx="32" cy="114" r="7" fill="{surface}" stroke="{ink}" stroke-width="4"/>
      {neck_join_svg}
      {head_svg}
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

    tail_svg = "" if waist_up else _render_mascot_tail_behind(resolved_style, False, ink, accent, surface)
    base_layer = "" if waist_up else f'<ellipse cx="0" cy="172" rx="68" ry="12" fill="{ink}" fill-opacity="0.12"/>\n    {legs_svg}'
    torso_path = (
        f'<path d="M-36 8 Q0 -6 36 8 L44 148 L-44 148 Z" fill="{surface}" stroke="{ink}" stroke-width="5.2" stroke-linejoin="round"/>'
        if waist_up
        else f'<path d="M-34 8 Q0 -6 34 8 L28 104 Q0 112 -28 104 Z" fill="{surface}" stroke="{ink}" stroke-width="5.2" stroke-linejoin="round"/>'
    )
    eff_left_arm = left_arm
    eff_right_arm = right_arm
    eff_left_hand = left_hand
    eff_right_hand = right_hand
    eff_extra_prop = extra_prop

    if waist_up:
        if pose == "slumped_sad":
            eff_left_arm = "M-26 26 L-44 64 L-30 82"
            eff_right_arm = "M30 28 L46 66 L38 84"
        elif pose == "pointing_accuse":
            eff_right_arm = "M32 16 L66 10 L88 6"
            eff_right_hand = (88, 6)
        elif pose == "blocking_noise":
            eff_right_arm = "M32 16 L68 8 L86 -12"
            eff_right_hand = (86, -12)
            eff_extra_prop = f"""
        <path d="M95 -34 L95 10" stroke="{accent}" stroke-width="5.5" stroke-linecap="round"/>
        <path d="M106 -26 L106 2" stroke="{accent}" stroke-width="3.8" stroke-linecap="round" stroke-opacity="0.55"/>
        """
        elif pose == "presenting_idea":
            eff_right_arm = "M32 16 L66 -2 L86 -24"
            eff_right_hand = (86, -24)
        elif pose == "shield_stance":
            eff_right_arm = "M32 18 L60 28 L72 12"
            eff_right_hand = (72, 12)
            eff_extra_prop = f"""
        <path d="M72 -28 L106 -16 L102 36 Q86 66 72 78 Q58 66 54 36 L58 -16 Z" fill="{surface}" stroke="{accent}" stroke-width="5.5" stroke-linejoin="round"/>
        <path d="M72 -10 L90 -3 L88 28 Q79 46 72 54 Q65 46 63 28 L65 -3 Z" fill="{accent}" fill-opacity="0.18"/>
        <path d="M62 22 L70 30 L84 12" fill="none" stroke="{accent}" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
        """
        eff_left_hand = (max(-88, min(88, eff_left_hand[0])), min(eff_left_hand[1], 82))
        eff_right_hand = (max(-88, min(88, eff_right_hand[0])), min(eff_right_hand[1], 84))

    return f"""<g transform="translate({x}, {y}) scale({sx}, {scale})">
    {base_layer}
    <g transform="{torso_skew}">
      {tail_svg}
      <path d="{eff_left_arm}" fill="none" stroke="{ink}" stroke-width="9" stroke-linecap="round" stroke-linejoin="round"/>
      <circle cx="{eff_left_hand[0]}" cy="{eff_left_hand[1]}" r="7.5" fill="{surface}" stroke="{ink}" stroke-width="4"/>
      {torso_path}
      {wing_trim_svg}
      <path d="{eff_right_arm}" fill="none" stroke="{ink}" stroke-width="9" stroke-linecap="round" stroke-linejoin="round"/>
      <circle cx="{eff_right_hand[0]}" cy="{eff_right_hand[1]}" r="7.5" fill="{surface}" stroke="{ink}" stroke-width="4"/>
      <g transform="translate({head_shift_x}, {head_shift_y})">
        {neck_join_svg}
        {head_svg}
      </g>
      {eff_extra_prop}
    </g>
  </g>"""


def _render_studio_prop(
    prop: str,
    x: int,
    y: int,
    scale: float,
    theme: StudioThemeColors,
    custom_prop_svg: Optional[str] = None,
) -> str:
    bg = theme.bg_color
    ink = theme.ink_color
    accent = theme.accent_color
    surface = theme.surface_fill
    sanitized_custom = sanitize_custom_vector_fragment(custom_prop_svg, theme)
    if sanitized_custom:
        return f'<g transform="translate({x}, {y}) scale({scale})">{sanitized_custom}</g>'
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
        <line x1="-26" y1="-44" x2="14" y2="-8" stroke="{accent}" stroke-opacity="0.45" stroke-width="7" stroke-linecap="round"/>
        <line x1="-24" y1="-12" x2="4" y2="14" stroke="{accent}" stroke-opacity="0.35" stroke-width="5" stroke-linecap="round"/>
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
    elif prop == "kintsugi_bowl":
        inner = f"""
        <ellipse cx="0" cy="96" rx="88" ry="12" fill="{ink}" fill-opacity="0.12"/>
        <path d="M-92 -28 Q-92 66 0 84 Q92 66 92 -28 Z" fill="{surface}" stroke="{ink}" stroke-width="6" stroke-linejoin="round"/>
        <ellipse cx="0" cy="-28" rx="92" ry="18" fill="{bg}" stroke="{ink}" stroke-width="5.5"/>
        <path d="M-36 -10 L-12 24 L-26 52 L6 78 M28 -12 L8 22 L32 48" fill="none" stroke="{accent}" stroke-width="6.5" stroke-linecap="round" stroke-linejoin="round"/>
        <circle cx="-12" cy="24" r="5" fill="{accent}"/>
        """
    elif prop == "iceberg_depth":
        inner = f"""
        <rect x="-126" y="-8" width="252" height="106" rx="14" fill="{accent}" fill-opacity="0.12" stroke="{accent}" stroke-width="3" stroke-dasharray="8 6"/>
        <line x1="-132" y1="-8" x2="132" y2="-8" stroke="{accent}" stroke-width="5" stroke-linecap="round"/>
        <polygon points="-38,-8 -8,-84 22,-52 44,-8" fill="{surface}" stroke="{ink}" stroke-width="5.5" stroke-linejoin="round"/>
        <polygon points="-44,-8 50,-8 92,42 36,96 -48,88 -82,36" fill="{surface}" fill-opacity="0.88" stroke="{ink}" stroke-width="5.5" stroke-linejoin="round"/>
        <path d="M-8 -8 L12 88 M44 -8 L36 42" stroke="{ink}" stroke-width="3.5" stroke-opacity="0.45"/>
        """
    elif prop == "domino_chain":
        inner = f"""
        <ellipse cx="0" cy="96" rx="116" ry="12" fill="{ink}" fill-opacity="0.12"/>
        <g transform="translate(-72, 24) rotate(26)"><rect x="-18" y="-56" width="36" height="112" rx="8" fill="{surface}" stroke="{ink}" stroke-width="5"/><circle cx="0" cy="-26" r="5" fill="{ink}"/><circle cx="0" cy="26" r="5" fill="{ink}"/></g>
        <g transform="translate(-8, 12) rotate(14)"><rect x="-18" y="-56" width="36" height="112" rx="8" fill="{surface}" stroke="{ink}" stroke-width="5"/><circle cx="0" cy="-26" r="5" fill="{accent}"/><circle cx="0" cy="26" r="5" fill="{accent}"/></g>
        <g transform="translate(64, 4)"><rect x="-18" y="-56" width="36" height="112" rx="8" fill="{accent}" fill-opacity="0.22" stroke="{accent}" stroke-width="5.5"/><path d="M-8 0 L0 10 L12 -10" fill="none" stroke="{accent}" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/></g>
        """
    elif prop == "candle_darkness":
        inner = f"""
        <circle cx="0" cy="-42" r="78" fill="{accent}" fill-opacity="0.14" stroke="{accent}" stroke-width="3" stroke-dasharray="8 8"/>
        <path d="M0 -84 C18 -58 22 -36 0 -22 C-22 -36 -18 -58 0 -84 Z" fill="{accent}" stroke="{ink}" stroke-width="4" stroke-linejoin="round"/>
        <line x1="0" y1="-22" x2="0" y2="-8" stroke="{ink}" stroke-width="4"/>
        <rect x="-28" y="-8" width="56" height="98" rx="8" fill="{surface}" stroke="{ink}" stroke-width="5.5"/>
        <rect x="-48" y="88" width="96" height="16" rx="6" fill="{ink}"/>
        """
    elif prop == "open_door_light":
        inner = f"""
        <polygon points="10,-86 116,-106 116,104 10,86" fill="{accent}" fill-opacity="0.22" stroke="{accent}" stroke-width="4" stroke-dasharray="8 6"/>
        <rect x="-78" y="-86" width="92" height="172" rx="6" fill="{surface}" stroke="{ink}" stroke-width="6"/>
        <polygon points="-78,-86 10,-64 10,64 -78,86" fill="{bg}" stroke="{ink}" stroke-width="5.5" stroke-linejoin="round"/>
        <circle cx="-12" cy="4" r="6" fill="{accent}"/>
        """
    elif prop == "magnifying_glass":
        inner = f"""
        <circle cx="-16" cy="-16" r="68" fill="{surface}" stroke="{ink}" stroke-width="7"/>
        <circle cx="-16" cy="-16" r="46" fill="{accent}" fill-opacity="0.14" stroke="{accent}" stroke-width="4"/>
        <circle cx="-16" cy="-16" r="14" fill="{accent}"/>
        <line x1="34" y1="34" x2="92" y2="92" stroke="{ink}" stroke-width="14" stroke-linecap="round"/>
        <line x1="34" y1="34" x2="92" y2="92" stroke="{accent}" stroke-width="5" stroke-linecap="round"/>
        """
    elif prop == "books_knowledge":
        inner = f"""
        <ellipse cx="0" cy="102" rx="96" ry="12" fill="{ink}" fill-opacity="0.12"/>
        <rect x="-86" y="42" width="172" height="44" rx="8" fill="{surface}" stroke="{ink}" stroke-width="5.5"/>
        <rect x="-72" y="-6" width="144" height="44" rx="8" fill="{accent}" fill-opacity="0.22" stroke="{ink}" stroke-width="5.5"/>
        <rect x="-58" y="-54" width="116" height="44" rx="8" fill="{surface}" stroke="{ink}" stroke-width="5.5"/>
        <path d="M52 -96 Q84 -84 74 -44 L44 -52 Z" fill="{accent}" stroke="{ink}" stroke-width="4" stroke-linejoin="round"/>
        """
    elif prop == "seedling_crack":
        inner = f"""
        <path d="M-112 72 L-38 56 L0 84 L46 58 L112 72" fill="none" stroke="{ink}" stroke-width="6.5" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M0 78 L0 -12" stroke="{ink}" stroke-width="6.5" stroke-linecap="round"/>
        <path d="M0 -4 Q-54 -48 -58 -8 Q-36 16 0 -4 Z" fill="{accent}" fill-opacity="0.28" stroke="{ink}" stroke-width="5" stroke-linejoin="round"/>
        <path d="M0 -20 Q56 -72 62 -24 Q38 4 0 -20 Z" fill="{accent}" stroke="{ink}" stroke-width="5" stroke-linejoin="round"/>
        """
    elif prop == "waves_boat":
        inner = f"""
        <polygon points="-58,18 58,18 40,56 -40,56" fill="{surface}" stroke="{ink}" stroke-width="5.5" stroke-linejoin="round"/>
        <line x1="0" y1="18" x2="0" y2="-76" stroke="{ink}" stroke-width="6" stroke-linecap="round"/>
        <polygon points="0,-74 52,-12 0,-4" fill="{accent}" fill-opacity="0.88" stroke="{ink}" stroke-width="4.5" stroke-linejoin="round"/>
        <path d="M-118 68 Q-84 44 -50 68 Q-16 92 18 68 Q52 44 86 68 Q106 82 122 68" fill="none" stroke="{accent}" stroke-width="6.5" stroke-linecap="round"/>
        """
    elif prop == "weight_lifting":
        inner = f"""
        <ellipse cx="0" cy="96" rx="92" ry="12" fill="{ink}" fill-opacity="0.12"/>
        <line x1="-88" y1="0" x2="88" y2="0" stroke="{ink}" stroke-width="9" stroke-linecap="round"/>
        <rect x="-86" y="-44" width="24" height="88" rx="8" fill="{surface}" stroke="{ink}" stroke-width="5.5"/>
        <rect x="-106" y="-30" width="18" height="60" rx="6" fill="{accent}" stroke="{ink}" stroke-width="4.5"/>
        <rect x="62" y="-44" width="24" height="88" rx="8" fill="{surface}" stroke="{ink}" stroke-width="5.5"/>
        <rect x="88" y="-30" width="18" height="60" rx="6" fill="{accent}" stroke="{ink}" stroke-width="4.5"/>
        <path d="M0 -68 L0 -26 M-16 -52 L0 -68 L16 -52" fill="none" stroke="{accent}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>
        """
    elif prop == "social_likes_trap":
        inner = f"""
        <rect x="-86" y="-68" width="172" height="122" rx="22" fill="{surface}" stroke="{ink}" stroke-width="5.5"/>
        <path d="M0 18 C-42 -8 -44 -42 -20 -50 C-6 -54 0 -40 0 -32 C0 -40 6 -54 20 -50 C44 -42 42 -8 0 18 Z" fill="{accent}" stroke="{ink}" stroke-width="4.5"/>
        <path d="M-64 78 L64 78" stroke="{ink}" stroke-width="6" stroke-linecap="round"/>
        <path d="M-44 -78 L44 64 M44 -78 L-44 64" stroke="{accent}" stroke-width="8" stroke-linecap="round" stroke-opacity="0.85"/>
        """
    elif prop == "coin_value":
        inner = f"""
        <ellipse cx="0" cy="102" rx="76" ry="12" fill="{ink}" fill-opacity="0.12"/>
        <circle cx="-18" cy="-4" r="74" fill="{accent}" fill-opacity="0.22" stroke="{ink}" stroke-width="6"/>
        <circle cx="-18" cy="-4" r="52" fill="{surface}" stroke="{accent}" stroke-width="4.5"/>
        <path d="M-18 -32 L-18 24 M-32 -16 Q-18 -28 -4 -16 Q-18 -4 -32 8 Q-18 20 -4 8" fill="none" stroke="{ink}" stroke-width="5" stroke-linecap="round"/>
        <polygon points="62,-72 72,-44 100,-44 78,-26 86,2 62,-16 38,2 46,-26 24,-44 52,-44" fill="{accent}" stroke="{ink}" stroke-width="4" stroke-linejoin="round"/>
        """
    elif prop == "hamster_wheel":
        inner = f"""
        <circle cx="0" cy="-6" r="84" fill="{surface}" stroke="{ink}" stroke-width="7"/>
        <circle cx="0" cy="-6" r="62" fill="none" stroke="{accent}" stroke-width="4" stroke-dasharray="12 10"/>
        <line x1="-62" y1="-6" x2="62" y2="-6" stroke="{ink}" stroke-width="4"/>
        <line x1="0" y1="-68" x2="0" y2="56" stroke="{ink}" stroke-width="4"/>
        <path d="M-48 88 L0 58 L48 88" fill="none" stroke="{ink}" stroke-width="6.5" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M88 -54 A102 102 0 0 1 92 38" fill="none" stroke="{accent}" stroke-width="6" stroke-linecap="round"/>
        """
    elif prop == "wings_freedom":
        inner = f"""
        <path d="M-12 24 C-68 18 -114 -24 -116 -76 C-76 -66 -46 -46 -22 -14 C-48 -28 -84 -32 -98 -4 C-68 10 -40 16 -12 24 Z" fill="{surface}" stroke="{ink}" stroke-width="5.5" stroke-linejoin="round"/>
        <path d="M12 24 C68 18 114 -24 116 -76 C76 -66 46 -46 22 -14 C48 -28 84 -32 98 -4 C68 10 40 16 12 24 Z" fill="{accent}" fill-opacity="0.22" stroke="{ink}" stroke-width="5.5" stroke-linejoin="round"/>
        <circle cx="0" cy="-16" r="16" fill="{accent}" stroke="{ink}" stroke-width="4"/>
        """
    elif prop == "radar_signal":
        inner = f"""
        <circle cx="0" cy="0" r="92" fill="{surface}" stroke="{ink}" stroke-width="5.5"/>
        <circle cx="0" cy="0" r="60" fill="none" stroke="{ink}" stroke-width="3.5" stroke-opacity="0.45"/>
        <circle cx="0" cy="0" r="28" fill="none" stroke="{accent}" stroke-width="4"/>
        <line x1="0" y1="-92" x2="0" y2="92" stroke="{ink}" stroke-width="2.5" stroke-opacity="0.35"/>
        <line x1="-92" y1="0" x2="92" y2="0" stroke="{ink}" stroke-width="2.5" stroke-opacity="0.35"/>
        <polygon points="0,0 56,-68 78,-26" fill="{accent}" fill-opacity="0.28"/>
        <circle cx="44" cy="-36" r="9" fill="{accent}"/>
        """
    elif prop == "bridge_gap":
        inner = f"""
        <polygon points="-126,92 -126,18 -64,18 -48,92" fill="{surface}" stroke="{ink}" stroke-width="5.5" stroke-linejoin="round"/>
        <polygon points="126,92 126,18 64,18 48,92" fill="{surface}" stroke="{ink}" stroke-width="5.5" stroke-linejoin="round"/>
        <path d="M-76 18 Q0 -34 76 18" fill="none" stroke="{accent}" stroke-width="9" stroke-linecap="round"/>
        <path d="M-72 2 Q0 -48 72 2" fill="none" stroke="{ink}" stroke-width="4" stroke-dasharray="8 8"/>
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
    <rect id="studio-backdrop-bg" width="{vb_w}" height="{vb_h}" fill="{bg}"/>
    <circle cx="{round(vb_w * 0.14)}" cy="{round(vb_h * 0.18)}" r="{140 if is_vertical else 190}" fill="{accent}" fill-opacity="0.05"/>
    <circle cx="{round(vb_w * 0.86)}" cy="{round(vb_h * 0.78)}" r="{160 if is_vertical else 210}" fill="{ink}" fill-opacity="0.04"/>
    """

    has_counter = (
        blueprint.beat_index is not None
        and blueprint.total_beats is not None
        and blueprint.total_beats > 1
    )

    header_clean = re.sub(r"[&<>]", " ", str(blueprint.chapter_header or "")).strip()[: (34 if is_vertical else 48)]
    header_rect_x = 44 if is_vertical else cx - 320
    header_rect_w = (vb_w - 180 if has_counter else vb_w - 88) if is_vertical else 640
    header_text_x = round(header_rect_x + header_rect_w / 2)
    header_svg = ""
    if header_clean:
        header_svg = f"""
    <g id="studio-header">
      <rect x="{header_rect_x}" y="22" width="{header_rect_w}" height="50" rx="25" fill="{surface}" stroke="{ink}" stroke-width="3"/>
      <text x="{header_text_x}" y="54" text-anchor="middle" font-family="{FONT_FAMILY}" font-size="{20 if is_vertical else 24}" font-weight="700" fill="{ink}">{_escape_xml(header_clean)}</text>
    </g>"""

    beat_counter_svg = ""
    if has_counter:
        beat_counter_svg = (
            f'<g id="studio-beat-counter">'
            f'<rect x="{vb_w - 118}" y="24" width="84" height="36" rx="18" fill="{surface}" fill-opacity="0.96" stroke="{accent}" stroke-width="2.5"/>'
            f'<text x="{vb_w - 76}" y="48" text-anchor="middle" font-family="{FONT_FAMILY}" font-size="18" font-weight="800" fill="{accent}">{(blueprint.beat_index or 0) + 1}/{blueprint.total_beats}</text>'
            f'</g>'
        )

    stage_x = 44 if is_vertical else 68
    stage_y = 94 if header_clean else 62
    stage_w = vb_w - stage_x * 2
    stage_h = 790 if is_vertical else 482
    stage_mid_x = round(stage_x + stage_w / 2)
    stage_mid_y = round(stage_y + stage_h / 2)
    caption_box_y = stage_y + stage_h + 22
    caption_box_h = vb_h - caption_box_y - 24

    comp = blueprint.composition
    is_full_bleed = comp == "full_bleed_hook"
    is_dark_contrast = comp == "dark_contrast_insight"
    stage_backdrop_style = _pick_enum(getattr(blueprint, "stage_backdrop", "clean"), STUDIO_BACKDROPS, "clean")

    def _render_stage_backdrop_pattern(
        backdrop: str,
        sx: int,
        sy: int,
        sw: int,
        sh: int,
        fg_color: str,
        hi_color: str,
    ) -> str:
        if backdrop == "grid_blueprint":
            return f"""
          <g opacity="0.09" stroke="{fg_color}" stroke-width="1.5">
            <line x1="{sx + round(sw * 0.25)}" y1="{sy + 24}" x2="{sx + round(sw * 0.25)}" y2="{sy + sh - 24}"/>
            <line x1="{sx + round(sw * 0.50)}" y1="{sy + 24}" x2="{sx + round(sw * 0.50)}" y2="{sy + sh - 24}"/>
            <line x1="{sx + round(sw * 0.75)}" y1="{sy + 24}" x2="{sx + round(sw * 0.75)}" y2="{sy + sh - 24}"/>
            <line x1="{sx + 24}" y1="{sy + round(sh * 0.33)}" x2="{sx + sw - 24}" y2="{sy + round(sh * 0.33)}"/>
            <line x1="{sx + 24}" y1="{sy + round(sh * 0.66)}" x2="{sx + sw - 24}" y2="{sy + round(sh * 0.66)}"/>
          </g>"""
        if backdrop == "mountain_horizon":
            return f'<path d="M{sx + 36} {sy + sh - 54} L{sx + round(sw * 0.22)} {sy + sh - 165} L{sx + round(sw * 0.42)} {sy + sh - 78} L{sx + round(sw * 0.68)} {sy + sh - 210} L{sx + sw - 36} {sy + sh - 54} Z" fill="{fg_color}" fill-opacity="0.06"/>'
        if backdrop == "city_skyline":
            return f'<path d="M{sx + 48} {sy + sh - 54} V{sy + sh - 150} H{sx + 130} V{sy + sh - 110} H{sx + 220} V{sy + sh - 190} H{sx + 320} V{sy + sh - 130} H{sx + round(sw * 0.72)} V{sy + sh - 175} H{sx + round(sw * 0.85)} V{sy + sh - 54} Z" fill="{fg_color}" fill-opacity="0.06"/>'
        if backdrop == "library_arch":
            return f"""
          <g opacity="0.1" fill="none" stroke="{fg_color}" stroke-width="3">
            <path d="M{sx + 90} {sy + sh - 54} V{sy + 140} A90 90 0 0 1 {sx + 270} {sy + 140} V{sy + sh - 54}"/>
            <path d="M{sx + sw - 270} {sy + sh - 54} V{sy + 140} A90 90 0 0 1 {sx + sw - 90} {sy + 140} V{sy + sh - 54}"/>
          </g>"""
        if backdrop == "night_stars":
            return f"""
          <g fill="{hi_color}" fill-opacity="0.28">
            <circle cx="{sx + 110}" cy="{sy + 86}" r="4"/><circle cx="{sx + 240}" cy="{sy + 144}" r="3"/>
            <circle cx="{sx + sw - 120}" cy="{sy + 92}" r="4.5"/><circle cx="{sx + sw - 260}" cy="{sy + 162}" r="3"/>
            <circle cx="{sx + round(sw * 0.52)}" cy="{sy + 72}" r="3.5"/>
          </g>"""
        if backdrop == "zen_ripples":
            return f"""
          <g fill="none" stroke="{hi_color}" stroke-opacity="0.12" stroke-width="2.5">
            <circle cx="{sx + round(sw / 2)}" cy="{sy + round(sh / 2)}" r="150"/>
            <circle cx="{sx + round(sw / 2)}" cy="{sy + round(sh / 2)}" r="230" stroke-dasharray="12 10"/>
          </g>"""
        if backdrop == "diagonal_rain":
            return f"""
          <g stroke="{fg_color}" stroke-opacity="0.09" stroke-width="3" stroke-linecap="round">
            <line x1="{sx + 120}" y1="{sy + 50}" x2="{sx + 80}" y2="{sy + 130}"/>
            <line x1="{sx + sw - 140}" y1="{sy + 60}" x2="{sx + sw - 180}" y2="{sy + 140}"/>
            <line x1="{sx + round(sw * 0.45)}" y1="{sy + 44}" x2="{sx + round(sw * 0.45) - 40}" y2="{sy + 118}"/>
          </g>"""
        return ""

    inner_backdrop_svg = _render_stage_backdrop_pattern(
        stage_backdrop_style,
        stage_x,
        stage_y,
        stage_w,
        stage_h,
        surface if (is_full_bleed or is_dark_contrast) else ink,
        accent,
    )

    if is_full_bleed:
        stage_frame_svg = f"""
    <g id="stage-full-bleed">
      <rect x="0" y="0" width="{vb_w}" height="{caption_box_y - 12}" fill="{ink}"/>
      {inner_backdrop_svg}
      <circle cx="{stage_mid_x if is_vertical else 978}" cy="{(stage_y + 448) if is_vertical else round((stage_y + caption_box_y - 12) * 0.52)}" r="{245 if is_vertical else 300}" fill="{surface}" fill-opacity="0.06"/>
      <circle cx="{stage_mid_x if is_vertical else 978}" cy="{(stage_y + 448) if is_vertical else round((stage_y + caption_box_y - 12) * 0.52)}" r="{195 if is_vertical else 225}" fill="{accent}" fill-opacity="0.16"/>
      <line x1="0" y1="{caption_box_y - 14}" x2="{vb_w}" y2="{caption_box_y - 14}" stroke="{accent}" stroke-width="5"/>
    </g>"""
    elif is_dark_contrast:
        stage_frame_svg = f"""
    <g id="stage-dark-contrast">
      <rect x="{stage_x + 8}" y="{stage_y + 8}" width="{stage_w}" height="{stage_h}" rx="28" fill="{ink}" fill-opacity="0.16"/>
      <rect x="{stage_x}" y="{stage_y}" width="{stage_w}" height="{stage_h}" rx="28" fill="{ink}" stroke="{accent}" stroke-width="4.5"/>
      {inner_backdrop_svg}
      <line x1="{stage_x + 42}" y1="{stage_y + stage_h - 54}" x2="{stage_x + stage_w - 42}" y2="{stage_y + stage_h - 54}" stroke="{surface}" stroke-width="2" stroke-opacity="0.2" stroke-linecap="round"/>
    </g>"""
    else:
        stage_frame_svg = f"""
    <g id="stage-card">
      <rect x="{stage_x + 8}" y="{stage_y + 8}" width="{stage_w}" height="{stage_h}" rx="28" fill="{ink}" fill-opacity="0.08"/>
      <rect x="{stage_x}" y="{stage_y}" width="{stage_w}" height="{stage_h}" rx="28" fill="{surface}" stroke="{ink}" stroke-width="4"/>
      {inner_backdrop_svg}
      <line x1="{stage_x + 42}" y1="{stage_y + stage_h - 54}" x2="{stage_x + stage_w - 42}" y2="{stage_y + stage_h - 54}" stroke="{ink}" stroke-width="2.5" stroke-opacity="0.18" stroke-linecap="round"/>
    </g>"""

    char_scale = 0.96 if is_vertical else 1.04
    prop_scale = 0.94 if is_vertical else 1.06
    char_style = resolve_studio_character_style(getattr(blueprint, "character_style", None))

    beat1_svg = ""
    beat2_svg = ""
    beat3_svg = ""

    if comp == "full_bleed_hook":
        dark_bottom = caption_box_y - 12
        hero_x = stage_mid_x if is_vertical else 978
        hero_disc_y = (stage_y + 448) if is_vertical else round((stage_y + dark_bottom) / 2) + 8
        hero_disc_r = 160 if is_vertical else 180
        hook_head_lines = _wrap_text_lines((blueprint.caption or "ĐIỂM MẤU CHỐT").upper(), 18 if is_vertical else 15, 3)
        text_x = stage_mid_x if is_vertical else 76
        text_anchor = "middle" if is_vertical else "start"
        tag_y = (stage_y + 26) if is_vertical else (stage_y + 42)
        text_start_y = (tag_y + 82) if is_vertical else (tag_y + 94)
        line_h = 46 if is_vertical else 54
        font_sz = 38 if is_vertical else 44
        tag_text = (blueprint.left_badge or blueprint.chapter_header or "ĐIỂM MẤU CHỐT")[:22]
        bar_y = text_start_y + max(1, len(hook_head_lines)) * line_h + 10

        beat1_svg = f"""
        <rect x="{stage_mid_x - 135 if is_vertical else 76}" y="{tag_y}" width="270" height="38" rx="19" fill="{accent}"/>
        <text x="{stage_mid_x if is_vertical else 211}" y="{tag_y + 25}" text-anchor="middle" font-family="{FONT_FAMILY}" font-size="18" font-weight="800" fill="{surface}">{_escape_xml(tag_text)}</text>
        {_render_multiline_text(hook_head_lines, text_x, text_start_y, line_h, font_sz, surface, "800", text_anchor)}
        <rect x="{stage_mid_x - 70 if is_vertical else 76}" y="{bar_y}" width="140" height="7" rx="3.5" fill="{accent}"/>
        """
        beat2_svg = f"""
        <circle cx="{hero_x}" cy="{hero_disc_y}" r="{hero_disc_r}" fill="{surface}" fill-opacity="0.98" stroke="{accent}" stroke-width="5"/>
        <circle cx="{hero_x}" cy="{hero_disc_y}" r="{hero_disc_r - 12}" fill="{accent}" fill-opacity="0.06" stroke="{accent}" stroke-width="2" stroke-dasharray="10 8"/>
        {_render_studio_character(hero_x, hero_disc_y - 12, blueprint.character_pose, blueprint.character_expression, theme, scale=0.88 if is_vertical else 0.96, flip_x=not is_vertical, character_style=char_style)}
        """
        prop_badge_x = stage_mid_x if is_vertical else 638
        prop_badge_y = (stage_y + 704) if is_vertical else (dark_bottom - 122)
        prop_badge_r = 68 if is_vertical else 72
        ov_part = (
            _render_overlay_effect(blueprint.overlay_effect, prop_badge_x + 54, prop_badge_y - 52, theme)
            if blueprint.overlay_effect != "none"
            else ""
        )
        beat3_svg = f"""
        <circle cx="{prop_badge_x}" cy="{prop_badge_y}" r="{prop_badge_r}" fill="{surface}" fill-opacity="0.98" stroke="{accent}" stroke-width="4.5"/>
        {_render_studio_prop(blueprint.primary_prop, prop_badge_x, prop_badge_y, 0.42 if is_vertical else 0.44, theme, blueprint.custom_prop_svg)}
        {ov_part}
        """

    elif comp == "dark_contrast_insight":
        left_x = stage_mid_x if is_vertical else stage_x + round(stage_w * 0.28)
        left_y = (stage_y + round(stage_h * 0.27)) if is_vertical else stage_mid_y + 12
        right_x = stage_mid_x if is_vertical else stage_x + round(stage_w * 0.72)
        right_y = (stage_y + round(stage_h * 0.75)) if is_vertical else stage_mid_y + 6
        hero_disc_r = 136 if is_vertical else 160
        warn_tag = (blueprint.left_badge or "CẦN NHẬN DIỆN")[:22]
        ov_eff = "big_x_crossout" if blueprint.overlay_effect == "none" else blueprint.overlay_effect
        mid_ov_y = (stage_y + round(stage_h * 0.49)) if is_vertical else stage_mid_y

        beat1_svg = f"""
        <rect x="{left_x - 120}" y="{stage_y + 22}" width="240" height="36" rx="18" fill="{accent}"/>
        <text x="{left_x}" y="{stage_y + 46}" text-anchor="middle" font-family="{FONT_FAMILY}" font-size="18" font-weight="800" fill="{surface}">{_escape_xml(warn_tag)}</text>
        <circle cx="{left_x}" cy="{left_y + 18}" r="{96 if is_vertical else 120}" fill="{surface}" fill-opacity="0.98" stroke="{accent}" stroke-width="4.5"/>
        {_render_studio_prop(blueprint.primary_prop, left_x, left_y + 18, 0.58 if is_vertical else 0.72, theme, blueprint.custom_prop_svg)}
        """
        beat2_svg = f"""
        <circle cx="{stage_mid_x}" cy="{mid_ov_y}" r="36" fill="{surface}" fill-opacity="0.95" stroke="{accent}" stroke-width="3.5"/>
        {_render_overlay_effect(ov_eff, stage_mid_x, mid_ov_y, theme)}
        """
        beat3_svg = f"""
        <circle cx="{right_x}" cy="{right_y + 8}" r="{hero_disc_r}" fill="{surface}" fill-opacity="0.98" stroke="{accent}" stroke-width="4.5"/>
        <circle cx="{right_x}" cy="{right_y + 8}" r="{hero_disc_r - 11}" fill="{accent}" fill-opacity="0.06"/>
        {_render_studio_character(right_x, right_y - 4, blueprint.character_pose, blueprint.character_expression, theme, scale=0.78 if is_vertical else 0.90, flip_x=not is_vertical, character_style=char_style)}
        """

    elif comp == "quote_spotlight":
        quote_text = (blueprint.sub_phrase if (blueprint.sub_phrase and len(blueprint.sub_phrase) > 10) else blueprint.caption) or ""
        q_lines = _wrap_text_lines(quote_text, 26 if is_vertical else 30, 3)
        q_font = (30 if is_vertical else 32) if len(q_lines) >= 3 else (34 if is_vertical else 36)
        q_start_y = (stage_y + 185) if is_vertical else stage_mid_y - round(max(0, len(q_lines) - 1) * 22)
        text_center_x = stage_mid_x if is_vertical else stage_x + round(stage_w * 0.38)
        bust_x = stage_mid_x if is_vertical else stage_x + round(stage_w * 0.80)
        bust_y = (stage_y + round(stage_h * 0.72)) if is_vertical else stage_mid_y + 20
        bust_r = 128 if is_vertical else 138
        tag_label = (blueprint.left_badge or "TRIẾT LÝ SỐNG")[:22]

        beat1_svg = f"""
        <rect x="{stage_x + 26}" y="{stage_y + 26}" width="{stage_w - 52}" height="{stage_h - 52}" rx="22" fill="{bg}" fill-opacity="0.55" stroke="{ink}" stroke-width="2" stroke-opacity="0.14"/>
        <text x="{stage_x + (66 if is_vertical else 68)}" y="{stage_y + (124 if is_vertical else 132)}" font-family="{FONT_FAMILY}" font-size="140" font-weight="800" fill="{accent}" fill-opacity="0.22">“</text>
        {_render_multiline_text(q_lines, text_center_x, q_start_y, 46, q_font, ink, "800", "middle")}
        """
        beat2_svg = f"""
        <rect x="{text_center_x - 96}" y="{q_start_y + len(q_lines) * 46 + 10}" width="192" height="6" rx="3" fill="{accent}"/>
        <rect x="{text_center_x - 125}" y="{q_start_y + len(q_lines) * 46 + 34}" width="250" height="36" rx="18" fill="{accent}" fill-opacity="0.14" stroke="{accent}" stroke-width="2.5"/>
        <text x="{text_center_x}" y="{q_start_y + len(q_lines) * 46 + 58}" text-anchor="middle" font-family="{FONT_FAMILY}" font-size="18" font-weight="800" fill="{accent}">{_escape_xml(tag_label)}</text>
        """
        beat3_svg = f"""
        <defs>
          <clipPath id="clip-quote-bust">
            <circle cx="{bust_x}" cy="{bust_y - 18}" r="{bust_r - 3}"/>
          </clipPath>
        </defs>
        <circle cx="{bust_x}" cy="{bust_y - 18}" r="{bust_r}" fill="{surface}" stroke="{accent}" stroke-width="4.5"/>
        <g clip-path="url(#clip-quote-bust)">
          {_render_studio_character(bust_x, bust_y + 14, blueprint.character_pose, blueprint.character_expression, theme, scale=1.02 if is_vertical else 1.12, flip_x=not is_vertical, character_style=char_style, waist_up=True)}
        </g>
        <circle cx="{bust_x}" cy="{bust_y - 18}" r="{bust_r}" fill="none" stroke="{accent}" stroke-width="4.5"/>
        """

    elif comp == "closeup_portrait":
        portrait_x = stage_mid_x if is_vertical else stage_x + round(stage_w * 0.36)
        portrait_y = (stage_y + round(stage_h * 0.44)) if is_vertical else stage_mid_y + 42
        portrait_r = 154 if is_vertical else 168
        prop_x = stage_mid_x if is_vertical else stage_x + round(stage_w * 0.78)
        prop_y = (stage_y + round(stage_h * 0.80)) if is_vertical else stage_mid_y - 12

        beat1_svg = f"""
        <circle cx="{portrait_x}" cy="{portrait_y - 34}" r="{188 if is_vertical else 204}" fill="{accent}" fill-opacity="0.08"/>
        <circle cx="{portrait_x}" cy="{portrait_y - 34}" r="{portrait_r}" fill="{bg}" stroke="{accent}" stroke-width="3.5" stroke-dasharray="10 8"/>
        """
        beat2_svg = f"""
        <defs>
          <clipPath id="clip-closeup-bust">
            <circle cx="{portrait_x}" cy="{portrait_y - 34}" r="{portrait_r - 3}"/>
          </clipPath>
        </defs>
        <g clip-path="url(#clip-closeup-bust)">
          {_render_studio_character(portrait_x, portrait_y + 10, blueprint.character_pose, blueprint.character_expression, theme, scale=1.50 if is_vertical else 1.66, character_style=char_style, waist_up=True)}
        </g>
        <circle cx="{portrait_x}" cy="{portrait_y - 34}" r="{portrait_r}" fill="none" stroke="{accent}" stroke-width="3.5"/>
        """
        ov_part = (
            _render_overlay_effect(blueprint.overlay_effect, prop_x + 76, prop_y - 76, theme)
            if blueprint.overlay_effect != "none"
            else ""
        )
        beat3_svg = f"""
        <circle cx="{prop_x}" cy="{prop_y}" r="{84 if is_vertical else 98}" fill="{surface}" stroke="{ink}" stroke-width="4"/>
        {_render_studio_prop(blueprint.primary_prop, prop_x, prop_y, 0.52 if is_vertical else 0.62, theme, blueprint.custom_prop_svg)}
        {ov_part}
        """

    elif comp == "center_metaphor":
        beat1_svg = _render_studio_prop(
            blueprint.primary_prop, stage_mid_x, stage_mid_y - 4, 1.24 if is_vertical else 1.38, theme, blueprint.custom_prop_svg
        )
        if blueprint.overlay_effect != "none":
            ov_x = stage_mid_x if blueprint.overlay_effect == "shield_aura" else stage_mid_x + (145 if is_vertical else 225)
            ov_y = stage_mid_y - 4 if blueprint.overlay_effect == "shield_aura" else stage_mid_y - 95
            beat2_svg = _render_overlay_effect(blueprint.overlay_effect, ov_x, ov_y, theme)
        else:
            beat2_svg = f'<circle cx="{stage_mid_x}" cy="{stage_mid_y - 4}" r="142" fill="none" stroke="{accent}" stroke-width="3" stroke-dasharray="12 10" stroke-opacity="0.45"/>'
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
        beat1_svg = _render_studio_prop(blueprint.primary_prop, left_x, left_y, prop_scale, theme, blueprint.custom_prop_svg)
        ov_eff = "curved_arrow_right" if blueprint.overlay_effect == "none" else blueprint.overlay_effect
        ov_x = left_x if blueprint.overlay_effect == "big_x_crossout" else stage_mid_x
        ov_y = left_y if blueprint.overlay_effect == "big_x_crossout" else stage_mid_y - 12
        beat2_svg = _render_overlay_effect(ov_eff, ov_x, ov_y, theme)
        beat3_svg = _render_studio_character(
            right_x, right_y, blueprint.character_pose, blueprint.character_expression, theme, scale=char_scale, flip_x=not is_vertical, character_style=char_style
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
        {_render_studio_prop(blueprint.primary_prop, left_mid_x, left_mid_y + 22, 0.72 if is_vertical else 0.88, theme, blueprint.custom_prop_svg)}
        """
        beat2_svg = f"""
        {_render_overlay_effect("big_x_crossout", left_mid_x + round(panel_w * 0.28), left_py + (116 if is_vertical else 124), theme)}
        <circle cx="{stage_mid_x}" cy="{stage_mid_y}" r="34" fill="{accent}" stroke="{surface}" stroke-width="5"/>
        <path d="M{stage_mid_x - 12} {stage_mid_y} L{stage_mid_x + 12} {stage_mid_y} M{stage_mid_x + 2} {stage_mid_y - 10} L{stage_mid_x + 14} {stage_mid_y} L{stage_mid_x + 2} {stage_mid_y + 10}" fill="none" stroke="{surface}" stroke-width="5.5" stroke-linecap="round" stroke-linejoin="round"/>
        """
        beat3_svg = f"""
        <rect x="{right_px}" y="{right_py}" width="{panel_w}" height="{panel_h}" rx="20" fill="{accent}" fill-opacity="0.08" stroke="{accent}" stroke-width="4"/>
        <rect x="{right_mid_x - 120}" y="{right_py + 18}" width="240" height="40" rx="20" fill="{accent}"/>
        <text x="{right_mid_x}" y="{right_py + 45}" text-anchor="middle" font-family="{FONT_FAMILY}" font-size="20" font-weight="800" fill="{surface}">{_escape_xml(right_tag)}</text>
        {_render_studio_character(right_mid_x, right_mid_y + 34, blueprint.character_pose, blueprint.character_expression, theme, scale=0.72 if is_vertical else 0.84, character_style=char_style)}
        """

    elif comp == "cause_effect_flow":
        left_x = stage_mid_x if is_vertical else stage_x + round(stage_w * 0.24)
        left_y = stage_y + round(stage_h * 0.24) if is_vertical else stage_mid_y + 18
        right_x = stage_mid_x if is_vertical else stage_x + round(stage_w * 0.76)
        right_y = stage_y + round(stage_h * 0.74) if is_vertical else stage_mid_y - 4
        beat1_svg = _render_studio_character(
            left_x, left_y, blueprint.character_pose, blueprint.character_expression, theme, scale=char_scale * 0.96, character_style=char_style
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
        left_x = (stage_mid_x - 145) if is_vertical else stage_x + round(stage_w * 0.23)
        right_x = (stage_mid_x + 145) if is_vertical else stage_x + round(stage_w * 0.77)
        char_y = (stage_y + 545) if is_vertical else stage_mid_y + 26
        mid_prop_y = (stage_y + 160) if is_vertical else stage_mid_y - 38
        beat1_svg = _render_studio_character(
            left_x,
            char_y,
            blueprint.secondary_pose or "pointing_accuse",
            blueprint.secondary_expression or "angry",
            theme,
            scale=0.78 if is_vertical else 0.96,
            accent_tie=False,
            character_style=char_style,
        )
        beat2_svg = _render_studio_prop(
            blueprint.primary_prop, stage_mid_x, mid_prop_y, 0.68 if is_vertical else 0.84, theme, blueprint.custom_prop_svg
        )
        beat3_svg = _render_studio_character(
            right_x,
            char_y,
            blueprint.character_pose,
            blueprint.character_expression,
            theme,
            scale=0.78 if is_vertical else 0.98,
            flip_x=True,
            accent_tie=True,
            character_style=char_style,
        )

    elif comp == "character_on_pedestal":
        pedestal_y = stage_y + stage_h - 120
        beat1_svg = f"""
        <polygon points="{stage_mid_x - 210},{stage_y + stage_h - 52} {stage_mid_x - 148},{pedestal_y} {stage_mid_x + 148},{pedestal_y} {stage_mid_x + 210},{stage_y + stage_h - 52}" fill="{bg}" stroke="{ink}" stroke-width="5" stroke-linejoin="round"/>
        <line x1="{stage_mid_x - 110}" y1="{pedestal_y + 28}" x2="{stage_mid_x + 110}" y2="{pedestal_y + 28}" stroke="{accent}" stroke-width="5" stroke-linecap="round"/>
        """
        ov_eff = "shield_aura" if blueprint.overlay_effect == "none" else blueprint.overlay_effect
        beat2_svg = _render_overlay_effect(
            ov_eff, stage_mid_x, (pedestal_y - 170) if is_vertical else (stage_mid_y - 26), theme
        )
        beat3_svg = (
            _render_studio_character(
                stage_mid_x,
                pedestal_y - 148,
                blueprint.character_pose,
                blueprint.character_expression,
                theme,
                scale=0.88 if is_vertical else 0.94,
                character_style=char_style,
            )
            + _render_studio_prop(
                blueprint.primary_prop,
                stage_mid_x + (168 if is_vertical else 275),
                (stage_y + 142) if is_vertical else (stage_mid_y - 28),
                0.54 if is_vertical else 0.72,
                theme,
                blueprint.custom_prop_svg,
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
            char_x, char_y, blueprint.character_pose, blueprint.character_expression, theme, scale=0.80 if is_vertical else 0.95, character_style=char_style
        )
        if not is_vertical:
            beat2_svg = (
                f'<path d="M{char_x + 115} {stage_mid_y - 10} L{cards_x - 24} {card_start_y + 46} '
                f'M{char_x + 115} {stage_mid_y - 10} L{cards_x - 24} {card_start_y + 174} '
                f'M{char_x + 115} {stage_mid_y - 10} L{cards_x - 24} {card_start_y + 302}" '
                f'stroke="{accent}" stroke-width="5" stroke-linecap="round" stroke-dasharray="10 8"/>'
            )
        else:
            beat2_svg = f'<line x1="{stage_x + 80}" y1="{stage_y + 365}" x2="{stage_x + stage_w - 80}" y2="{stage_y + 365}" stroke="{accent}" stroke-width="4" stroke-dasharray="10 8" stroke-linecap="round"/>'
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

    elif comp == "timeline_progression":
        node_labels = blueprint.step_items or [
            blueprint.left_badge or "1. Nhận diện",
            "2. Tĩnh lặng",
            blueprint.right_badge or "3. Hành động",
        ]
        nodes = node_labels[:3]
        if is_vertical:
            line_x = stage_x + 92
            beat1_svg = _render_studio_character(
                stage_mid_x + 125, stage_y + 210, blueprint.character_pose, blueprint.character_expression, theme, scale=0.78, character_style=char_style
            )
            node_parts = []
            for idx_n, label in enumerate(nodes):
                ny = stage_y + 165 + idx_n * 195
                clean = re.sub(r"^\d+\.\s*", "", label)
                node_parts.append(
                    f'<circle cx="{line_x}" cy="{ny}" r="24" fill="{accent}" stroke="{surface}" stroke-width="4"/>'
                    f'<text x="{line_x}" y="{ny + 8}" text-anchor="middle" font-family="{FONT_FAMILY}" font-size="22" font-weight="800" fill="{surface}">{idx_n + 1}</text>'
                    f'<rect x="{line_x + 42}" y="{ny - 34}" width="{stage_w - 170}" height="68" rx="16" fill="{bg}" stroke="{ink}" stroke-width="3.5"/>'
                    f'<text x="{line_x + 64}" y="{ny + 8}" text-anchor="start" font-family="{FONT_FAMILY}" font-size="22" font-weight="700" fill="{ink}">{_escape_xml(clean[:24])}</text>'
                )
            beat2_svg = (
                f'<line x1="{line_x}" y1="{stage_y + 120}" x2="{line_x}" y2="{stage_y + 620}" stroke="{accent}" stroke-width="6" stroke-dasharray="10 8" stroke-linecap="round"/>\n'
                + "\n".join(node_parts)
            )
            beat3_svg = _render_studio_prop(
                blueprint.primary_prop, stage_mid_x + 135, stage_y + 650, 0.66, theme, blueprint.custom_prop_svg
            )
        else:
            start_x = stage_x + 190
            step_gap = 370
            track_y = stage_y + 332
            node_parts = []
            for idx_n, label in enumerate(nodes):
                nx = start_x + idx_n * step_gap
                clean = re.sub(r"^\d+\.\s*", "", label)
                node_parts.append(
                    f'<circle cx="{nx}" cy="{track_y}" r="28" fill="{accent}" stroke="{surface}" stroke-width="5"/>'
                    f'<text x="{nx}" y="{track_y + 9}" text-anchor="middle" font-family="{FONT_FAMILY}" font-size="24" font-weight="800" fill="{surface}">{idx_n + 1}</text>'
                    f'<rect x="{nx - 125}" y="{track_y + 46}" width="250" height="54" rx="16" fill="{bg}" stroke="{ink}" stroke-width="3.5"/>'
                    f'<text x="{nx}" y="{track_y + 80}" text-anchor="middle" font-family="{FONT_FAMILY}" font-size="20" font-weight="700" fill="{ink}">{_escape_xml(clean[:22])}</text>'
                )
            beat1_svg = (
                f'<line x1="{start_x}" y1="{track_y}" x2="{start_x + step_gap * 2}" y2="{track_y}" stroke="{accent}" stroke-width="7" stroke-dasharray="12 10" stroke-linecap="round"/>\n'
                + "\n".join(node_parts)
            )
            beat2_svg = _render_studio_prop(
                blueprint.primary_prop, stage_mid_x + 185, stage_y + 148, 0.68, theme, blueprint.custom_prop_svg
            )
            beat3_svg = _render_studio_character(
                stage_mid_x - 185, stage_y + 178, blueprint.character_pose, blueprint.character_expression, theme, scale=0.72, character_style=char_style
            )

    elif comp == "stat_callout_card":
        metric = (blueprint.focal_metric or blueprint.left_badge or "90%")[:12].upper()
        sub_badge = (blueprint.right_badge or "ĐIỂM MẤU CHỐT")[:22]
        card_x = stage_x + (48 if is_vertical else 56)
        card_y = stage_y + (48 if is_vertical else 62)
        card_w = (stage_w - 96) if is_vertical else round(stage_w * 0.44)
        card_h = 260 if is_vertical else (stage_h - 124)
        card_mid_x = round(card_x + card_w / 2)
        card_mid_y = round(card_y + card_h / 2)
        metric_fs = 64 if len(metric) > 5 else 88

        beat1_svg = f"""
        <rect x="{card_x + 10}" y="{card_y + 10}" width="{card_w}" height="{card_h}" rx="24" fill="{ink}" fill-opacity="0.14"/>
        <rect x="{card_x}" y="{card_y}" width="{card_w}" height="{card_h}" rx="24" fill="{accent}"/>
        <rect x="{card_mid_x - 115}" y="{card_y + 28}" width="230" height="36" rx="18" fill="{surface}" fill-opacity="0.2"/>
        <text x="{card_mid_x}" y="{card_y + 52}" text-anchor="middle" font-family="{FONT_FAMILY}" font-size="18" font-weight="800" fill="{surface}">{_escape_xml(sub_badge)}</text>
        <text x="{card_mid_x}" y="{card_mid_y + 24}" text-anchor="middle" font-family="{FONT_FAMILY}" font-size="{metric_fs}" font-weight="900" fill="{surface}">{_escape_xml(metric)}</text>
        """
        beat2_svg = _render_studio_prop(
            blueprint.primary_prop,
            (stage_mid_x - 150) if is_vertical else stage_x + round(stage_w * 0.82),
            (stage_y + 650) if is_vertical else (stage_y + 148),
            0.62 if is_vertical else 0.68,
            theme,
            blueprint.custom_prop_svg,
        )
        beat3_svg = _render_studio_character(
            (stage_mid_x + 120) if is_vertical else stage_x + round(stage_w * 0.66),
            (stage_y + 545) if is_vertical else (stage_mid_y + 34),
            blueprint.character_pose,
            blueprint.character_expression,
            theme,
            scale=0.88 if is_vertical else 0.96,
            flip_x=True,
            character_style=char_style,
        )

    elif comp == "dialogue_debate":
        left_bubble = (blueprint.left_badge or "Phản xạ vội")[:22]
        right_bubble = (blueprint.right_badge or "Bình tĩnh chọn")[:22]
        left_x = (stage_mid_x - 145) if is_vertical else stage_x + round(stage_w * 0.24)
        right_x = (stage_mid_x + 145) if is_vertical else stage_x + round(stage_w * 0.76)
        char_y = (stage_y + 545) if is_vertical else stage_mid_y + 58
        bubble_y = (stage_y + 95) if is_vertical else stage_y + 44

        beat1_svg = f"""
        <rect x="{left_x - 125}" y="{bubble_y}" width="250" height="58" rx="18" fill="{bg}" stroke="{ink}" stroke-width="4"/>
        <text x="{left_x}" y="{bubble_y + 36}" text-anchor="middle" font-family="{FONT_FAMILY}" font-size="20" font-weight="800" fill="{ink}">{_escape_xml(left_bubble)}</text>
        {_render_studio_character(left_x, char_y, blueprint.secondary_pose or "pointing_accuse", blueprint.secondary_expression or "angry", theme, scale=0.76 if is_vertical else 0.90, accent_tie=False, character_style=char_style)}
        """
        mid_prop_cy = (stage_y + 265) if is_vertical else stage_mid_y - 26
        beat2_svg = f"""
        <circle cx="{stage_mid_x}" cy="{mid_prop_cy}" r="{82 if is_vertical else 92}" fill="{surface}" stroke="{accent}" stroke-width="4"/>
        {_render_studio_prop(blueprint.primary_prop, stage_mid_x, mid_prop_cy, 0.50 if is_vertical else 0.58, theme, blueprint.custom_prop_svg)}
        """
        beat3_svg = f"""
        <rect x="{right_x - 125}" y="{bubble_y}" width="250" height="58" rx="18" fill="{accent}"/>
        <text x="{right_x}" y="{bubble_y + 36}" text-anchor="middle" font-family="{FONT_FAMILY}" font-size="20" font-weight="800" fill="{surface}">{_escape_xml(right_bubble)}</text>
        {_render_studio_character(right_x, char_y, blueprint.character_pose, blueprint.character_expression, theme, scale=0.76 if is_vertical else 0.92, flip_x=True, accent_tie=True, character_style=char_style)}
        """

    elif comp == "ai_bespoke_scene":
        sanitized_scene = sanitize_custom_vector_fragment(blueprint.custom_scene_svg, theme)
        if sanitized_scene:
            scene_box_w = stage_w - 64
            scene_box_h = 440 if is_vertical else (stage_h - 72)
            scale_scene = min(scene_box_w / 1000.0, scene_box_h / 420.0)
            offset_x = round(stage_x + (stage_w - 1000.0 * scale_scene) / 2.0)
            offset_y = (stage_y + 56) if is_vertical else round(stage_y + (stage_h - 420.0 * scale_scene) / 2.0)

            beat1_svg = f'<rect x="{stage_x + 26}" y="{stage_y + 26}" width="{stage_w - 52}" height="{stage_h - 52}" rx="20" fill="{bg}" fill-opacity="0.45"/>'
            beat2_svg = f'<g transform="translate({offset_x}, {offset_y}) scale({scale_scene:.4f})">{sanitized_scene}</g>'
            cx_avatar = stage_mid_x if is_vertical else (stage_x + stage_w - 135)
            cy_avatar = (stage_y + 615) if is_vertical else (stage_y + stage_h - 132)
            beat3_svg = f"""
            <circle cx="{cx_avatar}" cy="{cy_avatar}" r="{112 if is_vertical else 96}" fill="{surface}" stroke="{accent}" stroke-width="4.5"/>
            {_render_studio_character(cx_avatar, cy_avatar + 10, blueprint.character_pose, blueprint.character_expression, theme, scale=0.62 if is_vertical else 0.54, flip_x=True, character_style=char_style, waist_up=True)}
            """
        else:
            beat1_svg = _render_studio_prop(
                blueprint.secondary_prop or "sunrise_horizon",
                stage_mid_x if is_vertical else stage_x + round(stage_w * 0.72),
                stage_y + round(stage_h * 0.28) if is_vertical else stage_mid_y - 12,
                0.92 if is_vertical else 1.04,
                theme,
            )
            beat2_svg = _render_studio_prop(
                blueprint.primary_prop,
                stage_mid_x if is_vertical else stage_x + round(stage_w * 0.44),
                stage_y + round(stage_h * 0.54) if is_vertical else stage_mid_y + 8,
                0.88 if is_vertical else 0.98,
                theme,
                blueprint.custom_prop_svg,
            )
            beat3_svg = _render_studio_character(
                stage_mid_x if is_vertical else stage_x + round(stage_w * 0.22),
                stage_y + round(stage_h * 0.78) if is_vertical else stage_mid_y + 28,
                blueprint.character_pose,
                blueprint.character_expression,
                theme,
                scale=0.86 if is_vertical else 0.96,
                character_style=char_style,
            )

    else:  # character_left_prop_right
        left_x = stage_mid_x if is_vertical else stage_x + round(stage_w * 0.28)
        left_y = stage_y + round(stage_h * 0.30) if is_vertical else stage_mid_y + 24
        right_x = stage_mid_x if is_vertical else stage_x + round(stage_w * 0.72)
        right_y = stage_y + round(stage_h * 0.72) if is_vertical else stage_mid_y - 8
        beat1_svg = _render_studio_character(
            left_x, left_y, blueprint.character_pose, blueprint.character_expression, theme, scale=char_scale, character_style=char_style
        )
        if blueprint.overlay_effect != "none":
            ov_x = left_x if blueprint.overlay_effect == "big_x_crossout" else stage_mid_x
            ov_y = left_y - 22 if blueprint.overlay_effect == "big_x_crossout" else stage_mid_y - 10
            beat2_svg = _render_overlay_effect(blueprint.overlay_effect, ov_x, ov_y, theme)
        else:
            beat2_svg = f'<path d="M{left_x + 115} {stage_mid_y} L{right_x - 150} {stage_mid_y}" stroke="{accent}" stroke-width="5" stroke-dasharray="10 8" stroke-linecap="round"/>'
        beat3_svg = _render_studio_prop(
            blueprint.primary_prop, right_x, right_y, prop_scale, theme, blueprint.custom_prop_svg
        )

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
  {stage_frame_svg}
  {header_svg}
  {beat_counter_svg}
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
  {_render_studio_character(854, 416, blueprint.character_pose, blueprint.character_expression, theme, scale=1.18, character_style=resolve_studio_character_style(getattr(blueprint, "character_style", None)))}
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
