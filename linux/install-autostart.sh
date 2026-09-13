#!/usr/bin/env bash
# Legt einen XDG-Autostart-Eintrag an (GNOME, KDE, XFCE, Cinnamon, ...).
set -euo pipefail
DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
AUTOSTART="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
mkdir -p "$AUTOSTART"

cat > "$AUTOSTART/whisperflow.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=WhisperFlow
Comment=Lokale Speech-to-Text per Hotkey
Exec="$DIR/linux/start.sh" --background
Terminal=false
X-GNOME-Autostart-enabled=true
EOF

echo "[OK] WhisperFlow startet ab jetzt automatisch nach dem Anmelden."
echo "     Entfernen: linux/uninstall-autostart.sh"
