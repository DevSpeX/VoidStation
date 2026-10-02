#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
VoidStation Live-ISO: eigenes Startmenue mit Logo, LIESMICH/README beilegen.

  grub-entries.py <iso-ein> <iso-aus> <LIESMICH.txt> <README.txt> <art-ordner>

void-mklive baut zwei Startmenues: GRUB fuer UEFI (boot/grub/grub_void.cfg) und isolinux fuer BIOS
(boot/isolinux/isolinux.cfg). Beide werden komplett ersetzt – es bleiben genau drei Eintraege:

  Start VoidStation Live                freie Treiber (Intel, AMD, nouveau fuer NVIDIA)
  Start VoidStation Live (NVIDIA only)  NVIDIA-Treiber statt nouveau (GeForce GTX 16xx / RTX 20xx und neuer)
  Reboot

Kernel, Initramfs und die Grund-Befehlszeile kommen aus dem ersten mklive-Eintrag. Das UEFI-Menue
bekommt das Theme aus <art-ordner>/grub (Hintergrund, Logo, Kacheln, Schriften), das BIOS-Menue
den Hintergrund <art-ordner>/isolinux/splash.png (640x480). Schreibt eine neue ISO, die
Startbereiche (BIOS/UEFI) werden unveraendert uebernommen (xorriso -boot_image any replay).
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ISOLINUX = "/boot/isolinux/isolinux.cfg"
THEME_DIR = "/boot/grub/themes/voidstation"
SPLASH = "vs-splash.png"                                    # liegt neben isolinux.cfg
TIMEOUT = 10                                                # Sekunden bis zum Start des ersten Eintrags

# Treiberwahl ueber die Kernel-Befehlszeile (kmod beachtet modprobe.blacklist auch im Initramfs):
#  - frei:   NVIDIA-Module gesperrt, nouveau mit GSP-Firmware (3D auf Turing/Ampere)
#  - NVIDIA: nouveau gesperrt; 99-voidstation-live.sh laedt nvidia_drm (modeset/fbdev aus modprobe.d)
FREE = "splash nouveau.config=NvGspRm=1 modprobe.blacklist=nvidia,nvidia_drm,nvidia_modeset,nvidia_uvm"
NVIDIA = "splash voidstation.gpu=nvidia modprobe.blacklist=nouveau,nova_core,nova_drm"
# Nur BIOS: VESA-Standardmodus 1024x768 (16 bit) fuer den Kernel – der Void-Kernel hat vesafb fest eingebaut,
# so gibt es auch ohne UEFI ein Startbild statt Textmeldungen. 791 (0x317) ist seit VBE 1.2 genormt; fehlt
# der Modus trotzdem, fragt der Kernel 30 s nach und startet dann im Textmodus weiter.
BIOS_EXTRA = "vga=791"
ENTRIES = [  # (id, Titel, Zusatz-Parameter); None = Neustart
    ("vs-live", "Start VoidStation Live", FREE),
    ("vs-nvidia", "Start VoidStation Live (NVIDIA only)", NVIDIA),
    ("vs-reboot", "Reboot", None),
]
FONTS = ("vs-20.pf2", "vs-30.pf2", "vs-mono-20.pf2")        # build-iso.sh erzeugt sie mit grub-mkfont


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


def merge_args(base, extra):
    """Zusatz-Parameter anhaengen; gleichnamige key=value aus der Grundzeile fallen weg."""
    keys = {a.split("=", 1)[0] for a in extra.split() if "=" in a}
    words = [a for a in base.split() if a.split("=", 1)[0] not in keys]
    return " ".join(words + extra.split())


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
    for m in re.finditer(r'^[ \t]*menuentry\b.*?\{', cfg, re.M):
        depth = 0
        for j in range(m.end() - 1, len(cfg)):
            if cfg[j] == "{":
                depth += 1
            elif cfg[j] == "}":
                depth -= 1
                if depth == 0:
                    body = cfg[m.end():j]
                    if "vmlinuz" in body:
                        return body
                    break
    return None


def grub_boot_lines(cfg):
    """(Kernel, Grund-Parameter, initrd) aus dem ersten mklive-Eintrag mit vmlinuz."""
    body = first_entry(cfg)
    if not body:
        sys.exit("GRUB: Menue-Eintrag mit vmlinuz nicht gefunden")
    body = re.sub(r"\\\n\s*", " ", body)                   # Fortsetzungszeilen zusammenfuegen
    lin = re.search(r"^\s*linux\s+(\S+)\s*(.*)$", body, re.M)
    ini = re.search(r"^\s*initrd\s+(.+?)\s*$", body, re.M)
    if not lin or not ini:
        sys.exit("GRUB: linux/initrd im Eintrag nicht gefunden")
    return lin.group(1), " ".join(lin.group(2).split()), ini.group(1)


def build_grub(cfg, fonts):
    kernel, base, initrd = grub_boot_lines(cfg)
    fonts = "\n".join(f'loadfont "${{vs_theme}}/{f}"' for f in fonts) or "# (keine eigenen Schriften)"
    out = [f"""# VoidStation Live – Startmenue (UEFI), erzeugt von grub-entries.py
export voidlive
set pager="1"

if [ -e "${{prefix}}/${{grub_cpu}}-${{grub_platform}}/all_video.mod" ]; then
    insmod all_video
else
    insmod efi_gop
    insmod efi_uga
    insmod video_bochs
    insmod video_cirrus
fi
insmod font
insmod png
insmod gfxmenu

set vs_theme="(${{voidlive}}){THEME_DIR}"
# eigene Schriften zuerst: GRUB nimmt fuer unbekannte Namen die zuletzt geladene (unicode.pf2)
{fonts}
if loadfont "(${{voidlive}})/boot/grub/fonts/unicode.pf2" ; then
    set gfxmode="1920x1080,1280x720,auto"
    insmod gfxterm
    terminal_input console
    terminal_output gfxterm
    if [ -e "${{vs_theme}}/theme.txt" ]; then
        set theme="${{vs_theme}}/theme.txt"
    fi
fi

set default="vs-live"
set timeout={TIMEOUT}
set timeout_style=menu
"""]
    for eid, title, extra in ENTRIES:
        if extra is None:
            out.append(f'menuentry "{title}" --id "{eid}" {{\n    reboot\n}}\n')
            continue
        out.append(f'menuentry "{title}" --id "{eid}" {{\n'
                   f'    set gfxpayload="keep"\n'
                   f'    linux {kernel} {merge_args(base, extra)}\n'
                   f'    initrd {initrd}\n}}\n')
    return "\n".join(out)


# ---------------------------------------------------------------------------
#  isolinux (BIOS)
# ---------------------------------------------------------------------------
def isolinux_boot_lines(cfg):
    """(Kernel, APPEND-Zeile) aus dem ersten LABEL-Block mit vmlinuz."""
    for block in re.split(r"(?mi)^(?=[ \t]*LABEL\s)", cfg)[1:]:
        k = re.search(r"(?mi)^\s*(?:KERNEL|LINUX)\s+(\S*vmlinuz\S*)", block)
        a = re.search(r"(?mi)^\s*APPEND\s+(.*)$", block)
        if k and a:
            return k.group(1), " ".join(a.group(1).split())
    sys.exit("isolinux: Eintrag mit vmlinuz nicht gefunden")


def build_isolinux(cfg):
    kernel, base = isolinux_boot_lines(cfg)
    # 640x480, Schrift 8x16 -> 80 Spalten, 30 Zeilen; das Logo steht im Hintergrundbild (Zeilen 6–10).
    # Alle *ROW-Angaben verschieben sich um VSHIFT: Eintraege Zeile 18–20, Countdown Zeile 23
    out = [f"""# VoidStation Live – Startmenue (BIOS), erzeugt von grub-entries.py
UI vesamenu.c32
PROMPT 0
TIMEOUT {TIMEOUT * 10}
ONTIMEOUT vs-live
DEFAULT vs-live
MENU BACKGROUND {SPLASH}
MENU TABMSG
MENU AUTOBOOT Start in # s
MENU WIDTH 80
MENU MARGIN 17
MENU ROWS 3
MENU VSHIFT 15
MENU TIMEOUTROW 8
MENU CMDLINEROW 10
MENU HELPMSGROW 11
MENU HELPMSGENDROW 13
MENU TABMSGROW 14

MENU COLOR screen      0 #00000000 #00000000 none
MENU COLOR border      0 #00000000 #00000000 none
MENU COLOR title       0 #00000000 #00000000 none
MENU COLOR unsel       0 #ffc9c8c4 #ff22262b none
MENU COLOR hotkey      0 #ffc9c8c4 #ff22262b none
MENU COLOR sel         0 #ffffffff #ff24414a none
MENU COLOR hotsel      0 #ffffffff #ff24414a none
MENU COLOR scrollbar   0 #00000000 #00000000 none
MENU COLOR tabmsg      0 #ff5c6066 #00000000 none
MENU COLOR cmdmark     0 #ff8a8f94 #00000000 none
MENU COLOR cmdline     0 #ffecebe8 #00000000 none
MENU COLOR timeout_msg 0 #ff8a8f94 #00000000 none
MENU COLOR timeout     0 #ff8a8f94 #00000000 none
MENU COLOR help        0 #ff8a8f94 #00000000 none
"""]
    for eid, title, extra in ENTRIES:
        if extra is None:
            out.append(f"LABEL {eid}\n  MENU LABEL {title}\n  COM32 reboot.c32\n")
            continue
        out.append(f"LABEL {eid}\n  MENU LABEL {title}\n  KERNEL {kernel}\n  APPEND {merge_args(base, extra + ' ' + BIOS_EXTRA)}\n")
    return "\n".join(out)


# ---------------------------------------------------------------------------
def main(src, dst, liesmich, readme, art):
    art = Path(art)
    path, names = find_cfg(src)
    if not path:
        sys.exit("kein GRUB-Menue in der ISO gefunden")
    theme = art / "grub"
    if not (theme / "theme.txt").is_file():
        sys.exit(f"Theme fehlt: {theme}/theme.txt")
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
        fonts = [f for f in FONTS if (theme / f).is_file()]
        local.write_text(build_grub(cfg, fonts), encoding="utf-8")
        maps += ["-map", str(local), path, "-map", str(theme), THEME_DIR]
        missing = [f for f in FONTS if f not in fonts]
        done.append(f"UEFI ({path}{', ohne ' + ', '.join(missing) if missing else ''})")

        if ISOLINUX in iso_files(src, "/boot/isolinux", "*.cfg"):
            iloc = Path(td) / "isolinux.cfg"
            iloc.write_text(build_isolinux(extract(src, ISOLINUX, iloc)), encoding="utf-8")
            maps += ["-map", str(iloc), ISOLINUX, "-map", str(art / "isolinux" / "splash.png"), f"/boot/isolinux/{SPLASH}"]
            done.append(f"BIOS ({ISOLINUX})")
        else:
            print("Hinweis: kein isolinux-Menue gefunden – BIOS-Start behaelt das Standardmenue", file=sys.stderr)

        xorriso("-indev", src, "-outdev", dst, "-boot_image", "any", "replay",
                *maps, "-map", liesmich, "/LIESMICH.txt", "-map", readme, "/README.txt", "-commit")
    print("Startmenue angepasst: " + ", ".join(done) + " – " + " / ".join(t for _, t, _ in ENTRIES))


if __name__ == "__main__":
    if len(sys.argv) != 6:
        sys.exit(__doc__)
    main(*sys.argv[1:])
