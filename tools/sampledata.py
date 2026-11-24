#!/usr/bin/env python3
"""
Beispieldaten fuer tools/qt-preview.py und tools/qt-screenshots.py (kein Void noetig): Kacheln, Sender,
Einstellungen, AppCenter – und ein kleiner HTTP-Handler mit den Grundrouten der Launcher-API.
Frueher tools/screenshots.py (Screenshots der Web-Oberflaeche, mit ihr 2026.12 entfernt).
"""
import json
import os
import re
from typing import Any
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

REPO = Path(__file__).resolve().parent.parent
TILES = json.loads((REPO / "launcher" / "tiles.json").read_text(encoding="utf-8"))
TILES["user"] = "Paul"
CAT = json.loads((REPO / "launcher" / "catalog.json").read_text(encoding="utf-8"))
LANG = os.environ.get("VS_LANG", "de")
# Sprachliste wie auf dem Geraet (LANG_TABLE in launcher.py), ohne launcher.py zu importieren
_src = (REPO / "launcher" / "launcher.py").read_text(encoding="utf-8")
_tab = _src[_src.index("LANG_TABLE = ["):]
LANGS = [{"id": i, "label": n} for i, n in re.findall(r'^\s*\("([A-Za-z-]+)", "([^"]+)"', _tab[:_tab.index("\n]")], re.M)]
INSTALLED = {"steam", "retroarch", "duckstation", "kodi", "ard", "supertuxkart", "jellyfin", "netflix"}

RADIO_NOW = {"station": {"name": "Deutschlandfunk", "url": "https://example.invalid/dlf"}, "title": "Nachrichten"}
RADIO_FAVS = [
    {"name": "Deutschlandfunk", "url": "https://example.invalid/dlf"},
    {"name": "MDR Sachsen-Anhalt", "url": "https://example.invalid/mdrsa"},
    {"name": "radioeins", "url": "https://example.invalid/r1"},
    {"name": "Klassik Radio", "url": "https://example.invalid/kr"},
    {"name": "MDR Jump", "url": "https://example.invalid/jump"},
]

CHANNELS = [
    ("Das Erste", "general", "1080p"), ("ZDF", "general", "1080p"), ("tagesschau24", "news", "720p"),
    ("phoenix", "news", "720p"), ("arte", "culture", "1080p"), ("3sat", "culture", "720p"),
    ("MDR Sachsen-Anhalt", "general", "720p"), ("NDR", "general", "720p"), ("WDR", "general", "720p"),
    ("BR", "general", "720p"), ("KiKA", "kids", "720p"), ("ONE", "series", "720p"),
    ("ZDFneo", "series", "720p"), ("ZDFinfo", "documentary", "720p"), ("Deutsche Welle", "news", "1080p"),
    ("SWR", "general", "720p"), ("hr-fernsehen", "general", "720p"), ("rbb", "general", "720p"),
]
TV: list[dict[str, Any]] = [{"key": f"k{i:02d}", "name": n, "country": "DE", "cats": [c], "quality": q, "logo": None}
                            for i, (n, c, q) in enumerate(CHANNELS)]
TV_FAVS = [TV[0], TV[1], TV[4], TV[6]]


def tv_list(q, data=None):
    """/api/tv/list wie im Launcher (Thema, Suche, A–Z, Seiten), Beispieldaten in fester Reihenfolge."""
    g = lambda k: q.get(k, [""])[0]
    letter_of = lambda n: (n[:1].upper() if n[:1].isalpha() and n[:1].upper() <= "Z" else "#")
    sel = [c for c in (data or TV) if not g("cat") or g("cat") in c["cats"]]
    letters: dict[str, int] = {}
    for c in sel:
        letters[letter_of(c["name"])] = letters.get(letter_of(c["name"]), 0) + 1
    if g("q"):
        sel = [c for c in sel if g("q").lower() in c["name"].lower()]
    elif g("letter"):
        sel = [c for c in sel if letter_of(c["name"]) == g("letter")]
    off, lim = int(g("offset") or 0), int(g("limit") or 200)
    return {"items": sel[off:off + lim], "total": len(sel), "offset": off, "limit": lim, "letter": g("letter"),
            "letters": [{"l": L, "n": letters.get(L, 0)} for L in ["#"] + [chr(c) for c in range(65, 91)]]}
COUNTRIES = [{"code": c, "n": n} for c, n in [("DE", 212), ("AT", 48), ("CH", 61), ("FR", 190), ("IT", 240),
                                              ("GB", 150), ("US", 1400), ("ES", 260), ("NL", 90), ("PL", 120)]]

SETTINGS: dict[str, Any] = {
    "lang": LANG, "langs": LANGS,
    "scale": float(os.environ.get("SCALE", "1.25")), "scales": [1, 1.25, 1.5, 1.75, 2, 2.25],
    "theme": "default-dark", "themes": ["default-dark", "default-light", "high-contrast", "nord"],
    "cursor": {"theme": "Bibata-Modern-Ice", "size": 48,
               "themes": [{"id": "Bibata-Modern-Ice", "label": "Hell"}, {"id": "Bibata-Modern-Classic", "label": "Dunkel"}],
               "sizes": [32, 48, 64, 80, 96]},
    "displays": [{"name": "HDMI-1", "current": "1280x720", "rate": 60.0, "preferred": "1920x1080i",
                  "modes": ["1920x1080i", "1280x720", "720x576"],
                  "rates": {"1920x1080i": [60.0, 50.0, 59.94], "1280x720": [60.0, 50.0, 59.94], "720x576": [50.0]}}],
    "rate": None, "match_rate": False, "game_fx": {"mode": "off", "ready": True, "busy": False, "failed": False},
    "audio": {"ok": True, "auto": True, "devices": [
        {"key": "alsa_card.pci-0000_00_1f.3#hdmi0", "kind": "hdmi", "name": "", "num": 0, "active": True,
         "formats": [{"id": "stereo", "key": "audio.fmt.stereo", "label": ""}, {"id": "surround-51", "key": "audio.fmt.surround", "label": "5.1"},
                     {"id": "surround-71", "key": "audio.fmt.surround", "label": "7.1"}],
         "format": "stereo", "mic": None, "micAvail": False},
        {"key": "alsa_card.usb-C-Media_Electronics_Inc_MCHOSE_X9-01", "kind": "usb", "name": "MCHOSE X9", "num": 0, "active": False,
         "formats": [{"id": "stereo", "key": "audio.fmt.stereo", "label": ""}], "format": "stereo", "mic": True, "micAvail": True},
        {"key": "bluez_card.AA_BB_CC_DD_EE_FF", "kind": "bt", "name": "JBL Flip 5", "num": 0, "active": False,
         "formats": [{"id": "a2dp:auto", "key": "audio.fmt.auto", "label": ""}, {"id": "a2dp:aac", "key": "", "label": "AAC"},
                     {"id": "a2dp:sbc", "key": "", "label": "SBC"}], "format": "a2dp:auto", "mic": False, "micAvail": True}]},
    "volume": {"level": 40, "muted": False},
    "sounds": {"on": True, "volume": 70, "preset": "void", "presets": ["void", "retro", "minimal"], "custom": 0},
    "net": {"hostname": "wohnzimmer", "addresses": [{"iface": "enp1s0", "ip": "192.168.178.42"}],
            "links": [{"dev": "enp1s0", "type": "wired", "connected": True, "name": "Kabelgebundene Verbindung 1",
                       "ip": "192.168.178.42", "internet": True}],
            "has_wired": True, "has_wifi": True, "mode": "both"},
    "share": {"path": "/home/paul/share", "exists": True, "samba": True, "name": "share", "user": "paul"},
}


def apps():
    out = []
    for a in CAT["apps"]:
        out.append({"id": a["id"], "name": a["name"], "desc": a["desc"], "cat": a["cat"],
                    "type": a["source"]["type"], "installed": a["id"] in INSTALLED, "tile": a["id"] in INSTALLED,
                    "icon": a.get("tile", {}).get("icon", "globe"), "color": a.get("tile", {}).get("color", "#2f3238")})
    out.append({"id": "desk-org.gnome.Calculator", "name": "Rechner", "desc": "", "cat": "Auf diesem Gerät", "type": "local",
                "installed": True, "tile": False, "icon": "store", "color": "#2f3238"})
    return {"categories": CAT["categories"], "local_cat": "Auf diesem Gerät", "apps": out, "job": None}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def j(self, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)
        routes = {
            "/tiles.json": lambda: TILES,
            "/api/status": lambda: {"running": ["youtube"], "radio": RADIO_NOW, "tv": None},
            "/api/volume": lambda: SETTINGS["volume"],
            "/api/settings": lambda: SETTINGS,
            "/api/radio/favs": lambda: RADIO_FAVS,
            "/api/tv/status": lambda: {"state": "ready", "error": None, "count": 10432, "countries": COUNTRIES, "now": None},
            "/api/tv/favs": lambda: TV_FAVS,
            "/api/tv/search": lambda: [c for c in TV if not q.get("cat", [""])[0] or q["cat"][0] in c["cats"]],
            "/api/tv/list": lambda: tv_list(q),
            "/api/apps": apps,
            "/api/apps/job": lambda: None,
        }
        if p in routes:
            return self.j(routes[p]())
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        return self.j({})
