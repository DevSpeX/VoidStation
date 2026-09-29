#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# =====================================================================
#  VoidStation: Live-ISO mit Installer bauen
#  Laeuft auf einem Void-System (z. B. einer bestehenden VoidStation):
#      sudo bash build-iso.sh
#  Ergebnis: ~/share/ISO/voidstation-<version>-JJJJMMTT.iso  (+ .sha256)
#
#  Das Live-System ist eine komplette VoidStation (YouTube, Fernsehen, Radio,
#  VLC …) mit der Kachel "VoidStation installieren". Der Installer kopiert
#  genau dieses System auf die SSD – dafuer braucht er kein Internet.
#  Grafik-Server: XLibre (Paketquelle xlibre-void).
# =====================================================================
set -euo pipefail

REPO="${REPO:-https://repo-default.voidlinux.org/current}"
XLIBRE_REPO=https://github.com/xlibre-void/xlibre/releases/latest/download
XLIBRE_KEYFP=00:ca:42:57:c9:c0:9a:ec:94:b4:7d:97:e5:a9:aa:1e
WORK="${WORK:-/var/tmp/voidstation-iso}"
VS_VERSION="__VS_RELEASE__"

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[!] %s\033[0m\n' "$*"; }
die()  { printf '\n\033[1;31m[x] %s\033[0m\n' "$*"; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Bitte mit sudo starten: sudo bash build-iso.sh"
command -v xbps-install >/dev/null || die "Das geht nur auf Void Linux."
[ "$(uname -m)" = x86_64 ] || die "Gebaut wird auf einem x86_64-Rechner."
VSUSER="${VSUSER:-${SUDO_USER:-paul}}"
HOMEDIR="$(getent passwd "$VSUSER" | cut -d: -f6)"
mkdir -p "$WORK"
FREE_GB=$(( $(df --output=avail -k "$WORK" | tail -1) / 1024 / 1024 ))
[ "$FREE_GB" -ge 10 ] || die "Zu wenig Platz in $WORK: ${FREE_GB} GB frei, mind. 10 GB noetig."

# ---------------------------------------------------------------------
say "1/5  Werkzeuge"
NEED=""
for p in git squashfs-tools xorriso mtools dosfstools liblz4 python3 grub-x86_64-efi grub-i386-efi; do
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

# Eigene Favoriten (Radio, TV) mitnehmen, falls vorhanden – im Live-System schon da
PERS="$SRC/personal"; mkdir -p "$PERS"
for f in radio.json tvfavs.json; do
  [ -f "$HOMEDIR/.local/share/voidstation/$f" ] && cp "$HOMEDIR/.local/share/voidstation/$f" "$PERS/" && echo "nehme mit: $f"
done

# Signaturschluessel der XLibre-Quelle (derselbe wie in voidstation-pkg) fuer den Bau
sed -n "/^  cat <<'KEYEOF'$/,/^KEYEOF$/p" "$SRC/voidstation-pkg" | sed '1d;$d' > "$MK/keys/$XLIBRE_KEYFP.plist"
grep -q '<plist' "$MK/keys/$XLIBRE_KEYFP.plist" || die "XLibre-Schluessel nicht gefunden."

# Paketliste: alles, was install.sh braucht, dazu Grafiktreiber fuer Intel, AMD und NVIDIA
# und die Werkzeuge des Installers
GPU_PKGS="mesa-dri mesa-intel-dri intel-video-accel mesa-vulkan-intel mesa-ati-dri mesa-vaapi mesa-vulkan-radeon mesa-nouveau-dri"
eval "$(sed -n '/^PKGS="/,/"$/p' "$SRC/install.sh" | head -20)"
[ -n "${PKGS:-}" ] || die "Paketliste aus install.sh nicht lesbar."
LIVE_PKGS="$PKGS void-repo-nonfree xlibre-minimal linux-firmware grub-x86_64-efi efibootmgr dracut sudo \
  gparted ntfs-3g btrfs-progs dosfstools e2fsprogs xfsprogs gptfdisk pciutils util-linux tar curl"
LIVE_PKGS="$(echo $LIVE_PKGS | tr ' ' '\n' | awk 'NF && !seen[$0]++' | tr '\n' ' ')"
# Pakete, die es in den Quellen nicht (mehr) gibt, weglassen statt den ganzen Bau abzubrechen
xbps-install -S >/dev/null 2>&1 || warn "Paketlisten konnten nicht aktualisiert werden"
OK_PKGS="" SKIPPED=""
for p in $LIVE_PKGS; do
  if xbps-query -R "$p" >/dev/null 2>&1; then OK_PKGS="$OK_PKGS $p"; else SKIPPED="$SKIPPED $p"; fi
done
[ -n "$SKIPPED" ] && warn "nicht in den Paketquellen, weggelassen:$SKIPPED"
for p in xlibre-minimal firefox python3 NetworkManager grub-x86_64-efi; do
  case " $OK_PKGS " in *" $p "*) ;; *) die "Pflichtpaket fehlt in den Paketquellen: $p" ;; esac
done
LIVE_PKGS="${OK_PKGS# }"
echo "$(echo $LIVE_PKGS | wc -w) Pakete"

# ---------------------------------------------------------------------
say "4/5  ISO bauen (Download ca. 1,5 GB, danach Komprimieren – ca. 20–40 Minuten)"
STAMP="$(date +%Y%m%d)"
ISO="voidstation-${VS_VERSION}-${STAMP}.iso"
export VOIDSTATION_SRC="$SRC"
cd "$MK"
./mklive.sh -a x86_64 \
  -r "$REPO" -r "$REPO/nonfree" -r "$XLIBRE_REPO" \
  -k de -l de_DE.UTF-8 -T "VoidStation" \
  -C "live.user=tv live.shell=/bin/bash quiet loglevel=3" \
  -p "$LIVE_PKGS" -S "dbus elogind NetworkManager chronyd" \
  -I "$INC" -x "$SRC/postsetup.sh" -o "$WORK/$ISO.raw"

# ---------------------------------------------------------------------
say "5/5  Startmenue (Deutsch/English, Installieren) und LIESMICH"
python3 "$SRC/grub-entries.py" "$WORK/$ISO.raw" "$WORK/$ISO" "$SRC/LIESMICH.txt" "$SRC/README.txt" \
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
exit 0
__PAYLOAD_BELOW__
