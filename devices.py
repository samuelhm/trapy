import argparse
import json
import subprocess
from typing import Any, Optional

import sounddevice as sd


def _find_first_index(devices: list[dict[str, Any]], needle: str, *, is_input: bool) -> Optional[int]:
    key = "max_input_channels" if is_input else "max_output_channels"
    n = needle.lower()
    for idx, dev in enumerate(devices):
        name = str(dev.get("name", "")).lower()
        if n in name and int(dev.get(key, 0)) > 0:
            return idx
    return None


def _print_table(devices: list[dict[str, Any]]) -> None:
    print("\n=== Dispositivos detectados (sounddevice) ===")
    for idx, dev in enumerate(devices):
        in_ch = int(dev.get("max_input_channels", 0))
        out_ch = int(dev.get("max_output_channels", 0))
        print(f"[{idx:>3}] in={in_ch:<2} out={out_ch:<2} name={dev.get('name', '')}")


def _pactl_list(kind: str) -> list[str]:
    try:
        result = subprocess.run(
            ["pactl", "list", "short", kind],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []

    return result.stdout.splitlines()


def _pactl_sink_exists(sink_name: str) -> bool:
    sinks = _pactl_list("sinks")
    return any(len(line.split("\t")) >= 2 and line.split("\t")[1] == sink_name for line in sinks)


def _pactl_source_exists(source_name: str) -> bool:
    sources = _pactl_list("sources")
    return any(len(line.split("\t")) >= 2 and line.split("\t")[1] == source_name for line in sources)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspecciona dispositivos de audio y sugiere IDs para .env"
    )
    parser.add_argument("--mic-virtual", default="Mic_Virtual", help="Nombre del sink virtual de salida para EN")
    parser.add_argument(
        "--altavoz-virtual",
        default="Altavoz_Virtual",
        help="Nombre del sink virtual cuyo monitor se captura para EN->ES",
    )
    parser.add_argument("--json", action="store_true", help="Salida en JSON")
    args = parser.parse_args()

    devices_raw = sd.query_devices()
    devices: list[dict[str, Any]] = [dict(d) for d in devices_raw]

    mic_virtual_output_id = _find_first_index(devices, args.mic_virtual, is_input=False)
    altavoz_monitor_input_id = _find_first_index(
        devices, f"{args.altavoz_virtual}.monitor", is_input=True
    )
    if altavoz_monitor_input_id is None:
        altavoz_monitor_input_id = _find_first_index(devices, args.altavoz_virtual, is_input=True)

    default_input, default_output = sd.default.device

    result = {
        "suggested": {
            "PHYSICAL_MIC_INPUT_DEVICE": default_input if default_input is not None and default_input >= 0 else None,
            "PHYSICAL_SPEAKER_OUTPUT_DEVICE": default_output if default_output is not None and default_output >= 0 else None,
            "MIC_VIRTUAL_OUTPUT_DEVICE_ID": mic_virtual_output_id,
            "ALTAVOZ_VIRTUAL_MONITOR_INPUT_DEVICE_ID": altavoz_monitor_input_id,
        },
        "virtual_names": {
            "MIC_VIRTUAL_SINK": args.mic_virtual,
            "ALTAVOZ_VIRTUAL_SINK": args.altavoz_virtual,
        },
    }

    if args.json:
        result["virtual_exists"] = {
            "MIC_VIRTUAL_SINK_EXISTS_PACTL": _pactl_sink_exists(args.mic_virtual),
            "ALTAVOZ_VIRTUAL_MONITOR_EXISTS_PACTL": _pactl_source_exists(f"{args.altavoz_virtual}.monitor"),
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    _print_table(devices)

    print("\n=== Recomendación para .env ===")
    print(f"MIC_VIRTUAL_SINK={args.mic_virtual}")
    print(f"ALTAVOZ_VIRTUAL_SINK={args.altavoz_virtual}")
    print(
        "PHYSICAL_MIC_INPUT_DEVICE="
        + (str(result["suggested"]["PHYSICAL_MIC_INPUT_DEVICE"]) if result["suggested"]["PHYSICAL_MIC_INPUT_DEVICE"] is not None else "")
    )
    print(
        "PHYSICAL_SPEAKER_OUTPUT_DEVICE="
        + (
            str(result["suggested"]["PHYSICAL_SPEAKER_OUTPUT_DEVICE"])
            if result["suggested"]["PHYSICAL_SPEAKER_OUTPUT_DEVICE"] is not None
            else ""
        )
    )

    print("\n=== IDs virtuales detectados (informativo) ===")
    print("MIC_VIRTUAL output device id:", result["suggested"]["MIC_VIRTUAL_OUTPUT_DEVICE_ID"])
    print(
        "ALTAVOZ_VIRTUAL monitor input device id:",
        result["suggested"]["ALTAVOZ_VIRTUAL_MONITOR_INPUT_DEVICE_ID"],
    )

    mic_sink_exists = _pactl_sink_exists(args.mic_virtual)
    altavoz_monitor_exists = _pactl_source_exists(f"{args.altavoz_virtual}.monitor")

    print("\n=== Estado en pactl (PulseAudio/PipeWire) ===")
    print(f"{args.mic_virtual} sink existe:", mic_sink_exists)
    print(f"{args.altavoz_virtual}.monitor source existe:", altavoz_monitor_exists)

    if result["suggested"]["MIC_VIRTUAL_OUTPUT_DEVICE_ID"] is None:
        if mic_sink_exists:
            print(
                "\n[INFO] El sink virtual existe en pactl, pero no aparece como dispositivo separado en sounddevice."
            )
        else:
            print(
                "\n[WARN] No se encontró salida para el sink virtual de mic. "
                "Asegúrate de que la app principal haya creado 'Mic_Virtual' o que exista previamente."
            )

    if result["suggested"]["ALTAVOZ_VIRTUAL_MONITOR_INPUT_DEVICE_ID"] is None:
        if altavoz_monitor_exists:
            print(
                "[INFO] El monitor virtual existe en pactl, pero no aparece como input separado en sounddevice."
            )
        else:
            print(
                "[WARN] No se encontró monitor de Altavoz_Virtual. "
                "Verifica que el sink exista y que el monitor sea visible en tu backend PulseAudio/PipeWire."
            )


if __name__ == "__main__":
    main()
