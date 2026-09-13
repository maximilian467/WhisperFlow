#!/usr/bin/env bash
# WhisperFlow - Installation (Linux)
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."

ask() {  # ask "Frage" -> 0 bei Ja (Standard), 1 bei Nein
    local answer
    read -r -p "$1 [J/n] " answer || answer="n"
    [[ -z "$answer" || "$answer" =~ ^[JjYy] ]]
}

echo "============================================================"
echo " WhisperFlow - Installation (Linux)"
echo "============================================================"
echo

# --- 1) Systempakete ---------------------------------------------------------
# Pflicht: Python-venv, Compiler (fuer evdev), PortAudio
# Optional: Zwischenablage (xclip / wl-clipboard) und Tastensender (xdotool / wtype)
if command -v apt-get >/dev/null; then
    CORE="python3-venv python3-dev gcc libportaudio2"
    OPTIONAL="xclip xdotool wl-clipboard wtype"
    install_cmd() { sudo apt-get install -y "$@"; }
    update_cmd() { sudo apt-get update; }
elif command -v dnf >/dev/null; then
    CORE="python3-devel gcc portaudio"
    OPTIONAL="xclip xdotool wl-clipboard wtype"
    install_cmd() { sudo dnf install -y "$@"; }
    update_cmd() { :; }
elif command -v pacman >/dev/null; then
    CORE="python gcc portaudio"
    OPTIONAL="xclip xdotool wl-clipboard wtype"
    install_cmd() { sudo pacman -S --needed --noconfirm "$@"; }
    update_cmd() { :; }
elif command -v zypper >/dev/null; then
    CORE="python3-devel gcc portaudio"
    OPTIONAL="xclip xdotool wl-clipboard wtype"
    install_cmd() { sudo zypper install -y "$@"; }
    update_cmd() { :; }
else
    CORE=""
fi

echo "[1/4] Systempakete"
if [[ -n "$CORE" ]]; then
    echo "      Benoetigt: $CORE"
    echo "      Optional:  $OPTIONAL"
    if ask "      Jetzt mit sudo installieren?"; then
        update_cmd
        install_cmd $CORE
        for pkg in $OPTIONAL; do
            install_cmd "$pkg" || echo "      [Hinweis] $pkg nicht verfuegbar - uebersprungen."
        done
    fi
else
    echo "      Unbekannte Distribution. Bitte selbst installieren:"
    echo "      Python 3 (inkl. venv + Header), gcc, PortAudio, xclip/xdotool (X11) bzw. wl-clipboard/wtype (Wayland)"
fi

# --- 2) Python-Umgebung ------------------------------------------------------
echo
echo "[2/4] Erstelle virtuelle Python-Umgebung (venv) ..."
python3 -m venv venv

echo "[3/4] Installiere Abhaengigkeiten (dauert beim ersten Mal etwas) ..."
venv/bin/python -m pip install --upgrade pip
venv/bin/python -m pip install -r requirements.txt

# --- 3) Rechte fuer Wayland --------------------------------------------------
echo
echo "[4/4] Tastatur-Zugriff"
SESSION="${XDG_SESSION_TYPE:-}"
if [[ "$SESSION" == "wayland" ]]; then
    echo "      Du nutzt Wayland. Globale Hotkeys gehen dort nur ueber /dev/input"
    echo "      (Gruppe 'input'), das Einfuegen ohne wtype ueber /dev/uinput."
    if ! id -nG "$USER" | grep -qw input; then
        if ask "      Benutzer '$USER' zur Gruppe 'input' hinzufuegen und uinput freigeben?"; then
            sudo usermod -aG input "$USER"
            echo 'KERNEL=="uinput", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"' \
                | sudo tee /etc/udev/rules/99-whisperflow-uinput.rules >/dev/null
            echo uinput | sudo tee /etc/modules-load.d/whisperflow-uinput.conf >/dev/null
            sudo modprobe uinput || true
            sudo udevadm trigger || true
            echo "      [OK] Bitte einmal ab- und wieder anmelden, damit die Gruppe aktiv wird."
        fi
    else
        echo "      [OK] Benutzer ist bereits in der Gruppe 'input'."
    fi
else
    echo "      X11 erkannt - keine besonderen Rechte noetig."
fi

echo
echo "============================================================"
echo " Fertig! Starte WhisperFlow mit:  linux/start.sh"
echo "============================================================"
