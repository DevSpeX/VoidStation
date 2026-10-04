#!/usr/bin/env python3
"""
Screenshots der Qt-Oberflaeche fuer README und Webseite (Beispieldaten, kein Void noetig).
Benoetigt: pip install PySide6-Essentials pillow, Schrift Noto Sans (sonst DejaVu)
Aufruf:    python3 tools/qt-screenshots.py            -> docs/screenshots/*.webp (de) und docs/screenshots/en/*.webp

Gerendert wird in 1920x1080 ohne GPU (offscreen), gespeichert als WebP in 1600x900.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "docs" / "screenshots"
SIZE = "1920x1080"
SAVE = (1600, 900)

# Datei -> (Optionen fuer qt-preview.py, Tasten bis zum Bild). "w" = kurz warten, Bild immer zuletzt.
SHOTS = {
    "1-start":     (["--clean", "--scale", "1.0"], []),
    "2-fernsehen": (["--clean"], ["down", "a", "w", "w", "w"]),
    "3-appcenter": (["--clean"], ["right", "right", "right", "down", "down", "a", "w", "w", "down", "w", "w"]),
    "4-radio":     (["--clean"], ["down", "down", "a", "w", "w", "w"]),
    "5-installer": (["--live"], ["w", "w"]),
    "6-ziel-ssd":  (["--live"], ["a", "w", "w", "w"]),
}


def shoot(lang, name, opts, keys, tmp):
    png = Path(tmp) / f"{lang}-{name}.png"
    env = dict(os.environ, VS_LANG=lang)
    cmd = [sys.executable, str(REPO / "tools" / "qt-preview.py"), "--size", SIZE, *opts,
           "--keys", ",".join(keys + [f"shot:{png}"])]
    subprocess.run(cmd, env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    if not png.exists():
        sys.exit(f"kein Bild fuer {lang}/{name}")
    dest = (OUT if lang == "de" else OUT / lang) / f"{name}.webp"
    dest.parent.mkdir(parents=True, exist_ok=True)
    Image.open(png).convert("RGB").resize(SAVE, Image.LANCZOS).save(dest, "WEBP", quality=88, method=6)
    print(f"{dest.relative_to(REPO)}  ({dest.stat().st_size // 1024} KB)")


def main():
    only = set(sys.argv[1:])
    with tempfile.TemporaryDirectory() as tmp:
        for lang in ("de", "en"):
            for name, (opts, keys) in SHOTS.items():
                if not only or name in only:
                    shoot(lang, name, opts, keys, tmp)


if __name__ == "__main__":
    main()
