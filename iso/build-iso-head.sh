#!/bin/bash
# =====================================================================
#  VoidStation: eigenen Installations-Stick (ISO) bauen
#  Laeuft auf einem Void-System (z. B. dem Esprimo):
#      sudo bash build-iso.sh
#  Ergebnis: ~/share/ISO/voidstation-JJJJMMTT.iso  (auch unter \\<host>\share\ISO)
# =====================================================================
set -euo pipefail

REPO="https://repo-default.voidlinux.org/current"
WORK=/var/tmp/voidstation-iso
LIVE_PKGS="NetworkManager gptfdisk dosfstools e2fsprogs efibootmgr curl nano linux-firmware"

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[!] %s\033[0m\n' "$*"; }
die()  { printf '\n\033[1;31m[x] %s\033[0m\n' "$*"; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Bitte mit sudo starten: sudo bash build-iso.sh"
command -v xbps-install >/dev/null || die "Das geht nur auf Void Linux."
VSUSER="${VSUSER:-${SUDO_USER:-paul}}"
HOMEDIR="$(getent passwd "$VSUSER" | cut -d: -f6)"
mkdir -p "$WORK"
FREE_GB=$(( $(df --output=avail -k "$WORK" | tail -1) / 1024 / 1024 ))
[ "$FREE_GB" -ge 4 ] || die "Zu wenig Platz in $WORK: ${FREE_GB} GB frei, mind. 4 GB noetig."

# ---------------------------------------------------------------------
say "1/4  Werkzeuge"
NEED=""
for p in git squashfs-tools xorriso mtools dosfstools liblz4; do
  xbps-query "$p" >/dev/null 2>&1 || NEED="$NEED $p"
done
[ -z "$NEED" ] && echo "alles da" || xbps-install -Sy $NEED

# ---------------------------------------------------------------------
say "2/4  void-mklive holen"
if [ -d "$WORK/void-mklive/.git" ]; then
  git -C "$WORK/void-mklive" pull --ff-only -q || warn "Aktualisieren fehlgeschlagen, nehme vorhandene Version"
else
  git clone -q --depth 1 https://github.com/void-linux/void-mklive "$WORK/void-mklive"
fi
[ -x "$WORK/void-mklive/mklive.sh" ] || { make -C "$WORK/void-mklive" >/dev/null 2>&1 || true; }
[ -x "$WORK/void-mklive/mklive.sh" ] || die "mklive.sh nicht gefunden."
echo "Stand: $(git -C "$WORK/void-mklive" log -1 --format='%h vom %cd' --date=short)"

# ---------------------------------------------------------------------
say "3/4  VoidStation-Dateien fuer den Stick zusammenstellen"
SRC="$WORK/files"; INC="$WORK/include"
rm -rf "$SRC" "$INC"; mkdir -p "$SRC"
sed -n '/^__PAYLOAD_BELOW__$/,$p' "$0" | tail -n +2 | base64 -d | tar -xz -C "$SRC"

install -D -m 755 "$SRC/voidstation-install"         "$INC/usr/local/bin/voidstation-install"
install -D -m 644 "$SRC/install.sh"              "$INC/usr/local/share/voidstation/install.sh"
install -D -m 644 "$SRC/99-voidstation-live.sh"      "$INC/etc/runit/core-services/99-voidstation-live.sh"
install -D -m 644 "$SRC/voidstation-live-profile.sh" "$INC/etc/profile.d/zz-voidstation-live.sh"

# Eigene Favoriten (Radio, TV) mitnehmen, falls vorhanden
PERS=0
for f in radio.json tvfavs.json; do
  if [ -f "$HOMEDIR/.local/share/voidstation/$f" ]; then
    install -D -m 644 "$HOMEDIR/.local/share/voidstation/$f" "$INC/usr/local/share/voidstation/personal/$f"
    PERS=1
  fi
done
[ "$PERS" = 1 ] && echo "Radio-/TV-Favoriten von $VSUSER werden mitgenommen"

# ---------------------------------------------------------------------
say "4/4  ISO bauen (Download ~500 MB, danach Komprimieren – ca. 10–25 Minuten)"
ISO="voidstation-$(date +%Y%m%d).iso"
cd "$WORK/void-mklive"
./mklive.sh -a x86_64 -r "$REPO" \
  -k de -l de_DE.UTF-8 -T "VoidStation Installer" \
  -p "$LIVE_PKGS" -S "dbus NetworkManager sshd" \
  -I "$INC" -o "$WORK/$ISO"

OUT="$HOMEDIR/share/ISO"
install -d -o "$VSUSER" -g "$VSUSER" "$OUT"
mv -f "$WORK/$ISO" "$OUT/$ISO"
chown "$VSUSER:$VSUSER" "$OUT/$ISO"
SIZE=$(du -m "$OUT/$ISO" | cut -f1)
HOST="$(cat /etc/hostname 2>/dev/null || hostname)"

cat <<EOF

---------------------------------------------------------------------
 ISO fertig: $OUT/$ISO  (${SIZE} MB)

 Unter Windows:  \\\\$HOST\\share\\ISO\\$ISO
 -> einfach auf den Ventoy-Stick kopieren.

 Paket-Cache bleibt in $WORK/void-mklive (naechster Bau geht schneller).
---------------------------------------------------------------------
EOF
exit 0
__PAYLOAD_BELOW__
