"""
src/studio_motion_renderer.py — Động cơ hoạt ảnh Motion Graphics đa lớp 30fps (v3.11 — 1:1 với Local Studio).

Đồng bộ hoàn toàn toàn bộ hiệu ứng cao cấp từ trình duyệt Local (`studioMotionRenderer.ts`) sang
môi trường render CPU GitHub Actions Ubuntu:
1. Tách mỗi Studio SVG thành 5 lớp trong suốt độc lập (`stage`, `beat-1`, `beat-2`, `beat-3`,
   `studio-caption`) + bản `full` cho hiệu ứng hòa tan chuyển nhịp êm dịu.
2. Rasterize mỗi lớp đúng 1 lần duy nhất bằng `rsvg-convert` (hoặc `cairosvg`) và cắt vùng biên
   chứa pixel thực (Tight Alpha Bounding Box) + Premultiplied Alpha để ghép tốc độ cao không viền tối.
3. Phụ đề chạy chữ từng từ khóa chặt theo năng lượng giọng đọc thật (`voice-activity locked`):
   - Tự chậm lại/dừng theo hơi thở và khoảng nghỉ thực tế trong đường bao RMS 30Hz.
   - Hộp phụ đề giữ vững phương ngang, hiển thị tối đa 2 dòng cân giữa.
4. Diễn hoạt điềm tĩnh chuẩn mực biên tập (`v3.11`):
   - Khung sân khấu bên ngoài (`stage`) đứng vững 100%, chỉ chuyển cảnh hòa tan dịu 0.12s.
   - Các lớp nội dung (`beat-1`, `beat-2`, `beat-3`) tiến vào mượt mà bằng `easeOutCubic`/`easeOutQuart`,
     không giật lò xo overshoot, không xoay lắc đầu hay nhấp nháy rung liên hồi.
   - 5 hạt không khí tròn nhẹ nhàng phía sau; bỏ huy hiệu sóng âm 7 cột gây xao nhãng.
   - Tự động căn điểm cắt giữa các beat vào đúng khoảng lặng tự nhiên của giọng đọc (`align_beat_bounds_to_audio_silences`).
"""

from __future__ import annotations

import bisect
import copy
import functools
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
import wave
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

import config

logger = logging.getLogger("studio_motion_renderer")

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)

SUBTITLE_FONT_CANDIDATES: Tuple[str, ...] = (
    os.path.join(config.ASSETS_FONTS_DIR, "NotoSans-Bold.ttf"),
    os.path.join(config.ASSETS_FONTS_DIR, "DejaVuSans-Bold.ttf"),
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-SemiBold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
)


# ==============================================================================
# CẤU TRÚC DỮ LIỆU & MÀU SẮC CHỦ ĐỀ
# ==============================================================================


@dataclass(frozen=True)
class MotionThemeStyle:
    bg_color: str
    ink_color: str
    accent_color: str
    bg_bgr: Tuple[int, int, int]
    ink_bgr: Tuple[int, int, int]
    accent_bgr: Tuple[int, int, int]
    is_dark: bool


@dataclass
class CroppedPremulLayer:
    """Lớp đồ họa BGRA đã cắt gọn theo vùng pixel có độ mờ > 0 và premultiply alpha."""

    premul_bgra: np.ndarray  # shape (bh, bw, 4), uint8: [pB, pG, pR, A]
    bx: int
    by: int
    bw: int
    bh: int


@dataclass
class WordSpriteSlot:
    """Một từ đã pre-render sẵn 2 biến thể (màu mực chuẩn & màu nhấn đang đọc) với tọa độ cố định."""

    global_idx: int
    page_idx: int
    start_p: float
    end_p: float
    x: float
    y: float
    w: float
    ink_layer: Optional[CroppedPremulLayer]
    accent_layer: Optional[CroppedPremulLayer]


@dataclass
class SubtitlePlan:
    font_size: float
    line_height: float
    cap_box_y: float
    cap_box_h: float
    cap_center_y: float
    pages: List[List[WordSpriteSlot]]
    word_page_map: List[Tuple[float, float, int]]  # (start_p, end_p, page_idx)


@dataclass
class MotionBeatAsset:
    """Toàn bộ các lớp bitmap và bảng từ phụ đề đã rasterize sẵn cho 1 beat."""

    has_layers: bool
    has_header: bool
    width: int
    height: int
    full_layer: Optional[CroppedPremulLayer]
    stage_layer: Optional[CroppedPremulLayer] = None
    beat1_layer: Optional[CroppedPremulLayer] = None
    beat2_layer: Optional[CroppedPremulLayer] = None
    beat3_layer: Optional[CroppedPremulLayer] = None
    caption_layer: Optional[CroppedPremulLayer] = None
    subtitle_plan: Optional[SubtitlePlan] = None


def _hex_to_rgb(hex_str: str, fallback: Tuple[int, int, int]) -> Tuple[int, int, int]:
    cleaned = (hex_str or "").strip().lstrip("#")
    if len(cleaned) == 3:
        cleaned = "".join(ch * 2 for ch in cleaned)
    if len(cleaned) == 6:
        try:
            return (
                int(cleaned[0:2], 16),
                int(cleaned[2:4], 16),
                int(cleaned[4:6], 16),
            )
        except ValueError:
            pass
    return fallback


def build_motion_theme_style(
    bg_color: Optional[str] = None,
    ink_color: Optional[str] = None,
    accent_color: Optional[str] = None,
) -> MotionThemeStyle:
    bg_hex = (bg_color or getattr(config, "WHITEBOARD_BG_COLOR", "#EEF2F7")).strip()
    ink_hex = (ink_color or getattr(config, "WHITEBOARD_INK_COLOR", "#0F172A")).strip()
    accent_hex = (accent_color or getattr(config, "WHITEBOARD_ACCENT_COLOR", "#2563EB")).strip()

    bg_rgb = _hex_to_rgb(bg_hex, (238, 242, 247))
    ink_rgb = _hex_to_rgb(ink_hex, (15, 23, 42))
    accent_rgb = _hex_to_rgb(accent_hex, (37, 99, 235))

    luminance = (0.299 * bg_rgb[0] + 0.587 * bg_rgb[1] + 0.114 * bg_rgb[2]) / 255.0
    is_dark = luminance < 0.46

    return MotionThemeStyle(
        bg_color=bg_hex,
        ink_color=ink_hex,
        accent_color=accent_hex,
        bg_bgr=(bg_rgb[2], bg_rgb[1], bg_rgb[0]),
        ink_bgr=(ink_rgb[2], ink_rgb[1], ink_rgb[0]),
        accent_bgr=(accent_rgb[2], accent_rgb[1], accent_rgb[0]),
        is_dark=is_dark,
    )


@functools.lru_cache(maxsize=8)
def _resolve_subtitle_font_path() -> Optional[str]:
    for path in SUBTITLE_FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    fc_match = shutil.which("fc-match")
    if fc_match:
        for query in ("Noto Sans:bold", "DejaVu Sans:bold", "sans-serif:bold"):
            proc = subprocess.run([fc_match, query, "-f", "%{file}"], capture_output=True, text=True)
            candidate = proc.stdout.strip()
            if proc.returncode == 0 and candidate and os.path.exists(candidate):
                return candidate
    return None


@functools.lru_cache(maxsize=16)
def _load_subtitle_font(pixel_size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_path = _resolve_subtitle_font_path()
    if font_path:
        try:
            return ImageFont.truetype(font_path, size=max(12, pixel_size))
        except OSError:
            pass
    return ImageFont.load_default()


# ==============================================================================
# TRÍCH XUẤT ĐƯỜNG BAO NĂNG LƯỢNG GIỌNG ĐỌC THẬT (30HZ RMS)
# ==============================================================================


def _read_audio_mono_float(audio_path: Path, target_rate: int = 24000) -> Tuple[np.ndarray, int]:
    """Đọc mọi file audio (.wav / .mp3 / .m4a) thành mảng mono float32 chuẩn hóa [-1, 1]."""
    if audio_path.suffix.lower() == ".wav":
        try:
            with wave.open(str(audio_path), "rb") as wf:
                channels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
                rate = wf.getframerate()
                nframes = wf.getnframes()
                raw = wf.readframes(nframes)
            if raw and rate > 0 and channels >= 1:
                if sampwidth == 1:
                    arr = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
                elif sampwidth == 2:
                    arr = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
                elif sampwidth == 3:
                    raw_u8 = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
                    vals = (
                        raw_u8[:, 0].astype(np.int32)
                        | (raw_u8[:, 1].astype(np.int32) << 8)
                        | (raw_u8[:, 2].astype(np.int32) << 16)
                    )
                    vals = np.where(vals >= 0x800000, vals - 0x1000000, vals)
                    arr = vals.astype(np.float32) / 8388608.0
                elif sampwidth == 4:
                    arr = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
                else:
                    arr = np.array([], dtype=np.float32)

                if arr.size > 0:
                    if channels > 1:
                        arr = arr[: (arr.size // channels) * channels].reshape(-1, channels)[:, 0]
                    return arr, rate
        except Exception:
            pass

    # Dự phòng đa năng (hỗ trợ .mp3 từ Cloud TTS hoặc WAV nén) qua ffmpeg stdout
    proc = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(audio_path),
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ac",
            "1",
            "-ar",
            str(target_rate),
            "pipe:1",
        ],
        capture_output=True,
    )
    if proc.returncode == 0 and proc.stdout:
        pcm = np.frombuffer(proc.stdout, dtype="<i2").astype(np.float32) / 32768.0
        return pcm, target_rate

    return np.array([], dtype=np.float32), target_rate


def extract_audio_energy_envelope(audio_path: Path, samples_per_sec: int = 30) -> List[float]:
    """
    Trích xuất đường bao năng lượng giọng nói (RMS amplitude 30 mẫu/giây, chuẩn hóa 0..1)
    khớp 100% công thức `extractAudioEnergyEnvelope` trên Local Browser.
    """
    if not audio_path.exists():
        return []
    samples, rate = _read_audio_mono_float(audio_path)
    if samples.size == 0 or rate <= 0:
        return []

    step = max(1, int(rate // max(1, samples_per_sec)))
    raw_rms: List[float] = []
    peak = 0.001

    total = samples.size
    for idx in range(0, total, step):
        chunk = samples[idx : min(total, idx + step)]
        if chunk.size == 0:
            continue
        rms = float(np.sqrt(np.mean(chunk * chunk)))
        if rms > peak:
            peak = rms
        raw_rms.append(rms)

    smoothed: List[float] = []
    prev = 0.0
    norm_div = peak * 0.78
    for r in raw_rms:
        norm = min(1.0, r / norm_div)
        nxt = (prev * 0.45 + norm * 0.55) if norm > prev else (prev * 0.76 + norm * 0.24)
        smoothed.append(nxt)
        prev = nxt
    return smoothed


def sample_audio_energy(
    envelope: List[float],
    local_time_sec: float,
    samples_per_sec: int = 30,
) -> float:
    if not envelope:
        return 0.25
    idx = max(0, min(len(envelope) - 1, int(math.floor(local_time_sec * samples_per_sec))))
    return envelope[idx]


# ==============================================================================
# TÁCH SVG STUDIO THÀNH 5 LỚP TRONG SUỐT ĐỘC LẬP & RASTERIZE TỐI ƯU ROI
# ==============================================================================


def _local_tag(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _is_full_canvas_bg_rect(el: ET.Element, vb_w: str, vb_h: str) -> bool:
    if _local_tag(el.tag).lower() != "rect":
        return False
    x = (el.attrib.get("x") or "0").strip()
    y = (el.attrib.get("y") or "0").strip()
    rw = (el.attrib.get("width") or "").strip()
    rh = (el.attrib.get("height") or "").strip()
    return x in ("0", "0px") and y in ("0", "0px") and rw == vb_w and rh == vb_h


def _strip_text_nodes(el: ET.Element) -> ET.Element:
    """Loại bỏ chữ `<text>`/`<tspan>` khỏi bản sao thẻ `#studio-caption` để thay bằng sub chạy từng từ."""
    cloned = copy.deepcopy(el)
    for parent in cloned.iter():
        for child in list(parent):
            if _local_tag(child.tag).lower() in ("text", "tspan"):
                parent.remove(child)
    return cloned


def _make_svg_with_children(root_attrib: Dict[str, str], children: List[ET.Element]) -> str:
    new_root = ET.Element(f"{{{SVG_NS}}}svg", dict(root_attrib))
    for child in children:
        new_root.append(child)
    return ET.tostring(new_root, encoding="unicode")


def split_studio_svg_layers(
    svg_markup: str,
    strip_caption_text: bool = False,
) -> Dict[str, Optional[str] | bool]:
    """
    Tách SVG Studio thành 5 SVG con cùng `viewBox` (đồng nhất 100% hệ tọa độ) nhưng tách rời hoàn toàn:
    - `full`: SVG đầy đủ gốc
    - `stage`: nền sân khấu & tiêu đề chương (đã bỏ rect nền đặc full-canvas để lộ hạt không khí)
    - `beat1`: chỉ `#beat-1`
    - `beat2`: chỉ `#beat-2`
    - `beat3`: chỉ `#beat-3`
    - `caption`: chỉ `#studio-caption` (khi `strip_caption_text=True` chỉ giữ khung thẻ + thanh nhấn trái)
    """
    try:
        root = ET.fromstring(svg_markup.encode("utf-8"))
    except ET.ParseError as exc:
        logger.warning("[SVG SPLIT] Không parse được SVG XML (%s) -> fallback 1 lớp.", exc)
        return {
            "full": svg_markup,
            "stage": None,
            "beat1": None,
            "beat2": None,
            "beat3": None,
            "caption": None,
            "has_header": False,
        }

    root_attrib = {k: v for k, v in root.attrib.items() if not k.startswith("xmlns")}
    vb_parts = (root.attrib.get("viewBox") or "").split()
    vb_w = vb_parts[2] if len(vb_parts) >= 4 else (root.attrib.get("width") or "1280").strip()
    vb_h = vb_parts[3] if len(vb_parts) >= 4 else (root.attrib.get("height") or "720").strip()

    defs_elements: List[ET.Element] = []
    stage_children: List[ET.Element] = []
    beat1_children: List[ET.Element] = []
    beat2_children: List[ET.Element] = []
    beat3_children: List[ET.Element] = []
    caption_children: List[ET.Element] = []
    has_header = False

    for child in list(root):
        ltag = _local_tag(child.tag).lower()
        cid = (child.attrib.get("id") or "").strip()

        if cid == "studio-header":
            has_header = True

        if ltag in ("defs", "style"):
            defs_elements.append(child)
        elif cid == "beat-1":
            beat1_children.append(child)
        elif cid == "beat-2":
            beat2_children.append(child)
        elif cid == "beat-3":
            beat3_children.append(child)
        elif cid == "studio-caption":
            caption_children.append(_strip_text_nodes(child) if strip_caption_text else child)
        else:
            if _is_full_canvas_bg_rect(child, vb_w, vb_h):
                continue
            stage_children.append(child)

    if not beat1_children or not beat2_children or not beat3_children:
        return {
            "full": svg_markup,
            "stage": None,
            "beat1": None,
            "beat2": None,
            "beat3": None,
            "caption": None,
            "has_header": has_header,
        }

    return {
        "full": svg_markup,
        "stage": _make_svg_with_children(root_attrib, defs_elements + stage_children),
        "beat1": _make_svg_with_children(root_attrib, defs_elements + beat1_children),
        "beat2": _make_svg_with_children(root_attrib, defs_elements + beat2_children),
        "beat3": _make_svg_with_children(root_attrib, defs_elements + beat3_children),
        "caption": (
            _make_svg_with_children(root_attrib, defs_elements + caption_children)
            if caption_children
            else None
        ),
        "has_header": has_header,
    }


def _rasterize_svg_to_bgra(svg_markup: str, width: int, height: int) -> Optional[np.ndarray]:
    """Rasterize 1 SVG string thành mảng NumPy BGRA trong suốt kích thước (height, width, 4)."""
    rsvg_bin = shutil.which("rsvg-convert")
    with tempfile.NamedTemporaryFile("w", suffix=".svg", encoding="utf-8", delete=False) as ts:
        ts.write(svg_markup)
        tmp_svg = Path(ts.name)
    tmp_png = tmp_svg.with_suffix(".png")

    try:
        if rsvg_bin:
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
                    str(tmp_png),
                    str(tmp_svg),
                ],
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0 and tmp_png.exists() and tmp_png.stat().st_size > 0:
                img = cv2.imread(str(tmp_png), cv2.IMREAD_UNCHANGED)
                if img is not None:
                    return _ensure_bgra(img, width, height)

        import cairosvg  # type: ignore

        cairosvg.svg2png(
            bytestring=svg_markup.encode("utf-8"),
            write_to=str(tmp_png),
            output_width=width,
            output_height=height,
        )
        if tmp_png.exists() and tmp_png.stat().st_size > 0:
            img = cv2.imread(str(tmp_png), cv2.IMREAD_UNCHANGED)
            if img is not None:
                return _ensure_bgra(img, width, height)
    except Exception as exc:
        logger.warning("[SVG LAYER RASTERIZE WARNING] %s", exc)
    finally:
        tmp_svg.unlink(missing_ok=True)
        tmp_png.unlink(missing_ok=True)

    return None


def _ensure_bgra(img: np.ndarray, width: int, height: int) -> np.ndarray:
    if img.shape[1] != width or img.shape[0] != height:
        img = cv2.resize(img, (width, height), interpolation=cv2.INTER_AREA)
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    elif img.shape[2] == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    return img


def _crop_to_premul_layer(bgra: Optional[np.ndarray], offset_x: int = 0, offset_y: int = 0) -> Optional[CroppedPremulLayer]:
    """Cắt bỏ toàn bộ vùng trong suốt xung quanh và premultiply RGB theo alpha."""
    if bgra is None or bgra.size == 0:
        return None
    h, w = bgra.shape[:2]
    alpha = bgra[:, :, 3]
    ys, xs = np.nonzero(alpha > 0)
    if ys.size == 0 or xs.size == 0:
        return None

    bx0 = max(0, int(xs.min()) - 2)
    by0 = max(0, int(ys.min()) - 2)
    bx1 = min(w, int(xs.max()) + 3)
    by1 = min(h, int(ys.max()) + 3)

    crop = bgra[by0:by1, bx0:bx1].astype(np.float32)
    a_norm = crop[:, :, 3:4] / 255.0
    crop[:, :, :3] = crop[:, :, :3] * a_norm
    premul = np.clip(crop, 0.0, 255.0).astype(np.uint8)

    return CroppedPremulLayer(
        premul_bgra=premul,
        bx=bx0 + offset_x,
        by=by0 + offset_y,
        bw=bx1 - bx0,
        bh=by1 - by0,
    )


# ==============================================================================
# BỘ DỰNG PHỤ ĐỀ & CĂN ĐIỂM CẮT BEAT KHỚP GIỌNG ĐỌC (VOICE-ACTIVITY LOCKED)
# ==============================================================================


def align_beat_bounds_to_audio_silences(
    weights: List[float],
    energy_envelope: Optional[List[float]],
    duration_sec: float,
    samples_per_sec: int = 30,
) -> List[float]:
    """
    Tự động căn ranh giới chuyển beat vào các khoảng lặng tự nhiên của giọng đọc
    (silence valleys ±0.65s) để hình ảnh không bao giờ cắt đột ngột giữa âm tiết đang nói.
    Trả về danh sách thời lượng từng beat `[d0, d1, ...]` có tổng đúng bằng `duration_sec`.
    """
    n = len(weights)
    if n <= 0:
        return [max(0.4, float(duration_sec))]
    if n == 1 or duration_sec <= 0.1:
        return [max(0.4, float(duration_sec))]

    safe_w = [max(1.0, float(w or 1.0)) for w in weights]
    total_w = sum(safe_w) or float(n)
    prop_times: List[float] = []
    acc = 0.0
    for k in range(n - 1):
        acc += safe_w[k]
        prop_times.append((acc / total_w) * duration_sec)

    if not energy_envelope or len(energy_envelope) < 10 or duration_sec < 2.2:
        cuts = [0.0, *prop_times, duration_sec]
        return [max(0.35, cuts[i + 1] - cuts[i]) for i in range(n)]

    min_beat_dur = min(1.1, (duration_sec / n) * 0.55)
    cuts_sec: List[float] = [0.0]
    prev_cut = 0.0

    for k in range(n - 1):
        target_t = prop_times[k]
        low_bound = prev_cut + min_beat_dur
        high_bound = duration_sec - (n - 1 - k) * min_beat_dur
        if high_bound <= low_bound:
            fallback_cut = max(prev_cut + 0.25, min(duration_sec - 0.25, target_t))
            cuts_sec.append(fallback_cut)
            prev_cut = fallback_cut
            continue

        target_idx = int(round(target_t * samples_per_sec))
        win_radius = max(2, int(round(min(0.65, (duration_sec / n) * 0.35) * samples_per_sec)))
        idx_start = max(int(math.ceil(low_bound * samples_per_sec)), target_idx - win_radius)
        idx_end = min(int(math.floor(high_bound * samples_per_sec)), target_idx + win_radius)

        best_idx = max(idx_start, min(idx_end, target_idx))
        best_score = -1e9
        env_len = len(energy_envelope)
        for idx in range(idx_start, idx_end + 1):
            w0 = max(0, idx - 2)
            w1 = min(env_len - 1, idx + 2)
            if w1 >= w0:
                local_mean = sum(energy_envelope[w0 : w1 + 1]) / float(w1 - w0 + 1)
            else:
                local_mean = 0.25
            dist_penalty = 0.08 * (abs(idx - target_idx) / float(max(1, win_radius)))
            score = 1.0 - local_mean - dist_penalty
            if score > best_score:
                best_score = score
                best_idx = idx

        snapped = max(low_bound, min(high_bound, best_idx / float(samples_per_sec)))
        cuts_sec.append(snapped)
        prev_cut = snapped

    cuts_sec.append(duration_sec)
    durs = [max(0.35, cuts_sec[i + 1] - cuts_sec[i]) for i in range(n)]
    scale = duration_sec / max(0.1, sum(durs))
    return [d * scale for d in durs]


def _normalize_token_for_match(token: str) -> str:
    return re.sub(
        r"""^[.,!?;:"'()\[\]…—–\-«»“”‘’]+|[.,!?;:"'()\[\]…—–\-«»“”‘’]+$""",
        "",
        token.lower(),
    )


def reconcile_visual_beats_to_narration(
    narration: str,
    beats: List[Dict[str, Any]] | List[str],
) -> List[str]:
    """
    Chuẩn hóa danh sách cụm `phrase` của các visual_beats thành phân hoạch LIỀN MẠCH 100%
    của toàn bộ lời thoại `narration` (không thiếu từ, không bỏ sót liên từ, giữ nguyên dấu câu).
    """
    clean_nar = re.sub(r"\s+", " ", (narration or "").strip())
    k = len(beats)
    if k <= 0:
        return []

    def _raw_phrase(b: Any) -> str:
        if isinstance(b, str):
            return b.strip()
        if isinstance(b, dict):
            return str(b.get("phrase") or "").strip()
        return ""

    if not clean_nar:
        return [_raw_phrase(b) for b in beats]

    words = [w for w in clean_nar.split(" ") if w]
    n = len(words)
    if k == 1 or n <= k:
        if k == 1:
            return [clean_nar]
        out: List[str] = []
        for i in range(k):
            s = (i * n) // k
            e = ((i + 1) * n) // k
            piece = " ".join(words[s:max(s, e)])
            out.append(piece if piece else (words[min(n - 1, i)] if words else ""))
        return out

    norm_nar = [_normalize_token_for_match(w) for w in words]
    beat_norm_words = [
        [_normalize_token_for_match(t) for t in re.split(r"\s+", _raw_phrase(b)) if _normalize_token_for_match(t)]
        for b in beats
    ]

    splits: List[int] = [0]
    matched_count = 0
    cursor = 1

    for b in range(1, k):
        bw = beat_norm_words[b]
        min_idx = cursor
        max_idx = n - (k - b)
        found_idx = -1

        if bw and max_idx >= min_idx:
            for len_try in range(min(2, len(bw)), 0, -1):
                if found_idx >= 0:
                    break
                for idx in range(min_idx, max_idx + 1):
                    if idx + len_try <= n and all(norm_nar[idx + j] == bw[j] for j in range(len_try)):
                        found_idx = idx
                        break

        if found_idx >= min_idx:
            splits.append(found_idx)
            cursor = found_idx + 1
            matched_count += 1
        else:
            splits.append(-1)
            cursor = min(max_idx + 1, cursor + 1)

    splits.append(n)
    valid_match_ratio = 1.0 if k <= 1 else (matched_count / float(k - 1))
    if valid_match_ratio >= 0.5:
        for b in range(1, k):
            if splits[b] >= 0:
                continue
            next_known_b = b + 1
            while next_known_b < k and splits[next_known_b] < 0:
                next_known_b += 1
            prev_bound = splits[b - 1]
            next_bound = splits[next_known_b]
            gap_beats = next_known_b - (b - 1)
            raw_target = int(round(prev_bound + ((next_bound - prev_bound) * 1.0) / gap_beats))
            splits[b] = max(prev_bound + 1, min(next_bound - (k - b), raw_target))

        out_phrases: List[str] = []
        all_valid = True
        for b in range(k):
            s = splits[b]
            e = splits[b + 1]
            if e <= s:
                all_valid = False
                break
            out_phrases.append(" ".join(words[s:e]))
        if all_valid and sum(len(p.split()) for p in out_phrases) == n:
            return out_phrases

    hint_weights = [max(2, len(_raw_phrase(b).split())) for b in beats]
    total_hint_w = sum(hint_weights) or k
    fallback_splits: List[int] = [0]
    acc_w = 0
    prev_cut = 0
    for b in range(k - 1):
        acc_w += hint_weights[b]
        target = int(round((acc_w / float(total_hint_w)) * n))
        low = prev_cut + 1
        high = n - (k - 1 - b)
        best = max(low, min(high, target))
        best_score = -1e9
        for cand in range(max(low, best - 3), min(high, best + 3) + 1):
            prev_tok = words[cand - 1] if cand > 0 else ""
            punct_bonus = 4.0 if prev_tok.endswith((".", "?", "!", "…")) else (2.5 if prev_tok.endswith((",", ";", ":")) else 0.0)
            score = punct_bonus - abs(cand - target) * 0.65
            if score > best_score:
                best_score = score
                best = cand
        fallback_splits.append(best)
        prev_cut = best
    fallback_splits.append(n)

    return [" ".join(words[fallback_splits[b] : fallback_splits[b + 1]]) for b in range(k)]


def _compute_speech_token_weight(word: str) -> float:
    clean = re.sub(r"""[.,!?;:"'()\[\]…—–-]""", "", word)
    clen = len(clean)
    syllable_est = 1.55 + min(9, clen) * 0.28 + max(0, clen - 6) * 0.14
    punct_pause = 0.0
    if word.endswith((",", ";", ":")):
        punct_pause = 1.15
    elif word.endswith((".", "?", "!", "…")):
        punct_pause = 2.0
    return syllable_est + punct_pause


def compute_word_speech_schedule(
    words: List[str],
    energy_envelope: Optional[List[float]] = None,
    audio_duration_sec: Optional[float] = None,
    total_duration_sec: Optional[float] = None,
) -> List[Tuple[float, float]]:
    """
    Tính dải tiến trình `[start_p, end_p]` cho từng từ dựa theo trọng số âm tiết cân bằng +
    dấu ngắt câu + đường bao giọng đọc 30Hz (tự nhận diện vùng bắt đầu/kết thúc âm thanh thật,
    loại bỏ khoảng lặng đầu/cuối/padding và chậm lại tại khoảng thở giữa câu).
    """
    if not words:
        return []
    weights = [_compute_speech_token_weight(w) for w in words]
    total_w = sum(weights) or float(len(words))

    has_ratio = (
        audio_duration_sec is not None
        and audio_duration_sec > 0.1
        and total_duration_sec is not None
        and total_duration_sec >= audio_duration_sec
    )
    audio_frac = min(1.0, float(audio_duration_sec) / float(total_duration_sec)) if has_ratio else 1.0

    active_start_frac = 0.005 * audio_frac
    active_end_frac = (0.985 if has_ratio else 0.96) * audio_frac
    cdf: Optional[List[float]] = None

    if energy_envelope and len(energy_envelope) >= 6:
        m = len(energy_envelope)
        first_active = -1
        last_active = -1
        for i, val in enumerate(energy_envelope):
            if float(val) >= 0.085:
                if first_active < 0:
                    first_active = i
                last_active = i
        if first_active >= 0 and last_active > first_active + 1:
            a0 = max(0, first_active - 1)
            a1 = min(m - 1, last_active + 2)
            active_start_frac = (a0 / float(m)) * audio_frac
            active_end_frac = ((a1 + 1) / float(m)) * audio_frac

            sub_len = a1 - a0 + 1
            cdf = [0.0] * (sub_len + 1)
            for i in range(sub_len):
                e = _clamp01(float(energy_envelope[a0 + i]))
                act = 0.06 if e < 0.075 else (0.50 + e * 1.05)
                cdf[i + 1] = cdf[i] + act
            total_act = cdf[sub_len] or 1.0
            for i in range(sub_len + 1):
                cdf[i] /= total_act

    speak_span = max(0.05, active_end_frac - active_start_frac)

    def _map_u(u_raw: float) -> float:
        u = _clamp01(u_raw)
        if not cdf:
            return active_start_frac + u * speak_span
        m = len(cdf) - 1
        lo = bisect.bisect_right(cdf, u) - 1
        lo = max(0, min(m - 1, lo))
        span = max(1e-6, cdf[lo + 1] - cdf[lo])
        frac = _clamp01((u - cdf[lo]) / span)
        t_norm = (lo + frac) / float(m)
        return active_start_frac + t_norm * speak_span

    schedule: List[Tuple[float, float]] = []
    acc = 0.0
    for wt in weights:
        s = _map_u(acc / total_w)
        acc += wt
        e = max(s + 0.004, _map_u(acc / total_w))
        schedule.append((s, e))
    return schedule


def schedule_scene_speech_and_beats(
    narration: str,
    beat_phrases: List[str],
    energy_envelope: Optional[List[float]],
    audio_duration_sec: float,
    trailing_gap_sec: float = 0.0,
    samples_per_sec: int = 30,
) -> Tuple[List[str], List[float], List[List[Tuple[float, float]]]]:
    """
    Đồng bộ toàn bộ các beat & phụ đề của 1 cảnh trực tiếp trên trục thời gian âm thanh thực tế:
    1. Phân hoạch 100% `narration` (không bỏ sót từ nào) vào các beat.
    2. Định lịch từng từ trên toàn `audio_duration_sec` (đã tách riêng khỏi `trailing_gap_sec`).
    3. Đặt ranh giới cắt beat tại khoảng nghỉ giữa từ cuối beat k và từ đầu beat k+1.
    Trả về `(reconciled_phrases, beat_durations_with_trailing, beat_word_ranges)`.
    """
    total_render_dur = max(0.2, float(audio_duration_sec) + max(0.0, float(trailing_gap_sec)))
    reconciled = reconcile_visual_beats_to_narration(narration, beat_phrases)

    full_words: List[str] = []
    beat_slices: List[Tuple[int, int]] = []
    for ph in reconciled:
        w_list = [w for w in re.split(r"\s+", ph.strip()) if w]
        s_w = len(full_words)
        full_words.extend(w_list)
        beat_slices.append((s_w, len(full_words)))

    k = max(1, len(beat_slices))
    if not full_words:
        eq = total_render_dur / float(k)
        return reconciled, [eq] * k, [[] for _ in range(k)]

    full_norm = compute_word_speech_schedule(
        full_words,
        energy_envelope=energy_envelope,
        audio_duration_sec=audio_duration_sec,
        total_duration_sec=audio_duration_sec,
    )
    word_times_sec = [(sp * audio_duration_sec, ep * audio_duration_sec) for sp, ep in full_norm]

    cuts_sec: List[float] = [0.0]
    for b in range(k - 1):
        prev_end_idx = beat_slices[b][1] - 1
        next_start_idx = beat_slices[b + 1][0]
        if prev_end_idx < 0 or next_start_idx >= len(word_times_sec):
            cuts_sec.append(min(audio_duration_sec, ((b + 1) / float(k)) * audio_duration_sec))
            continue

        t_after_prev = word_times_sec[prev_end_idx][1]
        t_before_next = word_times_sec[next_start_idx][0]
        ideal_cut = 0.5 * (t_after_prev + t_before_next)

        low_bound = max(cuts_sec[b] + 0.35, word_times_sec[max(0, prev_end_idx - 1)][0])
        high_bound = min(
            audio_duration_sec - 0.25 * (k - 1 - b),
            word_times_sec[min(len(word_times_sec) - 1, next_start_idx)][1],
        )
        chosen_cut = max(low_bound, min(high_bound if high_bound > low_bound else low_bound, ideal_cut))

        if energy_envelope and len(energy_envelope) >= 10 and high_bound > low_bound + 0.08:
            target_idx = int(round(ideal_cut * samples_per_sec))
            win_r = max(1, int(round(0.24 * samples_per_sec)))
            idx_start = max(int(math.ceil(low_bound * samples_per_sec)), target_idx - win_r)
            idx_end = min(int(math.floor(high_bound * samples_per_sec)), target_idx + win_r)
            if idx_end >= idx_start:
                best_idx = max(idx_start, min(idx_end, target_idx))
                best_score = -1e9
                env_len = len(energy_envelope)
                for idx in range(idx_start, idx_end + 1):
                    w0 = max(0, idx - 1)
                    w1 = min(env_len - 1, idx + 1)
                    local_mean = sum(energy_envelope[w0 : w1 + 1]) / float(max(1, w1 - w0 + 1))
                    dist_penalty = 0.18 * (abs(idx - target_idx) / float(max(1, win_r)))
                    score = 1.0 - local_mean - dist_penalty
                    if score > best_score:
                        best_score = score
                        best_idx = idx
                chosen_cut = max(low_bound, min(high_bound, best_idx / float(samples_per_sec)))

        cuts_sec.append(chosen_cut)

    cuts_sec.append(total_render_dur)
    beat_durs = [max(0.35, cuts_sec[b + 1] - cuts_sec[b]) for b in range(k)]

    beat_word_ranges: List[List[Tuple[float, float]]] = []
    for b in range(k):
        b_start = cuts_sec[b]
        b_end = cuts_sec[b + 1]
        b_dur = max(0.05, b_end - b_start)
        s_w, e_w = beat_slices[b]
        local_ranges: List[Tuple[float, float]] = []
        for wi in range(s_w, e_w):
            ws, we = word_times_sec[wi]
            sp = max(0.0, min(0.99, (ws - b_start) / b_dur))
            ep = max(sp + 0.004, min(1.0, (we - b_start) / b_dur))
            local_ranges.append((sp, ep))
        beat_word_ranges.append(local_ranges)

    return reconciled, beat_durs, beat_word_ranges


def _render_word_premul_sprite(
    word: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    slot_x: float,
    slot_y: float,
    color_bgr: Tuple[int, int, int],
) -> Optional[CroppedPremulLayer]:
    """Pre-render 1 từ bằng Pillow FreeType ra lớp premultiplied BGRA giữ trọn dấu tiếng Việt."""
    try:
        l, t, r, b = font.getbbox(word, anchor="lm")
    except Exception:
        l, t, r, b = font.getbbox(word)
        t = t - (b - t) // 2
        b = (b - t) // 2

    pad = 3
    pw = max(4, int(math.ceil(r - l)) + pad * 2)
    ph = max(4, int(math.ceil(b - t)) + pad * 2)

    img = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    rgb = (color_bgr[2], color_bgr[1], color_bgr[0], 255)
    try:
        draw.text((pad - l, pad - t), word, font=font, fill=rgb, anchor="lm")
    except Exception:
        draw.text((pad, pad), word, font=font, fill=rgb)

    rgba = np.array(img, dtype=np.uint8)
    bgra = rgba[:, :, [2, 1, 0, 3]]
    origin_x = int(round(slot_x)) + int(math.floor(l)) - pad
    origin_y = int(round(slot_y)) + int(math.floor(t)) - pad
    return _crop_to_premul_layer(bgra, offset_x=origin_x, offset_y=origin_y)


def build_subtitle_plan_for_box(
    text: str,
    box_x: float,
    box_y: float,
    box_w: float,
    box_h: float,
    base_font_size: float,
    single_line_font_size: float,
    max_lines_per_page: int,
    ink_bgr: Tuple[int, int, int],
    accent_bgr: Tuple[int, int, int],
    prerender_sprites: bool = True,
    energy_envelope: Optional[List[float]] = None,
    word_ranges: Optional[List[Tuple[float, float]]] = None,
    audio_duration_sec: Optional[float] = None,
    total_duration_sec: Optional[float] = None,
) -> SubtitlePlan:
    """Đo và chia toàn bộ phụ đề thành các trang tối đa 2–3 dòng cố định vị trí từng từ."""
    words = [w for w in re.split(r"\s+", text.strip()) if w]
    if not words:
        return SubtitlePlan(
            font_size=base_font_size,
            line_height=base_font_size * 1.28,
            cap_box_y=box_y,
            cap_box_h=box_h,
            cap_center_y=box_y + box_h / 2.0,
            pages=[],
            word_page_map=[],
        )

    if word_ranges and len(word_ranges) == len(words):
        words_range = word_ranges
    else:
        words_range = compute_word_speech_schedule(
            words,
            energy_envelope=energy_envelope,
            audio_duration_sec=audio_duration_sec,
            total_duration_sec=total_duration_sec,
        )

    def _measure(f_size: float):
        fnt = _load_subtitle_font(int(round(f_size)))
        try:
            space_w = float(fnt.getlength(" "))
            widths = [float(fnt.getlength(w)) for w in words]
        except Exception:
            space_w = f_size * 0.30
            widths = [f_size * 0.56 * len(w) for w in words]

        lines: List[Tuple[List[int], float]] = []
        curr_line: List[int] = []
        curr_w = 0.0
        for idx, ww in enumerate(widths):
            add_w = ww if not curr_line else (space_w + ww)
            if curr_line and curr_w + add_w > box_w:
                lines.append((curr_line, curr_w))
                curr_line = [idx]
                curr_w = ww
            else:
                curr_line.append(idx)
                curr_w += add_w
        if curr_line:
            lines.append((curr_line, curr_w))
        return fnt, space_w, widths, lines

    font_size = single_line_font_size
    font, space_w, widths, lines = _measure(single_line_font_size)
    if len(lines) > 1:
        font_size = base_font_size
        font, space_w, widths, lines = _measure(base_font_size)

    line_height = font_size * 1.28
    center_x = box_x + box_w / 2.0
    center_y = box_y + box_h / 2.0

    pages: List[List[WordSpriteSlot]] = []
    word_page_map: List[Tuple[float, float, int]] = [(s, e, 0) for s, e in words_range]

    for l_start in range(0, len(lines), max(1, max_lines_per_page)):
        chunk_lines = lines[l_start : l_start + max_lines_per_page]
        page_idx = len(pages)
        first_line_y = center_y - ((len(chunk_lines) - 1) * line_height) / 2.0
        page_slots: List[WordSpriteSlot] = []

        for ln_offset, (ln_indices, ln_width) in enumerate(chunk_lines):
            ly = first_line_y + ln_offset * line_height
            cursor_x = center_x - ln_width / 2.0
            for g_idx in ln_indices:
                ww = widths[g_idx]
                s_p, e_p = words_range[g_idx]
                word_page_map[g_idx] = (s_p, e_p, page_idx)
                ink_spr = (
                    _render_word_premul_sprite(words[g_idx], font, cursor_x, ly, ink_bgr)
                    if prerender_sprites
                    else None
                )
                acc_spr = (
                    _render_word_premul_sprite(words[g_idx], font, cursor_x, ly, accent_bgr)
                    if prerender_sprites
                    else None
                )
                page_slots.append(
                    WordSpriteSlot(
                        global_idx=g_idx,
                        page_idx=page_idx,
                        start_p=s_p,
                        end_p=e_p,
                        x=cursor_x,
                        y=ly,
                        w=ww,
                        ink_layer=ink_spr,
                        accent_layer=acc_spr,
                    )
                )
                cursor_x += ww + space_w

        pages.append(page_slots)

    return SubtitlePlan(
        font_size=font_size,
        line_height=line_height,
        cap_box_y=box_y,
        cap_box_h=box_h,
        cap_center_y=center_y,
        pages=pages,
        word_page_map=word_page_map,
    )


def prepare_motion_beat_asset(
    svg_markup: Optional[str],
    width: int,
    height: int,
    cached_full_png: Optional[Path] = None,
    subtitle_text: Optional[str] = None,
    theme: Optional[MotionThemeStyle] = None,
    energy_envelope: Optional[List[float]] = None,
    word_ranges: Optional[List[Tuple[float, float]]] = None,
    audio_duration_sec: Optional[float] = None,
    total_duration_sec: Optional[float] = None,
) -> MotionBeatAsset:
    """Rasterize trước toàn bộ các lớp SVG + pre-render từng từ phụ đề cho 1 beat."""
    clean_sub = re.sub(r"\s+", " ", (subtitle_text or "").strip())
    active_theme = theme or build_motion_theme_style()
    is_vertical = height > width
    ui_scale = min(width, height) / 720.0

    full_bgra: Optional[np.ndarray] = None
    if cached_full_png is not None and cached_full_png.exists():
        loaded = cv2.imread(str(cached_full_png), cv2.IMREAD_UNCHANGED)
        if loaded is not None:
            full_bgra = _ensure_bgra(loaded, width, height)

    if svg_markup:
        layers_svg = split_studio_svg_layers(
            svg_markup,
            strip_caption_text=bool(clean_sub),
        )
        has_header = bool(layers_svg.get("has_header"))
        has_layers = all(
            layers_svg[k] is not None for k in ("stage", "beat1", "beat2", "beat3")
        )
        if full_bgra is None and layers_svg["full"]:
            full_bgra = _rasterize_svg_to_bgra(str(layers_svg["full"]), width, height)

        if has_layers:
            stage_bgra = _rasterize_svg_to_bgra(str(layers_svg["stage"] or ""), width, height)
            b1_bgra = _rasterize_svg_to_bgra(str(layers_svg["beat1"] or ""), width, height)
            b2_bgra = _rasterize_svg_to_bgra(str(layers_svg["beat2"] or ""), width, height)
            b3_bgra = _rasterize_svg_to_bgra(str(layers_svg["beat3"] or ""), width, height)
            cap_bgra = (
                _rasterize_svg_to_bgra(str(layers_svg["caption"] or ""), width, height)
                if layers_svg["caption"]
                else None
            )

            stage_layer = _crop_to_premul_layer(stage_bgra)
            b1_layer = _crop_to_premul_layer(b1_bgra)
            b2_layer = _crop_to_premul_layer(b2_bgra)
            b3_layer = _crop_to_premul_layer(b3_bgra)
            cap_layer = _crop_to_premul_layer(cap_bgra)

            subtitle_plan: Optional[SubtitlePlan] = None
            if clean_sub and cap_layer is not None:
                stage_x = (44.0 if is_vertical else 68.0) * ui_scale
                stage_y = (94.0 if has_header else 62.0) * ui_scale
                stage_h = (790.0 if is_vertical else 482.0) * ui_scale
                cap_box_y = stage_y + stage_h + 22.0 * ui_scale
                cap_box_h = height - cap_box_y - 24.0 * ui_scale
                inner_x = stage_x + 34.0 * ui_scale
                inner_w = width - stage_x * 2.0 - 58.0 * ui_scale

                subtitle_plan = build_subtitle_plan_for_box(
                    text=clean_sub,
                    box_x=inner_x,
                    box_y=cap_box_y + 4.0 * ui_scale,
                    box_w=inner_w,
                    box_h=cap_box_h - 12.0 * ui_scale,
                    base_font_size=(29.0 if is_vertical else 26.0) * ui_scale,
                    single_line_font_size=(33.0 if is_vertical else 30.0) * ui_scale,
                    max_lines_per_page=3 if is_vertical else 2,
                    ink_bgr=active_theme.ink_bgr,
                    accent_bgr=active_theme.accent_bgr,
                    energy_envelope=energy_envelope,
                    word_ranges=word_ranges,
                    audio_duration_sec=audio_duration_sec,
                    total_duration_sec=total_duration_sec,
                )

            if stage_layer and (b1_layer or b2_layer or b3_layer):
                return MotionBeatAsset(
                    has_layers=True,
                    has_header=has_header,
                    width=width,
                    height=height,
                    full_layer=_crop_to_premul_layer(full_bgra),
                    stage_layer=stage_layer,
                    beat1_layer=b1_layer,
                    beat2_layer=b2_layer,
                    beat3_layer=b3_layer,
                    caption_layer=cap_layer,
                    subtitle_plan=subtitle_plan,
                )

    return MotionBeatAsset(
        has_layers=False,
        has_header=False,
        width=width,
        height=height,
        full_layer=_crop_to_premul_layer(full_bgra),
    )


# ==============================================================================
# HÀM EASING VẬT LÝ & BIẾN ĐỔI HÌNH HỌC CHUẨN LOCAL STUDIO
# ==============================================================================


def _clamp01(t: float) -> float:
    return 0.0 if t <= 0.0 else (1.0 if t >= 1.0 else float(t))


def _ease_out_cubic(t: float) -> float:
    x = _clamp01(t)
    return 1.0 - (1.0 - x) ** 3


def _ease_out_quart(t: float) -> float:
    x = _clamp01(t)
    return 1.0 - (1.0 - x) ** 4


def _ease_out_back(t: float, overshoot: float = 1.45) -> float:
    x = _clamp01(t)
    c3 = overshoot + 1.0
    return 1.0 + c3 * ((x - 1.0) ** 3) + overshoot * ((x - 1.0) ** 2)


def _ease_in_out_sine(t: float) -> float:
    x = _clamp01(t)
    return -(math.cos(math.pi * x) - 1.0) / 2.0


def _compute_camera_transform(
    beat_global_index: int,
    beat_p: float,
    width: int,
    height: int,
) -> Tuple[float, float, float]:
    """Quỹ đạo camera luân phiên 5 kiểu khớp 100% `computeCameraTransform` của Local."""
    eased = _ease_in_out_sine(beat_p)
    style = abs(beat_global_index) % 5

    if style == 0:  # Push-in mượt
        return (
            1.0 + 0.048 * eased,
            (eased - 0.5) * width * 0.012,
            -eased * height * 0.008,
        )
    if style == 1:  # Pull-out settle
        return (
            1.052 - 0.048 * eased,
            (0.5 - eased) * width * 0.014,
            (eased - 0.5) * height * 0.008,
        )
    if style == 2:  # Lướt ngang sang phải
        return (
            1.015 + 0.03 * eased,
            (0.5 - eased) * width * 0.022,
            math.sin(beat_p * math.pi) * (-height * 0.008),
        )
    if style == 3:  # Lướt ngang sang trái
        return (
            1.02 + 0.028 * (1.0 - eased),
            (eased - 0.5) * width * 0.022,
            math.sin(beat_p * math.pi) * (height * 0.006),
        )
    # Hero zoom tập trung trung tâm
    return (
        1.0 + 0.054 * _ease_out_cubic(beat_p),
        0.0,
        -eased * height * 0.01,
    )


# ==============================================================================
# VẼ HIỆU ỨNG TRÊN KHUNG HÌNH OPENCV/NUMPY SIÊU NHANH (< 5ms/FRAME)
# ==============================================================================


def _blend_patch_bgr(
    frame: np.ndarray,
    x0: int,
    y0: int,
    mask_u8: np.ndarray,
    color_bgr: Tuple[int, int, int],
    opacity: float,
) -> None:
    """Alpha blend màu đơn sắc qua mask uint8 lên vùng cắt nhỏ của frame."""
    h, w = mask_u8.shape
    a = (mask_u8.astype(np.float32) * (opacity / 255.0))[:, :, None]
    roi = frame[y0 : y0 + h, x0 : x0 + w].astype(np.float32)
    col = np.array(color_bgr, dtype=np.float32)
    frame[y0 : y0 + h, x0 : x0 + w] = np.clip(
        col * a + roi * (1.0 - a), 0.0, 255.0
    ).astype(np.uint8)


def _render_ambient_particles(
    frame: np.ndarray,
    width: int,
    height: int,
    elapsed_sec: float,
    theme: MotionThemeStyle,
    ui_scale: float,
) -> None:
    """Vẽ 5 hạt không khí hình tròn siêu nhẹ trôi êm phía sau sân khấu (không xoay vuông rối mắt)."""
    base_alpha = 0.08 if theme.is_dark else 0.06
    shift = 4
    scale_s = 1 << shift
    for i in range(5):
        seed = (i + 1) * 1.6180339
        speed_y = (6.0 + (i % 3) * 2.5) * ui_scale
        x_base = ((seed * 417.0) % 1.0) * width
        y_span = height + 80.0 * ui_scale
        y_raw = (((seed * 733.0) % 1.0) * height - elapsed_sec * speed_y) % y_span
        y = y_raw + y_span if y_raw < -40.0 * ui_scale else y_raw
        x = x_base + math.sin(elapsed_sec * 0.4 + i) * 10.0 * ui_scale
        radius = (3.2 + (i % 3) * 1.6) * ui_scale
        pulse = 0.72 + 0.28 * math.sin(elapsed_sec * 0.9 + i * 1.3)
        alpha = base_alpha * pulse
        color = theme.accent_bgr if i % 2 == 0 else theme.ink_bgr

        pad = int(math.ceil(radius * 1.6)) + 2
        x0 = max(0, int(round(x)) - pad)
        y0 = max(0, int(round(y)) - pad)
        x1 = min(width, int(round(x)) + pad + 1)
        y1 = min(height, int(round(y)) + pad + 1)
        mw = x1 - x0
        mh = y1 - y0
        if mw <= 1 or mh <= 1:
            continue

        mask = np.zeros((mh, mw), dtype=np.uint8)
        cx = x - x0
        cy = y - y0
        cv2.circle(
            mask,
            (int(round(cx * scale_s)), int(round(cy * scale_s))),
            max(1, int(round(radius * scale_s))),
            255,
            thickness=-1,
            lineType=cv2.LINE_AA,
            shift=shift,
        )
        _blend_patch_bgr(frame, x0, y0, mask, color, alpha)


def _draw_transformed_layer(
    frame: np.ndarray,
    layer: Optional[CroppedPremulLayer],
    alpha: float = 1.0,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    scale: float = 1.0,
    rotation: float = 0.0,
    pivot_x: Optional[float] = None,
    pivot_y: Optional[float] = None,
) -> None:
    """
    Ghép 1 lớp premultiplied BGRA bằng biến đổi affine quanh `(pivot_x, pivot_y)` chỉ trên
    vùng ROI đích thực tế (hoặc blit trực tiếp khi scale=1, rot=0 để đạt tốc độ tối đa).
    """
    if layer is None or alpha <= 0.005:
        return

    alpha = _clamp01(alpha)
    fh, fw = frame.shape[:2]

    # Đường chạy nhanh không nội suy khi cố định (scale=1, rot=0, dịch nguyên pixel)
    if (
        rotation == 0.0
        and abs(scale - 1.0) < 1e-4
        and abs(offset_x - round(offset_x)) < 0.05
        and abs(offset_y - round(offset_y)) < 0.05
    ):
        sx0 = layer.bx + int(round(offset_x))
        sy0 = layer.by + int(round(offset_y))
        dx0 = max(0, sx0)
        dy0 = max(0, sy0)
        dx1 = min(fw, sx0 + layer.bw)
        dy1 = min(fh, sy0 + layer.bh)
        if dx1 <= dx0 or dy1 <= dy0:
            return
        cx0 = dx0 - sx0
        cy0 = dy0 - sy0
        cw = dx1 - dx0
        ch = dy1 - dy0
        sub = layer.premul_bgra[cy0 : cy0 + ch, cx0 : cx0 + cw]
        a_ch = sub[:, :, 3:4].astype(np.float32) * (alpha / 255.0)
        fg = sub[:, :, :3].astype(np.float32) * alpha
        roi = frame[dy0:dy1, dx0:dx1].astype(np.float32)
        frame[dy0:dy1, dx0:dx1] = np.clip(fg + roi * (1.0 - a_ch), 0.0, 255.0).astype(np.uint8)
        return

    px = (fw / 2.0) if pivot_x is None else pivot_x
    py = (fh / 2.0) if pivot_y is None else pivot_y

    c = scale * math.cos(rotation)
    sn = scale * math.sin(rotation)
    tx = px + offset_x - c * px + sn * py + c * layer.bx - sn * layer.by
    ty = py + offset_y - sn * px - c * py + sn * layer.bx + c * layer.by

    bw = float(layer.bw)
    bh = float(layer.bh)
    xs = [tx, c * bw + tx, -sn * bh + tx, c * bw - sn * bh + tx]
    ys = [ty, sn * bw + ty, c * bh + ty, sn * bw + c * bh + ty]

    dx0 = max(0, int(math.floor(min(xs))) - 1)
    dy0 = max(0, int(math.floor(min(ys))) - 1)
    dx1 = min(fw, int(math.ceil(max(xs))) + 2)
    dy1 = min(fh, int(math.ceil(max(ys))) + 2)

    roi_w = dx1 - dx0
    roi_h = dy1 - dy0
    if roi_w <= 0 or roi_h <= 0:
        return

    M_roi = np.array(
        [[c, -sn, tx - dx0], [sn, c, ty - dy0]],
        dtype=np.float32,
    )
    warped = cv2.warpAffine(
        layer.premul_bgra,
        M_roi,
        (roi_w, roi_h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )

    a_ch = warped[:, :, 3:4].astype(np.float32) * (alpha / 255.0)
    fg = warped[:, :, :3].astype(np.float32) * alpha
    roi = frame[dy0:dy1, dx0:dx1].astype(np.float32)
    frame[dy0:dy1, dx0:dx1] = np.clip(fg + roi * (1.0 - a_ch), 0.0, 255.0).astype(np.uint8)


def _draw_rounded_bar(
    frame: np.ndarray,
    x: float,
    y: float,
    w: float,
    h: float,
    radius: float,
    color_bgr: Tuple[int, int, int],
    opacity: float,
) -> None:
    """Vẽ thanh/nền bo tròn mượt qua Pillow ROI."""
    if opacity <= 0.005:
        return
    fh, fw = frame.shape[:2]
    x0 = max(0, int(math.floor(x)) - 2)
    y0 = max(0, int(math.floor(y)) - 2)
    x1 = min(fw, int(math.ceil(x + w)) + 2)
    y1 = min(fh, int(math.ceil(y + h)) + 2)
    mw = x1 - x0
    mh = y1 - y0
    if mw <= 1 or mh <= 1 or w <= 0.5 or h <= 0.5:
        return

    patch = Image.new("L", (mw, mh), 0)
    draw = ImageDraw.Draw(patch)
    r = max(1, int(round(min(radius, w / 2.0, h / 2.0))))
    draw.rounded_rectangle(
        (x - x0, y - y0, x - x0 + w, y - y0 + h),
        radius=r,
        fill=255,
    )
    mask_u8 = np.array(patch, dtype=np.uint8)
    _blend_patch_bgr(frame, x0, y0, mask_u8, color_bgr, _clamp01(opacity))


def _render_subtitle_plan_on_frame(
    frame: np.ndarray,
    plan: SubtitlePlan,
    progress: float,
    alpha: float,
    accent_bgr: Tuple[int, int, int],
    ui_scale: float,
    cap_offset_y: float = 0.0,
    cap_scale: float = 1.0,
    cap_pivot_x: float = 0.0,
    cap_pivot_y: float = 0.0,
) -> None:
    """Vẽ phụ đề chạy từng từ đúng khớp tiến trình giọng đọc (đã căn sẵn trang 2 dòng)."""
    if not plan.pages or alpha <= 0.01:
        return

    active_word_idx = -1
    for i, (s_p, _, _) in enumerate(plan.word_page_map):
        if progress >= s_p:
            active_word_idx = i
        else:
            break

    if active_word_idx < 0:
        return

    _, _, page_idx = plan.word_page_map[active_word_idx]
    if page_idx < 0 or page_idx >= len(plan.pages):
        return
    page_slots = plan.pages[page_idx]

    pill_pad_x = 6.0 * ui_scale
    pill_half_h = plan.font_size * 0.64
    pill_radius = 6.0 * ui_scale

    for slot in page_slots:
        if slot.global_idx > active_word_idx:
            continue

        if slot.global_idx < active_word_idx:
            _draw_transformed_layer(
                frame,
                slot.ink_layer,
                alpha=alpha,
                offset_y=cap_offset_y,
                scale=cap_scale,
                pivot_x=cap_pivot_x,
                pivot_y=cap_pivot_y,
            )
        else:
            word_dur = max(0.02, slot.end_p - slot.start_p)
            reveal_t = _clamp01((progress - slot.start_p) / min(0.055, word_dur * 0.45))
            reveal_ease = _ease_out_cubic(reveal_t)
            pop_y = (1.0 - reveal_ease) * 4.0 * ui_scale

            # Nền nhấn bo góc mềm sau từ đang đọc
            px = (slot.x - pill_pad_x - cap_pivot_x) * cap_scale + cap_pivot_x
            py = (slot.y + pop_y - pill_half_h - cap_pivot_y) * cap_scale + cap_pivot_y + cap_offset_y
            pw = (slot.w + pill_pad_x * 2.0) * cap_scale
            ph = (pill_half_h * 2.0) * cap_scale
            _draw_rounded_bar(
                frame,
                x=px,
                y=py,
                w=pw,
                h=ph,
                radius=pill_radius * cap_scale,
                color_bgr=accent_bgr,
                opacity=alpha * 0.14 * reveal_ease,
            )

            _draw_transformed_layer(
                frame,
                slot.accent_layer,
                alpha=alpha * reveal_ease,
                offset_y=cap_offset_y + pop_y * cap_scale,
                scale=cap_scale,
                pivot_x=cap_pivot_x,
                pivot_y=cap_pivot_y,
            )


def _render_voice_equalizer_badge(
    frame: np.ndarray,
    voice_energy: float,
    elapsed_sec: float,
    theme: MotionThemeStyle,
    ui_scale: float,
) -> None:
    """Vẽ thanh sóng âm 7 cột góc trên trái nhảy khớp giọng đọc thật."""
    x0 = int(round(28 * ui_scale))
    y0 = int(round(22 * ui_scale))
    bar_count = 7
    bar_w = 4.0 * ui_scale
    gap = 4.5 * ui_scale
    max_h = 22.0 * ui_scale
    pill_w = int(round(bar_count * (bar_w + gap) + 18.0 * ui_scale))
    pill_h = int(round(34.0 * ui_scale))

    fh, fw = frame.shape[:2]
    if x0 + pill_w >= fw or y0 + pill_h >= fh:
        return

    pad = 3
    pw = pill_w + pad * 2
    ph = pill_h + pad * 2
    ss = 2
    img = Image.new("RGBA", (pw * ss, ph * ss), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    acc_rgb = (theme.accent_bgr[2], theme.accent_bgr[1], theme.accent_bgr[0])
    pill_fill = (15, 23, 42, int(0.72 * 0.88 * 255)) if theme.is_dark else (255, 255, 255, int(0.85 * 0.88 * 255))
    pill_outline = (*acc_rgb, int(0.88 * 255))
    border_w = max(1, int(round(1.6 * ui_scale * ss)))

    rx0 = pad * ss
    ry0 = pad * ss
    rx1 = (pad + pill_w) * ss
    ry1 = (pad + pill_h) * ss
    draw.rounded_rectangle(
        (rx0, ry0, rx1, ry1),
        radius=int(round((pill_h / 2.0) * ss)),
        fill=pill_fill,
        outline=pill_outline,
        width=border_w,
    )

    center_y = (pad + pill_h / 2.0) * ss
    bar_fill = (*acc_rgb, int(0.88 * 255))
    bar_radius = max(1, int(round(2.0 * ui_scale * ss)))

    for i in range(bar_count):
        shape_weight = 1.0 - abs(i - 3) * 0.16
        wave_mod = 0.55 + 0.45 * math.sin(elapsed_sec * (9.5 + i * 1.7) + i * 1.1)
        active_level = max(0.16, voice_energy * shape_weight * wave_mod)
        bh = max(4.0 * ui_scale, min(max_h, active_level * max_h))
        bx = (pad + 11.0 * ui_scale + i * (bar_w + gap)) * ss
        by0 = center_y - (bh * ss) / 2.0
        by1 = center_y + (bh * ss) / 2.0
        draw.rounded_rectangle(
            (bx, by0, bx + bar_w * ss, by1),
            radius=bar_radius,
            fill=bar_fill,
        )

    img = img.resize((pw, ph), resample=Image.Resampling.LANCZOS)
    rgba = np.array(img, dtype=np.uint8)
    bgr_fg = rgba[:, :, [2, 1, 0]].astype(np.float32)
    a = (rgba[:, :, 3:4].astype(np.float32)) / 255.0

    dst_x0 = max(0, x0 - pad)
    dst_y0 = max(0, y0 - pad)
    dst_x1 = min(fw, dst_x0 + pw)
    dst_y1 = min(fh, dst_y0 + ph)
    cw = dst_x1 - dst_x0
    ch = dst_y1 - dst_y0
    if cw <= 0 or ch <= 0:
        return

    roi = frame[dst_y0:dst_y1, dst_x0:dst_x1].astype(np.float32)
    frame[dst_y0:dst_y1, dst_x0:dst_x1] = np.clip(
        bgr_fg[:ch, :cw] * a[:ch, :cw] + roi * (1.0 - a[:ch, :cw]), 0.0, 255.0
    ).astype(np.uint8)


def _render_overall_progress_bar(
    frame: np.ndarray,
    overall_progress: float,
    theme: MotionThemeStyle,
    ui_scale: float,
) -> None:
    """Vẽ thanh tiến trình siêu mảnh sát mép dưới đồng bộ màu nhấn."""
    fh, fw = frame.shape[:2]
    bar_h = max(4, int(round(5.0 * ui_scale)))
    y0 = fh - bar_h
    if y0 < 0:
        return

    track_col = np.array((255, 255, 255), dtype=np.float32) if theme.is_dark else np.array((15, 23, 42), dtype=np.float32)
    track_alpha = 0.14 if theme.is_dark else 0.12
    roi = frame[y0:fh, 0:fw].astype(np.float32)
    frame[y0:fh, 0:fw] = np.clip(
        track_col * track_alpha + roi * (1.0 - track_alpha), 0.0, 255.0
    ).astype(np.uint8)

    fill_w = max(0, min(fw, int(round(fw * _clamp01(overall_progress)))))
    if fill_w > 0:
        frame[y0:fh, 0:fill_w] = theme.accent_bgr


def render_living_beat_frame(
    asset: MotionBeatAsset,
    prev_asset: Optional[MotionBeatAsset],
    beat_p: float,
    elapsed_sec: float,
    beat_global_index: int,
    voice_energy: float,
    theme: MotionThemeStyle,
    overall_progress: float = 0.0,
) -> np.ndarray:
    """Dựng 1 khung hình BGR24 30fps điềm tĩnh: khung ngoài đứng yên, chỉ nội dung bên trong chuyển động mượt."""
    del voice_energy  # Không rung/đập nhún nhân vật hay badge sóng âm gây xao nhãng
    width = asset.width
    height = asset.height
    p = _clamp01(beat_p)
    is_vertical = height > width
    ui_scale = min(width, height) / 720.0

    # 1. Nền phẳng đồng bộ màu kênh + 5 hạt không khí trôi êm (không xoay vuông)
    frame = np.empty((height, width, 3), dtype=np.uint8)
    frame[:, :] = theme.bg_bgr
    _render_ambient_particles(frame, width, height, elapsed_sec, theme, ui_scale)

    # 2. Chuyển cảnh hòa tan êm dịu (0.12 đầu nhịp), giữ khung ngoài đứng yên 100%
    transition_window = 0.12
    trans_t = _clamp01(p / transition_window)
    trans_ease = _ease_out_cubic(trans_t)

    if trans_t < 1.0 and prev_asset is not None and prev_asset is not asset and prev_asset.full_layer is not None:
        out_alpha = (1.0 - trans_ease) * 0.5
        _draw_transformed_layer(
            frame,
            prev_asset.full_layer,
            alpha=out_alpha,
            offset_x=0.0,
            offset_y=0.0,
            scale=1.0,
        )

    # Nếu là ảnh đơn không tách lớp SVG -> giữ khung tĩnh vững vàng, thở zoom siêu nhẹ
    if not asset.has_layers or asset.stage_layer is None:
        gentle_zoom = 1.0 + 0.015 * _ease_in_out_sine(p)
        _draw_transformed_layer(
            frame,
            asset.full_layer,
            alpha=trans_ease,
            offset_x=0.0,
            offset_y=0.0,
            scale=gentle_zoom,
        )
        _render_overall_progress_bar(frame, overall_progress, theme, ui_scale)
        return frame

    # 3. DIỄN HOẠT ĐA LỚP ĐIỀM TĨNH (KHUNG SÂN KHẤU ĐỨNG YÊN, CHỈ BÊN TRONG CHUYỂN ĐỘNG MƯỢT)

    # Lớp 0: Khung sân khấu & tiêu đề chương (đứng vững 100%, không trượt ngang hay zoom lệch viền)
    _draw_transformed_layer(
        frame,
        asset.stage_layer,
        alpha=trans_ease,
        offset_x=0.0,
        offset_y=0.0,
        scale=1.0,
    )

    # Lớp 1 (beat-1): Nhân vật/chủ thể chính tiến vào gọn gàng + nhịp thở cực nhẹ <= 1.2px
    b1_enter = _clamp01(p / 0.16)
    b1_ease = _ease_out_cubic(b1_enter)
    b1_breath_y = math.sin(elapsed_sec * 1.4 + beat_global_index) * 1.2 * ui_scale
    _draw_transformed_layer(
        frame,
        asset.beat1_layer,
        alpha=b1_ease,
        offset_x=0.0,
        offset_y=(1.0 - b1_ease) * 14.0 * ui_scale + b1_breath_y,
        scale=0.95 + 0.05 * b1_ease,
        pivot_x=width * 0.36,
        pivot_y=height * 0.48,
    )

    # Lớp 2 (beat-2): Điểm nhấn thị giác hiện sắc nét (không rung đập liên hồi)
    b2_enter = _clamp01((p - 0.14) / 0.16)
    if b2_enter > 0.0:
        b2_ease = _ease_out_quart(b2_enter)
        _draw_transformed_layer(
            frame,
            asset.beat2_layer,
            alpha=b2_ease,
            offset_x=0.0,
            offset_y=0.0,
            scale=0.88 + 0.12 * b2_ease,
            pivot_x=width * 0.5,
            pivot_y=height * 0.45,
        )

    # Lớp 3 (beat-3): Đạo cụ ẩn dụ / đối thoại trượt vào êm ái rồi dừng vững vàng
    b3_enter = _clamp01((p - 0.24) / 0.18)
    if b3_enter > 0.0:
        b3_ease = _ease_out_cubic(b3_enter)
        _draw_transformed_layer(
            frame,
            asset.beat3_layer,
            alpha=b3_ease,
            offset_x=(1.0 - b3_ease) * 18.0 * ui_scale,
            offset_y=(1.0 - b3_ease) * 8.0 * ui_scale,
            scale=0.94 + 0.06 * b3_ease,
            pivot_x=width * 0.68,
            pivot_y=height * 0.46,
        )

    # Lớp 4 (studio-caption): Hộp phụ đề đáy cố định ngang + chữ chạy sub khóa theo giọng nói thật
    if asset.caption_layer is not None:
        cap_enter = _clamp01(p / 0.10)
        cap_ease = _ease_out_quart(cap_enter)
        stage_x = (44.0 if is_vertical else 68.0) * ui_scale
        stage_y = (94.0 if asset.has_header else 62.0) * ui_scale
        stage_h = (790.0 if is_vertical else 482.0) * ui_scale
        cap_box_y = stage_y + stage_h + 22.0 * ui_scale
        cap_box_h = height - cap_box_y - 24.0 * ui_scale
        cap_pivot_x = width / 2.0
        cap_pivot_y = cap_box_y + cap_box_h / 2.0
        cap_offset_y = (1.0 - cap_ease) * 8.0 * ui_scale
        cap_scale = 1.0

        _draw_transformed_layer(
            frame,
            asset.caption_layer,
            alpha=cap_ease,
            offset_y=cap_offset_y,
            scale=cap_scale,
            pivot_x=cap_pivot_x,
            pivot_y=cap_pivot_y,
        )

        if asset.subtitle_plan is not None:
            _render_subtitle_plan_on_frame(
                frame=frame,
                plan=asset.subtitle_plan,
                progress=p,
                alpha=cap_ease,
                accent_bgr=theme.accent_bgr,
                ui_scale=ui_scale,
                cap_offset_y=cap_offset_y,
                cap_scale=cap_scale,
                cap_pivot_x=cap_pivot_x,
                cap_pivot_y=cap_pivot_y,
            )

        if cap_ease > 0.6:
            bar_y = height - 29.0 * ui_scale
            bar_max_w = width - stage_x * 2.0 - 36.0 * ui_scale
            bar_x = stage_x + 22.0 * ui_scale
            _draw_rounded_bar(
                frame,
                x=bar_x,
                y=bar_y,
                w=max(8.0 * ui_scale, bar_max_w * p),
                h=4.5 * ui_scale,
                radius=2.25 * ui_scale,
                color_bgr=theme.accent_bgr,
                opacity=0.82 * cap_ease,
            )

    # 4. Thanh tiến trình đáy video gọn gàng (bỏ badge sóng âm góc trên trái)
    _render_overall_progress_bar(frame, overall_progress, theme, ui_scale)
    return frame


# ==============================================================================
# HỖ TRỢ PHỤ ĐỀ CHẠY CHỮ CHO CẢ CHẾ ĐỘ PEN SKETCH & KEN BURNS 2D
# ==============================================================================


class BoxProgressiveSubtitleTracker:
    """Bộ vẽ phụ đề chạy từng từ trong hộp tối phía dưới cho `pen_sketch`."""

    def __init__(
        self,
        text: str,
        width: int,
        height: int,
        energy_envelope: Optional[List[float]] = None,
        audio_duration_sec: Optional[float] = None,
        total_duration_sec: Optional[float] = None,
    ) -> None:
        clean = re.sub(r"\s+", " ", (text or "").strip())
        is_vertical = height > width
        margin = int(round(min(width, height) * 0.036))
        bar_y = height - margin - 24
        block_h = int(round((116 if is_vertical else 98) * (min(width, height) / 720.0)))
        box_y = bar_y - block_h - 22
        box_w = min(width - margin * 3, int(round(980 * (width / 1280.0)))) if not is_vertical else (width - margin * 3)
        box_x = (width - box_w) // 2

        self.has_text = bool(clean)
        self.box = (box_x, box_y, box_w, block_h)
        ui_scale = max(0.85, (box_w / 600.0) if is_vertical else (box_w / 900.0))
        self.ui_scale = ui_scale
        self.accent_bgr = (130, 200, 231)  # #E7C882 in BGR
        self.plan = build_subtitle_plan_for_box(
            text=clean,
            box_x=box_x + 22,
            box_y=box_y + 8,
            box_w=box_w - 44,
            box_h=block_h - 16,
            base_font_size=(26.0 if is_vertical else 27.0) * ui_scale,
            single_line_font_size=(30.0 if is_vertical else 30.0) * ui_scale,
            max_lines_per_page=2,
            ink_bgr=(228, 238, 242),  # #F2EEE4 in BGR
            accent_bgr=self.accent_bgr,
            prerender_sprites=True,
            energy_envelope=energy_envelope,
            audio_duration_sec=audio_duration_sec,
            total_duration_sec=total_duration_sec,
        )

    def draw(self, frame: np.ndarray, progress: float) -> None:
        if not self.has_text:
            return
        bx, by, bw, bh = self.box
        _draw_rounded_bar(
            frame,
            x=float(bx),
            y=float(by),
            w=float(bw),
            h=float(bh),
            radius=6.0,
            color_bgr=(20, 14, 11),
            opacity=0.80,
        )
        cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), (89, 160, 197), 1)
        _render_subtitle_plan_on_frame(
            frame=frame,
            plan=self.plan,
            progress=_clamp01(progress),
            alpha=1.0,
            accent_bgr=self.accent_bgr,
            ui_scale=self.ui_scale,
        )


def _format_ass_time(sec: float) -> str:
    sec = max(0.0, float(sec))
    cs = int(round(sec * 100.0))
    hours = cs // 360000
    rem = cs % 360000
    mins = rem // 6000
    rem = rem % 6000
    secs = rem // 100
    centis = rem % 100
    return f"{hours}:{mins:02d}:{secs:02d}.{centis:02d}"


def _escape_ass_text(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")


def write_progressive_ass_subtitle(
    text: str,
    duration_sec: float,
    output_ass_path: Path,
    width: int,
    height: int,
    energy_envelope: Optional[List[float]] = None,
    total_duration_sec: Optional[float] = None,
) -> Path:
    """
    Xuất tệp `.ass` phụ đề chạy từng từ (đọc tới đâu hiện chữ tới đó, tô sáng từ đang đọc)
    cho chế độ `ken_burns_2d` để burn-in siêu nhanh trực tiếp bằng bộ lọc `ass=` của FFmpeg.
    """
    clean = re.sub(r"\s+", " ", (text or "").strip())
    is_vertical = height > width
    ui_scale = min(width, height) / 720.0
    margin = int(round(min(width, height) * 0.036))
    font_size = int(round((28.0 if is_vertical else 29.0) * ui_scale))
    margin_v = margin + int(round(46.0 * ui_scale))
    max_box_w = (width - margin * 4) if is_vertical else min(width - margin * 4, int(round(920 * (width / 1280.0))))

    span_sec = max(float(duration_sec), float(total_duration_sec or duration_sec))
    plan = build_subtitle_plan_for_box(
        text=clean,
        box_x=0.0,
        box_y=0.0,
        box_w=float(max_box_w),
        box_h=120.0 * ui_scale,
        base_font_size=float(font_size),
        single_line_font_size=float(font_size),
        max_lines_per_page=2,
        ink_bgr=(228, 238, 242),
        accent_bgr=(130, 200, 231),
        prerender_sprites=False,
        energy_envelope=energy_envelope,
        audio_duration_sec=duration_sec,
        total_duration_sec=span_sec,
    )

    words = [w for w in re.split(r"\s+", clean) if w]
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {width}\n"
        f"PlayResY: {height}\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: StoicSub,Noto Sans,{font_size},&H00E4EEF2,&H0082C8E7,&HAA140E0B,&HCC140E0B,"
        f"1,0,0,0,100,100,0,0,3,{max(10, int(round(12 * ui_scale)))},0,2,{margin * 2},{margin * 2},{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    events: List[str] = []
    if words and plan.pages:
        word_entries: List[Tuple[int, str, float, float]] = []
        # Map lại từng trang & dòng cho từng word index
        for page_idx, slots in enumerate(plan.pages):
            # Nhóm slot theo dòng y
            lines_by_y: Dict[float, List[WordSpriteSlot]] = {}
            for sl in slots:
                lines_by_y.setdefault(sl.y, []).append(sl)
            ordered_lines = [lines_by_y[y] for y in sorted(lines_by_y.keys())]

            for sl in slots:
                t_start = sl.start_p * span_sec
                # Kết thúc event ngay khi sang từ kế tiếp (hoặc kết thúc scene cho từ cuối trang/beat)
                next_idx = sl.global_idx + 1
                if next_idx < len(plan.word_page_map):
                    t_end = plan.word_page_map[next_idx][0] * span_sec
                else:
                    t_end = max(t_start + 0.15, span_sec - 0.05)

                if t_end <= t_start + 0.02:
                    t_end = t_start + 0.04

                line_strs: List[str] = []
                for ln in ordered_lines:
                    parts: List[str] = []
                    for item in ln:
                        w_txt = _escape_ass_text(words[item.global_idx])
                        if item.global_idx < sl.global_idx:
                            parts.append(w_txt)
                        elif item.global_idx == sl.global_idx:
                            parts.append(rf"{{\c&H0082C8E7&}}{w_txt}{{\c&H00E4EEF2&}}")
                    if parts:
                        line_strs.append(" ".join(parts))

                if line_strs:
                    full_ass_line = r"\N".join(line_strs)
                    word_entries.append((sl.global_idx, full_ass_line, t_start, t_end))

        for _, txt, ts, te in word_entries:
            events.append(
                f"Dialogue: 0,{_format_ass_time(ts)},{_format_ass_time(te)},StoicSub,,0,0,0,,{txt}"
            )

    output_ass_path.parent.mkdir(parents=True, exist_ok=True)
    output_ass_path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return output_ass_path


# ==============================================================================
# PIPELINE RENDER 1 PHÂN CẢNH MULTI-BEAT 30FPS TRỰC TIẾP SANG FFMPEG MP4
# ==============================================================================


def render_motion_beat_scene_clip(
    beat_svgs: List[Optional[str]],
    beat_durations: List[float],
    audio_path: Path,
    output_clip_path: Path,
    resolution: Tuple[int, int],
    scene_index: int = 0,
    total_scenes: int = 1,
    beat_global_offset: int = 0,
    elapsed_offset_sec: float = 0.0,
    prev_beat_svg: Optional[str] = None,
    cached_full_pngs: Optional[List[Path]] = None,
    theme: Optional[MotionThemeStyle] = None,
    beat_phrases: Optional[List[str]] = None,
    scene_narration: Optional[str] = None,
    beat_word_ranges: Optional[List[List[Tuple[float, float]]]] = None,
) -> Path:
    """
    Render toàn bộ các beat trong 1 phân cảnh thành clip `.mp4` 30fps bằng ống dẫn rawvideo
    trực tiếp vào FFmpeg (`libx264` + `aac`), kèm chữ chạy sub khớp 100% âm tiết giọng đọc.
    """
    if not beat_durations:
        beat_durations = [4.0]
    if len(beat_svgs) != len(beat_durations):
        raise ValueError("Số lượng beat_svgs phải khớp với beat_durations.")

    width, height = resolution
    fps = int(getattr(config, "VIDEO_FPS", 30))
    active_theme = theme or build_motion_theme_style()

    # 1. Trích xuất đường bao giọng đọc 30Hz
    energy_envelope = extract_audio_energy_envelope(audio_path, samples_per_sec=30)

    raw_total_dur = sum(max(0.4, float(d)) for d in beat_durations)
    tail_pad = 0.35
    padded_duration = round(raw_total_dur + tail_pad, 3)
    total_frames = max(1, int(math.ceil(padded_duration * fps)))

    effective_phrases = list(beat_phrases) if beat_phrases else ["" for _ in beat_svgs]
    effective_word_ranges = beat_word_ranges

    if scene_narration and scene_narration.strip() and effective_word_ranges is None:
        effective_phrases, synced_durs, effective_word_ranges = schedule_scene_speech_and_beats(
            narration=scene_narration,
            beat_phrases=effective_phrases,
            energy_envelope=energy_envelope,
            audio_duration_sec=raw_total_dur,
            trailing_gap_sec=tail_pad,
            samples_per_sec=30,
        )
        adjusted_durs = [max(0.4, float(d)) for d in synced_durs]
    else:
        adjusted_durs = [max(0.4, float(d)) for d in beat_durations]
        adjusted_durs[-1] += tail_pad

    # Chuẩn hóa tổng thời lượng đúng bằng padded_duration
    dur_sum = sum(adjusted_durs)
    if dur_sum > 0.1:
        scale_f = padded_duration / dur_sum
        adjusted_durs = [d * scale_f for d in adjusted_durs]

    beat_bounds: List[Tuple[float, float]] = []
    acc = 0.0
    for d in adjusted_durs:
        beat_bounds.append((acc, acc + d))
        acc += d

    # 2. Rasterize sẵn 5 lớp + bảng từ phụ đề (khóa theo đường bao giọng nói & word_ranges chuẩn)
    beat_assets: List[MotionBeatAsset] = []
    for idx, svg_code in enumerate(beat_svgs):
        png_cache = cached_full_pngs[idx] if (cached_full_pngs and idx < len(cached_full_pngs)) else None
        phrase = effective_phrases[idx] if idx < len(effective_phrases) else None
        w_ranges = (
            effective_word_ranges[idx]
            if (effective_word_ranges and idx < len(effective_word_ranges))
            else None
        )
        b_start, b_end = beat_bounds[idx]
        s_idx = max(0, int(math.floor(b_start * 30.0)))
        e_idx = min(len(energy_envelope), int(math.ceil(b_end * 30.0)))
        beat_env = energy_envelope[s_idx:e_idx] if e_idx > s_idx else None
        beat_dur = max(0.2, b_end - b_start)
        beat_audio_dur = max(0.2, beat_dur - (tail_pad if idx == len(beat_svgs) - 1 else 0.0))
        beat_assets.append(
            prepare_motion_beat_asset(
                svg_markup=svg_code,
                width=width,
                height=height,
                cached_full_png=png_cache,
                subtitle_text=phrase,
                theme=active_theme,
                energy_envelope=beat_env,
                word_ranges=w_ranges,
                audio_duration_sec=beat_audio_dur,
                total_duration_sec=beat_dur,
            )
        )

    prev_scene_asset: Optional[MotionBeatAsset] = None
    if prev_beat_svg:
        prev_scene_asset = prepare_motion_beat_asset(prev_beat_svg, width, height, theme=active_theme)

    # 3. Khởi chạy FFmpeg pipe BGR24 -> MP4
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
    tune = str(getattr(config, "FFMPEG_TUNE", "") or "").strip()
    if tune:
        idx_crf = ffmpeg_cmd.index("-crf")
        ffmpeg_cmd[idx_crf:idx_crf] = ["-tune", tune]

    proc = subprocess.Popen(
        ffmpeg_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    try:
        assert proc.stdin is not None
        num_beats = len(beat_assets)
        active_b_idx = 0

        for frame_idx in range(total_frames):
            local_sec = min(padded_duration, frame_idx / float(fps))
            while active_b_idx < num_beats - 1 and local_sec >= beat_bounds[active_b_idx][1]:
                active_b_idx += 1

            b_start, b_end = beat_bounds[active_b_idx]
            beat_p = _clamp01((local_sec - b_start) / max(0.05, b_end - b_start))
            local_scene_p = _clamp01(local_sec / max(0.1, padded_duration))
            overall_progress = _clamp01(
                (scene_index + local_scene_p) / max(1, total_scenes)
            )
            voice_energy = sample_audio_energy(energy_envelope, local_sec, samples_per_sec=30)

            curr_asset = beat_assets[active_b_idx]
            if active_b_idx > 0:
                prev_asset = beat_assets[active_b_idx - 1]
            else:
                prev_asset = prev_scene_asset

            frame_bgr = render_living_beat_frame(
                asset=curr_asset,
                prev_asset=prev_asset,
                beat_p=beat_p,
                elapsed_sec=elapsed_offset_sec + local_sec,
                beat_global_index=beat_global_offset + active_b_idx,
                voice_energy=voice_energy,
                theme=active_theme,
                overall_progress=overall_progress,
            )
            proc.stdin.write(frame_bgr.tobytes())

        proc.stdin.close()
        stderr_out = proc.stderr.read().decode("utf-8", errors="ignore") if proc.stderr else ""
        ret = proc.wait()
        if ret != 0:
            tail = "\n".join(stderr_out.splitlines()[-15:])
            raise RuntimeError(f"FFmpeg studio_motion_renderer thất bại:\n{tail}")
    finally:
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()

    logger.info(
        "[STUDIO MOTION OK] Clip='%s' | Beats=%d | Layered=%d/%d | Frames=%d | Duration=%.2fs",
        output_clip_path.name,
        len(beat_assets),
        sum(1 for a in beat_assets if a.has_layers),
        len(beat_assets),
        total_frames,
        padded_duration,
    )
    return output_clip_path
