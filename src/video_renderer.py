"""
src/video_renderer.py — Render video 2D tối ưu tốc độ trên CPU Runner (GitHub Actions Ubuntu).

- Dùng cờ `-preset ultrafast -tune stillimage -r 24` để render cực nhanh không cần GPU.
- Chuyển động camera 2D mượt mà (`zoom_in`, `zoom_out`, `pan_left`, `pan_right`) trên ảnh tĩnh.
- Ghép lớp đồ họa 2D RGBA từ Pillow + giọng đọc từng cảnh (khớp 100% duration) + nhạc nền tùy chọn.
- Hỗ trợ tạo Contact Sheet (1 frame mỗi 15 giây) gửi Gemini Vision tiết kiệm token.
"""

from __future__ import annotations

import logging
import math
import random
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

import config

logger = logging.getLogger("video_renderer")


def _run_ffmpeg(cmd: List[str], label: str) -> None:
    """Chạy lệnh FFmpeg và báo lỗi rõ ràng nếu thất bại."""
    logger.debug("[FFMPEG %s] %s", label, " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.splitlines()[-15:])
        raise RuntimeError(f"FFmpeg thất bại tại bước '{label}':\n{tail}")


def _ffmpeg_tune_args() -> List[str]:
    """Chỉ thêm cờ -tune khi được cấu hình (tránh -tune stillimage làm cứng chuyển động mượt)."""
    tune = str(getattr(config, "FFMPEG_TUNE", "") or "").strip()
    return ["-tune", tune] if tune else []


def _build_motion_filter(
    motion_type: str, width: int, height: int, frames: int, fps: int
) -> str:
    """
    Tạo chuyển động camera mượt theo đường cong sine-eased:
    - Chế độ `stickman_whiteboard`: phóng nhẹ ở tâm (1.00 -> 1.028 -> 1.00), tuyệt đối không
      crop 1.22x hay lia ngang để giữ trọn vẹn khung thẻ trắng, badge 1/4 và hộp Caption ở đáy.
    - Chế độ `ken_burns_2d`: overscan 1.22x + 6 kiểu zoom/pan/thở quang học.
    """
    total_f = max(frames, 1)
    ease = f"(0.5*(1-cos(PI*min(on/{total_f},1))))"

    if getattr(config, "VIDEO_VISUAL_MODE", "") == "stickman_whiteboard":
        if motion_type in ("zoom_out", "pan_left", "drift_down"):
            zoom_expr = f"1.028-0.028*{ease}"
        else:
            zoom_expr = f"1.000+0.028*{ease}"
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},"
            f"zoompan=z='{zoom_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={total_f}:s={width}x{height}:fps={fps}"
        )

    overscan_w = int(width * 1.22)
    overscan_h = int(height * 1.22)
    # Nhịp thở quang học siêu êm (chu kỳ ~4.2 giây) tạo cảm giác khung hình có sức sống
    breath_y = f"(sin(2*PI*on/{max(fps * 4.2, 1.0):.2f})*ih*0.008)"

    if motion_type == "zoom_in":
        zoom_expr = f"1.02+0.12*{ease}"
        x_expr = f"iw/2-(iw/zoom/2)+(iw*0.015*{ease})"
        y_expr = f"ih/2-(ih/zoom/2)+{breath_y}"
    elif motion_type == "zoom_out":
        zoom_expr = f"1.14-0.11*{ease}"
        x_expr = f"iw/2-(iw/zoom/2)-(iw*0.015*{ease})"
        y_expr = f"ih/2-(ih/zoom/2)+{breath_y}"
    elif motion_type == "pan_left":
        zoom_expr = f"1.12+0.03*{ease}"
        x_expr = f"(iw-iw/zoom)*(0.85-0.70*{ease})"
        y_expr = f"ih/2-(ih/zoom/2)+{breath_y}"
    elif motion_type == "pan_right":
        zoom_expr = f"1.12+0.03*{ease}"
        x_expr = f"(iw-iw/zoom)*(0.15+0.70*{ease})"
        y_expr = f"ih/2-(ih/zoom/2)+{breath_y}"
    elif motion_type == "drift_up":
        zoom_expr = f"1.08+0.06*{ease}"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = f"(ih-ih/zoom)*(0.78-0.56*{ease})"
    else:  # drift_down
        zoom_expr = f"1.12-0.05*{ease}"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = f"(ih-ih/zoom)*(0.22+0.56*{ease})"

    return (
        f"scale={overscan_w}:{overscan_h}:force_original_aspect_ratio=increase,"
        f"crop={overscan_w}:{overscan_h},"
        f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}':"
        f"d={total_f}:s={width}x{height}:fps={fps}"
    )


def render_scene_clip(
    image_path: Path,
    overlay_path: Path,
    audio_path: Path,
    output_clip_path: Path,
    duration_sec: float,
    motion_type: str,
    resolution: Tuple[int, int],
    narration_text: str = "",
) -> Path:
    """
    Render 1 phân cảnh hoàn chỉnh khớp 100% với thời lượng giọng đọc:
    - Nếu `VIDEO_VISUAL_MODE == "pen_sketch"`: Cây bút chuyển động vẽ nét phác họa rồi đổ bóng hiện hình.
    - Nếu `VIDEO_VISUAL_MODE == "stickman_whiteboard"` hoặc `"ken_burns_2d"`:
      Chuyển động camera sine-eased 30fps mượt mà (KHÔNG dùng cây bút di chuyển), kết hợp sub chạy từng từ.
    """
    if config.VIDEO_VISUAL_MODE == "pen_sketch":
        from src.sketch_animator import render_pen_sketch_scene

        return render_pen_sketch_scene(
            image_path=image_path,
            overlay_path=overlay_path,
            audio_path=audio_path,
            output_clip_path=output_clip_path,
            duration_sec=duration_sec,
            resolution=resolution,
            narration_text=narration_text,
        )

    width, height = resolution
    fps = config.VIDEO_FPS
    padded_duration = round(duration_sec + 0.35, 3)
    total_frames = max(1, int(math.ceil(padded_duration * fps)))

    motion_filter = _build_motion_filter(motion_type, width, height, total_frames, fps)
    fade_out_start = max(0.0, padded_duration - 0.22)

    ass_path: Optional[Path] = None
    ass_filter = ""
    if narration_text and narration_text.strip():
        try:
            from src.studio_motion_renderer import write_progressive_ass_subtitle

            ass_path = output_clip_path.with_suffix(".ass")
            write_progressive_ass_subtitle(
                text=narration_text,
                duration_sec=duration_sec,
                output_ass_path=ass_path,
                width=width,
                height=height,
            )
            ass_escaped = (
                str(ass_path.resolve().as_posix())
                .replace("\\", "/")
                .replace(":", "\\:")
                .replace("'", "\\'")
            )
            ass_filter = f",ass=filename='{ass_escaped}'"
        except Exception as ass_err:
            logger.warning("[SUBTITLE ASS FALLBACK] Bỏ qua phụ đề ASS (%s).", ass_err)
            ass_path = None
            ass_filter = ""

    # Filter complex: chuyển động 2D sine-eased -> ghép overlay RGBA -> sub chạy chữ -> fade vào/ra nhẹ
    filter_complex = (
        f"[0:v]{motion_filter},format=rgba[bg];"
        f"[1:v]scale={width}:{height},format=rgba[ov];"
        f"[bg][ov]overlay=0:0:shortest=1"
        f"{ass_filter},"
        f"fade=t=in:st=0:d=0.18,"
        f"fade=t=out:st={fade_out_start:.3f}:d=0.22,"
        f"format=yuv420p[vout];"
        f"[2:a]apad=pad_dur=0.35,atrim=0:{padded_duration:.3f},asetpts=PTS-STARTPTS[aout]"
    )

    output_clip_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(image_path),
        "-loop",
        "1",
        "-t",
        f"{padded_duration:.3f}",
        "-i",
        str(overlay_path),
        "-i",
        str(audio_path),
        "-filter_complex",
        filter_complex,
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        "-c:v",
        "libx264",
        "-preset",
        config.FFMPEG_PRESET,
        *_ffmpeg_tune_args(),
        "-crf",
        config.FFMPEG_CRF,
        "-r",
        str(fps),
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
    try:
        _run_ffmpeg(cmd, f"scene_{output_clip_path.stem}")
    finally:
        if ass_path is not None:
            ass_path.unlink(missing_ok=True)
    return output_clip_path


def render_multi_beat_scene_clip(
    beat_images: List[Path],
    beat_durations: List[float],
    overlay_path: Path,
    audio_path: Path,
    output_clip_path: Path,
    motion_type: str,
    resolution: Tuple[int, int],
    narration_text: str = "",
) -> Path:
    """
    Render 1 phân cảnh gồm 3–4 ảnh nối tiếp nhau (mỗi ảnh ~3–4 giây khớp từng cụm ý lời thoại)
    trên cùng 1 file giọng đọc liên mạch (không bị ngắt câu) để đạt mật độ ~72–96 ảnh / 5 phút.
    Sử dụng chuỗi chuyển cảnh động FFmpeg `xfade` (smoothleft/smoothright/slideleft/slideright/fade)
    kết hợp 6 kiểu camera sine-eased 30fps — loại bỏ hoàn toàn cảm giác chớp đen & đơ tĩnh giữa các ảnh.
    """
    if len(beat_images) <= 1:
        total_dur = sum(beat_durations) if beat_durations else 10.0
        return render_scene_clip(
            image_path=beat_images[0],
            overlay_path=overlay_path,
            audio_path=audio_path,
            output_clip_path=output_clip_path,
            duration_sec=total_dur,
            motion_type=motion_type,
            resolution=resolution,
            narration_text=narration_text,
        )

    width, height = resolution
    fps = config.VIDEO_FPS
    padded_total = round(sum(beat_durations) + 0.35, 3)

    # Phân bổ phần đệm 0.35s vào ảnh cuối để khớp 100% với luồng âm thanh
    adjusted_durs = [max(0.6, float(d)) for d in beat_durations]
    adjusted_durs[-1] = round(adjusted_durs[-1] + 0.35, 3)

    # Thời lượng xfade mượt giữa các beat (tối đa 0.28s, luôn an toàn <= 25% beat ngắn nhất)
    xfade_dur = round(min(0.28, min(adjusted_durs) * 0.25), 3)
    use_xfade = xfade_dur >= 0.08

    is_whiteboard = getattr(config, "VIDEO_VISUAL_MODE", "") == "stickman_whiteboard"
    motion_cycle = ["zoom_in", "zoom_out", "zoom_in", "zoom_out"] if is_whiteboard else ["zoom_in", "pan_right", "zoom_out", "pan_left", "drift_up", "drift_down"]
    xfade_cycle = ["fade"] if is_whiteboard else ["smoothleft", "smoothright", "slideleft", "slideright", "fade"]
    start_idx = motion_cycle.index(motion_type) if motion_type in motion_cycle else 0

    ffmpeg_inputs: List[str] = []
    filter_parts: List[str] = []

    num_beats = len(beat_images)
    for i, (img_path, dur) in enumerate(zip(beat_images, adjusted_durs)):
        ffmpeg_inputs.extend(["-i", str(img_path)])
        # Bù thêm xfade_dur cho mọi beat trước beat cuối để sau khi xfade chồng lấn, tổng thời lượng vẫn khớp 100%
        clip_dur = round(dur + (xfade_dur if (use_xfade and i < num_beats - 1) else 0.0), 3)
        frames = max(2, int(math.ceil(clip_dur * fps)))
        m_type = motion_cycle[(start_idx + i) % len(motion_cycle)]
        m_filter = _build_motion_filter(m_type, width, height, frames, fps)
        intro_fade = "fade=t=in:st=0:d=0.16," if i == 0 else ""
        # Chuẩn hóa timebase + fps + pixel format để xfade luôn khớp khung hình tuyệt đối
        filter_parts.append(
            f"[{i}:v]{m_filter},{intro_fade}settb=1/{fps},fps={fps},format=yuv420p[b{i}];"
        )

    if use_xfade:
        prev_label = "[b0]"
        cum_offset = 0.0
        for i in range(1, num_beats):
            cum_offset = round(cum_offset + adjusted_durs[i - 1], 3)
            tr_name = xfade_cycle[(start_idx + i - 1) % len(xfade_cycle)]
            out_label = "[bgseq_yuv]" if i == num_beats - 1 else f"[xf{i}]"
            filter_parts.append(
                f"{prev_label}[b{i}]xfade=transition={tr_name}:duration={xfade_dur:.3f}:offset={cum_offset:.3f}{out_label};"
            )
            prev_label = out_label
        seq_conv = "[bgseq_yuv]format=rgba[bgseq];"
    else:
        concat_labels = "".join(f"[b{i}]" for i in range(num_beats))
        seq_conv = f"{concat_labels}concat=n={num_beats}:v=1:a=0,format=rgba[bgseq];"

    ov_idx = num_beats
    aud_idx = num_beats + 1
    ffmpeg_inputs.extend(["-loop", "1", "-t", f"{padded_total:.3f}", "-i", str(overlay_path)])
    ffmpeg_inputs.extend(["-i", str(audio_path)])

    ass_path: Optional[Path] = None
    ass_filter = ""
    if narration_text and narration_text.strip():
        try:
            from src.studio_motion_renderer import write_progressive_ass_subtitle

            ass_path = output_clip_path.with_suffix(".ass")
            write_progressive_ass_subtitle(
                text=narration_text,
                duration_sec=sum(beat_durations),
                output_ass_path=ass_path,
                width=width,
                height=height,
            )
            ass_escaped = (
                str(ass_path.resolve().as_posix())
                .replace("\\", "/")
                .replace(":", "\\:")
                .replace("'", "\\'")
            )
            ass_filter = f",ass=filename='{ass_escaped}'"
        except Exception as ass_err:
            logger.warning("[SUBTITLE ASS FALLBACK] Bỏ qua phụ đề ASS (%s).", ass_err)
            ass_path = None
            ass_filter = ""

    fade_out_scene = max(0.0, padded_total - 0.20)
    filter_complex = (
        "".join(filter_parts)
        + seq_conv
        + f"[{ov_idx}:v]scale={width}:{height},format=rgba[ov];"
        + f"[bgseq][ov]overlay=0:0:shortest=1{ass_filter},fade=t=out:st={fade_out_scene:.3f}:d=0.20,format=yuv420p[vout];"
        + f"[{aud_idx}:a]apad=pad_dur=0.35,atrim=0:{padded_total:.3f},asetpts=PTS-STARTPTS[aout]"
    )

    output_clip_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        *ffmpeg_inputs,
        "-filter_complex",
        filter_complex,
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        "-c:v",
        "libx264",
        "-preset",
        config.FFMPEG_PRESET,
        *_ffmpeg_tune_args(),
        "-crf",
        config.FFMPEG_CRF,
        "-r",
        str(fps),
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
    try:
        _run_ffmpeg(cmd, f"multi_beat_{output_clip_path.stem}")
    finally:
        if ass_path is not None:
            ass_path.unlink(missing_ok=True)
    return output_clip_path


def pick_random_bgm() -> Optional[Path]:
    """Chọn ngẫu nhiên 1 file nhạc nền không bản quyền từ assets/bgm/ (nếu có)."""
    bgm_dir = Path(config.ASSETS_BGM_DIR)
    if not bgm_dir.exists():
        return None
    candidates = [
        p
        for p in bgm_dir.iterdir()
        if p.is_file() and p.suffix.lower() in {".mp3", ".wav", ".m4a", ".ogg"}
    ]
    if not candidates:
        return None
    chosen = random.choice(candidates)
    logger.info("[BGM] Đã chọn nhạc nền: %s", chosen.name)
    return chosen


def concatenate_and_mix_bgm(
    scene_clips: List[Path],
    output_video_path: Path,
    bgm_path: Optional[Path] = None,
) -> Path:
    """Ghép toàn bộ phân cảnh bằng concat demuxer (không re-encode video) và trộn nhạc nền."""
    if not scene_clips:
        raise ValueError("Danh sách scene_clips rỗng.")

    concat_list_path = output_video_path.parent / "concat_list.txt"
    lines = [f"file '{clip.resolve().as_posix()}'" for clip in scene_clips]
    concat_list_path.write_text("\n".join(lines), encoding="utf-8")

    merged_no_bgm = output_video_path.parent / "merged_raw.mp4"
    concat_cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list_path),
        "-c",
        "copy",
        str(merged_no_bgm),
    ]
    _run_ffmpeg(concat_cmd, "concat_scenes")

    speed = max(0.75, min(2.0, float(getattr(config, "VIDEO_PLAYBACK_SPEED", 1.25))))
    apply_speed = abs(speed - 1.0) > 0.01

    if bgm_path is None or not bgm_path.exists():
        if not apply_speed:
            merged_no_bgm.replace(output_video_path)
            logger.info("[RENDER] Xuất video hoàn chỉnh (không có BGM): %s", output_video_path.name)
            return output_video_path

        speed_cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(merged_no_bgm),
            "-vf",
            f"setpts=PTS/{speed:.4f}",
            "-af",
            f"atempo={speed:.4f}",
            "-c:v",
            "libx264",
            "-preset",
            config.FFMPEG_PRESET,
            "-crf",
            config.FFMPEG_CRF,
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(config.VIDEO_FPS),
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-movflags",
            "+faststart",
            str(output_video_path),
        ]
        _run_ffmpeg(speed_cmd, f"speed_{speed:.2f}x")
        merged_no_bgm.unlink(missing_ok=True)
        logger.info("[RENDER] Xuất video hoàn chỉnh tốc độ %.2fx: %s", speed, output_video_path.name)
        return output_video_path

    # Trộn nhạc nền lặp vô hạn (-22dB) và áp dụng tốc độ VIDEO_PLAYBACK_SPEED (mặc định 1.25x, giữ cao độ giọng)
    if apply_speed:
        mix_filter = (
            f"[0:v]setpts=PTS/{speed:.4f}[vout];"
            f"[0:a]atempo={speed:.4f}[voice];"
            f"[1:a]volume={config.BGM_VOLUME_DB},afade=t=in:st=0:d=2.5[bgm];"
            "[voice][bgm]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[aout]"
        )
        v_codec_args = [
            "-map",
            "[vout]",
            "-c:v",
            "libx264",
            "-preset",
            config.FFMPEG_PRESET,
            "-crf",
            config.FFMPEG_CRF,
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(config.VIDEO_FPS),
        ]
    else:
        mix_filter = (
            f"[1:a]volume={config.BGM_VOLUME_DB},afade=t=in:st=0:d=2.5[bgm];"
            "[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[aout]"
        )
        v_codec_args = ["-map", "0:v", "-c:v", "copy"]

    mix_cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(merged_no_bgm),
        "-stream_loop",
        "-1",
        "-i",
        str(bgm_path),
        "-filter_complex",
        mix_filter,
        *v_codec_args,
        "-map",
        "[aout]",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-movflags",
        "+faststart",
        str(output_video_path),
    ]
    _run_ffmpeg(mix_cmd, "mix_bgm")
    merged_no_bgm.unlink(missing_ok=True)
    logger.info(
        "[RENDER] Xuất video hoàn chỉnh kèm nhạc nền (tốc độ %.2fx): %s",
        speed,
        output_video_path.name,
    )
    return output_video_path


def generate_contact_sheet(
    video_path: Path,
    output_image_path: Path,
    interval_sec: int = config.CONTACT_SHEET_INTERVAL_SEC,
) -> Path:
    """
    Trích xuất 1 frame mỗi 15 giây và ghép thành duy nhất 1 ảnh lưới (Contact Sheet JPEG)
    để gửi cho Gemini Vision kiểm duyệt mà tiết kiệm >90% token so với tải cả video.
    """
    # Đo tổng thời lượng để tính kích thước lưới (5 cột × N hàng)
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    duration = max(1.0, float(probe.stdout.strip()))
    num_frames = max(1, int(math.ceil(duration / interval_sec)))
    cols = 5
    rows = max(1, int(math.ceil(num_frames / cols)))

    vf = (
        f"fps=1/{interval_sec},"
        "scale=420:-1,"
        f"tile={cols}x{rows}:padding=6:margin=8:color=0x11151E"
    )
    output_image_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vf",
        vf,
        "-frames:v",
        "1",
        "-q:v",
        "3",
        str(output_image_path),
    ]
    _run_ffmpeg(cmd, "contact_sheet")
    logger.info(
        "[CONTACT SHEET] Tạo ảnh lưới %dx%d (%d frame / mỗi %ds) tại %s",
        cols,
        rows,
        num_frames,
        interval_sec,
        output_image_path.name,
    )
    return output_image_path
