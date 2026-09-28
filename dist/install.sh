#!/bin/bash
# =====================================================================
#  VoidStation fuer Void Linux – Kacheloberflaeche fuer den Fernseher
#  Aufruf (per SSH als paul):   sudo bash install.sh
#  Optional anderer Benutzer:   sudo VSUSER=name bash install.sh
#  Optional EFISTUB (direkt booten, GRUB bleibt als Rueckfall):
#                               sudo EFISTUB=1 bash install.sh
# =====================================================================
set -euo pipefail

VSUSER="${VSUSER:-${SUDO_USER:-paul}}"
HOMEDIR="$(getent passwd "$VSUSER" | cut -d: -f6)"
TV="$HOMEDIR/.local/share/voidstation"
# Dienste-Ordner: im laufenden System /var/service, bei Installation vom Stick (chroot) der Standard-Runlevel
SVDIR="${SVDIR:-/var/service}"
CHROOT="${VOIDSTATION_CHROOT:-0}"

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[!] %s\033[0m\n' "$*"; }

[ "$(id -u)" -eq 0 ] || { echo "Bitte mit sudo starten: sudo bash install.sh"; exit 1; }
[ -n "$HOMEDIR" ] && [ -d "$HOMEDIR" ] || { echo "Benutzer '$VSUSER' nicht gefunden."; exit 1; }

say "Benutzer: $VSUSER ($HOMEDIR)"

# ---------------------------------------------------------------------
say "1/8  Nonfree-Repo und System-Update"
xbps-query void-repo-nonfree >/dev/null 2>&1 || xbps-install -Sy void-repo-nonfree
xbps-install -Syu xbps || true
xbps-install -Syu || true

# ---------------------------------------------------------------------
say "2/8  Pakete installieren"
# Grafiktreiber passend zur verbauten GPU
GPU_PKGS="mesa-dri"
for d in /sys/bus/pci/devices/*; do
  case "$(cat "$d/class" 2>/dev/null)" in 0x03*) ;; *) continue ;; esac
  case "$(cat "$d/vendor" 2>/dev/null)" in
    0x8086) echo "GPU: Intel";  GPU_PKGS="$GPU_PKGS mesa-intel-dri intel-video-accel mesa-vulkan-intel" ;;
    0x1002) echo "GPU: AMD";    GPU_PKGS="$GPU_PKGS mesa-ati-dri mesa-vaapi mesa-vdpau mesa-vulkan-radeon" ;;
    0x10de) echo "GPU: NVIDIA (nouveau)"; GPU_PKGS="$GPU_PKGS mesa-nouveau-dri" ;;
  esac
done
PKGS="xorg-minimal xinit xset xrandr setxkbmap $GPU_PKGS \
  openbox dbus elogind xrdb pulseaudio-utils curl python3 python3-evdev wmctrl unclutter-xfixes \
  firefox vlc mpv mgba-qt samba flatpak adwaita-qt adwaita-qt6 gnome-themes-extra xsetroot python3-gobject libwebkit2gtk41 pcmanfm gvfs xterm \
  pipewire wireplumber alsa-utils \
  noto-fonts-ttf noto-fonts-emoji noto-fonts-cjk dejavu-fonts-ttf \
  NetworkManager chrony"
MISSING=""
for p in $PKGS; do
  xbps-query "$p" >/dev/null 2>&1 && continue
  if xbps-query -R "$p" >/dev/null 2>&1; then MISSING="$MISSING $p"
  else warn "Paket nicht im Repo, uebersprungen: $p"; fi
done
if [ -n "$MISSING" ]; then xbps-install -Sy $MISSING; else echo "alles schon installiert"; fi

# ---------------------------------------------------------------------
say "3/8  Dateien entpacken nach $TV"
mkdir -p "$TV"
[ -f "$TV/tiles.json" ] && cp "$TV/tiles.json" /tmp/tiles.json.keep
sed -n '/^__PAYLOAD_BELOW__$/,$p' "$0" | tail -n +2 | base64 -d | tar -xz -C "$TV"
chmod +x "$TV/launcher.py" "$TV/home.sh" "$TV/vsctl" "$TV/voidstation-shell.py" "$TV/xstart"
echo "86bd9e0108af" > "$TV/VERSION"
echo 'eyJ2ZXJzaW9uIjogIjAuNi4wIiwgImJ1aWxkIjogIjg2YmQ5ZTAxMDhhZiIsICJkYXRlIjogIjIwMjYtMDktMjgiLCAiaGlzdG9yeSI6IFt7InZlcnNpb24iOiAiMC42LjAiLCAiZGF0ZSI6ICIyMDI2LTA5LTI4IiwgImNoYW5nZXMiOiBbIlNwcmFjaGU6IERldXRzY2ggb2RlciBFbmdsaXNjaCwgdW1zY2hhbHRiYXIgdW50ZXIgRWluc3RlbGx1bmdlbiDihpIgU3ByYWNoZSDCtyBMYW5ndWFnZSIsICLigJ5XYXMgaXN0IG5ldeKAnCBlcnNjaGVpbnQgaW4gZGVyIGdld8OkaGx0ZW4gU3ByYWNoZSIsICJVaHJ6ZWl0LCBEYXR1bSB1bmQgWmFobGVuIGltIEZvcm1hdCBkZXIgZ2V3w6RobHRlbiBTcHJhY2hlIiwgIlN0YW5kYXJkLUthY2hlbG4gd2VyZGVuIG1pdMO8YmVyc2V0enQsIGVpZ2VuZSBLYWNoZWxuYW1lbiBibGVpYmVuIHVudmVyw6RuZGVydCJdLCAiY2hhbmdlc19lbiI6IFsiTGFuZ3VhZ2U6IEdlcm1hbiBvciBFbmdsaXNoLCBzd2l0Y2ggdW5kZXIgU2V0dGluZ3Mg4oaSIExhbmd1YWdlIMK3IFNwcmFjaGUiLCAi4oCcV2hhdCdzIG5ld+KAnSBpcyBzaG93biBpbiB0aGUgc2VsZWN0ZWQgbGFuZ3VhZ2UiLCAiVGltZSwgZGF0ZSBhbmQgbnVtYmVycyBpbiB0aGUgZm9ybWF0IG9mIHRoZSBzZWxlY3RlZCBsYW5ndWFnZSIsICJEZWZhdWx0IHRpbGVzIGFyZSB0cmFuc2xhdGVkIHRvbywgeW91ciBvd24gdGlsZSBuYW1lcyBzdGF5IGFzIHRoZXkgYXJlIl19LCB7InZlcnNpb24iOiAiMC41LjEiLCAiZGF0ZSI6ICIyMDI2LTA5LTI4IiwgImNoYW5nZXMiOiBbIlVtenVnIG5hY2ggR2l0SHViIChnaXRodWIuY29tL1BhbnRoZXI5Mi9Wb2lkU3RhdGlvbikg4oCTIEdlcsOkdGUgYmV6aWVoZW4gVXBkYXRlcyBhYiBqZXR6dCB2b24gZG9ydCIsICJLdXJ6YmVmZWhsIHp1ciBOZXVpbnN0YWxsYXRpb246IHhicHMtZmV0Y2ggaHR0cHM6Ly9wYW50aGVyOTIuZ2l0aHViLmlvL1ZvaWRTdGF0aW9uL3ZzIl0sICJjaGFuZ2VzX2VuIjogWyJNb3ZlZCB0byBHaXRIdWIgKGdpdGh1Yi5jb20vUGFudGhlcjkyL1ZvaWRTdGF0aW9uKSDigJMgZGV2aWNlcyBub3cgZ2V0IHRoZWlyIHVwZGF0ZXMgZnJvbSB0aGVyZSIsICJTaG9ydCBjb21tYW5kIGZvciBhIGZyZXNoIGluc3RhbGw6IHhicHMtZmV0Y2ggaHR0cHM6Ly9wYW50aGVyOTIuZ2l0aHViLmlvL1ZvaWRTdGF0aW9uL3ZzIl19LCB7InZlcnNpb24iOiAiMC41LjAiLCAiZGF0ZSI6ICIyMDI2LTA5LTI4IiwgImNoYW5nZXMiOiBbIkdyYWZpay1TZXJ2ZXI6IFhMaWJyZSBzdGF0dCBYLk9yZyAoUGFrZXRxdWVsbGUgeGxpYnJlLXZvaWQsIFNjaGzDvHNzZWwgZmVzdCBoaW50ZXJsZWd0KSIsICJTaWNoZXJoZWl0c25ldHo6IHN0YXJ0ZXQgZGllIE9iZXJmbMOkY2hlIHp3ZWltYWwgbmljaHQsIHNjaGFsdGV0IFZvaWRTdGF0aW9uIGF1dG9tYXRpc2NoIGF1ZiBYLk9yZyB6dXLDvGNrIiwgIldhaGwgendpc2NoZW4gWExpYnJlIHVuZCBYLk9yZyB1bnRlciBFaW5zdGVsbHVuZ2VuIOKGkiBTeXN0ZW0g4oaSIEdyYWZpay1TZXJ2ZXIiXSwgImNoYW5nZXNfZW4iOiBbIkRpc3BsYXkgc2VydmVyOiBYTGlicmUgaW5zdGVhZCBvZiBYLk9yZyAoeGxpYnJlLXZvaWQgcmVwb3NpdG9yeSwga2V5IHBpbm5lZCkiLCAiU2FmZXR5IG5ldDogaWYgdGhlIGludGVyZmFjZSBmYWlscyB0byBzdGFydCB0d2ljZSwgVm9pZFN0YXRpb24gYXV0b21hdGljYWxseSBzd2l0Y2hlcyBiYWNrIHRvIFguT3JnIiwgIkNob29zZSBiZXR3ZWVuIFhMaWJyZSBhbmQgWC5PcmcgdW5kZXIgU2V0dGluZ3Mg4oaSIFN5c3RlbSDihpIgRGlzcGxheSBzZXJ2ZXIiXX0sIHsidmVyc2lvbiI6ICIwLjQuMCIsICJkYXRlIjogIjIwMjYtMDktMjgiLCAiY2hhbmdlcyI6IFsiVXBkYXRlLUthbsOkbGU6IOKAnlN0YWJpbOKAnCBmw7xyIGFsbGUsIOKAnlRlc3TigJwgenVtIEF1c3Byb2JpZXJlbiBuZXVlciBWZXJzaW9uZW4iLCAiVXBkYXRlcyBzaW5kIHNpZ25pZXJ0IOKAkyBHZXLDpHRlIGluc3RhbGxpZXJlbiBudXIgVXBkYXRlcyBtaXQgZ8O8bHRpZ2VyIFNpZ25hdHVyIiwgIkF1dG9tYXRpc2NoZSBVcGRhdGUtUHLDvGZ1bmcgbWl0IEhpbndlaXMgYXVmIGRlciBTdGFydHNlaXRlIiwgIlZlcnNpb25zbnVtbWVybiB1bmQg4oCeV2FzIGlzdCBuZXXigJwgaW0gVXBkYXRlLURpYWxvZyIsICJMaXplbno6IEdQTC0zLjAiXSwgImNoYW5nZXNfZW4iOiBbIlVwZGF0ZSBjaGFubmVsczog4oCcU3RhYmxl4oCdIGZvciBldmVyeW9uZSwg4oCcVGVzdGluZ+KAnSB0byB0cnkgbmV3IHZlcnNpb25zIGVhcmx5IiwgIlVwZGF0ZXMgYXJlIHNpZ25lZCDigJMgZGV2aWNlcyBvbmx5IGluc3RhbGwgdXBkYXRlcyB3aXRoIGEgdmFsaWQgc2lnbmF0dXJlIiwgIkF1dG9tYXRpYyB1cGRhdGUgY2hlY2sgd2l0aCBhIG5vdGljZSBvbiB0aGUgc3RhcnQgcGFnZSIsICJWZXJzaW9uIG51bWJlcnMgYW5kIOKAnFdoYXQncyBuZXfigJ0gaW4gdGhlIHVwZGF0ZSBkaWFsb2ciLCAiTGljZW5zZTogR1BMLTMuMCJdfSwgeyJ2ZXJzaW9uIjogIjAuMy4wIiwgImRhdGUiOiAiMjAyNi0wOS0yOCIsICJjaGFuZ2VzIjogWyJVcGRhdGUtS25vcGY6IFZvaWRTdGF0aW9uIGFrdHVhbGlzaWVydCBzaWNoIMO8YmVyIGRpZSBFaW5zdGVsbHVuZ2VuIHNlbGJzdCIsICJTdGVhbSBuYXRpdiBhdXMgZGVtIFZvaWQtUmVwbyAobm9uZnJlZSArIG11bHRpbGliKSBtaXQgYWt0dWVsbGVtIFByb3Rvbi1HRSIsICJTdGFydGJpbGRzY2hpcm0gYmxlaWJ0IHN0ZWhlbiwgYmlzIGVpbiBQcm9ncmFtbSB3aXJrbGljaCBlaW4gRmVuc3RlciB6ZWlndCIsICJBdWZsw7ZzdW5nOiA2MCBIeiBiZXZvcnp1Z3QsIEhhbGJiaWxkLU1vZGkgKDEwODBpKSB3ZXJkZW4gdmVybWllZGVuIiwgIkF1c2xhZ2VydW5nc2RhdGVpIGF1ZiBSZWNobmVybiBtaXQgd2VuaWdlciBhbHMgOCBHQiBSQU0iXSwgImNoYW5nZXNfZW4iOiBbIlVwZGF0ZSBidXR0b246IFZvaWRTdGF0aW9uIHVwZGF0ZXMgaXRzZWxmIGZyb20gdGhlIHNldHRpbmdzIiwgIlN0ZWFtIG5hdGl2ZWx5IGZyb20gdGhlIFZvaWQgcmVwb3NpdG9yeSAobm9uZnJlZSArIG11bHRpbGliKSB3aXRoIHRoZSBsYXRlc3QgUHJvdG9uLUdFIiwgIlRoZSBzcGxhc2ggc2NyZWVuIHN0YXlzIHVudGlsIGEgcHJvZ3JhbSByZWFsbHkgc2hvd3MgYSB3aW5kb3ciLCAiUmVzb2x1dGlvbjogNjAgSHogcHJlZmVycmVkLCBpbnRlcmxhY2VkIG1vZGVzICgxMDgwaSkgYXJlIGF2b2lkZWQiLCAiU3dhcCBmaWxlIG9uIGNvbXB1dGVycyB3aXRoIGxlc3MgdGhhbiA4IEdCIG9mIFJBTSJdfSwgeyJ2ZXJzaW9uIjogIjAuMi4wIiwgImRhdGUiOiAiMjAyNi0wOS0yNyIsICJjaGFuZ2VzIjogWyJOZXVlciBOYW1lOiBWb2lkU3RhdGlvbiIsICJOZXVpbnN0YWxsYXRpb24gZWluZXIgZ2FuemVuIFNTRCBtaXQgZWluZW0gQmVmZWhsIHZvbiBkZXIgb2ZmaXppZWxsZW4gVm9pZC1JU08iLCAiU2NyZWVuc2hvdHMsIFJhc3RlciBwYXNzZW4gc2ljaCBkZW0gUGxhdHogw7xiZXIgZGVyIEhpbndlaXN6ZWlsZSBhbiJdLCAiY2hhbmdlc19lbiI6IFsiTmV3IG5hbWU6IFZvaWRTdGF0aW9uIiwgIkZyZXNoIGluc3RhbGwgb2YgYSB3aG9sZSBTU0Qgd2l0aCBvbmUgY29tbWFuZCBmcm9tIHRoZSBvZmZpY2lhbCBWb2lkIElTTyIsICJTY3JlZW5zaG90czsgZ3JpZHMgYWRhcHQgdG8gdGhlIHNwYWNlIGFib3ZlIHRoZSBoaW50IGJhciJdfSwgeyJ2ZXJzaW9uIjogIjAuMS4wIiwgImRhdGUiOiAiMjAyNi0wOS0yNyIsICJjaGFuZ2VzIjogWyJLYWNoZWxvYmVyZmzDpGNoZSBtaXQgV2ViS2l0LVN0YXJ0c2VpdGUsIFJhZGlvLCBGZXJuc2VoZW4sIEFwcENlbnRlciwgRWluc3RlbGx1bmdlbiIsICJTYW1iYS1GcmVpZ2FiZSwgZHVua2xlcyBUaGVtZSwgZ3Jvw59lciBNYXVzemVpZ2VyLCBFRklTVFVCIl0sICJjaGFuZ2VzX2VuIjogWyJUaWxlIGludGVyZmFjZSB3aXRoIGEgV2ViS2l0IHN0YXJ0IHBhZ2UsIHJhZGlvLCBUViwgQXBwQ2VudGVyLCBzZXR0aW5ncyIsICJTYW1iYSBzaGFyZSwgZGFyayB0aGVtZSwgbGFyZ2UgbW91c2UgcG9pbnRlciwgRUZJU1RVQiJdfV19Cg==' | base64 -d > "$TV/version.json" 2>/dev/null || true

# Eigene, schon angepasste tiles.json behalten
if [ -f /tmp/tiles.json.keep ]; then
  mv -f /tmp/tiles.json.keep "$TV/tiles.json"; echo "eigene tiles.json behalten"
else
  # Neue Installation: Anzeigename oben rechts (VSNAME, sonst voller Name, sonst Benutzername)
  NAME="${VSNAME:-$(getent passwd "$VSUSER" | cut -d: -f5 | cut -d, -f1)}"
  [ -n "$NAME" ] || NAME="${VSUSER^}"
  python3 - "$TV/tiles.json" "$NAME" <<'PYEOF'
import json, sys
p, n = sys.argv[1], sys.argv[2]
d = json.load(open(p, encoding="utf-8")); d["user"] = n
json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
PYEOF
  echo "Anzeigename: $NAME"
fi

# ---------------------------------------------------------------------
say "4/8  Openbox, Autologin und X-Start"
install -d -o "$VSUSER" -g "$VSUSER" "$HOMEDIR/.config/openbox"
cp "$TV/openbox/"{rc.xml,menu.xml,autostart} "$HOMEDIR/.config/openbox/"

cat > "$HOMEDIR/.xinitrc" <<'EOF'
exec dbus-run-session openbox-session
EOF

touch "$HOMEDIR/.bash_profile"
sed -i 's/tvstart-runtime/voidstation-runtime/g; s/# TVSTART:/# VOIDSTATION:/' "$HOMEDIR/.bash_profile"
sed -i 's|^  exec startx -- -nolisten tcp vt1 >"$HOME/.xsession-errors" 2>&1$|  exec "$HOME/.local/share/voidstation/xstart"|' "$HOMEDIR/.bash_profile" 2>/dev/null || true
if ! grep -q 'VOIDSTATION' "$HOMEDIR/.bash_profile"; then
cat >> "$HOMEDIR/.bash_profile" <<'EOF'

# VOIDSTATION: grafische Oberflaeche automatisch auf tty1 starten
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
  # Eigener Laufzeitordner fuer die TV-Sitzung (unabhaengig von elogind)
  export XDG_RUNTIME_DIR="/tmp/voidstation-runtime-$(id -u)"
  rm -rf "$XDG_RUNTIME_DIR"; mkdir -m 0700 "$XDG_RUNTIME_DIR"
  exec "$HOME/.local/share/voidstation/xstart"
fi
EOF
fi

cat > /etc/sv/agetty-tty1/conf <<EOF
GETTY_ARGS="--autologin $VSUSER --noclear"
BAUD_RATE=38400
TERM_NAME=linux
EOF

# Gruppen: Gamepad/Eingabe, Ton, Grafik
for g in input audio video render; do
  getent group "$g" >/dev/null && usermod -aG "$g" "$VSUSER" || true
done

# ---------------------------------------------------------------------
say "5/8  Firefox-Profile (Startseite + YouTube)"
for p in home youtube; do
  install -d "$TV/profiles/$p"
  cp "$TV/firefox/user-common.js" "$TV/profiles/$p/user.js"
done
cat "$TV/firefox/user-youtube.js" >> "$TV/profiles/youtube/user.js"
install -d /etc/firefox/policies
cp "$TV/firefox/policies.json" /etc/firefox/policies/policies.json

# ---------------------------------------------------------------------
say "6/8  Ton (PipeWire) einrichten"
install -d /etc/pipewire/pipewire.conf.d /etc/alsa/conf.d
for f in /usr/share/examples/wireplumber/10-wireplumber.conf \
         /usr/share/examples/pipewire/20-pipewire-pulse.conf; do
  [ -e "$f" ] && ln -sf "$f" /etc/pipewire/pipewire.conf.d/ || warn "nicht gefunden: $f (Fallback im Autostart greift)"
done
for f in /usr/share/alsa/alsa.conf.d/50-pipewire.conf \
         /usr/share/alsa/alsa.conf.d/99-pipewire-default.conf; do
  [ -e "$f" ] && ln -sf "$f" /etc/alsa/conf.d/ || true
done

# ---------------------------------------------------------------------
say "7/8  Ausschalten ohne Passwort, GRUB ohne Wartezeit"
cat > /etc/sudoers.d/zz-voidstation <<EOF
$VSUSER ALL=(root) NOPASSWD: /usr/bin/poweroff, /usr/bin/reboot, /usr/bin/nmcli, /usr/local/sbin/voidstation-pkg
EOF
chmod 440 /etc/sudoers.d/zz-voidstation
visudo -cf /etc/sudoers.d/zz-voidstation >/dev/null || { warn "sudoers-Regel fehlerhaft, entferne sie"; rm -f /etc/sudoers.d/zz-voidstation; }

if [ -f /etc/default/grub ]; then
  sed -i 's/^#\?GRUB_TIMEOUT=.*/GRUB_TIMEOUT=0/' /etc/default/grub
  grep -q '^GRUB_TIMEOUT_STYLE' /etc/default/grub \
    && sed -i 's/^GRUB_TIMEOUT_STYLE=.*/GRUB_TIMEOUT_STYLE=hidden/' /etc/default/grub \
    || echo 'GRUB_TIMEOUT_STYLE=hidden' >> /etc/default/grub
  update-grub >/dev/null 2>&1 || grub-mkconfig -o /boot/grub/grub.cfg
fi

# ---------------------------------------------------------------------
if [ "${EFISTUB:-0}" = 1 ]; then
  say "Extra: EFISTUB (Kernel bootet direkt, GRUB bleibt als Rueckfall)"
  if [ ! -d /sys/firmware/efi ]; then
    warn "System laeuft nicht im UEFI-Modus – EFISTUB uebersprungen"
  else
    xbps-query efibootmgr >/dev/null 2>&1 || xbps-install -Sy efibootmgr
    ESP="$(findmnt -no TARGET -t vfat /boot/efi 2>/dev/null || true)"
    [ -n "$ESP" ] || ESP="$(findmnt -no TARGET -t vfat /boot 2>/dev/null || true)"
    if [ -z "$ESP" ]; then
      warn "Keine EFI-Partition unter /boot/efi oder /boot gefunden – uebersprungen"
    else
      ESPDEV="$(findmnt -no SOURCE "$ESP")"
      DISKDEV="/dev/$(lsblk -no PKNAME "$ESPDEV" | head -1)"
      PARTNO="$(cat "/sys/class/block/$(basename "$ESPDEV")/partition")"
      ROOTUUID="${ROOTUUID:-$(findmnt -no UUID / 2>/dev/null || true)}"
      [ -n "$ROOTUUID" ] || ROOTUUID="$(blkid -s UUID -o value "$(findmnt -no SOURCE /)")"
      # neuesten installierten Kernel nehmen (vom Stick aus laeuft ein anderer Kernel als der installierte)
      KVER="$(ls /boot/vmlinuz-* 2>/dev/null | sed 's|.*/vmlinuz-||' | sort -V | tail -1 || true)"
      KPKG="linux$(echo "${KVER:-$(uname -r)}" | cut -d. -f1-2)"
      FREE_MB=$(( $(df --output=avail -k "$ESP" | tail -1) / 1024 ))
      echo "EFI-Partition: $ESPDEV ($ESP) auf $DISKDEV, Partition $PARTNO, frei: ${FREE_MB} MB"
      if [ "$ESP" != "/boot" ] && [ "$FREE_MB" -lt 150 ]; then
        warn "Zu wenig Platz auf der EFI-Partition (<150 MB) – uebersprungen"
      else
        printf '%s\n' \
          'MODIFY_EFI_ENTRIES=1' \
          "OPTIONS=\"root=UUID=$ROOTUUID ro quiet loglevel=3 rd.udev.log_level=3\"" \
          "DISK=\"$DISKDEV\"" \
          "PART=$PARTNO" > /etc/default/efibootmgr-kernel-hook

        # Kernel + Initramfs auf die EFI-Partition kopieren (nur noetig, wenn sie unter /boot/efi haengt)
        if [ "$ESP" != "/boot" ]; then
          printf '%s\n' '#!/bin/sh' \
            '# VoidStation: Kernel fuer EFISTUB auf die EFI-Partition kopieren' \
            "cp -f \"/boot/vmlinuz-\$2\" \"/boot/initramfs-\$2.img\" \"$ESP/\"" \
            > /etc/kernel.d/post-install/40-voidstation-esp
          printf '%s\n' '#!/bin/sh' \
            "rm -f \"$ESP/vmlinuz-\$2\" \"$ESP/initramfs-\$2.img\"" \
            > /etc/kernel.d/post-remove/40-voidstation-esp
          chmod 744 /etc/kernel.d/post-install/40-voidstation-esp /etc/kernel.d/post-remove/40-voidstation-esp
        fi

        # Neuesten Void-Eintrag in der Bootreihenfolge nach vorn (auch nach Kernel-Updates)
        printf '%s\n' '#!/bin/sh' \
          'major=$(echo "$1" | cut -c 6-)' \
          'num=$(efibootmgr | grep -E "^Boot[0-9A-Fa-f]{4}\*? Void Linux with kernel ${major}([^0-9]|$)" | head -1 | cut -c5-8)' \
          '[ -n "$num" ] || exit 0' \
          'rest=$(efibootmgr | sed -n "s/^BootOrder: //p" | tr "," "\n" | grep -vi "^${num}$" | paste -sd, -)' \
          'efibootmgr -qo "${num}${rest:+,$rest}"' \
          > /etc/kernel.d/post-install/60-voidstation-bootorder
        chmod 744 /etc/kernel.d/post-install/60-voidstation-bootorder

        if xbps-reconfigure -f "$KPKG"; then
          echo
          efibootmgr 2>/dev/null | sed -n '1,4p;/Void Linux/p' || true
          echo "EFISTUB eingerichtet. GRUB bleibt als zweiter Eintrag erhalten."
        else
          warn "Kernel-Hook fehlgeschlagen – es bleibt beim Booten ueber GRUB"
        fi
      fi
    fi
  fi
fi

SHARE="$HOMEDIR/share"
say "Erscheinungsbild: dunkles Adwaita und Bibata-Mauszeiger"
for v in Ice Classic; do
  d="/usr/share/icons/Bibata-Modern-$v"
  if [ ! -d "$d/cursors" ]; then
    tmp="$(mktemp -d)"
    if curl -fsSL -o "$tmp/c.tar.xz" "https://github.com/ful1e5/Bibata_Cursor/releases/download/v2.0.7/Bibata-Modern-$v.tar.xz" \
       && python3 -c "import sys,tarfile; tarfile.open(sys.argv[1]).extractall('/usr/share/icons')" "$tmp/c.tar.xz"; then
      echo "Mauszeiger Bibata-Modern-$v installiert"
    else
      warn "Mauszeiger Bibata-Modern-$v konnte nicht geladen werden (es bleibt Adwaita)"
    fi
    rm -rf "$tmp"
  fi
done
mkdir -p /usr/share/icons/default
printf '[Icon Theme]\nInherits=Bibata-Modern-Ice\n' > /usr/share/icons/default/index.theme
mkdir -p "$HOMEDIR/.config/gtk-3.0" "$HOMEDIR/.config/gtk-4.0"
cat > "$HOMEDIR/.config/gtk-3.0/settings.ini" <<'GTK'
[Settings]
gtk-theme-name=Adwaita-dark
gtk-application-prefer-dark-theme=true
gtk-icon-theme-name=Adwaita
gtk-cursor-theme-name=Bibata-Modern-Ice
gtk-cursor-theme-size=48
gtk-font-name=Noto Sans 11
GTK
cat > "$HOMEDIR/.config/gtk-4.0/settings.ini" <<'GTK'
[Settings]
gtk-application-prefer-dark-theme=true
gtk-icon-theme-name=Adwaita
gtk-cursor-theme-name=Bibata-Modern-Ice
gtk-cursor-theme-size=48
GTK
cat > "$HOMEDIR/.gtkrc-2.0" <<'GTK'
gtk-theme-name="Adwaita-dark"
gtk-icon-theme-name="Adwaita"
gtk-cursor-theme-name="Bibata-Modern-Ice"
gtk-cursor-theme-size=48
GTK
# bestehende Firefox-Profile ebenfalls dunkel schalten
for uj in "$TV"/profiles/*/user.js; do
  [ -f "$uj" ] || continue
  grep -q 'prefers-color-scheme.content-override' "$uj" || cat >> "$uj" <<'JS'
user_pref("layout.css.prefers-color-scheme.content-override", 0);
user_pref("browser.theme.toolbar-theme", 0);
user_pref("browser.theme.content-theme", 0);
JS
done
chown -R "$VSUSER:$VSUSER" "$HOMEDIR/.config" "$HOMEDIR/.gtkrc-2.0"
echo "dunkles Theme eingerichtet (Mauszeiger-Stil und -Größe unter Einstellungen)"

say "Extra: AppCenter-Helfer (installiert nur freigegebene Pakete)"
install -o root -g root -m 755 "$TV/voidstation-pkg" /usr/local/sbin/voidstation-pkg
install -d -o root -g root -m 755 /usr/local/share/voidstation
python3 - "$TV/catalog.json" > /usr/local/share/voidstation/allowed-packages <<'PYEOF'
import json, sys
c = json.load(open(sys.argv[1], encoding="utf-8"))
pk = {"flatpak"}
for a in c["apps"]:
    s = a["source"]
    if s["type"] == "xbps":
        pk.add(s["pkg"])
    for k in ("repos", "deps", "optional", "host_pkgs"):
        pk.update(s.get(k, []))
    for v in s.get("gpu_deps", {}).values():
        pk.update(v)
pk = sorted(pk)
print("\n".join(pk))
PYEOF
chmod 644 /usr/local/share/voidstation/allowed-packages
echo "$(wc -l < /usr/local/share/voidstation/allowed-packages) Pakete freigegeben"
printf '%s\n' "https://raw.githubusercontent.com/Panther92/VoidStation/{channel}/dist" > /usr/local/share/voidstation/update-url
chmod 644 /usr/local/share/voidstation/update-url
# Update-Kanal (stable = fuer alle, main = Test); bestehende Wahl bleibt
[ -s /usr/local/share/voidstation/channel ] || echo stable > /usr/local/share/voidstation/channel
chmod 644 /usr/local/share/voidstation/channel
# Signaturschluessel: danach werden nur noch signierte Updates installiert
SIGNERS="$(echo 'dm9pZHN0YXRpb24tcmVsZWFzZSBuYW1lc3BhY2VzPSJ2b2lkc3RhdGlvbiIgc3NoLWVkMjU1MTkgQUFBQUMzTnphQzFsWkRJMU5URTVBQUFBSUZ2a1BRek96WEVMcWN3L0FoT2tjUkRWdXU3NmdySjAxUCtWMnVSZFRseEM=' | base64 -d 2>/dev/null || true)"
if [ -n "$SIGNERS" ]; then
  printf '%s\n' "$SIGNERS" > /usr/local/share/voidstation/allowed_signers
  chmod 644 /usr/local/share/voidstation/allowed_signers
  echo "Signaturpruefung fuer Updates aktiv"
fi

# ---------------------------------------------------------------------
say "X-Server: XLibre (Rueckfall auf X.Org, falls nicht verfuegbar)"
sh /usr/local/sbin/voidstation-pkg xserver auto || warn "XLibre nicht eingerichtet – es bleibt vorerst bei X.Org"

say "Extra: Freigabe-Ordner $SHARE"
for d in ROMs/gba ROMs/nes ROMs/snes ROMs/psx ROMs/psp ROMs/nds ROMs/gamecube ROMs/dreamcast \
         ROMs/dos ROMs/c64 ROMs/atari2600 ROMs/scummvm BIOS Musik Videos Bilder; do
  mkdir -p "$SHARE/$d"
done
[ -f "$SHARE/LIESMICH.txt" ] || cat > "$SHARE/LIESMICH.txt" <<'EOF'
VoidStation Freigabe
=================
ROMs/<system>   Spiele fuer die Emulatoren (gba, nes, snes, psx, psp, nds …)
BIOS            BIOS-Dateien (z. B. PlayStation fuer DuckStation)
Musik, Videos   eigene Medien fuer VLC oder Kodi
Bilder          fuer den Bildbetrachter
EOF
chown -R "$VSUSER:$VSUSER" "$SHARE"

say "Extra: Samba (Zugriff vom Windows-PC)"
HOST="$(cat /etc/hostname 2>/dev/null || hostname)"
if [ -f /etc/samba/smb.conf ] && ! grep -q 'VoidStation' /etc/samba/smb.conf; then
  cp /etc/samba/smb.conf /etc/samba/smb.conf.vor-voidstation
fi
mkdir -p /etc/samba /var/log/samba
cat > /etc/samba/smb.conf <<EOF
# VoidStation: Freigabe fuer den Windows-PC
[global]
   workgroup = WORKGROUP
   server string = VoidStation
   netbios name = ${HOST}
   server role = standalone server
   map to guest = never
   server min protocol = SMB2_10
   load printers = no
   printing = bsd
   printcap name = /dev/null
   disable spoolss = yes
   log file = /var/log/samba/%m.log
   max log size = 1000

[share]
   comment = VoidStation
   path = ${SHARE}
   valid users = ${VSUSER}
   force user = ${VSUSER}
   read only = no
   browseable = yes
   create mask = 0664
   directory mask = 0775
EOF
if pdbedit -L 2>/dev/null | grep -q "^${VSUSER}:" && [ -z "${SMBPASS:-}" ]; then
  echo "Freigabe-Benutzer $VSUSER existiert schon (Passwort bleibt)."
elif [ -n "${VOIDSTATION_NONINTERACTIVE:-}" ] && [ -z "${SMBPASS:-}" ]; then
  warn "Freigabe-Passwort fehlt – einmal per SSH setzen:  sudo smbpasswd -a $VSUSER"
else
  PW="${SMBPASS:-}"
  while [ -z "$PW" ]; do
    read -r -s -p "Passwort fuer die Freigabe (Benutzer $VSUSER): " PW1 </dev/tty; echo
    read -r -s -p "Nochmal: " PW2 </dev/tty; echo
    [ -n "$PW1" ] && [ "$PW1" = "$PW2" ] && PW="$PW1" || warn "Leer oder nicht gleich – bitte nochmal."
  done
  printf '%s\n%s\n' "$PW" "$PW" | smbpasswd -s -a "$VSUSER" >/dev/null && echo "Freigabe-Passwort gesetzt."
fi
for s in smbd nmbd; do
  [ -d "/etc/sv/$s" ] && { [ -e "$SVDIR/$s" ] || ln -s "/etc/sv/$s" "$SVDIR/"; }
done
[ "$CHROOT" = 1 ] || sv restart smbd >/dev/null 2>&1 || true

chown -R "$VSUSER:$VSUSER" "$HOMEDIR/.config" "$HOMEDIR/.local" "$HOMEDIR/.xinitrc" "$HOMEDIR/.bash_profile"

# ---------------------------------------------------------------------
# ---------------------------------------------------------------------
# Auslagerungsdatei bei wenig RAM: ohne Swap friert ein 4-GB-System bei
# Speicherdruck komplett ein, statt ein Programm zu beenden
MEM_MB=$(( $(awk '/MemTotal/{print $2}' /proc/meminfo) / 1024 ))
FREE_ROOT_MB=$(( $(df --output=avail -k / | tail -1) / 1024 ))
if [ "$MEM_MB" -lt 7800 ] && [ -z "$(swapon --noheadings --show 2>/dev/null)" ] && [ ! -e /swapfile ] \
   && [ "$FREE_ROOT_MB" -gt 6000 ]; then
  say "Auslagerungsdatei: 2 GB (RAM: ${MEM_MB} MB)"
  if dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none && chmod 600 /swapfile && mkswap -q /swapfile; then
    grep -q '^/swapfile' /etc/fstab || echo "/swapfile  none  swap  defaults  0 0" >> /etc/fstab
    if [ "${VOIDSTATION_CHROOT:-0}" != 1 ]; then swapon /swapfile && echo "aktiv"; fi
  else
    rm -f /swapfile; warn "Auslagerungsdatei konnte nicht angelegt werden"
  fi
fi

say "8/8  Dienste"
for s in dbus elogind sshd chronyd; do
  [ -d "/etc/sv/$s" ] || continue
  [ -e "$SVDIR/$s" ] || ln -s "/etc/sv/$s" "$SVDIR/"
done

NEED_NM=0
[ -e "$SVDIR/NetworkManager" ] || NEED_NM=1

cat <<EOF

---------------------------------------------------------------------
 Fertig.  Kacheln anpassen:  nano $TV/tiles.json
---------------------------------------------------------------------
EOF

if [ "$NEED_NM" = 1 ]; then
  if [ "$CHROOT" != 1 ]; then
    warn "Jetzt wird auf NetworkManager umgestellt (fuer WLAN)."
    warn "Die SSH-Verbindung kann dabei ~10 Sekunden haengen oder abbrechen – einfach neu verbinden."
    sleep 3
  fi
  rm -f "$SVDIR"/dhcpcd "$SVDIR"/dhcpcd-* "$SVDIR"/wpa_supplicant 2>/dev/null || true
  ln -s /etc/sv/NetworkManager "$SVDIR/"
fi

[ "$CHROOT" = 1 ] && exit 0
echo
echo "Zum Starten:  sudo reboot"
exit 0
__PAYLOAD_BELOW__
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
