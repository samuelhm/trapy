"""Voice Activity Detection using WebRTC VAD."""

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class VADDetector:
    """Real-time phrase boundary detection using WebRTC VAD."""

    def __init__(self, sample_rate: int = 16000, silence_duration_ms: int = 400, aggressiveness: int = 2):
        """
        Initialize VAD detector.
        
        Args:
            sample_rate: Audio sample rate (16000 Hz)
            silence_duration_ms: Silence duration before phrase boundary detection
            aggressiveness: VAD aggressiveness 0-3 (higher = fewer false positives)
        """
        import webrtcvad

        self.vad = webrtcvad.Vad(aggressiveness)
        self.sample_rate = sample_rate
        self.silence_duration_ms = silence_duration_ms

        # WebRTC VAD requires 10, 20, or 30ms frames
        self.frame_duration_ms = 20
        self.frame_bytes = (sample_rate * self.frame_duration_ms // 1000) * 2
        self.max_silence_frames = silence_duration_ms // self.frame_duration_ms

        self.buffer = bytearray()
        self.silence_frames = 0
        self.is_speech_active = False

    def process_chunk(self, chunk: bytes) -> Optional[bytes]:
        """Process audio chunk and return phrase when boundary detected."""
        self.buffer.extend(chunk)

        audio_array = np.frombuffer(chunk, dtype=np.int16)
        rms = float(np.sqrt(np.mean(audio_array ** 2))) if len(audio_array) > 0 else 0.0

        has_voice_count = 0
        total_frames = 0

        while len(self.buffer) >= self.frame_bytes:
            frame = bytes(self.buffer[:self.frame_bytes])
            del self.buffer[:self.frame_bytes]
            total_frames += 1

            try:
                has_voice = self.vad.is_speech(frame, self.sample_rate)
            except Exception as e:
                logger.info("VAD error: %s", e)
                has_voice = True

            if has_voice:
                has_voice_count += 1
                self.silence_frames = 0
                if not self.is_speech_active:
                    self.is_speech_active = True
                    logger.info("VAD: Speech started")
            else:
                if self.is_speech_active:
                    self.silence_frames += 1

            # Phrase boundary: silence after speech
            if self.is_speech_active and self.silence_frames >= self.max_silence_frames:
                phrase = bytes(self.buffer) + frame
                self.buffer.clear()
                self.silence_frames = 0
                self.is_speech_active = False
                logger.info("VAD: Phrase boundary detected")

                if len(phrase) > 0:
                    return phrase

        if total_frames > 0:
            logger.info("VAD: Processed %d frames, %d with voice, RMS=%.0f", total_frames, has_voice_count, rms)

        return None

    def flush(self) -> Optional[bytes]:
        """Return remaining buffered audio when input ends."""
        logger.info("VAD flush: %d bytes in buffer, is_speech_active=%s", len(self.buffer), self.is_speech_active)
        if self.buffer and self.is_speech_active:
            phrase = bytes(self.buffer)
            self.buffer.clear()
            self.is_speech_active = False
            return phrase
        return None
