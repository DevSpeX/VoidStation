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
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
Dy+PVxYAgAIA
