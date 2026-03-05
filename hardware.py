"""Virtual audio hardware management via PulseAudio/PipeWire."""

import subprocess
import logging

logger = logging.getLogger(__name__)


class VirtualHardwareManager:
    """Setup and cleanup of virtual audio sinks and sources."""

    def __init__(self, mic_sink_name: str, mic_source_name: str, altavoz_sink_name: str) -> None:
        self.mic_sink_name = mic_sink_name
        self.mic_source_name = mic_source_name
        self.altavoz_sink_name = altavoz_sink_name
        self._created_module_ids: list[int] = []

    def _run_pactl(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["pactl", *args],
            check=True,
            capture_output=True,
            text=True,
        )

    def _sink_exists(self, sink_name: str) -> bool:
        result = self._run_pactl(["list", "short", "sinks"])
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[1] == sink_name:
                return True
        return False

    def _source_exists(self, source_name: str) -> bool:
        result = self._run_pactl(["list", "short", "sources"])
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[1] == source_name:
                return True
        return False

    def sink_exists(self, sink_name: str) -> bool:
        return self._sink_exists(sink_name)

    def source_exists(self, source_name: str) -> bool:
        return self._source_exists(source_name)

    def _load_null_sink(self, sink_name: str) -> None:
        if self._sink_exists(sink_name):
            logger.info("Sink '%s' ya existe. No se crea de nuevo.", sink_name)
            return

        result = self._run_pactl(
            [
                "load-module",
                "module-null-sink",
                f"sink_name={sink_name}",
                f"sink_properties=device.description={sink_name}",
            ]
        )
        module_id = int(result.stdout.strip())
        self._created_module_ids.append(module_id)
        logger.info("Sink '%s' creado con module id %s", sink_name, module_id)

    def _load_remap_source(self, source_name: str, master_source_name: str) -> None:
        if self._source_exists(source_name):
            logger.info("Source '%s' ya existe. No se crea de nuevo.", source_name)
            return

        result = self._run_pactl(
            [
                "load-module",
                "module-remap-source",
                f"source_name={source_name}",
                f"master={master_source_name}",
                "channels=1",
                f"source_properties=device.description={source_name}",
            ]
        )
        module_id = int(result.stdout.strip())
        self._created_module_ids.append(module_id)
        logger.info(
            "Source remapeado '%s' creado desde '%s' con module id %s",
            source_name,
            master_source_name,
            module_id,
        )

    def setup(self) -> None:
        """Create virtual sinks and sources."""
        self._load_null_sink(self.mic_sink_name)
        self._load_null_sink(self.altavoz_sink_name)
        self._load_remap_source(self.mic_source_name, f"{self.mic_sink_name}.monitor")

    def cleanup(self) -> None:
        """Unload all created virtual modules."""
        for module_id in reversed(self._created_module_ids):
            try:
                self._run_pactl(["unload-module", str(module_id)])
                logger.info("Módulo virtual descargado: %s", module_id)
            except subprocess.CalledProcessError as exc:
                logger.warning("No se pudo descargar módulo %s: %s", module_id, exc)
