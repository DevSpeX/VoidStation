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
cmOWAIACAA==
