#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
VoidStation Launcher
-----------------
Kleiner lokaler Dienst fuer die Kacheloberflaeche:
  * liefert die Startseite (web/, tiles.json) aus
  * startet Programme aus tiles.json (nur diese, keine freien Befehle)
  * mehrere Programme parallel; erneutes Oeffnen holt ein laufendes nach vorn
  * "Home" holt die Startseite nach vorn, ohne etwas zu beenden
  * Radio im Hintergrund (mpv), Sendersuche ueber radio-browser.info, Favoriten
  * Lautstaerke (wpctl)
  * optional: Guide-/Home-Taste am Gamepad (python3-evdev)

Lauscht ausschliesslich auf 127.0.0.1.
"""

import hashlib
import json
import os
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
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = int(os.environ.get("VOIDSTATION_PORT", "8765"))
BASE = Path(__file__).resolve().parent
WEB = BASE / "web"
CONFIG = Path(os.environ.get("VOIDSTATION_CONFIG", BASE / "tiles.json"))
FAVS = BASE / "radio.json"
MPV_SOCK = str(BASE / "mpv.sock")
HOME_TITLE = "VoidStation"                      # <title> der Startseite
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
}


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
#  Fenster (wmctrl)
# ---------------------------------------------------------------------------
def windows():
    """Liste (id, pid, titel) aller Fenster."""
    r = run(["wmctrl", "-lp"])
    out = []
    if r and r.returncode == 0:
        for row in r.stdout.splitlines():
            parts = row.split(None, 4)
            if len(parts) >= 3 and parts[2].isdigit():
                out.append((parts[0], int(parts[2]), parts[4] if len(parts) > 4 else ""))
    return out


def session_pids(sid):
    r = run(["ps", "-e", "-o", "pid=,sid="])
    pids = set()
    if r:
        for row in r.stdout.strip().splitlines():
            p = row.split()
            if len(p) == 2 and p[1] == str(sid):
                pids.add(int(p[0]))
    return pids or {sid}


def raise_home():
    for wid, _pid, title in windows():
        if HOME_TITLE in title:
            run(["wmctrl", "-i", "-a", wid])
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

    def running(self):
        with self.lock:
            for tid in [t for t, p in self.procs.items() if p.poll() is not None]:
                del self.procs[tid]
                self.shown.discard(tid)
            return list(self.procs)

    def starting(self):
        """Laufende Programme, die noch kein Fenster zeigen (z. B. Steam bei der Ersteinrichtung)."""
        running = self.running()
        with self.lock:
            return [t for t in running if t not in self.shown]

    def _get(self, tile_id):
        with self.lock:
            p = self.procs.get(tile_id)
            return p if p and p.poll() is None else None

    def focus(self, tile_id):
        p = self._get(tile_id)
        if not p:
            return False
        pids = session_pids(p.pid)
        wins = [w for w in windows() if w[1] in pids]
        for wid, _, _ in wins:
            run(["wmctrl", "-i", "-a", wid])
        return bool(wins)

    def launch(self, tile):
        tid = tile["id"]
        if self._get(tid):
            log("schon offen, nach vorn:", tid)
            self.focus(tid)
            return "focused"
        cmd = tile.get("cmd")
        if not cmd:
            raise ValueError("Kachel hat keinen Befehl")
        args = expand(cmd if isinstance(cmd, list) else ["sh", "-c", cmd])
        return self.start(tid, args)

    def start(self, tid, args):
        log("starte", tid, args)
        logdir = BASE / "logs"
        logdir.mkdir(exist_ok=True)
        out = open(logdir / f"{tid}.log", "w")   # Ausgaben je Programm, hilft bei Abstuerzen
        if Path(args[0]).name == "firefox":
            firefox_lang(args, ui_lang())
        proc = subprocess.Popen(args, cwd=str(Path.home()), stdin=subprocess.DEVNULL, env=app_env(),
                                stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
        out.close()
        with self.lock:
            self.procs[tid] = proc
            self.shown.discard(tid)
        # Neues Fenster aktiv nach vorn holen (Openbox verhindert sonst u. U. den Fokuswechsel,
        # und das Programm laeuft unsichtbar hinter der Startseite)
        threading.Thread(target=self._bring_up, args=(tid, proc), daemon=True).start()
        return "started"

    def _bring_up(self, tid, proc):
        # Auf das erste Fenster warten: anfangs schnell, danach gemaechlich - Steam braucht
        # bei der Ersteinrichtung mehrere Minuten, bis sich ein Fenster zeigt
        t0 = time.monotonic()
        while time.monotonic() - t0 < 1800:
            time.sleep(0.3 if time.monotonic() - t0 < 12 else 1.0)
            if proc.poll() is not None:
                log(tid, "beendet mit Code", proc.returncode)
                return
            pids = session_pids(proc.pid)
            wins = [w for w in windows() if w[1] in pids and HOME_TITLE not in w[2]]
            if wins:
                with self.lock:
                    self.shown.add(tid)
                log(tid, f"Fenster nach {time.monotonic() - t0:.1f} s")
                time.sleep(0.4)
                for wid, _, _ in wins:
                    run(["wmctrl", "-i", "-a", wid])
                return
        with self.lock:                          # kein Fenster erkennbar -> nicht ewig "startet"
            self.shown.add(tid)

    def close(self, tile_id):
        with self.lock:
            proc = self.procs.pop(tile_id, None)
        if not proc or proc.poll() is not None:
            return
        sid = proc.pid
        pids = session_pids(sid)
        log("schliesse", tile_id, sorted(pids))
        wins = [w for w in windows() if w[1] in pids]
        for wid, _, _ in wins:                 # hoeflich, wie Alt+F4 -> Spielstaende werden gespeichert
            run(["wmctrl", "-i", "-c", wid])
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

    def close_all(self):
        for tid in self.running():
            self.close(tid)


APPS = AppManager()


# ---------------------------------------------------------------------------
#  Radio (mpv im Hintergrund)
# ---------------------------------------------------------------------------
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
        self.stop()
        log("Radio:", station.get("name"), url)
        proc = subprocess.Popen(
            ["mpv", "--no-video", "--no-terminal", "--idle=no", "--cache=yes",
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
DEFAULTS = {"scale": 1.75, "resolution": None, "cursor_theme": "Bibata-Modern-Ice", "cursor_size": 48, "lang": None, "theme": "default-dark",
            "sysupd_days": 90}
SYSUPD_DAYS = (30, 60, 90)                  # Erinnerung an Systemupdates (ohne VoidStation-Update) nach … Tagen
# Sprachen der Oberflaeche (Texte in web/i18n/<id>.json); Anzeige immer in der eigenen Sprache
LANGS = [{"id": "de", "label": "Deutsch"}, {"id": "en", "label": "English"}]
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
    sonst aus LANG der Sitzung (en_US.UTF-8 -> en), sonst Deutsch."""
    ids = {l["id"] for l in LANGS}
    lang = (s or settings_load()).get("lang")
    if lang in ids:
        return lang
    if Path("/etc/voidstation-live").exists() and cmdline_value("voidstation.lang") in ids:
        return cmdline_value("voidstation.lang")
    env = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or ""
    return "en" if env.startswith("en") else "de"


# Sprache fuer gestartete Programme: VLC, PCManFM und andere GTK-/Qt-Programme folgen LANG/LANGUAGE,
# Firefox (YouTube) bekommt Oberflaechen- und Webseiten-Sprache ueber sein Profil
LOCALES = {"de": "de_DE.UTF-8", "en": "en_US.UTF-8"}
LANGUAGE_ENV = {"de": "de_DE:de", "en": "en_US:en"}
FIREFOX_LANG = {"de": ("de", "de-DE, de, en-US, en"), "en": ("en-US", "en-US, en")}
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
    return env


def firefox_lang(args, lang):
    """Firefox mit --profile: intl.locale.requested (Menues) und intl.accept_languages (Webseiten, z. B. YouTube)
    vor jedem Start auf die Sprache der Oberflaeche setzen."""
    try:
        uj = Path(args[args.index("--profile") + 1]) / "user.js"
        old = uj.read_text(encoding="utf-8")
    except (ValueError, IndexError, OSError):
        return
    req, acc = FIREFOX_LANG[lang]
    want = {"intl.locale.requested": req, "intl.accept_languages": acc}
    out, seen = [], set()
    for line in old.splitlines():
        m = re.match(r'\s*user_pref\("([^"]+)"', line)
        if m and m.group(1) in want:
            if m.group(1) in seen:
                continue
            seen.add(m.group(1))
            line = f'user_pref("{m.group(1)}", "{want[m.group(1)]}");'
        out.append(line)
    out += [f'user_pref("{k}", "{v}");' for k, v in want.items() if k not in seen]
    new = "\n".join(out) + "\n"
    if new != old:
        uj.write_text(new, encoding="utf-8")


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


def apply_appearance(s):
    """Skalierung (Xft.dpi) und Mauszeiger fuer neu gestartete Programme setzen."""
    home = Path.home()
    dpi = round(96 * float(s["scale"]))
    theme = s.get("cursor_theme") or DEFAULTS["cursor_theme"]
    if theme not in cursor_themes():
        theme = next(iter(cursor_themes()), "Adwaita")
    size = int(s.get("cursor_size") or DEFAULTS["cursor_size"])
    xres = home / ".Xresources"
    try:
        lines = [l for l in xres.read_text().splitlines() if not l.startswith(("Xft.dpi", "Xcursor."))]
    except OSError:
        lines = []
    lines += [f"Xft.dpi: {dpi}", f"Xcursor.theme: {theme}", f"Xcursor.size: {size}"]
    xres.write_text("\n".join(lines) + "\n")
    run(["xrdb", "-merge", str(xres)])
    for gtk in ("gtk-3.0", "gtk-4.0"):
        _ini_set(home / ".config" / gtk / "settings.ini", "Settings",
                 {"gtk-cursor-theme-name": theme, "gtk-cursor-theme-size": str(size)})
    idx = home / ".icons" / "default" / "index.theme"
    idx.parent.mkdir(parents=True, exist_ok=True)
    idx.write_text(f"[Icon Theme]\nInherits={theme}\n")
    (BASE / "env.sh").write_text(
        f"export XCURSOR_THEME={theme}\nexport XCURSOR_SIZE={size}\n"
        "export QT_STYLE_OVERRIDE=Adwaita-Dark\nexport GTK_THEME=Adwaita:dark\n")
    os.environ.update({"XCURSOR_THEME": theme, "XCURSOR_SIZE": str(size),
                       "QT_STYLE_OVERRIDE": "Adwaita-Dark", "GTK_THEME": "Adwaita:dark"})
    run(["xsetroot", "-cursor_name", "left_ptr"])


def restart_home_later(delay=0.8):
    """Startseite neu starten, z. B. fuer den neuen Mauszeiger oder die andere Oberflaeche (home.sh startet sie neu)."""
    def _go():
        time.sleep(delay)
        run(["pkill", "-f", "voidstation-shell.py|voidstation-home.py|profiles/home"])
    threading.Thread(target=_go, daemon=True).start()


# Oberflaeche der Startseite: "qt" (Python + Qt 6, Standard, auch mit Installer im Live-System)
# oder "web" (WebKit-Shell / Firefox, Rueckfall). home.sh liest die Datei "frontend".
FRONTEND_FILE = BASE / "frontend"


def qt_available():
    try:
        import importlib.util
        return importlib.util.find_spec("PySide6") is not None and (BASE / "qt" / "voidstation-home.py").exists()
    except (ImportError, ValueError):
        return False


def frontends():
    return ["qt", "web"] if qt_available() else ["web"]


def frontend():
    try:
        f = FRONTEND_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        f = "qt"
    return f if f in frontends() else frontends()[0]


def xrandr_info():
    """Angeschlossene Ausgaenge mit Modi und Bildraten (aus xrandr --query)."""
    r = run(["xrandr", "--query"])
    outs = []
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


def _best_rate(rates):
    """Moeglichst 60 Hz (60.00 vor 59.94), sonst die hoechste Rate."""
    if not rates:
        return None
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


def apply_resolution(res):
    for o in xrandr_info():
        mode = res if res in o["modes"] else (None if res else _auto_mode(o))
        if not mode:
            continue
        rate = _best_rate(o["rates"].get(mode, []))
        if mode == o["current"] and (rate is None or o["rate"] == rate):
            continue
        cmd = ["xrandr", "--output", o["name"], "--mode", mode]
        if rate:
            cmd += ["--rate", f"{rate:.2f}"]
        run(cmd)
        log("Aufloesung", o["name"], mode, f"{rate} Hz" if rate else "", "(automatisch)" if not res else "")


def pactl_json(*args):
    r = run(["pactl", "-f", "json", *args])
    if not r or r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


def audio_info():
    cards = pactl_json("list", "cards")
    if cards is None:
        return {"ok": False, "outputs": []}
    outs = []
    for c in cards:
        active = c.get("active_profile")
        for name, prof in (c.get("profiles") or {}).items():
            if not name.startswith("output:") or prof.get("available") is False:
                continue
            desc = prof.get("description") or name
            outs.append({"card": c.get("name"), "profile": name,
                         "label": desc.replace(" Output", "").replace(" Duplex", ""),
                         "active": name == active})
    outs.sort(key=lambda o: (0 if "hdmi" in o["profile"] else 1, o["profile"]))
    return {"ok": True, "outputs": outs}


def audio_set(card, profile):
    run(["pactl", "set-card-profile", card, profile])
    time.sleep(0.6)
    prefix = card.replace("alsa_card.", "alsa_output.")   # alsa_card.pci-... -> alsa_output.pci-...
    for s in pactl_json("list", "sinks") or []:
        if s.get("name", "").startswith(prefix):
            run(["pactl", "set-default-sink", s["name"]])
            run(["pactl", "set-sink-mute", s["name"], "0"])
            break


def net_info():
    r = run(["ip", "-4", "-o", "addr", "show", "scope", "global"])
    addrs = []
    if r:
        for line in r.stdout.splitlines():
            p = line.split()
            if len(p) >= 4:
                addrs.append({"iface": p[1], "ip": p[3].split("/")[0]})
    return {"hostname": socket.gethostname(), "addresses": addrs}


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
    nets = {}
    for line in r.stdout.splitlines():
        use, ssid, sig, sec = (nm_split(line) + ["", "", "", ""])[:4]
        if not ssid:
            continue
        n = {"ssid": ssid, "signal": int(sig or 0), "secure": bool(sec and sec != "--"),
             "active": use.strip() == "*"}
        if ssid not in nets or n["signal"] > nets[ssid]["signal"]:
            nets[ssid] = n
    return sorted(nets.values(), key=lambda n: (-n["active"], -n["signal"]))


def wifi_profiles(ssid):
    """UUIDs aller gespeicherten WLAN-Profile fuer dieses Netz (Name und SSID koennen abweichen)."""
    r = run(["sudo", "-n", "nmcli", "-t", "-f", "UUID,TYPE", "connection", "show"], timeout=10)
    out = []
    if not r or r.returncode != 0:
        return out
    for line in r.stdout.splitlines():
        uuid, typ = (nm_split(line) + ["", ""])[:2]
        if typ not in ("802-11-wireless", "wifi") or not uuid:
            continue
        g = run(["sudo", "-n", "nmcli", "-g", "802-11-wireless.ssid", "connection", "show", uuid], timeout=10)
        if g and g.returncode == 0 and g.stdout.strip() == ssid:
            out.append(uuid)
    return out


def wifi_forget(uuids):
    for u in uuids:
        run(["sudo", "-n", "nmcli", "connection", "delete", "uuid", u], timeout=15)


# nmcli-Meldungen (deutsch oder englisch, je nach Locale) -> Schluessel aus web/i18n
WIFI_ERRORS = [
    ("wifi.err.password", ("secrets were required", "geheimdaten", "wireless-security.psk", "passwd-file",
                           "4-way handshake", "invalid passphrase", "property 'psk' is invalid",
                           "eigenschaft »psk« ist ungültig", "psk: ungültig", "psk: invalid")),
    ("wifi.err.notFound", ("no network with ssid", "kein netzwerk mit ssid")),
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
    """Verbinden. Mit Passwort wird ein altes Profil fuer dasselbe Netz vorher entfernt (sonst nimmt
    NetworkManager dessen gespeichertes, evtl. falsches Passwort); scheitert der Versuch, wird das dabei
    angelegte Profil wieder geloescht. Fehler kommen als Schluessel "wifi.err.*" oder als Klartext."""
    before = wifi_profiles(ssid)
    if password:
        wifi_forget(before)
        before = []
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
IPTV_API = "https://iptv-org.github.io/api/"
CACHE = BASE / "cache"
TVFAVS = BASE / "tvfavs.json"
UA = {"User-Agent": "VoidStation/4.0"}


def fetch(url, dest, max_age):
    """Datei herunterladen, wenn sie fehlt oder aelter als max_age Sekunden ist."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and time.time() - dest.stat().st_mtime < max_age:
        return dest
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        tmp = dest.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(dest)
    except Exception as e:  # noqa: BLE001
        if not dest.exists():
            raise
        log("Verzeichnis veraltet, nutze Cache:", e)
    return dest


class IPTV:
    def __init__(self):
        self.lock = threading.Lock()
        self.state, self.error = "idle", None
        self.index, self.by_key, self.countries = [], {}, []
        self.loaded_at = 0.0
        self.now = None

    def ensure(self):
        with self.lock:
            fresh = self.index and time.time() - self.loaded_at < 86400
            if fresh or self.state == "loading":
                return
            self.state = "loading"
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        try:
            day = 86400
            ch = json.loads(fetch(IPTV_API + "channels.json", CACHE / "channels.json", day).read_text())
            st = json.loads(fetch(IPTV_API + "streams.json", CACHE / "streams.json", day).read_text())
            try:
                lg = json.loads(fetch(IPTV_API + "logos.json", CACHE / "logos.json", 7 * day).read_text())
            except Exception:  # noqa: BLE001
                lg = []
            chans = {c["id"]: c for c in ch if not c.get("is_nsfw") and not c.get("closed")}
            logos = {}
            for l in lg:
                if l.get("channel") and l.get("url") and not l.get("feed"):
                    logos.setdefault(l["channel"], l["url"])
            index, seen, counts = [], set(), {}
            for s in st:
                c = chans.get(s.get("channel"))
                url = s.get("url") or ""
                if not c or not url.startswith(("http://", "https://")):
                    continue
                dedup = (c["id"], s.get("feed"))
                if dedup in seen:
                    continue
                seen.add(dedup)
                key = hashlib.sha1(url.encode()).hexdigest()[:12]
                e = {"key": key, "cid": c["id"], "name": c["name"], "alt": c.get("alt_names") or [],
                     "country": c.get("country") or "", "cats": c.get("categories") or [],
                     "quality": s.get("quality") or "", "logo": logos.get(c["id"], ""),
                     "url": url, "ref": s.get("referrer") or "", "ua": s.get("user_agent") or ""}
                if s.get("feed") and s.get("title") and s.get("title") != c["name"]:
                    e["name"] = s["title"]
                index.append(e)
                counts[e["country"]] = counts.get(e["country"], 0) + 1
            index.sort(key=lambda e: e["name"].lower())
            with self.lock:
                self.index = index
                self.by_key = {e["key"]: e for e in index}
                self.countries = sorted(counts.items(), key=lambda x: -x[1])
                self.loaded_at = time.time()
                self.state, self.error = "ready", None
            log(f"TV-Verzeichnis: {len(index)} Sender")
        except Exception as e:  # noqa: BLE001
            log("TV-Verzeichnis nicht ladbar:", e)
            with self.lock:
                self.state, self.error = ("ready" if self.index else "error"), str(e)

    @staticmethod
    def public(e):
        return {k: e[k] for k in ("key", "cid", "name", "country", "cats", "quality", "logo") if k in e}

    def search(self, q, country, cat, limit=80):
        self.ensure()
        q = (q or "").strip().lower()
        res = []
        for e in self.index:
            if country and e["country"] != country:
                continue
            if cat and cat not in e["cats"]:
                continue
            if q:
                names = [e["name"].lower()] + [a.lower() for a in e["alt"]]
                if not any(q in n for n in names):
                    continue
                rank = 0 if any(n.startswith(q) for n in names) else 1
            else:
                rank = 0
            res.append((rank, e))
            if not q and len(res) >= limit:
                break
        res.sort(key=lambda x: (x[0], x[1]["name"].lower()))
        return [self.public(e) for _, e in res[:limit]]

    def status(self):
        now = None
        if self.now and "tv" in APPS.running():
            now = self.now
        return {"state": self.state, "error": self.error, "count": len(self.index),
                "countries": [{"code": c, "n": n} for c, n in self.countries[:40]], "now": now}

    def entry(self, key):
        e = self.by_key.get(key)
        if e:
            return e
        for f in tvfavs_load():
            if f.get("key") == key:
                return f
        return None

    def play(self, key):
        e = self.entry(key)
        if not e:
            raise ValueError("Sender unbekannt")
        args = ["mpv", "--fs", "--force-window=immediate", "--keep-open=no",
                f"--title=TV · {e['name']}", "--cache=yes", "--demuxer-max-bytes=64MiB"]
        if e.get("ref"):
            args.append(f"--referrer={e['ref']}")
        if e.get("ua"):
            args.append(f"--user-agent={e['ua']}")
        args.append(e["url"])
        APPS.close("tv")
        APPS.start("tv", args)
        self.now = self.public(e)
        return self.status()


def tvfavs_load():
    try:
        return json.loads(TVFAVS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


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
            data = {}
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
    if s["type"] == "xbps":
        return s["pkg"] in pkgs
    if s["type"] == "flatpak":
        return s["ref"] in fps
    if s["type"] == "appimage":
        return (APPDIR / a["id"] / "AppRun").exists()
    if s["type"] == "web":
        return a["id"] in tiles
    return False


def app_installed(a):
    s = a["source"]
    if s["type"] == "xbps":
        r = run(["xbps-query", s["pkg"]])
        return bool(r and r.returncode == 0)
    if s["type"] == "flatpak":
        r = run(["flatpak", "info", "--user", s["ref"]])
        return bool(r and r.returncode == 0)
    if s["type"] == "appimage":
        return (APPDIR / a["id"] / "AppRun").exists()
    if s["type"] == "web":
        return a["id"] in tile_ids()
    return False


def app_cmd(a):
    s = a["source"]
    if s["type"] == "web":
        kiosk = ["--kiosk"] if s.get("kiosk", True) else []      # "kiosk": false -> normaler Browser mit Leisten
        return ["firefox", *kiosk, "--no-remote", "--profile",
                f"~/.local/share/voidstation/profiles/{a['id']}", s["url"]]
    return a["cmd"]


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
    if t.get("sub"):
        tile["sub"] = t["sub"]
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

    def __init__(self):
        self.lock = threading.Lock()
        self.job = None

    def current(self):
        with self.lock:
            return dict(self.job) if self.job else None

    def _log(self, line):
        line = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line).rstrip()
        if not line:
            return
        with self.lock:
            self.job["log"] = (self.job["log"] + [line])[-60:]
            self.job["n"] += 1                       # laufende Zeilennummer (fuer "vsctl update")

    def _run(self, args, cwd=None):
        self._log("$ " + " ".join(args))
        p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             stdin=subprocess.DEVNULL, cwd=cwd, bufsize=1, errors="replace",
                             start_new_session=True)
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
                        "log": [], "n": 0, "started": time.time(), "result": None}
        threading.Thread(target=self._work, args=(action, app), daemon=True).start()

    def _finish(self, ok, result=None, reboot=False):
        with self.lock:
            self.job["state"] = "done" if ok else "error"
            self.job["result"] = result
            self.job["reboot"] = bool(reboot)

    def _selfupdate(self):
        ok = self._run(["sudo", "-n", PKG_HELPER, "selfupdate"]) == 0
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
                elif action == "update":
                    ok, result, reboot = self._update_all()
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
        _sys_check(sync=True, logf=self._log)
        s = dict(_SCACHE)
        vs = vs_update_status(force=True)
        ok, done = True, []
        if s["pkgs"] or s["error"]:
            self._log(f"== Void-Pakete: {len(s['pkgs'])} ==")
            if self._run(["sudo", "-n", PKG_HELPER, "update"]) == 0:
                done.append("system")
            else:
                ok = False
        else:
            self._log("Void-Pakete: aktuell")
        if s["flatpak"] and shutil_which("flatpak"):
            self._log(f"== Flatpak: {len(s['flatpak'])} ==")
            ok = self._run(["flatpak", "update", "--user", "-y", "--noninteractive"]) == 0 and ok
        for app in catalog()["apps"]:
            if app["id"] in s["appimage"]:
                self._log(f"== {app['name']} (AppImage) ==")
                ok = self._appimage(app) and ok
        if s["proton"]:
            self._log(f"== Proton-GE {s['proton']} ==")
            ok = self._proton_ge() and ok
        if vs["available"]:
            self._log(f"== VoidStation {vs['remote']} ==")
            if self._selfupdate():
                done.append("voidstation")
            else:
                ok = False
        else:
            self._log("VoidStation: aktuell")
        self._log("Prüfe Stand …")
        _sys_check(sync=True)
        vs_update_status(force=True)
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
                done, last = 0, 0
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    h.update(chunk)
                    done += len(chunk)
                    if total and done * 10 // total > last:
                        last = done * 10 // total
                        self._log(f"… {last * 10} %")
            if h.hexdigest() != want:
                tmp.unlink(missing_ok=True)
                self._log("Proton-GE: Pruefsumme stimmt nicht – verworfen")
                return False
            self._log("Pruefsumme ok, entpacke …")
            with tarfile.open(tmp) as t:
                tops = sorted({m.name.split("/", 1)[0] for m in t.getmembers() if m.name and not m.name.startswith("/")})
                kw = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
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
        if s["type"] in ("appimage", "web"):
            target = APPDIR / a["id"] if s["type"] == "appimage" else BASE / "profiles" / a["id"]
            shutil.rmtree(target, ignore_errors=True)
            self._log(f"entfernt: {target}")
            return True
        return False

    def _appimage(self, a):
        APPDIR.mkdir(parents=True, exist_ok=True)
        img = APPDIR / f"{a['id']}.AppImage"
        self._log(f"Lade {a['source']['url']}")
        req = urllib.request.Request(a["source"]["url"], headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r, open(img, "wb") as f:
            stamp = asset_stamp(r.headers)
            total = int(r.headers.get("Content-Length") or 0)
            done, last = 0, 0
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total and done * 10 // total > last:
                    last = done * 10 // total
                    self._log(f"… {last * 10} %")
        img.chmod(0o755)
        work = APPDIR / f".{a['id']}-extract"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir()
        # Entpacken statt direkt starten: braucht kein FUSE und startet schneller
        self._log("Entpacke …")
        subprocess.run([str(img), "--appimage-extract"], cwd=str(work),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        root = work / "squashfs-root"
        if not (root / "AppRun").exists():
            self._log("Entpacken fehlgeschlagen")
            return False
        dest = APPDIR / a["id"]
        shutil.rmtree(dest, ignore_errors=True)
        shutil.move(str(root), str(dest))
        shutil.rmtree(work, ignore_errors=True)
        img.unlink(missing_ok=True)
        try:
            appimage_stampfile(a).write_text(stamp)    # Vergleichswert fuer die Update-Pruefung
        except OSError:
            pass
        self._log("installiert nach " + str(dest))
        return True


# ---------------------------------------------------------------------------
#  VoidStation selbst aktualisieren (Quelle: /usr/local/share/voidstation/update-url)
# ---------------------------------------------------------------------------
URLFILE = Path("/usr/local/share/voidstation/update-url")
CHANNELFILE = Path("/usr/local/share/voidstation/channel")
CHANNELS = {"stable": "Stable", "main": "Testing"}
_VCACHE = {"t": 0.0, "remote": None, "error": None, "key": None}


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
    """"0.7.2" -> (0, 7, 2); unbekannt -> None"""
    try:
        return tuple(int(x) for x in str(v).split("."))
    except (TypeError, ValueError):
        return None


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
_SCACHE = {"t": 0.0, "pkgs": [], "flatpak": [], "appimage": [], "proton": None, "error": None,
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
    out = {"kernel": False, "kernel_stuck": None, "voidstation": False}
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


def appimage_outdated(a):
    try:
        req = urllib.request.Request(a["source"]["url"], headers=UA, method="HEAD")
        with urllib.request.urlopen(req, timeout=20) as r:
            remote = asset_stamp(r.headers)
    except Exception:  # noqa: BLE001
        return False
    try:
        local = appimage_stampfile(a).read_text().strip()
    except OSError:
        local = None                                   # vor 0.9.0 installiert: einmal neu laden
    return remote != local


def _sys_check(sync, logf=None):
    """Sucht nach Updates ausser VoidStation selbst. Nur mit SYS_LOCK aufrufen!
    sync=False: nur Void-Pakete gegen die vorhandenen Paketlisten (schnell, ohne Netz)."""
    if LIVE:
        return
    res = {"pkgs": [], "error": None}
    r = run(["sudo", "-n", PKG_HELPER, "check"] + ([] if sync else ["--nosync"]), timeout=300)
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
            f = run(["flatpak", "remote-ls", "--user", "--updates", "--columns=application"], timeout=120)
            if f and f.returncode == 0:
                res["flatpak"] = [x.strip() for x in f.stdout.splitlines() if x.strip()]
        apps = catalog()["apps"]
        for a in apps:
            if a["source"]["type"] == "appimage" and app_installed(a) and appimage_outdated(a):
                res["appimage"].append(a["id"])
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
            "days": days, "due_at": due_at, "due": bool(due_at and time.time() >= due_at)}


def updates_state(force=False):
    """Gesamtstand fuer Einstellungen → Updates: VoidStation + System + Neustart."""
    vs = vs_update_status(force)          # ohne force: nur, wenn der letzte Stand aelter als 10 min ist
    busy = False
    if force and not sys_check(sync=True):
        busy = JOBS.busy() or xbps_busy()
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


def local_apps():
    """Programme mit .desktop-Datei, die weder im Katalog noch als eigene Kachel vorkommen."""
    lang = ui_lang()
    cat = catalog()
    known_bins = {Path(str(a["cmd"][0])).name for a in cat["apps"] if isinstance(a.get("cmd"), list) and a["cmd"]}
    known_bins |= {a["source"].get("pkg") for a in cat["apps"] if a["source"].get("pkg")}
    for a in cat["apps"]:                            # "for b in A B; do …" -> A und B
        m = re.match(r"for b in ([^;]+);", a.get("cmd")) if isinstance(a.get("cmd"), str) else None
        known_bins |= set(m.group(1).split()) if m else set()
    known_bins.discard("flatpak")                    # Flatpaks werden ueber ihre ID erkannt, nicht ueber "flatpak run"
    known_refs = {a["source"]["ref"] for a in cat["apps"] if a["source"].get("ref")}
    tiles = {t.get("id"): t for g in load_config().get("groups", []) for t in g.get("tiles", [])}
    tile_bins = {Path(str(t["cmd"][0])).name for t in tiles.values() if isinstance(t.get("cmd"), list) and t["cmd"]}
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
            binary = Path(args[0]).name
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
                args = ["xterm", "-fa", "DejaVu Sans Mono", "-fs", "14", "-e"] + args
            cats = e.get("Categories", "")
            icon = next((i for k, i in LOCAL_ICONS if k in cats.split(";")), "globe")
            name = e.get(f"Name[{lang}]") or e["Name"]
            desc = e.get(f"Comment[{lang}]") or e.get("Comment") or e.get(f"GenericName[{lang}]") or e.get("GenericName") or ""
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
        item["installed"] = app_installed_in(a, pkgs, fps, tiles)
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


def settings_payload():
    s = settings_load()
    return {"version": vs_version(), "ssh": ssh_state(), "live": LIVE, "lang": ui_lang(s), "langs": LANGS,
            "scale": s["scale"], "scales": SCALES,
            "theme": s.get("theme", "default-dark"), "themes": available_themes(),
            "cursor": {"theme": s.get("cursor_theme"), "size": s.get("cursor_size"),
                       "themes": [{"id": t, "label": CURSOR_NAMES[t]} for t in cursor_themes()],
                       "sizes": CURSOR_SIZES}, "displays": xrandr_info(),
            "audio": audio_info(), "volume": volume_get(), "net": net_info(), "share": share_info(),
            "sysupd_days": sysupd_days(s), "sysupd_choices": SYSUPD_DAYS,
            "frontend": frontend(), "frontends": frontends()}


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
        self.state = None
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
        p["lang"] = ui_lang()
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
                self.state = {"state": "running", "pct": 0, "phase": None, "phases": {}, "detail": None,
                              "started": time.time(), "mode": cfg.get("mode")}
            else:
                self.state = dict(self.state or {"phases": {}, "started": time.time()}, state="running", error=None, detached=False)
            # eigene Sitzung: laeuft auch weiter, wenn die Startseite neu startet
            self.proc = subprocess.Popen(["sudo", "-n", INSTALLER] + args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, text=True, start_new_session=True)
            try:
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
KEYMAPS = {"de": ["de"], "us": ["us"], "gb": ["gb"]}


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
        "retroarch": "retroarch",
    }
    SYSTEM_TO_TILE = {v: k for k, v in TILE_TO_SYSTEM.items()}

    EXTENSIONS = {
        "gba": [".gba", ".gbc", ".gb", ".zip", ".7z"],
        "snes": [".sfc", ".smc", ".zip", ".7z"],
        "nes": [".nes", ".zip", ".7z"],
        "psx": [".iso", ".cue", ".bin", ".chd", ".pbp"],
        "psp": [".iso", ".cso", ".pbp"],
        "nds": [".nds", ".zip"],
        "gamecube": [".iso", ".rvz", ".gcm"],
        "dreamcast": [".cdi", ".gdi", ".chd"],
        "n64": [".z64", ".n64", ".v64"],
        "c64": [".d64", ".t64", ".prg", ".crt"],
        "atari2600": [".a26", ".bin"],
        "megadrive": [".md", ".bin", ".smd", ".gen", ".zip", ".7z"],
        "genesis": [".md", ".bin", ".smd", ".gen", ".zip", ".7z"],
        "scummvm": [".scummvm"],
        "dos": [".conf", ".exe", ".bat"],
    }
    # Befehle aus catalog.json als Basis/Fallback
    EMULATOR_CMD = {
        "gba": ["mgba-qt"],
        "snes": ["snes9x-gtk"],
        "nes": ["nestopia"],
        "psx": ["~/.local/share/voidstation/apps/duckstation/AppRun"],
        "psp": ["PPSSPPSDL", "ppsspp", "PPSSPPQt"],   # erster vorhandener
        "nds": ["melonDS"],
        "dreamcast": ["flatpak", "run", "org.flycast.Flycast"],
        "gamecube": ["dolphin-emu"],
        "megadrive": ["mednafen"],
        "genesis": ["mednafen"],
    }

    def __init__(self):
        self.rom_dir = Path.home() / "share" / "ROMs"

    def canonical_system(self, sys_or_tile):
        return self.TILE_TO_SYSTEM.get(sys_or_tile, sys_or_tile)

    def list_roms(self, system):
        canon = self.canonical_system(system)
        sys_dir = self.rom_dir / canon
        if not sys_dir.is_dir():
            return []
        valid_exts = set(self.EXTENSIONS.get(canon, [".zip"]))
        roms = []
        try:
            for item in sorted(sys_dir.iterdir()):
                if item.is_file() and item.suffix.lower() in valid_exts:
                    name = item.stem
                    clean_name = re.sub(r"\s*[\(\[][^()\[\]]*[\)\]]", "", name).strip() or name
                    size_bytes = item.stat().st_size
                    size_mb = round(size_bytes / (1024 * 1024), 1)
                    size_str = f"{size_mb} MB" if size_mb >= 1 else f"{round(size_bytes / 1024)} KB"
                    roms.append({
                        "id": hashlib.sha1(str(item).encode()).hexdigest()[:10],
                        "name": clean_name,
                        "filename": item.name,
                        "system": canon,
                        "size": size_str,
                        "bytes": size_bytes,
                    })
        except OSError as e:
            log(f"ROMs fuer {canon} nicht lesbar:", e)
        return roms

    def launch(self, system, filename):
        canon = self.canonical_system(system)
        safe_name = os.path.basename(filename)
        sys_dir = (self.rom_dir / canon).resolve()
        target = (sys_dir / safe_name).resolve()

        if not target.is_file() or not target.is_relative_to(sys_dir):
            raise ValueError("Spieldatei nicht gefunden")

        # 1. Kachel-Befehl (tiles.json), 2. Katalog (catalog.json) – nur als Liste;
        #    Shell-Befehle (z. B. PPSSPP: "for b in ...; do exec $b; done") koennen keine Datei uebergeben
        cmd = None
        tid = self.SYSTEM_TO_TILE.get(canon, canon)
        for src in (find_tile(system), find_tile(tid), catalog_app(system), catalog_app(tid)):
            if src and isinstance(src.get("cmd"), list):
                cmd = expand(src["cmd"]) + [str(target)]
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

        return APPS.start(f"rom_{canon}", cmd)


ROMS = ROMManager()
#  Bluetooth: Audio-Kopfhörer und Wireless Gamepads
# ---------------------------------------------------------------------------
class BluetoothManager:
    """Verwaltet Bluetooth-Geräte (Headsets, Gamepads, etc.) über bluetoothctl."""

    def __init__(self):
        self.lock = threading.Lock()
        self._scanning = False

    def is_available(self):
        return bool(shutil.which("bluetoothctl"))

    def is_service_active(self):
        return os.path.exists("/var/service/bluetoothd")

    def is_powered(self):
        r = run(["bluetoothctl", "show"])
        if r and r.returncode == 0:
            for line in r.stdout.splitlines():
                if "Powered: yes" in line:
                    return True
        return False

    def status(self):
        available = self.is_available()
        service = self.is_service_active()
        powered = self.is_powered() if (available and service) else False
        devices = self.list_devices() if powered else []
        return {
            "available": available,
            "service": service,
            "powered": powered,
            "scanning": self._scanning,
            "devices": devices,
        }

    MAC_RE = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$", re.I)

    @staticmethod
    def _named(mac, name):
        # Geraete ohne Namen (bluetoothctl zeigt dann die MAC mit Bindestrichen) nicht anbieten
        return name.replace("-", ":").upper() != mac.upper()

    def list_devices(self):
        devs = {}
        # BlueZ 5: 'devices Paired'
        r = run(["bluetoothctl", "devices", "Paired"])
        if r and r.returncode == 0:
            for line in r.stdout.splitlines():
                parts = line.strip().split(None, 2)
                if len(parts) >= 3 and parts[0] == "Device":
                    mac = parts[1]
                    name = parts[2]
                    devs[mac] = {"mac": mac, "name": name, "paired": True, "connected": False, "icon": "bluetooth"}
        r = run(["bluetoothctl", "devices"])
        if r and r.returncode == 0:
            for line in r.stdout.splitlines():
                parts = line.strip().split(None, 2)
                if len(parts) >= 3 and parts[0] == "Device":
                    mac = parts[1]
                    name = parts[2]
                    if mac not in devs and self._named(mac, name):
                        devs[mac] = {"mac": mac, "name": name, "paired": False, "connected": False, "icon": "bluetooth"}

        for mac, d in list(devs.items())[:25]:
            info = run(["bluetoothctl", "info", mac])
            if info and info.returncode == 0:
                for line in info.stdout.splitlines():
                    line = line.strip()
                    if line.startswith("Connected: yes"):
                        d["connected"] = True
                    elif line.startswith("Icon:"):
                        icon_type = line.split(":", 1)[1].strip()
                        if any(w in icon_type for w in ("audio", "headset", "headphone")):
                            d["icon"] = "audio"
                        elif any(w in icon_type for w in ("gamepad", "joystick", "input-gaming")):
                            d["icon"] = "gamepad"
        return sorted(devs.values(), key=lambda x: (-x["connected"], -x["paired"], x["name"].lower()))

    def start_scan(self):
        with self.lock:
            if self._scanning:
                return
            self._scanning = True

        def _do_scan():
            try:
                run(["bluetoothctl", "--timeout", "10", "scan", "on"], timeout=15)
            finally:
                with self.lock:
                    self._scanning = False

        threading.Thread(target=_do_scan, daemon=True).start()

    def pair(self, mac):
        run(["bluetoothctl", "pair", mac], timeout=20)
        run(["bluetoothctl", "trust", mac], timeout=10)
        r = run(["bluetoothctl", "connect", mac], timeout=20)
        return bool(r and r.returncode == 0)

    def connect(self, mac):
        r = run(["bluetoothctl", "connect", mac], timeout=20)
        return bool(r and r.returncode == 0)

    def disconnect(self, mac):
        r = run(["bluetoothctl", "disconnect", mac], timeout=15)
        return bool(r and r.returncode == 0)

    def remove(self, mac):
        r = run(["bluetoothctl", "remove", mac], timeout=15)
        return bool(r and r.returncode == 0)

    def power(self, on):
        r = run(["bluetoothctl", "power", "on" if on else "off"], timeout=10)
        return bool(r and r.returncode == 0)


BLUETOOTH = BluetoothManager()


# ---------------------------------------------------------------------------
#  HTTP
# ---------------------------------------------------------------------------
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
        self.wfile.write(body)

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

    def do_GET(self):
        if not self._host_ok():
            return self._send(403)
        url = urllib.parse.urlparse(self.path)
        path = url.path
        if path == "/api/status":
            running = APPS.running()
            return self._json(200, {"running": running, "starting": APPS.starting(), "radio": RADIO.status(),
                                    "update": updates_badge() if not LIVE else {"available": False},
                                    "tv": TV.now if "tv" in running else None, "live": LIVE,
                                    "install": INSTALL.state.get("state") if INSTALL.state else None})
        if path == "/api/tv/status":
            TV.ensure()
            return self._json(200, TV.status())
        if path == "/api/tv/search":
            qs = urllib.parse.parse_qs(url.query)
            g = lambda k: qs.get(k, [""])[0]
            return self._json(200, TV.search(g("q"), g("country"), g("cat")))
        if path == "/api/tv/favs":
            return self._json(200, [IPTV.public(f) for f in tvfavs_load()])
        if path == "/api/tv/epg":
            qs = urllib.parse.parse_qs(url.query)
            ch_id = qs.get("id", [""])[0] or qs.get("channel_id", [""])[0]
            ch_name = qs.get("name", [""])[0] or qs.get("channel_name", [""])[0] or ch_id
            return self._json(200, EPG.get_program(ch_id, ch_name) or {})
        if path == "/api/apps":
            return self._json(200, apps_payload())
        if path in ("/api/updates", "/api/selfupdate"):
            force = urllib.parse.parse_qs(url.query).get("force", [""])[0] == "1"
            return self._json(200, updates_state(force))
        if path == "/api/apps/job":
            return self._json(200, JOBS.current() or {})
        if path == "/api/radio/favs":
            return self._json(200, favs_load())
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
                    r = ROMS.list_roms(s)
                    if r:
                        summary[s] = len(r)
                return self._json(200, {"systems": summary})
            roms = ROMS.list_roms(system)
            return self._json(200, {"system": ROMS.canonical_system(system), "count": len(roms), "roms": roms})
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
        if path == "/":
            path = "/index.html"
        target = (WEB / path.lstrip("/")).resolve()
        if WEB.resolve() not in target.parents or not target.is_file():
            return self._send(404)
        self._send(200, target.read_bytes(), MIME.get(target.suffix, "application/octet-stream"))

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
                return self._json(200, TV.play(str(self._body().get("key", ""))))
            if parts == ["api", "tv", "stop"]:
                APPS.close("tv")
                TV.now = None
                return self._json(200, TV.status())
            if parts[:2] == ["api", "tv"] and parts[2:] in (["fav"], ["unfav"]):
                key = str(self._body().get("key", ""))
                favs = [f for f in tvfavs_load() if f.get("key") != key]
                if parts[2] == "fav":
                    e = TV.entry(key)
                    if not e:
                        return self._json(404, {"error": "Sender unbekannt"})
                    favs.append(e)
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
                ch = str(self._body().get("channel", ""))
                if ch not in CHANNELS:
                    return self._json(400, {"error": "unbekannter Kanal"})
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
                return self._json(200, settings_payload())
            if parts == ["api", "settings", "frontend"]:
                fe = str(self._body().get("frontend", ""))
                if fe not in frontends():
                    return self._json(400, {"error": "unbekannte Oberflaeche"})
                FRONTEND_FILE.write_text(fe + "\n", encoding="utf-8")
                log("Oberflaeche:", fe)
                restart_home_later(0.6)
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
                res = str(self._body().get("mode", ""))
                if not any(res in o["modes"] for o in xrandr_info()):
                    return self._json(400, {"error": "Aufloesung nicht verfuegbar"})
                apply_resolution(res)
                s = settings_load(); s["resolution"] = res; settings_save(s)
                return self._json(200, settings_payload())
            if parts == ["api", "audio", "output"]:
                b = self._body()
                valid = {(o["card"], o["profile"]) for o in audio_info()["outputs"]}
                if (b.get("card"), b.get("profile")) not in valid:
                    return self._json(400, {"error": "unbekannter Ausgang"})
                audio_set(b["card"], b["profile"])
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
            if parts == ["api", "roms", "launch"]:
                b = self._body()
                sys_id = str(b.get("system", ""))
                filename = str(b.get("file") or b.get("filename") or b.get("path") or "")
                try:
                    res = ROMS.launch(sys_id, filename)
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
                ok = BLUETOOTH.pair(mac)
                return self._json(200, {"ok": ok, "status": BLUETOOTH.status()})
            if parts == ["api", "bluetooth", "connect"]:
                mac = str(self._body().get("mac", ""))
                if not BLUETOOTH.MAC_RE.match(mac):
                    return self._json(400, {"error": "ungueltige Geraeteadresse"})
                ok = BLUETOOTH.connect(mac)
                return self._json(200, {"ok": ok, "status": BLUETOOTH.status()})
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
            if parts[:2] == ["api", "power"] and len(parts) == 3 and parts[2] in POWER:
                RADIO.stop()
                APPS.close_all()
                subprocess.Popen(POWER[parts[2]])
                return self._json(200, {"ok": True})
        except Exception as e:  # noqa: BLE001
            log("Fehler:", e)
            return self._json(500, {"error": str(e)})
        self._send(404)

    def do_OPTIONS(self):
        self._send(403)


# ---------------------------------------------------------------------------
#  Gamepad: Guide-Taste -> Startseite nach vorn
# ---------------------------------------------------------------------------
def gamepad_watcher():
    try:
        import evdev  # type: ignore
        from evdev import ecodes
        import selectors
    except ImportError:
        log("python3-evdev fehlt, Gamepad-Home-Taste deaktiviert")
        return
    sel = selectors.DefaultSelector()
    known = {}

    def rescan():
        for path in evdev.list_devices():
            if path in known:
                continue
            try:
                dev = evdev.InputDevice(path)
                if ecodes.BTN_MODE in dev.capabilities().get(ecodes.EV_KEY, []):
                    known[path] = dev
                    sel.register(dev, selectors.EVENT_READ)
                    log("Gamepad erkannt:", dev.name)
                else:
                    dev.close()
            except OSError:
                pass

    last_scan = 0.0
    while True:
        if time.time() - last_scan > 5:
            rescan()
            last_scan = time.time()
        for key, _ in sel.select(timeout=1):
            dev = key.fileobj
            try:
                for ev in dev.read():
                    if ev.type == ecodes.EV_KEY and ev.code == ecodes.BTN_MODE and ev.value == 1:
                        raise_home()
            except OSError:
                sel.unregister(dev)
                known.pop(dev.path, None)


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


def main():
    global BOOT_BUILD
    BOOT_BUILD = vs_version().get("build")
    app_prefs()
    s = settings_load()
    apply_appearance(s)
    apply_resolution(s.get("resolution"))
    threading.Thread(target=gamepad_watcher, daemon=True).start()
    if not LIVE:                                    # im Live-System gibt es keine Updates
        threading.Thread(target=updates_background_check, daemon=True).start()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    log(f"laeuft auf http://{HOST}:{PORT}/")
    try:
        httpd.serve_forever()
    finally:
        RADIO.stop()


if __name__ == "__main__":
    main()
