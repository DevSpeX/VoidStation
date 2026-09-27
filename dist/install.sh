#!/bin/bash
# =====================================================================
#  VoidStation fuer Void Linux – Kacheloberflaeche fuer den Esprimo
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
chmod +x "$TV/launcher.py" "$TV/home.sh" "$TV/vsctl" "$TV/voidstation-shell.py"

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
if ! grep -q 'VOIDSTATION' "$HOMEDIR/.bash_profile"; then
cat >> "$HOMEDIR/.bash_profile" <<'EOF'

# VOIDSTATION: grafische Oberflaeche automatisch auf tty1 starten
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
  # Eigener Laufzeitordner fuer die TV-Sitzung (unabhaengig von elogind)
  export XDG_RUNTIME_DIR="/tmp/voidstation-runtime-$(id -u)"
  rm -rf "$XDG_RUNTIME_DIR"; mkdir -m 0700 "$XDG_RUNTIME_DIR"
  exec startx -- -nolisten tcp vt1 >"$HOME/.xsession-errors" 2>&1
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
pk = sorted({a["source"]["pkg"] for a in c["apps"] if a["source"]["type"] == "xbps"} | {"flatpak"})
print("\n".join(pk))
PYEOF
chmod 644 /usr/local/share/voidstation/allowed-packages
echo "$(wc -l < /usr/local/share/voidstation/allowed-packages) Pakete freigegeben"

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
