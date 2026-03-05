"""Bidirectional audio translator application."""

import asyncio
import logging
import signal

from config import AppConfig, AudioConfig, load_config
from hardware import VirtualHardwareManager
from device_utils import find_device_index, resolve_safe_device_index
from audio import AudioInputStream, AudioOutputStream, PulseSourceInputStream, PulseSinkOutputStream
from client import OpenAIRealtimeClient
from flow import TranslationFlow
from ptt_controller import MousePushToTalkController, KeyboardPushToTalkController

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bidi-translator")


class BidiTranslatorApp:
    """Main application orchestrating bidirectional translation."""

    def __init__(self, config: AppConfig, audio_cfg: AudioConfig) -> None:
        self.config = config
        self.audio_cfg = audio_cfg
        self.hw = VirtualHardwareManager(
            config.mic_virtual_sink,
            config.mic_virtual_source,
            config.altavoz_virtual_sink,
        )
        self.flow_outgoing: TranslationFlow | None = None
        self.flow_incoming: TranslationFlow | None = None
        self.ptt_controller = None
        self._stop_event = asyncio.Event()

    def _build_flow_outgoing(
        self,
        loop: asyncio.AbstractEventLoop,
        mic_virtual_out_device: int | None,
        use_pulse_sink_fallback: bool,
        physical_mic_input_device: int | None,
    ) -> TranslationFlow:
        input_q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=300)
        output_q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=50)

        input_stream = AudioInputStream(
            loop=loop,
            config=self.audio_cfg,
            queue=input_q,
            device=physical_mic_input_device,
            name="outgoing_mic_es",
        )
        
        if use_pulse_sink_fallback:
            output_stream = PulseSinkOutputStream(
                config=self.audio_cfg,
                sink_name=self.config.mic_virtual_sink,
                name="outgoing_to_mic_virtual_en",
            )
        else:
            output_stream = AudioOutputStream(
                config=self.audio_cfg,
                device=mic_virtual_out_device,
                name="outgoing_to_mic_virtual_en",
            )

        instructions = (
            "You are a simultaneous interpreter, not a general assistant. "
            "Source language: Spanish. Target language: English. "
            "For every detected speech segment, output only the direct translation in English audio. "
            "If there is no clear source speech to translate, output no audio at all. "
            "Never acknowledge readiness or say phrases like 'ok', 'de acuerdo', or 'voy a comenzar'. "
            "Do not answer questions, do not add commentary, do not introduce yourself, "
            "do not summarize, and do not ask follow-up questions. "
            "If speech is unclear, output a very short best-effort translation only."
        )
        
        client = OpenAIRealtimeClient(
            config=self.config,
            audio_config=self.audio_cfg,
            input_queue=input_q,
            output_queue=output_q,
            instructions=instructions,
            name="es_to_en",
            source_language="es",
            target_language="en",
        )

        return TranslationFlow(
            name="es_to_en",
            input_stream=input_stream,
            output_stream=output_stream,
            client=client,
            output_queue=output_q,
        )

    def _build_flow_incoming(
        self,
        loop: asyncio.AbstractEventLoop,
        altavoz_monitor_in_device: int | None,
        use_pulse_source_fallback: bool,
        physical_speaker_output_device: int | None,
    ) -> TranslationFlow:
        input_q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=300)
        output_q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=50)

        if use_pulse_source_fallback:
            input_stream = PulseSourceInputStream(
                loop=loop,
                config=self.audio_cfg,
                queue=input_q,
                source_name=f"{self.config.altavoz_virtual_sink}.monitor",
                name="incoming_virtual_en",
            )
        else:
            input_stream = AudioInputStream(
                loop=loop,
                config=self.audio_cfg,
                queue=input_q,
                device=altavoz_monitor_in_device,
                name="incoming_virtual_en",
            )
        
        output_stream = AudioOutputStream(
            config=self.audio_cfg,
            device=physical_speaker_output_device,
            name="incoming_to_physical_es",
        )

        instructions = (
            "You are a simultaneous interpreter, not a general assistant. "
            "Source language: English. Target language: Spanish. "
            "For every detected speech segment, output only the direct translation in Spanish audio. "
            "If there is no clear source speech to translate, output no audio at all. "
            "Never acknowledge readiness or say phrases like 'ok', 'de acuerdo', or 'voy a comenzar'. "
            "Do not answer questions, do not add commentary, do not introduce yourself, "
            "do not summarize, and do not ask follow-up questions. "
            "If speech is unclear, output a very short best-effort translation only."
        )
        
        client = OpenAIRealtimeClient(
            config=self.config,
            audio_config=self.audio_cfg,
            input_queue=input_q,
            output_queue=output_q,
            instructions=instructions,
            name="en_to_es",
            source_language="en",
            target_language="es",
        )

        return TranslationFlow(
            name="en_to_es",
            input_stream=input_stream,
            output_stream=output_stream,
            client=client,
            output_queue=output_q,
        )

    async def start(self) -> None:
        """Initialize hardware, audio, and start translation flows."""
        if self.config.mic_virtual_sink == self.config.altavoz_virtual_sink:
            raise RuntimeError(
                "MIC_VIRTUAL_SINK y ALTAVOZ_VIRTUAL_SINK no pueden ser el mismo sink."
            )

        self.hw.setup()

        # Find virtual device routes
        use_pulse_sink_fallback = False
        mic_virtual_out_device = find_device_index(self.config.mic_virtual_sink, is_input=False)
        if mic_virtual_out_device is None:
            if self.hw.sink_exists(self.config.mic_virtual_sink):
                use_pulse_sink_fallback = True
                logger.warning(
                    "No device encontrado para '%s', usando pacat fallback.",
                    self.config.mic_virtual_sink,
                )
            else:
                raise RuntimeError(
                    f"No se encontró dispositivo de salida para '{self.config.mic_virtual_sink}'."
                )

        use_pulse_source_fallback = False
        altavoz_monitor_in_device = find_device_index(
            f"{self.config.altavoz_virtual_sink}.monitor", is_input=True
        )
        if altavoz_monitor_in_device is None:
            altavoz_monitor_in_device = find_device_index(self.config.altavoz_virtual_sink, is_input=True)

        if altavoz_monitor_in_device is None:
            monitor_name = f"{self.config.altavoz_virtual_sink}.monitor"
            if self.hw.source_exists(monitor_name):
                use_pulse_source_fallback = True
                logger.warning(
                    "No device encontrado para '%s', usando parec fallback.",
                    monitor_name,
                )
            else:
                raise RuntimeError(
                    f"No se encontró input monitor para '{self.config.altavoz_virtual_sink}'."
                )

        # Find physical devices
        resolved_physical_mic_input_device = resolve_safe_device_index(
            config=self.config,
            is_input=True,
            explicit_index=self.config.physical_mic_input_device,
        )
        if resolved_physical_mic_input_device is None:
            raise RuntimeError(
                "No se pudo resolver micrófono físico. "
                "Configura PHYSICAL_MIC_INPUT_DEVICE en .env."
            )

        resolved_physical_speaker_output_device = resolve_safe_device_index(
            config=self.config,
            is_input=False,
            explicit_index=self.config.physical_speaker_output_device,
        )
        if resolved_physical_speaker_output_device is None:
            raise RuntimeError(
                "No se pudo resolver altavoz físico. "
                "Configura PHYSICAL_SPEAKER_OUTPUT_DEVICE en .env."
            )

        logger.info(
            "Dispositivos: mic_input=%s, speaker_output=%s",
            resolved_physical_mic_input_device,
            resolved_physical_speaker_output_device,
        )

        # Build flows
        loop = asyncio.get_running_loop()
        self.flow_outgoing = self._build_flow_outgoing(
            loop,
            mic_virtual_out_device,
            use_pulse_sink_fallback,
            resolved_physical_mic_input_device,
        )
        self.flow_incoming = self._build_flow_incoming(
            loop,
            altavoz_monitor_in_device,
            use_pulse_source_fallback,
            resolved_physical_speaker_output_device,
        )

        # Start flows
        await asyncio.gather(
            self.flow_outgoing.start(),
            self.flow_incoming.start(),
        )

        # Start push-to-talk controller
        if self.config.translation_mode == "mouse_hold":
            self.ptt_controller = MousePushToTalkController(
                loop=loop,
                flow_outgoing=self.flow_outgoing,
                flow_incoming=self.flow_incoming,
            )
            self.ptt_controller.start()
        elif self.config.translation_mode == "keyboard_hold":
            self.ptt_controller = KeyboardPushToTalkController(
                loop=loop,
                flow_outgoing=self.flow_outgoing,
                flow_incoming=self.flow_incoming,
                outgoing_keys=self.config.outgoing_ptt_keys,
                incoming_keys=self.config.incoming_ptt_keys,
            )
            self.ptt_controller.start()
        else:
            self.flow_outgoing.input_stream.set_capture_enabled(True)
            self.flow_incoming.input_stream.set_capture_enabled(True)

        logger.info("Aplicación iniciada. Ctrl+C para salir.")

    async def stop(self) -> None:
        """Stop translation flows and clean up hardware."""
        if self.ptt_controller is not None:
            self.ptt_controller.stop()
            self.ptt_controller = None

        if self.flow_outgoing or self.flow_incoming:
            await asyncio.gather(
                *(
                    flow.stop()
                    for flow in (self.flow_outgoing, self.flow_incoming)
                    if flow is not None
                ),
                return_exceptions=True,
            )

        self.hw.cleanup()
        logger.info("Cierre completo.")

    async def run_forever(self) -> None:
        """Run until stop event is set."""
        await self._stop_event.wait()


def _install_signal_handlers(app: BidiTranslatorApp) -> None:
    """Install signal handlers for graceful shutdown."""
    loop = asyncio.get_running_loop()

    def _stop() -> None:
        logger.info("Señal de parada recibida")
        app._stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            pass


async def async_main() -> None:
    """Main entry point."""
    config = load_config()
    audio_cfg = AudioConfig(
        sample_rate=16000,
        channels=1,
        dtype="int16",
        chunk_ms=10,
    )

    app = BidiTranslatorApp(config, audio_cfg)
    _install_signal_handlers(app)

    try:
        await app.start()
        await app.run_forever()
    finally:
        await app.stop()


def main() -> None:
    """Entry point."""
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
