"""OpenAI API client for STT, translation, and TTS."""

import asyncio
import io
import json
import logging
import mimetypes
import time
import urllib.error
import urllib.request
import wave
from typing import Optional

import numpy as np

from config import AppConfig, AudioConfig

logger = logging.getLogger(__name__)


class OpenAIRealtimeClient:
    """STT → Translation → TTS pipeline using OpenAI APIs."""

    def __init__(
        self,
        config: AppConfig,
        audio_config: AudioConfig,
        input_queue: asyncio.Queue[bytes],
        output_queue: asyncio.Queue[bytes],
        instructions: str,
        name: str,
        source_language: str,
        target_language: str,
    ) -> None:
        self.config = config
        self.audio_config = audio_config
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.instructions = instructions
        self.name = name
        self.source_language = source_language
        self.target_language = target_language
        self._running = False

    async def start(self) -> None:
        self._running = True
        logger.info("[%s] Cliente activo (STT→Translate→TTS)", self.name)

    async def stop(self) -> None:
        self._running = False

    def _pcm_to_wav(self, pcm_audio: bytes) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(self.audio_config.channels)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.audio_config.sample_rate)
            wav_file.writeframes(pcm_audio)
        return buffer.getvalue()

    def _post_json(self, url: str, payload: dict, *, timeout: int = 45) -> bytes:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        return self._urlopen_bytes(req, timeout=timeout)

    def _urlopen_bytes(self, req: urllib.request.Request, *, timeout: int) -> bytes:
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} en API: {body}") from exc

    def _post_multipart(
        self,
        url: str,
        *,
        fields: dict[str, str],
        file_field: str,
        file_name: str,
        file_bytes: bytes,
        file_content_type: str,
        timeout: int = 45,
    ) -> bytes:
        import uuid
        
        boundary = f"----Boundary{uuid.uuid4().hex}"
        body = bytearray()

        for key, value in fields.items():
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
            body.extend(value.encode("utf-8"))
            body.extend(b"\r\n")

        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            f'Content-Disposition: form-data; name="{file_field}"; filename="{file_name}"\r\n'.encode("utf-8")
        )
        body.extend(f"Content-Type: {file_content_type}\r\n\r\n".encode("utf-8"))
        body.extend(file_bytes)
        body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode("utf-8"))

        req = urllib.request.Request(
            url,
            data=bytes(body),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        return self._urlopen_bytes(req, timeout=timeout)

    def _transcribe(self, pcm_audio: bytes) -> str:
        """Convert audio to text using Whisper."""
        wav_bytes = self._pcm_to_wav(pcm_audio)
        transcribe_models = ["whisper-1", "gpt-4o-mini-transcribe"]
        last_exc: Optional[Exception] = None
        raw: Optional[bytes] = None

        for model_name in transcribe_models:
            try:
                raw = self._post_multipart(
                    "https://api.openai.com/v1/audio/transcriptions",
                    fields={"model": model_name, "language": self.source_language},
                    file_field="file",
                    file_name="segment.wav",
                    file_bytes=wav_bytes,
                    file_content_type=mimetypes.types_map.get(".wav", "audio/wav"),
                )
                break
            except Exception as exc:
                last_exc = exc

        if raw is None:
            if last_exc is not None:
                raise last_exc
            return ""

        payload = json.loads(raw.decode("utf-8"))
        return str(payload.get("text", "")).strip()

    def _translate_text(self, text: str) -> str:
        """Translate text using GPT."""
        payload = {
            "model": "gpt-3.5-turbo",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"You are a strict translator from {self.source_language} to {self.target_language}. "
                        "Output translation only, with no explanations or extra words."
                    ),
                },
                {"role": "user", "content": text},
            ],
            "temperature": 0,
        }
        raw = self._post_json("https://api.openai.com/v1/chat/completions", payload)
        data = json.loads(raw.decode("utf-8"))
        choices = data.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        return str(message.get("content", "")).strip()

    def _synthesize_speech(self, text: str) -> bytes:
        """Convert text to speech using TTS."""
        payload = {
            "model": "gpt-4o-mini-tts",
            "voice": self.config.voice,
            "input": text,
            "response_format": "pcm",
        }
        return self._post_json("https://api.openai.com/v1/audio/speech", payload)

    async def process_segment(self, pcm_audio: bytes) -> bool:
        """Process audio segment through STT→Translate→TTS pipeline."""
        if not self._running:
            logger.warning("[%s] Segmento ignorado: cliente no está activo", self.name)
            return False

        sample_count = len(pcm_audio) / (2 * self.audio_config.channels)
        audio_ms = (sample_count / self.audio_config.sample_rate) * 1000.0
        
        if audio_ms < 100.0:
            logger.warning("[%s] Segmento demasiado corto: %.1fms", self.name, audio_ms)
            return False

        logger.info("[%s] Procesando segmento de %.1fms", self.name, audio_ms)

        t0 = time.time()

        try:
            transcript = await asyncio.to_thread(self._transcribe, pcm_audio)
            t_stt = time.time() - t0
            if not transcript:
                logger.warning("[%s] STT vacío (sin texto reconocido)", self.name)
                return False

            logger.info("[%s] STT: %s [%.1fs]", self.name, transcript[:160], t_stt)

            translated = await asyncio.to_thread(self._translate_text, transcript)
            t_translate = time.time() - (t0 + t_stt)
            if not translated:
                logger.warning("[%s] Traducción vacía", self.name)
                return False

            logger.info("[%s] Traducción: %s [%.1fs]", self.name, translated[:160], t_translate)

            result_pcm = await asyncio.to_thread(self._synthesize_speech, translated)
            t_tts = time.time() - (t0 + t_stt + t_translate)
        except (urllib.error.URLError, RuntimeError) as exc:
            logger.error("[%s] Error HTTP API: %s", self.name, exc)
            return False
        except Exception as exc:
            logger.error("[%s] Error procesando segmento: %s", self.name, exc)
            return False

        if not result_pcm:
            logger.warning("[%s] TTS devolvió vacío", self.name)
            return False

        result_ms = (len(result_pcm) / (2 * self.audio_config.channels * self.audio_config.sample_rate)) * 1000.0
        logger.info("[%s] TTS: %d bytes (~%.1fms) [%.1fs]", self.name, len(result_pcm), result_ms, t_tts)

        total_time = time.time() - t0
        logger.info(
            "[%s] Pipeline: %.1fs (STT %.1fs + Traducción %.1fs + TTS %.1fs)",
            self.name,
            total_time,
            t_stt,
            t_translate,
            t_tts,
        )

        try:
            await asyncio.wait_for(self.output_queue.put(result_pcm), timeout=5.0)
        except asyncio.TimeoutError:
            logger.error("[%s] Timeout: cola de salida llena", self.name)
            return False

        return True
