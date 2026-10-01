#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
VoidStation Live-ISO: Startmenue anpassen und LIESMICH/README beilegen.

  grub-entries.py <iso-ein> <iso-aus> <LIESMICH.txt> <README.txt>

void-mklive baut zwei Startmenues: GRUB fuer UEFI (boot/grub/grub_void.cfg) und isolinux fuer BIOS
(boot/isolinux/isolinux.cfg). In beiden wird der erste Eintrag als Vorlage genommen und durch vier
Eintraege ersetzt: Live-System und Installer, jeweils Deutsch und English. Die uebrigen Eintraege
(RAM, ohne Grafik …) bleiben dahinter. Schreibt eine neue ISO, die Startbereiche (BIOS/UEFI) werden
unveraendert uebernommen (xorriso -boot_image any replay).
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ISOLINUX = "/boot/isolinux/isolinux.cfg"
INSTALL_FLAG = "voidstation.install"                      # launcher.py startet dann gleich den Installer
ENTRIES = [  # (Titel, Sprache, Installer)
    ("VoidStation", "de", False),
    ("VoidStation installieren", "de", True),
    ("VoidStation (English)", "en", False),
    ("Install VoidStation (English)", "en", True),
]


def xorriso(*args):
    r = subprocess.run(["xorriso", *args], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("xorriso: " + (r.stderr or r.stdout)[-800:])
    return r.stdout + r.stderr


def iso_files(iso, folder, pattern):
    out = xorriso("-indev", iso, "-find", folder, "-name", pattern)
    return re.findall(r"'(%s/[^']+)'" % re.escape(folder), out)


def extract(iso, path, local):
    xorriso("-osirrox", "on", "-indev", iso, "-extract", path, str(local))
    return Path(local).read_text(encoding="utf-8", errors="replace")


def english(s):
    s = re.sub(r"locale\.LANG=\S+", "locale.LANG=en_US.UTF-8", s)
    return re.sub(r"vconsole\.keymap=\S+", "vconsole.keymap=us", s)


# ---------------------------------------------------------------------------
#  GRUB (UEFI)
# ---------------------------------------------------------------------------
def find_cfg(iso):
    names = iso_files(iso, "/boot/grub", "*.cfg")
    for want in ("/boot/grub/grub_void.cfg", "/boot/grub/grub.cfg"):
        if want in names:
            return want, names
    return (names[0] if names else None), names


def first_entry(cfg):
    m = re.search(r'^[ \t]*menuentry\b.*?\{', cfg, re.M)
    if not m:
        return None
    depth = 0
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
        b = english(b)
    if install:
        b = re.sub(r"(\blinux\s+\S*vmlinuz\S*)", r"\1 " + INSTALL_FLAG, b, count=1)
    return b


def patch_grub(cfg):
    span = first_entry(cfg)
    if not span or "vmlinuz" not in cfg[span[0]:span[1]]:
        sys.exit("GRUB: Menue-Eintrag mit vmlinuz nicht gefunden")
    block = cfg[span[0]:span[1]]
    new = "\n\n".join(variant(block, *e) for e in ENTRIES)
    cfg = cfg[:span[0]] + new + cfg[span[1]:]          # ersetzt den ersten Eintrag, die uebrigen bleiben
    return re.sub(r"^(\s*(?:set\s+)?timeout\s*=\s*)\d+", r"\g<1>10", cfg, flags=re.M)   # mklive: "timeout=15"


# ---------------------------------------------------------------------------
#  isolinux (BIOS)
# ---------------------------------------------------------------------------
def isolinux_variant(block, title, lang, install):
    lid = "vs-%s%s" % (lang, "-install" if install else "")
    out = []
    for line in block.splitlines():
        s = line.strip()
        u = s.upper()
        if u.startswith("LABEL "):
            line = f"LABEL {lid}"
        elif u.startswith("MENU LABEL"):
            line = f"MENU LABEL {title}"
        elif u == "MENU DEFAULT":
            continue                                       # Standard ist der erste Eintrag
        elif u.startswith("APPEND "):
            if lang == "en":
                line = english(line)
            if install:
                line = line.rstrip() + " " + INSTALL_FLAG
        out.append(line)
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out)


def patch_isolinux(cfg):
    """Ersten LABEL-Block mit Kernel ersetzen, Wartezeit 10 s, Start nach Ablauf = Deutsch."""
    parts = re.split(r"(?m)^(?=[ \t]*LABEL\s)", cfg)
    head, blocks = parts[0], parts[1:]
    idx = next((i for i, b in enumerate(blocks)
                if re.search(r"(?mi)^\s*(KERNEL|LINUX)\s+\S*vmlinuz", b) and re.search(r"(?mi)^\s*APPEND\s", b)), None)
    if idx is None:
        sys.exit("isolinux: Eintrag mit vmlinuz nicht gefunden")
    old_label = re.match(r"\s*LABEL\s+(\S+)", blocks[idx], re.I).group(1)
    new = "\n\n".join(isolinux_variant(blocks[idx], *e) for e in ENTRIES) + "\n\n"
    blocks[idx] = new
    head = re.sub(r"(?mi)^(\s*ONTIMEOUT\s+)%s\s*$" % re.escape(old_label), r"\g<1>vs-de", head)
    head = re.sub(r"(?mi)^(\s*DEFAULT\s+)%s\s*$" % re.escape(old_label), r"\g<1>vs-de", head)
    head = re.sub(r"(?mi)^(\s*TIMEOUT\s+)\d+\s*$", r"\g<1>100", head)            # Zehntelsekunden
    head = re.sub(r"(?mi)^(\s*MENU AUTOBOOT\s+).*$", r"\g<1>VoidStation in # s", head)
    # drei Eintraege mehr als bei mklive: Liste hoeher, Countdown/Befehlszeile/Hilfe darunter (640x480 = 30 Zeilen, VSHIFT 2)
    rows = len(re.findall(r"(?mi)^\s*LABEL\s", "".join(blocks[:idx] + blocks[idx + 1:]))) + len(ENTRIES)
    for key, val in (("ROWS", rows), ("TIMEOUTROW", rows + 4), ("CMDLINEROW", rows + 6),
                     ("HELPMSGROW", rows + 8), ("HELPMSGENDROW", 27)):
        head = re.sub(r"(?mi)^(\s*MENU %s\s+)\d+\s*$" % key, r"\g<1>%d" % val, head)
    return head + "".join(blocks)


# ---------------------------------------------------------------------------
def main(src, dst, liesmich, readme):
    path, names = find_cfg(src)
    if not path:
        sys.exit("kein GRUB-Menue in der ISO gefunden")
    maps, done = [], []
    with tempfile.TemporaryDirectory() as td:
        local = Path(td) / "grub.cfg"
        cfg = extract(src, path, local)
        # Menue steht evtl. in einer anderen Datei, die grub.cfg nur einbindet
        if "menuentry" not in cfg:
            for n in names:
                if n != path:
                    cfg = extract(src, n, local)
                    if "menuentry" in cfg:
                        path = n
                        break
        local.write_text(patch_grub(cfg), encoding="utf-8")
        maps += ["-map", str(local), path]
        done.append(f"UEFI ({path})")

        if ISOLINUX in iso_files(src, "/boot/isolinux", "*.cfg"):
            iloc = Path(td) / "isolinux.cfg"
            iloc.write_text(patch_isolinux(extract(src, ISOLINUX, iloc)), encoding="utf-8")
            maps += ["-map", str(iloc), ISOLINUX]
            done.append(f"BIOS ({ISOLINUX})")
        else:
            print("Hinweis: kein isolinux-Menue gefunden – BIOS-Start behaelt das Standardmenue", file=sys.stderr)

        xorriso("-indev", src, "-outdev", dst, "-boot_image", "any", "replay",
                *maps, "-map", liesmich, "/LIESMICH.txt", "-map", readme, "/README.txt", "-commit")
    print("Startmenue angepasst: " + ", ".join(done) + " – Deutsch/English, je Live und Installieren")


if __name__ == "__main__":
    if len(sys.argv) != 5:
        sys.exit(__doc__)
    main(*sys.argv[1:])
