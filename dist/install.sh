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
echo "af919c624270" > "$TV/VERSION"
echo 'eyJ2ZXJzaW9uIjogIjAuNS4xIiwgImJ1aWxkIjogImFmOTE5YzYyNDI3MCIsICJkYXRlIjogIjIwMjYtMDktMjgiLCAiaGlzdG9yeSI6IFt7InZlcnNpb24iOiAiMC41LjEiLCAiZGF0ZSI6ICIyMDI2LTA5LTI4IiwgImNoYW5nZXMiOiBbIlVtenVnIG5hY2ggR2l0SHViIChnaXRodWIuY29tL1BhbnRoZXI5Mi9Wb2lkU3RhdGlvbikg4oCTIEdlcsOkdGUgYmV6aWVoZW4gVXBkYXRlcyBhYiBqZXR6dCB2b24gZG9ydCIsICJLdXJ6YmVmZWhsIHp1ciBOZXVpbnN0YWxsYXRpb246IHhicHMtZmV0Y2ggaHR0cHM6Ly9wYW50aGVyOTIuZ2l0aHViLmlvL1ZvaWRTdGF0aW9uL3ZzIl19LCB7InZlcnNpb24iOiAiMC41LjAiLCAiZGF0ZSI6ICIyMDI2LTA5LTI4IiwgImNoYW5nZXMiOiBbIkdyYWZpay1TZXJ2ZXI6IFhMaWJyZSBzdGF0dCBYLk9yZyAoUGFrZXRxdWVsbGUgeGxpYnJlLXZvaWQsIFNjaGzDvHNzZWwgZmVzdCBoaW50ZXJsZWd0KSIsICJTaWNoZXJoZWl0c25ldHo6IHN0YXJ0ZXQgZGllIE9iZXJmbMOkY2hlIHp3ZWltYWwgbmljaHQsIHNjaGFsdGV0IFZvaWRTdGF0aW9uIGF1dG9tYXRpc2NoIGF1ZiBYLk9yZyB6dXLDvGNrIiwgIldhaGwgendpc2NoZW4gWExpYnJlIHVuZCBYLk9yZyB1bnRlciBFaW5zdGVsbHVuZ2VuIOKGkiBTeXN0ZW0g4oaSIEdyYWZpay1TZXJ2ZXIiXX0sIHsidmVyc2lvbiI6ICIwLjQuMCIsICJkYXRlIjogIjIwMjYtMDktMjgiLCAiY2hhbmdlcyI6IFsiVXBkYXRlLUthbsOkbGU6IOKAnlN0YWJpbOKAnCBmw7xyIGFsbGUsIOKAnlRlc3TigJwgenVtIEF1c3Byb2JpZXJlbiBuZXVlciBWZXJzaW9uZW4iLCAiVXBkYXRlcyBzaW5kIHNpZ25pZXJ0IOKAkyBHZXLDpHRlIGluc3RhbGxpZXJlbiBudXIgVXBkYXRlcyBtaXQgZ8O8bHRpZ2VyIFNpZ25hdHVyIiwgIkF1dG9tYXRpc2NoZSBVcGRhdGUtUHLDvGZ1bmcgbWl0IEhpbndlaXMgYXVmIGRlciBTdGFydHNlaXRlIiwgIlZlcnNpb25zbnVtbWVybiB1bmQg4oCeV2FzIGlzdCBuZXXigJwgaW0gVXBkYXRlLURpYWxvZyIsICJMaXplbno6IEdQTC0zLjAiXX0sIHsidmVyc2lvbiI6ICIwLjMuMCIsICJkYXRlIjogIjIwMjYtMDktMjgiLCAiY2hhbmdlcyI6IFsiVXBkYXRlLUtub3BmOiBWb2lkU3RhdGlvbiBha3R1YWxpc2llcnQgc2ljaCDDvGJlciBkaWUgRWluc3RlbGx1bmdlbiBzZWxic3QiLCAiU3RlYW0gbmF0aXYgYXVzIGRlbSBWb2lkLVJlcG8gKG5vbmZyZWUgKyBtdWx0aWxpYikgbWl0IGFrdHVlbGxlbSBQcm90b24tR0UiLCAiU3RhcnRiaWxkc2NoaXJtIGJsZWlidCBzdGVoZW4sIGJpcyBlaW4gUHJvZ3JhbW0gd2lya2xpY2ggZWluIEZlbnN0ZXIgemVpZ3QiLCAiQXVmbMO2c3VuZzogNjAgSHogYmV2b3J6dWd0LCBIYWxiYmlsZC1Nb2RpICgxMDgwaSkgd2VyZGVuIHZlcm1pZWRlbiIsICJBdXNsYWdlcnVuZ3NkYXRlaSBhdWYgUmVjaG5lcm4gbWl0IHdlbmlnZXIgYWxzIDggR0IgUkFNIl19LCB7InZlcnNpb24iOiAiMC4yLjAiLCAiZGF0ZSI6ICIyMDI2LTA5LTI3IiwgImNoYW5nZXMiOiBbIk5ldWVyIE5hbWU6IFZvaWRTdGF0aW9uIiwgIk5ldWluc3RhbGxhdGlvbiBlaW5lciBnYW56ZW4gU1NEIG1pdCBlaW5lbSBCZWZlaGwgdm9uIGRlciBvZmZpemllbGxlbiBWb2lkLUlTTyIsICJTY3JlZW5zaG90cywgUmFzdGVyIHBhc3NlbiBzaWNoIGRlbSBQbGF0eiDDvGJlciBkZXIgSGlud2Vpc3plaWxlIGFuIl19LCB7InZlcnNpb24iOiAiMC4xLjAiLCAiZGF0ZSI6ICIyMDI2LTA5LTI3IiwgImNoYW5nZXMiOiBbIkthY2hlbG9iZXJmbMOkY2hlIG1pdCBXZWJLaXQtU3RhcnRzZWl0ZSwgUmFkaW8sIEZlcm5zZWhlbiwgQXBwQ2VudGVyLCBFaW5zdGVsbHVuZ2VuIiwgIlNhbWJhLUZyZWlnYWJlLCBkdW5rbGVzIFRoZW1lLCBncm/Dn2VyIE1hdXN6ZWlnZXIsIEVGSVNUVUIiXX1dfQo=' | base64 -d > "$TV/version.json" 2>/dev/null || true

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
