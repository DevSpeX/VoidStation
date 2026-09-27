#!/usr/bin/env python3
"""
VoidStation Shell
-----------------
Schlankes Vollbildfenster fuer die Startseite (WebKitGTK statt Firefox).
Zeigt http://127.0.0.1:8765/ an, wartet beim Start auf den Launcher,
laedt bei Fehlern selbst neu und hat kein Kontextmenue, keine Adressleiste.
WebKit-Daten liegen unter ~/.local/share/voidstation/webkit und
~/.cache/voidstation/webkit (nicht lose in ~/.local/share).
"""
import os
import sys
import time

T0 = time.monotonic()

import gi

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


class Shell(Gtk.Window):
    def __init__(self):
        super().__init__(title=TITLE)
        self.set_decorated(False)

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
        s.set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.ALWAYS)
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
        print("Webprozess beendet, lade neu:", reason, file=sys.stderr)
        GLib.timeout_add(500, lambda: (self.view.load_uri(URL), False)[1])

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
