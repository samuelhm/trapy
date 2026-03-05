#!/usr/bin/env zsh

set -euo pipefail

ROOT_DIR="${0:A:h}"
ENV_FILE="${ROOT_DIR}/.env"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  source "${ENV_FILE}"
  set +a
fi

MIC_VIRTUAL_SINK="${MIC_VIRTUAL_SINK:-Mic_Virtual}"
MIC_VIRTUAL_SOURCE="${MIC_VIRTUAL_SOURCE:-Mic_Virtual_Input}"
ALTAVOZ_VIRTUAL_SINK="${ALTAVOZ_VIRTUAL_SINK:-Altavoz_Virtual}"

ensure_pactl() {
  if ! command -v pactl >/dev/null 2>&1; then
    echo "[ERROR] 'pactl' no está disponible. Instala PulseAudio/PipeWire con compatibilidad pactl." >&2
    exit 1
  fi
}

sink_exists() {
  local sink_name="$1"
  pactl list short sinks | awk -F'\t' '{print $2}' | grep -Fxq "${sink_name}"
}

source_exists() {
  local source_name="$1"
  pactl list short sources | awk -F'\t' '{print $2}' | grep -Fxq "${source_name}"
}

create_sink_if_missing() {
  local sink_name="$1"
  if sink_exists "${sink_name}"; then
    echo "[INFO] Sink '${sink_name}' ya existe."
    return
  fi

  local module_id
  module_id="$(pactl load-module module-null-sink "sink_name=${sink_name}" "sink_properties=device.description=${sink_name}")"
  echo "[OK] Sink '${sink_name}' creado (module id: ${module_id})."
}

create_remap_source_if_missing() {
  local source_name="$1"
  local master_source="$2"

  if source_exists "${source_name}"; then
    echo "[INFO] Source '${source_name}' ya existe."
    return
  fi

  local module_id
  module_id="$(pactl load-module module-remap-source "source_name=${source_name}" "master=${master_source}" channels=1 "source_properties=device.description=${source_name}")"
  echo "[OK] Source '${source_name}' creado desde '${master_source}' (module id: ${module_id})."
}

list_null_sink_modules_for() {
  local sink_name="$1"
  pactl list short modules \
    | grep "module-null-sink" \
    | grep "sink_name=${sink_name}" \
    | awk '{print $1}'
}

list_remap_source_modules_for() {
  local source_name="$1"
  pactl list short modules \
    | grep "module-remap-source" \
    | grep "source_name=${source_name}" \
    | awk '{print $1}'
}

remove_sink_modules() {
  local sink_name="$1"
  local module_ids
  module_ids="$(list_null_sink_modules_for "${sink_name}" || true)"

  if [[ -z "${module_ids}" ]]; then
    echo "[INFO] No hay módulos cargados para '${sink_name}'."
    return
  fi

  local module_id
  while read -r module_id; do
    [[ -z "${module_id}" ]] && continue
    pactl unload-module "${module_id}"
    echo "[OK] Módulo ${module_id} descargado para '${sink_name}'."
  done <<< "${module_ids}"
}

remove_source_modules() {
  local source_name="$1"
  local module_ids
  module_ids="$(list_remap_source_modules_for "${source_name}" || true)"

  if [[ -z "${module_ids}" ]]; then
    echo "[INFO] No hay módulos cargados para source '${source_name}'."
    return
  fi

  local module_id
  while read -r module_id; do
    [[ -z "${module_id}" ]] && continue
    pactl unload-module "${module_id}"
    echo "[OK] Módulo ${module_id} descargado para source '${source_name}'."
  done <<< "${module_ids}"
}

status_sink() {
  local sink_name="$1"
  if sink_exists "${sink_name}"; then
    echo "[UP]   ${sink_name}"
  else
    echo "[DOWN] ${sink_name}"
  fi
}

status_source() {
  local source_name="$1"
  if source_exists "${source_name}"; then
    echo "[UP]   ${source_name}"
  else
    echo "[DOWN] ${source_name}"
  fi
}

usage() {
  echo "Uso: $0 {up|down|restart|status}"
}

main() {
  ensure_pactl

  local action="${1:-up}"
  case "${action}" in
    up)
      create_sink_if_missing "${MIC_VIRTUAL_SINK}"
      create_sink_if_missing "${ALTAVOZ_VIRTUAL_SINK}"
      create_remap_source_if_missing "${MIC_VIRTUAL_SOURCE}" "${MIC_VIRTUAL_SINK}.monitor"
      ;;
    down)
      remove_source_modules "${MIC_VIRTUAL_SOURCE}"
      remove_sink_modules "${MIC_VIRTUAL_SINK}"
      remove_sink_modules "${ALTAVOZ_VIRTUAL_SINK}"
      ;;
    restart)
      remove_source_modules "${MIC_VIRTUAL_SOURCE}"
      remove_sink_modules "${MIC_VIRTUAL_SINK}"
      remove_sink_modules "${ALTAVOZ_VIRTUAL_SINK}"
      create_sink_if_missing "${MIC_VIRTUAL_SINK}"
      create_sink_if_missing "${ALTAVOZ_VIRTUAL_SINK}"
      create_remap_source_if_missing "${MIC_VIRTUAL_SOURCE}" "${MIC_VIRTUAL_SINK}.monitor"
      ;;
    status)
      status_sink "${MIC_VIRTUAL_SINK}"
      status_sink "${ALTAVOZ_VIRTUAL_SINK}"
      status_source "${MIC_VIRTUAL_SOURCE}"
      ;;
    *)
      usage
      exit 1
      ;;
  esac
}

main "$@"