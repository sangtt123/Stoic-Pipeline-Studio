"""
src/dedup_manager.py — Cơ chế chống trùng lặp nội dung 3 tầng (Anti-Duplication Engine).

Tầng 1: Bộ nhớ lịch sử 90 ngày lưu trên Google Drive (`history_log.json`).
Tầng 2: Ma trận kết hợp ngẫu nhiên có kiểm soát (Triết gia × Bối cảnh × Cấu trúc kể chuyện).
Tầng 3: Kiểm tra độ tương đồng ngữ nghĩa bằng Vertex AI Text Embedding (`text-embedding-004`)
        kết hợp kiểm tra chéo LLM; tự động từ chối nếu độ tương đồng > 75%.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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

    def signature(self) -> str:
        return f"{self.philosopher} || {self.modern_context} || {self.narrative_hook}"

    def to_prompt_block(self) -> str:
        return (
            f"- Triết gia / Trường phái trọng tâm: {self.philosopher}\n"
            f"- Bối cảnh đời thực hiện đại: {self.modern_context}\n"
            f"- Cấu trúc kể chuyện (Narrative Hook): {self.narrative_hook}"
        )


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
    # TẦNG 2: Ma trận kết hợp ngẫu nhiên có kiểm soát (Angle & Persona Matrix)
    # ------------------------------------------------------------------
    def sample_daily_combos(
        self, count: int, exclude_signatures: Optional[set[str]] = None
    ) -> List[MatrixCombo]:
        """
        Chọn ngẫu nhiên `count` tổ hợp (Triết gia × Bối cảnh × Cấu trúc) hoàn toàn khác nhau
        trong ngày và tránh các tổ hợp đã dùng trong 30 ngày gần nhất.
        """
        recent_signatures = {
            f"{e.get('philosopher', '')} || {e.get('modern_context', '')} || {e.get('narrative_hook', '')}"
            for e in self.entries[-150:]
        }
        if exclude_signatures:
            recent_signatures |= exclude_signatures

        philosophers = config.PHILOSOPHERS_AND_SCHOOLS[:]
        contexts = config.MODERN_CONTEXTS[:]
        hooks = config.NARRATIVE_HOOKS[:]
        random.shuffle(philosophers)
        random.shuffle(contexts)
        random.shuffle(hooks)

        selected: List[MatrixCombo] = []
        used_phil_today: set[str] = set()
        used_ctx_today: set[str] = set()
        used_hook_today: set[str] = set()

        # Ưu tiên tối đa tính trực giao: không lặp triết gia, bối cảnh hoặc hook trong cùng 1 ngày
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

        # Bổ sung linh hoạt nếu count vượt số lượng hook/triết gia
        while len(selected) < count:
            combo = MatrixCombo(
                philosopher=random.choice(philosophers),
                modern_context=random.choice(contexts),
                narrative_hook=random.choice(hooks),
            )
            if combo.signature() not in recent_signatures:
                selected.append(combo)
                recent_signatures.add(combo.signature())

        logger.info("[DEDUP T2] Đã chọn %d tổ hợp ma trận trực giao cho hôm nay.", len(selected))
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
        hard_threshold = max(0.88, float(config.SEMANTIC_SIMILARITY_THRESHOLD))

        # Ngưỡng cứng > 0.90 => Chắc chắn trùng lặp ngữ nghĩa gần như nguyên bản
        if max_sim > hard_threshold:
            logger.warning(
                "[DEDUP T3 REJECT] Độ tương đồng=%.3f (> %.2f) với video cũ '%s'.",
                max_sim,
                hard_threshold,
                matched_title,
            )
            return True, max_sim, matched_title, candidate_embedding

        # Vùng giáp ranh (0.78 - 0.90): Dùng LLM kiểm tra chéo sâu xem có trùng ý tưởng thật không
        if max_sim >= 0.78 and closest_entry is not None:
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
        """LLM kiểm tra chéo sâu khi cosine similarity nằm ở vùng ranh giới 0.65–0.75."""
        prompt = (
            "So sánh 2 ý tưởng video Stoicism sau đây và xác định chúng có bị trùng lặp "
            "thông điệp/ý tưởng cốt lõi đối với khán giả hay không.\n\n"
            f"[VIDEO MỚI]\n"
            f"- Tiêu đề: {candidate.get('title')}\n"
            f"- Góc tiếp cận: {candidate.get('angle')}\n"
            f"- Trích dẫn: {candidate.get('core_quote')}\n"
            f"- Tóm tắt: {candidate.get('summary')}\n\n"
            f"[VIDEO ĐÃ SẢN XUẤT]\n"
            f"- Tiêu đề: {closest_entry.get('title')}\n"
            f"- Góc tiếp cận: {closest_entry.get('angle')}\n"
            f"- Trích dẫn: {closest_entry.get('core_quote')}\n"
            f"- Tóm tắt: {closest_entry.get('summary')}\n\n"
            'Trả về JSON: {"is_duplicate": true/false, "reason": "giải thích ngắn gọn 1 câu"}'
        )
        return self.vertex.generate_json(
            prompt=prompt,
            system_instruction="Bạn là biên tập viên chống trùng lặp nội dung cực kỳ khắt khe.",
            temperature=0.1,
            task_name="dedup_llm_crosscheck",
        )
