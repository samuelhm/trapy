"""Audio I/O streaming classes using sounddevice and PulseAudio."""

import asyncio
import logging
import subprocess
import threading
from collections import deque
from typing import Optional

import numpy as np
import sounddevice as sd

from config import AudioConfig

logger = logging.getLogger(__name__)


class AudioInputStream:
    """Capture audio from sounddevice with VAD trigger support."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        config: AudioConfig,
        queue: asyncio.Queue[bytes],
        device: Optional[int],
        name: str,
    ) -> None:
        self.loop = loop
        self.config = config
        self.queue = queue
        self.device = device
        self.name = name
        self._stream: Optional[sd.InputStream] = None
        self._capture_enabled = False
        self._captured_audio = bytearray()
        self._capture_lock = threading.Lock()

    def set_capture_enabled(self, enabled: bool) -> None:
        if enabled and not self._capture_enabled:
            with self._capture_lock:
                self._captured_audio.clear()
        self._capture_enabled = enabled

    def pop_captured_audio(self) -> bytes:
        with self._capture_lock:
            data = bytes(self._captured_audio)
            self._captured_audio.clear()
            return data

    def _callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        if status:
            logger.debug("Input status (%s): %s", self.name, status)

        if not self._capture_enabled or frames <= 0:
            return

        chunk = np.array(indata[:, 0], dtype=np.int16).tobytes()
        with self._capture_lock:
            self._captured_audio.extend(chunk)

        def _enqueue() -> None:
            if self.queue.full():
                return
            try:
                self.queue.put_nowait(chunk)
            except asyncio.QueueFull:
                pass

        self.loop.call_soon_threadsafe(_enqueue)

    def start(self) -> None:
        self._stream = sd.InputStream(
            samplerate=self.config.sample_rate,
            channels=self.config.channels,
            dtype=self.config.dtype,
            blocksize=self.config.frames_per_chunk,
            device=self.device,
            callback=self._callback,
        )
        assert self._stream is not None
        self._stream.start()
        logger.info("Input '%s' iniciado (device=%s)", self.name, self.device)

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            logger.info("Input '%s' detenido", self.name)


class AudioOutputStream:
    """Playback audio via sounddevice with buffering."""

    def __init__(self, config: AudioConfig, device: Optional[int], name: str) -> None:
        self.config = config
        self.device = device
        self.name = name
        self._stream: Optional[sd.OutputStream] = None
        self._buffer: deque[np.ndarray] = deque()
        self._lock = threading.Lock()

    def write_chunk(self, pcm_bytes: bytes) -> None:
        arr = np.frombuffer(pcm_bytes, dtype=np.int16)
        if arr.size == 0:
            return
        with self._lock:
            self._buffer.append(arr)

    def _callback(self, outdata: np.ndarray, frames: int, time_info, status) -> None:
        if status:
            logger.debug("Output status (%s): %s", self.name, status)

        out = np.zeros(frames, dtype=np.int16)
        offset = 0

        with self._lock:
            while self._buffer and offset < frames:
                cur = self._buffer[0]
                remaining = frames - offset
                take = min(remaining, cur.size)
                out[offset : offset + take] = cur[:take]
                offset += take

                if take == cur.size:
                    self._buffer.popleft()
                else:
                    self._buffer[0] = cur[take:]

        outdata[:, 0] = out

    def start(self) -> None:
        self._stream = sd.OutputStream(
            samplerate=self.config.sample_rate,
            channels=self.config.channels,
            dtype=self.config.dtype,
            blocksize=self.config.frames_per_chunk,
            device=self.device,
            callback=self._callback,
        )
        assert self._stream is not None
        self._stream.start()
        logger.info("Output '%s' iniciado (device=%s)", self.name, self.device)

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            logger.info("Output '%s' detenido", self.name)


class PulseSourceInputStream:
    """Capture audio from PulseAudio source via parec."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        config: AudioConfig,
        queue: asyncio.Queue[bytes],
        source_name: str,
        name: str,
    ) -> None:
        self.loop = loop
        self.config = config
        self.queue = queue
        self.source_name = source_name
        self.name = name
        self._proc: Optional[subprocess.Popen[bytes]] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._running = False
        self._capture_enabled = False
        self._captured_audio = bytearray()
        self._capture_lock = threading.Lock()

    def set_capture_enabled(self, enabled: bool) -> None:
        if enabled and not self._capture_enabled:
            with self._capture_lock:
                self._captured_audio.clear()
        self._capture_enabled = enabled

    def pop_captured_audio(self) -> bytes:
        with self._capture_lock:
            data = bytes(self._captured_audio)
            self._captured_audio.clear()
            return data

    def _enqueue_chunk(self, chunk: bytes) -> None:
        def _enqueue() -> None:
            if self.queue.full():
                return
            try:
                self.queue.put_nowait(chunk)
            except asyncio.QueueFull:
                pass

        self.loop.call_soon_threadsafe(_enqueue)

    def _reader_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None

        bytes_per_sample = 2
        chunk_size = self.config.frames_per_chunk * self.config.channels * bytes_per_sample

        while self._running:
            chunk = self._proc.stdout.read(chunk_size)
            if not chunk:
                break
            if not self._capture_enabled:
                continue
            with self._capture_lock:
                self._captured_audio.extend(chunk)
            self._enqueue_chunk(chunk)

    def start(self) -> None:
        cmd = [
            "parec",
            "--raw",
            "--format=s16le",
            f"--rate={self.config.sample_rate}",
            f"--channels={self.config.channels}",
            f"--device={self.source_name}",
        ]
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("No se encontró 'parec'. Instala pulseaudio-utils.") from exc

        self._running = True
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()
        logger.info("Input '%s' iniciado vía parec (source=%s)", self.name, self.source_name)

    def stop(self) -> None:
        self._running = False

        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self._proc.kill()

            if self._proc.stdout is not None:
                self._proc.stdout.close()

        if self._reader_thread is not None:
            self._reader_thread.join(timeout=1)

        logger.info("Input '%s' detenido", self.name)


class PulseSinkOutputStream:
    """Playback audio to PulseAudio sink via pacat."""

    def __init__(self, config: AudioConfig, sink_name: str, name: str) -> None:
        self.config = config
        self.sink_name = sink_name
        self.name = name
        self._proc: Optional[subprocess.Popen[bytes]] = None
        self._lock = threading.Lock()

    def write_chunk(self, pcm_bytes: bytes) -> None:
        if not pcm_bytes:
            return

        with self._lock:
            if self._proc is None or self._proc.stdin is None:
                return
            try:
                self._proc.stdin.write(pcm_bytes)
                self._proc.stdin.flush()
            except BrokenPipeError:
                logger.warning("Output '%s': pipe de pacat cerrado", self.name)

    def start(self) -> None:
        cmd = [
            "pacat",
            "--raw",
            "--format=s16le",
            f"--rate={self.config.sample_rate}",
            f"--channels={self.config.channels}",
            "--playback",
            f"--device={self.sink_name}",
        ]
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("No se encontró 'pacat'. Instala pulseaudio-utils.") from exc

        logger.info("Output '%s' iniciado vía pacat (sink=%s)", self.name, self.sink_name)

    def stop(self) -> None:
        if self._proc is not None:
            if self._proc.stdin is not None:
                self._proc.stdin.close()
            self._proc.terminate()
            try:
                self._proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self._proc.kill()

        logger.info("Output '%s' detenido", self.name)
