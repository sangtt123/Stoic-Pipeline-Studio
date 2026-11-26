"""
src/vertex_client.py — Auto-Fallback Wrapper cho Google Cloud Vertex AI (google-genai SDK).

Cơ chế xử lý lỗi 2 lớp:
1. Lỗi nhất thời (429 RPM/TPM, 503 Service Unavailable): Exponential Backoff + Jitter (10s -> 20s -> 40s).
2. Hết quota ngày / Model quá tải kéo dài / Model không khả dụng (404/400): Tự động hạ cấp
   xuống model tiếp theo trong danh sách ưu tiên (config.py) và ghi log rõ ràng.
"""

from __future__ import annotations

import base64
import json
import logging
import random
import re
import subprocess
import time
import wave
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypeVar

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

import config
from src.gcp_auth import load_gcp_service_account

logger = logging.getLogger("vertex_client")
T = TypeVar("T")


def _extract_status_code(exc: Exception) -> Optional[int]:
    """Trích xuất HTTP status code từ exception của google-genai."""
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    msg = str(exc)
    for candidate in (429, 503, 500, 404, 403, 400):
        if str(candidate) in msg:
            return candidate
    return None


def _is_transient_rate_error(exc: Exception) -> bool:
    """Kiểm tra lỗi nhất thời (429 Resource Exhausted / 503 Unavailable / Timeout)."""
    code = _extract_status_code(exc)
    msg = str(exc).upper()
    if code in (429, 503, 500):
        return True
    keywords = (
        "RESOURCE_EXHAUSTED",
        "TOO MANY REQUESTS",
        "SERVICE_UNAVAILABLE",
        "OVERLOADED",
        "UNAVAILABLE",
        "DEADLINE_EXCEEDED",
        "QUOTA",
    )
    return any(k in msg for k in keywords)


def _is_daily_quota_or_unavailable(exc: Exception) -> bool:
    """Kiểm tra lỗi nên chuyển ngay sang model fallback (không cần đợi backoff hết)."""
    code = _extract_status_code(exc)
    msg = str(exc).upper()
    if code == 404:
        return True
    immediate_fallback_keywords = (
        "NOT_FOUND",
        "MODEL_NOT_FOUND",
        "NOT SUPPORTED",
        "DAILY",
        "PER_DAY",
        "PERMISSION_DENIED",
        "UNSUPPORTED",
    )
    return any(k in msg for k in immediate_fallback_keywords)


def _strip_json_fences(raw_text: str) -> str:
    """Loại bỏ markdown code fence ```json ... ``` nếu model trả về kèm định dạng."""
    cleaned = raw_text.strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
    if fence_match:
        return fence_match.group(1).strip()
    return cleaned


class VertexAIClient:
    """
    Client 100% Google Cloud Vertex AI kết nối trực tiếp bằng file Service Account JSON
    (`service-account-key.json`, `GOOGLE_APPLICATION_CREDENTIALS` hoặc `GCP_SA_KEY`).
    Tự động đọc `project_id` ngay trong file JSON.
    """

    def __init__(self) -> None:
        auth = load_gcp_service_account()
        self.project_id = auth.project_id
        self.client_email = auth.client_email

        # LLM đa vùng:
        # - Model preview (gemini-3*) chạy trên location="global"
        # - Model GA (gemini-2.5*) chạy trên regional endpoint (mặc định us-central1)
        self.llm_client = genai.Client(
            vertexai=True,
            project=auth.project_id,
            location=config.VERTEX_LLM_LOCATION,
            credentials=auth.credentials,
        )
        regional_loc = config.VERTEX_IMAGEN_LOCATION or "us-central1"
        self.llm_regional_client = (
            self.llm_client
            if regional_loc == config.VERTEX_LLM_LOCATION
            else genai.Client(
                vertexai=True,
                project=auth.project_id,
                location=regional_loc,
                credentials=auth.credentials,
            )
        )
        self._regional_location = regional_loc
        self.imagen_client = genai.Client(
            vertexai=True,
            project=auth.project_id,
            location=config.VERTEX_IMAGEN_LOCATION,
            credentials=auth.credentials,
        )
        self.embedding_client = genai.Client(
            vertexai=True,
            project=auth.project_id,
            location=config.VERTEX_EMBEDDING_LOCATION,
            credentials=auth.credentials,
        )

        # Bộ nhớ tạm các model trả 404 NOT_FOUND để không gọi lại lãng phí ở các tác vụ sau
        self._unavailable_models: set[str] = set()
        # Thống kê số lần hạ cấp model để theo dõi vận hành
        self.fallback_events: List[Dict[str, Any]] = []

    def _generate_content_smart(
        self,
        model_name: str,
        contents: Any,
        gen_config: types.GenerateContentConfig,
    ) -> Any:
        """
        Tự động định tuyến đúng endpoint Vertex AI theo họ model:
        - gemini-2.5-* / gemini-2.0-*: ưu tiên regional (us-central1), 404 mới thử global
        - gemini-3*: ưu tiên global, 404 mới thử regional (us-central1)
        """
        prefer_regional = model_name.startswith(("gemini-2.5", "gemini-2.0"))
        clients = (
            [self.llm_regional_client, self.llm_client]
            if prefer_regional
            else [self.llm_client, self.llm_regional_client]
        )
        # Loại trùng nếu 2 location giống nhau
        unique_clients: List[genai.Client] = []
        for c in clients:
            if c not in unique_clients:
                unique_clients.append(c)

        last_exc: Optional[Exception] = None
        for idx, client in enumerate(unique_clients):
            try:
                return client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=gen_config,
                )
            except Exception as exc:
                last_exc = exc
                if idx + 1 < len(unique_clients) and _extract_status_code(exc) == 404:
                    continue
                raise
        assert last_exc is not None
        raise last_exc

    def _execute_with_fallback(
        self,
        task_name: str,
        model_chain: List[str],
        caller: Callable[[str], T],
    ) -> T:
        """
        Thực thi API call trên danh sách model theo thứ tự ưu tiên.
        - Lỗi nhất thời (429/503): Backoff 10s -> 20s -> 40s + Jitter trên model hiện tại.
        - Nếu vẫn lỗi hoặc model không khả dụng: Ghi log cảnh báo và hạ cấp sang model kế tiếp.
        """
        last_error: Optional[Exception] = None

        for idx, model_name in enumerate(model_chain):
            if model_name in self._unavailable_models:
                continue

            max_attempts = len(config.BACKOFF_DELAYS_SECONDS) + 1

            for attempt in range(max_attempts):
                try:
                    return caller(model_name)
                except Exception as exc:
                    last_error = exc
                    status_code = _extract_status_code(exc)

                    # Nếu model không tồn tại / hết quota ngày => chuyển model ngay lập tức
                    if _is_daily_quota_or_unavailable(exc):
                        if status_code == 404:
                            self._unavailable_models.add(model_name)
                        logger.warning(
                            "[AUTO-FALLBACK] Task='%s' | Model='%s' không khả dụng hoặc hết quota ngày "
                            "(HTTP %s): %s",
                            task_name,
                            model_name,
                            status_code,
                            exc,
                        )
                        break

                    # Lỗi nhất thời (429 RPM/TPM, 503 Overload) => Exponential Backoff + Jitter
                    if _is_transient_rate_error(exc) and attempt < len(config.BACKOFF_DELAYS_SECONDS):
                        base_delay = config.BACKOFF_DELAYS_SECONDS[attempt]
                        jitter = random.uniform(0.3, config.BACKOFF_JITTER_MAX_SECONDS)
                        sleep_sec = round(base_delay + jitter, 2)
                        logger.warning(
                            "[RETRY BACKOFF] Task='%s' | Model='%s' gặp lỗi HTTP %s "
                            "(lần %d/%d). Chờ %.2fs trước khi thử lại...",
                            task_name,
                            model_name,
                            status_code,
                            attempt + 1,
                            max_attempts,
                            sleep_sec,
                        )
                        time.sleep(sleep_sec)
                        continue

                    # Các lỗi khác hoặc đã hết số lần backoff trên model hiện tại
                    logger.error(
                        "[MODEL EXHAUSTED] Task='%s' | Model='%s' thất bại sau %d lần thử (HTTP %s): %s",
                        task_name,
                        model_name,
                        attempt + 1,
                        status_code,
                        exc,
                    )
                    break

            # Chuyển sang model hạ cấp tiếp theo nếu còn trong chuỗi
            if idx + 1 < len(model_chain):
                next_model = model_chain[idx + 1]
                event = {
                    "task": task_name,
                    "from_model": model_name,
                    "to_model": next_model,
                    "reason": str(last_error)[:240],
                }
                self.fallback_events.append(event)
                logger.warning(
                    "[MODEL DOWNGRADE] Task='%s' | Tự động hạ cấp: '%s' ---> '%s'",
                    task_name,
                    model_name,
                    next_model,
                )

        raise RuntimeError(
            f"Tất cả model trong chuỗi {model_chain} đều thất bại cho task '{task_name}'. "
            f"Lỗi cuối cùng: {last_error}"
        ) from last_error

    @staticmethod
    def _build_thinking_config(model_name: str) -> Optional[Any]:
        """
        Giảm độ trễ suy luận (thinking_level=LOW) cho Gemini 4 / Gemini 3 để viết kịch bản
        nhanh hơn 4–6 lần (~30s thay vì 3.5 phút/video) mà vẫn giữ chất lượng JSON sắc nét.
        """
        if not model_name.startswith(("gemini-4", "gemini-3")):
            return None
        try:
            thinking_level_cls = getattr(types, "ThinkingLevel", None)
            if thinking_level_cls is not None and hasattr(thinking_level_cls, "LOW"):
                return types.ThinkingConfig(thinking_level=thinking_level_cls.LOW)
            return types.ThinkingConfig(thinking_level="LOW")  # type: ignore[arg-type]
        except Exception:
            try:
                return types.ThinkingConfig(thinking_budget=512)
            except Exception:
                return None

    def generate_json(
        self,
        prompt: str,
        system_instruction: str,
        temperature: float = 0.75,
        task_name: str = "llm_json",
    ) -> Dict[str, Any]:
        """Gọi LLM trả về JSON thuần, tự động fallback qua chuỗi LLM_FALLBACK_MODELS."""

        def _call(model_name: str) -> Dict[str, Any]:
            thinking_cfg = self._build_thinking_config(model_name)
            gen_kwargs: Dict[str, Any] = {
                "system_instruction": system_instruction,
                "temperature": temperature,
                "response_mime_type": "application/json",
            }
            if thinking_cfg is not None:
                gen_kwargs["thinking_config"] = thinking_cfg

            try:
                response = self._generate_content_smart(
                    model_name=model_name,
                    contents=prompt,
                    gen_config=types.GenerateContentConfig(**gen_kwargs),
                )
            except Exception as exc:
                # Nếu model cụ thể không hỗ trợ thinking_config (HTTP 400), tự gọi lại không kèm thinking_config
                if thinking_cfg is not None and _extract_status_code(exc) == 400:
                    gen_kwargs.pop("thinking_config", None)
                    response = self._generate_content_smart(
                        model_name=model_name,
                        contents=prompt,
                        gen_config=types.GenerateContentConfig(**gen_kwargs),
                    )
                else:
                    raise

            text = response.text or ""
            parsed = json.loads(_strip_json_fences(text))
            if isinstance(parsed, list):
                if len(parsed) == 1 and isinstance(parsed[0], dict):
                    parsed = parsed[0]
                elif len(parsed) > 1 and isinstance(parsed[0], dict) and (
                    "narration" in parsed[0] or "scene_id" in parsed[0]
                ):
                    parsed = {"scenes": parsed}
                elif len(parsed) > 0 and isinstance(parsed[0], dict):
                    parsed = parsed[0]
                else:
                    raise ValueError(f"Model '{model_name}' trả về JSON list rỗng/không hợp lệ.")
            if not isinstance(parsed, dict):
                raise ValueError(f"Model '{model_name}' trả về kiểu JSON không phải object.")
            logger.info("[LLM OK] Task='%s' | Model='%s'", task_name, model_name)
            return parsed

        return self._execute_with_fallback(
            task_name=task_name,
            model_chain=config.LLM_FALLBACK_MODELS,
            caller=_call,
        )

    def review_contact_sheet(
        self,
        contact_sheet_path: Path,
        prompt: str,
        system_instruction: str,
        task_name: str = "vision_review",
    ) -> Dict[str, Any]:
        """Gửi 1 ảnh lưới Contact Sheet JPEG cho Gemini Vision để thẩm định video."""
        image_bytes = contact_sheet_path.read_bytes()

        def _call(model_name: str) -> Dict[str, Any]:
            response = self._generate_content_smart(
                model_name=model_name,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                    prompt,
                ],
                gen_config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.2,
                    response_mime_type="application/json",
                ),
            )
            text = response.text or ""
            parsed = json.loads(_strip_json_fences(text))
            if isinstance(parsed, list):
                if len(parsed) > 0 and isinstance(parsed[0], dict):
                    parsed = parsed[0]
                else:
                    raise ValueError(f"Vision model '{model_name}' trả về JSON list không hợp lệ.")
            if not isinstance(parsed, dict):
                raise ValueError(f"Vision model '{model_name}' trả về kiểu JSON không phải object.")
            logger.info("[VISION OK] Task='%s' | Model='%s'", task_name, model_name)
            return parsed

        return self._execute_with_fallback(
            task_name=task_name,
            model_chain=config.LLM_FALLBACK_MODELS,
            caller=_call,
        )

    @staticmethod
    def _sanitize_safety_prompt(raw_prompt: str) -> str:
        """
        Làm mềm các từ dễ kích hoạt bộ lọc an toàn (safety filter) của Vertex AI Imagen
        khi viết về chủ đề Khắc kỷ (công kích, phản bội, cái chết, giận dữ...) sang ẩn dụ hình ảnh sạch.
        """
        replacements = [
            (r"\b(kill|killing|murder|suicide|self-harm|blood|gore|corpse|dead body)\b", "fading storm shadow"),
            (r"\b(weapon|knife|sword|gun|shoot|stab|wound|bleeding)\b", "heavy dark obstacle"),
            (r"\b(attack|attacking|betrayal|betrayed|violent|violence|fight|fighting)\b", "harsh storm wind"),
            (r"\b(death|dying|skull|grave)\b", "hourglass running out of sand"),
            (r"\b(anger|rage|furious|screaming)\b", "tangled storm cloud overhead"),
            (r"\b(nudity|naked|nude)\b", "classic draped figure"),
        ]
        safe_text = raw_prompt
        for pattern, repl in replacements:
            safe_text = re.sub(pattern, repl, safe_text, flags=re.IGNORECASE)
        return safe_text

    @staticmethod
    def _enhance_imagen_prompt(raw_prompt: str) -> str:
        """
        Nâng cấp prompt cho Vertex AI Imagen theo chuẩn Editorial Flat-Vector Explainer:
        hết lỗi chữ rác (gibberish text), hết méo tay/mặt, đồng nhất phong cách nhân vật & màu nền.
        """
        clean = re.sub(r"[\r\n]+", " ", raw_prompt).strip()
        # Loại bỏ các cụm trích dẫn trong ngoặc kép (dễ khiến Imagen cố vẽ chữ lỗi lên tranh)
        clean = re.sub(r'["“”][^"“”]{2,48}["“”]', "", clean)
        bg = getattr(config, "WHITEBOARD_BG_COLOR", "#EEF2F7")
        ink = getattr(config, "WHITEBOARD_INK_COLOR", "#0F172A")
        accent = getattr(config, "WHITEBOARD_ACCENT_COLOR", "#2563EB")
        guardrail = (
            f"Editorial flat 2D vector illustration in the style of a clean modern YouTube explainer channel, "
            f"solid matte uniform {bg} background, uniform bold crisp {ink} ink contours, flat minimal shading, "
            f"vivid {accent} geometric accent highlights, ONE clear centered iconic visual metaphor with simple "
            "anatomically clean stylized silhouette (keep hands simple or tucked, avoid close-up fingers), "
            "generous clean negative space and open bottom margin for subtitles, "
            "strictly ZERO text, ZERO letters, ZERO numbers, ZERO speech bubble words, ZERO watermarks, ZERO logos, "
            "NOT photorealistic, NOT 3D render, NOT cluttered collage."
        )
        if "strictly zero text" in clean.lower():
            return clean
        return f"{clean}. {guardrail}"

    @staticmethod
    def _check_image_integrity(image_path: Path) -> None:
        """Kiểm định file PNG nguyên vẹn, đủ độ phân giải và không bị trắng trơn/đen xì bằng Pillow."""
        try:
            from PIL import Image, ImageStat

            with Image.open(image_path) as check_img:
                w, h = check_img.size
                check_img.verify()
            if w < 512 or h < 512:
                raise RuntimeError(f"Ảnh Imagen có độ phân giải quá thấp: {w}x{h}")

            with Image.open(image_path) as rgb_img:
                stat = ImageStat.Stat(rgb_img.convert("L"))
                stddev = stat.stddev[0] if stat.stddev else 0.0
                if stddev < 6.0:
                    raise RuntimeError(
                        f"Ảnh Imagen gần như đơn sắc/trống rỗng (stddev={stddev:.2f} < 6.0)."
                    )
        except ImportError:
            pass

    def generate_image(
        self,
        prompt: str,
        output_path: Path,
        aspect_ratio: Optional[str] = None,
        seed: Optional[int] = None,
        task_name: str = "imagen_2d",
    ) -> Path:
        """
        Tạo ảnh 2D tĩnh bằng Vertex AI Imagen (tiết kiệm chi phí, KHÔNG dùng Veo).
        Tự động nâng cấp prompt chống chữ rác/méo hình, tự viết lại prompt an toàn nếu bị safety filter
        chặn, và kiểm định file PNG đầu ra (độ phân giải + độ tương phản chống ảnh trống) bằng Pillow.
        """
        ratio = aspect_ratio or config.ASPECT_RATIO
        chosen_seed = seed if seed is not None else random.randint(1, 2_147_483_646)
        enhanced_prompt = self._enhance_imagen_prompt(prompt)
        negative_guard = (
            "text, letters, typography, words, numbers, caption, label, watermark, signature, logo, "
            "blurry, low quality, photorealistic, 3d render, deformed hands, extra fingers, extra limbs, "
            "distorted face, ugly anatomy, cluttered busy background, dark muddy shadows, split panel grid"
        )

        def _invoke_imagen(model_name: str, active_prompt: str, active_seed: int):
            base_kwargs: Dict[str, Any] = {
                "number_of_images": 1,
                "aspect_ratio": ratio,
                "output_mime_type": "image/png",
                "seed": active_seed,
                "add_watermark": False,
                "safety_filter_level": "BLOCK_MEDIUM_AND_ABOVE",
                "person_generation": "ALLOW_ADULT",
            }
            try:
                gen_config = types.GenerateImagesConfig(
                    **base_kwargs,
                    negative_prompt=negative_guard,
                )
                return self.imagen_client.models.generate_images(
                    model=model_name,
                    prompt=active_prompt,
                    config=gen_config,
                )
            except Exception as cfg_err:
                if "negative_prompt" in str(cfg_err).lower() or "extra_forbidden" in str(cfg_err).lower():
                    gen_config = types.GenerateImagesConfig(**base_kwargs)
                    return self.imagen_client.models.generate_images(
                        model=model_name,
                        prompt=active_prompt,
                        config=gen_config,
                    )
                raise

        def _call(model_name: str) -> Path:
            result = _invoke_imagen(model_name, enhanced_prompt, chosen_seed)
            if not result.generated_images:
                # Lần thử 2 tự động làm mềm từ khóa nhạy cảm nếu bộ lọc an toàn chặn ảnh
                softened = self._enhance_imagen_prompt(self._sanitize_safety_prompt(prompt))
                logger.warning(
                    "[IMAGEN SAFETY RETRY] Model='%s' trả ảnh rỗng, thử lại với prompt ẩn dụ sạch...",
                    model_name,
                )
                result = _invoke_imagen(model_name, softened, random.randint(1, 2_147_483_646))

            if not result.generated_images:
                raise RuntimeError(f"Imagen ({model_name}) không trả về ảnh nào cho prompt.")

            img_bytes = result.generated_images[0].image.image_bytes
            if not img_bytes or len(img_bytes) < 2048:
                raise RuntimeError(f"Imagen ({model_name}) trả về dữ liệu ảnh rỗng hoặc quá nhỏ.")

            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(img_bytes)

            try:
                self._check_image_integrity(output_path)
            except RuntimeError as qa_err:
                # Nếu ảnh bị trắng trơn / lỗi tương phản -> thử sinh lại 1 lần bằng bố cục ẩn dụ tương phản cao
                logger.warning(
                    "[IMAGEN INTEGRITY RETRY] %s -> thử sinh lại với bố cục rõ nét hơn...",
                    qa_err,
                )
                retry_prompt = self._enhance_imagen_prompt(
                    f"Bold high-contrast minimalist icon illustration representing: {self._sanitize_safety_prompt(prompt)}"
                )
                retry_res = _invoke_imagen(model_name, retry_prompt, random.randint(1, 2_147_483_646))
                if not retry_res.generated_images or not retry_res.generated_images[0].image.image_bytes:
                    raise qa_err
                output_path.write_bytes(retry_res.generated_images[0].image.image_bytes)
                self._check_image_integrity(output_path)

            logger.info(
                "[IMAGEN OK] Model='%s' | Seed=%d | Ratio=%s | Saved=%s",
                model_name,
                chosen_seed,
                ratio,
                output_path.name,
            )
            return output_path

        return self._execute_with_fallback(
            task_name=task_name,
            model_chain=config.IMAGEN_FALLBACK_MODELS,
            caller=_call,
        )

    @staticmethod
    def _write_audio_as_valid_wav(raw_data: bytes, mime_type: str, output_path: Path) -> None:
        """
        Đảm bảo dữ liệu âm thanh trả về từ Gemini TTS (thường là raw PCM 16-bit 24kHz không có header,
        hoặc đôi khi là WAV/MP3/OGG) luôn được lưu thành file RIFF/WAV chuẩn mà FFprobe & FFmpeg đọc 100%.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        mime_lower = (mime_type or "").lower()

        # Trường hợp 1: Đã là file RIFF/WAV chuẩn
        if len(raw_data) >= 12 and raw_data[:4] == b"RIFF" and raw_data[8:12] == b"WAVE":
            output_path.write_bytes(raw_data)
            return

        # Trường hợp 2: Là container âm thanh nén (MP3, OGG, FLAC, MP4/M4A...) -> transcode sang WAV chuẩn
        is_encoded_container = (
            any(tok in mime_lower for tok in ("mpeg", "mp3", "ogg", "opus", "flac", "mp4", "m4a", "aac"))
            or raw_data[:3] == b"ID3"
            or raw_data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")
            or raw_data[:4] in (b"OggS", b"fLaC")
        )
        if is_encoded_container:
            tmp_encoded = output_path.with_suffix(".tmp_tts_raw")
            try:
                tmp_encoded.write_bytes(raw_data)
                subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-i",
                        str(tmp_encoded),
                        "-ar",
                        "24000",
                        "-ac",
                        "1",
                        "-c:a",
                        "pcm_s16le",
                        str(output_path),
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                return
            finally:
                tmp_encoded.unlink(missing_ok=True)

        # Trường hợp 3 (phổ biến nhất ở Gemini TTS): Raw PCM 16-bit signed little-endian (audio/L16;codec=pcm;rate=24000)
        rate_match = re.search(r"rate=(\d+)", mime_lower)
        sample_rate = int(rate_match.group(1)) if rate_match else 24000
        chan_match = re.search(r"channels?=(\d+)", mime_lower)
        channels = int(chan_match.group(1)) if chan_match else 1

        # Đảm bảo độ dài byte chẵn cho PCM 16-bit (2 bytes/sample)
        frame_bytes = 2 * channels
        usable_len = len(raw_data) - (len(raw_data) % frame_bytes)
        if usable_len <= 0:
            raise RuntimeError(
                f"Dữ liệu PCM từ Gemini TTS quá ngắn ({len(raw_data)} bytes, mime='{mime_type}')."
            )
        pcm_payload = raw_data[:usable_len]

        with wave.open(str(output_path), "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(2)  # 16-bit PCM
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_payload)

    def synthesize_speech_wav(
        self,
        text: str,
        output_path: Path,
        voice_name: Optional[str] = None,
        voice_style: Optional[str] = None,
        task_name: str = "gemini_tts",
    ) -> Path:
        """
        Tạo giọng đọc WAV 24kHz tự nhiên bằng chuỗi Gemini TTS (`gemini-2.5-flash-tts` ->
        `gemini-3.8-flash-tts` -> `gemini-3.8-flash-lite-tts`), tự động định tuyến endpoint
        (us-central1 / global) và tự động đóng gói chuẩn RIFF/WAV header cho dữ liệu raw PCM.
        """
        selected_voice = voice_name or config.TTS_VOICE_PERSONA
        selected_style = voice_style or config.TTS_VOICE_STYLE
        styled_prompt = (
            f"Read the following narration aloud in a {selected_style}. "
            f"Do not add extra commentary or intro:\n\n{text.strip()}"
        )

        def _call(model_name: str) -> Path:
            gen_config = types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=selected_voice
                        )
                    )
                ),
            )
            response = self._generate_content_smart(
                model_name=model_name,
                contents=styled_prompt,
                gen_config=gen_config,
            )
            candidates = response.candidates or []
            audio_chunks: List[bytes] = []
            detected_mime: str = ""
            for cand in candidates:
                if cand.content and cand.content.parts:
                    for part in cand.content.parts:
                        if part.inline_data and part.inline_data.data:
                            raw_part = part.inline_data.data
                            if isinstance(raw_part, str):
                                raw_part = base64.b64decode(raw_part)
                            elif isinstance(raw_part, bytearray):
                                raw_part = bytes(raw_part)
                            if raw_part:
                                audio_chunks.append(raw_part)
                                if not detected_mime and part.inline_data.mime_type:
                                    detected_mime = part.inline_data.mime_type

            audio_bytes = b"".join(audio_chunks)
            if not audio_bytes or len(audio_bytes) < 64:
                raise RuntimeError(f"Gemini TTS ({model_name}) không trả về dữ liệu âm thanh hợp lệ.")

            self._write_audio_as_valid_wav(audio_bytes, detected_mime, output_path)

            # Kiểm định nhanh file WAV vừa ghi có thể đọc được số khung hình > 0
            try:
                with wave.open(str(output_path), "rb") as check_wf:
                    if check_wf.getnframes() <= 0 or check_wf.getframerate() <= 0:
                        raise RuntimeError("File WAV có 0 khung hình âm thanh.")
            except wave.Error as wav_err:
                raise RuntimeError(
                    f"File WAV sau khi ghi từ Gemini TTS không hợp lệ ({wav_err}, mime='{detected_mime}')."
                ) from wav_err

            logger.info(
                "[GEMINI TTS OK] Model='%s' | Voice='%s' | Mime='%s' | Size=%dB | Saved=%s",
                model_name,
                selected_voice,
                detected_mime or "raw_pcm",
                output_path.stat().st_size,
                output_path.name,
            )
            return output_path

        return self._execute_with_fallback(
            task_name=task_name,
            model_chain=config.TTS_FALLBACK_MODELS,
            caller=_call,
        )

    def embed_text(self, text: str, task_name: str = "text_embedding") -> List[float]:
        """Tạo vector embedding bằng chuỗi EMBEDDING_FALLBACK_MODELS để so sánh độ tương đồng ngữ nghĩa."""

        def _call(model_name: str) -> List[float]:
            response = self.embedding_client.models.embed_content(
                model=model_name,
                contents=text,
            )
            if not response.embeddings or not response.embeddings[0].values:
                raise RuntimeError(f"Embedding ({model_name}) trả về vector rỗng.")
            return list(response.embeddings[0].values)

        return self._execute_with_fallback(
            task_name=task_name,
            model_chain=config.EMBEDDING_FALLBACK_MODELS,
            caller=_call,
        )
