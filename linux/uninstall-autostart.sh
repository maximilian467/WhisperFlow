#!/usr/bin/env bash
FILE="${XDG_CONFIG_HOME:-$HOME/.config}/autostart/whisperflow.desktop"
if [[ -f "$FILE" ]]; then
    rm "$FILE"
    echo "[OK] Autostart entfernt."
else
    echo "Kein Autostart-Eintrag gefunden."
fi
