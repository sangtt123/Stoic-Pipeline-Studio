"""
src/dedup_manager.py — Cơ chế chống trùng lặp nội dung 3 tầng (Anti-Duplication Engine).

Tầng 1: Bộ nhớ lịch sử 90 ngày lưu trên Google Drive (`history_log.json`).
Tầng 2: Ma trận kết hợp ngẫu nhiên có kiểm soát (Triết gia × Bối cảnh × Cấu trúc kể chuyện).
Tầng 3: Kiểm tra độ tương đồng ngữ nghĩa bằng Vertex AI Text Embedding (`text-embedding-004`)
        kết hợp kiểm tra chéo LLM; tự động từ chối nếu độ tương đồng > 75%.
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

import config
from src.drive_manager import DriveManager
from src.vertex_client import VertexAIClient

logger = logging.getLogger("dedup_manager")


@dataclass(frozen=True)
class MatrixCombo:
    philosopher: str
    modern_context: str
    narrative_hook: str
    working_angle: str = ""

    def signature(self) -> str:
        return f"{self.philosopher} || {self.modern_context} || {self.narrative_hook}"

    def to_prompt_block(self) -> str:
        lines = [
            f"- Lăng kính / Lĩnh vực / Nhân vật gợi mở: {self.philosopher}",
            f"- Vấn đề / Tình huống đời thực cụ thể: {self.modern_context}",
            f"- Hình thức kể chuyện & cấu trúc: {self.narrative_hook}",
        ]
        if self.working_angle:
            lines.append(f"- Luận điểm cốt lõi cần khai thác: {self.working_angle}")
        return "\n".join(lines)


def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """Tính Cosine Similarity giữa 2 vector embedding trong khoảng [-1.0, 1.0]."""
    a = np.asarray(vec_a, dtype=np.float32)
    b = np.asarray(vec_b, dtype=np.float32)
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


class DedupManager:
    """Quản lý lịch sử 90 ngày, sinh tổ hợp ma trận góc nhìn và lọc trùng ngữ nghĩa."""

    def __init__(self, drive: DriveManager, vertex: VertexAIClient) -> None:
        self.drive = drive
        self.vertex = vertex
        self.entries: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # TẦNG 1: Đồng bộ & cắt tỉa lịch sử 90 ngày trên Google Drive
    # ------------------------------------------------------------------
    def load_history(self) -> List[Dict[str, Any]]:
        """Tải history_log.json từ Drive, nếu chưa có thì khởi tạo rỗng và lọc trong 90 ngày."""
        raw = self.drive.download_json(config.HISTORY_FILENAME)
        if not raw or not isinstance(raw.get("videos"), list):
            logger.info("[DEDUP T1] Khởi tạo history_log.json mới (chưa có dữ liệu lịch sử).")
            self.entries = []
            return self.entries

        cutoff = datetime.now(timezone.utc) - timedelta(days=config.HISTORY_RETENTION_DAYS)
        kept: List[Dict[str, Any]] = []
        for item in raw["videos"]:
            created_str = item.get("created_at", "")
            try:
                created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                if created_dt >= cutoff:
                    kept.append(item)
            except ValueError:
                # Giữ lại bản ghi nếu định dạng ngày cũ nhưng hợp lệ cơ bản
                kept.append(item)

        pruned_count = len(raw["videos"]) - len(kept)
        self.entries = kept
        logger.info(
            "[DEDUP T1] Đã nạp %d video trong %d ngày gần nhất (đã lược bỏ %d mục cũ hơn).",
            len(self.entries),
            config.HISTORY_RETENTION_DAYS,
            pruned_count,
        )
        return self.entries

    def save_history(self) -> None:
        """Ghi đè history_log.json lên lại Google Drive sau khi hoàn tất lập kế hoạch."""
        from pathlib import Path
        from src.drive_manager import is_storage_quota_error

        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "retention_days": config.HISTORY_RETENTION_DAYS,
            "total_records": len(self.entries),
            "videos": self.entries,
        }
        # Luôn lưu bản dự phòng cục bộ
        local_history = Path(config.OUTPUT_DIR) / config.HISTORY_FILENAME
        local_history.parent.mkdir(parents=True, exist_ok=True)
        local_history.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        try:
            self.drive.upsert_json(config.HISTORY_FILENAME, payload)
        except Exception as exc:
            if is_storage_quota_error(exc):
                logger.warning(
                    "[DRIVE QUOTA] Service Account không có dung lượng lưu trữ để tạo tệp mới trên "
                    "My Drive cá nhân (403 storageQuotaExceeded). Hãy thêm secret GDRIVE_OAUTH_TOKEN_JSON "
                    "(OAuth tài khoản Gmail cá nhân) hoặc dùng Shared Drive. Đã bỏ qua lưu history lên Drive "
                    "để tiếp tục sang Stage 2!"
                )
                return
            raise

    def register_approved_script(self, script: Dict[str, Any], embedding: List[float]) -> None:
        """Lưu kịch bản đã được duyệt vào bộ nhớ hiện tại (để chống trùng ngay trong cùng ngày)."""
        record = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "title": script["title"],
            "angle": script["angle"],
            "philosopher": script["philosopher"],
            "modern_context": script["modern_context"],
            "narrative_hook": script["narrative_hook"],
            "core_quote": script["core_quote"],
            "summary": script["summary"],
            "embedding": embedding,
        }
        self.entries.append(record)

    def build_history_exclusion_digest(self, max_items: int = 80) -> str:
        """Tóm tắt danh sách video gần đây để đưa vào System Prompt cấm AI lặp lại."""
        if not self.entries:
            return "(Chưa có video nào trong lịch sử 90 ngày qua.)"

        recent = self.entries[-max_items:]
        lines = []
        for idx, item in enumerate(recent, start=1):
            lines.append(
                f"{idx}. [{item.get('philosopher', 'N/A')}] "
                f"Tiêu đề: {item.get('title', '')} | "
                f"Góc tiếp cận: {item.get('angle', '')} | "
                f"Trích dẫn: {item.get('core_quote', '')} | "
                f"Tóm tắt: {item.get('summary', '')}"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # TẦNG 2: Động cơ Mở rộng Ý tưởng Tự do (Open-World AI Brainstorming)
    #         + Dự phòng Ma trận Đa lĩnh vực (KHÔNG gò bó danh sách cứng)
    # ------------------------------------------------------------------
    def _brainstorm_open_angles(
        self, count: int, exclude_signatures: Optional[set[str]] = None
    ) -> List[MatrixCombo]:
        """
        Gọi LLM sinh `count` ý tưởng hoàn toàn mới, mở rộng tự do sang nhiều lĩnh vực
        (tâm lý học, khoa học thần kinh, kinh tế hành vi, lịch sử Đông–Tây, chiến lược,
        tài chính, giao tiếp, tiểu sử nhân vật thực tế, triết học...) mà vẫn bám tinh thần
        CHANNEL_TOPIC và TRÁNH TUYỆT ĐỐI mọi chủ đề đã làm trong 90 ngày qua.
        """
        lang_hint = "Tiếng Việt" if config.LANGUAGE.startswith("vi") else "English"
        history_digest = self.build_history_exclusion_digest(max_items=60)
        excluded_today = "\n".join(f"- {sig}" for sig in sorted(exclude_signatures or set())) or "(Chưa có)"

        prompt = (
            f"Hãy lên ý tưởng cho ĐÚNG {count} video YouTube giải thích (explainer ~5 phút) "
            f"bằng {lang_hint} cho kênh có định hướng rộng: {config.CHANNEL_TOPIC}.\n\n"
            "NGUYÊN TẮC MỞ RỘNG NỘI DUNG (QUAN TRỌNG — ĐỂ KÊNH KHÔNG BỊ LẶP KHUÔN):\n"
            "1. KHÔNG BỊ GÒ BÓ vào 5–6 cái tên Khắc kỷ quen thuộc! Hãy tự do mở rộng biên độ sáng tạo sang "
            "nhiều lĩnh vực giàu giá trị cho người trưởng thành: tâm lý học hành vi, khoa học thần kinh về thói quen "
            "& cảm xúc, kinh tế học hành vi, thiên kiến nhận thức, chiến lược cổ kim (Đông & Tây), tiểu sử nhân vật "
            "lịch sử / doanh nhân / khoa học gia ít người biết, tư duy tài chính, đàm phán & giao tiếp sắc bén, "
            "nghệ thuật ra quyết định, hiệu suất sâu, bản lĩnh trong các mối quan hệ, triết học sống hiện đại...\n"
            f"2. MỖI video trong số {count} video hôm nay PHẢI thuộc một LĨNH VỰC / LĂNG KÍNH, một TÌNH HUỐNG ĐỜI THỰC "
            "cụ thể và một HÌNH THỨC KỂ CHUYỆN hoàn toàn khác nhau (trực giao 100%, không trùng ý tưởng lẫn nhau).\n"
            "3. CẤM TUYỆT ĐỐI lặp lại các khuôn sáo cũ kỹ như 'Thử thách 7 ngày', 'Biến mất 90 ngày', "
            "'Nghệ thuật rời đi trong im lặng', hoặc cấu trúc tiêu đề 'Nghịch lý của...' lặp đi lặp lại.\n"
            "4. TUYỆT ĐỐI KHÔNG trùng chủ đề, nhân vật trọng tâm hoặc bài học cốt lõi với lịch sử 90 ngày dưới đây:\n"
            f"{history_digest[:3500]}\n\n"
            f"Các tổ hợp đã chọn trong hôm nay (KHÔNG lặp lại):\n{excluded_today}\n\n"
            "Trả về JSON object đúng định dạng:\n"
            "{\n"
            '  "concepts": [\n'
            "    {\n"
            '      "domain_lens": "Lăng kính / học thuyết / nhân vật / ngành khoa học cụ thể",\n'
            '      "real_world_situation": "Tình huống đời sống hiện đại rất cụ thể và mới mẻ",\n'
            '      "storytelling_format": "Cấu trúc kể chuyện riêng (vd: phân tích thí nghiệm tâm lý, câu chuyện lịch sử thực, bóc tách sai lầm tư duy, mô hình ra quyết định...)",\n'
            '      "working_angle": "Luận điểm sắc bén, khác biệt trong 1 câu ngắn"\n'
            "    }\n"
            "  ]\n"
            "}"
        )

        raw = self.vertex.generate_json(
            prompt=prompt,
            system_instruction=(
                "Bạn là Giám đốc Nội dung sáng tạo đẳng cấp quốc tế. Nhiệm vụ của bạn là mở rộng đề tài "
                "thật phong phú, sắc sảo, mới lạ theo nhiều góc nhìn đa ngành, tuyệt đối không lặp lối mòn."
            ),
            temperature=0.95,
            task_name="brainstorm_open_angles",
        )

        raw_concepts = raw.get("concepts") if isinstance(raw, dict) else None
        if not isinstance(raw_concepts, list):
            return []

        combos: List[MatrixCombo] = []
        seen_sigs = set(exclude_signatures or set())
        for item in raw_concepts:
            if not isinstance(item, dict):
                continue
            lens = str(item.get("domain_lens") or "").strip()
            sit = str(item.get("real_world_situation") or "").strip()
            fmt = str(item.get("storytelling_format") or "").strip()
            angle = str(item.get("working_angle") or "").strip()
            if not (lens and sit and fmt):
                continue
            combo = MatrixCombo(
                philosopher=lens,
                modern_context=sit,
                narrative_hook=fmt,
                working_angle=angle,
            )
            if combo.signature() in seen_sigs:
                continue
            seen_sigs.add(combo.signature())
            combos.append(combo)
            if len(combos) >= count:
                break

        return combos

    def sample_daily_combos(
        self, count: int, exclude_signatures: Optional[set[str]] = None
    ) -> List[MatrixCombo]:
        """
        Sinh `count` định hướng nội dung hoàn toàn mới và trực giao cho hôm nay:
        - Ưu tiên AI Mở rộng Ý tưởng Tự do (OPEN_TOPIC_EXPANSION=True) để không bị gò bó danh sách cứng.
        - Tự động bù/dự phòng từ kho gợi ý mở rộng đa lĩnh vực nếu cần.
        """
        recent_signatures = {
            f"{e.get('philosopher', '')} || {e.get('modern_context', '')} || {e.get('narrative_hook', '')}"
            for e in self.entries[-150:]
        }
        if exclude_signatures:
            recent_signatures |= exclude_signatures

        selected: List[MatrixCombo] = []

        if getattr(config, "OPEN_TOPIC_EXPANSION", True):
            try:
                ai_combos = self._brainstorm_open_angles(count=count, exclude_signatures=recent_signatures)
                for combo in ai_combos:
                    selected.append(combo)
                    recent_signatures.add(combo.signature())
                if selected:
                    logger.info(
                        "[DEDUP T2 OPEN] AI đã tự mở rộng %d/%d định hướng chủ đề mới đa lĩnh vực.",
                        len(selected),
                        count,
                    )
            except Exception as exc:
                logger.warning(
                    "[DEDUP T2 OPEN FALLBACK] Brainstorm mở tạm thời lỗi (%s), dùng kho gợi ý mở rộng.",
                    exc,
                )

        if len(selected) >= count:
            return selected[:count]

        philosophers = config.PHILOSOPHERS_AND_SCHOOLS[:]
        contexts = config.MODERN_CONTEXTS[:]
        hooks = config.NARRATIVE_HOOKS[:]
        random.shuffle(philosophers)
        random.shuffle(contexts)
        random.shuffle(hooks)

        used_phil_today: set[str] = {c.philosopher for c in selected}
        used_ctx_today: set[str] = {c.modern_context for c in selected}
        used_hook_today: set[str] = {c.narrative_hook for c in selected}

        for _ in range(300):
            if len(selected) >= count:
                break
            p = random.choice(philosophers)
            c = random.choice(contexts)
            h = random.choice(hooks)
            combo = MatrixCombo(philosopher=p, modern_context=c, narrative_hook=h)

            if combo.signature() in recent_signatures:
                continue
            if p in used_phil_today or c in used_ctx_today or h in used_hook_today:
                continue

            selected.append(combo)
            used_phil_today.add(p)
            used_ctx_today.add(c)
            used_hook_today.add(h)
            recent_signatures.add(combo.signature())

        while len(selected) < count:
            combo = MatrixCombo(
                philosopher=random.choice(philosophers),
                modern_context=random.choice(contexts),
                narrative_hook=random.choice(hooks),
            )
            if combo.signature() not in recent_signatures:
                selected.append(combo)
                recent_signatures.add(combo.signature())

        logger.info("[DEDUP T2] Đã hoàn tất %d định hướng trực giao cho hôm nay.", len(selected))
        return selected

    # ------------------------------------------------------------------
    # TẦNG 3: Kiểm tra độ tương đồng ngữ nghĩa (Semantic Similarity Check)
    # ------------------------------------------------------------------
    def _build_semantic_text(
        self,
        title: str,
        summary: str,
        core_quote: str,
        angle: str,
        philosopher: str = "",
        modern_context: str = "",
    ) -> str:
        return (
            f"Title: {title}\n"
            f"Philosopher: {philosopher}\n"
            f"Modern Context: {modern_context}\n"
            f"Angle: {angle}\n"
            f"Core Quote: {core_quote}\n"
            f"Summary: {summary}"
        )

    def check_semantic_duplicate(
        self, candidate: Dict[str, Any]
    ) -> Tuple[bool, float, Optional[str], List[float]]:
        """
        Kiểm tra kịch bản ứng viên với toàn bộ lịch sử 90 ngày + các kịch bản đã duyệt trong ngày.
        Lưu ý hiệu chuẩn đa ngôn ngữ (đặc biệt tiếng Việt cùng ngách Stoicism):
        - Các video cùng ngách tiếng Việt thường có cosine nền ~0.76–0.84 trên text-embedding-004.
        - Chỉ loại cứng khi > config.SEMANTIC_SIMILARITY_THRESHOLD (mặc định 0.90).
        - Vùng giáp ranh 0.78–0.90 giao cho LLM kiểm tra chéo ý tưởng thực sự có trùng hay không.
        """
        semantic_text = self._build_semantic_text(
            title=candidate.get("title", ""),
            summary=candidate.get("summary", ""),
            core_quote=candidate.get("core_quote", ""),
            angle=candidate.get("angle", ""),
            philosopher=candidate.get("philosopher", ""),
            modern_context=candidate.get("modern_context", ""),
        )
        candidate_embedding = self.vertex.embed_text(
            semantic_text, task_name="dedup_candidate_embedding"
        )

        if not self.entries:
            return False, 0.0, None, candidate_embedding

        max_sim = 0.0
        closest_entry: Optional[Dict[str, Any]] = None

        for entry in self.entries:
            entry_emb = entry.get("embedding")
            if not entry_emb:
                entry_text = self._build_semantic_text(
                    title=entry.get("title", ""),
                    summary=entry.get("summary", ""),
                    core_quote=entry.get("core_quote", ""),
                    angle=entry.get("angle", ""),
                    philosopher=entry.get("philosopher", ""),
                    modern_context=entry.get("modern_context", ""),
                )
                entry_emb = self.vertex.embed_text(entry_text, task_name="dedup_history_backfill")
                entry["embedding"] = entry_emb

            sim = _cosine_similarity(candidate_embedding, entry_emb)
            if sim > max_sim:
                max_sim = sim
                closest_entry = entry

        matched_title = closest_entry.get("title") if closest_entry else None
        hard_threshold = float(config.SEMANTIC_SIMILARITY_THRESHOLD)
        borderline_floor = max(0.72, round(hard_threshold - 0.12, 2))

        # Ngưỡng cứng > SEMANTIC_SIMILARITY_THRESHOLD => Chắc chắn trùng lặp ngữ nghĩa
        if max_sim > hard_threshold:
            logger.warning(
                "[DEDUP T3 REJECT] Độ tương đồng=%.3f (> %.2f) với video cũ '%s'.",
                max_sim,
                hard_threshold,
                matched_title,
            )
            return True, max_sim, matched_title, candidate_embedding

        # Vùng giáp ranh (borderline_floor .. hard_threshold): Dùng LLM kiểm tra chéo sâu
        if max_sim >= borderline_floor and closest_entry is not None:
            cross_check = self._llm_overlap_crosscheck(candidate, closest_entry)
            if cross_check.get("is_duplicate", False):
                logger.warning(
                    "[DEDUP T3 LLM REJECT] Trùng ý tưởng cốt lõi với '%s' (sim=%.3f): %s",
                    matched_title,
                    max_sim,
                    cross_check.get("reason", ""),
                )
                return True, max_sim, matched_title, candidate_embedding
            logger.info(
                "[DEDUP T3 LLM PASS] Sim=%.3f nhưng AI xác nhận khác chủ đề với '%s': %s",
                max_sim,
                matched_title,
                cross_check.get("reason", ""),
            )

        logger.info(
            "[DEDUP T3 PASS] Độ tương đồng cao nhất=%.3f (ngưỡng cứng %.2f) — Đạt chuẩn mới lạ.",
            max_sim,
            hard_threshold,
        )
        return False, max_sim, matched_title, candidate_embedding

    def _llm_overlap_crosscheck(
        self, candidate: Dict[str, Any], closest_entry: Dict[str, Any]
    ) -> Dict[str, Any]:
        """LLM kiểm tra chéo sâu khi cosine similarity nằm ở vùng ranh giới."""
        prompt = (
            "So sánh 2 ý tưởng video sau đây và đánh giá KHẮT KHE xem chúng có trùng lặp "
            "thông điệp chính, vấn đề thực tế, hoặc bài học cốt lõi đối với người xem hay không.\n"
            "(Nếu chỉ đổi tên nhân vật hoặc đổi tiêu đề nhưng bài học thực tế giống >70% thì vẫn coi là TRÙNG).\n\n"
            f"[VIDEO MỚI]\n"
            f"- Tiêu đề: {candidate.get('title')}\n"
            f"- Lăng kính / Lĩnh vực: {candidate.get('philosopher')}\n"
            f"- Tình huống: {candidate.get('modern_context')}\n"
            f"- Góc tiếp cận: {candidate.get('angle')}\n"
            f"- Câu chốt / Trích dẫn: {candidate.get('core_quote')}\n"
            f"- Tóm tắt: {candidate.get('summary')}\n\n"
            f"[VIDEO ĐÃ SẢN XUẤT]\n"
            f"- Tiêu đề: {closest_entry.get('title')}\n"
            f"- Lăng kính / Lĩnh vực: {closest_entry.get('philosopher')}\n"
            f"- Tình huống: {closest_entry.get('modern_context')}\n"
            f"- Góc tiếp cận: {closest_entry.get('angle')}\n"
            f"- Câu chốt / Trích dẫn: {closest_entry.get('core_quote')}\n"
            f"- Tóm tắt: {closest_entry.get('summary')}\n\n"
            'Trả về JSON: {"is_duplicate": true/false, "reason": "giải thích ngắn gọn 1 câu"}'
        )
        return self.vertex.generate_json(
            prompt=prompt,
            system_instruction="Bạn là biên tập viên chống trùng lặp nội dung cực kỳ khắt khe.",
            temperature=0.1,
            task_name="dedup_llm_crosscheck",
        )
