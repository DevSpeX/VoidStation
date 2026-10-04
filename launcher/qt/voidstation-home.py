#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
VoidStation Home (Qt)
---------------------
Startseite als natives Programm: Python + Qt 6 (PySide6, QML). Ersetzt die WebKit-Shell fuer
die Kacheloberflaeche; der Installer im Live-System bleibt vorerst die Web-Oberflaeche.

Aufgaben dieses Programms (alles andere steht in qml/):
  * Fenster im Vollbild, Fenstertitel "VoidStation" (danach sucht der Launcher)
  * Verbindung zum Launcher (http://127.0.0.1:8765, dieselbe API wie die Web-Oberflaeche)
  * Texte aus web/i18n/*.json und Farben aus web/themes/*.css – eine Quelle fuer beide Oberflaechen
  * Gamepad ueber evdev (python3-evdev), Symbole als SVG

Darstellung: Qt Quick zeichnet mit OpenGL direkt auf der Grafikkarte (auch mit dem NVIDIA-Treiber).
Ohne Render-Schnittstelle (/dev/dri/renderD*) oder mit VS_QT_SOFTWARE=1 zeichnet Qt per Software.
Test ohne Geraet: VS_API=http://127.0.0.1:8766 python3 voidstation-home.py  (z. B. mit tools/qt-preview.py)
"""
import base64
import glob
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

T0 = time.monotonic()
HERE = Path(__file__).resolve().parent
WEB = Path(os.environ.get("VS_WEB") or HERE.parent / "web")
API = os.environ.get("VS_API", "http://127.0.0.1:8765").rstrip("/")
TITLE = "VoidStation"                     # muss zum Fenstertitel passen, den der Launcher sucht

if not glob.glob("/dev/dri/renderD*") or os.environ.get("VS_QT_SOFTWARE") == "1":
    os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
# 1 Pixel = 1 Bildpunkt: Groessen rechnet die Oberflaeche selbst (Skalierung × Bildschirmhoehe), Xft.dpi
# (vom Launcher fuer andere Programme gesetzt) wuerde sonst alles ein zweites Mal vergroessern
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
os.environ.pop("QT_SCALE_FACTOR", None)

sys.path.insert(0, str(HERE))
from icons import ICONS  # noqa: E402

from PySide6.QtCore import (Property, QObject, QTimer, QUrl, Signal, Slot)  # noqa: E402
from PySide6.QtGui import QFontDatabase, QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickWindow  # noqa: E402,F401  (macht Fenster aus QML zu QQuickWindow)


def log(*a):
    print("[home]", *a, file=sys.stderr, flush=True)


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
#  Gamepad (evdev): Zustand im Lese-Thread, Tastendruecke + Wiederholung im Qt-Thread
# ---------------------------------------------------------------------------
class Gamepad:
    REPEAT = {"left", "right", "up", "down", "lb", "rb", "lt", "rt"}
    KEYS = {304: "a", 305: "b", 307: "x", 308: "y", 310: "lb", 311: "rb", 312: "lt", 313: "rt",
            314: "select", 315: "start", 544: "up", 545: "down", 546: "left", 547: "right"}

    def __init__(self):
        self.state = {}            # (geraet, taste) -> gedrueckt
        self.lock = threading.Lock()
        self.names = []            # neu erkannte Controller (fuer die Meldung)
        self.trig = set()          # (geraet, achse): Achse ist eine Schultertaste (LT/RT)
        try:
            import evdev  # noqa: F401
        except ImportError:
            log("python3-evdev fehlt – Gamepad aus")
            return
        threading.Thread(target=self._run, daemon=True).start()

    def pressed(self):
        with self.lock:
            return {k for (_d, k), v in self.state.items() if v}

    def _set(self, dev, key, on):
        with self.lock:
            self.state[(dev, key)] = on

    def _run(self):
        import selectors
        import evdev
        from evdev import ecodes as E
        sel = selectors.DefaultSelector()
        known = {}                 # pfad -> (geraet, achsen-info)
        last = 0.0
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
                        if not (keys & {E.BTN_SOUTH, E.BTN_TRIGGER, E.BTN_JOYSTICK}):
                            dev.close()
                            continue
                        axes = {}
                        for code, info in caps.get(E.EV_ABS, []):
                            axes[code] = info
                        known[path] = (dev, axes)
                        sel.register(dev, selectors.EVENT_READ)
                        with self.lock:
                            self.names.append(dev.name)
                        log("Controller:", dev.name)
                    except OSError:
                        pass
            for key, _ in sel.select(timeout=1):
                dev = key.fileobj
                axes = known.get(dev.path, (None, {}))[1]
                try:
                    for ev in dev.read():
                        if ev.type == E.EV_KEY and ev.code in self.KEYS:
                            self._set(dev.path, self.KEYS[ev.code], ev.value != 0)
                        elif ev.type == E.EV_ABS:
                            self._abs(dev.path, ev.code, ev.value, axes.get(ev.code))
                except OSError:
                    sel.unregister(dev)
                    known.pop(dev.path, None)
                    with self.lock:
                        for k in [k for k in self.state if k[0] == dev.path]:
                            del self.state[k]

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
        if code in (E.ABS_X, E.ABS_Y):
            mid = (info.max + info.min) / 2
            n = (value - mid) / (span / 2)
            neg, pos = ("left", "right") if code == E.ABS_X else ("up", "down")
            self._set(dev, "stick" + neg, n < -0.55)
            self._set(dev, "stick" + pos, n > 0.55)
        elif code in (E.ABS_Z, E.ABS_RZ) and info.min >= 0:
            # Schultertasten als Achse (Xbox, DualSense): nur wenn die Achse in Ruhe am Anfang steht
            if (dev, code) in self.trig or (info.value - info.min) / span < 0.2:
                self.trig.add((dev, code))
                self._set(dev, "lt" if code == E.ABS_Z else "rt", (value - info.min) / span > 0.6)


class PadPump(QObject):
    """Fragt den Gamepad-Zustand ab (60 Hz) und meldet Druecke wie im Web: 380 ms bis zur Wiederholung, dann alle 140 ms."""
    key = Signal(str)
    connected = Signal(str)

    def __init__(self, pad):
        super().__init__()
        self.pad, self.held, self.next = pad, {}, {}
        self.t = QTimer(self)
        self.t.timeout.connect(self.tick)
        self.t.start(16)

    def tick(self):
        with self.pad.lock:
            names, self.pad.names = self.pad.names, []
        for n in names:
            self.connected.emit(n.split("(")[0].strip())
        if QGuiApplication.focusWindow() is None:      # Startseite nicht vorn: Controller gehoert dem Programm
            self.held = {}
            return
        raw = self.pad.pressed()
        now = time.monotonic()
        want = {k for k in raw if not k.startswith(("hat", "stick"))}
        want |= {k[3:] for k in raw if k.startswith("hat")} | {k[5:] for k in raw if k.startswith("stick")}
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


# ---------------------------------------------------------------------------
#  Verbindung zur Oberflaeche
# ---------------------------------------------------------------------------
class Vs(QObject):
    replied = Signal(int, bool, int, str)       # id, ok, HTTP-Status, Antwort (JSON-Text)
    themeChanged = Signal()
    stringsChanged = Signal()
    padKey = Signal(str)
    padConnected = Signal(str)

    def __init__(self):
        super().__init__()
        self._theme_name = "default-dark"
        self._theme = theme_tokens(self._theme_name)
        self._lang = "de"
        self._strings = {}
        self._de = self._load_lang("de")
        self._set_lang("de")
        self._icons = {}
        self.pad = None

    # ---- HTTP (in Threads, Antwort per Signal) ----
    @Slot(int, str, str, str)
    def request(self, rid, method, path, body):
        threading.Thread(target=self._do, args=(rid, method, path, body), daemon=True).start()

    def _do(self, rid, method, path, body):
        data = body.encode() if method == "POST" else None
        req = urllib.request.Request(API + path, data=data, method=method,
                                     headers={"X-TV": "1", "Content-Type": "application/json"})
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
        self._lang = lang if (WEB / "i18n" / f"{lang}.json").exists() else "de"
        s = dict(self._de)
        if self._lang != "de":
            s.update(self._load_lang(self._lang))
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

    @Slot(str, result=str)
    def tzTime(self, tz):
        """Uhrzeit in einer Zeitzone (fuer die Auswahl im Installer), im Format der Sprache."""
        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo
            t = datetime.now(ZoneInfo(tz))
        except Exception:  # noqa: BLE001
            return ""
        if self._lang == "de":
            return t.strftime("%H:%M")
        return t.strftime("%I:%M %p").lstrip("0")

    @Slot(str, result=bool)
    def padDown(self, key):
        """Wird diese Gamepad-Taste gerade gehalten? (Installieren: A halten)"""
        return self.pad is not None and key in self.pad.pressed()

    @Slot(result=float)
    def uptime(self):
        return time.monotonic() - T0

    @Slot(str)
    def log(self, msg):
        log(msg)

    @Slot()
    def restart(self):
        """Neu starten (z. B. nach Sprachwechsel), home.sh wuerde es sonst auch tun."""
        os.execv(sys.executable, [sys.executable] + sys.argv)


def main():
    QGuiApplication.setApplicationName("voidstation")
    QGuiApplication.setApplicationDisplayName(TITLE)
    QGuiApplication.setDesktopFileName("voidstation")
    app = QGuiApplication(sys.argv)
    families = set(QFontDatabase.families())
    for fam in ("Noto Sans", "DejaVu Sans"):
        if fam in families:
            f = app.font()
            f.setFamily(fam)
            app.setFont(f)
            break
    vs = Vs()
    vs.pad = Gamepad()
    pump = PadPump(vs.pad)
    pump.key.connect(vs.padKey)
    pump.connected.connect(vs.padConnected)

    engine = QQmlApplicationEngine()
    engine.addImportPath(str(HERE / "qml"))
    engine.rootContext().setContextProperty("vs", vs)
    engine.rootContext().setContextProperty("vsTitle", TITLE)
    engine.rootContext().setContextProperty("vsApi", API)
    engine.rootContext().setContextProperty("vsLogo", QUrl.fromLocalFile(str(WEB / "logo.png")).toString())
    engine.rootContext().setContextProperty("vsDemo", os.environ.get("VS_DEMO") == "1")
    size = os.environ.get("VS_SIZE", "")                 # Tests: z. B. 1920x1080 (sonst ganzer Bildschirm)
    w, _, h = size.partition("x")
    engine.rootContext().setContextProperty("vsW", int(w) if w.isdigit() else 0)
    engine.rootContext().setContextProperty("vsH", int(h) if h.isdigit() else 0)
    engine.load(QUrl.fromLocalFile(str(HERE / "qml" / "Main.qml")))
    if not engine.rootObjects():
        log("QML konnte nicht geladen werden")
        sys.exit(1)
    log(f"Startseite bereit nach {time.monotonic() - T0:.2f} s ({os.environ.get('QT_QUICK_BACKEND') or 'GPU'})")
    # Nur fuer Tests (tools/qt-preview.py): Gamepad-Druecke abspielen, Bildschirmfotos speichern
    #   VS_KEYS="right,right,a,shot:radio.png,b"  (w = kurz warten), VS_SCREENSHOT=datei.png zum Schluss
    steps = [k for k in os.environ.get("VS_KEYS", "").split(",") if k]
    shot = os.environ.get("VS_SCREENSHOT")
    if steps or shot:
        win = engine.rootObjects()[0]
        gap = int(os.environ.get("VS_KEYS_GAP", "450"))
        t = int(os.environ.get("VS_SCREENSHOT_DELAY", "2500"))
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent

        def press(name):                                  # k:Return, k:Escape, k:Left …, t:Text, c:x:y (Mausklick)
            if name.startswith("m:"):                     # m:x:y – Maus nur bewegen
                from PySide6.QtCore import QPointF
                from PySide6.QtGui import QMouseEvent
                pos = QPointF(*(float(v) for v in name[2:].split(":")))
                QGuiApplication.sendEvent(win, QMouseEvent(QEvent.MouseMove, pos, pos, Qt.NoButton, Qt.NoButton, Qt.NoModifier))
                return
            if name.startswith("c:"):
                from PySide6.QtCore import QPointF
                from PySide6.QtGui import QMouseEvent
                pos = QPointF(*(float(v) for v in name[2:].split(":")))
                for typ in (QEvent.MouseMove, QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
                    btn = Qt.NoButton if typ == QEvent.MouseMove else Qt.LeftButton
                    QGuiApplication.sendEvent(win, QMouseEvent(typ, pos, pos, btn, Qt.LeftButton if typ == QEvent.MouseButtonPress else Qt.NoButton, Qt.NoModifier))
                return
            if name.startswith("t:"):
                for ch in name[2:]:
                    for typ in (QEvent.KeyPress, QEvent.KeyRelease):
                        QGuiApplication.sendEvent(win, QKeyEvent(typ, 0, Qt.NoModifier, ch))
                return
            if name.startswith(("kd:", "ku:")):                  # Taste nur druecken / nur loslassen (halten)
                key = getattr(Qt, "Key_" + name[3:])
                QGuiApplication.sendEvent(win, QKeyEvent(QEvent.KeyPress if name[1] == "d" else QEvent.KeyRelease, key, Qt.NoModifier))
                return
            key = getattr(Qt, "Key_" + name[2:])
            for typ in (QEvent.KeyPress, QEvent.KeyRelease):
                QGuiApplication.sendEvent(win, QKeyEvent(typ, key, Qt.NoModifier))
        for k in steps:
            if k.startswith(("k:", "t:", "c:", "m:", "kd:", "ku:")):
                QTimer.singleShot(t, lambda k=k: press(k))
            elif k.startswith("shot:"):
                QTimer.singleShot(t, lambda f=k[5:]: win.grabWindow().save(f))
            elif k != "w":
                QTimer.singleShot(t, lambda k=k: vs.padKey.emit(k))
            t += gap
        if shot:
            QTimer.singleShot(t + 600, lambda: (win.grabWindow().save(shot), app.quit()))
        else:
            QTimer.singleShot(t + 600, app.quit)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
