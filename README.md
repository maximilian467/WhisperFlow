# WhisperFlow 🎙️

Lokale **Speech-to-Text per Tastenkombination** für **Windows und Linux** — komplett offline, 0 € Kosten, keine Cloud, keine Anmeldung.

Hotkey drücken → sprechen → Hotkey erneut drücken → der erkannte Text wird **direkt an deiner Cursorposition eingefügt** (egal ob Word, Browser, Chat, Code-Editor …).

Basiert auf [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (OpenAI Whisper, lokal auf der CPU).

---

## Projektstruktur

```
WhisperFlow/
├── config.json              Einstellungen (für beide Systeme)
├── requirements.txt         Python-Pakete (plattformabhängig markiert)
├── whisperflow/             Programmcode
│   ├── app.py               Aufnahme, Transkription, Ablaufsteuerung
│   ├── hotkey.py            Hotkey-Parser und Tastenerkennung
│   ├── platform_windows.py  Windows: RegisterHotKey, Einfügen, Pieptöne
│   └── platform_linux.py    Linux: evdev/pynput, xdotool/wtype, Töne
├── windows/                 install.bat, start.bat, Autostart
└── linux/                   install.sh, start.sh, Autostart
```

Das Log landet in `whisperflow.log` im Projektordner — praktisch, wenn WhisperFlow im Hintergrund läuft.

---

## Windows

### Installation (einmalig)
1. Doppelklick auf **`windows\install.bat`** → erstellt die Python-Umgebung und lädt alle Pakete.
2. Doppelklick auf **`windows\start.bat`** → beim **allerersten Start** wird das Sprachmodell heruntergeladen (~500 MB für `small`). Danach läuft alles offline.

### Automatisch mit Windows starten (optional)
- Aktivieren: **`windows\install-autostart.bat`** → startet unsichtbar im Hintergrund (nur Pieptöne als Feedback).
- Deaktivieren: **`windows\install-autostart-entfernen.bat`**

> Wer den Autostart schon mit der alten Version eingerichtet hatte: `windows\install-autostart.bat` einmal neu ausführen, damit die Verknüpfung auf den neuen Ordner zeigt.

---

## Linux

Unterstützt X11 und Wayland (GNOME, KDE, wlroots-Compositors wie Sway/Hyprland).

### Installation (einmalig)
```bash
chmod +x linux/*.sh
./linux/install.sh
```
Das Skript
- installiert (nach Rückfrage, per `sudo`) Python-venv, Compiler, PortAudio sowie `xclip`/`xdotool` (X11) bzw. `wl-clipboard`/`wtype` (Wayland) — für apt, dnf, pacman und zypper,
- legt die Python-Umgebung `venv/` an,
- fragt unter **Wayland**, ob dein Benutzer in die Gruppe `input` darf (nötig für globale Hotkeys) und gibt `/dev/uinput` frei. Danach **einmal ab- und wieder anmelden**.

### Starten
```bash
./linux/start.sh
```

### Autostart (optional)
- Aktivieren: `./linux/install-autostart.sh` (XDG-Autostart, läuft nach dem Anmelden im Hintergrund)
- Deaktivieren: `./linux/uninstall-autostart.sh`

### Wie Linux Hotkeys und Einfügen umsetzt
| | X11 | Wayland |
|---|---|---|
| Hotkey | `pynput` (keine Rechte nötig) | `evdev` über `/dev/input` (Gruppe `input`) |
| Einfügen | `xdotool` (sonst `pynput`) | `wtype` → `/dev/uinput` → `ydotool` |
| Zwischenablage | `xclip` / `xsel` | `wl-clipboard` |

Wenn gar kein Tastensender verfügbar ist, landet der Text in der Zwischenablage und du fügst ihn selbst mit `Strg+V` ein.

Hinweis zu `evdev`: Buchstaben beziehen sich auf die **physische Taste im US-Layout** — bei deutschem Layout sind `y` und `z` vertauscht.

---

## Benutzung

1. WhisperFlow starten (Konsolenfenster/Terminal zeigt den Status).
2. Cursor dort platzieren, wo der Text hin soll.
3. **`Strg + Alt + W`** drücken → es piept hoch → **sprechen**.
4. **`Strg + Alt + W`** erneut drücken → es piept runter → kurz warten → Text erscheint.

Beenden: `Strg + C` im Konsolenfenster oder Fenster schließen. Es kann immer nur eine Instanz gleichzeitig laufen.

---

## Einstellungen — `config.json`

Datei mit einem Texteditor öffnen und Werte anpassen (danach Programm neu starten):

| Einstellung | Bedeutung | Werte |
|---|---|---|
| `hotkey` | Tastenkombination | z. B. `ctrl+alt+w`, `f9`, `ctrl+shift+space` |
| `mode` | Aufnahmemodus | `toggle` (drücken/drücken) oder `push_to_talk` (gedrückt halten) |
| `model` | Genauigkeit vs. Tempo | `tiny`, `base`, `small`, `medium`, `large-v3` |
| `language` | Sprache | `de`, `en`, … oder `auto` |
| `compute_type` | Rechenpräzision | `int8` (schnell), `int8_float32`, `float32` |
| `paste_method` | Einfügeart | `clipboard` (Strg+V) oder `type` (tippen) |
| `paste_keys` | Tasten zum Einfügen | `ctrl+v` (Standard), `ctrl+shift+v` für Linux-Terminals |
| `add_trailing_space` | Leerzeichen anhängen | `true` / `false` |
| `sounds` | Pieptöne | `true` / `false` |
| `initial_prompt` | Kontext/Fachbegriffe vorgeben | z. B. `"Fachbegriffe: Kubernetes, Anthropic"` |
| `linux_backend` | Hotkey-Erkennung unter Linux | `auto`, `evdev`, `pynput` |

### Welches Modell?
Ohne NVIDIA-GPU läuft alles auf der CPU. Empfehlung:
- **`small`** (Standard) — guter Kompromiss, ~1–3 s pro Satz, gutes Deutsch.
- **`base`** — schneller, etwas ungenauer.
- **`medium`** — genauer, aber spürbar langsamer auf der CPU.

`push_to_talk` funktioniert mit einzelnen Tasten (`f9`) und mit Kombinationen (`ctrl+alt+w`) — die Aufnahme endet, sobald die Haupttaste losgelassen wird.

---

## Warum nicht `Win + W`?

`Win + W` ist in Windows 11 fest für das **Widgets-Panel** reserviert. Windows lässt Programme diese Kombination nicht registrieren; WhisperFlow weicht dann auf einen Tastatur-Hook aus, der weniger robust ist, und das Widgets-Fenster poppt trotzdem auf. Deshalb ist der Standard `Strg + Alt + W`.

**Wenn du `Win + W` unbedingt willst**, schalte zuerst die Widgets ab (*Einstellungen → Personalisierung → Taskleiste → „Widgets" ausschalten*) und setze `"hotkey": "windows+w"`. Unkomplizierter sind freie Kombinationen wie `ctrl+alt+space` oder `f9`.

---

## Problembehebung

- **Hotkey reagiert nach einiger Zeit nicht mehr:** In älteren Versionen lief der Hotkey über einen Low-Level-Tastatur-Hook. Den entfernt Windows stillschweigend, wenn er unter CPU-Last (Transkription!) zu langsam antwortet. Außerdem brachten verpasste Tasten-Loslass-Events (Sperrbildschirm `Win+L`, `Strg+Alt+Entf`, UAC, Standby) die Erkennung dauerhaft durcheinander. Ein Klick ins Konsolenfenster (QuickEdit) hat das Programm zusätzlich eingefroren. Seit Version 2 nutzt WhisperFlow `RegisterHotKey`, fragt den echten Tastenzustand ab und schaltet QuickEdit ab. Tritt es trotzdem auf: `whisperflow.log` ansehen.
- **„Hotkey ist bereits belegt":** Ein anderes Programm nutzt die Kombination → anderen Hotkey wählen.
- **„WhisperFlow läuft bereits":** Es läuft schon eine Instanz (z. B. über den Autostart).
- **Text wird nicht eingefügt, aber im Log steht er:** Manche Programme laufen als Administrator (z. B. Task-Manager). Dann kann ein normales Programm keine Tasten senden → WhisperFlow ebenfalls als Admin starten, oder `paste_method` auf `type` stellen.
- **„Mikrofon konnte nicht geöffnet werden":** Prüfen, dass ein Standard-Eingabegerät gesetzt ist. Nach Standby oder Headset-Wechsel initialisiert WhisperFlow das Audio automatisch neu.
- **Linux: „Keine lesbare Tastatur unter /dev/input":** `sudo usermod -aG input $USER`, neu anmelden — oder unter X11 `"linux_backend": "pynput"`.
- **Linux-Terminal fügt nichts ein:** `"paste_keys": "ctrl+shift+v"` setzen.
- **Sehr langsam:** Kleineres Modell wählen (`base` oder `tiny`).
- **Falsche Sprache erkannt:** `language` fest auf `de` stellen (statt `auto`).
- **Umlaute kaputt:** `paste_method` auf `clipboard` lassen (Standard).

---

## Wie es funktioniert

```
Hotkey → Mikrofon-Aufnahme (sounddevice, 16 kHz)
       → Whisper-Transkription (faster-whisper, lokal/CPU)
       → Text in Zwischenablage + Strg+V an Cursorposition
```

Alles passiert auf deinem Rechner. Es werden **keine Daten ins Internet gesendet** (außer dem einmaligen Modell-Download bei der ersten Nutzung).
