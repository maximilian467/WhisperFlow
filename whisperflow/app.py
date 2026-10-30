# -*- coding: utf-8 -*-
"""
WhisperFlow - Lokale Speech-to-Text per Hotkey (0 Euro, komplett offline).

Drueck den Hotkey (Standard: Strg+Alt+W), sprich, druecke ihn erneut ->
der erkannte Text wird an der Cursorposition eingefuegt.

Alles laeuft lokal auf deinem Rechner. Keine Cloud, keine Kosten.
"""

import os
import sys
import json
import atexit
import time
import queue
import logging
import threading
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

# HuggingFace-Cache-Warnung unter Windows unterdruecken (rein kosmetisch)
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

import numpy as np
import sounddevice as sd

from .hotkey import parse_hotkey

SAMPLE_RATE = 16000  # Whisper erwartet 16 kHz
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.json")
LOG_PATH = os.path.join(ROOT, "whisperflow.log")

DEFAULTS = {
    "hotkey": "ctrl+alt+w",
    "mode": "toggle",            # "toggle" oder "push_to_talk"
    "model": "small",            # tiny | base | small | medium | large-v3
    "language": "de",            # "de", "en", ... oder "auto"
    "device": "cpu",
    "compute_type": "int8",
    "beam_size": 1,
    "vad_filter": True,
    "paste_method": "clipboard",  # "clipboard" (Strg+V) oder "type" (tippen)
    "paste_keys": "ctrl+v",       # z. B. "ctrl+shift+v" fuer Linux-Terminals
    "add_trailing_space": True,
    "sounds": True,
    "initial_prompt": "",
    "linux_backend": "auto",      # "auto" | "evdev" | "pynput" (nur Linux)
    "status_file": True,          # Zustand fuer andere Apps (z. B. Developer Island) mitschreiben
}

log = logging.getLogger("whisperflow")


def status_path():
    """Windows: %LOCALAPPDATA%\\WhisperFlow\\status.json, Linux: ~/.local/state/whisperflow/status.json"""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "WhisperFlow", "status.json")
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "whisperflow", "status.json")


class StatusFile:
    """Schreibt nur den aktuellen Zustand (kein Audio, kein Text) in eine kleine JSON-Datei,
    damit andere Programme anzeigen koennen, ob WhisperFlow gerade aufnimmt oder transkribiert.
    Zustaende: loading, ready, recording, transcribing, done, empty, error, stopped.
    Fehler beim Schreiben werden ignoriert - die Statusdatei darf WhisperFlow nie stoeren."""

    def __init__(self, enabled):
        self.path = status_path() if enabled else None
        self._lock = threading.Lock()

    def write(self, state):
        if not self.path:
            return
        data = {
            "version": 1,
            "state": state,
            "at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "pid": os.getpid(),
        }
        with self._lock:
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                temp = f"{self.path}.{os.getpid()}.tmp"
                with open(temp, "w", encoding="utf-8") as f:
                    json.dump(data, f)
                os.replace(temp, self.path)
            except OSError:
                pass


def setup_logging():
    log.setLevel(logging.INFO)
    try:
        fh = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s [%(threadName)s] %(message)s"))
        log.addHandler(fh)
    except OSError:
        pass
    # Unter pythonw (Autostart ohne Fenster) gibt es kein stdout
    if sys.stdout is not None:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(sh)

    def thread_excepthook(args):
        log.error("Unbehandelter Fehler im Thread %s", args.thread.name if args.thread else "?",
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    threading.excepthook = thread_excepthook


def load_config():
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception as e:
            log.warning("[WARN] config.json konnte nicht gelesen werden: %s", e)
    return cfg


def load_platform():
    if sys.platform == "win32":
        from . import platform_windows as plat
    elif sys.platform.startswith("linux"):
        from . import platform_linux as plat
    else:
        raise SystemExit(f"Nicht unterstuetztes Betriebssystem: {sys.platform}")
    return plat


# ---------------------------------------------------------------------------
# Audioaufnahme
# ---------------------------------------------------------------------------
class Recorder:
    def __init__(self):
        self._chunks = []
        self._stream = None
        self._rate = SAMPLE_RATE

    @property
    def recording(self):
        return self._stream is not None

    def _callback(self, indata, frames, time_info, status):
        self._chunks.append(indata.copy())

    def _open(self):
        try:
            rate = SAMPLE_RATE
            stream = sd.InputStream(samplerate=rate, channels=1, dtype="float32",
                                    callback=self._callback)
        except sd.PortAudioError:
            # Manche Geraete (v. a. ALSA unter Linux) koennen kein 16 kHz ->
            # native Rate nehmen und spaeter umrechnen
            rate = int(sd.query_devices(kind="input")["default_samplerate"])
            stream = sd.InputStream(samplerate=rate, channels=1, dtype="float32",
                                    callback=self._callback)
        stream.start()
        self._rate = rate
        return stream

    def start(self):
        if self._stream is not None:
            return
        self._chunks = []
        try:
            self._stream = self._open()
        except Exception as e:
            # PortAudio merkt sich die Geraeteliste vom Programmstart. Nach Standby
            # oder Headset-Wechsel ist sie veraltet -> neu initialisieren, nochmal.
            log.warning("[WARN] Mikrofon-Fehler (%s) - initialisiere Audio neu ...", e)
            try:
                sd._terminate()
                sd._initialize()
            except Exception:
                pass
            self._stream = self._open()

    def stop(self):
        stream, self._stream = self._stream, None
        if stream is None:
            return np.zeros(0, dtype=np.float32)
        try:
            stream.stop()
            stream.close()
        except Exception as e:
            log.warning("[WARN] Audio-Stream liess sich nicht sauber schliessen: %s", e)
        chunks, self._chunks = self._chunks, []
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        audio = np.concatenate(chunks, axis=0).reshape(-1).astype(np.float32)
        if self._rate != SAMPLE_RATE:
            n = int(len(audio) * SAMPLE_RATE / self._rate)
            audio = np.interp(np.linspace(0, len(audio) - 1, n),
                              np.arange(len(audio)), audio).astype(np.float32)
        return audio


# ---------------------------------------------------------------------------
# Ablaufsteuerung
# ---------------------------------------------------------------------------
class Controller:
    """Hotkey-Threads rufen nur hotkey_down/hotkey_up auf; die eigentliche Arbeit
    passiert in eigenen Threads. So kann ein langsames Mikrofon, eine blockierte
    Konsole oder ein Fehler niemals die Hotkey-Erkennung lahmlegen."""

    def __init__(self, cfg, model, plat, status):
        self.cfg = cfg
        self.model = model
        self.plat = plat
        self.status = status
        self.inserter = plat.TextInserter(cfg)
        self.recorder = Recorder()
        self.push_to_talk = cfg.get("mode", "toggle") == "push_to_talk"
        self._events = queue.Queue()
        self._jobs = queue.Queue()
        threading.Thread(target=self._event_loop, name="events", daemon=True).start()
        threading.Thread(target=self._job_loop, name="transcribe", daemon=True).start()

    def hotkey_down(self):
        self._events.put("down")

    def hotkey_up(self):
        self._events.put("up")

    def beep(self, kind):
        if self.cfg.get("sounds", True):
            try:
                self.plat.beep(kind)
            except Exception:
                pass

    def _event_loop(self):
        while True:
            event = self._events.get()
            try:
                if event == "down":
                    if not self.recorder.recording:
                        self._start_recording()
                    elif not self.push_to_talk:
                        self._stop_recording()
                elif event == "up" and self.push_to_talk and self.recorder.recording:
                    self._stop_recording()
            except Exception:
                log.exception("[ERR] Fehler bei der Hotkey-Verarbeitung")
                self.beep("error")
                self._report_result("error")

    def _start_recording(self):
        try:
            self.recorder.start()
        except Exception as e:
            log.error("[ERR] Mikrofon konnte nicht geoeffnet werden: %s", e)
            self.beep("error")
            self._report_result("error")
            return
        if self.push_to_talk:
            log.info("[REC] Aufnahme laeuft ... (Hotkey loslassen zum Stoppen)")
        else:
            log.info("[REC] Aufnahme laeuft ... (Hotkey erneut druecken zum Stoppen)")
        self.status.write("recording")
        self.beep("start")

    def _stop_recording(self):
        audio = self.recorder.stop()
        self.beep("stop")
        log.info("[REC] Stop. %.1fs Audio aufgenommen.", audio.size / SAMPLE_RATE)
        self.status.write("transcribing")
        self._jobs.put(audio)

    def _job_loop(self):
        while True:
            audio = self._jobs.get()
            try:
                self._process(audio)
            except Exception:
                log.exception("[ERR] Transkription fehlgeschlagen")
                self.beep("error")
                self._report_result("error")

    def _report_result(self, state):
        """Ergebnis melden - ausser es laeuft schon die naechste Aufnahme oder Transkription,
        dann bleibt deren Zustand stehen."""
        if self.recorder.recording:
            return
        if not self._jobs.empty():
            return
        self.status.write(state)

    def _process(self, audio):
        log.info("[..] Transkribiere ...")
        t0 = time.time()
        text = self._transcribe(audio)
        dt = time.time() - t0
        if not text:
            log.info("[--] Nichts erkannt (%.1fs).", dt)
            self.beep("error")
            self._report_result("empty")
            return
        if self.cfg.get("add_trailing_space", True):
            text += " "
        log.info("[OK] (%.1fs) -> %r", dt, text)
        self.inserter.insert(text)
        self.beep("done")
        self._report_result("done")

    def _transcribe(self, audio):
        if audio.size < SAMPLE_RATE * 0.3:  # weniger als 0,3 s -> ignorieren
            return ""
        language = self.cfg.get("language", "de")
        if language == "auto":
            language = None
        kwargs = dict(
            language=language,
            beam_size=int(self.cfg.get("beam_size", 1)),
            vad_filter=bool(self.cfg.get("vad_filter", True)),
        )
        prompt = self.cfg.get("initial_prompt", "")
        if prompt:
            kwargs["initial_prompt"] = prompt
        segments, _info = self.model.transcribe(audio, **kwargs)
        return "".join(seg.text for seg in segments).strip()


def main():
    setup_logging()
    cfg = load_config()
    plat = load_platform()

    if not plat.acquire_single_instance():
        log.error("[ERR] WhisperFlow laeuft bereits (z. B. ueber den Autostart). Beende diese Instanz.")
        sys.exit(1)
    plat.prepare_console()

    # Erst nach der Einzelinstanz-Pruefung: eine zweite Instanz darf den Status nicht ueberschreiben.
    status = StatusFile(cfg.get("status_file", True))
    atexit.register(status.write, "stopped")
    status.write("loading")

    try:
        hotkey = parse_hotkey(cfg.get("hotkey", "ctrl+alt+w"))
    except ValueError as e:
        log.error("[ERR] %s", e)
        sys.exit(1)

    log.info("=" * 56)
    log.info(" WhisperFlow - lokale Speech-to-Text")
    log.info("=" * 56)
    log.info(" Modell:    %s (%s/%s)", cfg["model"], cfg["device"], cfg["compute_type"])
    log.info(" Sprache:   %s", cfg["language"])
    log.info(" Hotkey:    %s", cfg["hotkey"])
    log.info(" Modus:     %s", cfg["mode"])
    log.info("-" * 56)
    log.info(" Lade Modell ... (beim 1. Mal wird es heruntergeladen)")

    from faster_whisper import WhisperModel

    t0 = time.time()
    try:
        model = WhisperModel(cfg["model"], device=cfg["device"], compute_type=cfg["compute_type"])
    except Exception:
        log.exception("[ERR] Modell konnte nicht geladen werden")
        sys.exit(1)
    log.info(" Modell geladen in %.1fs.", time.time() - t0)
    log.info("-" * 56)

    controller = Controller(cfg, model, plat, status)
    listener = plat.create_hotkey_listener(cfg, hotkey, controller.hotkey_down, controller.hotkey_up)
    try:
        listener.start()
    except Exception as e:
        log.error("[ERR] Hotkey konnte nicht eingerichtet werden: %s", e)
        sys.exit(1)

    if controller.push_to_talk:
        log.info(" Bereit. Halte '%s' gedrueckt und sprich.", cfg["hotkey"])
    else:
        log.info(" Bereit. Druecke '%s' zum Starten/Stoppen.", cfg["hotkey"])
    log.info(" Beenden: Strg+C in diesem Fenster (oder Fenster schliessen).")
    log.info(" Log-Datei: %s", LOG_PATH)
    if status.path:
        log.info(" Status:    %s", status.path)
    log.info("=" * 56)
    status.write("ready")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Beendet.")
    finally:
        listener.stop()
