#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# =====================================================================
#  VoidStation: Live-ISO mit Installer bauen
#  Laeuft auf einem Void-System (z. B. einer bestehenden VoidStation):
#      sudo bash build-iso.sh
#  Ergebnis: ~/share/ISO/voidstation-<version>-JJJJMMTT.iso  (+ .sha256)
#
#  Das Live-System ist eine komplette VoidStation (YouTube, Fernsehen, Radio,
#  Videos & Musik …) mit der Kachel "VoidStation installieren". Der Installer kopiert
#  genau dieses System auf die SSD – dafuer braucht er kein Internet.
#  Grafik-Server: XLibre (eigene Paketquelle repo.voidstation.de, wie vs-chdman).
#  Startmenue mit Logo (Start / Start NVIDIA only / Reboot), Startbild per Plymouth.
#  NVIDIA-Treiber (offene Kernel-Module, DKMS) ist dabei, laedt aber nur ueber
#  den Eintrag "NVIDIA only" – sonst laufen die freien Treiber.
#
#  32-Bit (experimentell):  sudo bash build-iso.sh --arch i686
#    -> ~/share/ISO/voidstation-<version>-i686-JJJJMMTT.iso
#    ohne NVIDIA und Plymouth, Startmenue nur fuer BIOS-Rechner sinnvoll,
#    Kernel-Parameter forcepae (Pentium M melden PAE nicht, koennen es aber).
#    Gebaut wird trotzdem auf einem x86_64-Rechner (void-mklive -a i686).
# =====================================================================
set -euo pipefail

REPO="${REPO:-https://repo-default.voidlinux.org/current}"
VS_REPO=https://repo.voidstation.de                        # eigene Paketquelle (derselbe Eintrag wie in voidstation-pkg)
VS_KEYFP=df:95:b3:5d:e1:24:a1:4d:1f:63:ff:f4:f3:56:af:5c
WORK="${WORK:-/var/tmp/voidstation-iso}"
VS_VERSION="__VS_RELEASE__"

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[!] %s\033[0m\n' "$*"; }
die()  { printf '\n\033[1;31m[x] %s\033[0m\n' "$*"; exit 1; }

# Zielarchitektur: x86_64 (Standard) oder i686 (experimentell); auch per Umgebung VS_ARCH=i686
ARCH="${VS_ARCH:-x86_64}"
while [ $# -gt 0 ]; do
  case "$1" in
    --arch)   [ $# -ge 2 ] || die "--arch braucht einen Wert (x86_64 oder i686)"; ARCH="$2"; shift 2 ;;
    --arch=*) ARCH="${1#--arch=}"; shift ;;
    --i686)   ARCH=i686; shift ;;
    *) die "Unbekannte Option: $1  (erlaubt: --arch x86_64|i686)" ;;
  esac
done
case "$ARCH" in
  x86_64) ARCHTAG="" ;;
  i686)   ARCHTAG="-i686" ;;
  *) die "Architektur $ARCH wird nicht unterstuetzt (x86_64 oder i686)." ;;
esac

[ "$(id -u)" -eq 0 ] || die "Bitte mit sudo starten: sudo bash build-iso.sh"
# ISOs nur aus freigegebenen Staenden (Zweig stable) – der Testing-Stand traegt "+testing" in der Version
case "$VS_VERSION" in
  *+testing*)
    [ "${VS_ALLOW_TESTING:-0}" = 1 ] || die "Das ist der Testing-Stand ($VS_VERSION) – ISOs werden aus Stable gebaut:
    git -C ~/VoidStation fetch -q origin && git -C ~/VoidStation show origin/stable:dist/build-iso.sh > /var/tmp/build-iso.sh
    sudo bash /var/tmp/build-iso.sh
  (Nur zum Ausprobieren trotzdem aus Testing: sudo VS_ALLOW_TESTING=1 bash build-iso.sh)" ;;
esac
command -v xbps-install >/dev/null || die "Das geht nur auf Void Linux."
[ "$(uname -m)" = x86_64 ] || die "Gebaut wird auf einem x86_64-Rechner."
VSUSER="${VSUSER:-${SUDO_USER:-paul}}"
HOMEDIR="$(getent passwd "$VSUSER" | cut -d: -f6)"
mkdir -p "$WORK"
FREE_GB=$(( $(df --output=avail -k "$WORK" | tail -1) / 1024 / 1024 ))
[ "$FREE_GB" -ge 12 ] || die "Zu wenig Platz in $WORK: ${FREE_GB} GB frei, mind. 12 GB noetig."

# ---------------------------------------------------------------------
say "1/5  Werkzeuge"
NEED=""
# grub-utils: grub-mkfont fuer die Schriften im Startmenue; Noto/DejaVu als Vorlage
for p in git squashfs-tools xorriso mtools dosfstools liblz4 python3 grub-x86_64-efi grub-i386-efi grub-utils \
         noto-fonts-ttf dejavu-fonts-ttf; do
  xbps-query "$p" >/dev/null 2>&1 || NEED="$NEED $p"
done
[ -z "$NEED" ] && echo "alles da" || xbps-install -Sy $NEED

# ---------------------------------------------------------------------
say "2/5  void-mklive holen"
if [ -d "$WORK/void-mklive/.git" ]; then
  git -C "$WORK/void-mklive" pull --ff-only -q || warn "Aktualisieren fehlgeschlagen, nehme vorhandene Version"
else
  git clone -q --depth 1 https://github.com/void-linux/void-mklive "$WORK/void-mklive"
fi
MK="$WORK/void-mklive"
[ -x "$MK/mklive.sh" ] || { make -C "$MK" >/dev/null 2>&1 || true; }
[ -x "$MK/mklive.sh" ] || die "mklive.sh nicht gefunden."
grep -q -e "-x <" -e "POST" "$MK/mklive.sh" || die "void-mklive ist zu alt (Option -x fehlt)."
echo "Stand: $(git -C "$MK" log -1 --format='%h vom %cd' --date=short)"

# ---------------------------------------------------------------------
say "3/5  VoidStation-Dateien fuer den Stick zusammenstellen"
SRC="$WORK/files"; INC="$WORK/include"
rm -rf "$SRC" "$INC"; mkdir -p "$SRC" "$INC"
sed -n '/^__PAYLOAD_BELOW__$/,$p' "$0" | tail -n +2 | base64 -d | tar -xz -C "$SRC"
chmod 755 "$SRC/postsetup.sh" "$SRC/grub-entries.py"          # mklive startet postsetup direkt

install -D -m 755 "$SRC/voidstation-installer"      "$INC/usr/local/sbin/voidstation-installer"
install -D -m 644 "$SRC/install.sh"                 "$INC/usr/local/share/voidstation/install.sh"
install -D -m 644 "$SRC/99-voidstation-live.sh"     "$INC/etc/runit/core-services/99-voidstation-live.sh"
install -D -m 440 "$SRC/sudoers-installer"          "$INC/etc/sudoers.d/zz-voidstation-installer"
install -D -m 644 /dev/null                         "$INC/etc/voidstation-live"
echo "$VS_VERSION" >                                "$INC/etc/voidstation-live"
# Startbild beim Hochfahren (Plymouth-Theme; aktiviert in postsetup.sh, beendet in 99-voidstation-live.sh)
PLY="$INC/usr/share/plymouth/themes/voidstation"
install -d "$PLY"
install -m 644 "$SRC/art/plymouth/"* "$PLY/"

# Schriften fuer das Startmenue (UEFI) – fehlen sie, nimmt GRUB seine eigene (klein, aber lesbar).
# Zeichen: Latein mit Akzenten (cs, lv, hu, pl, sk, tr …; ș ț fuer ro), Griechisch und Kyrillisch (el, ru, uk), Vietnamesisch (vi), Striche, Pfeile
mkfont() {  # <ttf> <name> <groesse> <datei>
  [ -f "$1" ] || { warn "Schrift fehlt: $1"; return 0; }
  grub-mkfont -n "$2" -s "$3" -r 0x20-0x7E,0xA0-0x17F,0x1A0-0x1B0,0x218-0x21B,0x370-0x3FF,0x400-0x4FF,0x1EA0-0x1EFF,0x2010-0x2027,0x2190-0x2193 -o "$SRC/art/grub/$4" "$1" \
    || warn "grub-mkfont: $4 nicht erzeugt"
}
NOTO=/usr/share/fonts/noto/NotoSans-Regular.ttf
mkfont "$NOTO" VoidStation 20 vs-20.pf2
mkfont "$NOTO" VoidStation 24 vs-24.pf2
mkfont "$NOTO" VoidStation 30 vs-30.pf2
mkfont /usr/share/fonts/TTF/DejaVuSansMono.ttf "VoidStation Mono" 20 vs-mono-20.pf2

# Keine eigenen Favoriten (Radio, TV) auf dem Stick: Radio schlaegt die beliebtesten Sender des Landes vor,
# Fernsehen zeigt die Sender des Landes – beides nach der Sprache aus dem Startmenue (region in launcher.py)

# Signaturschluessel der eigenen Paketquelle (derselbe wie in voidstation-pkg, vs_key) fuer den Bau
sed -n "/^  cat <<'KEYEOF'$/,/^KEYEOF$/p" "$SRC/voidstation-pkg" | sed '1d;$d' > "$MK/keys/$VS_KEYFP.plist"
grep -q '<plist' "$MK/keys/$VS_KEYFP.plist" || die "Schluessel der VoidStation-Paketquelle nicht gefunden."

# Paketliste: alles, was install.sh braucht, dazu Grafiktreiber fuer Intel, AMD und NVIDIA
# und die Werkzeuge des Installers
GPU_PKGS="mesa-dri mesa-intel-dri intel-video-accel mesa-vulkan-intel mesa-ati-dri mesa-vaapi mesa-vulkan-radeon mesa-nouveau-dri"
eval "$(sed -n '/^PKGS="/,/"$/p' "$SRC/install.sh" | head -20)"
[ -n "${PKGS:-}" ] || die "Paketliste aus install.sh nicht lesbar."
# grub = GRUB fuer BIOS (i386-pc), grub-x86_64-efi = fuer UEFI – der Installer richtet je nach Startmodus ein
# nvidia = NVIDIA-Treiber (nonfree, offene Kernel-Module per DKMS, GeForce GTX 16xx / RTX 20xx und neuer);
#          bringt dkms, gcc und die Kernel-Header mit. Der Installer entfernt das alles wieder, wenn der Stick
#          nicht ueber "NVIDIA only" gestartet wurde.
# plymouth = Startbild mit Logo (Stick und installiertes System; dort richtet es voidstation-splash ein)
# i686 (experimentell): ohne NVIDIA (kein 32-Bit-Treiber), ohne Plymouth (spart Zeit und RAM beim Start
# auf alten Rechnern) und ohne GRUB fuer 64-Bit-UEFI – 32-Bit-Rechner starten praktisch immer per BIOS.
LIVE_PKGS="$PKGS void-repo-nonfree intel-ucode xlibre-minimal linux-firmware grub efibootmgr dracut sudo \
  gparted ntfs-3g btrfs-progs dosfstools e2fsprogs xfsprogs gptfdisk pciutils util-linux tar curl"
REQUIRED="xlibre-minimal firefox python3 python3-pyside6-declarative NetworkManager grub"
CMDLINE="live.user=tv live.shell=/bin/bash quiet loglevel=3"
if [ "$ARCH" = x86_64 ]; then
  # vs-chdman: bin/cue -> CHD in der Spieleliste (eigene Paketquelle, nur x86_64)
  LIVE_PKGS="$LIVE_PKGS linux-firmware-nvidia nvidia plymouth grub-x86_64-efi vs-chdman"
  REQUIRED="$REQUIRED grub-x86_64-efi nvidia"
else
  # Pentium M (Banias, fruehe Dothan) koennen PAE, melden es aber nicht – ohne forcepae startet kein PAE-Kernel.
  # Auf CPUs, die PAE melden, aendert der Parameter nichts.
  # rd.live.overlay.overlayfs=1: Schreibschicht per OverlayFS statt Device-Mapper-Snapshot. void-mklive setzt
  # dafuer rd.overlayfs=1, das kennt dracut aber nicht (dort rd.overlay / rd.live.overlay.overlayfs) – ohne
  # bleibt der i686-Start beim Anlegen des Snapshots haengen (udev-Timeout fuer loop1/dm-0 nach 180 s,
  # gefunden in QEMU am 22.10.2026). Spart ausserdem den 32-GB-Overlay-Loop.
  CMDLINE="$CMDLINE forcepae rd.live.overlay.overlayfs=1"
  # 2D-Treiber fuer alte Grafik (ATI, Intel, NVIDIA, VIA): Xv fuer den Player ohne 3D-Treiber (s. install.sh)
  LIVE_PKGS="$LIVE_PKGS xlibre-xf86-video-ati xlibre-xf86-video-intel xlibre-xf86-video-nouveau xlibre-xf86-video-openchrome"
fi
LIVE_PKGS="$(echo $LIVE_PKGS | tr ' ' '\n' | awk 'NF && !seen[$0]++' | tr '\n' ' ')"
# Pakete, die es in den Quellen nicht (mehr) gibt, weglassen statt den ganzen Bau abzubrechen
# (XBPS_ARCH: die Paketlisten der Zielarchitektur pruefen, nicht die des Bau-Rechners)
XBPS_ARCH="$ARCH" xbps-install -S >/dev/null 2>&1 || warn "Paketlisten konnten nicht aktualisiert werden"
OK_PKGS="" SKIPPED=""
for p in $LIVE_PKGS; do
  if XBPS_ARCH="$ARCH" xbps-query -R "$p" >/dev/null 2>&1; then OK_PKGS="$OK_PKGS $p"; else SKIPPED="$SKIPPED $p"; fi
done
[ -n "$SKIPPED" ] && warn "nicht in den Paketquellen ($ARCH), weggelassen:$SKIPPED"
for p in $REQUIRED; do
  case " $OK_PKGS " in *" $p "*) ;; *) die "Pflichtpaket fehlt in den Paketquellen ($ARCH): $p" ;; esac
done
LIVE_PKGS="${OK_PKGS# }"
echo "$(echo $LIVE_PKGS | wc -w) Pakete fuer $ARCH"

# ---------------------------------------------------------------------
if [ "$ARCH" = x86_64 ]; then
  say "4/5  ISO bauen (Download ca. 2 GB, NVIDIA-Modul kompilieren, Komprimieren – ca. 25–50 Minuten)"
else
  say "4/5  ISO bauen fuer $ARCH (experimentell; Download ca. 1,5 GB, Komprimieren – ca. 20–40 Minuten)"
fi
STAMP="$(date +%Y%m%d)"
ISO="voidstation-${VS_VERSION}${ARCHTAG}-${STAMP}.iso"
export VOIDSTATION_SRC="$SRC" VOIDSTATION_ARCH="$ARCH"
cd "$MK"
./mklive.sh -a "$ARCH" \
  -r "$REPO" -r "$REPO/nonfree" -r "$VS_REPO" \
  -k de -l de_DE.UTF-8 -T "VoidStation" \
  -C "$CMDLINE" \
  -p "$LIVE_PKGS" -S "dbus NetworkManager chronyd" \
  -I "$INC" -x "$SRC/postsetup.sh" -o "$WORK/$ISO.raw"

# ---------------------------------------------------------------------
say "5/5  Startmenue mit Logo fuer UEFI und BIOS und LIESMICH"
python3 "$SRC/grub-entries.py" "$WORK/$ISO.raw" "$WORK/$ISO" "$SRC/LIESMICH.txt" "$SRC/README.txt" "$SRC/art" \
  || { warn "Startmenue nicht angepasst – ISO bleibt beim Standardmenue"; mv -f "$WORK/$ISO.raw" "$WORK/$ISO"; }
rm -f "$WORK/$ISO.raw"

OUT="$HOMEDIR/share/ISO"
install -d -o "$VSUSER" -g "$VSUSER" "$OUT"
mv -f "$WORK/$ISO" "$OUT/$ISO"
(cd "$OUT" && sha256sum "$ISO" > "$ISO.sha256")
chown "$VSUSER:$VSUSER" "$OUT/$ISO" "$OUT/$ISO.sha256"
SIZE=$(du -m "$OUT/$ISO" | cut -f1)
HOST="$(cat /etc/hostname 2>/dev/null || hostname)"

cat <<EOF

---------------------------------------------------------------------
 ISO fertig: $OUT/$ISO  (${SIZE} MB)
 Pruefsumme: $OUT/$ISO.sha256

 Unter Windows:  \\\\$HOST\\share\\ISO\\$ISO
 -> auf einen Ventoy-Stick kopieren oder mit Rufus/balenaEtcher schreiben.

 Paket-Cache bleibt in $MK (naechster Bau geht schneller).
---------------------------------------------------------------------
EOF
if [ "$ARCH" = i686 ]; then
  cat <<EOF
 32-Bit-ISO (experimentell). Probelauf ohne PAE-Flag wie auf einem Pentium M:
   qemu-system-i386 -enable-kvm -cpu qemu32,+sse2,-pae -m 1024 -vga std -boot d -cdrom $OUT/$ISO
 (ohne KVM-Zugriff -enable-kvm weglassen, dann langsam). Im Live-System:  dmesg | grep -i pae
 Veroeffentlichen nur ausdruecklich:  vspub --iso $OUT/$ISO
 (die Webseite bietet weiter die x86_64-ISO an).
---------------------------------------------------------------------
EOF
fi
exit 0
__PAYLOAD_BELOW__
