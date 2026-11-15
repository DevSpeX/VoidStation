#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
VoidStation Launcher
-----------------
Kleiner lokaler Dienst fuer die Kacheloberflaeche:
  * liefert der Startseite (Qt) Kacheln, Texte und Zustand ueber eine HTTP-API
  * startet Programme aus tiles.json (nur diese, keine freien Befehle)
  * mehrere Programme parallel; erneutes Oeffnen holt ein laufendes nach vorn
  * "Home" holt die Startseite nach vorn, ohne etwas zu beenden
  * Radio im Hintergrund (mpv), Sendersuche ueber radio-browser.info, Favoriten
  * Lautstaerke (wpctl)
  * optional: Guide-/Home-Taste am Gamepad (python3-evdev)
  * Bluetooth: BlueZ ueber D-Bus mit eigenem Kopplungs-Agenten (python3-gobject)

Lauscht ausschliesslich auf 127.0.0.1.
"""

import csv
import datetime
import hashlib
import json
import os
import random
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from html import escape as html_escape, unescape as html_unescape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import tvindex
import vsreport
import vsx11
from tvindex import TV_LETTERS, TV_PAGE, tv_fold, tv_letter  # noqa: F401

HOST = "127.0.0.1"
PORT = int(os.environ.get("VOIDSTATION_PORT", "8765"))
BASE = Path(__file__).resolve().parent
WEB = BASE / "web"                                     # Texte (i18n/), Themes (themes/), Logo – kein HTML mehr
CONFIG = Path(os.environ.get("VOIDSTATION_CONFIG", BASE / "tiles.json"))
FAVS = BASE / "radio.json"
MPV_SOCK = str(BASE / "mpv.sock")
PLAYER_BIN = BASE / "qt" / "voidstation-player.py"    # eigener Player: Fernsehen, Videos & Musik
HOME_TITLE = "VoidStation"                      # <title> der Startseite
PAUSED_FILE = BASE / "paused.json"              # im Hintergrund angehaltene Prozesse (beim Launcher-Start fortsetzen)
RADIO_SERVERS = ["de1.api.radio-browser.info", "de2.api.radio-browser.info",
                 "fi1.api.radio-browser.info", "at1.api.radio-browser.info"]

MIME = {
    ".html": "text/html; charset=utf-8", ".json": "application/json; charset=utf-8",
    ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml", ".webp": "image/webp",
}
POWER = {
    "poweroff": ["sudo", "-n", "/usr/bin/poweroff"],
    "reboot": ["sudo", "-n", "/usr/bin/reboot"],
    "suspend": ["sudo", "-n", "/usr/local/sbin/voidstation-pkg", "suspend"],
}


def must_match(m: "re.Match[str] | None") -> "re.Match[str]":
    """Treffer, der da sein muss. Fehlt er, scheitert es wie bisher mit AttributeError."""
    if m is None:
        raise AttributeError("kein Treffer")
    return m


def log(*a):
    print("[voidstation]", *a, file=sys.stderr, flush=True)


def load_config():
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def find_tile(tile_id):
    for group in load_config().get("groups", []):
        for tile in group.get("tiles", []):
            if tile.get("id") == tile_id:
                return tile
    return None


def expand(args):
    return [os.path.expandvars(os.path.expanduser(a)) for a in args]


def run(args, timeout=5, **kw):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout, **kw)
    except (OSError, subprocess.TimeoutExpired):
        return None


# ---------------------------------------------------------------------------
#  Fenster (vsx11: libX11, Rueckfall wmctrl/xprop)
# ---------------------------------------------------------------------------
def windows():
    """Liste (id, pid, titel) aller Fenster."""
    return vsx11.windows()


def session_pids(sid):
    r = run(["ps", "-e", "-o", "pid=,sid="])
    pids = set()
    if r:
        for row in r.stdout.strip().splitlines():
            p = row.split()
            if len(p) == 2 and p[1] == str(sid):
                pids.add(int(p[0]))
    return pids or {sid}


def active_window():
    """Kennung des aktiven Fensters (_NET_ACTIVE_WINDOW) oder None."""
    return vsx11.active_window() or None


def media_notify(cmd):
    """Laufendem Player "Videos & Musik" bzw. "YouTube Light" Bescheid geben (ohne zu warten): "background" =
    Startseite oder anderes Programm kommt nach vorn (Videos halten an, Musik laeuft weiter), "pause" = Radio startet."""
    try:
        for tid, mode in (("media", "media"), ("ytlight", "yt")):
            if APPS._get(tid):
                threading.Thread(target=PLAYERS.send, args=(mode, {"cmd": cmd}), daemon=True).start()
    except NameError:                                   # beim Start, bevor es APPS/PLAYERS gibt
        pass


def raise_home():
    media_notify("background")
    try:
        APPS.pause_background()                         # Emulatoren anhalten, solange die Startseite vorn ist
    except NameError:
        pass
    for wid, _pid, title in windows():
        if HOME_TITLE in title:
            vsx11.activate(wid)
            return True
    return False


# ---------------------------------------------------------------------------
#  Programme
# ---------------------------------------------------------------------------
class AppManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.procs = {}                       # tile_id -> Popen
        self.shown = set()                    # tile_ids, deren Programm schon ein Fenster hat
        self.recent = []                      # tile_ids, zuletzt gestartet / nach vorn geholt (neueste hinten)
        self.claimed = {}                     # tile_id -> Fenster-IDs ohne passende Prozess-ID (Flatpak), beim Start zugeordnet
        self.paused = {}                      # tile_id -> Prozess-IDs, die im Hintergrund angehalten sind (SIGSTOP)
        self._pwatch = False                  # Waechter fuer angehaltene Programme laeuft
        self.kinds = {}                       # tile_id -> Programm (z. B. "mgba-qt"), fuer die Vollbild-Taste

    def running(self):
        with self.lock:
            for tid in [t for t, p in self.procs.items() if p.poll() is not None]:
                del self.procs[tid]
                self.shown.discard(tid)
                self.claimed.pop(tid, None)
                self.paused.pop(tid, None)
            return list(self.procs)

    # ---- Im Hintergrund anhalten (Emulatoren) -------------------------------------------------------------
    # Emulatoren lesen den Controller auch ohne Fokus weiter: Ist die Startseite vorn, spielte das Spiel mit
    # jedem Tastendruck mit. Deshalb halten sie an (SIGSTOP, wie Pause), sobald etwas anderes nach vorn kommt,
    # und laufen weiter (SIGCONT), wenn ihr Fenster wieder vorn ist – ueber die Kachel, die heisse Ecke oder
    # sonstwie (Waechter). Die Prozess-IDs stehen in PAUSED_FILE, damit ein neu gestarteter Launcher nichts
    # angehalten zuruecklaesst.
    def _persist_paused(self):
        with self.lock:
            pids = sorted({p for ps in self.paused.values() for p in ps})
        try:
            if pids:
                PAUSED_FILE.write_text(json.dumps(pids), encoding="utf-8")
            else:
                PAUSED_FILE.unlink(missing_ok=True)
        except OSError as e:
            log("paused.json:", e)

    @staticmethod
    def _kill_all(pids, sig):
        for pid in pids:
            try:
                os.kill(pid, sig)
            except (ProcessLookupError, PermissionError):
                pass

    def pause_background(self, keep=None):
        """Laufende Emulatoren anhalten, ausser `keep` (die Kachel, die gerade nach vorn kommt). Nur Programme, die
        schon ein Fenster zeigen – ein Emulator, der noch startet, bliebe sonst ohne Fenster stehen."""
        changed = False
        for tid in self.running():
            if tid == keep:
                continue
            with self.lock:
                proc = self.procs.get(tid)
                skip = not proc or tid in self.paused or tid not in self.shown
            if skip or proc is None or not app_suspendable(tid):
                continue
            pids = session_pids(proc.pid)
            self._kill_all(pids, signal.SIGSTOP)
            with self.lock:
                self.paused[tid] = pids
            log("angehalten (Hintergrund):", tid, sorted(pids))
            changed = True
        if changed:
            self._persist_paused()
            with self.lock:
                start, self._pwatch = not self._pwatch, True
            if start:
                threading.Thread(target=self._watch_paused, daemon=True).start()

    def resume(self, tid):
        with self.lock:
            pids = self.paused.pop(tid, None)
            proc = self.procs.get(tid)
        if pids is None:
            return
        if proc and proc.poll() is None:
            pids = pids | session_pids(proc.pid)        # inzwischen gestartete Kindprozesse auch
        self._kill_all(pids, signal.SIGCONT)
        log("laeuft weiter:", tid)
        self._persist_paused()

    def resume_all(self):
        with self.lock:
            tids = list(self.paused)
        for tid in tids:
            self.resume(tid)

    def _watch_paused(self):
        """Kommt das Fenster eines angehaltenen Programms auf anderem Weg nach vorn (Alt+Tab, Dialog), laeuft es
        weiter – sonst saehe es aus wie abgestuerzt."""
        while True:
            time.sleep(1.0)
            running = set(self.running())                # raeumt beendete Programme aus self.paused
            with self.lock:
                paused = {t: self.procs.get(t) for t in self.paused if t in running}
                if not paused:
                    self._pwatch = False
                    break
            act = active_window()
            if not act:
                continue
            wl = windows()
            for tid, proc in paused.items():
                if proc and any(int(w[0], 16) == act for w in self._windows_of(tid, proc, wl)):
                    self.resume(tid)
        self._persist_paused()

    def starting(self):
        """Laufende Programme, die noch kein Fenster zeigen (z. B. Steam bei der Ersteinrichtung)."""
        running = self.running()
        with self.lock:
            return [t for t in running if t not in self.shown]

    def _get(self, tile_id):
        with self.lock:
            p = self.procs.get(tile_id)
            return p if p and p.poll() is None else None

    def _windows_of(self, tid, proc, wl=None):
        """Fenster eines Programms: ueber die Prozess-IDs seiner Sitzung, dazu die beim Start zugeordneten.
        Flatpaks melden als Prozess-ID die aus ihrer Sandbox – die passt zu keiner Sitzung."""
        wl = windows() if wl is None else wl
        pids = session_pids(proc.pid)
        with self.lock:
            claimed = set(self.claimed.get(tid, ()))
        return [w for w in wl if (w[1] in pids or int(w[0], 16) in claimed) and HOME_TITLE not in w[2]]

    def _claim_new(self, tid, wl, before):
        """Fenster, die es vor dem Start noch nicht gab und die keinem anderen Programm gehoeren, dieser Kachel
        zuordnen (Programme, deren Fenster sich nicht ueber die Prozess-ID finden lassen, z. B. Flatpaks)."""
        with self.lock:
            others = [p for t, p in self.procs.items() if t != tid and p.poll() is None]
            taken = set().union(*self.claimed.values()) if self.claimed else set()
        other_pids = set()
        for op in others:
            other_pids |= session_pids(op.pid)
        new = [w for w in wl if int(w[0], 16) not in before and int(w[0], 16) not in taken
               and w[1] not in other_pids and HOME_TITLE not in w[2]]
        if new:
            with self.lock:
                self.claimed.setdefault(tid, set()).update(int(w[0], 16) for w in new)
            log(tid, "Fenster ohne passende Prozess-ID zugeordnet:", ", ".join(w[0] for w in new))
        return new

    def focus(self, tile_id):
        p = self._get(tile_id)
        if not p:
            return False
        self.resume(tile_id)
        self.pause_background(keep=tile_id)
        wins = self._windows_of(tile_id, p)
        for wid, _, _ in wins:
            vsx11.activate(wid)
        if not wins:
            log("kein Fenster gefunden fuer", tile_id)
        return bool(wins)

    def _touch(self, tid):
        with self.lock:
            if tid in self.recent:
                self.recent.remove(tid)
            self.recent.append(tid)

    def launch(self, tile):
        tid = tile["id"]
        if self._get(tid):
            log("schon offen, nach vorn:", tid)
            self._touch(tid)
            self.focus(tid)
            return "focused"
        cmd = tile.get("cmd")
        if not cmd:
            raise ValueError("Kachel hat keinen Befehl")
        args = expand(cmd if isinstance(cmd, list) else ["sh", "-c", cmd])
        if Path(args[0]).name == PLAYER_BIN.name:          # Videos & Musik, YouTube Light: eigener Player (Stufe, Absturzzaehler)
            mode = "yt" if "--yt" in args[1:2] else "media"
            return PLAYERS.start(tid, args[2] if len(args) > 2 else "", mode=mode)
        media_notify("background")                         # anderes Programm: laufendes Video anhalten
        return self.start(tid, args)

    def start(self, tid, args, env=None):
        log("starte", tid, args)
        logdir = BASE / "logs"
        logdir.mkdir(exist_ok=True)
        out = open(logdir / f"{tid}.log", "w")   # Ausgaben je Programm, hilft bei Abstuerzen
        before = {int(w, 16) for w, _, _ in windows()}  # Fenster vor dem Start (Zuordnung ohne Prozess-ID)
        if Path(args[0]).name == "firefox":
            firefox_prefs(args, ui_lang(), theme_is_dark(settings_load().get("theme") or DEFAULTS["theme"]))
        if tid == "librewolf":
            librewolf_keyboard()
        elif tid == "braveorigin":
            brave_origin_prepare()
        if Path(args[0]).name in ("dosbox", "dosbox-staging"):
            args = dosbox_prepare(args)
        args, emu_env, wm_fs = emu_prepare(tid, args)   # Emulatoren: Vorgaben, Vollbild, Controller
        penv = app_env()
        penv.update(emu_env)
        penv.update(game_fx_env(tid))
        penv.update(env or {})
        self.pause_background(keep=tid)                 # anderes Programm kommt nach vorn: Emulatoren anhalten
        proc = subprocess.Popen(args, cwd=str(Path.home()), stdin=subprocess.DEVNULL, env=penv,
                                stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
        out.close()
        with self.lock:
            self.procs[tid] = proc
            self.shown.discard(tid)
            self.kinds[tid] = emu_kind(args)
        self._touch(tid)
        PERF.started(tid)                               # Spiel oder Emulator: CPU-Takt hoch, solange es laeuft
        # Neues Fenster aktiv nach vorn holen (Openbox verhindert sonst u. U. den Fokuswechsel,
        # und das Programm laeuft unsichtbar hinter der Startseite)
        threading.Thread(target=self._bring_up, args=(tid, proc, before, wm_fs), daemon=True).start()
        return "started"

    def _bring_up(self, tid, proc, before=frozenset(), fullscreen=False):
        # Auf das erste Fenster warten: anfangs schnell, danach gemaechlich - Steam braucht
        # bei der Ersteinrichtung mehrere Minuten, bis sich ein Fenster zeigt
        t0 = time.monotonic()
        while time.monotonic() - t0 < 1800:
            time.sleep(0.3 if time.monotonic() - t0 < 12 else 1.0)
            if proc.poll() is not None:
                log(tid, "beendet mit Code", proc.returncode)
                return
            pids = session_pids(proc.pid)
            wl = windows()
            wins = [w for w in wl if w[1] in pids and HOME_TITLE not in w[2]]
            if not wins and time.monotonic() - t0 > 1.0:  # Flatpak & Co.: neues Fenster ohne passende Prozess-ID
                wins = self._claim_new(tid, wl, before)
            if wins:
                with self.lock:
                    self.shown.add(tid)
                log(tid, f"Fenster nach {time.monotonic() - t0:.1f} s")
                time.sleep(0.4)
                for wid, _, _ in wins:
                    vsx11.activate(wid)
                if fullscreen:                           # Emulator ohne eigene Vollbild-Option (EMU_WM_FULLSCREEN)
                    vsx11.wm_state(wins[0][0], "add", "fullscreen")
                elif app_maximize(tid):
                    # Openbox maximiert neue Fenster per Regel (rc.xml) – GTK4-Programme (Mission Center & Co.)
                    # setzen danach aber ihre gespeicherte Groesse und heben das wieder auf: nachsehen, nachziehen
                    for delay in (0.8, 2.5, 5.0):
                        time.sleep(delay)
                        if proc.poll() is not None:
                            return
                        for wid, _, _ in wins:
                            wm_maximize(wid)
                return
        with self.lock:                          # kein Fenster erkennbar -> nicht ewig "startet"
            self.shown.add(tid)

    def close(self, tile_id):
        self.resume(tile_id)                     # angehalten verarbeitet es kein "Fenster schliessen"
        with self.lock:
            proc = self.procs.pop(tile_id, None)
        if not proc or proc.poll() is not None:
            with self.lock:
                self.claimed.pop(tile_id, None)
            return
        sid = proc.pid
        wins = self._windows_of(tile_id, proc)
        with self.lock:
            self.claimed.pop(tile_id, None)
        log("schliesse", tile_id, sorted(session_pids(sid)))
        for wid, _, _ in wins:                 # hoeflich, wie Alt+F4 -> Spielstaende werden gespeichert
            vsx11.close(wid)
        if wins:
            for _ in range(40):
                if proc.poll() is not None:
                    return
                time.sleep(0.1)
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(sid, sig)
            except ProcessLookupError:
                return
            for _ in range(20):
                if proc.poll() is not None:
                    return
                time.sleep(0.1)

    def front(self):
        """Kachel des Programms im Vordergrund (fuer die heisse Ecke), sonst None.
        1. Aktives Fenster wurde beim Start einer Kachel zugeordnet (Flatpak & Co.) -> diese.
        2. Prozess-ID des aktiven Fensters gehoert zu einem gestarteten Programm -> dieses.
        3. Sonst: unter den Programmen, denen sich kein Fenster zuordnen laesst, das zuletzt gestartete bzw.
           nach vorn geholte."""
        running = self.running()
        if not running:
            return None
        with self.lock:
            procs = {t: p for t, p in self.procs.items() if t in running}
            recent = list(self.recent)
            claimed = {t: set(w) for t, w in self.claimed.items() if t in running}
        act = active_window()
        for tid, ws in claimed.items():
            if act in ws:
                return tid
        owner = {}
        for tid, proc in procs.items():
            for pid in session_pids(proc.pid):
                owner[pid] = tid
        wins = windows()
        wid = act
        if wid:
            pid = next((p for w, p, _ in wins if int(w, 16) == wid), None)
            if pid in owner:
                return owner[pid]
        seen = {owner[p] for _, p, _ in wins if p in owner}
        cands = [t for t in running if t not in seen] or running
        for tid in reversed(recent):
            if tid in cands:
                return tid
        return cands[0] if len(cands) == 1 else None

    def close_all(self):
        for tid in self.running():
            self.close(tid)


APPS = AppManager()


# ---------------------------------------------------------------------------
#  Eigener Player (qt/voidstation-player.py): Fernsehen ("tv"), Videos & Musik ("media"), YouTube Light ("yt")
# ---------------------------------------------------------------------------
class PlayerManager:
    """Startet den Player, reicht Auftraege an einen laufenden weiter (Socket) und stuft nach Abstuerzen hoch:
    0 Video in der Oberflaeche (EGL) -> 1 GLX + Decoding mit Kopie -> 2 mpv im eigenen Fenster -> 3 (nur Fernsehen)
    nacktes mpv wie frueher. Gilt bis zum Neustart des Launchers; fest: VS_PLAYER_LEVEL=0…3."""
    CRASH = {-4, -6, -7, -8, -11}                # SIGILL, SIGABRT, SIGBUS, SIGFPE, SIGSEGV; dazu Exit-Codes > 0

    def __init__(self):
        self.lock = threading.Lock()
        self.fails = []

    def level(self):
        forced = os.environ.get("VS_PLAYER_LEVEL", "")
        if forced in ("0", "1", "2", "3"):
            return int(forced)
        if not PLAYER_BIN.exists():
            return 3
        with self.lock:
            return min(3, len(self.fails))

    @staticmethod
    def sock(mode):
        return BASE / f"player-{mode}.sock"

    def send(self, mode, msg):
        """Auftrag an einen laufenden Player; False, wenn keiner antwortet."""
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(2)
                s.connect(str(self.sock(mode)))
                s.sendall((json.dumps(msg) + "\n").encode())
                return b"ok" in s.recv(256)
        except OSError:
            return False

    def start(self, tid, arg="", mode="media"):
        level = min(self.level(), 2)
        for other in ("tv", "media", "ytlight"):     # nur ein Video zur Zeit
            if other != tid:
                APPS.close(other)
        if tid == "tv":
            TV.raw = False
        if APPS._get(tid):
            msg = {"cmd": "tune", "key": arg} if mode == "tv" else {"cmd": "open", "path": arg}
            if (not arg and mode in ("media", "yt")) or self.send(mode, msg):
                APPS.focus(tid)
                return "focused"
            APPS.close(tid)
        args = [sys.executable, str(PLAYER_BIN), "--" + mode] + ([arg] if arg else [])
        res = APPS.start(tid, args, env={"VS_PLAYER_LEVEL": str(level)})
        proc = APPS._get(tid)
        if proc:
            threading.Thread(target=self._watch, args=(tid, proc, level), daemon=True).start()
        return res

    def _watch(self, tid, proc, level):
        t0 = time.monotonic()
        rc = proc.wait()
        try:
            DISPLAY_RATE.request(0, {"ytlight": "yt"}.get(tid, tid))   # Player zu -> Desktop-Rate
        except Exception as e:  # noqa: BLE001
            log("Bildrate zuruecksetzen:", e)
        if rc in self.CRASH or rc > 0:
            with self.lock:
                self.fails.append(time.time())
                n = len(self.fails)
            log(f"Player ({tid}, Stufe {level}) abgestuerzt nach {time.monotonic() - t0:.0f} s, Code {rc} – "
                f"naechster Start mit Stufe {min(3, n)} (Protokoll: logs/{tid}.log)")

    def active(self, tid):
        """Laeuft fuer diese Kachel der eigene Player (nicht das nackte mpv)?"""
        if tid in ("media", "ytlight"):
            return True
        return tid == "tv" and not TV.raw


PLAYERS = PlayerManager()
MEDIA_NOW: dict = {}                                   # was "Videos & Musik" gerade spielt (Kachel der Startseite)


# ---------------------------------------------------------------------------
#  Radio (mpv im Hintergrund)
# ---------------------------------------------------------------------------
def music_volume():
    """Eigener Regler fuer Musik und Radio (0–100), der Spielton und die Systemlautstaerke bleiben, wie sie sind."""
    try:
        return max(0, min(100, int(settings_load().get("music_volume", 100))))
    except (TypeError, ValueError):
        return 100


def now_playing():
    """Was laeuft gerade im Hintergrund (heisse Ecke oben links)? kind: "radio", "music" oder leer."""
    vol = music_volume()
    r = RADIO.status()
    st = r.get("station")
    if st:
        t = r.get("title")
        favs = [f.get("url") for f in favs_load()]
        return {"kind": "radio", "title": t or st.get("name", ""), "sub": st.get("name", "") if t else "", "paused": RADIO.paused(),
                "volume": vol, "skip": len(favs) > (1 if st.get("url") in favs else 0)}
    if "media" in APPS.running() and MEDIA_NOW.get("kind") == "audio" and MEDIA_NOW.get("title"):
        return {"kind": "music", "title": MEDIA_NOW["title"], "sub": MEDIA_NOW.get("sub", ""), "paused": bool(MEDIA_NOW.get("paused")),
                "volume": vol, "skip": True}
    return {"kind": ""}


def now_control(action):
    """Bedienung aus der heissen Ecke: prev, next, toggle, up, down (Lautstaerke der Musik, in 5er-Schritten)."""
    cur = now_playing()
    kind = cur.get("kind")
    if not kind:
        return cur
    if action in ("up", "down"):
        vol = max(0, min(100, cur["volume"] + (5 if action == "up" else -5)))
        s = settings_load()
        s["music_volume"] = vol
        settings_save(s)
        if kind == "radio":
            RADIO.set_volume(vol)
        else:
            PLAYERS.send("media", {"cmd": "control", "action": "volume", "value": vol})
    elif kind == "music" and action in ("prev", "next", "toggle"):
        PLAYERS.send("media", {"cmd": "control", "action": action})
        time.sleep(0.15)                            # der Player meldet den neuen Stand selbst
    elif action == "toggle":
        RADIO.toggle()
    elif action in ("prev", "next"):                # Radio: durch die Favoriten
        favs = favs_load()
        url = (RADIO.status().get("station") or {}).get("url")
        i = next((n for n, f in enumerate(favs) if f.get("url") == url), None)
        if favs:
            step = 1 if action == "next" else -1
            RADIO.play(favs[(0 if step > 0 else -1) if i is None else (i + step) % len(favs)])
    return now_playing()


class Radio:
    def __init__(self):
        self.lock = threading.Lock()
        self.proc = None
        self.station = None

    def _ipc(self, command):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                s.connect(MPV_SOCK)
                s.sendall((json.dumps({"command": command}) + "\n").encode())
                data = b""
                while b"\n" not in data:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                for line in data.decode(errors="replace").splitlines():
                    msg = json.loads(line)
                    if "error" in msg:
                        return msg.get("data")
        except (OSError, ValueError):
            return None
        return None

    def play(self, station):
        url = station.get("url")
        if not url or not url.startswith(("http://", "https://")):
            raise ValueError("ungueltige Stream-Adresse")
        media_notify("pause")                              # Musik/Video im Player anhalten
        self.stop()
        log("Radio:", station.get("name"), url)
        proc = subprocess.Popen(
            ["mpv", "--no-video", "--no-terminal", "--idle=no", "--cache=yes", f"--volume={music_volume()}",
             f"--input-ipc-server={MPV_SOCK}", url],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        with self.lock:
            self.proc, self.station = proc, {k: station.get(k, "") for k in ("name", "url", "favicon", "country", "tags")}

    def stop(self):
        with self.lock:
            proc, self.proc, self.station = self.proc, None, None
        if proc and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=2)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def paused(self):
        return self._ipc(["get_property", "pause"]) is True

    def toggle(self):
        self._ipc(["cycle", "pause"])

    def set_volume(self, vol):
        self._ipc(["set_property", "volume", vol])

    def status(self):
        with self.lock:
            alive = self.proc is not None and self.proc.poll() is None
            station = self.station if alive else None
            if not alive:
                self.proc, self.station = None, None
        title = None
        if station:
            t = self._ipc(["get_property", "media-title"])
            if t and t != station["url"] and not t.startswith("http"):
                title = t
        return {"station": station, "title": title}


RADIO = Radio()


def radio_search(query):
    params = urllib.parse.urlencode({
        "name": query, "limit": 40, "hidebroken": "true",
        "order": "clickcount", "reverse": "true",
    })
    last = None
    for host in RADIO_SERVERS:
        try:
            req = urllib.request.Request(f"https://{host}/json/stations/search?{params}",
                                         headers={"User-Agent": "VoidStation/2.0"})
            with urllib.request.urlopen(req, timeout=6) as r:
                items = json.load(r)
            return [{
                "name": (i.get("name") or "").strip(),
                "url": i.get("url_resolved") or i.get("url"),
                "favicon": i.get("favicon") or "",
                "country": i.get("countrycode") or "",
                "tags": (i.get("tags") or "")[:60],
                "bitrate": i.get("bitrate") or 0,
            } for i in items if (i.get("url_resolved") or i.get("url"))]
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"Senderverzeichnis nicht erreichbar ({last})")



_POPULAR: dict = {}                             # Land -> (Zeitpunkt, Sender); 6 h zwischenspeichern


def radio_popular(cc, limit=24):
    """Meistgehoerte Sender eines Landes (radio-browser.info, nach Klicks) – Vorschlaege im Radio."""
    cc = (cc or "").upper()
    if not re.fullmatch(r"[A-Z]{2}", cc):
        return []
    hit = _POPULAR.get(cc)
    if hit and time.time() - hit[0] < 6 * 3600:
        return hit[1]
    params = urllib.parse.urlencode({"countrycode": cc, "limit": limit * 2, "hidebroken": "true",
                                     "order": "clickcount", "reverse": "true"})
    last = None
    for host in RADIO_SERVERS:
        try:
            req = urllib.request.Request(f"https://{host}/json/stations/search?{params}",
                                         headers={"User-Agent": "VoidStation/2.0"})
            with urllib.request.urlopen(req, timeout=6) as r:
                items = json.load(r)
            out, seen = [], set()
            for i in items:
                url = i.get("url_resolved") or i.get("url")
                name = (i.get("name") or "").strip()
                if not url or not name or name.lower() in seen:     # gleicher Sender mehrfach (andere Bitrate)
                    continue
                seen.add(name.lower())
                out.append({"name": name, "url": url, "favicon": i.get("favicon") or "", "country": cc,
                            "tags": (i.get("tags") or "")[:60]})
            out = out[:limit]
            _POPULAR[cc] = (time.time(), out)
            return out
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"Senderverzeichnis nicht erreichbar ({last})")

def favs_load():
    try:
        return json.loads(FAVS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def favs_save(items):
    tmp = FAVS.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(FAVS)


# ---------------------------------------------------------------------------
#  Lautstaerke (PipeWire / wpctl)
# ---------------------------------------------------------------------------
def volume_get():
    r = run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
    if not r or r.returncode != 0:
        return None
    parts = r.stdout.split()                 # "Volume: 0.45 [MUTED]"
    try:
        return {"level": round(float(parts[1]) * 100), "muted": "[MUTED]" in r.stdout}
    except (IndexError, ValueError):
        return None


def volume_set(action):
    sink = "@DEFAULT_AUDIO_SINK@"
    cmds = {
        "up": ["wpctl", "set-volume", "-l", "1.0", sink, "5%+"],
        "down": ["wpctl", "set-volume", sink, "5%-"],
        "mute": ["wpctl", "set-mute", sink, "toggle"],
    }
    if action in cmds:
        run(cmds[action])
    return volume_get()


# ---------------------------------------------------------------------------
#  Einstellungen (Skalierung, Aufloesung, Audioausgang, Netzwerk)
# ---------------------------------------------------------------------------
SETTINGS = BASE / "settings.json"
DEFAULTS: dict[str, Any] = {"scale": 1.75, "resolution": None, "cursor_theme": "Bibata-Modern-Ice", "cursor_size": 48, "lang": None, "theme": "default-dark",
            "sysupd_days": 90, "padmouse": True, "covers_auto": True, "covers_embed": False, "audio_auto": True,
            "emu_fullscreen": True, "save_backup": True, "rom_covers": True,
            "rate": None, "match_rate": False, "osk_layout": None, "osk_mode": "auto"}
# Bildschirmtastatur: Belegungen (Qt: VS/OskLayouts.js, gleiche Kennungen) und wann die Tasten zu sehen sind
OSK_LAYOUTS = ("de", "us", "gb", "fr", "es", "it", "br", "nl", "lv", "hu", "pl", "cz", "sk", "ro", "tr", "dk", "ee", "is", "no",
               "fi", "se", "vi", "gr", "ru", "ua", "hi", "ta", "ml", "th", "ko")
OSK_MODES = ("auto", "always", "keyboard")      # automatisch / immer / nicht mit angeschlossener Tastatur
SYSUPD_DAYS = (30, 60, 90)                  # Erinnerung an Systemupdates (ohne VoidStation-Update) nach … Tagen
# Sprachen der Oberflaeche: Texte in web/i18n/<id>.json, fehlende Texte kommen aus en.json, dann aus de.json.
# Anzeige immer in der eigenen Sprache. Je Sprache auch das Locale fuer gestartete Programme (LANG/LANGUAGE) und
# die Firefox-Sprache (Menues nur mit installiertem Sprachpaket, Webseiten wie YouTube immer).
# Neue Sprache: Zeile hier + web/i18n/<id>.json (build.sh prueft Schluessel und Platzhalter gegen de.json).
LANG_TABLE = [  # (id, Name, Locale, Firefox-Sprache)
    ("de", "Deutsch", "de_DE", "de"),
    ("en", "English", "en_US", "en-US"),
    ("id", "Bahasa Indonesia", "id_ID", "id"),
    ("ms", "Bahasa Melayu", "ms_MY", "ms"),
    ("cs", "Čeština", "cs_CZ", "cs"),
    ("da", "Dansk", "da_DK", "da"),
    ("et", "Eesti", "et_EE", "et"),
    ("es", "Español", "es_ES", "es-ES"),
    ("fr", "Français", "fr_FR", "fr"),
    ("is", "Íslenska", "is_IS", "is"),
    ("it", "Italiano", "it_IT", "it"),
    ("lv", "Latviešu", "lv_LV", "lv"),
    ("hu", "Magyar", "hu_HU", "hu"),
    ("nl", "Nederlands", "nl_NL", "nl"),
    ("nb", "Norsk bokmål", "nb_NO", "nb-NO"),
    ("pl", "Polski", "pl_PL", "pl"),
    ("pt-BR", "Português (Brasil)", "pt_BR", "pt-BR"),
    ("ro", "Română", "ro_RO", "ro"),
    ("sk", "Slovenčina", "sk_SK", "sk"),
    ("fi", "Suomi", "fi_FI", "fi"),
    ("sv", "Svenska", "sv_SE", "sv-SE"),
    ("vi", "Tiếng Việt", "vi_VN", "vi"),
    ("tr", "Türkçe", "tr_TR", "tr"),
    ("el", "Ελληνικά", "el_GR", "el"),
    ("ru", "Русский", "ru_RU", "ru"),
    ("uk", "Українська", "uk_UA", "uk"),
    ("hi", "हिन्दी", "hi_IN", "hi-IN"),
    ("ta", "தமிழ்", "ta_IN", "ta"),
    ("ml", "മലയാളം", "ml_IN", "ml"),
    ("th", "ไทย", "th_TH", "th"),
    ("ja", "日本語", "ja_JP", "ja"),
    ("ko", "한국어", "ko_KR", "ko"),
    ("zh-CN", "简体中文", "zh_CN", "zh-CN"),
    ("zh-TW", "繁體中文", "zh_TW", "zh-TW"),
]
LANGS = [{"id": i, "label": n} for i, n, _, _ in LANG_TABLE]
CURSOR_SIZES = [32, 48, 64, 80, 96]
CURSOR_NAMES = {"Bibata-Modern-Ice": "Hell", "Bibata-Modern-Classic": "Dunkel", "Adwaita": "Adwaita"}
SCALES = [1.0, 1.25, 1.5, 1.75, 2.0, 2.25]


def available_themes():
    td = WEB / "themes"
    if td.is_dir():
        found = [p.stem for p in sorted(td.glob("*.css"))]
        if found:
            return found
    return ["default-dark", "default-light", "high-contrast", "nord"]


def settings_load():
    s = dict(DEFAULTS)
    try:
        s.update(json.loads(SETTINGS.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return s


def cmdline_value(name):
    """Wert eines Kernel-Parameters name=wert (z. B. voidstation.lang aus dem Startmenue des Sticks)."""
    try:
        for a in Path("/proc/cmdline").read_text().split():
            if a.startswith(name + "="):
                return a.split("=", 1)[1]
    except OSError:
        pass
    return None


def ui_lang(s=None):
    """Sprache der Oberflaeche: Einstellung, im Live-System sonst die Sprache aus dem Startmenue,
    sonst aus LANG der Sitzung (pt_BR.UTF-8 -> pt-BR, en_GB.UTF-8 -> en), sonst Deutsch."""
    ids = {l["id"] for l in LANGS}
    lang = (s or settings_load()).get("lang")
    if lang in ids:
        return lang
    if Path("/etc/voidstation-live").exists() and cmdline_value("voidstation.lang") in ids:
        return cmdline_value("voidstation.lang")
    env = (os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or "").split(".")[0]
    for cand in (env.replace("_", "-"), env.split("_")[0]):
        if cand in ids:
            return cand
    return "de"



# Land fuer Radio und Fernsehen ("region" in settings.json, ISO-Code wie DE). Vorgabe: das Land der Sprache, in der
# VoidStation installiert wurde. Je Sprache die Laender, in denen sie zu Hause ist – das erste ist der Standard; liegt die
# Zeitzone in einem der anderen, gilt dieses (de + Europe/Vienna -> AT, fr + Europe/Brussels -> BE, en + Europe/London -> GB).
LANG_REGIONS = {
    "de": ["DE", "AT", "CH", "LU", "LI", "BE"], "en": ["US", "GB", "CA", "IE", "AU", "NZ", "ZA", "IN", "MT"],
    "cs": ["CZ"], "sk": ["SK"], "fr": ["FR", "BE", "CH", "LU", "CA", "MC"],
    "es": ["ES", "MX", "AR", "CO", "CL", "PE", "VE", "UY"], "it": ["IT", "CH", "SM"], "lv": ["LV"], "hu": ["HU"],
    "nl": ["NL", "BE"], "pl": ["PL"], "pt-BR": ["BR", "PT"], "el": ["GR", "CY"], "ru": ["RU", "BY", "KZ"], "uk": ["UA"],
    "ja": ["JP"], "ro": ["RO"], "tr": ["TR"], "ko": ["KR"], "zh-CN": ["CN"], "zh-TW": ["TW"],
    "da": ["DK"], "sv": ["SE", "FI"], "nb": ["NO"], "is": ["IS"], "fi": ["FI"], "et": ["EE"],
    "id": ["ID"], "ms": ["MY", "SG"], "vi": ["VN"], "th": ["TH"], "hi": ["IN"], "ta": ["IN", "LK", "SG", "MY"], "ml": ["IN"],
}
# Schnellwahl der Laender im Fernsehen je Sprache (das eigene Land kommt immer zuerst), der Rest unter "Weitere Laender"
TV_QUICK = {
    "de": ["DE", "AT", "CH"], "en": ["US", "GB", "CA"], "cs": ["CZ", "SK", "AT"], "sk": ["SK", "CZ", "HU"],
    "fr": ["FR", "BE", "CH"], "es": ["ES", "MX", "AR"], "it": ["IT", "CH", "SM"], "lv": ["LV", "LT", "EE"],
    "hu": ["HU", "AT", "SK"], "nl": ["NL", "BE", "DE"], "pl": ["PL", "DE", "CZ"], "pt-BR": ["BR", "PT"],
    "el": ["GR", "CY"], "ru": ["RU", "BY", "KZ"], "uk": ["UA", "PL"], "ja": ["JP", "KR", "TW"],
    "ro": ["RO", "IT", "ES"], "tr": ["TR", "DE", "CY"], "ko": ["KR", "JP", "US"], "zh-CN": ["CN", "JP", "KR"],
    "zh-TW": ["TW", "JP", "KR"],
    "da": ["DK", "SE", "NO"], "sv": ["SE", "FI", "NO"], "nb": ["NO", "SE", "DK"], "is": ["IS", "DK", "NO"],
    "fi": ["FI", "SE", "EE"], "et": ["EE", "FI", "LV"],
    "id": ["ID", "MY", "SG"], "ms": ["MY", "ID", "SG"], "vi": ["VN", "TH", "SG"], "th": ["TH", "VN", "JP"],
    "hi": ["IN", "GB", "US"], "ta": ["IN", "LK", "SG"], "ml": ["IN", "AE", "GB"],
}


def tz_current():
    """Zeitzone des Systems (Ziel von /etc/localtime, z. B. Europe/Berlin), sonst ''."""
    try:
        t = os.readlink("/etc/localtime")
    except OSError:
        return ""
    return t.split("zoneinfo/", 1)[1] if "zoneinfo/" in t else ""


_TZ_CC: dict | None = None


def tz_country(tz):
    """Land einer Zeitzone laut zone.tab (Europe/Vienna -> AT), sonst ''."""
    global _TZ_CC
    if _TZ_CC is None:
        _TZ_CC = {}
        try:
            for line in Path("/usr/share/zoneinfo/zone.tab").read_text(encoding="utf-8").splitlines():
                f = line.split("\t")
                if len(f) >= 3 and not line.startswith("#"):
                    _TZ_CC[f[2]] = f[0]
        except OSError:
            pass
        _TZ_CC.setdefault("Europe/Kyiv", "UA")                # aeltere tzdata kennt nur Europe/Kiev
    return _TZ_CC.get(tz or "", "")


def region_for(lang, tz=""):
    """Vorgabe-Land fuer eine Sprache: das Land der Zeitzone, wenn die Sprache dort zu Hause ist, sonst das erste."""
    cands = LANG_REGIONS.get(lang) or LANG_REGIONS["de"]
    cc = tz_country(tz)
    return cc if cc in cands else cands[0]


def region(s=None):
    """Land fuer Radio und Fernsehen: Einstellung (setzt der Installer), sonst aus Sprache und Zeitzone."""
    s = s or settings_load()
    r = s.get("region")
    if isinstance(r, str) and re.fullmatch(r"[A-Z]{2}", r):
        return r
    return region_for(ui_lang(s), tz_current())


def region_quick(s=None):
    """Schnellwahl der Laender im Fernsehen: eigenes Land zuerst, dann die uebrigen der Sprache (3 Stueck)."""
    s = s or settings_load()
    r = region(s)
    return [r] + [c for c in TV_QUICK.get(ui_lang(s), []) if c != r][:2]

# Sprache fuer gestartete Programme: VLC, PCManFM und andere GTK-/Qt-Programme folgen LANG/LANGUAGE,
# Firefox (YouTube) bekommt Oberflaechen- und Webseiten-Sprache ueber sein Profil
LOCALES = {i: f"{loc}.UTF-8" for i, _, loc, _ in LANG_TABLE}
LANGUAGE_ENV = {i: f"{loc}:{loc.split('_')[0]}" for i, _, loc, _ in LANG_TABLE}
FIREFOX_LANG = {i: (ff, ", ".join(dict.fromkeys([loc.replace("_", "-"), loc.split("_")[0], "en-US", "en"])))
                for i, _, loc, ff in LANG_TABLE}
_LOCALES_AVAIL = None


def locale_available(name):
    global _LOCALES_AVAIL
    norm = lambda v: v.strip().lower().replace("utf-8", "utf8")
    if _LOCALES_AVAIL is None:
        try:
            out = subprocess.run(["locale", "-a"], capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            out = ""
        _LOCALES_AVAIL = {norm(l) for l in out.split()}
    return norm(name) in _LOCALES_AVAIL


def app_env():
    """Umgebung fuer Programme aus den Kacheln: Sprache der Oberflaeche. Fehlt das Locale (z. B. en_US nicht
    erzeugt), bleibt LANG wie es ist und nur LANGUAGE waehlt die Uebersetzung (gettext, Qt)."""
    lang = ui_lang()
    env = dict(os.environ)
    for k in ("LC_ALL", "LC_MESSAGES"):
        env.pop(k, None)
    if locale_available(LOCALES[lang]):
        env["LANG"] = LOCALES[lang]
    env["LANGUAGE"] = LANGUAGE_ENV[lang]
    if IME_STATE["on"]:                              # Japanisch, Koreanisch, Chinesisch: Eingabe ueber fcitx5
        env.update(IME_ENV)
    return env


# ---- Eingabemethode fuer Japanisch, Koreanisch und Chinesisch (fcitx5) ----------------------------------------------
# Mit echter Tastatur tippt man diese Sprachen ueber eine Eingabemethode: Koreanisch setzt Silben zusammen, Chinesisch
# und Japanisch waehlen Schriftzeichen aus einer Kandidatenliste. Steht die Oberflaeche auf ja/ko/zh, installiert
# VoidStation fcitx5 samt Engine der Sprache (Auftrag im Hintergrund, nur mit Internet, nicht im Live-System),
# startet es und gibt den Programmen aus den Kacheln die Umgebung dafuer mit; die Startseite bekommt sie ueber im.sh
# (Openbox-Autostart) beim naechsten Start. Umschalten Lateinisch <-> Landesschrift: Strg+Leertaste, auf koreanischen
# bzw. japanischen Tastaturen auch die Hangul- bzw. Zenkaku-Taste (Vorgaben von fcitx5). Erst lateinisch, damit
# Steuerung und Bildschirmtastatur unveraendert bleiben. Bei allen anderen Sprachen laeuft fcitx5 nicht; die Pakete
# bleiben. Paketnamen stehen auch in der Freigabeliste (install-head.sh, update-head.sh).
IME_PKGS = ("fcitx5", "fcitx5-gtk+3", "fcitx5-gtk4", "fcitx5-qt6")
IME_ENGINES = {"ko": ("fcitx5-hangul", "hangul"), "zh-CN": ("fcitx5-chinese-addons", "pinyin"),
               "zh-TW": ("fcitx5-chewing", "chewing"), "ja": ("fcitx5-mozc", "mozc")}
IME_ENGINES_32 = {"ja": ("fcitx5-anthy", "anthy")}            # Mozc gibt es nur fuer x86_64
IME_ENV = {"GTK_IM_MODULE": "fcitx", "QT_IM_MODULE": "fcitx", "XMODIFIERS": "@im=fcitx"}
IME_STATE = {"on": False, "asked": None}
IME_LOCK = threading.Lock()


def ime_engine(lang):
    """(Paket, fcitx5-Name) der Eingabemethode fuer die Sprache, sonst None."""
    if lang in IME_ENGINES_32 and os.uname().machine != "x86_64":
        return IME_ENGINES_32[lang]
    return IME_ENGINES.get(lang)


def ime_missing(lang):
    eng = ime_engine(lang)
    return [p for p in (*IME_PKGS, eng[0]) if not xbps_installed(p)] if eng else []


def xkb_layout():
    """Erstes Tastaturlayout der Sitzung (Installer bzw. Startmenue des Sticks), sonst us."""
    try:
        m = re.search(r'XkbLayout"\s+"([^"]+)"', Path("/etc/X11/xorg.conf.d/00-keyboard.conf").read_text())
        if m:
            return m.group(1).split(",")[0].strip() or "us"
    except OSError:
        pass
    return "us"


def ime_config(engine):
    """fcitx5-Profil: lateinische Tastatur zuerst (= aus), dann die Engine. Nur neu schreiben, wenn sich Engine oder
    Tastatur geaendert haben – sonst bleiben Aenderungen aus dem fcitx5-Konfigurationsprogramm erhalten.
    Kandidatenfenster: Schrift fuer den Fernseher, hell/dunkel nach dem VoidStation-Theme."""
    d = Path.home() / ".config" / "fcitx5"
    kb = xkb_layout()
    mark = d / ".voidstation"
    want = f"{engine} {kb}"
    try:
        d.mkdir(parents=True, exist_ok=True)
        if not (mark.read_text().strip() == want if mark.exists() else False) or not (d / "profile").exists():
            (d / "profile").write_text(
                "[Groups/0]\nName=VoidStation\nDefault Layout=" + kb + "\nDefaultIM=" + engine + "\n\n"
                "[Groups/0/Items/0]\nName=keyboard-" + kb + "\nLayout=\n\n"
                "[Groups/0/Items/1]\nName=" + engine + "\nLayout=\n\n"
                "[GroupOrder]\n0=VoidStation\n", encoding="utf-8")
            mark.write_text(want + "\n")
        dark = theme_is_dark(settings_load().get("theme") or DEFAULTS["theme"])
        (d / "conf").mkdir(exist_ok=True)
        _ini_flat(d / "conf" / "classicui.conf", {"Font": '"Sans 16"', "MenuFont": '"Sans 14"',
                                                  "Theme": "default-dark" if dark else "default",
                                                  "Vertical Candidate List": "False"})
    except OSError as e:
        log("fcitx5-Einstellungen nicht geschrieben:", e)


def _ini_flat(path, vals):
    """Schluessel=Wert-Datei ohne Abschnitte (fcitx5) setzen, andere Zeilen behalten."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    keep = [l for l in lines if l.split("=", 1)[0].strip() not in vals]
    path.write_text("\n".join(keep + [f"{k}={v}" for k, v in vals.items()]) + "\n", encoding="utf-8")


def ime_running():
    r = run(["pgrep", "-u", str(os.getuid()), "-x", "fcitx5"])
    return bool(r and r.returncode == 0)


def ime_sync():
    """Eingabemethode passend zur Sprache: einrichten und starten bzw. beenden. Fehlen Pakete, laeuft ein Auftrag,
    der am Ende ime_sync() erneut aufruft. Beim Start des Launchers und nach jedem Sprachwechsel."""
    with IME_LOCK:
        lang = ui_lang()
        eng = ime_engine(lang)
        im_sh = BASE / "im.sh"
        if not eng:
            if IME_STATE["on"] or ime_running():
                run(["pkill", "-u", str(os.getuid()), "-x", "fcitx5"])
                log("Eingabemethode beendet")
            IME_STATE["on"] = False
            im_sh.unlink(missing_ok=True)
            return
        missing = ime_missing(lang)
        if missing:
            IME_STATE["on"] = False
            if LIVE or not net_online() or JOBS.busy() or IME_STATE["asked"] == lang:
                return                                   # spaeter (naechster Start / Sprachwechsel)
            IME_STATE["asked"] = lang                    # pro Sprache nur ein Versuch je Launcher-Lauf
            name = i18n_text("ime.job", lang) or "fcitx5"
            log("Eingabemethode fehlt:", " ".join(missing))
            try:
                JOBS.start("ime", {"id": "ime", "name": name, "pkgs": missing})
            except RuntimeError:
                IME_STATE["asked"] = None
            return
        ime_config(eng[1])
        im_sh.write_text("".join(f"export {k}={v}\n" for k, v in IME_ENV.items()))
        if not ime_running():
            try:
                with open(BASE / "logs" / "fcitx5.log", "w") as out:
                    subprocess.Popen(["fcitx5", "-d", "--replace"], stdin=subprocess.DEVNULL, stdout=out,
                                     stderr=subprocess.STDOUT, start_new_session=True)
                log("Eingabemethode gestartet:", eng[1])
            except OSError as e:
                log("fcitx5 startet nicht:", e)
                return
        else:
            run(["fcitx5-remote", "-r"])                # Profil neu einlesen (Sprachwechsel ja <-> ko …)
        IME_STATE["on"] = True


def firefox_prefs(args, lang, dark):
    """Firefox mit --profile (Kacheln: YouTube, Mediatheken, Firefox): vor jedem Start in user.js setzen
    - Sprache der Oberflaeche: intl.locale.requested (Menues), intl.accept_languages (Webseiten, z. B. YouTube)
    - hell/dunkel nach dem VoidStation-Theme: Webseiten (prefers-color-scheme) und Leisten
    - Erweiterungen im Programmordner bei jedem Start einlesen (VoidStation-Tastatur auch in bestehenden Profilen)"""
    try:
        uj = Path(args[args.index("--profile") + 1]) / "user.js"
        old = uj.read_text(encoding="utf-8")
    except (ValueError, IndexError, OSError):
        return
    req, acc = FIREFOX_LANG[lang]
    scheme = 0 if dark else 1                    # 0 = dunkel, 1 = hell (2 waere "wie das System")
    want = {"intl.locale.requested": req, "intl.accept_languages": acc,
            "layout.css.prefers-color-scheme.content-override": scheme,
            "browser.theme.toolbar-theme": scheme, "browser.theme.content-theme": scheme,
            # Erweiterungen im Programmordner (VoidStation-Tastatur) bei jedem Start einlesen, nicht nur nach Firefox-Updates
            "extensions.startupScanScopes": 4}
    out, seen = [], set()
    for line in old.splitlines():
        m = re.match(r'\s*user_pref\("([^"]+)"', line)
        if m and m.group(1) in want:
            if m.group(1) in seen:
                continue
            seen.add(m.group(1))
            line = f'user_pref("{m.group(1)}", {json.dumps(want[m.group(1)])});'
        out.append(line)
    out += [f'user_pref("{k}", {json.dumps(v)});' for k, v in want.items() if k not in seen]
    new = "\n".join(out) + "\n"
    if new != old:
        uj.write_text(new, encoding="utf-8")


def brave_origin_prepare():
    """Brave Origin fragt beim allerersten Start nach einem Kauf, unter Linux ist es kostenlos ("Proceed with Origin for
    free on Linux"). Ein neues Profil bekommt diese Antwort schon vorab (brave.origin.free_tier_accepted in Local
    State, wie nach dem Klick); ein vorhandenes bleibt unberuehrt. Kaufen geht weiter ueber die Einstellungen."""
    ls = Path.home() / ".config/BraveSoftware/Brave-Origin/Local State"
    if ls.exists():
        return
    try:
        ls.parent.mkdir(parents=True, exist_ok=True)
        ls.write_text(json.dumps({"brave": {"origin": {"free_tier_accepted": True}}}), encoding="utf-8")
    except OSError as e:
        log("Brave Origin: Local State nicht angelegt:", e)


LIBREWOLF_KBD = Path("/usr/local/share/voidstation/keyboard.xpi")
LIBREWOLF_PREFS = (                                 # librewolf.overrides.cfg, Block zwischen den Markierungen
    '// VoidStation-Tastatur (Bildschirmtastatur): eigene, nicht von Mozilla signierte Erweiterung im Profil\n'
    'defaultPref("xpinstall.signatures.required", false);\n'
    'defaultPref("extensions.autoDisableScopes", 14);\n'      # Profil-Bereich (1) nicht abschalten, die anderen schon
    'defaultPref("extensions.startupScanScopes", 1);\n')       # Profilordner bei jedem Start einlesen


def librewolf_keyboard():
    """LibreWolf (Firefox-Ableger aus dem AppCenter) liest den Programmordner von Void-Firefox nicht. Vor jedem Start:
    Erweiterung VoidStation-Tastatur (dieselbe .xpi wie Firefox) in den Ordner extensions/ jedes Profils, in
    librewolf.overrides.cfg die Signaturpflicht aus (LibreWolf erlaubt das, Firefox nicht). Ein neues Profil bekommt
    sie beim zweiten Start. Eigene Zeilen in der .cfg bleiben."""
    if not LIBREWOLF_KBD.is_file():
        return
    data = LIBREWOLF_KBD.read_bytes()
    home = Path.home()
    for root in (home / ".librewolf", home / ".config/librewolf", home / ".config/librewolf/librewolf"):
        ini = root / "profiles.ini"
        if not ini.is_file():
            continue
        try:
            cfg = root / "librewolf.overrides.cfg"
            old = cfg.read_text(encoding="utf-8") if cfg.exists() else ""
            body = re.sub(r"\n?// >>> VoidStation.*?// <<< VoidStation\n?", "\n", old, flags=re.S).strip("\n")
            new = (body + "\n\n" if body else "") + "// >>> VoidStation\n" + LIBREWOLF_PREFS + "// <<< VoidStation\n"
            if new != old:
                cfg.write_text(new, encoding="utf-8")
            for m in re.finditer(r"^Path=(.+)$", ini.read_text(encoding="utf-8", errors="replace"), re.M):
                prof = Path(m.group(1).strip())
                prof = prof if prof.is_absolute() else root / prof
                if not prof.is_dir():
                    continue
                dst = prof / "extensions" / "keyboard@voidstation.de.xpi"
                if not dst.exists() or dst.read_bytes() != data:
                    dst.parent.mkdir(exist_ok=True)
                    dst.write_bytes(data)
                    log("LibreWolf: VoidStation-Tastatur in", prof.name)
        except OSError as e:
            log("LibreWolf: Tastatur nicht eingerichtet:", e)


# ---------------------------------------------------------------------------
#  DOSBox Staging: Grundeinstellung beim ersten Start + Sprache/Tastatur/Laufwerk C vor jedem Start
# ---------------------------------------------------------------------------
# Zwei Dateien, DOSBox Staging liest sie nacheinander (spaetere gewinnt, [autoexec] wird zusammengefuegt):
#  1. ~/.config/dosbox/dosbox-staging.conf – Grundeinstellung, legt VoidStation nur an, wenn es sie noch nicht gibt;
#     danach gehoert sie dem Benutzer (eigene Aenderungen bleiben).
#  2. <BASE>/dosbox/voidstation.conf (--conf) – vor jedem Start neu: Sprache der Oberflaeche, Tastatur wie unter X,
#     Laufwerk C = ~/share/ROMs/dos. Wer davon abweichen will: dosbox --set … oder eigener Kachel-Befehl mit --conf.
DOSBOX_LANG = {"de": "de", "en": "en", "es": "es", "fr": "fr", "it": "it", "nl": "nl", "pl": "pl", "pt-BR": "br", "ru": "ru"}
# X-Tastaturbelegung -> DOS-Tastaturcode (FreeDOS KEYB); unbekannt -> auto
DOSBOX_KEYB = {"de": "gr", "at": "gr", "ch": "sg", "us": "us", "gb": "uk", "fr": "fr", "it": "it", "es": "sp",
               "nl": "nl", "be": "be", "pl": "pl", "hu": "hu", "ru": "ru", "ua": "ur", "gr": "gk", "br": "br",
               "pt": "po", "dk": "dk", "se": "sv", "no": "no", "fi": "su", "cz": "cz", "sk": "sk", "tr": "tr", "ro": "ro",
               "is": "is161", "ee": "ee"}
DOSBOX_PRIMARY = """# DOSBox Staging – Grundeinstellung von VoidStation
# Angelegt beim ersten Start ueber die Kachel. Die Datei gehoert jetzt dir: Aenderungen bleiben erhalten,
# VoidStation aendert hier nur, was du in der Spieleliste unter "Optionen" umstellst. Geloescht wird sie
# beim naechsten Start neu angelegt.
# Nicht aufgefuehrte Einstellungen haben den Standardwert von DOSBox Staging; alle Einstellungen
# mit Erklaerung: https://www.dosbox-staging.org/manual/
#
# Sprache, Tastatur und Laufwerk C setzt VoidStation vor jedem Start in einer eigenen Datei
# (~/.local/share/voidstation/dosbox/voidstation.conf): Sprache wie die Oberflaeche, Tastatur wie
# eingestellt, C: = Freigabe share/ROMs/dos.

[sdl]
# Fernseher: gleich im Vollbild (Alt+Enter schaltet um)
fullscreen = true

[cpu]
# 386er mit dynamischem Kern: laeuft mit den meisten DOS-Spielen. Zu schnell/zu langsam?
# Ctrl+F11 / Ctrl+F12 aendern die Geschwindigkeit um je 500 Zyklen, oder cpu_cycles hier anpassen
# (Richtwerte: 286 = 1500, 386DX-33 = 6000, 486DX/2-66 = 25000, Pentium 90 = 50000).
core                 = dynamic
cputype              = 386
cpu_cycles           = 4000
cpu_cycles_protected = 60000
cycleup              = 500
cycledown            = 500
"""


def x_keyboard_layout():
    """Erste X-Tastaturbelegung (setxkbmap -query), sonst aus 00-keyboard.conf, sonst None."""
    r = run(["setxkbmap", "-query"])
    m = re.search(r"^layout:\s*([A-Za-z]+)", r.stdout, re.M) if r and r.returncode == 0 else None
    if m:
        return m.group(1).lower()
    try:
        t = Path("/etc/X11/xorg.conf.d/00-keyboard.conf").read_text(encoding="utf-8")
        m = re.search(r'XkbLayout"\s+"([A-Za-z]+)', t)
        return m.group(1).lower() if m else None
    except OSError:
        return None


def dosbox_primary():
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "dosbox" / "dosbox-staging.conf"


def dosbox_primary_ensure():
    """Grundeinstellung anlegen, falls es noch keine gibt. -> Pfad"""
    primary = dosbox_primary()
    if not primary.exists():
        primary.parent.mkdir(parents=True, exist_ok=True)
        primary.write_text(DOSBOX_PRIMARY, encoding="utf-8")
        log("DOSBox: Grundeinstellung angelegt:", primary)
    return primary


DOSBOX_SOUNDFONT = Path("/usr/share/soundfonts/FluidR3_GM.sf2")       # Void-Paket soundfont-fluid (MIT, rund 140 MB)
_DOSBOX_SF_TRIED: list = []


def dosbox_midi_conf():
    """General MIDI ueber den eingebauten FluidSynth, sobald das Soundfont da ist – sonst bleibt ein Spiel, das im eigenen
    SETUP auf "General MIDI" steht, stumm ("auto" nimmt in DOSBox Staging 0.82 weder fluidsynth noch mt32, midi.cpp).
    Nur, solange der Nutzer in seiner eigenen Datei nichts anderes gewaehlt hat. Fehlt das Soundfont, wird es einmal je
    Lauf im Hintergrund nachinstalliert (catalog.json: optional) und gilt ab dem naechsten Start von DOSBox."""
    try:
        own = ini_read(dosbox_primary())
        if own.get("midi", {}).get("mididevice", "auto").strip().lower() != "auto" or "soundfont" in own.get("fluidsynth", {}):
            return ""
        if DOSBOX_SOUNDFONT.is_file():
            return f"[midi]\nmididevice = fluidsynth\n\n[fluidsynth]\nsoundfont = {DOSBOX_SOUNDFONT}\n\n"
        if not _DOSBOX_SF_TRIED:
            _DOSBOX_SF_TRIED.append(1)

            def fetch():
                r = run(["sudo", "-n", PKG_HELPER, "install", "soundfont-fluid"], timeout=1800)     # rund 140 MB
                log("DOSBox: Soundfont fuer General MIDI", "installiert" if r and r.returncode == 0 else "nicht installiert")
            threading.Thread(target=fetch, daemon=True).start()
    except Exception as e:  # noqa: BLE001 – darf den Start nie verhindern
        log("DOSBox: MIDI:", e)
    return ""


def dosbox_game_conf(game):
    """Optionen nur fuer dieses Spiel (Spieleliste): Abschnitte fuer die Datei, die VoidStation vor jedem Start schreibt."""
    if not game:
        return ""
    sections: dict = {}
    try:
        own = emu_opts_game("dosbox", game.name)
        idx = _OPT_INDEX["dosbox"]
        with EMU_LOCK:
            st = emu_state_load()
        # Spielprofil (z. B. CPU-Tempo): nur, wo die Option allgemein auf Standard steht und fuer das Spiel nichts gewaehlt ist
        for oid, v in emu_profile("dosbox", game).items():
            opt = idx.get(oid)
            if opt and oid not in own and _opt_game_choice(opt, v) and _opt_auto_on("dosbox", opt, st):
                sections.setdefault(opt["section"], {}).update(_opt_writes(opt, _opt_choice(opt, v)))
        for section, values in emu_opts_game_writes("dosbox", game.name):
            sections.setdefault(section, {}).update(values)
    except Exception as e:  # noqa: BLE001 – darf den Start nie verhindern
        log("DOSBox: Optionen des Spiels:", e)
    return "".join(f"[{sec}]\n" + "".join(f"{k} = {v}\n" for k, v in vals.items()) + "\n" for sec, vals in sections.items())


def dosbox_prepare(args):
    """Vor dem Start von DOSBox Staging: Grundeinstellung anlegen (falls noch keine da ist),
    VoidStation-Datei schreiben und per --conf anhaengen. Gibt die Befehlszeile zurueck."""
    if "--noprimaryconf" in args:
        return args
    home = Path.home()
    rom_dir = home / "share" / "ROMs" / "dos"
    vs_conf = BASE / "dosbox" / "voidstation.conf"
    # Spiel aus der Spieleliste (Datei oder Ordner unter share/ROMs/dos): ueber [autoexec] starten, danach beenden
    game, own_conf = None, None
    if len(args) > 1:
        t = Path(str(args[-1]))
        try:
            inside = t.resolve().is_relative_to(rom_dir.resolve()) and t.resolve() != rom_dir.resolve()
        except OSError:
            inside = False
        if inside and t.exists():
            args = list(args[:-1])
            if t.suffix.lower() == ".conf":
                own_conf = t                      # eigene .conf bringt ihr eigenes [autoexec] mit
            else:
                game = t
    try:
        rom_dir.mkdir(parents=True, exist_ok=True)
        dosbox_primary_ensure()
        keyb = DOSBOX_KEYB.get(x_keyboard_layout() or "", "auto")
        lang = DOSBOX_LANG.get(ui_lang(), "en")
        auto = "" if own_conf else dosbox_game_lines(game, rom_dir)
        vs_conf.parent.mkdir(parents=True, exist_ok=True)
        vs_conf.write_text(
            "# Von VoidStation vor jedem Start von DOSBox neu geschrieben – Aenderungen hier gehen verloren.\n"
            "# Eigene Einstellungen: ~/.config/dosbox/dosbox-staging.conf\n\n"
            f"[dosbox]\nlanguage = {lang}\n\n"
            f"[dos]\nkeyboardlayout = {keyb}\n\n"
            + dosbox_midi_conf() + dosbox_game_conf(game or own_conf) +
            f'[autoexec]\n{auto}', encoding="utf-8")
    except OSError as e:
        log("DOSBox: Einstellungen nicht geschrieben:", e)
        return args
    if str(vs_conf) not in args:
        args = [args[0], "--conf", str(vs_conf)] + list(args[1:])
    if own_conf:
        # Eigene .conf (z. B. von GOG) mountet meist relativ ("mount c ."): DOSBox loest das gegen das
        # Arbeitsverzeichnis auf – also das der .conf, nicht das Home, aus dem VoidStation startet
        args = list(args) + ["--working-dir", str(own_conf.parent), "--conf", str(own_conf)]
    return args


DOS_83 = re.compile(r"[A-Z0-9!#$%&'()@^_`{}~-]{1,8}(\.[A-Z0-9!#$%&'()@^_`{}~-]{1,3})?")


# Programme in Spielordnern, die nie das Spiel selbst sind: Installation/Einrichtung, DOS-Extender, Packer, Intros …
DOS_HELPERS = re.compile(r"(install|setup|config|setsound|setsnd|sndsetup|soundset|sound$|uninst|dos4gw|dos32a|cwsdpmi|"
                         r"pmodew|dpmi|pkunzip|pkzip|unzip|lha$|arj$|intro|readme|liesmich|catalog|order|help$|info$|"
                         r"drivers?$|ipxsetup|sersetup|crack|trainer)", re.I)


def dosbox_start_file(game):
    """Start-Datei eines Spielordners -> (Datei, Argumente) oder (None, ""). Der Reihe nach:
      1. start.txt im Ordner: erste Zeile = Start-Datei, ggf. mit Argumenten (z. B. "MTV.EXE" oder "GAME /nosound")
      2. genau eine .bat (ohne Hilfsprogramme) bzw. genau eine .exe/.com
      3. mehrere: die eine, deren Name zum Ordnernamen passt (DOOM/DOOM.EXE, mad-tv/MTV.EXE, monkey2/MONKEY2.EXE)
    Sonst nichts – lieber an der Eingabe stehen als das Falsche starten."""
    try:
        entries = [f for f in game.iterdir() if f.is_file()]
    except OSError:
        return None, ""
    by_name = {f.name.upper(): f for f in entries}
    st = next((f for f in entries if f.name.lower() == "start.txt"), None)
    if st:
        try:
            line = next((l.strip() for l in st.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()), "")
        except OSError:
            line = ""
        name, _, rest = line.partition(" ")
        name = name.upper()
        cand = [name] if "." in name else [name + ext for ext in (".BAT", ".EXE", ".COM")]
        hit = next((by_name[c] for c in cand if c in by_name), None)
        if hit:
            return hit, re.sub(r"[\r\n&|<>]", "", rest).strip()
        log("DOSBox: start.txt nennt keine vorhandene Datei:", line)
    files = sorted((f for f in entries if f.suffix.lower() in (".bat", ".exe", ".com")
                    and not DOS_HELPERS.match(f.stem)), key=lambda f: f.name.upper())
    bats = [f for f in files if f.suffix.lower() == ".bat"]
    if len(bats) == 1:
        return bats[0], ""
    if len(files) == 1:
        return files[0], ""
    # Name passt zum Ordner: gleich, Anfang des einen ist der andere, oder Kuerzel (Buchstaben der Reihe nach)
    alnum = lambda t: re.sub(r"[^a-z0-9]", "", t.lower())
    folder = alnum(game.name)

    def fits(f):
        stem = alnum(f.stem)
        if not stem or not folder:
            return False
        if stem == folder or folder.startswith(stem) or stem.startswith(folder):
            return True
        it = iter(folder)
        return len(stem) >= 2 and stem[0] == folder[0] and all(c in it for c in stem)
    pool = bats or files
    match = [f for f in pool if fits(f)]
    if len(match) == 1:
        return match[0], ""
    return None, ""


def dosbox_game_lines(game, root):
    """[autoexec]-Zeilen: Laufwerk C: und ggf. Spiel starten, danach DOSBox beenden.
    C: ist wie beim Start ohne Spiel die ganze Freigabe share/ROMs/dos – ein Spiel, das man in DOSBox selbst
    installiert hat (INSTALL.EXE nach C:\\SPIEL), findet so seine Pfade wieder. Nur ein Ordner, dessen Name kein
    DOS-Name ist (laenger als 8.3, Leerzeichen …), wird selbst zu C: – solche Ordner kommen vom PC und waeren unter
    DOS nur als SPIEL~1 erreichbar. Start-Datei im Ordner: dosbox_start_file; findet sie keine eindeutige (oder hat
    die einen langen Namen), bleibt es bei C: und der Eingabe.
    Vorher wird C: freigegeben: Eine aeltere Grundeinstellung mountet C: oft schon selbst ([autoexec] beider Dateien
    werden aneinandergehaengt), dann schlug unser mount fehl und das Spiel startete nicht."""
    head = "mount -u c > nul\n"
    if game is None:
        return head + f'mount c "{root}"\nc:\n'
    cd, args = "", ""
    if game.is_dir():
        pick, args = dosbox_start_file(game)
        if game.resolve().parent == root.resolve() and DOS_83.fullmatch(game.name.upper()):
            mount, cd = root, f"cd \\{game.name.upper()}\n"
        else:
            mount = game
    else:
        pick, mount = game, game.parent
    out = head + f'mount c "{mount}"\nc:\n' + cd
    if pick is not None and not DOS_83.fullmatch(pick.name.upper()):
        pick = None                               # langer Name: unter DOS nicht aufrufbar – nicht starten und beenden
    if pick is not None:
        out += ("call " if pick.suffix.lower() == ".bat" else "") + pick.name + (f" {args}" if args else "") + "\nexit\n"
    else:
        log("DOSBox: keine eindeutige Start-Datei in", game, "– bleibt an der Eingabe (start.txt hilft)")
    return out


def settings_save(s):
    tmp = SETTINGS.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=2), encoding="utf-8")
    tmp.replace(SETTINGS)


def cursor_themes():
    found = []
    for base in (Path("/usr/share/icons"), Path.home() / ".local/share/icons", Path.home() / ".icons"):
        for name in CURSOR_NAMES:
            if (base / name / "cursors").is_dir() and name not in found:
                found.append(name)
    return [n for n in CURSOR_NAMES if n in found]


def _ini_set(path, section, values):
    """Schluessel in einer einfachen INI-Datei setzen, Rest unveraendert lassen."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        lines = path.read_text().splitlines()
    except OSError:
        lines = []
    if f"[{section}]" not in lines:
        lines = [f"[{section}]"] + lines
    keys = set(values)
    lines = [l for l in lines if l.split("=", 1)[0].strip() not in keys]
    idx = lines.index(f"[{section}]") + 1
    for k, v in values.items():
        lines.insert(idx, f"{k}={v}")
    path.write_text("\n".join(lines) + "\n")


def theme_is_dark(theme):
    """Dunkles VoidStation-Theme? Nach der Hintergrundfarbe (--bg-main) der Theme-Datei – so passen auch
    neue Themes ohne Liste –, sonst nach dem Namen."""
    try:
        css = (WEB / "themes" / f"{theme}.css").read_text(encoding="utf-8")
        m = re.search(r"--bg-main:\s*#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", css)
        if m:
            h = m.group(1)
            if len(h) == 3:
                h = "".join(c * 2 for c in h)
            r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
            return 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.5
    except OSError:
        pass
    return "light" not in theme


def apply_color_scheme(dark):
    """Farbschema fuer Programme, die es ueber GSettings bzw. das Settings-Portal lesen (Flatpaks wie FreeTube,
    Chromium/Electron, GTK 4). Deren Einstellung "Systemvorgabe" war sonst immer hell. Laufende Programme
    bekommen die Aenderung ueber das Portal mit, soweit sie darauf hoeren."""
    if not shutil.which("gsettings"):
        return
    iface = "org.gnome.desktop.interface"
    for key, val in (("color-scheme", "prefer-dark" if dark else "prefer-light"),
                     ("gtk-theme", "Adwaita-dark" if dark else "Adwaita")):
        r = run(["gsettings", "set", iface, key, val], timeout=10)
        if (not r or r.returncode) and key == "color-scheme" and not dark:
            r = run(["gsettings", "set", iface, key, "default"], timeout=10)   # aeltere Schemas ohne prefer-light
        if not r or r.returncode:
            log("gsettings", key, "nicht gesetzt:", (r.stderr.strip() if r else "nicht ausfuehrbar"))


# Terminal (xterm) – eingestellt ueber ~/.Xresources, gilt fuer jedes neu geoeffnete Terminal (Kachel, Strg+Alt+T,
# Terminal-Apps wie htop, "Im Terminal" startende Programme):
#  - Farben nach dem Theme (hell/dunkel) mit ruhiger 16-Farben-Palette; Cyan = Petrol wie im Logo (Eingabeaufforderung,
#    Titelzeile von fastfetch). boldColors aus: fett bleibt dieselbe Farbe statt der grelleren "hellen" Variante.
#  - meldet sich als xterm-256color (sonst nutzen htop, nano & Co. nur 8 Farben), 10.000 Zeilen zum Zurueckscrollen
#  - Eingabemarke als blinkender senkrechter Strich (wie in Editoren und Browsern) statt Block
#  - Schrift DejaVu Sans Mono 14 (skaliert mit Xft.dpi), Strg + / Strg - groesser/kleiner, Strg 0 zurueck
#  - Einfuegen aus der Zwischenablage wie ueberall: Strg+Umschalt+V, Umschalt+Einfg und Rechtsklick (Controller: L2).
#    Von Haus aus fuegt xterm nur die Markierung (PRIMARY) ein, nicht das mit Strg+C Kopierte. Markieren kopiert
#    zugleich in die Zwischenablage, Strg+Umschalt+C ebenso.
XTERM_PALETTE = {
    True: {"background": "#111316", "foreground": "#dcdcdc", "cursorColor": "#dcdcdc",
           "colors": ["#1e2126", "#d0585c", "#6fb36f", "#d6b45a", "#5b8ed6", "#a77dd0", "#5fa8b8", "#c8c8c8",
                      "#5c6370", "#e8797c", "#8fcf8f", "#ebd07f", "#80aaf0", "#c59de6", "#8cc8d4", "#f2f2f2"]},
    False: {"background": "#f6f6f4", "foreground": "#1e1f22", "cursorColor": "#1e1f22",
            "colors": ["#1e1f22", "#b3261e", "#2e7d32", "#8a6100", "#2a5db0", "#7b3fa6", "#2f6b7a", "#b8bcc2",
                       "#6b6f76", "#d0393b", "#3d9441", "#a87a00", "#3c74d0", "#9452c4", "#3f8fa0", "#e4e4e1"]},
}
XTERM_KEYS = re.compile(r"XTerm\*(selectToClipboard|VT100\.translations|termName|saveLines|faceName|faceSize\d?|"
                        r"boldColors|background|foreground|cursorColor|cursorBar|cursorBlink|color\d+)\s*:")


def xterm_resources(dark):
    pal = XTERM_PALETTE[bool(dark)]
    out = ["XTerm*termName: xterm-256color", "XTerm*saveLines: 10000", "XTerm*boldColors: false",
           "XTerm*cursorBar: true", "XTerm*cursorBlink: true",
           "XTerm*faceName: DejaVu Sans Mono", "XTerm*faceSize: 14"]
    # Stufen fuer Strg +/- (xterm springt zwischen faceSize1..6; dazwischen liegt die Grundgroesse 14)
    out += [f"XTerm*faceSize{i}: {v}" for i, v in enumerate((8, 10, 12, 17, 20, 26), 1)]
    out += [f"XTerm*{k}: {pal[k]}" for k in ("background", "foreground", "cursorColor")]
    out += [f"XTerm*color{i}: {c}" for i, c in enumerate(pal["colors"])]
    out += ["XTerm*selectToClipboard: true",
            "XTerm*VT100.translations: #override Ctrl Shift <Key>V: insert-selection(CLIPBOARD)\\n"
            "Ctrl Shift <Key>C: copy-selection(CLIPBOARD)\\nShift <Key>Insert: insert-selection(CLIPBOARD, PRIMARY)\\n"
            "<Btn3Down>: ignore()\\n<Btn3Up>: insert-selection(CLIPBOARD, PRIMARY)\\n"
            "Ctrl <Key>plus: larger-vt-font()\\nCtrl <Key>KP_Add: larger-vt-font()\\n"
            "Ctrl <Key>minus: smaller-vt-font()\\nCtrl <Key>KP_Subtract: smaller-vt-font()\\n"
            "Ctrl <Key>0: set-vt-font(d)\\nCtrl <Key>KP_0: set-vt-font(d)"]
    return out


def apply_appearance(s):
    """Skalierung (Xft.dpi), Mauszeiger und Farbschema (hell/dunkel nach dem Theme) fuer neu gestartete
    Programme setzen."""
    home = Path.home()
    dpi = round(96 * float(s["scale"]))
    theme = s.get("cursor_theme") or DEFAULTS["cursor_theme"]
    if theme not in cursor_themes():
        theme = next(iter(cursor_themes()), "Adwaita")
    size = int(s.get("cursor_size") or DEFAULTS["cursor_size"])
    xres = home / ".Xresources"
    dark = theme_is_dark(s.get("theme") or DEFAULTS["theme"])
    try:
        lines = [l for l in xres.read_text().splitlines()
                 if not l.startswith(("Xft.dpi", "Xcursor.")) and not XTERM_KEYS.match(l)]
    except OSError:
        lines = []
    lines += [f"Xft.dpi: {dpi}", f"Xcursor.theme: {theme}", f"Xcursor.size: {size}"]
    lines += xterm_resources(dark)
    xres.write_text("\n".join(lines) + "\n")
    run(["xrdb", "-merge", str(xres)])
    gtk_name = "Adwaita-dark" if dark else "Adwaita"
    for gtk in ("gtk-3.0", "gtk-4.0"):
        vals = {"gtk-cursor-theme-name": theme, "gtk-cursor-theme-size": str(size),
                "gtk-application-prefer-dark-theme": "true" if dark else "false"}
        if gtk == "gtk-3.0":
            vals["gtk-theme-name"] = gtk_name
        _ini_set(home / ".config" / gtk / "settings.ini", "Settings", vals)
    gtk2 = home / ".gtkrc-2.0"
    try:
        txt = gtk2.read_text()
        new = re.sub(r'(?m)^gtk-theme-name=.*$', f'gtk-theme-name="{gtk_name}"', txt)
        if new != txt:
            gtk2.write_text(new)
    except OSError:
        pass
    idx = home / ".icons" / "default" / "index.theme"
    idx.parent.mkdir(parents=True, exist_ok=True)
    idx.write_text(f"[Icon Theme]\nInherits={theme}\n")
    qt_style, gtk_env = ("Adwaita-Dark", "Adwaita:dark") if dark else ("Adwaita", "Adwaita")
    # libadwaita (GTK 4: Mission Center & Co.) ignoriert GTK_THEME und liest das Farbschema nur aus dem Portal bzw.
    # GSettings – entpackte AppImages mit eigener GLib erreichen beides oft nicht. ADW_DEBUG_COLOR_SCHEME gilt immer.
    adw = "prefer-dark" if dark else "prefer-light"
    (BASE / "env.sh").write_text(
        f"export XCURSOR_THEME={theme}\nexport XCURSOR_SIZE={size}\n"
        f"export QT_STYLE_OVERRIDE={qt_style}\nexport GTK_THEME={gtk_env}\nexport ADW_DEBUG_COLOR_SCHEME={adw}\n")
    os.environ.update({"XCURSOR_THEME": theme, "XCURSOR_SIZE": str(size),
                       "QT_STYLE_OVERRIDE": qt_style, "GTK_THEME": gtk_env, "ADW_DEBUG_COLOR_SCHEME": adw})
    run(["xsetroot", "-cursor_name", "left_ptr"])
    try:
        apply_openbox_theme(s.get("theme") or DEFAULTS["theme"], dark)
    except OSError as e:
        log("Openbox-Theme nicht geschrieben:", e)
    threading.Thread(target=apply_color_scheme, args=(dark,), daemon=True).start()   # Start nicht aufhalten
    if IME_STATE["on"]:                             # Kandidatenfenster von fcitx5 hell/dunkel mitziehen
        threading.Thread(target=ime_sync, daemon=True).start()


# Openbox: Fenster, die Openbox selbst zeichnet (Dialoge und Hilfsfenster von Emulatoren & Co. – normale Fenster
# laufen ohne Rahmen), sehen aus wie das gewaehlte Kachel-Theme statt wie Clearlooks. Das Theme "VoidStation" wird aus
# den Farben der Theme-Datei (web/themes/<name>.css) gebaut und nach jedem Theme-Wechsel neu geschrieben;
# rc.xml waehlt es. Schriften stehen in rc.xml.
OB_CLOSE_XBM = """#define close_width 10
#define close_height 10
static unsigned char close_bits[] = {
   0x03, 0x03, 0x87, 0x03, 0xce, 0x01, 0xfc, 0x00, 0x78, 0x00, 0x78, 0x00,
   0xfc, 0x00, 0xce, 0x01, 0x87, 0x03, 0x03, 0x03 };
"""


def theme_colors(theme):
    """Farben (#rrggbb) aus web/themes/<theme>.css; rgba(...) wird auf --surface-card bzw. --bg-main gemischt."""
    try:
        css = (WEB / "themes" / f"{theme}.css").read_text(encoding="utf-8")
    except OSError:
        css = ""
    raw = dict(re.findall(r"--([a-z0-9-]+):\s*([^;]+);", css))

    def hexc(v):
        v = (v or "").strip()
        m = re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})", v)
        if m:
            h = m.group(1)
            return "#" + ("".join(c * 2 for c in h) if len(h) == 3 else h).lower()
        return None

    base = hexc(raw.get("surface-card")) or hexc(raw.get("bg-main")) or "#22262b"
    out = {}
    for k, v in raw.items():
        c = hexc(v)
        m = re.fullmatch(r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)", v.strip())
        if not c and m:
            r, g, b, a = int(m.group(1)), int(m.group(2)), int(m.group(3)), float(m.group(4))
            br, bg_, bb = (int(base[i:i + 2], 16) for i in (1, 3, 5))
            c = "#%02x%02x%02x" % tuple(round(x * a + y * (1 - a)) for x, y in ((r, br), (g, bg_), (b, bb)))
        if c:
            out[k] = c
    return out


def openbox_themerc(theme, dark):
    c = theme_colors(theme)
    fb = ({"surface-card": "#22262b", "surface-dialog": "#1a1d21", "surface-card-hover": "#2e343b",
           "surface-active": "#4a5260", "text-primary": "#ecebe8", "text-dim": "#a7a6a4", "border-subtle": "#2c3035",
           "border-focus": "#f2efe9", "status-danger-bg": "#6e2b2b"} if dark else
          {"surface-card": "#ffffff", "surface-dialog": "#ffffff", "surface-card-hover": "#eef2f6",
           "surface-active": "#b8c8dc", "text-primary": "#15181c", "text-dim": "#5f6266", "border-subtle": "#d0d5dc",
           "border-focus": "#1a73e8", "status-danger-bg": "#c62828"})
    g = lambda k: c.get(k) or fb[k]
    title, title_in, text, dim = g("surface-card"), g("surface-dialog"), g("text-primary"), g("text-dim")
    border, hover, active, danger = g("border-subtle"), g("surface-card-hover"), g("surface-active"), g("status-danger-bg")
    btn_text = "#ffffff"                                  # weisses X auf Rot, in allen Themes
    lines = [
        f"# VoidStation: Openbox-Theme passend zum Kachel-Theme \"{theme}\" – wird vom Launcher geschrieben",
        "border.width: 1", "padding.width: 10", "padding.height: 8",
        "window.handle.width: 0", "window.client.padding.width: 0", "window.client.padding.height: 0",
        "window.label.text.justify: left",
        f"window.active.border.color: {border}", f"window.inactive.border.color: {border}",
        f"window.active.title.separator.color: {border}", f"window.inactive.title.separator.color: {border}",
        "window.active.title.bg: flat solid", f"window.active.title.bg.color: {title}",
        "window.inactive.title.bg: flat solid", f"window.inactive.title.bg.color: {title_in}",
        "window.active.label.bg: parentrelative", f"window.active.label.text.color: {text}",
        "window.inactive.label.bg: parentrelative", f"window.inactive.label.text.color: {dim}",
        f"window.active.client.color: {title}", f"window.inactive.client.color: {title_in}",
    ]
    for st, img in (("active", text), ("inactive", dim)):
        lines += [f"window.{st}.button.unpressed.bg: parentrelative", f"window.{st}.button.unpressed.image.color: {img}",
                  f"window.{st}.button.disabled.bg: parentrelative", f"window.{st}.button.disabled.image.color: {dim}",
                  f"window.{st}.button.hover.bg: flat solid", f"window.{st}.button.hover.bg.color: {hover}",
                  f"window.{st}.button.hover.image.color: {text}",
                  f"window.{st}.button.pressed.bg: flat solid", f"window.{st}.button.pressed.bg.color: {active}",
                  f"window.{st}.button.pressed.image.color: {text}",
                  f"window.{st}.button.toggled.bg: parentrelative", f"window.{st}.button.toggled.image.color: {img}"]
    # Schliessen-Knopf: beim Zeigen rot hinterlegt (wie die Ecke "App schliessen")
    lines += ["window.active.button.close.hover.bg: flat solid", f"window.active.button.close.hover.bg.color: {danger}",
              f"window.active.button.close.hover.image.color: {btn_text}",
              "window.active.button.close.pressed.bg: flat solid", f"window.active.button.close.pressed.bg.color: {danger}",
              f"window.active.button.close.pressed.image.color: {btn_text}"]
    lines += [
        "menu.border.width: 1", f"menu.border.color: {border}", "menu.overlap.x: 0", "menu.overlap.y: 0",
        "menu.title.bg: flat solid", f"menu.title.bg.color: {title}", f"menu.title.text.color: {text}",
        "menu.title.text.justify: left",
        "menu.items.bg: flat solid", f"menu.items.bg.color: {title_in}", f"menu.items.text.color: {text}",
        f"menu.items.disabled.text.color: {dim}",
        "menu.items.active.bg: flat solid", f"menu.items.active.bg.color: {hover}", f"menu.items.active.text.color: {text}",
        f"menu.separator.color: {border}", "menu.separator.width: 1", "menu.separator.padding.width: 6",
        "menu.separator.padding.height: 3",
        "osd.border.width: 1", f"osd.border.color: {border}", "osd.bg: flat solid", f"osd.bg.color: {title_in}",
        f"osd.label.text.color: {text}", "osd.hilight.bg: flat solid", f"osd.hilight.bg.color: {active}",
        "osd.unhilight.bg: flat solid", f"osd.unhilight.bg.color: {hover}",
    ]
    return "\n".join(lines) + "\n"


def apply_openbox_theme(theme, dark):
    d = Path.home() / ".local/share/themes/VoidStation/openbox-3"
    d.mkdir(parents=True, exist_ok=True)
    changed = False
    for name, txt in (("themerc", openbox_themerc(theme, dark)), ("close.xbm", OB_CLOSE_XBM)):
        p = d / name
        try:
            if p.read_text(encoding="utf-8") == txt:
                continue
        except OSError:
            pass
        p.write_text(txt, encoding="utf-8")
        changed = True
    if changed and os.environ.get("DISPLAY") and shutil.which("openbox"):
        run(["openbox", "--reconfigure"])                   # laufendes Openbox laedt das Theme neu


def openbox_rc_sync():
    """Neue Tastenkuerzel aus einem Update (rc.xml, z. B. F12 = Bildschirmfoto) gleich wirksam machen: Openbox liest
    rc.xml nur beim Start bzw. auf --reconfigure. Merkt sich den Stand, damit nicht jeder Launcher-Start neu laedt."""
    rc, mark = Path.home() / ".config/openbox/rc.xml", BASE / "openbox-rc.sha"
    try:
        if not rc.is_file():                        # noch nicht eingerichtet (Live-Start, Test)
            return
        h = hashlib.sha256(rc.read_bytes()).hexdigest()[:16]
        if mark.exists() and mark.read_text().strip() == h:
            return
        r = run(["pgrep", "-x", "openbox"])
        if os.environ.get("DISPLAY") and r and r.returncode == 0:      # laeuft es noch nicht, liest es rc.xml beim Start
            run(["openbox", "--reconfigure"])
            log("Openbox: rc.xml neu geladen")
        mark.write_text(h + "\n")
    except OSError as e:
        log("Openbox rc.xml:", e)


def restart_home_later(delay=0.8):
    """Startseite neu starten, z. B. fuer den neuen Mauszeiger (home.sh startet sie neu)."""
    def _go():
        time.sleep(delay)
        run(["pkill", "-f", "voidstation-home.py"])
    threading.Thread(target=_go, daemon=True).start()


def xrandr_info():
    """Angeschlossene Ausgaenge mit Modi und Bildraten (aus xrandr --query)."""
    r = run(["xrandr", "--query"])
    outs: list = []
    if not r or r.returncode != 0:
        return outs
    cur = None
    for line in r.stdout.splitlines():
        if not line.startswith(" "):
            parts = line.split()
            cur = None
            if len(parts) > 1 and parts[1] == "connected":
                cur = {"name": parts[0], "modes": [], "current": None, "rate": None,
                       "preferred": None, "rates": {}}
                outs.append(cur)
        elif cur is not None:
            p = line.split()
            if not p or "x" not in p[0]:
                continue
            mode = p[0]
            if mode not in cur["modes"]:
                cur["modes"].append(mode)
            for tok in p[1:]:
                try:
                    hz = float(tok.rstrip("*+"))
                except ValueError:
                    continue
                cur["rates"].setdefault(mode, []).append(hz)
                if "*" in tok:
                    cur["current"], cur["rate"] = mode, hz
                if "+" in tok and not cur["preferred"]:
                    cur["preferred"] = mode
    return outs


def _best_rate(rates, want=None):
    """Gewaehlte Rate (Einstellungen -> Anzeige), sonst moeglichst 60 Hz (60.00 vor 59.94), sonst die hoechste."""
    if not rates:
        return None
    if want:
        hit = [r for r in rates if abs(r - want) < 0.005]
        if hit:
            return hit[0]
    near = [r for r in rates if abs(r - 60) < 0.5]
    return max(near) if near else max(rates)


def _auto_mode(o):
    """Meldet der Fernseher ein Halbbild-Format (1080i) als Standard, lieber den
    groessten Vollbild-Modus mit ~60 Hz nehmen (ruhigeres Bild, YouTube ohne Ruckeln)."""
    pref = o.get("preferred") or o.get("current")
    if not pref or not pref.endswith("i"):
        return None
    prog = [m for m in o["modes"] if not m.endswith("i")
            and any(abs(r - 60) < 0.5 for r in o["rates"].get(m, []))]
    if not prog:
        return None
    return max(prog, key=lambda m: int(m.split("x")[0]) * int(m.split("x")[1].rstrip("i")))


def apply_resolution(res, want_rate=None):
    """Aufloesung (None = automatisch) und Bildrate des Desktops setzen (want_rate None = ~60 Hz)."""
    for o in xrandr_info():
        mode = res if res in o["modes"] else (None if res else _auto_mode(o))
        if not mode and want_rate and o["current"]:
            mode = o["current"]                         # automatische Aufloesung, aber feste Bildrate
        if not mode:
            continue
        rate = _best_rate(o["rates"].get(mode, []), want_rate)
        if mode == o["current"] and (rate is None or o["rate"] == rate):
            continue
        cmd = ["xrandr", "--output", o["name"], "--mode", mode]
        if rate:
            cmd += ["--rate", f"{rate:.2f}"]
        run(cmd)
        log("Aufloesung", o["name"], mode, f"{rate} Hz" if rate else "", "(automatisch)" if not res else "")


def apply_display(s=None):
    """Aufloesung und Bildrate aus den Einstellungen."""
    s = s or settings_load()
    apply_resolution(s.get("resolution"), s.get("rate"))


# Bildrate an das Video anpassen (Einstellungen -> Anzeige, Standard aus): Laeuft vorn ein Video mit 25/50 fps,
# schaltet der Bildschirm auf 50 Hz (sonst ruckelt es auf 60 Hz gleichmaessig: Bilder abwechselnd 2 und 3 Takte lang),
# 23,976 fps auf 23,98 Hz, 29,97 auf 59,94 Hz – nur wenn die aktuelle Aufloesung die Rate anbietet. Den Wunsch meldet
# der Player (POST /api/display/video {fps, src}), sobald die Bildrate feststeht, und 0, wenn kein Video mehr vorn
# laeuft (Ende, Musik, Startseite, Player zu). Zurueck auf die Desktop-Rate geht es spaetestens, wenn der Player endet.
# Jede Umschaltung kostet 1–3 s schwarzes Bild (HDMI rastet neu ein) – deshalb nur, wenn die Rate nicht ohnehin passt.
RATE_TOL = 0.002                                       # 0,2 %: 24 fps auf 23,98 Hz (0,1 %) gilt noch als passend


def rate_fits(fps, rate):
    """Zeigt rate jedes Bild gleich lang (ganzzahliges Vielfaches, bis auf RATE_TOL)?"""
    if not fps or not rate:
        return False
    k = round(rate / fps)
    return k >= 1 and abs(rate - k * fps) / rate <= RATE_TOL


def pick_rate(fps, rates):
    """Passende Bildschirm-Rate fuer ein Video: kleinste Abweichung, bei Gleichstand die hoehere Rate
    (25 fps -> 50 Hz statt 25 Hz). None, wenn keine Rate passt (z. B. 50 fps auf einem reinen 60-Hz-Fernseher)."""
    best = None
    for r in set(rates or []):
        if not 23 <= r <= 145 or not rate_fits(fps, r):
            continue
        key = (round(abs(r - round(r / fps) * fps) / r, 5), -r)
        if best is None or key < best[0]:
            best = (key, r)
    return best[1] if best else None


class DisplayRate:
    def __init__(self):
        self.lock = threading.RLock()
        self.wanted = 0.0                              # Bildrate des Videos, das gerade vorn laeuft (0 = keins)
        self.src = ""                                  # welcher Player sie gemeldet hat (tv, media, yt) bzw. die Emulator-Kachel
        self.forced = False                            # PAL-Spiel: gilt auch ohne "Bildrate an Video anpassen" (emu_pal_rate)
        self.base = {}                                 # Ausgang -> (Modus, Rate) vor dem Umschalten
        self.now = None                                # zuletzt gesetzte Video-Rate (fuer die Technik-Anzeige)

    def request(self, fps, src="", force=False):
        with self.lock:
            try:
                fps = float(fps or 0)
            except (TypeError, ValueError):
                fps = 0.0
            if not fps and src and self.src and src != self.src:
                return self.state()                    # ein anderer Player hat inzwischen uebernommen
            self.wanted = fps if 10 <= fps <= 121 else 0.0
            self.src = src if self.wanted else ""
            self.forced = bool(force and self.wanted)
            self._apply()
            return self.state()

    def reapply(self):
        """Beim Umschalten der Einstellung und nach dem Standby: laeuft vorn ein Video, gilt (wieder) dessen Rate.
        base bleibt – es haelt die Desktop-Rate fest, auch wenn der Bildschirm nach dem Aufwachen schon darauf steht."""
        with self.lock:
            self._apply()

    def state(self):
        return {"on": bool(settings_load().get("match_rate")), "fps": self.wanted, "rate": self.now}

    def _apply(self):
        if not self.wanted or not (self.forced or settings_load().get("match_rate")):
            self._restore()
            return
        for o in xrandr_info():
            mode, cur = o["current"], o["rate"]
            if not mode or not cur:
                continue
            if rate_fits(self.wanted, cur):
                self.now = cur if o["name"] in self.base else None
                continue
            r = pick_rate(self.wanted, o["rates"].get(mode, []))
            if not r:
                log(f"Bildrate: {self.wanted:.3f} fps – {o['name']} bietet bei {mode} keine passende Rate")
                continue
            self.base.setdefault(o["name"], (mode, cur))
            run(["xrandr", "--output", o["name"], "--mode", mode, "--rate", f"{r:.2f}"])
            self.now = r
            log(f"Bildrate an Video angepasst: {self.wanted:.3f} fps -> {o['name']} {mode} {r} Hz (vorher {cur} Hz)")

    def _restore(self):
        if not self.base:
            self.now = None
            return
        outs = {o["name"]: o for o in xrandr_info()}
        for name, (mode, rate) in self.base.items():
            o = outs.get(name)
            if not o or o["current"] != mode or (o["rate"] and abs(o["rate"] - rate) < 0.005):
                continue                               # inzwischen andere Aufloesung oder schon zurueck
            run(["xrandr", "--output", name, "--mode", mode, "--rate", f"{rate:.2f}"])
            log(f"Bildrate zurueck: {name} {mode} {rate} Hz")
        self.base = {}
        self.now = None


DISPLAY_RATE = DisplayRate()


def pactl_json(*args):
    r = run(["pactl", "-f", "json", *args])
    if not r or r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
#  Ton: Geraete statt Rohprofile (PipeWire ueber pactl)
#    Ein "Geraet" ist das, was man als Ausgang kennt: Fernseher (HDMI, je Anschluss), Klinke, S/PDIF,
#    USB-Headset, Bluetooth-Kopfhoerer. Je Geraet ein Format (Stereo, 5.1 …; Bluetooth: Codec) und
#    das Mikrofon an/aus – daraus ergibt sich das Profil der Karte. PipeWire-Profilnamen sieht niemand mehr.
#    Gemerkt je Geraet in settings.json: audio_prefs = {schluessel: {"format": …, "mic": bool}}
#    Schluessel: Kartenname (USB, Bluetooth) bzw. Kartenname#familie+anschluss (eingebaute Karten: hdmi0, analog0 …)
# ---------------------------------------------------------------------------
AUDIO_LOCK = threading.RLock()
AUDIO_LAYOUTS = ["mono", "stereo", "surround-21", "surround-40", "surround-41", "surround-50", "surround-51", "surround-71"]
AUDIO_CODECS = {"sbc": "SBC", "sbc_xq": "SBC-XQ", "aac": "AAC", "aac_eld": "AAC-ELD", "aptx": "aptX", "aptx_hd": "aptX HD",
                "aptx_ll": "aptX LL", "aptx_ll_duplex": "aptX LL", "ldac": "LDAC", "lc3plus_h3": "LC3plus", "lc3": "LC3",
                "opus_05": "Opus", "opus_g": "Opus", "faststream": "FastStream", "faststream_duplex": "FastStream"}
# Geraete, auf die der Ton beim Einstecken nicht von selbst wechseln soll (Controller mit Kopfhoerer-Buchse, Webcams)
AUDIO_NOAUTO = re.compile(r"controller|gamepad|dualsense|dualshock|joy-?con|webcam|camera|\bcam\b", re.I)


def _audio_profile(name):
    """Profilname -> (familie, anschluss, layout, mit_eingang) oder None (kein Ausgang, Durchreichen, aus).
    output:hdmi-surround71-extra1+input:analog-stereo -> ("hdmi", 1, "surround-71", True)
    a2dp-sink-aac -> ("bt", 0, "a2dp:aac", False) · headset-head-unit-msbc -> ("bt", 0, "hfp:msbc", True)"""
    if name.startswith("output:"):
        out, _, inp = name[7:].partition("+input:")
        m = re.match(r"^(analog|hdmi|iec958)-(.+?)(?:-extra(\d+))?$", out)
        fam, lay, port = (m.group(1), m.group(2), int(m.group(3) or 0)) if m else ("other", out, 0)
        if re.search(r"(^|-)(ac3|dts|eac3|truehd)(-|$)", lay):     # Bitstream an einen AV-Receiver: nicht anbieten
            return None
        lay = {"surround": "surround-51", "surround71": "surround-71"}.get(lay, lay)   # HDMI schreibt es anders
        if lay.endswith("-fallback"):
            lay = lay[:-9]
        return fam, port, lay, bool(inp)
    if name.startswith("a2dp-sink"):
        return "bt", 0, "a2dp:" + (name[10:] or "auto"), False
    if name.startswith("headset-head-unit"):
        return "bt", 0, "hfp:" + (name[18:] or "auto"), True
    return None


def _audio_card_kind(c):
    p = c.get("properties") or {}
    name = c.get("name", "")
    if name.startswith("bluez_card.") or p.get("device.bus") == "bluetooth":
        return "bt"
    if p.get("device.bus") == "usb" or ".usb-" in name:
        return "usb"
    return "pci"


def _audio_ports(c):
    ports = c.get("ports") or {}
    return list(ports.values()) if isinstance(ports, dict) else list(ports)


def _audio_fmt(lay):
    """Format fuer die Oberflaeche: key = Sprachschluessel (Text mit {ch}), label = sprachneutral."""
    if lay.startswith("a2dp:"):
        codec = lay[5:]
        if codec == "auto":
            return {"id": lay, "key": "audio.fmt.auto", "label": ""}
        return {"id": lay, "key": "", "label": AUDIO_CODECS.get(codec, codec.upper())}
    if lay in ("mono", "stereo"):
        return {"id": lay, "key": "audio.fmt." + lay, "label": ""}
    if lay.startswith("surround-") and lay[9:].isdigit() and len(lay) == 11:
        return {"id": lay, "key": "audio.fmt.surround", "label": lay[9] + "." + lay[10]}
    return {"id": lay, "key": "", "label": lay}


def _audio_sink_of(card, sinks):
    """Name des Ausgangs (Sink), den diese Karte gerade stellt, sonst None."""
    prefix = card.replace("_card.", "_output.")          # alsa_card.… -> alsa_output.…, bluez_card.… -> bluez_output.…
    for s in sinks or []:
        props = s.get("properties") or {}
        if props.get("device.name") == card or s.get("name", "").startswith(prefix + "."):
            return s.get("name")
    return None


def audio_devices(cards, sinks, default_sink):
    """Geraeteliste aus pactl (list cards / list sinks / get-default-sink). Rein rechnend – testbar ohne PipeWire."""
    devs: dict = {}
    for c in cards or []:
        card, kind = c.get("name", ""), _audio_card_kind(c)
        props = c.get("properties") or {}
        active = c.get("active_profile") or ""
        for pname, prof in (c.get("profiles") or {}).items():
            parsed = _audio_profile(pname)
            if not parsed:
                continue
            fam, port, lay, inp = parsed
            if kind == "pci":
                key, dkind = f"{card}#{fam}{port}", {"iec958": "spdif"}.get(fam, fam)
            else:
                key, dkind = card, kind
            d = devs.setdefault(key, {"key": key, "card": card, "kind": dkind, "cardKind": kind, "port": port,
                                      "name": "", "profiles": [], "activeProfile": None})
            d["profiles"].append({"name": pname, "fam": fam, "lay": lay, "inp": inp,
                                  "prio": prof.get("priority", 0) or 0, "avail": prof.get("available") is not False})
            if pname == active:
                d["activeProfile"] = pname
        # Namen: Bluetooth/USB/sonstige wie vom Geraet gemeldet, HDMI nach dem Bildschirm (EDID/ELD), wenn bekannt
        desc = props.get("device.description") or props.get("alsa.card_name") or card
        for d in devs.values():
            if d["card"] != card:
                continue
            if d["kind"] == "hdmi":
                names = {p["name"] for p in d["profiles"]}
                for port in _audio_ports(c):
                    pn = (port.get("properties") or {}).get("device.product.name")
                    if pn and names & set(port.get("profiles") or []):
                        d["name"] = pn
                        break
            elif d["kind"] not in ("analog", "spdif"):
                d["name"] = desc
    dsink_card = None
    for c in cards or []:
        if default_sink and _audio_sink_of(c.get("name", ""), sinks) == default_sink:
            dsink_card = c.get("name")
    out = []
    for d in devs.values():
        usable = [p for p in d["profiles"] if p["avail"]]
        if not usable and not d["activeProfile"]:
            continue                                     # z. B. HDMI-Anschluss ohne Bildschirm, Klinke ohne Stecker
        lays = {p["lay"] for p in usable if not p["lay"].startswith("hfp:")}
        def order(l):
            if l in AUDIO_LAYOUTS:
                return (0, AUDIO_LAYOUTS.index(l), "")
            if l == "a2dp:auto":
                return (1, 0, "")
            best = max((p["prio"] for p in usable if p["lay"] == l), default=0)
            return (2, -best, l)
        fmts = [_audio_fmt(l) for l in sorted(lays, key=order)]
        ap = next((p for p in d["profiles"] if p["name"] == d["activeProfile"]), None)
        cur_fmt = ap["lay"] if ap and not ap["lay"].startswith("hfp:") else None
        if d["cardKind"] == "bt":
            mic_avail = any(p["inp"] for p in usable)
        else:
            mic_avail = any(p["inp"] and p["lay"] == (cur_fmt or "stereo") for p in usable)
        out.append({"key": d["key"], "card": d["card"], "kind": d["kind"], "name": d["name"], "num": 0,
                    "active": bool(ap) and d["card"] == dsink_card, "formats": fmts, "format": cur_fmt,
                    "mic": (bool(ap and ap["inp"]) if mic_avail else None), "micAvail": mic_avail,
                    "profiles": d["profiles"], "activeProfile": d["activeProfile"]})
    # Mehrere HDMI-Ausgaenge mit gleichem Namen: durchnummerieren (Fernseher 1, Fernseher 2)
    hd = [d for d in out if d["kind"] == "hdmi"]
    for n in {d["name"] for d in hd}:
        same = sorted((d for d in hd if d["name"] == n), key=lambda d: (d["card"], d["key"]))
        if len(same) > 1:
            for i, d in enumerate(same):
                d["num"] = i + 1
    rank = {"hdmi": 0, "usb": 1, "bt": 2, "analog": 3, "spdif": 4, "other": 5}
    out.sort(key=lambda d: (rank.get(d["kind"], 9), d["name"].lower(), d["key"]))
    return out


def audio_default_format(dev):
    ids = [f["id"] for f in dev["formats"]]
    for want in ("stereo", "a2dp:auto"):
        if want in ids:
            return want
    return ids[0] if ids else None


def audio_default_mic(dev):
    return dev["kind"] == "usb"                         # USB-Headset: Mikro bereit; Bluetooth: sonst nur Sprachqualitaet


def audio_choose(dev, fmt, mic):
    """Profil fuer Format + Mikrofon. Bluetooth: Mikrofon an = Headset-Profil (HFP), sonst A2DP im gewuenschten Codec.
    Eingebaute/USB-Karten: analog vor S/PDIF (bei USB derselbe Ausgang), dann hoechste Prioritaet."""
    usable = [p for p in dev["profiles"] if p["avail"]] or dev["profiles"]
    def best(cands):
        return min(cands, key=lambda p: ({"analog": 0, "hdmi": 0, "iec958": 1}.get(p["fam"], 2), -p["prio"]))["name"] if cands else None
    if dev["kind"] == "bt" and mic:
        return best([p for p in usable if p["lay"].startswith("hfp:")]) or audio_choose(dev, fmt, False)
    same = [p for p in usable if p["lay"] == fmt] or [p for p in usable if p["lay"] == audio_default_format(dev)]
    if not same:
        same = [p for p in usable if not p["lay"].startswith("hfp:")]
    return best([p for p in same if p["inp"] == bool(mic)]) or best(same)


def audio_snapshot():
    cards = pactl_json("list", "cards")
    if cards is None:
        return None
    sinks = pactl_json("list", "sinks") or []
    r = run(["pactl", "get-default-sink"])
    default = r.stdout.strip() if r and r.returncode == 0 else ""
    return {"cards": cards, "sinks": sinks, "default": default, "devices": audio_devices(cards, sinks, default)}


def audio_info():
    snap = audio_snapshot()
    auto = bool(settings_load().get("audio_auto", True))
    if snap is None:
        return {"ok": False, "devices": [], "auto": auto}
    pub = ("key", "kind", "name", "num", "active", "formats", "format", "mic", "micAvail")
    return {"ok": True, "auto": auto, "devices": [{k: d[k] for k in pub} for d in snap["devices"]]}


def audio_select(key, fmt=None, mic=None, make_default=True):
    """Geraet waehlen (Format/Mikro aus den gemerkten Einstellungen, sonst Stereo; Mikro bei USB an) bzw. Format oder
    Mikro aendern. Setzt das Profil der Karte und – make_default – den Ausgang als Standard. Gibt False zurueck,
    wenn es das Geraet nicht (mehr) gibt."""
    with AUDIO_LOCK:
        snap = audio_snapshot()
        dev = next((d for d in (snap or {}).get("devices", []) if d["key"] == key), None)
        if not dev:
            return False
        s = settings_load()
        prefs = dict((s.get("audio_prefs") or {}).get(key) or {})
        ids = [f["id"] for f in dev["formats"]]
        picked = fmt is not None
        if not picked:                                   # Mikro umschalten: Format bleibt; Geraet waehlen: gemerktes
            fmt = dev["format"] if mic is not None and dev["format"] else prefs.get("format")
        if fmt not in ids:
            fmt = prefs.get("format") if prefs.get("format") in ids else audio_default_format(dev)
        if mic is None:
            if picked and dev["kind"] == "bt":
                mic = False                              # Codec gewaehlt = A2DP, das Headset-Profil kennt keine Codecs
            elif picked and dev["mic"] is not None:
                mic = dev["mic"]
            else:
                mic = prefs.get("mic", audio_default_mic(dev))
        prof = audio_choose(dev, fmt, mic)
        if prof and prof != dev["activeProfile"]:
            run(["pactl", "set-card-profile", dev["card"], prof])
        if make_default:
            sink = None
            for _ in range(20):                          # neuer Ausgang braucht nach dem Profilwechsel einen Moment
                sink = _audio_sink_of(dev["card"], pactl_json("list", "sinks") or [])
                if sink:
                    break
                time.sleep(0.2)
            if sink:
                run(["pactl", "set-default-sink", sink])
                run(["pactl", "set-sink-mute", sink, "0"])
        prefs.update({"format": fmt, "mic": bool(mic)})
        s = settings_load()
        s.setdefault("audio_prefs", {})[key] = prefs
        settings_save(s)
        log("Ton:", key, prof or "-", "(Standard)" if make_default else "")
        return True


def audio_tidy(snap=None):
    """Eingebaute Karten, die VoidStation zum ersten Mal sieht: HDMI von Surround auf Stereo stellen, solange niemand
    ein Format gewaehlt hat. Fernseher haben zwei Lautsprecher; bei 7.1 mischt mancher den Center-Kanal (Dialoge)
    schlecht herunter. Wer einen AV-Receiver hat, stellt Surround unter Einstellungen → Ton → Format wieder ein."""
    with AUDIO_LOCK:
        snap = snap or audio_snapshot()
        if not snap:
            return
        s = settings_load()
        seen, prefs = list(s.get("audio_seen") or []), s.get("audio_prefs") or {}
        changed = False
        for c in snap["cards"]:
            card = c.get("name", "")
            if _audio_card_kind(c) != "pci" or card in seen:
                continue
            seen.append(card)
            changed = True
            for d in snap["devices"]:
                ap = next((p for p in d["profiles"] if p["name"] == d["activeProfile"]), None)
                if d["card"] == card and d["kind"] == "hdmi" and ap and ap["lay"].startswith("surround") and d["key"] not in prefs \
                        and any(f["id"] == "stereo" for f in d["formats"]):
                    prof = audio_choose(d, "stereo", ap["inp"])
                    if prof:
                        was_default = d["active"]        # neuer Ausgangsname nach dem Wechsel: Standard mitnehmen
                        run(["pactl", "set-card-profile", card, prof])
                        log("Ton:", d["key"], "von", ap["lay"], "auf Stereo (Fernseher)")
                        for _ in range(20 if was_default else 0):
                            sink = _audio_sink_of(card, pactl_json("list", "sinks") or [])
                            if sink:
                                run(["pactl", "set-default-sink", sink])
                                break
                            time.sleep(0.2)
        if changed:
            s = settings_load()
            s["audio_seen"] = seen
            settings_save(s)


class AudioWatch:
    """Neu eingesteckte USB- bzw. eingeschaltete Bluetooth-Kopfhoerer uebernehmen den Ton (abschaltbar: audio_auto).
    Nicht beim Hochfahren und nicht direkt nach dem Standby – dann melden sich vorhandene Geraete nur neu an."""
    QUIET = 30

    def __init__(self):
        self.quiet_until = 0.0
        self.gap = self._gap()

    @staticmethod
    def _gap():
        return time.clock_gettime(time.CLOCK_BOOTTIME) - time.monotonic()

    def run(self):
        tries = 0                                        # PipeWire startet mit der Sitzung, evtl. nach dem Launcher
        while pactl_json("info") is None:                # nicht aufgeben: kommt der Ton spaeter (langsamer Rechner,
            tries += 1                                   # WirePlumber neu gestartet), soll die Ueberwachung mitlaufen
            if tries == 90:
                log("Ton: PipeWire nach 90 s nicht erreichbar – versuche es weiter")
            time.sleep(1 if tries < 90 else 10)
        if tries >= 90:
            log("Ton: PipeWire jetzt erreichbar")
        time.sleep(8)                                    # Geraete beim Hochfahren in Ruhe ankommen lassen
        try:
            audio_tidy()
        except Exception as e:  # noqa: BLE001
            log("Ton (Vorgaben):", e)
        while True:
            try:
                p = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
                assert p.stdout is not None
            except OSError:
                return
            for line in p.stdout:
                m = re.match(r"Event 'new' on card #(\d+)", line.strip())
                if m:
                    threading.Thread(target=self.new_card, args=(int(m.group(1)),), daemon=True).start()
            p.wait()
            time.sleep(5)                                # PipeWire neu gestartet: wieder anmelden

    def new_card(self, index):
        g = self._gap()
        if g - self.gap > 10:                            # dazwischen lag ein Standby
            self.quiet_until = time.monotonic() + self.QUIET
        self.gap = g
        time.sleep(1.5)                                  # Profile und Ausgaenge erst fertig anlegen lassen
        try:
            snap = audio_snapshot()
            c = next((x for x in (snap or {}).get("cards", []) if x.get("index") == index), None)
            if not c:
                return
            audio_tidy(snap)
            kind = _audio_card_kind(c)
            props = c.get("properties") or {}
            label = " ".join(str(props.get(k, "")) for k in ("device.description", "device.product.name", "alsa.card_name"))
            if kind not in ("usb", "bt") or time.monotonic() < self.quiet_until or not settings_load().get("audio_auto", True):
                return
            if AUDIO_NOAUTO.search(label) or props.get("device.form_factor") in ("webcam", "microphone") \
                    or (kind == "usb" and props.get("device.vendor.id") == "0x054c"):   # Sony: DualShock/DualSense per USB
                log("Ton: neues Geraet ohne automatischen Wechsel:", c.get("name"))
                return
            dev = next((d for d in snap["devices"] if d["card"] == c.get("name")), None)
            if dev:
                audio_select(dev["key"])
                log("Ton: neues Geraet uebernimmt:", dev["key"])
        except Exception as e:  # noqa: BLE001
            log("Ton (neues Geraet):", e)


AUDIO_WATCH = AudioWatch()


def net_info():
    r = run(["ip", "-4", "-o", "addr", "show", "scope", "global"])
    addrs = []
    if r:
        for line in r.stdout.splitlines():
            p = line.split()
            if len(p) >= 4:
                addrs.append({"iface": p[1], "ip": p[3].split("/")[0]})
    links = net_links(addrs)
    return {"hostname": socket.gethostname(), "addresses": addrs, "links": links,
            "has_wired": any(l["type"] == "wired" for l in links), "has_wifi": any(l["type"] == "wifi" for l in links),
            "mode": net_mode_get()}


# ---------------------------------------------------------------------------
#  Kabel oder WLAN bevorzugen: sind beide verbunden, nimmt Linux fuer das Internet die Standardroute mit der
#  kleinsten Metrik (NetworkManager: Kabel 100, WLAN 600). "WLAN bevorzugen" gibt allen WLAN-Profilen Metrik 50
#  (IPv4 und IPv6), "Kabel" stellt die Vorgabe wieder her. Lokale Ziele (Freigabe, SSH) bleiben ueber beide erreichbar.
#  Anlass: Kabelanschluss, der nur noch IPv6 durchlaesst – GitHub braucht IPv4, der Handy-Hotspot hat es.
# ---------------------------------------------------------------------------
NM_TYPES = {"ethernet": "wired", "802-3-ethernet": "wired", "wifi": "wifi", "802-11-wireless": "wifi"}


def net_default_dev(fam):
    """Schnittstelle der Standardroute mit der kleinsten Metrik (fam "-4"/"-6"), sonst ''."""
    r = run(["ip", fam, "route", "show", "default"])
    best = None
    for line in (r.stdout.splitlines() if r and r.returncode == 0 else []):
        m = re.search(r"\bdev (\S+)", line)
        if not m:
            continue
        mm = re.search(r"\bmetric (\d+)", line)
        metric = int(mm.group(1)) if mm else 0
        if best is None or metric < best[0]:
            best = (metric, m.group(1))
    return best[1] if best else ""


def net_links(addrs=None):
    """Kabel- und WLAN-Schnittstellen laut NetworkManager: Typ, Zustand, Profil (bei WLAN der Netzname),
    IPv4-Adresse und ob das Internet (Standardroute) gerade darueber laeuft."""
    r = run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"], timeout=10)
    ip4 = {a["iface"]: a["ip"] for a in (addrs or [])}
    d4, d6 = net_default_dev("-4"), net_default_dev("-6")
    out = []
    for line in (r.stdout.splitlines() if r and r.returncode == 0 else []):
        dev, typ, state, conn = (nm_split(line) + ["", "", "", ""])[:4]
        kind = NM_TYPES.get(typ)
        if not kind:
            continue
        up = state.split(" ")[0] in ("connected", "verbunden")
        # "internet": darueber laeuft das Internet – die IPv4-Standardroute, ohne IPv4 die von IPv6
        # "ready": getrennt, aber verbindbar (ohne Kabel meldet NetworkManager "unavailable")
        out.append({"dev": dev, "type": kind, "connected": up, "name": conn if up else "", "ip": ip4.get(dev, ""),
                    "internet": up and dev == (d4 or d6), "ready": state in ("disconnected", "getrennt")})
    out.sort(key=lambda l: (not l["connected"], l["type"] != "wired", l["dev"]))
    return out


def net_device(action, dev):
    r = run(["sudo", "-n", "nmcli", "--wait", "30", "device", action, dev], timeout=40)
    if r is None:
        raise RuntimeError(f"{dev}: Zeitueberschreitung")
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "nmcli").strip().splitlines()[-1])


def net_disconnect(kind):
    """Kabel oder WLAN trennen. "device disconnect" haelt das Geraet getrennt, bis man wieder verbindet oder neu
    startet – sonst waehlte NetworkManager gleich das naechste bekannte Netz. Die gespeicherten Profile bleiben."""
    done = 0
    for l in net_links():
        if l["type"] == kind and l["connected"]:
            net_device("disconnect", l["dev"])
            done += 1
    log("Netzwerk: getrennt", kind, f"({done})")


def net_connect(kind):
    """Getrenntes Kabel wieder verbinden (WLAN laeuft ueber wifi_connect, dort zaehlt das gewaehlte Netz)."""
    for l in net_links():
        if l["type"] == kind and l["ready"]:
            net_device("connect", l["dev"])


def net_mode_get(s=None):
    """Worueber das Internet laeuft: "wired" (nur Kabel), "wifi" (nur WLAN) oder "both"."""
    m = (s or settings_load()).get("net_mode")
    return m if m in ("wired", "wifi", "both") else "both"


def nm_profiles(kind):
    """UUIDs der gespeicherten NetworkManager-Profile eines Typs ("wired"/"wifi")."""
    r = run(["sudo", "-n", "nmcli", "-t", "-f", "UUID,TYPE", "connection", "show"], timeout=10)
    out = []
    for line in (r.stdout.splitlines() if r and r.returncode == 0 else []):
        uuid, typ = (nm_split(line) + ["", ""])[:2]
        if uuid and NM_TYPES.get(typ) == kind:
            out.append(uuid)
    return out


def net_metrics_reset():
    """Eine aeltere Einstellung „bevorzugt ueber WLAN“ (Routen-Metrik der WLAN-Profile) zuruecknehmen."""
    for u in nm_profiles("wifi"):
        run(["sudo", "-n", "nmcli", "connection", "modify", "uuid", u, "ipv4.route-metric", "-1", "ipv6.route-metric", "-1"], timeout=15)


def net_mode_set(mode):
    if mode not in ("wired", "wifi", "both"):
        raise ValueError("unbekannte Verbindungsart")
    if mode != "both" and mode not in {l["type"] for l in net_links()}:
        raise ValueError("Dieser Anschluss ist nicht vorhanden")
    net_metrics_reset()
    r = run(["sudo", "-n", PKG_HELPER, "netmode", mode], timeout=90)
    if r is None or r.returncode != 0:
        raise ValueError(((r.stderr or r.stdout or "nmcli") if r else "Zeitueberschreitung").strip().splitlines()[-1])
    s = settings_load()
    s["net_mode"] = mode
    settings_save(s)
    log("Netzwerk: Internet ueber", mode)


def nm_split(line):
    out, cur, esc = [], "", False
    for ch in line:
        if esc:
            cur += ch
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


def wifi_scan():
    # USB-Sticks brauchen fuer einen vollen Suchlauf oft mehr als 10 s. Reicht die Zeit nicht,
    # die zuletzt gefundenen Netze zeigen statt eines Fehlers.
    base = ["sudo", "-n", "nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list"]
    r = run(base + ["--rescan", "yes"], timeout=30)
    if not r or r.returncode != 0:
        old = run(base + ["--rescan", "no"], timeout=10)
        if old and old.returncode == 0 and old.stdout.strip():
            r = old
    if r is None:
        raise RuntimeError("WLAN-Suche dauert zu lange – ist ein WLAN-Adapter angeschlossen?")
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "WLAN-Suche fehlgeschlagen")
    nets: dict = {}
    for line in r.stdout.splitlines():
        use, ssid, sig, sec = (nm_split(line) + ["", "", "", ""])[:4]
        if not ssid:
            continue
        n = {"ssid": ssid, "signal": int(sig or 0), "secure": bool(sec and sec != "--"),
             "active": use.strip() == "*"}
        o = nets.get(ssid)                       # gleiches Netz mehrfach (Frequenzen, Zellen): staerkstes zeigen,
        if o:                                   # "aktiv" aber behalten (iPhone-Hotspot meldet sich oft doppelt)
            n["active"] = n["active"] or o["active"]
            if o["signal"] >= n["signal"]:
                o["active"] = n["active"]
                continue
        nets[ssid] = n
    saved = wifi_saved()
    for n in nets.values():
        n["known"] = n["ssid"] in saved          # Profil vorhanden: Verbinden ohne Passwort-Abfrage
    return sorted(nets.values(), key=lambda n: (-n["active"], -n["signal"]))


def wifi_saved():
    """Gespeicherte WLAN-Profile: {SSID: [UUIDs, zuletzt benutztes zuerst]} (Name und SSID koennen abweichen)."""
    r = run(["sudo", "-n", "nmcli", "-t", "-f", "UUID,TYPE,TIMESTAMP", "connection", "show"], timeout=10)
    found = []
    for line in (r.stdout.splitlines() if r and r.returncode == 0 else []):
        uuid, typ, ts = (nm_split(line) + ["", "", ""])[:3]
        if not uuid or NM_TYPES.get(typ) != "wifi":
            continue
        g = run(["sudo", "-n", "nmcli", "-g", "802-11-wireless.ssid", "connection", "show", uuid], timeout=10)
        if g and g.returncode == 0 and g.stdout.strip():
            # -g maskiert Doppelpunkte und Backslashes
            found.append((int(ts) if ts.isdigit() else 0, uuid, ":".join(nm_split(g.stdout.strip()))))
    out: dict = {}
    for _, uuid, ssid in sorted(found, key=lambda f: -f[0]):
        out.setdefault(ssid, []).append(uuid)
    return out


def wifi_profiles(ssid):
    """UUIDs aller gespeicherten WLAN-Profile fuer dieses Netz."""
    return wifi_saved().get(ssid, [])


def wifi_forget(uuids):
    for u in uuids:
        run(["sudo", "-n", "nmcli", "connection", "delete", "uuid", u], timeout=15)


# nmcli-Meldungen (deutsch oder englisch, je nach Locale) -> Schluessel aus web/i18n
WIFI_ERRORS = [
    ("wifi.err.password", ("secrets were required", "geheimdaten", "wireless-security.psk", "passwd-file",
                           "4-way handshake", "invalid passphrase", "property 'psk' is invalid",
                           "eigenschaft »psk« ist ungültig", "psk: ungültig", "psk: invalid")),
    ("wifi.err.notFound", ("no network with ssid", "kein netzwerk mit ssid", "no suitable device",
                           "kein geeignetes gerät")),
    ("wifi.err.noDevice", ("no wi-fi device", "kein wlan-gerät", "kein wi-fi-gerät")),
    ("wifi.err.timeout", ("timeout", "zeitüberschreitung", "timed out")),
]


def wifi_error(text):
    low = text.lower()
    for key, needles in WIFI_ERRORS:
        if any(n in low for n in needles):
            return key
    # sonst die eigentliche Fehlerzeile ohne Warnungen und "Error:"-Vorsatz
    lines = [l.strip() for l in text.splitlines() if l.strip()
             and not l.strip().lower().startswith(("warning:", "warnung:"))]
    msg = lines[-1] if lines else "Verbindung fehlgeschlagen"
    for pre in ("Error: ", "Fehler: "):
        if msg.startswith(pre):
            msg = msg[len(pre):]
    return msg


def wifi_connect(ssid, password):
    """Verbinden, auch beim Wechsel von einem anderen Netz. Ohne Passwort nimmt es das gespeicherte Profil (die
    Oberflaeche fragt bekannte Netze nicht ab; lehnt der Router das gespeicherte Passwort ab, kommt
    wifi.err.password und sie fragt dann doch). Mit Passwort wird ein altes Profil fuer dasselbe Netz vorher
    entfernt (sonst nimmt NetworkManager dessen gespeichertes, evtl. falsches Passwort); scheitert der Versuch,
    wird das dabei angelegte Profil wieder geloescht. Fehler kommen als Schluessel "wifi.err.*" oder als Klartext."""
    before = wifi_profiles(ssid)
    if password:
        wifi_forget(before)
        before = []
    if before:
        args = ["sudo", "-n", "nmcli", "--wait", "90", "connection", "up", "uuid", before[0]]
    else:
        args = ["sudo", "-n", "nmcli", "--wait", "90", "device", "wifi", "connect", ssid]
    if password:
        args += ["password", password]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=100)
        err = None if r.returncode == 0 else wifi_error((r.stderr or "") + "\n" + (r.stdout or ""))
    except subprocess.TimeoutExpired:
        err = "wifi.err.timeout"
    if err:
        wifi_forget([u for u in wifi_profiles(ssid) if u not in before])
        log("WLAN:", ssid, "->", err)
        raise RuntimeError(err)


def share_info():
    share = Path.home() / "share"
    r = run(["pgrep", "-x", "smbd"])
    smb = bool(r and r.returncode == 0)
    import pwd
    return {"path": str(share), "exists": share.is_dir(), "samba": smb, "name": "share",
            "user": pwd.getpwuid(os.getuid()).pw_name}


# ---------------------------------------------------------------------------
#  TV: Sender aus aller Welt (Verzeichnis von iptv-org, frei empfangbare Streams)
# ---------------------------------------------------------------------------
IPTV_API = tvindex.IPTV_API
CACHE = BASE / "cache"
TV_DB = CACHE / tvindex.DB_NAME              # Senderverzeichnis, gebaut von tvindex.py (eigener, kurzlebiger Prozess)
TVFAVS = BASE / "tvfavs.json"
TVRECENT = BASE / "tvrecent.json"           # zuletzt gesehene Sender (Player: Reiter „Zuletzt“)
UA = tvindex.UA


def fetch(url, dest, max_age):
    """Datei herunterladen, wenn sie fehlt oder aelter als max_age Sekunden ist."""
    return tvindex.fetch(url, dest, max_age, log)


class IPTV:
    def __init__(self):
        self.lock = threading.Lock()
        self.state, self.error = "idle", None
        self.count, self.countries = 0, []
        self.loaded_at = 0.0
        self.tried_at = 0.0         # letzter Versuch, das Verzeichnis neu zu bauen
        self.building = False
        self.now = None
        self.zap_keys = []          # Liste, in der der Player mit ▲▼ umschaltet (aus der heraus gestartet wurde)
        self.recent = tvrecent_load()
        self.broken = {}            # Sender -> Zeitpunkt, an dem er zuletzt nicht erreichbar war
        self.failed = None          # Rueckfall (nacktes mpv): zuletzt gescheiterter Sender, fuer die Meldung
        self.raw = False            # "tv" laeuft gerade als nacktes mpv (Stufe 3)

    def _take(self, got):
        self.count, self.countries, self.loaded_at = got
        self.state, self.error = "ready", None

    def ensure(self):
        """Vorhandene Datei sofort nutzen; ist sie aelter als ein Tag, im Hintergrund erneuern."""
        now = time.time()
        with self.lock:
            if not self.count:
                got = tvindex.info(TV_DB)
                if got:
                    self._take(got)
            fresh = self.count and now - self.loaded_at < 86400
            if fresh or self.building or (self.count and now - self.tried_at < 600):
                return
            self.building, self.tried_at = True, now
            if not self.count:
                self.state = "loading"
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        err = None
        try:
            r = subprocess.run(["nice", "-n", "10", sys.executable, str(BASE / "tvindex.py"), str(CACHE)],
                               capture_output=True, text=True, timeout=900)
            if r.returncode != 0:
                err = (r.stderr.strip().splitlines() or ["tvindex"])[-1]
        except Exception as e:  # noqa: BLE001
            err = str(e)
        got = None if err else tvindex.info(TV_DB)
        with self.lock:
            self.building = False
            if got:
                self._take(got)
            else:
                self.state, self.error = ("ready" if self.count else "error"), err or "tv.sqlite"
        if got:
            log(f"TV-Verzeichnis: {got[0]} Sender")
        else:
            log("TV-Verzeichnis nicht ladbar:", err)

    def _db(self, fn, fallback):
        """Abfrage der Datei; fehlt sie (geloescht, Platte voll), wird sie beim naechsten ensure() neu gebaut."""
        if not self.count:
            return fallback
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            log("TV-Verzeichnis:", e)
            with self.lock:
                self.count, self.tried_at = 0, 0.0
            return fallback

    @staticmethod
    def public(e):
        return {k: e[k] for k in ("key", "cid", "name", "country", "cats", "quality", "logo") if k in e}

    def page(self, q="", country="", cat="", letter="", offset=0, limit=TV_PAGE):
        self.ensure()
        res = self._db(lambda: tvindex.page(TV_DB, q, country, cat, letter, offset, limit), None) or tvindex.empty_page()
        res["items"] = [self.mark(i) for i in res["items"]]
        return res

    def mark(self, pub):
        """Oeffentlicher Eintrag + "broken", wenn der Sender in den letzten 24 h nicht erreichbar war."""
        t = self.broken.get(pub.get("key"))
        if t and time.time() - t < 86400:
            pub = dict(pub, broken=True)
        return pub

    def filtered_keys(self, q="", country="", cat=""):
        """Alle Sender zu Land/Thema/Suche (ohne Buchstabe, ohne Seiten) – Reihenfolge wie die Liste."""
        return self._db(lambda: tvindex.keys(TV_DB, q, country, cat), [])

    def search(self, q, country, cat, limit=80):
        """Alte Schnittstelle (/api/tv/search, z. B. fuer Forks): nur die ersten Treffer als Liste."""
        return self.page(q, country, cat, limit=limit)["items"]

    def status(self):
        now = None
        if self.now and "tv" in APPS.running():
            now = self.now
        return {"state": self.state, "error": self.error, "count": self.count,
                "countries": [{"code": c, "n": n} for c, n in self.countries[:40]], "now": now, "failed": self.failed,
                "region": region(), "quick": region_quick()}

    def entry(self, key):
        return self.entries([key]).get(key)

    def entries(self, keys):
        """{Sender: Eintrag} aus dem Verzeichnis; was dort fehlt, kommt aus Favoriten und Verlauf."""
        out = self._db(lambda: tvindex.entries(TV_DB, keys), {})
        if len(out) < len(set(keys)):
            for f in reversed(tvfavs_load() + list(self.recent)):
                if f.get("key") in keys and f.get("key") not in out:
                    out[f["key"]] = f
        return out

    def set_zap(self, key, ctx):
        """Zapp-Liste fuer den Player: Favoriten oder die Liste mit Land/Thema/Suche, aus der gestartet wurde
        (ohne Buchstaben-Filter, hoechstens 2000 Sender rund um den gewaehlten)."""
        keys = []
        if isinstance(ctx, dict):
            if ctx.get("favs"):
                keys = [f.get("key") for f in tvfavs_load() if f.get("key")]
            elif self.count:
                country = str(ctx.get("country") or "")
                keys = self.filtered_keys(str(ctx.get("q") or ""), "" if country == "*" else country, str(ctx.get("cat") or ""))
        if key not in keys:
            if not keys and key in self.zap_keys:
                return
            keys = keys or [f.get("key") for f in tvfavs_load() if f.get("key")]
            if key not in keys:
                keys = [key] + keys
        if len(keys) > 2000:
            i = keys.index(key)
            keys = keys[max(0, i - 1000):i + 1000]
        self.zap_keys = keys

    def zap(self):
        found = self.entries(self.zap_keys)
        items = [self.mark(self.public(found[k])) for k in self.zap_keys if k in found]
        return {"items": items, "favs": [self.mark(self.public(f)) for f in tvfavs_load()],
                "recent": [self.mark(self.public(f)) for f in self.recent], "key": (self.now or {}).get("key")}

    def remember(self, e):
        self.recent = [e] + [r for r in self.recent if r.get("key") != e.get("key")]
        self.recent = self.recent[:15]
        tvrecent_save(self.recent)

    def tune(self, key):
        """Player schaltet um: Stream-Adresse (bleibt im Launcher-Verzeichnis, nie in den Listen) + Angaben."""
        e = self.entry(key)
        if not e:
            raise ValueError("Sender unbekannt")
        RADIO.stop()
        self.now = self.public(e)
        self.broken.pop(key, None)
        self.remember(e)
        log("TV:", e.get("name"), e.get("url"))
        return {"entry": self.mark(self.public(e)), "url": e["url"], "ref": e.get("ref") or "", "ua": e.get("ua") or "",
                "recent": [self.mark(self.public(f)) for f in self.recent]}

    def mark_broken(self, key, reason=""):
        self.broken[key] = time.time()
        e = self.entry(key)
        log("TV: nicht erreichbar:", (e or {}).get("name", key), reason)

    def play(self, key, ctx=None):
        e = self.entry(key)
        if not e:
            raise ValueError("Sender unbekannt")
        self.set_zap(key, ctx)
        RADIO.stop()
        self.failed = None
        if PLAYERS.level() < 3:
            PLAYERS.start("tv", key, mode="tv")
        else:
            self.play_raw(e)
            self.remember(e)
        self.now = self.public(e)
        return self.status()

    def play_raw(self, e):
        """Stufe 3: nacktes mpv im Vollbild (wie vor dem eigenen Player), mit Hardware-Decoding."""
        args = ["mpv", "--fs", "--force-window=immediate", "--keep-open=no",
                f"--title=TV · {e['name']}", "--cache=yes", "--demuxer-max-bytes=64MiB", "--hwdec=auto-safe",
                "--network-timeout=10",           # ohne stream-lavf-o=reconnect: bremst HLS-Sender aus (s. Player)
                "--ytdl=no"]
        if os.environ.get("VS_WEAK", "1" if os.uname().machine in ("i386", "i486", "i586", "i686") else "0") == "1":
            # schwache Hardware (32 Bit, wie im Player): Xv statt OpenGL, Software-Decoding, niedrigste Qualitaet
            args = [a for a in args if not a.startswith("--hwdec=")] + [
                "--hwdec=no", "--vo=xv,x11", "--hls-bitrate=min", "--vd-lavc-fast=yes",
                "--vd-lavc-skiploopfilter=nonref", "--sws-scaler=fast-bilinear", "--sws-allow-zimg=no"]
        if e.get("ref"):
            args.append(f"--referrer={e['ref']}")
        if e.get("ua"):
            args.append(f"--user-agent={e['ua']}")
        args.append(e["url"])
        APPS.close("media")
        APPS.close("ytlight")
        APPS.close("tv")
        APPS.start("tv", args)
        self.raw = True
        proc = APPS._get("tv")
        if proc:
            threading.Thread(target=self._watch_raw, args=(e, proc), daemon=True).start()

    def _watch_raw(self, e, proc):
        t0 = time.monotonic()
        rc = proc.wait()
        if rc not in (0, -signal.SIGTERM, -signal.SIGKILL) and time.monotonic() - t0 < 30:
            self.failed = {"key": e["key"], "name": e["name"], "t": time.time()}
            self.mark_broken(e["key"], f"mpv-Code {rc}")


def tvfavs_load():
    try:
        return json.loads(TVFAVS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def tvrecent_load():
    try:
        d = json.loads(TVRECENT.read_text(encoding="utf-8"))
        return [x for x in d if isinstance(x, dict) and x.get("key") and x.get("url")]
    except (OSError, ValueError):
        return []


def tvrecent_save(items):
    try:
        tmp = TVRECENT.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(TVRECENT)
    except OSError as e:
        log("tvrecent.json:", e)


def tvfavs_save(items):
    tmp = TVFAVS.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(TVFAVS)


TV = IPTV()


# ---------------------------------------------------------------------------
#  EPG: Elektronischer Programmführer für TV-Sender
# ---------------------------------------------------------------------------
EPG_CONFIG_FILE = Path("/usr/local/share/voidstation/epg-url")


class EPGManager:
    """Verwaltet Programmvorschau (EPG) für TV-Sender."""

    def __init__(self):
        self.lock = threading.Lock()
        self.cache_file = CACHE / "epg.json"
        self.data = {}
        self.name_map = {}
        self.loaded_at = 0.0
        self.last_attempt = 0.0
        self.loading = False
        # Beim Start nur den kompakten JSON-Cache lesen (dauert wenige Millisekunden)
        self._load_cache()

    @staticmethod
    def _get_url():
        env = os.environ.get("VOIDSTATION_EPG_URL", "").strip()
        if env:
            return env
        for p in (EPG_CONFIG_FILE, BASE / "epg-url"):
            try:
                if p.exists():
                    u = p.read_text(encoding="utf-8").strip()
                    if u:
                        return u
            except OSError:
                pass
        return ""

    def ensure(self):
        url = self._get_url()
        has_local = any(p.exists() for p in (CACHE / "epg.xml.gz", CACHE / "epg.xml", BASE / "epg.xml.gz", BASE / "epg.xml"))
        if not url and not has_local:
            return
        now = time.time()
        with self.lock:
            if self.loading:
                return
            # Daten noch aktuell (< 24 h)?
            if self.data and (now - self.loaded_at < 86400):
                return
            # Nach einem Fehler/Versuch mindestens 1 Stunde warten
            if now - self.last_attempt < 3600:
                return
            self.loading = True
            self.last_attempt = now
        threading.Thread(target=self._fetch_and_load, daemon=True).start()

    def _fetch_and_load(self):
        try:
            url = self._get_url()
            if url:
                day = 86400
                is_gz = url.split("?")[0].endswith(".gz")
                xml_dest = CACHE / ("epg.xml.gz" if is_gz else "epg.xml")
                try:
                    fetch(url, xml_dest, day)
                except Exception as e:
                    log("EPG Download fehlgeschlagen:", e)

            # XMLTV im Hintergrund parsen und in epg.json cachen
            self._parse_xml_source()
        finally:
            with self.lock:
                self.loading = False

    @staticmethod
    def _parse_ts(s):
        s = s.strip()
        if not s:
            return 0
        from datetime import datetime, timezone
        try:
            if " " in s:
                return datetime.strptime(s, "%Y%m%d%H%M%S %z").timestamp()
            return datetime.strptime(s[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).timestamp()
        except Exception:
            return 0

    def _load_cache(self):
        for p in (self.cache_file, BASE / "epg.json"):
            if p.exists():
                try:
                    raw = json.loads(p.read_text(encoding="utf-8"))
                    with self.lock:
                        self.data = raw.get("programs", raw)
                        self.name_map = raw.get("name_map", {})
                        self.loaded_at = float(raw.get("loaded_at", p.stat().st_mtime))
                    return True
                except Exception as e:
                    log("EPG Cache nicht lesbar:", e)
        return False

    def _parse_xml_source(self):
        """Parst XMLTV im Hintergrund und schreibt eine kleine epg.json (nur jetzt bis +24h)."""
        import gzip
        import xml.etree.ElementTree as ET

        source_file = None
        for p in (CACHE / "epg.xml.gz", CACHE / "epg.xml", BASE / "epg.xml.gz", BASE / "epg.xml"):
            if p.exists():
                source_file = p
                break

        if not source_file:
            return

        try:
            with open(source_file, "rb") as test_f:
                magic = test_f.read(2)
            is_gz = (magic == b"\x1f\x8b")

            f = gzip.open(source_file, "rb") if is_gz else open(source_file, "rb")
            data: dict = {}
            name_map = {}
            now_ts = time.time()
            cutoff_past = now_ts - 7200       # 2 Stunden Puffer in die Vergangenheit
            cutoff_future = now_ts + 86400    # bis +24 Stunden vorausschauend

            try:
                for event, elem in ET.iterparse(f, events=("end",)):
                    if elem.tag == "channel":
                        cid = elem.get("id", "").strip()
                        dn_el = elem.find("display-name")
                        if cid and dn_el is not None and dn_el.text:
                            n_clean = dn_el.text.strip().lower()
                            name_map[n_clean] = cid
                            name_map[n_clean.replace(" ", "")] = cid
                            name_map[n_clean.replace(" hd", "").strip()] = cid
                        elem.clear()
                    elif elem.tag == "programme":
                        ch = elem.get("channel", "").strip()
                        s_str = elem.get("start", "").strip()
                        e_str = elem.get("stop", "").strip()
                        s_ts = self._parse_ts(s_str)
                        e_ts = self._parse_ts(e_str)
                        # Nur relevante Sendungen speichern -> kleine epg.json
                        if s_ts and e_ts and e_ts >= cutoff_past and s_ts <= cutoff_future:
                            t_el = elem.find("title")
                            d_el = elem.find("desc")
                            title = t_el.text if t_el is not None and t_el.text else ""
                            desc = d_el.text if d_el is not None and d_el.text else ""
                            data.setdefault(ch, []).append({"start": s_ts, "end": e_ts, "title": title, "desc": desc})
                        elem.clear()
            finally:
                f.close()

            with self.lock:
                self.data = data
                self.name_map = name_map
                self.loaded_at = now_ts

            # Kompakte epg.json schreiben (atomarer Tmp-Write)
            try:
                CACHE.mkdir(parents=True, exist_ok=True)
                payload = json.dumps({"loaded_at": now_ts, "name_map": name_map, "programs": data}, ensure_ascii=False)
                tmp = self.cache_file.with_suffix(".tmp")
                tmp.write_text(payload, encoding="utf-8")
                tmp.replace(self.cache_file)
            except Exception as e:
                log("EPG Cache schreiben fehlgeschlagen:", e)

        except Exception as e:
            log("EPG XML-Parsing fehlgeschlagen:", e)

    def get_program(self, channel_id, channel_name=""):
        self.ensure()
        with self.lock:
            prog = self.data.get(channel_id)
            if not prog and channel_name:
                clean_name = channel_name.strip().lower()
                mapped = (self.name_map.get(clean_name) or
                          self.name_map.get(clean_name.replace(" ", "")) or
                          self.name_map.get(clean_name.replace(" hd", "").strip()))
                if mapped:
                    prog = self.data.get(mapped)
            if not prog and channel_name:
                prog = self.data.get(channel_name)

        now_ts = time.time()
        if prog and isinstance(prog, list):
            current, next_p = None, None
            for p in prog:
                start = p.get("start", 0)
                end = p.get("end", 0)
                if start <= now_ts < end:
                    dur = max(1, end - start)
                    progress = min(100, max(0, int((now_ts - start) / dur * 100)))
                    current = {
                        "title": p.get("title", ""),
                        "desc": p.get("desc", ""),
                        "start": time.strftime("%H:%M", time.localtime(start)),
                        "stop": time.strftime("%H:%M", time.localtime(end)),
                        "end": time.strftime("%H:%M", time.localtime(end)),
                        "progress": progress
                    }
                elif now_ts < start and not next_p:
                    next_p = {
                        "title": p.get("title", ""),
                        "start": time.strftime("%H:%M", time.localtime(start)),
                        "stop": time.strftime("%H:%M", time.localtime(end)),
                        "end": time.strftime("%H:%M", time.localtime(end))
                    }
            if current:
                return {"current": current, "next": next_p}
        return None


EPG = EPGManager()


# ---------------------------------------------------------------------------
#  Videos & Musik: Mediathek fuer den Player (~/share/Videos, ~/share/Musik, USB-Laufwerke)
# ---------------------------------------------------------------------------
VIDEO_EXT = {".mp4", ".mkv", ".avi", ".mov", ".m4v", ".webm", ".ts", ".m2ts", ".mts", ".mpg", ".mpeg", ".wmv",
             ".flv", ".ogv", ".3gp", ".vob", ".divx"}
EMBED_EXT = {".mp3", ".m4a", ".flac"}             # Cover/Tags in die Datei schreiben (ffmpeg, ohne Neukodierung)
AUDIO_EXT = {".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".aac", ".wav", ".wma", ".ape", ".mka", ".wv", ".aiff", ".alac"}
COVER_NAMES = ("cover.jpg", "cover.png", "folder.jpg", "folder.png", "front.jpg", "front.png", "albumart.jpg", "album.jpg")
RESUME = BASE / "resume.json"


def natural_key(name):
    """„Folge 2“ vor „Folge 10“: Zahlen als Zahlen sortieren, ohne Gross-/Kleinschreibung."""
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", tv_fold(name))]


class DvdDrive:
    """DVD-Laufwerk fuer "Videos & Musik": Disc erkennen (ioctl CDROM_DRIVE_STATUS – laeuft die Disc nicht an),
    Titel lesen (lsdvd, einmal je Disc, im Hintergrund), auswerfen. Abgespielt wird mit mpv: dvd://<n>/<geraet>,
    mpv zaehlt Titel ab 0, lsdvd ab 1. DVD-Menues kann mpv nicht – deshalb die Titelliste (Serien: ein Titel je Folge).
    Kopiergeschuetzte Kauf-DVDs entschluesselt libdvdread ueber libdvdcss (bei Void eine Abhaengigkeit von mpv)."""
    CDROM_DRIVE_STATUS = 0x5326
    CDS_DISC_OK = 4
    MIN_TITLE = 60                                       # kuerzere Titel (Warnhinweise, Logos, Menues) ausblenden

    def __init__(self):
        self.lock = threading.Lock()
        self.cache = {}                                  # geraet -> {"key": (status, groesse), "info": ..., "busy": bool}

    @staticmethod
    def _test_disc():
        """Zum Ausprobieren ohne Spiele-Disc: Steht in <BASE>/test-disc der Pfad eines Abbilds, gilt es als eingelegt."""
        try:
            p = (BASE / "test-disc").read_text(encoding="utf-8").strip()
            return p if p and Path(p).is_file() else ""
        except OSError:
            return ""

    @classmethod
    def devices(cls):
        return ([p] if (p := cls._test_disc()) else []) + sorted(str(p) for p in Path("/dev").glob("sr[0-9]*"))

    def _status(self, dev):
        import fcntl
        if not dev.startswith("/dev/"):
            return self.CDS_DISC_OK
        try:
            fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            return -1
        try:
            return fcntl.ioctl(fd, self.CDROM_DRIVE_STATUS, 0x7fffffff)
        except OSError:
            return -1
        finally:
            os.close(fd)

    @staticmethod
    def _size(dev):
        try:
            if not dev.startswith("/dev/"):
                return Path(dev).stat().st_size
            return int(Path(f"/sys/block/{Path(dev).name}/size").read_text().strip() or 0)
        except (OSError, ValueError):
            return 0

    @staticmethod
    def parse(text):
        """lsdvd -Ox (XML) -> {"label", "titles": [{ix, length, aspect, format, chapters, audio, subs}], "longest"}.
        Mit regulaeren Ausdruecken statt XML-Parser: lsdvd schreibt Disc-Namen ungefiltert."""
        def tag(name, block, default=""):
            m = re.search(rf"<{name}>(.*?)</{name}>", block, re.S)
            return html_unescape(m.group(1).strip()) if m else default
        head = text.split("<track>", 1)[0]
        titles = []
        for block in re.findall(r"<track>(.*?)</track>", text, re.S):
            try:
                ix, length = int(tag("ix", block, "0")), float(tag("length", block, "0"))
            except ValueError:
                continue
            if ix > 0:
                titles.append({"ix": ix, "length": round(length, 1), "aspect": tag("aspect", block),
                               "format": tag("format", block), "chapters": block.count("<chapter>"),
                               "audio": block.count("<audio>"), "subs": block.count("<subp>")})
        longest = max(titles, key=lambda t: t["length"])["ix"] if titles else 0
        label = tag("title", head).replace("_", " ").strip()
        return {"label": "" if label.lower() == "unknown" else label, "titles": titles, "longest": longest}

    def _scan(self, dev, key):
        info = None
        exe = shutil.which("lsdvd")
        import discid                                    # nur bei Bedarf, spart dem Launcher Speicher
        game = discid.identify(dev)                      # PlayStation-Spiel statt Film?
        if game:
            log(f"Laufwerk {dev}: {game['kind']}, {game['serial']}")
            info = {"label": game["label"], "titles": [], "longest": 0, "game": game}
        elif exe:
            r = run([exe, "-Ox", "-v", "-a", "-c", "-s", dev], timeout=90)
            if r and r.stdout.strip():
                info = self.parse(r.stdout)
            else:
                log("DVD: lsdvd ohne Ergebnis", dev, (r.stderr.strip().splitlines() or [""])[-1][:200] if r else "")
        else:
            log("DVD: lsdvd fehlt")
        with self.lock:
            c = self.cache.get(dev)
            if c and c["key"] == key:
                c.update(info=info or {"label": "", "titles": [], "longest": 0}, busy=False)
        if info:
            log(f"DVD {dev}: „{info['label']}“, {len(info['titles'])} Titel")

    def discs(self):
        """Eingelegte Discs: [{dev, label, ready, n}]; liest neue Discs im Hintergrund ein."""
        out = []
        for dev in self.devices():
            st = self._status(dev)
            with self.lock:
                if st != self.CDS_DISC_OK:
                    self.cache.pop(dev, None)
                    continue
                key = (st, self._size(dev))
                c = self.cache.get(dev)
                if not c or c["key"] != key:
                    c = self.cache[dev] = {"key": key, "info": None, "busy": True}
                    threading.Thread(target=self._scan, args=(dev, key), daemon=True).start()
                info = c["info"]
            game = (info or {}).get("game")
            out.append({"dev": dev, "label": (info or {}).get("label", ""), "ready": info is not None,
                        "n": len(self.shown(info)) if info else 0, "game": game["kind"] if game else ""})
        return out

    def game(self, dev):
        """Eingelesene PlayStation-Disc in diesem Laufwerk -> {"kind", "serial", "crc", "label"} oder None."""
        self.discs()
        with self.lock:
            c = self.cache.get(dev)
            return (c["info"] or {}).get("game") if c else None

    def game_for(self, tile):
        """Disc, die zu dieser Kachel passt (fuer die Spieleliste) -> {"dev", "name", "label", "serial", "opts"} oder None."""
        kind = {"duckstation": "ps1", "pcsx2": "ps2"}.get(tile)
        for d in self.discs() if kind else []:
            if d["game"] != kind:
                continue
            g = self.game(d["dev"]) or {}
            label = g.get("label", "")
            if re.match(r"[A-Z]{4}[_-]?\d", label):       # Volumename ist nur die Seriennummer
                label = ""
            return {"dev": d["dev"], "name": os.path.basename(d["dev"]), "label": label.replace("_", " ").strip(),
                    "serial": g.get("serial") or "", "opts": bool(g.get("serial") and (kind == "ps1" or g.get("crc")))}
        return None

    def shown(self, info):
        t = [x for x in (info or {}).get("titles", []) if x["length"] >= self.MIN_TITLE]
        return t or (info or {}).get("titles", [])

    def listing(self, dev):
        if dev not in self.devices():
            raise FileNotFoundError(dev)
        for _ in range(180):                             # Disc wird gerade gelesen: bis zu 90 s warten
            self.discs()
            with self.lock:
                c = self.cache.get(dev)
                if not c:
                    raise FileNotFoundError("keine Disc im Laufwerk")
                if c["info"] is not None:
                    info = c["info"]
                    break
            time.sleep(0.5)
        else:
            raise FileNotFoundError("Disc nicht lesbar")
        titles = self.shown(info)
        items = []
        if len(titles) > 1:
            items.append({"kind": "dvdall", "path": f"dvd://{titles[0]['ix'] - 1}/{dev}", "title": "", "n": len(titles)})
        for t in titles:
            items.append({"kind": "dvdtitle", "path": f"dvd://{t['ix'] - 1}/{dev}", "ix": t["ix"], "dur": t["length"],
                          "aspect": t["aspect"], "chapters": t["chapters"], "main": t["ix"] == info["longest"],
                          "title": "", "name": f"{t['ix']}", "thumb": ""})
        items.append({"kind": "eject", "path": f"dvd:{dev}", "title": ""})
        return {"path": f"dvd:{dev}", "name": info["label"], "parent": "", "items": items, "select": "",
                "audio": 0, "coversPending": 0, "dvd": dev}

    def eject(self, dev):
        if dev not in self.devices():
            raise ValueError("kein Laufwerk")
        with self.lock:
            self.cache.pop(dev, None)
        if not dev.startswith("/dev/"):                  # Testdatei (s. _test_disc): "auswerfen" = Eintrag weg
            (BASE / "test-disc").unlink(missing_ok=True)
            return True
        r = run(["eject", dev], timeout=20)
        return bool(r and r.returncode == 0)


DVD = DvdDrive()


class MediaLib:
    """Ordner auflisten, Vorschaubilder (ffmpegthumbnailer, zwischengespeichert), Weiterschauen (resume.json).
    Nur innerhalb von ~/share und eingehaengten Laufwerken unter /run/media und /media."""
    THUMBS = Path.home() / ".cache" / "voidstation" / "thumbs"

    def __init__(self):
        self.lock = threading.Lock()
        self.sem = threading.Semaphore(2)          # hoechstens zwei Vorschaubilder gleichzeitig (schwache Geraete)
        self.thumbnailer = shutil.which("ffmpegthumbnailer")
        self.mixed_cache = {}                      # Ordner -> (mtime, gemischt?)
        self.tags_cache = {}                       # Datei -> (mtime, Tags)
        self.art_done = {}                         # Datei -> (mtime, Kennung des Bildes) – Bild steht fest

    @staticmethod
    def share():
        return Path.home() / "share"

    @staticmethod
    def drives():
        out = []
        try:
            lines = Path("/proc/mounts").read_text().splitlines()
        except OSError:
            lines = []
        for line in lines:
            parts = line.split()
            if len(parts) < 2:
                continue
            mp = parts[1].replace("\\040", " ")
            if mp.startswith(("/run/media/", "/media/")) and mp.count("/") >= 2 and os.path.isdir(mp):
                out.append(mp)
        return sorted(set(out))

    def allowed_roots(self):
        return [self.share().resolve()] + [Path(d).resolve() for d in self.drives()]

    def resolve(self, path):
        try:
            p = Path(path).expanduser().resolve()
        except (OSError, RuntimeError):
            return None
        for r in self.allowed_roots():
            if p == r or r in p.parents:
                return p
        return None

    @staticmethod
    def own_cover(folder):
        """Cover eines Ordners: Bilddatei im Ordner (cover.jpg & Co.) oder heruntergeladenes im Zwischenspeicher."""
        for n in COVER_NAMES:
            c = folder / n
            if c.is_file():
                return c
        c = COVERS.cache_file(folder)
        return c if c.is_file() else None

    def cover_url(self, folder, depth=1):
        """Bild fuer einen Ordner; ohne eigenes das des ersten Unterordners mit Cover (Interpret -> erstes Album)."""
        c = self.own_cover(folder)
        if c is None and depth > 0:
            for sub in self._subdirs(folder)[:40]:
                c = self.own_cover(sub)
                if c is not None:
                    break
        if c is None:
            return ""
        try:
            m = int(c.stat().st_mtime)
        except OSError:
            m = 0
        if c.parent == COVERS.CACHE:
            return "/api/media/thumb?cover=" + urllib.parse.quote(str(c.name)) + f"&m={m}"
        return "/api/media/thumb?path=" + urllib.parse.quote(str(c)) + f"&m={m}"

    def thumb_url(self, p, kind, st=None):
        if kind == "video" and self.thumbnailer:
            m = int(st.st_mtime) if st else 0
            return "/api/media/thumb?path=" + urllib.parse.quote(str(p)) + f"&m={m}"
        if kind == "dir":
            return self.cover_url(p)
        if kind == "audio":                        # eigenes Bild des Titels, sonst das des Albums (art())
            c = self.own_cover(p.parent)
            try:
                cm = int(c.stat().st_mtime) if c is not None else 0
            except OSError:
                cm = 0
            m = int(st.st_mtime) if st else 0
            done = self.art_done.get(str(p))
            r = done[1] if done and st and done[0] == st.st_mtime else 0
            return "/api/media/thumb?art=" + urllib.parse.quote(str(p)) + f"&m={m}&c={cm}&r={r}"
        return ""

    def mixed(self, folder):
        """Liegen in diesem Ordner Titel aus verschiedenen Alben (z. B. alles lose in share/Musik)? Dann gibt es kein
        gemeinsames Cover – jeder Titel zeigt sein eigenes. Stichprobe ueber bis zu 8 Dateien, gemerkt bis sich der
        Ordner aendert. Ohne Album-Tags zaehlen verschiedene Interpreten."""
        folder = Path(folder)
        try:
            mt = folder.stat().st_mtime
        except OSError:
            return False
        hit = self.mixed_cache.get(str(folder))
        if hit and hit[0] == mt:
            return hit[1]
        files = COVERS._audio_files(folder)
        if len(files) < 2:
            res = False
        else:
            step = max(1, len(files) // 8)
            albums, artists, bare = set(), set(), 0
            for f in files[::step][:8]:
                t = COVERS._tags(f)
                if t.get("album"):
                    albums.add(t["album"].casefold())
                a = t.get("album_artist") or t.get("albumartist") or t.get("artist") or ""
                if a:
                    artists.add(a.casefold())
                if not t.get("album") and not a:
                    bare += 1
            # Titel mit Tags neben solchen ganz ohne: eher eine lose Sammlung als ein Album
            res = len(albums) > 1 or (not albums and len(artists) > 1) or (bare > 0 and bool(albums or artists))
        if res:
            self._drop_wrong_cover(folder, files)
        try:
            mt = folder.stat().st_mtime                # _drop_wrong_cover kann den Ordner geaendert haben
        except OSError:
            pass
        self.mixed_cache[str(folder)] = (mt, res)
        return res

    @staticmethod
    def _drop_wrong_cover(folder, files):
        """Fruehere Fassung der Cover-Suche hat in gemischten Ordnern das Bild des ersten Titels als cover.jpg
        abgelegt. Geloescht wird nur, was Byte fuer Byte genau dieses Bild ist – eigene Cover bleiben."""
        cands = [folder / "cover.jpg", COVERS.cache_file(folder)]
        cands = [c for c in cands if c.is_file()]
        if not cands or not files:
            return
        img = COVERS._embedded(files[0])
        if not img:
            return
        for c in cands:
            try:
                if c.stat().st_size == len(img) and c.read_bytes() == img:
                    c.unlink()
                    log("Cover: falsches Ordner-Cover entfernt (gemischter Ordner):", c)
            except OSError:
                pass

    def track_tags(self, p, st=None):
        st = st or p.stat()
        hit = self.tags_cache.get(str(p))
        if hit and hit[0] == st.st_mtime:
            return hit[1]
        t = COVERS._tags(p)
        self.tags_cache[str(p)] = (st.st_mtime, t)
        return t

    def art_file(self, p, online=False):
        """Bild zu einem Musiktitel, der Reihe nach:
        1. in die Datei eingebettetes Cover (einmal herausgeholt, zwischengespeichert)
        2. Cover des Ordners – ausser der Ordner mischt verschiedene Alben
        3. online gefundenes Cover zu Interpret + Album bzw. Interpret + Titel (Zwischenspeicher, gilt fuer alle
           Titel desselben Albums) – nur mit online=True wird gesucht (Hintergrund, CoverFetcher)
        Vor allem anderen: ein gleichnamiges Bild neben dem Titel ("Interpret - Titel.jpg") – fuer Titel, die keine Suche
        findet oder bei denen sie danebenliegt.
        Rueckgabe (Pfad oder None, fertig): fertig=False heisst, eine Suche im Netz koennte noch etwas bringen."""
        st = p.stat()
        for ext in (".jpg", ".jpeg", ".png", ".webp", ".JPG", ".PNG"):
            side = p.with_suffix(ext)
            if side.is_file():
                return self._art_found(p, st, side)
        key = hashlib.sha1(f"art:{p}:{int(st.st_mtime)}:{st.st_size}".encode()).hexdigest()
        out, none, wide = self.THUMBS / f"{key}.jpg", self.THUMBS / f"{key}.none", self.THUMBS / f"{key}.wide"
        if not out.exists() and not none.exists():
            self.THUMBS.mkdir(parents=True, exist_ok=True)
            with self.sem:
                if not out.exists() and not none.exists():
                    img = COVERS._embedded(p)
                    try:
                        if img:
                            if self._pic_wide(p):
                                wide.touch()
                            tmp = out.with_name(f"{key}.{threading.get_ident()}.tmp.jpg")
                            tmp.write_bytes(img)
                            tmp.replace(out)
                        else:
                            none.touch()
                    except OSError:
                        pass
        if out.exists() and not wide.exists():
            return self._art_found(p, st, out)
        # Eingebettet ist nur ein Standbild aus einem Video (YouTube: 16:9 oder 4:3) – lieber das echte Cover suchen
        # und das Standbild nur nehmen, wenn es keins gibt (bis dahin zeigt die Kachel es schon)
        still = out if out.exists() else None
        if still is not None:
            ac = COVERS.track_cache(p, self.track_tags(p, st))
            if ac is None:
                return self._art_found(p, st, still)
            if ac.is_file():
                return self._art_found(p, st, ac)
            if COVERS.track_missed(ac):
                return self._art_found(p, st, still)
            if online:
                ok = COVERS.fetch_track(p, self.track_tags(p, st), ac)
                if ok is None:
                    return still, False
                return self._art_found(p, st, ac if ok else still)
            return still, False
        if not self.mixed(p.parent):
            c = self.own_cover(p.parent)
            if c is not None:
                return self._art_found(p, st, c)
        ac = COVERS.track_cache(p, self.track_tags(p, st))
        if ac is None:                                 # weder Tags noch brauchbarer Dateiname
            return self._art_found(p, st, None)
        if ac.is_file():
            return self._art_found(p, st, ac)
        if COVERS.track_missed(ac):
            return self._art_found(p, st, None)
        if online:
            ok = COVERS.fetch_track(p, self.track_tags(p, st), ac)
            if ok is None:                             # kein Netz – offen lassen
                return None, False
            return self._art_found(p, st, ac if ok else None)
        return None, False

    @staticmethod
    def _pic_wide(p):
        """Ist das eingebettete Bild deutlich breiter als hoch (Video-Standbild statt Plattencover)?"""
        r = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0",
                 str(p)], timeout=15)
        try:
            w, h = (int(x) for x in (r.stdout.strip().split(",")[:2] if r and r.returncode == 0 else ()))
        except ValueError:
            return False
        return h > 0 and w / h >= 1.25

    def _art_found(self, p, st, f):
        try:
            tag = int(f.stat().st_mtime) % 100000 + 1 if f is not None else 0
        except OSError:
            tag = 0
        self.art_done[str(p)] = (st.st_mtime, tag)
        return f, True

    def write_art(self, p, cover):
        """Cover und fehlende Tags in die Datei schreiben (MP3, M4A, FLAC) – nur wenn etwas fehlt, vorhandene Tags
        bleiben unangetastet. Ueber eine Kopie im selben Ordner, die vor dem Ersetzen geprueft wird; Aenderungszeit
        und Rechte bleiben. Schreibgeschuetzte Ordner (USB-Stick, fremde Freigaben) werden still uebersprungen."""
        if p.suffix.lower() not in EMBED_EXT or not os.access(p.parent, os.W_OK) or not os.access(p, os.W_OK):
            return False
        ff, fp = shutil.which("ffmpeg"), shutil.which("ffprobe")
        if not ff or not fp:
            return False
        st = p.stat()
        if cover is not None and (cover.parent == self.THUMBS or COVERS._embedded(p)):   # schon ein Bild in der Datei
            cover = None
        tags = self.track_tags(p, st)
        have = {k for k, v in tags.items() if v}
        if "album_artist" in have or "albumartist" in have:
            have.add("artist")
        # Quelle fuer fehlende Tags: gefundene Aufnahme (MusicBrainz), sonst der Dateiname "Interpret - Titel"
        meta = {}
        ac = COVERS.track_cache(p, tags)
        if ac is not None and ac.with_suffix(".json").is_file():
            try:
                meta = json.loads(ac.with_suffix(".json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                meta = {}
        artist, _album, title = COVERS._track_names(p, tags)
        meta["artist"] = meta.get("artist") or artist
        meta["title"] = meta.get("title") or title
        add = {k: str(meta.get(k) or "").strip() for k in ("artist", "title", "album", "date", "track")}
        add = {k: v for k, v in add.items() if v and k not in have}
        if cover is None and not add:
            return False
        ours = self._marker(tags)
        ours.update({k: self._fp(v) for k, v in add.items()})
        if cover is not None:
            try:
                ours["cover"] = self._fp_bytes(cover.read_bytes())
            except OSError:
                ours["cover"] = None
        args = []
        if cover is not None:
            args += ["-i", str(cover), "-map", "0:a", "-map", "1:0", "-disposition:v:0", "attached_pic",
                     "-metadata:s:v", "title=Album cover", "-metadata:s:v", "comment=Cover (front)"]
        else:
            args += ["-map", "0"]
        for k, v in add.items():
            args += ["-metadata", f"{k}={v}"]
        # was von VoidStation stammt, je mit Fingerabdruck des Werts – "Cover neu suchen" nimmt nur heraus, was noch so
        # in der Datei steht; von Hand Korrigiertes (EasyTAG & Co.) bleibt
        args += ["-metadata", "VOIDSTATION=" + ",".join(k + (f":{h}" if h else "") for k, h in sorted(ours.items()))]
        if not self._rewrite(p, args):
            return False
        parts = (["Cover"] if cover is not None else []) + ([", ".join(add)] if add else [])
        log("In Datei geschrieben:", p.name, "–", " + ".join(parts))
        return True

    def _rewrite(self, p, args):
        """Datei mit ffmpeg neu schreiben (ohne Neukodierung): Kopie im selben Ordner, Pruefung (Ton da, Laenge
        gleich), dann ersetzen; Aenderungszeit und Rechte bleiben. args: weitere Eingaben, -map und -metadata."""
        ff, fp = shutil.which("ffmpeg"), shutil.which("ffprobe")
        if not ff or not fp:
            return False
        st = p.stat()
        tmp = p.with_name(f".{p.stem}.vs-tmp{p.suffix}")
        cmd = [ff, "-v", "error", "-y", "-i", str(p)] + args + ["-c", "copy", "-map_metadata", "0"]
        if p.suffix.lower() == ".mp3":
            cmd += ["-id3v2_version", "3", "-write_id3v1", "1"]
        if p.suffix.lower() == ".m4a":
            cmd += ["-movflags", "use_metadata_tags"]
        cmd.append(str(tmp))
        try:
            r = run(cmd, timeout=120)
            ok = bool(r and r.returncode == 0 and tmp.is_file() and tmp.stat().st_size > 1000)
            if ok:                                     # Probe: Ton noch da, Laenge unveraendert
                def dur(f):
                    q = run([fp, "-v", "error", "-select_streams", "a:0", "-show_entries", "format=duration:stream=codec_type",
                             "-of", "json", str(f)], timeout=30)
                    d = json.loads(q.stdout) if q and q.returncode == 0 else {}
                    return float((d.get("format") or {}).get("duration") or 0), bool(d.get("streams"))
                d0, _ = dur(p)
                d1, audio = dur(tmp)
                ok = audio and d1 > 0 and abs(d1 - d0) < 1.5
            if not ok:
                log("Cover/Tags: Datei nicht geaendert (Pruefung fehlgeschlagen):", p.name)
                return False
            shutil.copymode(p, tmp)
            os.utime(tmp, (st.st_atime, st.st_mtime))
            os.replace(tmp, p)
        except Exception as e:  # noqa: BLE001
            log("Cover/Tags: Datei nicht geaendert:", p.name, e)
            return False
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass
        self.tags_cache.pop(str(p), None)
        return True

    @staticmethod
    def _fp(v):
        return hashlib.sha1(str(v).strip().encode("utf-8")).hexdigest()[:10]

    @staticmethod
    def _fp_bytes(b):
        return hashlib.sha1(b).hexdigest()[:10]

    @staticmethod
    def _marker(tags):
        """Kennzeichen VOIDSTATION -> {Tag: Fingerabdruck}; Fassungen bis Oktober 2026 ohne Fingerabdruck -> None."""
        out = {}
        for item in filter(None, (tags.get("voidstation") or "").split(",")):
            k, _, h = item.partition(":")
            out[k.strip()] = h.strip() or None
        return out

    @staticmethod
    def _pic_raw(p):
        """Eingebettetes Bild so, wie es in der Datei steckt (ohne Umrechnen) – fuer den Vergleich mit dem, was
        VoidStation hineingeschrieben hat."""
        ff = shutil.which("ffmpeg")
        if not ff:
            return None
        try:
            r = subprocess.run([ff, "-v", "error", "-i", str(p), "-map", "0:v:0", "-c", "copy", "-f", "image2pipe", "-"],
                               capture_output=True, timeout=20, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            return None
        return r.stdout if r.returncode == 0 and r.stdout else None

    def reset_art(self, p):
        """Cover neu suchen: Was VoidStation selbst in die Datei geschrieben hat (Kennzeichen VOIDSTATION; bei
        Dateien aus der ersten Fassung ohne Kennzeichen: Tags, die genau der damals gefundenen Aufnahme entsprechen),
        wieder herausnehmen und Zwischenspeicher wie "nichts gefunden" fuer diesen Titel vergessen."""
        tags = COVERS._tags(p)
        marker = self._marker(tags)
        ours = set()
        for k, h in marker.items():
            if h is None:                              # Kennzeichen ohne Fingerabdruck (aeltere Fassung): wie bisher
                ours.add(k)
            elif k == "cover":
                raw = self._pic_raw(p)
                if raw is not None and self._fp_bytes(raw) == h:
                    ours.add(k)
            elif tags.get(k) and self._fp(tags[k]) == h:
                ours.add(k)                            # steht noch so drin, wie VoidStation es schrieb
        kept = set(marker) - ours
        if kept:
            log("Cover neu suchen:", p.name, "– von Hand geaendert, bleibt:", ", ".join(sorted(kept)))
        if not marker and COVERS._embedded(p):         # erste Fassung schrieb immer Cover + Tags zusammen
            for c in COVERS.track_caches(p, tags):
                try:
                    meta = json.loads(c.with_suffix(".json").read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                same = {k for k in ("artist", "title", "album", "date", "track") if meta.get(k) and tags.get(k) == str(meta[k])}
                if not {"artist", "title"} <= same:
                    continue
                # Woher die Suche kam, sagt, was schon vorher in der Datei stand: geraten (nur Dateiname) -> alle Tags
                # von uns; ueber Interpret + Titel bzw. + Album -> diese Tags sind die eigenen der Datei
                native = {"guess": set(), "title": {"artist", "title"}, "album": {"artist", "album"}}[COVERS.cache_kind(p, tags, c)]
                ours = (same - native) | {"cover"}
                break
        orig = {k: v for k, v in tags.items() if k not in ours}
        for c in set(COVERS.track_caches(p, tags)) | set(COVERS.track_caches(p, orig)):
            COVERS.forget(c)
        if (ours or marker) and p.suffix.lower() in EMBED_EXT and os.access(p.parent, os.W_OK):
            args = ["-map", "0:a" if "cover" in ours else "0"]
            for k in sorted(ours - {"cover"}):
                args += ["-metadata", f"{k}="]
            args += ["-metadata", "VOIDSTATION="]
            if self._rewrite(p, args):
                log("Cover neu suchen:", p.name, "– entfernt:", ", ".join(sorted(ours)))
        self.tags_cache.pop(str(p), None)
        self.art_done.pop(str(p), None)

    def art_pending(self, p):
        """Ist fuer diesen Titel noch offen, welches Bild er bekommt? (billig, ohne ffmpeg/ffprobe)"""
        try:
            st = p.stat()
        except OSError:
            return False
        done = self.art_done.get(str(p))
        return not (done and done[0] == st.st_mtime)

    def art(self, path):
        """Bild zu einem Musiktitel fuer /api/media/thumb?art= (siehe art_file). Fehlt eins und koennte es online
        eins geben, sucht der CoverFetcher im Hintergrund danach – die Kachel bzw. der Player fragen spaeter nochmal."""
        p = self.resolve(path)
        if not p or not p.is_file() or p.suffix.lower() not in AUDIO_EXT:
            return None
        f, final = self.art_file(p)
        if not final:
            COVERS.add_track(p)
        if f is None:
            return None
        try:
            return f.read_bytes(), MIME.get(f.suffix.lower(), "image/jpeg")
        except OSError:
            return None

    @staticmethod
    def title(name):
        stem = name.rsplit(".", 1)[0] if "." in name else name
        return re.sub(r"[._]+", " ", stem).strip() or name

    def display_name(self, p, tags):
        """Anzeige eines Musiktitels -> (Titel, Interpret): Titel- und Interpret-Tag, wenn sie zusammenpassen; steckt
        im Titel-Tag "Interpret - Titel" (YouTube, Kanal als Interpret) oder fehlt er, der bereinigte Titel bzw.
        Dateiname als Ganzes, ohne Interpret ("Fat_Larry_s_Band_-_Act…" -> "Fat Larry's Band - Act Like You Know")."""
        t = (tags.get("title") or "").strip().lstrip("-–— ").strip()
        a = (tags.get("artist") or tags.get("album_artist") or tags.get("albumartist") or "").strip()
        if t and not COVERS.SEP.search(t):
            return t, a
        return COVERS._clean(t or self.title(p.name), tail=False) or t or p.stem, ""

    def _audio_names(self, items):
        """Titel und Interpret aus den Tags fuer die Kacheln und "Danach" (sonst stand dort der Dateiname). Tags
        werden je Datei einmal gelesen (bis zu 6 parallel) und bis zur naechsten Aenderung der Datei gemerkt."""
        from concurrent.futures import ThreadPoolExecutor

        def one(e):
            try:
                pth = Path(e["path"])
                title, artist = self.display_name(pth, self.track_tags(pth))
            except Exception:  # noqa: BLE001 – lieber Dateiname als gar keine Liste
                return
            if title:
                e["title"] = title
            if artist:
                e["sub"] = artist
        if not items:
            return
        with ThreadPoolExecutor(max_workers=6) as ex:
            list(ex.map(one, items))

    def resume_load(self):
        try:
            d = json.loads(RESUME.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def resume_set(self, path, pos, dur):
        p = self.resolve(path)
        if not p:
            raise ValueError("Pfad nicht erlaubt")
        try:
            pos, dur = float(pos), float(dur)
        except (TypeError, ValueError):
            raise ValueError("ungueltige Position")
        with self.lock:
            d = self.resume_load()
            if dur > 0 and 60 <= pos < dur * 0.95 and dur - pos > 60:
                d[str(p)] = {"pos": round(pos, 1), "dur": round(dur, 1), "t": int(time.time())}
            else:                                      # kaum angesehen oder fast fertig: nichts merken
                d.pop(str(p), None)
            if len(d) > 300:
                for k in sorted(d, key=lambda k: d[k].get("t", 0))[:len(d) - 300]:
                    del d[k]
            tmp = RESUME.with_suffix(".tmp")
            tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(RESUME)

    def entry(self, p, res=None):
        try:
            st = p.stat()
        except OSError:
            return None
        kind: str | None
        if p.is_dir():
            kind = "dir"
        else:
            ext = p.suffix.lower()
            kind = "video" if ext in VIDEO_EXT else "audio" if ext in AUDIO_EXT else None
            if not kind:
                return None
        e = {"name": p.name, "title": p.name if kind == "dir" else self.title(p.name), "path": str(p), "kind": kind,
             "mtime": int(st.st_mtime), "thumb": self.thumb_url(p, kind, st)}
        if kind != "dir":
            e["bytes"] = st.st_size
            r = (res or {}).get(str(p))
            if r:
                e["resume"] = {"pos": r.get("pos", 0), "dur": r.get("dur", 0)}
        return e

    def roots(self):
        share = self.share()
        out = [{"kind": "videos", "path": str(share / "Videos"), "title": "", "thumb": ""},
               {"kind": "music", "path": str(share / "Musik"), "title": "", "thumb": ""}]
        for d in self.drives():
            out.append({"kind": "drive", "path": d, "title": os.path.basename(d), "thumb": ""})
        for d in DVD.discs():                          # eingelegte DVD (Titel liest der Launcher im Hintergrund)
            out.append({"kind": "dvd", "path": "dvd:" + d["dev"], "title": d["label"], "ready": d["ready"], "n": d["n"],
                        "game": d["game"], "thumb": ""})
        res = self.resume_load()
        cont = []
        for path, r in sorted(res.items(), key=lambda kv: -kv[1].get("t", 0)):
            p = self.resolve(path)
            if p and p.is_file():
                e = self.entry(p, res)
                if e:
                    e["kind"] = "resume"
                    cont.append(e)
            if len(cont) >= 12:
                break
        return {"roots": out, "resume": cont}

    def listdir(self, path):
        if str(path).startswith("dvd:") and not str(path).startswith("dvd://"):
            return DVD.listing(str(path)[4:])
        p = self.resolve(path)
        if not p:
            raise ValueError("Ordner nicht erlaubt")
        select = ""
        if p.is_file():
            select, p = str(p), p.parent
        if not p.is_dir():
            if p in (self.share() / "Videos", self.share() / "Musik"):
                p.mkdir(parents=True, exist_ok=True)
            else:
                raise FileNotFoundError(str(p))
        res = self.resume_load()
        dirs: list
        files: list
        dirs, files = [], []
        try:
            names = sorted(os.listdir(p), key=natural_key)
        except OSError as e:
            raise FileNotFoundError(str(e))
        for n in names[:3000]:
            if n.startswith("."):
                continue
            ent = self.entry(p / n, res)
            if not ent:
                continue
            (dirs if ent["kind"] == "dir" else files).append(ent)
        roots = self.allowed_roots()
        parent = "" if p in roots or p.parent in (Path("/run/media"), Path("/media")) else str(p.parent)
        if p.parent == self.share().resolve():
            parent = ""                              # ~/share/Videos und ~/share/Musik: zurueck zur Startseite
        audio = sum(1 for f in files if f["kind"] == "audio")
        self._audio_names([f for f in files if f["kind"] == "audio"][:800])
        # Cover automatisch laden: dieser Ordner (hat er Musik) und die Unterordner ohne Bild
        pending = 0
        if COVERS.auto():
            if audio and MediaLib.own_cover(p) is None:
                pending += COVERS.add(p)
            for d in dirs[:60]:                    # auch Interpreten-Ordner, die schon das Bild eines Albums zeigen
                pending += COVERS.add(Path(d["path"]), deep=True)
            for f in files[:400]:                  # Titel ohne festes Bild (lose Sammlungen, Ordner ohne Cover)
                if f["kind"] == "audio" and MEDIA.art_pending(Path(f["path"])):
                    pending += COVERS.add_track(Path(f["path"]))
        return {"path": str(p), "name": p.name, "parent": parent, "items": dirs + files, "select": select,
                "audio": audio, "coversPending": pending or COVERS.busy_for(p)}

    def _subdirs(self, d):
        try:
            with os.scandir(d) as it:
                ds = [e for e in it if not e.name.startswith(".") and e.is_dir(follow_symlinks=False)]
        except OSError:
            return []
        return [Path(e.path) for e in sorted(ds, key=lambda e: natural_key(e.name))]

    def _preorder(self, root, limit=20000):
        """Alle Ordner unter root in der Reihenfolge der Mediathek (Ordner vor ihren Unterordnern, natuerlich sortiert)."""
        stack, n = [root], 0
        while stack and n < limit:
            d = stack.pop()
            n += 1
            yield d
            stack.extend(reversed(self._subdirs(d)))

    def next_folder(self, path):
        """Naechster Ordner mit Musik nach path – wie "weiter mit dem naechsten Ordner" beim MP3-Player: zuerst die
        Unterordner, dann die Nachbarn, dann weiter oben (Interpret A/Album 2 -> Interpret B/Album 1). Bleibt in
        share/Musik bzw. share/Videos oder auf dem Laufwerk. None am Ende."""
        p = self.resolve(path)
        if not p or not p.is_dir():
            raise ValueError("Ordner nicht erlaubt")
        root = next((r for r in self.allowed_roots() if p == r or r in p.parents), None)
        share = self.share().resolve()
        if root == share and p != share:
            root = share / p.relative_to(share).parts[0]
        found = False
        for d in self._preorder(root):
            if not found:
                found = d == p
                continue
            res = self.resume_load()
            files = []
            try:
                names = sorted(os.listdir(d), key=natural_key)
            except OSError:
                continue
            for n in names:
                if n.startswith(".") or Path(n).suffix.lower() not in AUDIO_EXT:
                    continue
                e = self.entry(d / n, res)
                if e and e["kind"] == "audio":
                    files.append(e)
            if files:
                return {"path": str(d), "name": d.name, "items": files}
        return None

    def thumb(self, path):
        """Vorschaubild als (Bytes, MIME): Cover-Bilder direkt, Videos ueber ffmpegthumbnailer (Cache)."""
        p = self.resolve(path)
        if not p or not p.is_file():
            return None
        ext = p.suffix.lower()
        if ext in (".jpg", ".jpeg", ".png"):
            return p.read_bytes(), MIME.get(ext if ext != ".jpeg" else ".jpg", "image/jpeg")
        if ext not in VIDEO_EXT or not self.thumbnailer:
            return None
        st = p.stat()
        key = hashlib.sha1(f"{p}:{int(st.st_mtime)}:{st.st_size}".encode()).hexdigest()
        out = self.THUMBS / f"{key}.jpg"
        if not out.exists():
            self.THUMBS.mkdir(parents=True, exist_ok=True)
            with self.sem:
                if not out.exists():                      # inzwischen von einer anderen Anfrage erzeugt?
                    tmp = out.with_name(f"{key}.{threading.get_ident()}.tmp.jpg")
                    r = run([self.thumbnailer, "-i", str(p), "-o", str(tmp), "-s", "480", "-t", "12%", "-q", "7"], timeout=25)
                    if r and r.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
                        tmp.replace(out)
                    else:
                        try:
                            tmp.unlink()
                        except OSError:
                            pass
        try:
            return out.read_bytes(), "image/jpeg"
        except OSError:
            return None


MEDIA = MediaLib()


# ---------------------------------------------------------------------------
#  Album-Cover automatisch laden (wie der Scraper in Batocera)
# ---------------------------------------------------------------------------
class MbBusy(Exception):
    """MusicBrainz drosselt oder ist ueberlastet (503) – spaeter nochmal, nicht als "nichts gefunden" merken."""


class CoverFetcher:
    """Fuer Musik-Ordner ohne Bild ein Cover besorgen, im Hintergrund, nacheinander:
    1. eingebettetes Bild der ersten Datei (ffmpeg) – ohne Internet
    2. Interpret + Album aus den Tags (ffprobe), sonst aus den Ordnernamen ("Interpret/Album" oder "Interpret - Album")
    3. MusicBrainz-Suche (Release-Group) -> Cover Art Archive (front-500), sonst iTunes-Suche (Bild 600x600)
    Gespeichert als cover.jpg im Ordner (sehen auch andere Player); ist der Ordner schreibgeschuetzt (USB-Stick,
    Freigabe), im Zwischenspeicher ~/.cache/voidstation/covers. Nichts gefunden: 30 Tage lang nicht erneut fragen.
    MusicBrainz erlaubt eine Anfrage pro Sekunde und verlangt einen erkennbaren User-Agent; antwortet es mit 503
    (ueberlastet bzw. zu viele Anfragen), wird kurz gewartet und nach drei Fehlschlaegen 15 Minuten nur iTunes
    gefragt. iTunes vertraegt etwa 20 Anfragen pro Minute."""
    CACHE = Path.home() / ".cache" / "voidstation" / "covers"
    MISSES = CACHE / "misses.json"
    MB = os.environ.get("VS_MB_URL", "https://musicbrainz.org/ws/2/")
    CAA = os.environ.get("VS_CAA_URL", "https://coverartarchive.org/")
    ITUNES = os.environ.get("VS_ITUNES_URL", "https://itunes.apple.com/search")
    UA = {"User-Agent": "VoidStation/2026 ( https://voidstation.de )", "Accept": "application/json"}

    def __init__(self):
        self.lock = threading.Lock()
        self.queue, self.queued = [], set()
        self.tqueue, self.tqueued = [], set()          # einzelne Titel (Bild je Titel)
        self.refresh = set()                           # Titel, deren Cover neu gesucht werden soll
        self.current = None
        self.stats = {"done": 0, "found": 0, "total": 0}
        self.last_mb = 0.0
        self.mb_lock = threading.Lock()                # MusicBrainz: hoechstens eine Anfrage je Sekunde, nie parallel
        self.mb_fails, self.mb_pause = 0, 0.0          # 503 hintereinander, Pause bis
        self.last_it = 0.0
        self.counted = set()                           # Titel, die in der Anzeige "n von m" mitzaehlen (Alle Cover laden)
        self.offline = False                           # letzte Suche scheiterte am Netz (dann nicht als "nichts da" merken)
        self.last_meta = None                          # Angaben zur zuletzt gefundenen Aufnahme
        self.misses = None
        self.worker = None

    # ---- Einstellungen / Zustand ----
    @staticmethod
    def auto():
        return bool(settings_load().get("covers_auto", True))

    @staticmethod
    def embed():
        """Gefundene Cover und fehlende Tags in die Musikdateien schreiben (Standard aus: aendert eigene Dateien)."""
        return bool(settings_load().get("covers_embed", False))

    def cache_file(self, folder):
        return self.CACHE / (hashlib.sha1(str(folder).encode()).hexdigest()[:16] + ".jpg")

    def _miss_load(self):
        if self.misses is None:
            try:
                self.misses = json.loads(self.MISSES.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.misses = {}
        return self.misses

    def _miss(self, folder):
        d = self._miss_load()
        d[str(folder)] = int(time.time())
        try:
            self.CACHE.mkdir(parents=True, exist_ok=True)
            tmp = self.MISSES.with_suffix(".tmp")
            tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.MISSES)
        except OSError:
            pass

    def _recent_miss(self, folder):
        t = self._miss_load().get(str(folder))
        return bool(t and time.time() - t < 30 * 86400)

    def status(self):
        with self.lock:
            return dict(self.stats, queue=len(self.queue), tracks=len(self.tqueue), embed=self.embed(),
                        running=self.current is not None or bool(self.queue) or bool(self.tqueue),
                        current=Path(self.current).name if self.current else "", auto=self.auto())

    def busy_for(self, folder):
        """Wird fuer diesen Ordner oder einen direkten Unterordner gerade ein Cover gesucht?"""
        with self.lock:
            items = list(self.queue) + list(self.tqueue) + ([self.current] if self.current else [])
        f = str(folder)
        return sum(1 for q in items if q == f or os.path.dirname(q) == f)

    # ---- Warteschlange ----
    def add(self, folder, deep=False, force=False):
        """Ordner vormerken (deep: Ordner ohne eigene Musik -> seine Unterordner eine Ebene tiefer). Rueckgabe: neu."""
        folder = Path(folder)
        if MediaLib.own_cover(folder) is not None or (not force and self._recent_miss(folder)):
            return 0
        if not self._has_audio(folder):
            if not deep:
                return 0
            return sum(self.add(sub, deep=False, force=force) for sub in MEDIA._subdirs(folder)[:40])
        with self.lock:
            if str(folder) in self.queued:
                return 0
            self.queued.add(str(folder))
            self.queue.append(str(folder))
            self.stats["total"] += 1
            self._start()
        return 1

    def add_track(self, path, force=False, count=False):
        """Titel vormerken: eingebettetes Bild pruefen, sonst Cover zu Interpret + Album (oder Titel) im Netz suchen.
        count: zaehlt in der Anzeige mit (Alle Cover laden, gemischter Ordner)."""
        if not force and not self.auto():
            return 0
        path = str(path)
        with self.lock:
            if count and path not in self.counted:
                self.counted.add(path)
                self.stats["total"] += 1
            if path in self.tqueued:
                return 0
            self.tqueued.add(path)
            self.tqueue.append(path)
            self._start()
        return 1

    def _start(self):                                  # unter self.lock aufrufen
        if self.worker is None:                        # der Arbeiter meldet sich unter dem Lock ab (kein Wettlauf)
            self.worker = threading.Thread(target=self._run, daemon=True)
            self.worker.start()

    def scan(self, root):
        """Ganze Sammlung (z. B. share/Musik) durchgehen – auch Ordner, fuer die es zuletzt nichts gab."""
        with self.lock:
            self.stats = {"done": 0, "found": 0, "total": len(self.queue) + len(self.counted)}
        n, t = 0, 0
        for d in MEDIA._preorder(Path(root)):
            n += self.add(d, force=True)
            if self.embed():                           # Cover/Tags auch in Dateien von Ordnern, die schon ein Bild haben
                t += sum(self.add_track(f, force=True, count=True) for f in self._audio_files(d)
                         if f.suffix.lower() in EMBED_EXT)
        log(f"Cover: {n} Ordner ohne Bild vorgemerkt" + (f", {t} Titel fuer Cover/Tags in den Dateien" if t else ""))
        return n

    @staticmethod
    def _audio_files(folder):
        try:
            names = sorted(os.listdir(folder), key=natural_key)
        except OSError:
            return []
        return [Path(folder) / n for n in names if not n.startswith(".") and Path(n).suffix.lower() in AUDIO_EXT]

    def _has_audio(self, folder):
        return bool(self._audio_files(folder))

    def _run(self):
        while True:
            with self.lock:
                if not self.queue and not self.tqueue:
                    self.current = None
                    self.worker = None
                    return
                track = not self.queue                 # Ordner zuerst: deren Cover gilt oft schon fuer die Titel
                self.current = (self.tqueue if track else self.queue).pop(0)
            if track:
                p = Path(self.current)
                f = None
                try:
                    with self.lock:
                        fresh = str(p) in self.refresh
                        self.refresh.discard(str(p))
                    if fresh and p.is_file():
                        MEDIA.reset_art(p)
                    if p.is_file():
                        f, _ = MEDIA.art_file(p, online=True)
                        if self.embed():
                            MEDIA.write_art(p, f)
                except Exception as e:  # noqa: BLE001
                    log("Cover:", p.name, e)
                with self.lock:
                    self.tqueued.discard(str(p))
                    if str(p) in self.counted:
                        self.counted.discard(str(p))
                        self.stats["done"] += 1
                        self.stats["found"] += 1 if f is not None else 0
                continue
            folder = Path(self.current)
            try:
                ok = self.fetch(folder)
            except Exception as e:  # noqa: BLE001
                log("Cover:", folder.name, e)
                ok = False
            with self.lock:
                self.queued.discard(str(folder))
                self.stats["done"] += 1
                self.stats["found"] += 1 if ok else 0

    # ---- Suche ----
    def fetch(self, folder):
        if MediaLib.own_cover(folder) is not None:
            return True
        files = self._audio_files(folder)
        if not files:
            return False
        if MEDIA.mixed(folder):                        # verschiedene Alben: jeder Titel zeigt sein eigenes Bild
            self._miss(folder)
            n = sum(self.add_track(f, force=True, count=True) for f in files[:400] if MEDIA.art_pending(f))
            log(f"Cover: gemischter Ordner, kein gemeinsames Cover – {folder.name} ({n} Titel einzeln)")
            return False
        img = self._embedded(files[0])
        source = "eingebettet"
        self.offline = False
        if not img:
            artist, album = self._names(folder, files[0])
            artist, album = self._main_artist(self._clean(artist)), self._clean(album, tail=False)
            img = self._online(artist, album) if album else None
            source = f"MusicBrainz ({artist} – {album})"
            if not img and album:
                img, _meta = self._itunes(artist, "", album)
                source = f"iTunes ({artist} – {album})"
                self.offline = self.offline and not img
        if not img:
            if self.offline:                           # kein Netz: beim naechsten Oeffnen nochmal versuchen
                return False
            self._miss(folder)
            log("Cover: nichts gefunden fuer", folder.name)
            return False
        where = self._save(folder, img)
        log("Cover:", folder.name, "<-", source, "->", where)
        return True

    @staticmethod
    def _embedded(f):
        ff = shutil.which("ffmpeg")
        if not ff:
            return None
        out = Path(tempfile_name("cover", ".jpg"))
        r = run([ff, "-v", "error", "-y", "-i", str(f), "-map", "0:v:0", "-frames:v", "1", "-an", "-vf", "scale='min(800,iw)':-2",
                 str(out)], timeout=20)
        try:
            data = out.read_bytes() if r and r.returncode == 0 and out.exists() and out.stat().st_size > 1000 else None
        finally:
            try:
                out.unlink()
            except OSError:
                pass
        return data

    @staticmethod
    def _tags(f):
        fp = shutil.which("ffprobe")
        if not fp:
            return {}
        r = run([fp, "-v", "error", "-show_entries", "format_tags", "-of", "json", str(f)], timeout=15)
        try:
            tags = json.loads(r.stdout).get("format", {}).get("tags", {}) if r and r.returncode == 0 else {}
        except ValueError:
            tags = {}
        return {str(k).lower(): str(v).strip() for k, v in tags.items()}

    def _names(self, folder, first):
        t = self._tags(first)
        artist = t.get("album_artist") or t.get("albumartist") or t.get("artist") or ""
        album = t.get("album") or ""
        if not album:                                  # Ordnernamen: "Interpret - Album" oder Interpret/Album
            name = re.sub(r"\s*[\[(]\d{4}[)\]]\s*", " ", folder.name).strip()
            if " - " in name:
                a, b = name.split(" - ", 1)
                artist, album = artist or a.strip(), b.strip()
            else:
                album = name
                parent = folder.parent
                if not artist and parent.resolve() not in MEDIA.allowed_roots() and parent.name not in ("Musik", "Music"):
                    artist = parent.name
        return artist, album

    def _mb_get(self, path):
        """Eine Anfrage an MusicBrainz – nie parallel, hoechstens eine je Sekunde. 503/429 (Drossel bzw. Ueberlast):
        zweimal mit Pause wiederholen; dreimal hintereinander erfolglos -> 15 Minuten keine Anfragen (MbBusy)."""
        with self.mb_lock:
            if time.time() < self.mb_pause:
                raise MbBusy("MusicBrainz pausiert")
            for attempt in range(3):
                wait = 1.1 - (time.time() - self.last_mb)
                if wait > 0:
                    time.sleep(wait)
                self.last_mb = time.time()
                try:
                    req = urllib.request.Request(self.MB + path, headers=self.UA)
                    with urllib.request.urlopen(req, timeout=15) as r:
                        data = json.loads(r.read().decode("utf-8"))
                    self.mb_fails = 0
                    return data
                except urllib.error.HTTPError as e:
                    if e.code not in (429, 503):
                        raise
                    if attempt < 2:
                        time.sleep(2 + 3 * attempt)
            self.mb_fails += 1
            if self.mb_fails >= 3:
                self.mb_pause, self.mb_fails = time.time() + 900, 0
                log("Cover: MusicBrainz ueberlastet – 15 Minuten Pause, bis dahin nur iTunes")
            raise MbBusy("MusicBrainz antwortet 503")

    @staticmethod
    def _q(s):
        return '"' + re.sub(r'([+\-!(){}\[\]^"~*?:\\/]|&&|\|\|)', r"\\\1", s) + '"'

    def _online(self, artist, album):
        q = "releasegroup:" + self._q(album) + (" AND artist:" + self._q(artist) if artist else "")
        try:
            d = self._mb_get("release-group/?fmt=json&limit=5&query=" + urllib.parse.quote(q))
        except Exception as e:  # noqa: BLE001
            if not isinstance(e, MbBusy):
                log("Cover: MusicBrainz nicht erreichbar:", e)
            self.offline = True
            return None
        for g in (d.get("release-groups") or [])[:5]:
            if int(g.get("score") or 0) < (90 if artist else 98):
                continue
            try:
                req = urllib.request.Request(self.CAA + f"release-group/{g['id']}/front-500", headers={"User-Agent": self.UA["User-Agent"]})
                with urllib.request.urlopen(req, timeout=20) as r:
                    data = r.read()
                if len(data) > 1000:
                    return data
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    log("Cover Art Archive:", e)
            except Exception as e:  # noqa: BLE001
                log("Cover Art Archive:", e)
        return None

    # ---- Cover je Titel (lose Sammlungen, gemischte Ordner) ----
    @staticmethod
    def _norm(x):
        return re.sub(r"\s+", " ", JUNK.sub("", x or "")).strip().casefold()

    # ---- Namen fuer die Suche: aus Tags und Dateinamen, auch von YouTube-Downloads ----
    # Zusaetze, die der Suche nur schaden: in Klammern (alles mit diesen Woertern), am Ende ohne Klammern
    BRACKET_JUNK = re.compile(
        r"\s*[\(\[\{][^\)\]\}]*\b(?:official|offizielle?s?|lyrics?|audio|video|hd|hq|4k|visuali[sz]er|clip|videoclip|"
        r"remaster(?:ed|is[eé])?|explicit|live|feat\.?|ft\.?|featuring|mix|edit|version|anniversary|mash ?up|cover|"
        r"performance|full|original|edition|deluxe|expanded|bonus)\b[^\)\]\}]*[\)\]\}]", re.I)
    TAIL_JUNK = re.compile(
        r"\s+(?:(?:official\s+)?(?:music\s+|lyrics?\s+)?(?:video|audio)\b|lyrics?\b|clip officiel\b|live\s+(?:at|in|from|\d)|"
        r"live performance\b|remaster(?:ed|is[eé])?\b|(?:original\s+|extended\s+|radio\s+|club\s+)+(?:mix|edit|version)\b|"
        r"extended\b|cover by\b|feat\.?\s|ft\.?\s|featuring\b|full original\b|\d+k\)?$|"
        r"[-–—]\s.*\b(?:mash ?up|remix|mix|edit|version|live)\b).*$", re.I)
    CONTRACTIONS = re.compile(r"\b([A-Za-z]+) (s|t|m|d|ll|re|ve)\b")       # "Larry s", "Don t", "I m" (Apostroph fiel weg)

    @classmethod
    def _clean(cls, s, tail=True):
        """Titel bzw. Interpret fuer die Suche: Unterstriche, Emojis, Zusaetze wie "(Lyrics)", "Official Video",
        "Live at …", "Remastered 1996", "-(115k)" weg; verlorene Apostrophe zurueck ("Larry s" -> "Larry's")."""
        s = unicodedata.normalize("NFKC", s or "").replace("_", " ")
        s = re.sub(r"[\U0001F000-\U0001FFFF☀-➿️]", "", s)
        s = re.sub(r"-?\(\d+k\)$", "", s.strip())                            # "-(115k)" vom Downloader
        for _ in range(3):
            s = cls.BRACKET_JUNK.sub("", s)
        s = JUNK.sub("", s)
        if tail:
            s = cls.TAIL_JUNK.sub("", s)
        s = cls.CONTRACTIONS.sub(lambda m: f"{m.group(1)}'{m.group(2)}"
                                 if m.group(2) != "s" or m.group(1).lower() not in ("a", "i") else m.group(0), s)
        s = re.sub(r"\s+", " ", s).strip(" -–—|·:,")
        return s

    @staticmethod
    def _main_artist(a):
        """Erster Interpret: "Eurythmics, Annie Lennox …" -> Eurythmics, "Bananarama / Shocking Blue" -> Bananarama,
        "X feat. Y" -> X; "Ray Parker, Jr." bleibt."""
        a = unicodedata.normalize("NFKC", a or "").strip()
        a = re.split(r"\s+(?:feat\.?|ft\.?|featuring|x|vs\.?)\s+|\s*/\s*|\s+&\s+|,(?!\s*(?:jr|sr)\b)", a,
                     maxsplit=1, flags=re.I)[0]
        return a.strip()

    @staticmethod
    def _fold(x):
        return re.sub(r"[^a-z0-9]+", " ", tv_fold(x or "")).strip()

    SEP = re.compile(r"\s+[-–—]\s+|(?<=\w)[-–—]\s+")       # "A - B", "A – B", "Prince- Purple Rain"

    def _track_cands(self, p, tags):
        """Moegliche (Interpret, Album, Titel) fuer die Suche, beste zuerst. Tags gehen vor; steckt im Titel-Tag
        "Interpret - Titel" (YouTube: der Kanal steht dann oft als Interpret drin, z. B. "7clouds"), zaehlt das.
        Ist unklar, was Interpret und was Titel ist ("Royals - Lorde"), kommen beide Reihenfolgen. Ohne Tags: der
        Dateiname ("01 - Interpret - Titel", "Interpret_-_Titel")."""
        tag_artist = tags.get("album_artist") or tags.get("albumartist") or tags.get("artist") or ""
        album = self._clean(tags.get("album") or "", tail=False)
        raw_title = (tags.get("title") or "").strip().lstrip("-–— ").strip()
        out = []

        def add(a, t, alb=album):
            a, t = self._main_artist(self._clean(a)), self._clean(t)
            if t and (a, alb, t) not in out:
                out.append((a, alb, t))

        def split(text):
            parts = self.SEP.split(self._clean(text, tail=False), maxsplit=1)
            return [x.strip() for x in parts] if len(parts) == 2 and all(x.strip() for x in parts) else None

        parts = split(raw_title) if raw_title else None
        if parts:
            fa = self._fold(self._main_artist(tag_artist))
            l, r = parts
            if fa and fa == self._fold(r) or (fa and self._fold(r).startswith(fa) and not self._fold(l).startswith(fa)):
                add(r, l)                                    # "Royals - Lorde" mit Interpret Lorde
            elif fa and (fa == self._fold(l) or self._fold(l).startswith(fa)):
                add(l, r)
            else:                                            # Interpret-Tag ist der Kanal: Titel-Tag entscheidet
                add(l, r, "")
                add(r, l, "")
        elif raw_title and tag_artist:
            add(tag_artist, raw_title)
        if not out:                                          # Dateiname
            stem = re.sub(r"^\d{1,3}[\s._-]+", "", p.stem.replace("_", " ")).strip()
            parts = split(stem)
            if parts:
                add(parts[0], parts[1], album)
                add(parts[1], parts[0], album)
            elif tag_artist:
                add(tag_artist, raw_title or stem)
            else:
                add("", raw_title or stem)
        return out

    def _track_names(self, p, tags):
        """Interpret, Album, Titel – die wahrscheinlichste Lesart (_track_cands)."""
        c = self._track_cands(p, tags)
        return c[0] if c else ("", "", "")

    def _guess_text(self, p, tags):
        """Ohne Interpret: der bereinigte Dateiname bzw. Titel als Ganzes, z. B. "Beck loser"."""
        _a, _al, t = self._track_names(p, tags)
        return t

    def track_cache(self, p, tags):
        """Datei im Zwischenspeicher fuer das Cover dieses Titels – gemeinsam fuer alle Titel eines Albums."""
        artist, album, title = self._track_names(p, tags)
        if not artist:                                 # nur ein Dateiname wie "Beck loser" oder "Funkytown": raten
            text = self._guess_text(p, tags)
            if not text:
                return None
            return self._guess_cache(p, tags)
        if not (album or title):
            return None
        key = f"album|{self._norm(artist)}|{self._norm(album)}" if album else f"title|{self._norm(artist)}|{self._norm(title)}"
        return self.CACHE / ("t-" + hashlib.sha1(key.encode()).hexdigest()[:16] + ".jpg")

    def cache_kind(self, p, tags, cache):
        if cache.name == self._guess_cache(p, tags).name:
            return "guess"
        _artist, album, _title = self._track_names(p, tags)
        return "album" if album else "title"

    def _guess_cache(self, p, tags):
        return self.CACHE / ("t-" + hashlib.sha1(f"guess|{self._norm(self._guess_text(p, tags))}".encode()).hexdigest()[:16] + ".jpg")

    def track_caches(self, p, tags):
        """Alle Zwischenspeicher-Dateien, die fuer diesen Titel in Frage kommen (Album, Titel, geraten)."""
        out = []                                       # geraten zuerst: dessen Angaben stammen sicher von uns
        if len(self._guess_text(p, tags).split()) >= 2:
            out.append(self._guess_cache(p, tags))
        c = self.track_cache(p, tags)
        if c is not None and c not in out:
            out.append(c)
        return out

    def forget(self, cache):
        for f in (cache, cache.with_suffix(".json")):
            try:
                f.unlink()
            except OSError:
                pass
        d = self._miss_load()
        if d.pop(cache.name, None) is not None:
            try:
                self.MISSES.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass

    def refresh_track(self, path):
        """Cover dieses Titels neu suchen (Menue im Player)."""
        with self.lock:
            self.refresh.add(str(path))
        self.add_track(path, force=True)

    def track_missed(self, cache):
        return self._recent_miss(cache.name)

    def fetch_track(self, p, tags, cache):
        """Cover fuer einen Titel suchen: je Lesart (_track_cands) MusicBrainz (Album, dann Aufnahme), ohne Interpret
        Raten aus dem Dateinamen; zuletzt iTunes (findet auch "Funkytown" allein). Rueckgabe True/False, None = kein
        Netz bzw. MusicBrainz ueberlastet (spaeter nochmal, nicht als "nichts gefunden" merken)."""
        if cache.is_file():                            # inzwischen von einem anderen Titel desselben Albums geholt
            return True
        cands = self._track_cands(p, tags)
        img, via, meta = None, "", None
        mb_off = False
        for artist, album, title in cands[:3]:
            self.offline = False
            if not artist:
                if len(title.split()) >= 2:
                    img, via = self._online_guess(title), f"MusicBrainz ({title})"
                    meta = self.last_meta if img else None
            else:
                if album:
                    img, via = self._online(artist, album), f"MusicBrainz ({artist} – {album})"
                if not img and title and not self.offline:
                    img, via = self._online_recording(artist, title), f"MusicBrainz ({artist} – {title})"
                    meta = self.last_meta if img else None
            mb_off = mb_off or self.offline
            if img:
                break
        if not img:
            self.offline = False
            for artist, album, title in cands[:2]:
                img, meta = self._itunes(artist, title, album)
                if img:
                    via = f"iTunes ({artist + ' – ' if artist else ''}{title or album})"
                    break
                if self.offline:
                    break
        if not img:
            if mb_off or self.offline:                 # kein Netz/ueberlastet: None = spaeter nochmal
                return None
            self._miss(cache.name)
            log("Cover: nichts gefunden fuer", p.name)
            return False
        try:
            self.CACHE.mkdir(parents=True, exist_ok=True)
            tmp = cache.with_suffix(".part")
            tmp.write_bytes(img)
            tmp.replace(cache)
            if meta:                                   # Angaben zur gefundenen Aufnahme (fuer fehlende Tags)
                cache.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        except OSError as e:
            log("Cover: Zwischenspeicher nicht beschreibbar:", e)
            return False
        log("Cover:", p.name, "<-", via)
        return True

    def _itunes(self, artist, title, album=""):
        """iTunes-Suche (Lied, ohne Titel: Album) -> (Bild 600x600, Angaben) oder (None, None). Passt nur, was im
        Titel (bzw. Album) fast genau und beim Interpreten aehnlich ist; ohne Interpret zaehlt allein der Titel, und
        es gilt der erste Treffer (iTunes sortiert nach Bekanntheit: "Funkytown" -> Lipps Inc.)."""
        import difflib
        entity, name = ("song", title) if title else ("album", album)
        if not name:
            return None, None
        term = urllib.parse.urlencode({"term": f"{artist} {name}".strip(), "entity": entity, "limit": "10",
                                       "media": "music"})
        with self.mb_lock:                             # gleiche Warteschlange wie MusicBrainz, ~20 Anfragen/Minute
            wait = 3.1 - (time.time() - self.last_it)
            if wait > 0:
                time.sleep(wait)
            self.last_it = time.time()
            try:
                req = urllib.request.Request(self.ITUNES + "?" + term, headers={"User-Agent": self.UA["User-Agent"]})
                with urllib.request.urlopen(req, timeout=15) as r:
                    d = json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                log("Cover: iTunes:", e)
                self.offline = self.offline or e.code in (403, 429, 503)
                return None, None
            except Exception as e:  # noqa: BLE001
                log("Cover: iTunes nicht erreichbar:", e)
                self.offline = True
                return None, None
        sim = lambda x, y: difflib.SequenceMatcher(None, self._fold(x), self._fold(y)).ratio()    # noqa: E731
        best: Any = None                               # Treffer (dict) aus der iTunes-Suche
        best_score = 0.0
        for r in d.get("results") or []:
            got = r.get("trackName") if title else r.get("collectionName")
            sn = max(sim(name, got), sim(name, self._clean(got or "")))
            fa, fb = self._fold(name), self._fold(got)
            if artist and fa and fb and min(len(fa.split()), len(fb.split())) >= 2 and (
                    f" {fa} " in f" {fb} " or f" {fb} " in f" {fa} "):
                sn = max(sn, 0.85)                     # "Stay With Me" in "真夜中のドア〜stay with me"
            if not artist:
                if sn >= 0.9:
                    best = r
                    break
                continue
            sa = max(sim(artist, r.get("artistName")), 1.0 if self._artist_fits(r.get("artistName") or "", artist) else 0.0)
            score = sn * 0.65 + sa * 0.35
            if sn >= 0.8 and sa >= 0.6 and score > best_score:
                best, best_score = r, score
        url = (best or {}).get("artworkUrl100") or ""
        if not url:
            return None, None
        url = re.sub(r"/\d+x\d+(bb)?\.(jpg|png)$", r"/600x600bb.jpg", url)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": self.UA["User-Agent"]}),
                                        timeout=20) as r:
                data = r.read()
        except Exception as e:  # noqa: BLE001
            log("Cover: iTunes-Bild:", e)
            return None, None
        if len(data) < 1000:
            return None, None
        meta = {"title": best.get("trackName") or "", "artist": best.get("artistName") or "",
                "album": best.get("collectionName") or "", "date": (best.get("releaseDate") or "")[:4],
                "track": str(best.get("trackNumber") or "")} if title else None
        return data, meta

    def _caa(self, gid):
        try:
            req = urllib.request.Request(self.CAA + f"release-group/{gid}/front-500", headers={"User-Agent": self.UA["User-Agent"]})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = r.read()
            return data if len(data) > 1000 else None
        except urllib.error.HTTPError as e:
            if e.code != 404:
                log("Cover Art Archive:", e)
        except Exception as e:  # noqa: BLE001
            log("Cover Art Archive:", e)
        return None

    @staticmethod
    def _similar(a, b):
        import difflib
        f = lambda x: re.sub(r"[^a-z0-9]+", " ", tv_fold(x or "")).strip()    # noqa: E731
        return difflib.SequenceMatcher(None, f(a), f(b)).ratio()

    @classmethod
    def _artist_fits(cls, credit, guess):
        """"Jade" passt zu "Jade LeMac", "beck" zu "Beck" – Woerter des geratenen Namens stecken im echten."""
        if cls._similar(credit, guess) >= 0.85:
            return True
        w = lambda x: set(re.sub(r"[^a-z0-9]+", " ", tv_fold(x or "")).split())    # noqa: E731
        g = w(guess)
        return bool(g) and g <= w(credit)

    def _online_guess(self, text):
        """Nur "Beck loser" oder "Midnight Cowboy Jade": alle Aufteilungen in Interpret + Titel durchprobieren (beide
        Richtungen, hoechstens 8 Anfragen) und nur nehmen, was bei MusicBrainz in Interpret UND Titel passt."""
        words = text.split()
        if not 2 <= len(words) <= 12:
            return None
        cands = []
        for i in range(1, len(words)):
            a, t = " ".join(words[:i]), " ".join(words[i:])
            cands += [(a, t), (t, a)]
        cands.sort(key=lambda c: abs(len(c[0].split()) - 1))   # meist ist der Interpret ein Wort ("Beck", "Jade")
        for a, t in cands[:8]:
            img = self._online_recording(a, t, strict=True)
            if img or self.offline:
                return img
        return None

    def _online_recording(self, artist, title, strict=False):
        """Titel ohne Album-Tag: Aufnahme suchen, deren Album (offiziell, Studioalbum vor Single, keine
        Zusammenstellung) nehmen. strict: Interpret und Titel muessen fast genau passen (geratene Aufteilung)."""
        q = "recording:" + self._q(title) + " AND artist:" + self._q(artist)
        try:
            d = self._mb_get("recording/?fmt=json&limit=8&query=" + urllib.parse.quote(q))
        except Exception as e:  # noqa: BLE001
            if not isinstance(e, MbBusy):
                log("Cover: MusicBrainz nicht erreichbar:", e)
            self.offline = True
            return None

        def rank(r, score):
            """Original vor Sampler: offiziell, keine Zusammenstellung/Live/Soundtrack (secondary-types, "Various
            Artists"), Studioalbum vor Single vor EP, dann der frueheste Termin – ueber alle Aufnahmen hinweg."""
            rg = r.get("release-group") or {}
            va = any((a.get("name") or "").casefold() in ("various artists", "verschiedene interpreten")
                     for a in r.get("artist-credit") or [])
            return (0 if r.get("status") == "Official" else 1, 1 if (rg.get("secondary-types") or va) else 0,
                    {"Album": 0, "Single": 1, "EP": 2}.get(rg.get("primary-type") or "", 3), r.get("date") or "9999", -score)
        best: dict = {}
        for rec in (d.get("recordings") or [])[:8]:
            score = int(rec.get("score") or 0)
            if score < 90:
                continue
            credit = "".join((a.get("name") or "") + (a.get("joinphrase") or "") for a in rec.get("artist-credit") or []).strip()
            if strict and (self._similar(rec.get("title"), title) < 0.85 or not self._artist_fits(credit, artist)):
                continue
            for r in rec.get("releases") or []:
                gid = (r.get("release-group") or {}).get("id")
                if not gid:
                    continue
                k = rank(r, score)
                if gid in best and best[gid][0] <= k:
                    continue
                tracks = [t for m in r.get("media") or [] for t in m.get("track") or []]
                best[gid] = (k, {"title": rec.get("title") or "", "artist": credit, "album": r.get("title") or "",
                                 "date": (r.get("date") or "")[:4], "track": str(tracks[0].get("number") or "") if tracks else ""})
        self.last_meta = None
        for gid, (_k, meta) in sorted(best.items(), key=lambda x: x[1][0])[:4]:
            img = self._caa(gid)
            if img:
                self.last_meta = meta
                return img
        return None

    def _save(self, folder, data):
        target = folder / "cover.jpg"
        try:
            tmp = folder / ".cover.jpg.part"
            tmp.write_bytes(data)
            tmp.replace(target)
            return "cover.jpg"
        except OSError:
            self.CACHE.mkdir(parents=True, exist_ok=True)
            c = self.cache_file(folder)
            c.write_bytes(data)
            return "Zwischenspeicher"


def tempfile_name(prefix, suffix):
    import tempfile
    fd, name = tempfile.mkstemp(prefix=prefix, suffix=suffix)
    os.close(fd)
    return name


COVERS = CoverFetcher()


# ---------------------------------------------------------------------------
#  Musik suchen und herunterladen (Videos & Musik -> "Musik suchen"), aehnlich wie ytmdl
# ---------------------------------------------------------------------------
DL_SOURCES = ("archive", "youtube", "soundcloud")          # Reihenfolge der Einstellungsseite
DL_DEFAULT = {"archive": False, "youtube": False, "soundcloud": False}   # keine Vorauswahl – der Nutzer kreuzt selbst an
JUNK = re.compile(r"\s*[\(\[](?:official|offizielles|music|lyric|lyrics|audio|video|hd|hq|4k|visuali[sz]er|clip|"
                  r"videoclip|remaster(?:ed)?(?: \d{4})?|explicit|live)[^\)\]]*[\)\]]", re.I)


def safe_name(s, fallback="Unbekannt"):
    """Datei-/Ordnername: keine Pfadtrenner und Steuerzeichen, hoechstens 120 Zeichen."""
    s = re.sub(r'[\x00-\x1f/\\:*?"<>|]+', " ", str(s or "")).strip().strip(".")
    s = re.sub(r"\s{2,}", " ", s)
    return s[:120] or fallback


class MusicDL:
    """Suche in mehreren Quellen und Download nach share/Musik:
      archive     Internet Archive (Netlabels, Live-Mitschnitte, Creative Commons/gemeinfrei) – ganze Alben, direkt
      youtube     YouTube ueber yt-dlp (+ Node.js fuer die Signatur-Pruefung von YouTube)
      soundcloud  SoundCloud ueber yt-dlp
    Einzelne Titel (YouTube/SoundCloud) werden zu MP3 (bestes VBR) und bekommen Tags + Cover wie bei ytmdl:
    Interpret/Titel aus den Angaben der Plattform bzw. dem Titel ("Interpret - Titel (Official Video)"), Album,
    Genre, Jahr, Titelnummer und Cover (600 px) aus der iTunes-Suche. Ablage: Musik/<Interpret>/<Album>/NN - Titel.mp3,
    ohne Album: Musik/<Interpret>/Singles/. Welche Quellen genutzt werden, waehlt man vorher selbst (Einstellungsseite)."""
    IA = os.environ.get("VS_IA_URL", "https://archive.org/")
    ITUNES = os.environ.get("VS_ITUNES_URL", "https://itunes.apple.com/search")
    UA = {"User-Agent": "VoidStation/2026 ( https://voidstation.de )"}

    def __init__(self):
        self.lock = threading.Lock()
        self.results = {}                  # key -> Treffer der letzten Suchen (Download nur ueber den Schluessel)
        self.jobs = []                     # Downloads: {key, title, artist, src, state, pct, msg, path}
        self.worker = None

    # ---- Einstellungen ----
    @staticmethod
    def settings():
        d = settings_load().get("dl") or {}
        src = dict(DL_DEFAULT)
        src.update({k: bool(v) for k, v in (d.get("sources") or {}).items() if k in DL_SOURCES})
        return {"sources": src, "configured": bool(d.get("configured"))}

    @staticmethod
    def ytdlp():
        # die eigene, aktuelle Kopie von YouTube Light (falls dort aktualisiert) vor dem Paket aus Void
        local = YtLight.LOCAL
        exe = os.environ.get("VS_YTDLP") or (str(local) if local.is_file() and os.access(local, os.X_OK) else "") \
            or shutil.which("yt-dlp")
        return exe

    def tools(self):
        exe = self.ytdlp()
        ver = ""
        if exe:
            r = run([exe, "--version"], timeout=20)
            ver = r.stdout.strip() if r and r.returncode == 0 else ""
        return {"ytdlp": ver, "node": bool(shutil.which("node")), "ffmpeg": bool(shutil.which("ffmpeg"))}

    def save_settings(self, sources):
        s = settings_load()
        src = {k: bool((sources or {}).get(k, DL_DEFAULT[k])) for k in DL_SOURCES}
        s["dl"] = {"sources": src, "configured": True}
        settings_save(s)
        log("Musik suchen: Quellen", ", ".join(k for k, v in src.items() if v) or "keine")
        return self.payload()

    def payload(self):
        return dict(self.settings(), tools=self.tools(), sources_list=list(DL_SOURCES))

    # ---- Suche ----
    def _get_json(self, url, timeout=15):
        req = urllib.request.Request(url, headers=self.UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def _remember(self, items):
        with self.lock:
            for it in items:
                self.results[it["key"]] = it
            if len(self.results) > 600:
                for k in list(self.results)[:len(self.results) - 600]:
                    del self.results[k]
        return [{k: v for k, v in it.items() if k not in ("url",)} for it in items]

    def search(self, q):
        q = " ".join(str(q or "").split())[:120]
        if not q:
            return {"items": [], "errors": {}}
        src = self.settings()["sources"]
        out, errors, threads = {}, {}, []

        def one(name, fn):
            try:
                out[name] = fn(q)
            except Exception as e:  # noqa: BLE001
                log("Musik suchen:", name, e)
                errors[name] = str(e)[:200]
        for name, fn in (("archive", self._s_archive), ("youtube", self._s_youtube), ("soundcloud", self._s_soundcloud)):
            if src.get(name):
                t = threading.Thread(target=one, args=(name, fn), daemon=True)
                t.start()
                threads.append(t)
        for t in threads:
            t.join(timeout=40)
        items = []
        for name in DL_SOURCES:                          # Quellen nacheinander, je Quelle in Trefferreihenfolge
            items += out.get(name, [])
        return {"items": self._remember(items), "errors": errors}

    def _s_archive(self, q):
        term = re.sub(r'[()":\\\[\]{}^~*?]', " ", q)
        query = (f'({term}) AND mediatype:(audio) AND (licenseurl:(*creativecommons*) OR licenseurl:(*publicdomain*) '
                 f'OR collection:(etree) OR collection:(netlabels))')
        params = urllib.parse.urlencode([("q", query), ("fl[]", "identifier"), ("fl[]", "title"), ("fl[]", "creator"),
                                         ("fl[]", "year"), ("fl[]", "licenseurl"), ("rows", "15"), ("output", "json"),
                                         ("sort[]", "downloads desc")])
        d = self._get_json(self.IA + "advancedsearch.php?" + params)
        items = []
        for doc in (d.get("response") or {}).get("docs") or []:
            ident = str(doc.get("identifier") or "")
            if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", ident):
                continue
            creator = doc.get("creator")
            creator = creator[0] if isinstance(creator, list) and creator else creator or ""
            lic = str(doc.get("licenseurl") or "")
            items.append({"key": "ia:" + ident, "src": "archive", "kind": "album", "id": ident,
                          "title": str(doc.get("title") or ident)[:150], "artist": str(creator)[:100],
                          "year": str(doc.get("year") or "")[:4], "duration": 0,
                          "license": "CC" if "creativecommons" in lic else "PD" if "publicdomain" in lic else "",
                          "thumb": self.IA + "services/img/" + ident})
        return items

    def _ytdlp_search(self, prefix, src, q):
        exe = self.ytdlp()
        if not exe:
            raise RuntimeError("yt-dlp fehlt")
        r = run([exe, "--flat-playlist", "-J", "--no-warnings", "--ignore-config", f"{prefix}12:{q}"], timeout=40)
        if not r or r.returncode != 0:
            raise RuntimeError((r.stderr.strip().splitlines() or ["yt-dlp-Fehler"])[-1] if r else "yt-dlp antwortet nicht")
        d = json.loads(r.stdout or "{}")
        items = []
        for e in d.get("entries") or []:
            url = str(e.get("url") or e.get("webpage_url") or "")
            vid = str(e.get("id") or "")
            if src == "youtube":
                if not re.fullmatch(r"[A-Za-z0-9_-]{6,20}", vid):
                    continue
                url = "https://www.youtube.com/watch?v=" + vid
            elif not url.startswith("https://soundcloud.com/") and not url.startswith("https://api.soundcloud.com/"):
                continue
            thumbs = e.get("thumbnails") or []
            thumb = e.get("thumbnail") or (thumbs[-1].get("url") if thumbs and isinstance(thumbs[-1], dict) else "")
            items.append({"key": f"{src}:{vid or hashlib.sha1(url.encode()).hexdigest()[:12]}", "src": src, "kind": "track",
                          "id": vid, "url": url, "title": str(e.get("title") or "")[:150],
                          "artist": str(e.get("artist") or e.get("uploader") or e.get("channel") or "")[:100],
                          "duration": int(e.get("duration") or 0), "year": "", "license": "", "thumb": str(thumb or "")})
        return items

    def _s_youtube(self, q):
        return self._ytdlp_search("ytsearch", "youtube", q)

    def _s_soundcloud(self, q):
        return self._ytdlp_search("scsearch", "soundcloud", q)

    # ---- Downloads ----
    def status(self):
        with self.lock:
            return {"jobs": [dict(j) for j in self.jobs[-40:]],
                    "active": any(j["state"] in ("queued", "running") for j in self.jobs)}

    def get(self, key):
        with self.lock:
            it = self.results.get(str(key))
            if not it:
                raise ValueError("Treffer unbekannt – bitte neu suchen")
            if any(j["key"] == it["key"] and j["state"] in ("queued", "running") for j in self.jobs):
                return self.status()
            self.jobs.append({"key": it["key"], "title": it["title"], "artist": it["artist"], "src": it["src"],
                              "state": "queued", "pct": 0, "msg": "", "path": ""})
            if self.worker is None:                    # der Arbeiter meldet sich unter dem Lock ab (kein Wettlauf)
                self.worker = threading.Thread(target=self._run, daemon=True)
                self.worker.start()
        return self.status()

    def _job(self, key, **kw):
        with self.lock:
            for j in reversed(self.jobs):
                if j["key"] == key:
                    j.update(kw)
                    return

    def _run(self):
        while True:
            with self.lock:
                job = next((j for j in self.jobs if j["state"] == "queued"), None)
                if not job:
                    self.worker = None
                    return
                job["state"] = "running"
                it: Any = self.results.get(job["key"])
            try:
                path = self._album(it) if it["kind"] == "album" else self._track(it)
                rel = str(Path(path).relative_to(MEDIA.share())) if str(path).startswith(str(MEDIA.share())) else str(path)
                self._job(it["key"], state="done", pct=100, path=str(path), msg=rel)
                log("Musik gespeichert:", rel)
            except Exception as e:  # noqa: BLE001
                log("Musik laden fehlgeschlagen:", it.get("title"), e)
                self._job(it["key"], state="error", msg=str(e)[:200])

    def _download(self, url, dest, key=None, part=(0, 1)):
        req = urllib.request.Request(url, headers=self.UA)
        tmp = dest.with_name("." + dest.name + ".part")
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as fh:
            total = int(r.headers.get("Content-Length") or 0)
            got = 0
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                fh.write(chunk)
                got += len(chunk)
                if key and total:
                    i, n = part
                    self._job(key, pct=int((i + got / total) / n * 100))
        tmp.replace(dest)

    def _album(self, it):
        """Internet Archive: alle MP3-Titel eines Eintrags nach Musik/<Interpret>/<Titel>/ (Tags bringt das Archiv mit)."""
        meta = self._get_json(self.IA + "metadata/" + it["id"], timeout=30)
        files = meta.get("files") or []
        def pick(fmt):
            return [f for f in files if f.get("format") == fmt and f.get("name") and not f.get("name", "").startswith(("_", "."))]
        tracks = pick("VBR MP3") or pick("MP3") or pick("128Kbps MP3") or pick("Ogg Vorbis") or pick("Flac")
        if not tracks:
            raise RuntimeError("keine Musikdateien in diesem Eintrag")
        tracks.sort(key=lambda f: (int(must_match(re.match(r"\d+", str(f.get("track") or "999"))).group(0)) if re.match(r"\d+", str(f.get("track") or "")) else 999,
                                   natural_key(f["name"])))
        md = meta.get("metadata") or {}
        artist = md.get("creator") or it["artist"]
        artist = artist[0] if isinstance(artist, list) and artist else artist
        folder = MEDIA.share() / "Musik" / safe_name(artist) / safe_name(md.get("title") or it["title"])
        folder.mkdir(parents=True, exist_ok=True)
        for i, f in enumerate(tracks[:200]):
            name = safe_name(Path(f["name"]).name)
            dest = folder / name
            if dest.exists():
                continue
            self._job(it["key"], msg=f"{i + 1}/{len(tracks)}")
            self._download(self.IA + "download/" + urllib.parse.quote(it["id"]) + "/" + urllib.parse.quote(f["name"]), dest,
                           it["key"], (i, len(tracks)))
        if MediaLib.own_cover(folder) is None:
            try:
                self._download(self.IA + "services/img/" + it["id"], folder / "cover.jpg")
            except Exception:  # noqa: BLE001
                pass
        return folder

    @staticmethod
    def _split(title, artist):
        """"Interpret - Titel (Official Video)" -> (Interpret, Titel); sonst Kanal als Interpret."""
        t = JUNK.sub("", title or "").strip()
        t = re.sub(r"\s*\|.*$", "", t).strip()
        m = re.match(r"^(.+?)\s+[-–—]\s+(.+)$", t)
        if m:
            return m.group(1).strip(), m.group(2).strip().strip('"“”')
        artist = re.sub(r"\s*-\s*Topic$|VEVO$", "", artist or "").strip()
        return artist, t

    def _itunes(self, artist, title):
        term = urllib.parse.urlencode({"term": f"{artist} {title}".strip(), "entity": "song", "limit": "8", "media": "music"})
        try:
            d = self._get_json(self.ITUNES + "?" + term)
        except Exception as e:  # noqa: BLE001
            log("iTunes-Suche:", e)
            return None
        def norm(x):
            return re.sub(r"[^a-z0-9]+", " ", tv_fold(JUNK.sub("", x or ""))).strip()
        nt, na = norm(title), norm(artist)
        best, best_score = None, 0.0
        import difflib
        for r in d.get("results") or []:
            st = difflib.SequenceMatcher(None, nt, norm(r.get("trackName"))).ratio()
            sa = difflib.SequenceMatcher(None, na, norm(r.get("artistName"))).ratio() if na else 0.6
            score = st * 0.65 + sa * 0.35
            if score > best_score:
                best, best_score = r, score
        return best if best_score >= 0.72 else None

    def _track(self, it):
        exe = self.ytdlp()
        if not exe:
            raise RuntimeError("yt-dlp fehlt")
        ff = shutil.which("ffmpeg")
        if not ff:
            raise RuntimeError("ffmpeg fehlt")
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="vs-dl-"))
        try:
            args = [exe, "--ignore-config", "--no-playlist", "--newline", "--no-warnings", "-f", "bestaudio/best",
                    "-x", "--audio-format", "mp3", "--audio-quality", "0", "--write-info-json",
                    "-o", str(tmp / "a.%(ext)s"), it["url"]]
            if it["src"] == "youtube" and shutil.which("node"):
                args[1:1] = ["--js-runtimes", "node"]
            p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
                                 stdin=subprocess.DEVNULL)
            last = ""
            assert p.stdout is not None
            for line in p.stdout:
                m = re.search(r"\[download\]\s+([\d.]+)%", line)
                if m:
                    self._job(it["key"], pct=int(float(m.group(1)) * 0.9))
                elif line.strip():
                    last = line.strip()
            if p.wait() != 0:
                raise RuntimeError(last or "Download fehlgeschlagen")
            audio = tmp / "a.mp3"
            if not audio.exists():
                raise RuntimeError("keine Audiodatei erhalten")
            try:
                info = json.loads((tmp / "a.info.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                info = {}
            self._job(it["key"], msg="Tags & Cover", pct=92)
            artist, title = (info.get("artist") or "").split(",")[0].strip(), info.get("track") or ""
            if not (artist and title):
                artist, title = self._split(info.get("title") or it["title"], info.get("uploader") or it["artist"])
            album, genre, year, num = info.get("album") or "", info.get("genre") or "", str(info.get("release_year") or ""), ""
            cover = None
            hit = self._itunes(artist, title)
            if hit:
                artist, title = hit.get("artistName") or artist, hit.get("trackName") or title
                album = hit.get("collectionName") or album
                genre = hit.get("primaryGenreName") or genre
                year = (hit.get("releaseDate") or "")[:4] or year
                num = str(hit.get("trackNumber") or "")
                art = hit.get("artworkUrl100") or ""
                if art:
                    try:
                        self._download(art.replace("100x100bb", "600x600bb"), tmp / "cover.jpg")
                        cover = tmp / "cover.jpg"
                    except Exception:  # noqa: BLE001
                        cover = None
            if cover is None and it.get("thumb", "").startswith("https://"):
                try:                                      # Vorschaubild der Plattform, quadratisch zugeschnitten
                    self._download(it["thumb"], tmp / "thumb.img")
                    r = run([ff, "-v", "error", "-y", "-i", str(tmp / "thumb.img"), "-vf",
                             "crop='min(iw,ih)':'min(iw,ih)',scale=600:600", str(tmp / "cover.jpg")], timeout=30)
                    cover = tmp / "cover.jpg" if r and r.returncode == 0 else None
                except Exception:  # noqa: BLE001
                    cover = None
            artist = artist or "Unbekannt"
            folder = MEDIA.share() / "Musik" / safe_name(artist) / (safe_name(album) if album else "Singles")
            folder.mkdir(parents=True, exist_ok=True)
            name = (f"{int(num):02d} - " if num.isdigit() and album else "") + safe_name(title, "Titel") + ".mp3"
            dest = folder / name
            meta = ["-metadata", f"title={title}", "-metadata", f"artist={artist}", "-metadata", f"album_artist={artist}"]
            for k, v in (("album", album), ("genre", genre), ("date", year), ("track", num)):
                if v:
                    meta += ["-metadata", f"{k}={v}"]
            out = tmp / "tagged.mp3"
            cmd = [ff, "-v", "error", "-y", "-i", str(audio)]
            if cover:
                cmd += ["-i", str(cover), "-map", "0:a", "-map", "1:v", "-c", "copy", "-id3v2_version", "3",
                        "-metadata:s:v", "title=Album cover", "-metadata:s:v", "comment=Cover (front)", "-disposition:v", "attached_pic"]
            else:
                cmd += ["-map", "0:a", "-c", "copy", "-id3v2_version", "3"]
            r = run(cmd + ["-map_metadata", "-1"] + meta + [str(out)], timeout=120)
            if not r or r.returncode != 0:
                raise RuntimeError("Tags konnten nicht geschrieben werden")
            shutil.move(str(out), str(dest))
            if cover and MediaLib.own_cover(folder) is None and album:
                shutil.copyfile(cover, folder / "cover.jpg")
            return dest
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


MUSICDL = MusicDL()


# ---------------------------------------------------------------------------
#  AppCenter: kuratierte optionale Programme
# ---------------------------------------------------------------------------
CATALOG = BASE / "catalog.json"
APPDIR = BASE / "apps"
PKG_HELPER = "/usr/local/sbin/voidstation-pkg"
FLATHUB = "https://dl.flathub.org/repo/flathub.flatpakrepo"


def catalog():
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def catalog_app(app_id):
    return next((a for a in catalog()["apps"] if a["id"] == app_id), None)


# Architektur des Geraets ("x86_64" oder "i686" – die 32-Bit-Variante ist experimentell)
SYS_ARCH = "i686" if os.uname().machine in ("i386", "i486", "i586", "i686") else os.uname().machine


# ---- Bild in Spielen (Paul, 13.11.2026: "ein Look fuer alle Vulkan-Programme") ----------------------------------
# vkBasalt (Void-Paket, Zlib-Lizenz) ist eine Vulkan-Schicht, die das fertige Bild eines Programms nachbearbeitet. Sie
# liegt als "implicit layer" im System und wird je Prozess mit ENABLE_VKBASALT=1 eingeschaltet (vkBasalt.json,
# enable_environment); VKBASALT_CONFIG_FILE zeigt auf die Einstellungen, die VoidStation schreibt.
# Einstellungen -> Anzeige -> "Bild in Spielen": Aus (Vorgabe) | Schaerfen (CAS) | Schaerfen + Kanten glaetten (SMAA, CAS).
# Gilt fuer Kacheln aus dem Katalog der Kategorien Emulatoren, Gaming, Spiele – ausser GAME_FX_SKIP (PCSX2 und
# DuckStation schaerfen und glaetten selbst, doppelt waere zu viel; mGBA und DOSBox nutzen OpenGL). Wirkt nur, wo ein
# Programm ueber Vulkan zeichnet; OpenGL-Programme merken nichts davon. Nur 64 Bit; 32-Bit-Spiele in Steam bleiben aussen
# vor (dafuer braeuchte es vkBasalt-32bit). Das Paket kommt erst, wenn jemand die Einstellung einschaltet.
GAME_FX = {"off": "", "cas": "cas", "smaa": "smaa:cas"}
GAME_FX_CATS = ("Emulatoren", "Gaming", "Spiele")
GAME_FX_SKIP = ("pcsx2", "duckstation", "gba", "dosbox")      # schaerfen/glaetten selbst bzw. zeichnen nicht ueber Vulkan
VKBASALT_LAYER = Path("/usr/share/vulkan/implicit_layer.d/vkBasalt.json")
VKBASALT_CONF = Path.home() / ".config/voidstation/vkBasalt.conf"
_GAME_FX_JOB: dict[str, Any] = {"busy": False, "failed": False}


def game_fx(s=None):
    v = (settings_load() if s is None else s).get("game_fx")
    return v if v in GAME_FX else "off"


def game_fx_state(s=None):
    """Fuer die Einstellungsseite: None, wo es die Einstellung nicht gibt (32 Bit, Live-System)."""
    if SYS_ARCH != "x86_64" or Path("/etc/voidstation-live").exists():
        return None
    return {"mode": game_fx(s), "ready": VKBASALT_LAYER.is_file(), "busy": _GAME_FX_JOB["busy"], "failed": _GAME_FX_JOB["failed"]}


def game_fx_set(mode):
    if mode not in GAME_FX or game_fx_state() is None:
        raise ValueError("Unbekannter Wert")
    s = settings_load()
    s["game_fx"] = mode
    settings_save(s)
    log("Bild in Spielen:", mode)
    if mode != "off" and not VKBASALT_LAYER.is_file() and not _GAME_FX_JOB["busy"]:
        _GAME_FX_JOB.update(busy=True, failed=False)

        def fetch():
            r = run(["sudo", "-n", PKG_HELPER, "install", "vkBasalt"], timeout=900)
            ok = bool(r and r.returncode == 0 and VKBASALT_LAYER.is_file())
            _GAME_FX_JOB.update(busy=False, failed=not ok)
            log("vkBasalt", "installiert" if ok else "nicht installiert: " + ((r.stdout + r.stderr).strip()[-200:] if r else "Zeit abgelaufen"))
        threading.Thread(target=fetch, daemon=True).start()


def game_fx_env(tid):
    """Umgebung fuer den Start einer Kachel: {} oder die Schalter fuer vkBasalt. Darf den Start nie verhindern."""
    try:
        effects = GAME_FX[game_fx()]
        if not effects or tid in GAME_FX_SKIP or SYS_ARCH != "x86_64" or not VKBASALT_LAYER.is_file():
            return {}
        app = catalog_app(tid)
        if not app or app.get("cat") not in GAME_FX_CATS:
            return {}
        # toggleKey: Vorgabe waere "Pos1" – eine Taste, die niemand aus Versehen trifft
        text = f"effects = {effects}\ncasSharpness = 0.4\nsmaaEdgeDetection = luma\nenableOnLaunch = True\ntoggleKey = Scroll_Lock\n"
        if not VKBASALT_CONF.is_file() or VKBASALT_CONF.read_text(encoding="utf-8") != text:
            VKBASALT_CONF.parent.mkdir(parents=True, exist_ok=True)
            VKBASALT_CONF.write_text(text, encoding="utf-8")
        return {"ENABLE_VKBASALT": "1", "VKBASALT_CONFIG_FILE": str(VKBASALT_CONF)}
    except Exception as e:  # noqa: BLE001
        log(f"{tid}: Bild in Spielen:", e)
        return {}


def app_archs(a):
    """Architekturen, fuer die es eine App gibt; None = alle. "arch" im Katalog geht vor, sonst aus der Quelle:
    Flathub baut kein 32-Bit-x86 mehr, AppImages im Katalog sind 64 Bit, Widevine (Netflix & Co.) gibt es unter
    Linux nur fuer 64 Bit."""
    if isinstance(a.get("arch"), list):
        return a["arch"]
    s = a.get("source", {})
    if s.get("type") in ("flatpak", "appimage") or s.get("drm"):
        return ["x86_64"]
    return None


def app_supported(a):
    archs = app_archs(a)
    return not archs or SYS_ARCH in archs


def pad_mouse_default(tile_id):
    """Controller als Maus (Startseite: rechter Stick, A/B bzw. ✕/○ klicken) im Programm dieser Kachel von selbst an?
    Vorrang: "mouse" an der Kachel (tiles.json), dann im Katalog; Spiele und Emulatoren (Gruppe "Spiele") aus,
    weil dort Sticks und Tasten zum Spiel gehoeren – R3 schaltet trotzdem um. Sonst an."""
    if not tile_id:
        return True
    if tile_id in ("tv", "media", "ytlight") and PLAYERS.active(tile_id):   # eigener Player: komplett mit dem Controller bedienbar
        return False
    t = find_tile(tile_id) or {}
    if isinstance(t.get("mouse"), bool):
        return t["mouse"]
    try:
        a = catalog_app(tile_id)
    except (OSError, ValueError):
        a = None
    if a:
        if isinstance(a.get("mouse"), bool):
            return a["mouse"]
        return (a.get("tile") or {}).get("group") != "Spiele"
    return True


def app_maximize(tile_id):
    """Fenster dieses Programms nach dem Start maximieren (Vorgabe: ja, wie im Vollbild – ohne Rahmen ist da kein
    Unterschied). Aus mit "maximize": false an der Kachel (tiles.json) oder im Katalog."""
    t = find_tile(tile_id) or {}
    if isinstance(t.get("maximize"), bool):
        return t["maximize"]
    try:
        a = catalog_app(tile_id)
    except (OSError, ValueError):
        a = None
    return not (a and a.get("maximize") is False)


def wm_maximize(wid):
    """Normales Fenster maximieren, wenn es weder maximiert noch im Vollbild ist (Dialoge und Spiele im Vollbild
    bleiben, wie sie sind)."""
    types = vsx11.atoms(wid, "_NET_WM_WINDOW_TYPE")
    if types and "_NET_WM_WINDOW_TYPE_NORMAL" not in types:
        return                                         # Dialog, Werkzeugleiste, Startbild …
    state = vsx11.atoms(wid, "_NET_WM_STATE")
    if "_NET_WM_STATE_FULLSCREEN" in state or ("_NET_WM_STATE_MAXIMIZED_VERT" in state and "_NET_WM_STATE_MAXIMIZED_HORZ" in state):
        return
    vsx11.wm_state(wid, "add", "maximized_vert", "maximized_horz")


def app_suspendable(tile_id):
    """Programm dieser Kachel anhalten, solange etwas anderes vorn ist? Vorrang: "suspend" an der Kachel
    (tiles.json), dann im Katalog; von selbst bei Emulatoren (Katalog-Kategorie "Emulatoren" bzw. Kacheln, die
    Spiele aus share/ROMs starten), weil sie den Controller auch im Hintergrund lesen. Spiele mit Mehrspieler
    uebers Netz (Xonotic, Luanti …) und Steam laufen weiter."""
    t = find_tile(tile_id) or {}
    if isinstance(t.get("suspend"), bool):
        return t["suspend"]
    try:
        a = catalog_app(tile_id)
    except (OSError, ValueError):
        a = None
    if a and isinstance(a.get("suspend"), bool):
        return a["suspend"]
    if a:
        return a.get("cat") == "Emulatoren"
    return tile_id in ROMS.SYSTEM_TO_TILE.values() or tile_id in ROMS.TILE_TO_SYSTEM


# ---------------------------------------------------------------------------
#  CPU-Takt beim Spielen (voidstation-tune perf, ueber den Root-Helfer): Solange ein Spiel oder Emulator laeuft und
#  nicht im Hintergrund angehalten ist, steht der Governor auf "performance" – der Takt muss bei Lastwechseln nicht
#  erst hochlaufen. Danach gilt wieder, was vorher eingestellt war. Abschalten: "perf": false in settings.json
#  (alle), an der Kachel oder im Katalog (ein Programm) – oder fuer das Geraet: sudo voidstation-tune off perf.
# ---------------------------------------------------------------------------
PERF_CATS = ("Emulatoren", "Gaming", "Spiele")
PERF_SAVED = Path("/run/voidstation/perf-saved")       # legt voidstation-tune an, solange der Takt oben ist


def app_perf(tile_id):
    """CPU-Takt hochstellen, solange das Programm dieser Kachel laeuft? Vorrang: "perf" an der Kachel (tiles.json),
    dann im Katalog; von selbst bei Emulatoren, Spielen und Spiele-Plattformen (Steam, Heroic, Moonlight …) sowie
    bei Kacheln, die Spiele aus share/ROMs starten."""
    t = find_tile(tile_id) or {}
    if isinstance(t.get("perf"), bool):
        return t["perf"]
    try:
        a = catalog_app(tile_id)
    except (OSError, ValueError):
        a = None
    if a:
        if isinstance(a.get("perf"), bool):
            return a["perf"]
        return a.get("cat") in PERF_CATS
    # Kacheln ausserhalb des Katalogs: Emulator-Kachel oder eine, die nach ihrem System heisst (Start aus der Spieleliste)
    return tile_id in ROMS.TILE_TO_SYSTEM or tile_id in ROMS.SYSTEM_TO_TILE


class PerfMode:
    def __init__(self):
        self.lock = threading.Lock()
        self.tids = set()                     # laufende Kacheln, fuer die der Takt hoch soll
        self.on = False
        self.watching = False

    def started(self, tid):
        try:
            if settings_load().get("perf") is False or not app_perf(tid):
                return
        except Exception as e:  # noqa: BLE001
            log("CPU-Takt:", e)
            return
        with self.lock:
            self.tids.add(tid)
            start, self.watching = not self.watching, True
        if start:
            threading.Thread(target=self._watch, daemon=True).start()

    def _set(self, on):
        if on == self.on:
            return
        self.on = on                          # auch nach einem Fehler: nicht alle drei Sekunden neu versuchen
        r = run(["sudo", "-n", PKG_HELPER, "perf", "on" if on else "off"], timeout=15)
        if r is None or r.returncode != 0:
            log("CPU-Takt: Umschalten fehlgeschlagen", ((r.stderr or r.stdout).strip() if r else "(keine Antwort)"))
        else:
            log("CPU-Takt:", "hoch (Spiel laeuft)" if on else "wie vorher")

    def _watch(self):
        """Laeuft, solange eine der Kacheln laeuft. Angehaltene Emulatoren (Startseite vorn) zaehlen nicht."""
        while True:
            with self.lock:
                tids = set(self.tids)
            alive = {t for t in tids if APPS._get(t)}
            with APPS.lock:
                paused = set(APPS.paused)
            with self.lock:
                self.tids -= tids - alive
                done = not self.tids
                if done:
                    self.watching = False
            self._set(bool(alive - paused))
            if done:
                return
            time.sleep(3)

    def reset(self):
        """Nach einem Neustart der Oberflaeche: War der Takt noch oben (Spiel lief beim Absturz), zurueckstellen."""
        if PERF_SAVED.exists():
            run(["sudo", "-n", PKG_HELPER, "perf", "off"], timeout=15)


PERF = PerfMode()


def tile_ids():
    return {t.get("id") for g in load_config().get("groups", []) for t in g.get("tiles", [])}


def installed_sets():
    """Installierte Void-Pakete und (Benutzer-)Flatpaks – je ein Aufruf fuer den ganzen Katalog."""
    pkgs, fps = set(), set()
    r = run(["xbps-query", "-l"], timeout=20)
    for line in (r.stdout.splitlines() if r and r.returncode == 0 else []):
        parts = line.split(None, 2)                  # "ii paket-1.2_1 Beschreibung"
        if len(parts) >= 2 and parts[0] == "ii":
            pkgs.add(parts[1].rsplit("-", 1)[0])
    if shutil.which("flatpak"):
        r = run(["flatpak", "list", "--user", "--app", "--columns=application"], timeout=20)
        fps = {x.strip() for x in (r.stdout.splitlines() if r and r.returncode == 0 else []) if x.strip()}
    return pkgs, fps


def app_installed_in(a, pkgs, fps, tiles):
    s = a["source"]
    if s["type"] == "xbps":                                # oder noch als frueheres AppImage (Wechsel beim naechsten Update)
        return s["pkg"] in pkgs or bool(s.get("was_appimage") and legacy_appimage(a))
    if s["type"] == "flatpak":
        return s["ref"] in fps
    if s["type"] == "appimage":                            # oder noch als frueheres Flatpak (Wechsel beim naechsten Update)
        return (APPDIR / a["id"] / "AppRun").exists() or bool(s.get("was_flatpak") and s["was_flatpak"] in fps)
    if s["type"] in ("web", "builtin"):                    # builtin: im Player eingebaut (YouTube Light) – nur die Kachel
        return a["id"] in tiles
    if s["type"] == "mullvad":                             # Paket mullvad-vpn (eigene Paketquelle) oder noch das alte
        return Vpn.PKG in pkgs or Vpn.OLD_PKG in pkgs
    return False


def app_installed(a):
    s = a["source"]
    if s["type"] == "xbps":
        r = run(["xbps-query", s["pkg"]])
        return bool(r and r.returncode == 0) or bool(s.get("was_appimage") and legacy_appimage(a))
    if s["type"] == "flatpak":
        r = run(["flatpak", "info", "--user", s["ref"]])
        return bool(r and r.returncode == 0)
    if s["type"] == "appimage":
        return (APPDIR / a["id"] / "AppRun").exists() or legacy_flatpak(a)
    if s["type"] in ("web", "builtin"):
        return a["id"] in tile_ids()
    if s["type"] == "mullvad":
        return xbps_installed(Vpn.PKG) or xbps_installed(Vpn.OLD_PKG)
    return False


def flathub_ensure():
    """Flathub als Quelle fuer den Benutzer einrichten (falls noch nicht da): Das AppCenter bietet seit 2026.11 keine
    Flatpaks mehr an, wer etwas selbst installiert ("flatpak install --user flathub …"), braucht sie aber.
    Kurz nach dem Start, ohne Netz einfach beim naechsten Mal."""
    time.sleep(120)
    if not shutil.which("flatpak"):
        return
    r = run(["flatpak", "remotes", "--user", "--columns=name"], timeout=20)
    if r and r.returncode == 0 and "flathub" in r.stdout.split():
        return
    r = run(["flatpak", "remote-add", "--user", "--if-not-exists", "flathub", FLATHUB], timeout=60)
    log("Flathub eingerichtet" if r and r.returncode == 0 else "Flathub nicht eingerichtet (kein Netz?)")


def legacy_appimage(a):
    """Ist von dieser App (heute Paket aus der eigenen Paketquelle) noch die fruehere entpackte Fassung da?"""
    return (APPDIR / a["id"] / "AppRun").exists()


def legacy_flatpak(a):
    """Ist von dieser App (heute AppImage) noch die fruehere Flatpak-Fassung installiert?"""
    ref = a["source"].get("was_flatpak")
    if not ref or not shutil.which("flatpak"):
        return False
    r = run(["flatpak", "info", "--user", ref])
    return bool(r and r.returncode == 0)


def app_cmd(a):
    s = a["source"]
    if s["type"] == "web":
        kiosk = ["--kiosk"] if s.get("kiosk", True) else []      # "kiosk": false -> normaler Browser mit Leisten
        return ["firefox", *kiosk, "--no-remote", "--profile",
                f"~/.local/share/voidstation/profiles/{a['id']}", s["url"]]
    return a.get("cmd")                                  # None: Kachel mit eigener Seite (Mullvad VPN)


def config_save(c):
    tmp = CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CONFIG)


def tile_add(a):
    c = load_config()
    if a["id"] in {t.get("id") for g in c["groups"] for t in g["tiles"]}:
        return
    t = dict(a.get("tile", {}))
    gname = t.pop("group", "Apps")
    tile = {"id": a["id"], "label": t.pop("label", a["name"]), "size": t.get("size", "medium"),
            "color": t.get("color", "#2f3238"), "icon": t.get("icon", "globe"),
            "cmd": app_cmd(a), "app": True}
    if not tile["cmd"]:
        del tile["cmd"]
    if t.get("sub"):
        tile["sub"] = t["sub"]
    if t.get("type"):                                  # eigene Seite statt Programm (Mullvad VPN: "vpn")
        tile["type"] = t["type"]
    grp = next((g for g in c["groups"] if g.get("name") == gname), None)
    if grp is None:
        grp = {"name": gname, "tiles": []}
        sys_idx = next((i for i, g in enumerate(c["groups"]) if g.get("name") == "System"), len(c["groups"]))
        c["groups"].insert(sys_idx, grp)
    grp["tiles"].append(tile)
    config_save(c)


def tile_remove(app_id):
    c = load_config()
    for g in c["groups"]:
        g["tiles"] = [t for t in g["tiles"] if t.get("id") != app_id]
    c["groups"] = [g for g in c["groups"] if g["tiles"]]
    config_save(c)


def gpu_vendors():
    """Verbaute Grafik: 'intel', 'amd', 'nvidia' (aus /sys, ohne Zusatzprogramme)."""
    names = {"0x8086": "intel", "0x1002": "amd", "0x10de": "nvidia"}
    found = []
    for d in Path("/sys/bus/pci/devices").glob("*"):
        try:
            if not (d / "class").read_text().startswith("0x03"):
                continue
            v = names.get((d / "vendor").read_text().strip())
        except OSError:
            continue
        if v and v not in found:
            found.append(v)
    return found


def xbps_installed(pkg):
    r = run(["xbps-query", pkg])
    return bool(r and r.returncode == 0)


# Proton-GE (offizielle Releases von GloriousEggroll) fuer natives Steam
PROTON_DIR = Path.home() / ".local/share/Steam/compatibilitytools.d"
PROTON_API = "https://api.github.com/repos/GloriousEggroll/proton-ge-custom/releases/latest"


def proton_latest():
    req = urllib.request.Request(PROTON_API, headers={**UA, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


PROTON_STATE = PROTON_DIR / ".voidstation.json"      # welche Versionen VoidStation selbst installiert hat


def proton_state():
    try:
        return [e for e in json.loads(PROTON_STATE.read_text()) if e.get("tag") and e.get("dir")]
    except (OSError, ValueError, AttributeError):
        return []


def proton_state_save(entries):
    PROTON_STATE.write_text(json.dumps(entries))


def proton_installed():
    return [e["tag"] for e in proton_state() if (PROTON_DIR / e["dir"]).is_dir()]


class Jobs:
    """Genau ein Installations-/Update-Auftrag gleichzeitig, mit Protokoll fuer die Oberflaeche."""

    UPDATE_LOG = BASE / "logs" / "update.log"      # ganzes Protokoll des letzten Update-Laufs (davor: .1)

    def __init__(self):
        self.lock = threading.Lock()
        self.job: Any = None                       # laufender bzw. letzter Auftrag (dict)
        self._rate = None
        self._logf = None

    def current(self):
        with self.lock:
            if not self.job:
                return None
            j = dict(self.job)
            j["steps"] = [dict(x) for x in self.job.get("steps") or []]
            j["items"] = [dict(x) for x in self.job.get("items") or []]
            return j

    def _log(self, line):
        line = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line).rstrip()
        if not line:
            return
        if line.startswith("@vs "):                  # Steuerzeile fuer die Oberflaeche (voidstation-pkg), nicht ins Protokoll
            return self._marker(line[4:].strip())
        if line == "Signatur geprueft: ok":          # aeltere voidstation-pkg ohne Steuerzeile
            self._marker("verified")
        with self.lock:
            self.job["log"] = (self.job["log"] + [line])[-60:]
            self.job["n"] += 1                       # laufende Zeilennummer (fuer "vsctl update -v")
            f = self._logf
        if f:
            try:
                f.write(line + "\n")
                f.flush()
            except (OSError, ValueError):
                pass

    # ---- Fortschritt des Update-Auftrags fuer den Vollbild-Bildschirm und "vsctl update":
    #   steps = [{"id": "apps"|"load"|"setup", "state": "wait"|"run"|"done"|"fail", "n": <Pakete>}]
    #   apps = Void-Pakete, Flatpaks, AppImages, Proton-GE · load = neue VoidStation-Version laden und
    #   Signatur pruefen · setup = update.sh richtet sie ein. Was nichts zu tun hat, fehlt in der Liste.
    def _step(self, sid, state):
        with self.lock:
            for x in self.job.get("steps") or []:
                if x["id"] == sid:
                    x["state"] = state

    def _step_state(self, sid):
        with self.lock:
            return next((x["state"] for x in self.job.get("steps") or [] if x["id"] == sid), None)

    def _progress(self, done=None, total=0):
        """Download-Fortschritt fuer die Oberflaeche: {"mb", "total_mb", "pct", "speed" (Byte/s), "eta" (s)} – statt
        Protokollzeilen "… 10 %" je Zehntel. None = fertig (der Wert verschwindet)."""
        now = time.monotonic()
        with self.lock:
            if not self.job:
                return
            if done is None:
                self.job.pop("progress", None)
                self._rate = None
                return
            r = self._rate
            if r is None or done < r["done"]:
                r = self._rate = {"t": now, "done": done, "speed": 0.0}
            elif now - r["t"] >= 0.3:                   # geglaettet: Mobilfunk liefert in Schueben
                inst = (done - r["done"]) / (now - r["t"])
                r.update(t=now, done=done, speed=inst if not r["speed"] else 0.85 * r["speed"] + 0.15 * inst)
            speed = r["speed"]
            self.job["progress"] = {"mb": round(done / 1048576, 1), "total_mb": round(total / 1048576, 1) if total else 0,
                                    "pct": min(100, done * 100 // total) if total else None, "speed": int(speed),
                                    "eta": int((total - done) / speed) if total and speed > 1024 else None}

    def _item(self, iid, state):
        """Zustand einer Kachel des Update-Bildschirms (wait/run/done/fail)."""
        with self.lock:
            for x in self.job.get("items") or []:
                if x["id"] == iid:
                    x["state"] = state
            self.job.pop("detail", None)

    def _detail(self, what):
        """Was das laufende Programm gerade tut, wenn es kein Download ist ("unpack")."""
        with self.lock:
            if self.job:
                self.job["detail"] = what

    def _marker(self, m):
        if m == "verified" and self._step_state("load") == "run":
            self._step("load", "done")
            self._step("setup", "run")

    def _open_log(self):
        try:
            self.UPDATE_LOG.parent.mkdir(parents=True, exist_ok=True)
            if self.UPDATE_LOG.exists():
                self.UPDATE_LOG.replace(self.UPDATE_LOG.with_name("update.log.1"))
            self._logf = open(self.UPDATE_LOG, "w", encoding="utf-8")
            self._logf.write(f"VoidStation-Update {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        except OSError as e:
            log("update.log:", e)
            self._logf = None

    def _close_log(self):
        f, self._logf = self._logf, None
        if f:
            try:
                f.close()
            except OSError:
                pass

    def _run(self, args, cwd=None):
        self._log("$ " + " ".join(args))
        p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             stdin=subprocess.DEVNULL, cwd=cwd, bufsize=1, errors="replace",
                             start_new_session=True)
        assert p.stdout is not None
        for line in p.stdout:
            for part in line.replace("\r", "\n").split("\n"):
                self._log(part)
        return p.wait()

    def busy(self):
        with self.lock:
            return bool(self.job and self.job["state"] == "running")

    def start(self, action, app=None):
        with self.lock:
            if self.job and self.job["state"] == "running":
                raise RuntimeError("Es läuft schon ein Auftrag")
            name = app["name"] if app else "Updates"
            self.job = {"action": action, "app": app["id"] if app else None,
                        "name": name, "state": "running", "reboot": False,
                        "log": [], "n": 0, "started": time.time(), "result": None,
                        "steps": [], "from": None, "to": None}
        threading.Thread(target=self._work, args=(action, app), daemon=True).start()

    def _finish(self, ok, result=None, reboot=False):
        with self.lock:
            self.job["state"] = "done" if ok else "error"
            self.job["result"] = result
            self.job["reboot"] = bool(reboot)

    def _selfupdate(self):
        ok = self._run(["sudo", "-n", PKG_HELPER, "selfupdate", "--markers"]) == 0
        _VCACHE["t"] = 0.0
        return ok

    def _work(self, action, a):
        try:
            with SYS_LOCK:                           # nie gleichzeitig mit der Update-Pruefung (xbps-Sperre)
                if action == "install":
                    ok = self._install(a)
                    if ok:
                        tile_add(a)
                    self._finish(ok, a.get("note") if ok else None)
                elif action == "remove":
                    APPS.close(a["id"])
                    ok = self._remove(a)
                    if ok:
                        tile_remove(a["id"])
                    self._finish(ok)
                elif action == "ime":                    # Eingabemethode (fcitx5) fuer ja/ko/zh nachinstallieren
                    ok = self._run(["sudo", "-n", PKG_HELPER, "install", *a["pkgs"]]) == 0
                    self._finish(ok)
                    if ok:
                        threading.Thread(target=ime_sync, daemon=True).start()
                elif action == "update":
                    self._open_log()
                    try:
                        ok, result, reboot = self._update_all()
                    finally:
                        self._close_log()
                    self._finish(ok, result, reboot)
                if action in ("install", "remove"):
                    _sys_check(sync=False)           # Paketstand hat sich geaendert
        except Exception as e:  # noqa: BLE001
            self._log(f"Fehler: {e}")
            self._finish(False)

    def _update_all(self):
        """Alle Updates in einem Durchgang: Void-Pakete (inkl. Kernel) -> Flatpak -> AppImages
        -> Proton-GE -> VoidStation. Was aktuell ist, wird uebersprungen."""
        if xbps_busy():
            self._log("xbps läuft gerade (z. B. im Terminal) – bitte warten, bis es fertig ist.")
            return False, {"busy": True}, False
        self._log("Suche nach Updates …")
        # Gerade erst (Einstellungen → Updates) mit frischen Paketlisten geprueft: nicht noch einmal laden
        fresh = time.time() - (_SCACHE["t"] or 0) < 180 and not _SCACHE["error"]
        _sys_check(sync=not fresh, logf=self._log)
        s = dict(_SCACHE)
        vs = vs_update_status(force=True)
        ok, done = True, []
        flat = bool(s["flatpak"] and shutil_which("flatpak"))
        imgs = [app for app in catalog()["apps"] if app["id"] in s["appimage"]]
        apps = bool(s["pkgs"] or s["error"] or flat or imgs or s["proton"])
        steps = [{"id": "apps", "state": "wait",
                  "n": len(s["pkgs"]) + (len(s["flatpak"]) if flat else 0) + len(imgs) + (1 if s["proton"] else 0)}] if apps else []
        if vs["available"]:
            steps += [{"id": "load", "state": "wait"}, {"id": "setup", "state": "wait"}]
        if steps:                                       # Paketlisten und App-Versionen neu abfragen: dauert, soll sichtbar sein
            steps.append({"id": "check", "state": "wait"})
        # Eine Kachel je Programm fuer den Update-Bildschirm, in der Farbe seiner Kachel auf der Startseite
        items = []
        if s["pkgs"] or s["error"]:
            items.append({"id": "system", "icon": "cube", "color": "#2f5578", "n": len(s["pkgs"]), "state": "wait"})
        if flat:
            items.append({"id": "flatpak", "icon": "store", "color": "#4a4580", "n": len(s["flatpak"]), "state": "wait"})
        for app in imgs:
            tile = app.get("tile") or {}
            items.append({"id": "app:" + app["id"], "name": app["name"], "icon": tile.get("icon") or "store",
                          "color": tile.get("color") or "#47505a", "state": "wait"})
        if s["proton"]:
            items.append({"id": "proton", "name": "Proton-GE", "icon": "gamepad", "color": "#3b2d5c", "state": "wait"})
        if vs["available"]:
            items.append({"id": "vs", "name": "VoidStation", "icon": "update", "color": "#1f6470", "state": "wait"})
        if steps:
            items.append({"id": "check", "icon": "search", "color": "#50575f", "state": "wait"})
        with self.lock:
            self.job.update(steps=steps, items=items, **({"from": vs["local"], "to": vs["remote"]} if vs["available"] else {}))
        if apps:
            self._step("apps", "run")
            ok_apps = True
            if s["pkgs"] or s["error"]:
                self._log(f"== Void-Pakete: {len(s['pkgs'])} ==")
                self._item("system", "run")
                if self._run(["sudo", "-n", PKG_HELPER, "update"]) == 0:
                    done.append("system")
                    self._item("system", "done")
                else:
                    ok_apps = False
                    self._item("system", "fail")
            else:
                self._log("Void-Pakete: aktuell")
            if flat:
                self._log(f"== Flatpak: {len(s['flatpak'])} ==")
                self._item("flatpak", "run")
                res = self._run(["flatpak", "update", "--user", "-y", "--noninteractive"]) == 0
                self._item("flatpak", "done" if res else "fail")
                ok_apps = res and ok_apps
            for app in imgs:
                self._log(f"== {app['name']} ({'Wechsel vom Flatpak' if legacy_flatpak(app) else 'Download'}) ==")
                self._item("app:" + app["id"], "run")
                res = self._app_update(app)
                self._item("app:" + app["id"], "done" if res else "fail")
                ok_apps = res and ok_apps
            if s["proton"]:
                self._log(f"== Proton-GE {s['proton']} ==")
                self._item("proton", "run")
                res = self._proton_ge()
                self._item("proton", "done" if res else "fail")
                ok_apps = res and ok_apps
            self._step("apps", "done" if ok_apps else "fail")
            ok = ok_apps
        else:
            self._log("Void-Pakete: aktuell")
        if vs["available"]:
            self._log(f"== VoidStation {vs['remote']} ==")
            self._step("load", "run")
            self._item("vs", "run")
            if self._selfupdate():
                self._step("load", "done")           # falls die Steuerzeile fehlte
                self._step("setup", "done")
                self._item("vs", "done")
                done.append("voidstation")
            else:
                self._step("load" if self._step_state("load") == "run" else "setup", "fail")
                self._item("vs", "fail")
                ok = False
        else:
            self._log("VoidStation: aktuell")
        if steps:                                       # sonst wurde gerade erst geprueft und nichts geaendert
            self._log("Prüfe Stand …")
            self._step("check", "run")
            self._item("check", "run")
            _sys_check(sync=True)
            vs_update_status(force=True)
            self._step("check", "done")
            self._item("check", "done")
        rb = reboot_needed()
        return ok, {"done": done, "kernel": rb["kernel"]}, rb["kernel"] or rb["voidstation"] or "voidstation" in done

    def _install(self, a):
        s = a["source"]
        if s["type"] == "xbps":
            return self._xbps_install(s)
        if s["type"] == "flatpak":
            if not shutil_which("flatpak"):
                self._log("Flatpak fehlt – wird installiert …")
                if self._run(["sudo", "-n", PKG_HELPER, "install", "flatpak"]) != 0:
                    return False
            for pkg in s.get("host_pkgs", []):
                if self._run(["sudo", "-n", PKG_HELPER, "install", pkg]) != 0:
                    self._log(f"Hinweis: {pkg} konnte nicht installiert werden")
            self._run(["flatpak", "remote-add", "--user", "--if-not-exists", "flathub", FLATHUB])
            if self._run(["flatpak", "install", "--user", "-y", "--noninteractive", "flathub", s["ref"]]) != 0:
                return False
            for ext in s.get("extras", []):
                if self._run(["flatpak", "install", "--user", "-y", "--noninteractive", "flathub", ext]) != 0:
                    self._log(f"Hinweis: Erweiterung {ext} fehlt – App spaeter im AppCenter entfernen und neu installieren")
            return True
        if s["type"] == "appimage":
            return self._appimage(a)
        if s["type"] == "mullvad":
            return self._mullvad("install")
        if s["type"] == "builtin":                     # Teil von VoidStation: nur fehlende Pakete nachholen, dann Kachel
            for pkg in s.get("pkgs", []):
                if not xbps_installed(pkg) and self._run(["sudo", "-n", PKG_HELPER, "install", pkg]) != 0:
                    return False
            self._log("in VoidStation eingebaut – Kachel wird angelegt")
            return True
        if s["type"] == "web":
            prof = BASE / "profiles" / a["id"]
            prof.mkdir(parents=True, exist_ok=True)
            js = (BASE / "firefox" / "user-common.js").read_text()
            if s.get("ua"):
                js += f'user_pref("general.useragent.override", {json.dumps(s["ua"])});\n'
            js += 'user_pref("media.ffmpeg.vaapi.enabled", true);\n'
            if s.get("drm"):                           # Netflix & Co.: Widevine (laedt Firefox beim ersten Bedarf selbst)
                js += ('user_pref("media.eme.enabled", true);\n'
                       'user_pref("media.gmp-widevinecdm.visible", true);\n'
                       'user_pref("media.gmp-widevinecdm.enabled", true);\n'
                       'user_pref("media.gmp-manager.updateEnabled", true);\n')
            (prof / "user.js").write_text(js)
            self._log(f"Profil angelegt: {prof}")
            return True
        return False

    def _xbps_install(self, s):
        # 1. Zusatz-Repos (z. B. nonfree, multilib), danach Paketlisten neu laden
        repos = [r for r in s.get("repos", []) if not xbps_installed(r)]
        if repos:
            if self._run(["sudo", "-n", PKG_HELPER, "install", *repos]) != 0:
                return False
            self._run(["sudo", "-n", PKG_HELPER, "sync"])
        # 2. Abhaengigkeiten: fest + passend zur GPU in EINEM xbps-Durchgang (keine Einzelabfragen
        #    gegen die Repos - die sind mit multilib/nonfree gross und auf schwachen Rechnern langsam)
        gpus = gpu_vendors()
        self._log("Grafik: " + (", ".join(gpus) or "unbekannt"))
        want = list(s.get("deps", []))
        for v in gpus:
            want += s.get("gpu_deps", {}).get(v, [])
        deps = [p for p in dict.fromkeys(want) if not xbps_installed(p)]
        if self._run(["sudo", "-n", PKG_HELPER, "install", *deps, s["pkg"]]) != 0:
            return False
        # 3. Optionale Pakete einzeln - fehlt eins im Repo, geht es trotzdem weiter
        for p in s.get("optional", []):
            if xbps_installed(p):
                continue
            if self._run(["sudo", "-n", PKG_HELPER, "install", p]) == 0:
                deps.append(p)
            else:
                self._log(f"Hinweis: optionales Paket {p} nicht installiert")
        # Neu hinzugekommene Abhaengigkeiten als automatisch markieren -> beim Entfernen wieder weg
        if deps:
            self._run(["sudo", "-n", PKG_HELPER, "markauto", *deps])
        for addon in s.get("addons", []):
            if addon == "proton-ge" and not self._proton_ge():
                self._log("Hinweis: Proton-GE kommt mit dem naechsten Update (Einstellungen → Updates)")
            # Proprietaerer NVIDIA-Treiber: 32-Bit-Bibliotheken in genau der Treiberversion (driver_deps im Katalog).
            # Paketlisten hat "install" gerade geladen. Scheitert es, holt das naechste Systemupdate es nach.
            if addon == "gpu32" and self._run(["sudo", "-n", PKG_HELPER, "gpu32", "--nosync"]) != 0:
                self._log("Hinweis: 32-Bit-Treiber fuer NVIDIA kommen mit dem naechsten Update (Einstellungen → Updates)")
        return True

    def _proton_ge(self):
        """Neueste Proton-GE-Version laden (SHA512 geprueft); die zwei neuesten eigenen behalten."""
        tmp, tops = None, []
        try:
            rel = proton_latest()
            tag = rel["tag_name"]
            mine = proton_state()
            if any(e["tag"] == tag and (PROTON_DIR / e["dir"]).is_dir() for e in mine):
                self._log(f"Proton-GE {tag} ist aktuell")
                return True
            assets = {x["name"]: x["browser_download_url"] for x in rel.get("assets", [])}
            tars = [n for n in assets if n.endswith("-x86_64.tar.gz")] or \
                   [n for n in assets if n.endswith(".tar.gz") and "aarch64" not in n]
            if not tars:
                self._log("Proton-GE: kein passendes Archiv im Release gefunden")
                return False
            tar_name = tars[0]
            sum_url = assets.get(tar_name[:-len(".tar.gz")] + ".sha512sum")
            if not sum_url:
                self._log("Proton-GE: Pruefsumme fehlt im Release – abgebrochen")
                return False
            with urllib.request.urlopen(urllib.request.Request(sum_url, headers=UA), timeout=30) as r:
                want = r.read().decode().split()[0].lower()
            PROTON_DIR.mkdir(parents=True, exist_ok=True)
            tmp = PROTON_DIR / f".{tar_name}.part"
            self._log(f"Lade {tar_name} …")
            h = hashlib.sha512()
            req = urllib.request.Request(assets[tar_name], headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                done, last, shown = 0, 0, 0.0
                self._progress(0, total)
                while True:
                    chunk = r.read(1 << 18)
                    if not chunk:
                        break
                    f.write(chunk)
                    h.update(chunk)
                    done += len(chunk)
                    if time.monotonic() - shown >= 0.5:
                        shown = time.monotonic()
                        self._progress(done, total)
                    if total and done * 10 // total > last:
                        last = done * 10 // total
                        self._log(f"… {last * 10} %")
            self._progress(None)
            if h.hexdigest() != want:
                tmp.unlink(missing_ok=True)
                self._log("Proton-GE: Pruefsumme stimmt nicht – verworfen")
                return False
            self._log("Pruefsumme ok, entpacke …")
            self._detail("unpack")
            with tarfile.open(tmp) as t:
                tops = sorted({m.name.split("/", 1)[0] for m in t.getmembers() if m.name and not m.name.startswith("/")})
                kw: dict[str, Any] = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
                t.extractall(PROTON_DIR, **kw)
            tmp.unlink(missing_ok=True)
            top = next((d for d in tops if (PROTON_DIR / d / "compatibilitytool.vdf").exists()), tops[0] if tops else tag)
            mine = [{"tag": tag, "dir": top}] + [e for e in mine if e["dir"] != top]
            for e in mine[2:]:
                shutil.rmtree(PROTON_DIR / e["dir"], ignore_errors=True)
                self._log(f"alte Version entfernt: {e['dir']}")
            proton_state_save(mine[:2])
            self._log(f"Proton-GE {tag} installiert ({top})")
            return True
        except Exception as e:  # noqa: BLE001
            self._log(f"Proton-GE: {e}")
            # halbe Downloads/Entpack-Reste wegraeumen (nichts anfassen, was schon vorher da war)
            if tmp:
                tmp.unlink(missing_ok=True)
            keep = {x["dir"] for x in proton_state()}
            for d in tops:
                if d not in keep and d and d not in (".", ".."):
                    shutil.rmtree(PROTON_DIR / d, ignore_errors=True)
            return False

    def _remove(self, a):
        s = a["source"]
        if s["type"] == "xbps":
            if s.get("was_appimage") and legacy_appimage(a):   # noch die fruehere entpackte Fassung
                rm_path(APPDIR / a["id"])
                appimage_stampfile(a).unlink(missing_ok=True)
                self._log(f"entfernt: {APPDIR / a['id']}")
                if not xbps_installed(s["pkg"]):
                    return True
            ok = self._run(["sudo", "-n", PKG_HELPER, "remove", s["pkg"]]) == 0
            if ok and "proton-ge" in s.get("addons", []):
                self._log("Spiele, Spielstaende und Proton-GE unter ~/.local/share/Steam bleiben erhalten")
            return ok
        if s["type"] == "flatpak":
            for ext in s.get("extras", []):
                self._run(["flatpak", "uninstall", "--user", "-y", "--noninteractive", ext])
            ok = self._run(["flatpak", "uninstall", "--user", "-y", "--noninteractive", s["ref"]]) == 0
            self._run(["flatpak", "uninstall", "--user", "-y", "--noninteractive", "--unused"])
            for pkg in s.get("host_pkgs", []):
                self._run(["sudo", "-n", PKG_HELPER, "remove", pkg])
            return ok
        if s["type"] == "builtin":                     # nur die Kachel; Abos und Verlauf bleiben fuer spaeter
            return True
        if s["type"] == "mullvad":
            return self._mullvad("remove")
        if s["type"] in ("appimage", "web"):
            target = APPDIR / a["id"] if s["type"] == "appimage" else BASE / "profiles" / a["id"]
            rm_path(target)
            self._log(f"entfernt: {target}")
            if s["type"] == "appimage" and legacy_flatpak(a):
                self._run(["flatpak", "uninstall", "--user", "-y", "--noninteractive", s["was_flatpak"]])
            return True
        return False

    def _mullvad(self, action):
        """Mullvad VPN: Root-Helfer laedt die .deb, prueft die Signatur, baut das Paket, richtet den Dienst ein."""
        ok = self._run(["sudo", "-n", PKG_HELPER, "mullvad", action]) == 0
        VPN.ensure()
        return ok

    def _app_update(self, a):
        """Ein Programm aus der Update-Liste (_SCACHE["appimage"]) aktualisieren."""
        if a["source"]["type"] == "mullvad":
            return self._mullvad("update")
        if a["source"]["type"] == "xbps":
            return self._to_package(a)
        return self._appimage(a)

    def _to_package(self, a):
        """Wechsel entpackte Fassung (apps/<id>) -> Paket aus der eigenen Paketquelle (seit 2026.12). Einstellungen
        liegen bei beiden unter ~/.config bzw. ~/.local/share und bleiben, wo sie sind. Erst wenn das Paket
        installiert ist, wird die Kachel umgestellt und der Ordner geloescht – nie ohne lauffaehige Fassung."""
        if not self._xbps_install(a["source"]):
            self._log("Paket nicht installiert – die entpackte Fassung bleibt, naechstes Update versucht es erneut")
            return False
        c = load_config()
        changed = False
        for g in c.get("groups", []):
            for t in g.get("tiles", []):
                cmd = t.get("cmd")
                if t.get("id") == a["id"] and isinstance(cmd, list) and cmd and Path(str(cmd[0])).name == "AppRun":
                    t["cmd"] = app_cmd(a)
                    changed = True
        if changed:
            config_save(c)
            self._log("Kachel startet jetzt das Paket")
        rm_path(APPDIR / a["id"])
        appimage_stampfile(a).unlink(missing_ok=True)
        self._log(f"entpackte Fassung entfernt: {APPDIR / a['id']}")
        emu_paths_refresh()
        return True

    def _appimage(self, a):
        """Programm herunterladen und unter apps/<id> entpacken – AppImage, ZIP, Tarball oder .deb (app_release).
        Gestartet wird immer apps/<id>/AppRun: beim AppImage dessen eigenes, sonst ein kleines Startskript, das
        VoidStation anlegt (Quelle "run"). Kein FUSE, keine Sandbox, Dateidialoge wie bei jedem anderen Programm."""
        s = a["source"]
        APPDIR.mkdir(parents=True, exist_ok=True)
        for pkg in s.get("host_pkgs", []):             # Bibliotheken, die das Programm vom System erwartet
            if not xbps_installed(pkg):
                self._log(f"benötigt {pkg} – wird installiert …")
                if self._run(["sudo", "-n", PKG_HELPER, "install", pkg]) != 0:
                    self._log(f"Hinweis: {pkg} konnte nicht installiert werden")
        try:
            rel = app_release(a)
        except Exception as e:  # noqa: BLE001
            self._log(f"Download-Adresse nicht gefunden: {e}")
            return False
        url = rel["url"]
        fmt = archive_format(a, url)
        dl = APPDIR / f".{a['id']}.download"
        self._log(f"Lade {url}")
        try:
            req = urllib.request.Request(url, headers=UA)
            h = hashlib.sha256()
            with urllib.request.urlopen(req, timeout=60) as r, open(dl, "wb") as f:
                stamp = rel["stamp"] or asset_stamp(r.headers)
                total = int(r.headers.get("Content-Length") or 0)
                done, last = 0, 0.0
                self._progress(0, total)
                while True:
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    f.write(chunk)
                    h.update(chunk)
                    done += len(chunk)
                    now = time.monotonic()
                    if now - last >= 0.5:              # Balken im Band (ohne Groessenangabe nur MB, z. B. GitLab)
                        last = now
                        self._progress(done, total)
            self._progress(None)
            self._log(f"geladen: {done / 1048576:.0f} MB")
            if total and done != total:
                raise RuntimeError(f"Download unvollständig ({done} von {total} Byte)")
            if rel["sha256"] and h.hexdigest() != rel["sha256"]:
                raise RuntimeError("Prüfsumme stimmt nicht")
        except Exception as e:  # noqa: BLE001
            self._progress(None)
            dl.unlink(missing_ok=True)
            self._log(f"Download fehlgeschlagen: {e}")
            return False
        work = APPDIR / f".{a['id']}-extract"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir()
        self._log("Entpacke …")
        self._detail("unpack")
        try:
            root = extract_app(dl, fmt, work, int(s.get("strip", 0)))
            if fmt != "appimage":
                app_launcher(root, a)
        except Exception as e:  # noqa: BLE001
            self._log(f"Entpacken fehlgeschlagen: {e}")
            shutil.rmtree(work, ignore_errors=True)
            dl.unlink(missing_ok=True)
            return False
        dest = APPDIR / a["id"]
        old = APPDIR / f".{a['id']}-old"
        rm_path(old)
        if dest.exists() or dest.is_symlink():         # auch ein kaputter Link (Fehler bis 01.11.2026)
            dest.rename(old)                           # erst tauschen, dann loeschen: nie ohne lauffaehige Fassung
        shutil.move(str(root), str(dest))
        rm_path(old)
        shutil.rmtree(work, ignore_errors=True)
        dl.unlink(missing_ok=True)
        try:
            appimage_stampfile(a).write_text(stamp)    # Vergleichswert fuer die Update-Pruefung
        except OSError:
            pass
        self._log("installiert nach " + str(dest))
        if s.get("was_flatpak"):                       # zuerst: Daten des Flatpaks uebernehmen ...
            self._from_flatpak(a)
        for js in s.get("json_set", []):               # ... dann z. B. Discord: eigenes Update-Fenster abschalten
            try:
                json_merge(Path(os.path.expanduser(js["path"])), js["values"])
            except (OSError, ValueError) as e:
                self._log(f"Hinweis: {js['path']} nicht angepasst ({e})")
        return True

    def _from_flatpak(self, a):
        """Wechsel Flatpak -> AppImage: Einstellungen, Spielstaende und Zwischenspeicher uebernehmen (nur, wo das
        AppImage noch nichts hat), Kachel umstellen, Flatpak entfernen – seine Daten unter ~/.var/app bleiben als
        Sicherung liegen."""
        ref = a["source"]["was_flatpak"]
        # Programme (nicht Emulatoren): Ordner aus ~/.var/app/<ref> verschieben statt kopieren – Spielebibliotheken
        # (itch) waeren sonst doppelt auf der Platte. Am alten Ort bleibt ein Link, damit gespeicherte absolute Pfade
        # (Heroic: Wine-Versionen unter config/heroic/tools, itch: Datenbank) weiter stimmen.
        fp = Path.home() / ".var/app" / ref
        for rel_src, rel_dst in a["source"].get("migrate", []):
            src, dst = fp / rel_src, Path.home() / rel_dst
            if not src.exists() or src.is_symlink():
                continue
            if dst.exists():
                self._log(f"nicht übernommen (gibt es schon): {dst}")
                continue
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                os.symlink(dst, src)
                self._log(f"übernommen: {src} -> {dst}")
            except OSError as e:
                self._log(f"nicht übernommen: {src} ({e})")
        for src, dst in emu_dirs(a["id"]):
            if src.is_dir() and not dst.exists():
                try:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(src, dst, symlinks=True)
                    self._log(f"übernommen: {src} -> {dst}")
                except OSError as e:
                    self._log(f"nicht übernommen: {src} ({e})")
        emu_paths_refresh()
        c = load_config()
        changed = False
        for g in c.get("groups", []):
            for t in g.get("tiles", []):
                cmd = t.get("cmd")
                if t.get("id") == a["id"] and isinstance(cmd, list) and ref in cmd:
                    t["cmd"] = app_cmd(a)
                    changed = True
        if changed:
            config_save(c)
            self._log("Kachel startet jetzt die entpackte Fassung")
        if legacy_flatpak(a):
            if self._run(["flatpak", "uninstall", "--user", "-y", "--noninteractive", ref]) == 0:
                self._run(["flatpak", "uninstall", "--user", "-y", "--noninteractive", "--unused"])
                self._log(f"Flatpak {ref} entfernt (Daten bleiben unter ~/.var/app/{ref})")


# ---------------------------------------------------------------------------
#  VoidStation selbst aktualisieren (Quelle: /usr/local/share/voidstation/update-url)
# ---------------------------------------------------------------------------
URLFILE = Path("/usr/local/share/voidstation/update-url")
CHANNELFILE = Path("/usr/local/share/voidstation/channel")
CHANNELS = {"stable": "Stable", "main": "Testing"}
OPTINFILE = Path("/usr/local/share/voidstation/testing-optin")   # Testing bewusst gewaehlt (vsctl channel testing)
_VCACHE: dict[str, Any] = {"t": 0.0, "remote": None, "error": None, "key": None}


def vs_channel():
    try:
        ch = CHANNELFILE.read_text().split()[0]
    except (OSError, IndexError):
        ch = "stable"
    return ch if ch in CHANNELS else "stable"


def vs_update_base():
    tmpl = URLFILE.read_text().split()[0].rstrip("/")
    return tmpl.replace("{channel}", vs_channel())


def vs_version():
    """Installierte Version: {"version": "0.4.0", "build": "…", "history": […]} (aeltere Stände: nur build)."""
    try:
        d = json.loads((BASE / "version.json").read_text(encoding="utf-8"))
        if d.get("build"):
            return d
    except (OSError, ValueError):
        pass
    try:
        b = (BASE / "VERSION").read_text().strip()
        return {"version": None, "build": b or None}
    except OSError:
        return {"version": None, "build": None}


def _fetch_remote(base):
    def get(name):
        req = urllib.request.Request(f"{base}/{name}", headers=UA)
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.read(200_000).decode("utf-8", "replace")
    try:
        d = json.loads(get("version.json"))
        if not re.fullmatch(r"[0-9a-f]{6,64}", str(d.get("build", ""))):
            raise ValueError("version.json ohne gueltige Build-Kennung")
        return d
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    b = get("version.txt").strip()                # aeltere Veroeffentlichungen
    if not re.fullmatch(r"[0-9a-f]{6,64}", b):
        raise ValueError("unerwartete Antwort vom Server")
    return {"version": None, "build": b, "history": []}


def vs_channel_migrate():
    """Seit 2026.11 gibt es Testing nur noch auf Wunsch (vsctl channel testing, Markierung testing-optin).
    Geraete, die Testing frueher im Installer oder in den Einstellungen gewaehlt haben, wechseln zu Stable,
    sobald Stable neuer ist als ihr eigener Stand – nie auf einen aelteren Stand. True = Kanal umgestellt."""
    if LIVE or vs_channel() != "main" or OPTINFILE.exists():
        return False
    try:
        tmpl = URLFILE.read_text().split()[0].rstrip("/")
        stable = _fetch_remote(tmpl.replace("{channel}", "stable"))
    except Exception:  # noqa: BLE001 – naechste Pruefung versucht es wieder
        return False
    lv, sv = vtuple(vs_version().get("version")), vtuple(stable.get("version"))
    if not (lv and sv and sv > lv):
        return False
    r = run(["sudo", "-n", PKG_HELPER, "channel", "auto"], timeout=20)
    if not r or r.returncode != 0 or vs_channel() != "stable":
        log("Kanal: Wechsel zu Stable fehlgeschlagen:", ((r.stdout + r.stderr).strip() if r else "Zeitueberschreitung")[-200:])
        return False
    log(f"Kanal: Testing -> Stable (Stable {stable.get('version')} ist neuer als {vs_version().get('version')};"
        " Testing gibt es nur noch auf Wunsch: vsctl channel testing)")
    return True


def vs_update_status(force=False):
    """Vergleicht die eigene Version mit dem Update-Kanal (hoechstens alle 10 min neu)."""
    try:
        base = vs_update_base()
    except (OSError, IndexError):
        base = None
    if base and not LIVE and (force or time.time() - _VCACHE["t"] > 600 or _VCACHE["key"] != base):
        if not net_online():
            # ohne Netz gar nicht erst versuchen; naechster Aufruf prueft wieder (kein 10-min-Zwischenspeicher)
            _VCACHE.update(error="offline")
            return vs_state()
        if vs_channel_migrate():
            base = vs_update_base()
        try:
            _VCACHE.update(remote=_fetch_remote(base), error=None)
        except Exception as e:  # noqa: BLE001
            _VCACHE.update(error=str(e))
            if _VCACHE["key"] != base:
                _VCACHE["remote"] = None
        _VCACHE.update(t=time.time(), key=base)
    return vs_state()


def net_online():
    """Gibt es eine Standardroute ins Netz (IPv4 oder IPv6, nicht ueber lo)? Schnell, ohne Netzwerkzugriff."""
    try:
        for line in Path("/proc/net/route").read_text().splitlines()[1:]:
            f = line.split()
            if len(f) > 3 and f[1] == "00000000" and int(f[3], 16) & 1:      # Ziel 0.0.0.0, Route aktiv (RTF_UP)
                return True
    except (OSError, ValueError):
        return True                                                        # unbekannt: nicht als offline melden
    try:
        for line in Path("/proc/net/ipv6_route").read_text().splitlines():
            f = line.split()
            if len(f) == 10 and f[0] == "0" * 32 and f[1] == "00" and f[9] != "lo" and not int(f[8], 16) & 0x200:
                return True                                                # ::/0, kein Reject-Eintrag
    except (OSError, ValueError):
        pass
    return False


def vtuple(v):
    """Version -> vergleichbares Tupel; unbekannt -> None.
    "0.7.2" -> (0, 7, 2) · "2026.11" -> (2026, 11) · "2026.11.1" -> (2026, 11, 1)
    "2026.11+testing.20261020" (Testing-Stand nach 2026.11) -> (2026, 11, 0, 20261020):
    neuer als 2026.11, aber aelter als 2026.11.1 und 2026.12."""
    s = str(v or "")
    base, _, extra = s.partition("+")
    try:
        t = tuple(int(x) for x in base.split("."))
    except ValueError:
        return None
    if not extra:
        return t
    m = re.fullmatch(r"testing\.(\d{8})", extra)
    if not m:
        return None
    if len(t) == 2:
        t += (0,)                                     # Testing nach 2026.11 liegt vor 2026.11.1
    return t + (int(m.group(1)),)


def vs_state():
    """Stand aus dem Zwischenspeicher, ohne Netzwerk (fuer /api/status)."""
    local, remote = vs_version(), _VCACHE["remote"]
    available = bool(remote and remote.get("build") and remote["build"] != local.get("build"))
    lv, rv = vtuple(local.get("version")), vtuple(remote.get("version")) if remote else None
    if available and lv and rv and rv < lv:
        available = False                             # nie auf eine aeltere Version "aktualisieren" (z. B. Stable hinter Testing)
    if LIVE:
        available = False
    changes = []
    if available:
        seen = {e.get("version") for e in (local.get("history") or [])}
        for e in remote.get("history") or []:
            if e.get("version") in seen:
                break
            changes.append(e)
    ch = vs_channel()
    return {"local": local.get("version") or local.get("build"), "local_build": local.get("build"),
            "remote": (remote.get("version") or remote.get("build")) if remote else None,
            "remote_build": remote.get("build") if remote else None,
            "available": available, "changes": changes[:5], "error": _VCACHE["error"],
            "channel": ch, "channel_label": CHANNELS[ch], "checked": _VCACHE["t"] or None,
            "online": True if remote and _VCACHE["error"] != "offline" else net_online()}


# ---------------------------------------------------------------------------
#  Alle uebrigen Updates: Void-Pakete (inkl. Kernel), Flatpaks, AppImages, Proton-GE.
#  Ausgeloest wird alles nur ueber Einstellungen → Updates (ein Auftrag, siehe Jobs._update_all).
#  Updates im Terminal (sudo xbps-install -Su) werden am Paketstand erkannt.
# ---------------------------------------------------------------------------
SYS_LOCK = threading.Lock()                 # Pruefung und Auftraege nie gleichzeitig (xbps-Sperre)
XBPS_DB = Path("/var/db/xbps")
PKG_LINE = re.compile(r"^(\S+)-([^-\s]+_\d+)\s+(install|update|remove|reinstall|configure|download|hold)\b")
KERNEL_PKG = re.compile(r"^linux(\d+\.\d+)?$")
_SCACHE: dict[str, Any] = {"t": 0.0, "pkgs": [], "flatpak": [], "appimage": [], "proton": None, "error": None,
           "db": None, "retry": 0.0}
BOOT_BUILD = None                           # VoidStation-Stand beim Start der Oberflaeche (main)
SYS_STAMP = BASE / "sysupdate.json"         # {"current": <Zeitpunkt, an dem zuletzt keine Void-Pakete ausstanden>}


def sysupd_days(s=None):
    d = (s or settings_load()).get("sysupd_days")
    return d if d in SYSUPD_DAYS else DEFAULTS["sysupd_days"]


def sys_current_since():
    """Seit wann gelten die Systemupdates als offen? Fehlt der Wert (Geraete vor 0.9.0),
    beginnt die Frist jetzt – kein Hinweis direkt nach dem Update auf 0.9.0."""
    try:
        return float(json.loads(SYS_STAMP.read_text())["current"])
    except (OSError, ValueError, KeyError, TypeError):
        sys_mark_current()
        return time.time()


def sys_mark_current():
    try:
        SYS_STAMP.write_text(json.dumps({"current": time.time()}))
    except OSError as e:
        log("sysupdate.json:", e)


def xbps_busy():
    """Laeuft xbps gerade (z. B. im Terminal)?"""
    r = run(["pgrep", "-x", "xbps-install|xbps-remove|xbps-reconfigure"])
    return bool(r and r.returncode == 0 and r.stdout.strip())


def pkgdb_stamp():
    try:
        return max((p.stat().st_mtime for p in XBPS_DB.glob("pkgdb-*.plist")), default=None)
    except OSError:
        return None


def vkey(v):
    return [int(x) for x in re.findall(r"\d+", v)]


def boot_time():
    """Startzeitpunkt (Unix-Zeit) aus /proc/stat."""
    try:
        for line in Path("/proc/stat").read_text().splitlines():
            if line.startswith("btime "):
                return int(line.split()[1])
    except (OSError, ValueError):
        pass
    return 0


def reboot_needed():
    """kernel: seit dem Start ist ein neuerer Kernel dazugekommen (ein Neustart nimmt ihn);
    kernel_stuck: ein neuerer Kernel war schon vor dem Start da und laeuft trotzdem nicht – ein Neustart
    hilft dann nicht, also kein Dauerhinweis "Neustart noetig" ({"version", "running"} oder None);
    voidstation: Oberflaeche seit dem Start aktualisiert.
    Als Kernel zaehlt nur, was Module UND /boot/vmlinuz-<version> hat (Reste in /usr/lib/modules nicht)."""
    out: dict[str, Any] = {"kernel": False, "kernel_stuck": None, "voidstation": False}
    if LIVE:
        return out
    running = os.uname().release
    try:
        ks = [d.name for d in Path("/usr/lib/modules").iterdir()
              if d.is_dir() and Path(f"/boot/vmlinuz-{d.name}").is_file()]
    except OSError:
        ks = []
    ks.sort(key=vkey)
    if ks and vkey(ks[-1]) > vkey(running):
        new = ks[-1]
        stamps = []
        for p in (Path("/usr/lib/modules") / new, Path(f"/boot/initramfs-{new}.img")):
            try:
                stamps.append(p.stat().st_mtime)   # beim Einrichten des Kernels geschrieben (depmod, dracut)
            except OSError:
                pass
        bt = boot_time()
        if stamps and bt and max(stamps) < bt:
            out["kernel_stuck"] = {"version": re.sub(r"_\d+$", "", new), "running": re.sub(r"_\d+$", "", running)}
        else:
            out["kernel"] = True
    build = vs_version().get("build")
    out["voidstation"] = bool(BOOT_BUILD and build and build != BOOT_BUILD)
    return out


def asset_stamp(headers):
    return headers.get("ETag") or f'{headers.get("Last-Modified", "")}|{headers.get("Content-Length", "")}'


def appimage_stampfile(a):
    return APPDIR / f".{a['id']}.stamp"


_AI_URL: dict = {}                                     # App -> (Zeitpunkt, Ausgabe: Adresse, Vergleichswert, SHA256)


def _http_get(url, timeout=20, head=False):
    """Antwort einer Anfrage (HEAD: nur Kopf) – liefert (endgueltige Adresse nach Weiterleitungen, Inhalt bzw. b"")."""
    req = urllib.request.Request(url, headers=UA, method="HEAD" if head else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.geturl(), (b"" if head else r.read(8 << 20))


def _url_exists(url):
    try:
        _http_get(url, head=True)
        return True
    except urllib.error.HTTPError as e:
        if e.code in (403, 404, 410):
            return False
        raise


def _deb_version_key(v):
    """Sortierschluessel fuer Debian-Versionen wie "1:1.2.95.453.g0eeebbed" (Epoche, dann Zahlenfolge)."""
    epoch, _, rest = v.partition(":") if ":" in v else ("0", "", v)
    return (int(epoch) if epoch.isdigit() else 0, [int(x) if x.isdigit() else -1 for x in re.split(r"[.+~-]", rest)])


def app_release(a):
    """Neueste Ausgabe einer App, die VoidStation selbst herunterlaedt und unter apps/<id> entpackt (Katalog-Quelle
    "appimage" – AppImage, ZIP, Tarball oder .deb). Ergebnis: {"url", "stamp" (Vergleichswert fuer die Update-Pruefung),
    "sha256" (oder None)}. Woher die Adresse kommt, steht in der Quelle:
      "url"      feste Adresse (DuckStation: Tag "latest"); Vergleichswert aus ETag/Last-Modified/Groesse
      "gh"       GitHub "besitzer/repo": /releases/latest leitet auf /releases/tag/<tag> um (ohne API, keine
                 Anfragegrenze); "assets" = Dateinamen-Muster mit {tag} und {ver} (Tag ohne fuehrendes v), es gilt
                 das erste, das es gibt
      "api"      JSON der neuesten Ausgabe (Forgejo/Gitea wie librewolf.dev, GitLab-Permalink); "pick" = Muster fuer
                 Dateiname bzw. Adresse
      "ver"      {"url", "json": Schluessel | "re": Muster} liefert die Versionsnummer, "dl" = Adresse mit {ver}
      "deb"      {"index": Packages-Datei, "pkg": Paketname, "base": Repo-Adresse} – mit SHA256 aus dem Index"""
    s = a["source"]
    if s.get("url"):
        return {"url": s["url"], "stamp": None, "sha256": None}
    hit = _AI_URL.get(a["id"])
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    rel = None
    if s.get("gh"):
        page = f"https://github.com/{s['gh']}/releases/latest"
        final, _ = _http_get(page, head=True)
        m = re.search(r"/releases/tag/([^/?#]+)/?$", final)
        if not m:
            raise RuntimeError(f"{a['name']}: keine Ausgabe auf GitHub gefunden")
        tag = urllib.parse.unquote(m.group(1))
        ver = tag[1:] if tag[:1] in "vV" and tag[1:2].isdigit() else tag
        base = f"https://github.com/{s['gh']}/releases/download/{urllib.parse.quote(tag)}/"
        for tpl in s.get("assets", []):
            url = base + urllib.parse.quote(tpl.format(tag=tag, ver=ver))
            if _url_exists(url):
                rel = {"url": url, "stamp": url, "sha256": None}
                break
        if not rel:
            raise RuntimeError(f"{a['name']}: keine passende Datei in {tag}")
    elif s.get("api"):
        _, body = _http_get(s["api"])
        assets = json.loads(body).get("assets") or []
        if isinstance(assets, dict):                   # GitLab: {"links": [...], "sources": [...]}
            assets = assets.get("links") or []
        pick = re.compile(s.get("pick", r"x86_64.*\.AppImage$"), re.I)
        for it in assets:
            url = it.get("browser_download_url") or it.get("direct_asset_url") or it.get("url") or ""
            name = it.get("name") or url.rsplit("/", 1)[-1]
            if url.startswith("https://") and (pick.search(name) or pick.search(url)):
                rel = {"url": url, "stamp": url, "sha256": None}
                break
        if not rel:
            raise RuntimeError(f"{a['name']}: keine passende Datei in der neuesten Ausgabe")
    elif s.get("ver"):
        v = s["ver"]
        _, body = _http_get(v["url"])
        txt = body.decode("utf-8", "replace")
        if v.get("json"):
            ver = str(json.loads(txt)[v["json"]])
        else:
            m = re.search(v.get("re", r"([0-9][0-9A-Za-z.+_-]*)"), txt)
            ver = m.group(1) if m else ""
        if not re.fullmatch(r"[0-9A-Za-z.+_-]{1,40}", ver):
            raise RuntimeError(f"{a['name']}: Versionsnummer nicht lesbar")
        url = s["dl"].format(ver=ver)
        rel = {"url": url, "stamp": url, "sha256": None}
    elif s.get("deb"):
        d = s["deb"]
        _, body = _http_get(d["index"])
        best = None
        for block in body.decode("utf-8", "replace").split("\n\n"):
            f = dict(re.findall(r"^([A-Za-z0-9-]+):\s*(.*)$", block, re.M))
            if f.get("Package") == d["pkg"] and f.get("Filename"):
                if not best or _deb_version_key(f.get("Version", "")) > _deb_version_key(best.get("Version", "")):
                    best = f
        if not best:
            raise RuntimeError(f"{a['name']}: {d['pkg']} nicht im Paketindex")
        url = d["base"].rstrip("/") + "/" + best["Filename"].lstrip("/")
        rel = {"url": url, "stamp": url, "sha256": (best.get("SHA256") or "").lower() or None}
    else:
        raise RuntimeError(f"{a['name']}: keine Download-Quelle im Katalog")
    _AI_URL[a["id"]] = (time.time(), rel)
    return rel


def appimage_url(a):
    return app_release(a)["url"]


def archive_format(a, url):
    """Art der heruntergeladenen Datei: "format" im Katalog, sonst nach der Endung."""
    f = a["source"].get("format")
    if f:
        return f
    low = urllib.parse.urlparse(url).path.lower()
    if low.endswith(".zip"):
        return "zip"
    if low.endswith(".deb"):
        return "deb"
    if re.search(r"\.(tar(\.(gz|xz|bz2|zst))?|tgz|txz)$", low):
        return "tar"
    return "appimage"


def appimage_outdated(a):
    if a["source"].get("self_update"):                 # aktualisiert sich selbst (Discord: Client in ~/.config/discord)
        return False
    try:
        if a["source"].get("url"):                     # feste Adresse: Vergleich ueber ETag/Last-Modified/Groesse
            req = urllib.request.Request(a["source"]["url"], headers=UA, method="HEAD")
            with urllib.request.urlopen(req, timeout=20) as r:
                remote = asset_stamp(r.headers)
        else:                                          # sonst enthaelt die Adresse die Version
            remote = app_release(a)["stamp"]
    except Exception:  # noqa: BLE001
        return False
    try:
        local = appimage_stampfile(a).read_text().strip()
    except OSError:
        local = None                                   # vor 0.9.0 installiert: einmal neu laden
    return remote != local


def rm_path(p):
    """Ordner, Datei oder (auch kaputten) Link entfernen – rmtree allein laesst Links stehen."""
    if p.is_symlink() or p.is_file():
        p.unlink(missing_ok=True)
    elif p.exists():
        shutil.rmtree(p, ignore_errors=True)


def _safe_member(work, name):
    """Ziel eines Archiv-Eintrags – nur innerhalb des Entpack-Ordners."""
    dest = (work / name).resolve()
    if dest != work.resolve() and work.resolve() not in dest.parents:
        raise RuntimeError(f"ungültiger Pfad im Archiv: {name}")
    return dest


def _extract_zip(path, work):
    """ZIP mit Ausfuehrungsrechten und symbolischen Links entpacken (zipfile allein verliert beides);
    setuid/setgid fallen weg (Brave: chrome-sandbox – Chromium nimmt dann die Namensraum-Sandbox)."""
    import zipfile
    with zipfile.ZipFile(path) as z:
        for i in z.infolist():
            mode = (i.external_attr >> 16) & 0o177777
            dest = _safe_member(work, i.filename)
            if i.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            if (mode & 0o170000) == 0o120000:          # symbolischer Link – nur innerhalb des Archivs
                target = z.read(i).decode("utf-8")
                if target.startswith("/") or work.resolve() not in (dest.parent / target).resolve().parents:
                    continue
                dest.unlink(missing_ok=True)
                os.symlink(target, dest)
                continue
            with z.open(i) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)
            os.chmod(dest, (mode & 0o777) or 0o644)


def _extract_tar(fileobj_or_path, work, stream=False):
    kw = {"fileobj": fileobj_or_path, "mode": "r|*"} if stream else {"name": str(fileobj_or_path), "mode": "r:*"}
    with tarfile.open(**kw) as t:
        try:
            t.extractall(work, filter="data")          # keine absoluten Pfade, kein setuid, Links nur nach innen
        except TypeError:                              # aelteres Python ohne Filter
            t.extractall(work)


def _extract_deb(path, work):
    """.deb = ar-Archiv: debian-binary, control.tar.*, data.tar.* – entpackt wird nur data.tar.* (ohne binutils)."""
    with open(path, "rb") as f:
        if f.read(8) != b"!<arch>\n":
            raise RuntimeError("kein .deb-Paket")
        while True:
            hdr = f.read(60)
            if len(hdr) < 60:
                break
            name = hdr[:16].decode("ascii", "replace").strip().rstrip("/")
            size = int(hdr[48:58].decode("ascii").strip())
            if name.startswith("data.tar"):
                part = path.with_name(path.name + "." + name)
                with open(part, "wb") as out:
                    left = size
                    while left:
                        chunk = f.read(min(left, 1 << 20))
                        if not chunk:
                            raise RuntimeError(".deb unvollständig")
                        out.write(chunk)
                        left -= len(chunk)
                try:
                    if name.endswith(".zst"):          # Pythons tarfile kann (noch) kein zstd
                        p = subprocess.Popen(["zstd", "-dcq", str(part)], stdout=subprocess.PIPE)
                        assert p.stdout is not None
                        try:
                            _extract_tar(p.stdout, work, stream=True)
                        finally:
                            p.stdout.close()
                            if p.wait() != 0:
                                raise RuntimeError("zstd fehlgeschlagen")
                    else:
                        _extract_tar(part, work)
                finally:
                    part.unlink(missing_ok=True)
                return
            f.seek(size + (size & 1), 1)
    raise RuntimeError("data.tar fehlt im .deb")


def extract_app(path, fmt, work, strip=0):
    """Heruntergeladene Datei nach work entpacken; Rueckgabe: Wurzelordner des Programms."""
    if fmt == "appimage":
        path.chmod(0o755)
        subprocess.run([str(path), "--appimage-extract"], cwd=str(work),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=900)
        # Neuere AppImage-Startteile (Mission Center) entpacken nach AppDir/ und legen squashfs-root nur als Link
        # darauf an – dann zaehlt der Ordner, auf den er zeigt (der Link selbst waere nach dem Verschieben kaputt)
        root = work / "squashfs-root"
        if not root.exists() and (work / "AppDir").is_dir():
            root = work / "AppDir"
        if root.is_symlink():
            root = root.resolve()
            if root.parent != work.resolve() or not root.is_dir():
                raise RuntimeError("AppImage entpackt an einen unerwarteten Ort")
        if not (root / "AppRun").exists():
            raise RuntimeError("AppImage ließ sich nicht entpacken")
        return root
    root = work / "root"
    root.mkdir()
    if fmt == "zip":
        _extract_zip(path, root)
    elif fmt == "tar":
        _extract_tar(path, root)
    elif fmt == "deb":
        _extract_deb(path, root)
    else:
        raise RuntimeError(f"unbekanntes Format {fmt}")
    for _ in range(strip):                             # z. B. Discord: alles steckt in "Discord/"
        inner = [x for x in root.iterdir()]
        if len(inner) != 1 or not inner[0].is_dir():
            raise RuntimeError("Archiv hat nicht den erwarteten Aufbau")
        inner[0].rename(work / "inner")
        root.rmdir()
        (work / "inner").rename(root)
    return root


def app_launcher(root, a):
    """Startskript AppRun fuer entpackte ZIP/Tarball/.deb-Programme: startet die Datei aus "run" (die erste, die es
    gibt) – fuer Chromium/Electron mit --no-sandbox nur dann, wenn der Kernel keine Benutzer-Namensraeume erlaubt
    (setuid-Helfer kann ein Download nicht haben). "links" legt symbolische Links an (Spotify: libcurl-gnutls)."""
    s = a["source"]
    runs = s["run"] if isinstance(s.get("run"), list) else [s.get("run")]
    exe = next((r for r in runs if r and (root / r).is_file()), None)
    if not exe:
        raise RuntimeError(f"Programmdatei fehlt im Archiv ({', '.join(r for r in runs if r)})")
    (root / exe).chmod((root / exe).stat().st_mode | 0o755)
    for rel, target in (s.get("links") or {}).items():
        lp = _safe_member(root, rel)
        lp.parent.mkdir(parents=True, exist_ok=True)
        if not lp.exists() and not lp.is_symlink():
            os.symlink(target, lp)
    sandbox = ('NS=\nunshare -Ur true 2>/dev/null || NS=--no-sandbox\n' if s.get("chromium") else "")
    shell = "sh " if s.get("shell") else ""           # Startskript ohne #!-Zeile (Discord)
    script = ("#!/bin/sh\n# von VoidStation angelegt – startet " + a["name"] + "\n"
              'HERE=$(dirname "$(readlink -f "$0")")\n' + sandbox +
              f'exec {shell}"$HERE/{exe}"' + (" $NS" if sandbox else "") + ' "$@"\n')
    (root / "AppRun").write_text(script)
    (root / "AppRun").chmod(0o755)


def json_merge(path, values):
    """Schluessel in eine JSON-Datei schreiben, Rest bleibt (legt die Datei bei Bedarf an)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    if all(data.get(k) == v for k, v in values.items()):
        return
    data.update(values)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".vs-tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def _sys_check(sync, logf=None):
    """Sucht nach Updates ausser VoidStation selbst. Nur mit SYS_LOCK aufrufen!
    sync=False: nur Void-Pakete gegen die vorhandenen Paketlisten (schnell, ohne Netz)."""
    if LIVE:
        return
    res: dict[str, Any] = {"pkgs": [], "error": None}
    # Der Helfer begrenzt das Laden der Paketlisten selbst (90 s je Versuch, dazwischen Mirror-Wahl) – sudo hier
    # abzuschiessen wuerde xbps darunter weiterlaufen lassen ("xbps beschaeftigt" beim naechsten Mal)
    r = run(["sudo", "-n", PKG_HELPER, "check"] + ([] if sync else ["--nosync"]), timeout=240)
    if r is None:
        res["error"] = "xbps antwortet nicht"
    else:
        for line in r.stdout.splitlines():
            m = PKG_LINE.match(line.strip())
            if m:
                res["pkgs"].append({"name": m[1], "version": m[2], "action": m[3]})
        if r.returncode != 0 and not res["pkgs"]:
            res["error"] = ((r.stdout + r.stderr).strip().splitlines() or [f"Fehler {r.returncode}"])[-1][:200]
    if logf:
        logf(f"Void-Pakete: {len(res['pkgs'])}" + (f" ({res['error']})" if res["error"] else ""))
    if sync:
        res.update(flatpak=[], appimage=[], proton=None)
        if shutil_which("flatpak"):
            f = run(["flatpak", "remote-ls", "--user", "--updates", "--columns=application"], timeout=45)
            if f and f.returncode == 0:
                res["flatpak"] = [x.strip() for x in f.stdout.splitlines() if x.strip()]
        apps = catalog()["apps"]
        for a in apps:
            if a["source"]["type"] == "mullvad":
                if VPN.outdated():
                    res["appimage"].append(a["id"])
                continue
            if a["source"]["type"] == "xbps" and a["source"].get("was_appimage") and legacy_appimage(a):
                res["appimage"].append(a["id"])       # Wechsel AppImage -> Paket (eigene Paketquelle) beim Update
                if logf:
                    logf(f"{a['name']}: Wechsel von der entpackten Fassung auf das Paket steht an")
                continue
            if a["source"]["type"] != "appimage":
                continue
            if (APPDIR / a["id"] / "AppRun").exists():
                if appimage_outdated(a):
                    res["appimage"].append(a["id"])
            elif legacy_flatpak(a):                    # noch das Flatpak: Wechsel auf die entpackte Fassung beim Update
                res["appimage"].append(a["id"])
                if logf:
                    logf(f"{a['name']}: Wechsel vom Flatpak auf die entpackte Fassung steht an")
        if any("proton-ge" in a["source"].get("addons", []) and app_installed(a) for a in apps):
            try:
                tag = proton_latest()["tag_name"]
                if tag not in proton_installed():
                    res["proton"] = tag
            except Exception as e:  # noqa: BLE001
                if logf:
                    logf(f"Proton-GE: {e}")
        if logf:
            logf(f"Flatpak: {len(res['flatpak'])}, AppImages: {len(res['appimage'])}, Proton-GE: {res['proton'] or 'aktuell'}")
        res["t"] = time.time()
    res["db"] = pkgdb_stamp()
    _SCACHE.update(res)
    if not res["pkgs"] and not res["error"]:
        sys_mark_current()                         # alles aktuell (auch nach Update im Terminal): Frist beginnt neu


_SYS_BG = {"running": False}
_SYS_BG_LOCK = threading.Lock()


def sys_check_background():
    """Pruefung mit frischen Paketlisten im Hintergrund starten (Einstellungen → Updates). Die Oberflaeche wartet
    nicht darauf: Sie zeigt sofort den bekannten Stand und fragt nach, bis "checking" weg ist."""
    with _SYS_BG_LOCK:
        if _SYS_BG["running"]:
            return
        _SYS_BG["running"] = True

    def _go():
        try:
            sys_check(sync=True)
        except Exception as e:  # noqa: BLE001
            log("Paketpruefung fehlgeschlagen:", e)
        finally:
            _SYS_BG["running"] = False
    threading.Thread(target=_go, daemon=True).start()


def sys_check(sync):
    """Pruefung von aussen (Hintergrund, Einstellungen); False = gerade nicht moeglich."""
    if LIVE or JOBS.busy() or xbps_busy() or not SYS_LOCK.acquire(blocking=False):
        return False
    try:
        _sys_check(sync)
        return True
    finally:
        SYS_LOCK.release()


def _sys_recheck():
    if not sys_check(sync=False):
        _SCACHE["retry"] = time.time()             # xbps laeuft noch: spaeter erneut


def sys_state():
    """Stand aus dem Zwischenspeicher. Hat sich der Paketstand geaendert (Update/Installation im
    Terminal), wird kurz ohne Netz neu geprueft – so verschwinden erledigte Updates von selbst."""
    if (not LIVE and _SCACHE["t"] and pkgdb_stamp() != _SCACHE["db"]
            and time.time() - _SCACHE["retry"] > 10 and not JOBS.busy()):
        _SCACHE["retry"] = time.time()
        threading.Thread(target=_sys_recheck, daemon=True).start()
    pkgs = _SCACHE["pkgs"]
    kernel = next((p["version"] for p in pkgs if KERNEL_PKG.match(p["name"])), None)
    names = {a["id"]: a["name"] for a in catalog()["apps"]} if _SCACHE["appimage"] else {}
    count = len(pkgs) + len(_SCACHE["flatpak"]) + len(_SCACHE["appimage"]) + (1 if _SCACHE["proton"] else 0)
    days = sysupd_days()
    due_at = sys_current_since() + days * 86400 if pkgs else None
    return {"pkgs": [p["name"] for p in pkgs], "kernel": kernel, "flatpak": len(_SCACHE["flatpak"]),
            "appimage": [names.get(i, i) for i in _SCACHE["appimage"]], "proton": _SCACHE["proton"],
            "count": count, "error": _SCACHE["error"], "checked": _SCACHE["t"] or None,
            "checking": _SYS_BG["running"] or (SYS_LOCK.locked() and not JOBS.busy()),   # auch die 6-h-Pruefung
            "days": days, "due_at": due_at, "due": bool(due_at and time.time() >= due_at)}


def updates_state(force=False):
    """Gesamtstand fuer Einstellungen → Updates: VoidStation + System + Neustart.
    force: VoidStation-Stand jetzt holen (ein kleiner Abruf) und die Paketpruefung im Hintergrund anstossen –
    die Antwort wartet nicht auf xbps (frueher bis zu 5 Minuten, wenn ein Mirror hing); system.checking zeigt,
    dass die Pruefung noch laeuft."""
    vs = vs_update_status(force)          # ohne force: nur, wenn der letzte Stand aelter als 10 min ist
    busy = False
    if force and not LIVE:
        if JOBS.busy() or xbps_busy():
            busy = True
        else:
            sys_check_background()
    sysst = sys_state()
    return {**vs, "system": sysst, "reboot": reboot_needed(), "busy": busy,
            "any": bool(vs["available"] or sysst["count"]), "notify": bool(vs["available"] or sysst["due"])}


def updates_badge():
    """Kurzfassung fuer /api/status (Hinweis unten rechts). Neue VoidStation-Versionen sofort,
    reine Systemupdates erst, wenn die eingestellte Frist (30/60/90 Tage) abgelaufen ist."""
    vs, sysst, rb = vs_state(), sys_state(), reboot_needed()
    return {"available": bool(vs["available"] or sysst["due"]), "version": vs["remote"] if vs["available"] else None,
            "system": sysst["count"] if sysst["due"] else 0, "reboot": rb["kernel"] or rb["voidstation"]}


def updates_background_check():
    """Prueft kurz nach dem Start und dann alle 6 Stunden auf Updates (alle Arten)."""
    time.sleep(90)
    while True:
        wait = 6 * 3600
        try:
            st = vs_update_status(force=True)
            ok = sys_check(sync=True)
            if not ok:
                wait = 600                             # Auftrag oder xbps im Terminal: in 10 min nochmal
            log("Update-Pruefung: VoidStation", "verfuegbar " + str(st["remote"]) if st["available"] else "aktuell",
                f"(Kanal {st['channel']})", st["error"] or "",
                "| System:", sys_state()["count"] if ok else "uebersprungen (xbps/Auftrag laeuft)")
        except Exception as e:  # noqa: BLE001
            log("Update-Pruefung fehlgeschlagen:", e)
        time.sleep(wait)


def kernel_autopurge():
    """Alte Kernel automatisch entfernen, sobald das System mit dem neuesten Kernel fehlerfrei laeuft:
    die Oberflaeche ist seit 10 Minuten oben und es laeuft der neueste installierte Kernel.
    Einmal je Start der Oberflaeche; laeuft gerade ein Auftrag oder xbps, spaeter nochmal."""
    time.sleep(600)
    for _ in range(12):
        try:
            rb = reboot_needed()
            if rb["kernel"] or rb["kernel_stuck"]:
                return                                 # neuester Kernel laeuft (noch) nicht: nichts anfassen
            ks = [d.name for d in Path("/usr/lib/modules").iterdir()
                  if d.is_dir() and Path(f"/boot/vmlinuz-{d.name}").is_file()]
            if len(ks) < 2:
                return
            if JOBS.busy() or xbps_busy() or not SYS_LOCK.acquire(timeout=5):
                time.sleep(600)
                continue
            try:
                r = run(["sudo", "-n", PKG_HELPER, "kernelpurge"], timeout=600)
            finally:
                SYS_LOCK.release()
            out = ((r.stdout or "") + (r.stderr or "")).strip() if r else "kein Ergebnis"
            log("Alte Kernel:", out.replace("\n", " | "))
            if r and r.returncode == 0:
                return
        except Exception as e:  # noqa: BLE001
            log("Alte Kernel entfernen fehlgeschlagen:", e)
        time.sleep(600)


def shutil_which(name):
    return shutil.which(name)


JOBS = Jobs()


# ---------------------------------------------------------------------------
#  Programme, die ausserhalb des AppCenters installiert wurden (z. B. per xbps-install im Terminal):
#  werden ueber ihre .desktop-Dateien gefunden und lassen sich als Kachel anlegen
# ---------------------------------------------------------------------------
DESKTOP_DIRS = [Path("/usr/share/applications"), Path("/usr/local/share/applications"),
                Path("/var/lib/flatpak/exports/share/applications"),
                Path.home() / ".local/share/flatpak/exports/share/applications",
                Path.home() / ".local/share/applications"]
# Teile des Systems, die keine eigene Kachel brauchen
LOCAL_SKIP = {"openbox", "obconf", "xterm", "uxterm", "pcmanfm-desktop-pref", "libfm-pref-apps", "lxshortcut",
              "gparted", "voidstation", "org.gnome.zenity", "mpv", "vlc", "firefox", "nm-connection-editor",
              "pavucontrol", "xdg-desktop-portal-gtk", "gcr-prompter", "gcr-viewer", "org.gnome.gcr",
              "display-im6.q16", "cups", "htop", "nano", "mousepad", "fastfetch", "pcmanfm", "flatpak",
              "org.freedesktop.impl.portal"}
FIELD_CODES = re.compile(r"%[fFuUdDnNickvm]")
LOCAL_ICONS = [("Game", "gamepad"), ("Emulator", "gamepad"), ("Audio", "music"), ("Video", "film"), ("AudioVideo", "film"),
               ("Graphics", "image"), ("Photography", "image"), ("WebBrowser", "globe"), ("Network", "globe"),
               ("Office", "chart"), ("Education", "store"), ("Development", "terminal"), ("System", "terminal"), ("FileManager", "folder"), ("Utility", "store")]


def _desktop_entry(path):
    try:
        txt = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    e: dict
    sect: str | None
    e, sect = {}, None
    for line in txt.splitlines():
        line = line.strip()
        if line.startswith("["):
            sect = line
            continue
        if sect == "[Desktop Entry]" and "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            e.setdefault(k.strip(), v.strip())
    return e


def _bin_key(path):
    """Vergleichsschluessel fuer Programme: der Dateiname – ausser bei entpackten AppImages, die alle "AppRun"
    heissen; dort zaehlt der ganze Pfad (sonst verschwindet jedes selbst entpackte AppImage aus der Liste)."""
    p = os.path.expanduser(str(path))
    return p if Path(p).name == "AppRun" else Path(p).name


def local_apps():
    """Programme mit .desktop-Datei, die weder im Katalog noch als eigene Kachel vorkommen."""
    lang = ui_lang().replace("-", "_")               # .desktop-Schluessel: Name[pt_BR], Name[fr]
    cat = catalog()
    known_bins = {_bin_key(a["cmd"][0]) for a in cat["apps"] if isinstance(a.get("cmd"), list) and a["cmd"]}
    known_bins |= {a["source"].get("pkg") for a in cat["apps"] if a["source"].get("pkg")}
    for a in cat["apps"]:                            # "for b in A B; do …" -> A und B
        m = re.match(r"for b in ([^;]+);", a.get("cmd")) if isinstance(a.get("cmd"), str) else None
        known_bins |= set(m.group(1).split()) if m else set()
    known_bins.discard("flatpak")                    # Flatpaks werden ueber ihre ID erkannt, nicht ueber "flatpak run"
    known_refs = {r for a in cat["apps"] for r in (a["source"].get("ref"), a["source"].get("was_flatpak")) if r}
    tiles = {t.get("id"): t for g in load_config().get("groups", []) for t in g.get("tiles", [])}
    tile_bins = {_bin_key(t["cmd"][0]) for t in tiles.values() if isinstance(t.get("cmd"), list) and t["cmd"]}
    out, seen = [], set()
    for d in DESKTOP_DIRS:
        for f in sorted(d.glob("*.desktop")) if d.is_dir() else []:
            stem = f.stem
            if stem in seen or stem.lower() in LOCAL_SKIP or stem.startswith(("org.gnome.Settings", "vim", "nvim")):
                continue
            e = _desktop_entry(f)
            if not e or e.get("Type") != "Application" or e.get("NoDisplay") == "true" or e.get("Hidden") == "true":
                continue
            if e.get("OnlyShowIn") or not e.get("Exec") or not e.get("Name"):
                continue
            try:
                args = [a for a in shlex.split(FIELD_CODES.sub("", e["Exec"])) if a]
            except ValueError:
                continue
            if not args or args[0] == "env" and len(args) < 2:
                continue
            binary = _bin_key(args[0])
            if e.get("TryExec") and not shutil.which(e["TryExec"]):
                continue
            if not (shutil.which(args[0]) or Path(args[0]).exists()):
                continue
            aid = "desk-" + re.sub(r"[^A-Za-z0-9_.-]", "_", stem)
            if stem in known_refs or (binary == "flatpak" and known_refs & set(args)):
                continue                              # Flatpak aus dem Katalog
            if aid not in tiles and (binary in known_bins or binary in tile_bins):
                continue                              # schon als Katalog-App oder Standard-Kachel vorhanden
            seen.add(stem)
            if e.get("Terminal") == "true":
                args = ["xterm", "-e"] + args          # Schrift/Farben: ~/.Xresources (apply_appearance)
            cats = e.get("Categories", "")
            icon = next((i for k, i in LOCAL_ICONS if k in cats.split(";")), "globe")
            loc = lambda k: e.get(f"{k}[{lang}]") or e.get(f"{k}[{lang.split('_')[0]}]")   # pt_BR, sonst pt
            name = loc("Name") or e["Name"]
            desc = loc("Comment") or e.get("Comment") or loc("GenericName") or e.get("GenericName") or ""
            out.append({"id": aid, "name": name, "desc": desc, "cmd": args, "icon": icon, "tile": aid in tiles,
                        "game": "Game" in cats})
    return sorted(out, key=lambda a: a["name"].lower())


def local_tile(aid, on):
    a = next((x for x in local_apps() if x["id"] == aid), None)
    if not a:
        raise RuntimeError("Programm nicht gefunden")
    if not on:
        tile_remove(aid)
        return
    palette = ["#2f3d57", "#3b2f4f", "#284843", "#4a3a2a", "#2d3763", "#453040"]
    tile_add({"id": aid, "name": a["name"], "cmd": a["cmd"], "source": {"type": "local"},
              "tile": {"group": "Spiele" if a["game"] else "Programme", "size": "medium", "icon": a["icon"],
                       "color": palette[sum(map(ord, aid)) % len(palette)]}})


LOCAL_CAT = "Auf diesem Gerät"     # ausserhalb des AppCenters installiert – erscheint nur unter "Installiert"


def apps_payload():
    """AppCenter-Daten: Kategorien in Katalog-Reihenfolge, alle Apps mit Stand. Die Seitenleiste
    ("Installiert" + Kategorien) baut die Oberflaeche selbst daraus."""
    cat = catalog()
    pkgs, fps = installed_sets()
    tiles = tile_ids()
    apps = []
    for a in cat["apps"]:
        item = {k: a[k] for k in ("id", "name", "desc", "cat")}
        item["type"] = a["source"]["type"]
        if item["type"] == "appimage" and a["source"].get("run"):   # ZIP, Tarball, .deb: Beschriftung "Download"
            item["type"] = "archive"
        elif item["type"] == "mullvad":                # seit 2026.12 ein Paket aus der eigenen Paketquelle
            item["type"] = "xbps"
        item["installed"] = app_installed_in(a, pkgs, fps, tiles)
        if not item["installed"] and (a.get("retired") or not app_supported(a)):
            continue                                   # nicht mehr im Angebot bzw. nicht fuer diese Architektur (32 Bit)
        item["tile"] = a["id"] in tiles
        item["icon"] = a.get("tile", {}).get("icon", "globe")
        item["color"] = a.get("tile", {}).get("color", "#2f3238")
        apps.append(item)
    cats = list(cat["categories"])
    try:
        for a in local_apps():
            apps.append({"id": a["id"], "name": a["name"], "desc": a["desc"], "cat": LOCAL_CAT, "type": "local",
                         "installed": True, "tile": a["tile"], "icon": a["icon"], "color": "#2f3238"})
    except Exception as e:  # noqa: BLE001 – eine kaputte .desktop-Datei darf das AppCenter nicht verhindern
        log("Programme suchen:", e)
    return {"categories": cats, "local_cat": LOCAL_CAT, "apps": apps, "job": JOBS.current()}


def ssh_state():
    return Path("/var/service/sshd").exists()


def can_suspend():
    """Standby moeglich? Der Kernel muss "mem" oder "freeze" anbieten; im Live-System nie."""
    if LIVE:
        return False
    try:
        states = Path("/sys/power/state").read_text().split()
    except OSError:
        return False
    return "mem" in states or "freeze" in states


def _sysread(p):
    try:
        return Path(p).read_text().strip()
    except OSError:
        return ""


def _suspend_counts():
    """(geglueckt, abgebrochen) aus /sys/power/suspend_stats – None, wenn nicht lesbar."""
    s, f = _sysread("/sys/power/suspend_stats/success"), _sysread("/sys/power/suspend_stats/fail")
    return (int(s), int(f)) if s.isdigit() and f.isdigit() else None


def _wakeup_counts():
    """Ereigniszaehler aller Weckquellen (/sys/class/wakeup/wakeupN/event_count)."""
    out = {}
    for w in Path("/sys/class/wakeup").glob("wakeup*"):
        n = _sysread(w / "event_count")
        if n.isdigit():
            out[w.name] = int(n)
    return out


def wake_sources(before, after, irq=True):
    """Lesbarer Weckgrund aus den gestiegenen Weckzaehlern. USB-Geraete mit Produktnamen zuerst –
    Einschaltknopf (PNP0C0C) und PCI-Bruecken zaehlen bei S3 meist mit und sagen allein wenig."""
    usb, other = [], []
    for k, n in sorted(after.items()):
        if n <= before.get(k, 0):
            continue
        w = Path("/sys/class/wakeup") / k
        name = _sysread(w / "name")
        try:
            dev = (w / "device").resolve(strict=True)
        except OSError:
            dev = None
        prod = _sysread(dev / "product") if dev else ""
        if prod:
            usb.append(f"USB {name} ({' '.join(x for x in (_sysread(dev / 'manufacturer'), prod) if x)})")
        elif name and not name.startswith("device:"):
            other.append(name)
    parts = usb or other
    if irq:
        n = _sysread("/sys/power/pm_wakeup_irq")
        if n.isdigit():
            desc = ""
            try:
                for line in Path("/proc/interrupts").read_text().splitlines():
                    if line.strip().startswith(n + ":"):
                        desc = " ".join(re.sub(r"^\s*\d+:\s+(\d+\s+)*", "", line).split())
                        break
            except OSError:
                pass
            parts = parts + [f"IRQ {n}" + (f" {desc}" if desc else "")]
    return ", ".join(parts) or "unbekannt"


def resume_watcher():
    """Nach dem Standby: Aufloesung erneut setzen (manche HDMI-Ausgaenge kommen sonst mit anderem Modus zurueck –
    apply_resolution aendert nur, was abweicht) und Weckgrund bzw. Abbruch ins Protokoll schreiben.
    Erkennt das Aufwachen an /sys/power/suspend_stats (Rueckfall: CLOCK_BOOTTIME zaehlt die Schlafzeit mit,
    CLOCK_MONOTONIC nicht). Abbruch = Standby kam gar nicht zustande, z. B. Weckereignis beim Einschlafen."""
    def gap():
        return time.clock_gettime(time.CLOCK_BOOTTIME) - time.monotonic()

    def dur(sec):
        return f"{sec:.0f} s" if sec < 120 else f"{sec / 60:.1f} min"

    last_gap, last_cnt, last_wake = gap(), _suspend_counts(), _wakeup_counts()
    while True:
        time.sleep(5)
        g, cnt, wake = gap(), _suspend_counts(), _wakeup_counts()
        slept = g - last_gap
        if cnt is not None and last_cnt is not None:
            woke, failed = cnt[0] > last_cnt[0], cnt[1] > last_cnt[1]
        else:
            woke, failed = slept > 10, False
        if failed:
            st = "/sys/power/suspend_stats/"
            step, dev, err = (_sysread(st + x) for x in ("last_failed_step", "last_failed_dev", "last_failed_errno"))
            detail = ", ".join(x for x in (f"Schritt {step}" if step else "", f"Geraet {dev}" if dev else "",
                                           f"Fehler {err}" if err else "") if x)
            log(f"Standby abgebrochen ({detail or 'ohne Angabe'}) – ausgeloest von: "
                f"{wake_sources(last_wake, wake, irq=False)}")
        if woke:
            log(f"aus dem Standby zurueck (nach {dur(max(slept, 0))}) – geweckt von: {wake_sources(last_wake, wake)}")
            time.sleep(3)                               # Bildschirm und Treiber erst aufwachen lassen
            try:
                apply_display()
                DISPLAY_RATE.reapply()                  # laeuft vorn ein Video, wieder dessen Rate
            except Exception as e:  # noqa: BLE001
                log("Aufloesung nach dem Standby:", e)
            g, cnt, wake = gap(), _suspend_counts(), _wakeup_counts()
        last_gap, last_cnt, last_wake = g, cnt, wake


def settings_payload():
    s = settings_load()
    return {"version": vs_version(), "ssh": ssh_state(), "live": LIVE, "standby": can_suspend(),
            "lang": ui_lang(s), "langs": LANGS,
            "scale": s["scale"], "scales": SCALES,
            "theme": s.get("theme", "default-dark"), "themes": available_themes(),
            "cursor": {"theme": s.get("cursor_theme"), "size": s.get("cursor_size"),
                       "themes": [{"id": t, "label": CURSOR_NAMES[t]} for t in cursor_themes()],
                       "sizes": CURSOR_SIZES}, "displays": xrandr_info(),
            "audio": audio_info(), "volume": volume_get(), "net": net_info(), "share": share_info(),
            "sysupd_days": sysupd_days(s), "sysupd_choices": SYSUPD_DAYS, "music_volume": music_volume(),
            "padmouse": bool(s.get("padmouse", True)),
            "rate": s.get("rate"), "match_rate": bool(s.get("match_rate")), "region": region(s),
            "game_fx": game_fx_state(s),
            "osk": {"choice": s.get("osk_layout") if s.get("osk_layout") in OSK_LAYOUTS else "auto",
                    "mode": s.get("osk_mode") if s.get("osk_mode") in OSK_MODES else "auto"}}


# ---------------------------------------------------------------------------
#  Live-System und Installer (voidstation-installer laeuft als root per sudo)
# ---------------------------------------------------------------------------
LIVE = Path("/etc/voidstation-live").exists()
INSTALLER = "/usr/local/sbin/voidstation-installer"


def cmdline_flag(name):
    try:
        return name in Path("/proc/cmdline").read_text().split()
    except OSError:
        return False


class Installer:
    """Startet den Installer, liest seine JSON-Zeilen und haelt den Stand fuer die Oberflaeche bereit."""

    def __init__(self):
        self.lock = threading.RLock()                   # start() ruft status() unter derselben Sperre auf
        self.proc = None
        self.state: Any = None
        self.autostart = LIVE and cmdline_flag("voidstation.install")
        self.probe_cache = None

    def _root(self, args, timeout=180, stdin=None):
        return subprocess.run(["sudo", "-n", INSTALLER] + args, input=stdin, capture_output=True, text=True, timeout=timeout)

    def probe(self, force=False):
        if self.probe_cache and not force:
            return self.probe_cache
        r = self._root(["probe"])
        if r.returncode != 0:
            raise RuntimeError((r.stdout + r.stderr).strip()[-300:] or "probe fehlgeschlagen")
        p = json.loads(r.stdout)
        disp = xrandr_info()
        p["screen"] = {"name": disp[0]["name"], "mode": disp[0]["current"], "rate": disp[0].get("rate")} if disp else None
        p["favs"] = {"radio": len(favs_load()), "tv": len(tvfavs_load())}
        p["live_home"] = str(Path.home())
        lang = ui_lang()
        p["lang"] = lang
        p["langs"] = [{"id": i, "label": n, "kb": INSTALL_DEFAULTS[i][0], "tz": INSTALL_DEFAULTS[i][1]} for i, n, _, _ in LANG_TABLE]
        p["kbs"] = list(KEYMAPS)
        kb = cmdline_value("voidstation.kb")              # Tastatur aus dem Startmenue des Sticks
        if kb not in KEYMAPS:
            kb = {"us": "us", "gb": "gb", "de": "de"}.get(x_keyboard_layout() or "", INSTALL_DEFAULTS.get(lang, ("de",))[0])
        p["kb"] = kb
        self.probe_cache = p
        return p

    def running(self):
        return bool(self.proc and self.proc.poll() is None)

    def start(self, cfg=None, resume=False, alt=False):
        with self.lock:
            if self.running() or (self.state and self.state.get("detached")):
                raise RuntimeError("Installation laeuft bereits")
            args = ["run"] + (["--resume"] if resume else []) + (["--alt"] if alt else [])
            if not resume:
                cfg = dict(cfg or {})
                cfg["live_home"] = str(Path.home())
                cfg["region"] = region_for(str(cfg.get("lang") or "de"), str(cfg.get("timezone") or ""))   # Radio/TV
                self.state = {"state": "running", "pct": 0, "phase": None, "phases": {}, "detail": None,
                              "started": time.time(), "mode": cfg.get("mode")}
            else:
                self.state = dict(self.state or {"phases": {}, "started": time.time()}, state="running", error=None, detached=False)
            # eigene Sitzung: laeuft auch weiter, wenn die Startseite neu startet
            self.proc = subprocess.Popen(["sudo", "-n", INSTALLER] + args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, text=True, start_new_session=True)
            try:
                assert self.proc.stdin is not None
                self.proc.stdin.write(json.dumps(cfg) if not resume else "")
                self.proc.stdin.close()
            except OSError:
                pass
            threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()
            log("Installation gestartet", "(neuer Versuch)" if resume else "", "(Ausweichweg)" if alt else "")
            return self.status()

    def _read(self, proc):
        for line in proc.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            with self.lock:
                st = self.state
                kind = ev.get("ev")
                if kind == "progress":
                    st.update(pct=ev.get("pct", st.get("pct")), phase=ev.get("phase"),
                              phase_pct=ev.get("phase_pct"), copy={k: ev[k] for k in ("done", "total", "eta") if k in ev} or st.get("copy"),
                              detail=ev.get("detail"))
                elif kind == "phase":
                    st["phases"][ev["phase"]] = ev["state"]
                    st["phase"] = ev["phase"]
                elif kind == "error":
                    st.update(state="error", error={k: ev.get(k) for k in ("phase", "code", "msg", "done", "foreign_untouched", "log", "alt")})
                    if ev.get("phase"):
                        st["phases"][ev["phase"]] = "error"
                elif kind == "done":
                    st.update(state="done", pct=100, result=ev)
        proc.wait()
        with self.lock:
            if self.state and self.state.get("state") == "running":
                self.state.update(state="error", error={"code": "internal", "msg": f"Installer beendet (Code {proc.returncode})",
                                                        "phase": self.state.get("phase"), "done": [], "log": [], "alt": False})
        log("Installation:", self.state.get("state") if self.state else "?")

    def status(self):
        if self.proc is None and LIVE and (self.state is None or self.state.get("detached")):
            self._reattach()
        with self.lock:
            return dict(self.state or {"state": "idle"}, running=self.running() or bool(self.state and self.state.get("detached")))

    def _reattach(self):
        """Startseite wurde neu gestartet: Stand beim Installer abfragen (laeuft er noch, als 'detached')."""
        try:
            st = json.loads(self._root(["status"], timeout=20).stdout or "{}")
        except (OSError, ValueError, subprocess.SubprocessError):
            st = {}
        if not st.get("config"):
            return
        alive = subprocess.run(["pgrep", "-f", INSTALLER + " run"], capture_output=True).returncode == 0
        done = st.get("done", [])
        weights = {"check": 2, "shrink": 8, "partition": 2, "format": 3, "copy": 60, "configure": 15, "boot": 7, "cleanup": 3}
        err = st.get("error")
        state = "done" if st.get("finished") else "running" if alive else "error"
        phases = {p: "done" for p in done}
        if alive and st.get("current"):
            phases[st["current"]] = "running"
        if err and not alive:
            phases[err.get("phase")] = "error"
        cfg = st["config"]
        self.state = {
            "state": state, "detached": alive, "phases": phases, "phase": st.get("current"), "mode": cfg.get("mode"),
            "pct": 100 if st.get("finished") else round(sum(weights.get(p, 0) for p in done) / sum(weights.values()) * 100),
            "started": st.get("started"),
            "error": None if state != "error" else dict(err or {"code": "internal", "msg": "abgebrochen", "phase": st.get("current")},
                                                        done=done, log=[], alt=(err or {}).get("phase") == "boot"),
            "result": {"user": cfg.get("user", {}).get("name"), "login": cfg.get("user", {}).get("login"),
                       "hostname": cfg.get("hostname"), "seconds": int(st["finished"] - (st.get("started") or st["finished"]))}
            if st.get("finished") else None}

    def gparted(self):
        disp = os.environ.get("DISPLAY", ":0")
        xa = os.environ.get("XAUTHORITY") or str(Path.home() / ".Xauthority")
        r = self._root(["gparted", disp, xa], timeout=30)
        if r.returncode != 0:
            raise RuntimeError((r.stdout + r.stderr).strip()[-300:] or "GParted startet nicht")
        self.probe_cache = None

    @staticmethod
    def gparted_running():
        return subprocess.run(["pgrep", "-x", "gparted"], capture_output=True).returncode == 0 or \
            subprocess.run(["pgrep", "-f", "gpartedbin"], capture_output=True).returncode == 0

    def savelog(self):
        r = self._root(["savelog"], timeout=60)
        try:
            return json.loads(r.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return {"ok": False, "code": "no_usb"}

    def log_text(self):
        return self._root(["log"], timeout=20).stdout


INSTALL = Installer()
# Tastaturen im Installer (Reihenfolge der Auswahl) -> setxkbmap; gleiche Kennungen wie voidstation.kb im Startmenue
# des Sticks und KEYMAPS in voidstation-installer. Griechisch/Russisch/Ukrainisch/Thai mit US dazu, Alt+Umschalt wechselt.
_GRP = ["-option", "", "-option", "grp:alt_shift_toggle"]
KEYMAPS = {"de": ["-layout", "de", "-option", ""], "us": ["-layout", "us", "-option", ""], "gb": ["-layout", "gb", "-option", ""],
           "fr": ["-layout", "fr", "-option", ""], "es": ["-layout", "es", "-option", ""], "it": ["-layout", "it", "-option", ""],
           "lv": ["-layout", "lv", "-option", ""], "hu": ["-layout", "hu", "-option", ""], "pl": ["-layout", "pl", "-option", ""],
           "br": ["-layout", "br", "-option", ""], "cz": ["-layout", "cz", "-option", ""], "sk": ["-layout", "sk", "-option", ""],
           "gr": ["-layout", "us,gr"] + _GRP, "ru": ["-layout", "us,ru"] + _GRP, "ua": ["-layout", "us,ua"] + _GRP,
           "jp": ["-layout", "jp", "-option", ""], "ro": ["-layout", "ro", "-option", ""],
           "tr": ["-layout", "tr", "-option", ""], "dk": ["-layout", "dk", "-option", ""],
           "se": ["-layout", "se", "-option", ""], "no": ["-layout", "no", "-option", ""], "fi": ["-layout", "fi", "-option", ""],
           "is": ["-layout", "is", "-option", ""], "ee": ["-layout", "ee", "-option", ""],
           "th": ["-layout", "us,th"] + _GRP}
# Vorgaben im Installer je Sprache: Tastatur und Zeitzone (aenderbar)
INSTALL_DEFAULTS = {"de": ("de", "Europe/Berlin"), "en": ("us", "America/New_York"), "cs": ("cz", "Europe/Prague"),
                    "es": ("es", "Europe/Madrid"), "fr": ("fr", "Europe/Paris"), "it": ("it", "Europe/Rome"),
                    "lv": ("lv", "Europe/Riga"), "hu": ("hu", "Europe/Budapest"), "nl": ("us", "Europe/Amsterdam"),
                    "pl": ("pl", "Europe/Warsaw"), "pt-BR": ("br", "America/Sao_Paulo"), "sk": ("sk", "Europe/Bratislava"),
                    "el": ("gr", "Europe/Athens"), "ru": ("ru", "Europe/Moscow"), "uk": ("ua", "Europe/Kyiv"),
                    "ja": ("jp", "Asia/Tokyo"), "ro": ("ro", "Europe/Bucharest"), "tr": ("tr", "Europe/Istanbul"),
                    "ko": ("us", "Asia/Seoul"), "zh-CN": ("us", "Asia/Shanghai"), "zh-TW": ("us", "Asia/Taipei"),
                    "da": ("dk", "Europe/Copenhagen"), "sv": ("se", "Europe/Stockholm"), "nb": ("no", "Europe/Oslo"),
                    "is": ("is", "Atlantic/Reykjavik"), "fi": ("fi", "Europe/Helsinki"), "et": ("ee", "Europe/Tallinn"),
                    "id": ("us", "Asia/Jakarta"), "ms": ("us", "Asia/Kuala_Lumpur"), "vi": ("us", "Asia/Ho_Chi_Minh"),
                    "th": ("th", "Asia/Bangkok"), "hi": ("us", "Asia/Kolkata"), "ta": ("us", "Asia/Kolkata"),
                    "ml": ("us", "Asia/Kolkata")}


# ---------------------------------------------------------------------------
#  ROMs & Emulatoren: Spiele aus der Samba-Freigabe ~/share/ROMs/<system>
# ---------------------------------------------------------------------------
class ROMManager:
    """Verwaltet Spiele (ROMs) aus der Samba-Freigabe ~/share/ROMs/<system>."""
    # Mapping von Kachel-ID auf Ordnername in ~/share/ROMs/
    TILE_TO_SYSTEM = {
        "gba": "gba",
        "snes9x": "snes",
        "nestopia": "nes",
        "duckstation": "psx",
        "melonds": "nds",
        "ppsspp": "psp",
        "flycast": "dreamcast",
        "dolphin": "gamecube",
        "vice": "c64",            # VICE (x64sc) startet die Datei direkt (Autostart)
        "stella": "atari2600",
        "pcsx2": "ps2",
        "rmg": "n64",
        "xemu": "xbox",
        "azahar": "3ds",
        "cemu": "wiiu",
        "mame": "mame",
        "dosbox": "dos",
        "scummvm": "scummvm",
        "retroarch": "retroarch",
        "mednafen": "megadrive",  # dazu mastersystem, gamegear, saturn, pcengine (SYSTEM_FOLDERS)
    }
    SYSTEM_TO_TILE = {v: k for k, v in TILE_TO_SYSTEM.items()}
    SYSTEM_TO_TILE["gbc"] = "gba"
    SYSTEM_TO_TILE["wii"] = "dolphin"
    # Mednafen: je Ordner das Modul, das -force_module bekommt (Endungen wie .bin oder .cue sind sonst nicht eindeutig)
    MEDNAFEN_MODULES = {"megadrive": "md", "mastersystem": "sms", "gamegear": "gg", "saturn": "ss", "pcengine": "pce"}
    SYSTEM_TO_TILE.update({f: "mednafen" for f in MEDNAFEN_MODULES})
    # Weitere Ordner, die eine Kachel mit anzeigt (erster Ordner = Hauptordner der Kachel).
    # mGBA spielt auch Game Boy (Color): Spiele aus ROMs/gba und ROMs/gbc stehen in einer Liste.
    # Dolphin spielt GameCube und Wii: ROMs/gamecube und ROMs/wii in einer Liste.
    SYSTEM_FOLDERS = {
        "gba": ["gba", "gbc"],
        "gamecube": ["gamecube", "wii"],
        "megadrive": list(MEDNAFEN_MODULES),
    }
    # Dolphin 2609 (DolphinQt/MainWindow.cpp, Datei oeffnen): ohne .elf/.dol/.dff/.json (keine Spiele) und .bin/.nfs
    _DOLPHIN_EXT = [".iso", ".rvz", ".gcm", ".gcz", ".ciso", ".wia", ".wbfs", ".wad", ".tgc", ".m3u"]

    EXTENSIONS = {
        "gba": [".gba", ".gbc", ".gb", ".zip", ".7z"],
        "gbc": [".gbc", ".gb", ".zip", ".7z"],
        "snes": [".sfc", ".smc", ".zip", ".7z"],
        "nes": [".nes", ".zip", ".7z"],
        "psx": [".iso", ".cue", ".bin", ".chd", ".pbp", ".m3u"],       # .m3u: Liste der CDs eines Spiels (system.cpp)
        "psp": [".iso", ".cso", ".pbp"],
        "nds": [".nds", ".zip"],
        "gamecube": _DOLPHIN_EXT,
        "wii": _DOLPHIN_EXT,
        "dreamcast": [".cdi", ".gdi", ".chd"],
        "n64": [".z64", ".n64", ".v64", ".zip", ".7z"],
        "ps2": [".iso", ".chd", ".cso", ".zso", ".cue", ".gz", ".elf"],
        "xbox": [".iso", ".xiso"],
        "3ds": [".3ds", ".cci", ".cxi", ".3dsx", ".zcci", ".zcxi", ".z3dsx"],
        "wiiu": [".wua", ".wux", ".wud", ".rpx"],
        "c64": [".d64", ".t64", ".prg", ".crt"],
        "atari2600": [".a26", ".bin"],
        # Mednafen 1.32.1: md/system.cpp, sms/system.cpp, pce/pce.cpp KnownExtensions; CDs mednafen.cpp KnownCDExtensions
        # (kein .chd, kein .iso); .zip packt es selbst aus, .7z nicht
        "megadrive": [".md", ".bin", ".gen", ".smd", ".zip"],
        "mastersystem": [".sms", ".zip"],
        "gamegear": [".gg", ".zip"],
        "saturn": [".cue", ".ccd", ".toc", ".m3u"],
        "pcengine": [".pce", ".sgx", ".cue", ".ccd", ".toc", ".m3u", ".zip"],
        "scummvm": [".scummvm"],
        "dos": [".conf", ".exe", ".bat", ".com"],
        "mame": [".zip", ".7z"],
        "retroarch": [".zip", ".7z"],             # dazu alles, was die installierten Kerne lesen (retroarch_exts)
    }
    # Ordner, in denen auch Unterordner als Spiel zaehlen (DOS-Spiel bzw. ScummVM-Spiel = Ordner)
    DIR_SYSTEMS = {"dos", "scummvm"}
    # Optionen direkt vor der Spieldatei (xemu: -dvd_path, Cemu: -g – sonst nimmt das Programm die Datei nicht)
    ROM_ARGS = {"xbox": ["-dvd_path"], "wiiu": ["-g"]}

    def rom_args(self, canon, target):
        """Was hinter den Befehl des Emulators kommt, um genau dieses Spiel zu starten."""
        if canon == "mame":                       # MAME will den Namen des ROM-Sets, nicht die Datei
            return [target.stem]
        if canon == "scummvm":                    # Spiel = Ordner (eine .scummvm-Datei liegt darin)
            d = target if target.is_dir() else target.parent
            return (["--fullscreen"] if emu_fullscreen_wanted("scummvm") else []) + [f"--path={d}", "--auto-detect"]
        if canon == "megadrive":                  # Mednafen: Modul nach Ordner; -video.fs merkt es sich sonst vom letzten Mal
            try:
                mod = self.MEDNAFEN_MODULES.get(target.relative_to(self.rom_dir).parts[0])
            except (ValueError, IndexError):
                mod = None
            return ((["-force_module", mod] if mod else [])
                    + ["-video.fs", "1" if emu_fullscreen_wanted("mednafen") else "0", str(target)])
        if canon == "retroarch":
            core = retroarch_core(target)
            if not core:
                raise ValueError(f"Kein RetroArch-Kern fuer {target.suffix or target.name} – in RetroArch unter "
                                 "Online-Aktualisierung einen Kern laden")
            return ["-L", str(core), str(target)]
        return self.ROM_ARGS.get(canon, []) + [str(target)]
    # Befehle aus catalog.json als Basis/Fallback
    EMULATOR_CMD = {
        "gba": ["mgba-qt"],
        "gbc": ["mgba-qt"],
        "snes": ["snes9x-gtk"],
        "nes": ["nestopia"],
        "psx": ["~/.local/share/voidstation/apps/duckstation/AppRun"],
        "psp": ["PPSSPPSDL", "ppsspp", "PPSSPPQt"],   # erster vorhandener
        "nds": ["melonDS"],
        "dreamcast": ["~/.local/share/voidstation/apps/flycast/AppRun"],
        "gamecube": ["dolphin-emu"],
        "megadrive": ["mednafen"],
    }

    def __init__(self):
        self.rom_dir = Path.home() / "share" / "ROMs"
        self.games: dict = {}                     # Kachel -> (Popen, Spielname) des aus der Spieleliste gestarteten Spiels

    _DISC_TAG = re.compile(r"[\(\[]\s*(?:disc|disk|cd)\s*([0-9]{1,2}|[a-d])\b[^()\[\]]*[\)\]]", re.I)

    @classmethod
    def clean_name(cls, name):
        """Spielname ohne Zusaetze in Klammern ("Spiel (Europe) [!]" -> "Spiel"), wie in der Spieleliste. Die Nummer
        der CD bleibt ("Spiel (Europe) (Disc 2)" -> "Spiel (Disc 2)"), sonst hiessen alle CDs eines Spiels gleich."""
        disc = cls._DISC_TAG.search(name)
        base = re.sub(r"\s*[\(\[][^()\[\]]*[\)\]]", "", name).strip() or name
        return f"{base} (Disc {disc.group(1).upper()})" if disc and base != name else base

    # Unterordner: Spiele duerfen in eigenen Ordnern liegen (bin/cue mit mehreren Dateien, mehrere CDs, eigene Ordnung).
    SCAN_DEPTH = 3                                # so viele Ordner-Ebenen unter ROMs/<system>
    SCAN_SKIP = {"bios", "cover", "covers", "textures", "saves", "savestates", "_umgewandelt"}    # keine Spiele (klein verglichen)
    FLAT_SYSTEMS = {"mame"}                       # MAME sucht ROM-Sets nur direkt im Ordner (rompath)

    def scan(self, sys_dir, valid_exts, deep=True):
        """Spieldateien unter sys_dir, auch in Unterordnern. Ohne versteckte Ordner und SCAN_SKIP."""
        out = []

        def walk(d, depth):
            try:
                entries = sorted(d.iterdir(), key=lambda q: q.name.casefold())
            except OSError as e:
                log(f"{d} nicht lesbar:", e)
                return
            for item in entries:
                if item.name.startswith("."):
                    continue
                if item.is_dir():
                    if deep and depth < self.SCAN_DEPTH and item.name.casefold() not in self.SCAN_SKIP:
                        walk(item, depth + 1)
                elif item.is_file() and item.suffix.lower() in valid_exts:
                    out.append(item)
        walk(sys_dir, 0)
        return out

    # .bin ohne .cue-Blatt (so liegen viele PS1-Abbilder vor): "Spiel (Europe) (Track 2).bin" ist Spur 2 von "Spiel (Europe)"
    _TRACK_TAG = re.compile(r"^(.*?)\s*\(\s*track\s*0*([0-9]{1,2})\s*\)$", re.I)

    @classmethod
    def bin_base(cls, f):
        """Name des Spiels einer Spur ohne "(Track n)": "Tekken 3 (Europe) (Track 1).bin" -> "Tekken 3 (Europe)"."""
        m = cls._TRACK_TAG.match(f.stem)
        return m.group(1) if m and m.group(1) else f.stem

    def bin_sets(self, files, hidden=()):
        """.bin ohne Blatt zu Spielen zusammenfassen: {erste Spur: [alle Spuren der Reihe nach]}. Eine einzelne .bin
        ohne "(Track n)" ist ein Spiel mit nur ihr. .bin, auf die ein .cue verweist (hidden), zaehlen nicht."""
        groups: dict = {}
        for f in files:
            if f.suffix.lower() != ".bin" or f in hidden:
                continue
            m = self._TRACK_TAG.match(f.stem)
            num = int(m.group(2)) if m and m.group(1) else 0
            groups.setdefault((f.parent, self.bin_base(f).casefold()), []).append((num, f))
        out = {}
        for items in groups.values():
            items.sort(key=lambda x: (x[0], x[1].name.casefold()))
            out[items[0][1]] = [f for _n, f in items]
        return out

    @staticmethod
    def cue_tracks(cue):
        """Dateien, auf die ein .cue-Blatt verweist (FILE "Track 01.bin" BINARY), als Pfade neben dem Blatt.
        Gross-/Kleinschreibung wie auf der Platte, falls das Blatt unter Windows entstand."""
        try:
            txt = cue.read_bytes()[:65536].decode("utf-8", "replace")
        except OSError:
            return []
        names = re.findall(r'^\s*FILE\s+(?:"([^"]+)"|(\S+))', txt, re.M | re.I)
        try:
            real = {q.name.casefold(): q for q in cue.parent.iterdir()}
        except OSError:
            real = {}
        out = []
        for quoted, bare in names:
            n = os.path.basename((quoted or bare).replace("\\", "/"))
            q = real.get(n.casefold())
            if q is not None and q.is_file():
                out.append(q)
        return out

    @staticmethod
    def m3u_discs(m3u):
        """Abbilder, die eine .m3u-Liste nennt (eine Datei je Zeile, # = Kommentar), als Pfade neben der Liste."""
        try:
            txt = m3u.read_bytes()[:65536].decode("utf-8-sig", "replace")
        except OSError:
            return []
        out = []
        for line in txt.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            q = m3u.parent / line.replace("\\", "/")
            if not q.is_file():                      # unter Windows geschrieben: Gross-/Kleinschreibung der Platte
                try:
                    q = next((x for x in q.parent.iterdir() if x.name.casefold() == q.name.casefold()), q)
                except OSError:
                    pass
            if q.is_file() and q != m3u and q not in out:
                out.append(q)
        return out

    def rom_file(self, folder, filename):
        """Spieldatei bzw. -ordner aus dem Namen der Spieleliste (relativ zu ROMs/<folder>, auch "Ordner/Spiel.cue")
        -> Pfad oder None. Nie ausserhalb des Ordners."""
        rel = Path(str(filename))
        if not str(filename) or rel.is_absolute() or ".." in rel.parts:
            return None
        sys_dir = (self.rom_dir / folder).resolve()
        t = (sys_dir / rel).resolve()
        if t == sys_dir or not t.is_relative_to(sys_dir):
            return None
        return t if t.is_file() or (folder in self.DIR_SYSTEMS and t.is_dir()) else None

    def title_of(self, canon, target, names=None):
        """Name des Spiels wie in der Spieleliste (MAME: voller Name des ROM-Sets, DOS/ScummVM: Ordner).
        Wii U entpackt: Die Datei heisst immer aehnlich (<Spiel>/code/….rpx) – dort zaehlt der Ordner des Spiels."""
        if target.is_dir():
            return target.name
        if target.suffix.lower() == ".rpx" and target.parent.name.casefold() == "code":
            return self.clean_name(target.parent.parent.name)
        if canon == "mame":
            names = names if names is not None else mame_names([target.stem])
            return self.clean_name(names.get(target.stem) or target.stem)
        return self.clean_name(target.stem)

    def playing(self, key):
        """Name des Spiels, das unter der Kachel `key` gerade laeuft ("" = unbekannt, z. B. im Emulator selbst geoeffnet)."""
        proc, name = self.games.get(key, (None, ""))
        return name if proc is not None and APPS._get(key) is proc else ""

    def canonical_system(self, sys_or_tile):
        return self.TILE_TO_SYSTEM.get(sys_or_tile, sys_or_tile)

    def folders(self, sys_or_tile):
        """Ordner unter ~/share/ROMs, deren Spiele die Kachel bzw. das System zeigt (Hauptordner zuerst)."""
        canon = self.canonical_system(sys_or_tile)
        return list(self.SYSTEM_FOLDERS.get(canon, [canon]))

    def list_folder(self, folder):
        """Spiele genau eines Ordners ~/share/ROMs/<folder>."""
        sys_dir = self.rom_dir / folder
        if not sys_dir.is_dir():
            return []
        valid_exts = set(self.EXTENSIONS.get(folder, [".zip"]))
        if folder == "retroarch":
            valid_exts |= retroarch_exts()
        dirs = folder in self.DIR_SYSTEMS
        roms = []
        try:
            if dirs:                              # DOS, ScummVM: jeder Unterordner ist ein Spiel
                for item in sorted(sys_dir.iterdir()):
                    if item.is_dir() and not item.name.startswith(".") and item.name.casefold() not in ("bios", "cover"):
                        roms.append({"id": hashlib.sha1(str(item).encode()).hexdigest()[:10], "name": item.name,
                                     "filename": item.name, "system": folder, "folder": folder, "size": "", "bytes": 0,
                                     "dir": True})
            files = self.scan(sys_dir, valid_exts, deep=not dirs and folder not in self.FLAT_SYSTEMS)
            # bin/cue: Das Blatt (.cue) ist das Spiel, seine .bin-Dateien sind nur die Spuren – nicht eigens zeigen
            tracks: dict = {}
            for f in files:
                if f.suffix.lower() == ".cue":
                    tracks[f] = self.cue_tracks(f)
            hidden = {t for ts in tracks.values() for t in ts}
            # .m3u: Die Liste ist das Spiel, ihre CDs (samt deren Spuren) stehen nicht eigens in der Liste
            for f in files:
                if f.suffix.lower() == ".m3u":
                    discs = self.m3u_discs(f)
                    tracks[f] = [q for d in discs for q in [d] + (tracks.get(d) or self.cue_tracks(d) if d.suffix.lower() == ".cue" else [])]
                    hidden.update(tracks[f])
            # .bin ohne Blatt: Spuren eines Spiels ("… (Track 2).bin") stehen nicht eigens in der Liste, die erste Spur
            # steht fuer das Spiel (Name ohne "(Track 1)", Groesse aller Spuren)
            for first, ts in self.bin_sets(files, hidden).items():
                if len(ts) > 1:
                    tracks[first] = ts[1:]
                    hidden.update(ts[1:])
            names = mame_names([f.stem for f in files]) if folder == "mame" else {}
            for item in files:
                if item in hidden:
                    continue
                size_bytes = item.stat().st_size + sum(t.stat().st_size for t in tracks.get(item, []))
                size_mb = round(size_bytes / (1024 * 1024), 1)
                size_str = f"{size_mb} MB" if size_mb >= 1 else f"{round(size_bytes / 1024)} KB"
                roms.append({
                    "id": hashlib.sha1(str(item).encode()).hexdigest()[:10],
                    "name": self.title_of(folder, item, names),
                    "filename": item.relative_to(sys_dir).as_posix(),      # mit Unterordner: "Tekken 3/Tekken 3.cue"
                    "system": folder,
                    "folder": folder,
                    "size": size_str,
                    "bytes": size_bytes,
                })
            roms.sort(key=lambda r: (r["name"].casefold(), r["filename"].casefold()))
        except OSError as e:
            log(f"ROMs fuer {folder} nicht lesbar:", e)
        return roms

    def list_roms(self, system):
        """Spiele einer Kachel bzw. eines Systems, aus allen zugehoerigen Ordnern, alphabetisch."""
        folders = self.folders(system)
        roms = []
        for folder in folders:
            roms += self.list_folder(folder)
        if len(folders) > 1:
            roms.sort(key=lambda r: (r["name"].casefold(), r["filename"].casefold()))
        return roms

    def launch(self, system, filename, folder=None):
        canon = self.canonical_system(system)
        # Ordner: der vom Spiel mitgeschickte (falls er zur Kachel gehoert), sonst alle der Kachel der Reihe nach
        allowed = self.folders(system)
        cands = [folder] if folder in allowed else allowed
        target = None
        for f in cands:
            target = self.rom_file(f, filename)
            if target:
                break
        if not target:
            raise ValueError("Spieldatei nicht gefunden")

        # 1. Kachel-Befehl (tiles.json), 2. Katalog (catalog.json) – nur als Liste;
        #    Shell-Befehle (z. B. PPSSPP: "for b in ...; do exec $b; done") koennen keine Datei uebergeben
        cmd = None
        tid = self.SYSTEM_TO_TILE.get(canon, canon)
        for src in (find_tile(system), find_tile(tid), catalog_app(system), catalog_app(tid)):
            if src and isinstance(src.get("cmd"), list):
                cmd = expand(src["cmd"]) + self.rom_args(canon, target)
                break
        # 3. Fallback: erstes vorhandene Programm aus EMULATOR_CMD
        if not cmd and canon in self.EMULATOR_CMD:
            cands = self.EMULATOR_CMD[canon]
            if canon == "psp":
                exe = next((c for c in cands if shutil.which(c)), None)
                cmd = [exe, str(target)] if exe else None
            else:
                cmd = expand(cands) + [str(target)]
        if not cmd:
            raise ValueError(f"Kein Emulator fuer {canon} konfiguriert")

        return self._start(system, tid, cmd, self.title_of(canon, target))

    def launch_disc(self, system, dev):
        """PlayStation-Disc aus dem Laufwerk starten. PCSX2 will -disc, DuckStation nimmt das Geraet wie eine Datei."""
        disc = DVD.game_for(system)
        if not disc or disc["dev"] != dev:
            raise ValueError("Keine passende Disc im Laufwerk")
        canon = self.canonical_system(system)
        tid = self.SYSTEM_TO_TILE.get(canon, canon)
        extra = ["-disc", dev] if canon == "ps2" and dev.startswith("/dev/") else [dev]
        for src in (find_tile(system), find_tile(tid), catalog_app(system), catalog_app(tid)):
            if src and isinstance(src.get("cmd"), list):
                return self._start(system, tid, expand(src["cmd"]) + extra, disc.get("label") or disc.get("serial") or "")
        raise ValueError(f"Kein Emulator fuer {canon} konfiguriert")

    def _start(self, system, tid, cmd, game=""):
        # Unter der Kennung der Kachel starten (frueher "rom_<system>"): Nur so kennt die Startseite das Spiel als
        # laufend – Kachel holt es zurueck, Y bzw. die heisse Ecke beenden es –, und ein zweites Spiel startet
        # keine weitere, dann nicht mehr erreichbare Instanz.
        key = system if find_tile(system) else tid
        if APPS._get(key):
            log("Emulator laeuft schon, wird fuer das neue Spiel beendet:", key)
            APPS.close(key)
        media_notify("background")
        res = APPS.start(key, cmd)
        self.games[key] = (APPS._get(key), game)           # fuer Bildschirmfotos (Dateiname)
        return res


ROMS = ROMManager()


# ---------------------------------------------------------------------------
#  Emulatoren: Vorgaben (Vollbild, Grafik, Controller), Spielstand-Sicherung, Cover in der Spieleliste
# ---------------------------------------------------------------------------
def ini_read(path):
    """Einfache INI-Datei -> {abschnitt: {schluessel: wert}} (Gross-/Kleinschreibung bleibt, keine Interpolation)."""
    out: dict
    sec: str | None
    out, sec = {}, None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            sec = s[1:-1]
            out.setdefault(sec, {})
        elif sec is not None and "=" in s and not s.startswith((";", "#")):
            k, v = s.split("=", 1)
            out[sec][k.strip()] = v.strip()
    return out


def ini_update(path, section, values, remove=()):
    """Schluessel in genau einem Abschnitt setzen bzw. entfernen; ein fehlender Abschnitt kommt ans Ende.
    Alles andere in der Datei bleibt, wie es ist (anders als _ini_set, das Schluessel in allen Abschnitten loescht)."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    head = f"[{section}]"
    start = next((i for i, line in enumerate(lines) if line.strip() == head), None)
    if start is None:
        while lines and not lines[-1].strip():
            lines.pop()
        if lines:
            lines.append("")
        lines.append(head)
        start = len(lines) - 1
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("[")), len(lines))
    todo, drop, body = dict(values), set(remove), []
    for line in lines[start + 1:end]:
        k = line.split("=", 1)[0].strip() if "=" in line else None
        if k in drop:
            continue
        if k in todo:
            body.append(f"{k}={todo.pop(k)}")
            continue
        body.append(line)
    while body and not body[-1].strip():
        body.pop()
    body += [f"{k}={v}" for k, v in todo.items()]
    new = lines[:start + 1] + body + ([""] if end < len(lines) else []) + lines[end:]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".vs-tmp")
    tmp.write_text("\n".join(new) + "\n", encoding="utf-8")
    tmp.replace(path)


EMU_STATE = BASE / "emu-defaults.json"      # was VoidStation zuletzt in die Einstellungen der Emulatoren geschrieben hat
EMU_LOCK = threading.Lock()


def emu_state_load():
    try:
        st = json.loads(EMU_STATE.read_text(encoding="utf-8"))
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def emu_state_save(st):
    try:
        tmp = EMU_STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(EMU_STATE)
    except OSError as e:
        log("emu-defaults.json:", e)


def ini_defaults(app, path, section, wanted, st):
    """Vorgaben von VoidStation in eine INI schreiben – aber nur Schluessel, die fehlen oder noch genau den Wert
    haben, den VoidStation zuletzt geschrieben hat. Was der Nutzer im Programm selbst umgestellt hat, bleibt."""
    mine = st.setdefault(app, {}).setdefault(section, {})
    cur = ini_read(path).get(section, {})
    todo = {k: v for k, v in wanted.items() if (k not in cur or cur[k] == mine.get(k)) and cur.get(k) != v}
    if todo:
        ini_update(path, section, todo)
        log(f"{app}: Vorgaben gesetzt:", ", ".join(f"{k}={v}" for k, v in todo.items()))
    for k, v in wanted.items():
        if k not in cur or cur[k] == mine.get(k) or cur[k] == v:
            mine[k] = v


# ---- Controller: welche Taste ist welche? ------------------------------------------------------------------
# mGBA liest Controller roh ueber SDL (Tastennummern statt "A/B"), und die Nummern haengen am Treiber: Ein
# PS4-Nachbau, ein DualSense und ein Xbox-Pad zaehlen ihre Tasten verschieden. Woher die Belegung kommt, der Reihe nach:
#   1. SDL selbst (dieselbe Bibliothek, die mGBA laedt): SDL kennt die meisten Controller samt Nachbauten aus seiner
#      Datenbank und sagt, welche rohe Taste "unten", "rechts", "oben" … ist (SDL_GameControllerGetBindForButton)
#   2. Notfalls die Linux-Tastencodes (BTN_SOUTH = unten, BTN_EAST = rechts …)
# Das ist die Vorgabe; was man je Emulator selbst belegt hat (Tastenbelegung in der Spieleliste), steht darueber.
# Rollen nach Lage: south = unten (✕/A), east = rechts (○/B), west = links (□/X), north = oben (△/Y).
# SDL zaehlt Tasten unter Linux so (joystick/linux/SDL_sysjoystick.c, ConfigJoystick): erst alle Codes ab
# BTN_JOYSTICK (0x120) aufsteigend, dann die darunter; Achsen nach Nummer ohne digitale Steuerkreuze (ABS_HAT*).
# Damit das gilt, starten Emulatoren mit SDL_JOYSTICK_HIDAPI=0 (sonst zaehlt SDL PS4/PS5/Switch ueber hidraw anders).
SDL_PROBE = r'''
import ctypes, ctypes.util, json, os, sys
os.environ["SDL_JOYSTICK_HIDAPI"] = "0"
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
lib = None
for n in ("libSDL2-2.0.so.0", ctypes.util.find_library("SDL2") or ""):
    if n:
        try:
            lib = ctypes.CDLL(n)
            break
        except OSError:
            pass
if lib is None:
    print("[]"); sys.exit()
class Hat(ctypes.Structure):
    _fields_ = [("hat", ctypes.c_int), ("mask", ctypes.c_int)]
class Val(ctypes.Union):
    _fields_ = [("button", ctypes.c_int), ("axis", ctypes.c_int), ("hat", Hat)]
class Bind(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("value", Val)]
lib.SDL_Init.argtypes = [ctypes.c_uint32]
if lib.SDL_Init(0x200 | 0x2000) != 0:              # JOYSTICK | GAMECONTROLLER
    print("[]"); sys.exit()
lib.SDL_JoystickNameForIndex.restype = ctypes.c_char_p
has_path = hasattr(lib, "SDL_JoystickPathForIndex")
if has_path:
    lib.SDL_JoystickPathForIndex.restype = ctypes.c_char_p
lib.SDL_GameControllerOpen.restype = ctypes.c_void_p
lib.SDL_GameControllerNameForIndex.restype = ctypes.c_char_p
lib.SDL_GameControllerClose.argtypes = [ctypes.c_void_p]
class Guid(ctypes.Structure):
    _fields_ = [("data", ctypes.c_uint8 * 16)]
lib.SDL_JoystickGetDeviceGUID.restype = Guid
lib.SDL_JoystickGetGUIDString.argtypes = [Guid, ctypes.c_char_p, ctypes.c_int]
for f in ("SDL_GameControllerGetBindForButton", "SDL_GameControllerGetBindForAxis"):
    getattr(lib, f).restype = Bind
    getattr(lib, f).argtypes = [ctypes.c_void_p, ctypes.c_int]
def enc(b):
    if b.type == 1: return {"button": b.value.button}
    if b.type == 2: return {"axis": b.value.axis}
    if b.type == 3: return {"hat": b.value.hat.hat, "mask": b.value.hat.mask}
    return None
BTN = (("a", 0), ("b", 1), ("x", 2), ("y", 3), ("select", 4), ("guide", 5), ("start", 6), ("l3", 7), ("r3", 8),
       ("lb", 9), ("rb", 10), ("up", 11), ("down", 12), ("left", 13), ("right", 14))
AX = (("lx", 0), ("ly", 1), ("rx", 2), ("ry", 3), ("lt", 4), ("rt", 5))
out = []
for i in range(lib.SDL_NumJoysticks()):
    d = {"index": i, "name": (lib.SDL_JoystickNameForIndex(i) or b"").decode("utf-8", "replace"),
         "path": (lib.SDL_JoystickPathForIndex(i) or b"").decode() if has_path else ""}
    buf = ctypes.create_string_buffer(64)
    lib.SDL_JoystickGetGUIDString(lib.SDL_JoystickGetDeviceGUID(i), buf, 64)
    d["guid"] = buf.value.decode()
    if lib.SDL_IsGameController(i):
        d["gcname"] = (lib.SDL_GameControllerNameForIndex(i) or b"").decode("utf-8", "replace")
        c = lib.SDL_GameControllerOpen(i)
        if c:
            d["buttons"] = {n: enc(lib.SDL_GameControllerGetBindForButton(c, k)) for n, k in BTN}
            d["axes"] = {n: enc(lib.SDL_GameControllerGetBindForAxis(c, k)) for n, k in AX}
            lib.SDL_GameControllerClose(c)
    out.append(d)
lib.SDL_Quit()
print(json.dumps(out))
'''


def sdl_probe():
    """Was SDL ueber die angeschlossenen Controller weiss (Name wie in mGBA, Pfad, Belegung). [] wenn SDL fehlt."""
    try:
        r = subprocess.run([sys.executable, "-I", "-c", SDL_PROBE], capture_output=True, text=True, timeout=10,
                           env=dict(os.environ, SDL_JOYSTICK_HIDAPI="0"))
        out = json.loads(r.stdout.strip() or "[]")
        return out if isinstance(out, list) else []
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        log("SDL-Abfrage der Controller:", e)
        return []


def gamepads():
    """Angeschlossene Gamepads (evdev) in der Reihenfolge, in der SDL sie findet (nach Geraetenummer)."""
    try:
        import evdev  # type: ignore
        from evdev import ecodes as E
    except ImportError:
        return []
    out = []
    for p in sorted(evdev.list_devices(), key=lambda s: int(re.sub(r"\D", "", s) or 0)):
        try:
            d = evdev.InputDevice(p)
            caps = d.capabilities()
            name, info = d.name, d.info
            d.close()
        except OSError:
            continue
        keys = set(caps.get(E.EV_KEY, []))
        axes = {a[0] if isinstance(a, (tuple, list)) else a for a in caps.get(E.EV_ABS, [])}
        pen = keys & {E.BTN_TOUCH, E.BTN_TOOL_PEN, E.BTN_STYLUS, E.BTN_TOOL_FINGER}
        pad = (E.BTN_SOUTH in keys or E.BTN_TRIGGER in keys) and not pen
        if pad and (E.ABS_X in axes or E.ABS_HAT0X in axes or E.BTN_DPAD_UP in keys):
            out.append({"path": p, "name": name, "id": f"{info.vendor:04x}:{info.product:04x}",
                        "keys": keys, "axes": axes})
    return out


def sdl_indices(pad):
    """(Tasten, Achsen) eines Gamepads als {evdev-Code: SDL-Nummer}."""
    from evdev import ecodes as E
    keys = pad["keys"]
    order = sorted(k for k in keys if E.BTN_JOYSTICK <= k < E.KEY_MAX) + sorted(k for k in keys if k < E.BTN_JOYSTICK)
    axes = sorted(a for a in pad["axes"] if not E.ABS_HAT0X <= a <= E.ABS_HAT3Y)
    return {k: i for i, k in enumerate(order)}, {a: i for i, a in enumerate(axes)}


def binding_label(b):
    """Kurzbeschreibung einer Bindung fuer Log und Oberflaeche (z. B. "BTN_EAST", "ABS_Z+", "Kreuz ↑")."""
    from evdev import ecodes as E
    if not b:
        return ""
    def one(n):                                    # evdev nennt manche Codes mehrfach (BTN_A = BTN_SOUTH …)
        if isinstance(n, (list, tuple)):
            return next((x for x in n if x.endswith(("SOUTH", "EAST", "NORTH", "WEST"))), n[-1])
        return n
    if "key" in b:
        return one(E.BTN.get(b["key"]) or E.KEY.get(b["key"]) or str(b["key"]))
    if "abs" in b:
        return one(E.ABS.get(b["abs"], str(b["abs"]))) + ("+" if b.get("dir", 1) > 0 else "-")
    if "hat" in b:
        return {("y", -1): "HAT ↑", ("y", 1): "HAT ↓", ("x", -1): "HAT ←", ("x", 1): "HAT →"}.get((b["hat"], b["dir"]), "HAT")
    return ""


def pad_roles(pad, probe=None):
    """Rolle -> Bindung fuer ein Gamepad und woher sie stammt ("SDL", "Linux").
    Rollen nach Lage (PAD_ROLES): south/east/west/north = unten/rechts/links/oben (✕/○/□/△ bzw. A/B/X/Y),
    l1 r1 l2 r2 select start l3 r3 up down left right. Bindung: {"key": evdev-Code} | {"abs": Code, "dir": ±1}
    (Schultertaste als Achse) | {"hat": "x"|"y", "dir": ±1} (Steuerkreuz als Achse)."""
    from evdev import ecodes as E
    btn, ax = sdl_indices(pad)
    by_index = {i: c for c, i in btn.items()}
    by_axis = {i: c for c, i in ax.items()}
    sdl = next((d for d in (probe or []) if d.get("path") == pad["path"] and d.get("buttons")), None)
    if sdl:
        names = {"a": "south", "b": "east", "x": "west", "y": "north", "lb": "l1", "rb": "r1", "select": "select",
                 "start": "start", "l3": "l3", "r3": "r3", "up": "up", "down": "down", "left": "left", "right": "right"}
        binds = {}
        for r, b in sdl["buttons"].items():
            if r in names and b and "button" in b and b["button"] in by_index:
                binds[names[r]] = {"key": by_index[b["button"]]}
            elif r in names and b and "hat" in b and r in ("up", "down", "left", "right"):
                binds[names[r]] = {"hat": "y" if r in ("up", "down") else "x", "dir": -1 if r in ("up", "left") else 1}
        for r, role in (("lt", "l2"), ("rt", "r2")):
            b = (sdl.get("axes") or {}).get(r)
            if b and "axis" in b and b["axis"] in by_axis:
                binds[role] = {"abs": by_axis[b["axis"]], "dir": 1}
            elif b and "button" in b and b["button"] in by_index:
                binds[role] = {"key": by_index[b["button"]]}
        if E.ABS_HAT0X in pad["axes"]:                 # Kreuz, zu dem SDL nichts sagt: als Hat annehmen
            for r, h, d in (("up", "y", -1), ("down", "y", 1), ("left", "x", -1), ("right", "x", 1)):
                binds.setdefault(r, {"hat": h, "dir": d})
        used = [b for b in binds.values()]
        for role, axis, key in (("l2", E.ABS_Z, E.BTN_TL2), ("r2", E.ABS_RZ, E.BTN_TR2)):
            if role not in binds:                      # Trigger, zu denen SDL nichts sagt: Linux-Achse bzw. -Taste
                for cand in ({"abs": axis, "dir": 1} if axis in pad["axes"] else None,
                             {"key": key} if key in pad["keys"] else None):
                    if cand and cand not in used:
                        binds[role] = cand
                        used.append(cand)
                        break
        if "south" in binds and "east" in binds:
            stick_roles(binds, pad, sdl, by_axis)
            return binds, "SDL"
    std = {"south": E.BTN_SOUTH, "east": E.BTN_EAST, "west": E.BTN_WEST, "north": E.BTN_NORTH, "l1": E.BTN_TL,
           "r1": E.BTN_TR, "l2": E.BTN_TL2, "r2": E.BTN_TR2, "select": E.BTN_SELECT, "start": E.BTN_START,
           "l3": E.BTN_THUMBL, "r3": E.BTN_THUMBR, "up": E.BTN_DPAD_UP, "down": E.BTN_DPAD_DOWN,
           "left": E.BTN_DPAD_LEFT, "right": E.BTN_DPAD_RIGHT}
    binds = {r: {"key": c} for r, c in std.items() if c in pad["keys"]}
    for r, code in (("l2", E.ABS_Z), ("r2", E.ABS_RZ)):
        if r not in binds and code in pad["axes"]:
            binds[r] = {"abs": code, "dir": 1}
    if E.ABS_HAT0X in pad["axes"]:
        for r, h, d in (("up", "y", -1), ("down", "y", 1), ("left", "x", -1), ("right", "x", 1)):
            binds.setdefault(r, {"hat": h, "dir": d})
    stick_roles(binds, pad)
    return binds, "Linux"


# Rechter Stick als vier Richtungen (N64: C-Tasten) – zusaetzlich zu PAD_ROLES, nur als Vorgabe einzelner Konsolen
STICK_ROLES = ["rs_up", "rs_down", "rs_left", "rs_right"]
STICK_TEXT = {"rs_up": "R↑", "rs_down": "R↓", "rs_left": "R←", "rs_right": "R→"}


def stick_roles(binds, pad, sdl=None, by_axis=None):
    """rs_up/rs_down/rs_left/rs_right: Achsen des rechten Sticks (laut SDL, sonst ABS_RX/ABS_RY)."""
    from evdev import ecodes as E
    axes = (sdl or {}).get("axes") or {}
    def code(name, fallback):
        b = axes.get(name)
        if b and "axis" in b and by_axis and b["axis"] in by_axis:
            return by_axis[b["axis"]]
        return fallback if fallback in pad["axes"] else None
    rx, ry = code("rx", E.ABS_RX), code("ry", E.ABS_RY)
    if rx is not None and ry is not None and rx != ry:
        binds.update({"rs_up": {"abs": ry, "dir": -1}, "rs_down": {"abs": ry, "dir": 1},
                      "rs_left": {"abs": rx, "dir": -1}, "rs_right": {"abs": rx, "dir": 1}})


# ---- Tastenbelegung je Emulator (Spieleliste des Emulators -> "Tastenbelegung") ------------------------------
# Die Oberflaeche (KeymapLayer.qml) zeigt eine Skizze der Konsole und fragt deren Tasten der Reihe nach ab; man drueckt
# jeweils die Controllertaste, die dafuer gelten soll. Gilt nur fuer den Emulator – die Startseite liest das nie.
# ~/.config/voidstation/emu-pads.json:
#   {"emus": {"<Kachel>": {"<vid:pid>": {"name": …, "map": {"<Konsolentaste>": Bindung | null}}}}}
# Gespeichert wird nur, was von der Vorgabe abweicht (Vorgabe: Rolle aus EMU_LAYOUTS -> Bindung aus pad_roles);
# null = absichtlich frei gelassen (z. B. Savestate laden, damit man nicht aus Versehen drankommt).
# Bindung: {"key": evdev-Code} | {"abs": Code, "dir": ±1} | {"hat": "x"|"y", "dir": ±1}, s. pad_roles.
EMU_PADS = Path.home() / ".config/voidstation/emu-pads.json"
PAD_ROLES = ["south", "east", "west", "north", "l1", "r1", "l2", "r2", "select", "start", "l3", "r3",
             "up", "down", "left", "right"]
# Je Kachel: Skizze der Konsole ("console", gezeichnet in ConsolePic.qml) und Tasten als (Kennung, Vorgabe-Rolle) in
# der Reihenfolge, in der "Alle nacheinander" fragt; Vorgabe-Rolle "" = frei. Konsolentasten liegen nach Lage
# (Nintendo: A rechts, B unten; PlayStation: ✕ unten …). Kennungen aus EMU_ACTIONS gibt es auf der Konsole nicht – die
# erledigt VoidStation selbst (Taste an den Emulator, EMU_KEYS); wo die Konsole alle Tasten des Controllers braucht,
# sind sie anfangs frei. "notes": Hinweise der Oberflaeche (keymap.note.*). Analogsticks belegt VoidStation fest mit.
_DPAD = [("Up", "up"), ("Down", "down"), ("Left", "left"), ("Right", "right")]
EMU_LAYOUTS: dict[str, Any] = {
    "gba": {"name": "mGBA", "sub": "Game Boy / Color / Advance", "console": "gba", "buttons": [
        ("A", "east"), ("B", "south"), ("L", "l1"), ("R", "r1"), ("Start", "start"), ("Select", "select"),
        *_DPAD, ("save", "north"), ("load", "west"), ("rewind", "l2"), ("ff", "r2")]},
    "nestopia": {"name": "Nestopia", "sub": "NES", "console": "nes", "buttons": [
        ("A", "east"), ("B", "south"), ("Start", "start"), ("Select", "select"),
        *_DPAD, ("save", "north"), ("load", "west"), ("ff", "r2")]},
    "snes9x": {"name": "Snes9x", "sub": "Super Nintendo", "console": "snes", "buttons": [
        ("A", "east"), ("B", "south"), ("X", "north"), ("Y", "west"), ("L", "l1"), ("R", "r1"),
        ("Start", "start"), ("Select", "select"), *_DPAD, ("save", ""), ("load", ""), ("ff", "r2")]},
    "melonds": {"name": "melonDS", "sub": "Nintendo DS", "console": "nds", "buttons": [
        ("A", "east"), ("B", "south"), ("X", "north"), ("Y", "west"), ("L", "l1"), ("R", "r1"),
        ("Start", "start"), ("Select", "select"), *_DPAD, ("save", ""), ("load", ""), ("ff", "r2")]},
    "duckstation": {"name": "DuckStation", "sub": "PlayStation", "console": "psx", "notes": ["sticks", "duckstation"],
                    "buttons": [
        ("Cross", "south"), ("Circle", "east"), ("Square", "west"), ("Triangle", "north"),
        ("L1", "l1"), ("R1", "r1"), ("L2", "l2"), ("R2", "r2"), ("L3", "l3"), ("R3", "r3"),
        ("Start", "start"), ("Select", "select"), *_DPAD, ("save", ""), ("load", ""), ("ff", "")]},
    "ppsspp": {"name": "PPSSPP", "sub": "PSP", "console": "psp", "notes": ["sticks"], "buttons": [
        ("Cross", "south"), ("Circle", "east"), ("Square", "west"), ("Triangle", "north"), ("L", "l1"), ("R", "r1"),
        ("Start", "start"), ("Select", "select"), *_DPAD, ("save", ""), ("load", ""), ("ff", "r2")]},
    "dolphin": {"name": "Dolphin", "sub": "GameCube", "console": "gc", "notes": ["sticks"], "buttons": [
        ("A", "south"), ("B", "west"), ("X", "east"), ("Y", "north"), ("Z", "r1"), ("L", "l2"), ("R", "r2"),
        ("Start", "start"), *_DPAD, ("save", ""), ("load", ""), ("ff", "l1")]},
    "flycast": {"name": "Flycast", "sub": "Dreamcast", "console": "dc", "notes": ["sticks", "flycast"], "buttons": [
        ("A", "south"), ("B", "east"), ("X", "west"), ("Y", "north"), ("L", "l2"), ("R", "r2"),
        ("Start", "start"), *_DPAD, ("ff", "r1")]},
    "pcsx2": {"name": "PCSX2", "sub": "PlayStation 2", "console": "ps2", "notes": ["sticks", "pcsx2"], "buttons": [
        ("Cross", "south"), ("Circle", "east"), ("Square", "west"), ("Triangle", "north"),
        ("L1", "l1"), ("R1", "r1"), ("L2", "l2"), ("R2", "r2"), ("L3", "l3"), ("R3", "r3"),
        ("Start", "start"), ("Select", "select"), *_DPAD, ("save", ""), ("load", ""), ("ff", "")]},
    # N64: A unten, B links (wie auf dem Original schraeg darueber), Z auf dem linken Trigger, C-Tasten auf dem rechten Stick
    "rmg": {"name": "Rosalie's Mupen GUI", "sub": "Nintendo 64", "console": "n64", "notes": ["n64"], "buttons": [
        ("A", "south"), ("B", "west"), ("Z", "l2"), ("L", "l1"), ("R", "r1"), ("Start", "start"),
        ("CUp", "rs_up"), ("CDown", "rs_down"), ("CLeft", "rs_left"), ("CRight", "rs_right"), *_DPAD,
        ("save", ""), ("load", ""), ("ff", "r2")]},
    "xemu": {"name": "xemu", "sub": "Xbox", "console": "xbox", "notes": ["sticks", "xemu"], "buttons": [
        ("A", "south"), ("B", "east"), ("X", "west"), ("Y", "north"), ("White", "l1"), ("Black", "r1"),
        ("LT", "l2"), ("RT", "r2"), ("Back", "select"), ("Start", "start"), ("LS", "l3"), ("RS", "r3"), *_DPAD,
        ("save", ""), ("load", "")]},
    "azahar": {"name": "Azahar", "sub": "Nintendo 3DS", "console": "n3ds", "notes": ["sticks"], "buttons": [
        ("A", "east"), ("B", "south"), ("X", "north"), ("Y", "west"), ("L", "l1"), ("R", "r1"), ("ZL", "l2"),
        ("ZR", "r2"), ("Start", "start"), ("Select", "select"), *_DPAD, ("save", ""), ("load", ""), ("ff", "")]},
    "cemu": {"name": "Cemu", "sub": "Wii U", "console": "wiiu", "notes": ["sticks", "cemu"], "buttons": [
        ("A", "east"), ("B", "south"), ("X", "north"), ("Y", "west"), ("L", "l1"), ("R", "r1"), ("ZL", "l2"),
        ("ZR", "r2"), ("Plus", "start"), ("Minus", "select"), ("L3", "l3"), ("R3", "r3"), *_DPAD]},
    # Arcade: sechs Tasten in zwei Reihen (unten 1–3, oben 4–6 ≈ Controller unten/rechts/links/oben + Schultern)
    "mame": {"name": "MAME", "sub": "Arcade", "console": "arcade", "notes": ["sticks", "mame"], "buttons": [
        ("Button1", "south"), ("Button2", "east"), ("Button3", "west"), ("Button4", "north"), ("Button5", "l1"),
        ("Button6", "r1"), ("Coin", "select"), ("Start", "start"), *_DPAD, ("save", ""), ("load", ""), ("ff", "r2")]},
    # DOS: der Controller als Tastatur – die Tasten schickt VoidStation (EMU_KEYS), DOSBox selbst bleibt unveraendert
    "dosbox": {"name": "DOSBox Staging", "sub": "DOS", "console": "keyboard", "notes": ["dosbox"], "buttons": [
        ("Space", "south"), ("Ctrl", "east"), ("Alt", "west"), ("Shift", "north"), ("Enter", "start"),
        ("Esc", "select"), ("KeyY", "l1"), ("KeyN", "r1"), ("Tab", "l2"), ("F1", "r2"), ("KeyUp", "up"),
        ("KeyDown", "down"), ("KeyLeft", "left"), ("KeyRight", "right")]},
    # RetroPad: Lage wie beim SNES-Pad (B unten, A rechts, Y links, X oben)
    "retroarch": {"name": "RetroArch", "sub": "RetroPad", "console": "retropad", "notes": ["sticks", "retroarch"],
                  "buttons": [
        ("B", "south"), ("A", "east"), ("Y", "west"), ("X", "north"), ("L", "l1"), ("R", "r1"), ("L2", "l2"),
        ("R2", "r2"), ("L3", "l3"), ("R3", "r3"), ("Start", "start"), ("Select", "select"), *_DPAD,
        ("save", ""), ("load", ""), ("ff", ""), ("rewind", "")]},
    # Mednafen: ein Pad fuer alle Systeme – Sega-Pad mit sechs Tasten (Saturn: dazu L/R). A/B/C liegen wie auf dem
    # Original in einer Reihe (links, unten, rechts), X/Y/Z darueber auf L1, oben, R1. Master System und Game Gear:
    # 1 = B, 2 = C; PC Engine: II = B, I = C, Select = Mode, Run = Start (MEDNAFEN_PADS)
    "mednafen": {"name": "Mednafen", "sub": "Sega · PC Engine", "console": "saturn", "notes": ["mednafen"], "buttons": [
        ("A", "west"), ("B", "south"), ("C", "east"), ("X", "l1"), ("Y", "north"), ("Z", "r1"), ("L", "l2"), ("R", "r2"),
        ("Start", "start"), ("Mode", "select"), *_DPAD, ("save", ""), ("load", ""), ("ff", "")]},
}
EMU_ACTIONS = {"save", "load", "rewind", "ff"}
# Was VoidStation fuer die Extras an das Fenster des Emulators schickt (tap = einmal, hold = solange gedrueckt).
# Tasten aus dem Quelltext der Emulatoren bzw. von VoidStation gesetzt, wo der Emulator keine vorgibt (s. *_prepare):
#   mGBA 0.10 Window.cpp · Snes9x 1.60 (keine Vorgabe) · Nestopia 1.53 inputmanager.cpp (F5/F7) · DuckStation
#   hotkeys.cpp (F2/F1/Tab) · PPSSPP 1.20 (Speichern/Laden ohne Vorgabe, Tab) · melonDS 1.1 Window.cpp (Umschalt+F1/F1)
#   · Dolphin 2609 HotkeyManager.cpp (Umschalt+F1/F1/Tab) · Flycast 2.7 keyboard_device.h (Leertaste)
#   · PCSX2 2.8 Pad.cpp (F1/F3; Turbo halten setzt VoidStation auf Tab) · RMG 0.9 Settings.cpp (F5/F7; F4 schaltet die
#   Geschwindigkeitsbremse – "toggle": beim Druecken und beim Loslassen je einmal) · xemu 0.8 main.cc (F5 laden,
#   Umschalt+F5 speichern, sobald F5 einem Schnappschuss zugeordnet ist – macht VoidStation) · Azahar 2126 (Schnell-
#   speichern/-laden und Turbo ohne Vorgabe, setzt VoidStation) · MAME 0.282 inpttype.ipp (Umschalt+F6/F7 Schnell-
#   speichern/-laden, Einfg vorspulen) · RetroArch 1.22 config.def.keybinds.h (F2/F4, L halten, R zurueckspulen)
#   · DOSBox: alle Tasten – der Controller tippt auf der Tastatur · Mednafen 1.32 drivers/input.cpp (F5/F7, ` halten)
EMU_KEYS = {
    "gba": {"save": ("tap", "shift+F1"), "load": ("tap", "F1"), "ff": ("hold", "Tab"), "rewind": ("hold", "Scroll_Lock")},
    "snes9x": {"save": ("tap", "shift+F1"), "load": ("tap", "F1"), "ff": ("hold", "Tab")},
    "nestopia": {"save": ("tap", "F5"), "load": ("tap", "F7"), "ff": ("hold", "Tab")},
    "duckstation": {"save": ("tap", "F2"), "load": ("tap", "F1"), "ff": ("hold", "Tab")},
    "ppsspp": {"save": ("tap", "F2"), "load": ("tap", "F4"), "ff": ("hold", "Tab")},
    "melonds": {"save": ("tap", "shift+F1"), "load": ("tap", "F1"), "ff": ("hold", "Tab")},
    "dolphin": {"save": ("tap", "shift+F1"), "load": ("tap", "F1"), "ff": ("hold", "Tab")},
    "flycast": {"ff": ("hold", "space")},
    "pcsx2": {"save": ("tap", "F1"), "load": ("tap", "F3"), "ff": ("hold", "Tab")},
    "rmg": {"save": ("tap", "F5"), "load": ("tap", "F7"), "ff": ("toggle", "F4")},
    "xemu": {"save": ("tap", "shift+F5"), "load": ("tap", "F5")},
    "azahar": {"save": ("tap", "shift+F1"), "load": ("tap", "F1"), "ff": ("toggle", "ctrl+t")},
    "mame": {"save": ("tap", "shift+F6"), "load": ("tap", "shift+F7"), "ff": ("hold", "Insert")},
    "mednafen": {"save": ("tap", "F5"), "load": ("tap", "F7"), "ff": ("hold", "grave")},
    "retroarch": {"save": ("tap", "F2"), "load": ("tap", "F4"), "ff": ("hold", "l"), "rewind": ("hold", "r")},
    "dosbox": {"Space": ("hold", "space"), "Ctrl": ("hold", "Control_L"), "Alt": ("hold", "Alt_L"),
               "Shift": ("hold", "Shift_L"), "Enter": ("hold", "Return"), "Esc": ("hold", "Escape"),
               "KeyY": ("hold", "y"), "KeyN": ("hold", "n"), "Tab": ("hold", "Tab"), "F1": ("hold", "F1"),
               "KeyUp": ("hold", "Up"), "KeyDown": ("hold", "Down"), "KeyLeft": ("hold", "Left"),
               "KeyRight": ("hold", "Right")},
}
EMU_PADS_LOCK = threading.Lock()
# Controllertasten zum Anzeigen, je nach Bauart (Steuerkreuz: Pfeile, die Oberflaeche setzt "Kreuz" davor)
ROLE_TEXT = {
    "ps": {"south": "✕", "east": "○", "west": "□", "north": "△", "l1": "L1", "r1": "R1", "l2": "L2", "r2": "R2",
           "select": "Share", "start": "Options", "l3": "L3", "r3": "R3"},
    "xbox": {"south": "A", "east": "B", "west": "X", "north": "Y", "l1": "LB", "r1": "RB", "l2": "LT", "r2": "RT",
             "select": "Back", "start": "Start", "l3": "LS", "r3": "RS"},
    # Nintendo: Tasten nach Lage belegt (hid-nintendo: untere Taste = BTN_SOUTH, beschriftet B)
    "nintendo": {"south": "B", "east": "A", "west": "Y", "north": "X", "l1": "L", "r1": "R", "l2": "ZL", "r2": "ZR",
                 "select": "−", "start": "+", "l3": "LS", "r3": "RS"},
}
DPAD_TEXT = {"up": "↑", "down": "↓", "left": "←", "right": "→"}


def emu_pads_load():
    try:
        d = json.loads(EMU_PADS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    if not isinstance(d, dict):
        d = {}
    if not isinstance(d.get("emus"), dict):
        d["emus"] = {}
    return d


def emu_pads_save(d):
    EMU_PADS.parent.mkdir(parents=True, exist_ok=True)
    tmp = EMU_PADS.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(EMU_PADS)


def valid_bind(b):
    if not isinstance(b, dict):
        return None
    if isinstance(b.get("key"), int):
        return {"key": b["key"]}
    if isinstance(b.get("abs"), int) and b.get("dir") in (1, -1):
        return {"abs": b["abs"], "dir": b["dir"]}
    if b.get("hat") in ("x", "y") and b.get("dir") in (1, -1):
        return {"hat": b["hat"], "dir": b["dir"]}
    return None


def pad_style(name, pid=""):
    """Beschriftung der Controllertasten: PlayStation-Symbole, Nintendo- oder Xbox-Buchstaben (wie
    vscommon.pad_style der Qt-Oberflaeche; pid = "vendor:product")."""
    vendor = str(pid).split(":")[0].lower()
    if vendor == "057e" or re.search(r"nintendo|pro controller|joy-?con|\bswitch\b", name or "", re.I):
        return "nintendo"
    # vor PlayStation: Xbox-Pads per Bluetooth heissen "Xbox Wireless Controller" (DualShock 4: "Wireless Controller")
    if vendor == "045e" or re.search(r"xbox|x-box|microsoft", name or "", re.I):
        return "xbox"
    if vendor == "054c" or re.search(r"sony|playstation|wireless controller|dualsense|dualshock|\bps[345]\b", name or "", re.I):
        return "ps"
    return "xbox"


def emu_binds(emu, pad, probe=None, roles=None):
    """Konsolentaste -> Bindung fuer einen Controller (Vorgabe ueber pad_roles, darueber die eigene Belegung)
    und ob es fuer diesen Controller eine eigene Belegung gibt."""
    lay = EMU_LAYOUTS.get(emu)
    if not lay:
        return {}, False
    if roles is None:
        roles = pad_roles(pad, probe)[0]
    ent = (emu_pads_load()["emus"].get(emu) or {}).get(pad["id"])
    own: Any = ent.get("map") if isinstance(ent, dict) and isinstance(ent.get("map"), dict) else {}
    out = {}
    for btn, role in lay["buttons"]:
        out[btn] = valid_bind(own[btn]) if btn in own else roles.get(role)   # null bzw. Unbrauchbares: frei
    return out, bool(own)


def keymap_payload(emu, path=""):
    """Fuer die Seite "Tastenbelegung": Konsole, Controller, je Konsolentaste die Controllertaste."""
    emu_paths_refresh()
    lay = EMU_LAYOUTS[emu]
    pads = gamepads()
    pad = next((p for p in pads if p["path"] == path), pads[0] if pads else None)
    out = {"emu": emu, "name": lay["name"], "sub": lay.get("sub", ""), "console": lay["console"],
           "notes": [n for n in lay.get("notes", []) if n not in KEYMAP_NOTE_READY or not KEYMAP_NOTE_READY[n]()],
           "rstick": any(r in STICK_ROLES for _, r in lay["buttons"]),
           "pads": [{"path": p["path"], "name": p["name"]} for p in pads], "pad": None, "custom": False}
    roles, src, style, binds = {}, "", "xbox", {}
    if pad:
        roles, src = pad_roles(pad, sdl_probe())
        style = pad_style(pad["name"], pad.get("id", ""))
        binds, out["custom"] = emu_binds(emu, pad, roles=roles)
        out["pad"] = {"path": pad["path"], "name": pad["name"], "id": pad["id"], "src": src}
    btns = []
    for btn, defrole in lay["buttons"]:
        b = binds.get(btn)
        role = next((r for r, x in roles.items() if x == b), "") if b else ""
        label = DPAD_TEXT.get(role) or STICK_TEXT.get(role) or ROLE_TEXT[style].get(role) or (binding_label(b) if b else "")
        btns.append({"id": btn, "action": btn in EMU_ACTIONS, "bind": b, "role": role, "label": label,
                     "custom": bool(pad) and b != roles.get(defrole)})
    out["buttons"] = btns
    return out


def keymap_pad(path):
    pad = next((p for p in gamepads() if p["path"] == path), None)
    if not pad:
        raise ValueError("Kein Controller unter diesem Pfad")
    return pad


def keymap_set(emu, path, button, bind):
    """Eine Konsolentaste auf eine Controllertaste legen (bind=None: frei lassen). Lag die Controllertaste schon auf
    einer anderen Konsolentaste, tauschen die beiden (die andere bekommt die bisherige Taste).
    -> Liste der getauschten Konsolentasten."""
    lay = EMU_LAYOUTS.get(emu)
    if not lay or button not in dict(lay["buttons"]):
        raise ValueError("Unbekannte Taste")
    if bind is not None:
        bind = valid_bind(bind)
        if not bind:
            raise ValueError("Ungueltige Taste")
    pad = keymap_pad(path)
    roles = pad_roles(pad, sdl_probe())[0]
    defs = {b: roles.get(r) for b, r in lay["buttons"]}
    with EMU_PADS_LOCK:
        cur, _ = emu_binds(emu, pad, roles=roles)
        new, swapped = dict(cur), []
        for other, ob in cur.items():
            if bind and other != button and ob == bind:
                new[other] = cur[button]
                swapped.append(other)
        new[button] = bind
        m = {b: v for b, v in new.items() if v != defs[b]}
        d = emu_pads_load()
        emus = d["emus"].setdefault(emu, {})
        if m:
            emus[pad["id"]] = {"name": pad["name"], "map": m}
        else:
            emus.pop(pad["id"], None)
        if not emus:
            d["emus"].pop(emu, None)
        emu_pads_save(d)
    log(f"Tastenbelegung {emu} ({pad['name']}): {button} = {binding_label(bind) if bind else 'frei'}",
        f"(getauscht mit {', '.join(swapped)})" if swapped else "")
    return swapped


def keymap_reset(emu, path):
    """Eigene Belegung eines Controllers fuer einen Emulator verwerfen (zurueck zur Vorgabe)."""
    pad = keymap_pad(path)
    with EMU_PADS_LOCK:
        d = emu_pads_load()
        (d["emus"].get(emu) or {}).pop(pad["id"], None)
        if not d["emus"].get(emu):
            d["emus"].pop(emu, None)
        emu_pads_save(d)
    log(f"Tastenbelegung {emu} ({pad['name']}): zurueck auf Vorgabe")


class PadCapture:
    """Tastenbelegung: auf den naechsten Tastendruck eines Controllers warten. Das Geraet ist dabei exklusiv geoeffnet
    (EVIOCGRAB), damit Startseite und Guide-Taste nichts davon mitbekommen – sonst wuerde jeder Druck auch die
    Oberflaeche bedienen. Zwischen zwei Fragen bleibt es kurz gegriffen (LINGER), damit ein schneller Druck nicht doch
    in der Oberflaeche landet. Guide/PS-Taste = abbrechen."""
    LINGER = 2.0

    def __init__(self):
        self.lock = threading.Lock()
        self.dev = None
        self.rest = {}                               # Achse -> (Ruhewert, min, max), beim Greifen gemerkt
        self.gen = 0                                 # jede neue Frage / Abbrechen zaehlt hoch

    def _device(self, path):
        import evdev  # type: ignore
        from evdev import ecodes as E
        if self.dev is not None and self.dev.path == path:
            return self.dev
        self._release()
        if path not in {p["path"] for p in gamepads()}:
            raise ValueError("Kein Controller unter diesem Pfad")
        dev = evdev.InputDevice(path)
        dev.grab()
        self.dev = dev
        self.rest = {c: (0 if E.ABS_HAT0X <= c <= E.ABS_HAT3Y else i.value, i.min, i.max)
                     for c, i in dev.capabilities().get(E.EV_ABS, [])}
        return dev

    def _release(self):
        dev, self.dev = self.dev, None
        if dev is not None:
            try:
                dev.ungrab()
            except OSError:
                pass
            try:
                dev.close()
            except OSError:
                pass

    def _linger(self, gen):
        time.sleep(self.LINGER)
        with self.lock:
            if self.gen == gen:
                self._release()

    def cancel(self):
        with self.lock:
            self.gen += 1
            self._release()

    def capture(self, path, timeout=10.0, rstick=False):
        """-> {"bind", "label"} | {"timeout": True} (nichts gedrueckt) | {"cancel": True} (Guide/PS-Taste)
        | {"cancelled": True} (von der Oberflaeche abgebrochen). rstick: auch der rechte Stick zaehlt (N64: C-Tasten),
        sonst nie ein Stick – ein leichtes Wackeln soll keine Taste belegen."""
        import select as sel
        from evdev import ecodes as E
        sticks = {E.ABS_X, E.ABS_Y} if rstick else {E.ABS_X, E.ABS_Y, E.ABS_RX, E.ABS_RY}
        with self.lock:
            self.gen += 1
            gen = self.gen
            dev = self._device(path)
            rest = dict(self.rest)
        try:
            while sel.select([dev.fd], [], [], 0)[0]:  # Liegengebliebenes (Loslassen der vorigen Taste …) verwerfen
                for _ev in dev.read():
                    pass
            held = set(dev.active_keys())             # noch gedrueckt: erst loslassen
            armed = {}                                 # Achse muss erst in Ruhe sein, bevor sie zaehlt
            for c, (v0, lo, hi) in rest.items():
                armed[c] = abs(dev.absinfo(c).value - v0) / ((hi - lo) or 1) < 0.3
            end = time.monotonic() + timeout
            while time.monotonic() < end:
                r, _, _ = sel.select([dev.fd], [], [], min(0.2, max(0.0, end - time.monotonic())))
                if self.gen != gen:
                    return {"cancelled": True}
                if not r:
                    continue
                for ev in dev.read():
                    if ev.type == E.EV_KEY:
                        if ev.value == 0:
                            held.discard(ev.code)
                        elif ev.value == 1 and ev.code not in held:
                            if ev.code == E.BTN_MODE:
                                return {"cancel": True}
                            b = {"key": ev.code}
                            return {"bind": b, "label": binding_label(b)}
                    elif ev.type == E.EV_ABS and ev.code not in sticks and ev.code in rest:
                        if E.ABS_HAT0X <= ev.code <= E.ABS_HAT3Y:
                            if ev.code in (E.ABS_HAT0X, E.ABS_HAT0Y):
                                if ev.value == 0:
                                    armed[ev.code] = True
                                elif armed.get(ev.code):
                                    b = {"hat": "x" if ev.code == E.ABS_HAT0X else "y", "dir": 1 if ev.value > 0 else -1}
                                    return {"bind": b, "label": binding_label(b)}
                            continue
                        v0, lo, hi = rest[ev.code]
                        x = abs(ev.value - v0) / ((hi - lo) or 1)
                        if x < 0.3:
                            armed[ev.code] = True
                        elif x > 0.6 and armed.get(ev.code):    # deutlich gedrueckt (Schultertaste als Achse)
                            b = {"abs": ev.code, "dir": 1 if ev.value > v0 else -1}
                            return {"bind": b, "label": binding_label(b)}
            return {"timeout": True}
        except OSError:
            if self.gen != gen:
                return {"cancelled": True}
            with self.lock:
                self._release()
            raise
        finally:
            threading.Thread(target=self._linger, args=(gen,), daemon=True).start()


PAD_CAPTURE = PadCapture()


# ---- mGBA (Kachel "gba"; geprueft am Quelltext von mGBA 0.10.5) ----------------------------------------------
MGBA_CONFIG = Path.home() / ".config/mgba/config.ini"
MGBA_QT = Path.home() / ".config/mgba/qt.ini"
MGBA_PAD = "gba.input.SDLB"                  # Belegung fuer alle Controller ohne eigenes Profil
# Namen, fuer die mGBA 0.10 eingebaute Profile mitbringt (src/platform/qt/InputProfile.cpp)
MGBA_BUILTIN_RE = re.compile(r"^(XInput Controller #\d+|Microsoft X-Box 360 pad|Xbox Gamepad \(userspace driver\)|"
                             r"Xbox 360 Wired Controller|(?:Sony Computer Entertainment )?Wireless Controller|"
                             r"PLAYSTATION\(R\)3 Controller|Wiimote \(..-..-..-..-..-..\))$", re.M)
MGBA_DEFAULTS = {
    "autosave": "1",              # Stand alle 10 s und beim Beenden sichern (Platz 0) ...
    "autoload": "1",              # ... und beim naechsten Start dort weitermachen
    "lockAspectRatio": "1",       # Seitenverhaeltnis behalten
    "lockIntegerScaling": "1",    # ganzzahlig vergroessern: gleich breite, scharfe Pixel (720p/1080p: wenig Rand)
    "resampleVideo": "0",         # nicht weichzeichnen
    "interframeBlending": "0",
    "pauseOnFocusLost": "0",      # Anhalten im Hintergrund macht VoidStation selbst
    "suspendScreensaver": "1",
}
MGBA_KEYS = ["A", "B", "Select", "Start", "Right", "Left", "Up", "Down", "R", "L"]     # GBA-Tastennummern 0…9
# Zurueckspulen bekommt in mGBA eine Taste, die auf jedem Tastaturlayout gleich ist (Vorgabe ` ist auf deutschen
# Tastaturen eine Tottaste); was VoidStation schickt, steht in EMU_KEYS
MGBA_REWIND_KEY = "ScrollLock"               # QKeySequence-Name fuer qt.ini [shortcutKey] holdRewind


def mgba_pad_map(pad, bmap):
    """Belegung fuer mGBA aus Konsolentaste -> Bindung (emu_binds). Tasten -> keyX = SDL-Tastennummer,
    Schultertasten als Achse -> axisX, Steuerkreuz als Achse -> hat0X. Der linke Stick steuert immer mit."""
    from evdev import ecodes as E
    btn, ax = sdl_indices(pad)
    m = {f"key{k}": "-1" for k in MGBA_KEYS}
    hat = {}
    axes = {}
    for k in MGBA_KEYS:
        b = bmap.get(k) or {}
        if "key" in b and b["key"] in btn:
            m[f"key{k}"] = str(btn[b["key"]])
        elif "hat" in b:
            hat[{("y", -1): "Up", ("y", 1): "Down", ("x", -1): "Left", ("x", 1): "Right"}[(b["hat"], b["dir"])]] = \
                str(MGBA_KEYS.index(k))
        elif "abs" in b and b["abs"] in ax:
            axes[k] = (ax[b["abs"]], b["dir"])
    m.update({f"hat0{d}": hat.get(d, "-1") for d in ("Up", "Right", "Down", "Left")})
    stick = {}
    if E.ABS_X in ax:
        stick["Left"], stick["Right"] = (ax[E.ABS_X], -1), (ax[E.ABS_X], 1)
    if E.ABS_Y in ax:
        stick["Up"], stick["Down"] = (ax[E.ABS_Y], -1), (ax[E.ABS_Y], 1)
    for k, (a, d) in {**stick, **axes}.items():
        m[f"axis{k}Value"] = str(16384 * d)
        m[f"axis{k}Axis"] = ("+" if d > 0 else "-") + str(a)
    return m


MGBA_AXIS_KEYS = [f"axis{k}{s}" for k in MGBA_KEYS for s in ("Value", "Axis")]


def qt_ini_group(name):
    """Gruppenname so maskiert, wie QSettings (IniFormat) ihn schreibt (Leerzeichen -> %20 usw.)."""
    return "".join(c if c.isascii() and (c.isalnum() or c in "_-.") else "".join(f"%{b:02X}" for b in c.encode())
                   if ord(c) <= 0xFF else f"%U{ord(c):04X}" for c in name)


def ini_section_once(app, path, section, values, st, key, remove=()):
    """Ganzen Abschnitt schreiben, solange er fehlt oder noch so aussieht, wie VoidStation ihn zuletzt schrieb."""
    cur = ini_read(path).get(section)
    last = st.get(app, {}).get(key)
    if cur and cur != last:
        return False                               # vom Nutzer in mGBA geaendert: bleibt
    if cur != values:
        ini_update(path, section, values, remove=remove)
    st.setdefault(app, {})[key] = dict(values)
    return True


def mgba_prepare():
    """Vor jedem Start von mGBA: Grundeinstellungen und Controller-Belegung.
    Hat man in VoidStation eine eigene Tastenbelegung festgelegt, gilt sie immer (sie ist ja ausdruecklich so
    gewollt); sonst die Vorgabe, aber nur, wo der Nutzer in mGBA selbst nichts geaendert hat."""
    emu_mute_apply("gba")
    with EMU_LOCK:
        st = emu_state_load()
        wanted = dict(MGBA_DEFAULTS)
        if SYS_ARCH != "i686":                 # Zurueckspulen kostet jedes Bild Rechenzeit – auf alten Rechnern nicht
            wanted["rewindEnable"] = "1"
        ini_defaults("mgba", MGBA_CONFIG, "ports.qt", wanted, st)
        pads = gamepads()
        sdl_name = ""
        if pads:
            pad = pads[0]
            probe = sdl_probe()
            roles, src = pad_roles(pad, probe)
            bmap, custom = emu_binds("gba", pad, roles=roles)
            m = mgba_pad_map(pad, bmap)
            rm = [k for k in MGBA_AXIS_KEYS if k not in m]
            sdl_name = next((d["name"] for d in probe if d.get("path") == pad["path"]), "") or \
                (probe[0]["name"] if len(probe) == 1 else "")
            sections = [(MGBA_PAD, "pad")] + ([(f"gba.input-profile.{sdl_name}", f"profile:{sdl_name}")] if sdl_name else [])
            for sec, key in sections:
                if custom:
                    ini_update(MGBA_CONFIG, sec, m, remove=rm)
                    st.setdefault("mgba", {})[key] = dict(m)
                elif not ini_section_once("mgba", MGBA_CONFIG, sec, m, st, key, rm):
                    log(f"mGBA: eigene Belegung in [{sec}] bleibt")
            log(f"mGBA: Controller-Belegung fuer {pad['name']} ({src}{', eigene Tastenbelegung' if custom else ''}):", m)
        # Eingebaute Profile von mGBA (InputProfile.cpp) legen Kurzbefehle auf Controller-Tasten – gezaehlt wie unter
        # Windows/macOS. Beim PS4-Controller ("Wireless Controller") lag "Laden" auf ✕. Savestates und Spulen macht
        # jetzt VoidStation (EMU_KEYS, frei belegbar), deshalb alle vier abschalten – fuer den Namen von SDL und
        # alle, unter denen mGBA schon ein Profil gespeichert hat. Nur, wo der Nutzer nichts eingestellt hat.
        names = {n for n in MGBA_BUILTIN_RE.findall("\n".join(
            s[len("gba.input-profile."):] for s in ini_read(MGBA_CONFIG) if s.startswith("gba.input-profile."))) if n}
        if sdl_name and MGBA_BUILTIN_RE.fullmatch(sdl_name):
            names.add(sdl_name)
        for n in sorted(names):
            grp = "shortcutProfileButton." + qt_ini_group(n)
            cur = ini_read(MGBA_QT).get(grp, {})
            fix = {k: "-1" for k in ("loadState", "saveState", "holdFastForward", "holdRewind") if k not in cur}
            if fix:
                ini_update(MGBA_QT, grp, fix)
                log(f"mGBA: Kurzbefehle des eingebauten Profils fuer {n!r} aus:", fix)
        for k in [k for k in st.setdefault("mgba", {}) if k.startswith(("shortcuts:", "shortcutaxes:"))]:
            st["mgba"].pop(k, None)                   # Merker aelterer Fassungen
        # Zurueckspulen (gehalten) auf eine Taste, die xdotool auf jedem Layout schicken kann
        keys = ini_read(MGBA_QT).get("shortcutKey", {})
        if "holdRewind" not in keys or (keys["holdRewind"] == MGBA_REWIND_KEY):
            if keys.get("holdRewind") != MGBA_REWIND_KEY:
                ini_update(MGBA_QT, "shortcutKey", {"holdRewind": MGBA_REWIND_KEY})
        emu_state_save(st)


# ---- Tastenbelegung in die Emulatoren schreiben (vor jedem Start, emu_prepare) -------------------------------
# Je Emulator das eigene Format, jeweils am Quelltext der installierten Fassung geprueft. Geschrieben wird
#   * immer, wenn es in VoidStation eine eigene Belegung fuer den Controller gibt (sie ist ja so gewollt),
#   * sonst die Vorgabe, aber nur, solange der Nutzer die Belegung im Emulator nicht selbst geaendert hat
#     (keymap_once: verglichen mit dem, was VoidStation zuletzt geschrieben hat).
# Rohe Tasten-/Achsennummern zaehlt VoidStation wie SDL unter Linux (sdl_indices); dafuer starten die Emulatoren
# mit SDL_JOYSTICK_HIDAPI=0. Wo der Emulator SDL-Controllernamen versteht (DuckStation, PPSSPP, Dolphin), schreibt
# VoidStation diese – dann ist die Zaehlung egal.
GC_ROLE = {"south": "a", "east": "b", "west": "x", "north": "y", "l1": "lb", "r1": "rb", "l2": "lt", "r2": "rt",
           "select": "back", "start": "start", "l3": "l3", "r3": "r3",
           "up": "up", "down": "down", "left": "left", "right": "right"}
HAT_DIRS = {("y", -1): "up", ("y", 1): "down", ("x", -1): "left", ("x", 1): "right"}


def keymap_context(tile):
    """Erster Controller mit Rollen und Belegung fuer `tile` -> dict oder None (kein Controller)."""
    pads = gamepads()
    if not pads:
        return None
    pad = pads[0]
    probe = sdl_probe()
    roles, src = pad_roles(pad, probe)
    bmap, custom = emu_binds(tile, pad, roles=roles)
    info = next((d for d in probe if d.get("path") == pad["path"]), None) or (probe[0] if len(probe) == 1 else {})
    btn, ax = sdl_indices(pad)
    return {"pad": pad, "roles": roles, "src": src, "bmap": bmap, "custom": custom, "sdl": info,
            "index": int(info.get("index", 0) or 0), "btn": btn, "ax": ax}


def bind_role(b, roles):
    """Rolle (PAD_ROLES) einer Bindung, "" fuer alles andere (auch Richtungen des rechten Sticks)."""
    return next((r for r in PAD_ROLES if roles.get(r) == b), "") if b else ""


def bind_raw(ctx, b):
    """Bindung -> ("button", n) | ("axis", n, ±1) | ("hat", Richtung) | None, gezaehlt wie SDL-Joysticks."""
    if not b:
        return None
    if "key" in b and b["key"] in ctx["btn"]:
        return ("button", ctx["btn"][b["key"]])
    if "abs" in b and b["abs"] in ctx["ax"]:
        return ("axis", ctx["ax"][b["abs"]], b["dir"])
    if "hat" in b:
        return ("hat", HAT_DIRS[(b["hat"], b["dir"])])
    return None


def stick_axes(ctx):
    """SDL-Achsennummern der Sticks: {"lx", "ly", "rx", "ry"} (soweit vorhanden)."""
    from evdev import ecodes as E
    return {n: ctx["ax"][c] for n, c in (("lx", E.ABS_X), ("ly", E.ABS_Y), ("rx", E.ABS_RX), ("ry", E.ABS_RY))
            if c in ctx["ax"]}


def keymap_once(app, key, current, wanted, force):
    """Belegung schreiben? force (eigene Belegung), nichts da, oder noch genau das, was VoidStation zuletzt schrieb.
    Merkt sich das Geschriebene in emu-defaults.json. -> True, wenn geschrieben werden soll."""
    st = emu_state_load()
    last = st.get(app, {}).get(key)
    empty = not any(v not in (None, "", "-1", -1, "Unset") for v in (current or {}).values())
    if not (force or empty or current == last or current == wanted):
        log(f"{app}: eigene Belegung im Emulator bleibt")
        return False
    st.setdefault(app, {})[key] = wanted
    emu_state_save(st)
    return True


def ini_multi_set(path, section, wanted, drop):
    """Abschnitt mit mehrfachen Schluesseln (DuckStation: "Cross = Keyboard/X" und "Cross = SDL-0/A"): fuer jeden
    Schluessel aus `wanted` Zeilen entfernen, deren Wert drop(wert) erfuellt, und den neuen Wert (falls nicht None)
    anhaengen. Alles andere bleibt, wie es ist."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    head = f"[{section}]"
    start = next((i for i, line in enumerate(lines) if line.strip() == head), None)
    if start is None:
        lines += ([""] if lines else []) + [head]
        start = len(lines) - 1
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("[")), len(lines))
    body = []
    for line in lines[start + 1:end]:
        k, sep, v = line.partition("=")
        if sep and k.strip() in wanted and drop(v.strip()):
            continue
        body.append(line)
    while body and not body[-1].strip():
        body.pop()
    body += [f"{k} = {v}" for k, v in wanted.items() if v is not None]
    new = lines[:start + 1] + body + ([""] if end < len(lines) else []) + lines[end:]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".vs-tmp")
    tmp.write_text("\n".join(new) + "\n", encoding="utf-8")
    tmp.replace(path)


def ini_multi_get(path, section, keys, keep):
    """Werte mehrfacher Schluessel eines Abschnitts, die keep(wert) erfuellen -> {Schluessel: Wert | None}."""
    out = {k: None for k in keys}
    sec = None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        t = line.strip()
        if t.startswith("[") and t.endswith("]"):
            sec = t[1:-1]
        elif sec == section and "=" in t:
            k, _, v = t.partition("=")
            if k.strip() in out and keep(v.strip()):
                out[k.strip()] = v.strip()
    return out


# -- DuckStation (AppImage, SDL3; settings.ini [Pad1], src/util/sdl_input_source.cpp, src/core/analog_controller.cpp)
DUCK_INI = Path.home() / ".local/share/duckstation/settings.ini"
DUCK_GC = {"a": "A", "b": "B", "x": "X", "y": "Y", "back": "Back", "start": "Start", "l3": "LeftStick",
           "r3": "RightStick", "lb": "LeftShoulder", "rb": "RightShoulder", "up": "DPadUp", "down": "DPadDown",
           "left": "DPadLeft", "right": "DPadRight", "lt": "+LeftTrigger", "rt": "+RightTrigger"}
DUCK_HAT = {"up": "North", "right": "East", "down": "South", "left": "West"}


def duck_name(ctx, b):
    role = bind_role(b, ctx["roles"])
    if role:
        return f"SDL-0/{DUCK_GC[GC_ROLE[role]]}"
    raw = bind_raw(ctx, b)
    if not raw:
        return None
    if raw[0] == "button":
        return f"SDL-0/Button{raw[1]}"
    if raw[0] == "axis":
        return f"SDL-0/{'+' if raw[2] > 0 else '-'}Axis{raw[1]}"
    return f"SDL-0/Hat0{DUCK_HAT[raw[1]]}"


def duck_ready():
    """DuckStation schon eingerichtet (settings.ini mit [Pad1])? Vorher schreibt VoidStation nichts hinein."""
    try:
        return "[Pad1]" in DUCK_INI.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def duckstation_prepare(ctx):
    """[Pad1]: SDL-Belegung neben der Tastatur. Erst, wenn DuckStation einmal gelaufen ist (Einrichtungsassistent
    legt settings.ini samt [Pad1] an) – vorher wuerde DuckStation die Datei als neu behandeln."""
    if not duck_ready():
        log("DuckStation: noch nicht eingerichtet – Belegung beim naechsten Start")
        return
    wanted = {b: duck_name(ctx, ctx["bmap"].get(b)) for b, _ in EMU_LAYOUTS["duckstation"]["buttons"]
              if b not in EMU_ACTIONS}
    wanted.update({"LLeft": "SDL-0/-LeftX", "LRight": "SDL-0/+LeftX", "LUp": "SDL-0/-LeftY",
                   "LDown": "SDL-0/+LeftY", "RLeft": "SDL-0/-RightX", "RRight": "SDL-0/+RightX",
                   "RUp": "SDL-0/-RightY", "RDown": "SDL-0/+RightY"})
    is_sdl = lambda v: v.startswith("SDL-")
    cur = ini_multi_get(DUCK_INI, "Pad1", list(wanted), is_sdl)
    if keymap_once("duckstation", "pad", cur, wanted, ctx["custom"]):
        ini_multi_set(DUCK_INI, "Pad1", wanted, is_sdl)
        log("DuckStation: Controller-Belegung", wanted)


# -- Snes9x 1.60 (GTK, SDL2-Joystick; snes9x.conf [Joypad 0], gtk_binding.cpp, gtk_control.cpp)
def snes9x_conf():
    legacy, new = Path.home() / ".snes9x", Path.home() / ".config/snes9x"
    return (legacy if legacy.is_dir() and not new.is_dir() else new) / "snes9x.conf"


def snes9x_value(ctx, b):
    """Binding::to_string: "Joystick 1 Button 3", "Joystick 1 Axis 2 + 50%"; Steuerkreuz = Achsen hinter den echten
    (num_axes + 2*hat: hoch +, runter −; num_axes + 2*hat + 1: links −, rechts +)."""
    raw, dev = bind_raw(ctx, b), ctx["index"] + 1
    if not raw:
        return "Unset"
    if raw[0] == "button":
        return f"Joystick {dev} Button {raw[1]}"
    if raw[0] == "axis":
        return f"Joystick {dev} Axis {raw[1]} {'+' if raw[2] > 0 else '-'} 50%"
    n = len(ctx["ax"])
    axis, sign = {"up": (n, "+"), "down": (n, "-"), "left": (n + 1, "-"), "right": (n + 1, "+")}[raw[1]]
    return f"Joystick {dev} Axis {axis} {sign} 50%"


def snes9x_prepare(ctx):
    path = snes9x_conf()
    wanted = {b: snes9x_value(ctx, ctx["bmap"].get(b)) for b, _ in EMU_LAYOUTS["snes9x"]["buttons"]
              if b not in EMU_ACTIONS}
    cur = {k: v for k, v in ini_read(path).get("Joypad 0", {}).items() if k in wanted}
    if keymap_once("snes9x", "pad", cur, wanted, ctx["custom"]):
        ini_update(path, "Joypad 0", wanted)
        log("Snes9x: Controller-Belegung", wanted)
    # Tasten fuer die Extras (EMU_KEYS) – Snes9x gibt keine vor; nur, wo noch nichts eingestellt ist
    sc = ini_read(path).get("Shortcuts", {})
    fix = {k: v for k, v in (("QuickSave000", "Keyboard Shift+F1"), ("QuickLoad000", "Keyboard F1"),
                             ("EmuTurbo", "Keyboard Tab")) if sc.get(k, "Unset") in ("", "Unset")}
    if fix:
        ini_update(path, "Shortcuts", fix)


# -- Nestopia 1.53 (FLTK, SDL2-Joystick; input.conf [nespad1j], fltkui/inputmanager.cpp; mINI: Kleinschreibung)
NESTOPIA_INPUT = Path.home() / ".config/nestopia/input.conf"
# Einstellungsdateien fuer die Optionen (EMU_OPTS) und Stumm (EMU_MUTE)
NESTOPIA_CONF = NESTOPIA_INPUT.with_name("nestopia.conf")
SCUMMVM_INI = Path.home() / ".config/scummvm/scummvm.ini"
VICE_RC = Path.home() / ".config/vice/vicerc"
STELLA_DB = Path.home() / ".config/stella/stella.sqlite3"       # OSystemStandalone.cxx: StellaDb(basedir, "stella")


def nestopia_value(ctx, b):
    raw, port = bind_raw(ctx, b), ctx["index"]
    if not raw:
        return ""
    if raw[0] == "button":
        return f"j{port}b{raw[1]}"
    if raw[0] == "axis":
        return f"j{port}a{raw[1] * 2 + (1 if raw[2] > 0 else 0)}"
    return f"j{port}h{['up', 'down', 'left', 'right'].index(raw[1])}"


def nestopia_prepare(ctx):
    wanted = {b.lower(): nestopia_value(ctx, ctx["bmap"].get(b)) for b, _ in EMU_LAYOUTS["nestopia"]["buttons"]
              if b not in EMU_ACTIONS}
    ini = ini_read(NESTOPIA_INPUT)
    cur = {k: v for k, v in ini.get("nespad1j", {}).items() if k in wanted}
    if keymap_once("nestopia", "pad", cur, wanted, ctx["custom"]):
        ini_update(NESTOPIA_INPUT, "nespad1j", wanted)
        log("Nestopia: Controller-Belegung", wanted)
    # Vorspulen: Vorgabe ` ist auf deutschen Tastaturen eine Tottaste -> Tab (FLTK FL_Tab), nur ueber der Vorgabe
    if ini.get("ui", {}).get("fastforward", "96") in ("", "96"):
        ini_update(NESTOPIA_INPUT, "ui", {"fastforward": "65289"})


# -- PPSSPP 1.20 (SDL2-GameController; PSP/SYSTEM/controls.ini [ControlMapping], Core/KeyMap.cpp, SDL/SDLJoystick.cpp)
PPSSPP_CTRL = Path.home() / ".config/ppsspp/PSP/SYSTEM/controls.ini"
PPSSPP_INI = PPSSPP_CTRL.with_name("ppsspp.ini")
PPSSPP_PAD = {"y": 188, "a": 189, "b": 190, "x": 191, "rb": 192, "lb": 193, "back": 196, "start": 197, "l3": 106,
              "r3": 107, "up": 19, "down": 20, "left": 21, "right": 22, "lt": 4008, "rt": 4010}   # NKCODE / 4000+Achse*2
# Vorgaben von PPSSPP (RestoreDefault: Tastatur QWERTY + DEFAULT_MAPPING_PAD), aus KeyMapDefaults.cpp erzeugt. Fehlt
# ein Schluessel, sobald [ControlMapping] existiert, gilt er als unbelegt – deshalb beim ersten Mal alle schreiben.
PPSSPP_DEFAULTS = {
    "Up": "1-19,10-19", "Down": "1-20,10-20", "Left": "1-21,10-21", "Right": "1-22,10-22", "Circle": "1-52,10-190",
    "Cross": "1-54,10-189", "Square": "1-29,10-191", "Triangle": "1-47,10-188", "Start": "1-62,10-197",
    "Select": "1-50,1-66,10-196", "L": "1-45,10-194", "R": "1-51,10-195", "An.Up": "1-37,10-4003",
    "An.Down": "1-39,10-4002", "An.Left": "1-38,10-4001", "An.Right": "1-40,10-4000", "Analog limiter": "1-60",
    "RapidFire": "1-59", "Fast-forward": "1-61", "Pause": "1-111,10-109,10-104,10-4034", "Pause (no menu)": "1-138",
    "SpeedToggle": "1-68", "Analog speed": "10-4036", "Rewind": "1-67", "Toggle Debugger": "1-142",
}
PPSSPP_KEYS = ["Cross", "Circle", "Square", "Triangle", "L", "R", "Start", "Select", "Up", "Down", "Left", "Right"]


def ppsspp_prepare(ctx):
    ini = ini_read(PPSSPP_CTRL)
    has = "ControlMapping" in ini
    sec = ini["ControlMapping"] if has else dict(PPSSPP_DEFAULTS)
    pad_of = lambda v: ",".join(x.strip() for x in v.split(",") if x.strip().startswith("10-")) or None
    wanted = {}
    for b in PPSSPP_KEYS:
        role = bind_role(ctx["bmap"].get(b), ctx["roles"])
        wanted[b] = f"10-{PPSSPP_PAD[GC_ROLE[role]]}" if role else None
    cur = {b: pad_of(sec.get(b, "")) for b in PPSSPP_KEYS}
    stock = {b: pad_of(PPSSPP_DEFAULTS[b]) for b in PPSSPP_KEYS}
    values = {}
    # PPSSPPs eigene Vorgabe legt L/R auf Tasten, die SDL nie meldet -> die gilt nicht als eigene Einstellung
    if keymap_once("ppsspp", "pad", cur, wanted, ctx["custom"] or cur == stock):
        for b in PPSSPP_KEYS:
            keep = [x.strip() for x in sec.get(b, "").split(",") if x.strip() and not x.strip().startswith("10-")]
            values[b] = ",".join(keep + ([wanted[b]] if wanted[b] else []))
    for k, code in (("Save State", "1-132"), ("Load State", "1-134")):   # F2 / F4 (EMU_KEYS), wo nichts belegt ist
        if not sec.get(k, "").strip():
            values[k] = code
    if not has:
        values = {**PPSSPP_DEFAULTS, **values}
    if values:
        ini_update(PPSSPP_CTRL, "ControlMapping", values)
        log("PPSSPP: Controller-Belegung", {k: values[k] for k in values if k in PPSSPP_KEYS})


# -- melonDS 1.1 (SDL2-Joystick; melonDS.toml [Instance0.Joystick], EmuInstanceInput.cpp)
MELONDS_TOML = Path.home() / ".config/melonDS/melonDS.toml"
MELONDS_HAT = {"up": 0x1, "right": 0x2, "down": 0x4, "left": 0x8}


def melonds_value(ctx, b):
    """Taste = Nummer; Steuerkreuz = 0x100 | Hat<<4 | Richtung; Achse = 0xFFFF | 0x10000 | Achse<<24 | Richtung<<20
    (0 = positiv, 1 = negativ); -1 = frei."""
    raw = bind_raw(ctx, b)
    if not raw:
        return -1
    if raw[0] == "button":
        return raw[1]
    if raw[0] == "axis":
        return 0xFFFF | 0x10000 | (raw[1] << 24) | ((0 if raw[2] > 0 else 1) << 20)
    return 0x100 | MELONDS_HAT[raw[1]]


def toml_dump(d):
    """Kleiner TOML-Schreiber fuer melonDS.toml und xemu.toml (Tabellen, Listen von Tabellen, Zahlen,
    Wahrheitswerte, Texte, Listen davon)."""
    def key(k):
        return k if re.fullmatch(r"[A-Za-z0-9_-]+", k) else json.dumps(k, ensure_ascii=False)

    def val(v):
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return repr(v)
        if isinstance(v, str):
            return json.dumps(v, ensure_ascii=False)
        if isinstance(v, list) and not any(isinstance(x, (dict, list)) for x in v):
            return "[" + ", ".join(val(x) for x in v) + "]"
        raise ValueError(f"TOML: {type(v)}")

    out = []
    is_tables = lambda v: isinstance(v, list) and bool(v) and all(isinstance(x, dict) for x in v)

    def table(t, path, head=True):
        scal = [(k, v) for k, v in t.items() if not isinstance(v, dict) and not is_tables(v)]
        subs = [(k, v) for k, v in t.items() if isinstance(v, dict) or is_tables(v)]
        if head and path and (scal or not subs):
            out.append("\n[" + ".".join(key(p) for p in path) + "]")
        out.extend(f"{key(k)} = {val(v)}" for k, v in scal)
        for k, v in subs:
            if isinstance(v, dict):
                table(v, path + [k])
            else:
                for item in v:
                    out.append("\n[[" + ".".join(key(p) for p in path + [k]) + "]]")
                    table(item, path + [k], head=False)
    table(d, [])
    return "\n".join(out).lstrip("\n") + "\n"


def melonds_prepare(ctx):
    import tomllib
    if not MELONDS_TOML.exists() and (MELONDS_TOML.parent / "melonDS.ini").exists():
        return                                    # alte ini: melonDS uebernimmt sie selbst beim ersten Start
    try:
        root = tomllib.loads(MELONDS_TOML.read_text(encoding="utf-8")) if MELONDS_TOML.exists() else {}
    except (OSError, ValueError) as e:
        log("melonDS.toml nicht lesbar, Belegung bleibt:", e)
        return
    inst = root.setdefault("Instance0", {})
    joy = inst.setdefault("Joystick", {})
    wanted = {b: melonds_value(ctx, ctx["bmap"].get(b)) for b, _ in EMU_LAYOUTS["melonds"]["buttons"]
              if b not in EMU_ACTIONS}
    cur = {b: joy.get(b) for b in wanted if b in joy}
    changed = False
    if keymap_once("melonds", "pad", cur, wanted, ctx["custom"]):
        joy.update(wanted)
        inst["JoystickID"] = ctx["index"]
        changed = True
    kb = inst.setdefault("Keyboard", {})
    if kb.get("HK_FastForward", -1) == -1:        # Vorspulen auf Tab (Qt::Key_Tab), wie in EMU_KEYS
        kb["HK_FastForward"] = 0x01000001
        changed = True
    if changed:
        try:
            text = toml_dump(root)
        except ValueError as e:                   # z. B. Tabellen-Listen: lieber nichts schreiben als zerstoeren
            log("melonDS.toml: unbekannter Aufbau, Belegung bleibt:", e)
            return
        MELONDS_TOML.parent.mkdir(parents=True, exist_ok=True)
        tmp = MELONDS_TOML.with_suffix(".vs-tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(MELONDS_TOML)
        log("melonDS: Controller-Belegung", wanted)


# -- Dolphin 2609 (SDL3-Gamepad; GCPadNew.ini [GCPad1], ControllerInterface/SDL/SDLGamepad.h, Core/HW/GCPadEmu.cpp)
DOLPHIN_GC = {"a": "Button S", "b": "Button E", "x": "Button W", "y": "Button N", "back": "Back", "start": "Start",
              "l3": "Thumb L", "r3": "Thumb R", "lb": "Shoulder L", "rb": "Shoulder R", "up": "Pad N",
              "down": "Pad S", "left": "Pad W", "right": "Pad E", "lt": "Trigger L", "rt": "Trigger R"}


def dolphin_dir():
    legacy = Path.home() / ".dolphin-emu"
    return legacy if legacy.is_dir() else Path.home() / ".config/dolphin-emu"


def dolphin_expr(name):
    """Wie MappingCommon::GetExpressionForControl: Namen mit Nicht-Buchstaben in Backticks."""
    return name if name.isalpha() else f"`{name}`"


def dolphin_prepare(ctx):
    name = ctx["sdl"].get("gcname") or ctx["sdl"].get("name") or ""
    if not name:
        log("Dolphin: SDL kennt den Controller nicht – Belegung bleibt")
        return
    path = dolphin_dir() / "GCPadNew.ini"
    m = {}
    for b, _ in EMU_LAYOUTS["dolphin"]["buttons"]:
        if b in EMU_ACTIONS:
            continue
        role = bind_role(ctx["bmap"].get(b), ctx["roles"])
        m[b] = dolphin_expr(DOLPHIN_GC[GC_ROLE[role]]) if role else ""
    wanted = {"Device": f"SDL/0/{name}"}
    wanted.update({f"Buttons/{b}": m[b] for b in ("A", "B", "X", "Y", "Z", "Start")})
    wanted.update({f"D-Pad/{b}": m[b] for b in ("Up", "Down", "Left", "Right")})
    wanted.update({"Triggers/L": m["L"], "Triggers/R": m["R"], "Triggers/L-Analog": m["L"],
                   "Triggers/R-Analog": m["R"]})
    for grp, ax in (("Main Stick", "Left"), ("C-Stick", "Right")):   # SDLGamepad: Hochachsen umgedreht (Y+ = hoch)
        wanted.update({f"{grp}/Up": f"`{ax} Y+`", f"{grp}/Down": f"`{ax} Y-`", f"{grp}/Left": f"`{ax} X-`",
                       f"{grp}/Right": f"`{ax} X+`"})
    cur = {k: v for k, v in ini_read(path).get("GCPad1", {}).items() if k in wanted}
    if cur.get("Device", "").startswith(("XInput2/", "Keyboard")):
        cur = {}                                  # Tastatur (Vorgabe von Dolphin) gilt als nichts eingestellt
    if keymap_once("dolphin", "pad", cur, wanted, ctx["custom"]):
        ini_update(path, "GCPad1", wanted)
        log("Dolphin: Controller-Belegung", wanted)


# -- Flycast 2.7 (Flatpak, SDL2-Joystick; mappings/SDL_<Name>.cfg, core/input/mapping.cpp, sdl/sdl.cpp)
FLYCAST_MAPPINGS = Path.home() / ".var/app/org.flycast.Flycast/config/flycast/mappings"
FLYCAST_KEYS = {"A": "btn_a", "B": "btn_b", "X": "btn_x", "Y": "btn_y", "Start": "btn_start",
                "Up": "btn_dpad1_up", "Down": "btn_dpad1_down", "Left": "btn_dpad1_left", "Right": "btn_dpad1_right",
                "L": "trigger_left", "R": "trigger_right"}


def flycast_file(name):
    """GamepadDevice::make_mapping_filename: "SDL_" + Name, Sonderzeichen -> "-"."""
    return FLYCAST_MAPPINGS / ("SDL_" + re.sub(r'[/\\\\:?*|"<>]', "-", name) + ".cfg")


def flycast_text(ctx, name):
    dig, ana, trig = [], [], []
    for b, opt in FLYCAST_KEYS.items():
        raw = bind_raw(ctx, ctx["bmap"].get(b))
        if not raw:
            continue
        if raw[0] == "button":
            dig.append(f"{raw[1]}:{'btn_' + opt if opt.startswith('trigger') else opt}")
        elif raw[0] == "hat":                     # sdl.cpp: (Hat + 1) << 8 | hoch 0, runter 1, links 2, rechts 3
            dig.append(f"{(1 << 8) | ['up', 'down', 'left', 'right'].index(raw[1])}:"
                       f"{'btn_' + opt if opt.startswith('trigger') else opt}")
        elif opt.startswith("trigger"):
            ana.append(f"{raw[1]}{'+' if raw[2] > 0 else '-'}:axis_{opt}")
            trig.append(str(raw[1]))
        else:                                     # Taste auf einer Achse kennt Flycast so nicht -> frei
            log(f"Flycast: {b} auf einer Achse wird nicht unterstuetzt")
    sel = ctx["roles"].get("select")              # Select oeffnet das Flycast-Menue (wie Flycasts eigene Vorgabe)
    raw = bind_raw(ctx, sel)
    if raw and raw[0] == "button" and not any(x.startswith(f"{raw[1]}:") for x in dig):
        dig.append(f"{raw[1]}:btn_menu")
    st = stick_axes(ctx)
    if "lx" in st and "ly" in st:
        ana += [f"{st['lx']}-:axis_left", f"{st['lx']}+:axis_right", f"{st['ly']}-:axis_up", f"{st['ly']}+:axis_down"]
    lines = ["[emulator]", f"mapping_name = {name}", "dead_zone = 10", "saturation = 100", "rumble_power = 100",
             "version = 4"] + ([f"triggers = {','.join(trig)}"] if trig else [])
    lines += ["", "[digital]"] + [f"bind{i} = {x}" for i, x in enumerate(dig)]
    lines += ["", "[analog]"] + [f"bind{i} = {x}" for i, x in enumerate(ana)]
    return "\n".join(lines) + "\n"


def flycast_prepare(ctx):
    name = ctx["sdl"].get("name") or ctx["pad"]["name"]
    path = flycast_file(name)
    text = flycast_text(ctx, name)
    cur = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    if keymap_once("flycast", "pad", {"file": cur or None}, {"file": text}, ctx["custom"]):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        log("Flycast: Controller-Belegung", path.name)


# -- BIOS: je System ein eigener Ordner share/ROMs/<system>/bios, vom PC aus befuellt. Jeder Emulator liest nur
# seinen Ordner – so kommen sich gleich grosse Dateien verschiedener Konsolen nicht in die Quere (Saturn- und
# PS1-BIOS haben beide 512 KiB, die DS-Firmware so viel wie ein Xbox-Flash). VoidStation stellt den Emulator vor dem
# Start darauf ein, solange er in seinem eigenen Ordner bzw. Pfad nichts Brauchbares findet. Erkannt wird wie in den
# Emulatoren selbst, der Name ist egal (ausser bei Flycast):
#   PlayStation 512 KiB (DuckStation bios.h) · PlayStation 2 4–8 MiB (PCSX2 BiosTools.cpp) · Xbox: MCPX-Boot-ROM
#   512 Byte, Flash-BIOS 256 KiB oder 1 MiB, Festplatte .qcow2 (xemu) · Dreamcast: dc_boot.bin bzw. dc_bios.bin
#   (Flycast 2.7 sucht nur nach dem Namen, nvmem.cpp) · DS: ARM9 4 KiB, ARM7 16 KiB, Firmware 128/256/512 KiB
#   (melonDS 1.1 verifyDSBIOS/verifyDSFirmware) · GBA 16 KiB mit Sprungtabelle (mGBA GBAIsBIOS) · Game Boy (Color)
#   Boot-ROMs nach CRC32 (mGBA GBIsBIOS).
# In jedem Ordner liegt ein Hinweis in der Sprache der Oberflaeche, ob das BIOS noetig oder optional ist (bios_sync).
ROMS_DIR = Path.home() / "share" / "ROMs"
BIOS_OLD = Path.home() / "share" / "BIOS"        # bis Oktober 2026 ein gemeinsamer Ordner – bios_migrate raeumt ihn auf
BIOS_SYSTEMS = {"psx": True, "ps2": True, "xbox": True,                       # Ordner -> Pflicht?
                "dreamcast": False, "nds": False, "gba": False, "gbc": False, "saturn": True, "pcengine": False}
BIOS_NOT = {".txt", ".md", ".nfo", ".url", ".htm", ".html", ".pdf", ".jpg", ".jpeg", ".png", ".ini", ".cfg", ".zip",
            ".7z", ".rar"}                       # Hinweise und Beiwerk zaehlen nie als BIOS (z. B. 512-Byte-Textdatei)
GB_BOOT = {0xC2F5CC97: "gb", 0x59C8598E: "gb", 0xE6920754: "gb", 0xEC8A83B9: "sgb", 0x53D0DD63: "sgb",
           0x41884E46: "gbc", 0xE8EF5318: "gbc", 0xE95DC95D: "gbc", 0xFFD6B0F1: "gbc", 0x570337EA: "gbc"}


def _gba_bios(f):
    """mGBA GBAIsBIOS: die ersten 7 Woerter sind ARM-Sprungbefehle (…xx 00 EA)."""
    try:
        with open(f, "rb") as fh:
            t = fh.read(28)
    except OSError:
        return False
    return len(t) == 28 and all(t[4 * i + 3] == 0xEA and t[4 * i + 2] == 0 for i in range(7))


def _gb_boot(f, n):
    """Game-Boy-Boot-ROM nach CRC32 wie mGBA: "gb" (DMG/MGB), "sgb" oder "gbc" (CGB/AGB), sonst None."""
    if not 0 < n <= 0x4000:
        return None
    try:
        return GB_BOOT.get(zlib.crc32(f.read_bytes()) & 0xFFFFFFFF)
    except OSError:
        return None


# Saturn: SHA-256 der BIOS-Fassungen, die Mednafen kennt (ss/ss.cpp BIOSDB) – Japan bzw. Nordamerika/Europa
SS_BIOS = {"cc1e1b7f88f1c6e6fc35994bae2c2292e06fdae258c79eb26a1f1391e72914a8": "jp",
           "ae4058627bb5db9be6d8d83c6be95a4aa981acc8a89042e517e73317886c8bc2": "jp",
           "dcfef4b99605f872b6c3b6d05c045385cdea3d1b702906a0ed930df7bcb7deac": "jp",
           "87293093fad802fcff31fcab427a16caff1acbc5184899b8383b360fd58efb73": "eu",
           "96e106f740ab448cf89f0dd49dfbac7fe5391cb6bd6e14ad5e3061c13330266f": "eu"}


def _ss_bios(f, n):
    if n != 0x80000:
        return None
    try:
        return SS_BIOS.get(hashlib.sha256(f.read_bytes()).hexdigest())
    except OSError:
        return None


BIOS_KINDS = {  # Art -> (Ordner unter share/ROMs, Test(Datei, Groesse))
    "psx": ("psx", lambda f, n: n == 0x80000),
    # PS2: Hauptteil (.bin, vom Dumper oft .ROM0); .rom1/.rom2/.erom (DVD-Player usw.) laedt PCSX2 selbst dazu
    "ps2": ("ps2", lambda f, n: 4 << 20 <= n <= 8 << 20 and f.suffix.lower() not in (
        ".qcow2", ".iso", ".chd", ".rom1", ".rom2", ".erom", ".diff", ".mec", ".nvm")),
    "mcpx": ("xbox", lambda f, n: n == 512),
    "flash": ("xbox", lambda f, n: n in (0x40000, 0x100000)),
    "hdd": ("xbox", lambda f, n: f.suffix.lower() == ".qcow2"),
    "dc": ("dreamcast", lambda f, n: f.name in ("dc_boot.bin", "dc_bios.bin")),
    "bios9": ("nds", lambda f, n: n == 0x1000),
    "bios7": ("nds", lambda f, n: n == 0x4000),
    "firmware": ("nds", lambda f, n: n in (0x20000, 0x40000, 0x80000)),
    "gba": ("gba", lambda f, n: n == 0x4000 and _gba_bios(f)),
    "gb": ("gbc", lambda f, n: _gb_boot(f, n) == "gb"),
    "sgb": ("gbc", lambda f, n: _gb_boot(f, n) == "sgb"),
    "gbc": ("gbc", lambda f, n: _gb_boot(f, n) == "gbc"),
    "ss_jp": ("saturn", lambda f, n: _ss_bios(f, n) == "jp"),
    "ss_eu": ("saturn", lambda f, n: _ss_bios(f, n) == "eu"),
    "pcecd": ("pcengine", lambda f, n: n in (0x40000, 0x40200)),       # System Card, mit oder ohne 512-Byte-Kopf
}


def bios_dir(system):
    return ROMS_DIR / system / "bios"


def bios_find(kind, root=None, deep=True):
    """Dateien einer Art im bios-Ordner ihres Systems (bzw. root), mit einer Ebene Unterordnern; oben vor tief,
    nach Name."""
    system, test = BIOS_KINDS[kind]
    root = Path(root) if root else bios_dir(system)
    out = []
    try:
        level = [root]
        for _ in range(2 if deep else 1):
            nxt = []
            for d in level:
                for f in sorted(d.iterdir(), key=lambda x: x.name.casefold()):
                    if f.name.startswith("."):
                        continue
                    if f.is_dir():
                        nxt.append(f)
                    elif f.is_file() and f.suffix.lower() not in BIOS_NOT and test(f, f.stat().st_size):
                        out.append(f)
            level = nxt
    except OSError:
        pass
    return out


def portal_path(p):
    """Pfad aus dem Dokumenten-Portal (Dateidialog eines Flatpaks: <Laufzeitordner>/doc/<id>/…)? Von aussen erreichbar,
    im Flatpak aber nicht (VoidStation hat einen eigenen Laufzeitordner) – solche Pfade gelten als nicht gesetzt."""
    s = str(p)
    roots = {os.environ.get("XDG_RUNTIME_DIR", ""), f"/run/user/{os.getuid()}", f"/tmp/voidstation-runtime-{os.getuid()}"}
    return any(r and s.startswith(r.rstrip("/") + "/doc/") for r in roots) or s.startswith("/run/flatpak/doc/")


def bios_dir_has(kind, d):
    return bool(d) and not portal_path(d) and Path(d).is_dir() and bool(bios_find(kind, d, deep=False))


# Je Kachel: was gebraucht wird und wo der Emulator gerade sucht (Ordner bzw. Datei je Art)
def _duck_bios_dir():
    v = ini_read(DUCK_INI).get("BIOS", {}).get("SearchDirectory", "bios") or "bios"
    p = Path(v).expanduser()
    return p if p.is_absolute() else DUCK_INI.parent / p


def _pcsx2_bios_dir():
    v = ini_read(PCSX2_INI).get("Folders", {}).get("Bios", "bios") or "bios"
    p = Path(v).expanduser()
    return p if p.is_absolute() else PCSX2_INI.parent.parent / p


def bios_status(tile):
    """Fuer die Spieleliste: {"ok", "missing": [Art …], "folder"} – None, wenn der Emulator kein BIOS braucht
    (optionale BIOS-Dateien melden nichts: es fehlt ja nichts)."""
    tile = {v: k for k, v in ROMS.TILE_TO_SYSTEM.items()}.get(tile, tile)      # auch Ordnername erlaubt
    emu_paths_refresh()
    if tile == "duckstation":
        ok = bios_dir_has("psx", _duck_bios_dir()) or bios_dir_has("ps2", _duck_bios_dir()) or bool(bios_find("psx"))
        return {"ok": ok, "missing": [] if ok else ["bios"], "folder": "psx"}
    if tile == "pcsx2":
        ok = bios_dir_has("ps2", _pcsx2_bios_dir()) or bool(bios_find("ps2"))
        return {"ok": ok, "missing": [] if ok else ["bios"], "folder": "ps2"}
    if tile == "xemu":
        files = xemu_files(xemu_load())
        miss = [k for k in ("mcpx", "flash", "hdd") if not files.get(k) and not bios_find(k)]
        return {"ok": not miss, "missing": miss, "folder": "xbox"}
    if tile == "mednafen":                             # nur der Saturn braucht ein BIOS – melden, sobald Spiele da sind
        if not ROMS.scan(ROMS.rom_dir / "saturn", set(ROMS.EXTENSIONS["saturn"])):
            return None
        cur = mednafen_read({"filesys.path_firmware", "ss.bios_jp", "ss.bios_na_eu"})
        fw = Path(cur.get("filesys.path_firmware") or "firmware").expanduser()
        fw = fw if fw.is_absolute() else MEDNAFEN_DIR / fw
        ok = bool(bios_find("ss_jp") or bios_find("ss_eu")) or any(
            (f if f.is_absolute() else fw / f).is_file()
            for f in (Path(cur.get(k) or d).expanduser() for k, d in (("ss.bios_jp", "sega_101.bin"), ("ss.bios_na_eu", "mpr-17933.bin"))))
        return {"ok": ok, "missing": [] if ok else ["bios"], "folder": "saturn"}
    return None


def bios_prepare(tile):
    """Vor dem Start: Emulator auf seinen bios-Ordner stellen, wenn er selbst nichts findet."""
    with EMU_LOCK:
        if tile == "duckstation" and duck_ready():
            cur = _duck_bios_dir()
            if not (bios_dir_has("psx", cur) or bios_dir_has("ps2", cur)):
                hit = (bios_find("psx") or [None])[0]
                if hit:
                    ini_update(DUCK_INI, "BIOS", {"SearchDirectory": str(hit.parent)})
                    log("DuckStation: BIOS aus", hit.parent)
        elif tile == "pcsx2" and pcsx2_ready():
            cur = _pcsx2_bios_dir()
            if not bios_dir_has("ps2", cur):
                hit = (bios_find("ps2") or [None])[0]
                if hit:
                    ini_update(PCSX2_INI, "Folders", {"Bios": str(hit.parent)})
                    log("PCSX2: BIOS aus", hit.parent)
                    cur = hit.parent
            # Gewaehltes BIOS ([Filenames] BIOS): fehlt es oder liegt es nicht im Ordner (Einrichtung ohne BIOS
            # abgeschlossen, Datei umbenannt), das erste aus dem Ordner nehmen
            name = ini_read(PCSX2_INI).get("Filenames", {}).get("BIOS", "")
            have = bios_find("ps2", cur, deep=False) if Path(cur).is_dir() else []
            if have and not any(f.name == name for f in have):
                ini_update(PCSX2_INI, "Filenames", {"BIOS": have[0].name})
                log("PCSX2: BIOS-Datei", have[0].name)
        elif tile == "xemu":
            xemu_bios()
        elif tile == "gba":
            mgba_bios()
        elif tile == "melonds":
            melonds_bios()
        elif tile == "flycast":
            flycast_bios()
        elif tile == "mednafen":
            mednafen_bios()


# mGBA 0.10: [ports.qt] gba.bios / gb.bios / sgb.bios / gbc.bios (SettingsView.cpp), Rueckfall <config>/<art>_bios.bin
# (gba/core.c, gb/core.c). Ob das Startlogo laeuft ("useBios", "skipBios"), bleibt mGBAs Sache.
MGBA_BIOS = {"gba": "gba.bios", "gb": "gb.bios", "sgb": "sgb.bios", "gbc": "gbc.bios"}


def mgba_bios():
    cur = ini_read(MGBA_CONFIG).get("ports.qt", {})
    todo = {}
    for kind, key in MGBA_BIOS.items():
        if cur.get(key) and Path(cur[key]).is_file():
            continue                                  # in mGBA eingestellt (oder schon von VoidStation) und da
        if (MGBA_CONFIG.parent / f"{kind}_bios.bin").is_file():
            continue                                  # mGBAs eigener Ordner
        hit = (bios_find(kind) or [None])[0]
        if hit:
            todo[key] = str(hit)
    if todo:
        ini_update(MGBA_CONFIG, "ports.qt", todo)
        log("mGBA: BIOS", todo)


# melonDS 1.1: [Emu] ExternalBIOSEnable, [DS] BIOS9Path/BIOS7Path/FirmwarePath (Config.cpp). Mit eigenem BIOS braucht
# melonDS alle drei, sonst startet es gar nicht (verifySetup) – deshalb nur einschalten, wenn alle drei da sind, und
# wieder aus, wenn VoidStation es eingeschaltet hatte und sie fehlen. Selbst in melonDS eingerichtet: bleibt.
def melonds_bios():
    import tomllib
    if not MELONDS_TOML.exists() and (MELONDS_TOML.parent / "melonDS.ini").exists():
        return                                        # alte ini: melonDS uebernimmt sie selbst beim ersten Start
    try:
        root = tomllib.loads(MELONDS_TOML.read_text(encoding="utf-8")) if MELONDS_TOML.exists() else {}
    except (OSError, ValueError) as e:
        log("melonDS.toml nicht lesbar, BIOS bleibt:", e)
        return
    emu, ds = root.setdefault("Emu", {}), root.setdefault("DS", {})
    st = emu_state_load()
    mine = bool(st.get("melonds", {}).get("bios"))
    hits = {k: (bios_find(k) or [None])[0] for k in ("bios9", "bios7", "firmware")}
    changed = False
    if all(hits.values()):
        if emu.get("ExternalBIOSEnable") and not mine:
            return                                    # in melonDS selbst eingerichtet
        want = {"BIOS9Path": str(hits["bios9"]), "BIOS7Path": str(hits["bios7"]),
                "FirmwarePath": str(hits["firmware"])}
        if any(ds.get(k) != v for k, v in want.items()) or emu.get("ExternalBIOSEnable") is not True:
            ds.update(want)
            emu["ExternalBIOSEnable"] = True
            changed = True
            log("melonDS: BIOS und Firmware", want)
        st.setdefault("melonds", {})["bios"] = True
    elif mine:
        emu["ExternalBIOSEnable"] = False             # Dateien weg: zurueck zum eingebauten BIOS
        st.setdefault("melonds", {}).pop("bios", None)
        changed = True
        log("melonDS: BIOS-Dateien fehlen – eingebautes BIOS")
    if not changed:
        emu_state_save(st)
        return
    try:
        text = toml_dump(root)
    except ValueError as e:
        log("melonDS.toml: unbekannter Aufbau, BIOS bleibt:", e)
        return
    MELONDS_TOML.parent.mkdir(parents=True, exist_ok=True)
    tmp = MELONDS_TOML.with_suffix(".vs-tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(MELONDS_TOML)
    emu_state_save(st)


# Flycast 2.7: emu.cfg [config] Dreamcast.BiosPath (Liste mit ";", option.h), sucht dort zuerst dc_boot.bin bzw.
# dc_bios.bin (oslib.cpp findFlash) – nur im Ordner selbst, nicht darunter.
FLYCAST_CFG = Path.home() / ".var/app/org.flycast.Flycast/config/flycast/emu.cfg"


def flycast_bios():
    d = bios_dir("dreamcast")
    if not bios_find("dc", deep=False):
        return
    cur = ini_read(FLYCAST_CFG).get("config", {}).get("Dreamcast.BiosPath", "")
    if str(d) in [p.strip().strip('"') for p in cur.split(";")]:
        return
    ini_update_spaced(FLYCAST_CFG, "config", {"Dreamcast.BiosPath": f"{cur};{d}" if cur else str(d)})
    log("Flycast: BIOS-Ordner", d)


def bios_migrate():
    """Alter gemeinsamer Ordner share/BIOS: PlayStation-, PS2- und Xbox-Dateien (mehr stand dort nie beschrieben) und
    Dreamcast-BIOS nach Namen in den Ordner ihres Systems verschieben. Was nicht eindeutig ist, bleibt liegen; ein
    leerer Ordner verschwindet. Die Emulatoren stellt bios_prepare beim naechsten Start auf den neuen Ort."""
    if not BIOS_OLD.is_dir():
        return
    for kind in ("psx", "ps2", "mcpx", "flash", "hdd", "dc"):
        for f in bios_find(kind, BIOS_OLD):
            if kind == "flash" and "firm" in f.name.lower():
                continue                              # 256 KiB: eher DS-Firmware – lieber liegen lassen
            dest = bios_dir(BIOS_KINDS[kind][0])
            try:
                dest.mkdir(parents=True, exist_ok=True)
                t = dest / f.name
                if t.exists():
                    if t.stat().st_size == f.stat().st_size and t.read_bytes() == f.read_bytes():
                        f.unlink()
                    continue
                shutil.move(str(f), str(t))
                log("BIOS verschoben:", f, "->", t)
            except OSError as e:
                log("BIOS nicht verschoben:", f, e)
    for d in sorted((p for p in BIOS_OLD.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)) + [BIOS_OLD]:
        try:
            d.rmdir()                                 # nur, wenn leer
        except OSError:
            pass


_I18N: dict = {}


def i18n_text(key, lang):
    """Text aus web/i18n wie in der Oberflaeche: Sprache, dann Englisch, dann Deutsch."""
    for l in (lang, "en", "de"):
        if l not in _I18N:
            try:
                _I18N[l] = json.loads((WEB / "i18n" / f"{l}.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                _I18N[l] = {}
        if key in _I18N[l]:
            return _I18N[l][key]
    return ""


BIOS_SYNC_LOCK = threading.Lock()


def bios_sync():
    """Beim Start und nach einem Sprachwechsel: alten Ordner share/BIOS aufloesen, je System einen bios-Ordner mit
    Hinweis anlegen ("BIOS noetig – LIESMICH.txt" bzw. "BIOS optional – …", in der Sprache der Oberflaeche). Fassungen
    in anderen Sprachen raeumt er weg; andere Dateien im Ordner bleiben unberuehrt."""
    with BIOS_SYNC_LOCK:
        try:
            bios_migrate()
        except Exception as e:  # noqa: BLE001 – darf den Start nie stoeren
            log("BIOS: alter Ordner:", e)
        lang = ui_lang()
        names = {i18n_text(f"bios.file.{k}", l["id"]) for l in LANGS for k in ("req", "opt")} - {""}
        for system, req in BIOS_SYSTEMS.items():
            if not (ROMS_DIR / system).is_dir():
                continue
            d = bios_dir(system)
            name = i18n_text("bios.file." + ("req" if req else "opt"), lang)
            body = i18n_text(f"bios.readme.{system}", lang)
            if not name or not body:
                continue
            data = (body.replace("\r\n", "\n").replace("\n", "\r\n") + "\r\n").encode("utf-8")   # auch fuer Windows
            try:
                d.mkdir(exist_ok=True)
                for old in names - {name}:
                    (d / old).unlink(missing_ok=True)
                f = d / name
                if not f.exists() or f.read_bytes() != data:
                    f.write_bytes(data)
            except OSError as e:
                log(f"BIOS-Hinweis {system}:", e)


# -- PCSX2 2.8 (Flatpak, SDL3-Gamepad; inis/PCSX2.ini [Pad1], pcsx2/Input/SDLInputSource.cpp, SIO/Pad/PadDualshock2.cpp)
PCSX2_INI = Path.home() / ".var/app/net.pcsx2.PCSX2/config/PCSX2/inis/PCSX2.ini"
PCSX2_GC = {"a": "FaceSouth", "b": "FaceEast", "x": "FaceWest", "y": "FaceNorth", "back": "Back", "start": "Start",
            "l3": "LeftStick", "r3": "RightStick", "lb": "LeftShoulder", "rb": "RightShoulder", "up": "DPadUp",
            "down": "DPadDown", "left": "DPadLeft", "right": "DPadRight", "lt": "+LeftTrigger", "rt": "+RightTrigger"}


def pcsx2_name(ctx, b):
    """ConvertKeyToString: "SDL-0/FaceSouth", roh "SDL-0/JoyButton3", "SDL-0/+JoyAxis2", "SDL-0/Hat0North"."""
    role = bind_role(b, ctx["roles"])
    if role:
        return f"SDL-0/{PCSX2_GC[GC_ROLE[role]]}"
    raw = bind_raw(ctx, b)
    if not raw:
        return None
    if raw[0] == "button":
        return f"SDL-0/JoyButton{raw[1]}"
    if raw[0] == "axis":
        return f"SDL-0/{'+' if raw[2] > 0 else '-'}JoyAxis{raw[1]}"
    return f"SDL-0/Hat0{DUCK_HAT[raw[1]]}"


def pcsx2_ready():
    """PCSX2 eingerichtet (PCSX2.ini da, Einrichtungsassistent durch)? Vorher behandelt PCSX2 die Datei als neu."""
    ini = ini_read(PCSX2_INI)
    return "Pad1" in ini and ini.get("UI", {}).get("SetupWizardIncomplete", "false").lower() != "true"


def pcsx2_prepare(ctx):
    if not pcsx2_ready():
        log("PCSX2: noch nicht eingerichtet – Belegung beim naechsten Start")
        return
    wanted = {b: pcsx2_name(ctx, ctx["bmap"].get(b)) for b, _ in EMU_LAYOUTS["pcsx2"]["buttons"] if b not in EMU_ACTIONS}
    wanted.update({"LLeft": "SDL-0/-LeftX", "LRight": "SDL-0/+LeftX", "LUp": "SDL-0/-LeftY", "LDown": "SDL-0/+LeftY",
                   "RLeft": "SDL-0/-RightX", "RRight": "SDL-0/+RightX", "RUp": "SDL-0/-RightY",
                   "RDown": "SDL-0/+RightY"})
    is_sdl = lambda v: v.startswith("SDL-")
    cur = ini_multi_get(PCSX2_INI, "Pad1", list(wanted), is_sdl)
    if keymap_once("pcsx2", "pad", cur, wanted, ctx["custom"]):
        ini_multi_set(PCSX2_INI, "Pad1", wanted, is_sdl)
        log("PCSX2: Controller-Belegung", wanted)
    hk = ini_read(PCSX2_INI).get("Hotkeys", {})
    if not hk.get("HoldTurbo"):                   # Vorspulen halten (EMU_KEYS) – PCSX2 gibt dafuer nichts vor
        ini_update(PCSX2_INI, "Hotkeys", {"HoldTurbo": "Keyboard/Tab"})


# -- Rosalie's Mupen GUI 0.9 (Flatpak, SDL3; RMG/mupen64plus.cfg, RMG-Input/main.cpp, RMG-Core/Settings.cpp)
RMG_CFG = Path.home() / ".var/app/com.github.Rosalie241.RMG/config/RMG/mupen64plus.cfg"
RMG_SECTION = "Rosalie's Mupen GUI - Input Plugin Profile 0"
RMG_KEYS = {"A": "A", "B": "B", "Z": "ZTrigger", "L": "LeftShoulder", "R": "RightShoulder", "Start": "Start",
            "CUp": "CButtonUp", "CDown": "CButtonDown", "CLeft": "CButtonLeft", "CRight": "CButtonRight",
            "Up": "DpadUp", "Down": "DpadDown", "Left": "DpadLeft", "Right": "DpadRight"}
# SDL_GamepadButton bzw. SDL_GamepadAxis (SDL3, gleiche Nummern wie SDL2) und deren Namen
SDL_GC_BUTTON = {"a": 0, "b": 1, "x": 2, "y": 3, "back": 4, "guide": 5, "start": 6, "l3": 7, "r3": 8, "lb": 9, "rb": 10,
                 "up": 11, "down": 12, "left": 13, "right": 14}
SDL_GC_BUTTON_NAME = {"a": "a", "b": "b", "x": "x", "y": "y", "back": "back", "start": "start", "l3": "leftstick",
                      "r3": "rightstick", "lb": "leftshoulder", "rb": "rightshoulder", "up": "dpup", "down": "dpdown",
                      "left": "dpleft", "right": "dpright"}
SDL_GC_AXIS = {"lt": 4, "rt": 5}
STICK_AXIS = {"rs_up": (3, 0), "rs_down": (3, 1), "rs_left": (2, 0), "rs_right": (2, 1)}   # (Achse, 1 = positiv)
SDL_HAT_MASK = {"up": 1, "right": 2, "down": 4, "left": 8}


def stick_role(b, roles):
    return next((r for r in STICK_ROLES if roles.get(r) == b), "") if b else ""


def rmg_mapping(ctx, b):
    """-> (InputType, Name, Data, ExtraData) als Texte; InputType: 0 Gamepad-Taste, 1 Gamepad-Achse,
    2 Joystick-Taste, 3 Joystick-Achse, 4 Joystick-Hat (RMG-Input common.hpp). Frei: alles leer."""
    role = bind_role(b, ctx["roles"])
    if role:
        gc = GC_ROLE[role]
        if gc in SDL_GC_AXIS:
            return ("1", ("lefttrigger" if gc == "lt" else "righttrigger") + "+", str(SDL_GC_AXIS[gc]), "1")
        return ("0", SDL_GC_BUTTON_NAME[gc], str(SDL_GC_BUTTON[gc]), "0")
    st = stick_role(b, ctx["roles"])
    if st:
        ax, pos = STICK_AXIS[st]
        return ("1", ("rightx" if ax == 2 else "righty") + ("+" if pos else "-"), str(ax), str(pos))
    raw = bind_raw(ctx, b)
    if not raw:
        return ("", "", "", "")
    if raw[0] == "button":
        return ("2", f"button {raw[1]}", str(raw[1]), "0")
    if raw[0] == "axis":
        return ("3", f"axis {raw[1]}{'+' if raw[2] > 0 else '-'}", str(raw[1]), "1" if raw[2] > 0 else "0")
    return ("4", f"hat 0 {raw[1]}", "0", str(SDL_HAT_MASK[raw[1]]))


def m64_str(v):
    return '"' + str(v).replace('"', "") + '"'


def rmg_prepare(ctx):
    sec = ini_read(RMG_CFG).get(RMG_SECTION, {})
    wanted = {}
    for b, key in RMG_KEYS.items():
        t, name, data, extra = rmg_mapping(ctx, ctx["bmap"].get(b))
        wanted.update({f"{key}_InputType": m64_str(t), f"{key}_Name": m64_str(name), f"{key}_Data": m64_str(data),
                       f"{key}_ExtraData": m64_str(extra)})
    for key, ax, pos in (("AnalogStickUp", 1, 0), ("AnalogStickDown", 1, 1), ("AnalogStickLeft", 0, 0),
                         ("AnalogStickRight", 0, 1)):
        wanted.update({f"{key}_InputType": '"1"', f"{key}_Name": m64_str(("leftx" if ax == 0 else "lefty") + "-+"[pos]),
                       f"{key}_Data": m64_str(ax), f"{key}_ExtraData": m64_str(pos)})
    cur = {k: sec[k] for k in wanted if k in sec}
    # Ohne Abschnitt ist bei RMG kein Controller eingesteckt – dann alles anlegen ("Automatic": erstes Gamepad)
    plugged = sec.get("PluggedIn", "False") == "True" and sec.get("DeviceType") in ("2", "4")
    if keymap_once("rmg", "pad", cur, wanted, ctx["custom"] or not plugged):
        base = {} if plugged else {"PluggedIn": "True", "DeviceName": '"Automatic"', "DeviceType": "2",
                                   "DevicePath": '""', "DeviceSerial": '""', "Deadzone": "9", "Sensitivity": "100",
                                   "Pak": "0", "RemoveDuplicateMappings": "True", "FilterEventsForButtons": "True",
                                   "FilterEventsForAxis": "True"}
        ini_update_spaced(RMG_CFG, RMG_SECTION, {**base, **wanted})
        log("RMG: Controller-Belegung", {k: wanted[k] for k in wanted if k.endswith("_Name")})


def ini_update_spaced(path, section, values):
    """ini_update fuer Dateien im Stil "Schluessel = Wert" (mupen64plus.cfg): vorhandene Zeilen bleiben, wie sie sind."""
    ini_update(path, section, values)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    out, sec = [], None
    for line in lines:
        t = line.strip()
        if t.startswith("[") and t.endswith("]"):
            sec = t[1:-1]
        elif sec == section and "=" in line and " = " not in line:
            k, _, v = line.partition("=")
            if k.strip() in values:
                line = f"{k.strip()} = {v.strip()}"
        out.append(line)
    tmp = path.with_name(path.name + ".vs-tmp")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    tmp.replace(path)


# -- xemu 0.8 (Flatpak, SDL3-Gamepad; xemu.toml, config_spec.yml, ui/xemu-input.c) – auch BIOS-Pfade und Savestate-Taste
XEMU_TOML = Path.home() / ".var/app/app.xemu.xemu/data/xemu/xemu/xemu.toml"
XEMU_KEYS = {"A": "a", "B": "b", "X": "x", "Y": "y", "White": "lshoulder", "Black": "rshoulder", "Back": "back",
             "Start": "start", "LS": "lstick_btn", "RS": "rstick_btn", "Up": "dpad_up", "Down": "dpad_down",
             "Left": "dpad_left", "Right": "dpad_right"}
XEMU_DEFAULT = {"a": 0, "b": 1, "x": 2, "y": 3, "back": 4, "guide": 5, "start": 6, "lstick_btn": 7, "rstick_btn": 8,
                "lshoulder": 9, "rshoulder": 10, "dpad_up": 11, "dpad_down": 12, "dpad_left": 13, "dpad_right": 14,
                "axis_left_x": 0, "axis_left_y": 1, "axis_right_x": 2, "axis_right_y": 3, "axis_trigger_left": 4,
                "axis_trigger_right": 5}
XEMU_SNAPSHOT = "VoidStation"


def xemu_load():
    import tomllib
    try:
        return tomllib.loads(XEMU_TOML.read_text(encoding="utf-8")) if XEMU_TOML.exists() else {}
    except (OSError, ValueError) as e:
        log("xemu.toml nicht lesbar:", e)
        return None


def xemu_files(root):
    """Gesetzte und vorhandene Dateien aus [sys.files] -> {"mcpx", "flash", "hdd"}."""
    f = ((root or {}).get("sys") or {}).get("files") or {}
    out = {}
    for k, key in (("mcpx", "bootrom_path"), ("flash", "flashrom_path"), ("hdd", "hdd_path")):
        v = f.get(key)
        if isinstance(v, str) and v and not portal_path(v) and Path(v).is_file():
            out[k] = v
    return out


def xemu_mapping(ctx):
    """controller_mapping fuer den ersten Controller: Xbox-Taste -> SDL-Gamepad-Taste (-1 = frei). xemu kann nur
    Gamepad-Tasten tauschen; LT/RT nur auf Trigger-Achsen."""
    m = {}
    for b, key in XEMU_KEYS.items():
        bind = ctx["bmap"].get(b)
        gc = GC_ROLE.get(bind_role(bind, ctx["roles"]), "")
        if gc in SDL_GC_BUTTON:
            m[key] = SDL_GC_BUTTON[gc]
        else:
            if bind:
                log(f"xemu: {b} geht nur auf eine Controllertaste – bleibt frei")
            m[key] = -1
    for b, key, dflt in (("LT", "axis_trigger_left", 4), ("RT", "axis_trigger_right", 5)):
        bind = ctx["bmap"].get(b)
        gc = GC_ROLE.get(bind_role(bind, ctx["roles"]), "")
        m[key] = SDL_GC_AXIS[gc] if gc in SDL_GC_AXIS else (-1 if not bind else dflt)
    return m


def xemu_prepare(ctx):
    root = xemu_load()
    if root is None:
        return
    changed = False
    # Savestates: F5 auf einen Schnappschuss legen (F5 laden, Umschalt+F5 speichern, s. EMU_KEYS)
    sc = root.setdefault("general", {}).setdefault("snapshots", {}).setdefault("shortcuts", {})
    if not sc.get("f5"):
        sc["f5"] = XEMU_SNAPSHOT
        changed = True
    guid = (ctx.get("sdl") or {}).get("guid", "")
    if guid:
        maps = root.setdefault("input", {}).setdefault("gamepad_mappings", [])
        ent = next((m for m in maps if isinstance(m, dict) and m.get("gamepad_id") == guid), None)
        cm = dict(XEMU_DEFAULT, **((ent or {}).get("controller_mapping") or {}))
        wanted = xemu_mapping(ctx)
        cur = {k: cm.get(k) for k in wanted}
        stock = {k: XEMU_DEFAULT[k] for k in wanted}
        if keymap_once("xemu", "pad", cur, wanted, ctx["custom"] or cur == stock):
            if ent is None:
                ent = {"gamepad_id": guid}
                maps.append(ent)
            ent.setdefault("controller_mapping", {}).update(wanted)
            changed = True
            log("xemu: Controller-Belegung", wanted)
    if changed:
        xemu_save(root)


def xemu_save(root):
    try:
        text = toml_dump(root)
    except ValueError as e:
        log("xemu.toml: unbekannter Aufbau, bleibt:", e)
        return
    XEMU_TOML.parent.mkdir(parents=True, exist_ok=True)
    tmp = XEMU_TOML.with_suffix(".vs-tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(XEMU_TOML)


def xemu_bios():
    """BIOS-Dateien aus share/ROMs/xbox/bios, wo xemu noch nichts (Vorhandenes) eingetragen hat – auch ohne
    Controller (die Belegung schreibt xemu_prepare nur mit einem)."""
    root = xemu_load()
    if root is None:
        return
    files = root.setdefault("sys", {}).setdefault("files", {})
    have = xemu_files(root)
    changed = False
    for k, key in (("mcpx", "bootrom_path"), ("flash", "flashrom_path"), ("hdd", "hdd_path")):
        hit = (bios_find(k) or [None])[0]
        if k not in have and hit:
            files[key] = str(hit)
            changed = True
            log(f"xemu: {key} =", hit)
    if changed:
        xemu_save(root)


# -- Azahar 2126 (Flatpak, SDL2-GameController; azahar-emu/qt-config.ini [Controls] profiles\N\…, QSettings-Format)
AZAHAR_INI = Path.home() / ".var/app/org.azahar_emu.Azahar/config/azahar-emu/qt-config.ini"
AZAHAR_KEYS = {"A": "button_a", "B": "button_b", "X": "button_x", "Y": "button_y", "Up": "button_up",
               "Down": "button_down", "Left": "button_left", "Right": "button_right", "L": "button_l", "R": "button_r",
               "Start": "button_start", "Select": "button_select", "ZL": "button_zl", "ZR": "button_zr"}
# Schnellspeichern/-laden und Turbo (EMU_KEYS): Azahar gibt keine Tasten vor
# (Strg+T ist in Azahar 2126 frei, config.cpp default_hotkeys; F12 gehoert seit 2026.12 dem Bildschirmfoto)
AZAHAR_HOTKEYS = {"Quick Save": "Shift+F1", "Quick Load": "F1", "Toggle Turbo Mode": "Ctrl+T"}
AZAHAR_HOTKEYS_OLD = {"Toggle Turbo Mode": "F12"}      # frueher von VoidStation gesetzt -> umstellen


def azahar_param(ctx, b):
    """ParamPackage (Schluessel alphabetisch, wie Azahar es schreibt). Gamepad-Tasten fuer alle Controller
    (maptype:all), rohe Tasten fuer genau diesen (guid+port)."""
    role = bind_role(b, ctx["roles"])
    if role:
        gc = GC_ROLE[role]
        if gc in SDL_GC_AXIS:
            return f"api:controller,axis:{SDL_GC_AXIS[gc]},direction:+,engine:sdl,guid:0,maptype:all,port:0,threshold:0.5"
        return f"api:controller,button:{SDL_GC_BUTTON[gc]},engine:sdl,guid:0,maptype:all,port:0"
    raw = bind_raw(ctx, b)
    guid = (ctx.get("sdl") or {}).get("guid", "")
    if not raw or not guid:
        return "code:0,engine:keyboard"            # frei (leer hiesse: Azahars Tastatur-Vorgabe)
    if raw[0] == "button":
        return f"button:{raw[1]},engine:sdl,guid:{guid},port:0"
    if raw[0] == "axis":
        return f"axis:{raw[1]},direction:{'+' if raw[2] > 0 else '-'},engine:sdl,guid:{guid},port:0,threshold:0.5"
    return f"direction:{raw[1]},engine:sdl,guid:{guid},hat:0,port:0"


def qt_unquote(v):
    v = (v or "").strip()
    return v[1:-1] if len(v) >= 2 and v[0] == v[-1] == '"' else v


def azahar_prepare(ctx):
    ini = ini_read(AZAHAR_INI)
    ctl = ini.get("Controls", {})
    try:
        idx = int(qt_unquote(ctl.get("profile", "0")) or 0) + 1
        size = int(qt_unquote(ctl.get("profiles\\size", "0")) or 0)
    except ValueError:
        idx, size = 1, 0
    if idx > max(size, 1):
        idx = 1
    pre = f"profiles\\{idx}\\"
    wanted = {pre + k: azahar_param(ctx, ctx["bmap"].get(b)) for b, k in AZAHAR_KEYS.items()}
    wanted[pre + "circle_pad"] = "api:controller,axis_x:0,axis_y:1,deadzone:0.100000,engine:sdl,guid:0,maptype:all,port:0"
    wanted[pre + "c_stick"] = "api:controller,axis_x:2,axis_y:3,deadzone:0.100000,engine:sdl,guid:0,maptype:all,port:0"
    # Wert mit "\default=true" gilt als Vorgabe (Tastatur) – also nichts eingestellt
    cur = {k: (None if ctl.get(k + "\\default", "false") == "true" else qt_unquote(ctl.get(k)) or None) for k in wanted}
    values = {}
    if keymap_once("azahar", "pad", cur, wanted, ctx["custom"]):
        for k, v in wanted.items():
            values[k] = f'"{v}"'
            values[k + "\\default"] = "false"
        if size < 1:
            values.update({"profiles\\size": "1", pre + "name": "Default", pre + "name\\default": "false"})
        values.update({pre + "input_maptype": "0", pre + "input_maptype\\default": "false"})
    if values:
        ini_update(AZAHAR_INI, "Controls", values)
        log("Azahar: Controller-Belegung", {k[len(pre):]: v for k, v in wanted.items()})
    sc = ini_read(AZAHAR_INI).get("Shortcuts", {})
    fix = {}
    for name, keyseq in AZAHAR_HOTKEYS.items():
        k = "Main%20Window\\" + name.replace(" ", "%20") + "\\KeySeq"
        if sc.get(k + "\\default", "true") == "true" or not qt_unquote(sc.get(k)) or \
                qt_unquote(sc.get(k)) == AZAHAR_HOTKEYS_OLD.get(name):
            fix.update({k: keyseq, k + "\\default": "false"})
    if fix:
        ini_update(AZAHAR_INI, "Shortcuts", fix)


# -- Cemu 2.6 (Flatpak, SDL2-GameController; Cemu/controllerProfiles/controller0.xml, input/InputManager.cpp,
#    input/emulated/VPADController.h, input/api/Controller.h)
CEMU_PROFILE = Path.home() / ".var/app/info.cemu.Cemu/config/Cemu/controllerProfiles/controller0.xml"
CEMU_VPAD = {"A": 1, "B": 2, "X": 3, "Y": 4, "L": 5, "R": 6, "ZL": 7, "ZR": 8, "Plus": 9, "Minus": 10, "Up": 11,
             "Down": 12, "Left": 13, "Right": 14, "L3": 15, "R3": 16}
CEMU_STICKS = {17: 45, 18: 39, 19: 44, 20: 38, 21: 47, 22: 41, 23: 46, 24: 40}   # Sticks: kAxis*/kRotation*
CEMU_TRIGGER = {"lt": 42, "rt": 43}                                               # kTriggerXP / kTriggerYP


def cemu_mapping(ctx):
    """VPAD-Taste -> Cemu-Tastennummer (SDL-Gamepad-Taste n = kButton n). Rohe Tasten kennt Cemu so nicht -> frei."""
    m = {}
    for b, vp in CEMU_VPAD.items():
        bind = ctx["bmap"].get(b)
        gc = GC_ROLE.get(bind_role(bind, ctx["roles"]), "")
        if gc in CEMU_TRIGGER:
            m[vp] = CEMU_TRIGGER[gc]
        elif gc in SDL_GC_BUTTON:
            m[vp] = SDL_GC_BUTTON[gc]
        elif bind:
            log(f"Cemu: {b} geht nur auf eine Controllertaste – bleibt frei")
    m.update(CEMU_STICKS)
    return m


def cemu_prepare(ctx):
    import xml.etree.ElementTree as ET
    guid = (ctx.get("sdl") or {}).get("guid", "")
    root = None
    if CEMU_PROFILE.exists():
        try:
            root = ET.parse(CEMU_PROFILE).getroot()
        except (OSError, ET.ParseError) as e:
            log("Cemu: controller0.xml nicht lesbar, bleibt:", e)
            return
        if (root.findtext("type") or "").strip() != "Wii U GamePad":
            log("Cemu: anderer Controller-Typ eingestellt – Belegung bleibt")
            return
    ctl = None
    if root is not None:
        ctl = next((c for c in root.findall("controller") if (c.findtext("api") or "").strip() == "SDLController"), None)
    wanted = cemu_mapping(ctx)
    cur = {}
    if ctl is not None:
        for ent in ctl.findall("mappings/entry"):
            try:
                cur[int(ent.findtext("mapping"))] = int(ent.findtext("button"))  # type: ignore[arg-type]  # None -> TypeError
            except (TypeError, ValueError):
                pass
    stock = {1: 1, 2: 0, 3: 3, 4: 2, 5: 9, 6: 10, 7: 42, 8: 43, 9: 6, 10: 4, 11: 11, 12: 12, 13: 13, 14: 14, 15: 7, 16: 8,
             **CEMU_STICKS}                         # Cemus eigene Vorgabe fuer SDL-Controller (VPADController.cpp)
    if not keymap_once("cemu", "pad", {str(k): v for k, v in cur.items()}, {str(k): v for k, v in wanted.items()},
                       ctx["custom"] or cur == stock):
        return
    if ctl is None and not guid:
        log("Cemu: SDL kennt den Controller nicht – Belegung bleibt")
        return
    if root is None:
        root = ET.Element("emulated_controller")
        ET.SubElement(root, "type").text = "Wii U GamePad"
    if ctl is None:                                # Tastatur o. Ae. bleibt daneben
        ctl = ET.SubElement(root, "controller")
        ET.SubElement(ctl, "api").text = "SDLController"
        ET.SubElement(ctl, "uuid").text = f"0_{guid}"
        ET.SubElement(ctl, "display_name").text = (ctx.get("sdl") or {}).get("gcname") or ctx["pad"]["name"]
        for grp, dz in (("axis", "0.25"), ("rotation", "0.25"), ("trigger", "0.25")):
            g = ET.SubElement(ctl, grp)
            ET.SubElement(g, "deadzone").text = dz
            ET.SubElement(g, "range").text = "1"
    old = ctl.find("mappings")
    if old is not None:
        ctl.remove(old)
    maps = ET.SubElement(ctl, "mappings")
    for vp, btn in sorted(wanted.items()):
        ent = ET.SubElement(maps, "entry")
        ET.SubElement(ent, "mapping").text = str(vp)
        ET.SubElement(ent, "button").text = str(btn)
    ET.indent(root, space="\t")
    CEMU_PROFILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CEMU_PROFILE.with_suffix(".vs-tmp")
    tmp.write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n",
                   encoding="utf-8")
    tmp.replace(CEMU_PROFILE)
    log("Cemu: Controller-Belegung", wanted)


# -- MAME 0.282 (SDL2-GameController mit -joystickprovider sdlgame; ~/.mame/cfg/default.cfg, osd/modules/input/
#    input_sdl.cpp, emu/inpttype.ipp, emu/input.cpp). Void startet MAME ueber /usr/bin/mame (Skript): beim allerersten
#    Aufruf legt es nur ~/.mame samt mame.ini an und beendet sich – das erledigt VoidStation vorher (mame_setup).
MAME_DIR = Path.home() / ".mame"
MAME_CFG = MAME_DIR / "cfg" / "default.cfg"
# Port -> Tastatur-/Maus-Vorgabe von MAME (inpttype.ipp), bleibt vor der Controllertaste stehen
MAME_PORTS = {"Button1": ("P1_BUTTON1", "KEYCODE_LCONTROL OR MOUSECODE_1_BUTTON1 OR GUNCODE_1_BUTTON1"),
              "Button2": ("P1_BUTTON2", "KEYCODE_LALT OR MOUSECODE_1_BUTTON3 OR GUNCODE_1_BUTTON2"),
              "Button3": ("P1_BUTTON3", "KEYCODE_SPACE OR MOUSECODE_1_BUTTON2"),
              "Button4": ("P1_BUTTON4", "KEYCODE_LSHIFT"), "Button5": ("P1_BUTTON5", "KEYCODE_Z"),
              "Button6": ("P1_BUTTON6", "KEYCODE_X"), "Coin": ("COIN1", "KEYCODE_5"), "Start": ("START1", "KEYCODE_1"),
              "Up": ("P1_JOYSTICK_UP", "KEYCODE_UP"), "Down": ("P1_JOYSTICK_DOWN", "KEYCODE_DOWN"),
              "Left": ("P1_JOYSTICK_LEFT", "KEYCODE_LEFT"), "Right": ("P1_JOYSTICK_RIGHT", "KEYCODE_RIGHT")}
MAME_STICK = {"Up": "JOYCODE_1_YAXIS_UP_SWITCH", "Down": "JOYCODE_1_YAXIS_DOWN_SWITCH",
              "Left": "JOYCODE_1_XAXIS_LEFT_SWITCH", "Right": "JOYCODE_1_XAXIS_RIGHT_SWITCH"}


def mame_items(sdl):
    """SDL-Gamepad-Taste (GC_ROLE-Name) -> MAME-Eingabe. Nummeriert werden nur vorhandene Tasten, der Reihe nach
    A, B, X, Y, LB, RB, (Trigger, wenn SDL sie als Taste meldet), L3, R3 – wie input_sdl.cpp; analoge Trigger sind
    SLIDER1/2 (gedrueckt negativ)."""
    btns, axes = (sdl or {}).get("buttons"), (sdl or {}).get("axes") or {}
    have = (lambda n: btns.get(n) is not None) if isinstance(btns, dict) else (lambda n: True)
    out: dict[str, str] = {}
    n = 1
    for name in ("a", "b", "x", "y", "lb", "rb", "lt", "rt", "l3", "r3"):
        if name in ("lt", "rt"):
            b = axes.get(name)
            if b and "button" in b:
                out[name], n = f"BUTTON{n}", n + 1
            elif b is not None or not isinstance(btns, dict):
                out[name] = "SLIDER1_NEG_SWITCH" if name == "lt" else "SLIDER2_NEG_SWITCH"
        elif have(name):
            out[name], n = f"BUTTON{n}", n + 1
    out.update({"back": "SELECT", "start": "START", "up": "HAT1UP", "down": "HAT1DOWN", "left": "HAT1LEFT",
                "right": "HAT1RIGHT"})
    return out


def mame_seqs(ctx):
    items = mame_items(ctx.get("sdl"))
    out = {}
    for b, (port, kb) in MAME_PORTS.items():
        bind = ctx["bmap"].get(b)
        gc = GC_ROLE.get(bind_role(bind, ctx["roles"]), "")
        seq = kb + (f" OR JOYCODE_1_{items[gc]}" if gc in items else "")
        if bind and gc not in items:
            log(f"MAME: {b} geht nur auf eine Controllertaste – bleibt frei")
        if b in MAME_STICK:
            seq += f" OR {MAME_STICK[b]}"         # linker Stick steuert immer mit
        out[port] = seq
    return out


def mame_setup():
    """Erster Start: mame.ini und Ordner anlegen lassen (das Skript von Void tut beim ersten Aufruf nur das)."""
    if (MAME_DIR / "mame.ini").exists() or not shutil.which("mame"):
        return
    try:
        subprocess.run(["mame"], cwd=str(Path.home()), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=60)
        log("MAME: Grundeinstellung angelegt")
    except (OSError, subprocess.SubprocessError) as e:
        log("MAME: Grundeinstellung:", e)


def mame_prepare(ctx):
    import xml.etree.ElementTree as ET
    mame_setup()
    root = None
    if MAME_CFG.exists():
        try:
            root = ET.parse(MAME_CFG).getroot()
        except (OSError, ET.ParseError) as e:
            log("MAME: default.cfg nicht lesbar, bleibt:", e)
            return
    wanted = mame_seqs(ctx)
    inp = None
    if root is not None:
        sysn = next((x for x in root.findall("system") if x.get("name") == "default"), None)
        inp = sysn.find("input") if sysn is not None else None
    cur = {}
    if inp is not None:
        for port in inp.findall("port"):
            if port.get("type") in wanted:
                cur[port.get("type")] = " ".join((port.findtext("newseq") or "").split())
    if not keymap_once("mame", "pad", cur, wanted, ctx["custom"]):
        return
    if root is None:
        root = ET.Element("mameconfig", version="10")
    sysn = next((x for x in root.findall("system") if x.get("name") == "default"), None)
    if sysn is None:
        sysn = ET.SubElement(root, "system", name="default")
    inp = sysn.find("input")
    if inp is None:
        inp = ET.SubElement(sysn, "input")
    for port in [x for x in inp.findall("port") if x.get("type") in wanted]:
        inp.remove(port)
    for t, seq in wanted.items():
        port = ET.SubElement(inp, "port", type=t)
        ET.SubElement(port, "newseq", type="standard").text = seq
    ET.indent(root, space="    ")
    MAME_CFG.parent.mkdir(parents=True, exist_ok=True)
    tmp = MAME_CFG.with_suffix(".vs-tmp")
    tmp.write_text('<?xml version="1.0"?>\n' + ET.tostring(root, encoding="unicode") + "\n", encoding="utf-8")
    tmp.replace(MAME_CFG)
    log("MAME: Controller-Belegung", wanted)


MAME_NAMES = BASE / "cache" / "mame-names.json"


def mame_names(sets):
    """ROM-Set -> Spielname (mame -listfull), zwischengespeichert je MAME-Fassung. Unbekannte Sets fehlen einfach."""
    exe = shutil.which("mame")
    if not sets or not exe:
        return {}
    try:
        stamp = str(Path("/usr/libexec/mame/mame").stat().st_mtime_ns)
    except OSError:
        stamp = exe
    try:
        cache = json.loads(MAME_NAMES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    if cache.get("stamp") != stamp:
        cache = {"stamp": stamp, "names": {}}
    names = cache["names"]
    todo = [x for x in sets if x not in names]
    if todo:
        r = run(["/usr/libexec/mame/mame" if Path("/usr/libexec/mame/mame").exists() else exe, "-listfull", *todo],
                timeout=30)
        for line in (r.stdout if r else "").splitlines()[1:]:
            m = re.match(r'^(\S+)\s+"(.*)"\s*$', line)
            if m:
                names[m.group(1)] = m.group(2)
        for x in todo:
            names.setdefault(x, "")              # unbekannt: nicht jedes Mal neu fragen
        try:
            MAME_NAMES.parent.mkdir(parents=True, exist_ok=True)
            MAME_NAMES.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return {k: v for k, v in names.items() if k in sets and v}


# -- RetroArch 1.22 (udev-Joypad; ~/.config/retroarch/retroarch.cfg input_player1_*, input/drivers_joypad/udev_joypad.c)
RETROARCH_CFG = Path.home() / ".config/retroarch/retroarch.cfg"
RETROARCH_KEYS = {"B": "b", "A": "a", "Y": "y", "X": "x", "L": "l", "R": "r", "L2": "l2", "R2": "r2", "L3": "l3",
                  "R3": "r3", "Start": "start", "Select": "select", "Up": "up", "Down": "down", "Left": "left",
                  "Right": "right"}


def retroarch_cfg_read(path=None):
    out = {}
    try:
        for line in (path or RETROARCH_CFG).read_text(encoding="utf-8", errors="replace").splitlines():
            k, sep, v = line.partition("=")
            if sep and not k.strip().startswith("#"):
                out[k.strip()] = v.strip().strip('"')
    except OSError:
        pass
    return out


def retroarch_cfg_write(values, path=None):
    """Schluessel in retroarch.cfg setzen ("key = \\"wert\\""), Rest bleibt."""
    path = path or RETROARCH_CFG
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    todo = dict(values)
    for i, line in enumerate(lines):
        k = line.partition("=")[0].strip()
        if k in todo:
            lines[i] = f'{k} = "{todo.pop(k)}"'
    lines += [f'{k} = "{v}"' for k, v in todo.items()]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".vs-tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)


def retroarch_indices(pad):
    """(Tasten, Achsen) wie RetroArchs udev-Joypad: KEY_UP..KEY_DOWN, BTN_MISC.., dann der Rest; Achsen ohne Hats."""
    from evdev import ecodes as E
    keys = sorted(pad["keys"])
    order = [k for k in keys if E.KEY_UP <= k <= E.KEY_DOWN] + [k for k in keys if k >= E.BTN_MISC] \
        + [k for k in keys if k < E.KEY_UP] + [k for k in keys if E.KEY_DOWN < k < E.BTN_MISC]
    axes = sorted(a for a in pad["axes"] if a < E.ABS_MISC and not E.ABS_HAT0X <= a <= E.ABS_HAT3Y)
    return {k: i for i, k in enumerate(order)}, {a: i for i, a in enumerate(axes)}


def retroarch_prepare(ctx):
    cfg = retroarch_cfg_read()
    if cfg.get("input_joypad_driver", "udev") == "udev":
        btn, ax = retroarch_indices(ctx["pad"])
    else:
        btn, ax = ctx["btn"], ctx["ax"]
    wanted = {}
    for b, k in RETROARCH_KEYS.items():
        bind = ctx["bmap"].get(b)
        v_btn = v_ax = "nul"
        if bind and "key" in bind and bind["key"] in btn:
            v_btn = str(btn[bind["key"]])
        elif bind and "abs" in bind and bind["abs"] in ax:
            v_ax = f"{'+' if bind['dir'] > 0 else '-'}{ax[bind['abs']]}"
        elif bind and "hat" in bind:
            v_btn = "h0" + HAT_DIRS[(bind["hat"], bind["dir"])]
        wanted[f"input_player1_{k}_btn"] = v_btn
        wanted[f"input_player1_{k}_axis"] = v_ax
    cur = {k: (None if cfg.get(k, "nul") == "nul" else cfg[k]) for k in wanted}
    values = {}
    if keymap_once("retroarch", "pad", cur, wanted, ctx["custom"]):
        values.update(wanted)
    if ctx["bmap"].get("rewind") and cfg.get("rewind_enable", "false") != "true":
        values["rewind_enable"] = "true"           # Zurueckspulen belegt: in RetroArch einschalten
    if values:
        retroarch_cfg_write(values)
        log("RetroArch: Controller-Belegung", {k: v for k, v in values.items() if k.endswith("_btn") and v != "nul"})


def retroarch_dirs():
    cfg = retroarch_cfg_read()
    exp = lambda v: Path(os.path.expanduser(v.replace(":/", "~/.config/retroarch/", 1) if v.startswith(":/") else v))
    cores = [exp(cfg["libretro_directory"])] if cfg.get("libretro_directory") not in (None, "", "default") else []
    cores += [Path.home() / ".config/retroarch/cores", Path("/usr/lib/libretro")]
    infos = [exp(cfg["libretro_info_path"])] if cfg.get("libretro_info_path") not in (None, "", "default") else []
    infos += [Path.home() / ".config/retroarch/cores", Path.home() / ".config/retroarch/info",
              Path("/usr/share/libretro/info")]
    return cores, infos


# Bevorzugte Kerne je Endung, wenn mehrere passen (sonst der erste nach Namen)
RETROARCH_PREFER = ["mgba", "snes9x", "nestopia", "genesis_plus_gx", "picodrive", "mupen64plus_next", "pcsx_rearmed",
                    "beetle_psx", "mednafen_pce_fast", "fbneo", "stella", "prosystem", "handy", "mednafen_ngp",
                    "mednafen_wswan", "gambatte", "melonds", "ppsspp"]


def retroarch_cores():
    """Installierte Kerne -> Endungen aus ihren .info-Dateien (supported_extensions)."""
    cores, infos = retroarch_dirs()
    out: dict = {}
    for d in cores:
        try:
            for so in sorted(d.glob("*_libretro.so")):
                out.setdefault(so, set())
        except OSError:
            pass
    for so in out:
        for d in infos:
            info = d / (so.stem + ".info")
            try:
                m = re.search(r'^supported_extensions\s*=\s*"([^"]*)"', info.read_text(errors="replace"), re.M)
            except OSError:
                continue
            if m:
                out[so] = {"." + e.lower() for e in m.group(1).split("|") if e}
                break
    return out


def retroarch_exts():
    exts = set()
    for e in retroarch_cores().values():
        exts |= e
    return exts


def retroarch_core(target):
    ext = target.suffix.lower()
    cands = [so for so, e in retroarch_cores().items() if ext in e]
    if not cands:
        return None
    rank = lambda so: next((i for i, p in enumerate(RETROARCH_PREFER) if so.stem == f"{p}_libretro"), 99)
    return sorted(cands, key=lambda so: (rank(so), so.name))[0]


# ---- Flatpak oder AppImage: wo die Emulatoren ihre Einstellungen haben ---------------------------------------
# Seit Oktober 2026 kommen PCSX2, xemu, Flycast, Azahar, Cemu und RMG als AppImage (entpackt unter apps/<id>, wie
# DuckStation): ohne Sandbox, ohne Dokumenten-Portal, Dateidialoge wie gewohnt. Ein frueher installiertes Flatpak laeuft
# weiter, bis das naechste Update wechselt (_from_flatpak kopiert die Ordner). Die Pfade der Belegungs- und BIOS-
# Funktionen richten sich danach, welche Fassung gerade installiert ist (emu_paths_refresh).
_H = Path.home()
_FP = _H / ".var/app"
EMU_DIRS = {  # Kachel -> [(Ordner im Flatpak, Ordner beim AppImage)], der erste traegt die Einstellungsdatei
    "pcsx2": [(_FP / "net.pcsx2.PCSX2/config/PCSX2", _H / ".config/PCSX2")],
    "xemu": [(_FP / "app.xemu.xemu/data/xemu", _H / ".local/share/xemu")],
    "flycast": [(_FP / "org.flycast.Flycast/config/flycast", _H / ".config/flycast"),
                (_FP / "org.flycast.Flycast/data/flycast", _H / ".local/share/flycast")],
    "azahar": [(_FP / "org.azahar_emu.Azahar/config/azahar-emu", _H / ".config/azahar-emu"),
               (_FP / "org.azahar_emu.Azahar/data/azahar-emu", _H / ".local/share/azahar-emu")],
    "cemu": [(_FP / "info.cemu.Cemu/config/Cemu", _H / ".config/Cemu"), (_FP / "info.cemu.Cemu/data/Cemu", _H / ".local/share/Cemu"),
             (_FP / "info.cemu.Cemu/cache/Cemu", _H / ".cache/Cemu")],
    "rmg": [(_FP / "com.github.Rosalie241.RMG/config/RMG", _H / ".config/RMG"),
            (_FP / "com.github.Rosalie241.RMG/data/RMG", _H / ".local/share/RMG"),
            (_FP / "com.github.Rosalie241.RMG/cache/RMG", _H / ".cache/RMG")],
}


def emu_dirs(tid):
    return EMU_DIRS.get(tid, [])


def emu_native(tid):
    """Laeuft die Kachel ohne Flatpak – als Paket (seit 2026.12) oder entpackt? Sonst (noch) als Flatpak."""
    if (APPDIR / tid / "AppRun").exists():
        return True
    a = catalog_app(tid)
    return bool(a and a["source"].get("type") == "xbps")


def emu_dir(tid, i=0):
    fp, nat = EMU_DIRS[tid][i]
    return nat if emu_native(tid) else fp


def emu_paths_refresh():
    global PCSX2_INI, RMG_CFG, XEMU_TOML, AZAHAR_INI, CEMU_PROFILE, FLYCAST_MAPPINGS, FLYCAST_CFG
    PCSX2_INI = emu_dir("pcsx2") / "inis/PCSX2.ini"
    RMG_CFG = emu_dir("rmg") / "mupen64plus.cfg"
    XEMU_TOML = emu_dir("xemu") / "xemu/xemu.toml"
    AZAHAR_INI = emu_dir("azahar") / "qt-config.ini"
    CEMU_PROFILE = emu_dir("cemu") / "controllerProfiles/controller0.xml"
    FLYCAST_MAPPINGS = emu_dir("flycast") / "mappings"
    FLYCAST_CFG = emu_dir("flycast") / "emu.cfg"


emu_paths_refresh()


# -- Mednafen 1.32.1 (Void-Paket; kein eigenes Menue – Einstellungen nur in ~/.mednafen/mednafen.cfg, je Zeile
#    "<name> <wert>", settings.cpp; eine unvollstaendige Datei ergaenzt es beim Beenden selbst).
#    Controller: Joystick-Geraete des Kernels (/dev/input/js*, drivers/Joystick_Linux.cpp), Bindung
#    "joystick 0x<Kennung> button_3" bzw. "abs_1-" (drivers/input.cpp BCGToString, Joystick.cpp BNToString).
MEDNAFEN_DIR = Path.home() / ".mednafen"
MEDNAFEN_CFG = MEDNAFEN_DIR / "mednafen.cfg"
MEDNAFEN_SYSFS = Path("/sys/class/input")
_MDFN_DIRS = {"up": "Up", "down": "Down", "left": "Left", "right": "Right"}
# Geraet in Mednafen -> {dessen Taste: Taste der Skizze}; md: je nach Spiel 3 oder 6 Tasten (md.input.auto), gamepad2 = 2 Tasten
MEDNAFEN_PADS = {
    "md.input.port1.gamepad": {"a": "A", "b": "B", "c": "C", "start": "Start"},
    "md.input.port1.gamepad2": {"a": "A", "b": "B", "start": "Start"},
    "md.input.port1.gamepad6": {"a": "A", "b": "B", "c": "C", "x": "X", "y": "Y", "z": "Z", "start": "Start", "mode": "Mode"},
    "sms.input.port1.gamepad": {"fire1": "B", "fire2": "C", "pause": "Start"},
    "gg.input.builtin.gamepad": {"button1": "B", "button2": "C", "start": "Start"},
    "ss.input.port1.gamepad": {"a": "A", "b": "B", "c": "C", "x": "X", "y": "Y", "z": "Z", "ls": "L", "rs": "R", "start": "Start"},
    "pce.input.port1.gamepad": {"ii": "B", "i": "C", "select": "Mode", "run": "Start"},
}


def mednafen_read(keys=None):
    out: dict[str, str] = {}
    try:
        lines = MEDNAFEN_CFG.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        k, sep, v = line.partition(" ")
        if sep and k and k[0] not in ";#" and (keys is None or k in keys):
            out[k] = v
    return out


def mednafen_write(updates):
    """Einstellungen setzen; alles andere (auch die Kommentarzeilen) bleibt."""
    todo, out = {k: str(v) for k, v in updates.items()}, []
    try:
        lines = MEDNAFEN_CFG.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    for line in lines:
        k = line.partition(" ")[0]
        out.append(f"{k} {todo.pop(k)}" if k in todo and line[:1] not in (";", "#") else line)
    out += [f"{k} {v}" for k, v in todo.items()]
    MEDNAFEN_DIR.mkdir(parents=True, exist_ok=True)
    tmp = MEDNAFEN_CFG.with_suffix(".vs-tmp")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    tmp.replace(MEDNAFEN_CFG)


def js_indices(pad):
    """(Tasten, Achsen) eines Gamepads als {evdev-Code: Nummer}, gezaehlt wie /dev/input/js* (Kernel joydev.c): Tasten ab
    BTN_JOYSTICK, dann BTN_MISC bis davor; Achsen in der Reihenfolge der Codes – das Steuerkreuz zaehlt dort als Achse mit."""
    from evdev import ecodes as E
    keys = pad["keys"]
    order = sorted(k for k in keys if E.BTN_JOYSTICK <= k <= E.KEY_MAX) + sorted(k for k in keys if E.BTN_MISC <= k < E.BTN_JOYSTICK)
    return {k: i for i, k in enumerate(order)}, {a: i for i, a in enumerate(sorted(pad["axes"]))}


def mednafen_pad_ids(pads):
    """{Pfad: Kennung} wie Mednafen sie bildet (Joystick_Linux.cpp): Bus, Hersteller, Produkt, Version aus sysfs, dann Zahl
    der Achsen und Tasten; gleiche Geraete zaehlt es in der Reihenfolge der js-Nummern hoch (Joystick.cpp). Ohne
    js-Geraet (Modul joydev fehlt) sieht Mednafen den Controller nicht."""
    rows = []
    for pad in pads:
        dev = MEDNAFEN_SYSFS / Path(pad["path"]).name / "device"
        try:
            js = next((int(q.name[2:]) for q in dev.iterdir() if re.fullmatch(r"js\d+", q.name)), None)
            ids = [int((dev / "id" / n).read_text().strip(), 16) & 0xFFFF for n in ("bustype", "vendor", "product", "version")]
        except (OSError, ValueError):
            continue
        if js is None:
            continue
        btn, ax = js_indices(pad)
        rows.append((js, pad["path"], ids[0] << 48 | ids[1] << 32 | ids[2] << 16 | ids[3], len(ax) << 48 | len(btn) << 32))
    out: dict = {}
    seen: dict = {}
    for _, path, hi, lo in sorted(rows):
        n = seen.get((hi, lo), 0)
        seen[(hi, lo)] = n + 1
        out[path] = f"0x{hi:016x}{(lo + n) & 0xFFFFFFFFFFFFFFFF:016x}"
    return out


def mednafen_value(b, jid, btn, ax):
    from evdev import ecodes as E
    if not b:
        return None
    if "key" in b and b["key"] in btn:
        return f"joystick {jid} button_{btn[b['key']]}"
    code = b.get("abs") if "abs" in b else {"x": E.ABS_HAT0X, "y": E.ABS_HAT0Y}.get(b.get("hat"))
    if code in ax:
        return f"joystick {jid} abs_{ax[code]}{'+' if b['dir'] > 0 else '-'}"
    return None


def mednafen_prepare(ctx):
    from evdev import ecodes as E
    jid = mednafen_pad_ids(gamepads()).get(ctx["pad"]["path"])
    if not jid:
        log("Mednafen: kein Joystick-Geraet (js) zum Controller – Belegung bleibt")
        return
    btn, ax = js_indices(ctx["pad"])
    val = {b: mednafen_value(ctx["bmap"].get(b), jid, btn, ax) for b, _ in EMU_LAYOUTS["mednafen"]["buttons"] if b not in EMU_ACTIONS}
    # linker Stick steuert mit, soweit seine Achsen nicht schon belegt sind
    used = {v for v in val.values() if v}
    for name, code, sign in (("Up", E.ABS_Y, "-"), ("Down", E.ABS_Y, "+"), ("Left", E.ABS_X, "-"), ("Right", E.ABS_X, "+")):
        stick = f"joystick {jid} abs_{ax[code]}{sign}" if code in ax else None
        if stick and stick not in used:
            val[name] = f"{val[name]} || {stick}" if val.get(name) else stick
    wanted = {}
    for dev, keys in MEDNAFEN_PADS.items():
        for k, b in {**_MDFN_DIRS, **keys}.items():
            if val.get(b):
                wanted[f"{dev}.{k}"] = val[b]
    have = mednafen_read(set(wanted))
    split = {k: [x.strip() for x in v.split(" || ")] for k, v in have.items()}
    cur = {k: " || ".join(x for x in parts if x.startswith("joystick ")) for k, parts in split.items()}
    if not keymap_once("mednafen", "pad", cur, wanted, ctx["custom"]):
        return
    # Tastatur-Belegung von Mednafen bleibt davor stehen
    mednafen_write({k: " || ".join([x for x in split.get(k, []) if x and not x.startswith("joystick ")] + [v])
                    for k, v in wanted.items()})
    log("Mednafen: Controller-Belegung", jid)


def mednafen_bios():
    """Saturn-BIOS und PC-Engine-CD-BIOS aus der Freigabe eintragen, wenn Mednafen an seinem Ort nichts findet."""
    cur = mednafen_read({"filesys.path_firmware", "ss.bios_jp", "ss.bios_na_eu", "pce.cdbios"})
    fw = Path(cur.get("filesys.path_firmware") or "firmware").expanduser()
    fw = fw if fw.is_absolute() else MEDNAFEN_DIR / fw
    put = {}
    for key, default, kind in (("ss.bios_jp", "sega_101.bin", "ss_jp"), ("ss.bios_na_eu", "mpr-17933.bin", "ss_eu"),
                               ("pce.cdbios", "syscard3.pce", "pcecd")):
        f = Path(cur.get(key) or default).expanduser()
        if (f if f.is_absolute() else fw / f).is_file():
            continue
        hit = bios_find(kind)
        if hit:
            put[key] = str(hit[0])
    if put:
        mednafen_write(put)
        log("Mednafen: BIOS", put)


KEYMAP_WRITERS = {"duckstation": duckstation_prepare, "snes9x": snes9x_prepare, "nestopia": nestopia_prepare,
                  "ppsspp": ppsspp_prepare, "melonds": melonds_prepare, "dolphin": dolphin_prepare,
                  "flycast": flycast_prepare, "pcsx2": pcsx2_prepare, "rmg": rmg_prepare, "xemu": xemu_prepare,
                  "azahar": azahar_prepare, "cemu": cemu_prepare, "mame": mame_prepare, "retroarch": retroarch_prepare,
                  "mednafen": mednafen_prepare}
# Hinweise der Tastenbelegung, die nur gelten, solange der Emulator noch nicht eingerichtet ist
KEYMAP_NOTE_READY = {"duckstation": lambda: duck_ready(), "pcsx2": lambda: pcsx2_ready()}


def keymap_prepare(tile):
    """Vor dem Start eines Emulators (ausser mGBA, s. mgba_prepare): Belegung in dessen Einstellungen schreiben."""
    fn = KEYMAP_WRITERS.get(tile)
    if not fn:
        return
    with EMU_LOCK:
        ctx = keymap_context(tile)
    if not ctx:
        return
    with EMU_LOCK:
        fn(ctx)


# ---- Ton aus je Emulator (Spieleliste: Optionen → "Spiel stumm") ----------------------------------------------------------
# Geschaltet wird der Schalter des Emulators selbst, damit VoidStation und das Menue des Emulators uebereinstimmen.
# mGBA 0.10: [ports.qt] mute (Window.cpp Audio -> Stumm; CoreController liest es beim Start).
# Laeuft der Emulator gerade, schreibt er beim Beenden seine Einstellungen zurueck – deshalb merkt sich VoidStation
# den Wunsch zusaetzlich und setzt ihn vor dem naechsten Start noch einmal (emu_mute_apply).
# DuckStation, PCSX2 und DOSBox Staging lesen ihren Schalter als Wahr/Falsch (settings.cpp, Pcsx2Config.cpp, mixer.cpp).
EMU_MUTE = {"gba": lambda: (MGBA_CONFIG, "ports.qt", "mute", "1", "0"),
            "pcsx2": lambda: (PCSX2_INI, "SPU2/Output", "OutputMuted", "true", "false"),
            "duckstation": lambda: (DUCK_INI, "Audio", "OutputMuted", "true", "false"),
            "dosbox": lambda: (dosbox_primary(), "mixer", "nosound", "true", "false"),
            "ppsspp": lambda: (PPSSPP_INI, "Sound", "Enable", "False", "True"),
            "dolphin": lambda: (dolphin_dir() / "Dolphin.ini", "DSP", "Muted", "True", "False"),
            "snes9x": lambda: (snes9x_conf(), "Sound", "MuteSound", "true", "false"),
            "nestopia": lambda: (NESTOPIA_CONF, "frontend", "a_mute", "1", "0"),
            "scummvm": lambda: (SCUMMVM_INI, "scummvm", "mute", "true", "false"),
            "vice": lambda: (VICE_RC, "C64SC", "Sound", "0", "1")}
# vorher gilt die Datei dem Emulator als neu; Cemu: settings.xml legt first_run an (sonst fehlten dort die Spielordner)
# RMG: GLideN64 verwirft eine GLideN64.ini ohne "version" (GLideNUI/Settings.cpp) – erst nach dessen erstem Start.
# MAME: mame.ini legt das Skript von Void an (mame_setup). Stella: Die Datenbank legt Stella selbst an.
# melonDS: eine alte melonDS.ini uebernimmt es beim ersten Start selbst in die neue Datei.
EMU_READY = {"duckstation": lambda: duck_ready(), "pcsx2": lambda: pcsx2_ready(),
             "cemu": lambda: (emu_dir("cemu") / "settings.xml").exists(),
             "rmg": lambda: "version" in ini_read(rmg_gliden()).get("General", {}),
             "mame": lambda: (MAME_DIR / "mame.ini").exists(),
             "stella": lambda: STELLA_DB.is_file(),
             "melonds": lambda: MELONDS_TOML.exists() or not (MELONDS_TOML.parent / "melonDS.ini").exists()}


def emu_ready(tile):
    fn = EMU_READY.get(tile)
    return fn() if fn else True


def emu_set_mute(tile, on):
    spec = EMU_MUTE.get(tile)
    if not spec:
        raise ValueError("Dieser Emulator laesst sich nicht stumm schalten")
    path, sec, key, yes, no = spec()
    with EMU_LOCK:
        if tile == "dosbox":
            dosbox_primary_ensure()
        if emu_ready(tile):
            ini_update(path, sec, {key: yes if on else no})
        st = emu_state_load()
        st.setdefault("mute", {})[tile] = bool(on)
        emu_state_save(st)
    log(f"{tile}: Ton {'aus' if on else 'an'}")


def emu_mute_apply(tile):
    """Vor dem Start: einen in VoidStation gesetzten Wunsch (noch) einmal schreiben, danach gilt wieder der Emulator."""
    spec = EMU_MUTE.get(tile)
    if not spec:
        return
    if not emu_ready(tile):
        return
    with EMU_LOCK:
        st = emu_state_load()
        want = (st.get("mute") or {}).pop(tile, None)
        if want is None:
            return
        path, sec, key, yes, no = spec()
        ini_update(path, sec, {key: yes if want else no})
        emu_state_save(st)


# ---- Optionen je Emulator (Spieleliste: "Optionen") ------------------------------------------------------------
# Nur die wichtigsten Schalter; alles Weitere bleibt im Fenster des Emulators. Geschrieben wird immer die Einstellung des
# Emulators selbst, damit beide dasselbe zeigen. Schluessel und Werte geprueft an den Quelltexten (November 2026):
# PCSX2 Pcsx2Config.cpp/Config.h, DuckStation settings.cpp, mGBA 0.10 core/config.c + Qt, DOSBox Staging 0.82.2
# (Void-Paket; glshader gilt in 0.83 weiter, aber als veraltet).
# PPSSPP, Dolphin, Cemu, Azahar: s. weiter unten bei _OtherIni. Je Spiel gibt es dort nur den Rueckfall (Wert gilt fuer
# einen Start in der Haupteinstellung) – ihre eigenen Spiel-Einstellungen braeuchten je Format das Lesen der Spielkennung.
#
# "game": auch je Spiel waehlbar. DOSBox: kommt in die Datei, die VoidStation vor jedem Start schreibt. PCSX2/DuckStation:
# in deren eigene Spiel-Einstellungen (gamesettings/<Seriennummer>…ini, s. emu_game_ini; Seriennummer aus dem Abbild, discid.py).
# Rueckfall, wo sich das Abbild nicht lesen laesst (.cso, .gz, .pbp, .chd ohne chdman, zweite CD bei DuckStation …): Der Wert gilt fuer diesen Start
# in der Haupteinstellung, der alte kommt vor dem naechsten Start bzw. Oeffnen der Optionen zurueck (emu_opts_restore; nur, wo
# der Nutzer in der Zwischenzeit nichts anderes eingestellt hat).
#
# Spielprofile (gameprofiles.py, gamedb/<system>.csv): Was VoidStation fuer ein bekanntes Spiel von selbst einstellt, z. B.
# Texturen glaetten bei 3D-Spielen der PlayStation oder das CPU-Tempo eines DOS-Spiels. Ein Profil gilt nur, solange die Option
# allgemein auf der Stufe aus EMU_AUTO steht ("Automatisch" bzw. "Standard") und der Nutzer fuer das Spiel nichts gewaehlt hat.
# Eingetragen wird es wie der Rueckfall oben: fuer diesen einen Start, danach kommt der alte Wert zurueck.
# Eine Moeglichkeit mit "auto": True schreibt denselben Wert wie eine andere (bei DuckStation "Nearest"); welche von beiden
# gemeint ist, steht in emu-defaults.json unter opt_fixed. Je Spiel gibt es sie nicht (dort heisst "nichts gewaehlt" schon das).
#
# "VoidStation-Einstellungen | Anpassen" (Paul, 12.11.2026): Die Karte zeigt zuerst nur diesen Schalter und "Spiel stumm".
# VoidStation-Einstellungen = jede Option steht auf dem, was VoidStation vorsieht (_opt_vs: Vorgabe je Geraet, sonst der
# Standard) – das wird nicht gespeichert, sondern an den Einstellungen des Emulators abgelesen (emu_opts_mode): Wer dort
# etwas aendert, sieht hier "Anpassen" und seine Werte. "Anpassen" ohne Aenderung merkt opt_mode in emu-defaults.json.
# Zurueck auf VoidStation-Einstellungen: Werte merken (opt_saved), Vorgaben eintragen; "Anpassen" holt die gemerkten zurueck.
EMU_GAME_OPTS = Path.home() / ".config/voidstation/emu-games.json"       # {Kachel: {Spieldatei: {Option: Wert}}}
_OPT_MODE = [{"v": "vs", "k": "emuopt.v.vs"}, {"v": "custom", "k": "emuopt.v.custom"}]
EMU_AUTO = {"duckstation": {"texfilter": "auto", "fxaa": "auto"}, "dosbox": {"speed": "std"}}   # {Kachel: {Option: Stufe, auf der Profile gelten}}
EMU_OWN = BASE / "emu-own.ini"                         # Schalter von VoidStation selbst: [<Kachel>] <Option> = Wert
_OPT_TF = [{"v": "true", "k": "common.on"}, {"v": "false", "k": "common.off"}]
_OPT_10 = [{"v": "1", "k": "common.on"}, {"v": "0", "k": "common.off"}]


def _opt(oid, section, key, choices, default, game=False, hidden=False, own=False, label=None, io=None):
    """hidden: gehoert zu den VoidStation-Einstellungen (Vorgabe, wird beim Zurueckstellen mitgesetzt), hat auf der Karte
    aber keine eigene Zeile – wer daran drehen will, tut das im Emulator.
    own: kein Schluessel des Emulators, sondern ein Schalter von VoidStation selbst (EMU_OWN, Abschnitt = Kachel) – fuer
    die Patches je Spiel (EMU_PATCHES), fuer die die Emulatoren keinen allgemeinen Schalter haben.
    label: Beschriftung einer anderen Option uebernehmen (emuopt.<label>).
    io: eigenes Lesen/Schreiben fuer Optionen, die mehr als einen Abschnitt beruehren (Shader-Ketten von DuckStation,
    Shader-Pfad von mGBA): Objekt mit read(ini) -> Wert oder None und write(path, value); fuer DuckStation dazu
    writes/game_read/game_writes/game_clear (Spiel-Datei, Spielprofile)."""
    return {"id": oid, "section": section, "keys": key if isinstance(key, list) else [key], "choices": choices,
            "default": default, "game": game, "hidden": hidden, "own": own, "label": label, "io": io}


def _opt_res(values):
    return [{"v": "1", "k": "emuopt.v.original"}] + [{"v": str(v), "t": f"{v}×"} for v in values]


def _opt_cycles(real, protected):
    return {"cpu_cycles": real, "cpu_cycles_protected": protected}


# ---- Bildstil: Shader der Emulatoren (Paul, 13.11.2026: "die Presets, die von Haus aus von den Emulatoren kommen") ----
# Eine Zeile "Stil" in der Spalte Bildstil (Karte "Anpassen"), dazu bei PS1/PS2 "Kanten glaetten" (FXAA, Vorgabe von
# VoidStation, sobald es eine GPU gibt). Angeboten wird, was ein Bild gestaltet; Werkzeuge (Kalibrierung, Spiegeln,
# Tiefenpuffer anzeigen, Schwarzbilder fuer 120 Hz, Farbsehschwaeche simulieren …) bleiben im Emulator.
# Namen der Shader am Quelltext geprueft (13.11.2026): DuckStation data/resources/shaders (GLSL: Pfad ohne .glsl,
# ReShade: Pfad unter reshade/Shaders ohne .fx, postprocessing.cpp TryLoadingShader), PCSX2 TVShader 0–7
# (GraphicsPostProcessingSettingsTab.ui), mGBA res/shaders (mitgeliefert, s. launcher/shaders/LIESMICH.txt),
# DOSBox Staging 0.82.2 glshader (render.cpp, shader_manager.cpp MapShaderName).
_TRUE = ("true", "1", "yes", "on")
SHADER_DIR = BASE / "shaders"
MGBA_SHADERS = SHADER_DIR / "mgba"                    # Shader von mGBA und "voidstation-*.shader" (eigene)
DUCK_OWN_SHADERS = SHADER_DIR / "duckstation"         # eigene Shader fuer DuckStation (*.glsl), s. duck_shaders_install
LOOK_PREVIEWS = SHADER_DIR / "previews"               # Vorschaubilder je Stil: <Kachel>/<Option>-<Wert>.jpg (tools/look-previews.py)


def _io_apply(path, sets, drops=None):
    """{Abschnitt: {Schluessel: Wert}} schreiben und {Abschnitt: [Schluessel]} entfernen; nichts anlegen, wo nichts zu tun ist."""
    drops = drops or {}
    have = ini_read(path) if drops else {}
    for sec in list(sets) + [x for x in drops if x not in sets]:
        rm = [k for k in drops.get(sec, ()) if k in have.get(sec, {})]
        if sets.get(sec) or rm:
            ini_update(path, sec, sets.get(sec, {}), remove=rm)


def _duck_stages(ini, chain):
    """Shader der eingeschalteten Stufen einer Nachbearbeitungs-Kette von DuckStation (postprocessing.cpp: [<Kette>] Enabled,
    StageCount, [<Kette>/Stage<n>] ShaderName, StageEnabled). [] = Kette aus oder leer, None = nicht lesbar."""
    main = ini.get(chain, {})
    try:
        count = int(main.get("StageCount", "0") or 0)
    except ValueError:
        return None
    if main.get("Enabled", "false").strip().lower() not in _TRUE:
        return []
    out = []
    for i in range(1, count + 1):
        stage = ini.get(f"{chain}/Stage{i}", {})
        if stage.get("StageEnabled", "true").strip().lower() in _TRUE:
            out.append(stage.get("ShaderName", "").strip())
    return out


def _duck_chain_writes(ini, chain, shaders):
    """Kette auf genau diese Shader stellen -> (setzen, entfernen). Wechselt in einer Stufe der Shader, fliegen die Regler
    des alten heraus (sonst traegt der neue fremde Werte)."""
    if not shaders:
        return {chain: {"Enabled": "false"}}, {}
    sets = {chain: {"Enabled": "true", "StageCount": str(len(shaders))}}
    drops = {}
    for i, name in enumerate(shaders, 1):
        sec = f"{chain}/Stage{i}"
        old = ini.get(sec, {})
        sets[sec] = {"ShaderName": name, "StageEnabled": "true"}
        if old.get("ShaderName") != name:
            drops[sec] = [k for k in old if k not in ("ShaderName", "StageEnabled")]
    return sets, drops


def _duck_chain_clear(ini, chain):
    return {sec: list(vals) for sec, vals in ini.items() if sec == chain or sec.startswith(chain + "/Stage")}


class _DuckSingle:
    """Ein Shader als einzige Stufe einer Kette ("off" = Kette aus) – fuer "Kanten glaetten" in [InternalPostProcessing].
    Mehrere Werte duerfen denselben Shader meinen (Automatik und An); gelesen wird der erste. Hat der Nutzer im Emulator
    eine andere Kette gebaut, ist kein Knopf an (None); erst eine Wahl hier ersetzt sie.
    Je Spiel: Steht in der Spiel-Datei [<Kette>] Enabled, nimmt DuckStation die ganze Kette von dort
    (video_presenter.cpp GetPostProcessingSettingsInterface)."""

    def __init__(self, chain, shaders):
        self.chain, self.shaders = chain, shaders

    def read(self, ini):
        stages = _duck_stages(ini, self.chain)
        if stages is None:
            return None
        if not stages:
            return "off"
        return next((v for v, name in self.shaders.items() if [name] == stages), None)

    def game_read(self, ini):
        return self.read(ini) if "Enabled" in ini.get(self.chain, {}) else None

    def writes(self, value, ini):
        return _duck_chain_writes(ini, self.chain, [] if value == "off" else [self.shaders[value]])

    def game_writes(self, value, ini, base):
        return self.writes(value, ini)

    def game_clear(self, ini):
        return _duck_chain_clear(ini, self.chain)

    def write(self, path, value):
        _io_apply(path, *self.writes(value, ini_read(path)))


class _DuckDisplay:
    """"Stil" (role 0) und "Farbe" (role 1) teilen sich die Kette [PostProcessing]: erst die Farbe, dann der Stil.
    Lesbar ist nur, was genau so aufgebaut ist – sonst ist kein Knopf an. Je Spiel gibt es nur den Stil; die Kette des
    Spiels bekommt die allgemeine Farbe davor (duck_game_color_sync zieht sie vor jedem Start nach)."""
    chain = "PostProcessing"

    def __init__(self, role, looks, colors):
        self.role, self.looks, self.colors = role, looks, colors

    def pair(self, ini):
        stages = _duck_stages(ini, self.chain)
        if stages is None:
            return None
        color = "nat"
        if stages:
            hit = next((v for v, name in self.colors.items() if name == stages[0]), None)
            if hit:
                color, stages = hit, stages[1:]
        if not stages:
            return ("off", color)
        look = next((v for v, name in self.looks.items() if name == stages[0]), None) if len(stages) == 1 else None
        return (look, color) if look else None

    def compose(self, look, color):
        return ([self.colors[color]] if color != "nat" else []) + ([self.looks[look]] if look != "off" else [])

    def read(self, ini):
        got = self.pair(ini)
        return got[self.role] if got else None

    def game_read(self, ini):
        return self.read(ini) if "Enabled" in ini.get(self.chain, {}) else None

    def writes(self, value, ini):
        cur = list(self.pair(ini) or ("off", "nat"))
        cur[self.role] = value
        return _duck_chain_writes(ini, self.chain, self.compose(*cur))

    def game_writes(self, value, ini, base):
        return _duck_chain_writes(ini, self.chain, self.compose(value, (self.pair(base) or ("off", "nat"))[1]))

    def game_clear(self, ini):
        return _duck_chain_clear(ini, self.chain)

    def write(self, path, value):
        _io_apply(path, *self.writes(value, ini_read(path)))


def duck_game_color_sync(native):
    """Spiel mit eigenem Stil: Seine Kette ersetzt bei DuckStation die allgemeine – die allgemeine Farbe nachziehen."""
    io, gi = _DUCK_LOOK_IO, ini_read(native)
    if "Enabled" not in gi.get(io.chain, {}):
        return
    mine, base = io.pair(gi), ini_read(DUCK_INI)
    if mine and mine[1] != (io.pair(base) or ("off", "nat"))[1]:
        _io_apply(native, *io.game_writes(mine[0], gi, base))


def duck_shaders_install():
    """Eigene Shader in den Shader-Ordner von DuckStation legen ([Folders] Shaders, sonst <Daten>/shaders) – dort sucht es
    zuerst (postprocessing.cpp TryLoadingShader). Vor jedem Start, nur was fehlt oder sich geaendert hat."""
    dst = DUCK_INI.parent / (ini_read(DUCK_INI).get("Folders", {}).get("Shaders") or "shaders")
    for src in sorted(DUCK_OWN_SHADERS.glob("*.glsl")):
        try:
            data = src.read_bytes()
            out = dst / src.name
            if not out.is_file() or out.read_bytes() != data:
                dst.mkdir(parents=True, exist_ok=True)
                out.write_bytes(data)
        except OSError as e:
            log("DuckStation: Shader", src.name, e)


class _MgbaShader:
    """Shader von mGBA: [ports.qt] shader = Ordner des Shaders (ShaderSelector.cpp), leer = keiner. Was gewaehlt ist, merkt
    sich VoidStation in EMU_OWN ([gba] look = Wert, shader = zuletzt eingetragener Pfad), weil der Pfad je Spiel wechseln kann:
    "Original-Farben" nimmt GBA Color, GBC Color oder bei Game-Boy-Spielen keinen, und ein Spiel kann einen eigenen Stil
    haben (emu-games.json). Steht in mGBA etwas anderes als zuletzt eingetragen, hat der Nutzer dort gewaehlt – das gilt."""
    ORIG = {".gbc": "gbc-color", ".gb": ""}        # .gb: Das Display des ersten Game Boy hatte keine Farben zu korrigieren

    def __init__(self, folders):
        self.folders = folders                       # {Wert: Ordner unter MGBA_SHADERS ohne ".shader"}
        self.values = {"off", "orig"} | set(folders)

    def path(self, value, ext=""):
        name = self.ORIG.get(ext, "gba-color") if value == "orig" else self.folders.get(value, "")
        return str(MGBA_SHADERS / f"{name}.shader") if name else ""

    def derive(self, cur):
        if not cur:
            return "off"
        p = Path(cur)
        if str(p.parent) != str(MGBA_SHADERS):
            return None
        name = p.name.removesuffix(".shader")
        if name in ("gba-color", "gbc-color"):
            return "orig"
        return next((v for v, folder in self.folders.items() if folder == name), None)

    def read(self, ini):
        cur = ini.get("ports.qt", {}).get("shader", "").strip()
        own = ini_read(EMU_OWN).get("gba", {})
        if "look" in own and cur == own.get("shader", ""):
            return own["look"] if own["look"] in self.values else None
        return self.derive(cur)

    def write(self, path, value):
        shader = self.path(value)
        ini_update(EMU_OWN, "gba", {"look": value, "shader": shader})
        ini_update(path, "ports.qt", {"shader": shader})


def mgba_look_game(game):
    """Vor jedem Start von mGBA den Shader fuer dieses Spiel eintragen: die Wahl fuer das Spiel, sonst die allgemeine
    (Original-Farben je nach Endung). Hat der Nutzer in mGBA selbst einen Shader gewaehlt, wird das die allgemeine Wahl
    (ein fremder bleibt als Pfad gemerkt und kommt nach einem Spiel mit eigenem Stil zurueck). Aufruf mit EMU_LOCK."""
    io = _MGBA_LOOK_IO
    own = dict(ini_read(EMU_OWN).get("gba", {}))
    cur = ini_read(MGBA_CONFIG).get("ports.qt", {}).get("shader", "").strip()
    if "look" not in own or cur != own.get("shader", ""):
        own["look"], own["keep"] = io.derive(cur) or "custom", cur
    mine = emu_opts_game("gba", os.path.basename(game)).get("look") if game else None
    ext = Path(game).suffix.lower() if game else ""
    want = mine or own["look"]
    shader = io.path(want, ext) if want in io.values else own.get("keep", "")
    if shader != cur:
        ini_update(MGBA_CONFIG, "ports.qt", {"shader": shader})
        log(f"mGBA: Bildstil {want}{' (Spiel)' if mine else ''}: {Path(shader).name or 'ohne Shader'}")
    ini_update(EMU_OWN, "gba", {"look": own["look"], "keep": own.get("keep", ""), "shader": shader})


_OFF = {"v": "off", "k": "common.off"}
_KLAR = {"k": "emuopt.v.klar"}                 # eigener Stil von VoidStation (launcher/shaders/LIESMICH.txt)
DUCK_LOOKS = [                                 # (Wert, ShaderName, Beschriftung: Schluessel "k" oder fester Name "t")
    ("klar", "voidstation-klar", _KLAR),
    ("crt-lottes", "crt-lottes", {"t": "CRT-Lottes"}),
    ("crt-lottes2", "CRTLottes2", {"t": "CRT-Lottes 2"}),
    ("crt-hyllian", "dolphinfx/crt/CRT-HYLLIAN", {"t": "CRT-Hyllian"}),
    ("crt-newpixie", "CRT-NewPixie", {"t": "CRT-NewPixie"}),
    ("scanlines", "dolphinfx/scanlines", {"k": "emuopt.v.scanlines"}),
    ("scanlines-4x2", "scanline-modern-4x2", {"t": "Scanlines 4×2"}),
    ("scanlines-ex", "scanline-modern-ex", {"t": "Scanlines EX"}),
    ("scanlines-abs", "scanlines-abs", {"t": "Scanlines abs"}),
    ("ntsc", "ntsc/ntsc-adaptive-lite", {"t": "NTSC"}),
    ("sharpen", "simple-sharpen", {"k": "emuopt.v.sharpen"}),
    ("bicubic", "interpolation/bicubic", {"k": "emuopt.v.bicubic"}),
    ("deband", "Deband", {"k": "emuopt.v.deband"}),
    ("grain", "FilmGrain2", {"k": "emuopt.v.grain"}),
    ("pixellate", "dolphinfx/pixel-art/PIXELLATE", {"t": "Pixellate"}),
    ("ddt", "dolphinfx/edge-smoothing/DDT", {"t": "DDT"}),
    ("xbr", "dolphinfx/edge-smoothing/XBR", {"t": "xBR"}),
    ("super-xbr", "edge-smoothing/super-xbr", {"t": "Super-xBR"}),
]
# Farbe: bei DuckStation eigene Shader mit festen Werten, bei PCSX2 dessen ShadeBoost (Wert / 50 = Faktor) – dieselbe
# Formel (shadeboost.glsl), dieselben Zahlen, also derselbe Eindruck auf beiden. "Warm" o. Ae. kann ShadeBoost nicht.
DUCK_COLORS = {"vivid": "voidstation-kraeftig", "bright": "voidstation-hell"}
_COLOR_CHOICES = [{"v": "nat", "k": "emuopt.v.natural"}, {"v": "vivid", "k": "emuopt.v.vivid"},
                  {"v": "bright", "k": "emuopt.v.bright"}]


def _shadeboost(on, brightness=50, contrast=50, saturation=50, gamma=50):
    if not on:
        return {"ShadeBoost": "false"}
    return {"ShadeBoost": "true", "ShadeBoost_Brightness": str(brightness), "ShadeBoost_Contrast": str(contrast),
            "ShadeBoost_Saturation": str(saturation), "ShadeBoost_Gamma": str(gamma)}


PCSX2_COLORS = [dict(_COLOR_CHOICES[0], set=_shadeboost(False)),
                dict(_COLOR_CHOICES[1], set=_shadeboost(True, contrast=54, saturation=60)),
                dict(_COLOR_CHOICES[2], set=_shadeboost(True, brightness=54, gamma=55))]
PCSX2_LOOKS = [{"v": "0", "k": "common.off"}, {"v": "5", "t": "Lottes CRT"}, {"v": "1", "k": "emuopt.v.scanlines"},
               {"v": "2", "k": "emuopt.v.diagonal"}, {"v": "3", "k": "emuopt.v.triangular"},
               {"v": "4", "k": "emuopt.v.wave"}, {"v": "6", "t": "4×RGSS"}, {"v": "7", "t": "N×AGSS"}]
MGBA_LOOKS = [                                 # (Wert = Ordner unter launcher/shaders/mgba ohne ".shader", Beschriftung)
    ("agb001", {"t": "AGB-001"}), ("ags001", {"t": "AGS-001"}), ("sp101-color", {"t": "GBA SP 101"}),
    ("nso-gba-color", {"t": "NSO GBA"}), ("nso-gbc-color", {"t": "NSO GBC"}), ("gb-micro-color", {"t": "GB Micro"}),
    ("dslite-color", {"t": "DS Lite"}), ("nds-color", {"t": "Nintendo DS"}), ("wiiu", {"t": "Wii U"}),
    ("lcd", {"t": "LCD"}), ("gbc-lcd", {"t": "GBC-LCD"}), ("tv-mode", {"k": "emuopt.v.tv"}),
    ("scanlines", {"k": "emuopt.v.scanlines"}), ("soften", {"k": "emuopt.v.soft"}),
    ("motion_blur", {"k": "emuopt.v.motionBlur"}), ("vignette", {"k": "emuopt.v.vignette"}),
    ("pixelate", {"t": "Pixelate"}), ("vba_pixelate", {"t": "VBA Pixelate"}), ("scale2x", {"t": "Scale2x"}),
    ("scale4x", {"t": "Scale4x"}), ("hq2x", {"t": "hq2x"}), ("xbr-lv2", {"t": "xBR-lv2"}), ("xbr-lv3", {"t": "xBR-lv3"}),
    ("mmpx", {"t": "MMPX"}), ("fish", {"t": "fish"}),       # OmniScale braucht "outputSize", das mGBA 0.10.5 nicht kennt
]
DOSBOX_LOOKS = [
    {"v": "sharp", "k": "emuopt.v.sharp"}, {"v": "nearest", "k": "emuopt.v.nearest"},
    {"v": "bilinear", "k": "emuopt.v.soft"}, {"v": "interpolation/catmull-rom", "t": "Catmull-Rom"},
    {"v": "crt-auto", "k": "emuopt.v.crt"}, {"v": "crt-auto-machine", "k": "emuopt.v.crtMachine"},
    {"v": "crt-auto-arcade", "k": "emuopt.v.crtArcade"}, {"v": "crt-auto-arcade-sharp", "k": "emuopt.v.crtArcadeSharp"},
    {"v": "scaler/xbr-lv3", "t": "xBR-lv3"}, {"v": "scaler/xbr-lv2-3d", "t": "xBR-lv2 3D"},
    {"v": "scaler/xbr-lv2-noblend", "t": "xBR-lv2 noblend"}, {"v": "scaler/advmame2x", "t": "AdvMAME2x"},
    {"v": "scaler/advmame3x", "t": "AdvMAME3x"}, {"v": "scaler/advinterp2x", "t": "AdvInterp2x"},
    {"v": "scaler/advinterp3x", "t": "AdvInterp3x"},
]
_DUCK_LOOK_IO = _DuckDisplay(0, {v: name for v, name, _ in DUCK_LOOKS}, DUCK_COLORS)
_DUCK_COLOR_IO = _DuckDisplay(1, {v: name for v, name, _ in DUCK_LOOKS}, DUCK_COLORS)
# Vor dem Hochrechnen aufs Display, in der Renderaufloesung: guenstiger. "auto" und "on" schreiben dasselbe; auf Automatik
# nehmen Spielprofile die Glaettung bei Pixelgrafik heraus (gameprofiles.PSX_CATEGORIES)
_DUCK_FXAA_IO = _DuckSingle("InternalPostProcessing", {"auto": "anti-aliasing/fxaa", "on": "anti-aliasing/fxaa"})
_MGBA_LOOK_IO = _MgbaShader(dict({"klar": "voidstation-klar"}, **{v: v for v, _ in MGBA_LOOKS}))


# ---- PPSSPP, Dolphin, Cemu, Azahar (Paul, 13.11.2026: "zur Vereinheitlichung eine vollstaendige Optionsseite") ----
# Schluessel geprueft am 13.11.2026: PPSSPP v1.20.4 (Void-Paket) Core/Config.cpp + assets/shaders/defaultshaders.ini,
# Dolphin 2609 (Void-Paket) Core/Config/GraphicsSettings.cpp, MainSettings.cpp, VideoCommon/VideoConfig.h, Data/Sys/Shaders,
# Cemu (main) src/config/CemuConfig.cpp/.h, Azahar (master) src/common/settings.h, citra_qt/configuration/config.cpp.
_OPT_TFC = [{"v": "True", "k": "common.on"}, {"v": "False", "k": "common.off"}]     # PPSSPP, Dolphin: True/False


class _OtherIni:
    """Schluessel in einer anderen Datei als der der Kachel (Dolphin: Dolphin.ini neben GFX.ini). Nur allgemein."""

    def __init__(self, path, section, key, default):
        self.path, self.section, self.key, self.default = path, section, key, default

    def read(self, ini):
        return ini_read(self.path()).get(self.section, {}).get(self.key, self.default)

    def write(self, path, value):
        ini_update(self.path(), self.section, {self.key: value})


class _QtIni:
    """Qt-Einstellungsdatei von Azahar: Neben jedem Schluessel steht "<Schluessel>\\default"; ist das true, gilt die
    Vorgabe des Programms, egal was im Schluessel steht (config.cpp ReadBasicSetting). Geschrieben wird beides, wie
    Azahar es selbst tut. fallback: laesst sich je Spiel fuer einen Start in die Haupteinstellung eintragen."""
    fallback = True

    def __init__(self, section, key, default):
        self.section, self.key, self.default = section, key, default

    def read(self, ini):
        sec = ini.get(self.section, {})
        if self.key not in sec or sec.get(self.key + "\\default", "false").strip().lower() == "true":
            return self.default
        return qt_unquote(sec[self.key])

    def writes(self, value, ini):
        return {self.section: {self.key: value, self.key + "\\default": "true" if value == self.default else "false"}}, {}

    def write(self, path, value):
        _io_apply(path, *self.writes(value, {}))


class _CemuXml:
    """Wert in Cemus settings.xml (<content><Graphic><api>…). Die Datei muss es schon geben (EMU_READY)."""

    def __init__(self, path, default):
        self.path, self.default = path, default

    def read(self, ini):
        try:
            node = ET.parse(emu_dir("cemu") / "settings.xml").getroot().find("/".join(self.path))
        except (OSError, ET.ParseError):
            return self.default
        return (node.text or "").strip() if node is not None and (node.text or "").strip() else self.default

    def write(self, path, value):
        try:
            tree = ET.parse(path)
        except (OSError, ET.ParseError) as e:
            log("Cemu: settings.xml:", e)
            return
        node = tree.getroot()
        for name in self.path:
            nxt = node.find(name)
            node = ET.SubElement(node, name) if nxt is None else nxt
        node.text = value
        tmp = path.with_name(path.name + ".vs-tmp")
        tree.write(tmp, encoding="UTF-8", xml_declaration=True)
        tmp.replace(path)


class _PpssppShader:
    """Nachbearbeitung von PPSSPP: [PostShaderList] PostShader1…n = Name des Shaders (Abschnitt in defaultshaders.ini),
    "Off" zaehlt nicht (Config.cpp). Hier: genau einer oder keiner; eine laengere Kette des Nutzers -> kein Knopf an."""

    def __init__(self, names):
        self.names = set(names)

    def read(self, ini):
        chain = [v.strip() for k, v in sorted(ini.get("PostShaderList", {}).items())
                 if k.startswith("PostShader") and v.strip() and v.strip() != "Off"]
        if not chain:
            return "off"
        return chain[0] if len(chain) == 1 and chain[0] in self.names else None

    def write(self, path, value):
        drop = [k for k in ini_read(path).get("PostShaderList", {}) if k.startswith("PostShader") and k != "PostShader1"]
        ini_update(path, "PostShaderList", {"PostShader1": "Off" if value == "off" else value}, remove=drop)


PPSSPP_LOOKS = [                               # (Abschnitt in defaultshaders.ini, Beschriftung); ohne Stereo-Shader
    ("PSPColor", {"k": "emuopt.v.orig"}), ("FXAA", {"t": "FXAA"}), ("Sharpen", {"k": "emuopt.v.sharpen"}),
    ("FSR-RCAS", {"t": "FSR (RCAS)"}), ("FSR-EASU", {"t": "FSR (EASU)"}), ("UpscaleSharpBilinear", {"t": "Sharp Bilinear"}),
    ("UpscaleBicubic", {"k": "emuopt.v.bicubic"}), ("UpscaleSpline36", {"t": "Spline36"}), ("SSAA(Gauss)", {"t": "SSAA (Gauss)"}),
    ("VideoSmoothingAA", {"t": "Video AA"}), ("AAColor", {"t": "AA-Color"}), ("Natural", {"t": "Natural Colors"}),
    ("NaturalA", {"t": "Natural Colors (No Blur)"}), ("ColorCorrection", {"t": "Color Correction"}),
    ("CRT", {"t": "CRT"}), ("Scanlines", {"k": "emuopt.v.scanlines"}), ("LCDPersistence", {"t": "LCD Persistence"}),
    ("Vignette", {"k": "emuopt.v.vignette"}), ("Bloom", {"t": "Bloom"}), ("BloomNoBlur", {"t": "Bloom (no blur)"}),
    ("FakeReflections", {"t": "Fake Reflections"}), ("Cartoon", {"t": "Cartoon"}), ("4xHqGLSL", {"t": "4xHQ"}),
    ("5xBR", {"t": "5xBR"}), ("5xBR-lv2", {"t": "5xBR lv2"}),
]
# Dateien in Dolphins Sys/Shaders ohne ".glsl" – so heissen sie auch in Dolphin selbst. Nicht dabei: die Werkzeuge
# default_pre_post_process, AutoHDR, PerceptualHDR, swap_RGB_*
DOLPHIN_LOOKS = ["FXAA", "integer_scaling", "brighten", "darkerbrighter", "sunset", "sepia", "grayscale", "grayscale2",
                 "16bit", "32bit", "posterize", "posterize2", "primarycolors", "auto_toon", "auto_toon2", "sketchy",
                 "emboss", "invertedoutline", "bad_bloom", "lens_distortion", "asciiart", "nightvision", "nightvision2",
                 "nightvision2scanlines", "acidmetal", "acidtrip", "acidtrip2", "chrismas", "cool1", "fire", "fire2",
                 "firewater", "invert", "invert_blue", "mad_world", "spookey1", "spookey2", "toxic"]
_AUTO0 = {"v": "0", "k": "emuopt.v.auto"}
_PPSSPP_LOOK_IO = _PpssppShader([n for n, _ in PPSSPP_LOOKS])


# ---- RMG, Flycast, xemu, melonDS, Snes9x, Nestopia, MAME, ScummVM, VICE, Stella (Paul, 13.11.2026: "Alle 10") ----
# Schluessel geprueft am 13.11.2026: RMG (GLideN64 mit eigener Oberflaeche: GLideNUI/Settings.cpp, Config.cpp/.h),
# Flycast (master) core/cfg/option.cpp, xemu (master) config_spec.yml, melonDS 1.1 frontend/qt_sdl/Config.cpp,
# Snes9x 1.60 gtk/src/gtk_config.cpp + gtk_display.h, Nestopia 1.53.2 fltkui/setmanager.cpp + jg.cpp, MAME 0.282
# emuopts.cpp, osdobj_common.cpp, bgfx/chains, ScummVM 2026.1.0 base/commandLine.cpp, graphics/scaler, opengl-graphics.cpp,
# VICE 3.9 video/video-resources.c, video.h, vicii-resources.c, Stella 6.5.3 emucore/Settings.cxx, repository/sqlite.
_OPT_YN = [{"v": "yes", "k": "common.on"}, {"v": "no", "k": "common.off"}]          # Flycast


def rmg_gliden():
    return emu_dir("rmg") / "GLideN64.ini"


class _QtProfile:
    """GLideN64.ini (QSettings): [General] profile nennt den Abschnitt mit den Einstellungen (Vorgabe "User"), darin
    Schluessel wie "video\\fxaa". fallback: laesst sich je Spiel fuer einen Start eintragen."""
    fallback = True

    def __init__(self, key, default):
        self.key, self.default = key, default

    def _sec(self, ini):
        return qt_unquote(ini.get("General", {}).get("profile", "")) or "User"

    def read(self, ini):
        return qt_unquote(ini.get(self._sec(ini), {}).get(self.key, self.default))

    def writes(self, value, ini):
        return {self._sec(ini or ini_read(rmg_gliden())): {self.key: value}}, {}

    def write(self, path, value):
        _io_apply(path, *self.writes(value, ini_read(path)))


class _IniStore:
    """Ein Abschnitt einer INI-Datei, deren Zeilen hinten Kommentare tragen (snes9x.conf: "AspectRatio = 2  # 0: …",
    conffile.cpp)."""

    def __init__(self, path, section):
        self.path, self.section = path, section

    def values(self, keys):
        return {k: v.split("#", 1)[0].strip() for k, v in ini_read(self.path()).get(self.section, {}).items() if k in keys}

    def put(self, updates):
        ini_update(self.path(), self.section, updates)


class _TomlStore:
    """melonDS.toml, xemu.toml: ganz lesen, Werte an ihren Pfaden setzen, ganz schreiben (toml_dump)."""

    def __init__(self, load, save):
        self._load, self._save = load, save

    def values(self, keys):
        root = self._load()
        if root is None:
            return None
        out = {}
        for path in keys:
            node: Any = root
            for name in path:
                node = node.get(name) if isinstance(node, dict) else None
            if node is not None:
                out[path] = node
        return out

    def put(self, updates):
        root = self._load()
        if root is None:
            return
        for path, value in updates.items():
            node = root
            for name in path[:-1]:
                node = node.setdefault(name, {})
            node[path[-1]] = value
        self._save(root)


def _melonds_load():
    import tomllib
    try:
        return tomllib.loads(MELONDS_TOML.read_text(encoding="utf-8")) if MELONDS_TOML.exists() else {}
    except (OSError, ValueError) as e:
        log("melonDS.toml nicht lesbar:", e)
        return None


def _melonds_save(root):
    MELONDS_TOML.parent.mkdir(parents=True, exist_ok=True)
    tmp = MELONDS_TOML.with_suffix(".vs-tmp")
    tmp.write_text(toml_dump(root), encoding="utf-8")
    tmp.replace(MELONDS_TOML)


class _MameStore:
    """mame.ini: je Zeile "name   wert", Kommentare mit #."""

    def values(self, keys):
        out = {}
        try:
            for line in (MAME_DIR / "mame.ini").read_text(encoding="utf-8", errors="replace").splitlines():
                parts = line.split(None, 1)
                if parts and not parts[0].startswith("#") and parts[0] in keys:
                    out[parts[0]] = parts[1].strip() if len(parts) > 1 else ""
        except OSError:
            pass
        return out

    def put(self, updates):
        path, todo, out = MAME_DIR / "mame.ini", dict(updates), []
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return
        for line in lines:
            parts = line.split(None, 1)
            out.append(f"{parts[0]:<25} {todo.pop(parts[0])}" if parts and parts[0] in todo else line)
        out += [f"{k:<25} {v}" for k, v in todo.items()]
        tmp = path.with_name("mame.ini.vs-tmp")
        tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
        tmp.replace(path)


class _StellaStore:
    """Einstellungen von Stella: Tabelle settings (setting, value) in dessen SQLite-Datenbank."""

    def values(self, keys):
        if not STELLA_DB.is_file():
            return {}
        import sqlite3
        try:
            con = sqlite3.connect(f"file:{STELLA_DB}?mode=ro", uri=True, timeout=2)
            try:
                return {k: v for k, v in con.execute("SELECT setting, value FROM settings") if k in keys}
            finally:
                con.close()
        except sqlite3.Error as e:
            log("Stella: Datenbank:", e)
            return None

    def put(self, updates):
        if not STELLA_DB.is_file():
            return
        import sqlite3
        try:
            con = sqlite3.connect(STELLA_DB, timeout=2)
            try:
                with con:
                    con.executemany("INSERT OR REPLACE INTO settings (setting, value) VALUES (?, ?)", [(k, str(v)) for k, v in updates.items()])
            finally:
                con.close()
        except sqlite3.Error as e:
            log("Stella: Datenbank:", e)


class _Mapped:
    """Option in einem Speicher mit eigenem Format (TOML, mame.ini, SQLite). mapping: {Wert: {Schluessel: Inhalt}} – gewaehlt
    ist der erste Wert, dessen Inhalte alle passen; fehlt ein Schluessel im Speicher, gilt defaults. Inhalt als Liste:
    geschrieben wird der erste, beim Lesen gilt jeder (Stella: "true" oder "1"). Nur allgemein."""

    def __init__(self, store, mapping, defaults):
        self.store, self.mapping, self.defaults = store, mapping, defaults

    @staticmethod
    def _same(a, b):
        if isinstance(b, list):
            return any(_Mapped._same(a, x) for x in b)
        return a == b if isinstance(a, bool) or isinstance(b, bool) else _opt_norm(a) == _opt_norm(b)

    def read(self, ini):
        cur = self.store.values(set(self.defaults))
        if cur is None:
            return None
        return next((value for value, want in self.mapping.items()
                     if all(self._same(cur.get(k, self.defaults[k]), v) for k, v in want.items())), None)

    def write(self, path, value):
        self.store.put({k: v[0] if isinstance(v, list) else v for k, v in self.mapping[value].items()})


_XEMU = _TomlStore(lambda: xemu_load(), lambda root: xemu_save(root))
_MELON = _TomlStore(_melonds_load, _melonds_save)
_MAME, _STELLA, _S9X = _MameStore(), _StellaStore(), _IniStore(lambda: snes9x_conf(), "Display")


class _MdfnStore:
    """mednafen.cfg ("<name> <wert>")."""

    def values(self, keys):
        return mednafen_read(set(keys))

    def put(self, updates):
        mednafen_write(updates)


_MDFN = _MdfnStore()
_MDFN_SYS = ("md", "sms", "gg", "ss", "pce")
# videoip: Vorgabe je System (drivers/video.cpp: 1, wo das System die Aufloesung wechseln kann)
_MDFN_IP = {"md": "1", "sms": "0", "gg": "0", "ss": "1", "pce": "1"}


def _mdfn(oid, key, rows, default_content, default, **kw):
    """Dieselbe Einstellung fuer alle fuenf Systeme: rows [(Wert, Beschriftung, Inhalt)]"""
    return _map(oid, _MDFN, [(v, lab, {f"{m}.{key}": c for m in _MDFN_SYS}) for v, lab, c in rows],
                {f"{m}.{key}": default_content for m in _MDFN_SYS}, default, **kw)
_ST_ON, _ST_OFF = ["true", "1"], ["false", "0"]                     # Stella: Variant(bool) schreibt 1/0, die Vorgaben stehen als Wort


def _map(oid, store, rows, defaults, default, **kw):
    """rows: [(Wert, Beschriftung, {Schluessel: Inhalt})]"""
    return _opt(oid, "", oid, [dict(lab, v=v) for v, lab, _ in rows], default,
                io=_Mapped(store, {v: m for v, _, m in rows}, defaults), **kw)


def _one(oid, store, key, rows, default_content, default, **kw):
    """Ein Schluessel: rows [(Wert, Beschriftung, Inhalt)]"""
    return _map(oid, store, [(v, lab, {key: c}) for v, lab, c in rows], {key: default_content}, default, **kw)


def _gl64(oid, key, choices, default, **kw):
    return _opt(oid, "User", key, choices, default, io=_QtProfile(key, default), **kw)


_ON, _OFFK, _ORIG, _STRETCH = {"k": "common.on"}, {"k": "common.off"}, {"k": "emuopt.v.original"}, {"k": "emuopt.v.stretch"}
_MELON_3D, _MELON_SCALE, _MELON_GL = ("3D", "Renderer"), ("3D", "GL", "ScaleFactor"), ("Screen", "UseGL")
_MELON_LAY, _MELON_SIZE = ("Instance0", "Window0", "ScreenLayout"), ("Instance0", "Window0", "ScreenSizing")
_XEMU_FIT, _XEMU_AR = ("display", "ui", "fit"), ("display", "ui", "aspect_ratio")
SNES9X_FILTERS = [("7", {"k": "emuopt.v.scanlines"}), ("6", {"t": "NTSC"}), ("1", {"t": "Super Eagle"}), ("2", {"t": "2xSaI"}),
                  ("3", {"t": "Super 2xSaI"}), ("4", {"t": "EPX"}), ("5", {"t": "EPX Smooth"}), ("11", {"t": "HQ2x"}),
                  ("12", {"t": "HQ3x"}), ("13", {"t": "HQ4x"}), ("14", {"t": "2xBRZ"}), ("15", {"t": "3xBRZ"}), ("16", {"t": "4xBRZ"})]
SCUMMVM_SCALERS = [("hq", "HQ"), ("edge", "Edge"), ("advmame", "AdvMAME"), ("sai", "2xSaI"), ("supersai", "Super 2xSaI"),
                   ("supereagle", "Super Eagle"), ("pm", "PM"), ("dotmatrix", "DotMatrix"), ("tv", "TV")]


def _az(oid, section, key, choices, default, **kw):
    return _opt(oid, section, key, choices, default, io=_QtIni(section, key, default), **kw)


def _cemu(oid, key, choices, default, **kw):
    return _opt(oid, "Graphic", key, choices, default, io=_CemuXml(("Graphic", key), default), **kw)


EMU_OPTS: dict[str, Any] = {
    "pcsx2": {"file": lambda: PCSX2_INI, "groups": [
        ("picture", [
            _opt("res", "EmuCore/GS", "upscale_multiplier", _opt_res([2, 3, 4]), "1"),
            _opt("aspect", "EmuCore/GS", "AspectRatio", [
                {"v": "Auto 4:3/3:2", "k": "emuopt.v.auto"}, {"v": "4:3", "t": "4:3"}, {"v": "16:9", "t": "16:9"},
                {"v": "Stretch", "k": "emuopt.v.stretch"}], "Auto 4:3/3:2", game=True),
            _opt("widescreen", "EmuCore", "EnableWideScreenPatches", _OPT_TF, "false", game=True),
            _opt("noInterlace", "EmuCore", "EnableNoInterlacingPatches", _OPT_TF, "false"),
            _opt("aniso", "EmuCore/GS", "MaxAnisotropy", [
                {"v": "0", "k": "common.off"}, {"v": "4", "t": "4×"}, {"v": "8", "t": "8×"}, {"v": "16", "t": "16×"}], "0"),
            # Nachschaerfen (CAS, Config.h GSCASMode: 0 aus, 1 nur schaerfen, 2 schaerfen und auf Bildschirmgroesse rechnen)
            _opt("sharpen", "EmuCore/GS", "CASMode", [{"v": "0"}, {"v": "2"}], "0", hidden=True),
            # Texturpakete aus share/ROMs/ps2/textures/<Seriennummer>/replacements laden (wirkt nur, wo eins liegt)
            _opt("textures", "EmuCore/GS", "LoadTextureReplacements", _OPT_TF, "false", hidden=True),
            # Bildraten-Patch aus PCSX2' patches.zip, je Spiel eingetragen (EMU_PATCHES, _patches_apply)
            _opt("fps", "pcsx2", "fps", _OPT_TF, "false", game=True, hidden=True, own=True),
        ]),
        ("look", [
            _opt("fxaa", "EmuCore/GS", "fxaa", _OPT_TF, "false", game=True),
            _opt("color", "EmuCore/GS", "ShadeBoost", PCSX2_COLORS, "nat"),
            _opt("look", "EmuCore/GS", "TVShader", PCSX2_LOOKS, "0", game=True),
        ]),
        ("play", [
            _opt("fastBoot", "EmuCore", "EnableFastBoot", _OPT_TF, "true"),
            # Automatik nimmt unter Linux Vulkan, bei Intel-Grafik und Software-Treibern OpenGL (GSUtil::GetPreferredRenderer)
            _opt("renderer", "EmuCore/GS", "Renderer", [
                {"v": "-1", "k": "emuopt.v.auto"}, {"v": "14", "t": "Vulkan"}, {"v": "12", "t": "OpenGL"},
                {"v": "13", "t": "Software"}], "-1"),
        ]),
    ]},
    "duckstation": {"file": lambda: DUCK_INI, "groups": [
        ("picture", [
            _opt("res", "GPU", "ResolutionScale", _opt_res([2, 3, 4, 6]), "1"),
            _opt("aspect", "Display", "AspectRatio", [
                {"v": "Auto (Game Native)", "k": "emuopt.v.auto"}, {"v": "4:3", "t": "4:3"}, {"v": "16:9", "t": "16:9"},
                {"v": "Stretch To Fill", "k": "emuopt.v.stretch"}], "Auto (Game Native)", game=True),
            _opt("widescreen", "GPU", "WidescreenHack", _OPT_TF, "false", game=True),
            _opt("pgxp", "GPU", "PGXPEnable", _OPT_TF, "false"),
            # Nur die Texturen der 3D-Flaechen; Sprites (Schrift, Menues) haben mit SpriteTextureFilter einen eigenen Filter
            _opt("texfilter", "GPU", "TextureFilter", [
                {"v": "auto", "k": "emuopt.v.auto", "set": {"TextureFilter": "Nearest"}, "auto": True},
                {"v": "BilinearBinAlpha", "k": "common.on"}, {"v": "Nearest", "k": "common.off"}], "auto", game=True),
            # Filmsequenzen (24-Bit-Bild): Farbkloetzchen glaetten
            _opt("fmvSmooth", "GPU", "ChromaSmoothing24Bit", _OPT_TF, "false", hidden=True),
            # Ersatzbilder fuer gemalte Hintergruende aus share/ROMs/psx/textures/<Seriennummer>/replacements (nur, wo welche liegen).
            # Ersatz fuer 3D-Texturen braucht DuckStations Textur-Cache (GPU/EnableTextureCache) – der bleibt aus.
            _opt("textures", "TextureReplacements", "EnableVRAMWriteReplacements", _OPT_TF, "false", hidden=True),
            # Echte Breitbild- und Bildraten-Patches aus DuckStations patches.zip, je Spiel eingetragen (EMU_PATCHES)
            _opt("wsPatch", "duckstation", "wsPatch", _OPT_TF, "false", game=True, hidden=True, own=True, label="widescreen"),
            _opt("fps", "duckstation", "fps", _OPT_TF, "false", game=True, hidden=True, own=True),
        ]),
        ("look", [
            # In der Kette vor der Ausgabe (InternalPostProcessing, Renderaufloesung) statt am fertigen Bild: guenstiger
            _opt("fxaa", "InternalPostProcessing", "Enabled", [
                {"v": "auto", "k": "emuopt.v.auto", "auto": True}, {"v": "on", "k": "common.on"}, _OFF], "off",
                 game=True, io=_DUCK_FXAA_IO),
            _opt("color", "PostProcessing", "Enabled", _COLOR_CHOICES, "nat", io=_DUCK_COLOR_IO),
            _opt("look", "PostProcessing", "Enabled", [_OFF] + [dict(lab, v=v) for v, _, lab in DUCK_LOOKS], "off",
                 game=True, io=_DUCK_LOOK_IO),
        ]),
        ("play", [
            _opt("fastBoot", "BIOS", "PatchFastBoot", _OPT_TF, "false"),
            _opt("resume", "Main", "SaveStateOnExit", _OPT_TF, "true"),
            # Daten 4-mal so schnell von der CD lesen; Musik und Filme laufen normal (cdrom.cpp CanUseReadSpeedup), bei
            # Spielen, die es nicht vertragen, schaltet DuckStation selbst ab (gamedb DisableCDROMReadSpeedup)
            _opt("cdSpeed", "CDROM", "ReadSpeedup", [{"v": "1"}, {"v": "4"}], "1", hidden=True),
            # Automatik nimmt unter Linux Vulkan, nur bei Software-Treibern und alter Intel-Grafik (bis Broadwell) OpenGL
            _opt("renderer", "GPU", "Renderer", [
                {"v": "Automatic", "k": "emuopt.v.auto"}, {"v": "Vulkan", "t": "Vulkan"}, {"v": "OpenGL", "t": "OpenGL"},
                {"v": "Software", "t": "Software"}], "Automatic"),
        ]),
    ]},
    "gba": {"file": lambda: MGBA_CONFIG, "groups": [
        ("picture", [
            _opt("integer", "ports.qt", "lockIntegerScaling", _OPT_10, "1"),
            _opt("smooth", "ports.qt", "resampleVideo", _OPT_10, "0"),
            _opt("blend", "ports.qt", "interframeBlending", _OPT_10, "0"),
            _opt("sgb", "ports.qt", "sgb.borders", _OPT_10, "1"),
        ]),
        ("look", [
            _opt("look", "ports.qt", "shader", [_OFF, dict(_KLAR, v="klar"), {"v": "orig", "k": "emuopt.v.orig"}] +
                 [dict(lab, v=v) for v, lab in MGBA_LOOKS], "off", game=True, io=_MGBA_LOOK_IO),
        ]),
        ("play", [
            _opt("resume", "ports.qt", ["autosave", "autoload"], _OPT_10, "1"),
            _opt("rewind", "ports.qt", "rewindEnable", _OPT_10, "0"),
            _opt("ffSpeed", "ports.qt", "fastForwardRatio", [
                {"v": "-1", "k": "emuopt.v.unlimited"}, {"v": "2", "t": "2×"}, {"v": "3", "t": "3×"},
                {"v": "4", "t": "4×"}], "-1"),
        ]),
    ]},
    "dosbox": {"file": lambda: dosbox_primary(), "groups": [
        ("picture", [
            _opt("aspect", "render", "aspect", [
                {"v": "auto", "t": "4:3"}, {"v": "square-pixels", "k": "emuopt.v.square"},
                {"v": "stretch", "k": "emuopt.v.stretch"}], "auto"),
            _opt("integer", "render", "integer_scaling", [
                {"v": "auto", "k": "emuopt.v.auto"}, {"v": "off", "k": "common.off"}], "auto"),
            _opt("fullscreen", "sdl", "fullscreen", _OPT_TF, "true"),
        ]),
        ("look", [
            _opt("shader", "render", "glshader", DOSBOX_LOOKS, "crt-auto", game=True, label="look"),
        ]),
        ("play", [
            _opt("speed", "cpu", ["cpu_cycles", "cpu_cycles_protected"], [
                {"v": "std", "k": "emuopt.v.standard", "set": _opt_cycles("4000", "60000")},
                {"v": "xt", "t": "XT", "set": _opt_cycles("300", "300")},
                {"v": "286", "t": "286", "set": _opt_cycles("1500", "1500")},
                {"v": "386", "t": "386", "set": _opt_cycles("6000", "6000")},
                {"v": "486", "t": "486", "set": _opt_cycles("25000", "25000")},
                {"v": "pentium", "t": "Pentium", "set": _opt_cycles("50000", "50000")},
                {"v": "max", "t": "Max", "set": _opt_cycles("max", "max")}], "std", game=True),
            _opt("soundCard", "sblaster", "sbtype", [
                {"v": "sb16", "t": "Sound Blaster 16"}, {"v": "sbpro2", "t": "Sound Blaster Pro 2"},
                {"v": "sb1", "t": "Sound Blaster 1.0"}], "sb16", game=True),
            _opt("reverb", "mixer", "reverb", [
                {"v": "off", "k": "common.off"}, {"v": "small", "k": "emuopt.v.small"},
                {"v": "medium", "k": "emuopt.v.medium"}, {"v": "large", "k": "emuopt.v.large"}], "off"),
        ]),
    ]},
    "ppsspp": {"file": lambda: PPSSPP_INI, "groups": [
        ("picture", [
            # 0 = so gross wie das Fenster; PPSSPP waehlt ohne Eintrag 2-fach, sobald der Bildschirm 1000 Punkte breit ist
            _opt("res", "Graphics", "InternalResolution", [_AUTO0] + _opt_res([2, 3, 4, 5]), "2", game=True),
            _opt("aspect", "DisplayLayout.Landscape", "DisplayStretch", [
                {"v": "False", "k": "emuopt.v.original"}, {"v": "True", "k": "emuopt.v.stretch"}], "False", game=True),
            _opt("integer", "DisplayLayout.Landscape", "DisplayIntegerScale", _OPT_TFC, "False"),
            _opt("aniso", "Graphics", "AnisotropyLevel", [
                {"v": "0", "k": "common.off"}, {"v": "1", "t": "2×"}, {"v": "2", "t": "4×"}, {"v": "3", "t": "8×"},
                {"v": "4", "t": "16×"}], "4"),
        ]),
        ("look", [
            # Zahl der Abtastungen ist 1 << Wert; wirkt nur mit Vulkan
            _opt("msaa", "Graphics", "MultiSampleLevel", [
                {"v": "0", "k": "common.off"}, {"v": "1", "t": "2×"}, {"v": "2", "t": "4×"}, {"v": "3", "t": "8×"}], "0"),
            _opt("look", "PostShaderList", "PostShader1", [_OFF] + [dict(lab, v=v) for v, lab in PPSSPP_LOOKS], "off",
                 io=_PPSSPP_LOOK_IO),
        ]),
        ("play", [
            # PPSSPP schreibt "<Nummer> (<Name>)" und liest die Nummer (ConfigTranslator)
            _opt("renderer", "Graphics", "GraphicsBackend", [
                {"v": "3 (VULKAN)", "t": "Vulkan"}, {"v": "0 (OPENGL)", "t": "OpenGL"}], "3 (VULKAN)"),
        ]),
    ]},
    "dolphin": {"file": lambda: dolphin_dir() / "GFX.ini", "groups": [
        ("picture", [
            _opt("res", "Settings", "InternalResolution", [_AUTO0] + _opt_res([2, 3, 4, 5, 6]), "1", game=True),
            _opt("aspect", "Settings", "AspectRatio", [                     # VideoConfig.h AspectMode
                _AUTO0, {"v": "2", "t": "4:3"}, {"v": "1", "t": "16:9"}, {"v": "3", "k": "emuopt.v.stretch"}], "0", game=True),
            _opt("widescreen", "Settings", "wideScreenHack", _OPT_TFC, "False", game=True),
            _opt("aniso", "Enhancements", "MaxAnisotropy", [                # AnisotropicFilteringMode: -1 = wie das Spiel
                {"v": "-1", "k": "emuopt.v.standard"}, {"v": "1", "t": "2×"}, {"v": "2", "t": "4×"}, {"v": "3", "t": "8×"},
                {"v": "4", "t": "16×"}], "-1"),
        ]),
        ("look", [
            _opt("msaa", "Settings", "MSAA", [
                {"v": "1", "k": "common.off"}, {"v": "2", "t": "2×"}, {"v": "4", "t": "4×"}, {"v": "8", "t": "8×"}], "1"),
            _opt("look", "Enhancements", "PostProcessingShader", [dict(_OFF, set={"PostProcessingShader": ""})] +
                 [{"v": n, "t": n} for n in DOLPHIN_LOOKS], "off", game=True),
        ]),
        ("play", [
            # ShaderCompilationMode 2 = AsynchronousUberShaders: kein Stocken, waehrend Dolphin Shader uebersetzt
            _opt("asyncShaders", "Settings", "ShaderCompilationMode", [
                {"v": "2", "k": "common.on"}, {"v": "0", "k": "common.off"}], "0"),
            _opt("renderer", "Core", "GFXBackend", [
                {"v": "OGL", "t": "OpenGL"}, {"v": "Vulkan", "t": "Vulkan"}, {"v": "Software Renderer", "t": "Software"}],
                 "OGL", io=_OtherIni(lambda: dolphin_dir() / "Dolphin.ini", "Core", "GFXBackend", "OGL")),
        ]),
    ]},
    # Cemu: keine allgemeine Aufloesung – die stellen bei der Wii U Grafikpakete je Spiel ein (in Cemu selbst)
    "cemu": {"file": lambda: emu_dir("cemu") / "settings.xml", "groups": [
        ("picture", [
            _cemu("aspect", "FullscreenScaling", [
                {"v": "0", "k": "emuopt.v.original"}, {"v": "1", "k": "emuopt.v.stretch"}], "0"),
        ]),
        ("look", [
            _cemu("upscale", "UpscaleFilter", [                             # CemuConfig.h: 0 linear … 3 naechster Nachbar
                {"v": "0", "k": "emuopt.v.soft"}, {"v": "1", "k": "emuopt.v.bicubic"}, {"v": "2", "t": "Hermite"},
                {"v": "3", "k": "emuopt.v.nearest"}], "2"),
        ]),
        ("play", [
            _cemu("asyncShaders", "AsyncCompile", _OPT_TF, "true"),
            _cemu("renderer", "api", [{"v": "1", "t": "Vulkan"}, {"v": "0", "t": "OpenGL"}], "1"),
        ]),
    ]},
    "azahar": {"file": lambda: AZAHAR_INI, "groups": [
        ("picture", [
            _az("res", "Renderer", "resolution_factor", [_AUTO0] + _opt_res([2, 3, 4, 5]), "1", game=True),
            _az("layout", "Layout", "layout_option", [                      # settings.h LayoutOption (4 = eigene Fenster)
                {"v": "0", "k": "emuopt.v.layStd"}, {"v": "2", "k": "emuopt.v.layLarge"}, {"v": "3", "k": "emuopt.v.laySide"},
                {"v": "1", "k": "emuopt.v.laySingle"}, {"v": "5", "k": "emuopt.v.layHybrid"}], "0", game=True),
            _az("swap", "Layout", "swap_screen", _OPT_TF, "false", game=True),
            _az("integer", "Renderer", "use_integer_scaling", _OPT_TF, "false"),
            _az("smooth", "Layout", "filter_mode", _OPT_TF, "true"),
        ]),
        ("look", [
            _az("texscale", "Renderer", "texture_filter", [                 # settings.h TextureFilter
                {"v": "0", "k": "common.off"}, {"v": "2", "k": "emuopt.v.bicubic"}, {"v": "1", "t": "Anime4K"},
                {"v": "3", "t": "ScaleForce"}, {"v": "4", "t": "xBRZ"}, {"v": "5", "t": "MMPX"}], "0"),
        ]),
        ("play", [
            _az("asyncShaders", "Renderer", "async_shader_compilation", _OPT_TF, "false"),
            _az("renderer", "Renderer", "graphics_api", [
                {"v": "1", "t": "OpenGL"}, {"v": "2", "t": "Vulkan"}, {"v": "0", "t": "Software"}], "1"),
        ]),
    ]},
    # RMG: Bild macht GLideN64 (mit RMG gebaut, eigene GLideN64.ini). 0 = so gross wie das Fenster (dessen Vorgabe)
    "rmg": {"file": rmg_gliden, "groups": [
        ("picture", [
            _gl64("res", "frameBufferEmulation\\nativeResFactor", [_AUTO0] + _opt_res([2, 3, 4]), "0", game=True),
            _gl64("aspect", "frameBufferEmulation\\aspect", [           # Config.h Aspect
                {"v": "1", "t": "4:3"}, {"v": "2", "t": "16:9"}, {"v": "0", "k": "emuopt.v.stretch"}], "1", game=True),
        ]),
        ("look", [
            _gl64("msaa", "video\\multisampling", [
                {"v": "0", "k": "common.off"}, {"v": "2", "t": "2×"}, {"v": "4", "t": "4×"}, {"v": "8", "t": "8×"}], "0"),
            _gl64("fxaa", "video\\fxaa", _OPT_10, "0"),
        ]),
        ("play", []),
    ]},
    "flycast": {"file": lambda: FLYCAST_CFG, "groups": [
        ("picture", [
            _opt("res", "config", "rend.Resolution", [                      # Hoehe in Zeilen, 480 = wie die Konsole
                {"v": "480", "k": "emuopt.v.original"}, {"v": "960", "t": "2×"}, {"v": "1440", "t": "3×"},
                {"v": "1920", "t": "4×"}], "480", game=True),
            _opt("widescreen", "config", "rend.WideScreen", _OPT_YN, "no", game=True),
            _opt("integer", "config", "rend.IntegerScale", _OPT_YN, "no"),
            _opt("smooth", "config", "rend.LinearInterpolation", _OPT_YN, "yes"),
            _opt("aniso", "config", "rend.AnisotropicFiltering", [
                {"v": "1", "k": "common.off"}, {"v": "2", "t": "2×"}, {"v": "4", "t": "4×"}, {"v": "8", "t": "8×"},
                {"v": "16", "t": "16×"}], "1"),
        ]),
        ("look", [
            _opt("texscale", "config", "rend.TextureUpscale2", [
                {"v": "1", "k": "common.off"}, {"v": "2", "t": "xBRZ 2×"}, {"v": "4", "t": "xBRZ 4×"},
                {"v": "6", "t": "xBRZ 6×"}], "1"),
        ]),
        ("play", [
            _opt("renderer", "config", "pvr.rend", [{"v": "0", "t": "OpenGL"}, {"v": "4", "t": "Vulkan"}], "0"),  # types.h RenderType
        ]),
    ]},
    "xemu": {"file": lambda: XEMU_TOML, "groups": [
        ("picture", [
            _one("res", _XEMU, ("display", "quality", "surface_scale"),
                 [("1", _ORIG, 1), ("2", {"t": "2×"}, 2), ("3", {"t": "3×"}, 3), ("4", {"t": "4×"}, 4)], 1, "1"),
            _map("aspect", _XEMU, [
                ("auto", {"k": "emuopt.v.auto"}, {_XEMU_FIT: "scale", _XEMU_AR: "auto"}),
                ("4:3", {"t": "4:3"}, {_XEMU_FIT: "scale", _XEMU_AR: "4x3"}),
                ("16:9", {"t": "16:9"}, {_XEMU_FIT: "scale", _XEMU_AR: "16x9"}),
                ("stretch", _STRETCH, {_XEMU_FIT: "stretch"})], {_XEMU_FIT: "scale", _XEMU_AR: "auto"}, "auto"),
            _one("smooth", _XEMU, ("display", "filtering"), [("true", _ON, "linear"), ("false", _OFFK, "nearest")], "linear", "true"),
        ]),
        ("play", [
            _one("renderer", _XEMU, ("display", "renderer"), [("OPENGL", {"t": "OpenGL"}, "OPENGL"), ("VULKAN", {"t": "Vulkan"}, "VULKAN")],
                 "OPENGL", "OPENGL"),
        ]),
    ]},
    # melonDS: Mehr als die Aufloesung der Konsole geht nur mit dem OpenGL-Renderer (3D.Renderer 1); "Original" ist der
    # Software-Renderer (dessen Vorgabe, am genauesten)
    "melonds": {"file": lambda: MELONDS_TOML, "groups": [
        ("picture", [
            _map("res", _MELON, [("1", _ORIG, {_MELON_3D: 0})] + [
                (str(n), {"t": f"{n}×"}, {_MELON_3D: 1, _MELON_SCALE: n, _MELON_GL: True}) for n in (2, 3, 4)],
                 {_MELON_3D: 0, _MELON_SCALE: 1, _MELON_GL: True}, "1"),
            _map("layout", _MELON, [
                ("std", {"k": "emuopt.v.layStd"}, {_MELON_LAY: 0, _MELON_SIZE: 0}),
                ("large", {"k": "emuopt.v.layLarge"}, {_MELON_LAY: 2, _MELON_SIZE: 1}),
                ("side", {"k": "emuopt.v.laySide"}, {_MELON_LAY: 2, _MELON_SIZE: 0}),
                ("single", {"k": "emuopt.v.laySingle"}, {_MELON_SIZE: 4}),
                ("hybrid", {"k": "emuopt.v.layHybrid"}, {_MELON_LAY: 3, _MELON_SIZE: 0})],
                 {_MELON_LAY: 0, _MELON_SIZE: 0}, "std"),
            _one("swap", _MELON, ("Instance0", "Window0", "ScreenSwap"), [("true", _ON, True), ("false", _OFFK, False)], False, "false"),
            _one("integer", _MELON, ("Instance0", "Window0", "IntegerScaling"), [("true", _ON, True), ("false", _OFFK, False)],
                 False, "false"),
            _one("smooth", _MELON, ("Screen", "Filter"), [("true", _ON, True), ("false", _OFFK, False)], True, "true"),
        ]),
        ("play", []),
    ]},
    "snes9x": {"file": snes9x_conf, "groups": [
        ("picture", [
            _map("aspect", _S9X, [                                          # gtk_config.cpp: 0 unkorrigiert, 2 = 4:3
                ("4:3", {"t": "4:3"}, {"AspectRatio": "2", "MaintainAspectRatio": "true", "ScaleToFit": "true"}),
                ("square", {"k": "emuopt.v.square"}, {"AspectRatio": "0", "MaintainAspectRatio": "true", "ScaleToFit": "true"}),
                ("stretch", _STRETCH, {"MaintainAspectRatio": "false", "ScaleToFit": "true"})],
                 {"AspectRatio": "2", "MaintainAspectRatio": "true", "ScaleToFit": "true"}, "4:3"),
            _one("smooth", _S9X, "BilinearFilter", [("true", _ON, "true"), ("false", _OFFK, "false")], "false", "false"),
        ]),
        ("look", [
            _one("filter", _S9X, "SoftwareScaleFilter", [("0", _OFFK, "0")] + [(v, lab, v) for v, lab in SNES9X_FILTERS],
                 "0", "0"),                                                 # gtk_display.h FILTER_*
        ]),
        ("play", []),
    ]},
    "nestopia": {"file": lambda: NESTOPIA_CONF, "groups": [
        ("picture", [
            _opt("aspect", "frontend", "v_aspect", [
                _AUTO0, {"v": "2", "t": "4:3"}, {"v": "1", "k": "emuopt.v.square"}], "0"),
        ]),
        ("look", [
            _opt("filter", "frontend", "v_postproc", [                      # setmanager.cpp: 2 = Sharp Bilinear (Vorgabe)
                {"v": "2", "k": "emuopt.v.sharp"}, {"v": "0", "k": "emuopt.v.nearest"}, {"v": "1", "k": "emuopt.v.soft"},
                {"v": "3", "k": "emuopt.v.crt"}, {"v": "4", "t": "MMPX"}, {"v": "5", "t": "OmniScale"}], "2"),
            _opt("ntsc", "nestopia", "ntsc_filter", _OPT_10, "0"),
        ]),
        ("play", []),
    ]},
    # MAME: Stile sind BGFX-Ketten (bgfx/chains) und brauchen "video bgfx"; "Aus" stellt auf opengl, wie es das Skript
    # von Void beim Anlegen der mame.ini eintraegt
    "mame": {"file": lambda: MAME_DIR / "mame.ini", "groups": [
        ("picture", [
            _one("aspect", _MAME, "keepaspect", [("1", _ORIG, "1"), ("0", _STRETCH, "0")], "1", "1"),
            _one("integer", _MAME, "unevenstretch", [("true", _ON, "0"), ("false", _OFFK, "1")], "1", "false"),
            _one("smooth", _MAME, "filter", [("true", _ON, "1"), ("false", _OFFK, "0")], "1", "true"),
        ]),
        ("look", [
            _map("look", _MAME, [("off", _OFFK, {"video": "opengl"})] + [
                (c, {"t": t}, {"video": "bgfx", "bgfx_screen_chains": c}) for c, t in (
                    ("crt-geom", "CRT-Geom"), ("crt-geom-deluxe", "CRT-Geom Deluxe"), ("hlsl", "HLSL"), ("lcd-grid", "LCD"))],
                 {"video": "opengl", "bgfx_screen_chains": "default"}, "off"),
        ]),
        ("play", []),
    ]},
    "scummvm": {"file": lambda: SCUMMVM_INI, "groups": [
        ("picture", [
            _opt("aspect", "scummvm", "stretch_mode", [                     # opengl-graphics.cpp s_supportedStretchModes
                {"v": "default", "k": "emuopt.v.auto"}, {"v": "fit_force_aspect", "t": "4:3"},
                {"v": "pixel-perfect", "k": "emuopt.v.nearest"}, {"v": "stretch", "k": "emuopt.v.stretch"}], "default"),
            _opt("smooth", "scummvm", "filtering", _OPT_TF, "false"),
        ]),
        ("look", [
            _opt("filter", "scummvm", "scaler", [{"v": "default", "k": "common.off"}] +
                 [{"v": v, "t": t} for v, t in SCUMMVM_SCALERS], "default"),
        ]),
        ("play", []),
    ]},
    # VICE (x64sc): vicerc haelt nur, was von der Vorgabe abweicht; Abschnitt [C64SC]
    "vice": {"file": lambda: VICE_RC, "groups": [
        ("picture", [
            _opt("aspect", "C64SC", "VICIIAspectMode", [                    # video.h VIDEO_ASPECT_MODE_*
                {"v": "2", "k": "emuopt.v.original"}, {"v": "0", "k": "emuopt.v.stretch"}], "2"),
            _opt("border", "C64SC", "VICIIBorderMode", [                    # 0 normal, 3 ohne Rand
                {"v": "0", "k": "emuopt.v.standard"}, {"v": "3", "k": "common.off"}], "0"),
            _opt("upscale", "C64SC", "VICIIGLFilter", [                     # video.h VIDEO_GLFILTER_*
                {"v": "2", "k": "emuopt.v.bicubic"}, {"v": "1", "k": "emuopt.v.soft"}, {"v": "0", "k": "emuopt.v.nearest"}], "2"),
        ]),
        ("look", [
            _opt("filter", "C64SC", "VICIIFilter", [                        # video.h VIDEO_FILTER_*: 1 = Roehre (Vorgabe)
                {"v": "1", "k": "emuopt.v.crt"}, {"v": "0", "k": "common.off"}, {"v": "2", "t": "Scale2x"}], "1"),
        ]),
        ("play", []),
    ]},
    # Mednafen: je System eigene Schluessel (md.stretch, ss.stretch …) – die Karte stellt alle fuenf gleich
    "mednafen": {"file": lambda: Path(os.devnull), "groups": [
        ("picture", [
            _mdfn("aspect", "stretch", [                                    # drivers/video.cpp StretchMode_List
                ("aspect_mult2", {"k": "emuopt.v.nearest"}, "aspect_mult2"), ("aspect", _ORIG, "aspect"),
                ("full", _STRETCH, "full")], "aspect_mult2", "aspect_mult2"),
            _map("smooth", _MDFN, [
                ("auto", {"k": "emuopt.v.auto"}, {f"{m}.videoip": v for m, v in _MDFN_IP.items()}),
                ("true", _ON, {f"{m}.videoip": "1" for m in _MDFN_SYS}),
                ("false", _OFFK, {f"{m}.videoip": "0" for m in _MDFN_SYS})],
                 {f"{m}.videoip": v for m, v in _MDFN_IP.items()}, "auto"),
        ]),
        ("look", [
            _mdfn("look", "shader", [                                       # Shader_List
                ("none", _OFFK, "none"), ("autoipsharper", {"k": "emuopt.v.sharp"}, "autoipsharper"),
                ("scale2x", {"t": "Scale2x"}, "scale2x"), ("sabr", {"t": "SABR"}, "sabr"),
                ("goat", {"k": "emuopt.v.crt"}, "goat")], "none", "none"),
            _mdfn("filter", "special", [("none", _OFFK, "none")] + [                 # Special_List
                (v, {"t": t}, v) for v, t in (("hq2x", "HQ2x"), ("hq3x", "HQ3x"), ("hq4x", "HQ4x"), ("scale2x", "Scale2x"),
                                              ("scale3x", "Scale3x"), ("scale4x", "Scale4x"), ("2xsai", "2xSaI"),
                                              ("super2xsai", "Super 2xSaI"), ("supereagle", "Super Eagle"))], "none", "none"),
            _mdfn("scanlines", "scanlines", [
                ("0", _OFFK, "0"), ("25", {"t": "25 %"}, "25"), ("50", {"t": "50 %"}, "50"), ("75", {"t": "75 %"}, "75")], "0", "0"),
        ]),
        ("play", []),
    ]},
    # Stella: Einstellungen stehen in einer Datenbank (STELLA_DB, _StellaStore) – als "Datei" der Kachel dient nichts
    "stella": {"file": lambda: Path(os.devnull), "groups": [
        ("picture", [
            _one("aspect", _STELLA, "tia.fs_stretch", [("false", _ORIG, _ST_OFF), ("true", _STRETCH, _ST_ON)], "false", "false"),
            _one("smooth", _STELLA, "tia.inter", [("true", _ON, _ST_ON), ("false", _OFFK, _ST_OFF)], "false", "false"),
        ]),
        ("look", [
            _one("filter", _STELLA, "tv.filter", [                            # NTSCFilter.hxx Preset
                ("0", _OFFK, "0"), ("1", {"t": "RGB"}, "1"), ("2", {"t": "S-Video"}, "2"), ("3", {"t": "Composite"}, "3"),
                ("4", {"t": "Bad adjust"}, "4")], "0", "0"),
            _one("scanlines", _STELLA, "tv.scanlines", [
                ("0", _OFFK, "0"), ("25", {"t": "25 %"}, "25"), ("50", {"t": "50 %"}, "50"), ("75", {"t": "75 %"}, "75")], "0", "0"),
        ]),
        ("play", []),
    ]},
}
_OPT_INDEX = {t: {o["id"]: o for _, opts in spec["groups"] for o in opts} for t, spec in EMU_OPTS.items()}


def emu_gpu_class():
    """Grobe Einstufung fuer Vorgaben: 'none' (kein Render-Knoten, Software-OpenGL), 'dgpu' (Grafikkarte mit genug eigenem
    Speicher, NVIDIA nur mit dem proprietaeren Treiber) oder 'igp'. Im Zweifel die vorsichtigere Stufe."""
    if not list(Path("/dev/dri").glob("renderD*")):
        return "none"
    if Path("/sys/module/nvidia_drm").exists():
        return "dgpu"
    try:
        apu = any(w in Path("/proc/cpuinfo").read_text(errors="replace").lower() for w in ("radeon", "vega"))
    except OSError:
        apu = False
    if not apu:
        for f in Path("/sys/class/drm").glob("card*/device/mem_info_vram_total"):
            try:
                if int(f.read_text()) >= 3500 * 1024 * 1024:
                    return "dgpu"
            except (OSError, ValueError):
                continue
    return "igp"


def emu_cpu_class():
    """'strong' oder 'weak' – grobe Annahme, ob der Rechner PS2-Spiele auch mit doppelter Bildrate schafft: mindestens
    vier echte Kerne, mindestens 3 GHz und AVX2 (Haswell bzw. Ryzen oder neuer). Nicht gemessen; im Zweifel 'weak'."""
    try:
        info = Path("/proc/cpuinfo").read_text(errors="replace")
        m = re.search(r"^cpu cores\s*:\s*(\d+)", info, re.M)
        cores = int(m.group(1)) if m else 0
        f = re.search(r"^flags\s*:\s*(.*)$", info, re.M)
        avx2 = bool(f and " avx2 " in f" {f.group(1)} ")
        try:
            mhz = int(Path("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq").read_text()) / 1000
        except (OSError, ValueError):
            mhz = max((float(x) for x in re.findall(r"^cpu MHz\s*:\s*([\d.]+)", info, re.M)), default=0.0)
        return "strong" if cores >= 4 and mhz >= 3000 and avx2 else "weak"
    except (OSError, ValueError):
        return "weak"


def _opt_defaults_for(tile):
    """Vorgaben von VoidStation, die von der Hardware abhaengen: {Option: Wert}."""
    gpu = emu_gpu_class()
    if tile == "pcsx2":
        # Offizielle Patches, wo PCSX2 fuer das Spiel einen hat (4.280 Breitbild, 332 Zeilensprung; Stand 11/2026) – kostet nichts
        d = {"widescreen": "true", "noInterlace": "true", "textures": "true"}
        if gpu != "none":               # schaerfen statt hochrechnen: fuer integrierte Grafik gedacht, schadet der grossen nicht
            d["sharpen"] = "2"
        if gpu == "dgpu":               # PS2 hochskalieren ist teuer: nur mit eigener Grafikkarte
            d.update({"res": "2", "aniso": "16"})
        if gpu != "none" and emu_cpu_class() == "strong":     # doppelte Bildrate, oft mit uebertakteter PS2-CPU: kostet Rechenzeit
            d["fps"] = "true"
        if gpu != "none":               # Kanten glaetten (Paul, 13.11.2026: Vorgabe von VoidStation); kostet kaum etwas
            d["fxaa"] = "true"
        return d
    if tile == "duckstation":
        d = {"cdSpeed": "4", "fmvSmooth": "true", "textures": "true", "wsPatch": "true", "fps": "true"}
        if gpu != "none":
            d.update({"res": "4" if gpu == "dgpu" else "2", "pgxp": "true", "fxaa": "auto"})
        return d
    if tile == "dosbox":                # Fernseher: scharfe Pixel statt nachgemachter Roehre (DOSBox' eigener Standard)
        return {"shader": "sharp"}
    # Aufloesung nach Grafikleistung (Annahme, nicht gemessen): PSP 480×272, GameCube 640×528, 3DS 400×240 je Bildschirm
    if tile == "ppsspp":
        return {"res": "4"} if gpu == "dgpu" else {"res": "1"} if gpu == "none" else {}
    if tile == "dolphin":
        return {"res": "3"} if gpu == "dgpu" else {"res": "2"} if gpu == "igp" else {}
    if tile == "azahar":
        return {"res": "4"} if gpu == "dgpu" else {"res": "2"} if gpu == "igp" else {}
    if tile == "flycast":               # Dreamcast 640×480
        return {"res": "1440"} if gpu == "dgpu" else {"res": "960"} if gpu == "igp" else {}
    if tile == "melonds":               # DS 256×192 je Bildschirm; mehr braucht den OpenGL-Renderer
        return {"res": "4"} if gpu == "dgpu" else {"res": "2"} if gpu == "igp" else {}
    return {}


def _opt_norm(v):
    s = str(v).strip().lower()
    try:
        return f"{float(s):g}"
    except ValueError:
        return s


def _opt_writes(opt, choice):
    return dict(choice["set"]) if choice.get("set") else {k: choice["v"] for k in opt["keys"]}


def _opt_choice(opt, value):
    return next((c for c in opt["choices"] if c["v"] == value), None)


def _opt_game_choice(opt, value):
    """Wie _opt_choice, aber nur, was sich auch fuer ein einzelnes Spiel waehlen laesst."""
    c = _opt_choice(opt, value)
    return None if c and c.get("auto") else c


def _opt_secs(opt, choice, ini=None):
    """Was eine Moeglichkeit schreibt, je Abschnitt: {Abschnitt: {Schluessel: Wert}}."""
    if opt["io"]:
        return opt["io"].writes(choice["v"], ini or {})[0] if hasattr(opt["io"], "writes") else {"": {"": choice["v"]}}
    return {opt["section"]: _opt_writes(opt, choice)}


def _opt_plain(opt, choice):
    """Zu einer "auto"-Moeglichkeit die gewoehnliche, die dasselbe schreibt."""
    return next((c for c in opt["choices"] if not c.get("auto") and _opt_secs(opt, c) == _opt_secs(opt, choice)), choice)


def _opt_fixed(tile, opt, st):
    return opt["id"] in st.get("opt_fixed", {}).get(tile, [])


def _opt_auto_on(tile, opt, st):
    """Duerfen Spielprofile diese Option gerade setzen? (allgemein auf der Automatik-Stufe, s. EMU_AUTO)"""
    level = EMU_AUTO.get(tile, {}).get(opt["id"])
    return bool(level) and _opt_value(tile, opt) == level and not _opt_fixed(tile, opt, st)


def _opt_value(tile, opt, ini=None):
    """Aktuell gewaehlte Moeglichkeit laut Datei des Emulators, der Standard, wenn nichts drinsteht, oder None (etwas
    anderes, das sich hier nicht waehlen laesst – dann ist keiner der Knoepfe an)."""
    if opt["io"]:
        return opt["io"].read(ini_read(EMU_OPTS[tile]["file"]()) if ini is None else ini)
    if opt["own"]:
        ini = ini_read(EMU_OWN)
    sec = (ini_read(EMU_OPTS[tile]["file"]()) if ini is None else ini).get(opt["section"], {})
    if not any(k in sec for k in opt["keys"]):
        return opt["default"]
    for c in opt["choices"]:
        if all(_opt_norm(sec.get(k, v)) == _opt_norm(v) for k, v in _opt_writes(opt, c).items()):
            return c["v"]
    return None


def _opts_ini_base(tile, st):
    """Haupteinstellung ohne das, was nur fuer das gerade laufende Spiel drinsteht (opt_game, s. emu_opts_restore)."""
    ini = {sec: dict(vals) for sec, vals in ini_read(EMU_OPTS[tile]["file"]()).items()}
    for sec, vals in (st.get("opt_game", {}).get(tile) or {}).items():
        for k, (old, wrote) in vals.items():
            if _opt_norm(ini.get(sec, {}).get(k, "")) != _opt_norm(wrote):
                continue
            if old is None:
                ini[sec].pop(k, None)
            else:
                ini[sec][k] = old
    return ini


def _opt_shown(tile, opt, st, ini):
    """Was die Karte fuer diese Option allgemein zeigt: Vorgemerktes vor der Datei; "Automatik" oder ihr Zwilling."""
    v = st.get("opt_pending", {}).get(tile, {}).get(opt["id"], _opt_value(tile, opt, ini))
    c = _opt_choice(opt, v) if v is not None else None
    return _opt_plain(opt, c)["v"] if c and c.get("auto") and _opt_fixed(tile, opt, st) else v


def _opt_vs(tile):
    """Was VoidStation je Option vorsieht: Vorgabe fuer dieses Geraet, sonst der Standard."""
    own = _opt_defaults_for(tile)
    return {oid: own.get(oid, opt["default"]) for oid, opt in _OPT_INDEX[tile].items()}


def emu_opts_mode(tile, st, ini=None):
    """"vs" (alles steht auf den VoidStation-Einstellungen) oder "custom" (der Nutzer passt an bzw. hat etwas geaendert,
    hier oder im Emulator). Aufruf mit EMU_LOCK."""
    if st.get("opt_mode", {}).get(tile) == "custom":
        return "custom"
    ini = _opts_ini_base(tile, st) if ini is None else ini
    mine = st.get("opt_defaults", {}).get(tile, {})
    for oid, want in _opt_vs(tile).items():
        opt = _OPT_INDEX[tile][oid]
        cur = _opt_shown(tile, opt, st, ini)
        if cur == want:
            continue
        # Vorgabe, die erst der naechste Start eintraegt bzw. nachzieht (anderes Geraet): zaehlt als VoidStation
        if (oid not in mine and cur == opt["default"]) or (mine.get(oid) is not None and cur == mine[oid]):
            continue
        return "custom"
    return "vs"


def _opt_user_set(tile, opt, value, st, ready, running):
    """Eine Option allgemein auf die Wahl des Nutzers stellen. Aufruf mit EMU_LOCK."""
    oid = opt["id"]
    pending = st.setdefault("opt_pending", {}).setdefault(tile, {})
    if ready:
        _opt_write(tile, opt, value)
    # Laeuft der Emulator, schreibt er beim Beenden seine Einstellungen zurueck; vor dem Einrichten gibt es noch keine
    if not ready or running:
        pending[oid] = value
    else:
        pending.pop(oid, None)                           # sonst zeigte die Karte weiter das frueher Vorgemerkte
    st.setdefault("opt_defaults", {}).setdefault(tile, {})[oid] = None      # ab jetzt die Wahl des Nutzers
    if any(c.get("auto") for c in opt["choices"]):   # "Automatik" und "Aus" schreiben dasselbe: merken, was gemeint ist
        fixed = [o for o in st.setdefault("opt_fixed", {}).get(tile, []) if o != oid]
        st["opt_fixed"][tile] = fixed if _opt_choice(opt, value).get("auto") else fixed + [oid]


def emu_opts_mode_set(tile, mode):
    """Zwischen "VoidStation-Einstellungen" und "Anpassen" wechseln (s. oben)."""
    if tile not in EMU_OPTS or mode not in ("vs", "custom"):
        raise ValueError("Unbekannter Wert")
    idx = _OPT_INDEX[tile]
    with EMU_LOCK:
        if tile == "dosbox":
            dosbox_primary_ensure()
        st = emu_state_load()
        ready, running = emu_ready(tile), bool(APPS._get(tile))
        if ready and not running:
            emu_opts_restore(tile, st)
        ini = _opts_ini_base(tile, st)
        now = {oid: _opt_shown(tile, opt, st, ini) for oid, opt in idx.items()}
        was = emu_opts_mode(tile, st, ini)
        if mode == "custom":
            st.setdefault("opt_mode", {})[tile] = "custom"
            for oid, v in ((st.get("opt_saved") or {}).pop(tile, None) or {}).items():      # die frueheren Werte zurueck
                if oid in idx and _opt_choice(idx[oid], v) and now[oid] != v:
                    _opt_user_set(tile, idx[oid], v, st, ready, running)
        else:
            vs = _opt_vs(tile)
            if was == "custom" and any(now[oid] not in (None, vs[oid]) for oid in idx):
                st.setdefault("opt_saved", {})[tile] = {oid: v for oid, v in now.items() if v is not None}
            hw = _opt_defaults_for(tile)
            mine = st.setdefault("opt_defaults", {}).setdefault(tile, {})
            pending = st.setdefault("opt_pending", {}).setdefault(tile, {})
            for oid, want in vs.items():
                if now[oid] != want or _opt_value(tile, idx[oid], ini) != want:
                    if ready:
                        _opt_write(tile, idx[oid], want)
                    if not ready or running:
                        pending[oid] = want
                if ready and not running:
                    pending.pop(oid, None)
                if oid in hw:
                    mine[oid] = want                     # wieder Vorgabe: zieht mit, wenn sich das Geraet aendert
                else:
                    mine.pop(oid, None)
            st.setdefault("opt_fixed", {})[tile] = []
            st.setdefault("opt_mode", {}).pop(tile, None)
        emu_state_save(st)
    log(f"{tile}: Optionen: {'Anpassen' if mode == 'custom' else 'VoidStation-Einstellungen'}")
    return emu_opts_payload(tile)


def _opt_write(tile, opt, value):
    if opt["io"]:
        opt["io"].write(EMU_OPTS[tile]["file"](), value)
        return
    ini_update(EMU_OWN if opt["own"] else EMU_OPTS[tile]["file"](), opt["section"], _opt_writes(opt, _opt_choice(opt, value)))


def emu_opts_has_game(tile):
    return any(o["game"] for o in _OPT_INDEX.get(tile, {}).values())


def emu_games_load():
    try:
        d = json.loads(EMU_GAME_OPTS.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def emu_games_save(d):
    EMU_GAME_OPTS.parent.mkdir(parents=True, exist_ok=True)
    tmp = EMU_GAME_OPTS.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(EMU_GAME_OPTS)


_DISC_LOCK = threading.Lock()
_DISC_NAME = re.compile(r"sr\d+")
PCSX2_WS_PATCH = "Widescreen 16:9"               # Patch.cpp WS_PATCH_NAME


def _game_settings_dir(main_ini, root):
    """Ordner der Spiel-Einstellungen: [Folders] GameSettings, relativ zum Datenordner (EmuFolders)."""
    return root / (ini_read(main_ini).get("Folders", {}).get("GameSettings") or "gamesettings")


def _disc_key(tile, path, st):
    """Schluessel im Merkzettel. ".chd" hat einen eigenen: Bis 11/2026 liess es sich nicht lesen, dort steht noch "nichts"."""
    return f"{tile}|{path}|{st.st_size}|{st.st_mtime_ns}" + ("|chd" if path.suffix.lower() == ".chd" else "")


def _disc_id(tile, path):
    """Seriennummer bzw. (Seriennummer, CRC) eines Abbilds; gemerkt je Datei, Groesse und Zeit. None = nicht lesbar."""
    cache = Path.home() / ".cache/voidstation/disc-ids.json"
    if path.suffix.lower() == ".m3u":                    # Liste der CDs: Die erste steht fuer das Spiel
        path = (ROMManager.m3u_discs(path) or [path])[0]
    try:
        st = path.stat()
    except OSError:
        return None
    key = _disc_key(tile, path, st)
    with _DISC_LOCK:
        try:
            known = json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            known = {}
        if key in known:
            return known[key]
        import discid                                    # nur bei Bedarf, spart dem Launcher Speicher
        discid.CHDMAN = CHD.tool()                       # .chd: ueber chdman aus vs-chdman (nur 64 Bit)
        got = discid.ps2_id(path) if tile == "pcsx2" else discid.psx_serial(path)
        known = {k: v for k, v in known.items() if not k.startswith(f"{tile}|{path}|")}
        known[key] = got
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache.with_suffix(".tmp")
            tmp.write_text(json.dumps(known, ensure_ascii=False), encoding="utf-8")
            tmp.replace(cache)
        except OSError as e:
            log("disc-ids.json:", e)
    return list(got) if isinstance(got, tuple) else got


def _disc_id_put(tile, path, got):
    """Seriennummer eines Abbilds eintragen, das VoidStation nicht selbst lesen kann (.chd nach dem Umwandeln aus bin/cue)."""
    cache = Path.home() / ".cache/voidstation/disc-ids.json"
    try:
        st = path.stat()
    except OSError:
        return
    with _DISC_LOCK:
        try:
            known = json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            known = {}
        known = {k: v for k, v in known.items() if not k.startswith(f"{tile}|{path}|")}
        known[_disc_key(tile, path, st)] = got
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache.with_suffix(".tmp")
            tmp.write_text(json.dumps(known, ensure_ascii=False), encoding="utf-8")
            tmp.replace(cache)
        except OSError as e:
            log("disc-ids.json:", e)


def _game_rel(game):
    """Name eines Spiels, wie ihn die Spieleliste schickt (auch "Ordner/Spiel.cue") – nie absolut, nie nach oben."""
    p = Path(str(game))
    return os.path.basename(str(game)) if p.is_absolute() or ".." in p.parts else str(game)


def emu_rom_path(tile, name):
    """Spieldatei einer Kachel aus ihrem Namen in der Spieleliste (auch "Ordner/Spiel.cue") -> Pfad oder None."""
    for f in ROMS.folders(tile):
        p = ROMS.rom_file(f, name)
        if p and p.is_file():
            return p
    return None


def emu_game_ini(tile, game):
    """Die Spiel-Einstellungen des Emulators selbst fuer dieses Spiel (Pfad, muss noch nicht da sein) oder None."""
    if tile not in ("pcsx2", "duckstation"):
        return None
    if _DISC_NAME.fullmatch(os.path.basename(str(game))):     # Disc im Laufwerk (nie aus dem Merkzettel: anderes Geraet, andere Disc)
        g = DVD.game("/dev/" + os.path.basename(str(game))) or {}
        if tile == "pcsx2":
            return _game_ini_path(tile, [g["serial"], g["crc"]]) if g.get("kind") == "ps2" and g.get("serial") and g.get("crc") else None
        return _game_ini_path(tile, g["serial"]) if g.get("kind") == "ps1" and g.get("serial") else None
    path = Path(game)
    if not path.is_absolute():
        path = emu_rom_path(tile, game)
        if not path:
            return None
    # Mehrere CDs: DuckStation nimmt die Datei der ersten CD (System::GetGameSettingsPath), die kennt nur seine Datenbank
    if tile == "duckstation" and re.search(r"(disc|disk|cd)\s*[2-9]", path.name, re.I):
        return None
    got = _disc_id(tile, path)
    return _game_ini_path(tile, got) if got else None


def _game_ini_path(tile, got):
    if tile == "pcsx2":
        return _game_settings_dir(PCSX2_INI, PCSX2_INI.parent.parent) / f"{got[0]}_{got[1]:08X}.ini"
    return _game_settings_dir(DUCK_INI, DUCK_INI.parent) / f"{got}.ini"


def _is_ws_patch(value):
    return value == PCSX2_WS_PATCH


def _game_ini_read(tile, opt, ini):
    if tile == "pcsx2" and opt["id"] == "widescreen":    # PCSX2 verwirft den Schalter in Spiel-Dateien (ClearInvalidPerGameConfiguration)
        have = ini_multi_get(ini, "Patches", ["Enable", "Disable"], _is_ws_patch)
        return "true" if have["Enable"] else "false" if have["Disable"] else None
    if opt["io"]:
        v = opt["io"].game_read(ini_read(ini))
        c = _opt_choice(opt, v) if v is not None else None
        return _opt_plain(opt, c)["v"] if c and c.get("auto") else v
    sec = ini_read(ini).get(opt["section"], {})
    if not any(k in sec for k in opt["keys"]):
        return None
    for c in opt["choices"]:
        if not c.get("auto") and all(_opt_norm(sec.get(k, v)) == _opt_norm(v) for k, v in _opt_writes(opt, c).items()):
            return c["v"]
    return None


def _game_ini_write(tile, opt, ini, value):
    """Option in die Spiel-Datei schreiben; None nimmt sie heraus. Andere Eintraege der Datei bleiben, wie sie sind."""
    if tile == "pcsx2" and opt["id"] == "widescreen":
        ini_multi_set(ini, "Patches", {"Enable": PCSX2_WS_PATCH if value == "true" else None,
                                       "Disable": PCSX2_WS_PATCH if value == "false" else None}, _is_ws_patch)
    elif opt["io"]:
        have = ini_read(ini)
        if value is None:
            _io_apply(ini, {}, opt["io"].game_clear(have))
        else:
            _io_apply(ini, *opt["io"].game_writes(value, have, ini_read(EMU_OPTS[tile]["file"]())))
    elif value is None:
        ini_update(ini, opt["section"], {}, remove=opt["keys"])
    else:
        ini_update(ini, opt["section"], _opt_writes(opt, _opt_choice(opt, value)))
    try:
        if not any("=" in line for line in ini.read_text(encoding="utf-8", errors="replace").splitlines()):
            ini.unlink()                                 # nichts mehr drin: keine leere Datei liegen lassen
    except OSError:
        pass


def _game_sync(tile, name, ini):
    """Frueher in VoidStation gemerkte Werte in die Spiel-Datei des Emulators uebernehmen."""
    d = emu_games_load()
    own = d.get(tile, {}).get(name) or {}
    move = {k: v for k, v in own.items() if k not in EMU_PATCHES.get(tile, {})}
    if not move:
        return
    idx = _OPT_INDEX[tile]
    for oid, v in move.items():
        if oid in idx and idx[oid]["game"] and _opt_game_choice(idx[oid], v):
            _game_ini_write(tile, idx[oid], ini, v)
        own.pop(oid)
    if not own:
        d[tile].pop(name, None)
    emu_games_save(d)
    log(f"{tile}: Optionen fuer {name} in {ini.name} uebernommen")


def emu_opts_game(tile, game):
    """Fuer ein Spiel gewaehlte Optionen {Option: Wert}, nur was es (noch) gibt."""
    idx = _OPT_INDEX.get(tile, {})
    own = emu_games_load().get(tile, {}).get(os.path.basename(game), {})
    return {k: v for k, v in own.items() if k in idx and idx[k]["game"] and _opt_game_choice(idx[k], v)}


def emu_opts_game_writes(tile, game):
    """[(Abschnitt, {Schluessel: Wert})] der Optionen eines Spiels."""
    idx = _OPT_INDEX[tile]
    return [(sec, vals) for k, v in emu_opts_game(tile, game).items()
            if not idx[k]["own"] and (not idx[k]["io"] or getattr(idx[k]["io"], "fallback", False))
            for sec, vals in _opt_secs(idx[k], _opt_choice(idx[k], v)).items()]


def emu_opts_restore(tile, st):
    """Was fuer ein Spiel in die Haupteinstellung kam, zuruecknehmen. Hat der Nutzer es im Emulator geaendert, bleibt das.
    Aufruf mit EMU_LOCK."""
    rec = st.setdefault("opt_game", {}).pop(tile, None)
    if not rec:
        return
    path = EMU_OPTS[tile]["file"]()
    ini = ini_read(path)
    for sec, vals in rec.items():
        put, drop = {}, []
        for k, (old, wrote) in vals.items():
            if _opt_norm(ini.get(sec, {}).get(k, "")) != _opt_norm(wrote):
                continue
            if old is None:
                drop.append(k)
            else:
                put[k] = old
        if put or drop:
            ini_update(path, sec, put, remove=drop)
    log(f"{tile}: Optionen des letzten Spiels zurueckgenommen")


def _opts_apply_game(tile, game, st):
    """Optionen eines Spiels vor dem Start in die Haupteinstellung schreiben und den alten Wert merken (s. oben)."""
    path = EMU_OPTS[tile]["file"]()
    ini = ini_read(path)
    rec: dict = {}
    for sec, vals in emu_opts_game_writes(tile, game):
        for k, v in vals.items():
            rec.setdefault(sec, {})[k] = [ini.get(sec, {}).get(k), v]
        ini_update(path, sec, vals)
    if rec:
        st.setdefault("opt_game", {})[tile] = rec
        log(f"{tile}: Optionen fuer {os.path.basename(game)}:", rec)


DUCK_APP = Path.home() / ".local/share/voidstation/apps/duckstation"
_DUCK_DB: list = []


def duck_gamedb():
    """gamedb.yaml von DuckStation (liegt entpackt bei dessen Programm; nur lesen) oder None."""
    if _DUCK_DB and (_DUCK_DB[0] is None or _DUCK_DB[0].is_file()):
        return _DUCK_DB[0]
    found = next((p for p in (DUCK_APP / "usr/bin/resources/gamedb.yaml", DUCK_APP / "usr/share/duckstation/resources/gamedb.yaml",
                              DUCK_APP / "resources/gamedb.yaml") if p.is_file()), None)
    if not found and DUCK_APP.is_dir():
        found = next(iter(sorted(DUCK_APP.rglob("gamedb.yaml"))), None)
    _DUCK_DB[:] = [found]
    return found


def emu_profile(tile, game):
    """Spielprofil {Option: Wert} fuer ein Spiel der Spieleliste ({} = nichts bekannt). Liest ggf. das Abbild und DuckStations
    Datenbank – nicht unter EMU_LOCK aufrufen. Darf den Start nie verhindern."""
    if tile not in EMU_AUTO or not game:
        return {}
    try:
        import gameprofiles                              # nur bei Bedarf, spart dem Launcher Speicher
        if tile == "duckstation":
            path = Path(game)
            if _DISC_NAME.fullmatch(path.name):
                serial = (DVD.game("/dev/" + path.name) or {}).get("serial")
                names: list = []
            else:
                if not path.is_absolute():
                    path = emu_rom_path(tile, game) or path
                serial = _disc_id(tile, path) if path.is_file() else None
                names = [path.stem, path.parent.name]
            entry = gameprofiles.duck_entry(duck_gamedb(), serial) if isinstance(serial, str) else {}
            got, why = gameprofiles.psx_profile([entry.get("name")] + names, entry.get("genre", ""))
        elif tile == "dosbox":
            got, why = gameprofiles.dos_profile(game)
        else:
            return {}
    except Exception as e:  # noqa: BLE001
        log(f"{tile}: Spielprofil:", e)
        return {}
    if got:
        log(f"{tile}: Spielprofil {why} ->", got)
    return got


# ---- Patches je Spiel (Paul, 12.11.2026: Bildraten-Patches fuer jedes Spiel, bei der PS1 dazu die echten Breitbild-Patches) --
# Quelle sind die Sammlungen, die die Emulatoren selbst mitbringen und mit jedem ihrer Updates erneuern (resources/patches.zip:
# PCSX2 <Seriennummer>_<CRC>.pnach, DuckStation <Seriennummer>[_<Hash>].cht) – VoidStation pflegt keine eigene Liste und laedt
# nichts herunter. Vor jedem Start: Spiel an Seriennummer (und CRC) erkennen, in der Sammlung nachsehen, den Patch in den
# Spiel-Einstellungen des Emulators eintragen ([Patches] Enable = <Name>, geprueft an Patch.cpp bzw. cheats.cpp).
# Was VoidStation eingetragen hat, steht in emu-defaults.json unter "patches" – nur das nimmt es auch wieder heraus. Schaltet
# der Nutzer einen solchen Patch im Emulator ab, gilt das als seine Wahl fuer dieses Spiel. Gewollt ist ein Patch, wenn der
# Schalter fuer das Spiel an ist (emu-games.json), sonst wenn der allgemeine Schalter (EMU_OWN) an ist.
_FPS_PATCH = re.compile(r"(?:50|60|50/60) FPS")
EMU_PATCHES: dict[str, dict[str, Any]] = {            # Kachel -> {Option: Muster fuer den Namen des Patches}
    "pcsx2": {"fps": _FPS_PATCH},
    "duckstation": {"wsPatch": re.compile(r"Widescreen 16:9"), "fps": _FPS_PATCH},
}
PCSX2_EE_RATE = {"130": 1, "180": 2, "300": 3}        # "Might need EE Overclock at 130%" -> [EmuCore/Speedhacks] EECycleRate
_EMU_RES: dict[tuple, Any] = {}
_PATCH_CACHE: dict[tuple, Any] = {}


def emu_resource(tile, name):
    """Datei aus dem resources-Ordner eines Emulators (gamedb.yaml, patches.zip; nur lesen) oder None."""
    hit = _EMU_RES.get((tile, name))
    if hit is not None and hit.is_file():
        return hit
    roots = [APPDIR / tile]
    if tile == "pcsx2":                                  # bis zum Wechsel aufs AppImage: Flatpak
        roots += [Path(r) / "app/net.pcsx2.PCSX2/current/active/files" for r in
                  ("/var/lib/flatpak", Path.home() / ".local/share/flatpak")]
    found = None
    for root in roots:
        found = next((x for x in (root / "usr/bin/resources" / name, root / "bin/resources" / name,
                                  root / "resources" / name) if x.is_file()), None)
        if not found and root.is_dir() and root.parts[-2:] != ("active", "files"):
            found = next(iter(sorted(root.rglob(name))), None)
        if found:
            break
    if found:
        _EMU_RES[(tile, name)] = found
    return found


def _patch_got(tile, game):
    """Seriennummer (DuckStation) bzw. [Seriennummer, CRC] (PCSX2) eines Spiels oder einer Disc im Laufwerk, sonst None."""
    path = Path(game)
    if _DISC_NAME.fullmatch(path.name):
        g = DVD.game("/dev/" + path.name) or {}
        if tile == "pcsx2":
            return [g["serial"], g["crc"]] if g.get("serial") and g.get("crc") else None
        return g.get("serial") or None
    if not path.is_absolute():
        path = emu_rom_path(tile, game) or path
    return _disc_id(tile, path) if path.is_file() else None


def emu_patch_plan(tile, game):
    """Welche Patches aus EMU_PATCHES es fuer dieses Spiel gibt: {Option: {"label": Name, "ee": Stufe oder None}}.
    Nur, wo genau ein Patch der Art in der Datei steht. Liest Abbild und Archiv – nicht unter EMU_LOCK."""
    rules = EMU_PATCHES.get(tile)
    if not rules or not game:
        return {}
    try:
        got = _patch_got(tile, game)
        src = emu_resource(tile, "patches.zip") if got else None
        if not src:
            return {}
        key = (tile, json.dumps(got), src.stat().st_mtime_ns)
        if key in _PATCH_CACHE:
            return _PATCH_CACHE[key]
        import zipfile                                   # nur bei Bedarf
        found: list[tuple[str, str]] = []                # (Name, Beschreibung)
        with zipfile.ZipFile(src) as z:
            if tile == "pcsx2":
                want = f"{got[0]}_{got[1]:08X}.pnach".lower()
                names = [n for n in z.namelist() if n.lower() == want]
            else:
                names = [n for n in z.namelist() if n.lower() == f"{got}.cht".lower() or n.lower().startswith(f"{got}_".lower())]
            for n in names:
                text = z.read(n).decode("utf-8", "replace")
                for m in re.finditer(r"^\[([^\]\r\n]+)\][ \t]*\r?\n((?:(?!\[).*(?:\r?\n|$))*)", text, re.M):
                    desc = " ".join(re.findall(r"(?im)^description\s*=\s*(.*)$", m.group(2)))
                    found.append((m.group(1).strip(), desc))
        plan: dict[str, Any] = {}
        for oid, rule in rules.items():
            hits = {lab: d for lab, d in found if rule.fullmatch(lab)}
            if len(hits) != 1:
                continue                                 # keiner oder mehrere (welcher gilt, haengt vom Spiel ab): nichts
            lab, desc = next(iter(hits.items()))
            ee = None
            if tile == "pcsx2" and re.search(r"(?i)overclock", desc):
                pct = re.search(r"(\d{3}) ?%", desc)
                ee = PCSX2_EE_RATE.get(pct.group(1), 1) if pct else 1
            plan[oid] = {"label": lab, "ee": ee}
        _PATCH_CACHE[key] = plan
        return plan
    except Exception as e:  # noqa: BLE001 – darf den Start nie verhindern
        log(f"{tile}: Patches nachsehen:", e)
        return {}


def _ini_multi_all(path, section, key):
    """Alle Werte eines mehrfachen Schluessels in einem Abschnitt."""
    out: list[str] = []
    sec = None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        t = line.strip()
        if t.startswith("[") and t.endswith("]"):
            sec = t[1:-1]
        elif sec == section and "=" in t:
            k, _, v = t.partition("=")
            if k.strip() == key:
                out.append(v.strip())
    return out


def _patches_apply(tile, game, native, plan, st):
    """Patches fuer dieses Spiel in dessen Spiel-Datei ein- bzw. austragen (s. oben). Aufruf mit EMU_LOCK."""
    idx = _OPT_INDEX[tile]
    name = os.path.basename(str(game))
    games = emu_games_load()
    own = games.get(tile, {}).get(name, {})
    book = st.setdefault("patches", {}).setdefault(tile, {})
    mine = book.setdefault(native.name, {})              # {Option: {"label": Name, "ee": Stufe}} – von VoidStation eingetragen
    enabled = _ini_multi_all(native, "Patches", "Enable")
    for oid in EMU_PATCHES.get(tile, {}):
        info, rec = plan.get(oid), mine.get(oid)
        if rec and rec["label"] not in enabled:          # im Emulator abgeschaltet: die Wahl des Nutzers fuer dieses Spiel
            if rec.get("ee") and ini_read(native).get("EmuCore/Speedhacks", {}).get("EECycleRate") == str(rec["ee"]):
                ini_update(native, "EmuCore/Speedhacks", {}, remove=["EECycleRate"])     # unsere Uebertaktung geht mit
            mine.pop(oid)
            rec = None
            if own.get(oid) != "true":
                games.setdefault(tile, {}).setdefault(name, {})[oid] = "false"
                emu_games_save(games)
                own = games[tile][name]
                log(f"{tile}: {name}: Patch im Emulator abgeschaltet – bleibt aus")
        choice = own.get(oid)
        if choice in ("true", "false"):
            want = choice == "true"
        else:                                            # allgemein an; 300 % Uebertaktung nur auf ausdruecklichen Wunsch
            want = _opt_value(tile, idx[oid]) == "true" and not (info and info.get("ee") == 3)
        if want and info:
            if info["label"] in enabled and not rec:
                continue                                 # hat der Nutzer selbst eingeschaltet: nicht unseres
            if info["label"] not in enabled:
                ini_multi_set(native, "Patches", {"Enable": info["label"]}, lambda v, lab=info["label"]: v == lab)
                rec = mine[oid] = {"label": info["label"], "ee": None}
                log(f"{tile}: {name}: Patch {info['label']} eingetragen")
            if info.get("ee") and rec and not rec.get("ee") \
                    and "EECycleRate" not in ini_read(native).get("EmuCore/Speedhacks", {}):
                ini_update(native, "EmuCore/Speedhacks", {"EECycleRate": str(info["ee"])})
                rec["ee"] = info["ee"]
        elif rec:                                        # nicht mehr gewollt: nur zuruecknehmen, was von VoidStation kam
            ini_multi_set(native, "Patches", {"Enable": None}, lambda v, lab=rec["label"]: v == lab)
            if rec.get("ee") and ini_read(native).get("EmuCore/Speedhacks", {}).get("EECycleRate") == str(rec["ee"]):
                ini_update(native, "EmuCore/Speedhacks", {}, remove=["EECycleRate"])
            mine.pop(oid)
            log(f"{tile}: {name}: Patch {rec['label']} herausgenommen")
    if not mine:
        book.pop(native.name, None)
    try:
        if native.is_file() and not any("=" in line for line in native.read_text(encoding="utf-8", errors="replace").splitlines()):
            native.unlink()                              # nichts mehr drin: keine leere Datei liegen lassen
    except OSError:
        pass


_PAL_SERIAL = re.compile(r"S[LC]E[SD]", re.I)          # SLES/SCES (Europa), SLED/SCED (Demos)


def emu_pal_rate(tile, game):
    """PAL-Spiel der PlayStation (50 Bilder/s): Bildschirm fuer die Dauer des Spiels auf 50 Hz, wenn er das bei dieser
    Aufloesung anbietet – auf 60 Hz ruckelt es sonst zehnmal in der Sekunde. Zurueck geht es, wenn der Emulator endet
    (Apps._watch). Nur DuckStation: Viele PAL-Spiele der PS2 bieten beim Start 60 Hz an, da waere 50 Hz die falsche Wahl.
    Abschalten ohne Oberflaeche: "pal50": false in settings.json. Liest ggf. das Abbild – nicht unter EMU_LOCK."""
    if tile != "duckstation" or not game or settings_load().get("pal50") is False:
        return
    try:
        path = Path(game)
        if _DISC_NAME.fullmatch(path.name):
            serial = (DVD.game("/dev/" + path.name) or {}).get("serial")
        else:
            serial = _disc_id(tile, path) if path.is_file() else None
        if isinstance(serial, str) and _PAL_SERIAL.match(serial):
            DISPLAY_RATE.request(50.0, tile, force=True)
    except Exception as e:  # noqa: BLE001 – darf den Start nie verhindern
        log(f"{tile}: 50 Hz fuer PAL-Spiel:", e)


EMU_TEXTURES_NOTE = """HD-Texturen / HD textures
=========================

Deutsch: Texturpakete fuer einzelne Spiele kommen in einen Unterordner mit der Seriennummer des Spiels (z. B. {ex}).
VoidStation laedt selbst keine Pakete herunter. Liegt hier eins, nimmt {emu} es beim naechsten Start von selbst.
{how_de}

English: Texture packs for a game go into a subfolder named after the game's serial (e.g. {ex}).
VoidStation does not download packs itself. If one is here, {emu} picks it up on the next start.
{how_en}
"""
EMU_TEXTURES = {
    "pcsx2": ("PCSX2", "SLES-52541", "Aufbau: textures/<Seriennummer>/replacements/<Dateien>.png oder .dds",
              "Layout: textures/<serial>/replacements/<files>.png or .dds"),
    "duckstation": ("DuckStation", "SLES-02080", "Aufbau: textures/<Seriennummer>/replacements/<Dateien>.png. Ersetzt werden gemalte "
                    "Hintergruende und Bilder; Pakete fuer 3D-Texturen brauchen in DuckStation zusaetzlich "
                    "Grafik > Textur-Cache.", "Layout: textures/<serial>/replacements/<files>.png. Replaces painted backgrounds and "
                    "images; packs for 3D textures additionally need Graphics > Texture Cache in DuckStation."),
}


def emu_textures_prepare(tile):
    """Ordner fuer Texturpakete in der Freigabe (share/ROMs/<system>/textures) anlegen und dem Emulator zeigen – nur, solange
    dort noch sein eigener Standardordner steht. Aufruf mit EMU_LOCK, Emulator eingerichtet."""
    spec = EMU_TEXTURES.get(tile)
    folders = ROMS.folders(tile) if spec else []
    if not spec or not folders:
        return
    path = EMU_OPTS[tile]["file"]()
    cur = ini_read(path).get("Folders", {}).get("Textures", "")
    if cur not in ("", "textures"):
        return                                           # der Nutzer hat einen eigenen Ordner gewaehlt (oder unserer steht schon)
    tex = ROMS.rom_dir / folders[0] / "textures"
    try:
        tex.mkdir(parents=True, exist_ok=True)
        note = tex / "LIESMICH.txt"
        if not note.exists():
            note.write_text(EMU_TEXTURES_NOTE.format(emu=spec[0], ex=spec[1], how_de=spec[2], how_en=spec[3]), encoding="utf-8")
    except OSError as e:
        log(f"{tile}: Texturordner:", e)
        return
    ini_update(path, "Folders", {"Textures": str(tex)})
    log(f"{tile}: Texturpakete aus {tex}")


def _opts_apply_profile(tile, game, native, profile, st):
    """Spielprofil fuer diesen Start in die Haupteinstellung schreiben und den alten Wert merken – nur Optionen, die allgemein
    auf Automatik stehen und fuer die der Nutzer bei diesem Spiel nichts gewaehlt hat. Aufruf mit EMU_LOCK."""
    idx = _OPT_INDEX[tile]
    own = {} if native else emu_opts_game(tile, game)
    path = EMU_OPTS[tile]["file"]()
    ini = ini_read(path)
    rec = st.setdefault("opt_game", {}).get(tile) or {}
    done = {}
    for oid, v in profile.items():
        opt = idx.get(oid)
        if not opt or not _opt_game_choice(opt, v) or oid in own:
            continue
        if native and _game_ini_read(tile, opt, native) is not None:
            continue
        if not _opt_auto_on(tile, opt, st):
            continue
        secs = _opt_secs(opt, _opt_choice(opt, v), ini)
        if secs == _opt_secs(opt, _opt_choice(opt, EMU_AUTO[tile][oid]), ini):
            continue                                     # das Profil will, was ohnehin gilt
        for sec, vals in secs.items():
            for k, w in vals.items():
                rec.setdefault(sec, {})[k] = [ini.get(sec, {}).get(k), w]
            ini_update(path, sec, vals)
        done[oid] = v
    if done:
        st["opt_game"][tile] = rec
        log(f"{tile}: Spielprofil fuer {os.path.basename(game)} eingetragen:", done)


def _opts_apply_defaults(tile, st):
    """Vorgaben einmal setzen, solange die Option noch auf dem Standard des Emulators steht. Nie ueber das, was der Nutzer
    gewaehlt hat (mine[option] = None), egal ob hier oder im Emulator."""
    mine = st.setdefault("opt_defaults", {}).setdefault(tile, {})
    idx = _OPT_INDEX[tile]
    for oid, want in _opt_defaults_for(tile).items():
        opt = idx[oid]
        cur = _opt_value(tile, opt)
        if oid not in mine:
            if cur == opt["default"]:
                _opt_write(tile, opt, want)
                mine[oid] = want
                log(f"{tile}: Vorgabe {oid}={want}")
            else:
                mine[oid] = None
        elif mine[oid] is not None and cur != mine[oid]:
            mine[oid] = None
        elif mine[oid] is not None and want != cur:      # andere Grafikkarte: Vorgabe mitziehen
            _opt_write(tile, opt, want)
            mine[oid] = want


def emu_opts_prepare(tid, args):
    """Vor jedem Start (nach dem Erststart): Optionen des letzten Spiels zuruecknehmen, Vorgemerktes eintragen, Vorgaben,
    dann die Optionen des Spiels, das jetzt startet. DOSBox: Spiel-Optionen stehen schon in voidstation.conf."""
    if tid not in EMU_OPTS:
        return
    if tid == "dosbox":
        dosbox_primary_ensure()
    if tid != "gba":                                     # mGBA: schon in mgba_prepare
        emu_mute_apply(tid)
    if not emu_ready(tid):
        return
    game = str(args[-1]) if len(args) > 1 else ""
    if tid == "dosbox" or Path(game).suffix.lower() not in {e for x in ROMS.EXTENSIONS.values() for e in x}:
        game = ""
    last = str(args[-1]) if len(args) > 1 else ""
    disc = last if last.startswith("/dev/") and _DISC_NAME.fullmatch(os.path.basename(last)) else ""     # Disc im Laufwerk
    native = emu_game_ini(tid, game or disc) if game or disc else None      # Abbild lesen dauert: nicht unter der Sperre
    profile = emu_profile(tid, game or disc) if game or disc else {}        # DOSBox: s. dosbox_game_conf
    emu_pal_rate(tid, game or disc)
    plan = emu_patch_plan(tid, game or disc) if native else {}
    with EMU_LOCK:
        st = emu_state_load()
        emu_opts_restore(tid, st)
        for oid, v in (st.get("opt_pending") or {}).pop(tid, {}).items():
            opt = _OPT_INDEX[tid].get(oid)
            if opt and _opt_choice(opt, v):
                _opt_write(tid, opt, v)
        _opts_apply_defaults(tid, st)
        if tid == "gba":
            mgba_look_game(game)
        elif tid == "duckstation":
            duck_shaders_install()
            if native:
                duck_game_color_sync(native)
        emu_textures_prepare(tid)
        if native and game:
            _game_sync(tid, os.path.basename(game), native)
        elif game:
            _opts_apply_game(tid, game, st)
        if profile:
            _opts_apply_profile(tid, game or disc, native, profile, st)
        if native and tid in EMU_PATCHES:
            _patches_apply(tid, game or disc, native, plan, st)
        emu_state_save(st)


def _opt_mute_now(tile, st):
    want = st.get("mute", {}).get(tile)
    if want is not None:                               # vorgemerkt (Emulator lief noch nie oder laeuft gerade)
        return bool(want)
    path, sec, key, yes, _ = EMU_MUTE[tile]()
    cur = ini_read(path).get(sec, {}).get(key)
    return cur is not None and _opt_norm(cur) == _opt_norm(yes)


_LOOK_PREVIEWS: dict[str, bool] = {}


def look_preview(tile, opt, choice, group):
    """{"p": Pfad} zum Vorschaubild einer Moeglichkeit in der Spalte Bildstil, {} wenn es keins gibt."""
    if group != "look":
        return {}
    f = LOOK_PREVIEWS / tile / f"{opt['id']}-{str(choice['v']).replace('/', '_')}.jpg"
    key = str(f)
    if key not in _LOOK_PREVIEWS:
        _LOOK_PREVIEWS[key] = f.is_file()
    return {"p": key} if _LOOK_PREVIEWS[key] else {}


def emu_opts_payload(tile, game=None):
    spec = EMU_OPTS.get(tile)
    if not spec:
        raise ValueError("Dieser Emulator hat keine Optionen")
    rel = _game_rel(game) if game else None            # Spiele in Unterordnern: die Datei findet sich nur mit dem Ordner
    game = os.path.basename(game) if game else None
    running = bool(APPS._get(tile))
    native = emu_game_ini(tile, rel) if rel else None
    patches = EMU_PATCHES.get(tile, {})
    plan = emu_patch_plan(tile, rel) if rel and native and patches else {}      # nur Patches, die es fuer das Spiel gibt
    with EMU_LOCK:
        st = emu_state_load()
        if not running and emu_ready(tile) and st.get("opt_game", {}).get(tile):
            emu_opts_restore(tile, st)
            emu_state_save(st)
        values: dict[str, Any] = {}
        groups: list[dict[str, Any]] = []
        if native:
            _game_sync(tile, game, native)
        own = emu_opts_game(tile, game) if game and not native else {}
        ini = None if game else _opts_ini_base(tile, st)
        mode = None if game else emu_opts_mode(tile, st, ini)
        # Allgemein: links "Allgemein" mit dem Schalter VoidStation-Einstellungen | Anpassen, rechts "Bild"; die uebrigen
        # Zeilen nur bei "Anpassen". Je Spiel: wie bisher Bild, dann Spiel, nur was sich je Spiel waehlen laesst.
        order = spec["groups"] if game else sorted(spec["groups"], key=lambda g: g[0] != "play")
        for gid, opts in order:
            if game:                                     # ein echter Breitbild-Patch ersetzt bei dem Spiel den Schalter fuer den Hack
                shown = [o for o in opts if o["game"] and (o["id"] in plan if o["id"] in patches else
                                                           not (o["id"] == "widescreen" and "wsPatch" in plan))
                         and (not o["io"] or native or tile == "gba" or getattr(o["io"], "fallback", False))]
            else:
                shown = [o for o in opts if not o["hidden"]] if mode == "custom" else []
            for o in shown:
                if game and o["id"] in patches:          # Patch-Schalter merkt VoidStation selbst (s. EMU_PATCHES)
                    values[o["id"]] = emu_opts_game(tile, game).get(o["id"])
                elif native:
                    values[o["id"]] = _game_ini_read(tile, o, native)
                elif game:
                    values[o["id"]] = own.get(o["id"])
                else:
                    values[o["id"]] = _opt_shown(tile, o, st, ini)
            rows = [dict({"id": o["id"], "choices": [
                dict({x: c[x] for x in ("v", "k", "t") if x in c}, **look_preview(tile, o, c, gid))
                for c in o["choices"] if not (game and c.get("auto"))]},
                **({"label": o["label"]} if o["label"] else {})) for o in shown]
            if not game and gid == "play":
                rows.insert(0, {"id": "mode", "choices": _OPT_MODE})
                values["mode"] = mode
                if tile in EMU_MUTE:                     # "Spiel stumm": eigener Weg (emu_set_mute); bleibt beim Umschalten stehen
                    rows.insert(1, {"id": "mute", "choices": _OPT_TF})
                    values["mute"] = "true" if _opt_mute_now(tile, st) else "false"
            if rows:
                groups.append({"id": "general" if gid == "play" and not game else gid, "opts": rows})
    layout = EMU_LAYOUTS.get(tile) or {}
    return {"emu": tile, "name": layout.get("name") or tile, "game": game, "mode": mode, "groups": groups, "values": values}


def emu_opts_set(tile, oid, value, game=None):
    """Option setzen: fuer ein Spiel (value None = wieder wie ueberall) oder allgemein, in der Datei des Emulators."""
    if oid == "mute" and tile in EMU_MUTE and not game:
        if value not in ("true", "false"):
            raise ValueError("Unbekannter Wert")
        emu_set_mute(tile, value == "true")
        return emu_opts_payload(tile)
    if oid == "mode" and not game:
        return emu_opts_mode_set(tile, value)
    opt = _OPT_INDEX.get(tile, {}).get(oid)
    if not opt:
        raise ValueError("Unbekannte Option")
    if value is not None and not (_opt_game_choice(opt, value) if game else _opt_choice(opt, value)):
        raise ValueError("Unbekannter Wert")
    if game:
        if not opt["game"]:
            raise ValueError("Diese Option gilt nicht je Spiel")
        name, rel = os.path.basename(game), _game_rel(game)
        if oid in EMU_PATCHES.get(tile, {}):             # gilt ab dem naechsten Start des Spiels (_patches_apply)
            with EMU_LOCK:
                d = emu_games_load()
                mine = d.setdefault(tile, {}).setdefault(name, {})
                if value is None:
                    mine.pop(oid, None)
                    if not mine:
                        d[tile].pop(name, None)
                else:
                    mine[oid] = value
                emu_games_save(d)
            return emu_opts_payload(tile, rel)
        native = emu_game_ini(tile, rel)
        if native:
            with EMU_LOCK:
                _game_sync(tile, name, native)
                _game_ini_write(tile, opt, native, value)
            return emu_opts_payload(tile, rel)
        if _DISC_NAME.fullmatch(name):
            raise ValueError("Diese Disc hat keine Seriennummer")
        if opt["io"] and tile != "gba" and not getattr(opt["io"], "fallback", False):
            raise ValueError("Fuer dieses Spiel nicht einstellbar")
        with EMU_LOCK:
            d = emu_games_load()
            own = d.setdefault(tile, {}).setdefault(name, {})
            if value is None:
                own.pop(oid, None)
                if not own:
                    d[tile].pop(name, None)
            else:
                own[oid] = value
            emu_games_save(d)
        return emu_opts_payload(tile, rel)
    if value is None:
        raise ValueError("Wert fehlt")
    with EMU_LOCK:
        if tile == "dosbox":
            dosbox_primary_ensure()
        st = emu_state_load()
        ready, running = emu_ready(tile), bool(APPS._get(tile))
        if ready and not running:
            emu_opts_restore(tile, st)
        _opt_user_set(tile, opt, value, st, ready, running)
        st.setdefault("opt_mode", {})[tile] = "custom"   # wer einen Schalter anfasst, passt an
        emu_state_save(st)
    log(f"{tile}: Option {oid}={value}")
    return emu_opts_payload(tile)


def emu_front(tile):
    """True, wenn das aktive Fenster wirklich zur Kachel `tile` gehoert (laeuft und ist vorn)."""
    if not tile or APPS.front() != tile:
        return False
    proc = APPS._get(tile)
    act = active_window()
    return bool(proc and act and any(int(w[0], 16) == act for w in APPS._windows_of(tile, proc)))


EMU_HELD: set = set()                         # gerade gehaltene Tasten (keydown bzw. Umschalter an), werden sicher geloest


def emu_action(action, down):
    """Extra aus der Tastenbelegung ("<Kachel>:<save|load|ff|rewind>"): Taste an den Emulator schicken (EMU_KEYS).
    Nur, wenn genau dieser Emulator vorn ist; eine gehaltene Taste wird beim Loslassen immer freigegeben."""
    tile, _, act = str(action).partition(":")
    spec = EMU_KEYS.get(tile, {}).get(act)
    if not spec or not shutil.which("xdotool"):
        return
    how, key = spec
    if how in ("hold", "toggle") and not down:
        if key in EMU_HELD:
            EMU_HELD.discard(key)
            if how == "hold":
                run(["xdotool", "keyup", key])
            elif emu_front(tile):                 # Umschalter: zweiter Druck stellt zurueck
                run(["xdotool", "key", "--clearmodifiers", key])
        return
    if not down or not emu_front(tile):
        return
    if how == "tap":
        run(["xdotool", "key", "--clearmodifiers", key])
    elif how == "toggle":
        EMU_HELD.add(key)
        run(["xdotool", "key", "--clearmodifiers", key])
    else:
        EMU_HELD.add(key)
        run(["xdotool", "keydown", key])
    log(f"{tile}:", act)


# ---- Vollbild ------------------------------------------------------------------------------------------------
# Programm -> (Startoption, Taste zum Umschalten). Beide aus dem Quelltext der Programme: mGBA (commandline.c "-f",
# Window.cpp Strg+F), DuckStation (qthost.cpp "-fullscreen", hotkeys.cpp F11).
EMU_FULLSCREEN: dict[str, tuple] = {"mgba-qt": ("-f", "ctrl+f"), "duckstation": ("-fullscreen", "F11")}
# Dasselbe je Kachel fuer Flatpaks (Programm ist dort "flatpak"): PCSX2 (QtHost.cpp "-fullscreen", Alt+Enter),
# RMG (main.cpp "-f", Alt+Enter), xemu (QEMU "-full-screen", F11), Azahar (citra_qt.cpp "-f", F11), Cemu
# (LaunchSettings.cpp "-f", MainWindow.cpp F11). Die Option steht vor der Spieldatei (und ROM_ARGS).
EMU_FULLSCREEN_TILE: dict[str, tuple] = {"mednafen": (None, "alt+Return"),      # Schalter mit Wert: s. ROMManager.rom_args
                                         "pcsx2": ("-fullscreen", "alt+Return"), "rmg": ("-f", "alt+Return"), "xemu": ("-full-screen", "F11"),
                       "azahar": ("-f", "F11"), "cemu": ("-f", "F11")}
# Emulatoren mit einem einzigen Fenster ohne eigene Vollbild-Startoption: Vollbild ueber den Fenstermanager
EMU_WM_FULLSCREEN = {"snes9x", "nestopia", "melonds", "stella", "vice", "retroarch"}
FS_HOLD = 0.8                                # L3 so lange halten -> Vollbild an/aus
SAVESTATE_HOLD = 0.5                         # Savestate speichern/laden erst nach so langem Halten (nicht aus Versehen)
HOLD_ACTIONS = {"fullscreen": FS_HOLD, "save": SAVESTATE_HOLD, "load": SAVESTATE_HOLD}   # je Aktion (Kachel egal)


EMU_BIN_KIND = {"pcsx2-qt": "pcsx2", "RMG": "rmg"}   # Paket-Programme, deren Name nicht der Kachel entspricht


def emu_kind(args):
    p = Path(str(args[0]))
    return p.parent.name.lower() if p.name == "AppRun" else EMU_BIN_KIND.get(p.name, p.name)


def emu_fullscreen_wanted(tid):
    t = find_tile(tid) or {}
    if isinstance(t.get("fullscreen"), bool):
        return t["fullscreen"]
    return bool(settings_load().get("emu_fullscreen", True))


# ---- Einrichtungsassistenten vorwegnehmen ------------------------------------------------------------------
# PCSX2 und DuckStation schreiben beim allerersten Start sofort ihre Standardeinstellungen (QtHost::InitializeConfig,
# Core::InitializeBaseSettingsLayer) und zeigen erst danach den Assistenten, solange ein Merkzeichen
# (SetupWizardIncomplete) gesetzt ist. VoidStation startet das Programm deshalb einmal unsichtbar
# (QT_QPA_PLATFORM=offscreen, Rueckfall xcb), wartet auf die Datei, beendet es und traegt ein, was der Assistent
# abfragt: Merkzeichen aus, Spieleordner; BIOS und Controller setzen bios_prepare und die Belegung wie bei jedem
# Start. Cemu (wxWidgets) zeigt "Getting started", solange settings.xml fehlt – die legt VoidStation selbst an.
def _first_run_patch_pcsx2(ini):
    cur = ini_read(ini)
    ini_update(ini, "UI", {"SetupWizardIncomplete": "false"})
    gl = cur.get("GameList", {})
    if not gl.get("Paths") and not gl.get("RecursivePaths"):
        ini_update(ini, "GameList", {"RecursivePaths": str(ROMS.rom_dir / "ps2")})


def _first_run_patch_duck(ini):
    cur = ini_read(ini)
    ini_update(ini, "Main", {"SetupWizardIncomplete": "false"})
    gl = cur.get("GameList", {})
    if not gl.get("Paths") and not gl.get("RecursivePaths"):
        ini_update(ini, "GameList", {"RecursivePaths": str(ROMS.rom_dir / "psx")})


FIRST_RUN = {  # Kachel -> (Einstellungsdatei, Abschnitt mit dem Merkzeichen, Eintragen)
    "pcsx2": (lambda: PCSX2_INI, "UI", _first_run_patch_pcsx2),
    "duckstation": (lambda: DUCK_INI, "Main", _first_run_patch_duck),
}


def _first_run_pass(args, ini):
    """Das Programm unsichtbar starten, bis seine Einstellungsdatei samt Controller-Abschnitt steht (hoechstens 20 s)."""
    flat = args[:2] == ["flatpak", "run"]
    plat = "QT_QPA_PLATFORM=offscreen;xcb"
    if flat:
        ref = next((a for a in args[2:] if not str(a).startswith("-")), None)
        if not ref:
            return False
        cmd = ["flatpak", "run", f"--env={plat}", ref]
    else:
        cmd = [args[0]]
    env = app_env()
    env["QT_QPA_PLATFORM"] = "offscreen;xcb"
    log("Erster Start ohne Assistent:", " ".join(map(str, cmd)))
    try:
        proc = subprocess.Popen(cmd, cwd=str(Path.home()), env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        log("Erster Start:", e)
        return False
    ok, last, t0 = False, None, time.monotonic()
    while time.monotonic() - t0 < 20 and proc.poll() is None:
        time.sleep(0.25)
        try:
            text = ini.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "[Pad1]" in text:
            if text == last:                       # zweimal gleich: fertig geschrieben
                ok = True
                break
            last = text
    for sig, wait in ((signal.SIGTERM, 3), (signal.SIGKILL, 2)):
        if proc.poll() is not None:
            break
        try:
            os.killpg(proc.pid, sig)
        except OSError:
            pass
        try:
            proc.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            pass
    return ok or ini.exists()


def first_run(tid, args):
    if tid == "cemu":
        f = emu_dir("cemu") / "settings.xml"
        if not f.exists():                          # ohne settings.xml zeigt Cemu "Getting started" (CemuApp.cpp)
            f.parent.mkdir(parents=True, exist_ok=True)
            games = ROMS.rom_dir / "wiiu"
            f.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<content>\n    <GamePaths>\n'
                         f'        <Entry>{html_escape(str(games))}</Entry>\n    </GamePaths>\n</content>\n',
                         encoding="utf-8")
            log("Cemu: Einstellungen angelegt (ohne Assistent), Spiele aus", games)
        return
    spec = FIRST_RUN.get(tid)
    if not spec:
        return
    ini, section, patch = spec[0](), spec[1], spec[2]
    if not ini.exists():
        with EMU_LOCK:
            if not ini.exists() and not _first_run_pass(args, ini):
                log(f"{tid}: unsichtbarer erster Start ohne Ergebnis – der Assistent erscheint wie gewohnt")
                return
    sec = ini_read(ini).get(section, {})
    flag = sec.get("SetupWizardIncomplete", "").strip().lower()
    # DuckStation zeigt den Assistenten auch, wenn weder das Merkzeichen noch SettingsVersion da ist (dsqthost.cpp)
    if flag in ("true", "1") or (tid == "duckstation" and "SetupWizardIncomplete" not in sec
                                 and "SettingsVersion" not in sec):
        patch(ini)
        log(f"{tid}: Einrichtungsassistent uebersprungen")


def emu_prepare(tid, args):
    """Vor dem Start: Vorgaben schreiben, Vollbild-Option einsetzen. -> (args, Umgebung, Vollbild ueber Fenstermanager)"""
    emu_paths_refresh()
    kind = emu_kind(args)
    env, wm_fs = {}, False
    try:
        first_run(tid, args)
    except Exception as e:  # noqa: BLE001 – darf den Start nie verhindern
        log(f"{tid}: erster Start:", e)
    if kind == "mgba-qt":
        try:
            mgba_prepare()
        except Exception as e:  # noqa: BLE001 – Vorgaben duerfen den Start nie verhindern
            log("mGBA-Vorgaben:", e)
        env["SDL_JOYSTICK_HIDAPI"] = "0"
    try:
        bios_prepare(tid)
    except Exception as e:  # noqa: BLE001
        log(f"{tid}: BIOS:", e)
    if tid == "mame" and "-joystickprovider" not in args:   # SDL-Gamepad-Namen wie in mame_items
        args = [args[0], "-joystickprovider", "sdlgame"] + list(args[1:])
    flat = args[:2] == ["flatpak", "run"]
    if flat:
        # Dateidialoge (Dokumenten-Portal) liefern Pfade unter <Laufzeitordner>/doc/… – VoidStation hat einen eigenen
        # Laufzeitordner, den das Flatpak nicht kennt (es bekommt das Portal nur unter /run/user/<uid>/doc). Den Ordner
        # unter seinem Namen freigeben, damit gewaehlte Dateien und Ordner im Programm auch ankommen.
        rt = os.environ.get("XDG_RUNTIME_DIR", "")
        if rt and rt.rstrip("/") != f"/run/user/{os.getuid()}" and os.path.ismount(os.path.join(rt, "doc")):
            opt = f"--filesystem={os.path.join(rt, 'doc')}"
            if opt not in args:
                args = ["flatpak", "run", opt] + list(args[2:])
    if tid in KEYMAP_WRITERS:
        try:
            keymap_prepare(tid)
        except Exception as e:  # noqa: BLE001 – die Belegung darf den Start nie verhindern
            log(f"{tid}: Controller-Belegung:", e)
        env["SDL_JOYSTICK_HIDAPI"] = "0"          # rohe Tastennummern wie in sdl_indices (s. SDL_PROBE)
        if flat and not any(str(a).startswith("--env=SDL_JOYSTICK_HIDAPI") for a in args):
            args = ["flatpak", "run", "--env=SDL_JOYSTICK_HIDAPI=0"] + list(args[2:])
    try:
        emu_opts_prepare(tid, args)
    except Exception as e:  # noqa: BLE001 – Optionen duerfen den Start nie verhindern
        log(f"{tid}: Optionen:", e)
    if flat and tid in EMU_LAYOUTS:
        # Spiele und BIOS liegen in der Freigabe: manche Flatpaks sehen das Home gar nicht (RMG) oder nur lesend
        # (xemu braucht das Festplatten-Image in share/ROMs/xbox/bios zum Schreiben)
        share = f"--filesystem={Path.home() / 'share'}"
        if share not in args:
            args = ["flatpak", "run", share] + list(args[2:])
    # Nur mit Spiel (aus der Spieleliste): "Emulator ohne Spiel starten" bleibt im Fenster, dort will man die Menues
    game = len(args) > 1 and (Path(str(args[-1])).suffix.lower() in {e for x in ROMS.EXTENSIONS.values() for e in x}
                              or str(args[-1]).startswith("/dev/sr"))
    if game and emu_fullscreen_wanted(tid):
        spec = EMU_FULLSCREEN_TILE.get(tid) if (flat or kind == tid) else None
        spec = spec or EMU_FULLSCREEN.get(kind)
        if spec and not spec[0]:
            pass
        elif spec and flat:
            if spec[0] not in args:                 # vor der Spieldatei samt ihrer Option (ROM_ARGS)
                n = 1 + len(next((v for v in ROMS.ROM_ARGS.values() if list(args[-1 - len(v):-1]) == v), []))
                args = list(args[:-n]) + [spec[0]] + list(args[-n:])
        elif spec:
            if spec[0] not in args:
                args = [args[0], spec[0]] + list(args[1:])
        elif tid in EMU_WM_FULLSCREEN:
            wm_fs = True
    return args, env, wm_fs


def emu_toggle_fullscreen():
    """L3 lang gedrueckt: Vollbild des Emulators vorn an/aus (zum Beispiel, um an die Menues von mGBA zu kommen).
    Nur, wenn das aktive Fenster wirklich zu einem Emulator gehoert – nie in Firefox, Steam oder der Startseite."""
    tid = APPS.front()
    if not tid or not app_suspendable(tid):
        return
    proc = APPS._get(tid)
    act = active_window()
    if not proc or not act or not any(int(w[0], 16) == act for w in APPS._windows_of(tid, proc)):
        return
    key = (EMU_FULLSCREEN_TILE.get(tid) or EMU_FULLSCREEN.get(APPS.kinds.get(tid, ""), (None, None)))[1]
    if key and shutil.which("xdotool"):
        run(["xdotool", "key", "--clearmodifiers", key])
    else:
        vsx11.wm_state(act, "toggle", "fullscreen")
    log("Vollbild umgeschaltet:", tid)


# ---- Spielstand-Sicherung -------------------------------------------------------------------------------------
class SaveBackup:
    """Sichert alle 30 Minuten (und kurz nach dem Beenden eines Emulators) die Spielstaende nach
    ~/share/Spielstand-Backups/<Datum_Uhrzeit>/ – vom PC aus ueber die Freigabe erreichbar.
      * nur, wenn sich seit der letzten Sicherung etwas geaendert hat
      * unveraenderte Dateien sind harte Links auf die vorige Sicherung (kostet keinen Platz)
      * behaelt alle Sicherungen der letzten 24 Stunden, danach eine pro Tag fuer 30 Tage
    Gesichert werden Speicherstaende neben den Spielen (share/ROMs: .sav, .srm, Savestates .ss0–.ss9 …) und die
    bekannten Ordner der Emulatoren, soweit vorhanden. Abschalten: "save_backup": false in settings.json."""
    INTERVAL = 1800
    KEEP_ALL = 24 * 3600
    KEEP_DAYS = 30
    MAX_FILE = 512 * 1024 * 1024
    SAVE_EXT = re.compile(r"\.(sav|srm|sra|eep|fla|rtc|mpk|dsv|mcr|mcd|ss\d|st\d|state\d*|oops)$", re.I)
    ROOT = Path.home() / "share" / "Spielstand-Backups"
    H = Path.home()
    # (Name im Backup, Ordner, nur Speicherstaende?) – fehlende Ordner werden uebersprungen
    SOURCES = [
        ("ROMs", H / "share" / "ROMs", True),                                # mGBA, melonDS, Snes9x … neben dem Spiel
        ("DuckStation", H / ".local/share/duckstation/memcards", False),
        ("DuckStation-Savestates", H / ".local/share/duckstation/savestates", False),
        ("PPSSPP", H / ".config/ppsspp/PSP/SAVEDATA", False),
        ("PPSSPP-Savestates", H / ".config/ppsspp/PSP/PPSSPP_STATE", False),
        ("Dolphin-GC", H / ".local/share/dolphin-emu/GC", False),
        ("Dolphin-Savestates", H / ".local/share/dolphin-emu/StateSaves", False),
        ("RetroArch", H / ".config/retroarch/saves", False),
        ("RetroArch-Savestates", H / ".config/retroarch/states", False),
        ("PCSX2", H / ".config/PCSX2/memcards", False),                       # AppImage
        ("PCSX2-Savestates", H / ".config/PCSX2/sstates", False),
        ("Flycast", H / ".local/share/flycast", True),
        ("RMG", H / ".local/share/RMG/Save", False),
        ("Azahar-Savestates", H / ".local/share/azahar-emu/states", False),
        ("Cemu", H / ".local/share/Cemu/mlc01/usr/save", False),
        ("PCSX2", H / ".var/app/net.pcsx2.PCSX2/config/PCSX2/memcards", False),     # Flatpak (bis zum Wechsel)
        ("PCSX2-Savestates", H / ".var/app/net.pcsx2.PCSX2/config/PCSX2/sstates", False),
        ("Flycast", H / ".var/app/org.flycast.Flycast/data/flycast", True),
        ("RMG", H / ".var/app/com.github.Rosalie241.RMG/data/RMG/Save", False),           # Game/ und State/
        ("Azahar-Savestates", H / ".var/app/org.azahar_emu.Azahar/data/azahar-emu/states", False),
        ("Cemu", H / ".var/app/info.cemu.Cemu/data/Cemu/mlc01/usr/save", False),
        ("MAME", H / ".mame/nvram", False),
        ("MAME-Savestates", H / ".mame/sta", False),
        ("Mednafen", H / ".mednafen/sav", False),
        ("Mednafen-Savestates", H / ".mednafen/mcs", False),
        ("Nestopia", H / ".nestopia/save", False),
        ("ScummVM", H / ".local/share/scummvm/saves", False),
    ]
    STAMP = "%Y-%m-%d_%H-%M-%S"

    def __init__(self):
        self.lock = threading.Lock()
        self.last_sig = None
        self.last_run = 0.0
        self.last_result = None

    def enabled(self):
        return bool(settings_load().get("save_backup", True))

    def _files(self):
        """[(Pfad im Backup, Datei, Groesse, mtime_ns)] aller zu sichernden Dateien."""
        out = []
        for name, root, saves_only in self.SOURCES:
            if not root.is_dir():
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "Cover"]
                for fn in filenames:
                    if saves_only and not self.SAVE_EXT.search(fn):
                        continue
                    p = Path(dirpath) / fn
                    try:
                        s = p.stat()
                    except OSError:
                        continue
                    if s.st_size > self.MAX_FILE or not p.is_file():
                        continue
                    out.append((f"{name}/{p.relative_to(root)}", p, s.st_size, s.st_mtime_ns))
        out.sort()
        return out

    def snapshots(self):
        try:
            return sorted(d for d in self.ROOT.iterdir() if d.is_dir() and re.fullmatch(r"\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d", d.name))
        except OSError:
            return []

    def run_once(self, why=""):
        if not self.enabled():
            return None
        with self.lock:
            self.last_run = time.time()
            files = self._files()
            if not files:
                return None
            sig = hashlib.sha1(json.dumps([(r, sz, mt) for r, _, sz, mt in files]).encode()).hexdigest()
            snaps = self.snapshots()
            if self.last_sig is None:
                try:
                    self.last_sig = (snaps[-1] / ".signatur").read_text().strip() if snaps else ""
                except OSError:
                    self.last_sig = ""
            if sig == self.last_sig:
                return None
            prev = snaps[-1] if snaps else None
            name = datetime.datetime.now().strftime(self.STAMP)
            tmp = self.ROOT / f".{name}.tmp"
            shutil.rmtree(tmp, ignore_errors=True)
            copied = linked = 0
            try:
                for rel, src, size, mtime in files:
                    dst = tmp / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    old = prev / rel if prev else None
                    try:
                        if old and old.is_file():
                            os_ = old.stat()
                            if os_.st_size == size and os_.st_mtime_ns == mtime:
                                os.link(old, dst)
                                linked += 1
                                continue
                    except OSError:
                        pass
                    shutil.copy2(src, dst)
                    copied += 1
                (tmp / ".signatur").write_text(sig)
                tmp.rename(self.ROOT / name)
            except OSError as e:
                log("Spielstand-Sicherung fehlgeschlagen:", e)
                shutil.rmtree(tmp, ignore_errors=True)
                return None
            self.last_sig = sig
            self._readme()
            self._prune()
            self.last_result = {"name": name, "copied": copied, "linked": linked}
            log(f"Spielstaende gesichert ({why}): {name}, {copied} neu, {linked} unveraendert")
            return self.last_result

    def _prune(self):
        now = datetime.datetime.now()
        keep_day = set()
        for d in reversed(self.snapshots()):
            try:
                t = datetime.datetime.strptime(d.name, self.STAMP)
            except ValueError:
                continue
            age = (now - t).total_seconds()
            day = t.date()
            if age <= self.KEEP_ALL:
                keep_day.add(day)
                continue
            if age <= self.KEEP_DAYS * 86400 and day not in keep_day:
                keep_day.add(day)                    # neueste Sicherung dieses Tages behalten
                continue
            shutil.rmtree(d, ignore_errors=True)

    def _readme(self):
        f = self.ROOT / "LIESMICH.txt"
        if f.exists():
            return
        try:
            f.write_text(
                "VoidStation – Spielstand-Sicherung / save backups\n"
                "=================================================\n"
                "Alle 30 Minuten (und kurz nach dem Beenden eines Emulators) landet hier ein Ordner mit Datum und\n"
                "Uhrzeit – aber nur, wenn sich ein Spielstand geaendert hat. Behalten werden alle Sicherungen der\n"
                "letzten 24 Stunden und danach eine pro Tag fuer 30 Tage.\n"
                "Zurueckholen: Emulator beenden, Datei aus dem gewuenschten Ordner an ihren alten Platz kopieren\n"
                "(ROMs/... = Freigabe-Ordner ROMs; mGBA: .sav = Spielstand im Spiel, .ss0 = automatischer Stand).\n\n"
                "Every 30 minutes (and shortly after an emulator closes) a dated folder appears here – only if a save\n"
                "changed. All backups of the last 24 hours are kept, then one per day for 30 days.\n"
                "To restore: close the emulator and copy the file back to where it came from.\n", encoding="utf-8")
        except OSError:
            pass

    def watcher(self):
        """Hintergrund-Thread: alle 30 Minuten, und 10 s nachdem ein Emulator beendet wurde."""
        time.sleep(180)
        emus_before: set = set()
        due_at = 0.0
        while True:
            try:
                emus = {t for t in APPS.running() if app_suspendable(t)}
                if emus_before - emus:
                    due_at = time.time() + 10
                emus_before = emus
                if due_at and time.time() >= due_at:
                    due_at = 0.0
                    self.run_once("Emulator beendet")
                elif time.time() - self.last_run >= self.INTERVAL:
                    self.run_once("alle 30 Minuten")
            except Exception as e:  # noqa: BLE001 – der Waechter darf nie sterben
                log("Spielstand-Sicherung:", e)
            time.sleep(15)


SAVES = SaveBackup()


# ---- Cover in der Spieleliste ----------------------------------------------------------------------------------
class RomCovers:
    """Bild zu jedem Spiel der Spieleliste. Reihenfolge:
      1. eigenes Bild: ROMs/<system>/Cover/<Name des Spiels>.png|.jpg|.jpeg|.webp (oder gleichnamig neben dem Spiel)
      2. sonst online gesucht und dauerhaft als ROMs/<system>/Cover/<Name>.png gespeichert – Quelle sind die
         Boxbilder von libretro-thumbnails (dieselben wie in RetroArch), Liste ueber GitHub, Rueckfall
         thumbnails.libretro.com
    Gesucht wird nach dem genauen Dateinamen (No-Intro-Namen wie "Pokemon - Crystal Version (USA, Europe)"), dann
    nach dem Titel ohne Klammern (Region der eigenen Sprache bevorzugt), dann aehnlich geschrieben. ROM-Hacks und
    selbst benannte Dateien finden oft nichts – dafuer ist Punkt 1 da. Nicht Gefundenes wird 14 Tage nicht erneut
    gesucht. Abschalten: "rom_covers": false in settings.json."""
    SYSTEMS = {                                  # Ordner unter share/ROMs -> System bei libretro
        "gba": "Nintendo - Game Boy Advance", "gbc": "Nintendo - Game Boy Color", "gb": "Nintendo - Game Boy",
        "snes": "Nintendo - Super Nintendo Entertainment System", "nes": "Nintendo - Nintendo Entertainment System",
        "psx": "Sony - PlayStation", "psp": "Sony - PlayStation Portable", "nds": "Nintendo - Nintendo DS",
        "gamecube": "Nintendo - GameCube", "wii": "Nintendo - Wii", "dreamcast": "Sega - Dreamcast", "n64": "Nintendo - Nintendo 64",
        "megadrive": "Sega - Mega Drive - Genesis", "mastersystem": "Sega - Master System - Mark III",
        "gamegear": "Sega - Game Gear", "saturn": "Sega - Saturn", "pcengine": "NEC - PC Engine - TurboGrafx 16",
        "atari2600": "Atari - 2600", "c64": "Commodore - 64", "ps2": "Sony - PlayStation 2", "xbox": "Microsoft - Xbox",
        "3ds": "Nintendo - Nintendo 3DS",
        "dos": "DOS", "scummvm": "ScummVM", "mame": "MAME",
    }
    BY_EXT = {".gba": "gba", ".gbc": "gbc", ".gb": "gb"}     # mGBA-Ordner enthalten alle drei
    IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")
    LIST_AGE = 30 * 86400
    MISS_AGE = 14 * 86400
    CACHE = BASE / "cache" / "romcovers"
    REGIONS = {"de": ("Germany", "Europe", "World", "USA"), "en": ("USA", "World", "Europe")}

    def __init__(self):
        self.lock = threading.Lock()
        self.list_locks = {}
        self.lists = {}                          # System -> {"names": set, "by_key": {schluessel: [namen]}}
        self.list_fail = {}                      # System -> Zeitpunkt des letzten Fehlschlags
        self.dl = threading.Semaphore(3)
        self.miss = None

    def enabled(self):
        return bool(settings_load().get("rom_covers", True))

    @staticmethod
    def key(name):
        """Vergleichsschluessel: ohne Klammern, Akzente, "The", Satzzeichen."""
        s = re.sub(r"\s*[\(\[][^()\[\]]*[\)\]]", "", name)
        s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().replace("&", " and ")
        s = re.sub(r"\bthe\b", " ", s)
        return re.sub(r"[^a-z0-9]", "", s)

    @staticmethod
    def thumb_name(stem):
        return re.sub(r'[&*/:`<>?\\|"]', "_", stem)

    def system_of(self, folder, filename):
        return self.SYSTEMS.get(self.BY_EXT.get(Path(filename).suffix.lower(), folder))

    @staticmethod
    def stem_of(filename):
        """Name des Bildes zu einer Spieldatei: Dateiname ohne Endung, bei Spuren ohne Blatt ohne "(Track n)"
        ("Tekken 3 (Europe) (Track 1).bin" -> "Tekken 3 (Europe)", passt so auch nach der Umwandlung zur .chd)."""
        p = Path(filename)
        return ROMS.bin_base(p) if p.suffix.lower() == ".bin" else p.stem

    def own_image(self, folder, filename):
        stems = list(dict.fromkeys((self.stem_of(filename), Path(filename).stem)))
        base = ROMS.rom_dir / folder
        game = base / filename
        own_dir = [game.parent] if game.parent != base else []      # Spiel im Unterordner: Bild auch dort
        for d in (base / "Cover", base, *own_dir):
            for stem in stems:
                for ext in self.IMG_EXT:
                    p = d / (stem + ext)
                    if p.is_file():
                        return p
        # DOS/ScummVM: Spiel = Ordner – Bild auch darin (cover.jpg …); ebenso im eigenen Ordner eines Spiels
        game = game if folder in ROMS.DIR_SYSTEMS else (own_dir[0] if own_dir else game)
        if (folder in ROMS.DIR_SYSTEMS or own_dir) and game.is_dir():
            for n in ("cover", "folder", "box", "boxart", "front"):
                for ext in self.IMG_EXT:
                    for cand in (n + ext, n.upper() + ext.upper()):
                        p = game / cand
                        if p.is_file():
                            return p
        return None

    def lookup_name(self, folder, filename):
        """Name, unter dem das Spiel gesucht wird: Dateiname ohne Endung, Ordnername bei DOS/ScummVM, bei MAME der
        Spieltitel statt des Set-Namens (libretro-thumbnails/MAME ist nach Titeln benannt: "Street Fighter II_ …")."""
        stem = filename if folder in ROMS.DIR_SYSTEMS else self.stem_of(filename)
        if folder == "mame":
            stem = mame_names([stem]).get(stem) or stem
        return stem

    def url(self, rom):
        """Adresse fuer die Oberflaeche; ?v= wechselt, sobald ein Bild da ist (sonst haelt Qt das alte Ergebnis)."""
        f = rom.get("folder") or rom.get("system") or ""
        own = self.own_image(f, rom["filename"])
        v = int(own.stat().st_mtime) if own else 0
        return ("/api/roms/cover?folder=" + urllib.parse.quote(f) + "&file=" + urllib.parse.quote(rom["filename"])
                + f"&v={v}")

    # -- Liste der vorhandenen Bilder eines Systems --
    def _repo(self, system):
        return system.replace(" ", "_")

    def _load_list(self, system):
        with self.lock:
            lk = self.list_locks.setdefault(system, threading.Lock())
        with lk:
            if system in self.lists:
                return self.lists[system]
            if time.time() - self.list_fail.get(system, 0) < 600:
                return None
            self.CACHE.mkdir(parents=True, exist_ok=True)
            cf = self.CACHE / (self._repo(system) + ".json")
            names = None
            try:
                if time.time() - cf.stat().st_mtime < self.LIST_AGE:
                    names = json.loads(cf.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
            if names is None:
                names = self._fetch_list(system)
                if names:
                    try:
                        cf.write_text(json.dumps(names, ensure_ascii=False), encoding="utf-8")
                    except OSError:
                        pass
                else:
                    try:                            # offline: lieber alte Liste als keine
                        names = json.loads(cf.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        self.list_fail[system] = time.time()
                        return None
            by_key: dict = {}
            for n in names:
                by_key.setdefault(self.key(n), []).append(n)
            self.lists[system] = {"names": set(names), "by_key": by_key}
            return self.lists[system]

    def _fetch_list(self, system):
        repo = self._repo(system)
        try:                                        # GitHub: eine Anfrage je System (ohne Konto 60 pro Stunde)
            req = urllib.request.Request(
                f"https://api.github.com/repos/libretro-thumbnails/{repo}/git/trees/master?recursive=1",
                headers={**UA, "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                tree = json.loads(r.read().decode("utf-8"))
            names = [t["path"][len("Named_Boxarts/"):-4] for t in tree.get("tree", [])
                     if t.get("path", "").startswith("Named_Boxarts/") and t["path"].endswith(".png")]
            if names:
                return names
        except (OSError, ValueError, KeyError) as e:
            log("Cover-Liste (GitHub):", system, e)
        try:                                        # Rueckfall: Verzeichnisliste von thumbnails.libretro.com
            req = urllib.request.Request(
                "https://thumbnails.libretro.com/" + urllib.parse.quote(system) + "/Named_Boxarts/", headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                html = r.read().decode("utf-8", "replace")
            return [urllib.parse.unquote(h)[:-4] for h in re.findall(r'href="([^"?/]+\.png)"', html)]
        except OSError as e:
            log("Cover-Liste (libretro):", system, e)
        return []

    def _pick(self, lst, stem):
        tn = self.thumb_name(stem)
        if tn in lst["names"]:
            return tn
        k = self.key(stem)
        cands = lst["by_key"].get(k)
        if not cands and len(k) >= 6:              # "Pokemon Smaragd" -> "Pokemon - Smaragd-Edition", nur wenn eindeutig
            longer = [x for x in lst["by_key"] if x.startswith(k)]
            if len(longer) == 1:
                cands = lst["by_key"][longer[0]]
        if not cands and len(k) >= 4:
            import difflib
            close = difflib.get_close_matches(k, list(lst["by_key"]), n=1, cutoff=0.88)
            cands = lst["by_key"][close[0]] if close else None
        if not cands:
            return None
        own = set(re.findall(r"\(([^)]*)\)", stem))
        pref = self.REGIONS.get(ui_lang(), self.REGIONS["en"])

        def score(n):
            tags = re.findall(r"\(([^)]*)\)", n)
            regs = [r.strip() for t in tags[:1] for r in t.split(",")]
            s = len(own & set(tags)) * 10
            for i, r in enumerate(pref):
                if r in regs:
                    s += (len(pref) - i)
                    break
            return (s, -len(n))
        return max(cands, key=score)

    def _download(self, system, name, depth=0):
        """PNG-Daten des Boxbilds. libretro-thumbnails enthaelt Verweise (Symlinks): GitHub liefert dann statt des
        Bildes nur den Namen des Zielbilds – dem wird gefolgt (hoechstens zweimal)."""
        repo = self._repo(system)
        for u in (f"https://raw.githubusercontent.com/libretro-thumbnails/{repo}/master/Named_Boxarts/"
                  + urllib.parse.quote(name + ".png"),
                  "https://thumbnails.libretro.com/" + urllib.parse.quote(system) + "/Named_Boxarts/"
                  + urllib.parse.quote(name + ".png")):
            try:
                with self.dl:
                    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30) as r:
                        data = r.read(8 * 1024 * 1024)
            except OSError:
                continue
            if data[:8] == b"\x89PNG\r\n\x1a\n":
                return data
            link = data.strip()
            if len(link) < 300 and link.endswith(b".png") and depth < 2:
                return self._download(system, link.decode("utf-8", "replace").split("/")[-1][:-4], depth + 1)
        return None

    def _miss_load(self):
        if self.miss is None:
            try:
                self.miss = json.loads((self.CACHE / "miss.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.miss = {}
        return self.miss

    def _miss_set(self, k, on):
        with self.lock:
            m = self._miss_load()
            if on:
                m[k] = time.time()
            else:
                m.pop(k, None)
            try:
                self.CACHE.mkdir(parents=True, exist_ok=True)
                (self.CACHE / "miss.json").write_text(json.dumps(m), encoding="utf-8")
            except OSError:
                pass

    def get(self, folder, filename):
        """Pfad zum Bild des Spiels oder None (holt es bei Bedarf aus dem Netz – kann einige Sekunden dauern)."""
        if folder not in ROMS.EXTENSIONS or not ROMS.rom_file(folder, filename):
            return None
        own = self.own_image(folder, filename)
        if own or not self.enabled():
            return own
        system = self.system_of(folder, filename)
        if not system:
            return None
        mk = f"{folder}/{filename}"
        with self.lock:
            t = self._miss_load().get(mk, 0)
        if time.time() - t < self.MISS_AGE:
            return None
        lst = self._load_list(system)
        if not lst:
            return None                              # offline – naechstes Mal wieder versuchen
        name = self._pick(lst, self.lookup_name(folder, filename))
        data = self._download(system, name) if name else None
        if not data:
            if not name:                             # nichts Passendes: 14 Tage Ruhe; Downloadfehler: bald wieder
                self._miss_set(mk, True)
            return None
        out = ROMS.rom_dir / folder / "Cover" / (self.stem_of(filename) + ".png")
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_name(out.name + ".part")
            tmp.write_bytes(data)
            tmp.replace(out)
        except OSError as e:
            log("Cover nicht gespeichert:", out, e)
            return None
        self._miss_set(mk, False)
        log("Cover gespeichert:", out.name, "<-", name)
        return out


ROM_COVERS = RomCovers()


# ---------------------------------------------------------------------------
#  bin/cue -> CHD (eine Datei je Spiel, kleiner, ohne Verlust). Werkzeug: chdman aus MAME, von VoidStation selbst
#  gebaut, als Paket vs-chdman aus der eigenen Paketquelle (/usr/libexec/voidstation/chdman, nur x86_64; Template in
#  github.com/Panther92/voidstation-packages). Die Spieleliste fragt einmal je neuem
#  Fund; umgewandelt wird im Hintergrund, Spiel fuer Spiel: umwandeln -> pruefen (chdman verify) -> erst dann das
#  Original loeschen bzw. nach ROMs/<system>/_umgewandelt verschieben.
# ---------------------------------------------------------------------------
class ChdConvert:
    FOLDERS = {"psx", "ps2"}                       # Systeme, deren Emulator CHD liest und die bin/cue kennen
    KEEP_DIR = "_umgewandelt"
    STATE = BASE / "chd.json"                      # {"declined": {Ordner: [Blaetter, zu denen "Nein" gesagt wurde]}}
    CODECS = "cdlz,cdzl,cdfl"                      # Vorgabe von chdman fuer CDs; liest jeder Emulator (kein zstd noetig)
    RESERVE = 200 * 1024 * 1024                    # so viel Platz bleibt mindestens frei
    STALL = 180                                    # so lange ohne Lebenszeichen von chdman -> abbrechen (haengt)
    SECTORS = (2352, 2048, 2336, 2448)             # Sektorgroessen in .bin-Dateien (roh, Mode 1, Mode 2, mit Subcode)

    def __init__(self):
        self.lock = threading.Lock()
        self.job: dict[str, Any] = {}
        self.proc: Any = None
        self.stop = False
        self._tool: Any = None

    # -- Werkzeug --
    PKG_TOOL = "/usr/libexec/voidstation/chdman"   # Paket vs-chdman (bis 2026.11: launcher/bin/chdman)

    def tool(self):
        """Pfad zu chdman oder "" (32 Bit, nicht installiert, fehlende Bibliothek). Einmal je Launcher-Start geprueft.
        Rueckfall: ein chdman im PATH (z. B. aus Voids MAME-Paket)."""
        if self._tool is None:
            self._tool = ""
            for cand in (self.PKG_TOOL, shutil.which("chdman") or ""):
                if not cand or not os.access(cand, os.X_OK):
                    continue
                try:
                    r = subprocess.run([cand, "help"], capture_output=True, timeout=10)
                except (OSError, subprocess.TimeoutExpired):
                    continue
                if b"chdman" in r.stdout + r.stderr:
                    self._tool = cand
                    break
        return self._tool

    # -- was gibt es umzuwandeln? --
    def folders(self, system):
        return [f for f in ROMS.folders(system) if f in self.FOLDERS]

    SYNC = b"\x00" + b"\xff" * 10 + b"\x00"         # Anfang jedes rohen CD-Datensektors (2352 Byte)
    PREGAP = 150                                   # 2 Sekunden Pause vor Musikspuren (Redump: in der Spur-Datei enthalten)

    @classmethod
    def track_kind(cls, path, first):
        """Art einer Spur ohne Blatt: "MODE2/2352", "MODE1/2352", "MODE1/2048" (ISO), "AUDIO" oder None (unbekannt)."""
        try:
            size = path.stat().st_size
            with open(path, "rb") as fh:
                head = fh.read(16)
                fh.seek(16 * 2048 + 1)
                iso = fh.read(5) == b"CD001"
        except OSError:
            return None
        if size and size % 2352 == 0 and head[:12] == cls.SYNC:
            return "MODE2/2352" if head[15] == 2 else "MODE1/2352"
        if first and iso and size % 2048 == 0:
            return "MODE1/2048"
        if not first and size and size % 2352 == 0:
            return "AUDIO"
        return None

    @classmethod
    def sheet(cls, tracks):
        """Blatt (.cue-Text) fuer .bin-Spuren ohne eigenes Blatt, oder None, wenn die erste Spur keine Daten-Spur ist
        (dann ist es kein PlayStation-Abbild). Musikspuren nach Daten: Beginnen sie mit 2 Sekunden Stille, ist das
        die Pause vor der Spur (INDEX 00/01 wie bei Redump), sonst startet die Spur sofort."""
        lines = []
        for n, t in enumerate(tracks, 1):
            kind = cls.track_kind(t, n == 1)
            if kind is None or (n == 1 and kind == "AUDIO") or '"' in t.name:
                return None
            lines += [f'FILE "{t.name}" BINARY', f"  TRACK {n:02d} {kind}"]
            gap = False
            if kind == "AUDIO":
                try:
                    with open(t, "rb") as fh:
                        blk = fh.read(cls.PREGAP * 2352)
                    gap = len(blk) == cls.PREGAP * 2352 and blk.count(0) == len(blk)
                except OSError:
                    return None
            lines += ["    INDEX 00 00:00:00", "    INDEX 01 00:02:00"] if gap else ["    INDEX 01 00:00:00"]
        return "\n".join(lines) + "\n"

    def candidates(self, folder):
        """Spiele aus bin/cue, zu denen es noch keine .chd gibt: [{"cue", "sheet", "tracks", "bytes", "rel", "final",
        "key"}]. Mit Blatt: cue = die .cue. Ohne Blatt (nur .bin, auch mehrere Spuren "… (Track n).bin"): cue = None,
        sheet = erzeugtes Blatt – das legt die Umwandlung kurz als versteckte Datei neben die Spuren."""
        sys_dir = ROMS.rom_dir / folder
        out: list[dict[str, Any]] = []
        if not sys_dir.is_dir():
            return out

        def sizes_ok(files):
            # Abgeschnittene oder fremde Dateien (keine ganzen Sektoren): chdman bleibt daran haengen – gar nicht anbieten
            try:
                sizes = [t.stat().st_size for t in files]
            except OSError:
                return None
            if any(n == 0 or all(n % sec for sec in self.SECTORS) for n in sizes):
                return None
            return sum(sizes)

        files = ROMS.scan(sys_dir, {".cue", ".bin"})
        hidden: set = set()
        for cue in (f for f in files if f.suffix.lower() == ".cue"):
            tracks = ROMS.cue_tracks(cue)
            hidden.update(tracks)
            final = cue.with_suffix(".chd")
            if not tracks or final.exists():
                continue
            size = sizes_ok(tracks)
            if size is None:
                continue
            try:
                size += cue.stat().st_size
            except OSError:
                continue
            out.append({"cue": cue, "sheet": None, "tracks": tracks, "bytes": size, "final": final, "key": cue.name,
                        "rel": cue.relative_to(sys_dir).as_posix()})
        for first, tracks in ROMS.bin_sets(files, hidden).items():
            final = first.with_name(ROMS.bin_base(first) + ".chd")
            if final.exists():
                continue
            size = sizes_ok(tracks)
            if size is None:
                continue
            sheet = self.sheet(tracks)
            if sheet is None:
                continue
            out.append({"cue": None, "sheet": sheet, "tracks": tracks, "bytes": size, "final": final, "key": first.name,
                        "rel": first.relative_to(sys_dir).as_posix()})
        out.sort(key=lambda c: c["rel"].casefold())
        return out

    def _state(self):
        try:
            d = json.loads(self.STATE.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _state_save(self, d):
        try:
            tmp = self.STATE.with_suffix(".tmp")
            tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.STATE)
        except OSError as e:
            log("chd.json:", e)

    def status(self, system):
        """Fuer die Spieleliste: wie viele bin/cue-Spiele, ob gefragt werden soll (neue seit dem letzten "Nein"),
        freier Platz, laufender Auftrag."""
        job = self.view()
        folders = self.folders(system)
        if not folders or not self.tool():
            return {"count": 0, "bytes": 0, "ask": False, "free": 0, "job": job}
        declined = self._state().get("declined", {})
        count = size = new = 0
        for f in folders:
            seen = set(declined.get(f, []))
            for c in self.candidates(f):
                count += 1
                size += c["bytes"]
                new += c["rel"] not in seen
        try:
            free = shutil.disk_usage(ROMS.rom_dir).free
        except OSError:
            free = 0
        running = job.get("state") == "running"
        return {"count": 0 if running else count, "bytes": size, "ask": bool(new) and not running, "free": free, "job": job}

    def decline(self, system):
        """"Nein": Fuer die jetzt vorhandenen Spiele nicht mehr fragen (neue loesen die Frage wieder aus)."""
        d = self._state()
        dec = d.setdefault("declined", {})
        for f in self.folders(system):
            dec[f] = sorted(set(dec.get(f, [])) | {c["rel"] for c in self.candidates(f)})
        self._state_save(d)

    def view(self):
        with self.lock:
            return dict(self.job)

    # -- Auftrag --
    def start(self, system, delete):
        tool = self.tool()
        folders = self.folders(system)
        if not tool or not folders:
            raise ValueError("CHD-Umwandlung hier nicht moeglich")
        with self.lock:
            if self.job.get("state") == "running":
                raise ValueError("Umwandlung laeuft schon")
            todo = [(f, c) for f in folders for c in self.candidates(f)]
            if not todo:
                raise ValueError("Nichts umzuwandeln")
            self.stop = False
            self.job = {"state": "running", "system": system, "delete": bool(delete), "i": 0, "n": len(todo), "name": "",
                        "step": "convert", "pct": 0.0, "ok": 0, "failed": [], "saved": 0, "error": ""}
        threading.Thread(target=self._run, args=(tool, system, todo, bool(delete)), daemon=True).start()
        return self.view()

    def cancel(self):
        self.stop = True
        p = self.proc
        if p is not None and p.poll() is None:
            try:
                p.terminate()
            except OSError:
                pass

    def _set(self, **kw):
        with self.lock:
            self.job.update(kw)

    def _chdman(self, args, progress=False):
        """chdman ausfuehren (niedrige Prioritaet, ein Kern bleibt frei). Fortschritt steht in stderr als
        "Compressing, 12.3% complete…" mit Wagenruecklauf statt Zeilenende. -> Rueckgabecode"""
        self.proc = subprocess.Popen(["nice", "-n", "10", *args], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.PIPE)
        assert self.proc.stderr is not None
        proc, alive, stalled = self.proc, [time.monotonic()], [False]

        def watchdog():                                  # chdman ohne Ausgabe = haengt (kaputtes Abbild)
            while proc.poll() is None:
                if time.monotonic() - alive[0] > self.STALL:
                    stalled[0] = True
                    proc.kill()
                    return
                time.sleep(1)
        threading.Thread(target=watchdog, daemon=True).start()
        buf, tail = b"", b""
        while True:
            chunk = self.proc.stderr.read1(4096)
            if not chunk:
                break
            alive[0] = time.monotonic()
            tail = (tail + chunk)[-2000:]
            buf += chunk
            parts = re.split(rb"[\r\n]", buf)
            buf = parts.pop()
            for line in parts:
                m = re.search(rb"([0-9]+(?:\.[0-9]+)?)% complete", line)
                if m and progress:
                    self._set(pct=float(m.group(1)))
        rc = self.proc.wait()
        self.proc = None
        if stalled[0]:
            log("chdman:", args[1], f"seit {self.STALL} s ohne Ausgabe, abgebrochen")
        elif rc != 0 and not self.stop:
            log("chdman:", args[1], "->", rc, tail.decode("utf-8", "replace").strip().splitlines()[-1:] or "")
        return rc

    def _run(self, tool, system, todo, delete):
        tile = ROMS.SYSTEM_TO_TILE.get(ROMS.canonical_system(system), system)
        cores = max(1, (os.cpu_count() or 2) - 1)
        refs: dict = {}                                  # Spur -> wie viele Blaetter sie noch brauchen
        for _f, c in todo:
            for t in c["tracks"]:
                refs[t] = refs.get(t, 0) + 1
        state, error = "done", ""
        for i, (folder, c) in enumerate(todo, 1):
            cue, final = c["cue"], c["final"]
            src = cue or c["tracks"][0]                   # ohne Blatt: die erste Spur steht fuer das Spiel
            name = ROMS.title_of(folder, src)
            self._set(i=i, name=name, step="convert", pct=0.0)
            if self.stop:
                state = "cancelled"
                break
            part = final.with_name("." + final.stem + ".chd.part")
            sheet = final.with_name("." + final.stem + ".vs.cue")    # erzeugtes Blatt, nur fuer die Dauer der Umwandlung
            try:
                if shutil.disk_usage(final.parent).free < c["bytes"] + self.RESERVE:
                    state, error = "error", "space"       # schlimmstenfalls so gross wie das Original
                    break
                serial = _disc_id(tile, src) if tile in ("duckstation", "pcsx2") else None
                if c.get("sheet"):
                    sheet.write_text(c["sheet"], encoding="utf-8")
                    cue = sheet
                try:
                    rc = self._chdman([tool, "createcd", "-i", str(cue), "-o", str(part), "-f", "-c", self.CODECS,
                                       "-np", str(cores)], progress=True)
                finally:
                    if c.get("sheet"):
                        sheet.unlink(missing_ok=True)
                if rc == 0 and not self.stop:
                    self._set(step="verify", pct=0.0)
                    rc = self._chdman([tool, "verify", "-i", str(part)], progress=True)
                if self.stop:
                    part.unlink(missing_ok=True)
                    state = "cancelled"
                    break
                if rc != 0 or not part.is_file() or part.stat().st_size == 0 or final.exists():
                    part.unlink(missing_ok=True)
                    with self.lock:
                        self.job["failed"].append(name)
                    continue
                os.replace(part, final)
                self._after(tile, folder, c, final, serial, delete, refs)
                with self.lock:
                    self.job["ok"] += 1
                    self.job["saved"] += max(0, c["bytes"] - final.stat().st_size)
                log(f"CHD: {c['rel']} -> {final.name} ({c['bytes'] >> 20} -> {final.stat().st_size >> 20} MB)")
            except OSError as e:
                part.unlink(missing_ok=True)
                log("CHD:", c["rel"], e)
                with self.lock:
                    self.job["failed"].append(name)
        self._set(state=state, error=error, step="", pct=0.0)
        log("CHD-Umwandlung:", state, error, f"{self.job.get('ok')} von {len(todo)}")

    def _after(self, tile, folder, c, final, serial, delete, refs):
        """Nach gepruefter Umwandlung: Seriennummer merken (aus einer .chd liest VoidStation sie nicht selbst), Optionen
        des Spiels auf den neuen Dateinamen umziehen, Originale loeschen oder nach _umgewandelt verschieben."""
        cue, key = c["cue"], c["key"]                     # key: Dateiname, unter dem die Spieleliste das Spiel fuehrte
        if serial:
            _disc_id_put(tile, final, serial)
        try:
            d = emu_games_load()
            moved = False
            for games in d.values():
                if isinstance(games, dict) and key in games and final.name not in games:
                    games[final.name] = games.pop(key)
                    moved = True
            if moved:
                emu_games_save(d)
        except OSError as e:
            log("emu-games.json:", e)
        sys_dir = ROMS.rom_dir / folder
        if not cue:                                        # Bild "Spiel (Track 1).png" -> "Spiel.png" (Name der .chd)
            old = ROM_COVERS.own_image(folder, c["tracks"][0].relative_to(sys_dir).as_posix())
            if old is not None and old.stem != final.stem and old.parent.name.casefold() == "cover":
                new = old.with_name(final.stem + old.suffix)
                if not new.exists():
                    try:
                        os.replace(old, new)
                    except OSError as e:
                        log("CHD: Bild bleibt:", old.name, e)
        files = [cue] if cue else []                       # ohne Blatt: nur die Spuren (das erzeugte Blatt ist schon weg)
        for t in c["tracks"]:
            refs[t] = refs.get(t, 1) - 1
            if refs[t] <= 0:                              # eine Spur, die noch ein anderes Blatt braucht, bleibt liegen
                files.append(t)
        for f in files:
            try:
                if delete:
                    f.unlink()
                else:
                    dest = sys_dir / self.KEEP_DIR / f.relative_to(sys_dir)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if dest.exists():
                        dest = dest.with_name(f"{dest.stem}-{int(time.time())}{dest.suffix}")
                    os.replace(f, dest)
            except OSError as e:
                log("CHD: Original bleibt liegen:", f.name, e)


CHD = ChdConvert()


# ---------------------------------------------------------------------------
#  Bluetooth: Kopfhoerer, Controller, Joysticks, Tastaturen – BlueZ ueber D-Bus
# ---------------------------------------------------------------------------
BT_AGENT_XML = """
<node>
  <interface name="org.bluez.Agent1">
    <method name="Release"/>
    <method name="RequestPinCode"><arg type="o" direction="in"/><arg type="s" direction="out"/></method>
    <method name="DisplayPinCode"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
    <method name="RequestPasskey"><arg type="o" direction="in"/><arg type="u" direction="out"/></method>
    <method name="DisplayPasskey"><arg type="o" direction="in"/><arg type="u" direction="in"/><arg type="q" direction="in"/></method>
    <method name="RequestConfirmation"><arg type="o" direction="in"/><arg type="u" direction="in"/></method>
    <method name="RequestAuthorization"><arg type="o" direction="in"/></method>
    <method name="AuthorizeService"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
    <method name="Cancel"/>
  </interface>
</node>
"""

# Geraeteart aus dem BlueZ-Symbol; was nicht gekoppelt ist und hier "hide" ergibt, erscheint nicht in der Liste
BT_KIND_BY_ICON = (("audio", "audio"), ("input-gaming", "gamepad"), ("input-keyboard", "keyboard"),
                   ("input-mouse", "mouse"), ("input-tablet", "mouse"), ("phone", "hide"),
                   ("computer", "hide"), ("video-display", "hide"), ("printer", "hide"),
                   ("camera", "hide"), ("network", "hide"), ("modem", "hide"))
BT_KIND_ORDER = {"audio": 0, "gamepad": 1, "keyboard": 2, "mouse": 3, "other": 4, "hide": 5}

# BlueZ-Fehler -> Schluessel in i18n (bt.err.*)
BT_ERRORS = (("AuthenticationFailed", "auth"), ("AuthenticationRejected", "auth"), ("AuthenticationCanceled", "auth"),
             ("AuthenticationTimeout", "timeout"), ("ConnectionAttemptFailed", "timeout"), ("Page Timeout", "timeout"),
             ("page-timeout", "timeout"), ("Host is down", "timeout"), ("UnknownObject", "gone"),
             ("DoesNotExist", "gone"), ("does not exist", "gone"), ("NotReady", "off"), ("Blocked", "off"),
             ("InProgress", "busy"), ("profile-unavailable", "profile"), ("NotAvailable", "profile"))


def bt_error_key(msg):
    for needle, key in BT_ERRORS:
        if needle.lower() in (msg or "").lower():
            return "bt.err." + key
    return "bt.err.other"


class BluetoothManager:
    """BlueZ ueber D-Bus (python3-gobject) mit eigenem Kopplungs-Agenten.

    Der Agent beantwortet Kopplungsanfragen selbst, ohne Tastatur am Fernseher:
      * Just Works / Bestaetigung (Kopfhoerer, Controller, AirPods): annehmen
      * alte Geraete mit PIN: nacheinander 0000, 1234, 1111
      * Tastaturen, die einen Code verlangen: Code steht in status()["prompt"] (Oberflaeche zeigt ihn)
    Anfragen, die ein Geraet von sich aus stellt, nimmt er nur im Kopplungsfenster an (Suche + 3 Min.)
    oder fuer bereits gekoppelte Geraete – sonst koennte sich jedes Geraet in Reichweite koppeln.
    Mehrere Adapter (z. B. USB-Stick + eingebauter Chip): der neueste Bluetooth-Standard gewinnt,
    die anderen werden ausgeschaltet. Fest waehlbar ueber /usr/local/share/voidstation/bt-adapter
    (Adresse des Adapters)."""

    MAC_RE = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$", re.I)
    AGENT_PATH = "/org/voidstation/btagent"
    PINS = ("0000", "1234", "1111")
    SCAN_SECONDS = 30
    WINDOW = 180
    ADAPTER_FILE = Path("/usr/local/share/voidstation/bt-adapter")

    def __init__(self):
        self.lock = threading.Lock()
        self.bus = None
        self.Gio: Any = None                           # gi.repository, geladen im Agent-Thread
        self.GLib: Any = None
        self._agent_ok = False
        self._started = False
        self._scanning = False
        self._scan_until = 0.0
        self._window_until = 0.0
        self._pairing = None          # D-Bus-Pfad des Geraets, das gerade gekoppelt wird
        self._pin = "0000"
        self._pin_asked = False
        self._prompt = None           # {"mac", "code"} fuer Tastaturen
        self._adapter_path = None
        self._last_err = ""

    # ---- Verbindung zu BlueZ ----
    def start(self):
        """Agent-Thread starten (einmal, beim Start des Launchers)."""
        if self._started:
            return
        self._started = True
        try:
            import gi
            gi.require_version("Gio", "2.0")
            from gi.repository import Gio, GLib
        except (ImportError, ValueError) as e:
            log("Bluetooth: python3-gobject fehlt, nur bluetoothctl:", e)
            return
        self.Gio, self.GLib = Gio, GLib
        threading.Thread(target=self._agent_thread, daemon=True).start()

    def _connect_bus(self):
        Gio = self.Gio
        addr = os.environ.get("VS_BT_BUS")             # nur fuer Tests (eigener D-Bus mit nachgebautem BlueZ)
        if addr:
            return Gio.DBusConnection.new_for_address_sync(
                addr, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
        return Gio.bus_get_sync(Gio.BusType.SYSTEM, None)

    def _agent_thread(self):
        Gio, GLib = self.Gio, self.GLib
        ctx = GLib.MainContext()
        ctx.push_thread_default()
        while self.bus is None:
            try:
                self.bus = self._connect_bus()
            except GLib.Error as e:
                log("Bluetooth: kein System-D-Bus:", e.message)
                time.sleep(10)
        node = Gio.DBusNodeInfo.new_for_xml(BT_AGENT_XML)
        self.bus.register_object(self.AGENT_PATH, node.interfaces[0], self._agent_call, None, None)
        self.bus.signal_subscribe("org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged",
                                  "/org/freedesktop/DBus", "org.bluez", Gio.DBusSignalFlags.NONE,
                                  self._owner_changed, None)
        self._register_agent()
        GLib.MainLoop(ctx).run()

    def _owner_changed(self, _conn, _sender, _path, _iface, _sig, params, _data):
        name, _old, new = params.unpack()
        if name != "org.bluez":
            return
        self._agent_ok = False
        self._adapter_path = None
        if new:                                         # bluetoothd (neu) gestartet
            threading.Thread(target=lambda: (time.sleep(1), self._register_agent()), daemon=True).start()  # type: ignore[func-returns-value]

    def _register_agent(self):
        if not self.bus:
            return False
        try:
            self._call("/org/bluez", "org.bluez.AgentManager1", "RegisterAgent",
                       self.GLib.Variant("(os)", (self.AGENT_PATH, "KeyboardDisplay")))
        except RuntimeError as e:
            if "AlreadyExists" not in str(e):
                if "ServiceUnknown" not in str(e) and "NameHasNoOwner" not in str(e):
                    log("Bluetooth: Agent nicht angemeldet:", e)
                return False
        try:
            self._call("/org/bluez", "org.bluez.AgentManager1", "RequestDefaultAgent",
                       self.GLib.Variant("(o)", (self.AGENT_PATH,)))
        except RuntimeError as e:
            log("Bluetooth: Agent nicht Standard:", e)
        if not self._agent_ok:
            log("Bluetooth: Kopplungs-Agent aktiv")
        self._agent_ok = True
        return True

    def _call(self, path, iface, method, params=None, timeout=10):
        """Methode bei BlueZ aufrufen; Fehler -> RuntimeError mit D-Bus-Fehlername und Text."""
        if not self.bus:
            raise RuntimeError("org.bluez.Error.NotReady: kein D-Bus")
        try:
            r = self.bus.call_sync("org.bluez", path, iface, method, params, None,
                                   self.Gio.DBusCallFlags.NONE, int(timeout * 1000), None)
            return r.unpack() if r is not None else ()
        except self.GLib.Error as e:
            name = self.Gio.DBusError.get_remote_error(e) or ""
            msg = re.sub(r"^GDBus\.Error:[\w.]+: ", "", e.message or "")
            raise RuntimeError(f"{name}: {msg}") from None

    def _set_prop(self, path, iface, prop, variant):
        self._call(path, "org.freedesktop.DBus.Properties", "Set", self.GLib.Variant("(ssv)", (iface, prop, variant)))

    def _objects(self):
        try:
            return self._call("/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects")[0]
        except RuntimeError:
            return {}

    def _bluez_running(self):
        if not self.bus:
            return False
        try:
            r = self.bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                   "NameHasOwner", self.GLib.Variant("(s)", ("org.bluez",)), None,
                                   self.Gio.DBusCallFlags.NONE, 3000, None)
            return bool(r.unpack()[0])
        except self.GLib.Error:
            return False

    # ---- Adapter ----
    def _adapter(self, objs=None):
        """Pfad des Adapters, mit dem VoidStation arbeitet (siehe Klassenbeschreibung)."""
        objs = objs if objs is not None else self._objects()
        ads = sorted((p, o["org.bluez.Adapter1"]) for p, o in objs.items() if "org.bluez.Adapter1" in o)
        if not ads:
            self._adapter_path = None
            return None
        try:
            want = self.ADAPTER_FILE.read_text(encoding="utf-8").strip().upper()
        except OSError:
            want = ""
        pick = next((p for p, a in ads if want and str(a.get("Address", "")).upper() == want), None)
        if not pick:
            usable = [(p, a) for p, a in ads if a.get("PowerState") != "off-blocked"] or ads
            pick = max(usable, key=lambda pa: (int(pa[1].get("Version", 0) or 0), -ads.index(pa)))[0]
        if pick != self._adapter_path:
            self._adapter_path = pick
            a = dict(ads)[pick]
            log("Bluetooth-Adapter:", pick, a.get("Address", ""), "Version", a.get("Version", "?"))
            for p, other in ads:                           # zweiter Adapter aus, sonst antworten beide
                if p != pick and other.get("Powered"):
                    try:
                        self._set_prop(p, "org.bluez.Adapter1", "Powered", self.GLib.Variant("b", False))
                        log("Bluetooth: weiterer Adapter ausgeschaltet:", p, other.get("Address", ""))
                    except RuntimeError as e:
                        log("Bluetooth:", p, e)
        return pick

    def _dev_path(self, adapter, mac):
        return f"{adapter}/dev_{mac.upper().replace(':', '_')}"

    @staticmethod
    def _mac_of(path):
        m = re.search(r"dev_([0-9A-F_]{17})$", path or "", re.I)
        return m.group(1).replace("_", ":").upper() if m else ""

    # ---- Agent (laeuft im Agent-Thread) ----
    def _allowed(self, path):
        return path == self._pairing or time.time() < self._window_until

    def _known(self, path):
        d = self._objects().get(path, {}).get("org.bluez.Device1", {})
        return bool(d.get("Paired") or d.get("Trusted"))

    def _agent_call(self, _conn, _sender, _path, _iface, method, params, inv):
        GLib = self.GLib
        args = params.unpack()
        dev = args[0] if args else ""
        mac = self._mac_of(dev)

        def reject(why="Rejected"):
            log("Bluetooth-Agent:", method, mac, "abgelehnt")
            inv.return_dbus_error("org.bluez.Error." + why, "VoidStation: nicht im Kopplungsfenster")

        if method == "Release":
            self._agent_ok = False
            return inv.return_value(None)
        if method == "Cancel":
            self._prompt = None
            return inv.return_value(None)
        if method == "RequestPinCode":
            if not self._allowed(dev):
                return reject()
            self._pin_asked = True
            log("Bluetooth-Agent: PIN", self._pin, "fuer", mac)
            return inv.return_value(GLib.Variant("(s)", (self._pin,)))
        if method == "DisplayPinCode":
            self._prompt = {"mac": mac, "code": args[1]}
            return inv.return_value(None)
        if method == "RequestPasskey":
            if not self._allowed(dev):
                return reject()
            return inv.return_value(GLib.Variant("(u)", (0,)))
        if method == "DisplayPasskey":
            self._prompt = {"mac": mac, "code": f"{args[1]:06d}", "entered": args[2]}
            return inv.return_value(None)
        if method in ("RequestConfirmation", "RequestAuthorization"):
            if not self._allowed(dev):
                return reject()
            return inv.return_value(None)
        if method == "AuthorizeService":
            if self._known(dev) or self._allowed(dev):
                return inv.return_value(None)
            return reject()
        inv.return_dbus_error("org.bluez.Error.Rejected", "unbekannt")

    # ---- Abfragen ----
    def is_available(self):
        return bool(shutil.which("bluetoothctl"))

    def is_service_active(self):
        return os.path.exists("/var/service/bluetoothd") or self._bluez_running()

    @staticmethod
    def _kind(dev):
        icon = str(dev.get("Icon") or "")
        for prefix, kind in BT_KIND_BY_ICON:
            if icon.startswith(prefix):
                return kind
        cls = int(dev.get("Class") or 0)
        major, minor = (cls >> 8) & 0x1F, (cls >> 2) & 0x3F
        if major == 0x04:
            return "audio"
        if major == 0x05:
            if (minor & 0x0F) in (1, 2):                       # Joystick, Gamepad
                return "gamepad"
            return "keyboard" if minor & 0x10 else "mouse" if minor & 0x20 else "gamepad"
        if major in (0x01, 0x02):
            return "hide"
        uuids = " ".join(str(u) for u in dev.get("UUIDs") or [])
        if "0000110b" in uuids or "0000111e" in uuids:
            return "audio"
        if "00001124" in uuids or "00001812" in uuids:      # HID (klassisch / LE)
            return "gamepad"
        return "other"

    def _devices(self, objs, adapter):
        out: list[dict[str, Any]] = []
        for path, o in objs.items():
            d = o.get("org.bluez.Device1")
            if not d or not path.startswith(adapter + "/"):
                continue
            mac = str(d.get("Address") or self._mac_of(path)).upper()
            name = str(d.get("Name") or "")
            alias = str(d.get("Alias") or "")
            if alias.replace("-", ":").upper() == mac:
                alias = ""
            paired = bool(d.get("Paired") or d.get("Bonded"))
            kind = self._kind(d)
            if not paired and (not (name or alias) or kind == "hide"):
                continue
            bat = o.get("org.bluez.Battery1", {}).get("Percentage")
            out.append({"mac": mac, "name": alias or name, "orig": name, "custom": bool(alias) and alias != name,
                        "paired": paired,
                        "connected": bool(d.get("Connected")), "trusted": bool(d.get("Trusted")),
                        "kind": "other" if kind == "hide" else kind,
                        "icon": "audio" if kind == "audio" else "gamepad" if kind == "gamepad" else "bluetooth",
                        "battery": int(bat) if bat is not None else None,
                        "rssi": int(d["RSSI"]) if d.get("RSSI") is not None else None})
        out.sort(key=lambda x: (not x["connected"], not x["paired"], BT_KIND_ORDER.get(x["kind"], 4),
                                -(x["rssi"] if x["rssi"] is not None else -999), x["name"].lower()))
        return out[:30]

    def status(self):
        if not self.bus:
            return self._legacy_status()
        objs = self._objects()
        adapter = self._adapter(objs)
        service = self.is_service_active()
        if adapter and not self._agent_ok:
            self._register_agent()
        a = objs.get(adapter, {}).get("org.bluez.Adapter1", {}) if adapter else {}
        powered = bool(a.get("Powered"))
        prompt = self._prompt if self._pairing else None
        return {
            "available": self.is_available() and (adapter is not None or not self._bluez_running()),
            "service": service,
            "powered": powered,
            "blocked": a.get("PowerState") == "off-blocked",
            "scanning": self._scanning,
            "pairing": self._mac_of(self._pairing) if self._pairing else None,
            "prompt": prompt,
            "adapter": str(a.get("Address", "")),
            "devices": self._devices(objs, adapter) if (adapter and powered) else [],
        }

    # ---- Suche ----
    def start_scan(self, seconds=None):
        if not self.bus:
            return self._legacy_scan()
        seconds = seconds or self.SCAN_SECONDS
        adapter = self._adapter()
        if not adapter:
            return
        self._register_agent()                          # Standard-Agent holen (falls bluetoothctl ihn hatte)
        now = time.time()
        self._window_until = max(self._window_until, now + seconds + self.WINDOW)
        with self.lock:
            self._scan_until = max(self._scan_until, now + seconds)
            if self._scanning:
                return
            self._scanning = True
        try:
            self._call(adapter, "org.bluez.Adapter1", "SetDiscoveryFilter",
                       self.GLib.Variant("(a{sv})", ({"Transport": self.GLib.Variant("s", "auto"),
                                                       "DuplicateData": self.GLib.Variant("b", False)},)))
        except RuntimeError as e:
            log("Bluetooth: Suchfilter:", e)
        try:
            self._call(adapter, "org.bluez.Adapter1", "StartDiscovery")
        except RuntimeError as e:
            if "InProgress" not in str(e):
                log("Bluetooth: Suche:", e)
                with self.lock:
                    self._scanning = False
                return

        def stop_later():
            while time.time() < self._scan_until and self._scanning:
                time.sleep(0.5)
            self._stop_scan(adapter)

        threading.Thread(target=stop_later, daemon=True).start()

    def _stop_scan(self, adapter=None):
        adapter = adapter or self._adapter_path
        with self.lock:
            was, self._scanning = self._scanning, False
        if was and adapter:
            try:
                self._call(adapter, "org.bluez.Adapter1", "StopDiscovery")
            except RuntimeError:
                pass

    # ---- Koppeln / Verbinden ----
    def pair(self, mac):
        """Koppeln, vertrauen, verbinden. Rueckgabe (ok, Fehlerschluessel oder None)."""
        if not self.bus:
            return self._legacy_pair(mac), None
        adapter = self._adapter()
        if not adapter:
            return False, "bt.err.off"
        path = self._dev_path(adapter, mac)
        self._window_until = max(self._window_until, time.time() + self.WINDOW)
        if path not in self._objects():                # BlueZ vergisst ungekoppelte Geraete nach der Suche
            self.start_scan(20)
            t0 = time.time()
            while path not in self._objects() and time.time() - t0 < 15:
                time.sleep(0.5)
            if path not in self._objects():
                return False, "bt.err.gone"
        self._stop_scan(adapter)                        # manche Controller koppeln nicht, solange gesucht wird
        self._register_agent()
        self._pairing, self._prompt = path, None
        try:
            err = None
            for i, pin in enumerate(self.PINS):
                self._pin, self._pin_asked = pin, False
                try:
                    self._call(path, "org.bluez.Device1", "Pair", timeout=60)
                    err = None
                    break
                except RuntimeError as e:
                    err = str(e)
                    if "AlreadyExists" in err:          # war schon gekoppelt
                        err = None
                        break
                    log("Bluetooth: Koppeln", mac, "fehlgeschlagen:", err)
                    if self._pin_asked and bt_error_key(err) == "bt.err.auth" and i + 1 < len(self.PINS):
                        time.sleep(1)
                        continue
                    break
            if err:
                return False, bt_error_key(err)
            log("Bluetooth: gekoppelt", mac)
            try:
                self._set_prop(path, "org.bluez.Device1", "Trusted", self.GLib.Variant("b", True))
            except RuntimeError as e:
                log("Bluetooth: vertrauen", mac, e)
            ok, cerr = self._connect_path(path, mac)
            return ok, cerr
        finally:
            self._pairing, self._prompt = None, None

    def _connect_path(self, path, mac):
        err = ""
        for attempt in range(2):
            try:
                self._call(path, "org.bluez.Device1", "Connect", timeout=30)
                err = ""
                break
            except RuntimeError as e:
                err = str(e)
                if "AlreadyConnected" in err or "InProgress" in err:
                    err = ""
                    break
                log("Bluetooth: verbinden", mac, f"(Versuch {attempt + 1}):", err)
                time.sleep(2)
        d = self._objects().get(path, {}).get("org.bluez.Device1", {})
        if err and not d.get("Connected"):
            return False, bt_error_key(err)
        if self._kind(d) == "audio":
            threading.Thread(target=bt_audio_follow, args=(mac,), daemon=True).start()
        return True, None

    def connect(self, mac):
        if not self.bus:
            return self._legacy_connect(mac), None
        adapter = self._adapter()
        if not adapter:
            return False, "bt.err.off"
        path = self._dev_path(adapter, mac)
        if path not in self._objects():
            return False, "bt.err.gone"
        self._stop_scan(adapter)
        return self._connect_path(path, mac)

    def disconnect(self, mac):
        if not self.bus:
            return self._legacy_simple("disconnect", mac)
        adapter = self._adapter()
        try:
            self._call(self._dev_path(adapter, mac), "org.bluez.Device1", "Disconnect", timeout=15)
            return True
        except (RuntimeError, TypeError) as e:
            log("Bluetooth: trennen", mac, e)
            return False

    def remove(self, mac):
        if not self.bus:
            return self._legacy_simple("remove", mac)
        adapter = self._adapter()
        try:
            self._call(adapter, "org.bluez.Adapter1", "RemoveDevice",
                       self.GLib.Variant("(o)", (self._dev_path(adapter, mac),)), timeout=15)
            return True
        except (RuntimeError, TypeError) as e:
            log("Bluetooth: entfernen", mac, e)
            return False

    # ---- Umbenennen: eigener Name als BlueZ-Alias (bei gekoppelten Geraeten dauerhaft gespeichert,
    #      der vom Geraet gemeldete Name bleibt unberuehrt; leerer Name = wieder der Geraetename) ----
    NAME_MAX = 40

    @classmethod
    def clean_name(cls, name):
        name = re.sub(r"[\x00-\x1f\x7f]+", " ", str(name or ""))
        name = re.sub(r"\s{2,}", " ", name).strip()
        return name[:cls.NAME_MAX].strip()

    def rename(self, mac, name):
        name = self.clean_name(name)
        if not self.bus:
            return self._legacy_rename(mac, name)
        adapter = self._adapter()
        if not adapter:
            return False
        path = self._dev_path(adapter, mac)
        if path not in self._objects():
            return False
        try:
            self._set_prop(path, "org.bluez.Device1", "Alias", self.GLib.Variant("s", name))
            log("Bluetooth: umbenannt", mac, "->", repr(name) if name else "(Geraetename)")
            return True
        except RuntimeError as e:
            log("Bluetooth: umbenennen", mac, e)
            return False

    def power(self, on):
        if not self.bus:
            return self._legacy_simple("power", "on" if on else "off")
        adapter = self._adapter()
        if not adapter:
            return False
        for attempt in range(2):
            try:
                self._set_prop(adapter, "org.bluez.Adapter1", "Powered", self.GLib.Variant("b", bool(on)))
                return True
            except RuntimeError as e:
                log("Bluetooth: Ein/Aus:", e)
                if on and attempt == 0:                 # per Funkschalter (rfkill) gesperrt -> freigeben
                    subprocess.run(["sudo", "-n", PKG_HELPER, "bluetooth", "on"],
                                   capture_output=True, text=True, timeout=30)
                    time.sleep(1)
        return False

    # ---- Rueckfall ohne python3-gobject: bluetoothctl (ohne eigenen Agenten) ----
    def _legacy_status(self):
        available = self.is_available()
        service = os.path.exists("/var/service/bluetoothd")
        powered = False
        if available and service:
            r = run(["bluetoothctl", "show"])
            powered = bool(r and r.returncode == 0 and "Powered: yes" in r.stdout)
        devs = {}
        if powered:
            for args, paired in ((["devices", "Paired"], True), (["devices"], False)):
                r = run(["bluetoothctl", *args])
                for line in (r.stdout.splitlines() if r and r.returncode == 0 else []):
                    p = line.strip().split(None, 2)
                    if len(p) >= 3 and p[0] == "Device" and p[1] not in devs:
                        if paired or p[2].replace("-", ":").upper() != p[1].upper():
                            devs[p[1]] = {"mac": p[1], "name": p[2], "paired": paired, "connected": False,
                                          "icon": "bluetooth", "kind": "other", "battery": None}
            for mac, d in list(devs.items())[:25]:
                info = run(["bluetoothctl", "info", mac])
                for line in (info.stdout.splitlines() if info and info.returncode == 0 else []):
                    line = line.strip()
                    if line.startswith("Connected: yes"):
                        d["connected"] = True
                    elif line.startswith("Icon:"):
                        ic = line.split(":", 1)[1].strip()
                        d["kind"] = self._kind({"Icon": ic})
                        d["icon"] = "audio" if d["kind"] == "audio" else "gamepad" if d["kind"] == "gamepad" else "bluetooth"
        lst = sorted(devs.values(), key=lambda x: (not x["connected"], not x["paired"], x["name"].lower()))
        return {"available": available, "service": service, "powered": powered, "scanning": self._scanning,
                "pairing": None, "prompt": None, "devices": lst}

    def _legacy_scan(self):
        with self.lock:
            if self._scanning:
                return
            self._scanning = True

        def _do():
            try:
                run(["bluetoothctl", "--timeout", str(self.SCAN_SECONDS), "scan", "on"], timeout=self.SCAN_SECONDS + 5)
            finally:
                with self.lock:
                    self._scanning = False

        threading.Thread(target=_do, daemon=True).start()

    def _legacy_pair(self, mac):
        run(["bluetoothctl", "pair", mac], timeout=30)
        run(["bluetoothctl", "trust", mac], timeout=10)
        return self._legacy_connect(mac)

    def _legacy_connect(self, mac):
        r = run(["bluetoothctl", "connect", mac], timeout=20)
        return bool(r and r.returncode == 0)

    def _legacy_simple(self, cmd, arg):
        r = run(["bluetoothctl", cmd, arg], timeout=15)
        return bool(r and r.returncode == 0)

    def _legacy_rename(self, mac, name):
        """bluetoothctl kann den Alias nur fuer das gerade gewaehlte Geraet setzen -> direkt per dbus-send."""
        dev = "dev_" + mac.upper().replace(":", "_")
        hcis = sorted(p.name for p in Path("/sys/class/bluetooth").glob("hci*") if ":" not in p.name) if \
            Path("/sys/class/bluetooth").is_dir() else []
        for hci in hcis:
            r = run(["dbus-send", "--system", "--print-reply", "--dest=org.bluez", f"/org/bluez/{hci}/{dev}",
                     "org.freedesktop.DBus.Properties.Set", "string:org.bluez.Device1", "string:Alias",
                     f"variant:string:{name}"], timeout=10)
            if r and r.returncode == 0:
                return True
        return False


def bt_audio_follow(mac, wait=10):
    """Ton auf den gerade verbundenen Bluetooth-Kopfhoerer legen (PipeWire merkt sich das als Standard:
    verbindet er sich spaeter von selbst, wechselt der Ton wieder dorthin)."""
    key = mac.upper().replace(":", "_")
    t0 = time.time()
    while time.time() - t0 < wait:
        for s in pactl_json("list", "sinks") or []:
            name = s.get("name", "")
            props = s.get("properties") or {}
            if key in name.upper() or str(props.get("api.bluez5.address", "")).upper() == mac.upper():
                if audio_select("bluez_card." + key):    # gemerktes Format/Mikro, sonst A2DP (volle Qualitaet)
                    log("Ton auf Bluetooth:", name)
                    return True
                run(["pactl", "set-default-sink", name])
                run(["pactl", "set-sink-mute", name, "0"])
                log("Ton auf Bluetooth:", name)
                return True
        time.sleep(0.5)
    log("Bluetooth: kein Tonausgang fuer", mac, "(Geraet ohne Audio-Profil oder PipeWire-Bluetooth fehlt)")
    return False


BLUETOOTH = BluetoothManager()


# ---------------------------------------------------------------------------
#  YouTube Light (Player-Modus --yt, Kachel "ytlight"): YouTube ohne Browser und ohne Google-Konto.
#  Suche, Kanaele, Playlists und Stream-Adressen ueber yt-dlp; Abos lokal ueber die RSS-Feeds der Kanaele
#  (Import aus Google Takeout, NewPipe, FreeTube); Verlauf, Weiterschauen und "Spaeter ansehen" lokal.
#  Shorts bleiben draussen (Feed: Playlist-Feed UULF… = nur normale Videos; Suche: /shorts/-Adressen und <= 60 s).
#  Kein Google-Login: die Data-API verbietet Fremd-Player, Cookies aus einem Browser gefaehrden das Konto.
# ---------------------------------------------------------------------------
YT_VID = re.compile(r"[A-Za-z0-9_-]{11}")
YT_CID = re.compile(r"UC[A-Za-z0-9_-]{22}")
YT_PID = re.compile(r"[A-Za-z0-9_-]{10,80}")
YT_QUALITIES = ("auto", "1080", "720", "480", "360")
YT_IMG_HOSTS = re.compile(r"^https://(i\d?\.ytimg\.com|yt3\.ggpht\.com|yt3\.googleusercontent\.com|i\.ytimg\.com)/")
# Fehlermeldungen von yt-dlp -> Grund fuer die Anzeige (yt.err.<grund>)
YT_ERRORS = [
    (re.compile(r"(?i)confirm your age|age-restricted|inappropriate for some users"), "age"),
    (re.compile(r"(?i)not a bot|sign in to confirm"), "bot"),
    (re.compile(r"(?i)private video"), "private"),
    (re.compile(r"(?i)members[- ]only|join this channel"), "members"),
    (re.compile(r"(?i)not available in your country|blocked it in your country|geo"), "geo"),
    (re.compile(r"(?i)premieres? in|live event will begin|upcoming"), "upcoming"),
    (re.compile(r"(?i)video unavailable|has been removed|does not exist|account.*terminated|no longer available"), "gone"),
    (re.compile(r"(?i)requested format is not available|nsig|n challenge|signature|js runtime|javascript|"
                r"some formats may be missing|unable to extract|http error 403"), "outdated"),
    (re.compile(r"(?i)timed out|temporary failure in name resolution|network is unreachable|"
                r"name or service not known|connection (refused|reset)|urlopen error|unable to download|"
                r"unable to connect|proxy"), "offline"),
]


class YtError(Exception):
    def __init__(self, reason, msg=""):
        super().__init__(msg or reason)
        self.reason = reason


def yt_classify(text):
    for rx, reason in YT_ERRORS:
        if rx.search(text or ""):
            return reason
    return "failed"


class YtLight:
    SUBS = BASE / "yt-subs.json"
    HIST = BASE / "yt-history.json"
    LATER = BASE / "yt-later.json"
    LOCAL = BASE / "bin" / "yt-dlp"                     # eigene, aktuelle yt-dlp-Kopie (Knopf "yt-dlp aktualisieren")
    CACHE = Path.home() / ".cache" / "voidstation" / "yt"
    RSS = "https://www.youtube.com/feeds/videos.xml?"
    YTDLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/"
    NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
          "m": "http://search.yahoo.com/mrss/"}
    # Seiten von youtube.com ohne Zustimmungsdialog (EU): Cookie "Notwendige" wie nach "Alle ablehnen"
    WEB_HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0",
                   "Accept-Language": "en-US,en;q=0.8", "Cookie": "SOCS=CAI; CONSENT=PENDING+999"}
    MAX_HIST = 500
    MAX_LATER = 500

    def __init__(self):
        self.lock = threading.Lock()
        self.cache = {}                                  # (art, schluessel) -> (zeit, daten)
        self.feed: dict[str, Any] = {"items": [], "t": 0, "refreshing": False, "errors": 0}
        self.upd: dict[str, Any] = {"state": "idle", "msg": "", "t": 0}
        self.ver = ("", 0.0)
        self.avatar_busy = False

    # ---- Dateien ----
    @staticmethod
    def _load(path, default):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            return d if isinstance(d, type(default)) else default
        except (OSError, ValueError):
            return default

    @staticmethod
    def _save(path, data):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(path)
        except OSError as e:
            log("YouTube Light:", path.name, e)

    # ---- Einstellungen und Werkzeuge ----
    @staticmethod
    def weak():
        v = os.environ.get("VS_WEAK", "")
        return v == "1" if v in ("0", "1") else os.uname().machine in ("i386", "i486", "i586", "i686")

    def settings(self):
        d = settings_load().get("yt") or {}
        q = str(d.get("quality") or "auto")
        return {"accepted": bool(d.get("accepted")), "quality": q if q in YT_QUALITIES else "auto"}

    def save_settings(self, body):
        s = settings_load()
        d = dict(s.get("yt") or {})
        if "accepted" in body:
            d["accepted"] = bool(body.get("accepted"))
        if body.get("quality") in YT_QUALITIES:
            d["quality"] = body["quality"]
        s["yt"] = d
        settings_save(s)
        return self.state()

    def tool(self):
        if os.environ.get("VS_YTDLP"):
            return os.environ["VS_YTDLP"]
        if self.LOCAL.is_file() and os.access(self.LOCAL, os.X_OK):
            return str(self.LOCAL)
        return shutil.which("yt-dlp")

    def version(self):
        v, t = self.ver
        if time.time() - t < 600:
            return v
        exe = self.tool()
        r = run([exe, "--version"], timeout=40) if exe else None
        v = r.stdout.strip() if r and r.returncode == 0 else ""
        self.ver = (v, time.time())
        return v

    def base_args(self):
        exe = self.tool()
        if not exe:
            raise YtError("noytdlp", "yt-dlp fehlt")
        args = [exe, "--ignore-config", "--no-warnings", "--no-progress"]
        if shutil.which("node"):                        # JS-Aufgaben von YouTube (yt-dlp-ejs), Node.js >= 22
            args += ["--js-runtimes", "node"]
        return args

    def state(self):
        self._auto_update()
        return dict(self.settings(), weak=self.weak(), subs=len(self._load(self.SUBS, [])),
                    tools={"ytdlp": self.version(), "local": self.LOCAL.is_file(), "node": bool(shutil.which("node"))},
                    update=dict(self.upd))

    def _ytdlp(self, args, timeout=60):
        """yt-dlp mit -J aufrufen und das JSON zurueckgeben; Fehler als YtError mit Grund."""
        full = self.base_args() + args
        t0 = time.monotonic()
        try:
            r = subprocess.run(full, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            raise YtError("timeout", "yt-dlp antwortet nicht")
        except OSError as e:
            raise YtError("noytdlp", str(e))
        if r.returncode != 0 or not r.stdout.strip():
            err = [ln for ln in (r.stderr or "").splitlines() if "ERROR" in ln] or (r.stderr or "").strip().splitlines()
            msg = (err[-1] if err else "yt-dlp-Fehler").replace("ERROR: ", "")
            log(f"YouTube Light: yt-dlp ({time.monotonic() - t0:.1f} s):", msg[:300])
            raise YtError(yt_classify(r.stderr), msg[:300])
        try:
            d = json.loads(r.stdout)
        except ValueError:
            raise YtError("failed", "Antwort von yt-dlp nicht lesbar")
        if not isinstance(d, dict):
            raise YtError("failed", "Antwort von yt-dlp nicht lesbar")
        # Netzfehler bei Listen: yt-dlp meldet ERROR, liefert aber trotzdem JSON mit leeren Eintraegen ([null])
        ents = d.get("entries")
        if ents is not None:
            d["entries"] = [e for e in ents if isinstance(e, dict)]
            if not d["entries"] and "ERROR" in (r.stderr or ""):
                err = [ln for ln in r.stderr.splitlines() if "ERROR" in ln]
                log("YouTube Light: yt-dlp:", err[-1][:300])
                raise YtError(yt_classify(r.stderr), err[-1].replace("ERROR: ", "")[:300])
        return d

    def _cached(self, kind, key, ttl, fn):
        now = time.time()
        with self.lock:
            hit = self.cache.get((kind, key))
            if hit and now - hit[0] < ttl:
                return hit[1]
        data = fn()
        with self.lock:
            self.cache[(kind, key)] = (now, data)
            if len(self.cache) > 300:
                for k, _ in sorted(self.cache.items(), key=lambda kv: kv[1][0])[:100]:
                    self.cache.pop(k, None)
        return data

    # ---- Eintraege ----
    @staticmethod
    def _thumb_url(thumbs, square=False):
        best, bw = "", 0
        for t in thumbs or []:
            if not isinstance(t, dict) or not t.get("url"):
                continue
            w = int(t.get("width") or 0)
            h = int(t.get("height") or 0)
            if square and w and h and abs(w - h) > 4:
                continue
            if w > 900 or (bw and w < bw):
                continue
            best, bw = t["url"], w
        if best.startswith("//"):
            best = "https:" + best
        return best

    @staticmethod
    def img_url(u):
        return "/api/yt/img?u=" + urllib.parse.quote(u, safe="") if u else ""

    def video(self, e):
        """Eintrag aus yt-dlp (flach) -> Video fuer die Oberflaeche; None fuer Shorts und Unbrauchbares."""
        vid = str(e.get("id") or "")
        url = str(e.get("url") or e.get("webpage_url") or "")
        if not YT_VID.fullmatch(vid) or "/shorts/" in url:
            return None
        live = e.get("live_status") == "is_live" or bool(e.get("is_live"))
        if e.get("live_status") in ("is_upcoming", "post_live") and not live:
            return None
        dur = int(e.get("duration") or 0)
        if 0 < dur <= 60:                                  # Shorts tauchen in der Suche auch als normale Videos auf
            return None
        ts = e.get("timestamp") or e.get("release_timestamp") or 0
        return {"kind": "video", "id": vid, "title": str(e.get("title") or "")[:200],
                "channel": str(e.get("channel") or e.get("uploader") or "")[:100],
                "channel_id": str(e.get("channel_id") or "") if YT_CID.fullmatch(str(e.get("channel_id") or "")) else "",
                "duration": dur, "views": int(e.get("view_count") or 0), "published": int(ts or 0), "live": live,
                "thumb": f"/api/yt/img?v={vid}"}

    def channel_item(self, e):
        cid = str(e.get("channel_id") or e.get("id") or "")
        if not YT_CID.fullmatch(cid):
            m = YT_CID.search(str(e.get("url") or ""))
            cid = m.group(0) if m else ""
        if not cid:
            return None
        return {"kind": "channel", "id": cid, "title": str(e.get("channel") or e.get("title") or "")[:100],
                "followers": int(e.get("channel_follower_count") or 0),
                "thumb": self.img_url(self._thumb_url(e.get("thumbnails"), square=True))}

    def playlist_item(self, e):
        url = str(e.get("url") or "")
        m = re.search(r"[?&]list=([A-Za-z0-9_-]+)", url)
        pid = m.group(1) if m else str(e.get("id") or "")
        if not YT_PID.fullmatch(pid) or YT_VID.fullmatch(pid):
            return None
        thumb = self._thumb_url(e.get("thumbnails"))
        return {"kind": "playlist", "id": pid, "title": str(e.get("title") or "")[:200],
                "channel": str(e.get("channel") or e.get("uploader") or "")[:100],
                "count": int(e.get("playlist_count") or 0), "thumb": self.img_url(thumb)}

    def entry(self, e):
        url = str(e.get("url") or "")
        if "list=" in url and "watch?" not in url:
            return self.playlist_item(e)
        if "/channel/" in url or "/@" in url or YT_CID.fullmatch(str(e.get("id") or "")):
            return self.channel_item(e)
        return self.video(e)

    def annotate(self, items):
        """Fortschritt (Verlauf), Spaeter-Markierung und Abo-Status ergaenzen."""
        hist = {h["id"]: h for h in self._load(self.HIST, []) if isinstance(h, dict) and h.get("id")}
        later = {x.get("id") for x in self._load(self.LATER, []) if isinstance(x, dict)}
        subs = {x.get("id") for x in self._load(self.SUBS, []) if isinstance(x, dict)}
        out = []
        for it in items:
            if not it:
                continue
            it = dict(it)
            if it["kind"] == "video":
                h = hist.get(it["id"])
                if h and not it.get("live"):
                    it["pos"], it["dur"] = h.get("pos", 0), h.get("dur", 0)
                it["later"] = it["id"] in later
            elif it["kind"] == "channel":
                it["sub"] = it["id"] in subs
            out.append(it)
        return out

    # ---- Suche, Kanaele, Playlists ----
    def search(self, q, kind="video"):
        q = " ".join(str(q or "").split())[:200]
        if not q:
            return {"items": []}
        if kind not in ("video", "channel", "playlist"):
            kind = "video"

        def fetch():
            if kind == "video":
                d = self._ytdlp(["-J", "--flat-playlist", f"ytsearch40:{q}"], timeout=90)
                items = [self.video(e) for e in d.get("entries") or []]
            else:
                sp = "EgIQAg==" if kind == "channel" else "EgIQAw=="
                url = "https://www.youtube.com/results?" + urllib.parse.urlencode({"search_query": q, "sp": sp})
                d = self._ytdlp(["-J", "--flat-playlist", "--playlist-end", "30", url], timeout=90)
                items = [self.entry(e) for e in d.get("entries") or []]
                items = [x for x in items if x and x["kind"] == kind]
            seen, out = set(), []
            for x in items:
                if x and (x["kind"], x["id"]) not in seen:
                    seen.add((x["kind"], x["id"]))
                    out.append(x)
            return out
        return {"items": self.annotate(self._cached("search", (kind, q.lower()), 600, fetch)), "q": q, "kind": kind}

    def channel(self, cid, tab="videos"):
        if not YT_CID.fullmatch(cid or ""):
            raise YtError("gone", "ungueltige Kanal-ID")
        tab = tab if tab in ("videos", "streams", "playlists") else "videos"

        def fetch():
            d = self._ytdlp(["-J", "--flat-playlist", "--playlist-end", "60",
                             f"https://www.youtube.com/channel/{cid}/{tab}"], timeout=90)
            ents = d.get("entries") or []
            items = [self.playlist_item(e) if tab == "playlists" else self.video(e) for e in ents]
            if tab == "streams":                           # vergangene Livestreams sind normale Videos
                items = [x for x in items if x]
            name = str(d.get("channel") or d.get("uploader") or d.get("title") or "")
            name = re.sub(r"\s+-\s+(Videos|Live|Playlists)$", "", name)
            thumb = self._thumb_url([t for t in d.get("thumbnails") or [] if "avatar" in str(t.get("id", ""))]
                                    or d.get("thumbnails"), square=True)
            return {"id": cid, "title": name[:100], "followers": int(d.get("channel_follower_count") or 0),
                    "thumb": self.img_url(thumb), "tab": tab, "items": [x for x in items if x]}
        r = dict(self._cached("channel", (cid, tab), 900, fetch))
        self._sub_touch(cid, r.get("title"), r.get("thumb"))
        r["sub"] = cid in {x.get("id") for x in self._load(self.SUBS, []) if isinstance(x, dict)}
        r["items"] = self.annotate(r["items"])
        return r

    def playlist(self, pid):
        if not YT_PID.fullmatch(pid or ""):
            raise YtError("gone", "ungueltige Playlist-ID")

        def fetch():
            d = self._ytdlp(["-J", "--flat-playlist", "--playlist-end", "300",
                             f"https://www.youtube.com/playlist?list={pid}"], timeout=120)
            items = [self.video(e) for e in d.get("entries") or []]
            return {"id": pid, "title": str(d.get("title") or "")[:200],
                    "channel": str(d.get("channel") or d.get("uploader") or "")[:100],
                    "channel_id": str(d.get("channel_id") or "") if YT_CID.fullmatch(str(d.get("channel_id") or "")) else "",
                    "items": [x for x in items if x]}
        r = dict(self._cached("playlist", pid, 900, fetch))
        r["items"] = self.annotate(r["items"])
        r["count"] = len(r["items"])
        return r

    # ---- Abspielen ----
    @staticmethod
    def chapters(d):
        """Kapitel aus yt-dlp (aus der Beschreibung bzw. von YouTube): [{"t": Start in s, "title"}], aufsteigend, ab 0.
        Weniger als zwei Kapitel = keine (ein einzelnes "Kapitel" ist das ganze Video)."""
        dur = float(d.get("duration") or 0)
        out: list[dict[str, Any]] = []
        for c in d.get("chapters") or []:
            if not isinstance(c, dict):
                continue
            try:
                t = max(0.0, float(c.get("start_time") or 0))
            except (TypeError, ValueError):
                continue
            if dur and t >= dur:
                continue
            title = " ".join(str(c.get("title") or "").split())[:120]
            out.append({"t": round(t, 1), "title": title})
        out.sort(key=lambda c: c["t"])
        uniq: list = []
        for c in out:                                   # gleiche Startzeit: das erste zaehlt
            if not uniq or c["t"] - uniq[-1]["t"] >= 1:
                uniq.append(c)
        if len(uniq) < 2:
            return []
        uniq[0]["t"] = 0.0                              # das erste Kapitel beginnt immer am Anfang
        return uniq[:300]

    def resolve(self, vid, quality="auto", lang="de"):
        """Stream-Adressen fuer mpv: Bild und Ton getrennt (DASH) oder eine Adresse (Livestream: HLS)."""
        if not YT_VID.fullmatch(vid or ""):
            raise YtError("gone", "ungueltige Video-ID")
        if quality not in YT_QUALITIES:
            quality = self.settings()["quality"]
        weak = self.weak()
        h = (480 if weak else 1080) if quality == "auto" else int(quality)
        # H.264 ist am billigsten zu dekodieren (und kann fast jede Grafikkarte); auf schwacher Hardware hoechstens 30 fps
        sort = f"res:{h},vcodec:h264,acodec:aac" + (",fps:30" if weak else "")

        def fetch():
            d = self._ytdlp(["-J", "--no-playlist", "-f", "bv+ba/b", "-S", sort,
                             f"https://www.youtube.com/watch?v={vid}"], timeout=150 if weak else 75)
            rf = d.get("requested_formats") or []
            vf = next((f for f in rf if f.get("vcodec") not in (None, "none")), None)
            af = next((f for f in rf if f.get("vcodec") in (None, "none") and f.get("acodec") not in (None, "none")), None)
            main = vf or d
            url = str(main.get("url") or "")
            if not url.startswith("http"):
                raise YtError("failed", "keine Stream-Adresse")
            hdr = main.get("http_headers") or d.get("http_headers") or {}
            heights = sorted({int(f.get("height") or 0) for f in d.get("formats") or []
                              if f.get("vcodec") not in (None, "none") and 144 <= int(f.get("height") or 0) <= 2160},
                             reverse=True)
            subs = []
            for code, tracks in (d.get("subtitles") or {}).items():   # nur echte Untertitel, keine automatischen
                vtt = next((t for t in tracks or [] if t.get("ext") == "vtt" and t.get("url")), None)
                if vtt and code != "live_chat":
                    subs.append({"lang": code, "name": str(vtt.get("name") or code), "url": vtt["url"]})
            want = [lang.split("-")[0], "en", str(d.get("language") or "")]
            subs.sort(key=lambda s: next((i for i, w in enumerate(want) if w and s["lang"].split("-")[0] == w), 9))
            live = bool(d.get("is_live"))
            return {"id": vid, "title": str(d.get("title") or "")[:200], "chapters": [] if live else self.chapters(d),
                    "channel": str(d.get("channel") or d.get("uploader") or "")[:100],
                    "channel_id": str(d.get("channel_id") or "") if YT_CID.fullmatch(str(d.get("channel_id") or "")) else "",
                    "duration": int(d.get("duration") or 0), "live": live,
                    "url": url, "audio": str(af.get("url") or "") if af else "",
                    "ua": str(hdr.get("User-Agent") or ""), "referer": str(hdr.get("Referer") or ""),
                    "height": int(main.get("height") or 0), "vcodec": str(main.get("vcodec") or ""),
                    "heights": heights, "quality": quality, "subs": subs[:3],
                    "thumb": f"/api/yt/img?v={vid}"}
        t0 = time.monotonic()
        key = ("resolve", (vid, quality, lang))
        with self.lock:
            hit = self.cache.get(key)
        # Adressen gelten bei YouTube etwa 6 Stunden; Livestreams nur kurz aufheben
        if hit and time.time() - hit[0] < (600 if hit[1].get("live") else 5400):
            return hit[1]
        r = fetch()
        with self.lock:
            self.cache[key] = (time.time(), r)
        log(f"YouTube Light: {vid} aufgeloest in {time.monotonic() - t0:.1f} s ({r.get('height')}p {r.get('vcodec')})")
        return r

    # ---- Verlauf, Spaeter, Weiterschauen ----
    @staticmethod
    def _meta(body):
        vid = str(body.get("id") or "")
        if not YT_VID.fullmatch(vid):
            raise ValueError("ungueltige Video-ID")
        cid = str(body.get("channel_id") or "")
        return {"kind": "video", "id": vid, "title": str(body.get("title") or "")[:200],
                "channel": str(body.get("channel") or "")[:100], "channel_id": cid if YT_CID.fullmatch(cid) else "",
                "duration": int(float(body.get("duration") or body.get("dur") or 0)), "live": bool(body.get("live")),
                "thumb": f"/api/yt/img?v={vid}"}

    def progress(self, body):
        it = self._meta(body)
        pos, dur = float(body.get("pos") or 0), float(body.get("dur") or 0)
        with self.lock:
            hist = [h for h in self._load(self.HIST, []) if isinstance(h, dict) and h.get("id") != it["id"]]
            it.update({"pos": 0 if it["live"] else round(pos, 1), "dur": round(dur, 1), "t": int(time.time())})
            hist.insert(0, it)
            self._save(self.HIST, hist[:self.MAX_HIST])
        return {"ok": True}

    def history(self):
        return {"items": self.annotate(self._load(self.HIST, []))}

    def history_remove(self, vid):
        with self.lock:
            hist = self._load(self.HIST, [])
            self._save(self.HIST, [h for h in hist if isinstance(h, dict) and h.get("id") != vid] if vid else [])
        return self.history()

    def resume_list(self):
        out = []
        for h in self._load(self.HIST, []):
            if isinstance(h, dict) and not h.get("live") and h.get("dur", 0) > 0 and 30 < h.get("pos", 0) < 0.95 * h["dur"]:
                out.append(h)
        return self.annotate(out[:20])

    def later(self):
        return {"items": self.annotate(self._load(self.LATER, []))}

    def later_set(self, body):
        it = self._meta(body.get("item") or {})
        with self.lock:
            lst = [x for x in self._load(self.LATER, []) if isinstance(x, dict) and x.get("id") != it["id"]]
            if body.get("on"):
                lst.insert(0, it)
            self._save(self.LATER, lst[:self.MAX_LATER])
        return {"on": bool(body.get("on")), "n": len(lst)}

    # ---- Abos ----
    def subs(self):
        lst = [x for x in self._load(self.SUBS, []) if isinstance(x, dict) and YT_CID.fullmatch(str(x.get("id") or ""))]
        lst.sort(key=lambda x: str(x.get("title") or "").lower())
        if any(not x.get("thumb") for x in lst):
            self._fetch_avatars()
        return [{"kind": "channel", "id": x["id"], "title": x.get("title") or x["id"], "thumb": x.get("thumb") or "",
                 "sub": True} for x in lst]

    def sub_set(self, body):
        it = body.get("item") or {}
        cid = str(it.get("id") or it.get("channel_id") or "")
        if not YT_CID.fullmatch(cid):
            raise ValueError("ungueltige Kanal-ID")
        on = bool(body.get("on"))
        with self.lock:
            lst = [x for x in self._load(self.SUBS, []) if isinstance(x, dict) and x.get("id") != cid]
            if on:
                lst.append({"id": cid, "title": str(it.get("title") or it.get("channel") or "")[:100],
                            "thumb": str(it.get("thumb") or ""), "t": int(time.time())})
            self._save(self.SUBS, lst)
            self.feed["t"] = 0                             # Feed beim naechsten Abruf neu holen
        log("YouTube Light: Abo", "an" if on else "aus", cid)
        return {"on": on, "n": len(lst)}

    def _sub_touch(self, cid, title, thumb):
        """Name und Bild eines abonnierten Kanals nachtragen (Import liefert oft nur die ID)."""
        with self.lock:
            lst = self._load(self.SUBS, [])
            changed = False
            for x in lst:
                if isinstance(x, dict) and x.get("id") == cid:
                    if title and not x.get("title"):
                        x["title"], changed = title, True
                    if thumb and not x.get("thumb"):
                        x["thumb"], changed = thumb, True
            if changed:
                self._save(self.SUBS, lst)

    def _fetch_avatars(self):
        """Fehlende Kanalbilder nachladen (og:image der Kanalseite), eins pro Sekunde, im Hintergrund."""
        if self.avatar_busy:
            return
        self.avatar_busy = True

        def work():
            try:
                for x in self._load(self.SUBS, []):
                    if not isinstance(x, dict) or x.get("thumb") or not YT_CID.fullmatch(str(x.get("id") or "")):
                        continue
                    if x.get("nothumb", 0) > time.time() - 86400:
                        continue
                    thumb, title = "", ""
                    try:
                        req = urllib.request.Request(f"https://www.youtube.com/channel/{x['id']}", headers=self.WEB_HEADERS)
                        with urllib.request.urlopen(req, timeout=15) as r:
                            html = r.read(1_500_000).decode("utf-8", "replace")
                        m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
                        thumb = self.img_url(m.group(1).replace("&amp;", "&")) if m and YT_IMG_HOSTS.match(m.group(1)) else ""
                        m = re.search(r'<meta property="og:title" content="([^"]+)"', html)
                        title = m.group(1) if m else ""
                    except (OSError, ValueError) as e:
                        log("YouTube Light: Kanalbild", x["id"], e)
                    with self.lock:
                        lst = self._load(self.SUBS, [])
                        for y in lst:
                            if isinstance(y, dict) and y.get("id") == x["id"]:
                                if thumb:
                                    y["thumb"] = thumb
                                else:
                                    y["nothumb"] = int(time.time())
                                if title and not y.get("title"):
                                    y["title"] = html_unescape(title)[:100]
                        self._save(self.SUBS, lst)
                    time.sleep(1)
            finally:
                self.avatar_busy = False
        threading.Thread(target=work, daemon=True).start()

    def import_subs(self):
        """Abos aus Dateien uebernehmen: Google Takeout (subscriptions.csv / Abos.csv, auch im ZIP), NewPipe
        (newpipe_subscriptions*.json), FreeTube (profiles.db / *subscriptions*.db). Gesucht wird in ~/share und auf
        USB-Laufwerken; vorhandene Abos bleiben."""
        import zipfile
        found: list
        chans: dict
        found, chans = [], {}

        def take(text, name):
            n0 = len(chans)
            lines = text.splitlines()
            if name.lower().endswith(".csv"):
                for ln in lines[1:]:
                    m = YT_CID.search(ln)
                    if m:
                        cols = next(csv.reader([ln]), [])
                        title = next((c for c in reversed(cols) if c and "youtube.com" not in c and not YT_CID.fullmatch(c)), "")
                        chans.setdefault(m.group(0), title.strip())
            else:
                try:
                    objs = [json.loads(text)]
                except ValueError:
                    objs = []
                    for ln in lines:                       # FreeTube: eine JSON-Zeile pro Profil
                        try:
                            objs.append(json.loads(ln))
                        except ValueError:
                            pass
                for o in objs:
                    for s in (o.get("subscriptions") or []) if isinstance(o, dict) else []:
                        if not isinstance(s, dict):
                            continue
                        m = YT_CID.search(str(s.get("id") or s.get("url") or ""))
                        if m:
                            chans.setdefault(m.group(0), str(s.get("name") or "").strip())
            if len(chans) > n0:
                found.append(name)

        def wanted(p):
            n = p.name.lower()
            return (n.endswith(".csv") and ("subscription" in n or n.startswith("abo"))) or \
                   (n.endswith(".json") and "newpipe" in n and "subscription" in n) or \
                   (n.endswith(".db") and ("profiles" in n or "subscription" in n)) or \
                   (n.endswith(".zip") and n.startswith("takeout"))
        roots = [Path.home() / "share"] + [p for d in ("/run/media", "/media") for p in Path(d).glob("*/*") if p.is_dir()]
        for root in roots:
            base_depth = len(root.parts)
            for dirpath, dirs, files in os.walk(root):
                if len(Path(dirpath).parts) - base_depth >= 4:
                    dirs[:] = []
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for fn in files:
                    p = Path(dirpath) / fn
                    if not wanted(p):
                        continue
                    try:
                        if p.stat().st_size > 50_000_000:
                            continue
                        if p.suffix.lower() == ".zip":
                            with zipfile.ZipFile(p) as z:
                                for zn in z.namelist():
                                    low = zn.lower().rsplit("/", 1)[-1]
                                    if low.endswith(".csv") and ("subscription" in low or low.startswith("abo")):
                                        take(z.read(zn).decode("utf-8-sig", "replace"), f"{p.name}/{low}")
                        else:
                            take(p.read_text(encoding="utf-8-sig", errors="replace"), p.name)
                    except (OSError, zipfile.BadZipFile, UnicodeError) as e:
                        log("YouTube Light: Import", p, e)
        added = 0
        with self.lock:
            lst = [x for x in self._load(self.SUBS, []) if isinstance(x, dict)]
            have = {x.get("id") for x in lst}
            for cid, title in chans.items():
                if cid not in have:
                    lst.append({"id": cid, "title": title[:100], "thumb": "", "t": int(time.time())})
                    added += 1
            self._save(self.SUBS, lst)
            if added:
                self.feed["t"] = 0
        log(f"YouTube Light: Import aus {', '.join(found) or 'nichts gefunden'} – {added} neue Kanaele")
        if added:
            self._fetch_avatars()
        return {"files": found, "found": len(chans), "added": added, "total": len(lst)}

    # ---- Abo-Feed (RSS) ----
    def _rss(self, cid):
        """Neueste Videos eines Kanals. Zuerst der Playlist-Feed UULF… (nur normale Videos, ohne Shorts und
        Livestreams), sonst der Kanal-Feed ohne /shorts/-Eintraege. Bei Fehlern der letzte gute Stand."""
        cache = self.CACHE / "feeds" / f"{cid}.json"
        old = self._load(cache, {})
        items, err = None, ""
        for q, shorts_filter in ((f"playlist_id=UULF{cid[2:]}", False), (f"channel_id={cid}", True)):
            try:
                req = urllib.request.Request(self.RSS + q, headers=UA)
                with urllib.request.urlopen(req, timeout=15) as r:
                    root = ET.fromstring(r.read(3_000_000))
            except urllib.error.HTTPError as e:
                err = f"HTTP {e.code}"
                if e.code == 404:
                    continue
                break
            except (OSError, ET.ParseError) as e:
                err = str(e)
                break
            items = []
            title = (root.findtext("a:title", "", self.NS) or "").strip()
            for en in root.findall("a:entry", self.NS):
                vid = en.findtext("yt:videoId", "", self.NS)
                link = en.find("a:link", self.NS)
                href = link.get("href", "") if link is not None else ""
                if not YT_VID.fullmatch(vid or "") or (shorts_filter and "/shorts/" in href):
                    continue
                stats = en.find("m:group/m:community/m:statistics", self.NS)
                pub = en.findtext("a:published", "", self.NS)
                try:
                    ts = int(datetime.datetime.fromisoformat(pub.replace("Z", "+00:00")).timestamp())
                except ValueError:
                    ts = 0
                items.append({"kind": "video", "id": vid, "title": (en.findtext("a:title", "", self.NS) or "")[:200],
                              "channel": (en.findtext("a:author/a:name", "", self.NS) or title)[:100], "channel_id": cid,
                              "duration": 0, "views": int(stats.get("views") or 0) if stats is not None else 0,
                              "published": ts, "live": False, "thumb": f"/api/yt/img?v={vid}"})
            break
        if items is None:
            return old.get("items") or [], err or "kein Feed"
        self._save(cache, {"t": int(time.time()), "items": items})
        return items, ""

    def _refresh_feed(self):
        from concurrent.futures import ThreadPoolExecutor
        subs = [x for x in self._load(self.SUBS, []) if isinstance(x, dict) and YT_CID.fullmatch(str(x.get("id") or ""))]
        t0 = time.monotonic()
        errors, allv = 0, []
        try:
            with ThreadPoolExecutor(max_workers=6) as ex:
                for items, err in ex.map(lambda s: self._rss(s["id"]), subs):
                    allv += items
                    errors += 1 if err else 0
            seen, uniq = set(), []
            for v in sorted(allv, key=lambda v: v["published"], reverse=True):
                if v["id"] not in seen:
                    seen.add(v["id"])
                    uniq.append(v)
            with self.lock:
                self.feed.update(items=uniq[:300], t=time.time(), errors=errors)
            log(f"YouTube Light: Feed aus {len(subs)} Kanaelen in {time.monotonic() - t0:.1f} s"
                + (f", {errors} nicht erreichbar" if errors else ""))
        finally:
            with self.lock:
                self.feed["refreshing"] = False

    def feed_get(self, limit=150, force=False):
        has_subs = bool(self._load(self.SUBS, []))
        with self.lock:
            stale = force or time.time() - self.feed["t"] > 900
            if stale and has_subs and not self.feed["refreshing"]:
                self.feed["refreshing"] = True
                threading.Thread(target=self._refresh_feed, daemon=True).start()
            items = list(self.feed["items"][:limit])
            state = {"refreshing": self.feed["refreshing"], "errors": self.feed["errors"], "t": int(self.feed["t"])}
        if not items and not self.feed["t"]:                # gleich nach dem Start: letzter Stand aus den Dateien
            allv: list = []
            for x in self._load(self.SUBS, []):
                if isinstance(x, dict) and x.get("id"):
                    allv += self._load(self.CACHE / "feeds" / f"{x['id']}.json", {}).get("items") or []
            items = sorted({v["id"]: v for v in allv}.values(), key=lambda v: v["published"], reverse=True)[:limit]
        return dict(state, items=self.annotate(items))

    def home(self):
        f = self.feed_get(60)
        later = self._load(self.LATER, [])
        return {"resume": self.resume_list(), "feed": f["items"], "refreshing": f["refreshing"], "errors": f["errors"],
                "later": self.annotate(later[:30]), "laterCount": len(later), "subs": self.subs(),
                "historyCount": len(self._load(self.HIST, []))}

    # ---- Bilder (Zwischenspeicher, damit alte Rechner nicht alles neu laden) ----
    def img(self, vid="", url=""):
        if vid:
            if not YT_VID.fullmatch(vid):
                return None
            url = f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg"
        if not YT_IMG_HOSTS.match(url or ""):
            return None
        f = self.CACHE / "img" / (hashlib.sha1(url.encode()).hexdigest()[:20] + ".jpg")
        try:
            if f.is_file() and f.stat().st_size:
                return f.read_bytes()
        except OSError:
            pass
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=15) as r:
                data = r.read(2_000_000)
                if not str(r.headers.get("Content-Type", "")).startswith("image/"):
                    return None
        except (OSError, ValueError):
            return None
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(data)
            if random.random() < 0.02:                     # ab und zu aufraeumen: hoechstens ~4000 Bilder
                files = sorted(f.parent.glob("*.jpg"), key=lambda p: p.stat().st_mtime)
                for p in files[:max(0, len(files) - 4000)]:
                    p.unlink(missing_ok=True)
        except OSError:
            pass
        return data

    # ---- yt-dlp aktualisieren (eigene Kopie, Prüfsumme von GitHub) ----
    def update_ytdlp(self, quiet=False):
        with self.lock:
            if self.upd["state"] == "running":
                return dict(self.upd)
            self.upd = {"state": "running", "msg": "", "t": int(time.time()), "quiet": quiet}

        def work():
            tmp = self.LOCAL.with_suffix(".new")
            try:
                req = urllib.request.Request(self.YTDLP_URL + "SHA2-256SUMS", headers=UA)
                with urllib.request.urlopen(req, timeout=30) as r:
                    sums = r.read(200_000).decode("utf-8", "replace")
                want = next((ln.split()[0] for ln in sums.splitlines()
                             if len(ln.split()) == 2 and ln.split()[1].lstrip("*") == "yt-dlp"), "")
                if not re.fullmatch(r"[0-9a-f]{64}", want):
                    raise RuntimeError("Pruefsumme nicht gefunden")
                self.LOCAL.parent.mkdir(parents=True, exist_ok=True)
                h = hashlib.sha256()
                req = urllib.request.Request(self.YTDLP_URL + "yt-dlp", headers=UA)
                with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as fh:
                    while True:
                        b = r.read(65536)
                        if not b:
                            break
                        h.update(b)
                        fh.write(b)
                if h.hexdigest() != want:
                    raise RuntimeError("Pruefsumme stimmt nicht")
                tmp.chmod(0o755)
                r = run([str(tmp), "--version"], timeout=60)
                if not r or r.returncode != 0:
                    raise RuntimeError("neue Version startet nicht")
                tmp.replace(self.LOCAL)
                self.ver = ("", 0.0)
                with self.lock:
                    self.cache = {k: v for k, v in self.cache.items() if k[0] != "resolve"}
                    self.upd = {"state": "done", "msg": r.stdout.strip(), "t": int(time.time()), "quiet": quiet}
                log("YouTube Light: yt-dlp aktualisiert auf", r.stdout.strip())
            except (OSError, RuntimeError, ValueError) as e:
                tmp.unlink(missing_ok=True)
                with self.lock:
                    self.upd = {"state": "error", "msg": str(e)[:200], "t": int(time.time()), "quiet": quiet}
                log("YouTube Light: yt-dlp-Aktualisierung fehlgeschlagen:", e)
        threading.Thread(target=work, daemon=True).start()
        return dict(self.upd)

    def _auto_update(self):
        """Gibt es schon eine eigene yt-dlp-Kopie, wird sie woechentlich still aktualisiert (YouTube aendert oft etwas)."""
        try:
            age = time.time() - self.LOCAL.stat().st_mtime
        except OSError:
            return
        if age > 7 * 86400 and self.upd["state"] != "running" and time.time() - self.upd.get("t", 0) > 86400:
            self.update_ytdlp(quiet=True)


YT = YtLight()


# ---------------------------------------------------------------------------
#  HTTP
# ---------------------------------------------------------------------------
class OskField:
    """Eingabefeld im Browser angewaehlt oder verlassen (Firefox-Erweiterung "VoidStation-Tastatur", firefox/keyboard/):
    Die Erweiterung meldet es per POST /api/osk/field, die Startseite wartet darauf mit GET /api/osk/wait (lange offen,
    kehrt bei jeder Aenderung sofort zurueck) und oeffnet bzw. schliesst die Bildschirmtastatur ueber dem Programm.
    Ereignisse: focus (Feld angewaehlt, kind = text/password/search/email/url/tel/number/textarea, pos = Mitte des
    Felds als Anteil der Bildschirmhoehe 0..1), blur (verlassen), typed (auf einer echten Tastatur getippt).
    sid kennzeichnet die meldende Seite bzw. den Frame.
    Ausserdem (vom Launcher selbst, notice): shot (Bildschirmfoto gespeichert, file = Dateiname, ok = True/False) –
    die Startseite zeigt dazu kurz einen Hinweis ueber dem Programm."""
    KINDS = ("text", "password", "search", "email", "url", "tel", "number", "textarea")

    def __init__(self):
        self.cv = threading.Condition()
        self.seq = 0
        self.state = {}

    def post(self, b):
        ev = str(b.get("ev") or "")
        if ev not in ("focus", "blur", "typed"):
            return False
        kind = str(b.get("kind") or "text")
        try:
            pos = max(0.0, min(1.0, float(b.get("pos"))))
        except (TypeError, ValueError):
            pos = None
        with self.cv:
            self.seq += 1
            self.state = {"ev": ev, "kind": kind if kind in self.KINDS else "text", "pos": pos,
                          "sid": str(b.get("sid") or "")[:40], "t": time.time()}
            self.cv.notify_all()
        return True

    def notice(self, ev, **data):
        """Meldung des Launchers an die Startseite (siehe oben), nicht von der Firefox-Erweiterung."""
        with self.cv:
            self.seq += 1
            self.state = dict(data, ev=ev, t=time.time())
            self.cv.notify_all()

    def wait(self, seq, timeout=25.0):
        """Neuester Stand, sobald er sich gegenueber seq geaendert hat (seq < 0: sofort)."""
        with self.cv:
            if seq >= 0:
                self.cv.wait_for(lambda: self.seq != seq, timeout)
            return dict(self.state, seq=self.seq)


OSK_FIELD = OskField()


# ---------------------------------------------------------------------------
#  Mullvad VPN (AppCenter-Eintrag "mullvad", Quelle "mullvad": Paket mullvad-vpn aus der eigenen Paketquelle, Daemon
#  + CLI aus der signierten .deb; voidstation-mullvad schaltet den Dienst ein). Die Startseite bedient alles ueber die mullvad-CLI – kein Electron, kein Root:
#  der Daemon nimmt Befehle von jedem lokalen Benutzer an. Zustand ueber "mullvad status listen -j" (ein Prozess,
#  meldet nur Aenderungen), Rest bei Bedarf mit kurzen Aufrufen.
# ---------------------------------------------------------------------------
class Vpn:
    PKG = "mullvad-vpn"
    OLD_PKG = "mullvad-vpn-voidstation"             # bis 2026.11 auf dem Geraet aus der .deb gebaut
    BIN = "/usr/bin/mullvad"
    STATE = BASE / "vpn.json"                       # zuletzt verbundene Orte (Startseite: "Zuletzt verbunden")
    MAP = BASE / "qt" / "qml" / "vpn" / "worldmap.json"
    ACCT = re.compile(r"^\d{16}$")
    DNS_KEYS = ("ads", "trackers", "malware", "gambling", "adult_content", "social_media")

    def __init__(self):
        self.lock = threading.Lock()
        self.cv = threading.Condition(self.lock)
        self.tunnel = None                          # letzte TunnelState-Meldung (JSON des Daemons)
        self.daemon = False
        self.seq = 0
        self.watching = False
        self._acct: dict[str, Any] = {"t": 0.0, "v": None}
        self._relays: dict[str, Any] = {"t": 0.0, "v": None}

    # ---- installiert? ------------------------------------------------------------------------------------------
    def installed(self):
        return os.path.exists(self.BIN)

    def ensure(self):
        """Beobachter starten, sobald Mullvad installiert ist (Startseite fragt /api/status alle 1,5 s ab)."""
        if self.watching or not self.installed():
            return
        with self.lock:
            if self.watching:
                return
            self.watching = True
        threading.Thread(target=self._watch, daemon=True).start()

    def _set(self, tunnel=None, daemon=None):
        with self.cv:
            if tunnel is not None:
                self.tunnel = tunnel
            if daemon is not None:
                self.daemon = daemon
            self.seq += 1
            self.cv.notify_all()

    def _watch(self):
        """"mullvad status listen -j": erst der aktuelle Zustand, dann jede Aenderung als JSON-Zeile. Neben dem
        Tunnel kommen auch Einstellungen, Serverliste usw. – Tunnel-Meldungen erkennt man am Schluessel "state".
        Faellt der Daemon weg (Update, Neustart), endet der Prozess: nach einer Pause neu verbinden."""
        try:
            while self.installed():
                try:
                    p = subprocess.Popen([self.BIN, "status", "-j", "listen"], stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, text=True, bufsize=1)
                except OSError:
                    time.sleep(10)
                    continue
                assert p.stdout is not None
                for line in p.stdout:
                    line = line.strip()
                    if not line.startswith("{"):
                        continue
                    try:
                        j = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(j, dict) and "state" in j:
                        self._set(tunnel=j, daemon=True)
                        with self.lock:
                            self._acct["t"] = 0.0           # Konto (Ablauf) nach Zustandswechsel neu lesen
                rc = p.wait()
                self._set(daemon=False)
                time.sleep(3 if rc == 0 else 6)
        finally:
            with self.lock:
                self.watching = False
                self.tunnel = None
            self._set(daemon=False)

    # ---- Zustand ---------------------------------------------------------------------------------------------
    @staticmethod
    def _loc(d):
        """TunnelState-Ort -> kompakte Form fuer die Oberflaeche."""
        loc = (d or {}).get("location") or {}
        cc = city = host = ""
        c = loc.get("location") or {}
        for kind in ("hostname", "city", "country"):
            v = c.get(kind)
            if v:
                v = v if isinstance(v, list) else [v]
                cc = str(v[0]).lower()
                city = str(v[1]) if len(v) > 1 else ""
                host = str(v[2]) if len(v) > 2 else ""
                break
        out = {"country": loc.get("country") or "", "city": loc.get("city") or "", "cc": cc, "cityCode": city,
               "host": host, "ip": loc.get("ipv4") or loc.get("ipv6") or "", "mullvadIp": bool(loc.get("mullvad_exit_ip"))}
        try:
            out["lat"], out["lon"] = float(loc["latitude"]), float(loc["longitude"])
        except (KeyError, TypeError, ValueError):
            pass
        return out

    def summary(self):
        """Kurzfassung fuer /api/status: Symbol oben rechts und Kachel."""
        if not self.installed():
            return {"installed": False}
        self.ensure()
        with self.lock:
            t, daemon, seq = self.tunnel, self.daemon, self.seq
        if not daemon or not t:
            return {"installed": True, "state": "nodaemon", "seq": seq}
        st = t.get("state")
        d = t.get("details") if isinstance(t.get("details"), dict) else {}
        out = {"installed": True, "state": st if st in ("connected", "connecting", "disconnected", "disconnecting",
                                                          "error") else "error", "seq": seq}
        if st == "disconnected":
            out["locked"] = bool(d.get("locked_down"))
        if st == "error":                                   # Fehlerzustand blockiert den Verkehr, wenn moeglich
            out["locked"] = not bool(d.get("block_failure"))
        if st in ("connected", "connecting", "disconnected"):
            out.update(self._loc(d))
        return out

    def wait(self, seq, timeout=25.0):
        with self.cv:
            if seq >= 0:
                self.cv.wait_for(lambda: self.seq != seq, timeout)
        return self.summary()

    # ---- CLI -------------------------------------------------------------------------------------------------
    def cli(self, *args, timeout=20):
        r = run([self.BIN, *args], timeout=timeout)
        if r is None:
            raise RuntimeError("timeout")
        if r.returncode != 0:
            msg = (r.stderr.strip() or r.stdout.strip() or f"Fehler {r.returncode}").splitlines()
            raise RuntimeError(msg[-1][:240] if msg else "?")
        return r.stdout

    @staticmethod
    def _onoff(out):
        v = out.strip().rsplit(":", 1)[-1].strip().lower()
        return v in ("on", "allow", "true", "yes")

    def account(self, force=False):
        """{"loggedIn", "last4", "expires" (JJJJ-MM-TT), "device"} – "account get" fragt Mullvad im Netz ab,
        deshalb hoechstens einmal je Minute (nach Zustandswechsel und Anmelden sofort)."""
        with self.lock:
            if not force and self._acct["v"] is not None and time.time() - self._acct["t"] < 60:
                return dict(self._acct["v"])
        try:
            out = self.cli("account", "get", timeout=25)
        except RuntimeError as e:
            v = {"loggedIn": False, "error": str(e)}
        else:
            v = {"loggedIn": False}
            for line in out.splitlines():
                k, _, val = line.partition(":")
                k, val = k.strip().lower(), val.strip()
                if k == "mullvad account" and val:
                    num = re.sub(r"\D", "", val)
                    v["last4"] = num[-4:]
                    v["loggedIn"] = "revoked" not in out.lower()
                elif k == "expires at":
                    v["expires"] = val[:10]
                elif k == "device name":
                    v["device"] = val
            if "revoked" in out.lower():
                v["revoked"] = True
        with self.lock:
            self._acct = {"t": time.time(), "v": v}
        return dict(v)

    def settings(self):
        s = {}
        for key, args in (("lockdown", ("lockdown-mode", "get")), ("autoconnect", ("auto-connect", "get")),
                          ("lan", ("lan", "get"))):
            try:
                s[key] = self._onoff(self.cli(*args))
            except RuntimeError:
                s[key] = None
        dns = {}
        try:
            for line in self.cli("dns", "get").splitlines():
                k, _, val = line.partition(":")
                k = k.strip().lower()
                if k.startswith("block "):
                    dns[k[6:].replace(" ", "_")] = val.strip().lower() == "true"
                elif k == "custom dns":
                    s["customDns"] = val.strip().lower() == "yes"
        except RuntimeError:
            pass
        s["dns"] = {k: bool(dns.get(k)) for k in self.DNS_KEYS}
        return s

    def relays(self, force=False):
        """Laender und Staedte aus "mullvad relay list" (Text; Breiten-/Laengengrad stehen ungeachtet der Beschriftung
        °N/°W als Zahl mit Vorzeichen da). Zwischengespeichert fuer 10 Minuten."""
        with self.lock:
            if not force and self._relays["v"] is not None and time.time() - self._relays["t"] < 600:
                return self._relays["v"]
        out = self.cli("relay", "list", timeout=25)
        countries: list[dict[str, Any]] = []
        cur: dict[str, Any] | None = None
        city: dict[str, Any] | None = None
        rx_c = re.compile(r"^(.+?) \(([a-z]{2})\)$")
        rx_city = re.compile(r"^(.+?) \(([a-z0-9]+)\) @ (-?[\d.]+)°N, (-?[\d.]+)°W$")
        for raw in out.splitlines():
            if not raw.strip():
                continue
            depth = len(raw) - len(raw.lstrip("\t"))
            s = raw.strip()
            if depth == 0:
                m = rx_c.match(s)
                cur = {"cc": m[2], "name": m[1], "cities": []} if m else None
                if cur:
                    countries.append(cur)
            elif depth == 1 and cur is not None:
                m = rx_city.match(s)
                city = {"code": m[2], "name": m[1], "lat": float(m[3]), "lon": float(m[4]), "n": 0} if m else None
                if city:
                    cur["cities"].append(city)
            elif depth >= 2 and city is not None:
                city["n"] += 1
        countries = [c for c in countries if c["cities"]]
        with self.lock:
            self._relays = {"t": time.time(), "v": countries}
        return countries

    def latest(self):
        """Version in der Paketquelle (Paketlisten laedt die Update-Pruefung)."""
        r = run(["xbps-query", "-R", "-p", "pkgver", self.PKG], timeout=60)
        m = re.match(rf"^{re.escape(self.PKG)}-(.+)_\d+$", r.stdout.strip()) if r and r.returncode == 0 else None
        if not m:
            raise RuntimeError("Mullvad: nicht in der Paketquelle")
        return m.group(1)

    def version(self):
        for pkg in (self.PKG, self.OLD_PKG):
            r = run(["xbps-query", "-p", "pkgver", pkg])
            m = re.match(rf"^{re.escape(pkg)}-(.+)_\d+$", r.stdout.strip()) if r and r.returncode == 0 else None
            if m:
                return m.group(1)
        return None

    def outdated(self):
        """Nur der Wechsel vom alten, auf dem Geraet gebauten Paket steht als eigenes Update an. Neue Versionen von
        mullvad-vpn kommen mit den Paket-Updates (voidstation-pkg update startet den Dienst danach neu). Ebenso ein
        abgebrochener Wechsel (Dienst ohne run, supervise als Ordner statt Verweis): voidstation-mullvad repariert ihn."""
        sv = Path("/etc/sv/mullvad-daemon")
        sup = sv / "supervise"
        broken = sv.is_dir() and (not (sv / "run").exists() or (sup.is_dir() and not sup.is_symlink()))
        return xbps_installed(self.OLD_PKG) or (broken and self.installed())

    # ---- zuletzt verbunden -------------------------------------------------------------------------------------
    def recent(self):
        try:
            v = json.loads(self.STATE.read_text(encoding="utf-8")).get("recent", [])
            return [x for x in v if isinstance(x, dict) and x.get("cc")][:3]
        except (OSError, ValueError, AttributeError):
            return []

    def _remember(self, cc, city):
        items = [{"cc": cc, "city": city}] + [x for x in self.recent() if (x.get("cc"), x.get("city")) != (cc, city)]
        tmp = self.STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"recent": items[:3]}), encoding="utf-8")
        tmp.replace(self.STATE)

    # ---- Seite ---------------------------------------------------------------------------------------------------
    def page(self):
        """Alles fuer die Mullvad-Seite (GET /api/vpn)."""
        if not self.installed():
            return {"installed": False}
        out = {"installed": True, "status": self.summary(), "recent": self.recent(), "version": self.version()}
        if out["status"].get("state") == "nodaemon":
            return out
        out["account"] = self.account()
        if out["account"].get("loggedIn"):
            out["settings"] = self.settings()
        return out

    def login(self, number):
        number = re.sub(r"\s", "", str(number or ""))
        if not self.ACCT.match(number):
            return {"ok": False, "error": "format"}
        try:
            self.cli("account", "login", number, timeout=40)
        except RuntimeError as e:
            m = str(e).lower()
            code = ("devices" if "too many devices" in m or "max" in m and "device" in m else
                    "invalid" if "invalid" in m or "not found" in m or "account" in m and "doesn" in m else
                    "network" if "timeout" in m or "network" in m or "connect" in m else "other")
            return {"ok": False, "error": code, "msg": str(e)}
        return {"ok": True, "account": self.account(force=True)}

    def logout(self):
        try:
            self.cli("disconnect")
        except RuntimeError:
            pass
        self.cli("account", "logout", timeout=30)
        with self.lock:
            self._acct = {"t": 0.0, "v": None}
        return {"ok": True}

    def connect(self, cc=None, city=None):
        cc = (cc or "").lower()
        city = (city or "").lower()
        if cc:
            if not re.match(r"^[a-z]{2}$", cc) or (city and not re.match(r"^[a-z0-9]{2,8}$", city)):
                raise ValueError("ungueltiger Ort")
            self.cli("relay", "set", "location", cc, *([city] if city else []))
            self._remember(cc, city)
        self.cli("connect")
        return self.summary()

    def nearest(self):
        """"Automatisch": Land des eigenen Anschlusses, wenn Mullvad dort Server hat (Mullvad selbst kennt keinen
        "naechsten Ort"), sonst Schweden."""
        st = self.summary()
        country = st.get("country", "") if st.get("state") == "disconnected" else ""
        try:
            for c in self.relays():
                if c["name"].lower() == country.lower():
                    return c["cc"]
        except RuntimeError:
            pass
        return "se"

    def disconnect(self):
        self.cli("disconnect")
        return self.summary()

    def toggle(self):
        st = self.summary().get("state")
        if st in ("connected", "connecting"):
            return self.disconnect()
        return self.connect()

    def set_option(self, key, value):
        on = bool(value)
        if key == "lockdown":
            self.cli("lockdown-mode", "set", "on" if on else "off")
        elif key == "autoconnect":
            self.cli("auto-connect", "set", "on" if on else "off")
        elif key == "lan":
            self.cli("lan", "set", "allow" if on else "block")
        elif key.startswith("dns."):
            want = self.settings()["dns"]
            k = key[4:]
            if k not in self.DNS_KEYS:
                raise ValueError("unbekannter Filter")
            want[k] = on
            self.cli("dns", "set", "default", *[f"--block-{n.replace('_', '-')}" for n in self.DNS_KEYS if want[n]])
        else:
            raise ValueError("unbekannte Einstellung")
        return self.settings()

    def map_data(self):
        try:
            return self.MAP.read_bytes()
        except OSError:
            return b"{}"


VPN = Vpn()
CRX_DIR = Path("/usr/local/share/voidstation/chromium")     # Tastatur-Erweiterung fuer Chromium/Brave, s. crxpack.py


class Handler(BaseHTTPRequestHandler):
    server_version = "voidstation"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body=b"", ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):     # Oberflaeche hat abgebrochen (z. B. Vorschaubild weggeblaettert)
            pass

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode())

    def _host_ok(self):
        return self.headers.get("Host", "") in (f"{HOST}:{PORT}", f"localhost:{PORT}")

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > 65536:
            return {}
        try:
            return json.loads(self.rfile.read(n))
        except ValueError:
            return {}

    def _keymap_post(self, rest, b):
        """Tastenbelegung je Emulator: Taste abfragen (capture), belegen (set), zuruecksetzen (reset), abbrechen."""
        try:
            if rest == ["capture"]:
                return self._json(200, PAD_CAPTURE.capture(str(b.get("path", "")), min(30.0, float(b.get("timeout") or 10)),
                                                           bool(b.get("rstick"))))
            if rest == ["cancel"]:
                PAD_CAPTURE.cancel()
                return self._json(200, {"ok": True})
            emu = str(b.get("emu", ""))
            if emu not in EMU_LAYOUTS:
                return self._json(404, {"error": "Unbekannter Emulator"})
            path = str(b.get("path", ""))
            if rest == ["set"]:
                swapped = keymap_set(emu, path, str(b.get("button", "")), b.get("bind"))
                return self._json(200, dict(keymap_payload(emu, path), swapped=swapped))
            if rest == ["reset"]:
                keymap_reset(emu, path)
                return self._json(200, keymap_payload(emu, path))
        except (ValueError, OSError) as e:
            return self._json(400, {"error": str(e)})
        return self._json(404, {"error": "unbekannt"})

    def _yt_get(self, what, qs):
        """YouTube Light (GET): Zustand, Startseite, Feed, Suche, Kanal, Playlist, Verlauf, Spaeter, Abos, Bilder."""
        g = lambda k: qs.get(k, [""])[0]
        try:
            if what == "img":
                data = YT.img(vid=g("v"), url=g("u"))
                return self._send(200, data, "image/jpeg") if data else self._send(404)
            res = {"state": YT.state, "home": YT.home, "history": YT.history, "later": YT.later,
                   "subs": lambda: {"items": YT.subs()},
                   "feed": lambda: YT.feed_get(300, force=g("force") == "1"),
                   "search": lambda: YT.search(g("q"), g("kind") or "video"),
                   "channel": lambda: YT.channel(g("id"), g("tab") or "videos"),
                   "playlist": lambda: YT.playlist(g("id"))}.get(what)
            if not res:
                return self._send(404)
            return self._json(200, res())
        except YtError as e:
            return self._json(502, {"error": e.reason, "msg": str(e)})
        except (ValueError, OSError) as e:
            log("YouTube Light:", e)
            return self._json(500, {"error": "failed", "msg": str(e)})

    def do_GET(self):
        if not self._host_ok():
            return self._send(403)
        url = urllib.parse.urlparse(self.path)
        path = url.path
        if path == "/api/front":                   # heisse Ecke und Controller-Maus der Startseite
            tid = APPS.front()
            return self._json(200, {"id": tid, "mouse": pad_mouse_default(tid),
                                    "padmouse": bool(settings_load().get("padmouse", True))})
        if path in ("/ext/keyboard.xml", "/ext/keyboard.crx"):   # VoidStation-Tastatur fuer Chromium/Brave (crxpack.py)
            try:
                data = (CRX_DIR / path.rsplit("/", 1)[1]).read_bytes()
            except OSError:
                return self._send(404)
            return self._send(200, data, "text/xml; charset=utf-8" if path.endswith(".xml")
                              else "application/x-chrome-extension")
        if path == "/api/osk/wait":                # Startseite: Eingabefeld im Browser (Long-Poll, s. OskField)
            qs = urllib.parse.parse_qs(url.query)
            try:
                seq = int(qs.get("seq", ["-1"])[0])
            except ValueError:
                seq = -1
            return self._json(200, OSK_FIELD.wait(seq))
        if path == "/api/nowplaying":              # heisse Ecke oben links
            return self._json(200, now_playing())
        if path == "/api/status":
            running = APPS.running()
            return self._json(200, {"running": running, "starting": APPS.starting(), "radio": RADIO.status(),
                                    "update": updates_badge() if not LIVE else {"available": False},
                                    "tv": TV.now if "tv" in running else None, "tvFailed": TV.failed, "live": LIVE,
                                    "media": (MEDIA_NOW or None) if "media" in running else None,
                                    "install": INSTALL.state.get("state") if INSTALL.state else None,
                                    "vpn": VPN.summary()})
        if path == "/api/tv/status":
            TV.ensure()
            return self._json(200, TV.status())
        if path in ("/api/tv/list", "/api/tv/search"):
            qs = urllib.parse.parse_qs(url.query)
            g = lambda k: qs.get(k, [""])[0]
            if path == "/api/tv/search":
                return self._json(200, TV.search(g("q"), g("country"), g("cat")))
            num = lambda k, d: int(g(k)) if g(k).isdigit() else d
            return self._json(200, TV.page(g("q"), g("country"), g("cat"), g("letter").upper(),
                                           num("offset", 0), num("limit", TV_PAGE)))
        if path == "/api/tv/favs":
            return self._json(200, [TV.mark(IPTV.public(f)) for f in tvfavs_load()])
        if path == "/api/tv/zap":                    # Player: Liste zum Umschalten, Favoriten, zuletzt gesehen
            TV.ensure()
            return self._json(200, TV.zap())
        if path == "/api/media/roots":
            return self._json(200, MEDIA.roots())
        if path == "/api/media/list":
            try:
                return self._json(200, MEDIA.listdir(urllib.parse.parse_qs(url.query).get("path", [""])[0]))
            except (ValueError, FileNotFoundError, OSError) as e:
                return self._json(404, {"error": str(e)})
        if path == "/api/media/dvd":                 # Startseite der Mediathek: Disc eingelegt/entnommen?
            return self._json(200, {"discs": DVD.discs()})
        if path == "/api/media/nextfolder":
            try:
                return self._json(200, MEDIA.next_folder(urllib.parse.parse_qs(url.query).get("path", [""])[0]) or {})
            except (ValueError, OSError) as e:
                return self._json(404, {"error": str(e)})
        if path == "/api/dl/settings":
            return self._json(200, MUSICDL.payload())
        if path == "/api/dl/status":
            return self._json(200, MUSICDL.status())
        if path.startswith("/api/yt/"):
            return self._yt_get(path[8:], urllib.parse.parse_qs(url.query))
        if path == "/api/media/covers":
            return self._json(200, COVERS.status())
        if path == "/api/media/thumb":
            qs = urllib.parse.parse_qs(url.query)
            cname = qs.get("cover", [""])[0]
            if cname:                                    # heruntergeladenes Cover aus dem Zwischenspeicher
                if not re.fullmatch(r"[0-9a-f]{16}\.jpg", cname) or not (COVERS.CACHE / cname).is_file():
                    return self._send(404)
                return self._send(200, (COVERS.CACHE / cname).read_bytes(), "image/jpeg")
            art = qs.get("art", [""])[0]
            r = MEDIA.art(art) if art else MEDIA.thumb(qs.get("path", [""])[0])
            if not r:
                return self._send(404)
            return self._send(200, r[0], r[1])
        if path == "/api/tv/epg":
            qs = urllib.parse.parse_qs(url.query)
            ch_id = qs.get("id", [""])[0] or qs.get("channel_id", [""])[0]
            ch_name = qs.get("name", [""])[0] or qs.get("channel_name", [""])[0] or ch_id
            return self._json(200, EPG.get_program(ch_id, ch_name) or {})
        if path == "/api/apps":
            return self._json(200, apps_payload())
        if path == "/api/vpn":                         # Mullvad-Seite: Zustand, Konto, Optionen, zuletzt verbunden
            return self._json(200, VPN.page())
        if path == "/api/vpn/relays":
            try:
                return self._json(200, {"countries": VPN.relays(), "nearest": VPN.nearest()})
            except RuntimeError as e:
                return self._json(502, {"error": str(e)})
        if path == "/api/vpn/wait":                    # lange offen, kehrt bei jeder Aenderung des Tunnels zurueck
            q = urllib.parse.parse_qs(url.query).get("seq", ["-1"])[0]
            return self._json(200, VPN.wait(int(q) if q.lstrip("-").isdigit() else -1))
        if path == "/api/vpn/map":                     # Punktraster der Weltkarte (tools/vpn-map.py)
            return self._send(200, VPN.map_data(), "application/json")
        if path in ("/api/updates", "/api/selfupdate"):
            force = urllib.parse.parse_qs(url.query).get("force", [""])[0] == "1"
            return self._json(200, updates_state(force))
        if path == "/api/apps/job":
            return self._json(200, JOBS.current() or {})
        if path == "/api/radio/favs":
            return self._json(200, favs_load())
        if path == "/api/radio/popular":
            cc = region()
            try:
                return self._json(200, {"country": cc, "stations": radio_popular(cc)})
            except RuntimeError as e:
                return self._json(502, {"error": str(e), "country": cc})
        if path == "/api/radio/search":
            q = urllib.parse.parse_qs(url.query).get("q", [""])[0].strip()
            if not q:
                return self._json(200, [])
            try:
                return self._json(200, radio_search(q))
            except RuntimeError as e:
                return self._json(502, {"error": str(e)})
        if path == "/api/volume":
            return self._json(200, volume_get() or {})
        if path == "/api/settings":
            return self._json(200, settings_payload())
        if path == "/api/install/probe":
            if not LIVE:
                return self._json(404, {"error": "nur im Live-System"})
            try:
                force = urllib.parse.parse_qs(url.query).get("force", [""])[0] == "1"
                return self._json(200, INSTALL.probe(force))
            except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as e:
                return self._json(502, {"error": str(e)})
        if path == "/api/install/status":
            st = INSTALL.status()
            if INSTALL.autostart:
                st["autostart"] = True
                INSTALL.autostart = False                 # nur beim ersten Aufruf
            return self._json(200, st)
        if path == "/api/install/gparted":
            return self._json(200, {"running": INSTALL.gparted_running()})
        if path == "/api/install/log":
            try:
                return self._json(200, {"log": INSTALL.log_text()})
            except (OSError, subprocess.SubprocessError) as e:
                return self._json(502, {"error": str(e)})
        if path == "/api/wifi/scan":
            try:
                return self._json(200, wifi_scan())
            except RuntimeError as e:
                return self._json(502, {"error": str(e)})
        if path == "/api/roms":
            qs = urllib.parse.parse_qs(url.query)
            system = qs.get("system", [""])[0]
            if not system:
                summary = {}
                for s in ROMS.EXTENSIONS:
                    r = ROMS.list_folder(s)
                    if r:
                        summary[s] = len(r)
                return self._json(200, {"systems": summary})
            roms = ROMS.list_roms(system)
            for r in roms:
                r["cover"] = ROM_COVERS.url(r)
            return self._json(200, {"system": ROMS.canonical_system(system), "folders": ROMS.folders(system),
                                    "count": len(roms), "roms": roms, "keymap": system in EMU_LAYOUTS,
                                    "noMenu": ROMS.canonical_system(system) == "megadrive",    # Mednafen hat kein Menue
                                    "bios": bios_status(system),
                                    "opts": system in EMU_OPTS, "gameOpts": emu_opts_has_game(system),
                                    "disc": DVD.game_for(system), "chd": CHD.status(system),
                                    "discDrive": system in ("duckstation", "pcsx2") and bool(DVD.devices())})
        if path == "/api/roms/chd":                # Spieleliste: bin/cue -> CHD (Stand, Fortschritt)
            return self._json(200, CHD.status(urllib.parse.parse_qs(url.query).get("system", [""])[0]))
        if path == "/api/roms/disc":               # Spieleliste: Disc eingelegt/entnommen?
            return self._json(200, {"disc": DVD.game_for(urllib.parse.parse_qs(url.query).get("system", [""])[0])})
        if path == "/api/emuopts":                 # Optionen eines Emulators bzw. eines Spiels (&game=<datei>)
            qs = urllib.parse.parse_qs(url.query)
            try:
                return self._json(200, emu_opts_payload(qs.get("emu", [""])[0], qs.get("game", [""])[0] or None))
            except ValueError as e:
                return self._json(404, {"error": str(e)})
        if path == "/api/keymap":                  # Tastenbelegung eines Emulators (Konsole, Controller, Tasten)
            qs = urllib.parse.parse_qs(url.query)
            emu = qs.get("emu", [""])[0]
            if emu not in EMU_LAYOUTS:
                return self._json(404, {"error": "Unbekannter Emulator"})
            return self._json(200, keymap_payload(emu, qs.get("path", [""])[0]))
        if path == "/api/roms/cover":              # Bild zum Spiel (eigenes oder online gesucht, s. RomCovers)
            qs = urllib.parse.parse_qs(url.query)
            try:
                f = ROM_COVERS.get(qs.get("folder", [""])[0], qs.get("file", [""])[0])
                if f:
                    return self._send(200, f.read_bytes(), MIME.get(f.suffix.lower(), "image/png"))
            except OSError as e:
                log("Cover:", e)
            return self._send(404)
        if path == "/api/bluetooth/status":
            return self._json(200, BLUETOOTH.status())
        if path == "/tiles.json":
            try:
                c = json.loads(CONFIG.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return self._send(404)
            hints = {a["id"]: a["start_hint"] for a in catalog()["apps"] if a.get("start_hint")}
            for g in c.get("groups", []):
                for t in g.get("tiles", []):
                    if t.get("id") in hints and not t.get("start_hint"):
                        t["start_hint"] = hints[t["id"]]
            return self._json(200, c)
        self._send(404)

    def do_POST(self):
        # Eigener Header erzwingt bei fremden Webseiten einen CORS-Preflight,
        # den wir nie beantworten -> nur die eigene Startseite darf Aktionen ausloesen.
        if not self._host_ok() or self.headers.get("X-TV") != "1":
            return self._send(403)
        parts = self.path.strip("/").split("/")
        try:
            if parts[:2] == ["api", "launch"] and len(parts) == 3:
                tile = find_tile(parts[2])
                if not tile:
                    return self._json(404, {"error": "unbekannte Kachel"})
                return self._json(200, {"result": APPS.launch(tile), "running": APPS.running()})
            if parts[:2] == ["api", "close"] and len(parts) == 3:
                APPS.close(parts[2])
                raise_home()
                return self._json(200, {"running": APPS.running()})
            if parts == ["api", "home"]:
                raise_home()
                return self._json(200, {"running": APPS.running()})
            if parts == ["api", "report"]:             # Einstellungen → System → Fehlerbericht (vsctl report: vsreport.py direkt)
                try:
                    rep = vsreport.create(status={"running": APPS.running(), "front": APPS.front()})
                except RuntimeError:
                    return self._json(409, {"error": "busy"})
                except OSError as e:
                    log("Fehlerbericht fehlgeschlagen:", e)
                    return self._json(500, {"error": str(e)})
                log(f"Fehlerbericht ({rep['seconds']} s, {rep['size']} Bytes):", rep["name"])
                return self._json(200, {k: rep[k] for k in ("name", "size", "overview", "logs")})
            if parts == ["api", "shot"]:               # vsshot bzw. F12: Bildschirmfoto nach share/Screenshots
                path, err = screenshot("vsshot")
                return self._json(200 if path else 500, {"path": str(path) if path else "", "error": err})
            if parts == ["api", "osk", "field"]:       # Firefox-Erweiterung: Eingabefeld an/ab
                return self._json(200 if OSK_FIELD.post(self._body()) else 400, {"ok": True})
            if parts[:2] == ["api", "vpn"] and len(parts) == 3:
                b = self._body()
                try:
                    act = parts[2]
                    if act == "login":
                        return self._json(200, VPN.login(b.get("account")))
                    if act == "logout":
                        return self._json(200, VPN.logout())
                    if act == "connect":
                        cc = b.get("cc") or (VPN.nearest() if b.get("auto") else None)
                        return self._json(200, VPN.connect(cc, b.get("city")))
                    if act == "disconnect":
                        return self._json(200, VPN.disconnect())
                    if act == "toggle":
                        return self._json(200, VPN.toggle())
                    if act == "set":
                        return self._json(200, VPN.set_option(str(b.get("key", "")), b.get("value")))
                except (RuntimeError, ValueError) as e:
                    return self._json(502, {"error": str(e)})
                return self._json(404, {"error": "unbekannt"})
            if parts == ["api", "nowplaying", "control"]:
                return self._json(200, now_control(str(self._body().get("action", ""))))
            if parts == ["api", "radio", "play"]:
                RADIO.play(self._body())
                return self._json(200, RADIO.status())
            if parts == ["api", "radio", "stop"]:
                RADIO.stop()
                return self._json(200, RADIO.status())
            if parts == ["api", "radio", "fav"]:
                st = self._body()
                favs = [f for f in favs_load() if f.get("url") != st.get("url")]
                if st.get("url"):
                    favs.append({k: st.get(k, "") for k in ("name", "url", "favicon", "country", "tags")})
                favs_save(favs)
                return self._json(200, favs)
            if parts == ["api", "radio", "unfav"]:
                url = self._body().get("url")
                favs = [f for f in favs_load() if f.get("url") != url]
                favs_save(favs)
                return self._json(200, favs)
            if parts == ["api", "tv", "play"]:
                b = self._body()
                return self._json(200, TV.play(str(b.get("key", "")), b.get("ctx")))
            if parts == ["api", "tv", "tune"]:              # Player schaltet um
                return self._json(200, TV.tune(str(self._body().get("key", ""))))
            if parts == ["api", "tv", "broken"]:
                b = self._body()
                TV.mark_broken(str(b.get("key", "")), str(b.get("reason", ""))[:40])
                return self._json(200, {"ok": True})
            if parts == ["api", "dl", "settings"]:
                return self._json(200, MUSICDL.save_settings(self._body().get("sources")))
            if parts[:2] == ["api", "yt"]:                        # YouTube Light
                b = self._body()
                act = "/".join(parts[2:])
                res = {"settings": lambda: YT.save_settings(b),
                       "resolve": lambda: YT.resolve(str(b.get("id") or ""), str(b.get("quality") or ""),
                                                     str(b.get("lang") or "de")),
                       "progress": lambda: YT.progress(b), "later": lambda: YT.later_set(b),
                       "sub": lambda: YT.sub_set(b), "import": YT.import_subs,
                       "history/remove": lambda: YT.history_remove(str(b.get("id") or "") or "-"),
                       "history/clear": lambda: YT.history_remove(""),
                       "update": lambda: YT.update_ytdlp()}.get(act)
                if not res:
                    return self._send(404)
                return self._json(200, res())
            if parts == ["api", "dl", "search"]:
                return self._json(200, MUSICDL.search(self._body().get("q")))
            if parts == ["api", "dl", "get"]:
                return self._json(200, MUSICDL.get(self._body().get("key")))
            if parts == ["api", "media", "covers", "scan"]:     # alle Ordner ohne Bild (Standard: share/Musik)
                root = MEDIA.resolve(str(self._body().get("path") or MEDIA.share() / "Musik"))
                if not root or not root.is_dir():
                    return self._json(404, {"error": "Ordner nicht gefunden"})
                COVERS.scan(root)
                return self._json(200, COVERS.status())
            if parts == ["api", "media", "covers", "auto"]:
                s = settings_load(); s["covers_auto"] = bool(self._body().get("on")); settings_save(s)
                return self._json(200, COVERS.status())
            if parts == ["api", "media", "covers", "refresh"]:  # Cover eines Titels neu suchen
                p = MEDIA.resolve(str(self._body().get("path") or ""))
                if not p or not p.is_file():
                    return self._json(404, {"error": "Datei nicht gefunden"})
                COVERS.refresh_track(p)
                return self._json(200, {"ok": True})
            if parts == ["api", "media", "covers", "embed"]:   # Cover + fehlende Tags in die Dateien schreiben
                s = settings_load(); s["covers_embed"] = bool(self._body().get("on")); settings_save(s)
                if s["covers_embed"]:
                    MEDIA.art_done.clear()               # beim naechsten Oeffnen der Ordner alle Titel einmal pruefen
                return self._json(200, COVERS.status())
            if parts == ["api", "media", "eject"]:
                return self._json(200, {"ok": DVD.eject(str(self._body().get("dev") or ""))})
            if parts == ["api", "media", "now"]:
                b = self._body()
                MEDIA_NOW.clear()
                if b.get("title"):
                    MEDIA_NOW.update({k: str(b.get(k) or "")[:120] for k in ("title", "sub", "kind")})
                    MEDIA_NOW["paused"] = bool(b.get("paused"))
                return self._json(200, {"ok": True})
            if parts == ["api", "media", "resume"]:
                b = self._body()
                MEDIA.resume_set(str(b.get("path", "")), b.get("pos"), b.get("dur"))
                return self._json(200, {"ok": True})
            if parts == ["api", "tv", "stop"]:
                APPS.close("tv")
                TV.now = None
                return self._json(200, TV.status())
            if parts[:2] == ["api", "tv"] and parts[2:] in (["fav"], ["unfav"]):
                key = str(self._body().get("key", ""))
                favs = [f for f in tvfavs_load() if f.get("key") != key]
                if parts[2] == "fav":
                    ent = TV.entry(key)
                    if not ent:
                        return self._json(404, {"error": "Sender unbekannt"})
                    favs.append(ent)
                tvfavs_save(favs)
                return self._json(200, [IPTV.public(f) for f in favs])
            if parts[:2] == ["api", "install"] and len(parts) == 3:
                if not LIVE:
                    return self._json(404, {"error": "nur im Live-System"})
                b = self._body()
                try:
                    if parts[2] == "start":
                        return self._json(200, INSTALL.start(b.get("config") or {}))
                    if parts[2] == "retry":
                        return self._json(200, INSTALL.start(resume=True, alt=bool(b.get("alt"))))
                    if parts[2] == "gparted":
                        INSTALL.gparted()
                        return self._json(200, {"running": True})
                    if parts[2] == "savelog":
                        return self._json(200, INSTALL.savelog())
                    if parts[2] == "keymap":
                        km = str(b.get("keymap", ""))
                        if km not in KEYMAPS:
                            return self._json(400, {"error": "unbekannte Tastatur"})
                        subprocess.run(["setxkbmap"] + KEYMAPS[km], capture_output=True, timeout=10)
                        return self._json(200, {"keymap": km})
                except RuntimeError as e:
                    return self._json(409, {"error": str(e)})
                return self._send(404)
            if parts == ["api", "settings", "ssh"]:
                on = bool(self._body().get("on"))
                r = subprocess.run(["sudo", "-n", PKG_HELPER, "ssh", "on" if on else "off"],
                                   capture_output=True, text=True, timeout=180)
                if r.returncode != 0:
                    return self._json(500, {"error": (r.stdout + r.stderr).strip()[-300:] or "fehlgeschlagen"})
                log("Fernzugriff (SSH):", "an" if on else "aus")
                return self._json(200, {"ssh": ssh_state()})
            if parts == ["api", "selfupdate", "channel"]:
                # Seit 2026.11 nur noch zurueck zu Stable; Testing gibt es nur im Terminal (vsctl channel testing)
                ch = str(self._body().get("channel", ""))
                if ch != "stable":
                    return self._json(400, {"error": "Testing nur noch im Terminal: vsctl channel testing"})
                r = subprocess.run(["sudo", "-n", PKG_HELPER, "channel", ch], capture_output=True, text=True, timeout=20)
                if r.returncode != 0:
                    return self._json(500, {"error": (r.stdout + r.stderr).strip() or "fehlgeschlagen"})
                vs_update_status(force=True)
                return self._json(200, updates_state())
            if parts == ["api", "apps", "localtile"]:
                b = self._body()
                try:
                    local_tile(str(b.get("id", "")), bool(b.get("on")))
                except RuntimeError as e:
                    return self._json(404, {"error": str(e)})
                return self._json(200, apps_payload())
            if parts[:2] == ["api", "apps"] and len(parts) == 3:
                act = parts[2]
                try:
                    if act in ("install", "remove"):
                        a = catalog_app(str(self._body().get("id", "")))
                        if not a:
                            return self._json(404, {"error": "unbekannte App"})
                        if act == "install" and a.get("retired"):
                            return self._json(409, {"error": f"{a['name']} gibt es im AppCenter nicht mehr"})
                        if act == "install" and not app_supported(a):
                            return self._json(409, {"error": f"{a['name']} gibt es nicht für {SYS_ARCH}"})
                        JOBS.start(act, a)
                    elif act == "update":               # alle Updates (Einstellungen → Updates, vsctl update)
                        if LIVE:
                            return self._json(409, {"error": "im Live-System gibt es keine Updates"})
                        JOBS.start(act)
                    else:
                        return self._send(404)
                except RuntimeError as e:
                    return self._json(409, {"error": str(e)})
                return self._json(200, JOBS.current())
            if parts == ["api", "settings", "sysupd"]:
                days = self._body().get("days")
                if days not in SYSUPD_DAYS:
                    return self._json(400, {"error": "ungueltige Frist"})
                s = settings_load(); s["sysupd_days"] = days; settings_save(s)
                log("Systemupdate-Erinnerung nach", days, "Tagen")
                return self._json(200, updates_state())
            if parts == ["api", "settings", "lang"]:
                lang = str(self._body().get("lang", ""))
                if lang not in {l["id"] for l in LANGS}:
                    return self._json(400, {"error": "unbekannte Sprache"})
                s = settings_load(); s["lang"] = lang; settings_save(s)
                log("Sprache:", lang)
                threading.Thread(target=bios_sync, daemon=True).start()      # Hinweise in den bios-Ordnern
                threading.Thread(target=ime_sync, daemon=True).start()       # Eingabemethode ja/ko/zh
                return self._json(200, {"lang": lang})
            if parts == ["api", "settings", "scale"]:
                val = float(self._body().get("scale", 1.75))
                if val not in SCALES:
                    return self._json(400, {"error": "ungueltige Skalierung"})
                s = settings_load(); s["scale"] = val; settings_save(s)
                apply_appearance(s)
                return self._json(200, settings_payload())
            if parts == ["api", "settings", "theme"]:
                th = str(self._body().get("theme", "")).strip()
                if th not in available_themes():
                    return self._json(400, {"error": "unbekanntes Theme"})
                s = settings_load(); s["theme"] = th; settings_save(s)
                apply_appearance(s)                    # Programme folgen hell/dunkel
                return self._json(200, settings_payload())
            if parts == ["api", "settings", "osk"]:      # Bildschirmtastatur: {layout: "auto" | Kennung, mode}
                b = self._body()
                s = settings_load()
                if "layout" in b:
                    lay = str(b.get("layout") or "auto")
                    if lay != "auto" and lay not in OSK_LAYOUTS:
                        return self._json(400, {"error": "unbekannte Belegung"})
                    s["osk_layout"] = None if lay == "auto" else lay
                if "mode" in b:
                    mode = str(b.get("mode"))
                    if mode not in OSK_MODES:
                        return self._json(400, {"error": "unbekannte Einstellung"})
                    s["osk_mode"] = mode
                settings_save(s)
                log("Bildschirmtastatur:", s.get("osk_layout") or "nach Sprache", s.get("osk_mode"))
                return self._json(200, settings_payload())
            if parts == ["api", "settings", "padmouse"]:
                on = bool(self._body().get("on"))
                s = settings_load(); s["padmouse"] = on; settings_save(s)
                log("Controller-Maus:", "an" if on else "aus")
                return self._json(200, settings_payload())
            if parts == ["api", "settings", "cursor"]:
                b = self._body()
                s = settings_load()
                if b.get("theme") in cursor_themes():
                    s["cursor_theme"] = b["theme"]
                if int(b.get("size") or 0) in CURSOR_SIZES:
                    s["cursor_size"] = int(b["size"])
                settings_save(s)
                apply_appearance(s)
                restart_home_later()
                return self._json(200, settings_payload())
            if parts == ["api", "settings", "resolution"]:
                b = self._body()
                mode = str(b.get("mode", ""))
                outs = [o for o in xrandr_info() if mode in o["modes"]]
                if not outs:
                    return self._json(400, {"error": "Aufloesung nicht verfuegbar"})
                rate = None                                 # ohne Angabe: wieder automatisch (~60 Hz)
                if b.get("rate") not in (None, "", 0):
                    try:
                        rate = round(float(b["rate"]), 2)
                    except (TypeError, ValueError):
                        return self._json(400, {"error": "ungueltige Bildrate"})
                    if not any(abs(r - rate) < 0.005 for o in outs for r in o["rates"].get(mode, [])):
                        return self._json(400, {"error": "Bildrate nicht verfuegbar"})
                with DISPLAY_RATE.lock:
                    DISPLAY_RATE.base = {}                  # die neue Wahl gilt als Desktop-Rate
                    apply_resolution(mode, rate)
                s = settings_load(); s["resolution"] = mode; s["rate"] = rate; settings_save(s)
                return self._json(200, settings_payload())
            if parts == ["api", "settings", "matchrate"]:
                on = bool(self._body().get("on"))
                s = settings_load(); s["match_rate"] = on; settings_save(s)
                log("Bildrate an Video anpassen:", "an" if on else "aus")
                DISPLAY_RATE.reapply()
                return self._json(200, settings_payload())
            if parts == ["api", "settings", "gamefx"]:
                try:
                    game_fx_set(str(self._body().get("mode")))
                except ValueError as e:
                    return self._json(400, {"error": str(e)})
                return self._json(200, settings_payload())
            if parts == ["api", "display", "video"]:
                b = self._body()
                return self._json(200, DISPLAY_RATE.request(b.get("fps"), str(b.get("src") or "")))
            if parts[:2] == ["api", "audio"] and len(parts) == 3 and parts[2] in ("device", "format", "mic"):
                b = self._body()
                key = str(b.get("key") or "")
                fmt = str(b["format"]) if parts[2] == "format" and b.get("format") is not None else None
                mic = bool(b.get("on")) if parts[2] == "mic" else None
                if parts[2] == "format" and fmt is None:
                    return self._json(400, {"error": "kein Format gewaehlt"})
                if not audio_select(key, fmt=fmt, mic=mic):
                    return self._json(400, {"error": "unbekannter Ausgang"})
                return self._json(200, settings_payload())
            if parts == ["api", "audio", "auto"]:
                s = settings_load(); s["audio_auto"] = bool(self._body().get("on")); settings_save(s)
                return self._json(200, settings_payload())
            if parts == ["api", "net", "prefer"]:
                try:
                    net_mode_set(str(self._body().get("mode", "")))
                except ValueError as e:
                    return self._json(400, {"error": str(e)})
                time.sleep(2)                     # Routen stehen nach reapply erst nach einem Moment
                return self._json(200, settings_payload())
            if parts in (["api", "net", "disconnect"], ["api", "net", "connect"]):
                kind = self._body().get("type")
                if kind not in ("wired", "wifi") or (parts[2] == "connect" and kind != "wired"):
                    return self._json(400, {"error": "unbekannte Verbindungsart"})
                try:
                    (net_connect if parts[2] == "connect" else net_disconnect)(kind)
                except RuntimeError as e:
                    return self._json(502, {"error": str(e)})
                return self._json(200, settings_payload())
            if parts == ["api", "wifi", "connect"]:
                b = self._body()
                if not b.get("ssid"):
                    return self._json(400, {"error": "kein Netz gewaehlt"})
                try:
                    wifi_connect(str(b["ssid"]), str(b.get("password") or ""))
                except RuntimeError as e:
                    return self._json(502, {"error": str(e)})
                return self._json(200, settings_payload())
            if parts[:2] == ["api", "keymap"]:
                return self._keymap_post(parts[2:], self._body())
            if parts == ["api", "emuopts", "set"]:    # Spieleliste: "Optionen"
                b = self._body()
                try:
                    return self._json(200, emu_opts_set(str(b.get("emu", "")), str(b.get("id", "")), b.get("value"),
                                                        str(b.get("game") or "") or None))
                except (ValueError, OSError) as e:
                    return self._json(400, {"error": str(e)})
            if parts[:3] == ["api", "roms", "chd"] and len(parts) == 4:
                b = self._body()
                sys_id = str(b.get("system", ""))
                try:
                    if parts[3] == "start":
                        return self._json(200, {"job": CHD.start(sys_id, b.get("delete") is True)})
                    if parts[3] == "decline":
                        CHD.decline(sys_id)
                    elif parts[3] == "cancel":
                        CHD.cancel()
                    else:
                        return self._send(404)
                    return self._json(200, CHD.status(sys_id))
                except ValueError as e:
                    return self._json(400, {"error": str(e)})
            if parts == ["api", "roms", "launch"]:
                b = self._body()
                sys_id = str(b.get("system", ""))
                filename = str(b.get("file") or b.get("filename") or b.get("path") or "")
                folder = str(b.get("folder") or "") or None
                try:
                    res = ROMS.launch_disc(sys_id, str(b["disc"])) if b.get("disc") else ROMS.launch(sys_id, filename, folder)
                    return self._json(200, {"result": res, "running": APPS.running()})
                except OSError as e:          # Emulator nicht installiert
                    return self._json(400, {"error": f"Emulator nicht gefunden: {e.filename or e}"})
                except (ValueError, RuntimeError) as e:
                    return self._json(400, {"error": str(e)})
            if parts == ["api", "bluetooth", "scan"]:
                BLUETOOTH.start_scan()
                return self._json(200, BLUETOOTH.status())
            if parts == ["api", "bluetooth", "pair"]:
                mac = str(self._body().get("mac", ""))
                if not BLUETOOTH.MAC_RE.match(mac):
                    return self._json(400, {"error": "ungueltige Geraeteadresse"})
                ok, err = BLUETOOTH.pair(mac)
                return self._json(200, {"ok": ok, "error": err, "status": BLUETOOTH.status()})
            if parts == ["api", "bluetooth", "connect"]:
                mac = str(self._body().get("mac", ""))
                if not BLUETOOTH.MAC_RE.match(mac):
                    return self._json(400, {"error": "ungueltige Geraeteadresse"})
                ok, err = BLUETOOTH.connect(mac)
                return self._json(200, {"ok": ok, "error": err, "status": BLUETOOTH.status()})
            if parts == ["api", "bluetooth", "disconnect"]:
                mac = str(self._body().get("mac", ""))
                if not BLUETOOTH.MAC_RE.match(mac):
                    return self._json(400, {"error": "ungueltige Geraeteadresse"})
                ok = BLUETOOTH.disconnect(mac)
                return self._json(200, {"ok": ok, "status": BLUETOOTH.status()})
            if parts == ["api", "bluetooth", "remove"]:
                mac = str(self._body().get("mac", ""))
                if not BLUETOOTH.MAC_RE.match(mac):
                    return self._json(400, {"error": "ungueltige Geraeteadresse"})
                ok = BLUETOOTH.remove(mac)
                return self._json(200, {"ok": ok, "status": BLUETOOTH.status()})
            if parts == ["api", "bluetooth", "rename"]:
                b = self._body()
                mac = str(b.get("mac", ""))
                if not BLUETOOTH.MAC_RE.match(mac):
                    return self._json(400, {"error": "ungueltige Geraeteadresse"})
                ok = BLUETOOTH.rename(mac, b.get("name", ""))
                return self._json(200, {"ok": ok, "status": BLUETOOTH.status()})
            if parts == ["api", "bluetooth", "power"]:
                b = self._body()
                on = b.get("powered") if "powered" in b else b.get("on")
                ok = BLUETOOTH.power(bool(on))
                return self._json(200, {"ok": ok, "status": BLUETOOTH.status()})
            if parts == ["api", "bluetooth", "service"]:
                b = self._body()
                on = (b.get("action") == "start") if "action" in b else bool(b.get("on"))
                subprocess.run(["sudo", "-n", PKG_HELPER, "bluetooth", "on" if on else "off"],
                               capture_output=True, text=True, timeout=30)
                return self._json(200, BLUETOOTH.status())
            if parts[:2] == ["api", "volume"] and len(parts) == 3:
                return self._json(200, volume_set(parts[2]) or {})
            if parts == ["api", "power", "suspend"]:
                if not can_suspend():
                    return self._json(400, {"error": "Standby wird hier nicht unterstuetzt"})
                RADIO.stop()                           # wie beim Fernseher: Ton aus; Programme bleiben offen
                log("Standby")
                # kurz warten, damit die Antwort noch rausgeht und die Oberflaeche den Dialog schliesst
                threading.Timer(0.8, lambda: subprocess.Popen(POWER["suspend"])).start()
                return self._json(200, {"ok": True})
            if parts[:2] == ["api", "power"] and len(parts) == 3 and parts[2] in POWER:
                RADIO.stop()
                APPS.close_all()
                subprocess.Popen(POWER[parts[2]])
                return self._json(200, {"ok": True})
        except YtError as e:
            return self._json(502, {"error": e.reason, "msg": str(e)})
        except Exception as e:  # noqa: BLE001
            log("Fehler:", e)
            return self._json(500, {"error": str(e)})
        self._send(404)

    def do_OPTIONS(self):
        self._send(403)


# ---------------------------------------------------------------------------
#  Bildschirmfotos: F12 (Openbox, rc.xml), Befehl vsshot, Start + Select am Controller
# ---------------------------------------------------------------------------
SHOT_DIR = Path.home() / "share" / "Screenshots"
SHOT_LOCK = threading.Lock()                       # ein Bild nach dem anderen (Tastenwiederholung, zwei Wege zugleich)
_SHOT_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')    # in Windows-Dateinamen verboten (Freigabe per Samba)
# Fenstertitel der Browser enden auf den Programmnamen – der steht schon vorn im Dateinamen
_SHOT_TITLE_TAIL = re.compile(r"\s+[-—–]\s+(Mozilla Firefox|LibreWolf|Chromium|Brave|Google Chrome)\s*$")


def shot_part(text, limit=60):
    """Teil eines Dateinamens: ohne verbotene Zeichen, Leerraum zusammengefasst, hoechstens `limit` Zeichen."""
    t = re.sub(r"\s+", " ", _SHOT_BAD.sub(" ", str(text or ""))).strip()
    return t[:limit].strip().rstrip(". ")


def shot_context():
    """(Programm, Spiel) fuer den Dateinamen. Programm = Name aus dem AppCenter (mGBA, DuckStation, PCSX2 …), sonst
    die Kachel; nichts vorn -> "VoidStation". Spiel = das aus der Spieleliste gestartete (ROMS.playing). Bei Programmen,
    die keine Emulatoren sind (Steam, Browser), der Fenstertitel – bei Steam ist das der Name des Spiels."""
    tid = APPS.front()
    if not tid or not emu_front(tid):
        return "VoidStation", ""
    app = (catalog_app(tid) or {}).get("name") or (find_tile(tid) or {}).get("label") or tid
    app = str(app).split(" + ")[0]                  # "Steam + Proton-GE" -> "Steam"
    game = ROMS.playing(tid)
    emu = tid in ROMS.TILE_TO_SYSTEM or tid in ROMS.SYSTEM_TO_TILE
    if not game and not emu:
        act = active_window()
        title = next((t for w, _, t in windows() if int(w, 16) == act), "") if act else ""
        title = _SHOT_TITLE_TAIL.sub("", title or "").strip()
        game = "" if title.casefold() in (app.casefold(), str(tid).casefold()) else title
    return app, game


def shot_encode(w, h, raw, dest):
    """BGRX-Rohdaten (vsx11.grab_screen) als PNG speichern – ffmpeg ist auf jedem Geraet (Player, Musik)."""
    r = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr0",
                        "-video_size", f"{w}x{h}", "-i", "-", "-frames:v", "1", "-y", str(dest)],
                       input=raw, capture_output=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode(errors="replace").strip()[-300:] or "ffmpeg")


def shot_x11grab(dest):
    """Rueckfall ohne libX11 bzw. bei fremdem Pixelformat: ffmpeg nimmt den Bildschirm selbst auf."""
    r = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "x11grab", "-i", os.environ.get("DISPLAY", ":0"),
                        "-frames:v", "1", "-y", str(dest)], capture_output=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode(errors="replace").strip()[-300:] or "ffmpeg")


def screenshot(how="?"):
    """Ganzen Bildschirm nach share/Screenshots: "<Programm>_<Spiel>_<JJJJ-MM-TT_HH-MM-SS>.png" (ohne Spiel nur
    Programm und Zeit). Erst das Bild holen (Moment des Tastendrucks), dann Namen bilden und speichern; danach kurzer
    Hinweis ueber dem Programm. Rueckgabe (Pfad, Fehlertext)."""
    if not SHOT_LOCK.acquire(blocking=False):
        return None, "busy"
    try:
        t0 = time.monotonic()
        try:
            img = vsx11.grab_screen()
        except Exception as e:  # noqa: BLE001
            log("Bildschirmfoto: XGetImage", e)
            img = None
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        app, game = shot_context()
        base = "_".join(p for p in (shot_part(app) or "VoidStation", shot_part(game)) if p) + "_" + stamp
        SHOT_DIR.mkdir(parents=True, exist_ok=True)
        dest = SHOT_DIR / f"{base}.png"
        n = 2
        while dest.exists():                         # zwei Bilder in derselben Sekunde
            dest = SHOT_DIR / f"{base}-{n}.png"
            n += 1
        tmp = dest.with_name("." + dest.name + ".tmp.png")   # erst fertig, dann sichtbar (Freigabe, Bildbetrachter)
        try:
            if img:
                w, h, raw = img
                shot_encode(w, h, raw, tmp)
            else:
                shot_x11grab(tmp)
            os.replace(tmp, dest)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as e:
            tmp.unlink(missing_ok=True)
            log("Bildschirmfoto fehlgeschlagen:", e)
            OSK_FIELD.notice("shot", ok=False, file="")
            return None, str(e)
        log(f"Bildschirmfoto ({how}, {'XGetImage' if img else 'x11grab'}, {time.monotonic() - t0:.2f} s):", dest.name)
        OSK_FIELD.notice("shot", ok=True, file=dest.name)
        return dest, ""
    finally:
        SHOT_LOCK.release()


# ---------------------------------------------------------------------------
#  Gamepad: Guide-Taste -> Startseite nach vorn
# ---------------------------------------------------------------------------
def gamepad_watcher():
    """Controller-Tasten, die VoidStation selbst auswertet (auch wenn ein Programm vorn ist):
      * Guide/Home: Startseite nach vorn
      * L3 lang halten: Vollbild des Emulators vorn an/aus (emu_toggle_fullscreen)
      * Aktionen aus der Tastenbelegung des Emulators, z. B. mGBA: △ speichern, □ laden (je eine halbe Sekunde
        halten, SAVESTATE_HOLD – Antippen tut nichts), L2/R2 halten = spulen
      * Start + Select zusammen: Bildschirmfoto (screenshot), ausgeloest beim Druck der zweiten Taste, einmal je Druck
    Welche Taste welche Rolle hat, kommt aus pad_roles (SDL, Linux-Codes) und emu_binds. Waehrend die Seite
    "Tastenbelegung" eine Taste abfragt, haelt PadCapture das Geraet exklusiv – dann kommt hier nichts an."""
    try:
        import evdev  # type: ignore
        from evdev import ecodes
        import selectors
    except ImportError:
        log("python3-evdev fehlt, Gamepad-Home-Taste deaktiviert")
        return
    sel = selectors.DefaultSelector()
    known: dict = {}                               # Pfad -> Geraet
    acts = {}                                      # Pfad -> [(Bindung, Aktion)]
    rests = {}                                     # Pfad -> {Achse: (Ruhe, min, max)}
    state: dict = {}                               # (Pfad, Aktion) -> gedrueckt
    stamp = [None]                                 # Stand von emu-pads.json (Aenderung -> neu zuordnen)

    def actions_for(pad, probe):
        roles, src = pad_roles(pad, probe)
        out = [(roles["l3"], "fullscreen")] if roles.get("l3") else []
        out += [(roles[r], "shot:" + r) for r in ("select", "start") if roles.get(r)]
        own = []
        for tile, keys in EMU_KEYS.items():                    # Extras jedes Emulators; ausgeloest nur, wenn er vorn ist
            bmap, custom = emu_binds(tile, pad, roles=roles)
            own += [tile] if custom else []
            out += [(bmap[a], f"{tile}:{a}") for a in keys if bmap.get(a)]
        return out, src + (f" + eigene Tastenbelegung ({', '.join(own)})" if own else "")

    def pads_stamp():
        try:
            return EMU_PADS.stat().st_mtime_ns
        except OSError:
            return 0

    def rescan(force=False):
        pads = {p["path"]: p for p in gamepads()}
        new = [p for p in pads if p not in known or force]
        probe = sdl_probe() if new else []
        for path in evdev.list_devices():
            if path in known and not force:
                continue
            try:
                if path in known:
                    dev = known[path]
                else:
                    dev = evdev.InputDevice(path)
                    if not (path in pads or ecodes.BTN_MODE in dev.capabilities().get(ecodes.EV_KEY, [])):
                        dev.close()
                        continue
                    known[path] = dev
                    sel.register(dev, selectors.EVENT_READ)
                if path in pads:
                    acts[path], src = actions_for(pads[path], probe)
                    rests[path] = {c: (i.value, i.min, i.max) for c, i in dev.capabilities().get(ecodes.EV_ABS, [])}
                    log("Gamepad erkannt:", dev.name, f"[{pads[path]['id']}] Belegung: {src};",
                        ", ".join(f"{a}={binding_label(b)}" for b, a in acts[path]))
                else:
                    acts[path] = [({"key": ecodes.BTN_THUMBL}, "fullscreen")]
                    log("Gamepad erkannt:", dev.name)
            except OSError:
                pass

    def drop(path):
        known.pop(path, None)
        acts.pop(path, None)
        rests.pop(path, None)
        for k in [k for k in state if k[0] == path]:
            if state.pop(k):
                emu_action(k[1], False)

    def fire(path, action, on, ev_time):
        k = (path, action)
        was = state.get(k, False)
        if on == was:
            return
        state[k] = on
        if action.startswith("shot:"):                 # Start + Select: sobald beide gehalten sind
            if on and state.get((path, "shot:select")) and state.get((path, "shot:start")):
                threading.Thread(target=screenshot, args=("Start+Select",), daemon=True).start()
            return
        if action.rpartition(":")[2] in HOLD_ACTIONS:   # erst nach langem Halten (Vollbild, Savestates)
            if on:
                hold_since[k] = ev_time
            else:
                hold_since.pop(k, None)
                done.discard(k)
        else:
            threading.Thread(target=emu_action, args=(action, on), daemon=True).start()

    last_scan = 0.0
    hold_since: dict = {}                          # Halte-Aktionen (HOLD_ACTIONS): seit wann gehalten
    done = set()                                   # langes Halten hat schon ausgeloest (einmal je Druck)
    dev: Any                                       # evdev.InputDevice (key.fileobj)
    while True:
        if time.time() - last_scan > 5:
            st_now = pads_stamp()
            rescan(force=st_now != stamp[0] and stamp[0] is not None)
            stamp[0] = st_now
            last_scan = time.time()
        for key, _ in sel.select(timeout=0.1 if hold_since else 1):
            dev = key.fileobj
            try:
                for ev in dev.read():
                    if ev.type == ecodes.EV_KEY and ev.code == ecodes.BTN_MODE and ev.value == 1:
                        raise_home()
                        continue
                    if ev.type not in (ecodes.EV_KEY, ecodes.EV_ABS):
                        continue
                    for b, action in acts.get(dev.path, []):
                        if ev.type == ecodes.EV_KEY and b.get("key") == ev.code and ev.value in (0, 1):
                            fire(dev.path, action, ev.value == 1, time.monotonic())
                        elif ev.type == ecodes.EV_ABS and "abs" in b and b["abs"] == ev.code:
                            v0, lo, hi = rests.get(dev.path, {}).get(ev.code, (0, 0, 1))
                            fire(dev.path, action, (ev.value - v0) * b["dir"] / ((hi - lo) or 1) > 0.4, time.monotonic())
                        elif ev.type == ecodes.EV_ABS and "hat" in b and \
                                ev.code == (ecodes.ABS_HAT0X if b["hat"] == "x" else ecodes.ABS_HAT0Y):
                            fire(dev.path, action, ev.value * b["dir"] > 0, time.monotonic())
            except OSError:
                sel.unregister(dev)
                drop(dev.path)
        for k, t in list(hold_since.items()):
            if k not in done and time.monotonic() - t >= HOLD_ACTIONS[k[1].rpartition(":")[2]]:
                done.add(k)
                fn, args = (emu_toggle_fullscreen, ()) if k[1] == "fullscreen" else (emu_action, (k[1], True))
                threading.Thread(target=fn, args=args, daemon=True).start()


def app_prefs():
    """Voreinstellungen fuer mitgelieferte Programme (nur Werte, die VoidStation vorgibt)."""
    conf = Path.home() / ".config/gpicview/gpicview.conf"            # Bildbetrachter: schwarzer Hintergrund
    try:
        txt = conf.read_text(encoding="utf-8") if conf.exists() else "[General]\n"
        for k in ("bg", "bg_full"):
            if re.search(rf"^{k}=", txt, re.M):
                txt = re.sub(rf"^{k}=.*$", f"{k}=#000000", txt, flags=re.M)
            else:
                txt = txt.replace("[General]\n", f"[General]\n{k}=#000000\n", 1)
        conf.parent.mkdir(parents=True, exist_ok=True)
        conf.write_text(txt, encoding="utf-8")
    except OSError as e:
        log("gpicview.conf:", e)


def resume_leftovers():
    """Vom vorigen Launcher im Hintergrund angehaltene Programme weiterlaufen lassen (z. B. nach einem Update,
    das den Launcher neu startet) – sonst hingen sie unsichtbar und unerreichbar herum."""
    try:
        pids = json.loads(PAUSED_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    AppManager._kill_all([p for p in pids if isinstance(p, int) and p > 1], signal.SIGCONT)
    log("vom vorigen Start angehalten, laeuft weiter:", pids)
    PAUSED_FILE.unlink(missing_ok=True)


def on_term(sig, _frame):
    """SIGTERM: angehaltene Programme fortsetzen, sonst wie bisher sofort beenden (Radio & Co. laufen weiter)."""
    try:
        APPS.resume_all()
    finally:
        signal.signal(sig, signal.SIG_DFL)
        os.kill(os.getpid(), sig)


def main():
    global BOOT_BUILD
    BOOT_BUILD = vs_version().get("build")
    resume_leftovers()
    signal.signal(signal.SIGTERM, on_term)
    app_prefs()
    s = settings_load()
    apply_appearance(s)
    apply_display(s)
    openbox_rc_sync()
    threading.Thread(target=gamepad_watcher, daemon=True).start()
    threading.Thread(target=resume_watcher, daemon=True).start()
    BLUETOOTH.start()                               # Kopplungs-Agent (BlueZ ueber D-Bus)
    threading.Thread(target=AUDIO_WATCH.run, daemon=True).start()   # neue Kopfhoerer, HDMI-Vorgabe Stereo
    threading.Thread(target=bios_sync, daemon=True).start()         # bios-Ordner je System samt Hinweis
    threading.Thread(target=ime_sync, daemon=True).start()          # Eingabemethode fuer ja/ko/zh (fcitx5)
    threading.Thread(target=PERF.reset, daemon=True).start()        # CPU-Takt: Rest eines abgebrochenen Spiels
    if not LIVE:                                    # im Live-System gibt es keine Updates
        threading.Thread(target=updates_background_check, daemon=True).start()
        threading.Thread(target=kernel_autopurge, daemon=True).start()
        threading.Thread(target=SAVES.watcher, daemon=True).start()   # Spielstaende alle 30 Minuten sichern
        threading.Thread(target=flathub_ensure, daemon=True).start()  # Flathub fuer selbst installierte Flatpaks
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    log(f"laeuft auf http://{HOST}:{PORT}/")
    try:
        httpd.serve_forever()
    finally:
        APPS.resume_all()
        RADIO.stop()


if __name__ == "__main__":
    main()
