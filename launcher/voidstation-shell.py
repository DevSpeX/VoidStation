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

Darstellung (Stufen, von schnell nach robust):
  0  normal: GPU-Beschleunigung, DMA-BUF-Renderer
  1  ohne DMA-BUF-Renderer – noetig mit NVIDIA (nvidia und nouveau: sonst bleibt das Fenster schwarz)
  2  ganz ohne GPU (Software) – wenn es keine Render-Schnittstelle gibt oder Stufe 1 abstuerzt
Die Stufe wird vor dem Start von WebKit gewaehlt (Grafiktreiber aus /sys). Stuerzt der
Webprozess wiederholt ab, startet die Shell sich mit der naechsten Stufe neu; die gilt bis
zum Neustart des Geraets. Erzwingen: VS_WEBKIT_LEVEL=0|1|2 (z. B. in ~/.local/share/voidstation/env.sh).
"""
import glob
import os
import sys
import time

T0 = time.monotonic()
UID = os.getuid()
LEVEL_FILE = f"/tmp/voidstation-webkit-level-{UID}"     # /tmp ist tmpfs: gilt bis zum Neustart


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
from gi.repository import Gdk, GLib, Gtk, WebKit2  # noqa: E402

URL = "http://127.0.0.1:8765/"
TITLE = "VoidStation"                   # muss zum Fenstertitel passen, den der Launcher sucht

DATA_HOME = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
CACHE_HOME = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
WK_DATA = os.path.join(DATA_HOME, "voidstation", "webkit")
WK_CACHE = os.path.join(CACHE_HOME, "voidstation", "webkit")
CRASH_WINDOW = 60                       # so viele Abstuerze in dieser Zeit (s) -> naechste Stufe
CRASH_LIMIT = 2


class Shell(Gtk.Window):
    def __init__(self):
        super().__init__(title=TITLE)
        self.set_decorated(False)
        self.crashes = []

        os.makedirs(WK_DATA, exist_ok=True)
        os.makedirs(WK_CACHE, exist_ok=True)
        mgr = WebKit2.WebsiteDataManager(base_data_directory=WK_DATA, base_cache_directory=WK_CACHE)
        ctx = WebKit2.WebContext.new_with_website_data_manager(mgr)
        ctx.set_cache_model(WebKit2.CacheModel.DOCUMENT_VIEWER)   # wenig Speicher, keine Seitenhistorie
        ctx.set_spell_checking_enabled(False)

        self.view = WebKit2.WebView.new_with_context(ctx)
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

        self.add(self.view)
        self.connect("destroy", Gtk.main_quit)
        # Bildschirmgroesse vorgeben (greift auch, falls der Fenstermanager Vollbild verweigert)
        geo = Gdk.Display.get_default().get_monitor(0).get_geometry()
        self.set_default_size(geo.width, geo.height)
        self.move(0, 0)
        self.fullscreen()
        self.show_all()
        self.view.grab_focus()                  # Tastatur und Fernbedienung direkt an die Seite
        self.view.load_uri(URL)

    def _on_load(self, view, event):
        if event == WebKit2.LoadEvent.FINISHED:
            print(f"Startseite geladen nach {time.monotonic() - T0:.1f} s", file=sys.stderr, flush=True)

    def _on_failed(self, view, event, uri, error):
        # Launcher noch nicht bereit -> in einer Sekunde nochmal
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
