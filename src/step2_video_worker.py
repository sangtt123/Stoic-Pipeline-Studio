"""
src/step2_video_worker.py — Giai đoạn 2: Worker độc lập sản xuất 1 Video 2D, QA & Upload Drive.

Nhận biến môi trường `VIDEO_INDEX` (0..4) từ GitHub Actions Matrix:
1. Đọc đúng kịch bản theo `VIDEO_INDEX` từ `output/scripts.json`.
2. Tạo giọng đọc nam trầm từng phân cảnh bằng Google Cloud TTS -> lấy chính xác duration.
3. Tạo ảnh 2D tĩnh bằng Vertex AI Imagen (KHÔNG dùng Veo) với seed ngẫu nhiên từng cảnh.
4. Vẽ lớp phủ đồ họa 2D RGBA bằng Pillow + Render FFmpeg ultrafast + trộn nhạc nền (nếu có).
5. Kiểm duyệt kỹ thuật + Gemini Vision Contact Sheet; nếu lỗi -> tự động sửa phân cảnh lỗi
   và render lại (tối đa `max_retries = 2`). Nếu sau 2 lần vẫn chưa đạt -> gắn `[CHECK_REQUIRED]_`.
6. Upload file `.mp4` lên Google Drive và xóa sạch thư mục tạm.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set

from dotenv import load_dotenv

import config
from src.drive_manager import DriveManager
from src.graphics_2d import render_scene_overlay, render_youtube_thumbnail
from src.studio_art_engine import (
    rasterize_svg_to_png,
    render_studio_shot_svg,
    render_studio_thumbnail_svg,
    resolve_studio_theme,
)
from src.studio_motion_renderer import (
    align_beat_bounds_to_audio_silences,
    build_motion_theme_style,
    extract_audio_energy_envelope,
    reconcile_visual_beats_to_narration,
    render_motion_beat_scene_clip,
    schedule_scene_speech_and_beats,
)
from src.tts_generator import TTSGenerator
from src.vertex_client import VertexAIClient
from src.video_renderer import (
    concatenate_and_mix_bgm,
    ensure_ambient_bgm,
    pick_random_bgm,
    render_multi_beat_scene_clip,
    render_scene_clip,
)
from src.video_reviewer import review_final_video

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("step2_video_worker")


def _slugify_filename(text: str, max_len: int = 58) -> str:
    """Tạo tên file an toàn từ tiêu đề tiếng Anh/Việt."""
    clean = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip()
    clean = re.sub(r"[-\s]+", "_", clean)
    return clean[:max_len].strip("_") or "stoic_video"


def _render_fallback_scene_art(output_path: Path, resolution: tuple[int, int]) -> Path:
    """
    Vẽ hình nền tối giản 2D đồng bộ màu kênh bằng Pillow làm dự phòng cuối cùng
    khi toàn bộ model Vertex AI Imagen gặp lỗi mạng/quota, đảm bảo không bao giờ gãy luồng dựng video.
    """
    from PIL import Image, ImageDraw

    def _hex_rgb(hex_str: str, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
        h = (hex_str or "").strip().lstrip("#")
        if len(h) == 6:
            try:
                return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
            except ValueError:
                pass
        return fallback

    w, h = resolution
    bg = _hex_rgb(getattr(config, "WHITEBOARD_BG_COLOR", "#EEF2F7"), (238, 242, 247))
    ink = _hex_rgb(getattr(config, "WHITEBOARD_INK_COLOR", "#0F172A"), (15, 23, 42))
    accent = _hex_rgb(getattr(config, "WHITEBOARD_ACCENT_COLOR", "#2563EB"), (37, 99, 235))
    is_dark = (0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]) / 255.0 < 0.46
    surface = (29, 41, 61) if is_dark else (255, 255, 255)

    img = Image.new("RGB", (w, h), bg)
    draw = ImageDraw.Draw(img)

    # Khung sân khấu editorial bo góc có chiều sâu
    pad_x = int(w * 0.08)
    pad_y = int(h * 0.10)
    card_box = (pad_x, pad_y, w - pad_x, int(h * 0.80))
    draw.rounded_rectangle(card_box, radius=32, fill=surface, outline=ink, width=6)

    # Biểu tượng khiên Khắc kỷ cân đối ở trung tâm
    cx, cy = w // 2, int(h * 0.45)
    s = int(min(w, h) * 0.17)
    shield_pts = [
        (cx, cy - s),
        (cx + int(s * 0.82), cy - int(s * 0.65)),
        (cx + int(s * 0.72), cy + int(s * 0.25)),
        (cx, cy + int(s * 0.96)),
        (cx - int(s * 0.72), cy + int(s * 0.25)),
        (cx - int(s * 0.82), cy - int(s * 0.65)),
    ]
    draw.polygon(shield_pts, fill=bg, outline=ink)
    draw.line(shield_pts + [shield_pts[0]], fill=ink, width=8)
    # Dấu tick nhấn bên trong khiên
    draw.line(
        [(cx - int(s * 0.28), cy), (cx - int(s * 0.05), cy + int(s * 0.24)), (cx + int(s * 0.34), cy - int(s * 0.24))],
        fill=accent,
        width=12,
    )
    # Thanh nhấn đối xứng hai bên
    draw.line((cx - s - 120, cy, cx - s - 36, cy), fill=accent, width=8)
    draw.line((cx + s + 36, cy, cx + s + 120, cy), fill=accent, width=8)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, format="PNG")
    return output_path


def _produce_scene_assets(
    scene: Dict[str, Any],
    scene_idx: int,
    total_scenes: int,
    scene_dir: Path,
    resolution: tuple[int, int],
    tts: TTSGenerator,
    vertex: VertexAIClient,
    regenerate_visual_only: bool = False,
    beat_global_offset: int = 0,
    elapsed_offset_sec: float = 0.0,
    prev_beat_svg: str | None = None,
) -> tuple[Path, float]:
    """Tạo tài nguyên (TTS + Imagen 2D + Pillow Overlay) và render clip cho 1 phân cảnh."""
    audio_stem = scene_dir / f"scene_{scene_idx:02d}"
    cached_audio_path = Path(scene["_cached_audio_path"]) if scene.get("_cached_audio_path") else None
    image_path = scene_dir / f"scene_{scene_idx:02d}_art.png"
    overlay_path = scene_dir / f"scene_{scene_idx:02d}_overlay.png"
    clip_path = scene_dir / f"scene_{scene_idx:02d}.mp4"

    # 1. Tạo giọng đọc (giữ lại audio cũ nếu chỉ đang sửa lỗi hình ảnh khi retry)
    if not regenerate_visual_only or cached_audio_path is None or not cached_audio_path.exists():
        audio_path, duration_sec = tts.synthesize_scene(scene["narration"], audio_stem)
        scene["_cached_audio_path"] = str(audio_path)
        scene["_cached_duration"] = duration_sec
    else:
        audio_path = cached_audio_path
        duration_sec = float(scene.get("_cached_duration", 15.0))

    # 2. Tạo 3–4 ảnh 2D độc lập theo từng `visual_beats` (cứ ~3–4 giây đổi 1 ảnh khớp đúng cụm từ)
    raw_beats = scene.get("visual_beats")
    if not isinstance(raw_beats, list) or len(raw_beats) == 0:
        raw_beats = [
            {
                "beat_id": 1,
                "phrase": scene.get("narration", ""),
                "caption": scene.get("quote_overlay", ""),
                "image_prompt": scene["image_prompt"],
            }
        ]
    active_beats = [dict(b) for b in raw_beats[:4]]
    scene_narration_str = str(scene.get("narration") or "").strip()
    if scene_narration_str and active_beats:
        reconciled_phrases = reconcile_visual_beats_to_narration(scene_narration_str, active_beats)
        for b_item, r_phrase in zip(active_beats, reconciled_phrases):
            if r_phrase:
                b_item["phrase"] = r_phrase

    beat_images: List[Path] = []
    beat_svgs: List[str | None] = []
    beat_phrases: List[str] = []
    beat_weights: List[float] = []
    use_studio_vector = getattr(config, "VIDEO_VISUAL_MODE", "") == "stickman_whiteboard"
    studio_theme = resolve_studio_theme() if use_studio_vector else None

    if use_studio_vector and studio_theme is not None:
        variation_shift = 1 if regenerate_visual_only else 0
        blueprints = vertex.direct_studio_scene_beats(
            narration=scene.get("narration", ""),
            beats=active_beats,
            language=config.LANGUAGE,
            task_name=f"studio_director_s{scene_idx:02d}",
            variation_shift=variation_shift,
            chapter_header=str(scene.get("chapter_header") or "").strip() or None,
        )
        for b_idx, (beat, bp) in enumerate(zip(active_beats, blueprints)):
            beat_img_path = (
                image_path if b_idx == 0 else scene_dir / f"scene_{scene_idx:02d}_beat_{b_idx:02d}_art.png"
            )
            generated_svg: str | None = None
            try:
                generated_svg = render_studio_shot_svg(
                    blueprint=bp,
                    theme=studio_theme,
                    aspect_ratio=config.ASPECT_RATIO,
                )
                rasterize_svg_to_png(
                    svg_markup=generated_svg,
                    output_path=beat_img_path,
                    width=resolution[0],
                    height=resolution[1],
                )
            except Exception as svg_err:
                logger.warning(
                    "[STUDIO SVG FALLBACK] Cảnh %d beat #%d rasterize lỗi (%s) -> dùng ảnh vector dự phòng.",
                    scene_idx + 1,
                    b_idx + 1,
                    svg_err,
                )
                generated_svg = None
                _render_fallback_scene_art(beat_img_path, resolution)

            beat_images.append(beat_img_path)
            beat_svgs.append(generated_svg)
            phrase_str = str(beat.get("phrase") or scene.get("narration") or "").strip()
            beat_phrases.append(phrase_str)
            phrase_words = max(3, len(phrase_str.split()))
            beat_weights.append(float(phrase_words))

        # Nghỉ nhẹ giữa các phân cảnh (chỉ 1 LLM call/cảnh nên rất nhẹ RPM)
        time.sleep(0.4)
    else:
        for b_idx, beat in enumerate(active_beats):
            beat_img_path = (
                image_path if b_idx == 0 else scene_dir / f"scene_{scene_idx:02d}_beat_{b_idx:02d}_art.png"
            )
            unique_seed = random.randint(10_000, 2_147_483_000)
            prompt = str(beat.get("image_prompt") or scene["image_prompt"]).strip()
            if regenerate_visual_only:
                prompt = (
                    f"{prompt}. Fresh uncluttered centered composition, simple iconic 2D shapes, "
                    "strictly zero embedded text or letters, no distorted hands, open clean bottom margin."
                )

            try:
                vertex.generate_image(
                    prompt=prompt,
                    output_path=beat_img_path,
                    aspect_ratio=config.ASPECT_RATIO,
                    seed=unique_seed,
                    task_name=f"imagen_s{scene_idx:02d}_b{b_idx:02d}",
                )
            except Exception as img_err:
                logger.warning(
                    "[IMAGEN FALLBACK] Cảnh %d ảnh #%d không tạo được từ Vertex AI (%s) -> dùng ảnh vector tối giản.",
                    scene_idx + 1,
                    b_idx + 1,
                    img_err,
                )
                _render_fallback_scene_art(beat_img_path, resolution)

            beat_images.append(beat_img_path)
            beat_svgs.append(None)
            phrase_str = str(beat.get("phrase") or scene.get("narration") or "").strip()
            beat_phrases.append(phrase_str)
            phrase_words = max(3, len(phrase_str.split()))
            beat_weights.append(float(phrase_words))

            # Nhịp nghỉ nhẹ giữa các ảnh liên tiếp để không dồn RPM gây lỗi 429
            delay_sec = float(getattr(config, "IMAGE_REQUEST_DELAY_SEC", 1.2))
            if delay_sec > 0:
                time.sleep(delay_sec)

    try:
        scene_env = extract_audio_energy_envelope(audio_path, samples_per_sec=30)
    except Exception:
        scene_env = None

    scene_narration_for_sync = str(scene.get("narration") or "").strip()
    if scene_narration_for_sync and beat_phrases:
        beat_phrases, synced_beat_durs, beat_word_ranges = schedule_scene_speech_and_beats(
            narration=scene_narration_for_sync,
            beat_phrases=beat_phrases,
            energy_envelope=scene_env,
            audio_duration_sec=duration_sec,
            trailing_gap_sec=0.0,
            samples_per_sec=30,
        )
        beat_durations = [round(d, 3) for d in synced_beat_durs]
    else:
        beat_word_ranges = None
        beat_durations = align_beat_bounds_to_audio_silences(
            weights=beat_weights,
            energy_envelope=scene_env,
            duration_sec=duration_sec,
            samples_per_sec=30,
        )
        beat_durations = [round(d, 3) for d in beat_durations]

    if beat_durations:
        diff = round(duration_sec - sum(beat_durations), 3)
        beat_durations[-1] = max(0.35, round(beat_durations[-1] + diff, 3))

    scene["_beat_count"] = len(beat_images)
    scene["_last_beat_svg"] = beat_svgs[-1] if beat_svgs else None
    scene["_beat_global_offset"] = beat_global_offset
    scene["_elapsed_offset_sec"] = elapsed_offset_sec

    # 3. Nếu là chế độ Studio Vector (`stickman_whiteboard`): chạy bộ Motion Graphics đa lớp 30fps 1:1 với Local
    if use_studio_vector and any(svg is not None for svg in beat_svgs):
        try:
            motion_theme = build_motion_theme_style(
                bg_color=studio_theme.bg_color if studio_theme else None,
                ink_color=studio_theme.ink_color if studio_theme else None,
                accent_color=studio_theme.accent_color if studio_theme else None,
            )
            render_motion_beat_scene_clip(
                beat_svgs=beat_svgs,
                beat_durations=beat_durations,
                audio_path=audio_path,
                output_clip_path=clip_path,
                resolution=resolution,
                scene_index=scene_idx,
                total_scenes=total_scenes,
                beat_global_offset=beat_global_offset,
                elapsed_offset_sec=elapsed_offset_sec,
                prev_beat_svg=prev_beat_svg,
                cached_full_pngs=beat_images,
                theme=motion_theme,
                beat_phrases=beat_phrases,
                scene_narration=scene_narration_for_sync,
            )
            return clip_path, duration_sec
        except Exception as motion_err:
            logger.warning(
                "[STUDIO MOTION FALLBACK] Cảnh %d motion graphics gặp lỗi (%s) -> chuyển về FFmpeg zoom/fade dự phòng.",
                scene_idx + 1,
                motion_err,
            )

    # 4. Vẽ lớp phủ 2D trong suốt bằng Pillow cho chế độ ken_burns_2d / pen_sketch / dự phòng
    scene_narration = str(scene.get("narration") or "").strip()
    quote_text = "" if scene_narration else str(scene.get("quote_overlay", "")).strip()

    render_scene_overlay(
        output_path=overlay_path,
        resolution=resolution,
        scene_index=scene_idx,
        total_scenes=total_scenes,
        quote_overlay=quote_text,
    )

    # 5. Render clip phân cảnh nối 3–4 ảnh con trên cùng 1 giọng đọc liên mạch (khớp 100% duration)
    if len(beat_images) > 1 and config.VIDEO_VISUAL_MODE != "pen_sketch":
        render_multi_beat_scene_clip(
            beat_images=beat_images,
            beat_durations=beat_durations,
            overlay_path=overlay_path,
            audio_path=audio_path,
            output_clip_path=clip_path,
            motion_type=scene.get("motion_type", "zoom_in"),
            resolution=resolution,
            narration_text=scene_narration,
        )
    else:
        render_scene_clip(
            image_path=beat_images[0],
            overlay_path=overlay_path,
            audio_path=audio_path,
            output_clip_path=clip_path,
            duration_sec=duration_sec,
            motion_type=scene.get("motion_type", "zoom_in"),
            resolution=resolution,
            narration_text=scene_narration,
        )
    return clip_path, duration_sec


def run_worker(video_index: int) -> None:
    """Thực thi toàn bộ Giai đoạn 2 cho 1 video độc lập theo VIDEO_INDEX."""
    scripts_path = Path(config.SCRIPTS_JSON_PATH)
    if not scripts_path.exists():
        raise FileNotFoundError(
            f"Không tìm thấy {scripts_path}. Hãy chắc chắn Giai đoạn 1 đã hoàn thành và tải artifact."
        )

    bundle = json.loads(scripts_path.read_text(encoding="utf-8"))
    scripts: List[Dict[str, Any]] = bundle.get("scripts", [])
    if video_index < 0 or video_index >= len(scripts):
        raise IndexError(
            f"VIDEO_INDEX={video_index} vượt phạm vi danh sách kịch bản (có {len(scripts)} kịch bản)."
        )

    script = scripts[video_index]
    scenes: List[Dict[str, Any]] = script["scenes"]
    resolution = config.get_video_resolution()
    date_tag = datetime.now(timezone.utc).strftime("%Y%m%d")
    slug = _slugify_filename(script["title"])

    workdir = Path(config.WORK_DIR) / f"video_{video_index}_{date_tag}"
    scene_dir = workdir / "scenes"
    scene_dir.mkdir(parents=True, exist_ok=True)

    vertex = VertexAIClient()
    tts = TTSGenerator(language=script.get("language", config.LANGUAGE), vertex=vertex)
    drive = DriveManager()

    logger.info(
        "[PIPELINE BUILD %s] ========== BẮT ĐẦU SẢN XUẤT VIDEO #%d: '%s' (%d cảnh | %s) ==========",
        getattr(config, "PIPELINE_BUILD", "v3.11"),
        video_index,
        script["title"],
        len(scenes),
        config.ASPECT_RATIO,
    )

    try:
        scene_clips: List[Path] = []
        bgm_path = pick_random_bgm() or ensure_ambient_bgm(workdir)

        # Xác định số thứ tự & tên thư mục Google Drive theo chủ đề video (bắt đầu từ 1, nối tiếp số hiện có trên Drive)
        folder_number = script.get("folder_number")
        if folder_number is None:
            folder_number = drive.get_next_folder_sequence()
        folder_number = int(folder_number)
        drive_folder_name = script.get("drive_folder_name") or drive.format_numbered_folder_name(
            folder_number, script["title"]
        )

        final_local_mp4 = workdir / f"{folder_number}_{slug}.mp4"
        thumbnail_art_path = workdir / "thumbnail_art.png"
        final_thumbnail_png = workdir / f"{folder_number}_thumbnail.png"

        # Vòng đầu tiên: sản xuất toàn bộ phân cảnh (truyền beat offset & đồng hồ liên tục xuyên suốt)
        running_beat_offset = 0
        running_elapsed_sec = 0.0
        prev_scene_last_svg: str | None = None
        for idx, scene in enumerate(scenes):
            clip_path, scene_dur = _produce_scene_assets(
                scene=scene,
                scene_idx=idx,
                total_scenes=len(scenes),
                scene_dir=scene_dir,
                resolution=resolution,
                tts=tts,
                vertex=vertex,
                regenerate_visual_only=False,
                beat_global_offset=running_beat_offset,
                elapsed_offset_sec=running_elapsed_sec,
                prev_beat_svg=prev_scene_last_svg,
            )
            scene_clips.append(clip_path)
            running_beat_offset += int(scene.get("_beat_count", 1))
            running_elapsed_sec += float(scene_dur) + 0.35
            prev_scene_last_svg = scene.get("_last_beat_svg")

        concatenate_and_mix_bgm(scene_clips, final_local_mp4, bgm_path=bgm_path)

        # Kiểm duyệt tự động & tự sửa lỗi (tối đa max_retries = 2)
        review_passed = False
        for retry in range(config.VIDEO_REVIEW_MAX_RETRIES + 1):
            qa = review_final_video(final_local_mp4, script, vertex, workdir)
            if qa.passed:
                review_passed = True
                logger.info("[QA PASSED] Video #%d đạt chuẩn sau %d lần sửa.", video_index, retry)
                break

            if retry >= config.VIDEO_REVIEW_MAX_RETRIES:
                logger.warning(
                    "[QA MAX RETRIES] Video #%d vẫn chưa đạt sau %d lần sửa (%s). "
                    "Sẽ gắn tiền tố [CHECK_REQUIRED]_ trước khi upload.",
                    video_index,
                    config.VIDEO_REVIEW_MAX_RETRIES,
                    qa.technical_issues + qa.vision_issues,
                )
                break

            # Xác định các cảnh cần sửa lại (nếu Vision không chỉ đích danh, chọn 2 cảnh nghi ngờ đầu tiên)
            bad_zero_based: Set[int] = {i - 1 for i in qa.bad_scene_indices if 1 <= i <= len(scenes)}
            if not bad_zero_based:
                bad_zero_based = {0, min(1, len(scenes) - 1)}

            logger.warning(
                "[SELF-HEAL RETRY %d/%d] Đang vẽ & render lại các phân cảnh lỗi: %s",
                retry + 1,
                config.VIDEO_REVIEW_MAX_RETRIES,
                sorted(i + 1 for i in bad_zero_based),
            )

            regen_audio = len(qa.technical_issues) > 0
            for scene_idx in sorted(bad_zero_based):
                retry_prev_svg = (
                    scenes[scene_idx - 1].get("_last_beat_svg") if scene_idx > 0 else None
                )
                new_clip, _ = _produce_scene_assets(
                    scene=scenes[scene_idx],
                    scene_idx=scene_idx,
                    total_scenes=len(scenes),
                    scene_dir=scene_dir,
                    resolution=resolution,
                    tts=tts,
                    vertex=vertex,
                    regenerate_visual_only=not regen_audio,
                    beat_global_offset=int(scenes[scene_idx].get("_beat_global_offset", scene_idx * 4)),
                    elapsed_offset_sec=float(scenes[scene_idx].get("_elapsed_offset_sec", scene_idx * 12.0)),
                    prev_beat_svg=retry_prev_svg,
                )
                scene_clips[scene_idx] = new_clip

            concatenate_and_mix_bgm(scene_clips, final_local_mp4, bgm_path=bgm_path)

        # Tạo ảnh Thumbnail YouTube 1280x720 đồng bộ 100% phong cách Studio & chủ đề video
        thumb_prompt = (script.get("thumbnail_prompt") or "").strip()
        if not thumb_prompt and scenes:
            thumb_prompt = scenes[0].get("image_prompt", "")

        thumb_headline = (script.get("thumbnail_hook") or script["title"]).strip().upper()
        thumb_subtitle = (script.get("core_quote") or "").strip()

        if getattr(config, "VIDEO_VISUAL_MODE", "") == "stickman_whiteboard":
            try:
                thumb_bp = vertex.direct_studio_thumbnail(
                    title=script["title"],
                    hook=thumb_headline,
                    prompt_hint=thumb_prompt,
                    task_name=f"studio_thumb_v{video_index}",
                )
                is_vi = str(script.get("language", config.LANGUAGE)).startswith("vi")
                badge_label = f"TẬP #{folder_number:02d}" if is_vi else f"EP #{folder_number:02d}"
                thumb_svg = render_studio_thumbnail_svg(
                    headline=thumb_headline,
                    subtitle=thumb_subtitle,
                    badge_label=badge_label,
                    blueprint=thumb_bp,
                    theme=resolve_studio_theme(),
                )
                rasterize_svg_to_png(thumb_svg, final_thumbnail_png, 1280, 720)
                logger.info("[STUDIO THUMBNAIL] Đã xuất Thumbnail Vector 1280x720: %s", final_thumbnail_png.name)
            except Exception as thumb_svg_err:
                logger.warning(
                    "[STUDIO THUMBNAIL FALLBACK] SVG thumbnail lỗi (%s) -> dùng Pillow thumbnail.",
                    thumb_svg_err,
                )
                fallback_art = scene_dir / "scene_00_art.png"
                if fallback_art.exists():
                    shutil.copy2(fallback_art, thumbnail_art_path)
                render_youtube_thumbnail(
                    art_image_path=thumbnail_art_path,
                    output_path=final_thumbnail_png,
                    headline=thumb_headline,
                    subtitle=thumb_subtitle,
                    folder_number=folder_number,
                )
        else:
            try:
                vertex.generate_image(
                    prompt=(
                        f"{thumb_prompt}. Bold high-CTR YouTube thumbnail focal artwork, "
                        "expressive subject, clean uncluttered framing, strictly no embedded text."
                    ),
                    output_path=thumbnail_art_path,
                    aspect_ratio="16:9",
                    seed=random.randint(10_000, 2_147_483_000),
                    task_name=f"imagen_thumbnail_v{video_index}",
                )
            except Exception as thumb_err:
                logger.warning("[THUMBNAIL] Imagen gặp lỗi (%s), dùng ảnh cảnh 1 làm dự phòng.", thumb_err)
                fallback_art = scene_dir / "scene_00_art.png"
                if fallback_art.exists():
                    shutil.copy2(fallback_art, thumbnail_art_path)

            render_youtube_thumbnail(
                art_image_path=thumbnail_art_path,
                output_path=final_thumbnail_png,
                headline=thumb_headline,
                subtitle=thumb_subtitle,
                folder_number=folder_number,
            )

        # Gắn tiền tố [CHECK_REQUIRED]_ cho tên video nếu sau 2 lần sửa vẫn chưa đạt chuẩn
        remote_video_name = final_local_mp4.name
        if not review_passed:
            remote_video_name = f"[CHECK_REQUIRED]_{remote_video_name}"

        # Luôn lưu bản sao vào output/artifacts/video_{video_index} để GitHub Actions đính kèm tải về
        artifact_dir = Path(config.OUTPUT_DIR) / "artifacts" / f"video_{video_index}"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(final_local_mp4, artifact_dir / remote_video_name)
        shutil.copy2(final_thumbnail_png, artifact_dir / final_thumbnail_png.name)
        logger.info("[ARTIFACT READY] Đã lưu bản dự phòng tại %s", artifact_dir)

        # Tạo thư mục con theo chủ đề & số thứ tự kế tiếp trên Google Drive, rồi upload Video + Thumbnail vào chung 1 folder
        from src.drive_manager import is_storage_quota_error

        try:
            video_folder_id = drive.get_or_create_subfolder(drive_folder_name)
            drive.upload_video(
                final_local_mp4,
                remote_filename=remote_video_name,
                target_folder_id=video_folder_id,
            )
            drive.upload_thumbnail(
                final_thumbnail_png,
                remote_filename=final_thumbnail_png.name,
                target_folder_id=video_folder_id,
            )
            logger.info(
                "[WORKER #%d DONE] Đã upload Video ('%s') & Thumbnail ('%s') vào thư mục Drive '%s'.",
                video_index,
                remote_video_name,
                final_thumbnail_png.name,
                drive_folder_name,
            )
        except Exception as drive_err:
            if is_storage_quota_error(drive_err):
                logger.warning(
                    "[DRIVE QUOTA] Không thể upload Video #%d lên My Drive cá nhân bằng Service Account "
                    "(403 storageQuotaExceeded). Hãy thêm secret GDRIVE_OAUTH_TOKEN_JSON (OAuth Gmail cá nhân). "
                    "Video & Thumbnail đã được lưu an toàn trong GitHub Actions Artifacts!",
                    video_index,
                )
            else:
                raise

    finally:
        # Xóa sạch toàn bộ file tạm sau khi hoàn tất để giữ sạch ổ đĩa runner
        if workdir.exists():
            shutil.rmtree(workdir, ignore_errors=True)
            logger.info("[CLEANUP] Đã xóa thư mục tạm %s", workdir)


if __name__ == "__main__":
    raw_idx = os.getenv("VIDEO_INDEX")
    if raw_idx is None:
        raise EnvironmentError("Thiếu biến môi trường VIDEO_INDEX (giá trị từ 0 đến 4).")
    run_worker(int(raw_idx))
