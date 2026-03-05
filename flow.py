"""Translation flow orchestration."""

import asyncio
import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from client import OpenAIRealtimeClient
    from audio import AudioInputStream, AudioOutputStream

logger = logging.getLogger(__name__)


class TranslationFlow:
    """Bidirectional audio stream with translation client and playback."""

    def __init__(
        self,
        name: str,
        input_stream: "AudioInputStream",
        output_stream: "AudioOutputStream",
        client: "OpenAIRealtimeClient",
        output_queue: asyncio.Queue[bytes],
    ) -> None:
        self.name = name
        self.input_stream = input_stream
        self.output_stream = output_stream
        self.client = client
        self.output_queue = output_queue
        self._playback_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start output stream, input stream, client, and playback loop."""
        self.output_stream.start()
        self.input_stream.start()
        await self.client.start()
        self._playback_task = asyncio.create_task(self._playback_loop(), name=f"{self.name}-playback")
        logger.info("Flujo '%s' activo", self.name)

    async def stop(self) -> None:
        """Stop all components."""
        if self._playback_task is not None:
            self._playback_task.cancel()
            try:
                await self._playback_task
            except asyncio.CancelledError:
                pass

        await self.client.stop()
        self.input_stream.stop()
        self.output_stream.stop()
        logger.info("Flujo '%s' detenido", self.name)

    async def _playback_loop(self) -> None:
        """Continuously play audio from output queue."""
        while True:
            pcm = await self.output_queue.get()
            self.output_stream.write_chunk(pcm)
