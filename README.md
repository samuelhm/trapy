# Bidirectional Voice Translator

A real-time bidirectional audio translation tool for Linux using OpenAI's speech APIs. Capture audio via push-to-talk, translate Spanish ↔ English, and play back synthesized speech — all with minimal latency.

## Features

- **Real-time bidirectional translation**: Spanish → English and English → Spanish
- **Push-to-talk controls**: Keyboard (F8/F9) or mouse buttons
- **Voice Activity Detection (VAD)**: Automatic phrase boundary detection
- **Modular architecture**: Well-separated concerns for easy maintenance
- **Virtual audio routing**: Seamless integration with PulseAudio/PipeWire
- **OpenAI APIs**: Whisper (STT) → GPT (translation) → TTS (speech synthesis)

## System Requirements

- **OS**: Linux with PulseAudio or PipeWire
- **Python**: 3.10+
- **Audio Tools**: 
  - `pactl`, `pacat`, `parec` (install: `pulseaudio-utils` on Debian/Ubuntu)
  - Or compatible PipeWire equivalents
- **API Key**: OpenAI API key with access to audio models

## Installation

### 1. Clone and setup environment

```bash
git clone https://github.com/yourusername/trapy.git
cd trapy
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and add your OpenAI API key:

```env
OPENAI_API_KEY=sk-...
TRANSLATION_MODE=keyboard_hold
OUTGOING_PTT_KEYS=f8
INCOMING_PTT_KEYS=f9
```

### 3. Set audio device IDs (optional but recommended)

List your audio devices:

```bash
python -c "import sounddevice as sd; print(sd.query_devices())"
```

Add device IDs to `.env`:

```env
PHYSICAL_MIC_INPUT_DEVICE=1
PHYSICAL_SPEAKER_OUTPUT_DEVICE=2
```

## Usage

### Quick start

```bash
python app.py
```

### With virtual device management

```bash
./start_translator.zsh
```

### Manual device management

```bash
# Check status
./manage_virtual_devices.zsh status

# Create virtual devices
./manage_virtual_devices.zsh up

# Run translator
python app.py

# Clean up
./manage_virtual_devices.zsh down
```

## Configuration

### Translation Modes

- `keyboard_hold`: Hold F8 (ES→EN) or F9 (EN→ES), release to translate
- `mouse_hold`: Left click and drag (ES→EN), middle click and drag (EN→ES)
- `simultaneous`: Continuous translation (both flows active)
- `turn`: Manual control (capture disabled by default)

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | Required | OpenAI API key |
| `TRANSLATION_MODE` | `keyboard_hold` | Input method |
| `OUTGOING_PTT_KEYS` | `f8` | Key(s) for ES→EN |
| `INCOMING_PTT_KEYS` | `f9` | Key(s) for EN→ES |
| `MIC_VIRTUAL_SINK` | `Mic_Virtual` | Virtual sink name |
| `ALTAVOZ_VIRTUAL_SINK` | `Altavoz_Virtual` | Speaker sink name |
| `PHYSICAL_MIC_INPUT_DEVICE` | Auto-detect | Physical microphone ID |
| `PHYSICAL_SPEAKER_OUTPUT_DEVICE` | Auto-detect | Physical speaker ID |

## Project Structure

```
trapy/
├── app.py                    # Main application entry
├── config.py                 # Configuration & environment
├── hardware.py               # Virtual device management
├── device_utils.py           # Audio device discovery
├── audio.py                  # Audio I/O streams
├── vad.py                    # Voice Activity Detection
├── client.py                 # OpenAI API integration
├── flow.py                   # Translation pipeline orchestration
├── ptt_controller.py         # Push-to-talk input handlers
├── manage_virtual_devices.zsh # Device management script
├── start_translator.zsh      # Automated startup script
├── requirements.txt          # Python dependencies
├── .env.example              # Environment template
└── README.md                 # This file
```

### Module Overview

- **config.py**: Loads and validates configuration from environment
- **hardware.py**: Creates/destroys virtual PulseAudio sinks and sources
- **device_utils.py**: Discovers and selects physical audio devices
- **audio.py**: Handles sounddevice and PulseAudio I/O streams
- **vad.py**: WebRTC-based phrase boundary detection
- **client.py**: Whisper (STT) → GPT (translation) → TTS pipeline
- **flow.py**: Manages bidirectional audio flows with playback
- **ptt_controller.py**: Keyboard and mouse input handlers with VAD integration

## How It Works

### Translation Pipeline

1. **Capture**: Audio from physical mic or virtual sink
2. **VAD**: Detect speech with WebRTC VAD (phrase boundaries)
3. **STT**: Convert audio → text with Whisper
4. **Translate**: Convert text with GPT-3.5-turbo
5. **TTS**: Convert text → audio with GPT-4o-mini-TTS
6. **Playback**: Output synthesized audio to speaker or virtual sink

### Virtual Audio Routing

- **Mic_Virtual**: Null sink for capturing English (EN→ES translation)
- **Mic_Virtual_Input**: Remapped source for browser audio selection
- **Altavoz_Virtual**: Null sink for capturing incoming audio (ES→EN translation)

## Troubleshooting

### No keyboard device detected

```bash
python -c "from evdev import list_devices; print(list(list_devices()))"
```

Pick the correct event device and check logs for details.

### Virtual devices not appearing in sounddevice

Some PipeWire systems don't expose virtual monitors. Use PulseAudio fallback (`pacat`/`parec`) automatically via:

```bash
./manage_virtual_devices.zsh up
```

### Audio latency

- Increase `AUDIO_CHUNK_MS` in `.env` for latency tolerance
- Check OpenAI API response times in logs
- Verify network connectivity

### API quota exceeded

Monitor your OpenAI usage. Large batches of translation consume tokens quickly.

## Development

### Running Tests

```bash
# Check for syntax errors
python -m py_compile *.py

# Validate imports
python -c "import app; import config; import hardware"
```

### Adding New Input Methods

1. Create class in `ptt_controller.py` implementing push-to-talk interface
2. Register in `app.py` under `BidiTranslatorApp.start()`
3. Update `TRANSLATION_MODE` in documentation

### Extending Translation Logic

Modify `client.py` to:
- Use different STT models (Whisper vs GPT-4o Audio)
- Change translation models (GPT-4 for complex text)
- Add language pairs beyond ES/EN

## Performance Notes

- **Hardware**: 2-3ms audio latency (network-bound)
- **STT**: ~1-2 seconds per segment (Whisper-1 is faster)
- **Translation**: ~0.5 seconds (gpt-3.5-turbo)
- **TTS**: ~1 second (gpt-4o-mini-tts)
- **Total**: 3-6 seconds per translation cycle

## License

MIT License - See LICENSE file for details

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Submit a pull request with clear commit messages

## Support

For issues, questions, or feature requests:
- Check the [GitHub Issues](https://github.com/yourusername/trapy/issues)
- Review logs: `tail -f debug.log` (if enabled)
- Test with a minimal `.env` configuration

---

**Built with**: Python 3.10+, OpenAI APIs, sounddevice, evdev, PulseAudio
como dispositivos separados. Si `python devices.py` muestra IDs virtuales en `None` pero en
"Estado en pactl" aparece `True`, los dispositivos virtuales sí están creados correctamente.
En ese caso, `app.py` ahora usa fallback automático por Pulse (`pacat` para salida y `parec`
para entrada del monitor virtual).

## Mapear dispositivos de audio

Para inspeccionar IDs y nombres de dispositivos:

```bash
python -c "import sounddevice as sd; print(sd.query_devices())"
```

También puedes usar el helper incluido:

```bash
python devices.py
```

Opcionalmente con nombres personalizados de sinks:

```bash
python devices.py --mic-virtual Mic_Virtual --altavoz-virtual Altavoz_Virtual
```

Si necesitas fijar dispositivos físicos concretos, usa en `.env`:

- `PHYSICAL_MIC_INPUT_DEVICE=<id>`
- `PHYSICAL_SPEAKER_OUTPUT_DEVICE=<id>`

Por defecto ambos van en `None` (dispositivo del sistema).

Para nombre personalizado del mic virtual visible en navegador:

- `MIC_VIRTUAL_SOURCE=Mic_Virtual_Input`

Luego ejecuta:

```bash
./manage_virtual_devices.zsh restart
```

Y selecciona `Mic_Virtual_Input` en Brave (`brave://settings/content/microphone`).

## Modo por segmentos (recomendado para push-to-talk)

La app captura audio mientras mantienes pulsada una tecla/botón y al soltar ejecuta:

1. STT (transcripción)
2. Traducción de texto
3. TTS (audio traducido)

Configuración aplicada por defecto (sin opciones manuales):

- Voz fija `ash` (perfil masculino joven).
- VAD adaptativo siempre activo: la app ajusta automáticamente `threshold/prefix/silence`
	durante la llamada para reducir latencia sin recortar palabras.
- `AUDIO_CHUNK_MS=10` se mantiene para streaming continuo en trozos pequeños.

Modo de traducción seleccionable por entorno:

- `TRANSLATION_MODE=turn`: legado Realtime.
- `TRANSLATION_MODE=simultaneous`: legado Realtime.
- `TRANSLATION_MODE=mouse_hold`: segmentación manual por botón del ratón.
	- Mantén click izquierdo: captura ES->EN. Al soltar, traduce y envía al mic virtual.
	- Mantén botón central (rueda): captura EN->ES. Al soltar, traduce y reproduce por altavoces.
	- En este modo no se usa corte automático por frases/VAD.
- `TRANSLATION_MODE=keyboard_hold`: segmentación manual por teclado global.
	- Mantén `OUTGOING_PTT_KEYS` (default `f8`): captura ES->EN; al soltar traduce al mic virtual.
	- Mantén `INCOMING_PTT_KEYS` (default `f9`): captura EN->ES; al soltar traduce a altavoces.
	- Soporta combinación, por ejemplo: `ctrl_r+f8` y `ctrl_r+f9`.

En `keyboard_hold` y `mouse_hold`, no se usa WebSocket Realtime para el tramo de traducción;
se usa pipeline HTTP por segmento para mayor estabilidad en push-to-talk.
