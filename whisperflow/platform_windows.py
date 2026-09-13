# -*- coding: utf-8 -*-
"""Windows: Hotkey ueber RegisterHotKey, Einfuegen ueber Zwischenablage/SendInput."""

import time
import ctypes
import logging
import threading
from ctypes import wintypes

import pyperclip

from .hotkey import HotkeyMatcher

log = logging.getLogger("whisperflow")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
user32.VkKeyScanW.restype = ctypes.c_short
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.GetStdHandle.restype = wintypes.HANDLE
kernel32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel32.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
MOD_FLAGS = {"alt": MOD_ALT, "ctrl": MOD_CONTROL, "shift": MOD_SHIFT, "super": MOD_WIN}
MOD_VKS = {"ctrl": (0x11,), "alt": (0x12,), "shift": (0x10,), "super": (0x5B, 0x5C)}
ERROR_ALREADY_EXISTS = 183
ERROR_HOTKEY_ALREADY_REGISTERED = 1409

NAMED_VKS = {
    "space": 0x20, "enter": 0x0D, "tab": 0x09, "escape": 0x1B, "backspace": 0x08,
    "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23,
    "page_up": 0x21, "page_down": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "pause": 0x13, "scroll_lock": 0x91, "print_screen": 0x2C,
}

HOTKEY_ID = 0x5746  # beliebig, "WF"
_mutex = None


def key_to_vk(key):
    if key in NAMED_VKS:
        return NAMED_VKS[key]
    if key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        return 0x70 + int(key[1:]) - 1
    if len(key) == 1:
        if "a" <= key <= "z" or "0" <= key <= "9":
            return ord(key.upper())
        res = user32.VkKeyScanW(key)  # Sonderzeichen gemaess Tastaturlayout
        if res != -1:
            return res & 0xFF
    raise ValueError(f"Unbekannte Taste im Hotkey: {key!r}")


def acquire_single_instance():
    global _mutex
    _mutex = kernel32.CreateMutexW(None, False, "Local\\WhisperFlow-SingleInstance")
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS


def prepare_console():
    """Schaltet den QuickEdit-Modus der Konsole ab. Sonst friert ein versehentlicher
    Klick ins Konsolenfenster jede Ausgabe (und damit das Programm) ein, bis man
    Enter/Esc drueckt."""
    handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
    mode = wintypes.DWORD()
    if handle and kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        ENABLE_QUICK_EDIT_MODE, ENABLE_EXTENDED_FLAGS = 0x0040, 0x0080
        kernel32.SetConsoleMode(handle, (mode.value & ~ENABLE_QUICK_EDIT_MODE) | ENABLE_EXTENDED_FLAGS)


def _is_down(vk):
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def _query_modifiers():
    return {name for name, vks in MOD_VKS.items() if any(_is_down(vk) for vk in vks)}


def create_hotkey_listener(cfg, hotkey, on_down, on_up):
    return WindowsHotkeyListener(hotkey, on_down, on_up)


class WindowsHotkeyListener:
    """Nutzt RegisterHotKey statt eines Low-Level-Keyboard-Hooks.

    Windows entfernt Low-Level-Hooks stillschweigend, wenn sie nicht schnell genug
    antworten (z. B. waehrend die CPU mit der Transkription ausgelastet ist).
    Registrierte Hotkeys laufen dagegen ueber normale Fenster-Nachrichten, werden
    nie entfernt und haben kein Problem mit "haengengebliebenen" Modifier-Tasten
    nach Sperrbildschirm oder Standby.
    """

    def __init__(self, hotkey, on_down, on_up):
        self.hotkey = hotkey
        self.on_down = on_down
        self.on_up = on_up
        self.vk = key_to_vk(hotkey.key)
        self.mods = sum(MOD_FLAGS[m] for m in hotkey.modifiers)
        self._thread = None
        self._thread_id = None
        self._ready = threading.Event()
        self._error = None
        self._fallback = None
        self._release_watch = False

    def start(self):
        self._thread = threading.Thread(target=self._run, name="hotkey", daemon=True)
        self._thread.start()
        self._ready.wait(5)
        if self._error is not None:
            log.warning("[WARN] %s", self._error)
            log.warning("[WARN] Weiche auf Keyboard-Hook aus (weniger robust). "
                        "Tipp: einen freien Hotkey wie ctrl+alt+space oder f9 waehlen.")
            self._fallback = KeyboardHookListener(self.hotkey, self.on_down, self.on_up)
            self._fallback.start()

    def stop(self):
        if self._fallback is not None:
            self._fallback.stop()
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)

    def _run(self):
        self._thread_id = kernel32.GetCurrentThreadId()
        if not user32.RegisterHotKey(None, HOTKEY_ID, self.mods | MOD_NOREPEAT, self.vk):
            err = ctypes.get_last_error()
            if err == ERROR_HOTKEY_ALREADY_REGISTERED:
                self._error = "Hotkey ist bereits von Windows oder einem anderen Programm belegt."
            else:
                self._error = f"RegisterHotKey fehlgeschlagen (Fehler {err})."
            self._ready.set()
            return
        self._ready.set()
        msg = wintypes.MSG()
        try:
            while True:
                res = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if res == 0 or res == -1:
                    break
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    self._on_hotkey()
        finally:
            user32.UnregisterHotKey(None, HOTKEY_ID)

    def _on_hotkey(self):
        self.on_down()
        if not self._release_watch:
            self._release_watch = True
            threading.Thread(target=self._watch_release, name="hotkey-release", daemon=True).start()

    def _watch_release(self):
        # WM_HOTKEY meldet nur das Druecken; Loslassen (fuer push_to_talk) per Abfrage
        try:
            while _is_down(self.vk):
                time.sleep(0.015)
        finally:
            self._release_watch = False
            self.on_up()


class KeyboardHookListener:
    """Fallback ueber die 'keyboard'-Bibliothek, z. B. fuer 'windows+w'.
    Der echte Modifier-Zustand wird jedes Mal bei Windows abgefragt."""

    def __init__(self, hotkey, on_down, on_up):
        import keyboard
        self._kb = keyboard
        self._hook = None
        self._names = {}  # Scancode -> normalisierter Name
        for name, kb_names in (("ctrl", ("ctrl",)), ("alt", ("alt",)), ("shift", ("shift",)),
                               ("super", ("left windows", "right windows"))):
            for kb_name in kb_names:
                for code in keyboard.key_to_scan_codes(kb_name, error_if_missing=False):
                    self._names[code] = name
        for code in keyboard.key_to_scan_codes(hotkey.key):
            self._names[code] = hotkey.key
        self._matcher = HotkeyMatcher(hotkey, on_down, on_up, query_modifiers=_query_modifiers)

    def _handle(self, event):
        try:
            name = self._names.get(event.scan_code)
            if name:
                self._matcher.key_event(name, event.event_type == self._kb.KEY_DOWN)
        except Exception:
            log.exception("[ERR] Fehler im Keyboard-Hook")

    def start(self):
        self._hook = self._kb.hook(self._handle)

    def stop(self):
        if self._hook is not None:
            self._kb.unhook(self._hook)


class TextInserter:
    def __init__(self, cfg):
        import keyboard
        self._kb = keyboard
        self.cfg = cfg

    def insert(self, text):
        if not text:
            return
        if self.cfg.get("paste_method", "clipboard") == "type":
            # Tippt den Text Zeichen fuer Zeichen. Funktioniert ueberall,
            # ist aber langsamer und kann bei Sonderlayouts haken.
            self._kb.write(text, delay=0.0)
            return

        # Standard: ueber die Zwischenablage + Strg+V (zuverlaessig fuer Umlaute)
        try:
            old_clip = pyperclip.paste()
        except Exception:
            old_clip = None
        pyperclip.copy(text)
        time.sleep(0.05)
        self._kb.send(self.cfg.get("paste_keys", "ctrl+v"))
        time.sleep(0.2)
        if old_clip is not None:
            try:
                pyperclip.copy(old_clip)
            except Exception:
                pass


def beep(kind):
    import winsound
    tones = {"start": (880, 120), "stop": (523, 120), "done": (1175, 80), "error": (300, 250)}
    if kind in tones:
        winsound.Beep(*tones[kind])
