#!/bin/bash
# =====================================================================
#  VoidStation Update – fuer eine bestehende Installation
#  Aufruf (per SSH als paul):   sudo bash update.sh
#  Neu: schlanke Startseite (WebKit statt Firefox), Fernsehen, AppCenter,
#       Freigabe-Ordner (Samba), dunkles Theme, grosser Mauszeiger
#  Optional: Freigabe-Passwort vorgeben mit  sudo SMBPASS='geheim' bash update.sh
# =====================================================================
set -uo pipefail

VSUSER="${VSUSER:-${SUDO_USER:-paul}}"
HOMEDIR="$(getent passwd "$VSUSER" | cut -d: -f6)"
TV="$HOMEDIR/.local/share/voidstation"
SHARE="$HOMEDIR/share"
say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[!] %s\033[0m\n' "$*"; }

[ "$(id -u)" -eq 0 ] || { echo "Bitte mit sudo starten: sudo bash update.sh"; exit 1; }

# ---------------------------------------------------------------------
# Umzug von "TV-Start" (alter Name) nach "VoidStation"
OLD="$HOMEDIR/.local/share/tvstart"
if [ -d "$OLD" ] && [ ! -L "$OLD" ]; then
  say "0/8  Umzug: TV-Start -> VoidStation"
  if [ -e "$TV" ]; then
    warn "$TV existiert schon – Umzug uebersprungen, bitte von Hand pruefen."
  else
    mv "$OLD" "$TV"
    ln -s voidstation "$OLD"      # alte absolute Pfade (Firefox-Profile, eigene Kacheln) laufen weiter
    sed -i 's|/\.local/share/tvstart/|/.local/share/voidstation/|g' "$TV/tiles.json" 2>/dev/null || true
    rm -f "$TV/tvstart-shell.py" "$TV/tvstart-pkg" "$TV/tvctl"
    echo "Datenordner umgezogen: $TV  (alter Pfad bleibt als Verweis)"
  fi
  # Systemdateien mit altem Namen ersetzen
  rm -f /usr/local/sbin/tvstart-pkg /etc/sudoers.d/tvstart /etc/sudoers.d/zz-tvstart
  rm -rf /usr/local/share/tvstart
  for f in /etc/kernel.d/post-install/40-tvstart-esp /etc/kernel.d/post-remove/40-tvstart-esp \
           /etc/kernel.d/post-install/60-tvstart-bootorder; do
    [ -f "$f" ] && mv "$f" "${f/tvstart/voidstation}" && echo "Kernel-Hook umbenannt: ${f/tvstart/voidstation}"
  done
  [ -f "$HOMEDIR/.bash_profile" ] && sed -i 's/tvstart-runtime/voidstation-runtime/g; s/# TVSTART:/# VOIDSTATION:/' "$HOMEDIR/.bash_profile"
  [ -f /etc/samba/smb.conf.vor-tvstart ] && mv /etc/samba/smb.conf.vor-tvstart /etc/samba/smb.conf.vor-voidstation
fi

[ -d "$TV" ] || { echo "Keine VoidStation-Installation unter $TV gefunden."; exit 1; }

# Alte WebKit-Ordner der Startseite (lagen lose in ~/.local/share und ~/.cache), jetzt unter .../voidstation/webkit
for d in tvstart-shell.py voidstation-shell.py; do
  rm -rf "$HOMEDIR/.local/share/$d" "$HOMEDIR/.cache/$d"
done

say "1/8  Pakete"
MISSING=""
for p in elogind xrdb pulseaudio-utils mpv mgba-qt samba flatpak adwaita-qt adwaita-qt6 gnome-themes-extra xsetroot python3-gobject libwebkit2gtk41; do
  xbps-query "$p" >/dev/null 2>&1 || MISSING="$MISSING $p"
done
if [ -n "$MISSING" ]; then xbps-install -Sy $MISSING || warn "Paketinstallation fehlgeschlagen"; else echo "alles da"; fi

say "2/8  Programmdateien (eigene Kacheln, Favoriten, Einstellungen bleiben)"
KEEP="$(mktemp -d)"
for f in tiles.json radio.json tvfavs.json settings.json; do [ -f "$TV/$f" ] && cp "$TV/$f" "$KEEP/"; done
sed -n '/^__PAYLOAD_BELOW__$/,$p' "$0" | tail -n +2 | base64 -d | tar -xz -C "$TV" || { warn "Entpacken fehlgeschlagen"; exit 1; }
for f in tiles.json radio.json tvfavs.json settings.json; do [ -f "$KEEP/$f" ] && cp "$KEEP/$f" "$TV/$f"; done
rm -rf "$KEEP"
chmod +x "$TV/launcher.py" "$TV/home.sh" "$TV/vsctl" "$TV/voidstation-shell.py"
cp "$TV/openbox/"{rc.xml,menu.xml,autostart} "$HOMEDIR/.config/openbox/"

python3 - "$TV/tiles.json" <<'PYEOF'
import json, sys
p = sys.argv[1]
c = json.load(open(p, encoding="utf-8"))
tiles = [t for g in c["groups"] for t in g["tiles"]]
def group(name, before="System"):
    g = next((g for g in c["groups"] if g.get("name") == name), None)
    if g is None:
        g = {"name": name, "tiles": []}
        idx = next((i for i, x in enumerate(c["groups"]) if x.get("name") == before), len(c["groups"]))
        c["groups"].insert(idx, g)
    return g
def add(tile, gname, pos):
    if any(t.get("type") == tile["type"] for t in tiles):
        return
    g = group(gname)
    g["tiles"].insert(min(pos, len(g["tiles"])), tile)
    print("Kachel hinzugefuegt:", tile["label"])
add({"id": "tv", "label": "Fernsehen", "sub": "Sender aus aller Welt", "size": "wide", "color": "#24414a", "icon": "tv", "type": "tv"}, "Unterhaltung", 1)
add({"id": "settings", "label": "Einstellungen", "size": "medium", "color": "#3a3f46", "icon": "gear", "type": "settings"}, "System", 1)
add({"id": "appcenter", "label": "AppCenter", "sub": "Apps & Updates", "size": "medium", "color": "#39414d", "icon": "store", "type": "apps"}, "System", 2)
for t in [t for g in c["groups"] for t in g["tiles"]]:
    if t.get("cmd") and t["cmd"][0] == "visualboyadvance-m":
        t["cmd"] = ["mgba-qt"]; t["sub"] = "mGBA"
    if t.get("id") == "files" and t.get("cmd") == ["pcmanfm", "~"]:
        t["cmd"] = ["pcmanfm", "~/share"]
json.dump(c, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
PYEOF
xbps-query vba-m >/dev/null 2>&1 && xbps-remove -Ry vba-m >/dev/null 2>&1 && echo "defektes vba-m entfernt"

say "3/8  AppCenter-Helfer (installiert nur freigegebene Pakete)"
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

say "4/8  Rechte ohne Passwort: Ausschalten, WLAN, AppCenter"
rm -f /etc/sudoers.d/voidstation /etc/sudoers.d/tvstart /etc/sudoers.d/zz-tvstart
cat > /etc/sudoers.d/zz-voidstation <<EOF
$VSUSER ALL=(root) NOPASSWD: /usr/bin/poweroff, /usr/bin/reboot, /usr/bin/nmcli, /usr/local/sbin/voidstation-pkg
EOF
chmod 440 /etc/sudoers.d/zz-voidstation
visudo -cf /etc/sudoers.d/zz-voidstation >/dev/null || { warn "sudoers-Regel fehlerhaft, entferne sie"; rm -f /etc/sudoers.d/zz-voidstation; }

say "5/8  Laufzeitordner fuer den Ton"
python3 - "$HOMEDIR/.bash_profile" <<'PYEOF'
import sys, re
p = sys.argv[1]
s = open(p).read()
s = re.sub(r'if \[ -z "\$XDG_RUNTIME_DIR" \]; then\n.*?\nfi\n', '', s, flags=re.S)
marker = 'if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then\n'
block = ('  # Eigener Laufzeitordner fuer die TV-Sitzung (unabhaengig von elogind)\n'
         '  export XDG_RUNTIME_DIR="/tmp/voidstation-runtime-$(id -u)"\n'
         '  rm -rf "$XDG_RUNTIME_DIR"; mkdir -m 0700 "$XDG_RUNTIME_DIR"\n')
if 'voidstation-runtime' not in s and marker in s:
    s = s.replace(marker, marker + block, 1)
open(p, "w").write(s)
print("ok")
PYEOF

say "6/8  Freigabe-Ordner $SHARE"
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

say "7/8  Samba (Zugriff vom Windows-PC)"
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
  [ -d "/etc/sv/$s" ] && { [ -e "/var/service/$s" ] || ln -s "/etc/sv/$s" /var/service/; }
done
sv restart smbd >/dev/null 2>&1 || true

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

say "8/8  Besitzrechte"
chown -R "$VSUSER:$VSUSER" "$HOMEDIR/.config" "$HOMEDIR/.local" "$HOMEDIR/.bash_profile" "$HOMEDIR/.xinitrc"

IP="$(ip -4 -o addr show scope global | awk '{print $4}' | cut -d/ -f1 | head -1)"
cat <<EOF

---------------------------------------------------------------------
 Fertig.  Uebernehmen mit:  sudo reboot

 Freigabe im Windows-Explorer:   \\\\${HOST}\\share
                     oder:       \\\\${IP}\\share
 Anmelden als "${VSUSER}" mit dem Freigabe-Passwort.
---------------------------------------------------------------------
EOF
exit 0
__PAYLOAD_BELOW__
