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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set

from dotenv import load_dotenv

import config
from src.drive_manager import DriveManager
from src.graphics_2d import render_scene_overlay, render_youtube_thumbnail
from src.tts_generator import TTSGenerator
from src.vertex_client import VertexAIClient
from src.video_renderer import (
    concatenate_and_mix_bgm,
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
                "image_prompt": scene["image_prompt"],
            }
        ]

    beat_images: List[Path] = []
    beat_weights: List[float] = []

    for b_idx, beat in enumerate(raw_beats[:4]):
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
        phrase_words = max(3, len(str(beat.get("phrase") or "").split()))
        beat_weights.append(float(phrase_words))

    total_weight = sum(beat_weights) or float(len(beat_images))
    beat_durations = [
        max(1.4, round(duration_sec * (w / total_weight), 3)) for w in beat_weights
    ]
    # Chuẩn hóa lại tổng thời lượng các ảnh con bằng đúng duration_sec
    scale_factor = duration_sec / max(0.1, sum(beat_durations))
    beat_durations = [round(d * scale_factor, 3) for d in beat_durations]

    # 3. Vẽ lớp phủ 2D trong suốt bằng Pillow (viền, thanh tiến trình, trích dẫn, hạt phim)
    quote_text = scene.get("quote_overlay", "")
    # Nếu lần retry trước nghi ngờ lỗi chữ tràn -> rút gọn an toàn trích dẫn
    if regenerate_visual_only and len(quote_text.split()) > 10:
        quote_text = " ".join(quote_text.split()[:10])

    render_scene_overlay(
        output_path=overlay_path,
        resolution=resolution,
        scene_index=scene_idx,
        total_scenes=total_scenes,
        quote_overlay=quote_text,
    )

    # 4. Render clip phân cảnh nối 3–4 ảnh con trên cùng 1 giọng đọc liên mạch (khớp 100% duration)
    if len(beat_images) > 1 and config.VIDEO_VISUAL_MODE != "pen_sketch":
        render_multi_beat_scene_clip(
            beat_images=beat_images,
            beat_durations=beat_durations,
            overlay_path=overlay_path,
            audio_path=audio_path,
            output_clip_path=clip_path,
            motion_type=scene.get("motion_type", "zoom_in"),
            resolution=resolution,
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
        "========== BẮT ĐẦU SẢN XUẤT VIDEO #%d: '%s' (%d cảnh | %s) ==========",
        video_index,
        script["title"],
        len(scenes),
        config.ASPECT_RATIO,
    )

    try:
        scene_clips: List[Path] = []
        bgm_path = pick_random_bgm()

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

        # Vòng đầu tiên: sản xuất toàn bộ phân cảnh
        for idx, scene in enumerate(scenes):
            clip_path, _ = _produce_scene_assets(
                scene=scene,
                scene_idx=idx,
                total_scenes=len(scenes),
                scene_dir=scene_dir,
                resolution=resolution,
                tts=tts,
                vertex=vertex,
                regenerate_visual_only=False,
            )
            scene_clips.append(clip_path)

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
                new_clip, _ = _produce_scene_assets(
                    scene=scenes[scene_idx],
                    scene_idx=scene_idx,
                    total_scenes=len(scenes),
                    scene_dir=scene_dir,
                    resolution=resolution,
                    tts=tts,
                    vertex=vertex,
                    regenerate_visual_only=not regen_audio,
                )
                scene_clips[scene_idx] = new_clip

            concatenate_and_mix_bgm(scene_clips, final_local_mp4, bgm_path=bgm_path)

        # Tạo ảnh Thumbnail YouTube 1280x720 đồng bộ màu nền & chủ đề video
        thumb_prompt = (script.get("thumbnail_prompt") or "").strip()
        if not thumb_prompt and scenes:
            thumb_prompt = scenes[0].get("image_prompt", "")
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
            headline=script.get("thumbnail_hook") or script["title"],
            subtitle=script.get("core_quote") or "",
            folder_number=folder_number,
        )

        # Gắn tiền tố [CHECK_REQUIRED]_ cho tên video nếu sau 2 lần sửa vẫn chưa đạt chuẩn
        remote_video_name = final_local_mp4.name
        if not review_passed:
            remote_video_name = f"[CHECK_REQUIRED]_{remote_video_name}"

        # Tạo thư mục con theo chủ đề & số thứ tự kế tiếp trên Google Drive, rồi upload Video + Thumbnail vào chung 1 folder
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
