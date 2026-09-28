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


def run(args, **kw):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=5, **kw)
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
        proc = subprocess.Popen(args, cwd=str(Path.home()), stdin=subprocess.DEVNULL,
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
DEFAULTS = {"scale": 1.75, "resolution": None, "cursor_theme": "Bibata-Modern-Ice", "cursor_size": 48}
CURSOR_SIZES = [32, 48, 64, 80, 96]
CURSOR_NAMES = {"Bibata-Modern-Ice": "Hell", "Bibata-Modern-Classic": "Dunkel", "Adwaita": "Adwaita"}
SCALES = [1.0, 1.25, 1.5, 1.75, 2.0, 2.25]


def settings_load():
    s = dict(DEFAULTS)
    try:
        s.update(json.loads(SETTINGS.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return s


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
    """Startseite neu starten, damit sie den neuen Mauszeiger uebernimmt (home.sh startet sie neu)."""
    def _go():
        time.sleep(delay)
        run(["pkill", "-f", "voidstation-shell.py|profiles/home"])
    threading.Thread(target=_go, daemon=True).start()


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
    r = run(["sudo", "-n", "nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY",
             "device", "wifi", "list", "--rescan", "yes"])
    if not r or r.returncode != 0:
        raise RuntimeError((r.stderr.strip() if r else "") or "nmcli nicht verfuegbar")
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


def wifi_connect(ssid, password):
    args = ["sudo", "-n", "nmcli", "device", "wifi", "connect", ssid]
    if password:
        args += ["password", password]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=45)
    except subprocess.TimeoutExpired:
        raise RuntimeError("Zeitueberschreitung beim Verbinden")
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip() or "Verbindung fehlgeschlagen")


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
                e = {"key": key, "name": c["name"], "alt": c.get("alt_names") or [],
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
        return {k: e[k] for k in ("key", "name", "country", "cats", "quality", "logo")}

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
    if a["source"]["type"] == "web":
        return ["firefox", "--kiosk", "--no-remote", "--profile",
                f"~/.local/share/voidstation/profiles/{a['id']}", a["source"]["url"]]
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

    def _run(self, args, cwd=None):
        self._log("$ " + " ".join(args))
        p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             stdin=subprocess.DEVNULL, cwd=cwd, bufsize=1, errors="replace",
                             start_new_session=True)
        for line in p.stdout:
            for part in line.replace("\r", "\n").split("\n"):
                self._log(part)
        return p.wait()

    def start(self, action, app=None):
        with self.lock:
            if self.job and self.job["state"] == "running":
                raise RuntimeError("Es läuft schon ein Auftrag")
            name = app["name"] if app else ("VoidStation" if action == "selfupdate" else "System")
            self.job = {"action": action, "app": app["id"] if app else None,
                        "name": name, "state": "running", "reboot": False,
                        "log": [], "started": time.time(), "result": None}
        threading.Thread(target=self._work, args=(action, app), daemon=True).start()

    def _finish(self, ok, result=None, reboot=False):
        with self.lock:
            self.job["state"] = "done" if ok else "error"
            self.job["result"] = result
            self.job["reboot"] = bool(reboot)

    def _selfupdate(self):
        self._log("VoidStation wird aktualisiert …")
        ok = self._run(["sudo", "-n", PKG_HELPER, "selfupdate"]) == 0
        _VCACHE["t"] = 0.0
        return ok

    def _work(self, action, a):
        try:
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
                ok = self._run(["sudo", "-n", PKG_HELPER, "update"]) == 0
                if shutil_which("flatpak"):
                    self._run(["flatpak", "update", "--user", "-y", "--noninteractive"])
                for app in catalog()["apps"]:
                    if app["source"]["type"] == "appimage" and app_installed(app):
                        self._appimage(app)
                    if "proton-ge" in app["source"].get("addons", []) and app_installed(app):
                        self._proton_ge()
                reboot = False
                if vs_update_status(force=True)["available"]:
                    reboot = self._selfupdate()
                    ok = ok and reboot
                self._finish(ok, "Neustart empfohlen, falls der Kernel aktualisiert wurde" if ok else None, reboot)
            elif action == "selfupdate":
                ok = self._selfupdate()
                self._finish(ok, None, ok)
            elif action == "check":
                self._log("Suche nach Updates …")
                r = subprocess.run(["sudo", "-n", PKG_HELPER, "check"], capture_output=True, text=True, timeout=300)
                lines = [l for l in r.stdout.splitlines() if l.strip()]
                for l in lines[:40]:
                    self._log(l)
                n = len(lines)
                if shutil_which("flatpak"):
                    f = run(["flatpak", "remote-ls", "--user", "--updates", "--columns=application"])
                    if f and f.returncode == 0:
                        n += len([l for l in f.stdout.splitlines() if l.strip()])
                if any("proton-ge" in a["source"].get("addons", []) and app_installed(a) for a in catalog()["apps"]):
                    try:
                        tag = proton_latest()["tag_name"]
                        if tag not in proton_installed():
                            self._log(f"Proton-GE: neue Version {tag}")
                            n += 1
                    except Exception as e:  # noqa: BLE001
                        self._log(f"Proton-GE: {e}")
                vs = vs_update_status(force=True)
                if vs["available"]:
                    self._log(f"VoidStation: neue Version {vs['remote']} (installiert: {vs['local']})")
                    n += 1
                self._finish(r.returncode == 0, {"updates": n, "voidstation": vs["available"]})
        except Exception as e:  # noqa: BLE001
            self._log(f"Fehler: {e}")
            self._finish(False)

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
                    self._log(f"Hinweis: Erweiterung {ext} fehlt – spaeter ueber 'Alles aktualisieren' nachholen")
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
                self._log("Hinweis: Proton-GE spaeter ueber 'Alles aktualisieren' nachholen")
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
        self._log("installiert nach " + str(dest))
        return True


# ---------------------------------------------------------------------------
#  VoidStation selbst aktualisieren (Quelle: /usr/local/share/voidstation/update-url)
# ---------------------------------------------------------------------------
URLFILE = Path("/usr/local/share/voidstation/update-url")
CHANNELFILE = Path("/usr/local/share/voidstation/channel")
CHANNELS = {"stable": "Stabil", "main": "Test"}
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
    if base and (force or time.time() - _VCACHE["t"] > 600 or _VCACHE["key"] != base):
        try:
            _VCACHE.update(remote=_fetch_remote(base), error=None)
        except Exception as e:  # noqa: BLE001
            _VCACHE.update(error=str(e))
            if _VCACHE["key"] != base:
                _VCACHE["remote"] = None
        _VCACHE.update(t=time.time(), key=base)
    return vs_state()


def vs_state():
    """Stand aus dem Zwischenspeicher, ohne Netzwerk (fuer /api/status)."""
    local, remote = vs_version(), _VCACHE["remote"]
    available = bool(remote and remote.get("build") and remote["build"] != local.get("build"))
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
            "channel": ch, "channel_label": CHANNELS[ch], "checked": _VCACHE["t"] or None}


def vs_background_check():
    """Prueft kurz nach dem Start und dann alle 6 Stunden auf Updates."""
    time.sleep(90)
    while True:
        try:
            st = vs_update_status(force=True)
            log("Update-Pruefung:", "verfuegbar " + str(st["remote"]) if st["available"] else "aktuell",
                f"(Kanal {st['channel']})", st["error"] or "")
        except Exception as e:  # noqa: BLE001
            log("Update-Pruefung fehlgeschlagen:", e)
        time.sleep(6 * 3600)


def shutil_which(name):
    return shutil.which(name)


JOBS = Jobs()


def apps_payload():
    cat = catalog()
    apps = []
    for a in cat["apps"]:
        item = {k: a[k] for k in ("id", "name", "desc", "cat")}
        item["type"] = a["source"]["type"]
        item["installed"] = app_installed(a)
        item["icon"] = a.get("tile", {}).get("icon", "globe")
        item["color"] = a.get("tile", {}).get("color", "#2f3238")
        apps.append(item)
    return {"categories": cat["categories"], "apps": apps, "job": JOBS.current()}


def settings_payload():
    s = settings_load()
    return {"version": vs_version(), "scale": s["scale"], "scales": SCALES,
            "cursor": {"theme": s.get("cursor_theme"), "size": s.get("cursor_size"),
                       "themes": [{"id": t, "label": CURSOR_NAMES[t]} for t in cursor_themes()],
                       "sizes": CURSOR_SIZES}, "displays": xrandr_info(),
            "audio": audio_info(), "volume": volume_get(), "net": net_info(), "share": share_info()}


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
            vs = vs_state()
            return self._json(200, {"running": running, "starting": APPS.starting(), "radio": RADIO.status(),
                                    "update": {"available": vs["available"], "version": vs["remote"]},
                                    "tv": TV.now if "tv" in running else None})
        if path == "/api/tv/status":
            TV.ensure()
            return self._json(200, TV.status())
        if path == "/api/tv/search":
            qs = urllib.parse.parse_qs(url.query)
            g = lambda k: qs.get(k, [""])[0]
            return self._json(200, TV.search(g("q"), g("country"), g("cat")))
        if path == "/api/tv/favs":
            return self._json(200, [IPTV.public(f) for f in tvfavs_load()])
        if path == "/api/apps":
            return self._json(200, apps_payload())
        if path == "/api/selfupdate":
            force = urllib.parse.parse_qs(url.query).get("force", [""])[0] == "1"
            return self._json(200, vs_update_status(force))
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
        if path == "/api/wifi/scan":
            try:
                return self._json(200, wifi_scan())
            except RuntimeError as e:
                return self._json(502, {"error": str(e)})
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
            if parts == ["api", "selfupdate", "channel"]:
                ch = str(self._body().get("channel", ""))
                if ch not in CHANNELS:
                    return self._json(400, {"error": "unbekannter Kanal"})
                r = subprocess.run(["sudo", "-n", PKG_HELPER, "channel", ch], capture_output=True, text=True, timeout=20)
                if r.returncode != 0:
                    return self._json(500, {"error": (r.stdout + r.stderr).strip() or "fehlgeschlagen"})
                return self._json(200, vs_update_status(force=True))
            if parts[:2] == ["api", "apps"] and len(parts) == 3:
                act = parts[2]
                try:
                    if act in ("install", "remove"):
                        a = catalog_app(str(self._body().get("id", "")))
                        if not a:
                            return self._json(404, {"error": "unbekannte App"})
                        JOBS.start(act, a)
                    elif act in ("update", "check", "selfupdate"):
                        JOBS.start(act)
                    else:
                        return self._send(404)
                except RuntimeError as e:
                    return self._json(409, {"error": str(e)})
                return self._json(200, JOBS.current())
            if parts == ["api", "settings", "scale"]:
                val = float(self._body().get("scale", 1.75))
                if val not in SCALES:
                    return self._json(400, {"error": "ungueltige Skalierung"})
                s = settings_load(); s["scale"] = val; settings_save(s)
                apply_appearance(s)
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


def main():
    s = settings_load()
    apply_appearance(s)
    apply_resolution(s.get("resolution"))
    threading.Thread(target=gamepad_watcher, daemon=True).start()
    threading.Thread(target=vs_background_check, daemon=True).start()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    log(f"laeuft auf http://{HOST}:{PORT}/")
    try:
        httpd.serve_forever()
    finally:
        RADIO.stop()


if __name__ == "__main__":
    main()
