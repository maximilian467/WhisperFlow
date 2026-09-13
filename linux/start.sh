#!/usr/bin/env bash
# Startet WhisperFlow. Mit --background ohne Terminal (fuer den Autostart);
# Ausgaben landen dann in whisperflow.log im Projektordner.
cd "$(dirname "$(readlink -f "$0")")/.." || exit 1

if [[ ! -x venv/bin/python ]]; then
    echo "[FEHLER] Keine Python-Umgebung gefunden. Bitte zuerst linux/install.sh ausfuehren."
    exit 1
fi

if [[ "${1:-}" == "--background" ]]; then
    nohup venv/bin/python -m whisperflow >/dev/null 2>&1 &
    exit 0
fi

exec venv/bin/python -m whisperflow
