#!/bin/bash
# =====================================================================
#  TV-Start fuer Void Linux – Kacheloberflaeche fuer den Esprimo
#  Aufruf (per SSH als paul):   sudo bash install.sh
#  Optional anderer Benutzer:   sudo TVUSER=name bash install.sh
#  Optional EFISTUB (direkt booten, GRUB bleibt als Rueckfall):
#                               sudo EFISTUB=1 bash install.sh
# =====================================================================
set -euo pipefail

TVUSER="${TVUSER:-${SUDO_USER:-paul}}"
HOMEDIR="$(getent passwd "$TVUSER" | cut -d: -f6)"
TV="$HOMEDIR/.local/share/tvstart"
# Dienste-Ordner: im laufenden System /var/service, bei Installation vom Stick (chroot) der Standard-Runlevel
SVDIR="${SVDIR:-/var/service}"
CHROOT="${TVSTART_CHROOT:-0}"

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[!] %s\033[0m\n' "$*"; }

[ "$(id -u)" -eq 0 ] || { echo "Bitte mit sudo starten: sudo bash install.sh"; exit 1; }
[ -n "$HOMEDIR" ] && [ -d "$HOMEDIR" ] || { echo "Benutzer '$TVUSER' nicht gefunden."; exit 1; }

say "Benutzer: $TVUSER ($HOMEDIR)"

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
chmod +x "$TV/launcher.py" "$TV/home.sh" "$TV/tvctl" "$TV/tvstart-shell.py"

# Eigene, schon angepasste tiles.json behalten
if [ -f /tmp/tiles.json.keep ]; then
  mv -f /tmp/tiles.json.keep "$TV/tiles.json"; echo "eigene tiles.json behalten"
else
  # Neue Installation: Anzeigename oben rechts (TVNAME, sonst voller Name, sonst Benutzername)
  NAME="${TVNAME:-$(getent passwd "$TVUSER" | cut -d: -f5 | cut -d, -f1)}"
  [ -n "$NAME" ] || NAME="${TVUSER^}"
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
install -d -o "$TVUSER" -g "$TVUSER" "$HOMEDIR/.config/openbox"
cp "$TV/openbox/"{rc.xml,menu.xml,autostart} "$HOMEDIR/.config/openbox/"

cat > "$HOMEDIR/.xinitrc" <<'EOF'
exec dbus-run-session openbox-session
EOF

touch "$HOMEDIR/.bash_profile"
if ! grep -q 'TVSTART' "$HOMEDIR/.bash_profile"; then
cat >> "$HOMEDIR/.bash_profile" <<'EOF'

# TVSTART: grafische Oberflaeche automatisch auf tty1 starten
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
  # Eigener Laufzeitordner fuer die TV-Sitzung (unabhaengig von elogind)
  export XDG_RUNTIME_DIR="/tmp/tvstart-runtime-$(id -u)"
  rm -rf "$XDG_RUNTIME_DIR"; mkdir -m 0700 "$XDG_RUNTIME_DIR"
  exec startx -- -nolisten tcp vt1 >"$HOME/.xsession-errors" 2>&1
fi
EOF
fi

cat > /etc/sv/agetty-tty1/conf <<EOF
GETTY_ARGS="--autologin $TVUSER --noclear"
BAUD_RATE=38400
TERM_NAME=linux
EOF

# Gruppen: Gamepad/Eingabe, Ton, Grafik
for g in input audio video render; do
  getent group "$g" >/dev/null && usermod -aG "$g" "$TVUSER" || true
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
cat > /etc/sudoers.d/zz-tvstart <<EOF
$TVUSER ALL=(root) NOPASSWD: /usr/bin/poweroff, /usr/bin/reboot, /usr/bin/nmcli, /usr/local/sbin/tvstart-pkg
EOF
chmod 440 /etc/sudoers.d/zz-tvstart
visudo -cf /etc/sudoers.d/zz-tvstart >/dev/null || { warn "sudoers-Regel fehlerhaft, entferne sie"; rm -f /etc/sudoers.d/zz-tvstart; }

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
            '# TV-Start: Kernel fuer EFISTUB auf die EFI-Partition kopieren' \
            "cp -f \"/boot/vmlinuz-\$2\" \"/boot/initramfs-\$2.img\" \"$ESP/\"" \
            > /etc/kernel.d/post-install/40-tvstart-esp
          printf '%s\n' '#!/bin/sh' \
            "rm -f \"$ESP/vmlinuz-\$2\" \"$ESP/initramfs-\$2.img\"" \
            > /etc/kernel.d/post-remove/40-tvstart-esp
          chmod 744 /etc/kernel.d/post-install/40-tvstart-esp /etc/kernel.d/post-remove/40-tvstart-esp
        fi

        # Neuesten Void-Eintrag in der Bootreihenfolge nach vorn (auch nach Kernel-Updates)
        printf '%s\n' '#!/bin/sh' \
          'major=$(echo "$1" | cut -c 6-)' \
          'num=$(efibootmgr | grep -E "^Boot[0-9A-Fa-f]{4}\*? Void Linux with kernel ${major}([^0-9]|$)" | head -1 | cut -c5-8)' \
          '[ -n "$num" ] || exit 0' \
          'rest=$(efibootmgr | sed -n "s/^BootOrder: //p" | tr "," "\n" | grep -vi "^${num}$" | paste -sd, -)' \
          'efibootmgr -qo "${num}${rest:+,$rest}"' \
          > /etc/kernel.d/post-install/60-tvstart-bootorder
        chmod 744 /etc/kernel.d/post-install/60-tvstart-bootorder

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
chown -R "$TVUSER:$TVUSER" "$HOMEDIR/.config" "$HOMEDIR/.gtkrc-2.0"
echo "dunkles Theme eingerichtet (Mauszeiger-Stil und -Größe unter Einstellungen)"

say "Extra: AppCenter-Helfer (installiert nur freigegebene Pakete)"
install -o root -g root -m 755 "$TV/tvstart-pkg" /usr/local/sbin/tvstart-pkg
install -d -o root -g root -m 755 /usr/local/share/tvstart
python3 - "$TV/catalog.json" > /usr/local/share/tvstart/allowed-packages <<'PYEOF'
import json, sys
c = json.load(open(sys.argv[1], encoding="utf-8"))
pk = sorted({a["source"]["pkg"] for a in c["apps"] if a["source"]["type"] == "xbps"} | {"flatpak"})
print("\n".join(pk))
PYEOF
chmod 644 /usr/local/share/tvstart/allowed-packages
echo "$(wc -l < /usr/local/share/tvstart/allowed-packages) Pakete freigegeben"

say "Extra: Freigabe-Ordner $SHARE"
for d in ROMs/gba ROMs/nes ROMs/snes ROMs/psx ROMs/psp ROMs/nds ROMs/gamecube ROMs/dreamcast \
         ROMs/dos ROMs/c64 ROMs/atari2600 ROMs/scummvm BIOS Musik Videos Bilder; do
  mkdir -p "$SHARE/$d"
done
[ -f "$SHARE/LIESMICH.txt" ] || cat > "$SHARE/LIESMICH.txt" <<'EOF'
TV-Start Freigabe
=================
ROMs/<system>   Spiele fuer die Emulatoren (gba, nes, snes, psx, psp, nds …)
BIOS            BIOS-Dateien (z. B. PlayStation fuer DuckStation)
Musik, Videos   eigene Medien fuer VLC oder Kodi
Bilder          fuer den Bildbetrachter
EOF
chown -R "$TVUSER:$TVUSER" "$SHARE"

say "Extra: Samba (Zugriff vom Windows-PC)"
HOST="$(cat /etc/hostname 2>/dev/null || hostname)"
if [ -f /etc/samba/smb.conf ] && ! grep -q 'TV-Start' /etc/samba/smb.conf; then
  cp /etc/samba/smb.conf /etc/samba/smb.conf.vor-tvstart
fi
mkdir -p /etc/samba /var/log/samba
cat > /etc/samba/smb.conf <<EOF
# TV-Start: Freigabe fuer den Windows-PC
[global]
   workgroup = WORKGROUP
   server string = TV-Start
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
   comment = TV-Start
   path = ${SHARE}
   valid users = ${TVUSER}
   force user = ${TVUSER}
   read only = no
   browseable = yes
   create mask = 0664
   directory mask = 0775
EOF
if pdbedit -L 2>/dev/null | grep -q "^${TVUSER}:" && [ -z "${SMBPASS:-}" ]; then
  echo "Freigabe-Benutzer $TVUSER existiert schon (Passwort bleibt)."
else
  PW="${SMBPASS:-}"
  while [ -z "$PW" ]; do
    read -r -s -p "Passwort fuer die Freigabe (Benutzer $TVUSER): " PW1 </dev/tty; echo
    read -r -s -p "Nochmal: " PW2 </dev/tty; echo
    [ -n "$PW1" ] && [ "$PW1" = "$PW2" ] && PW="$PW1" || warn "Leer oder nicht gleich – bitte nochmal."
  done
  printf '%s\n%s\n' "$PW" "$PW" | smbpasswd -s -a "$TVUSER" >/dev/null && echo "Freigabe-Passwort gesetzt."
fi
for s in smbd nmbd; do
  [ -d "/etc/sv/$s" ] && { [ -e "$SVDIR/$s" ] || ln -s "/etc/sv/$s" "$SVDIR/"; }
done
[ "$CHROOT" = 1 ] || sv restart smbd >/dev/null 2>&1 || true

chown -R "$TVUSER:$TVUSER" "$HOMEDIR/.config" "$HOMEDIR/.local" "$HOMEDIR/.xinitrc" "$HOMEDIR/.bash_profile"

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
