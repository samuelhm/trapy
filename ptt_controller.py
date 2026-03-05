"""Push-to-talk controllers for different input methods."""

import asyncio
import logging
import threading
from typing import TYPE_CHECKING, Optional, Any

from vad import VADDetector

if TYPE_CHECKING:
    from flow import TranslationFlow

logger = logging.getLogger(__name__)


class MousePushToTalkController:
    """Mouse button push-to-talk controller."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        flow_outgoing: "TranslationFlow",
        flow_incoming: "TranslationFlow",
    ) -> None:
        self.loop = loop
        self.flow_outgoing = flow_outgoing
        self.flow_incoming = flow_incoming
        self._listener = None
        self._mouse_module = None
        self._left_pressed = False
        self._middle_pressed = False

    def start(self) -> None:
        from pynput import mouse as mouse_module

        self._mouse_module = mouse_module
        self.flow_outgoing.input_stream.set_capture_enabled(False)
        self.flow_incoming.input_stream.set_capture_enabled(False)
        self._listener = mouse_module.Listener(on_click=self._on_click)
        self._listener.start()
        logger.info("Push-to-talk mouse: Left (ES→EN), Middle (EN→ES)")

    def stop(self) -> None:
        self.flow_outgoing.input_stream.set_capture_enabled(False)
        self.flow_incoming.input_stream.set_capture_enabled(False)
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def _on_click(self, x, y, button, pressed) -> None:
        if self._mouse_module is None:
            return

        if button == self._mouse_module.Button.left:
            if pressed and not self._left_pressed:
                self._left_pressed = True
                self.flow_outgoing.input_stream.set_capture_enabled(True)
                logger.info("[es_to_en] Captura iniciada")
            elif not pressed and self._left_pressed:
                self._left_pressed = False
                self.flow_outgoing.input_stream.set_capture_enabled(False)
                logger.info("[es_to_en] Captura finalizada")
                self.loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(self._commit_flow(self.flow_outgoing, "es_to_en"))
                )

        if button == self._mouse_module.Button.middle:
            if pressed and not self._middle_pressed:
                self._middle_pressed = True
                self.flow_incoming.input_stream.set_capture_enabled(True)
                logger.info("[en_to_es] Captura iniciada")
            elif not pressed and self._middle_pressed:
                self._middle_pressed = False
                self.flow_incoming.input_stream.set_capture_enabled(False)
                logger.info("[en_to_es] Captura finalizada")
                self.loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(self._commit_flow(self.flow_incoming, "en_to_es"))
                )

    async def _commit_flow(self, flow: "TranslationFlow", flow_name: str) -> None:
        try:
            pcm = flow.input_stream.pop_captured_audio()
            logger.info("[%s] Audio: %d bytes", flow_name, len(pcm))
            asyncio.create_task(self._process_segment_async(flow, flow_name, pcm))
        except Exception as exc:
            logger.error("[%s] Error: %s", flow_name, exc)

    async def _process_segment_async(self, flow: "TranslationFlow", flow_name: str, pcm: bytes) -> None:
        try:
            committed = await flow.client.process_segment(pcm)
            if not committed:
                logger.warning("[%s] Segmento no procesado", flow_name)
        except Exception as exc:
            logger.error("[%s] Error procesando: %s", flow_name, exc)


class KeyboardPushToTalkController:
    """Keyboard push-to-talk with VAD phrase detection."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        flow_outgoing: "TranslationFlow",
        flow_incoming: "TranslationFlow",
        outgoing_keys: str,
        incoming_keys: str,
    ) -> None:
        self.loop = loop
        self.flow_outgoing = flow_outgoing
        self.flow_incoming = flow_incoming
        self.outgoing_keys = outgoing_keys
        self.incoming_keys = incoming_keys

        self._key_map = self._build_key_map()
        self._outgoing_codes = self._parse_key_codes(outgoing_keys)
        self._incoming_codes = self._parse_key_codes(incoming_keys)

        self._listener_thread: Optional[threading.Thread] = None
        self._stop_listener = False
        self._pressed_codes: set[int] = set()
        self._outgoing_active = False
        self._incoming_active = False
        self._device: Optional[Any] = None

        self._outgoing_vad = VADDetector(sample_rate=16000, silence_duration_ms=600)
        self._incoming_vad = VADDetector(sample_rate=16000, silence_duration_ms=600)

        self._outgoing_task: Optional[asyncio.Task] = None
        self._incoming_task: Optional[asyncio.Task] = None
        self._stop_processing = False

    def _build_key_map(self) -> dict[str, int]:
        """Map key names to evdev key codes."""
        try:
            from evdev import ecodes
            return {
                'f1': ecodes.KEY_F1, 'f2': ecodes.KEY_F2, 'f3': ecodes.KEY_F3,
                'f4': ecodes.KEY_F4, 'f5': ecodes.KEY_F5, 'f6': ecodes.KEY_F6,
                'f7': ecodes.KEY_F7, 'f8': ecodes.KEY_F8, 'f9': ecodes.KEY_F9,
                'f10': ecodes.KEY_F10, 'f11': ecodes.KEY_F11, 'f12': ecodes.KEY_F12,
            }
        except ImportError:
            logger.error("evdev no disponible")
            return {}

    def _parse_key_codes(self, keys_str: str) -> set[int]:
        """Parse key string (e.g., 'f8') into evdev codes."""
        codes = set()
        for key in keys_str.split("+"):
            key = key.strip().lower()
            if key in self._key_map:
                codes.add(self._key_map[key])
        return codes

    def _find_keyboard_device(self) -> Optional[Any]:
        """Find first keyboard device excluding mice and touchpads."""
        try:
            from evdev import InputDevice, ecodes
            import glob

            excluded_keywords = ["mouse", "touchpad", "trackpad", "cursor", "pointer"]
            preferred_keywords = ["keyboard", "kbd"]

            candidates = []

            for path in glob.glob("/dev/input/event*"):
                try:
                    device = InputDevice(path)
                    device_name = device.name.lower()

                    if any(keyword in device_name for keyword in excluded_keywords):
                        logger.debug("Dispositivo descartado: %s (%s)", path, device.name)
                        continue

                    capabilities = device.capabilities()
                    if ecodes.EV_KEY not in capabilities:
                        continue

                    has_movement = ecodes.EV_REL in capabilities or ecodes.EV_ABS in capabilities
                    is_keyboard_name = any(keyword in device_name for keyword in preferred_keywords)

                    candidates.append({
                        'path': path,
                        'name': device.name,
                        'device': device,
                        'is_keyboard_name': is_keyboard_name,
                        'has_movement': has_movement,
                    })

                except (PermissionError, OSError) as e:
                    logger.debug("No se puede acceder a %s: %s", path, e)
                    continue

            if not candidates:
                logger.error("No se encontró dispositivo de teclado. Usa: python -c \"from evdev import list_devices; print(list(list_devices()))\"")
                return None

            candidates.sort(key=lambda x: (
                not x['is_keyboard_name'],
                x['has_movement'],
            ))

            selected = candidates[0]
            logger.info("Teclado seleccionado: %s (%s)", selected['path'], selected['name'])

            if len(candidates) > 1:
                logger.debug("Otros dispositivos encontrados:")
                for c in candidates[1:]:
                    logger.debug("  %s: %s", c['path'], c['name'])

            return selected['device']

        except ImportError:
            logger.error("evdev no disponible")
            return None

    def start(self) -> None:
        self.flow_outgoing.input_stream.set_capture_enabled(False)
        self.flow_incoming.input_stream.set_capture_enabled(False)

        self._device = self._find_keyboard_device()
        if self._device is None:
            logger.error("No se pudo iniciar keyboard controller")
            return

        self._stop_listener = False
        self._listener_thread = threading.Thread(target=self._event_loop, daemon=True)
        self._listener_thread.start()

        logger.info("Push-to-talk teclado: %s (ES→EN), %s (EN→ES)", self.outgoing_keys, self.incoming_keys)

    def stop(self) -> None:
        self.flow_outgoing.input_stream.set_capture_enabled(False)
        self.flow_incoming.input_stream.set_capture_enabled(False)
        self._stop_listener = True
        if self._listener_thread is not None:
            self._listener_thread.join(timeout=1.0)
            self._listener_thread = None
        if self._device is not None:
            try:
                self._device.close()
            except:
                pass
            self._device = None

    def _event_loop(self) -> None:
        """Listen for keyboard events in background thread."""
        if self._device is None:
            return

        try:
            for event in self._device.read_loop():
                if self._stop_listener:
                    break

                from evdev import ecodes

                if event.type != ecodes.EV_KEY:
                    continue

                key_code = event.code
                key_state = event.value

                if key_state == 1:
                    self._handle_key_press(key_code)
                elif key_state == 0:
                    self._handle_key_release(key_code)

        except Exception as e:
            logger.error("Error en event loop: %s", e)

    def _handle_key_press(self, key_code: int) -> None:
        """Start VAD processing on key press."""
        self._pressed_codes.add(key_code)

        if self._outgoing_codes.issubset(self._pressed_codes) and not self._outgoing_active:
            self._outgoing_active = True
            self.flow_outgoing.input_stream.set_capture_enabled(True)
            self._stop_processing = False
            self._outgoing_task = self.loop.create_task(self._vad_processing_loop(
                self.flow_outgoing, self._outgoing_vad, "es_to_en"
            ))
            logger.info("[es_to_en] Captura iniciada")

        if self._incoming_codes.issubset(self._pressed_codes) and not self._incoming_active:
            self._incoming_active = True
            self.flow_incoming.input_stream.set_capture_enabled(True)
            self._stop_processing = False
            self._incoming_task = self.loop.create_task(self._vad_processing_loop(
                self.flow_incoming, self._incoming_vad, "en_to_es"
            ))
            logger.info("[en_to_es] Captura iniciada")

    def _handle_key_release(self, key_code: int) -> None:
        """Stop VAD processing and flush on key release."""
        self._pressed_codes.discard(key_code)

        if self._outgoing_active and not self._outgoing_codes.issubset(self._pressed_codes):
            self._outgoing_active = False
            self.flow_outgoing.input_stream.set_capture_enabled(False)
            logger.info("[es_to_en] Captura finalizada")
            self._stop_processing = True
            if self._outgoing_task is not None:
                self.loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(self._wait_and_flush(self._outgoing_task, self._outgoing_vad, "es_to_en", self.flow_outgoing))
                )

        if self._incoming_active and not self._incoming_codes.issubset(self._pressed_codes):
            self._incoming_active = False
            self.flow_incoming.input_stream.set_capture_enabled(False)
            logger.info("[en_to_es] Captura finalizada")
            self._stop_processing = True
            if self._incoming_task is not None:
                self.loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(self._wait_and_flush(self._incoming_task, self._incoming_vad, "en_to_es", self.flow_incoming))
                )

    async def _vad_processing_loop(self, flow: "TranslationFlow", vad: VADDetector, flow_name: str) -> None:
        """Detect phrases with VAD while key is pressed."""
        total_audio = 0
        while not self._stop_processing:
            try:
                chunk = flow.input_stream.pop_captured_audio()

                if chunk and len(chunk) > 0:
                    total_audio += len(chunk)
                    logger.info("[%s] Audio: %d bytes (total: %d)", flow_name, len(chunk), total_audio)
                    phrase = vad.process_chunk(chunk)

                    if phrase:
                        logger.info("[%s] Frase detectada: %d bytes", flow_name, len(phrase))
                        asyncio.create_task(self._process_segment_async(flow, flow_name, phrase))

                await asyncio.sleep(0.05)

            except Exception as e:
                logger.error("[%s] Error VAD: %s", flow_name, e)
                await asyncio.sleep(0.05)

    async def _wait_and_flush(self, task: Optional[asyncio.Task], vad: VADDetector, flow_name: str, flow: "TranslationFlow") -> None:
        """Wait for VAD task and flush remaining audio."""
        logger.info("[%s] Flush VAD", flow_name)
        if task is not None:
            try:
                await asyncio.wait_for(task, timeout=0.5)
            except asyncio.CancelledError:
                pass
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                logger.debug("[%s] Error esperando VAD: %s", flow_name, e)

        remaining = vad.flush()
        if remaining and len(remaining) > 0:
            logger.info("[%s] Frase final: %d bytes", flow_name, len(remaining))
            await self._process_segment_async(flow, flow_name, remaining)

    async def _process_segment_async(self, flow: "TranslationFlow", flow_name: str, pcm: bytes) -> None:
        """Process audio segment."""
        try:
            committed = await flow.client.process_segment(pcm)
            if not committed:
                logger.warning("[%s] Segmento no procesado", flow_name)
        except Exception as exc:
            logger.error("[%s] Error: %s", flow_name, exc)
