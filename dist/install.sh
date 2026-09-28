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
chmod +x "$TV/launcher.py" "$TV/home.sh" "$TV/vsctl" "$TV/voidstation-shell.py"
echo "0a30edc0cfa8" > "$TV/VERSION"
echo 'eyJ2ZXJzaW9uIjogIjAuNC4wIiwgImJ1aWxkIjogIjBhMzBlZGMwY2ZhOCIsICJkYXRlIjogIjIwMjYtMDktMjgiLCAiaGlzdG9yeSI6IFt7InZlcnNpb24iOiAiMC40LjAiLCAiZGF0ZSI6ICIyMDI2LTA5LTI4IiwgImNoYW5nZXMiOiBbIlVwZGF0ZS1LYW7DpGxlOiDigJ5TdGFiaWzigJwgZsO8ciBhbGxlLCDigJ5UZXN04oCcIHp1bSBBdXNwcm9iaWVyZW4gbmV1ZXIgVmVyc2lvbmVuIiwgIlVwZGF0ZXMgc2luZCBzaWduaWVydCDigJMgR2Vyw6R0ZSBpbnN0YWxsaWVyZW4gbnVyIFVwZGF0ZXMgbWl0IGfDvGx0aWdlciBTaWduYXR1ciIsICJBdXRvbWF0aXNjaGUgVXBkYXRlLVByw7xmdW5nIG1pdCBIaW53ZWlzIGF1ZiBkZXIgU3RhcnRzZWl0ZSIsICJWZXJzaW9uc251bW1lcm4gdW5kIOKAnldhcyBpc3QgbmV14oCcIGltIFVwZGF0ZS1EaWFsb2ciLCAiTGl6ZW56OiBHUEwtMy4wIl19LCB7InZlcnNpb24iOiAiMC4zLjAiLCAiZGF0ZSI6ICIyMDI2LTA5LTI4IiwgImNoYW5nZXMiOiBbIlVwZGF0ZS1Lbm9wZjogVm9pZFN0YXRpb24gYWt0dWFsaXNpZXJ0IHNpY2ggw7xiZXIgZGllIEVpbnN0ZWxsdW5nZW4gc2VsYnN0IiwgIlN0ZWFtIG5hdGl2IGF1cyBkZW0gVm9pZC1SZXBvIChub25mcmVlICsgbXVsdGlsaWIpIG1pdCBha3R1ZWxsZW0gUHJvdG9uLUdFIiwgIlN0YXJ0YmlsZHNjaGlybSBibGVpYnQgc3RlaGVuLCBiaXMgZWluIFByb2dyYW1tIHdpcmtsaWNoIGVpbiBGZW5zdGVyIHplaWd0IiwgIkF1ZmzDtnN1bmc6IDYwIEh6IGJldm9yenVndCwgSGFsYmJpbGQtTW9kaSAoMTA4MGkpIHdlcmRlbiB2ZXJtaWVkZW4iLCAiQXVzbGFnZXJ1bmdzZGF0ZWkgYXVmIFJlY2huZXJuIG1pdCB3ZW5pZ2VyIGFscyA4IEdCIFJBTSJdfSwgeyJ2ZXJzaW9uIjogIjAuMi4wIiwgImRhdGUiOiAiMjAyNi0wOS0yNyIsICJjaGFuZ2VzIjogWyJOZXVlciBOYW1lOiBWb2lkU3RhdGlvbiIsICJOZXVpbnN0YWxsYXRpb24gZWluZXIgZ2FuemVuIFNTRCBtaXQgZWluZW0gQmVmZWhsIHZvbiBkZXIgb2ZmaXppZWxsZW4gVm9pZC1JU08iLCAiU2NyZWVuc2hvdHMsIFJhc3RlciBwYXNzZW4gc2ljaCBkZW0gUGxhdHogw7xiZXIgZGVyIEhpbndlaXN6ZWlsZSBhbiJdfSwgeyJ2ZXJzaW9uIjogIjAuMS4wIiwgImRhdGUiOiAiMjAyNi0wOS0yNyIsICJjaGFuZ2VzIjogWyJLYWNoZWxvYmVyZmzDpGNoZSBtaXQgV2ViS2l0LVN0YXJ0c2VpdGUsIFJhZGlvLCBGZXJuc2VoZW4sIEFwcENlbnRlciwgRWluc3RlbGx1bmdlbiIsICJTYW1iYS1GcmVpZ2FiZSwgZHVua2xlcyBUaGVtZSwgZ3Jvw59lciBNYXVzemVpZ2VyLCBFRklTVFVCIl19XX0K' | base64 -d > "$TV/version.json" 2>/dev/null || true

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
printf '%s\n' "https://codeberg.org/goldhahn/VoidStation/raw/branch/{channel}/dist" > /usr/local/share/voidstation/update-url
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
