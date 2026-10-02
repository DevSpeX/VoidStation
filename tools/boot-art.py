#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Grafiken fuer Startmenue und Startbild der Live-ISO neu erzeugen (aus site/assets/logo.svg).
Benoetigt: pip install playwright pillow && playwright install chromium
Aufruf:    python3 tools/boot-art.py        -> iso/art/{grub,isolinux,plymouth}/*.png, launcher/web/logo.png

  grub/      Theme fuer das UEFI-Startmenue: Hintergrund 1920x1080, Logo, Kachel-Rahmen der Eintraege
  isolinux/  Hintergrund 640x480 fuer das BIOS-Startmenue (Logo eingebrannt, vesamenu kann nur ein Bild)
  plymouth/  Logo fuer das Startbild waehrend des Hochfahrens
Farben wie Startseite/Webseite (Theme "Dunkel").
"""
import base64
from pathlib import Path

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "iso" / "art"
LOGO = (REPO / "site" / "assets" / "logo.svg").read_text(encoding="utf-8")
LOGO_URI = "data:image/svg+xml;base64," + base64.b64encode(LOGO.encode()).decode()

BG = "#0e1012"
BG_CSS = (f"background: radial-gradient(120vw 90vh at 15% 0%, #1b1f24 0%, transparent 60%),"
          f" radial-gradient(90vw 80vh at 100% 100%, #14171b 0%, transparent 55%), {BG};")
CARD = (0x22, 0x26, 0x2b, 255)          # --surface-card: Eintrag nicht gewaehlt
ACCENT = (0x24, 0x41, 0x4a, 255)        # --accent-tv: gewaehlter Eintrag
FOCUS = (0xf2, 0xef, 0xe9, 255)         # --border-focus: Rahmen um den gewaehlten Eintrag
FOCUS_W = 3


def shot(page, html, w, h, path, transparent=False):
    page.set_viewport_size({"width": w, "height": h})
    page.set_content(f"<html><body style='margin:0'>{html}</body></html>")
    page.wait_for_timeout(150)
    page.screenshot(path=str(path), omit_background=transparent)


def logo_html(w, h, extra=""):
    return (f"<div style='width:{w}px;height:{h}px;display:flex;align-items:center;justify-content:center;{extra}'>"
            f"<img src='{LOGO_URI}' style='width:100%;height:auto'></div>")


def box(path_prefix, center, edge, ew):
    """9 Teile fuer GRUBs *_pixmap_style: Rand ew Pixel breit, Mitte einfarbig."""
    parts = {"c": (1, 1, center), "n": (1, ew, edge), "s": (1, ew, edge), "e": (ew, 1, edge), "w": (ew, 1, edge),
             "ne": (ew, ew, edge), "nw": (ew, ew, edge), "se": (ew, ew, edge), "sw": (ew, ew, edge)}
    for k, (w, h, col) in parts.items():
        Image.new("RGBA", (w, h), col).save(f"{path_prefix}_{k}.png", optimize=True)


def dot(path, d):
    """Runder Punkt fuer die Lade-Animation (4x ueberabgetastet, damit der Rand weich ist)."""
    big =Image.new("RGBA", (d * 4, d * 4), (0, 0, 0, 0))
    ImageDraw.Draw(big).ellipse((0, 0, d * 4 - 1, d * 4 - 1), fill=(0xec, 0xeb, 0xe8, 255))
    big.resize((d, d), Image.LANCZOS).save(path, optimize=True)


def opt(p, mode="RGB"):
    im = Image.open(p).convert(mode)
    im.save(p, optimize=True)


def main():
    for d in ("grub", "isolinux", "plymouth"):
        (OUT / d).mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page()
        # GRUB: Hintergrund (wird auf die Bildschirmgroesse gestreckt – nur Verlauf, darum unkritisch)
        shot(pg, f"<div style='width:1920px;height:1080px;{BG_CSS}'></div>", 1920, 1080, OUT / "grub/background.png")
        opt(OUT / "grub/background.png")
        # GRUB: Logo einzeln (bleibt unverzerrt, egal welche Aufloesung)
        shot(pg, logo_html(720, 129), 720, 129, OUT / "grub/logo.png", transparent=True)
        opt(OUT / "grub/logo.png", "RGBA")
        # BIOS (vesamenu): 640x480, Logo eingebrannt, Menue darunter
        shot(pg, f"<div style='width:640px;height:480px;{BG_CSS};position:relative'>"
                 f"<div style='position:absolute;left:120px;top:96px'>{logo_html(400, 72)}</div></div>",
             640, 480, OUT / "isolinux/splash.png")
        opt(OUT / "isolinux/splash.png")
        # Startbild (Plymouth): Logo gross, das Skript skaliert passend zum Bildschirm
        shot(pg, logo_html(960, 172), 960, 172, OUT / "plymouth/logo.png", transparent=True)
        opt(OUT / "plymouth/logo.png", "RGBA")
        # dasselbe Logo fuer das Ladebild der Startseite (voidstation-shell.py)
        (REPO / "launcher/web/logo.png").write_bytes((OUT / "plymouth/logo.png").read_bytes())
        b.close()
    box(OUT / "grub/item", CARD, CARD, 1)
    box(OUT / "grub/select", ACCENT, FOCUS, FOCUS_W)
    box(OUT / "grub/term", (0x0e, 0x10, 0x12, 255), (0x2c, 0x30, 0x35, 255), 2)   # Rahmen fuer Befehlszeile / "e"
    dot(OUT / "plymouth/dot.png", 14)
    for p in sorted(OUT.rglob("*.png")):
        print(f"{p.relative_to(REPO)}  {Image.open(p).size}  {p.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
