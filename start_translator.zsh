#!/usr/bin/env zsh

set -euo pipefail

ROOT_DIR="${0:A:h}"

if [[ ! -x "${ROOT_DIR}/manage_virtual_devices.zsh" ]]; then
  echo "[ERROR] No existe script ejecutable: ${ROOT_DIR}/manage_virtual_devices.zsh" >&2
  exit 1
fi

echo "[INFO] Verificando/levantando dispositivos virtuales..."
"${ROOT_DIR}/manage_virtual_devices.zsh" up

echo "[INFO] Iniciando traductor en tiempo real..."
exec python3 "${ROOT_DIR}/app.py"