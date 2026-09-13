# -*- coding: utf-8 -*-
"""Linux (X11 + Wayland): Hotkey ueber evdev oder pynput, Einfuegen ueber
Zwischenablage + xdotool / wtype / uinput / ydotool."""

import os
import time
import select
import shutil
import fcntl
import logging
import threading
import subprocess

import numpy as np
import pyperclip

from .hotkey import HotkeyMatcher, parse_hotkey

log = logging.getLogger("whisperflow")

_lock_file = None


def session_type():
    kind = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if kind in ("x11", "wayland"):
        return kind
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "tty"


def acquire_single_instance():
    global _lock_file
    runtime = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    path = os.path.join(runtime, f"whisperflow-{os.getuid()}.lock")
    _lock_file = open(path, "w")
    try:
        fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def prepare_console():
    pass


# ---------------------------------------------------------------------------
# Hotkey
# ---------------------------------------------------------------------------
def create_hotkey_listener(cfg, hotkey, on_down, on_up):
    backend = cfg.get("linux_backend", "auto")
    session = session_type()
    if backend == "auto":
        backend = "pynput" if session == "x11" else "evdev"
    log.info(" Sitzung:   %s (Hotkey-Backend: %s)", session, backend)
    if backend == "pynput":
        return PynputHotkeyListener(hotkey, on_down, on_up)
    if backend == "evdev":
        return EvdevHotkeyListener(hotkey, on_down, on_up)
    raise ValueError(f"Unbekanntes linux_backend: {backend!r}")


EVDEV_NAMES = {
    "leftctrl": "ctrl", "rightctrl": "ctrl",
    "leftalt": "alt", "rightalt": "alt",
    "leftshift": "shift", "rightshift": "shift",
    "leftmeta": "super", "rightmeta": "super",
    "esc": "escape", "pageup": "page_up", "pagedown": "page_down",
    "sysrq": "print_screen", "scrolllock": "scroll_lock",
}


class EvdevHotkeyListener:
    """Liest die Tastaturen direkt ueber /dev/input. Funktioniert unter X11 und
    Wayland, braucht aber Mitgliedschaft in der Gruppe 'input'.
    Tastaturen, die (z. B. nach Standby oder USB-Wechsel) neu auftauchen, werden
    automatisch wieder eingebunden."""

    def __init__(self, hotkey, on_down, on_up):
        import evdev
        self._evdev = evdev
        self._devices = {}
        self._stop = False
        self._thread = None
        self._matcher = HotkeyMatcher(hotkey, on_down, on_up, query_modifiers=self._query_modifiers)
        key_name = "KEY_" + {v: k for k, v in EVDEV_NAMES.items()}.get(hotkey.key, hotkey.key).upper()
        self._key_code = evdev.ecodes.ecodes.get(key_name)
        if self._key_code is None:
            raise ValueError(f"Unbekannte Taste im Hotkey: {hotkey.key!r}")

    def _name(self, code):
        name = self._evdev.ecodes.KEY.get(code)
        if isinstance(name, (list, tuple)):
            name = name[0]
        if not name:
            return None
        name = name[4:].lower() if name.startswith("KEY_") else name.lower()
        return EVDEV_NAMES.get(name, name)

    def _scan(self):
        for path in self._evdev.list_devices():
            if path in self._devices:
                continue
            try:
                dev = self._evdev.InputDevice(path)
            except OSError:
                continue
            keys = dev.capabilities().get(self._evdev.ecodes.EV_KEY, [])
            if self._key_code in keys and self._evdev.ecodes.KEY_A in keys:
                self._devices[path] = dev
                log.info(" Tastatur:  %s", dev.name)
            else:
                dev.close()

    def _drop(self, dev):
        self._devices.pop(dev.path, None)
        try:
            dev.close()
        except Exception:
            pass

    def _query_modifiers(self):
        mods = set()
        for dev in list(self._devices.values()):
            try:
                for code in dev.active_keys():
                    name = self._name(code)
                    if name in ("ctrl", "alt", "shift", "super"):
                        mods.add(name)
            except OSError:
                pass
        return mods

    def start(self):
        self._scan()
        if not self._devices:
            raise RuntimeError(
                "Keine lesbare Tastatur unter /dev/input gefunden. Fuege deinen Benutzer der "
                "Gruppe 'input' hinzu (sudo usermod -aG input $USER), melde dich neu an - "
                "oder setze unter X11 \"linux_backend\": \"pynput\" in config.json.")
        self._thread = threading.Thread(target=self._run, name="hotkey", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop = True

    def _run(self):
        ecodes = self._evdev.ecodes
        last_scan = time.monotonic()
        while not self._stop:
            devices = list(self._devices.values())
            try:
                readable, _, _ = select.select(devices, [], [], 2.0)
            except (OSError, ValueError):
                readable = []
                for dev in devices:
                    try:
                        os.fstat(dev.fd)
                    except OSError:
                        self._drop(dev)
            for dev in readable:
                try:
                    for ev in dev.read():
                        if ev.type == ecodes.EV_KEY and ev.value in (0, 1):
                            name = self._name(ev.code)
                            if name:
                                self._matcher.key_event(name, ev.value == 1)
                except OSError:
                    log.info("[..] Tastatur getrennt: %s", dev.name)
                    self._drop(dev)
                except Exception:
                    log.exception("[ERR] Fehler bei der Tastenverarbeitung")
            if time.monotonic() - last_scan > 3:
                self._scan()
                last_scan = time.monotonic()


PYNPUT_NAMES = {
    "ctrl_l": "ctrl", "ctrl_r": "ctrl",
    "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt",
    "shift_l": "shift", "shift_r": "shift",
    "cmd": "super", "cmd_l": "super", "cmd_r": "super",
    "esc": "escape",
}

X11_MODIFIER_KEYSYMS = {
    "ctrl": ("Control_L", "Control_R"),
    "alt": ("Alt_L", "Alt_R", "ISO_Level3_Shift"),
    "shift": ("Shift_L", "Shift_R"),
    "super": ("Super_L", "Super_R"),
}


class PynputHotkeyListener:
    """X11 ohne besondere Rechte. Stirbt der Listener (z. B. X-Verbindung weg),
    wird er automatisch neu gestartet."""

    def __init__(self, hotkey, on_down, on_up):
        from pynput import keyboard
        self._pk = keyboard
        self._listener = None
        self._stop = False
        self._x_lock = threading.Lock()
        self._display, self._mod_codes = self._open_display()
        query = self._query_modifiers if self._display is not None else None
        self._matcher = HotkeyMatcher(hotkey, on_down, on_up, query_modifiers=query,
                                      release_delay=0.06)

    def _open_display(self):
        try:
            from Xlib import XK, display
            d = display.Display()
            codes = {name: [d.keysym_to_keycode(XK.string_to_keysym(s)) for s in syms]
                     for name, syms in X11_MODIFIER_KEYSYMS.items()}
            return d, codes
        except Exception as e:
            log.debug("Xlib nicht verfuegbar: %s", e)
            return None, {}

    def _query_modifiers(self):
        with self._x_lock:
            keymap = self._display.query_keymap()
        return {name for name, codes in self._mod_codes.items()
                if any(c and keymap[c // 8] & (1 << (c % 8)) for c in codes)}

    def _name(self, key):
        if isinstance(key, self._pk.Key):
            return PYNPUT_NAMES.get(key.name, key.name)
        char = getattr(key, "char", None)
        return char.lower() if char else None

    def _handler(self, is_down):
        def handle(key):
            try:
                name = self._name(key)
                if name:
                    self._matcher.key_event(name, is_down)
            except Exception:
                log.exception("[ERR] Fehler bei der Tastenverarbeitung")
        return handle

    def _spawn(self):
        self._listener = self._pk.Listener(on_press=self._handler(True), on_release=self._handler(False))
        self._listener.start()
        self._listener.wait()

    def start(self):
        self._spawn()
        threading.Thread(target=self._watchdog, name="hotkey-watchdog", daemon=True).start()

    def stop(self):
        self._stop = True
        if self._listener is not None:
            self._listener.stop()

    def _watchdog(self):
        while not self._stop:
            time.sleep(5)
            if not self._stop and not self._listener.is_alive():
                log.warning("[WARN] Tastatur-Listener beendet - starte neu ...")
                try:
                    self._spawn()
                except Exception:
                    log.exception("[ERR] Neustart des Listeners fehlgeschlagen")


# ---------------------------------------------------------------------------
# Texteinfuegung
# ---------------------------------------------------------------------------
def _run(cmd, **kwargs):
    try:
        subprocess.run(cmd, check=True, timeout=10, stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE, **kwargs)
        return True
    except (OSError, subprocess.SubprocessError) as e:
        log.debug("%s fehlgeschlagen: %s", cmd[0], e)
        return False


class TextInserter:
    def __init__(self, cfg):
        self.cfg = cfg
        self.session = session_type()
        self.paste_keys = parse_hotkey(cfg.get("paste_keys", "ctrl+v"))
        self._uinput = None
        if self.session == "wayland" and not shutil.which("wtype"):
            self._uinput = self._open_uinput()
        if self.session == "wayland" and not (shutil.which("wtype") or self._uinput or shutil.which("ydotool")):
            log.warning("[WARN] Kein Werkzeug zum Senden von Tasten gefunden (wtype, /dev/uinput "
                        "oder ydotool). Text landet nur in der Zwischenablage.")

    def _open_uinput(self):
        try:
            from evdev import UInput
            ui = UInput(name="whisperflow-keyboard")
            time.sleep(0.3)  # Compositor muss das neue Geraet erst erkennen
            return ui
        except Exception as e:
            log.debug("uinput nicht nutzbar: %s", e)
            return None

    def insert(self, text):
        if not text:
            return
        if self.cfg.get("paste_method", "clipboard") == "type":
            if self._type(text):
                return
            log.warning("[WARN] Tippen nicht moeglich, nutze Zwischenablage.")

        try:
            old_clip = pyperclip.paste()
        except Exception:
            old_clip = None
        try:
            pyperclip.copy(text)
        except Exception as e:
            log.error("[ERR] Zwischenablage nicht nutzbar (xclip bzw. wl-clipboard installiert?): %s", e)
            return
        time.sleep(0.05)
        if not self._send_paste():
            log.warning("[WARN] Konnte Einfuegen nicht ausloesen - Text liegt in der Zwischenablage.")
            return
        time.sleep(0.2)
        if old_clip is not None:
            try:
                pyperclip.copy(old_clip)
            except Exception:
                pass

    def _type(self, text):
        if self.session == "x11":
            if shutil.which("xdotool"):
                return _run(["xdotool", "type", "--clearmodifiers", "--delay", "0", "--", text])
            try:
                from pynput.keyboard import Controller
                Controller().type(text)
                return True
            except Exception:
                return False
        if shutil.which("wtype"):
            return _run(["wtype", "--", text])
        if shutil.which("ydotool"):
            return _run(["ydotool", "type", "--", text])
        return False

    def _send_paste(self):
        mods, key = self.paste_keys.modifiers, self.paste_keys.key
        if self.session == "x11":
            if shutil.which("xdotool"):
                return _run(["xdotool", "key", "--clearmodifiers", "+".join(sorted(mods) + [key])])
            return self._pynput_keys(mods, key)
        if shutil.which("wtype"):
            cmd = ["wtype"]
            for m in mods:
                cmd += ["-M", m if m != "super" else "logo"]
            cmd += ["-k", key]
            for m in mods:
                cmd += ["-m", m if m != "super" else "logo"]
            return _run(cmd)
        if self._uinput is not None:
            return self._uinput_keys(mods, key)
        if shutil.which("ydotool"):
            codes = self._evdev_codes(mods, key)
            if codes:
                seq = [f"{c}:1" for c in codes] + [f"{c}:0" for c in reversed(codes)]
                return _run(["ydotool", "key"] + seq)
        return False

    @staticmethod
    def _evdev_codes(mods, key):
        try:
            from evdev import ecodes
        except ImportError:
            return None
        names = {"ctrl": "LEFTCTRL", "alt": "LEFTALT", "shift": "LEFTSHIFT", "super": "LEFTMETA"}
        codes = [ecodes.ecodes["KEY_" + names[m]] for m in sorted(mods)]
        code = ecodes.ecodes.get("KEY_" + key.upper())
        return codes + [code] if code is not None else None

    def _uinput_keys(self, mods, key):
        from evdev import ecodes
        codes = self._evdev_codes(mods, key)
        if not codes:
            return False
        for c in codes:
            self._uinput.write(ecodes.EV_KEY, c, 1)
        for c in reversed(codes):
            self._uinput.write(ecodes.EV_KEY, c, 0)
        self._uinput.syn()
        return True

    @staticmethod
    def _pynput_keys(mods, key):
        try:
            from pynput.keyboard import Controller, Key
            kb = Controller()
            pk_mods = [{"ctrl": Key.ctrl, "alt": Key.alt, "shift": Key.shift, "super": Key.cmd}[m] for m in mods]
            main = getattr(Key, key) if len(key) > 1 else key
            with kb.pressed(*pk_mods):
                kb.press(main)
                kb.release(main)
            return True
        except Exception as e:
            log.debug("pynput-Tastendruck fehlgeschlagen: %s", e)
            return False


# ---------------------------------------------------------------------------
# Toene
# ---------------------------------------------------------------------------
_TONES = {"start": (880, 0.12), "stop": (523, 0.12), "done": (1175, 0.08), "error": (300, 0.25)}


def beep(kind):
    if kind not in _TONES:
        return
    import sounddevice as sd
    freq, dur = _TONES[kind]
    rate = 44100
    t = np.arange(int(rate * dur)) / rate
    tone = 0.25 * np.sin(2 * np.pi * freq * t)
    fade = min(len(t) // 4, int(rate * 0.01))
    tone[:fade] *= np.linspace(0, 1, fade)
    tone[-fade:] *= np.linspace(1, 0, fade)
    sd.play(tone.astype(np.float32), rate)
