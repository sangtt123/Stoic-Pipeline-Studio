"""
src/tts_generator.py — Tạo giọng đọc nam trầm truyền cảm với 2 tầng Auto-Fallback:

- Tầng 1 (Ưu tiên — biểu cảm tự nhiên cao nhất): Vertex AI Gemini Native TTS
  (`gemini-3.8-flash-tts` -> `gemini-3.8-flash-lite-tts`, giọng `Charon` / `Fenrir`).
- Tầng 2 (Dự phòng bền bỉ): Google Cloud Text-to-Speech
  (`Studio` -> `Chirp3-HD` -> `Neural2` -> `WaveNet` -> `Standard`).

Xuất file audio riêng cho từng phân cảnh và đo chính xác duration bằng ffprobe để đồng bộ hình & tiếng 100%.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from google.cloud import texttospeech

import config
from src.gcp_auth import load_gcp_service_account
from src.vertex_client import VertexAIClient

logger = logging.getLogger("tts_generator")


def _is_cloud_tts_api_disabled(exc: Exception) -> bool:
    """Phát hiện lỗi Cloud Text-to-Speech API chưa bật hoặc bị chặn quyền (403 SERVICE_DISABLED)."""
    msg = str(exc).upper()
    return (
        "SERVICE_DISABLED" in msg
        or "API HAS NOT BEEN USED" in msg
        or "IT IS DISABLED" in msg
        or ("403" in msg and "TEXTTOSPEECH" in msg)
    )


def get_audio_duration(audio_path: Path) -> float:
    """Đo chính xác thời lượng file audio (giây) bằng ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout.strip():
        size = audio_path.stat().st_size if audio_path.exists() else -1
        raise RuntimeError(
            f"ffprobe không đọc được file audio '{audio_path.name}' (size={size}B, exit={result.returncode}): "
            f"{result.stderr.strip()}"
        )
    return float(result.stdout.strip())


class TTSGenerator:
    """Bộ tạo giọng đọc 2 tầng: Google Cloud TTS (Chirp3-HD/Studio/Neural2) + Vertex AI Gemini TTS."""

    def __init__(
        self,
        language: Optional[str] = None,
        vertex: Optional[VertexAIClient] = None,
    ) -> None:
        self.language = language or config.LANGUAGE
        self.vertex = vertex
        self._cloud_tts_client: Optional[texttospeech.TextToSpeechClient] = None
        self._cloud_tts_disabled: bool = False
        self.voice_chain = config.TTS_VOICE_CHAINS.get(
            self.language, config.TTS_VOICE_CHAINS["en-US"]
        )
        self._active_voice_idx = 0

    def _get_cloud_tts_client(self) -> texttospeech.TextToSpeechClient:
        if self._cloud_tts_client is None:
            auth = load_gcp_service_account()
            self._cloud_tts_client = texttospeech.TextToSpeechClient(credentials=auth.credentials)
        return self._cloud_tts_client

    def _synthesize_with_cloud_tts(self, clean_text: str, mp3_path: Path) -> Tuple[Path, float]:
        """Tầng dự phòng: Google Cloud Text-to-Speech (Studio / Chirp3-HD / Neural2)."""
        if self._cloud_tts_disabled:
            raise RuntimeError("Cloud Text-to-Speech API đang tắt trên GCP Project (đã bỏ qua nhanh).")

        client = self._get_cloud_tts_client()
        last_exc: Optional[Exception] = None

        for idx in range(self._active_voice_idx, len(self.voice_chain)):
            voice_opt = self.voice_chain[idx]
            try:
                synthesis_input = texttospeech.SynthesisInput(text=clean_text)
                voice_params = texttospeech.VoiceSelectionParams(
                    language_code=voice_opt.language_code,
                    name=voice_opt.voice_name,
                    ssml_gender=texttospeech.SsmlVoiceGender.MALE,
                )

                # Chirp3-HD và Studio không hỗ trợ tùy chỉnh pitch thủ công => chỉ truyền speaking_rate
                audio_kwargs = {
                    "audio_encoding": texttospeech.AudioEncoding.MP3,
                    "speaking_rate": voice_opt.speaking_rate,
                }
                if "Chirp" not in voice_opt.voice_name and "Studio" not in voice_opt.voice_name:
                    audio_kwargs["pitch"] = voice_opt.pitch

                audio_config = texttospeech.AudioConfig(**audio_kwargs)
                response = client.synthesize_speech(
                    input=synthesis_input,
                    voice=voice_params,
                    audio_config=audio_config,
                )

                mp3_path.write_bytes(response.audio_content)
                duration = get_audio_duration(mp3_path)
                self._active_voice_idx = idx
                logger.info(
                    "[CLOUD TTS OK] Voice='%s' | File='%s' | Duration=%.2fs",
                    voice_opt.voice_name,
                    mp3_path.name,
                    duration,
                )
                return mp3_path, duration

            except Exception as exc:
                last_exc = exc
                if _is_cloud_tts_api_disabled(exc):
                    self._cloud_tts_disabled = True
                    logger.warning(
                        "[CLOUD TTS DISABLED] Cloud Text-to-Speech API chưa được bật trên GCP Project (%s). "
                        "Chuyển hẳn sang Vertex AI Gemini TTS cho toàn bộ các phân cảnh còn lại!",
                        exc,
                    )
                    break
                logger.warning(
                    "[CLOUD TTS FALLBACK] Giọng '%s' lỗi (%s). Chuyển giọng dự phòng kế tiếp...",
                    voice_opt.voice_name,
                    exc,
                )

        raise RuntimeError(
            f"Tất cả giọng Google Cloud TTS cho '{self.language}' đều thất bại: {last_exc}"
        ) from last_exc

    def synthesize_scene(self, text: str, output_stem_path: Path) -> Tuple[Path, float]:
        """
        Tạo file audio cho 1 phân cảnh và trả về (actual_audio_path, exact_duration_seconds).
        - Mặc định (`cloud_tts` — chuẩn Google Cloud Console): ưu tiên Google Cloud Text-to-Speech
          (Chirp 3 HD -> Studio -> Neural2 -> WaveNet), tự động dự phòng sang Vertex AI Gemini TTS nếu lỗi.
        - Nếu chọn `gemini_tts`: ưu tiên Vertex AI Gemini TTS (.wav), tự động dự phòng sang Cloud TTS (.mp3).
        """
        output_stem_path.parent.mkdir(parents=True, exist_ok=True)
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("Lời thoại phân cảnh không được để trống.")

        wav_path = output_stem_path.with_suffix(".wav")
        mp3_path = output_stem_path.with_suffix(".mp3")

        if (
            (config.TTS_PRIMARY_PROVIDER == "gemini_tts" or self._cloud_tts_disabled)
            and self.vertex is not None
        ):
            try:
                self.vertex.synthesize_speech_wav(
                    text=clean_text,
                    output_path=wav_path,
                    voice_name=config.TTS_VOICE_PERSONA,
                    voice_style=config.TTS_VOICE_STYLE,
                    task_name=f"tts_{output_stem_path.stem}",
                )
                duration = get_audio_duration(wav_path)
                logger.info(
                    "[TTS DURATION] File='%s' | Duration=%.2fs (Vertex AI Gemini TTS)",
                    wav_path.name,
                    duration,
                )
                return wav_path, duration
            except Exception as exc:
                if self._cloud_tts_disabled:
                    raise
                logger.warning(
                    "[TTS PROVIDER FALLBACK] Vertex AI Gemini TTS lỗi (%s). "
                    "Tự động chuyển sang Google Cloud Text-to-Speech...",
                    exc,
                )
            return self._synthesize_with_cloud_tts(clean_text, mp3_path)

        # Mặc định cho Google Cloud Console: Google Cloud TTS -> dự phòng Vertex AI Gemini TTS
        try:
            return self._synthesize_with_cloud_tts(clean_text, mp3_path)
        except Exception as cloud_exc:
            if self.vertex is None:
                raise
            logger.warning(
                "[TTS PROVIDER FALLBACK] Google Cloud TTS lỗi (%s). "
                "Tự động chuyển sang Vertex AI Gemini TTS...",
                cloud_exc,
            )
            self.vertex.synthesize_speech_wav(
                text=clean_text,
                output_path=wav_path,
                voice_name=config.TTS_VOICE_PERSONA,
                voice_style=config.TTS_VOICE_STYLE,
                task_name=f"tts_fallback_{output_stem_path.stem}",
            )
            duration = get_audio_duration(wav_path)
            logger.info(
                "[TTS DURATION] File='%s' | Duration=%.2fs (Vertex AI Gemini TTS Fallback)",
                wav_path.name,
                duration,
            )
            return wav_path, duration
