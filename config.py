"""Configuration management for bidirectional translator."""

import os
import logging
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


@dataclass
class AudioConfig:
    """Audio stream configuration parameters."""
    sample_rate: int = 16000
    channels: int = 1
    dtype: str = "int16"
    chunk_ms: int = 10

    @property
    def frames_per_chunk(self) -> int:
        return int(self.sample_rate * self.chunk_ms / 1000)


@dataclass
class AppConfig:
    """Application configuration from environment variables."""
    api_key: str
    model: str = "gpt-realtime"
    ws_url_base: str = "wss://api.openai.com/v1/realtime"
    voice: str = "ash"
    translation_mode: str = "keyboard_hold"
    outgoing_ptt_keys: str = "f8"
    incoming_ptt_keys: str = "f9"
    vad_threshold: float = 0.32
    vad_prefix_padding_ms: int = 260
    vad_silence_duration_ms: int = 140

    # Virtual device names expected in PulseAudio/PipeWire
    mic_virtual_sink: str = "Mic_Virtual"
    mic_virtual_source: str = "Mic_Virtual_Input"
    altavoz_virtual_sink: str = "Altavoz_Virtual"

    # Physical devices. None means OS default.
    physical_mic_input_device: Optional[int] = None
    physical_speaker_output_device: Optional[int] = None


def load_config() -> AppConfig:
    """Load configuration from .env file and environment variables."""
    load_dotenv()

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Falta OPENAI_API_KEY en .env")

    mic_input_env = os.getenv("PHYSICAL_MIC_INPUT_DEVICE")
    speaker_output_env = os.getenv("PHYSICAL_SPEAKER_OUTPUT_DEVICE")
    translation_mode = os.getenv("TRANSLATION_MODE", "keyboard_hold").strip().lower()
    
    if translation_mode not in {"turn", "simultaneous", "mouse_hold", "keyboard_hold"}:
        logger.warning(
            "TRANSLATION_MODE='%s' inválido. Se usará 'keyboard_hold'.",
            translation_mode,
        )
        translation_mode = "keyboard_hold"

    return AppConfig(
        api_key=api_key,
        model=os.getenv("REALTIME_MODEL", "gpt-realtime"),
        ws_url_base=os.getenv("REALTIME_WS_URL", "wss://api.openai.com/v1/realtime"),
        voice="ash",
        translation_mode=translation_mode,
        outgoing_ptt_keys=os.getenv("OUTGOING_PTT_KEYS", "f8"),
        incoming_ptt_keys=os.getenv("INCOMING_PTT_KEYS", "f9"),
        vad_threshold=0.32,
        vad_prefix_padding_ms=260,
        vad_silence_duration_ms=140,
        mic_virtual_sink=os.getenv("MIC_VIRTUAL_SINK", "Mic_Virtual"),
        mic_virtual_source=os.getenv("MIC_VIRTUAL_SOURCE", "Mic_Virtual_Input"),
        altavoz_virtual_sink=os.getenv("ALTAVOZ_VIRTUAL_SINK", "Altavoz_Virtual"),
        physical_mic_input_device=int(mic_input_env) if mic_input_env else None,
        physical_speaker_output_device=int(speaker_output_env) if speaker_output_env else None,
    )
