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
    return dict(S.SETTINGS, volume=STATE["volume"], version={"version": "0.12.1", "build": "abc123"}, ssh=True, live=False,
                sysupd_days=90, sysupd_choices=[30, 60, 90], frontend=STATE.get("frontend", "qt"), frontends=["qt", "web"])


class H(S.H):
    def do_GET(self):
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)
        st = STATE
        routes = {
            "/tiles.json": lambda: TILES,
            "/api/status": lambda: {"running": st["running"], "starting": [], "radio": st["radio"], "tv": st["tv"],
                                    "update": st["update"], "live": False},
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
    a = ap.parse_args()
    if a.theme:
        S.SETTINGS["theme"] = a.theme
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
