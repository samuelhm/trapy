"""Audio device discovery and selection utilities."""

import logging
from typing import Optional

import sounddevice as sd

from config import AppConfig

logger = logging.getLogger(__name__)


def find_device_index(name_substring: str, *, is_input: bool) -> Optional[int]:
    """Find first audio device matching name substring."""
    devices = sd.query_devices()
    target = name_substring.lower()
    channel_key = "max_input_channels" if is_input else "max_output_channels"

    for idx, dev in enumerate(devices):
        if target in dev["name"].lower() and dev[channel_key] > 0:
            return idx
    return None


def resolve_safe_device_index(
    *,
    config: AppConfig,
    is_input: bool,
    explicit_index: Optional[int],
) -> Optional[int]:
    """
    Resolve a safe physical device index, excluding virtual devices.
    
    Prefers explicit index, then OS default (if safe), then first safe device.
    """
    if explicit_index is not None:
        return explicit_index

    devices = sd.query_devices()
    channel_key = "max_input_channels" if is_input else "max_output_channels"
    default_in, default_out = sd.default.device
    default_index = default_in if is_input else default_out

    blocked_terms = {
        config.mic_virtual_sink.lower(),
        config.mic_virtual_source.lower(),
        f"{config.mic_virtual_sink}.monitor".lower(),
        config.altavoz_virtual_sink.lower(),
        f"{config.altavoz_virtual_sink}.monitor".lower(),
    }

    def _is_valid_candidate(idx: int) -> bool:
        if idx < 0 or idx >= len(devices):
            return False
        dev = devices[idx]
        if int(dev.get(channel_key, 0)) <= 0:
            return False
        dev_name = str(dev.get("name", "")).lower()
        return not any(term in dev_name for term in blocked_terms)

    if isinstance(default_index, int) and _is_valid_candidate(default_index):
        return default_index

    for idx in range(len(devices)):
        if _is_valid_candidate(idx):
            return idx

    if isinstance(default_index, int) and default_index >= 0 and default_index < len(devices):
        if int(devices[default_index].get(channel_key, 0)) > 0:
            return default_index

    return None
