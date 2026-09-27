#!/usr/bin/env python3
"""
README-Screenshots neu erzeugen: echte Oberflaeche, Beispieldaten (kein Void noetig).
Benoetigt: pip install playwright pillow && playwright install chromium
Aufruf:    python3 tools/screenshots.py      -> docs/screenshots/*.webp
"""
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

REPO = Path(__file__).resolve().parent.parent
WEB = REPO / "launcher" / "web"
TILES = json.loads((REPO / "launcher" / "tiles.json").read_text(encoding="utf-8"))
TILES["user"] = "Paul"
CAT = json.loads((REPO / "launcher" / "catalog.json").read_text(encoding="utf-8"))
INSTALLED = {"retroarch", "duckstation", "kodi", "youtube-tv"}

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
TV = [{"key": f"k{i:02d}", "name": n, "country": "DE", "cats": [c], "quality": q, "logo": None}
      for i, (n, c, q) in enumerate(CHANNELS)]
TV_FAVS = [TV[0], TV[1], TV[4], TV[6]]
COUNTRIES = [{"code": c, "n": n} for c, n in [("DE", 212), ("AT", 48), ("CH", 61), ("FR", 190), ("IT", 240),
                                              ("GB", 150), ("US", 1400), ("ES", 260), ("NL", 90), ("PL", 120)]]

SETTINGS = {
    "scale": float(__import__("os").environ.get("SCALE", "1.25")), "scales": [1, 1.25, 1.5, 1.75, 2, 2.25],
    "cursor": {"theme": "Bibata-Modern-Ice", "size": 48,
               "themes": [{"id": "Bibata-Modern-Ice", "label": "Hell"}, {"id": "Bibata-Modern-Classic", "label": "Dunkel"}],
               "sizes": [32, 48, 64, 80, 96]},
    "displays": [{"name": "HDMI-A-0", "current": "1920x1080", "modes": ["3840x2160", "1920x1080", "1280x720"]}],
    "audio": {"ok": True, "outputs": [
        {"card": "c", "profile": "output:hdmi-stereo", "label": "Digital Stereo (HDMI)", "active": True},
        {"card": "c", "profile": "output:analog-stereo", "label": "Analog Stereo", "active": False}]},
    "volume": {"level": 40, "muted": False},
    "net": {"hostname": "wohnzimmer", "addresses": [{"iface": "enp1s0", "ip": "192.168.178.42"}]},
    "share": {"path": "/home/paul/share", "exists": True, "samba": True, "name": "share", "user": "paul"},
}


def apps():
    out = []
    for a in CAT["apps"]:
        out.append({"id": a["id"], "name": a["name"], "desc": a["desc"], "cat": a["cat"],
                    "type": a["source"]["type"], "installed": a["id"] in INSTALLED,
                    "icon": a.get("tile", {}).get("icon", "globe"), "color": a.get("tile", {}).get("color", "#2f3238")})
    return {"categories": CAT["categories"], "apps": out, "job": None}


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(WEB), **k)

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
            "/api/apps": apps,
            "/api/apps/job": lambda: None,
        }
        if p in routes:
            return self.j(routes[p]())
        return super().do_GET()

    def do_POST(self):
        return self.j({})


FAKE_DATE = """(() => { const F = new Date(2026, 9, 2, 20, 15, 0).getTime(), T0 = Date.now(), D = Date;
  class FD extends D { constructor(...a) { if (a.length) super(...a); else super(F + (D.now() - T0)); }
    static now() { return F + (D.now() - T0); } }
  window.Date = FD; })();"""


def shoot(out):
    import io
    import threading
    import time
    from PIL import Image
    from playwright.sync_api import sync_playwright
    srv = ThreadingHTTPServer(("127.0.0.1", 8765), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    out.mkdir(parents=True, exist_ok=True)

    def save(pg, name):
        png = pg.screenshot()
        Image.open(io.BytesIO(png)).convert("RGB").resize((1600, 900), Image.LANCZOS) \
            .save(out / f"{name}.webp", quality=90, method=6)
        print("gespeichert:", out / f"{name}.webp")

    def open_tile(pg, tid):
        pg.evaluate("t => setFocus(document.querySelector('[data-id=' + JSON.stringify(t) + ']'))", tid)
        pg.keyboard.press("Enter"); time.sleep(2)

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1920, "height": 1080}, locale="de-DE")
        pg.add_init_script(FAKE_DATE)
        pg.goto("http://127.0.0.1:8765/"); time.sleep(3)
        pg.evaluate("setFocus(document.querySelector('[data-id=youtube]'), true)"); time.sleep(0.5)
        save(pg, "1-start")
        for tid, name in ([("tv", "2-fernsehen"), ("appcenter", "3-appcenter"), ("radio", "4-radio")]):
            open_tile(pg, tid); save(pg, name)
            pg.keyboard.press("Escape"); time.sleep(0.8)
        b.close()
    srv.shutdown()


if __name__ == "__main__":
    shoot(REPO / "docs" / "screenshots")
