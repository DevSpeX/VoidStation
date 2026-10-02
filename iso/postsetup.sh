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
ch() { chroot "$R" /usr/bin/env -i PATH=/usr/bin:/usr/sbin:/bin:/sbin HOME=/root TERM=dumb LANG=C.UTF-8 "$@"; }

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
d["user"] = {"de": "Gast", "en": "Guest"}
for g in d.get("groups", []):
    g["tiles"] = [t for t in g.get("tiles", []) if t.get("id") != "gba"]      # mGBA gibt es erst nach der Installation
d["groups"] = [g for g in d["groups"] if g.get("tiles")]
d["groups"].insert(0, {"name": {"de": "Installieren", "en": "Install"}, "tiles": [{
    "id": "install", "type": "install", "size": "large", "color": "#2f6d4f", "icon": "install",
    "label": {"de": "VoidStation installieren", "en": "Install VoidStation"},
    "sub": {"de": "auf diesen PC", "en": "on this PC"}}]})
json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
PYEOF
for f in radio.json tvfavs.json; do
  [ -f "$SRC/personal/$f" ] && install -m 644 "$SRC/personal/$f" "$TV/$f"
done
ch chown -R tv:tv /home/tv

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
