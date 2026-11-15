#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
VoidStation Live-ISO: eigenes Startmenue mit Logo, LIESMICH/README beilegen.

  grub-entries.py <iso-ein> <iso-aus> <LIESMICH.txt> <README.txt> <art-ordner>

void-mklive baut zwei Startmenues: GRUB fuer UEFI (boot/grub/grub_void.cfg) und isolinux fuer BIOS
(boot/isolinux/isolinux.cfg). Beide werden komplett ersetzt – oben steht die Sprache, darunter je zwei Starteintraege:

  1. Seite   Deutsch / English / Français / Other Languages / Reboot
  2. Seite   (nur ueber "Other Languages") die uebrigen Sprachen in der Reihenfolge der Einstellungen
             (Čeština, Español, Italiano … Українська) + Back
  3. Seite   VoidStation Live starten                freie Treiber (Intel, AMD, nouveau fuer NVIDIA)
             VoidStation Live starten (nur NVIDIA)   NVIDIA-Treiber statt nouveau (GTX 16xx / RTX 20xx und neuer)
             Zurueck                                 – jeweils in der gewaehlten Sprache

Die Sprache stellt Oberflaeche, Installer und Tastatur ein (voidstation.lang, locale.LANG, voidstation.kb fuer
die Tastatur der Oberflaeche, vconsole.keymap fuer die Konsole). Ohne Tastendruck startet nach TIMEOUT Sekunden
"Deutsch › VoidStation Live starten". Mit VOIDSTATION_ARCH=i686 (32-Bit-ISO) gibt es je Sprache nur den einen
Starteintrag (mit forcepae).

Kernel, Initramfs und die Grund-Befehlszeile kommen aus dem ersten mklive-Eintrag. Das UEFI-Menue
bekommt das Theme aus <art-ordner>/grub (Hintergrund, Logo, Kacheln, Schriften mit Griechisch und Kyrillisch),
das BIOS-Menue den Hintergrund <art-ordner>/isolinux/splash.png (640x480). Die BIOS-Schrift kennt nur
Codepage 437: Akzente fallen dort weg (Čeština -> Cestina), griechische und kyrillische Texte stehen
in Umschrift bzw. auf Englisch. Schreibt eine neue ISO, die Startbereiche (BIOS/UEFI) werden unveraendert
uebernommen (xorriso -boot_image any replay).
"""
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

ISOLINUX = "/boot/isolinux/isolinux.cfg"
THEME_DIR = "/boot/grub/themes/voidstation"
SPLASH = "vs-splash.png"                                    # liegt neben isolinux.cfg
TIMEOUT = 15                                                # Sekunden bis zum Start des ersten Eintrags (steht bei Tastendruck)

# Treiberwahl ueber die Kernel-Befehlszeile (kmod beachtet modprobe.blacklist auch im Initramfs):
#  - frei:   NVIDIA-Module gesperrt, nouveau mit GSP-Firmware (3D auf Turing/Ampere)
#  - NVIDIA: nouveau gesperrt; 99-voidstation-live.sh laedt nvidia_drm (modeset/fbdev aus modprobe.d)
FREE = "splash nouveau.config=NvGspRm=1 modprobe.blacklist=nvidia,nvidia_drm,nvidia_modeset,nvidia_uvm"
NVIDIA = "splash voidstation.gpu=nvidia modprobe.blacklist=nouveau,nova_core,nova_drm"
# Nur BIOS: VESA-Standardmodus 1024x768 (16 bit) fuer den Kernel – der Void-Kernel hat vesafb fest eingebaut,
# so gibt es auch ohne UEFI ein Startbild statt Textmeldungen. 791 (0x317) ist seit VBE 1.2 genormt; fehlt
# der Modus trotzdem, fragt der Kernel 30 s nach und startet dann im Textmodus weiter.
BIOS_EXTRA = "vga=791"
# Sprachen in der Reihenfolge der Einstellungen (LANG_TABLE in launcher/launcher.py). Je Sprache:
#   id, Name (wie in den Einstellungen), Locale, Tastatur der Oberflaeche (voidstation.kb, siehe
#   99-voidstation-live.sh und KEYMAPS im Installer), Konsolen-Tastatur (vconsole.keymap, kbd-Name),
#   Umschrift fuers BIOS-Menue (nur wenn der Name nicht in Codepage 437 geht), Zurueck, Start, Start nur NVIDIA.
# Griechisch/Russisch/Ukrainisch/Thai: Oberflaeche mit US-Tastatur + Landesbelegung (Alt+Umschalt wechselt),
# Konsole bleibt US (Anmeldename und Befehle sind lateinisch). Niederlaendisch: US-Tastatur wie dort ueblich,
# ebenso Koreanisch und Chinesisch (ohne Eingabemethode tippt die Landesbelegung ohnehin lateinisch).
# Japanisch, Koreanisch, Chinesisch: die Schriften des Startmenues haben keine CJK-Zeichen – dort stehen Umschrift
# und die englischen Starteintraege (grub_text/bios_text). Ebenso Hindi, Tamil, Malayalam und Thai: GRUB setzt
# keine Vokalzeichen und Ligaturen, die Schriften blieben unlesbar. Vietnamesisch geht (Zeichen in GRUB_RANGES).
LANGUAGES = [
    ("de", "Deutsch", "de_DE", "de", "de", None, "Zurück",
     "VoidStation Live starten", "VoidStation Live starten (nur NVIDIA)"),
    ("en", "English", "en_US", "us", "us", None, "Back",
     "Start VoidStation Live", "Start VoidStation Live (NVIDIA only)"),
    ("id", "Bahasa Indonesia", "id_ID", "us", "us", None, "Kembali",
     "Mulai VoidStation Live", "Mulai VoidStation Live (khusus NVIDIA)"),
    ("ms", "Bahasa Melayu", "ms_MY", "us", "us", None, "Kembali",
     "Mulakan VoidStation Live", "Mulakan VoidStation Live (NVIDIA sahaja)"),
    ("cs", "Čeština", "cs_CZ", "cz", "cz-qwertz", None, "Zpět",
     "Spustit VoidStation Live", "Spustit VoidStation Live (pouze NVIDIA)"),
    ("da", "Dansk", "da_DK", "dk", "dk", None, "Tilbage",
     "Start VoidStation Live", "Start VoidStation Live (kun NVIDIA)"),
    ("et", "Eesti", "et_EE", "ee", "et", None, "Tagasi",
     "Käivita VoidStation Live", "Käivita VoidStation Live (ainult NVIDIA)"),
    ("es", "Español", "es_ES", "es", "es", None, "Atrás",
     "Iniciar VoidStation Live", "Iniciar VoidStation Live (solo NVIDIA)"),
    ("fr", "Français", "fr_FR", "fr", "fr", None, "Retour",
     "Démarrer VoidStation Live", "Démarrer VoidStation Live (NVIDIA uniquement)"),
    ("is", "Íslenska", "is_IS", "is", "is-latin1", None, "Til baka",
     "Ræsa VoidStation Live", "Ræsa VoidStation Live (aðeins NVIDIA)"),
    ("it", "Italiano", "it_IT", "it", "it", None, "Indietro",
     "Avvia VoidStation Live", "Avvia VoidStation Live (solo NVIDIA)"),
    ("lv", "Latviešu", "lv_LV", "lv", "lv", None, "Atpakaļ",
     "Palaist VoidStation Live", "Palaist VoidStation Live (tikai NVIDIA)"),
    ("hu", "Magyar", "hu_HU", "hu", "hu", None, "Vissza",
     "VoidStation Live indítása", "VoidStation Live indítása (csak NVIDIA)"),
    ("nl", "Nederlands", "nl_NL", "us", "us", None, "Terug",
     "VoidStation Live starten", "VoidStation Live starten (alleen NVIDIA)"),
    ("nb", "Norsk bokmål", "nb_NO", "no", "no", None, "Tilbake",
     "Start VoidStation Live", "Start VoidStation Live (kun NVIDIA)"),
    ("pl", "Polski", "pl_PL", "pl", "pl", None, "Wstecz",
     "Uruchom VoidStation Live", "Uruchom VoidStation Live (tylko NVIDIA)"),
    ("pt-BR", "Português (Brasil)", "pt_BR", "br", "br-abnt2", None, "Voltar",
     "Iniciar o VoidStation Live", "Iniciar o VoidStation Live (somente NVIDIA)"),
    ("ro", "Română", "ro_RO", "ro", "ro", None, "Înapoi",
     "Pornește VoidStation Live", "Pornește VoidStation Live (doar NVIDIA)"),
    ("sk", "Slovenčina", "sk_SK", "sk", "sk-qwertz", None, "Späť",
     "Spustiť VoidStation Live", "Spustiť VoidStation Live (iba NVIDIA)"),
    ("fi", "Suomi", "fi_FI", "fi", "fi", None, "Takaisin",
     "Käynnistä VoidStation Live", "Käynnistä VoidStation Live (vain NVIDIA)"),
    ("sv", "Svenska", "sv_SE", "se", "sv-latin1", None, "Tillbaka",
     "Starta VoidStation Live", "Starta VoidStation Live (endast NVIDIA)"),
    ("vi", "Tiếng Việt", "vi_VN", "us", "us", None, "Quay lại",
     "Khởi động VoidStation Live", "Khởi động VoidStation Live (chỉ NVIDIA)"),
    ("tr", "Türkçe", "tr_TR", "tr", "trq", None, "Geri",
     "VoidStation Live’ı başlat", "VoidStation Live’ı başlat (yalnızca NVIDIA)"),
    ("el", "Ελληνικά", "el_GR", "gr", "us", "Ellinika (Greek)", "Πίσω",
     "Εκκίνηση VoidStation Live",
     "Εκκίνηση VoidStation Live (μόνο NVIDIA)"),
    ("ru", "Русский", "ru_RU", "ru", "us", "Russkiy (Russian)", "Назад",
     "Запустить VoidStation Live",
     "Запустить VoidStation Live (только NVIDIA)"),
    ("uk", "Українська", "uk_UA", "ua", "us", "Ukrainska (Ukrainian)", "Назад",
     "Запустити VoidStation Live",
     "Запустити VoidStation Live (лише NVIDIA)"),
    ("hi", "हिन्दी", "hi_IN", "us", "us", "Hindi", "वापस",
     "VoidStation Live शुरू करें", "VoidStation Live शुरू करें (केवल NVIDIA)"),
    ("ta", "தமிழ்", "ta_IN", "us", "us", "Tamil", "பின்செல்",
     "VoidStation Live ஐத் தொடங்கு", "VoidStation Live ஐத் தொடங்கு (NVIDIA மட்டும்)"),
    ("ml", "മലയാളം", "ml_IN", "us", "us", "Malayalam", "മടങ്ങുക",
     "VoidStation Live തുടങ്ങുക", "VoidStation Live തുടങ്ങുക (NVIDIA മാത്രം)"),
    ("th", "ไทย", "th_TH", "th", "us", "Thai", "ย้อนกลับ",
     "เริ่ม VoidStation Live", "เริ่ม VoidStation Live (NVIDIA เท่านั้น)"),
    ("ja", "日本語", "ja_JP", "jp", "jp106", "Nihongo (Japanese)", "戻る",
     "VoidStation Liveを起動", "VoidStation Liveを起動(NVIDIAのみ)"),
    ("ko", "한국어", "ko_KR", "us", "us", "Hangugeo (Korean)", "뒤로",
     "VoidStation Live 시작", "VoidStation Live 시작 (NVIDIA 전용)"),
    ("zh-CN", "简体中文", "zh_CN", "us", "us", "Jianti Zhongwen (Chinese, Simplified)", "返回",
     "启动 VoidStation Live", "启动 VoidStation Live(仅 NVIDIA)"),
    ("zh-TW", "繁體中文", "zh_TW", "us", "us", "Fanti Zhongwen (Chinese, Traditional)", "返回",
     "啟動 VoidStation Live", "啟動 VoidStation Live(僅 NVIDIA)"),
]
TOP = ("de", "en", "fr")                                    # 1. Seite, der Rest unter "Other Languages"
OTHER = ("vs-other", "Other Languages", "Back")
LANGS = [  # (id, Menuepunkt, Zusatz-Parameter der Sprache, Zurueck, [(id, Titel, Treiber-Parameter)], BIOS-Umschrift)
    (lid, name, f"voidstation.lang={lid} locale.LANG={loc}.UTF-8 voidstation.kb={kb} vconsole.keymap={con}", back,
     [("live", start, FREE), ("nvidia", start_nv, NVIDIA)], bios)
    for lid, name, loc, kb, con, bios, back, start, start_nv in LANGUAGES
]
# 32-Bit-ISO (experimentell, VOIDSTATION_ARCH=i686 aus build-iso.sh): kein NVIDIA-Treiber und kein Startbild,
# also nur ein Starteintrag je Sprache. forcepae: Pentium M (Banias, fruehe Dothan) koennen PAE, melden es aber
# nicht – ohne den Parameter startet kein PAE-Kernel; CPUs, die PAE melden, merken davon nichts.
ARCH = os.environ.get("VOIDSTATION_ARCH", "x86_64")
if ARCH == "i686":
    I686 = "forcepae"
    LANGS = [(lid, lname, lextra, back, [(entries[0][0], entries[0][1], I686)], bios)
             for lid, lname, lextra, back, entries, bios in LANGS]
REBOOT = ("vs-reboot", "Reboot")
DEFAULT = ("de", "live")                                    # Start nach Ablauf des Countdowns
FONTS = ("vs-20.pf2", "vs-24.pf2", "vs-30.pf2", "vs-mono-20.pf2")        # build-iso.sh erzeugt sie mit grub-mkfont


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
    """Zusatz-Parameter anhaengen; gleichnamige key=value und gleiche Schalter (z. B. forcepae)
    aus der Grundzeile fallen weg."""
    keys = {a.split("=", 1)[0] for a in extra.split()}
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


def build_grub(cfg, fonts, cfg_path="/boot/grub/grub_void.cfg"):
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
export vs_theme
# eigene Schriften zuerst: GRUB nimmt fuer unbekannte Namen die zuletzt geladene (unicode.pf2)
{fonts}
if loadfont "(${{voidlive}})/boot/grub/fonts/unicode.pf2" ; then
    # nie in 4K zeichnen: dort reagiert das Menue (ohne Grafiktreiber) kaum noch auf Tasten.
    # NVIDIA-Firmware bietet an 4K-Fernsehern oft kein 1920x1080 an, 1024x768 aber praktisch immer
    set gfxmode="1920x1080,1280x720,1024x768,auto"
    insmod gfxterm
    terminal_input console
    terminal_output gfxterm
    if [ -e "${{vs_theme}}/theme.txt" ]; then
        set theme="${{vs_theme}}/theme.txt"
        export theme
    fi
fi

# 1. Seite: Sprache. Countdown nur beim ersten Anzeigen – "Zurueck" laedt diese Datei neu (vs_back = Eintrag,
# von dem man kam), dann wartet das Menue, bis jemand waehlt. Ohne Tastendruck: Deutsch › VoidStation Live starten
set default="vs-{DEFAULT[0]}>vs-{DEFAULT[0]}-{DEFAULT[1]}"
if [ -n "${{vs_back}}" ]; then
    set default="${{vs_back}}"
    set timeout=-1
else
    set timeout={TIMEOUT}
fi
set timeout_style=menu
"""]
    def back_entry(eid, title, to, ind):
        # Zurueck zur 1. Seite, dort steht der Eintrag "to" vorne (Esc geht auch, eine Ebene hoch)
        return (f'{ind}menuentry "{title}" --id "{eid}" {{\n'
                f'{ind}    set vs_back="{to}"\n{ind}    export vs_back\n'
                f'{ind}    configfile "(${{voidlive}}){cfg_path}"\n{ind}}}')

    en = next(lang for lang in LANGS if lang[0] == "en")
    eng = {eid: title for eid, title, _ in en[4]}

    def lang_menu(lang, ind, back_to):
        lid, lname, lextra, back, entries, translit = lang
        sub = [f'{ind}submenu "{grub_text(lname, translit)}" --id "vs-{lid}" {{']
        for eid, title, extra in entries:
            title = grub_text(title, eng.get(eid, title))
            sub.append(f'{ind}    menuentry "{title}" --id "vs-{lid}-{eid}" {{\n'
                       f'{ind}        set gfxpayload="keep"\n'
                       f'{ind}        linux {kernel} {merge_args(base, extra + " " + lextra)}\n'
                       f'{ind}        initrd {initrd}\n{ind}    }}')
        sub.append(back_entry(f"vs-{lid}-back", grub_text(back, en[3]), back_to, ind + "    "))
        sub.append(f"{ind}}}")
        return "\n".join(sub)

    for lang in LANGS:
        if lang[0] in TOP:
            out.append(lang_menu(lang, "", f"vs-{lang[0]}") + "\n")
    others = [lang for lang in LANGS if lang[0] not in TOP]
    if others:
        sub = [f'submenu "{OTHER[1]}" --id "{OTHER[0]}" {{']
        sub += [lang_menu(lang, "    ", OTHER[0]) for lang in others]
        sub.append(back_entry(f"{OTHER[0]}-back", OTHER[2], OTHER[0], "    "))
        sub.append("}\n")
        out.append("\n".join(sub))
    out.append(f'menuentry "{REBOOT[1]}" --id "{REBOOT[0]}" {{\n    reboot\n}}\n')
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


# Zeichen der GRUB-Schriften (grub-mkfont -r in build-iso.sh): Latein mit Akzenten, Griechisch, Kyrillisch, Striche, Pfeile
GRUB_RANGES = ((0x20, 0x7E), (0xA0, 0x17F), (0x1A0, 0x1B0), (0x218, 0x21B), (0x370, 0x3FF), (0x400, 0x4FF),
               (0x1EA0, 0x1EFF), (0x2010, 0x2027), (0x2190, 0x2193))


def grub_text(text, fallback):
    """Text fuer das UEFI-Menue: unveraendert, wenn die Schrift alle Zeichen hat, sonst der Ersatztext
    (Japanisch: Umschrift bzw. Englisch – die Schriften haben keine japanischen Zeichen)."""
    if all(any(a <= ord(c) <= b for a, b in GRUB_RANGES) for c in text):
        return text
    return fallback or text


# Buchstaben ohne zerlegbaren Akzent, die Codepage 437 nicht kennt (Türkçe: "Live’ı başlat" -> "Live'i baslat",
# Íslenska: "Ræsa … (aðeins NVIDIA)" -> "Ræsa … (adeins NVIDIA)"; æ, å, ä, ö kennt sie)
BIOS_PLAIN = str.maketrans({"ı": "i", "İ": "I", "’": "'", "ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "ð": "d", "Ð": "D", "đ": "d", "Đ": "D",
                            "þ": "th", "Þ": "Th"})


def bios_text(text, fallback):
    """Text fuer das BIOS-Menue (Codepage 437): unveraendert, wenn er dort geht, sonst ohne Akzente
    (Čeština -> Cestina, Atpakaļ -> Atpakal), sonst der Ersatztext (Umschrift bzw. Englisch)."""
    plain = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    for cand in (text, plain.translate(BIOS_PLAIN)):
        try:
            cand.encode("cp437")
            return cand
        except UnicodeEncodeError:
            pass
    return fallback or text


def build_isolinux(cfg):
    kernel, base = isolinux_boot_lines(cfg)
    # 640x480, Schrift 8x16 -> 80 Spalten, 30 Zeilen; das Logo steht im Hintergrundbild (Zeilen 6–10).
    # Alle *ROW-Angaben verschieben sich um VSHIFT: Eintraege ab Zeile 13 (14 Zeilen; "Other Languages" hat mehr
    # Eintraege, dort blaettert das Menue mit den Pfeiltasten), Countdown Zeile 27
    out = [f"""# VoidStation Live – Startmenue (BIOS), erzeugt von grub-entries.py
UI vesamenu.c32
PROMPT 0
TIMEOUT {TIMEOUT * 10}
ONTIMEOUT vs-{DEFAULT[0]}-{DEFAULT[1]}
MENU BACKGROUND {SPLASH}
MENU TABMSG
MENU AUTOBOOT Start in # s
MENU WIDTH 80
MENU MARGIN 15
MENU ROWS 14
MENU VSHIFT 10
MENU TIMEOUTROW 17
MENU CMDLINEROW 18
MENU HELPMSGROW 19
MENU HELPMSGENDROW 19
MENU TABMSGROW 19

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
    # Kein DEFAULT: stuende er im Untermenue, oeffnete isolinux gleich dort statt auf der Sprachseite.
    # ONTIMEOUT startet trotzdem Deutsch › VoidStation Live (Labels gelten im ganzen Menue).
    # Untermenues erben Farben und Hintergrund. Die Datei wird in Codepage 437 geschrieben (Schrift des BIOS):
    # Akzente, die es dort nicht gibt, fallen weg (bios_text), Griechisch/Kyrillisch steht als Umschrift bzw. Englisch.
    en = next(lang for lang in LANGS if lang[0] == "en")

    def lang_menu(lang, ind):
        lid, lname, lextra, back, entries, translit = lang
        eng = {eid: title for eid, title, _ in en[4]}
        out = [f"{ind}MENU BEGIN vs-{lid}\n{ind}  MENU LABEL {bios_text(lname, translit)}\n{ind}  MENU TITLE\n"]
        for eid, title, extra in entries:
            out.append(f"{ind}  LABEL vs-{lid}-{eid}\n{ind}    MENU LABEL {bios_text(title, eng.get(eid, title))}\n"
                       f"{ind}    KERNEL {kernel}\n"
                       f"{ind}    APPEND {merge_args(base, extra + ' ' + lextra + ' ' + BIOS_EXTRA)}\n")
        out.append(f"{ind}  LABEL vs-{lid}-back\n{ind}    MENU LABEL {bios_text(back, en[3])}\n{ind}    MENU EXIT\n{ind}MENU END\n")
        return "\n".join(out)

    for lang in LANGS:
        if lang[0] in TOP:
            out.append(lang_menu(lang, ""))
    others = [lang for lang in LANGS if lang[0] not in TOP]
    if others:
        out.append(f"MENU BEGIN {OTHER[0]}\n  MENU LABEL {OTHER[1]}\n  MENU TITLE\n")
        out += [lang_menu(lang, "  ") for lang in others]
        out.append(f"  LABEL {OTHER[0]}-back\n    MENU LABEL {OTHER[2]}\n    MENU EXIT\nMENU END\n")
    out.append(f"LABEL {REBOOT[0]}\n  MENU LABEL {REBOOT[1]}\n  COM32 reboot.c32\n")
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
        local.write_text(build_grub(cfg, fonts, path), encoding="utf-8")
        maps += ["-map", str(local), path, "-map", str(theme), THEME_DIR]
        missing = [f for f in FONTS if f not in fonts]
        done.append(f"UEFI ({path}{', ohne ' + ', '.join(missing) if missing else ''})")

        if ISOLINUX in iso_files(src, "/boot/isolinux", "*.cfg"):
            iloc = Path(td) / "isolinux.cfg"
            iloc.write_text(build_isolinux(extract(src, ISOLINUX, iloc)), encoding="cp437", errors="replace")
            maps += ["-map", str(iloc), ISOLINUX, "-map", str(art / "isolinux" / "splash.png"), f"/boot/isolinux/{SPLASH}"]
            done.append(f"BIOS ({ISOLINUX})")
        else:
            print("Hinweis: kein isolinux-Menue gefunden – BIOS-Start behaelt das Standardmenue", file=sys.stderr)

        xorriso("-indev", src, "-outdev", dst, "-boot_image", "any", "replay",
                *maps, "-map", liesmich, "/LIESMICH.txt", "-map", readme, "/README.txt", "-commit")
    top = [l[1] for l in LANGS if l[0] in TOP] + [OTHER[1] + " (" + ", ".join(l[0] for l in LANGS if l[0] not in TOP) + ")"]
    print("Startmenue angepasst: " + ", ".join(done) + " – " + " / ".join(top) + " / " + REBOOT[1])


if __name__ == "__main__":
    if len(sys.argv) != 6:
        sys.exit(__doc__)
    main(*sys.argv[1:])
