#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
VoidStation Live-ISO: Startmenue anpassen und LIESMICH/README beilegen.

  grub-entries.py <iso-ein> <iso-aus> <LIESMICH.txt> <README.txt>

Nimmt den ersten Eintrag aus dem GRUB-Menue von void-mklive (boot/grub/grub_void.cfg) als Vorlage und
ersetzt ihn durch vier Eintraege: Live-System und Installer, jeweils Deutsch und English. Die uebrigen
Eintraege (RAM, ohne Grafik …) bleiben dahinter. Schreibt eine neue ISO, die Startbereiche (BIOS/UEFI)
werden unveraendert uebernommen (xorriso -boot_image any replay).
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def xorriso(*args):
    r = subprocess.run(["xorriso", *args], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("xorriso: " + (r.stderr or r.stdout)[-800:])
    return r.stdout + r.stderr


def find_cfg(iso):
    out = xorriso("-indev", iso, "-find", "/boot/grub", "-name", "*.cfg")
    names = re.findall(r"'(/boot/grub/[^']+\.cfg)'", out)
    for want in ("/boot/grub/grub_void.cfg", "/boot/grub/grub.cfg"):
        if want in names:
            return want, names
    return (names[0] if names else None), names


def first_entry(cfg):
    m = re.search(r'^[ \t]*menuentry\b.*?\{', cfg, re.M)
    if not m:
        return None
    depth, i = 0, m.start()
    for j in range(m.end() - 1, len(cfg)):
        if cfg[j] == "{":
            depth += 1
        elif cfg[j] == "}":
            depth -= 1
            if depth == 0:
                return m.start(), j + 1
    return None


def variant(block, title, lang, install):
    b = re.sub(r'menuentry\s+"[^"]*"', f'menuentry "{title}"', block, count=1)
    b = re.sub(r'menuentry\s+\'[^\']*\'', f'menuentry "{title}"', b, count=1)
    b = re.sub(r'--id\s+"?[\w-]+"?', "--id \"vs-%s%s\"" % (lang, "-install" if install else ""), b, count=1)
    if lang == "en":
        b = re.sub(r"locale\.LANG=\S+", "locale.LANG=en_US.UTF-8", b)
        b = re.sub(r"vconsole\.keymap=\S+", "vconsole.keymap=us", b)
    if install:
        b = re.sub(r"(\blinux\s+\S*vmlinuz\S*)", r"\1 voidstation.install", b, count=1)
    return b


def main(src, dst, liesmich, readme):
    path, names = find_cfg(src)
    if not path:
        sys.exit("kein GRUB-Menue in der ISO gefunden")
    with tempfile.TemporaryDirectory() as td:
        local = Path(td) / "menu.cfg"
        xorriso("-osirrox", "on", "-indev", src, "-extract", path, str(local))
        cfg = local.read_text(encoding="utf-8", errors="replace")
        # Menue steht evtl. in einer anderen Datei, die grub.cfg nur einbindet
        if "menuentry" not in cfg:
            for n in names:
                if n != path:
                    xorriso("-osirrox", "on", "-indev", src, "-extract", n, str(local))
                    cfg = local.read_text(encoding="utf-8", errors="replace")
                    if "menuentry" in cfg:
                        path = n
                        break
        span = first_entry(cfg)
        if not span or "vmlinuz" not in cfg[span[0]:span[1]]:
            sys.exit("Menue-Eintrag mit vmlinuz nicht gefunden")
        block = cfg[span[0]:span[1]]
        new = "\n\n".join([
            variant(block, "VoidStation", "de", False),
            variant(block, "VoidStation installieren", "de", True),
            variant(block, "VoidStation (English)", "en", False),
            variant(block, "Install VoidStation (English)", "en", True),
        ])
        cfg = cfg[:span[0]] + new + cfg[span[1]:]          # ersetzt den ersten Eintrag, die uebrigen bleiben
        cfg = re.sub(r"^(\s*set\s+timeout\s*=\s*)\d+", r"\g<1>10", cfg, flags=re.M)
        local.write_text(cfg, encoding="utf-8")
        xorriso("-indev", src, "-outdev", dst, "-boot_image", "any", "replay",
                "-map", str(local), path, "-map", liesmich, "/LIESMICH.txt", "-map", readme, "/README.txt", "-commit")
    print(f"Startmenue angepasst ({path}): Deutsch/English, je Live und Installieren")


if __name__ == "__main__":
    if len(sys.argv) != 5:
        sys.exit(__doc__)
    main(*sys.argv[1:])
