# SPDX-License-Identifier: GPL-3.0-or-later
"""
Gemeinsame Teile der Qt-Programme (Startseite voidstation-home.py und Player voidstation-player.py):
  * Farben aus den CSS-Themes (web/themes/<name>.css), Texte aus web/i18n/<sprache>.json
  * Gamepad ueber evdev (python3-evdev) mit Tastenwiederholung wie im Web
  * VsBase: Bruecke zur QML-Oberflaeche (Launcher-Aufrufe in Threads, Texte, Farben, Symbole)
  * QML-Zwischenspeicher nach Updates verwerfen
"""
import base64
import ctypes
import hashlib
import json
import os
import re
import shutil
import struct
import sys
import threading
import time
import urllib.error
import urllib.request
import weakref
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QEvent, QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication

T0 = time.monotonic()
HERE = Path(__file__).resolve().parent
WEB = Path(os.environ.get("VS_WEB") or HERE.parent / "web")
API = os.environ.get("VS_API", "http://127.0.0.1:8765").rstrip("/")
PADMOUSE_NAME = "VoidStation Controller-Maus"    # virtuelle Maus der Startseite – kein Controller
LOG_PREFIX = "home"                              # setzt das jeweilige Programm


def log(*a):
    print(f"[{LOG_PREFIX}]", *a, file=sys.stderr, flush=True)


sys.path.insert(0, str(HERE))
if str(HERE.parent) not in sys.path:
    sys.path.append(str(HERE.parent))
from icons import ICONS  # noqa: E402
import vssound  # noqa: E402
try:
    from vsaccount.storage import API_TOKEN_HEADER, read_api_token  # noqa: E402
except ImportError:
    API_TOKEN_HEADER = "X-VS-Token"

    def read_api_token(runtime_dir: Path | None = None) -> str:
        base = runtime_dir or Path(os.environ.get("XDG_RUNTIME_DIR", "").strip()
                                   or f"/tmp/voidstation-runtime-{os.getuid()}")
        path = base / "voidstation-api.token"
        try:
            if path.is_symlink() or not path.is_file():
                return ""
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""


# ---------------------------------------------------------------------------
#  Farben aus den CSS-Themes (web/themes/<name>.css)
# ---------------------------------------------------------------------------
def _hex2(v):
    return f"{max(0, min(255, int(round(v)))):02x}"


def css_color(v):
    """CSS-Farbe -> Qt-Farbe (#rrggbb oder #aarrggbb). rgba(...) kennt QML nicht."""
    v = v.strip()
    m = re.match(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+%?)\s*)?\)$", v)
    if m:
        r, g, b = (float(x) for x in m.groups()[:3])
        a = m.group(4)
        alpha = 1.0 if a is None else (float(a[:-1]) / 100 if a.endswith("%") else float(a))
        return "#" + (_hex2(alpha * 255) if alpha < 1 else "") + _hex2(r) + _hex2(g) + _hex2(b)
    if re.match(r"#[0-9a-fA-F]{3}$", v):
        return "#" + "".join(c * 2 for c in v[1:])
    if re.match(r"#[0-9a-fA-F]{8}$", v):                       # CSS #rrggbbaa -> Qt #aarrggbb
        return "#" + v[7:9] + v[1:7]
    return v


def _camel(name):
    return re.sub(r"-([a-z0-9])", lambda m: m.group(1).upper(), name)


def _lum(col):
    c = col.lstrip("#")[-6:]
    try:
        r, g, b = (int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return 0
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def theme_names():
    found = sorted(p.stem for p in (WEB / "themes").glob("*.css"))
    return found or ["default-dark"]


def theme_tokens(name):
    """Alle --variablen eines Themes (Grundlage: default-dark), aufgeloeste var(), Qt-Farben, camelCase."""
    raw = {}

    def read(n):
        try:
            css = (WEB / "themes" / f"{n}.css").read_text(encoding="utf-8")
        except OSError:
            return ""
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        root = re.search(r"^[^{]*:root[^{]*\{(.*?)\}", css, re.S | re.M)
        for k, v in re.findall(r"--([\w-]+)\s*:\s*([^;]+);", root.group(1) if root else ""):
            raw[k] = v.strip()
        return css

    read("default-dark")
    css = read(name) if name != "default-dark" else read("default-dark")

    def resolve(v, depth=0):
        m = re.fullmatch(r"var\(--([\w-]+)\)", v.strip())
        if m and depth < 8:
            return resolve(raw.get(m.group(1), ""), depth + 1)
        return v

    out = {}
    for k, v in raw.items():
        v = resolve(v)
        if k in ("f", "u", "rows", "gap", "pad-x", "ease", "focus-ring"):
            continue
        out[_camel(k)] = css_color(v)
    # Abgeleitet: Schrift auf farbigen Kacheln und auf aktiven Knoepfen (helle Themes ueberschreiben das im CSS)
    light = _lum(out.get("bgMain", "#000000")) > 0.5
    out["light"] = light
    out["tileText"] = "#ffffff" if light else out.get("textPrimary", "#ecebe8")
    out["tileSub"] = "#d9ffffff" if light else out.get("textSecondary", "#b8ecebe8")
    m = re.search(r"\.pill\.on[^{]*\{[^}]*?color:\s*([^;]+);", css or "")
    out["pillOnText"] = css_color(m.group(1)) if m else out.get("textPrimary", "#ecebe8")
    return out


# ---------------------------------------------------------------------------
#  Bauart des Controllers: welche Beschriftung tragen die Tasten?
# ---------------------------------------------------------------------------
PAD_STYLES = ("xbox", "ps", "nintendo")
_RE_NINTENDO = re.compile(r"nintendo|pro controller|joy-?con|\bswitch\b", re.I)
_RE_PS = re.compile(r"sony|playstation|wireless controller|dualsense|dualshock|\bps[345]\b", re.I)
# Vor _RE_PS: Xbox-Pads per Bluetooth heissen "Xbox Wireless Controller" (DualShock 4: "Wireless Controller")
_RE_XBOX = re.compile(r"xbox|x-box|microsoft", re.I)


def pad_style(name, vendor=0):
    """xbox (A/B/X/Y, LB/RB, LT/RT – auch alle Pads ohne eigene Beschriftung), ps (✕ ○ □ △, L1/R1, L2/R2) oder
    nintendo (B/A/Y/X, L/R, ZL/ZR). Erkennung ueber die USB-Herstellerkennung, sonst ueber den Geraetenamen.
    Die Tasten selbst bleiben nach Lage belegt (Linux-Gamepad-Norm: BTN_SOUTH = untere Taste): auf einem
    Nintendo-Pad ist "a" (bestaetigen) also die untere Taste mit der Aufschrift B – genau das zeigen die Hinweise."""
    if vendor == 0x057e or _RE_NINTENDO.search(name or ""):
        return "nintendo"
    if vendor == 0x045e or _RE_XBOX.search(name or ""):
        return "xbox"
    if vendor == 0x054c or _RE_PS.search(name or ""):
        return "ps"
    return "xbox"


# Aufschriften je Bauart (Rolle wie in Gamepad.KEYS: a = untere Taste, b = rechte, x = linke, y = obere)
PAD_LABELS = {
    "xbox": {"a": "A", "b": "B", "x": "X", "y": "Y", "lb": "LB", "rb": "RB", "lt": "LT", "rt": "RT",
             "l3": "LS", "r3": "RS"},
    "ps": {"lb": "L1", "rb": "R1", "lt": "L2", "rt": "R2", "l3": "L3", "r3": "R3"},
    "nintendo": {"a": "B", "b": "A", "x": "Y", "y": "X", "lb": "L", "rb": "R", "lt": "ZL", "rt": "ZR",
                 "l3": "LS", "r3": "RS"},
}


# Tasten wie auf aktuellen Controllern: dunkler Koerper, helle Aufschrift; die vier Haupttasten in ihren
# Originalfarben (entschieden 29.10.2026). Nintendo-Pads sind einfarbig, darum dort hell.
KEY_FILL = "#2f343a"                # Tastenkoerper (auch auf hellen Themes und auf dem grauen Update-Bildschirm)
KEY_EDGE = "#565c64"                # feiner Rand, damit die Taste auf dunklem Grund nicht verschwindet
KEY_TEXT = "#e4e4e1"
PAD_COLORS = {
    "xbox": {"a": "#6cc644", "b": "#ef4f45", "x": "#4a95ec", "y": "#f4c430"},
    "ps": {"a": "#8db0ee", "b": "#f06464", "x": "#e996d4", "y": "#46cdae"},   # ✕ blau, ○ rot, □ rosa, △ gruen
    "nintendo": {},
}


def pad_glyph_svg(role, style, h):
    """Tasten-Symbol als SVG in genau h Pixel Hoehe (scharf, ohne Skalieren): dunkle Taste, farbige bzw. helle
    Aufschrift. Keine Markenlogos: Guide ist ein Haus, bei PlayStation die Aufschrift "PS".
    -> (svg, Breite in Pixeln)"""
    style = style if style in PAD_STYLES else "xbox"
    lc = PAD_COLORS[style].get(role, KEY_TEXT)
    font = 'font-family="Noto Sans, DejaVu Sans, sans-serif" font-weight="bold" text-anchor="middle"'
    lab = PAD_LABELS[style].get(role, "")
    K = f'fill="{KEY_FILL}" stroke="{KEY_EDGE}" stroke-width="1"'         # Tastenkoerper
    L = f'fill="{lc}"'                                                     # Aufschrift

    def S(sw=2.2):                                                         # Linie in der Aufschrift-Farbe
        return (f'fill="none" stroke="{lc}" stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round"')
    if role in ("a", "b", "x", "y"):
        vw, body = 24, f'<circle cx="12" cy="12" r="11" {K}/>'
        if style == "ps":
            body += {"a": f'<path d="M8 8 L16 16 M16 8 L8 16" {S()}/>',
                     "b": f'<circle cx="12" cy="12" r="4.6" {S()}/>',
                     "x": f'<rect x="7.8" y="7.8" width="8.4" height="8.4" {S()}/>',
                     "y": f'<path d="M12 6.9 L17.2 15.9 H6.8 Z" {S()}/>'}[role]
        else:
            body += f'<text x="12" y="17" font-size="14" {font} {L}>{lab}</text>'
    elif role in ("lb", "rb"):
        vw = 34
        body = (f'<rect x="1" y="4" width="32" height="16" rx="8" {K}/>'
                f'<text x="17" y="16" font-size="11" {font} {L}>{lab}</text>')
    elif role in ("lt", "rt"):
        vw = 32
        body = (f'<path d="M2 21 V11 Q2 3 10 3 H22 Q30 3 30 11 V21 Z" {K}/>'
                f'<text x="16" y="16.5" font-size="11" {font} {L}>{lab}</text>')
    elif role in ("start", "select"):
        vw, body = 24, f'<circle cx="12" cy="12" r="10" {K}/>'
        if style == "nintendo":
            body += f'<path d="{"M7.5 12 H16.5 M12 7.5 V16.5" if role == "start" else "M7.5 12 H16.5"}" {S()}/>'
        elif role == "start":
            body += f'<path d="M7.5 8.5 H16.5 M7.5 12 H16.5 M7.5 15.5 H16.5" {S(1.8)}/>'
        elif style == "ps":                                   # Create/Share: Pfeil nach oben aus einer Schale
            body += f'<path d="M12 6.8 V13.5 M9.2 9.4 L12 6.6 L14.8 9.4 M7.5 13 V16.5 H16.5 V13" {S(1.8)}/>'
        else:                                                 # View: zwei uebereinanderliegende Fenster
            body += (f'<rect x="6.5" y="7" width="7.5" height="6" rx="1" {S(1.6)}/>'
                     f'<rect x="10" y="11" width="7.5" height="6" rx="1" fill="{KEY_FILL}" stroke="{lc}" stroke-width="1.6"/>')
    elif role == "guide":
        vw, body = 24, f'<circle cx="12" cy="12" r="11" {K}/>'
        if style == "ps":
            body += f'<text x="12" y="15.8" font-size="10" {font} {L}>PS</text>'
        else:
            body += f'<path d="M6.8 11.6 L12 7 L17.2 11.6 M8.4 10.4 V16.8 H15.6 V10.4" {S(1.9)}/>'
    elif role in ("l3", "r3"):                                # Stick: Taste mit Ring
        vw = 24
        body = (f'<circle cx="12" cy="12" r="11" {K}/>'
                f'<circle cx="12" cy="12" r="8.3" fill="none" stroke="{KEY_EDGE}" stroke-width="1.2"/>'
                f'<text x="12" y="15.6" font-size="9" {font} {L}>{lab}</text>')
    else:
        return "", 0
    w = max(1, round(h * vw / 24))
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {vw} 24">{body}</svg>')
    return svg, w


# ---------------------------------------------------------------------------
#  Gamepad (evdev): Zustand im Lese-Thread, Tastendruecke + Wiederholung im Qt-Thread
# ---------------------------------------------------------------------------

# Japanisch, Koreanisch, Chinesisch: Schriftzeichen aus der passenden Fassung von Noto Sans CJK. Noto Sans hat keine
# CJK-Zeichen; die Ersatzschrift der Systemauswahl ist sonst oft eine andere Fassung (dieselben Zeichen sehen in
# Japan, Korea, China und Taiwan verschieden aus). Alle Fassungen stecken in noto-fonts-cjk.
# Hindi, Tamil, Malayalam, Thai: ebenso die Noto-Schrift der jeweiligen Schrift (aus noto-fonts-ttf), damit die Wahl
# nicht von der Reihenfolge der installierten Schriften abhaengt.
CJK_FONTS = {"ja": "Noto Sans CJK JP", "ko": "Noto Sans CJK KR", "zh-CN": "Noto Sans CJK SC", "zh-TW": "Noto Sans CJK TC",
             "hi": "Noto Sans Devanagari", "ta": "Noto Sans Tamil", "ml": "Noto Sans Malayalam", "th": "Noto Sans Thai"}


def cjk_font(lang):
    if QGuiApplication.instance() is None:
        return
    cjk = CJK_FONTS.get(lang)
    for fam in ("Noto Sans", "DejaVu Sans"):
        QFont.removeSubstitutions(fam)
        if cjk and cjk in QFontDatabase.families():
            QFont.insertSubstitution(fam, cjk)


class Gamepad:
    REPEAT = {"left", "right", "up", "down", "lb", "rb", "lt", "rt"}
    # Controller mit Kernel-Treiber (Xbox, PlayStation, Switch, 8BitDo, Steam …): einheitliche Tasten
    KEYS = {304: "a", 305: "b", 307: "x", 308: "y", 310: "lb", 311: "rb", 312: "lt", 313: "rt",
            314: "select", 315: "start", 544: "up", 545: "down", 546: "left", 547: "right"}
    # Einfache USB-Pads ohne eigenen Treiber (DragonRise u. a., Tasten ab BTN_TRIGGER): Taste 3 unten = A,
    # Taste 2 rechts = B (SNES- wie PlayStation-Nachbauten)
    GENERIC = {288: "y", 289: "b", 290: "a", 291: "x", 292: "lb", 293: "rb", 294: "lt", 295: "rt",
               296: "select", 297: "start"}
    # Joysticks / Flugsteuerung: Abzug = A, Daumentaste = B
    JOY = {288: "a", 289: "b", 290: "x", 291: "y", 292: "lb", 293: "rb", 294: "select", 295: "start"}
    # Arcade-Sticks u. ae. mit Tasten ab BTN_0
    MISC = {256: "a", 257: "b", 258: "x", 259: "y", 260: "lb", 261: "rb", 262: "select", 263: "start"}
    # {"<Geraetename oder vid:pid>": {"<Code>": "a", …, "style": "ps"}} – eigene Belegung bzw. Bauart (Beschriftung)
    OVERRIDE = Path.home() / ".config/voidstation/pads.json"

    @classmethod
    def style_of(cls, dev):
        """Bauart (xbox/ps/nintendo) eines Controllers; pads.json kann sie mit "style" festlegen."""
        info = dev.info
        try:
            own = json.loads(cls.OVERRIDE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            own = {}
        for i in (dev.name, f"{info.vendor:04x}:{info.product:04x}"):
            ent = own.get(i) if isinstance(own, dict) else None
            if isinstance(ent, dict) and ent.get("style") in PAD_STYLES:
                return ent["style"]
        return pad_style(dev.name, info.vendor)

    @classmethod
    def keymap(cls, dev, keys, abs_codes):
        """Tastenbelegung fuer ein Geraet; None = kein Controller."""
        from evdev import ecodes as E
        info = dev.info
        ids = (dev.name, f"{info.vendor:04x}:{info.product:04x}")
        try:
            own = json.loads(cls.OVERRIDE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            own = {}
        for i in ids:
            if isinstance(own.get(i), dict):
                return {int(k): str(v) for k, v in own[i].items() if str(k).isdigit()}
        if E.BTN_SOUTH in keys:
            return dict(cls.KEYS)
        pen = keys & {E.BTN_TOUCH, E.BTN_TOOL_PEN, E.BTN_STYLUS, E.BTN_TOOL_FINGER}
        if E.BTN_TRIGGER in keys and not pen:
            stick = abs_codes & {E.ABS_THROTTLE, E.ABS_RUDDER}    # Schubregler/Ruder: Flugsteuerung
            m = dict(cls.JOY if stick else cls.GENERIC)
            m.update({k: v for k, v in cls.KEYS.items() if k >= 544})      # Steuerkreuz als Tasten
            return m
        if E.BTN_0 in keys and not pen and {E.ABS_X, E.ABS_Y} <= abs_codes and "wacom" not in dev.name.lower():
            return dict(cls.MISC)
        return None

    def __init__(self):
        self.devs = {}             # pfad -> (geraet, achsen-info, tastenbelegung)
        self.state = {}            # (geraet, taste) -> gedrueckt
        self.lock = threading.Lock()
        self.names = []            # neu erkannte Controller (fuer die Meldung)
        self.trig = set()          # (geraet, achse): Achse ist eine Schultertaste (LT/RT)
        self.raw = {}              # (geraet, "rx"/"ry"/"ly"/"r3") -> Stick -1…1 bzw. gedrueckt (Controller-Maus)
        self.rx_dev = set()        # Geraete mit eigenem rechten Stick (ABS_RX/RY)
        self.generic = set()       # einfache USB-Pads (Tasten ab BTN_TRIGGER, R3 = BTN_BASE6)
        self.styles = {}           # geraet -> Bauart (xbox/ps/nintendo)
        self.last_style = ""       # Bauart des zuletzt benutzten Controllers
        # Kein Takt im Leerlauf: Wer den Zustand liest, wird bei Aenderungen geweckt statt staendig nachzufragen.
        self.listeners = []        # Rueckrufe (aus dem Geraete-Thread) bei Tasten, neuen oder abgezogenen Controllern
        self.changed = threading.Event()   # gesetzt bei jeder Aenderung, auch an den Sticks (Controller-Maus)
        try:
            import evdev  # noqa: F401
        except ImportError:
            log("python3-evdev fehlt – Gamepad aus")
            return
        threading.Thread(target=self._run, daemon=True).start()

    def grab(self, on):
        """Controller exklusiv nehmen (heisse Ecke offen): Das Spiel bekommt die Eingaben solange nicht."""
        for dev, *_ in list(self.devs.values()):
            try:
                if on:
                    dev.grab()
                else:
                    dev.ungrab()
            except OSError:
                pass

    def on_change(self, cb):
        """cb() kommt aus dem Geraete-Thread, sobald sich Tasten aendern oder ein Controller kommt bzw. geht.
        Methoden werden nur schwach gehalten: Sonst hielte das Gamepad die Pumpe und ueber deren active() die
        Bruecke fest (Kreis vs -> pad -> pump -> vs), und Python raeumte sie beim Beenden zu beliebiger Zeit ab."""
        self.listeners.append(weakref.WeakMethod(cb) if hasattr(cb, "__self__") else (lambda: cb))

    def _notify(self, keys=True):
        self.changed.set()
        if keys:
            for ref in list(self.listeners):
                cb = ref()
                if cb is None:
                    self.listeners.remove(ref)
                    continue
                try:
                    cb()
                except Exception as e:  # noqa: BLE001  – der Geraete-Thread darf daran nicht sterben
                    log("Gamepad-Rueckruf:", e)

    def wait_change(self, timeout=None):
        """Fuer Threads (Controller-Maus): schlafen, bis sich am Controller etwas aendert."""
        self.changed.wait(timeout)
        self.changed.clear()

    def pressed(self):
        with self.lock:
            return {k for (_d, k), v in self.state.items() if v}

    def _set(self, dev, key, on):
        with self.lock:
            if self.state.get((dev, key), False) == on:
                return                                # Stick bewegt sich nur innerhalb der Richtung: nichts Neues
            self.state[(dev, key)] = on
            if on:
                self.last_style = self.styles.get(dev, self.last_style)
        self._notify()

    def style(self):
        """Bauart fuer die Tasten-Hinweise: die des zuletzt benutzten Controllers, "" = keiner angeschlossen."""
        with self.lock:
            if not self.styles:
                return ""
            if self.last_style not in self.styles.values():          # zuletzt benutzter wurde abgezogen
                self.last_style = next(iter(self.styles.values()))
            return self.last_style

    def _raw(self, dev, key, val):
        with self.lock:
            if self.raw.get((dev, key)) == val:
                return
            self.raw[(dev, key)] = val
        self._notify(keys=False)

    def mouse_state(self):
        """Fuer die Controller-Maus: staerkster Ausschlag je Achse ueber alle Controller, R3, untere/rechte Taste,
        dazu L2 und L3 (zusammen: Bildschirmtastatur ueber dem Programm)."""
        out = {"rx": 0.0, "ry": 0.0, "ly": 0.0, "r3": False, "l3": False, "a": False, "b": False, "lt": False}
        with self.lock:
            for (_d, k), v in self.raw.items():
                if k in ("r3", "l3"):
                    out[k] = out[k] or bool(v)
                elif abs(v) > abs(out[k]):
                    out[k] = v
            for (_d, k), v in self.state.items():
                if k in ("a", "b", "lt") and v:
                    out[k] = True
        return out

    def _run(self):
        import selectors
        import evdev
        from evdev import ecodes as E
        sel = selectors.DefaultSelector()
        known = self.devs
        last = 0.0
        dev: Any                                       # evdev.InputDevice (auch key.fileobj unten)
        while True:
            if time.monotonic() - last > 3:
                last = time.monotonic()
                for path in evdev.list_devices():
                    if path in known:
                        continue
                    try:
                        dev = evdev.InputDevice(path)
                        caps = dev.capabilities()
                        keys = set(caps.get(E.EV_KEY, []))
                        axes = {}
                        for code, info in caps.get(E.EV_ABS, []):
                            axes[code] = info
                        kmap = self.keymap(dev, keys, set(axes))
                        if kmap is None or dev.name == PADMOUSE_NAME:
                            dev.close()
                            continue
                        known[path] = (dev, axes, kmap)
                        if E.ABS_RX in axes:
                            self.rx_dev.add(path)
                        if kmap.get(296) == "select":
                            self.generic.add(path)
                        style = self.style_of(dev)
                        sel.register(dev, selectors.EVENT_READ)
                        with self.lock:
                            self.names.append(dev.name)
                            self.styles[path] = style
                            if not self.last_style:
                                self.last_style = style
                        log("Controller:", dev.name, f"({style})")
                        self._notify()
                    except OSError:
                        pass
            for key, _ in sel.select(timeout=1):
                dev = key.fileobj
                _d, axes, kmap = known.get(dev.path, (None, {}, {}))
                try:
                    for ev in dev.read():
                        if ev.type == E.EV_KEY and ev.code in kmap:
                            self._set(dev.path, kmap[ev.code], ev.value != 0)
                        elif ev.type == E.EV_KEY and (ev.code == E.BTN_THUMBR or
                                                      (ev.code == E.BTN_BASE6 and dev.path in self.generic)):
                            self._raw(dev.path, "r3", ev.value != 0)
                        elif ev.type == E.EV_KEY and (ev.code == E.BTN_THUMBL or
                                                      (ev.code == E.BTN_BASE5 and dev.path in self.generic)):
                            self._raw(dev.path, "l3", ev.value != 0)
                        elif ev.type == E.EV_ABS:
                            self._abs(dev.path, ev.code, ev.value, axes.get(ev.code))
                except OSError:
                    sel.unregister(dev)
                    known.pop(dev.path, None)
                    with self.lock:
                        self.styles.pop(dev.path, None)
                        for k in [k for k in self.state if k[0] == dev.path]:
                            del self.state[k]
                        for k in [k for k in self.raw if k[0] == dev.path]:
                            del self.raw[k]
                    self._notify()

    def _abs(self, dev, code, value, info):
        from evdev import ecodes as E
        if code in (E.ABS_HAT0X, E.ABS_HAT0Y):
            neg, pos = ("left", "right") if code == E.ABS_HAT0X else ("up", "down")
            self._set(dev, "hat" + neg, value < 0)
            self._set(dev, "hat" + pos, value > 0)
            return
        if not info:
            return
        span = (info.max - info.min) or 1
        n = max(-1.0, min(1.0, (value - (info.max + info.min) / 2) / (span / 2)))
        if code in (E.ABS_X, E.ABS_Y):
            neg, pos = ("left", "right") if code == E.ABS_X else ("up", "down")
            self._set(dev, "stick" + neg, n < -0.55)
            self._set(dev, "stick" + pos, n > 0.55)
            if code == E.ABS_Y:
                self._raw(dev, "ly", n)
        elif code in (E.ABS_RX, E.ABS_RY):
            self._raw(dev, "rx" if code == E.ABS_RX else "ry", n)
        elif code in (E.ABS_Z, E.ABS_RZ):
            # Schultertasten als Achse (Xbox, DualSense): nur wenn die Achse in Ruhe am Anfang steht
            if info.min >= 0 and ((dev, code) in self.trig or (info.value - info.min) / span < 0.2):
                self.trig.add((dev, code))
                self._set(dev, "lt" if code == E.ABS_Z else "rt", (value - info.min) / span > 0.6)
            elif dev not in self.rx_dev:              # einfache Pads: rechter Stick auf Z (waagrecht) / RZ
                self._raw(dev, "rx" if code == E.ABS_Z else "ry", n)


class PadPump(QObject):
    """Meldet Controller-Druecke wie im Web: 380 ms bis zur Wiederholung, dann alle 140 ms.
    Ohne festen Takt: Der Geraete-Thread weckt die Pumpe bei jeder Aenderung (Taste, neuer oder abgezogener
    Controller), ein Zeitgeber laeuft nur, solange eine Taste mit Wiederholung gehalten wird. Ist ein anderes
    Programm vorn oder liegt der Controller still, laeuft hier kein Python. Wer "active" von sich aus umschaltet
    (heisse Ecke, Tastatur ueber Programmen), ruft poke(); Fensterwechsel bemerkt die Pumpe selbst."""
    key = Signal(str)
    style = Signal(str)            # Bauart des Controllers fuer die Tasten-Hinweise ("" = keiner angeschlossen)
    connected = Signal(str)
    _wake = Signal()               # aus dem Geraete-Thread, landet in der Ereignisschleife (QueuedConnection)

    def __init__(self, pad, active=None, absorb=False):
        super().__init__()
        self.pad, self.held, self.next = pad, {}, {}
        # absorb: Tasten, die beim Zustaendigwerden schon gehalten sind, zaehlen erst nach dem Loslassen (Startseite:
        # A der Controller-Maus, mit dem in Firefox ein Feld angeklickt wurde, tippt sonst gleich auf der Tastatur)
        self.absorb, self.was_active = absorb, False
        self.idle_held = set()     # zuletzt gehaltene Tasten, waehrend die Pumpe nicht zustaendig war (absorb)
        self.last_style = None
        self.pending = False       # Wecken unterwegs (mehrere Ereignisse ergeben einen Durchlauf)
        # Wann gehoert der Controller diesem Programm? Standard: eines seiner Fenster ist vorn
        self.active = active or (lambda: QGuiApplication.focusWindow() is not None)
        self.t = QTimer(self)
        self.t.setSingleShot(True)
        self.t.setTimerType(Qt.TimerType.PreciseTimer)
        self.t.timeout.connect(self.tick)
        self._wake.connect(self.tick, Qt.QueuedConnection)
        app = QGuiApplication.instance()
        if app is not None:
            app.focusWindowChanged.connect(self.poke)
        if pad is not None:
            pad.on_change(self._from_thread)
        QTimer.singleShot(0, self.poke)            # Controller, die schon vor der Pumpe erkannt wurden

    def _from_thread(self):
        if not self.pending:
            self.pending = True
            self._wake.emit()

    def poke(self, *_):
        """Zustaendigkeit hat sich geaendert (Fenster, heisse Ecke, Tastatur): gleich neu bewerten. Wird die Pumpe
        dabei zustaendig, schluckt absorb alle gehaltenen Tasten (wie frueher beim ersten Takt)."""
        self.tick(poked=True)

    def tick(self, poked=False):
        self.pending = False                       # vor dem Lesen: spaetere Aenderungen wecken erneut
        with self.pad.lock:
            names, self.pad.names = self.pad.names, []
        for n in names:
            self.connected.emit(n.split("(")[0].strip())
        st = self.pad.style()
        if st != self.last_style:
            self.last_style = st
            self.style.emit(st)
        raw = self.pad.pressed()
        want = {k for k in raw if not k.startswith(("hat", "stick"))}
        want |= {k[3:] for k in raw if k.startswith("hat")} | {k[5:] for k in raw if k.startswith("stick")}
        if not self.active():                          # nicht vorn: Controller gehoert dem anderen Programm
            self.held = {}
            self.was_active = False
            self.idle_held = want
            self.t.stop()
            return
        now = time.monotonic()
        if self.absorb and not self.was_active:
            # Per poke() zustaendig: alles Gehaltene schlucken. Bemerkt erst durch einen Tastendruck (Zustaendigkeit
            # wechselte still, z. B. Player mit mpv-Fenster): nur was schon vorher gehalten war, der neue Druck zaehlt
            keep = want if poked else want & self.idle_held
            self.held = {k: True for k in keep}
            self.next = {k: float("inf") for k in keep}         # auch keine Wiederholung, bis losgelassen
        self.was_active = True
        self.idle_held = set()
        for k in list(self.held):
            if k not in want:
                del self.held[k]
        for k in want:
            if k not in self.held:
                self.held[k] = True
                self.next[k] = now + 0.38
                self.key.emit(k)
            elif k in Gamepad.REPEAT and now >= self.next.get(k, 0):
                self.next[k] = now + 0.14
                self.key.emit(k)
        due = [self.next[k] for k in self.held if k in Gamepad.REPEAT and self.next.get(k, 0) != float("inf")]
        if due:
            self.t.start(max(1, int((min(due) - time.monotonic()) * 1000 + 0.999)))
        else:
            self.t.stop()


# ---------------------------------------------------------------------------
#  Verbindung zur Oberflaeche
# ---------------------------------------------------------------------------
# Echte Tastatur? Aus /proc/bus/input/devices (kein Geraet wird geoeffnet): Handler "kbd" und alle Buchstaben,
# Ziffern-Reihe und Leertaste. Fernbedienungen, Lautstaerke-/Power-Tasten und Controller haben die nicht.
# Funkempfaenger von Maeusen melden sich oft trotzdem als Tastatur – deshalb blendet die Bildschirmtastatur ihre Tasten
# in der Einstellung "Automatisch" erst aus, wenn auch wirklich getippt wurde (VsBase.kbdTyping).
_KBD_KEYS = list(range(2, 12)) + list(range(16, 26)) + list(range(30, 39)) + list(range(44, 51)) + [57]
_NOT_KEYBOARDS = ("consumer control", "system control", "power button", "sleep button", "video bus", "voidstation")


def real_keyboards(text=None):
    """Namen der angeschlossenen Tastaturen mit Buchstaben."""
    if text is None:
        try:
            text = Path("/proc/bus/input/devices").read_text(errors="replace")
        except OSError:
            return []
    bits = struct.calcsize("l") * 8              # Breite der Woerter in B: KEY= (long des Kernels)
    out = []
    for block in text.split("\n\n"):
        name, handlers, words = "", [], []
        for line in block.splitlines():
            if line.startswith("N: Name="):
                name = line[8:].strip().strip('"')
            elif line.startswith("H: Handlers="):
                handlers = line[12:].split()
            elif line.startswith("B: KEY="):
                words = line[7:].split()
        if "kbd" not in handlers or not words or any(w in name.lower() for w in _NOT_KEYBOARDS):
            continue
        val = 0
        try:
            for w in words:
                val = (val << bits) | int(w, 16)
        except ValueError:
            continue
        if all(val >> k & 1 for k in _KBD_KEYS):
            out.append(name)
    return out


class VsBase(QObject):
    """Bruecke zur QML-Oberflaeche (Startseite und Player): Launcher-Aufrufe, Texte, Farben, Symbole."""
    replied = Signal(int, bool, int, str)       # id, ok, HTTP-Status, Antwort (JSON-Text)
    themeChanged = Signal()
    stringsChanged = Signal()
    padKey = Signal(str)
    padConnected = Signal(str)
    padStyleChanged = Signal()
    kbdChanged = Signal()
    padOwnerChanged = Signal()                  # wem der Controller gehoert, hat sich geaendert (heisse Ecke, Tastatur)

    def __init__(self):
        super().__init__()
        self._theme_name = "default-dark"
        self._theme = theme_tokens(self._theme_name)
        self._lang = "de"
        self._strings = {}
        self._de = self._load_lang("de")
        self._set_lang("de")
        self._icons = {}
        self._glyphs = {}
        self._sound = vssound.SoundEngine(WEB / "sounds")
        self.pad: Any = None         # Gamepad, sobald die App ihn anlegt
        self._pad_style = ""         # Bauart des zuletzt benutzten Controllers, "" = keiner angeschlossen
        self._force_style = os.environ.get("VS_PAD_STYLE", "")   # Tests: so tun, als steckte dieser Controller
        if self._force_style in PAD_STYLES:
            self._pad_style = self._force_style
        self._kbd = False            # zuletzt die Tastatur benutzt: Hinweise wie bisher (Tastatur + Controller)
        self._kbd_present = False    # echte Tastatur angeschlossen (real_keyboards)
        self._kbd_typing = False     # zuletzt darauf getippt (Buchstaben, Ziffern …), nicht nur Pfeile/Enter
        self._kbd_force = os.environ.get("VS_KBD", "")     # Tests: 1 = so tun, als steckte eine Tastatur, 0 = keine
        self._kbd_timer = QTimer(self)
        self._kbd_timer.timeout.connect(self._scan_keyboards)
        self._kbd_timer.start(4000)
        QTimer.singleShot(0, self._scan_keyboards)
        self._watched = set()
        self._watch = QTimer(self)
        self._watch.timeout.connect(self._watch_windows)
        self._watch.start(2000)
        QTimer.singleShot(0, self._watch_windows)

    # ---- Controller oder Tastatur? (Tasten-Hinweise passen sich an) ----
    def attach_pump(self, pump):
        """Controller-Tasten weiterreichen und merken, welche Bauart zuletzt benutzt wurde. padOwnerChanged weckt die
        Pumpe, wenn sich ihre Zustaendigkeit aendert (ueber ein Signal statt einer Referenz: kein Kreis vs <-> pump)."""
        self.padOwnerChanged.connect(pump.poke)
        pump.key.connect(self._pad_used)
        pump.key.connect(self.padKey)
        pump.connected.connect(self.padConnected)
        pump.style.connect(self._set_pad_style)

    def _effective_style(self):
        return "" if self._kbd else self._pad_style

    def _set_pad_style(self, st):
        before = self._effective_style()
        if self._force_style in PAD_STYLES:
            st = self._force_style
        self._pad_style = st if st in PAD_STYLES else ""
        if not self._pad_style:
            self._kbd = False                       # ohne Controller: Hinweise ohnehin wie bisher
        if self._effective_style() != before:
            self.padStyleChanged.emit()

    def _pad_used(self, _key):
        if self._kbd_typing:
            self._kbd_typing = False
            self.kbdChanged.emit()
        if self._kbd:
            self._kbd = False
            if self._pad_style:
                self.padStyleChanged.emit()

    def _watch_windows(self):
        """Tastendruecke an allen Fenstern dieses Programms bemerken (auch in Eingabefeldern, die sie selbst
        verbrauchen) – nur die Fenster, nicht die ganze Anwendung, damit nicht jedes Ereignis durch Python laeuft."""
        for w in QGuiApplication.topLevelWindows():
            if id(w) not in self._watched:
                self._watched.add(id(w))
                w.installEventFilter(self)

    def _scan_keyboards(self):
        if self._kbd_force in ("0", "1"):
            found = self._kbd_force == "1"
        else:
            found = bool(real_keyboards())
        if found != self._kbd_present:
            self._kbd_present = found
            log("Tastatur", "erkannt" if found else "nicht mehr da")
            self.kbdChanged.emit()

    def _get_kbd_present(self):
        return self._kbd_present

    def _get_kbd_typing(self):
        return self._kbd_typing

    kbdPresent = Property(bool, _get_kbd_present, notify=kbdChanged)
    kbdTyping = Property(bool, _get_kbd_typing, notify=kbdChanged)

    def eventFilter(self, obj, ev):  # noqa: N802 (Qt-Name)
        if ev.type() == QEvent.KeyPress and not self._kbd_typing and not ev.isAutoRepeat():
            t = ev.text()
            if len(t) == 1 and t.isprintable() and not (ev.modifiers() & Qt.ControlModifier):
                self._kbd_typing = True
                self.kbdChanged.emit()
        if ev.type() == QEvent.KeyPress and not self._kbd:
            if not ev.isAutoRepeat():
                self._kbd = True
                if self._pad_style:
                    self.padStyleChanged.emit()
        return False

    def _get_pad_style(self):
        return self._effective_style()

    padStyle = Property(str, _get_pad_style, notify=padStyleChanged)

    @Slot(str, int, result="QVariantMap")
    def keyGlyph(self, role, h):
        """Tasten-Symbol der aktuellen Bauart: {src: data-URL, w, h}; leer, wenn es die Taste nicht gibt."""
        style = self._pad_style or "xbox"
        key = (role, style, h)
        if key not in self._glyphs:
            svg, w = pad_glyph_svg(role, style, max(8, int(h)))
            self._glyphs[key] = ({"src": "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode(),
                                  "w": w, "h": max(8, int(h))} if svg else {})
        return self._glyphs[key]

    # ---- HTTP (in Threads, Antwort per Signal) ----
    @Slot(int, str, str, str)
    def request(self, rid, method, path, body):
        threading.Thread(target=self._do, args=(rid, method, path, body), daemon=True).start()

    def _do(self, rid, method, path, body):
        data = body.encode() if method == "POST" else None
        headers = {"X-TV": "1", "Content-Type": "application/json"}
        token = read_api_token()
        if token:
            headers[API_TOKEN_HEADER] = token
        req = urllib.request.Request(API + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                self.replied.emit(rid, True, r.status, r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            try:
                txt = e.read().decode("utf-8", "replace")
            except OSError:
                txt = ""
            self.replied.emit(rid, False, e.code, txt)
        except (OSError, ValueError) as e:
            self.replied.emit(rid, False, 0, json.dumps({"error": str(e)}))

    # ---- Texte ----
    def _load_lang(self, lang):
        try:
            return json.loads((WEB / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _set_lang(self, lang):
        ok = bool(lang) and all(c.isalnum() or c == "-" for c in lang) and (WEB / "i18n" / f"{lang}.json").exists()
        self._lang = lang if ok else "de"
        cjk_font(self._lang)
        # Rueckfall wie im Web: Sprache -> Englisch -> Deutsch (Deutsch selbst faellt nicht auf Englisch zurueck,
        # sonst kaemen z. B. die englischen App-Beschreibungen statt der deutschen aus catalog.json)
        s = dict(self._de)
        for l in [] if self._lang == "de" else (["en"] if self._lang == "en" else ["en", self._lang]):
            d = self._load_lang(l)
            labels = {**s.get("labels", {}), **d.get("labels", {})}
            s.update(d)
            s["labels"] = labels
        self._strings = s

    def _get_strings(self):
        return self._strings

    def _get_lang(self):
        return self._lang

    strings = Property("QVariantMap", _get_strings, notify=stringsChanged)
    lang = Property(str, _get_lang, notify=stringsChanged)

    @Slot(str)
    def setLang(self, lang):
        if lang != self._lang or not self._strings:
            self._set_lang(lang)
            self.stringsChanged.emit()

    # ---- Farben ----
    def _get_theme(self):
        return self._theme

    def _get_theme_name(self):
        return self._theme_name

    theme = Property("QVariantMap", _get_theme, notify=themeChanged)
    themeName = Property(str, _get_theme_name, notify=themeChanged)

    @Slot(str)
    def setTheme(self, name):
        name = name if name in theme_names() else "default-dark"
        if name == self._theme_name:
            return
        self._theme_name = name
        self._theme = theme_tokens(name)
        self._icons.clear()
        self.themeChanged.emit()

    # ---- Symbole ----
    @Slot(str, str, result=str)
    def icon(self, name, color):
        key = (name, color)
        if key not in self._icons:
            svg = ICONS.get(name) or ICONS["globe"]
            col = color if len(color) != 9 else "#" + color[3:]           # SVG kennt kein #aarrggbb
            op = "" if len(color) != 9 else f' opacity="{int(color[1:3], 16) / 255:.2f}"'
            svg = svg.replace("currentColor", col)
            if "xmlns" not in svg:
                svg = svg.replace("<svg ", f'<svg xmlns="http://www.w3.org/2000/svg"{op} ', 1)
            self._icons[key] = "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()
        return self._icons[key]

    @Slot()
    def trimMemory(self):
        """Nach dem Schliessen einer Unterseite: Freigegebenes wirklich ans System zurueckgeben. Ohne malloc_trim
        behaelt glibc den Speicher, auch wenn Qt die Kacheln laengst abgebaut hat."""
        engine = getattr(self, "engine", None)
        if engine is not None:
            engine.collectGarbage()
            engine.trimComponentCache()
        malloc_trim()

    @Slot(result=float)
    def uptime(self):
        return time.monotonic() - T0

    @Slot(str)
    def log(self, msg):
        log(msg)

    # ---- Oberflaechentoene ----
    @Slot(str)
    def playSound(self, event):
        self._sound.play(str(event))

    @Slot(bool, int, str)
    def setSounds(self, enabled, volume, preset):
        self._sound.configure(enabled=bool(enabled), volume=int(volume), preset=str(preset))

    @Slot()
    def playStartupSound(self):
        self._sound.play_startup_once()


def limit_arenas():
    """Weniger malloc-Arenen (M_ARENA_MAX, rund 10 MB auf der Startseite). Als Aufruf statt MALLOC_ARENA_MAX,
    weil die Umgebungsvariable auch fuer alle gestarteten Programme gelten wuerde; Spiele sollen sie nicht erben."""
    try:
        ctypes.CDLL(None).mallopt(-8, 2)
    except (OSError, AttributeError):
        pass


def malloc_trim():
    try:
        ctypes.CDLL(None).malloc_trim(0)
    except (OSError, AttributeError):
        pass


def drop_stale_qml_cache(here=HERE):
    """Qt speichert kompiliertes QML in ~/.cache/voidstation/qmlcache. Qt 6.11 (Void) prueft dabei nur den
    Zeitstempel der Quelldatei – und der ist nach jedem Update derselbe (tar --mtime im Build). Ohne diese Pruefung
    liefe nach einem Update weiter das alte QML (in Qt 6.11.2 nachgestellt). Darum: Pruefsumme ueber den Inhalt
    aller QML-Dateien merken und den Cache verwerfen, sobald sie sich aendert. Kostet beim Start wenige ms."""
    from PySide6.QtCore import QStandardPaths
    h = hashlib.sha256()
    for p in sorted((here / "qml").rglob("*")):
        if p.is_file() and (p.suffix in (".qml", ".js") or p.name == "qmldir"):
            h.update(str(p.relative_to(here)).encode())
            h.update(p.read_bytes())
    stamp = h.hexdigest()[:16]
    cache = Path(QStandardPaths.writableLocation(QStandardPaths.CacheLocation)) / "qmlcache"
    mark = cache / ".voidstation-qml"
    try:
        if mark.read_text(encoding="utf-8").strip() == stamp:
            return
    except OSError:
        pass
    shutil.rmtree(cache, ignore_errors=True)
    try:
        cache.mkdir(parents=True, exist_ok=True)
        mark.write_text(stamp + "\n", encoding="utf-8")
    except OSError as e:
        log("QML-Cache: Kennung nicht gespeichert:", e)
    log("QML-Cache verworfen (Oberflaeche geaendert):", stamp)
