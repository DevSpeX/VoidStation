#!/usr/bin/env python3
"""
Qt-Startseite ohne Void-Geraet ausprobieren: Beispieldaten aus tools/sampledata.py, eigener Port 8766.
Benoetigt: pip install PySide6-Essentials (gleiche Version wie python3-pyside6 in Void)
Aufruf:    python3 tools/qt-preview.py                         -> Fenster 1280×720 auf dem Bildschirm
           python3 tools/qt-preview.py --size 1920x1080
           python3 tools/qt-preview.py --shot out.png --keys "right,a,shot:radio.png,b"   (ohne Bildschirm)
           VS_LANG=en …                                        -> englische Oberflaeche
           python3 tools/qt-preview.py --player tv             -> Fernseh-Player (Teststream von mpv: Testbild)
           python3 tools/qt-preview.py --player media --home DIR   -> Videos & Musik, DIR wie ein Home (DIR/share/Videos …)
           python3 tools/qt-preview.py --player yt [--yt-demo]     -> YouTube Light mit yt-dlp-Attrappe (tools/yt-dlp-mock.py),
                                                                      RSS-Feeds, Vorschaubildern und Testvideo von hier
           VS_ROM_COVERS=DIR …                                 -> Spieleliste mit Bildern: DIR/<Dateiname ohne Endung>.png
"""
import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import sampledata as S  # noqa: E402  (Beispieldaten und Grundrouten der API)

PORT = 8766
BT: dict[str, Any] = {"pairing": None, "prompt": None, "names": {}}   # Bluetooth-Kopplung, eigene Geraetenamen (Vorschau)
BT_DEVICES = [{"mac": "11:22:33:44:55:66", "name": "Wireless Controller", "paired": True, "connected": True,
               "kind": "gamepad", "battery": 80},
              {"mac": "AA:BB:CC:DD:EE:01", "name": "AirPods", "paired": False, "kind": "audio", "battery": None},
              {"mac": "AA:BB:CC:DD:EE:FF", "name": "JBL Flip 5", "paired": True, "kind": "audio", "battery": None}]


def bt_devices():
    out = []
    for d in BT_DEVICES:
        alias = BT["names"].get(d["mac"], "")
        out.append(dict(d, name=alias or d["name"], orig=d["name"], custom=bool(alias) and alias != d["name"]))
    return out


def bt_status():
    return {"available": True, "service": True, "powered": STATE["bt_powered"], "scanning": False,
            "pairing": BT["pairing"], "prompt": BT["prompt"], "blocked": False, "devices": bt_devices()}
NOWP: dict[str, Any] = {"kind": "music", "title": "Beispieltitel", "sub": "Beispielband", "paused": False, "volume": 80, "skip": True}
STATE: dict[str, Any] = {"running": ["youtube"], "radio": S.RADIO_NOW, "tv": None, "favs": list(S.RADIO_FAVS), "tvfavs": list(S.TV_FAVS),
         "volume": dict(S.SETTINGS["volume"]), "bt_powered": True, "update": {"available": True, "version": "0.13.0"}}
STATIONS = [{"name": f"Testsender {i}", "url": f"https://example.invalid/s{i}", "favicon": ""} for i in range(1, 15)]
ROMS = [{"title": n, "name": n, "filename": n.lower().replace(" ", "-") + ".gba", "size": "8 MB"} for n in
        ("Advance Wars", "Golden Sun", "Metroid Fusion", "Pokémon Smaragd", "Mario Kart", "Zelda Minish Cap", "F-Zero")]
ROM_COVERS = Path(os.environ["VS_ROM_COVERS"]) if os.environ.get("VS_ROM_COVERS") else None
# Tastenbelegung: Beispiel-Controller (PS4) und mGBA-Belegung wie im Launcher (EMU_LAYOUTS, keymap_payload)
# Layouts wie im Launcher (EMU_LAYOUTS, dort gepflegt – hier nur ausgelesen, damit die Vorschau nicht abweicht)
_src = (REPO / "launcher" / "launcher.py").read_text(encoding="utf-8")
_ns: dict[str, Any] = {"Any": Any}      # Ausschnitt nutzt Annotationen mit Any
exec(_src[_src.index("_DPAD = ["):_src.index("EMU_ACTIONS = {")], _ns)
EMU_LAYOUTS = _ns["EMU_LAYOUTS"]
PS_TEXT = {"south": "✕", "east": "○", "west": "□", "north": "△", "l1": "L1", "r1": "R1", "l2": "L2", "r2": "R2",
           "select": "Share", "start": "Options", "l3": "L3", "r3": "R3", "up": "↑", "down": "↓", "left": "←", "right": "→",
           "rs_up": "R↑", "rs_down": "R↓", "rs_left": "R←", "rs_right": "R→"}
# BIOS-Hinweis der Spieleliste wie launcher.py bios_status (VS_BIOS_OK=1: alles da)
BIOS_NEED = {"duckstation": ["bios"], "pcsx2": ["bios"], "xemu": ["mcpx", "flash", "hdd"]}
CAPTURE_ROLES = ["south", "east", "west", "north", "l1", "r1", "l2", "r2", "start", "select", "up", "down", "left", "right",
                 "l3", "r3"]
KEYMAP: dict[str, Any] = {"own": {}, "step": 0, "nopad": os.environ.get("VS_NO_PAD") == "1"}
# Optionen der Spieleliste (Attrappe; die echten stehen in launcher.py EMU_OPTS)
EMUOPTS: dict[Any, Any] = {"res": "2", "aspect": "Auto", "widescreen": "false", "renderer": "auto", "speed": "std"}
EMUOPTS_GAME: dict[str, Any] = {}
# VS_GAME_DISC=1: Spieleliste mit eingelegter PlayStation-Disc
PREVIEW_DISC: dict[str, Any] | None = {"dev": "/dev/sr0", "name": "sr0", "label": "Beispielspiel", "serial": "SLUS-20946", "opts": True} \
    if os.environ.get("VS_GAME_DISC") == "1" else None
EMUOPT_TF = [{"v": "true", "k": "common.on"}, {"v": "false", "k": "common.off"}]
EMUOPT_LIST: list[tuple[str, list[tuple[str, bool, list[dict[str, Any]]]]]] = [("picture", [
    ("res", False, [{"v": "1", "k": "emuopt.v.original"}, {"v": "2", "t": "2\u00d7"}, {"v": "3", "t": "3\u00d7"}, {"v": "4", "t": "4\u00d7"}]),
    ("aspect", True, [{"v": "Auto", "k": "emuopt.v.auto"}, {"v": "4:3", "t": "4:3"}, {"v": "16:9", "t": "16:9"}, {"v": "Stretch", "k": "emuopt.v.stretch"}]),
    ("widescreen", True, EMUOPT_TF),
    ("pgxp", False, EMUOPT_TF),
    ("texfilter", True, [{"v": "auto", "k": "emuopt.v.auto", "auto": True}, {"v": "on", "k": "common.on"}, {"v": "off", "k": "common.off"}]),
    ("aniso", False, [{"v": "0", "k": "common.off"}, {"v": "4", "t": "4\u00d7"}, {"v": "8", "t": "8\u00d7"}, {"v": "16", "t": "16\u00d7"}]),
]), ("play", [
    ("fastBoot", False, EMUOPT_TF),
    ("resume", False, EMUOPT_TF),
    ("renderer", False, [{"v": "auto", "k": "emuopt.v.auto"}, {"v": "vk", "t": "Vulkan"}, {"v": "gl", "t": "OpenGL"}, {"v": "sw", "t": "Software"}]),
    ("mute", False, EMUOPT_TF),
    ("speed", True, [{"v": "std", "k": "emuopt.v.standard"}, {"v": "xt", "t": "XT"}, {"v": "286", "t": "286"}, {"v": "386", "t": "386"}, {"v": "486", "t": "486"}, {"v": "pentium", "t": "Pentium"}, {"v": "max", "t": "Max"}]),
    ("soundCard", True, [{"v": "sb16", "t": "Sound Blaster 16"}, {"v": "sbpro2", "t": "Sound Blaster Pro 2"}, {"v": "sb1", "t": "Sound Blaster 1.0"}]),
])]
# Spalte Bildstil mit den echten Listen aus launcher.py; VS_LOOK=duckstation|pcsx2|gba|dosbox (Standard duckstation)
_looks: dict[str, Any] = {"BASE": REPO / "launcher", "Path": Path}
exec(_src[_src.index("_OFF = {"):_src.index("_DUCK_LOOK_IO = ")], _looks)
_LOOK_EMU = os.environ.get("VS_LOOK", "duckstation")
_LOOK_CHOICES = {
    "duckstation": [_looks["_OFF"]] + [dict(lab, v=v) for v, _, lab in _looks["DUCK_LOOKS"]],
    "pcsx2": _looks["PCSX2_LOOKS"],
    "gba": [_looks["_OFF"], dict(_looks["_KLAR"], v="klar"), {"v": "orig", "k": "emuopt.v.orig"}]
    + [dict(lab, v=v) for v, lab in _looks["MGBA_LOOKS"]],
    "dosbox": _looks["DOSBOX_LOOKS"],
}[_LOOK_EMU]
_LOOK_ID = "shader" if _LOOK_EMU == "dosbox" else "look"


def _look_p(oid, choices):
    """Vorschaubild je Moeglichkeit wie launcher.py look_preview"""
    out = []
    for c in choices:
        f = REPO / "launcher" / "shaders" / "previews" / _LOOK_EMU / f"{oid}-{str(c['v']).replace('/', '_')}.jpg"
        out.append(dict(c, p=str(f)) if f.is_file() else c)
    return out


_FXAA = {"duckstation": [{"v": "auto", "k": "emuopt.v.auto", "auto": True}, {"v": "on", "k": "common.on"}, _looks["_OFF"]],
         "pcsx2": EMUOPT_TF}.get(_LOOK_EMU)
EMUOPT_LIST.append(("look", ([("fxaa", True, _look_p("fxaa", _FXAA)), ("color", False, _look_p("color", _looks["_COLOR_CHOICES"]))]
                             if _FXAA else []) + [(_LOOK_ID, True, _look_p(_LOOK_ID, _LOOK_CHOICES))]))
EMUOPTS.update({"fxaa": _FXAA[0]["v"] if _FXAA else "", "color": "nat"})


def emuopts_payload(emu, game):
    own = EMUOPTS_GAME.get(game, {})
    only = [x for x in os.environ.get("VS_OPTS", "").split(",") if x]      # VS_OPTS=res,aspect,…: nur diese Optionen zeigen
    mode = None if game else EMUOPTS.setdefault("mode", os.environ.get("VS_OPTS_MODE", "vs"))
    groups, values = [], {}
    # wie launcher.py emu_opts_payload: allgemein links "Allgemein" (Schalter VoidStation-Einstellungen | Anpassen, die
    # uebrigen Zeilen erst mit "Anpassen"), rechts "Bild"; je Spiel Bild, dann Spiel, ohne "Automatik"
    for gid, opts in (EMUOPT_LIST if game else sorted(EMUOPT_LIST, key=lambda g: g[0] != "play")):
        shown = [o for o in opts if (o[1] if game else mode == "custom" and o[0] != "mute") and (not only or o[0] in only)]
        rows = [{"id": o[0], "choices": [{k: v for k, v in c.items() if k != "auto"} for c in o[2] if not (game and c.get("auto"))]}
                for o in shown]
        for o in shown:
            values[o[0]] = own.get(o[0]) if game else EMUOPTS.get(o[0], o[2][0]["v"])
        if not game and gid == "play":
            rows.insert(0, {"id": "mode", "choices": [{"v": "vs", "k": "emuopt.v.vs"}, {"v": "custom", "k": "emuopt.v.custom"}]})
            rows.insert(1, {"id": "mute", "choices": EMUOPT_TF})
            values["mode"], values["mute"] = mode, EMUOPTS.get("mute", "false")
        if rows:
            groups.append({"id": "general" if gid == "play" and not game else gid, "opts": rows})
    return {"emu": emu, "name": emu, "game": game or None, "mode": mode, "groups": groups, "values": values}


def keymap_payload(emu="gba"):
    emu = os.environ.get("VS_KEYMAP") or emu            # VS_KEYMAP=mednafen: Skizze einer anderen Kachel ansehen
    lay = EMU_LAYOUTS.get(emu) or EMU_LAYOUTS["gba"]
    own = KEYMAP["own"].setdefault(emu, {})
    cur = {b: own.get(b, r) for b, r in lay["buttons"]}
    pad = None if KEYMAP["nopad"] else {"path": "/dev/input/event21", "name": "Wireless Controller", "id": "054c:09cc", "src": "SDL"}
    return {"emu": emu, "name": lay["name"], "sub": lay.get("sub", ""), "console": lay["console"], "notes": lay.get("notes", []),
            "rstick": any(r.startswith("rs_") for _, r in lay["buttons"]),
            "pads": [] if not pad else [{"path": pad["path"], "name": pad["name"]}], "pad": pad, "custom": bool(own),
            "buttons": [{"id": b, "action": b in ("save", "load", "rewind", "ff"), "bind": {"role": cur[b]} if cur[b] else None,
                         "role": cur[b] or "", "label": PS_TEXT.get(cur[b], ""), "custom": cur[b] != r} for b, r in lay["buttons"]]}


for _r in ROMS:                                   # wie der Launcher: Adresse immer da, 404 wenn es kein Bild gibt
    _r["cover"] = "/api/roms/cover?folder=gba&file=" + _r["filename"]


TILES = json.loads(json.dumps(S.TILES))
TILES["groups"].insert(1, {"name": "Spiele", "tiles": [
    {"id": "gba", "label": "Game Boy Advance", "sub": "mGBA", "size": "wide", "color": "#2d3763", "icon": "handheld", "cmd": ["mgba-qt"]}]
    + [{"id": t, "label": lay["sub"], "sub": lay["name"], "color": "#3a3157", "icon": "gamepad", "cmd": [t]}
       for t, lay in EMU_LAYOUTS.items() if t != "gba"
       and (not os.environ.get("VS_PREVIEW_EMUS") or t in os.environ["VS_PREVIEW_EMUS"].split(","))]})
# VS_PREVIEW_EMUS=pcsx2,rmg …: nur diese Emulator-Kacheln (fuer Bildschirmfotos der Tastenbelegung)


JOB: dict[str, Any] = {}
# bin/cue -> CHD (VS_CHD=ask: Karte fragt beim Oeffnen einer Spieleliste, VS_CHD=pill: nur der Knopf in der Leiste).
# "Umwandeln" spielt sechs Spiele in rund 20 Sekunden durch, eines davon schlaegt fehl.
CHDM: dict[str, Any] = {"mode": os.environ.get("VS_CHD", ""), "job": {}, "t0": 0.0, "stop": False}
CHD_GAMES = ["Tekken 3", "Legend of Kartia", "Final Fantasy VII (Disc 1)", "Final Fantasy VII (Disc 2)",
             "Final Fantasy VII (Disc 3)", "Rayman"]


def chd_status():
    if not CHDM["mode"]:
        return {"count": 0, "bytes": 0, "ask": False, "free": 0, "job": {}}
    job = CHDM["job"]
    if job.get("state") == "running":
        el, per = time.time() - CHDM["t0"], 3.3
        i = int(el // per)
        if CHDM["stop"] or i >= len(CHD_GAMES):
            done = min(i, len(CHD_GAMES))
            job.update(state="cancelled" if CHDM["stop"] else "done", ok=max(0, done - (1 if done > 1 else 0)),
                       failed=["Legend of Kartia"] if done > 1 else [], saved=done * 231_000_000, step="", pct=0.0)
            CHDM["mode"] = "done"
        else:
            f = (el % per) / per
            job.update(i=i + 1, name=CHD_GAMES[i], step="convert" if f < 0.8 else "verify",
                       pct=round(f / 0.8 * 100 if f < 0.8 else (f - 0.8) / 0.2 * 100, 1))
    running = job.get("state") == "running"
    left = CHDM["mode"] in ("ask", "pill")
    return {"count": len(CHD_GAMES) if left and not running else 0, "bytes": 3_870_000_000 if left else 0,
            "ask": CHDM["mode"] == "ask" and not running, "free": 60_000_000_000, "job": dict(job)}


# Mullvad VPN (VS_VPN=login | off | on | locked | nodaemon): Kachel in "System", Symbol oben rechts, Seite mit Attrappe
VPNM: dict[str, Any] = {"mode": os.environ.get("VS_VPN", ""), "loc": ["se", "sto"], "recent": [{"cc": "de", "city": "fra"},
        {"cc": "nl", "city": "ams"}, {"cc": "ch", "city": "zrh"}],
        "opt": {"lockdown": True, "autoconnect": True, "lan": True, "customDns": False,
                "dns": {"ads": True, "trackers": True, "malware": True, "gambling": False, "adult_content": False, "social_media": False}}}
VPN_RELAYS = [  # Beispieldaten im Format von launcher.py Vpn.relays()
    ("au", "Australia", [("syd", "Sydney", -33.87, 151.21, 6), ("mel", "Melbourne", -37.81, 144.96, 3)]),
    ("at", "Austria", [("vie", "Vienna", 48.21, 16.37, 4)]),
    ("br", "Brazil", [("sao", "Sao Paulo", -23.55, -46.63, 3)]),
    ("ca", "Canada", [("tor", "Toronto", 43.65, -79.38, 8), ("van", "Vancouver", 49.28, -123.12, 4)]),
    ("de", "Germany", [("ber", "Berlin", 52.52, 13.40, 6), ("dus", "Dusseldorf", 51.23, 6.78, 4), ("fra", "Frankfurt", 50.11, 8.68, 28)]),
    ("fi", "Finland", [("hel", "Helsinki", 60.17, 24.94, 5)]),
    ("gb", "UK", [("lon", "London", 51.51, -0.13, 18), ("man", "Manchester", 53.48, -2.24, 4)]),
    ("jp", "Japan", [("tyo", "Tokyo", 35.68, 139.69, 8), ("osa", "Osaka", 34.69, 135.50, 3)]),
    ("nl", "Netherlands", [("ams", "Amsterdam", 52.37, 4.90, 20)]),
    ("se", "Sweden", [("got", "Gothenburg", 57.71, 11.97, 12), ("hel", "Helsingborg", 56.05, 12.69, 4),
                      ("mma", "Malmo", 55.60, 13.00, 16), ("sto", "Stockholm", 59.33, 18.07, 22)]),
    ("ch", "Switzerland", [("zrh", "Zurich", 47.37, 8.54, 10)]),
    ("sg", "Singapore", [("sin", "Singapore", 1.35, 103.82, 6)]),
    ("za", "South Africa", [("jnb", "Johannesburg", -26.20, 28.05, 2)]),
    ("es", "Spain", [("mad", "Madrid", 40.42, -3.70, 6)]),
    ("us", "USA", [("lax", "Los Angeles, CA", 34.05, -118.24, 30), ("nyc", "New York, NY", 40.71, -74.01, 34),
                   ("dal", "Dallas, TX", 32.78, -96.80, 20), ("chi", "Chicago, IL", 41.88, -87.63, 18)]),
]
VPN_CITY = {cc: (name, {c[0]: c for c in cities}) for cc, name, cities in VPN_RELAYS}


def vpn_summary():
    m = VPNM["mode"]
    if not m:
        return {"installed": False}
    if m == "nodaemon":
        return {"installed": True, "state": "nodaemon"}
    if m == "on":
        cc, city = VPNM["loc"]
        cname, cities = VPN_CITY[cc]
        c = cities.get(city) or next(iter(cities.values()))
        return {"installed": True, "state": "connected", "country": cname, "city": c[1], "cc": cc, "cityCode": c[0],
                "host": f"{cc}-{c[0]}-wg-007", "ip": "185.65.135.12", "mullvadIp": True, "lat": c[2], "lon": c[3]}
    return {"installed": True, "state": "disconnected", "locked": m == "locked", "country": "Germany", "city": "Magdeburg",
            "cc": "", "cityCode": "", "host": "", "ip": "93.104.1.2", "mullvadIp": False, "lat": 52.13, "lon": 11.63}


def vpn_page():
    out = {"installed": bool(VPNM["mode"]), "status": vpn_summary(), "recent": VPNM["recent"], "version": "2026.5"}
    if VPNM["mode"] in ("", "nodaemon"):
        return out
    out["account"] = {"loggedIn": False} if VPNM["mode"] == "login" else \
        {"loggedIn": True, "last4": "5521", "expires": "2026-12-05", "device": "Witty Owl"}
    if VPNM["mode"] != "login":
        out["settings"] = VPNM["opt"]
    return out


if VPNM["mode"]:
    for _g in TILES["groups"]:
        if _g.get("name") == "System":
            _g["tiles"].insert(1, {"id": "mullvad", "label": "Mullvad VPN", "size": "wide", "color": "#2b4a6b", "icon": "shield",
                                   "sub": "VPN", "type": "vpn", "app": True})
# Player (--player): Teststream, zuletzt gesehen, Mediathek ueber den echten Launcher-Code (MediaLib) in --home
PLAYER: dict[str, Any] = {"stream": "av://lavfi:testsrc2=size=1280x720:rate=25", "recent": [], "media": None, "tmp": None}


def media():
    """MediaLib aus launcher.py mit HOME = --home; Weiterschauen und Vorschaubilder in einem Wegwerf-Ordner."""
    if PLAYER["media"] is None:
        import tempfile
        sys.path.insert(0, str(REPO / "launcher"))
        import launcher as L  # noqa: E402
        tmp = Path(tempfile.mkdtemp(prefix="vs-preview-"))
        L.init_accounts(base_dir=tmp, runtime_dir=tmp / "rt")
        L.MediaLib.THUMBS = tmp / "thumbs"
        L.CoverFetcher.CACHE = tmp / "covers"                   # Cover-Suche: Zwischenspeicher im Wegwerf-Ordner,
        L.CoverFetcher.MISSES = tmp / "covers" / "misses.json"  # Schalter nur im Speicher (VS_MB_URL/VS_CAA_URL: Testserver)
        L.CoverFetcher.auto = staticmethod(lambda: PLAYER.get("covers_auto", True))  # type: ignore[method-assign]
        L.CoverFetcher.embed = staticmethod(lambda: PLAYER.get("covers_embed", False))  # type: ignore[method-assign]
        L.SETTINGS = tmp / "settings.json"                     # Einstellungen (Musik suchen) nicht ins Repo schreiben
        if os.environ.get("VS_DVD"):                           # VS_DVD=<Ordner mit VIDEO_TS>: gilt als eingelegte DVD
            dvd = str(Path(os.environ["VS_DVD"]).resolve())
            L.DVD.devices = staticmethod(lambda: [dvd])  # type: ignore[method-assign]
            L.DVD._status = lambda d: L.DvdDrive.CDS_DISC_OK  # type: ignore[method-assign]
            L.DVD._size = staticmethod(lambda d: 1)  # type: ignore[method-assign]
            L.DVD.eject = lambda d: True  # type: ignore[method-assign]
        PLAYER["L"] = L
        PLAYER["media"], PLAYER["tmp"] = L.MediaLib(), tmp
    return PLAYER["media"]


def media_list(q):
    try:
        return media().listdir(q.get("path", [""])[0])
    except (ValueError, OSError) as e:
        return {"error": str(e)}
# YouTube Light (--player yt): echter Launcher-Code (YtLight), Daten im Wegwerf-Ordner; yt-dlp ist tools/yt-dlp-mock.py,
# RSS-Feeds, Bilder und das Testvideo liefert dieser Server (/yt-rss, /yt-media/…). --yt-demo: Abos, Verlauf, Spaeter.
YTP: dict[str, Any] = {}


def yt():
    if "YT" not in YTP:
        media()
        L, tmp = PLAYER["L"], PLAYER["tmp"]
        C = L.YtLight
        C.SUBS, C.HIST, C.LATER = tmp / "yt-subs.json", tmp / "yt-history.json", tmp / "yt-later.json"
        C.LOCAL, C.CACHE = tmp / "bin" / "yt-dlp", tmp / "ytcache"
        C.RSS = f"http://127.0.0.1:{PORT}/yt-rss?"
        C.img = lambda self, vid="", url="": yt_img(vid or url)
        os.environ.setdefault("VS_YTDLP", str(REPO / "tools" / "yt-dlp-mock.py"))
        os.environ.setdefault("VS_YT_MEDIA", f"http://127.0.0.1:{PORT}/yt-media/")
        YTP["YT"] = C()
        yt_media("v.mp4")                                     # Testvideo vorab erzeugen (sonst Wettlauf mit mpv)
        if YTP.get("demo"):
            sys.path.insert(0, str(REPO / "tools"))
            import importlib.util
            spec = importlib.util.spec_from_file_location("ytmock", REPO / "tools" / "yt-dlp-mock.py")
            assert spec is not None and spec.loader is not None
            M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)
            Y = YTP["YT"]
            Y._save(C.SUBS, [{"id": c, "title": n, "thumb": f"/api/yt/img?u=https://yt3.ggpht.com/{c}"} for c, n in M.CHANNELS])
            hist = [dict(Y.video(M.video("Verlauf", i)), pos=60 + 90 * i, dur=600, t=int(time.time()) - i * 3600) for i in range(6) if i != 3]
            Y._save(C.HIST, hist)
            Y._save(C.LATER, [Y.video(M.video("Später", i)) for i in (0, 1, 4)])
            s = L.settings_load(); s["yt"] = {"accepted": True, "quality": "auto"}; L.settings_save(s)
    return YTP["YT"]


def yt_img(key):
    """Vorschaubild-Attrappe: Farbverlauf je Video/Kanal (ffmpeg), im Wegwerf-Ordner zwischengespeichert."""
    import hashlib
    h = hashlib.sha1(str(key).encode()).hexdigest()
    f = PLAYER["tmp"] / "ytimg" / f"{h[:12]}.jpg"
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        size = "160x160" if "yt3." in str(key) else "320x180"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i",
                        f"gradients=s={size}:c0=0x{h[:6]}:c1=0x{h[6:12]}:seed={int(h[12:16], 16)}", "-frames:v", "1", "-y", str(f)])
    return f.read_bytes() if f.exists() else None


def yt_rss(q):
    """Atom-Feed wie bei YouTube (Playlist-Feed UULF… bzw. Kanal-Feed) mit sechs Videos je Kanal."""
    cid = q.get("channel_id", [""])[0] or "UC" + q.get("playlist_id", ["UULF"])[0][4:]
    name = {"UCaaaaaaaaaaaaaaaaaaaaa1": "Retro Werkstatt", "UCbbbbbbbbbbbbbbbbbbbbb2": "Kochen mit Oma"}.get(cid, "Kanal " + cid[-4:])
    import hashlib
    ents = []
    for i in range(6):
        v = hashlib.sha1(f"{cid}{i}".encode()).hexdigest()[:10] + "f"
        t = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() - (i * 30 + hash(cid) % 20) * 3600))
        ents.append(f"""<entry><id>yt:video:{v}</id><yt:videoId>{v}</yt:videoId><yt:channelId>{cid}</yt:channelId>
<title>{name}: Neues Video {i + 1}</title><link rel="alternate" href="https://www.youtube.com/watch?v={v}"/>
<author><name>{name}</name></author><published>{t}</published><media:group><media:community>
<media:statistics views="{(i + 1) * 4321}"/></media:community></media:group></entry>""")
    return ('<?xml version="1.0" encoding="UTF-8"?><feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" '
            'xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">'
            f'<title>{name}</title>' + "".join(ents) + "</feed>").encode()


def yt_media(name):
    """Testvideo fuer die Wiedergabe: 30 s Testbild (H.264) und Ton (AAC) getrennt wie bei YouTube, dazu Untertitel."""
    d = PLAYER["tmp"] / "ytmedia"
    if not (d / "de.vtt").exists():                        # zuletzt geschrieben: alles da
        d.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=25", "-t", "30",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-y", str(d / "v.mp4")])
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440", "-t", "30",
                        "-c:a", "aac", "-movflags", "+faststart", "-y", str(d / "a.m4a")])
        for lang, txt in (("en", "Hello from the subtitle track"), ("de", "Hallo aus der Untertitelspur")):
            (d / f"{lang}.vtt").write_text(f"WEBVTT\n\n00:00:01.000 --> 00:00:29.000\n{txt}\n", encoding="utf-8")
    f = d / name
    return f.read_bytes() if f.is_file() and f.parent == d else None


# VS_TVDATA=<Ordner mit channels.json, streams.json, logos.json von iptv-org>: echte Senderliste statt Beispieldaten
TVREAL: dict[str, Any] = {}


def tv_list(q):
    d = os.environ.get("VS_TVDATA")
    if not d:
        return S.tv_list(q)
    if "db" not in TVREAL:
        sys.path.insert(0, str(REPO / "launcher"))
        import tempfile
        import tvindex as T  # noqa: E402
        rd = lambda n: json.loads((Path(d) / n).read_text(encoding="utf-8")) if (Path(d) / n).exists() else []
        TVREAL["T"], TVREAL["db"] = T, Path(tempfile.mkdtemp()) / T.DB_NAME
        T.write_db(T.build_index(rd("channels.json"), rd("streams.json"), rd("logos.json")), TVREAL["db"])
    g = lambda k: q.get(k, [""])[0]
    num = lambda k, dflt: int(g(k)) if g(k).isdigit() else dflt
    return TVREAL["T"].page(TVREAL["db"], g("q"), g("country"), g("cat"), g("letter").upper(), num("offset", 0), num("limit", 200))


def job():
    if JOB.get("action") == "update" and JOB.get("state") == "running":
        # Updates wie launcher.py (Jobs._update_all): Schritte nacheinander, ~1,5 s je Schritt.
        # VS_UPD_JOB=fail: das Einrichten scheitert · VS_UPD_JOB=slow: jeder Schritt 6 s (fuer Bildschirmfotos)
        mode = os.environ.get("VS_UPD_JOB", "")
        t = (time.time() - JOB["t0"]) / (4.0 if mode == "slow" else 1.0)
        if t >= 1:
            JOB.update(steps=[{"id": "apps", "state": "wait", "n": 12}, {"id": "load", "state": "wait"}, {"id": "setup", "state": "wait"},
                              {"id": "check", "state": "wait"}],
                       **{"from": "0.12.1", "to": "0.13.0"})
            for i, x in enumerate(JOB["steps"]):
                x["state"] = "done" if t >= 2.5 + 1.5 * i else "run" if t >= 1 + 1.5 * i else "wait"
            items: list[dict[str, Any]] = [{"id": "system", "icon": "cube", "color": "#2f5578", "n": 12}, {"id": "app:spotify", "name": "Spotify", "icon": "music", "color": "#1e4a2e"},
                     {"id": "app:heroic", "name": "Heroic Games Launcher", "icon": "gamepad", "color": "#3b2d5c"},
                     {"id": "vs", "name": "VoidStation", "icon": "update", "color": "#1f6470"}, {"id": "check", "icon": "search", "color": "#50575f"}]
            spans = [(1, 2), (2, 4.5), (4.5, 5.5), (5.5, 6.5), (6.5, 7)]
            JOB["items"] = [dict(it, state="done" if t >= b else "run" if t >= a else "wait") for it, (a, b) in zip(items, spans)]
            JOB.pop("progress", None)
            JOB.pop("detail", None)
            if 2 <= t < 4.0:
                f = (t - 2) / 2
                JOB["progress"] = {"mb": round(151 * f, 1), "total_mb": 151.0, "pct": int(f * 100), "speed": 212000,
                                   "eta": int((1 - f) * 720) + 3}
            elif 4.0 <= t < 4.5:
                JOB["detail"] = "unpack"
        if t >= 7:
            if mode == "fail":
                JOB["steps"][2]["state"] = "fail"
                JOB["items"][3]["state"] = "fail"
            JOB.update(state="error" if mode == "fail" else "done", reboot=mode != "fail", result={"done": ["voidstation"], "kernel": False})
        JOB["log"] = [f"Zeile {k}" for k in range(int(t * 10))][-60:]
        JOB["n"] = len(JOB["log"])
        return JOB
    if JOB.get("state") == "running" and os.environ.get("VS_JOB_DL") and JOB.get("action") == "install":
        # Download wie Jobs._appimage: "progress" statt Protokollzeilen. VS_JOB_DL=size (mit Groesse, 120 MB)
        # oder nosize (Server ohne Groessenangabe, z. B. GitLab-Artefakte); dauert ~12 s
        t = time.time() - JOB.setdefault("t0", time.time())
        total = 0 if os.environ["VS_JOB_DL"] == "nosize" else 120 << 20
        done = int(min(t / 10, 1) * (120 << 20))
        JOB["log"] = ["$ sudo -n /usr/local/sbin/voidstation-pkg install libcups",
                      "Lade https://github.com/example/releases/download/v1.0/Example-x86_64.AppImage"]
        if t < 10:
            JOB["progress"] = {"mb": round(done / 1048576, 1), "total_mb": round(total / 1048576, 1) if total else 0,
                               "pct": done * 100 // total if total else None}
        else:
            JOB.pop("progress", None)
            JOB["log"] += ["geladen: 120 MB", "Entpacke …"]
        if t >= 12:
            JOB["log"].append("installiert")
            JOB["state"] = "done"
        return JOB
    if JOB.get("state") == "running":
        JOB["n"] = JOB.get("n", 0) + 1
        JOB["log"].append(f"Schritt {JOB['n']} …")
        if JOB["n"] >= 4:
            JOB["state"] = "done"
    return JOB


def settings():
    return dict(S.SETTINGS, volume=STATE["volume"], version={"version": "0.12.1", "build": "abc123"}, ssh=True, live=LIVE["on"],
                standby=not LIVE["on"],
                sysupd_days=90, sysupd_choices=[30, 60, 90],
                padmouse=STATE.get("padmouse", True),
                osk=S.SETTINGS.get("osk") or {"choice": os.environ.get("VS_OSK_LAYOUT", "auto"), "mode": os.environ.get("VS_OSK_MODE", "auto")})


# Installer (--live): Geraet wie im Web-Installer (DEMO_PROBE), Installation laeuft simuliert in ~20 s durch
GiB = 1024 ** 3
PROBE: dict[str, Any] = {"uefi": True, "secureboot": False, "arch": "x86_64", "ram": 3.7 * GiB, "cpu": "Intel Core i3-6100T", "gpu": ["Intel HD Graphics 530"],
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
# Sprachen, Tastaturen und Vorgaben wie im Launcher (probe: langs, kbs, kb, lang)
_li: dict[str, Any] = {"Any": Any}
exec(_src[_src.index("LANG_TABLE = ["):_src.index("LANGS = [")], _li)
exec(_src[_src.index("_GRP = ["):_src.index("# ----", _src.index("_GRP = ["))], _li)
PROBE["langs"] = [{"id": i, "label": n, "kb": _li["INSTALL_DEFAULTS"][i][0], "tz": _li["INSTALL_DEFAULTS"][i][1]}
                  for i, n, _, _ in _li["LANG_TABLE"]]
PROBE["kbs"] = list(_li["KEYMAPS"])
# Land fuer Radio und Fernsehen wie im Launcher (LANG_REGIONS/TV_QUICK); VS_REGION=AT … ueberschreibt
exec(_src[_src.index("LANG_REGIONS = {"):_src.index("def tz_current")], _li)


def region_of(lang):
    return os.environ.get("VS_REGION") or _li["LANG_REGIONS"].get(lang, ["DE"])[0]


def region_quick(lang):
    r = region_of(lang)
    return [r] + [c for c in _li["TV_QUICK"].get(lang, []) if c != r][:2]
INST: dict[str, Any] = {"state": "idle"}
LIVE: dict[str, Any] = {"on": False, "fail": False}


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
                                                    "hostname": st["cfg"]["hostname"],
                                                    "auto_login": bool(st["cfg"].get("user", {}).get("auto_login", True)),
                                                    "seconds": int(t)})
    return st


# Einstellungen → Updates: ?force=1 stoesst wie auf dem Geraet eine Paketpruefung "im Hintergrund" an, die hier
# VS_UPD_CHECK Sekunden dauert (Standard 4). VS_UPD=sys -> kein VoidStation-Update, Systemupdates erst nach der Pruefung
# (die Oberflaeche wartet); VS_UPD=none -> nichts zu tun. VS_CHANNEL=main -> Geraet steht auf Testing.
UPD: dict[str, Any] = {"until": 0.0, "done": False, "channel": os.environ.get("VS_CHANNEL", "stable")}


def updates(q):
    now = time.time()
    if q.get("force", [""])[0] == "1" and now >= UPD["until"]:
        UPD["until"] = now + float(os.environ.get("VS_UPD_CHECK", "4"))
    checking = now < UPD["until"]
    if not checking and UPD["until"]:
        UPD["done"] = True
    mode = os.environ.get("VS_UPD", "")
    vs = mode not in ("sys", "none")
    pkgs = ["linux6.18", "mesa", "firefox", "mpv"] if UPD["done"] and mode != "none" else (["mesa"] if vs else [])
    system = {"count": len(pkgs), "pkgs": pkgs, "kernel": "6.18.59_1" if "linux6.18" in pkgs else None, "flatpak": 0,
              "appimage": [], "proton": None, "checked": True, "due": False, "due_at": 0, "checking": checking}
    ch = UPD["channel"] if UPD["channel"] in ("stable", "main") else "stable"
    return {"local": "0.12.1", "remote": "0.13.0", "available": vs, "any": bool(vs or pkgs), "channel": ch,
            "channel_label": {"stable": "Stable", "main": "Testing"}[ch], "changes": [{"version": "0.13.0", "changes": ["Neue Qt-Startseite"],
                                                     "changes_en": ["New Qt start page"]}] if vs else [],
            "system": system, "reboot": {}}


# Eingabefeld im Browser (wie OskField in launcher.py): melden mit
#   curl -H 'X-TV: 1' -d '{"ev":"focus","kind":"search","pos":0.1,"sid":"t"}' http://127.0.0.1:8766/api/osk/field
# Hinweis "Bildschirmfoto gespeichert" (OskField.notice im Launcher) ueber denselben Weg:
#   curl -H 'X-TV: 1' -d '{"ev":"shot","ok":true,"file":"x.png"}' http://127.0.0.1:8766/api/osk/field
OSKF: dict[str, Any] = {"cv": threading.Condition(), "seq": 0, "state": {}}


def osk_wait(seq):
    with OSKF["cv"]:
        if seq >= 0:
            OSKF["cv"].wait_for(lambda: OSKF["seq"] != seq, 25)
        return dict(OSKF["state"], seq=OSKF["seq"])


# Account-System (Vorschau; VS_ACCOUNT_LOCKED=1, VS_ACCOUNT_CHILD=1, VS_PARENTAL_LOCKED=1, VS_PARENTAL_WARN=1)
_START_CHILD = os.environ.get("VS_ACCOUNT_CHILD") == "1" or os.environ.get("VS_PARENTAL_LOCKED") == "1"
_INIT_ACC = S.ACCOUNTS[2] if _START_CHILD else S.ACCOUNTS[0]
ACC_STATE: dict[str, Any] = {
    "accounts": json.loads(json.dumps(S.ACCOUNTS)),
    "policy": dict(S.ACCOUNT_POLICY),
    "session": {
        "account_id": _INIT_ACC["id"],
        "display_name": _INIT_ACC["display_name"],
        "role": _INIT_ACC["role"],
        "avatar": _INIT_ACC["avatar"],
        "color": _INIT_ACC["color"],
        "is_guest": False,
        "locked": os.environ.get("VS_ACCOUNT_LOCKED") == "1",
        "picker_required": os.environ.get("VS_ACCOUNT_LOCKED") == "1",
        "elevated_until": 0,
    },
    "secrets": {"acc-paul": {"pin": "1234", "password": "voidstation"}, "acc-anna": {"pin": "2580"}, "acc-leo": {}},
    "throttle": {},
    "prefs": {},
    "parental_policies": json.loads(json.dumps(S.PARENTAL_POLICIES)),
    "parental_usage": {
        "acc-leo": {
            "used_seconds": 3600 if os.environ.get("VS_PARENTAL_LOCKED") == "1" else 900,
            "bonus_seconds": 0,
        }
    },
    "allow_once": {},
    "bedtime_override": {},
    "seq": 1,
}
_CAT_APPS = {a["id"]: a for a in S.CAT["apps"]}
_BROWSER_IDS = {"firefox", "chromium", "brave", "braveorigin", "librewolf"}
_ALWAYS_VISIBLE = {"clock", "settings"}
_ADMIN_ONLY = {"appcenter"}
_GUEST_BLOCKED_TILES = {"terminal", "files"}
_GUEST_BLOCKED_CATS = {"Werkzeuge"}


def _parental_policy_for(aid: str) -> dict[str, Any]:
    return ACC_STATE["parental_policies"].setdefault(aid, {
        "account_id": aid, "mode": "allowlist", "allowed_tiles": [],
        "blocked_tiles": ["terminal", "files"], "blocked_cats": ["Werkzeuge"],
        "max_age_rating": 12, "daily_limit_min": 0, "bedtime_start": "", "bedtime_end": "",
        "allow_yt_search": False, "allow_browser": False, "allow_power_menu": False, "updated_at": 0,
    })


def _parental_status(aid: str | None = None) -> dict[str, Any]:
    sess = ACC_STATE["session"]
    target = aid or (sess["account_id"] if not sess["is_guest"] else "")
    acc = _acc_find(target) if target else None
    if aid is None and sess["is_guest"]:
        return {
            "restricted": True, "locked": bool(sess["locked"]),
            "reason": "", "remaining_seconds": None,
            "allow_yt_search": True, "allow_browser": False, "allow_power_menu": True,
        }
    if not acc or acc["role"] != "child":
        return {
            "restricted": False, "locked": bool(sess["locked"]) if aid is None else False,
            "reason": "", "remaining_seconds": None,
            "allow_yt_search": True, "allow_browser": True, "allow_power_menu": True,
        }
    pol = _parental_policy_for(acc["id"])
    u = ACC_STATE["parental_usage"].setdefault(acc["id"], {"used_seconds": 0, "bonus_seconds": 0})
    lim_sec = int(pol["daily_limit_min"]) * 60 + int(u["bonus_seconds"]) if int(pol["daily_limit_min"]) > 0 else 0
    rem = max(0, lim_sec - int(u["used_seconds"])) if int(pol["daily_limit_min"]) > 0 else None
    locked = (rem is not None and rem <= 0)
    reason = "daily_limit" if locked else ""
    return {
        "restricted": True,
        "locked": bool(locked or (sess["locked"] if aid is None else False)),
        "reason": reason,
        "remaining_seconds": rem,
        "used_seconds": int(u["used_seconds"]),
        "bonus_seconds": int(u["bonus_seconds"]),
        "limit_seconds": lim_sec,
        "in_bedtime": False,
        "allow_yt_search": bool(pol["allow_yt_search"]),
        "allow_browser": bool(pol["allow_browser"]),
        "allow_power_menu": bool(pol["allow_power_menu"]),
        "policy": pol,
        "usage": {
            "used_seconds": int(u["used_seconds"]),
            "bonus_seconds": int(u["bonus_seconds"]),
            "remaining_seconds": rem,
            "in_bedtime": False,
        },
    }


def _parental_tile_choices() -> tuple[list[str], list[dict[str, Any]]]:
    out = []
    for g in TILES.get("groups", []):
        for t in g.get("tiles", []):
            tid = str(t.get("id") or "")
            if not tid or tid in _ALWAYS_VISIBLE or tid in _ADMIN_ONLY:
                continue
            app = _CAT_APPS.get(tid, {})
            cat = t.get("cat") or app.get("cat") or ""
            out.append({"id": tid, "label": t.get("label") or tid, "cat": cat, "is_browser": tid in _BROWSER_IDS or cat == "Browser"})
    return list(S.CAT.get("categories", [])), out


def _parental_check_tile(tid: str, *, ignore_time: bool = False, consume_once: bool = False) -> tuple[bool, str, bool]:
    sess = ACC_STATE["session"]
    if sess["is_guest"]:
        if tid in _ALWAYS_VISIBLE:
            return True, "", False
        if tid in _ADMIN_ONLY:
            return False, "admin_only", False
        app = _CAT_APPS.get(tid, {})
        cat = app.get("cat") or ""
        if tid in _BROWSER_IDS or cat == "Browser":
            return False, "browser_blocked", False
        if tid in _GUEST_BLOCKED_TILES or (cat and cat in _GUEST_BLOCKED_CATS):
            return False, "guest_restricted", False
        allowed = ACC_STATE["policy"].get("guest_allowed_tiles") or []
        if allowed and tid not in allowed:
            return False, "guest_restricted", False
        return True, "", False
    if sess["role"] != "child" or tid in _ALWAYS_VISIBLE:
        return True, "", False
    st = _parental_status(sess["account_id"])
    if not ignore_time and st["locked"]:
        return False, st["reason"] or "daily_limit", True
    once = ACC_STATE["allow_once"].setdefault(sess["account_id"], set())
    if tid in once:
        if consume_once:
            once.discard(tid)
        return True, "", False
    if tid in _ADMIN_ONLY:
        return False, "admin_only", False
    pol = _parental_policy_for(sess["account_id"])
    app = _CAT_APPS.get(tid, {})
    cat = app.get("cat") or ""
    if (tid in _BROWSER_IDS or cat == "Browser") and not pol["allow_browser"]:
        return False, "browser_blocked", True
    if tid in pol["blocked_tiles"]:
        return False, "tile_blocked", True
    if cat and cat in pol["blocked_cats"]:
        return False, "category_blocked", True
    raw_age = app.get("age_rating")
    if isinstance(raw_age, (int, float)) and not isinstance(raw_age, bool) and int(raw_age) > int(pol.get("max_age_rating", 12)):
        return False, "age_rating", True
    if pol["mode"] == "allowlist" and tid not in pol["allowed_tiles"]:
        return False, "not_allowed", True
    return True, "", False


def _acc_find(aid: str) -> dict[str, Any] | None:
    return next((a for a in ACC_STATE["accounts"] if a["id"] == aid), None)


def _acc_sync_flags(acc: dict[str, Any]) -> None:
    sec = ACC_STATE["secrets"].setdefault(acc["id"], {})
    acc["has_pin"] = bool(sec.get("pin"))
    acc["has_password"] = bool(sec.get("password"))
    acc["auth_configured"] = acc["has_pin"] or acc["has_password"]


def _acc_prefs_for(aid: str) -> dict[str, Any]:
    return ACC_STATE["prefs"].setdefault(aid, {
        "lang": S.SETTINGS.get("lang", "de"),
        "theme": S.SETTINGS.get("theme", "default-dark"),
        "scale": S.SETTINGS.get("scale", 1.25),
        "ui_sounds": True,
        "ui_sounds_volume": 70,
        "ui_sounds_preset": "void",
    })


def _acc_apply_prefs(aid: str) -> dict[str, Any]:
    prefs = _acc_prefs_for(aid)
    S.SETTINGS["lang"] = prefs["lang"]
    S.SETTINGS["theme"] = prefs["theme"]
    S.SETTINGS["scale"] = prefs["scale"]
    S.SETTINGS["sounds"].update({
        "on": prefs["ui_sounds"],
        "volume": prefs["ui_sounds_volume"],
        "preset": prefs["ui_sounds_preset"],
    })
    return dict(prefs)


def _acc_verify(aid: str, factor: str, secret: str) -> tuple[int, dict[str, Any] | None]:
    now = time.time()
    key = (aid, factor)
    th = ACC_STATE["throttle"].setdefault(key, {"count": 0, "until": 0.0, "hard": False})
    if th["hard"]:
        return 423, {"error": "account.err.pinLocked", "msg": "PIN locked", "hard_locked": True}
    if th["until"] > now:
        return 429, {"error": "account.cooldown", "msg": "Cooldown", "retry_after": int(th["until"] - now) + 1}
    expected = ACC_STATE["secrets"].get(aid, {}).get(factor)
    if expected and secret == expected:
        ACC_STATE["throttle"].pop(key, None)
        if factor == "password":
            ACC_STATE["throttle"].pop((aid, "pin"), None)
        return 200, None
    th["count"] += 1
    if factor == "pin" and th["count"] >= 5:
        th["hard"] = True
        return 423, {"error": "account.err.pinLocked", "msg": "PIN locked", "hard_locked": True}
    if th["count"] >= 3:
        wait = 5 if th["count"] == 3 else 15
        th["until"] = now + wait
        return 429, {"error": "account.cooldown", "msg": "Cooldown", "retry_after": wait}
    return 401, {"error": "account.err.invalid", "msg": "Invalid credentials"}


def _parental_payload() -> dict[str, Any]:
    cats, tiles = _parental_tile_choices()
    return {
        "policies": {a["id"]: _parental_policy_for(a["id"]) for a in ACC_STATE["accounts"] if a["role"] == "child"},
        "statuses": {a["id"]: _parental_status(a["id"]) for a in ACC_STATE["accounts"] if a["role"] == "child"},
        "categories": cats,
        "tiles": tiles,
    }


def _tiles_payload() -> dict[str, Any]:
    if LIVE["on"]:
        return TILES
    out = json.loads(json.dumps(TILES))
    sess = ACC_STATE["session"]
    if sess["role"] == "child" or sess["is_guest"]:
        groups = []
        for g in out.get("groups", []):
            kept = [t for t in g.get("tiles", []) if _parental_check_tile(str(t.get("id") or ""), ignore_time=True)[0]]
            if kept:
                g["tiles"] = kept
                groups.append(g)
        out["groups"] = groups
    out["user"] = sess["display_name"]
    return out


class H(S.H):
    def do_GET(self):
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)
        st = STATE
        if p == "/api/vpn/map":
            data = (REPO / "launcher/qt/qml/vpn/worldmap.json").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return None
        if p == "/api/osk/wait":
            try:
                return self.j(osk_wait(int(q.get("seq", ["-1"])[0])))
            except (BrokenPipeError, ConnectionResetError):        # Startseite beendet, waehrend sie wartete
                return None
        routes = {
            "/tiles.json": _tiles_payload,
            "/api/status": lambda: {"running": st["running"], "starting": [], "radio": st["radio"], "tv": st["tv"],
                                    "update": st["update"] if not LIVE["on"] else {"available": False}, "live": LIVE["on"],
                                    "vpn": vpn_summary(),
                                    "account": S.account_summary(ACC_STATE["session"], ACC_STATE["policy"], ACC_STATE["accounts"], _parental_status())},
            "/api/session": lambda: {"session": ACC_STATE["session"], "device_policy": ACC_STATE["policy"],
                                     "accounts_count": len(ACC_STATE["accounts"]), "migrated": False,
                                     "parental": _parental_status()},
            "/api/accounts": lambda: {"accounts": ACC_STATE["accounts"], "session": ACC_STATE["session"],
                                      "device_policy": ACC_STATE["policy"]},
            "/api/accounts/parental": _parental_payload,
            "/api/vpn": vpn_page,
            "/api/vpn/relays": lambda: {"countries": [{"cc": cc, "name": n, "cities": [
                {"code": c[0], "name": c[1], "lat": c[2], "lon": c[3], "n": c[4]} for c in cities]} for cc, n, cities in VPN_RELAYS],
                "nearest": "de"},
            "/api/front": lambda: {"id": st["running"][0] if st["running"] else None, "mouse": True,
                                   "padmouse": STATE.get("padmouse", True)},
            "/api/volume": lambda: st["volume"],
            "/api/nowplaying": lambda: NOWP,
            "/api/settings": settings,
            "/api/radio/favs": lambda: st["favs"],
            "/api/radio/search": lambda: STATIONS,
            "/api/radio/popular": lambda: {"country": region_of(S.SETTINGS.get("lang") or "de"),
                                           "stations": [dict(x, name=f"Beliebt {i}") for i, x in enumerate(STATIONS[:10], 1)]},
            "/api/tv/status": lambda: {"state": "ready", "error": None, "count": 10432, "countries": S.COUNTRIES, "now": st["tv"],
                                       "region": region_of(S.SETTINGS.get("lang") or "de"),
                                       "quick": region_quick(S.SETTINGS.get("lang") or "de")},
            "/api/tv/favs": lambda: st["tvfavs"],
            "/api/tv/search": lambda: [c for c in S.TV if not q.get("cat", [""])[0] or q["cat"][0] in c["cats"]],
            "/api/tv/list": lambda: tv_list(q),
            "/api/tv/epg": lambda: {"current": {"title": "Tagesschau", "start": "20:00", "stop": "20:15", "progress": 60},
                                    "next": {"title": "Wetter"}},
            "/api/apps": S.apps,
            "/api/apps/job": job,
            "/api/updates": lambda: updates(q),
            "/api/bluetooth/status": bt_status,
            "/api/wifi/scan": lambda: [{"ssid": "FRITZ!Box 7530", "signal": 72, "secure": True, "known": True,
                                        "active": any(l["type"] == "wifi" and l["connected"] for l in S.SETTINGS["net"]["links"])},
                                       {"ssid": "iPhone von Paul", "signal": 58, "secure": True, "known": True, "active": False},
                                       {"ssid": "Nachbar", "signal": 31, "secure": True, "known": False, "active": False}],
            "/api/roms/disc": lambda: {"disc": PREVIEW_DISC},
            "/api/roms/chd": chd_status,
            "/api/keymap": lambda: keymap_payload(q.get("emu", ["gba"])[0]),
            "/api/emuopts": lambda: emuopts_payload(q.get("emu", ["gba"])[0], q.get("game", [""])[0]),
            "/api/roms": lambda: {"system": q.get("system", ["gba"])[0], "count": len(ROMS), "roms": ROMS,
                                  "keymap": q.get("system", ["gba"])[0] in EMU_LAYOUTS,
                                  "opts": True, "gameOpts": True, "discDrive": True, "disc": PREVIEW_DISC,
                                  "chd": chd_status(),
                                  "bios": None if q.get("system", ["gba"])[0] not in BIOS_NEED else
                                  {"ok": True, "missing": []} if os.environ.get("VS_BIOS_OK") == "1" else
                                  {"ok": False, "missing": BIOS_NEED[q.get("system", ["gba"])[0]]}},
            "/api/install/probe": lambda: PROBE,
            "/api/install/status": lambda: dict(inst_status(), autostart=LIVE["on"] and INST.get("state") == "idle" and not INST.get("seen")),
            "/api/install/gparted": lambda: {"running": False},
            "/api/install/log": lambda: {"log": "[check] ok\n[partition] sgdisk …\n[boot] efibootmgr: Could not prepare Boot variable"},
            "/api/tv/zap": lambda: {"items": S.TV, "favs": st["tvfavs"], "recent": PLAYER["recent"], "key": (st["tv"] or {}).get("key")},
            "/api/media/roots": lambda: media().roots(),
            "/api/media/list": lambda: media_list(q),
            "/api/media/nextfolder": lambda: media().next_folder(q.get("path", [""])[0]) or {},
            "/api/media/covers": lambda: (media(), PLAYER["L"].COVERS.status())[1],
            "/api/media/dvd": lambda: (media(), {"discs": PLAYER["L"].DVD.discs()})[1],
            "/api/dl/settings": lambda: (media(), PLAYER["L"].MUSICDL.payload())[1],
            "/api/dl/status": lambda: (media(), PLAYER["L"].MUSICDL.status())[1],
        }
        if p.startswith("/api/yt/") or p in ("/yt-rss",) or p.startswith("/yt-media/"):
            return self.yt_get(p, q)
        if p == "/api/roms/cover":
            f = ROM_COVERS / (Path(q.get("file", [""])[0]).stem + ".png") if ROM_COVERS else None
            if f and f.is_file():
                return self.raw(200, f.read_bytes(), "image/png")
            return self.raw(404, b"", "text/plain")
        if p == "/api/media/thumb":
            art = q.get("art", [""])[0]
            r = media().art(art) if art else media().thumb(q.get("path", [""])[0])
            if not r:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", r[1])
            self.send_header("Content-Length", str(len(r[0])))
            self.end_headers()
            self.wfile.write(r[0])
            return
        if p in routes:
            return self.j(routes[p]())
        return super().do_GET()

    def raw(self, code, data, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def j_status(self, code: int, obj: Any) -> None:
        self.raw(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def yt_get(self, p, q):
        g = lambda k: q.get(k, [""])[0]
        Y = yt()
        if p == "/yt-rss":
            return self.raw(200, yt_rss(q), "application/atom+xml")
        if p.startswith("/yt-media/"):                   # wie googlevideo: mit Range (mpv springt im Video)
            data = yt_media(p.rsplit("/", 1)[1])
            if not data:
                return self.raw(404, b"", "text/plain")
            m = re.match(r"bytes=(\d+)-(\d*)", self.headers.get("Range", ""))
            if not m:
                self.send_response(200)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                return self.wfile.write(data)
            a0 = int(m.group(1)); a1 = int(m.group(2)) if m.group(2) else len(data) - 1
            part = data[a0:a1 + 1]
            self.send_response(206)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Range", f"bytes {a0}-{a0 + len(part) - 1}/{len(data)}")
            self.send_header("Content-Length", str(len(part)))
            self.end_headers()
            return self.wfile.write(part)
        what = p[len("/api/yt/"):]
        try:
            if what == "img":
                data = Y.img(vid=g("v"), url=g("u"))
                return self.raw(200, data, "image/jpeg") if data else self.raw(404, b"", "text/plain")
            if what == "search" and not _parental_status()["allow_yt_search"]:
                return self.j_status(403, {"error": "account.blocked", "reason": "yt_search_blocked", "override_allowed": False})
            if what == "state":
                res = dict(Y.state())
                res["allow_search"] = _parental_status()["allow_yt_search"]
                return self.j(res)
            fn = {"home": Y.home, "history": Y.history, "later": Y.later, "subs": lambda: {"items": Y.subs()},
                  "feed": lambda: Y.feed_get(300, force=g("force") == "1"), "search": lambda: Y.search(g("q"), g("kind") or "video"),
                  "channel": lambda: Y.channel(g("id"), g("tab") or "videos"), "playlist": lambda: Y.playlist(g("id"))}[what]
            return self.j(fn())
        except PLAYER["L"].YtError as e:
            return self.raw(502, json.dumps({"error": e.reason, "msg": str(e)}).encode(), "application/json")

    def do_POST(self):
        p = urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        st = STATE
        if p == "/api/session/switch":
            aid = str(body.get("account_id") or body.get("id") or "").strip()
            acc = _acc_find(aid)
            if not acc or not acc.get("active", True):
                return self.j_status(404, {"error": "account.err.notFound"})
            if acc["has_pin"] or acc["has_password"]:
                if "password" in body and body["password"] is not None:
                    code, err = _acc_verify(aid, "password", str(body["password"]))
                elif "pin" in body and body["pin"] is not None:
                    code, err = _acc_verify(aid, "pin", str(body["pin"]))
                else:
                    return self.j_status(401, {"error": "account.err.invalid"})
                if err is not None:
                    return self.j_status(code, err)
            elif acc["role"] != "child" and any(a["role"] == "child" and a.get("active", True) for a in ACC_STATE["accounts"]):
                return self.j_status(403, {"error": "account.err.parentAuthRequired"})
            ACC_STATE["session"] = {
                "account_id": acc["id"], "display_name": acc["display_name"], "role": acc["role"],
                "avatar": acc["avatar"], "color": acc["color"], "is_guest": False,
                "locked": False, "picker_required": False, "elevated_until": 0,
            }
            return self.j({"ok": True, "session": ACC_STATE["session"], "prefs": _acc_apply_prefs(acc["id"]), "parental": _parental_status()})
        if p == "/api/session/lock":
            sess = ACC_STATE["session"]
            if sess["is_guest"]:
                fallback = ACC_STATE["accounts"][0]
                ACC_STATE["session"] = {
                    "account_id": fallback["id"], "display_name": fallback["display_name"], "role": fallback["role"],
                    "avatar": fallback["avatar"], "color": fallback["color"], "is_guest": False,
                    "locked": True, "picker_required": True, "elevated_until": 0,
                }
            else:
                sess["locked"] = True
                sess["picker_required"] = True
            return self.j({"ok": True, "session": ACC_STATE["session"]})
        if p == "/api/session/guest":
            if not ACC_STATE["policy"]["guest_enabled"]:
                return self.j_status(403, {"error": "account.err.guestDisabled"})
            if ACC_STATE["session"]["role"] == "child" and not ACC_STATE["session"]["is_guest"]:
                return self.j_status(403, {"error": "account.err.blocked"})
            ACC_STATE["session"] = {
                "account_id": "guest", "display_name": str(body.get("display_name") or "Gast"), "role": "guest",
                "avatar": "user", "color": "#3a3f46", "is_guest": True,
                "locked": False, "picker_required": False, "elevated_until": 0,
            }
            return self.j({"ok": True, "session": ACC_STATE["session"], "prefs": _acc_apply_prefs("guest"), "parental": _parental_status()})
        if p == "/api/accounts/create":
            sess = ACC_STATE["session"]
            if sess["locked"] or sess["is_guest"] or sess["role"] != "admin":
                return self.j_status(403, {"error": "account.err.adminRequired"})
            name = str(body.get("display_name") or "").strip()
            if not name:
                return self.j_status(400, {"error": "account.err.nameRequired"})
            role = str(body.get("role") or "standard")
            parent_id = body.get("parent_id") if role == "child" else None
            if role == "child":
                parent = _acc_find(str(parent_id or ""))
                if not parent or not parent.get("active", True) or parent.get("role") != "admin":
                    return self.j_status(403, {"error": "account.err.parentRequired"})
                if not (parent.get("has_pin") or parent.get("has_password")):
                    return self.j_status(403, {"error": "account.err.parentAuthRequired"})
            pin = body.get("pin")
            pw = body.get("password")
            if pin is not None and not re.fullmatch(r"\d{4,8}", str(pin)):
                return self.j_status(400, {"error": "account.err.pinFormat"})
            if pw is not None and not (1 <= len(str(pw)) <= 200):
                return self.j_status(400, {"error": "account.err.pwFormat"})
            aid = f"acc-demo-{ACC_STATE['seq']}"
            ACC_STATE["seq"] += 1
            if body.get("auto_login"):
                for a in ACC_STATE["accounts"]:
                    a["auto_login"] = False
            acc = {
                "id": aid, "display_name": name, "role": role,
                "parent_id": body.get("parent_id") if role == "child" else None,
                "avatar": str(body.get("avatar") or "user"), "color": str(body.get("color") or "#2d4a6b"),
                "active": True, "auto_login": bool(body.get("auto_login", False)),
                "created_at": int(time.time()), "last_login_at": 0,
                "has_password": bool(pw), "has_pin": bool(pin), "auth_configured": bool(pw or pin),
            }
            ACC_STATE["secrets"][aid] = {k: str(v) for k, v in (("pin", pin), ("password", pw)) if v}
            ACC_STATE["accounts"].append(acc)
            return self.j({"ok": True, "account": acc, "accounts": ACC_STATE["accounts"]})
        if p == "/api/accounts/update":
            sess = ACC_STATE["session"]
            if sess["locked"] or sess["is_guest"] or sess["role"] == "child":
                return self.j_status(403, {"error": "account.err.adminRequired"})
            aid = str(body.get("account_id") or body.get("id") or "").strip()
            acc = _acc_find(aid)
            if not acc:
                return self.j_status(404, {"error": "account.err.notFound"})
            if sess["role"] != "admin" and (aid != sess["account_id"] or any(k in body for k in ("role", "parent_id", "active", "auto_login"))):
                return self.j_status(403, {"error": "account.err.adminRequired"})
            if "display_name" in body:
                nm = str(body["display_name"] or "").strip()
                if not nm:
                    return self.j_status(400, {"error": "account.err.nameRequired"})
                acc["display_name"] = nm
            if "role" in body and body["role"] in ("admin", "standard", "child"):
                admins = [a for a in ACC_STATE["accounts"] if a["role"] == "admin" and a["active"]]
                if acc["role"] == "admin" and body["role"] != "admin" and len(admins) <= 1:
                    return self.j_status(403, {"error": "account.err.lastAdmin"})
                acc["role"] = body["role"]
            if "parent_id" in body:
                acc["parent_id"] = body["parent_id"] or None
            if "avatar" in body and body["avatar"]:
                acc["avatar"] = str(body["avatar"])
            if "color" in body and body["color"]:
                acc["color"] = str(body["color"])
            if body.get("auto_login") is True:
                for a in ACC_STATE["accounts"]:
                    a["auto_login"] = (a["id"] == aid)
            elif "auto_login" in body:
                acc["auto_login"] = bool(body["auto_login"])
            if sess["account_id"] == aid and not sess["is_guest"]:
                sess.update(display_name=acc["display_name"], role=acc["role"], avatar=acc["avatar"], color=acc["color"])
            return self.j({"ok": True, "account": acc, "session": sess})
        if p == "/api/accounts/credentials":
            sess = ACC_STATE["session"]
            if sess["locked"] or sess["is_guest"] or sess["role"] == "child":
                return self.j_status(403, {"error": "account.err.adminRequired"})
            aid = str(body.get("account_id") or body.get("id") or sess["account_id"]).strip()
            acc = _acc_find(aid)
            if not acc:
                return self.j_status(404, {"error": "account.err.notFound"})
            action = str(body.get("action") or "set").strip().lower()
            factor = str(body.get("factor") or ("pin" if "pin" in body else "password" if "password" in body else "")).strip().lower()
            if action == "unlock":
                if sess["role"] != "admin":
                    return self.j_status(403, {"error": "account.err.adminRequired"})
                if factor:
                    ACC_STATE["throttle"].pop((aid, factor), None)
                else:
                    ACC_STATE["throttle"].pop((aid, "pin"), None)
                    ACC_STATE["throttle"].pop((aid, "password"), None)
                return self.j({"ok": True, "account": acc})
            if sess["role"] != "admin":
                if aid != sess["account_id"]:
                    return self.j_status(403, {"error": "account.err.adminRequired"})
                if acc["has_pin"] or acc["has_password"]:
                    if body.get("current_password") is not None:
                        code, err = _acc_verify(aid, "password", str(body["current_password"]))
                    elif body.get("current_pin") is not None:
                        code, err = _acc_verify(aid, "pin", str(body["current_pin"]))
                    else:
                        return self.j_status(401, {"error": "account.err.invalid"})
                    if err is not None:
                        return self.j_status(code, err)
            sec = ACC_STATE["secrets"].setdefault(aid, {})
            if action == "remove":
                if acc["role"] != "child":
                    has_children = any(a["role"] == "child" and a.get("active", True) for a in ACC_STATE["accounts"])
                    rem_pin = bool(sec.get("pin")) and factor != "pin"
                    rem_pw = bool(sec.get("password")) and factor != "password"
                    if has_children and not (rem_pin or rem_pw):
                        return self.j_status(403, {"error": "account.err.parentAuthRequired"})
                sec.pop(factor, None)
                _acc_sync_flags(acc)
                return self.j({"ok": True, "account": acc})
            val = str(body.get("secret") if "secret" in body else body.get(factor, ""))
            if factor == "pin" and not re.fullmatch(r"\d{4,8}", val):
                return self.j_status(400, {"error": "account.err.pinFormat"})
            if factor == "password" and not (1 <= len(val) <= 200):
                return self.j_status(400, {"error": "account.err.pwFormat"})
            sec[factor] = val
            _acc_sync_flags(acc)
            resp: dict[str, Any] = {"ok": True, "account": acc}
            if factor == "pin":
                resp["weak_pin"] = val in ("0000", "1234", "1111", "2222", "123456") or len(set(val)) == 1
            return self.j(resp)
        if p == "/api/accounts/delete":
            sess = ACC_STATE["session"]
            if sess["locked"] or sess["is_guest"] or sess["role"] != "admin":
                return self.j_status(403, {"error": "account.err.adminRequired"})
            aid = str(body.get("account_id") or body.get("id") or "").strip()
            acc = _acc_find(aid)
            if not acc:
                return self.j_status(404, {"error": "account.err.notFound"})
            admins = [a for a in ACC_STATE["accounts"] if a["role"] == "admin" and a["active"]]
            if acc["role"] == "admin" and len(admins) <= 1:
                return self.j_status(403, {"error": "account.err.lastAdmin"})
            ACC_STATE["accounts"] = [a for a in ACC_STATE["accounts"] if a["id"] != aid]
            ACC_STATE["secrets"].pop(aid, None)
            if sess["account_id"] == aid and not sess["is_guest"]:
                nxt = ACC_STATE["accounts"][0]
                ACC_STATE["session"] = {
                    "account_id": nxt["id"], "display_name": nxt["display_name"], "role": nxt["role"],
                    "avatar": nxt["avatar"], "color": nxt["color"], "is_guest": False,
                    "locked": True, "picker_required": True, "elevated_until": 0,
                }
            return self.j({"ok": True, "deleted": aid, "session": ACC_STATE["session"], "accounts": ACC_STATE["accounts"]})
        if p == "/api/accounts/device-policy":
            sess = ACC_STATE["session"]
            if sess["locked"] or sess["is_guest"] or sess["role"] != "admin":
                return self.j_status(403, {"error": "account.err.adminRequired"})
            pol = ACC_STATE["policy"]
            for k in ("ask_on_boot", "guest_enabled"):
                if k in body and body[k] is not None:
                    pol[k] = bool(body[k])
            if "default_account_id" in body and body["default_account_id"] is not None:
                pol["default_account_id"] = str(body["default_account_id"])
            if not pol["guest_enabled"] and sess["is_guest"]:
                fallback = ACC_STATE["accounts"][0]
                ACC_STATE["session"] = {
                    "account_id": fallback["id"], "display_name": fallback["display_name"], "role": fallback["role"],
                    "avatar": fallback["avatar"], "color": fallback["color"], "is_guest": False,
                    "locked": True, "picker_required": True, "elevated_until": 0,
                }
            return self.j({"ok": True, "device_policy": pol, "session": ACC_STATE["session"]})
        if p == "/api/accounts/parental":
            sess = ACC_STATE["session"]
            if sess["locked"] or sess["is_guest"] or sess["role"] != "admin":
                return self.j_status(403, {"error": "account.err.adminRequired"})
            aid = str(body.get("account_id") or body.get("id") or "").strip()
            pol = _parental_policy_for(aid)
            src = body["policy"] if isinstance(body.get("policy"), dict) else body
            for k in ("mode", "allowed_tiles", "blocked_tiles", "blocked_cats", "max_age_rating", "daily_limit_min",
                      "bedtime_start", "bedtime_end", "allow_yt_search", "allow_browser", "allow_power_menu"):
                if k in src:
                    pol[k] = src[k]
            return self.j({"ok": True, "policy": pol, "status": _parental_status(aid)})
        if p == "/api/accounts/parental/override":
            admin_id = str(body.get("admin_id") or "acc-paul")
            factor = str(body.get("factor") or ("pin" if "pin" in body else "password"))
            secret = str(body.get("secret") if "secret" in body else body.get(factor, ""))
            code, err = _acc_verify(admin_id, factor, secret)
            if err is not None:
                return self.j_status(code, err)
            sess = ACC_STATE["session"]
            cid = str(body.get("child_id") or sess["account_id"])
            act = str(body.get("action") or "allow_once")
            if act == "allow_once":
                ACC_STATE["allow_once"].setdefault(cid, set()).add(str(body.get("tile_id") or ""))
            elif act == "add_minutes":
                u = ACC_STATE["parental_usage"].setdefault(cid, {"used_seconds": 0, "bonus_seconds": 0})
                u["bonus_seconds"] += int(body.get("minutes") or 15) * 60
            return self.j({"ok": True, "action": act, "parental": _parental_status(cid)})
        if p == "/api/osk/field":
            with OSKF["cv"]:
                OSKF["seq"] += 1
                OSKF["state"] = {k: body.get(k) for k in ("ev", "kind", "pos", "sid", "ok", "file")}
                OSKF["cv"].notify_all()
            print("[vorschau] Eingabefeld:", OSKF["state"], flush=True)
            return self.j({"ok": True})
        if p.startswith("/api/vpn/"):
            act = p.rsplit("/", 1)[-1]
            print("[vorschau] VPN:", act, body, flush=True)
            if act == "login":
                if len(str(body.get("account", ""))) != 16:
                    return self.j({"ok": False, "error": "format"})
                if str(body.get("account")).startswith("0000"):
                    return self.j({"ok": False, "error": "invalid", "msg": "InvalidAccount"})
                VPNM["mode"] = "off"
                return self.j({"ok": True})
            if act == "logout":
                VPNM["mode"] = "login"
            elif act == "connect":
                if body.get("cc"):
                    VPNM["loc"] = [body["cc"], body.get("city") or next(iter(VPN_CITY[body["cc"]][1]))]
                VPNM["mode"] = "on"
            elif act in ("disconnect",):
                VPNM["mode"] = "off"
            elif act == "toggle":
                VPNM["mode"] = "off" if VPNM["mode"] == "on" else "on"
            elif act == "set":
                k, v = str(body.get("key", "")), bool(body.get("value"))
                if k.startswith("dns."):
                    VPNM["opt"]["dns"][k[4:]] = v
                else:
                    VPNM["opt"][k] = v
                return self.j(VPNM["opt"])
            return self.j(vpn_summary())
        if p == "/api/report":                      # Einstellungen → System → Fehlerbericht: echter Bericht, nicht gespeichert
            sys.path.insert(0, str(REPO / "launcher"))
            import vsreport
            time.sleep(1.5)                         # Hinweis „Erstelle Fehlerbericht …“ sichtbar
            rep = vsreport.build({"running": [], "front": None})
            name = f"{vsreport.PREFIX}{vsreport.safe(rep['host'])}_{rep['time']:%Y-%m-%d_%H-%M-%S}.txt"
            return self.j({"name": name, "size": len(rep["text"].encode()), "overview": rep["overview"], "logs": rep["logs"]})
        if p == "/api/nowplaying/control":          # heisse Ecke oben links
            a = body.get("action")
            print("[vorschau] Musik:", a, flush=True)
            if a == "toggle":
                NOWP["paused"] = not NOWP["paused"]
            elif a in ("up", "down"):
                NOWP["volume"] = max(0, min(100, NOWP["volume"] + (5 if a == "up" else -5)))
            elif a in ("prev", "next"):
                NOWP["title"] = "Titel nach " + a
            return self.j(NOWP)
        if p == "/api/selfupdate/channel":         # wie launcher.py: nur noch zurueck zu Stable
            if body.get("channel") == "stable":
                UPD["channel"] = "stable"
            return self.j(updates({}))
        if p == "/api/keymap/capture":            # Vorschau: jede "Taste" nach 0,6 s, der Reihe nach
            time.sleep(0.6)
            role = CAPTURE_ROLES[KEYMAP["step"] % len(CAPTURE_ROLES)]
            KEYMAP["step"] += 1
            return self.j({"bind": {"role": role}, "label": role})
        if p == "/api/keymap/set":
            lay = dict(EMU_LAYOUTS[body.get("emu", "gba")]["buttons"])
            own = KEYMAP["own"].setdefault(body.get("emu", "gba"), {})
            km_role = (body.get("bind") or {}).get("role")
            cur = {b: own.get(b, r) for b, r in lay.items()}
            swapped = [o for o, r in cur.items() if km_role and o != body["button"] and r == km_role]
            for o in swapped:
                own[o] = cur[body["button"]]
            own[body["button"]] = km_role
            KEYMAP["own"][body.get("emu", "gba")] = {b: r for b, r in own.items() if r != lay[b]}
            return self.j(dict(keymap_payload(body.get("emu", "gba")), swapped=swapped))
        if p == "/api/keymap/reset":
            KEYMAP["own"][body.get("emu", "gba")] = {}
            return self.j(keymap_payload(body.get("emu", "gba")))
        if p == "/api/emuopts/set":
            game, oid, opt_val = body.get("game") or "", body.get("id"), body.get("value")
            if game:
                own = EMUOPTS_GAME.setdefault(game, {})
                own.pop(oid, None) if opt_val is None else own.__setitem__(oid, opt_val)
            else:
                EMUOPTS[oid] = opt_val
            return self.j(emuopts_payload(body.get("emu", "gba"), game))
        if p == "/api/keymap/cancel":
            return self.j({"ok": True})
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
        if p == "/api/tv/tune":                  # Player: Teststream; Sender mit "Fehler" im Namen scheitern
            ch = next((c for c in S.TV if c["key"] == body.get("key")), None) or S.TV[0]
            st["tv"] = ch
            PLAYER["recent"] = [ch] + [r for r in PLAYER["recent"] if r["key"] != ch["key"]][:14]
            url = "https://example.invalid/fehler.m3u8" if "Fehler" in ch["name"] else PLAYER["stream"]
            return self.j({"entry": ch, "url": url, "ref": "", "ua": "", "recent": PLAYER["recent"]})
        if p in ("/api/tv/fav", "/api/tv/unfav"):
            ch = next((c for c in S.TV if c["key"] == body.get("key")), None)
            st["tvfavs"] = [f for f in st["tvfavs"] if f["key"] != body.get("key")] + ([ch] if ch and p.endswith("/fav") else [])
            return self.j(st["tvfavs"])
        if p.startswith("/api/yt/"):                 # YouTube Light: echter Launcher-Code mit yt-dlp-Attrappe
            Y = yt()
            act = p[len("/api/yt/"):]
            fn = {"settings": lambda: Y.save_settings(body),
                  "resolve": lambda: Y.resolve(str(body.get("id") or ""), str(body.get("quality") or ""), str(body.get("lang") or "de")),
                  "progress": lambda: Y.progress(body), "later": lambda: Y.later_set(body), "sub": lambda: Y.sub_set(body),
                  "import": Y.import_subs, "history/remove": lambda: Y.history_remove(str(body.get("id") or "") or "-"),
                  "history/clear": lambda: Y.history_remove(""), "update": lambda: Y.update_ytdlp()}.get(act)
            try:
                return self.j(fn() if fn else {})
            except PLAYER["L"].YtError as e:
                return self.raw(502, json.dumps({"error": e.reason, "msg": str(e)}).encode(), "application/json")
        if p.startswith("/api/dl/"):                # Musik suchen: echter Launcher-Code (VS_IA_URL/VS_ITUNES_URL/VS_YTDLP: Testserver)
            media()
            D = PLAYER["L"].MUSICDL
            try:
                if p == "/api/dl/settings":
                    return self.j(D.save_settings(body.get("sources")))
                if p == "/api/dl/search":
                    return self.j(D.search(body.get("q")))
                if p == "/api/dl/get":
                    return self.j(D.get(body.get("key")))
            except ValueError as e:
                self.send_response(404); self.end_headers(); self.wfile.write(json.dumps({"error": str(e)}).encode()); return
        if p == "/api/media/covers/scan":
            media()
            L = PLAYER["L"]
            L.COVERS.scan(Path(os.environ["HOME"]) / "share" / "Musik")
            return self.j(L.COVERS.status())
        if p == "/api/media/covers/refresh":
            media()
            L = PLAYER["L"]
            f = L.MEDIA.resolve(body.get("path", ""))
            if f:
                L.COVERS.refresh_track(f)
            return self.j({"ok": bool(f)})
        if p == "/api/media/covers/embed":
            media()
            PLAYER["covers_embed"] = bool(body.get("on"))
            PLAYER["L"].MEDIA.art_done.clear()
            return self.j(PLAYER["L"].COVERS.status())
        if p == "/api/media/covers/auto":
            media()
            PLAYER["covers_auto"] = bool(body.get("on"))
            return self.j(PLAYER["L"].COVERS.status())
        if p == "/api/media/resume":
            media().resume_set(body.get("path", ""), body.get("pos"), body.get("dur"))
            return self.j({"ok": True})
        if p in ("/api/apps/install", "/api/apps/remove", "/api/apps/update"):
            JOB.clear()
            JOB.update({"state": "running", "action": p.rsplit("/", 1)[1], "name": body.get("id", ""), "app": body.get("id"),
                        "log": ["xbps-install -Sy …"], "n": 0, "t0": time.time(), "steps": [], "from": None, "to": None})
            return self.j(JOB)
        if p == "/api/install/start":
            INST.clear()
            cfg = body["config"]
            INST.update({"state": "running", "pct": 0, "phases": {}, "mode": cfg["mode"], "t0": time.time(), "cfg": cfg})
            safe_cfg = json.loads(json.dumps(cfg))
            if isinstance(safe_cfg.get("user"), dict):
                if safe_cfg["user"].get("password"):
                    safe_cfg["user"]["password"] = "***"
                if safe_cfg["user"].get("pin"):
                    safe_cfg["user"]["pin"] = "***"
            print("Installer-Konfiguration:", json.dumps(safe_cfg, ensure_ascii=False), flush=True)
            return self.j(inst_status())
        if p == "/api/install/retry":
            LIVE["fail"] = False
            INST.update(state="running", error=None, t0=time.time() - 15)
            return self.j(inst_status())
        if p in ("/api/install/keymap", "/api/install/gparted"):
            return self.j({"keymap": body.get("keymap"), "running": True})
        if p == "/api/install/savelog":
            return self.j({"ok": False, "code": "no_usb"})
        if p == "/api/bluetooth/rename":         # eigener Name (leer = Geraetename)
            BT["names"][body.get("mac", "")] = " ".join(str(body.get("name", "")).split())[:40]
            return self.j({"ok": True, "status": bt_status()})
        if p == "/api/bluetooth/pair":           # Koppeln: Tastatur-Code 3 s anzeigen, dann je nach Geraet Erfolg/Fehler
            BT.update(pairing=body.get("mac"), prompt={"mac": body.get("mac"), "code": "482913"})
            time.sleep(3)
            BT.update(pairing=None, prompt=None)
            ok = not body.get("mac", "").endswith("01")
            return self.j({"ok": ok, "error": None if ok else "bt.err.timeout", "status": {}})
        if p.startswith("/api/roms/chd/"):
            act = p.rsplit("/", 1)[-1]
            print("[vorschau] CHD:", act, body, flush=True)
            if act == "start":
                CHDM.update(t0=time.time(), stop=False, job={"state": "running", "system": body.get("system"),
                            "delete": body.get("delete") is True, "i": 1, "n": len(CHD_GAMES), "name": CHD_GAMES[0],
                            "step": "convert", "pct": 0.0, "ok": 0, "failed": [], "saved": 0, "error": ""})
                return self.j({"job": chd_status()["job"]})
            if act == "decline":
                CHDM["mode"] = "pill"
            elif act == "cancel":
                CHDM["stop"] = True
            return self.j(chd_status())
        if p == "/api/roms/launch":              # wie der Launcher: Spiel laeuft unter der Kennung der Kachel
            tid = str(body.get("system", ""))
            ok, reason, ov = _parental_check_tile(tid, consume_once=True)
            if not ok:
                return self.j_status(403, {"error": "account.blocked", "reason": reason, "tile_id": tid, "override_allowed": ov})
            if tid not in st["running"]:
                st["running"].append(tid)
            return self.j({"result": "started", "running": st["running"]})
        if p.startswith("/api/launch/"):
            tid = p.rsplit("/", 1)[1]
            ok, reason, ov = _parental_check_tile(tid, consume_once=True)
            if not ok:
                return self.j_status(403, {"error": "account.blocked", "reason": reason, "tile_id": tid, "override_allowed": ov})
            if tid not in st["running"]:
                st["running"].append(tid)
            return self.j({"running": st["running"]})
        if p.startswith("/api/close/"):
            tid = p.rsplit("/", 1)[1]
            st["running"] = [t for t in st["running"] if t != tid]
            return self.j({"running": st["running"]})
        if p.startswith("/api/audio/"):          # Ton: Beispielgeraete aus sampledata.py umschalten
            a = S.SETTINGS["audio"]
            d = next((x for x in a["devices"] if x["key"] == body.get("key")), None)
            if p.endswith("/device") and d:
                for x in a["devices"]:
                    x["active"] = x is d
            elif p.endswith("/format") and d:
                d["format"] = body.get("format")
                if d["kind"] == "bt":
                    d["mic"] = False
            elif p.endswith("/mic") and d:
                d["mic"] = bool(body.get("on"))
                if d["kind"] == "bt":
                    d["format"] = None if d["mic"] else "a2dp:auto"
            elif p.endswith("/auto"):
                a["auto"] = bool(body.get("on"))
            return self.j(settings())
        if p == "/api/net/prefer":                 # Kabel/WLAN bevorzugen: Haken wandert mit
            n = S.SETTINGS["net"]
            n["mode"] = body.get("mode") if body.get("mode") in ("wired", "wifi", "both") else "both"
            for l in n["links"]:
                l["connected"] = n["mode"] in ("both", l["type"])
                l["internet"] = l["connected"] and (n["mode"] != "both" or l["type"] == "wired")
            return self.j(settings())
        if p in ("/api/net/disconnect", "/api/net/connect"):
            n = S.SETTINGS["net"]
            on = p.endswith("/connect")
            for l in n["links"]:
                if l["type"] == body.get("type"):
                    l.update(connected=on, ready=not on, name=l["name"] if on else "", internet=on)
            return self.j(settings())
        if p == "/api/wifi/connect":                # verbunden: WLAN-Zeile unter Verbindung
            n = S.SETTINGS["net"]
            n["links"] = [l for l in n["links"] if l["type"] != "wifi"] + [
                {"dev": "wlp2s0", "type": "wifi", "connected": True, "name": body.get("ssid", ""), "ip": "172.20.10.3",
                 "internet": n.get("mode") == "wifi"}]
        if p.startswith("/api/settings/") or p == "/api/wifi/connect":
            aid = ACC_STATE["session"]["account_id"] or "acc-paul"
            aprefs = _acc_prefs_for(aid)
            if p.endswith("/theme"):
                S.SETTINGS["theme"] = body.get("theme")
                aprefs["theme"] = S.SETTINGS["theme"]
            if p.endswith("/scale"):
                S.SETTINGS["scale"] = body.get("scale")
                aprefs["scale"] = S.SETTINGS["scale"]
            if p.endswith("/lang"):
                S.SETTINGS["lang"] = body.get("lang")
                aprefs["lang"] = S.SETTINGS["lang"]
                return self.j({"lang": body.get("lang")})
            if p.endswith("/padmouse"):
                STATE["padmouse"] = bool(body.get("on"))
            if p.endswith("/sounds"):
                snd = S.SETTINGS.setdefault("sounds", {"on": True, "volume": 70, "preset": "void",
                                                      "presets": ["void", "retro", "minimal"], "custom": 0})
                if "on" in body:
                    snd["on"] = bool(body["on"])
                    aprefs["ui_sounds"] = snd["on"]
                if "volume" in body:
                    snd["volume"] = max(1, min(100, int(round(float(body["volume"])))))
                    aprefs["ui_sounds_volume"] = snd["volume"]
                if body.get("preset") in ("void", "retro", "minimal"):
                    snd["preset"] = body["preset"]
                    aprefs["ui_sounds_preset"] = snd["preset"]
            if p.endswith("/osk"):
                o = S.SETTINGS.setdefault("osk", {"choice": "auto", "mode": "auto"})
                if "layout" in body:
                    o["choice"] = body.get("layout") or "auto"
                if "mode" in body:
                    o["mode"] = body.get("mode")
            if p.endswith("/resolution"):
                d = S.SETTINGS["displays"][0]
                d["current"] = body.get("mode") or d["current"]
                r = body.get("rate")
                S.SETTINGS["rate"] = float(r) if r else None
                d["rate"] = float(r) if r else max((x for x in d["rates"].get(d["current"], [60.0]) if abs(x - 60) < 0.5),
                                                   default=max(d["rates"].get(d["current"], [60.0])))
            if p.endswith("/matchrate"):
                S.SETTINGS["match_rate"] = bool(body.get("on"))
            if p.endswith("/gamefx"):
                S.SETTINGS["game_fx"] = {"mode": body.get("mode"), "ready": os.environ.get("VS_GAMEFX") != "install",
                                         "busy": False, "failed": os.environ.get("VS_GAMEFX") == "failed"}
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
    ap.add_argument("--player", choices=["tv", "media", "yt"], help="Player statt Startseite: Fernsehen, Videos & Musik, YouTube Light")
    ap.add_argument("--yt-demo", action="store_true", help="YouTube Light: Hinweis schon bestaetigt, Abos, Verlauf und Spaeter-Liste")
    ap.add_argument("--stream", help="Stream/Datei fuer den Fernseh-Player (Standard: Testbild von mpv)")
    ap.add_argument("--home", help="Ordner, der fuer die Mediathek als Home gilt (darin share/Videos, share/Musik)")
    ap.add_argument("--arg", default="", help="Startargument des Players (Sender bzw. Datei/Ordner)")
    a = ap.parse_args()
    if a.stream:
        PLAYER["stream"] = a.stream
    YTP["demo"] = a.yt_demo
    if a.home:
        os.environ["HOME"] = str(Path(a.home).resolve())
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
    PROBE["lang"] = S.SETTINGS.get("lang") or "de"           # wie der Launcher: Sprache der Oberflaeche
    PROBE["kb"] = _li["INSTALL_DEFAULTS"].get(PROBE["lang"], ("de",))[0]
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    if os.environ.get("VS_PARENTAL_WARN") == "1" or os.environ.get("VS_PARENTAL_LOCKED") == "1":
        def _push_parental() -> None:
            time.sleep(1.5)
            with OSKF["cv"]:
                OSKF["seq"] += 1
                if os.environ.get("VS_PARENTAL_LOCKED") == "1":
                    OSKF["state"] = {"ev": "account_locked", "reason": "daily_limit", "remaining_seconds": 0}
                else:
                    OSKF["state"] = {"ev": "account_warn", "reason": "daily_limit", "remaining_seconds": 240, "minutes": 4}
                OSKF["cv"].notify_all()
        threading.Thread(target=_push_parental, daemon=True).start()
    env = dict(os.environ, VS_API=f"http://127.0.0.1:{PORT}", VS_SIZE=a.size, VS_DEMO="1")
    if a.shot or a.keys:
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        env.setdefault("QT_QUICK_BACKEND", "software")
        env["VS_KEYS"] = a.keys
        if a.shot:
            env["VS_SCREENSHOT"] = a.shot
    t0 = time.monotonic()
    if a.player:
        prog = [sys.executable, str(REPO / "launcher" / "qt" / "voidstation-player.py"), "--" + a.player]
        prog += [a.arg or (S.TV[0]["key"] if a.player == "tv" else "")]
        if a.player == "yt":
            yt()                                                  # Wegwerf-Ordner und Beispieldaten vor dem Start
        env["VS_BASE"] = str(PLAYER["tmp"] or Path("/tmp"))      # Steuer-Socket nicht im Repo
        if a.shot or a.keys:
            env.pop("QT_QPA_PLATFORM", None) if os.environ.get("DISPLAY") else None
            env.pop("QT_QUICK_BACKEND", None)
        r = subprocess.run([x for x in prog if x != ""], env=env)
    else:
        r = subprocess.run([sys.executable, str(REPO / "launcher" / "qt" / "voidstation-home.py")], env=env)
    print(f"beendet nach {time.monotonic() - t0:.1f} s, Code {r.returncode}")
    srv.shutdown()


if __name__ == "__main__":
    main()
