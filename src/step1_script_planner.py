"""
src/step1_script_planner.py — Giai đoạn 1: Lập kế hoạch 5 kịch bản, Lọc trùng 3 tầng & AI Critic Review.

Chạy độc lập ở Job 1 của GitHub Actions:
1. Tải `history_log.json` từ Google Drive qua `dedup_manager.py`.
2. Sinh 5 tổ hợp Ma trận góc nhìn (Triết gia × Bối cảnh × Cấu trúc) trực giao nhau.
3. Viết kịch bản chi tiết ~5 phút đọc (15–20 phân cảnh) cho từng video theo ngôn ngữ cấu hình.
4. Kiểm tra trùng lặp ngữ nghĩa (Embedding + LLM cross-check) và chấm điểm bởi Giám đốc Sáng tạo AI.
   - Nếu điểm < 8.0 hoặc bị trùng ý tưởng => Tự động viết lại tối đa 2 lần.
5. Cập nhật `history_log.json` lên Google Drive và xuất `output/scripts.json` làm artifact cho Job 2.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

import config
from src.dedup_manager import DedupManager, MatrixCombo
from src.drive_manager import DriveManager
from src.vertex_client import VertexAIClient

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("step1_script_planner")

ALLOWED_MOTIONS = ("zoom_in", "zoom_out", "pan_left", "pan_right")


def _language_label() -> str:
    return "Tiếng Việt (Vietnamese)" if config.LANGUAGE.startswith("vi") else "English (Tiếng Anh)"


def _word_target() -> tuple[int, int]:
    return config.TARGET_WORD_COUNT.get(config.LANGUAGE, (750, 820))


def _closing_comment_cta() -> str:
    if config.LANGUAGE.startswith("vi"):
        return "Hãy bình luận ý kiến của bạn ngay dưới video nhé."
    return "Share your thoughts in the comments below."


def _build_writer_system_prompt(history_digest: str) -> str:
    min_words, max_words = _word_target()
    lang_label = _language_label()
    closing_cta = _closing_comment_cta()
    return (
        f"Bạn là Biên kịch trưởng chuyên sâu về chủ đề: {config.CHANNEL_TOPIC}.\n"
        f"Ngôn ngữ bắt buộc cho tiêu đề, lời thoại (narration) và quote_overlay: {lang_label}.\n"
        f"Ngôn ngữ bắt buộc cho `image_prompt`: LUÔN VIẾT BẰNG TIẾNG ANH chuẩn cho Vertex AI Imagen.\n\n"
        f"PHONG CÁCH HÌNH ẢNH 2D CỐ ĐỊNH (bắt buộc nhúng vào mọi `image_prompt`):\n"
        f"{config.VISUAL_STYLE_PROMPT}\n\n"
        "QUY TẮC CẤM TRÙNG LẶP LỊCH SỬ (90 NGÀY QUA):\n"
        "Tuyệt đối KHÔNG lặp lại tiêu đề, góc tiếp cận, câu chuyện mở đầu hoặc trích dẫn chính "
        "của bất kỳ video nào trong danh sách dưới đây:\n"
        f"{history_digest}\n\n"
        "YÊU CẦU KỸ THUẬT KỊCH BẢN (CHUẨN VIDEO GIẢI THÍCH BẢNG TRẮNG 5 PHÚT):\n"
        f"1. Tổng độ dài lời thoại (`narration`) toàn video phải đạt {min_words}–{max_words} từ (~5 phút đọc).\n"
        f"2. Chia thành đúng {config.SCENES_MIN} đến {config.SCENES_MAX} phân cảnh mạch lạc theo cấu trúc giải thích dễ hiểu: Hook đánh trúng vấn đề (cảnh 1–2) -> 4 Nguyên lý đánh số #1, #2, #3, #4 kèm cách áp dụng cụ thể -> Tổng kết checklist -> Cảnh cuối cùng (Câu chốt + câu hỏi mở + kêu gọi bình luận).\n"
        "3. Phân cảnh 1–2 (15 giây đầu tiên) phải là một Hook sắc bén, đặt vấn đề trực diện, không chào hỏi sáo rỗng.\n"
        f"4. CHIA NHIỀU ẢNH DÀY THEO TỪNG CỤM Ý (3–4 ẢNH / CẢNH = ~72–96 ẢNH CHO 5 PHÚT, ~3–4 GIÂY/ẢNH): Mỗi phân cảnh BẮT BUỘC có mảng `visual_beats` gồm ĐÚNG {config.BEATS_PER_SCENE_MIN} đến {config.BEATS_PER_SCENE_MAX} phần tử ứng với từng cụm từ/ý tưởng trong câu thoại `narration` (ví dụ câu 'khi bị chê bai, thay vì đau khổ, hãy coi đó là luồng gió thổi qua hòn đá tảng tâm trí vững vàng' -> tách thành 4 ảnh: 1. Bị chê bai, 2. Đau khổ bị gạch bỏ, 3. Gió thổi qua tảng đá, 4. Tâm trí vững vàng). Mỗi `visual_beats[i].image_prompt` mô tả DUY NHẤT 1 chủ thể/ẩn dụ trực quan tối giản trên nền {config.WHITEBOARD_BG_COLOR}, nét {config.WHITEBOARD_INK_COLOR}, nhấn {config.WHITEBOARD_ACCENT_COLOR}. TUYỆT ĐỐI KHÔNG vẽ chữ/ký tự bên trong tranh, KHÔNG bàn tay chi tiết hay đám đông rối, KHÔNG dùng từ bạo lực/máu me/vũ khí.\n"
        "5. `quote_overlay`: Từ khóa hoặc câu chốt ngắn tối đa 9 từ (để rỗng `\"\"` ở những cảnh không cần chữ).\n"
        "6. `motion_type`: Chỉ chọn 1 trong 4 giá trị: `zoom_in`, `zoom_out`, `pan_left`, `pan_right` (luân phiên mượt mà).\n"
        f"7. CÂU CHỐT CUỐI VIDEO (BẮT BUỘC): Phân cảnh cuối cùng PHẢI gồm 1 câu tóm tắt đắt giá + 1 câu hỏi gợi mở hành động + kết thúc ĐÚNG bằng câu kêu gọi tương tác: \"{closing_cta}\" (Ví dụ chuẩn: \"Tóm lại, thành công là kết quả của sự lặp lại. Bạn đã sẵn sàng thức dậy vào ngày mai và giành lấy tự do cho chính cuộc đời mình chưa? Hãy bình luận ý kiến của bạn ngay dưới video nhé.\")."
    )


def _build_writer_user_prompt(
    video_slot: int,
    combo: MatrixCombo,
    revision_feedback: Optional[str] = None,
) -> str:
    min_words, max_words = _word_target()
    feedback_section = ""
    if revision_feedback:
        feedback_section = (
            "\n\n[PHẢN HỒI BẮT BUỘC PHẢI KHẮC PHỤC TỪ LẦN DUYỆT TRƯỚC]\n"
            f"{revision_feedback}\n"
            "Hãy thay đổi góc nhìn sâu sắc hơn, loại bỏ hoàn toàn sự sáo rỗng hoặc ý tưởng bị trùng."
        )

    return (
        f"Hãy lên ý tưởng và viết kịch bản hoàn chỉnh cho VIDEO #{video_slot + 1} hôm nay.\n\n"
        "[TỔ HỢP MA TRẬN BẮT BUỘC]\n"
        f"{combo.to_prompt_block()}\n"
        f"{feedback_section}\n\n"
        "Trả về duy nhất 1 JSON object đúng schema sau:\n"
        "{\n"
        '  "title": "Tiêu đề cuốn hút, sắc bén, không giật tít rẻ tiền",\n'
        '  "thumbnail_hook": "Câu chốt ngắn 3-6 từ cực thu hút đặt lên Thumbnail YouTube",\n'
        '  "thumbnail_prompt": "English visual description for a bold high-CTR YouTube thumbnail illustration matching the channel palette",\n'
        '  "angle": "Góc tiếp cận cốt lõi (1 câu ngắn)",\n'
        '  "core_quote": "Câu trích dẫn Khắc kỷ trọng tâm của video",\n'
        '  "summary": "Tóm tắt nội dung cốt lõi trong đúng 1 câu súc tích",\n'
        '  "scenes": [\n'
        "    {\n"
        '      "scene_id": 1,\n'
        '      "narration": "Lời thoại tự nhiên, trầm tĩnh, giàu nhịp điệu (~45-60 từ)",\n'
        '      "image_prompt": "English 2D summary visual description (fallback)",\n'
        '      "quote_overlay": "Trích dẫn ngắn <= 10 từ hoặc chuỗi rỗng",\n'
        '      "motion_type": "zoom_in",\n'
        '      "visual_beats": [\n'
        '        {"beat_id": 1, "phrase": "Cụm từ 1 trong narration", "caption": "2-4 từ ngắn", "image_prompt": "English clean 2D minimalist visual for phrase 1"},\n'
        '        {"beat_id": 2, "phrase": "Cụm từ 2 trong narration", "caption": "2-4 từ ngắn", "image_prompt": "English clean 2D minimalist visual for phrase 2"},\n'
        '        {"beat_id": 3, "phrase": "Cụm từ 3 trong narration", "caption": "2-4 từ ngắn", "image_prompt": "English clean 2D minimalist visual for phrase 3"}\n'
        "      ]\n"
        "    }\n"
        "  ]\n"
        "}\n"
        f"Nhắc lại: Tổng số từ của toàn bộ `narration` phải nằm trong khoảng {min_words}–{max_words} từ, "
        f"số phần tử trong `scenes` từ {config.SCENES_MIN} đến {config.SCENES_MAX}, và mỗi scene có "
        f"{config.BEATS_PER_SCENE_MIN}–{config.BEATS_PER_SCENE_MAX} `visual_beats` để đổi ảnh liên tục mỗi 3–4 giây."
    )


def _evaluate_script_with_critic(
    vertex: VertexAIClient,
    script: Dict[str, Any],
    history_digest: str,
) -> Dict[str, Any]:
    """AI đóng vai Giám đốc Sáng tạo khắt khe chấm điểm kịch bản trên thang 10."""
    first_two_narration = " ".join(s.get("narration", "") for s in script.get("scenes", [])[:2])
    total_words = sum(len(s.get("narration", "").split()) for s in script.get("scenes", []))
    scene_count = len(script.get("scenes", []))

    prompt = (
        "Đánh giá nghiêm khắc kịch bản video Stoicism sau đây trên thang điểm 0.0 đến 10.0.\n\n"
        f"- Tiêu đề: {script.get('title')}\n"
        f"- Góc tiếp cận: {script.get('angle')}\n"
        f"- Trích dẫn cốt lõi: {script.get('core_quote')}\n"
        f"- Tóm tắt: {script.get('summary')}\n"
        f"- Tổng số cảnh: {scene_count} | Tổng số từ: {total_words}\n"
        f"- Hook 15 giây đầu: {first_two_narration}\n"
        f"- Toàn bộ các phân cảnh: {json.dumps(script.get('scenes', []), ensure_ascii=False)}\n\n"
        "LỊCH SỬ VIDEO ĐÃ LÀM (kiểm tra tính mới lạ):\n"
        f"{history_digest[:4000]}\n\n"
        "TIÊU CHÍ CHẤM ĐIỂM (MỖI TIÊU CHÍ TỐI ĐA 2.5 ĐIỂM):\n"
        "1. hook_score: 15s đầu có sắc bén, kéo người xem vào vấn đề ngay lập tức không?\n"
        "2. depth_score: Chiều sâu triết lý Khắc kỷ có thực tế, không rao giảng giáo điều sáo rỗng?\n"
        "3. novelty_score: Góc tiếp cận có thật sự mới so với lịch sử không?\n"
        "4. visual_variety_score: Các image_prompt có đa dạng bố cục giữa các cảnh không?\n\n"
        "Trả về JSON đúng định dạng:\n"
        "{\n"
        '  "hook_score": 2.2,\n'
        '  "depth_score": 2.1,\n'
        '  "novelty_score": 2.3,\n'
        '  "visual_variety_score": 2.0,\n'
        '  "total_score": 8.6,\n'
        '  "is_cliche_or_repetitive": false,\n'
        '  "critique_feedback": "Nhận xét cụ thể điểm cần sửa nếu tổng điểm < 8.0"\n'
        "}"
    )

    return vertex.generate_json(
        prompt=prompt,
        system_instruction=(
            "Bạn là Giám đốc Sáng tạo (Creative Director) cực kỳ khó tính của một kênh YouTube "
            "Triết lý Khắc kỷ triệu người đăng ký. Chỉ cho >= 8.0 khi kịch bản thực sự sắc sảo."
        ),
        temperature=0.2,
        task_name="ai_critic_review",
    )


def _normalize_script(raw_script: Any, combo: MatrixCombo, video_index: int) -> Dict[str, Any]:
    """Chuẩn hóa cấu trúc kịch bản, đảm bảo đủ trường dữ liệu và phong cách 2D đồng nhất."""
    if isinstance(raw_script, list):
        if len(raw_script) == 1 and isinstance(raw_script[0], dict):
            raw_script = raw_script[0]
        elif len(raw_script) > 0 and isinstance(raw_script[0], dict) and (
            "narration" in raw_script[0] or "scene_id" in raw_script[0]
        ):
            raw_script = {"scenes": raw_script}
        else:
            raw_script = {}
    if not isinstance(raw_script, dict):
        raw_script = {}

    scenes_clean: List[Dict[str, Any]] = []
    raw_scenes = raw_script.get("scenes", [])
    if not isinstance(raw_scenes, list):
        raw_scenes = []

    for idx, scene in enumerate(raw_scenes):
        if not isinstance(scene, dict):
            continue
        motion = scene.get("motion_type", ALLOWED_MOTIONS[idx % len(ALLOWED_MOTIONS)])
        if motion not in ALLOWED_MOTIONS:
            motion = ALLOWED_MOTIONS[idx % len(ALLOWED_MOTIONS)]

        img_prompt = (scene.get("image_prompt") or "").strip()
        if config.VISUAL_STYLE_PROMPT[:32].lower() not in img_prompt.lower():
            img_prompt = f"{img_prompt}. {config.VISUAL_STYLE_PROMPT}"

        raw_beats = scene.get("visual_beats")
        beats_clean: List[Dict[str, Any]] = []
        if isinstance(raw_beats, list) and len(raw_beats) > 0:
            for b_idx, beat in enumerate(raw_beats[: config.BEATS_PER_SCENE_MAX]):
                if not isinstance(beat, dict):
                    continue
                b_prompt = (beat.get("image_prompt") or img_prompt).strip()
                if config.VISUAL_STYLE_PROMPT[:32].lower() not in b_prompt.lower():
                    b_prompt = f"{b_prompt}. {config.VISUAL_STYLE_PROMPT}"
                beats_clean.append(
                    {
                        "beat_id": int(beat.get("beat_id") or (b_idx + 1)),
                        "phrase": (beat.get("phrase") or "").strip(),
                        "caption": (beat.get("caption") or beat.get("short_label") or "").strip(),
                        "image_prompt": b_prompt,
                    }
                )

        scenes_clean.append(
            {
                "scene_id": idx + 1,
                "narration": (scene.get("narration") or "").strip(),
                "image_prompt": img_prompt,
                "quote_overlay": (scene.get("quote_overlay") or "").strip(),
                "motion_type": motion,
                "visual_beats": beats_clean,
            }
        )

    # Đảm bảo cảnh cuối cùng LUÔN kết thúc bằng câu kêu gọi bình luận dưới video
    if scenes_clean:
        last_scene = scenes_clean[-1]
        closing_cta = _closing_comment_cta()
        narration_text = (last_scene.get("narration") or "").strip()
        if narration_text and not re.search(
            r"(bình luận|comment|để lại ý kiến|chia sẻ ý kiến)", narration_text, re.IGNORECASE
        ):
            sep = "" if re.search(r"[.!?…]$", narration_text) else "."
            last_scene["narration"] = f"{narration_text}{sep} {closing_cta}"

            beats = last_scene.get("visual_beats") or []
            cta_caption = "Bình luận ngay" if config.LANGUAGE.startswith("vi") else "Comment Below"
            cta_prompt = (
                "Friendly smiling stickman narrator gesturing toward a glowing comment speech bubble. "
                f"{config.VISUAL_STYLE_PROMPT}"
            )
            if 0 < len(beats) < config.BEATS_PER_SCENE_MAX:
                beats.append(
                    {
                        "beat_id": len(beats) + 1,
                        "phrase": closing_cta,
                        "caption": cta_caption,
                        "image_prompt": cta_prompt,
                    }
                )
                last_scene["visual_beats"] = beats
            elif len(beats) >= config.BEATS_PER_SCENE_MAX:
                last_beat = beats[-1]
                prev_phrase = (last_beat.get("phrase") or "").strip()
                if not re.search(r"(bình luận|comment)", prev_phrase, re.IGNORECASE):
                    last_beat["phrase"] = f"{prev_phrase} {closing_cta}".strip()

    thumb_prompt = (raw_script.get("thumbnail_prompt") or "").strip()
    if not thumb_prompt and scenes_clean:
        thumb_prompt = scenes_clean[0]["image_prompt"]
    elif thumb_prompt and config.VISUAL_STYLE_PROMPT[:32].lower() not in thumb_prompt.lower():
        thumb_prompt = f"{thumb_prompt}. {config.VISUAL_STYLE_PROMPT}"

    title_clean = (raw_script.get("title") or f"Stoic Mindset #{video_index + 1}").strip()

    return {
        "video_index": video_index,
        "language": config.LANGUAGE,
        "aspect_ratio": config.ASPECT_RATIO,
        "title": title_clean,
        "thumbnail_hook": (raw_script.get("thumbnail_hook") or title_clean).strip(),
        "thumbnail_prompt": thumb_prompt,
        "angle": (raw_script.get("angle") or combo.narrative_hook).strip(),
        "philosopher": combo.philosopher,
        "modern_context": combo.modern_context,
        "narrative_hook": combo.narrative_hook,
        "core_quote": (raw_script.get("core_quote") or "").strip(),
        "summary": (raw_script.get("summary") or "").strip(),
        "scenes": scenes_clean,
    }


def plan_daily_scripts() -> Path:
    """Chạy toàn bộ Giai đoạn 1: tạo 5 kịch bản đạt chuẩn, gán số thứ tự thư mục Drive & xuất scripts.json."""
    logger.info(
        "[PIPELINE BUILD %s] LLM ưu tiên='%s' | Ngưỡng trùng=%.2f | Số video=%d",
        getattr(config, "PIPELINE_BUILD", "v2.4"),
        config.LLM_FALLBACK_MODELS[0] if config.LLM_FALLBACK_MODELS else "unknown",
        config.SEMANTIC_SIMILARITY_THRESHOLD,
        config.DAILY_VIDEO_COUNT,
    )
    vertex = VertexAIClient()
    drive = DriveManager()
    dedup = DedupManager(drive=drive, vertex=vertex)

    # 1. Nạp lịch sử 90 ngày từ Google Drive & kiểm tra số thứ tự thư mục hiện có trên Drive
    dedup.load_history()
    next_folder_seq = drive.get_next_folder_sequence()

    # 2. Sinh 5 tổ hợp Ma trận góc nhìn khác biệt cho hôm nay
    daily_combos = dedup.sample_daily_combos(count=config.DAILY_VIDEO_COUNT)
    used_signatures = {c.signature() for c in daily_combos}

    approved_scripts: List[Dict[str, Any]] = []

    for video_index, initial_combo in enumerate(daily_combos):
        logger.info(
            "========== ĐANG LÊN KỊCH BẢN VIDEO %d/%d ==========",
            video_index + 1,
            config.DAILY_VIDEO_COUNT,
        )
        current_combo = initial_combo
        revision_feedback: Optional[str] = None
        best_candidate: Optional[Dict[str, Any]] = None
        best_embedding: List[float] = []
        best_score = -1.0
        fallback_candidate: Optional[Dict[str, Any]] = None
        fallback_embedding: List[float] = []
        fallback_sim = 2.0

        for attempt in range(config.SCRIPT_MAX_RETRIES + 1):
            history_digest = dedup.build_history_exclusion_digest()
            sys_prompt = _build_writer_system_prompt(history_digest)
            user_prompt = _build_writer_user_prompt(video_index, current_combo, revision_feedback)

            raw_script = vertex.generate_json(
                prompt=user_prompt,
                system_instruction=sys_prompt,
                temperature=0.78 if attempt == 0 else 0.88,
                task_name=f"script_gen_v{video_index}_try{attempt}",
            )
            candidate = _normalize_script(raw_script, current_combo, video_index)

            # Kiểm tra cấu trúc tối thiểu
            scene_count = len(candidate["scenes"])
            if scene_count < 10:
                revision_feedback = (
                    f"Kịch bản chỉ có {scene_count} cảnh, quá ngắn. "
                    f"Bắt buộc chia thành {config.SCENES_MIN}–{config.SCENES_MAX} phân cảnh."
                )
                logger.warning("[SCRIPT V%d TRY %d] %s", video_index, attempt, revision_feedback)
                continue

            # Tầng 3: Kiểm tra trùng lặp ngữ nghĩa với 90 ngày lịch sử + các video đã duyệt hôm nay
            is_dup, max_sim, matched_title, embedding = dedup.check_semantic_duplicate(candidate)

            # Luôn giữ lại bản ít giống nhất làm phương án dự phòng để không làm sập toàn bộ 5 video
            if max_sim < fallback_sim:
                fallback_sim = max_sim
                fallback_candidate = candidate
                fallback_embedding = embedding
                fallback_candidate["max_history_similarity"] = round(max_sim, 4)

            if is_dup:
                revision_feedback = (
                    f"Ý tưởng bị trùng lặp ngữ nghĩa (độ tương đồng {max_sim:.2%}) với video cũ "
                    f"'{matched_title}'. Hãy chuyển sang góc nhìn hoàn toàn mới!"
                )
                # Đổi luôn sang một tổ hợp ma trận hoàn toàn mới cho lần viết lại
                fresh = dedup.sample_daily_combos(count=1, exclude_signatures=used_signatures)[0]
                current_combo = fresh
                used_signatures.add(fresh.signature())
                logger.warning("[SCRIPT V%d TRY %d] Bị loại do trùng lặp. Đổi tổ hợp mới.", video_index, attempt)
                continue

            # AI Critic Review (Thang 10)
            review = _evaluate_script_with_critic(vertex, candidate, history_digest)
            score = float(review.get("total_score", 0.0))
            candidate["critic_review"] = review
            candidate["max_history_similarity"] = round(max_sim, 4)

            logger.info(
                "[CRITIC V%d TRY %d] Điểm=%.2f/10 | Sim=%.3f | Title='%s'",
                video_index,
                attempt,
                score,
                max_sim,
                candidate["title"],
            )

            if score > best_score:
                best_score = score
                best_candidate = candidate
                best_embedding = embedding

            if score >= config.CRITIC_MIN_SCORE and not review.get("is_cliche_or_repetitive", False):
                logger.info("[APPROVED V%d] Đạt chuẩn chất lượng (%.2f/10)!", video_index, score)
                break

            revision_feedback = (
                f"Điểm AI Critic chỉ đạt {score:.1f}/10 (yêu cầu >= {config.CRITIC_MIN_SCORE}). "
                f"Nhận xét cần sửa: {review.get('critique_feedback', 'Tăng chiều sâu và độ sắc của Hook 15s đầu.')}"
            )
            logger.warning("[REWRITE V%d] Chưa đạt ngưỡng 8.0, viết lại lần %d...", video_index, attempt + 1)

        if best_candidate is None and fallback_candidate is not None:
            logger.warning(
                "[FALLBACK APPROVE V%d] Dùng phương án ít trùng nhất (sim=%.3f) để tiếp tục xuất xưởng: '%s'",
                video_index,
                fallback_sim,
                fallback_candidate.get("title", ""),
            )
            best_candidate = fallback_candidate
            best_embedding = fallback_embedding

        if best_candidate is None:
            raise RuntimeError(f"Không thể tạo kịch bản hợp lệ cho VIDEO #{video_index + 1} sau 3 lần thử.")

        # Gán số thứ tự & tên thư mục Google Drive tuần tự (chống xung đột khi 5 worker chạy song song)
        assigned_number = next_folder_seq + video_index
        best_candidate["folder_number"] = assigned_number
        best_candidate["drive_folder_name"] = drive.format_numbered_folder_name(
            assigned_number, best_candidate["title"]
        )
        logger.info(
            "[DRIVE FOLDER ASSIGNED] Video #%d -> '%s'",
            video_index,
            best_candidate["drive_folder_name"],
        )

        # Lưu vào danh sách duyệt + cập nhật bộ nhớ Dedup ngay lập tức để video sau không trùng video trước
        approved_scripts.append(best_candidate)
        dedup.register_approved_script(best_candidate, best_embedding)

    # 3. Ghi đè history_log.json lên Google Drive
    dedup.save_history()

    # 4. Xuất file output/scripts.json cho Job 2 (Matrix 5 workers)
    output_path = Path(config.SCRIPTS_JSON_PATH)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    bundle = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "language": config.LANGUAGE,
        "aspect_ratio": config.ASPECT_RATIO,
        "video_count": len(approved_scripts),
        "fallback_events": vertex.fallback_events,
        "scripts": approved_scripts,
    }
    output_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("[STEP 1 COMPLETE] Đã xuất %d kịch bản đạt chuẩn tại %s", len(approved_scripts), output_path)
    return output_path


if __name__ == "__main__":
    plan_daily_scripts()
