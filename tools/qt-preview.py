#!/usr/bin/env python3
"""
Qt-Startseite ohne Void-Geraet ausprobieren: Beispieldaten wie tools/screenshots.py, eigener Port 8766.
Benoetigt: pip install PySide6-Essentials (gleiche Version wie python3-pyside6 in Void)
Aufruf:    python3 tools/qt-preview.py                         -> Fenster 1280×720 auf dem Bildschirm
           python3 tools/qt-preview.py --size 1920x1080
           python3 tools/qt-preview.py --shot out.png --keys "right,a,shot:radio.png,b"   (ohne Bildschirm)
           VS_LANG=en …                                        -> englische Oberflaeche
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import screenshots as S  # noqa: E402  (Beispieldaten und Web-Auslieferung)

PORT = 8766
STATE = {"running": ["youtube"], "radio": S.RADIO_NOW, "tv": None, "favs": list(S.RADIO_FAVS), "tvfavs": list(S.TV_FAVS),
         "volume": dict(S.SETTINGS["volume"]), "bt_powered": True, "update": {"available": True, "version": "0.13.0"}}
STATIONS = [{"name": f"Testsender {i}", "url": f"https://example.invalid/s{i}", "favicon": ""} for i in range(1, 15)]
ROMS = [{"title": n, "name": n, "filename": n.lower().replace(" ", "-") + ".gba", "size": "8 MB"} for n in
        ("Advance Wars", "Golden Sun", "Metroid Fusion", "Pokémon Smaragd", "Mario Kart", "Zelda Minish Cap", "F-Zero")]


TILES = json.loads(json.dumps(S.TILES))
TILES["groups"].insert(1, {"name": "Spiele", "tiles": [
    {"id": "gba", "label": "Game Boy Advance", "sub": "mGBA", "size": "wide", "color": "#2d3763", "icon": "handheld", "cmd": ["mgba-qt"]}]})


JOB = {}


def job():
    if JOB.get("state") == "running":
        JOB["n"] = JOB.get("n", 0) + 1
        JOB["log"].append(f"Schritt {JOB['n']} …")
        if JOB["n"] >= 4:
            JOB["state"] = "done"
    return JOB


def settings():
    return dict(S.SETTINGS, volume=STATE["volume"], version={"version": "0.12.1", "build": "abc123"}, ssh=True, live=LIVE["on"],
                sysupd_days=90, sysupd_choices=[30, 60, 90], frontend=STATE.get("frontend", "qt"), frontends=["qt", "web"])


# Installer (--live): Geraet wie im Web-Installer (DEMO_PROBE), Installation laeuft simuliert in ~20 s durch
GiB = 1024 ** 3
PROBE = {"uefi": True, "secureboot": False, "arch": "x86_64", "ram": 3.7 * GiB, "cpu": "Intel Core i3-6100T", "gpu": ["Intel HD Graphics 530"],
         "net": "lan", "screen": {"mode": "1280x720", "rate": 60}, "favs": {"radio": 2, "tv": 1}, "wifi_saved": ["Zuhause-5G"],
         "windows": False, "lang": "de", "users": [],
         "disks": [
             {"path": "/dev/sda", "size": 128e9, "model": "Samsung SSD MZ7TE128", "tran": "sata", "label": "gpt", "esp": "/dev/sda1",
              "systems": ["Ubuntu 24.04 LTS"],
              "parts": [{"path": "/dev/sda1", "start": 2048, "sectors": 1048576, "size": 536870912, "fstype": "vfat", "role": "esp"},
                        {"path": "/dev/sda2", "start": 1050624, "sectors": 243000000, "size": 124416000000, "fstype": "ext4", "role": "os",
                         "os": "Ubuntu 24.04 LTS"},
                        {"path": "/dev/sda3", "start": 244050624, "sectors": 4000000, "size": 2048000000, "fstype": "swap", "role": "swap"}],
              "free": [], "options": {"whole": True, "beside": [{"part": "/dev/sda2", "os": "Ubuntu 24.04 LTS", "fstype": "ext4",
                                                               "size": 124416000000, "used": 41e9, "min": 40e9, "max_new": 78e9,
                                                               "default": 59 * GiB}]}},
             {"path": "/dev/nvme0n1", "size": 500e9, "model": "Crucial P3", "tran": "nvme", "label": "gpt", "esp": "/dev/nvme0n1p1",
              "systems": ["FreeBSD"],
              "parts": [{"path": "/dev/nvme0n1p1", "start": 2048, "sectors": 532480, "size": 272629760, "fstype": "vfat", "role": "esp"},
                        {"path": "/dev/nvme0n1p2", "start": 534528, "sectors": 777000000, "size": 397824000000, "fstype": "zfs_member",
                         "role": "os", "os": "FreeBSD", "locked": True}],
              "free": [{"start": 777534528, "sectors": 199000000, "bytes": 101888000000}],
              "options": {"whole": True, "free": [{"start": 777534528, "sectors": 199000000, "bytes": 101888000000}]}}]}
INST = {"state": "idle"}
LIVE = {"on": False, "fail": False}


def inst_status():
    st = INST
    if st.get("state") == "running":
        t = time.time() - st["t0"]
        order = ["check", "partition", "format", "copy", "configure", "boot", "cleanup"]
        dur = [1, 1, 1, 10, 3, 2, 1]
        acc, cur = 0, None
        for ph, d in zip(order, dur):
            if t >= acc + d:
                st["phases"][ph] = "done"
            elif cur is None:
                st["phases"][ph] = "running"
                cur = ph
                st["phase"], st["phase_pct"] = ph, (t - acc) / d * 100
                if ph == "copy":
                    st["copy"] = {"done": 1.4e9 * (t - acc) / d, "total": 1.4e9, "eta": int((d - (t - acc)) * 20)}
                if LIVE["fail"] and ph == "boot":
                    st.update(state="error", error={"phase": "boot", "code": "efi_nvram", "msg": "efibootmgr: Could not prepare Boot variable",
                                                    "done": [p for p in order if st["phases"].get(p) == "done"], "alt": True})
                    st["phases"][ph] = "error"
                    return st
            acc += d
        st["pct"] = min(100, t / sum(dur) * 100)
        if cur is None:
            st.update(state="done", pct=100, result={"user": st["cfg"]["user"]["name"], "login": st["cfg"]["user"]["login"],
                                                    "hostname": st["cfg"]["hostname"], "seconds": int(t)})
    return st


class H(S.H):
    def do_GET(self):
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)
        st = STATE
        routes = {
            "/tiles.json": lambda: TILES,
            "/api/status": lambda: {"running": st["running"], "starting": [], "radio": st["radio"], "tv": st["tv"],
                                    "update": st["update"] if not LIVE["on"] else {"available": False}, "live": LIVE["on"]},
            "/api/volume": lambda: st["volume"],
            "/api/settings": settings,
            "/api/radio/favs": lambda: st["favs"],
            "/api/radio/search": lambda: STATIONS,
            "/api/tv/status": lambda: {"state": "ready", "error": None, "count": 10432, "countries": S.COUNTRIES, "now": st["tv"]},
            "/api/tv/favs": lambda: st["tvfavs"],
            "/api/tv/search": lambda: [c for c in S.TV if not q.get("cat", [""])[0] or q["cat"][0] in c["cats"]],
            "/api/tv/epg": lambda: {"current": {"title": "Tagesschau", "start": "20:00", "stop": "20:15", "progress": 60},
                                    "next": {"title": "Wetter"}},
            "/api/apps": S.apps,
            "/api/apps/job": job,
            "/api/updates": lambda: {"local": "0.12.1", "remote": "0.13.0", "available": True, "any": True, "channel": "stable",
                                     "channel_label": "Stable", "changes": [{"version": "0.13.0", "changes": ["Neue Qt-Startseite"],
                                                                              "changes_en": ["New Qt start page"]}],
                                     "system": {"count": 12, "pkgs": ["linux6.18", "mesa"], "kernel": "6.18.45_1", "flatpak": 0,
                                                "appimage": [], "proton": None, "checked": True, "due": False, "due_at": 0},
                                     "reboot": {}},
            "/api/bluetooth/status": lambda: {"available": True, "service": True, "powered": st["bt_powered"], "scanning": False,
                                              "devices": [{"mac": "11:22:33:44:55:66", "name": "Xbox Wireless Controller",
                                                           "paired": True, "connected": True},
                                                          {"mac": "AA:BB:CC:DD:EE:FF", "name": "JBL Flip 5", "paired": False}]},
            "/api/wifi/scan": lambda: [{"ssid": "FRITZ!Box 7530", "signal": 72, "secure": True, "active": True},
                                       {"ssid": "Nachbar", "signal": 31, "secure": True, "active": False}],
            "/api/roms": lambda: {"system": q.get("system", ["gba"])[0], "count": len(ROMS), "roms": ROMS},
            "/api/install/probe": lambda: PROBE,
            "/api/install/status": lambda: dict(inst_status(), autostart=LIVE["on"] and INST.get("state") == "idle" and not INST.get("seen")),
            "/api/install/gparted": lambda: {"running": False},
            "/api/install/log": lambda: {"log": "[check] ok\n[partition] sgdisk …\n[boot] efibootmgr: Could not prepare Boot variable"},
        }
        if p in routes:
            return self.j(routes[p]())
        return super().do_GET()

    def do_POST(self):
        p = urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        st = STATE
        if p.startswith("/api/volume/"):
            a = p.rsplit("/", 1)[1]
            v = st["volume"]
            v["level"] = max(0, min(100, v["level"] + (5 if a == "up" else -5 if a == "down" else 0)))
            if a == "mute":
                v["muted"] = not v.get("muted")
            return self.j(v)
        if p == "/api/radio/play":
            st["radio"] = {"station": body, "title": None}
            return self.j(st["radio"])
        if p == "/api/radio/stop":
            st["radio"] = {}
            return self.j({})
        if p in ("/api/radio/fav", "/api/radio/unfav"):
            st["favs"] = [f for f in st["favs"] if f["url"] != body.get("url")] + ([body] if p.endswith("/fav") else [])
            return self.j(st["favs"])
        if p == "/api/tv/play":
            ch = next((c for c in S.TV if c["key"] == body.get("key")), None)
            st["tv"] = ch
            return self.j({"now": ch})
        if p in ("/api/apps/install", "/api/apps/remove", "/api/apps/update"):
            JOB.clear()
            JOB.update({"state": "running", "action": p.rsplit("/", 1)[1], "name": body.get("id", ""), "app": body.get("id"),
                        "log": ["xbps-install -Sy …"], "n": 0})
            return self.j(JOB)
        if p == "/api/install/start":
            INST.clear()
            INST.update({"state": "running", "pct": 0, "phases": {}, "mode": body["config"]["mode"], "t0": time.time(), "cfg": body["config"]})
            print("Installer-Konfiguration:", json.dumps(body["config"], ensure_ascii=False), flush=True)
            return self.j(inst_status())
        if p == "/api/install/retry":
            LIVE["fail"] = False
            INST.update(state="running", error=None, t0=time.time() - 15)
            return self.j(inst_status())
        if p in ("/api/install/keymap", "/api/install/gparted"):
            return self.j({"keymap": body.get("keymap"), "running": True})
        if p == "/api/install/savelog":
            return self.j({"ok": False, "code": "no_usb"})
        if p.startswith("/api/launch/"):
            tid = p.rsplit("/", 1)[1]
            if tid not in st["running"]:
                st["running"].append(tid)
            return self.j({"running": st["running"]})
        if p.startswith("/api/close/"):
            tid = p.rsplit("/", 1)[1]
            st["running"] = [t for t in st["running"] if t != tid]
            return self.j({"running": st["running"]})
        if p.startswith("/api/settings/") or p in ("/api/audio/output", "/api/wifi/connect"):
            if p.endswith("/theme"):
                S.SETTINGS["theme"] = body.get("theme")
            if p.endswith("/scale"):
                S.SETTINGS["scale"] = body.get("scale")
            if p.endswith("/lang"):
                S.SETTINGS["lang"] = body.get("lang")
                return self.j({"lang": body.get("lang")})
            if p.endswith("/frontend"):
                STATE["frontend"] = body.get("frontend")
            return self.j(settings())
        return self.j({})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", default="1280x720")
    ap.add_argument("--shot")
    ap.add_argument("--keys", default="")
    ap.add_argument("--theme")
    ap.add_argument("--live", action="store_true", help="Live-System mit Installer-Kachel")
    ap.add_argument("--fail", action="store_true", help="Installation scheitert beim Startmanager (Fehlerseite)")
    ap.add_argument("--bios", action="store_true", help="Geraet im BIOS-Modus")
    ap.add_argument("--clean", action="store_true", help="fuer Screenshots: kein Update-Hinweis, keine laufende App")
    ap.add_argument("--scale", type=float, help="Skalierung der Oberflaeche (Standard 1.25)")
    a = ap.parse_args()
    if a.clean:
        STATE["running"] = []
        STATE["update"] = {"available": False}
    if a.scale:
        S.SETTINGS["scale"] = a.scale
    if a.theme:
        S.SETTINGS["theme"] = a.theme
    if a.live:
        LIVE["on"] = True
        TILES["groups"].insert(0, {"name": {"de": "Installieren", "en": "Install"}, "tiles": [{
            "id": "install", "type": "install", "size": "large", "color": "#2f6d4f", "icon": "install",
            "label": {"de": "VoidStation installieren", "en": "Install VoidStation"}, "sub": {"de": "auf diesen PC", "en": "on this PC"}}]})
        TILES["user"] = {"de": "Gast", "en": "Guest"}
    LIVE["fail"] = a.fail
    if a.bios:
        PROBE["uefi"] = False
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    env = dict(os.environ, VS_API=f"http://127.0.0.1:{PORT}", VS_SIZE=a.size, VS_DEMO="1")
    if a.shot or a.keys:
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        env.setdefault("QT_QUICK_BACKEND", "software")
        env["VS_KEYS"] = a.keys
        if a.shot:
            env["VS_SCREENSHOT"] = a.shot
    t0 = time.monotonic()
    r = subprocess.run([sys.executable, str(REPO / "launcher" / "qt" / "voidstation-home.py")], env=env)
    print(f"beendet nach {time.monotonic() - t0:.1f} s, Code {r.returncode}")
    srv.shutdown()


if __name__ == "__main__":
    main()
