#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# VoidStation Live-ISO: wird von void-mklive (-x) aufgerufen, bevor das Initramfs entsteht.
# $1 = Wurzel des Live-Systems. Richtet dort VoidStation fuer den Live-Benutzer "tv" ein –
# mit demselben install.sh wie jede Installation (VOIDSTATION_LIVE=1: ohne Swap, Freigabe und SSH).
# Dazu: NVIDIA-Modul pruefen und Treiberwahl per Startmenue vorbereiten, Startbild (Plymouth) einschalten.
set -euo pipefail
R="$1"
SRC="${VOIDSTATION_SRC:?}"
say() { printf '\n\033[1;36m--> %s\033[0m\n' "$*"; }
ARCH="${VOIDSTATION_ARCH:-x86_64}"
# 32-Bit-Abbild auf einem 64-Bit-Bau-Rechner: setarch sorgt dafuer, dass uname im Chroot i686 meldet
# (xbps und install.sh richten sich danach, sonst hielten sie das Abbild fuer x86_64)
CHPRE=(); [ "$ARCH" = i686 ] && CHPRE=(setarch i686)
ch() { "${CHPRE[@]}" chroot "$R" /usr/bin/env -i PATH=/usr/bin:/usr/sbin:/bin:/sbin HOME=/root TERM=dumb LANG=C.UTF-8 "$@"; }

say "Live-Benutzer tv"
cp -L /etc/resolv.conf "$R/etc/resolv.conf"             # nur fuer Downloads beim Bau (Mauszeiger)
if ! ch id tv >/dev/null 2>&1; then
  groups=""
  for g in wheel audio video input render network plugdev storage; do
    ch getent group "$g" >/dev/null 2>&1 && groups="$groups,$g"
  done
  ch useradd -m -s /bin/bash -c Gast -G "${groups#,}" tv
fi

say "VoidStation einrichten (install.sh, Live-Modus)"
ch VSUSER=tv VSNAME=Gast SVDIR=/etc/runit/runsvdir/default VOIDSTATION_CHROOT=1 VOIDSTATION_LIVE=1 \
   VOIDSTATION_OFFLINE=1 VOIDSTATION_NOSSH=1 VOIDSTATION_NONINTERACTIVE=1 \
   bash /usr/local/share/voidstation/install.sh

say "Kacheln fuer das Live-System"
TV="$R/home/tv/.local/share/voidstation"
python3 - "$TV/tiles.json" <<'PYEOF'
import json, sys
p = sys.argv[1]
d = json.load(open(p, encoding="utf-8"))
# Texte in allen Sprachen der Oberflaeche (LANG_TABLE in launcher.py); fehlt eine, gilt Englisch
d.pop("radio_suggestions", None)            # Radio schlaegt die beliebtesten Sender des Landes vor
d["user"] = {"de": "Gast", "en": "Guest", "cs": "Host", "es": "Invitado", "fr": "Invité", "it": "Ospite", "lv": "Viesis",
             "hu": "Vendég", "nl": "Gast", "pl": "Gość", "pt-BR": "Convidado", "sk": "Hosť", "el": "Επισκέπτης",
             "ru": "Гость", "uk": "Гість", "ja": "ゲスト", "ro": "Invitat", "tr": "Misafir", "ko": "게스트",
             "zh-CN": "访客", "zh-TW": "訪客", "da": "Gæst", "sv": "Gäst", "nb": "Gjest", "is": "Gestur", "fi": "Vieras",
             "et": "Külaline", "id": "Tamu", "ms": "Tetamu", "vi": "Khách", "th": "ผู้มาเยือน", "hi": "अतिथि", "ta": "விருந்தினர்",
             "ml": "അതിഥി"}
for g in d.get("groups", []):
    g["tiles"] = [t for t in g.get("tiles", []) if t.get("id") != "gba"]      # mGBA gibt es erst nach der Installation
d["groups"] = [g for g in d["groups"] if g.get("tiles")]
d["groups"].insert(0, {"name": {
    "de": "Installieren", "en": "Install", "cs": "Instalace", "es": "Instalar", "fr": "Installer", "it": "Installa",
    "lv": "Instalēt", "hu": "Telepítés", "nl": "Installeren", "pl": "Instalacja", "pt-BR": "Instalar", "sk": "Inštalácia",
    "el": "Εγκατάσταση", "ru": "Установка", "uk": "Встановлення", "ja": "インストール", "ro": "Instalare",
    "tr": "Kurulum", "ko": "설치", "zh-CN": "安装", "zh-TW": "安裝", "da": "Installation", "sv": "Installation",
    "nb": "Installasjon", "is": "Uppsetning", "fi": "Asennus", "et": "Paigaldamine", "id": "Instal", "ms": "Pasang",
    "vi": "Cài đặt", "th": "ติดตั้ง", "hi": "इंस्टॉल करें", "ta": "நிறுவு", "ml": "ഇൻസ്റ്റാൾ ചെയ്യുക"}, "tiles": [{
    "id": "install", "type": "install", "size": "large", "color": "#2f6d4f", "icon": "install",
    "label": {"de": "VoidStation installieren", "en": "Install VoidStation", "cs": "Nainstalovat VoidStation",
              "es": "Instalar VoidStation", "fr": "Installer VoidStation", "it": "Installa VoidStation",
              "lv": "Instalēt VoidStation", "hu": "VoidStation telepítése", "nl": "VoidStation installeren",
              "pl": "Zainstaluj VoidStation", "pt-BR": "Instalar o VoidStation", "sk": "Nainštalovať VoidStation",
              "el": "Εγκατάσταση VoidStation", "ru": "Установить VoidStation", "uk": "Встановити VoidStation",
              "ja": "VoidStationをインストール", "ro": "Instalează VoidStation", "tr": "VoidStation’ı kur",
              "ko": "VoidStation 설치", "zh-CN": "安装 VoidStation", "zh-TW": "安裝 VoidStation",
              "da": "Installer VoidStation", "sv": "Installera VoidStation", "nb": "Installer VoidStation",
              "is": "Setja upp VoidStation", "fi": "Asenna VoidStation", "et": "Paigalda VoidStation",
              "id": "Instal VoidStation", "ms": "Pasang VoidStation", "vi": "Cài đặt VoidStation", "th": "ติดตั้ง VoidStation",
              "hi": "VoidStation इंस्टॉल करें", "ta": "VoidStation ஐ நிறுவு", "ml": "VoidStation ഇൻസ്റ്റാൾ ചെയ്യുക"},
    "sub": {"de": "auf diesen PC", "en": "on this PC", "cs": "na tento počítač", "es": "en este PC", "fr": "sur ce PC",
            "it": "su questo PC", "lv": "šajā datorā", "hu": "erre a gépre", "nl": "op deze pc", "pl": "na tym komputerze",
            "pt-BR": "neste PC", "sk": "na tento počítač", "el": "σε αυτόν τον υπολογιστή", "ru": "на этот компьютер",
            "uk": "на цей комп’ютер", "ja": "このPCに", "ro": "pe acest PC", "tr": "bu PC’ye", "ko": "이 PC에",
            "zh-CN": "到这台电脑", "zh-TW": "到這台電腦", "da": "på denne pc", "sv": "på den här datorn", "nb": "på denne PC-en",
            "is": "á þessa tölvu", "fi": "tälle tietokoneelle", "et": "sellesse arvutisse",
            "id": "di PC ini", "ms": "pada PC ini", "vi": "trên PC này", "th": "บน PC เครื่องนี้", "hi": "इस PC पर",
            "ta": "இந்த PC யில்", "ml": "ഈ PC-യിൽ"}}]})
json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
PYEOF
ch chown -R tv:tv /home/tv

if ch xbps-query nvidia >/dev/null 2>&1; then
say "NVIDIA-Treiber (nur ueber den Eintrag \"NVIDIA only\")"
KVER="$(ls "$R/usr/lib/modules" | sort -V | tail -1)"
nvko() { [ -n "$(find "$R/usr/lib/modules/$KVER" -name 'nvidia-drm.ko*' -print -quit 2>/dev/null)" ]; }
if ! nvko; then
  echo "Modul fuer $KVER fehlt noch – baue es mit DKMS …"
  ch dkms autoinstall -k "$KVER" || true
  ch depmod -a "$KVER" || true
fi
nvko || { echo "[x] NVIDIA-Modul fuer Kernel $KVER fehlt (DKMS-Bau fehlgeschlagen, siehe /var/lib/dkms im Bauordner)"; exit 1; }
echo "nvidia-drm fuer $KVER vorhanden"
mkdir -p "$R/etc/modprobe.d"
# Das Paket sperrt nouveau (/usr/lib/modprobe.d/nvidia.conf). Auf dem Stick entscheidet der Startmenue-Eintrag
# (modprobe.blacklist=… auf der Kernel-Befehlszeile) – gleichnamige Datei in /etc ersetzt die Sperre.
# Der Installer loescht sie, wenn er den NVIDIA-Treiber uebernimmt.
cat > "$R/etc/modprobe.d/nvidia.conf" <<'EOF'
# VoidStation Live: nouveau hier NICHT sperren – welcher Treiber laedt, bestimmt der Eintrag im Startmenue.
# Ersetzt /usr/lib/modprobe.d/nvidia.conf (blacklist nouveau). Der Installer entfernt diese Datei,
# wenn das installierte System den NVIDIA-Treiber bekommt.
EOF
cat > "$R/etc/modprobe.d/voidstation-nvidia.conf" <<'EOF'
# VoidStation: NVIDIA mit Kernel-Modesetting (Konsole/Startbild in voller Aufloesung, X ueber nvidia-drm)
options nvidia_drm modeset=1 fbdev=1
EOF
else
  say "NVIDIA-Treiber: nicht dabei ($ARCH) – nur freie Treiber"
fi

say "Startbild (Plymouth)"
if [ -f "$R/usr/share/plymouth/themes/voidstation/voidstation.plymouth" ] && [ -x "$R/usr/bin/plymouthd" ]; then
  mkdir -p "$R/etc/plymouth"
  printf '[Daemon]\nTheme=voidstation\nShowDelay=0\nDeviceTimeout=8\n' > "$R/etc/plymouth/plymouthd.conf"
  echo "Theme voidstation aktiv (landet mit dem Initramfs auf dem Stick)"
else
  echo "Plymouth oder Theme fehlt – Start ohne Startbild"
fi

say "Aufraeumen"
rm -f "$R/etc/resolv.conf"
ch xbps-remove -Oy >/dev/null 2>&1 || true              # Paket-Cache nicht mit auf den Stick
rm -rf "$R/var/cache/xbps/"*
echo "Live-System fertig eingerichtet."
