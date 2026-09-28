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

# Sprachen der Oberflaeche: deutsches und englisches Locale erzeugen (VLC, Dateimanager usw. folgen der UI-Sprache)
if [ -f /etc/default/libc-locales ]; then
  LCH=0
  for l in de_DE en_US; do
    if ! grep -q "^$l.UTF-8 UTF-8" /etc/default/libc-locales && grep -q "^#[[:space:]]*$l.UTF-8 UTF-8" /etc/default/libc-locales; then
      sed -i "s/^#[[:space:]]*\($l.UTF-8 UTF-8\)/\1/" /etc/default/libc-locales; LCH=1
    fi
  done
  if [ "$LCH" = 1 ]; then xbps-reconfigure -f glibc-locales >/dev/null 2>&1 && echo "Locales de_DE und en_US erzeugt" || warn "Locales konnten nicht erzeugt werden"; fi
fi

# ---------------------------------------------------------------------
say "3/8  Dateien entpacken nach $TV"
mkdir -p "$TV"
[ -f "$TV/tiles.json" ] && cp "$TV/tiles.json" /tmp/tiles.json.keep
sed -n '/^__PAYLOAD_BELOW__$/,$p' "$0" | tail -n +2 | base64 -d | tar -xz -C "$TV"
chmod +x "$TV/launcher.py" "$TV/home.sh" "$TV/vsctl" "$TV/voidstation-shell.py" "$TV/xstart"
echo "24cbbf773721" > "$TV/VERSION"
echo 'eyJ2ZXJzaW9uIjogIjAuNi4xIiwgImJ1aWxkIjogIjI0Y2JiZjc3MzcyMSIsICJkYXRlIjogIjIwMjYtMDktMjgiLCAiaGlzdG9yeSI6IFt7InZlcnNpb24iOiAiMC42LjEiLCAiZGF0ZSI6ICIyMDI2LTA5LTI4IiwgImNoYW5nZXMiOiBbIlByb2dyYW1tZSB3aWUgVkxDLCBEYXRlaW1hbmFnZXIgdW5kIFlvdVR1YmUgc3RhcnRlbiBpbiBkZXIgZ2V3w6RobHRlbiBTcHJhY2hlIiwgIlBmZWlsZSBvYmVuIHJlY2h0cyB6ZWlnZW4sIGRhc3MgZXMgbGlua3Mgb2RlciByZWNodHMgd2VpdGVyZ2VodDsgZWluIFB1bmt0IGplIEdydXBwZSIsICJHcnVwcGVud2Vpc2UgYmzDpHR0ZXJuOiBMVCAvIFJUIGFtIENvbnRyb2xsZXIsIEJpbGQg4oaRIC8gQmlsZCDihpMgYXVmIGRlciBUYXN0YXR1ciIsICJVcGRhdGUtSGlud2VpcyB1bnRlbiByZWNodHMgbWl0IGdlbGJlbSBXYXJuZHJlaWVjayDigJMgw7ZmZm5lbiBtaXQgVSBvZGVyIFNlbGVjdCBhbSBDb250cm9sbGVyIl0sICJjaGFuZ2VzX2VuIjogWyJQcm9ncmFtcyBsaWtlIFZMQywgdGhlIGZpbGUgbWFuYWdlciBhbmQgWW91VHViZSBzdGFydCBpbiB0aGUgc2VsZWN0ZWQgbGFuZ3VhZ2UiLCAiQXJyb3dzIGF0IHRoZSB0b3AgcmlnaHQgc2hvdyB0aGF0IHRoZXJlIGlzIG1vcmUgdG8gdGhlIGxlZnQgb3IgcmlnaHQ7IG9uZSBkb3QgcGVyIGdyb3VwIiwgIkp1bXAgZ3JvdXAgYnkgZ3JvdXA6IExUIC8gUlQgb24gdGhlIGNvbnRyb2xsZXIsIFBhZ2UgVXAgLyBQYWdlIERvd24gb24gdGhlIGtleWJvYXJkIiwgIlVwZGF0ZSBub3RpY2UgYXQgdGhlIGJvdHRvbSByaWdodCB3aXRoIGEgeWVsbG93IHdhcm5pbmcgdHJpYW5nbGUg4oCTIG9wZW4gaXQgd2l0aCBVIG9yIFNlbGVjdCBvbiB0aGUgY29udHJvbGxlciJdfSwgeyJ2ZXJzaW9uIjogIjAuNi4wIiwgImRhdGUiOiAiMjAyNi0wOS0yOCIsICJjaGFuZ2VzIjogWyJTcHJhY2hlOiBEZXV0c2NoIG9kZXIgRW5nbGlzY2gsIHVtc2NoYWx0YmFyIHVudGVyIEVpbnN0ZWxsdW5nZW4g4oaSIFNwcmFjaGUgwrcgTGFuZ3VhZ2UiLCAi4oCeV2FzIGlzdCBuZXXigJwgZXJzY2hlaW50IGluIGRlciBnZXfDpGhsdGVuIFNwcmFjaGUiLCAiVWhyemVpdCwgRGF0dW0gdW5kIFphaGxlbiBpbSBGb3JtYXQgZGVyIGdld8OkaGx0ZW4gU3ByYWNoZSIsICJTdGFuZGFyZC1LYWNoZWxuIHdlcmRlbiBtaXTDvGJlcnNldHp0LCBlaWdlbmUgS2FjaGVsbmFtZW4gYmxlaWJlbiB1bnZlcsOkbmRlcnQiXSwgImNoYW5nZXNfZW4iOiBbIkxhbmd1YWdlOiBHZXJtYW4gb3IgRW5nbGlzaCwgc3dpdGNoIHVuZGVyIFNldHRpbmdzIOKGkiBMYW5ndWFnZSDCtyBTcHJhY2hlIiwgIuKAnFdoYXQncyBuZXfigJ0gaXMgc2hvd24gaW4gdGhlIHNlbGVjdGVkIGxhbmd1YWdlIiwgIlRpbWUsIGRhdGUgYW5kIG51bWJlcnMgaW4gdGhlIGZvcm1hdCBvZiB0aGUgc2VsZWN0ZWQgbGFuZ3VhZ2UiLCAiRGVmYXVsdCB0aWxlcyBhcmUgdHJhbnNsYXRlZCB0b28sIHlvdXIgb3duIHRpbGUgbmFtZXMgc3RheSBhcyB0aGV5IGFyZSJdfSwgeyJ2ZXJzaW9uIjogIjAuNS4xIiwgImRhdGUiOiAiMjAyNi0wOS0yOCIsICJjaGFuZ2VzIjogWyJVbXp1ZyBuYWNoIEdpdEh1YiAoZ2l0aHViLmNvbS9QYW50aGVyOTIvVm9pZFN0YXRpb24pIOKAkyBHZXLDpHRlIGJlemllaGVuIFVwZGF0ZXMgYWIgamV0enQgdm9uIGRvcnQiLCAiS3VyemJlZmVobCB6dXIgTmV1aW5zdGFsbGF0aW9uOiB4YnBzLWZldGNoIGh0dHBzOi8vcGFudGhlcjkyLmdpdGh1Yi5pby9Wb2lkU3RhdGlvbi92cyJdLCAiY2hhbmdlc19lbiI6IFsiTW92ZWQgdG8gR2l0SHViIChnaXRodWIuY29tL1BhbnRoZXI5Mi9Wb2lkU3RhdGlvbikg4oCTIGRldmljZXMgbm93IGdldCB0aGVpciB1cGRhdGVzIGZyb20gdGhlcmUiLCAiU2hvcnQgY29tbWFuZCBmb3IgYSBmcmVzaCBpbnN0YWxsOiB4YnBzLWZldGNoIGh0dHBzOi8vcGFudGhlcjkyLmdpdGh1Yi5pby9Wb2lkU3RhdGlvbi92cyJdfSwgeyJ2ZXJzaW9uIjogIjAuNS4wIiwgImRhdGUiOiAiMjAyNi0wOS0yOCIsICJjaGFuZ2VzIjogWyJHcmFmaWstU2VydmVyOiBYTGlicmUgc3RhdHQgWC5PcmcgKFBha2V0cXVlbGxlIHhsaWJyZS12b2lkLCBTY2hsw7xzc2VsIGZlc3QgaGludGVybGVndCkiLCAiU2ljaGVyaGVpdHNuZXR6OiBzdGFydGV0IGRpZSBPYmVyZmzDpGNoZSB6d2VpbWFsIG5pY2h0LCBzY2hhbHRldCBWb2lkU3RhdGlvbiBhdXRvbWF0aXNjaCBhdWYgWC5PcmcgenVyw7xjayIsICJXYWhsIHp3aXNjaGVuIFhMaWJyZSB1bmQgWC5PcmcgdW50ZXIgRWluc3RlbGx1bmdlbiDihpIgU3lzdGVtIOKGkiBHcmFmaWstU2VydmVyIl0sICJjaGFuZ2VzX2VuIjogWyJEaXNwbGF5IHNlcnZlcjogWExpYnJlIGluc3RlYWQgb2YgWC5PcmcgKHhsaWJyZS12b2lkIHJlcG9zaXRvcnksIGtleSBwaW5uZWQpIiwgIlNhZmV0eSBuZXQ6IGlmIHRoZSBpbnRlcmZhY2UgZmFpbHMgdG8gc3RhcnQgdHdpY2UsIFZvaWRTdGF0aW9uIGF1dG9tYXRpY2FsbHkgc3dpdGNoZXMgYmFjayB0byBYLk9yZyIsICJDaG9vc2UgYmV0d2VlbiBYTGlicmUgYW5kIFguT3JnIHVuZGVyIFNldHRpbmdzIOKGkiBTeXN0ZW0g4oaSIERpc3BsYXkgc2VydmVyIl19LCB7InZlcnNpb24iOiAiMC40LjAiLCAiZGF0ZSI6ICIyMDI2LTA5LTI4IiwgImNoYW5nZXMiOiBbIlVwZGF0ZS1LYW7DpGxlOiDigJ5TdGFiaWzigJwgZsO8ciBhbGxlLCDigJ5UZXN04oCcIHp1bSBBdXNwcm9iaWVyZW4gbmV1ZXIgVmVyc2lvbmVuIiwgIlVwZGF0ZXMgc2luZCBzaWduaWVydCDigJMgR2Vyw6R0ZSBpbnN0YWxsaWVyZW4gbnVyIFVwZGF0ZXMgbWl0IGfDvGx0aWdlciBTaWduYXR1ciIsICJBdXRvbWF0aXNjaGUgVXBkYXRlLVByw7xmdW5nIG1pdCBIaW53ZWlzIGF1ZiBkZXIgU3RhcnRzZWl0ZSIsICJWZXJzaW9uc251bW1lcm4gdW5kIOKAnldhcyBpc3QgbmV14oCcIGltIFVwZGF0ZS1EaWFsb2ciLCAiTGl6ZW56OiBHUEwtMy4wIl0sICJjaGFuZ2VzX2VuIjogWyJVcGRhdGUgY2hhbm5lbHM6IOKAnFN0YWJsZeKAnSBmb3IgZXZlcnlvbmUsIOKAnFRlc3RpbmfigJ0gdG8gdHJ5IG5ldyB2ZXJzaW9ucyBlYXJseSIsICJVcGRhdGVzIGFyZSBzaWduZWQg4oCTIGRldmljZXMgb25seSBpbnN0YWxsIHVwZGF0ZXMgd2l0aCBhIHZhbGlkIHNpZ25hdHVyZSIsICJBdXRvbWF0aWMgdXBkYXRlIGNoZWNrIHdpdGggYSBub3RpY2Ugb24gdGhlIHN0YXJ0IHBhZ2UiLCAiVmVyc2lvbiBudW1iZXJzIGFuZCDigJxXaGF0J3MgbmV34oCdIGluIHRoZSB1cGRhdGUgZGlhbG9nIiwgIkxpY2Vuc2U6IEdQTC0zLjAiXX0sIHsidmVyc2lvbiI6ICIwLjMuMCIsICJkYXRlIjogIjIwMjYtMDktMjgiLCAiY2hhbmdlcyI6IFsiVXBkYXRlLUtub3BmOiBWb2lkU3RhdGlvbiBha3R1YWxpc2llcnQgc2ljaCDDvGJlciBkaWUgRWluc3RlbGx1bmdlbiBzZWxic3QiLCAiU3RlYW0gbmF0aXYgYXVzIGRlbSBWb2lkLVJlcG8gKG5vbmZyZWUgKyBtdWx0aWxpYikgbWl0IGFrdHVlbGxlbSBQcm90b24tR0UiLCAiU3RhcnRiaWxkc2NoaXJtIGJsZWlidCBzdGVoZW4sIGJpcyBlaW4gUHJvZ3JhbW0gd2lya2xpY2ggZWluIEZlbnN0ZXIgemVpZ3QiLCAiQXVmbMO2c3VuZzogNjAgSHogYmV2b3J6dWd0LCBIYWxiYmlsZC1Nb2RpICgxMDgwaSkgd2VyZGVuIHZlcm1pZWRlbiIsICJBdXNsYWdlcnVuZ3NkYXRlaSBhdWYgUmVjaG5lcm4gbWl0IHdlbmlnZXIgYWxzIDggR0IgUkFNIl0sICJjaGFuZ2VzX2VuIjogWyJVcGRhdGUgYnV0dG9uOiBWb2lkU3RhdGlvbiB1cGRhdGVzIGl0c2VsZiBmcm9tIHRoZSBzZXR0aW5ncyIsICJTdGVhbSBuYXRpdmVseSBmcm9tIHRoZSBWb2lkIHJlcG9zaXRvcnkgKG5vbmZyZWUgKyBtdWx0aWxpYikgd2l0aCB0aGUgbGF0ZXN0IFByb3Rvbi1HRSIsICJUaGUgc3BsYXNoIHNjcmVlbiBzdGF5cyB1bnRpbCBhIHByb2dyYW0gcmVhbGx5IHNob3dzIGEgd2luZG93IiwgIlJlc29sdXRpb246IDYwIEh6IHByZWZlcnJlZCwgaW50ZXJsYWNlZCBtb2RlcyAoMTA4MGkpIGFyZSBhdm9pZGVkIiwgIlN3YXAgZmlsZSBvbiBjb21wdXRlcnMgd2l0aCBsZXNzIHRoYW4gOCBHQiBvZiBSQU0iXX0sIHsidmVyc2lvbiI6ICIwLjIuMCIsICJkYXRlIjogIjIwMjYtMDktMjciLCAiY2hhbmdlcyI6IFsiTmV1ZXIgTmFtZTogVm9pZFN0YXRpb24iLCAiTmV1aW5zdGFsbGF0aW9uIGVpbmVyIGdhbnplbiBTU0QgbWl0IGVpbmVtIEJlZmVobCB2b24gZGVyIG9mZml6aWVsbGVuIFZvaWQtSVNPIiwgIlNjcmVlbnNob3RzLCBSYXN0ZXIgcGFzc2VuIHNpY2ggZGVtIFBsYXR6IMO8YmVyIGRlciBIaW53ZWlzemVpbGUgYW4iXSwgImNoYW5nZXNfZW4iOiBbIk5ldyBuYW1lOiBWb2lkU3RhdGlvbiIsICJGcmVzaCBpbnN0YWxsIG9mIGEgd2hvbGUgU1NEIHdpdGggb25lIGNvbW1hbmQgZnJvbSB0aGUgb2ZmaWNpYWwgVm9pZCBJU08iLCAiU2NyZWVuc2hvdHM7IGdyaWRzIGFkYXB0IHRvIHRoZSBzcGFjZSBhYm92ZSB0aGUgaGludCBiYXIiXX0sIHsidmVyc2lvbiI6ICIwLjEuMCIsICJkYXRlIjogIjIwMjYtMDktMjciLCAiY2hhbmdlcyI6IFsiS2FjaGVsb2JlcmZsw6RjaGUgbWl0IFdlYktpdC1TdGFydHNlaXRlLCBSYWRpbywgRmVybnNlaGVuLCBBcHBDZW50ZXIsIEVpbnN0ZWxsdW5nZW4iLCAiU2FtYmEtRnJlaWdhYmUsIGR1bmtsZXMgVGhlbWUsIGdyb8OfZXIgTWF1c3plaWdlciwgRUZJU1RVQiJdLCAiY2hhbmdlc19lbiI6IFsiVGlsZSBpbnRlcmZhY2Ugd2l0aCBhIFdlYktpdCBzdGFydCBwYWdlLCByYWRpbywgVFYsIEFwcENlbnRlciwgc2V0dGluZ3MiLCAiU2FtYmEgc2hhcmUsIGRhcmsgdGhlbWUsIGxhcmdlIG1vdXNlIHBvaW50ZXIsIEVGSVNUVUIiXX1dfQo=' | base64 -d > "$TV/version.json" 2>/dev/null || true

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
