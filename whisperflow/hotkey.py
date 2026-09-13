# -*- coding: utf-8 -*-
"""Plattformunabhaengige Hotkey-Logik: Parsen von "ctrl+alt+w" und Erkennen
von Druecken/Loslassen aus rohen Tastenevents."""

import time
import logging
import threading
from collections import namedtuple

log = logging.getLogger("whisperflow")

MODIFIERS = {
    "ctrl": "ctrl", "control": "ctrl", "strg": "ctrl",
    "alt": "alt",
    "shift": "shift",
    "win": "super", "windows": "super", "super": "super", "cmd": "super", "meta": "super",
}

KEY_ALIASES = {
    "esc": "escape",
    "return": "enter",
    "del": "delete",
    "ins": "insert",
    "pgup": "page_up", "pageup": "page_up",
    "pgdn": "page_down", "pagedown": "page_down",
    "spacebar": "space", "leertaste": "space",
}

Hotkey = namedtuple("Hotkey", "modifiers key")

MODIFIER_NAMES = ("ctrl", "alt", "shift", "super")
STALE_AFTER = 1.0  # Sekunden: aeltere Modifier werden gegen den echten Zustand geprueft


def parse_hotkey(text):
    """'ctrl+alt+w' -> Hotkey(modifiers=frozenset({'ctrl','alt'}), key='w')"""
    mods = set()
    key = None
    for part in str(text).lower().replace(" ", "").split("+"):
        if not part:
            raise ValueError(f"Ungueltiger Hotkey: {text!r}")
        if part in MODIFIERS:
            mods.add(MODIFIERS[part])
        elif key is None:
            key = KEY_ALIASES.get(part, part)
        else:
            raise ValueError(f"Hotkey {text!r} darf nur eine normale Taste enthalten (plus Modifier).")
    if key is None:
        raise ValueError(f"Hotkey {text!r} braucht eine normale Taste (z. B. 'w' oder 'f9').")
    return Hotkey(frozenset(mods), key)


class HotkeyMatcher:
    """Wird mit normalisierten Tastennamen gefuettert ('ctrl', 'alt', 'w', 'f9', ...)
    und ruft on_down/on_up genau einmal pro Druck auf.

    Loslass-Events koennen verloren gehen (Sperrbildschirm, Standby, Fenster mit
    Admin-Rechten), dann gilt ein Modifier ewig als gedrueckt. Deshalb werden
    Modifier, die schon laenger als STALE_AFTER gedrueckt sein sollen, gegen den
    echten Zustand (query_modifiers) geprueft. Frische Events werden nicht geprueft,
    weil die Abfrage bei verzoegerter Verarbeitung schon "losgelassen" melden kann.
    """

    def __init__(self, hotkey, on_down, on_up, query_modifiers=None, release_delay=0.0):
        self.hotkey = hotkey
        self._on_down = on_down
        self._on_up = on_up
        self._query_modifiers = query_modifiers
        self._release_delay = release_delay
        self._pressed = {}  # Name -> Zeitpunkt des Drueckens
        self._active = False
        self._release_timer = None
        self._lock = threading.Lock()

    def _modifiers_down(self):
        now = time.monotonic()
        mods = {m for m in self._pressed if m in MODIFIER_NAMES}
        if self._query_modifiers is None or all(now - self._pressed[m] < STALE_AFTER for m in mods):
            return mods
        try:
            real = self._query_modifiers()
        except Exception as e:
            log.debug("Modifier-Abfrage fehlgeschlagen: %s", e)
            return mods
        if real is None:
            return mods
        for m in list(mods):
            if m not in real and now - self._pressed[m] >= STALE_AFTER:
                del self._pressed[m]
                mods.discard(m)
        return mods

    def key_event(self, name, is_down):
        with self._lock:
            if is_down:
                self._pressed.setdefault(name, time.monotonic())
            else:
                self._pressed.pop(name, None)

            if name == self.hotkey.key:
                if is_down:
                    if self._release_timer is not None:
                        # Autorepeat (Loslassen+Druecken kurz hintereinander) -> ignorieren
                        self._release_timer.cancel()
                        self._release_timer = None
                        return
                    if not self._active and self.hotkey.modifiers <= self._modifiers_down():
                        self._active = True
                        self._on_down()
                elif self._active:
                    self._schedule_release()
            elif not is_down and self._active and name in self.hotkey.modifiers:
                self._schedule_release()

    def _schedule_release(self):
        if self._release_delay <= 0:
            self._release()
            return
        if self._release_timer is None:
            self._release_timer = threading.Timer(self._release_delay, self._release_later)
            self._release_timer.daemon = True
            self._release_timer.start()

    def _release_later(self):
        with self._lock:
            if self._release_timer is None:
                return
            self._release()

    def _release(self):
        self._release_timer = None
        self._active = False
        self._on_up()
