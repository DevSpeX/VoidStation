#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
VoidStation Shell
-----------------
Schlankes Vollbildfenster fuer die Startseite (WebKitGTK statt Firefox).
Zeigt http://127.0.0.1:8765/ an, wartet beim Start auf den Launcher,
laedt bei Fehlern selbst neu und hat kein Kontextmenue, keine Adressleiste.
WebKit-Daten liegen unter ~/.local/share/voidstation/webkit und
~/.cache/voidstation/webkit (nicht lose in ~/.local/share).

Ladebild: Bis die Startseite ihre Kacheln gezeichnet hat (Nachricht "vsReady" aus index.html),
liegt ueber ihr ein Vollbild mit Logo und Lade-Punkten – genau wie das Startbild beim Hochfahren
(Plymouth), damit der Bildschirm zwischen Hochfahren und Startseite nie leer ist.

Darstellung (Stufen, von schnell nach robust):
  0  normal: GPU-Beschleunigung, DMA-BUF-Renderer
  1  ohne DMA-BUF-Renderer – noetig mit NVIDIA (nvidia und nouveau: sonst bleibt das Fenster schwarz)
  2  ganz ohne GPU (Software) – wenn es keine Render-Schnittstelle gibt oder Stufe 1 abstuerzt
Die Stufe wird vor dem Start von WebKit gewaehlt (Grafiktreiber aus /sys). Stuerzt der
Webprozess wiederholt ab, startet die Shell sich mit der naechsten Stufe neu; die gilt bis
zum Neustart des Geraets. Erzwingen: VS_WEBKIT_LEVEL=0|1|2 (z. B. in ~/.local/share/voidstation/env.sh).
"""
import glob
import math
import os
import sys
import time

T0 = time.monotonic()
UID = os.getuid()
LEVEL_FILE = f"/tmp/voidstation-webkit-level-{UID}"     # /tmp ist tmpfs: gilt bis zum Neustart
HERE = os.path.dirname(os.path.abspath(__file__))


def gpu_drivers():
    """Kernel-Treiber der Grafikkarten (i915, amdgpu, nouveau, nvidia …) aus /sys, ohne Zusatzprogramme."""
    out = []
    for d in glob.glob("/sys/bus/pci/devices/*"):
        try:
            with open(os.path.join(d, "class")) as f:
                if not f.read().startswith("0x03"):
                    continue
            out.append(os.path.basename(os.readlink(os.path.join(d, "driver"))))
        except OSError:
            continue
    return out


def pick_level():
    forced = os.environ.get("VS_WEBKIT_LEVEL", "").strip()
    if forced in ("0", "1", "2"):
        return int(forced), "VS_WEBKIT_LEVEL"
    try:
        with open(LEVEL_FILE) as f:
            return min(2, max(0, int(f.read().strip()))), "nach Absturz"
    except (OSError, ValueError):
        pass
    if not glob.glob("/dev/dri/renderD*"):
        return 2, "keine Render-Schnittstelle (/dev/dri/renderD*)"
    drv = gpu_drivers()
    if any(d in ("nvidia", "nouveau") for d in drv):
        return 1, "NVIDIA (" + ", ".join(drv) + ")"
    return 0, ", ".join(drv) or "Treiber unbekannt"


LEVEL, WHY = pick_level()
# muss vor dem Laden von WebKit gesetzt sein (gilt auch fuer den Webprozess)
if LEVEL >= 1:
    os.environ["WEBKIT_DISABLE_DMABUF_RENDERER"] = "1"
if LEVEL >= 2:
    os.environ["WEBKIT_DISABLE_COMPOSITING_MODE"] = "1"
    os.environ["LIBGL_ALWAYS_SOFTWARE"] = "1"
print(f"Darstellung: Stufe {LEVEL} ({WHY})", file=sys.stderr, flush=True)

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, WebKit2  # noqa: E402

URL = "http://127.0.0.1:8765/"
TITLE = "VoidStation"                   # muss zum Fenstertitel passen, den der Launcher sucht

DATA_HOME = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
CACHE_HOME = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
WK_DATA = os.path.join(DATA_HOME, "voidstation", "webkit")
WK_CACHE = os.path.join(CACHE_HOME, "voidstation", "webkit")
CRASH_WINDOW = 60                       # so viele Abstuerze in dieser Zeit (s) -> naechste Stufe
CRASH_LIMIT = 2
SPLASH_FALLBACK = 6                     # s nach "Seite geladen": Ladebild weg, auch ohne vsReady
BG = (0x0e / 255, 0x10 / 255, 0x12 / 255)
FG = (0xec / 255, 0xeb / 255, 0xe8 / 255)


class Splash(Gtk.DrawingArea):
    """Logo mittig, drei pulsierende Punkte darunter – Aufteilung wie das Plymouth-Theme."""

    def __init__(self):
        super().__init__()
        try:
            self.logo = GdkPixbuf.Pixbuf.new_from_file(os.path.join(HERE, "web", "logo.png"))
        except GLib.Error:
            self.logo = None
        self.scaled = None
        self.t0 = time.monotonic()
        self.connect("draw", self._draw)
        self.tick = GLib.timeout_add(33, self._tick)

    def _tick(self):
        self.queue_draw()
        return True

    def stop(self):
        if self.tick:
            GLib.source_remove(self.tick)
            self.tick = 0
        self.hide()

    def _draw(self, widget, cr):
        w, h = self.get_allocated_width(), self.get_allocated_height()
        cr.set_source_rgb(*BG)
        cr.paint()
        lh = 0
        if self.logo:
            lw = min(int(w * 0.42), self.logo.get_width())
            lh = int(self.logo.get_height() * lw / self.logo.get_width())
            if not self.scaled or self.scaled.get_width() != lw:
                self.scaled = self.logo.scale_simple(lw, lh, GdkPixbuf.InterpType.BILINEAR)
            Gdk.cairo_set_source_pixbuf(cr, self.scaled, (w - lw) // 2, int(h * 0.45 - lh / 2))
            cr.paint()
        ds = max(8, min(18, w // 120))
        gap = ds * 2
        y = int(h * 0.45 + lh / 2 + h * 0.08) + ds / 2
        x0 = (w - (3 * ds + 2 * gap)) / 2 + ds / 2
        t = time.monotonic() - self.t0
        for i in range(3):
            a = max(0.0, math.sin(t * 4.0 - i * 0.9))     # wie Plymouth: 0,08 je Bild bei 50 Bildern/s
            cr.set_source_rgba(*FG, 0.2 + 0.8 * a)
            cr.arc(x0 + i * (ds + gap), y, ds / 2, 0, 2 * math.pi)
            cr.fill()
        return False


class Shell(Gtk.Window):
    def __init__(self):
        super().__init__(title=TITLE)
        self.set_decorated(False)
        self.crashes = []
        self.ready = False
        self.failed = False

        os.makedirs(WK_DATA, exist_ok=True)
        os.makedirs(WK_CACHE, exist_ok=True)
        mgr = WebKit2.WebsiteDataManager(base_data_directory=WK_DATA, base_cache_directory=WK_CACHE)
        ctx = WebKit2.WebContext.new_with_website_data_manager(mgr)
        ctx.set_cache_model(WebKit2.CacheModel.DOCUMENT_VIEWER)   # wenig Speicher, keine Seitenhistorie
        ctx.set_spell_checking_enabled(False)

        ucm = WebKit2.UserContentManager()
        ucm.register_script_message_handler("vsReady")             # Startseite meldet: Kacheln gezeichnet
        ucm.connect("script-message-received::vsReady", lambda *a: self._ready("vsReady"))

        self.view = WebKit2.WebView(web_context=ctx, user_content_manager=ucm)
        s = self.view.get_settings()
        s.set_enable_developer_extras(False)
        s.set_enable_smooth_scrolling(True)
        s.set_enable_page_cache(False)
        s.set_enable_write_console_messages_to_stdout(True)
        s.set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.NEVER if LEVEL >= 2
                                           else WebKit2.HardwareAccelerationPolicy.ALWAYS)
        s.set_media_playback_requires_user_gesture(False)
        s.set_default_font_family("Noto Sans")
        self.view.set_background_color(_rgba("#0e1012"))

        self.view.connect("context-menu", lambda *a: True)          # kein Rechtsklick-Menue
        self.view.connect("load-failed", self._on_failed)
        self.view.connect("web-process-terminated", self._on_crash)
        self.view.connect("decide-policy", self._on_policy)
        self.view.connect("load-changed", self._on_load)

        # Ladebild ueber der Seite (die Seite darunter rendert schon, sonst wuerde WebKit sie drosseln)
        self.splash = Splash()
        overlay = Gtk.Overlay()
        overlay.add(self.view)
        overlay.add_overlay(self.splash)
        overlay.set_overlay_pass_through(self.splash, True)
        self.add(overlay)
        self.connect("destroy", Gtk.main_quit)
        # Bildschirmgroesse vorgeben (greift auch, falls der Fenstermanager Vollbild verweigert)
        geo = Gdk.Display.get_default().get_monitor(0).get_geometry()
        self.set_default_size(geo.width, geo.height)
        self.move(0, 0)
        self.fullscreen()
        self.show_all()
        self.view.grab_focus()                  # Tastatur und Fernbedienung direkt an die Seite
        self.view.load_uri(URL)

    def _ready(self, why):
        if self.ready:
            return False
        self.ready = True
        self.splash.stop()
        self.view.grab_focus()
        print(f"Startseite sichtbar nach {time.monotonic() - T0:.1f} s ({why})", file=sys.stderr, flush=True)
        return False

    def _on_load(self, view, event):
        if event == WebKit2.LoadEvent.STARTED:
            self.failed = False
        elif event == WebKit2.LoadEvent.FINISHED and not self.failed:   # FINISHED kommt auch nach Fehlern
            print(f"Startseite geladen nach {time.monotonic() - T0:.1f} s", file=sys.stderr, flush=True)
            if not self.ready:                  # aeltere index.html ohne vsReady oder Skriptfehler
                GLib.timeout_add_seconds(SPLASH_FALLBACK, self._ready, "Zeitablauf")

    def _on_failed(self, view, event, uri, error):
        # Launcher noch nicht bereit -> in einer Sekunde nochmal
        self.failed = True
        GLib.timeout_add(1000, lambda: (self.view.load_uri(URL), False)[1])
        return True

    def _on_crash(self, view, reason):
        print("Webprozess beendet:", reason, file=sys.stderr, flush=True)
        now = time.monotonic()
        self.crashes = [t for t in self.crashes if now - t < CRASH_WINDOW] + [now]
        if len(self.crashes) >= CRASH_LIMIT and LEVEL < 2 and "VS_WEBKIT_LEVEL" not in os.environ:
            self._restart(LEVEL + 1)
            return
        GLib.timeout_add(500, lambda: (self.view.load_uri(URL), False)[1])

    def _restart(self, level):
        """Mit robusterer Darstellung neu starten (Umgebung fuer WebKit laesst sich nur vor dem Start setzen)."""
        print(f"Wiederholte Abstuerze – starte neu mit Stufe {level}", file=sys.stderr, flush=True)
        try:
            with open(LEVEL_FILE, "w") as f:
                f.write(f"{level}\n")
        except OSError:
            pass
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def _on_policy(self, view, decision, kind):
        # Nur die eigene Startseite anzeigen, keine fremden Seiten oder Popups
        if kind == WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            uri = decision.get_navigation_action().get_request().get_uri()
            if not uri.startswith(URL):
                decision.ignore()
                return True
        if kind == WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION:
            decision.ignore()
            return True
        return False


def _rgba(hex_color):
    c = Gdk.RGBA()
    c.parse(hex_color)
    return c


if __name__ == "__main__":
    GLib.set_prgname("voidstation")         # Fensterklasse und Standard-Ordnernamen
    GLib.set_application_name("VoidStation")
    Shell()
    Gtk.main()
