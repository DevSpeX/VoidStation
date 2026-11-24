#!/bin/bash
# =====================================================================
#  VoidStation Update – fuer eine bestehende Installation
#  Aufruf (per SSH als paul):   sudo bash update.sh
#  Neu: Startseite (Qt), Fernsehen, AppCenter,
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

# Web-Oberflaeche entfernt (2026.12, nur noch die Qt-Startseite): Shell, HTML, Umschalter, Firefox-Profil und
# WebKit-Daten der alten Startseite (auch die ganz alten Orte lose in ~/.local/share und ~/.cache).
for d in tvstart-shell.py voidstation-shell.py; do
  rm -rf "$HOMEDIR/.local/share/$d" "$HOMEDIR/.cache/$d"
done
rm -f "$TV/voidstation-shell.py" "$TV/web/index.html" "$TV/frontend" "$TV/use-firefox" "$TV/use-webkit" \
      "$TV/logs/shell.log" "$TV/logs/home-fallback.log"
rm -rf "$TV/profiles/home" "$TV/webkit" "$HOMEDIR/.cache/voidstation/webkit"

say "1/8  Pakete"
MISSING=""
for p in curl elogind xrdb pulseaudio-utils xdotool mpv python3-mpv ffmpegthumbnailer ffmpeg yt-dlp nodejs lsdvd samba flatpak xdg-desktop-portal xdg-desktop-portal-gtk fuse3 dconf xprop adwaita-qt adwaita-qt6 gnome-themes-extra xsetroot python3-gobject \
         bluez libspa-bluetooth htop nano fastfetch mousepad python3-pyside6-declarative qt6-svg qt6-imageformats qt6-plugin-tls-openssl \
         wireless-regdb bash-completion earlyoom; do
  xbps-query "$p" >/dev/null 2>&1 || MISSING="$MISSING $p"
done
# Startbild beim Hochfahren (s. voidstation-splash) – nur 64 Bit
[ "$(xbps-uhelper arch 2>/dev/null)" = x86_64 ] && ! xbps-query plymouth >/dev/null 2>&1 && MISSING="$MISSING plymouth"
if [ -n "$MISSING" ]; then xbps-install -Sy $MISSING || warn "Paketinstallation fehlgeschlagen"; else echo "alles da"; fi
# WebKitGTK brauchte nur die alte Web-Oberflaeche. Entfernen samt Abhaengigkeiten, die sonst niemand braucht (-R nimmt
# nur automatisch installierte). Haengt ein anderes Paket daran, bleibt es – nur als Abhaengigkeit markiert, damit es
# mit diesem Paket verschwindet.
if xbps-query libwebkit2gtk41 >/dev/null 2>&1; then
  if [ -z "$(xbps-query -X libwebkit2gtk41 2>/dev/null)" ]; then
    xbps-remove -Ry libwebkit2gtk41 >/dev/null 2>&1 && echo "WebKitGTK entfernt (alte Web-Oberflaeche)" \
      || warn "WebKitGTK konnte nicht entfernt werden"
  else
    xbps-pkgdb -m auto libwebkit2gtk41 >/dev/null 2>&1 || true
  fi
fi
# 32-Bit-Rechner (experimentell): 2D-Treiber fuer die alte Grafik nachholen (Xv fuer den Player, s. install.sh)
if [ "$(xbps-uhelper arch 2>/dev/null)" = i686 ]; then
  DDX=""
  for d in /sys/bus/pci/devices/*; do
    case "$(cat "$d/class" 2>/dev/null)" in 0x03*) ;; *) continue ;; esac
    case "$(cat "$d/vendor" 2>/dev/null)" in
      0x1002) ddxp=xlibre-xf86-video-ati ;;
      0x8086) ddxp=xlibre-xf86-video-intel ;;
      0x10de) ddxp=xlibre-xf86-video-nouveau ;;
      0x1106) ddxp=xlibre-xf86-video-openchrome ;;
      *) continue ;;
    esac
    xbps-query "$ddxp" >/dev/null 2>&1 || ! xbps-query -R "$ddxp" >/dev/null 2>&1 || DDX="$DDX $ddxp"
  done
  if [ -n "$DDX" ]; then
    xbps-install -Sy $DDX && echo "Grafiktreiber (2D):$DDX – wirkt nach dem Neustart" \
      || warn "Grafiktreiber$DDX konnte nicht installiert werden"
  fi
fi

# Intel-CPU: aktueller Microcode beim Start (behebt u. a. Haenger aelterer Skylake-CPUs mit altem BIOS)
if grep -q GenuineIntel /proc/cpuinfo 2>/dev/null && ! xbps-query intel-ucode >/dev/null 2>&1 && [ "${VOIDSTATION_OFFLINE:-0}" != 1 ]; then
  xbps-query void-repo-nonfree >/dev/null 2>&1 || xbps-install -Sy void-repo-nonfree || true
  if xbps-install -Sy intel-ucode; then
    UKV="$(ls /usr/lib/modules 2>/dev/null | sort -V | tail -1)"
    [ -n "$UKV" ] && xbps-reconfigure -f "linux$(echo "$UKV" | cut -d. -f1-2)" >/dev/null 2>&1 \
      && echo "Intel-Microcode eingerichtet (wirkt nach dem Neustart)" || warn "Initramfs mit Microcode nicht neu erzeugt"
  else
    warn "intel-ucode konnte nicht installiert werden"
  fi
fi

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

say "2/8  Programmdateien (eigene Kacheln, Favoriten, Einstellungen bleiben)"
KEEP="$(mktemp -d)"
for f in tiles.json radio.json tvfavs.json settings.json; do [ -f "$TV/$f" ] && cp "$TV/$f" "$KEEP/"; done
sed -n '/^__PAYLOAD_BELOW__$/,$p' "$0" | tail -n +2 | base64 -d | tar -xz -C "$TV" || { warn "Entpacken fehlgeschlagen"; exit 1; }
for f in tiles.json radio.json tvfavs.json settings.json; do [ -f "$KEEP/$f" ] && cp "$KEEP/$f" "$TV/$f"; done
rm -rf "$KEEP"
chmod +x "$TV/launcher.py" "$TV/launcher-start.py" "$TV/home.sh" "$TV/vsctl" "$TV/vsshot" "$TV/xstart" "$TV/qt/voidstation-home.py" "$TV/qt/voidstation-player.py" "$TV/sysfix.sh"
# Python-Bytecode mit Pruefsumme statt Dateizeit: build.sh setzt feste Dateizeiten, ein gleich grosser neuer Stand
# saehe fuer Python sonst unveraendert aus. Scheitert es, uebersetzt Python beim naechsten Start selbst.
rm -rf "$TV/__pycache__" "$TV/qt/__pycache__"
# chdman kommt seit 2026.12 als Paket vs-chdman aus der eigenen Paketquelle (s. "Grafik-Server" unten)
rm -rf "${TV:?}/bin"
mkdir -p "$TV/sounds"
python3 -m compileall -q --invalidation-mode checked-hash "$TV/launcher.py" "$TV/tvindex.py" "$TV/discid.py" "$TV/gameprofiles.py" "$TV/vsx11.py" "$TV/vsreport.py" "$TV/vssound.py" "$TV/qt" || warn "Bytecode nicht vorbereitet"
echo "__VS_VERSION__" > "$TV/VERSION"
echo '__VS_VERSION_B64__' | base64 -d > "$TV/version.json" 2>/dev/null || true
cp "$TV/openbox/"{rc.xml,menu.xml,autostart} "$HOMEDIR/.config/openbox/"
# Terminal: die Void-Vorgabe PS1='[\u@\h \W]\$ ' aus ~/.bashrc nehmen – sie ueberdeckt sonst die
# Eingabeaufforderung von VoidStation (/etc/bash/bashrc.d/voidstation.sh, s. sysfix.sh). Nur die unveraenderte Zeile;
# ein eigenes PS1 bleibt und geht vor.
python3 - "$HOMEDIR/.bashrc" <<'PYEOF'
import sys
p = sys.argv[1]
try:
    lines = open(p, encoding="utf-8").read().split("\n")
except OSError:
    sys.exit(0)
old = r"PS1='[\u@\h \W]\$ '"
if old in lines:
    lines[lines.index(old)] = "# PS1: kommt von VoidStation (/etc/bash/bashrc.d/voidstation.sh) – ein eigenes PS1 hier geht vor"
    open(p, "w", encoding="utf-8").write("\n".join(lines))
    print("Eingabeaufforderung: VoidStation-Vorgabe")
PYEOF

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
add({"id": "appcenter", "label": "AppCenter", "sub": "Programme", "size": "medium", "color": "#39414d", "icon": "store", "type": "apps"}, "System", 2)
# Eigener Player: Kachel „Videos & Musik“ – an die Stelle von VLC, falls es die Kachel gibt (VLC fliegt weiter unten raus)
if not any(t.get("id") == "media" for t in tiles):
    media = {"id": "media", "label": "Videos & Musik", "sub": "Eigene Medien", "size": "medium", "color": "#74461f",
             "icon": "film", "cmd": ["~/.local/share/voidstation/qt/voidstation-player.py", "--media"]}
    g = next((g for g in c["groups"] if any(t.get("id") == "vlc" for t in g["tiles"])), None)
    if g is not None:
        g["tiles"].insert(next(i for i, t in enumerate(g["tiles"]) if t.get("id") == "vlc"), media)
        vlc = next(t for t in g["tiles"] if t.get("id") == "vlc")
        if vlc.get("color") == "#74461f":
            vlc["color"] = "#5a3a1f"                   # zwei gleichfarbige Kacheln nebeneinander vermeiden
    else:
        group("Unterhaltung")["tiles"].insert(3, media)
    print("Kachel hinzugefuegt: Videos & Musik")
for t in [t for g in c["groups"] for t in g["tiles"]]:
    if t.get("type") == "apps" and t.get("sub") == "Apps & Updates":   # Updates gibt es seit 0.9.0 nur noch in den Einstellungen
        t["sub"] = "Programme"
    if t.get("cmd") and t["cmd"][0] == "visualboyadvance-m":
        t["cmd"] = ["mgba-qt"]; t["sub"] = "mGBA"
    if t.get("id") == "files" and t.get("cmd") == ["pcmanfm", "~"]:
        t["cmd"] = ["pcmanfm", "~/share"]
    # Terminal (und Terminal-Apps wie htop): Schrift und Farben kommen jetzt aus ~/.Xresources (folgen dem Theme);
    # die alten festen Vorgaben raus, eigene andere Werte bleiben
    if t.get("cmd") and t["cmd"][0] == "xterm":
        old = {"-fa": {"Monospace", "DejaVu Sans Mono"}, "-fs": {"13", "14"}, "-bg": {"#111316"}, "-fg": {"#dcdcdc"}}
        cmd, out, i = t["cmd"], [t["cmd"][0]], 1
        while i < len(cmd):
            if cmd[i] == "-e":
                out += cmd[i:]; break
            if cmd[i] in old and i + 1 < len(cmd) and cmd[i + 1] in old[cmd[i]]:
                i += 2; continue
            out.append(cmd[i]); i += 1
        if out != cmd:
            t["cmd"] = out
            print("Kachel", t.get("label", t.get("id")) + ": Terminal folgt jetzt dem Theme")
json.dump(c, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
PYEOF
xbps-query vba-m >/dev/null 2>&1 && xbps-remove -Ry vba-m >/dev/null 2>&1 && echo "defektes vba-m entfernt"

# VLC raus – „Videos & Musik“ uebernimmt. Einmalig je Geraet (Merker), damit ein spaeter selbst
# installiertes VLC nicht bei jedem Update wieder verschwindet. Wer VLC ueber das AppCenter geholt hat
# (Kachel mit "app"), behaelt es. Zurueck jederzeit ueber AppCenter → Medien → VLC.
VLCDONE=/usr/local/share/voidstation/vlc-removed
if [ ! -e "$VLCDONE" ]; then
  VLCMODE="$(python3 - "$TV/tiles.json" <<'PYEOF'
import json, sys
c = json.load(open(sys.argv[1], encoding="utf-8"))
print("keep" if any(t.get("id") == "vlc" and t.get("app") for g in c["groups"] for t in g["tiles"]) else "remove")
PYEOF
)"
  VLCOK=1
  if [ "$VLCMODE" = remove ] && xbps-query vlc >/dev/null 2>&1; then
    say 'VLC entfernen (ersetzt durch "Videos & Musik", zurueck ueber das AppCenter)'
    if xbps-remove -Ry vlc; then
      echo "VLC entfernt"
    else
      VLCOK=0; warn "VLC konnte nicht entfernt werden (haengt etwas davon ab?) – naechstes Update versucht es erneut"
    fi
  fi
  if [ "$VLCOK" = 1 ]; then
    if [ "$VLCMODE" = remove ]; then
      python3 - "$TV/tiles.json" <<'PYEOF'
import json, sys
p = sys.argv[1]
c = json.load(open(p, encoding="utf-8"))
n = 0
for g in c["groups"]:
    keep = [t for t in g["tiles"] if t.get("id") != "vlc"]
    n += len(g["tiles"]) - len(keep)
    g["tiles"] = keep
c["groups"] = [g for g in c["groups"] if g["tiles"]]
json.dump(c, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
if n:
    print("Kachel entfernt: VLC")
PYEOF
    else
      echo "VLC bleibt (selbst ueber das AppCenter installiert)"
    fi
    install -d -m 755 /usr/local/share/voidstation && date -I > "$VLCDONE" && chmod 644 "$VLCDONE"
  fi
fi

# YouTube TV-Oberflaeche (youtube.com/tv mit vorgetaeuschtem Smart-TV-Browser) ist aus dem AppCenter
# geflogen: Google laesst sie nur auf echten Fernsehern zu und meldet sonst, das Geraet werde nicht erkannt.
# Einmalig je Geraet: Kachel und Firefox-Profil entfernen. Normales YouTube (Kachel "YouTube") bleibt.
YTTVDONE=/usr/local/share/voidstation/youtube-tv-removed
if [ ! -e "$YTTVDONE" ]; then
  if python3 - "$TV/tiles.json" <<'PYEOF'
import json, sys
p = sys.argv[1]
c = json.load(open(p, encoding="utf-8"))
n = 0
for g in c["groups"]:
    keep = [t for t in g["tiles"] if t.get("id") != "youtube-tv"]
    n += len(g["tiles"]) - len(keep)
    g["tiles"] = keep
if n:
    c["groups"] = [g for g in c["groups"] if g["tiles"]]
    json.dump(c, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("Kachel entfernt: YouTube TV")
PYEOF
  then
    if [ -d "$TV/profiles/youtube-tv" ]; then
      rm -rf "$TV/profiles/youtube-tv" && echo "Firefox-Profil der YouTube TV-Oberflaeche entfernt"
    fi
    install -d -m 755 /usr/local/share/voidstation && date -I > "$YTTVDONE" && chmod 644 "$YTTVDONE"
  else
    warn "Kachel YouTube TV konnte nicht entfernt werden – naechstes Update versucht es erneut"
  fi
fi

# 32 Bit (experimentell): YouTube Light loest die YouTube-Kachel im Firefox-Kiosk ab (einmalig, an derselben Stelle und
# in derselben Groesse). Ist YouTube Light schon da (aus dem AppCenter: klein, am Ende der Gruppe), wandert diese Kachel
# an den Platz der alten. Neue Installationen bekommen das schon von install.sh; 64 Bit behaelt Firefox, YouTube Light
# steht dort im AppCenter.
# ytlight-i686 = erste Fassung (nur Testing, 22.10.2026): entfernte bei vorhandenem YouTube Light nur die alte Kachel –
# dann YouTube Light einmalig an den Anfang seiner Gruppe holen (breit).
YTLDONE=/usr/local/share/voidstation/ytlight-i686-v2
YTLOLD=/usr/local/share/voidstation/ytlight-i686
if [ "$(xbps-uhelper arch 2>/dev/null)" = i686 ] && [ ! -e "$YTLDONE" ]; then
  if python3 - "$TV/tiles.json" "$([ -e "$YTLOLD" ] && echo repair)" <<'PYEOF'
import json, sys
p, repair = sys.argv[1], sys.argv[2] == "repair"
c = json.load(open(p, encoding="utf-8"))
new = {"id": "ytlight", "label": "YouTube Light", "sub": "Videos & Abos", "size": "wide", "color": "#6e2b2b",
       "icon": "play", "cmd": ["~/.local/share/voidstation/qt/voidstation-player.py", "--yt"], "app": True}
yt_pos = next(((gi, ti) for gi, g in enumerate(c["groups"]) for ti, t in enumerate(g["tiles"]) if t.get("id") == "youtube"), None)
old = next(((gi, ti) for gi, g in enumerate(c["groups"]) for ti, t in enumerate(g["tiles"]) if t.get("id") == "ytlight"), None)
msg = ""
if yt_pos:
    gi, ti = yt_pos
    size = c["groups"][gi]["tiles"][ti].get("size", "wide")
    tile = dict(c["groups"][old[0]]["tiles"][old[1]]) if old else dict(new)
    tile["size"] = size
    c["groups"][gi]["tiles"][ti] = tile                      # an die Stelle der alten Kachel
    if old:
        c["groups"][old[0]]["tiles"].pop(old[1])          # die kleine Kachel vom AppCenter
    msg = "32 Bit: Kachel YouTube (Firefox) durch YouTube Light ersetzt"
elif repair and old:
    gi, ti = old
    tile = c["groups"][gi]["tiles"].pop(ti)
    tile["size"] = "wide"
    c["groups"][gi]["tiles"].insert(0, tile)
    msg = "32 Bit: YouTube Light an den Platz der alten YouTube-Kachel gerueckt"
if msg:
    c["groups"] = [g for g in c["groups"] if g["tiles"]]
    json.dump(c, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(msg)
PYEOF
  then
    install -d -m 755 /usr/local/share/voidstation && date -I > "$YTLDONE" && chmod 644 "$YTLDONE"
  else
    warn "YouTube Light konnte die YouTube-Kachel nicht ersetzen – naechstes Update versucht es erneut"
  fi
fi

# Bluetooth: bluetoothctl braucht die Gruppe bluetooth (wirkt nach dem naechsten Neustart)
getent group bluetooth >/dev/null && usermod -aG bluetooth "$VSUSER" || true
# DVD-Laufwerk lesen (Videos & Musik: DVDs; wirkt nach dem naechsten Neustart)
for g in optical cdrom; do getent group "$g" >/dev/null && usermod -aG "$g" "$VSUSER" || true; done

# Bluetooth & Controller (BlueZ-Einstellungen, udev-Regeln, uinput): sysfix.sh

say "Systemkorrekturen (elogind, WLAN, GRUB, Bluetooth, Controller)"
sh "$TV/sysfix.sh" || warn "Systemkorrekturen unvollstaendig"

# Konsolen: agetty-tty2 bis -tty6 nutzen per Symlink die conf von tty1 – das Autologin galt damit fuer alle sechs.
# Wirkt beim naechsten Start, damit keine offene Sitzung (auch nicht dieses Update) abbricht.
# Fassung ohne Autologin oder schon auf tty1 begrenzt: bleibt.
GETTY_CONF=/etc/sv/agetty-tty1/conf
if [ -f "$GETTY_CONF" ] && grep -q -- '--autologin' "$GETTY_CONF" && ! grep -q '"\$tty" = tty1' "$GETTY_CONF"; then
  GETTY_USER="$(sed -n 's/.*--autologin \([^ "]*\).*/\1/p' "$GETTY_CONF" | head -n1)"
  cat > "$GETTY_CONF" <<EOF
# VoidStation: gilt per Symlink auch fuer tty2 bis tty6; Autologin nur auf tty1
if [ "\$tty" = tty1 ]; then
  GETTY_ARGS="--autologin ${GETTY_USER:-$VSUSER} --noclear"
fi
BAUD_RATE=38400
TERM_NAME=linux
EOF
  echo "Konsolen: Autologin nur noch auf tty1 (ab dem naechsten Start)"
fi

say "3/8  AppCenter-Helfer (installiert nur freigegebene Pakete)"
install -o root -g root -m 755 "$TV/voidstation-pkg" /usr/local/sbin/voidstation-pkg
ln -sfn "$TV/vsctl" /usr/local/bin/vsctl          # "vsctl update" im Terminal = Einstellungen → Updates
ln -sfn "$TV/vsshot" /usr/local/bin/vsshot        # Bildschirmfoto nach share/Screenshots (wie F12, Start + Select)
install -d -o root -g root -m 755 /usr/local/share/voidstation
python3 - "$TV/catalog.json" "$(xbps-uhelper arch 2>/dev/null)" > /usr/local/share/voidstation/allowed-packages <<'PYEOF'
import json, sys
c = json.load(open(sys.argv[1], encoding="utf-8"))
arch = sys.argv[2] if len(sys.argv) > 2 else ""
pk = {"flatpak"}
# Eingabemethode fuer Japanisch, Koreanisch, Chinesisch (IME_PKGS/IME_ENGINES in launcher.py)
pk.update(["fcitx5", "fcitx5-gtk+3", "fcitx5-gtk4", "fcitx5-qt6", "fcitx5-hangul", "fcitx5-chinese-addons",
           "fcitx5-chewing", "fcitx5-mozc", "fcitx5-anthy"])
pk.add("vkBasalt")                                # Bild in Spielen (launcher.py GAME_FX), kommt erst beim Einschalten
for a in c["apps"]:
    s = a["source"]
    if arch and isinstance(a.get("arch"), list) and arch not in a["arch"]:
        continue                                  # z. B. Steam (multilib) nicht auf 32 Bit
    if s["type"] == "xbps":
        pk.add(s["pkg"])
    for k in ("repos", "deps", "optional", "host_pkgs"):
        pk.update(s.get(k, []))
    for v in s.get("gpu_deps", {}).values():
        pk.update(v)
    for v in s.get("driver_deps", {}).values():  # nur wenn der Treiber installiert ist (voidstation-pkg gpu32)
        pk.update(v)
pk = sorted(pk)
print("\n".join(pk))
PYEOF
chmod 644 /usr/local/share/voidstation/allowed-packages
echo "$(wc -l < /usr/local/share/voidstation/allowed-packages) Pakete freigegeben"
# Steam mit proprietaerem NVIDIA-Treiber: 32-Bit-Bibliotheken nachruesten (laedt Paketlisten nur, wenn noetig)
sh /usr/local/sbin/voidstation-pkg gpu32 || warn "32-Bit-Treiber fuer Steam (NVIDIA) nicht installiert – naechstes Update versucht es erneut"
printf '%s\n' "__VS_UPDATE_URL__" > /usr/local/share/voidstation/update-url
chmod 644 /usr/local/share/voidstation/update-url
# Update-Kanal (stable = fuer alle, main = Testing); bestehende Wahl bleibt
[ -s /usr/local/share/voidstation/channel ] || echo stable > /usr/local/share/voidstation/channel
# Seit 2026.11 gibt es Testing nur noch auf Wunsch (vsctl channel testing, Markierung testing-optin).
# Wer Testing frueher im Installer oder in den Einstellungen gewaehlt hat, kehrt mit dem ersten freigegebenen
# Stand auf main (Version ohne "+testing" = gleich Stable) zu Stable zurueck – ohne Downgrade. Spaetere Faelle
# erledigt der Launcher, sobald Stable neuer ist als der eigene Stand.
VSVER="$(echo '__VS_VERSION_B64__' | base64 -d 2>/dev/null | sed -n 's/^{"version": "\([^"]*\)".*/\1/p')"
if [ "$(head -n1 /usr/local/share/voidstation/channel)" = main ] && [ ! -e /usr/local/share/voidstation/testing-optin ] \
   && [ -n "$VSVER" ] && [ "${VSVER#*+testing}" = "$VSVER" ]; then
  echo stable > /usr/local/share/voidstation/channel
  echo "Update-Kanal: Stable (Testing gibt es nur noch auf Wunsch: vsctl channel testing)"
fi
chmod 644 /usr/local/share/voidstation/channel
# Signaturschluessel: danach werden nur noch signierte Updates installiert
SIGNERS="$(echo '__VS_SIGNERS_B64__' | base64 -d 2>/dev/null || true)"
if [ -n "$SIGNERS" ]; then
  printf '%s\n' "$SIGNERS" > /usr/local/share/voidstation/allowed_signers
  chmod 644 /usr/local/share/voidstation/allowed_signers
  echo "Signaturpruefung fuer Updates aktiv"
fi

# ---------------------------------------------------------------------
# Kernel-Start (ab 0.14.2): EFISTUB mit festen Dateinamen + kleineres Initramfs.
# Vorher: Eintrag je Kernelversion (manche Firmware startete weiter den alten Kernel) und
# ~240 MB Initramfs je Kernel auf der 512-MB-EFI-Partition.
install -o root -g root -m 755 "$TV/voidstation-efistub" /usr/local/sbin/voidstation-efistub
install -o root -g root -m 755 "$TV/voidstation-splash" /usr/local/sbin/voidstation-splash
install -o root -g root -m 755 "$TV/voidstation-zram" /usr/local/sbin/voidstation-zram
install -o root -g root -m 755 "$TV/voidstation-mullvad" /usr/local/sbin/voidstation-mullvad
install -d -o root -g root -m 755 /usr/local/share/voidstation
# Mullvad kommt seit 2026.12 signiert aus der eigenen Paketquelle (geprueft wird dort in der CI): Schluessel weg
rm -f /usr/local/share/voidstation/mullvad-signing.asc "$TV/mullvad-signing.asc"
install -o root -g root -m 644 "$TV/dracut-voidstation.conf" /usr/local/share/voidstation/dracut-voidstation.conf
KCHANGED=0
# Initramfs-Vorgabe von VoidStation (vom Installer bzw. aus 0.14.2) auf den neuen Stand bringen:
# kleines Initramfs ohne Grafiktreiber; seit 2026.11 darf das Startbild (Plymouth) mit hinein
DCONF=/etc/dracut.conf.d/10-voidstation.conf
if [ -f "$DCONF" ] && grep -q '^hostonly="no"' "$DCONF" && grep -q 'VoidStation' "$DCONF" \
   && ! cmp -s "$TV/dracut-voidstation.conf" "$DCONF"; then
  say "Kernel-Start: Initramfs-Vorgabe erneuert (ohne Grafiktreiber, mit Startbild)"
  install -m 644 "$TV/dracut-voidstation.conf" "$DCONF"
  KCHANGED=1
fi
if [ -f /etc/kernel.d/post-install/40-voidstation-esp ] && [ ! -f /etc/default/voidstation-efistub ]; then
  say "Kernel-Start: EFISTUB mit festem Starteintrag"
  ESPM="$(findmnt -no TARGET -t vfat /boot/efi 2>/dev/null || true)"
  if [ -n "$ESPM" ] && [ -f /etc/default/efibootmgr-kernel-hook ]; then
    OLDOPT="$(. /etc/default/efibootmgr-kernel-hook; echo "$OPTIONS")"
    OLDDISK="$(. /etc/default/efibootmgr-kernel-hook; echo "$DISK")"
    OLDPART="$(. /etc/default/efibootmgr-kernel-hook; echo "$PART")"
    if [ -n "$OLDOPT" ] && [ -n "$OLDDISK" ] && [ -n "$OLDPART" ]; then
      printf '%s\n' '# VoidStation: Kernel direkt starten (EFISTUB). Nach Aenderungen:  sudo voidstation-efistub' \
        "ESP=\"$ESPM\"" "DISK=\"$OLDDISK\"" "PART=$OLDPART" "OPTIONS=\"$OLDOPT\"" > /etc/default/voidstation-efistub
      KCHANGED=2
    else
      warn "EFISTUB-Einstellungen unvollstaendig – Umstellung uebersprungen (Start bleibt wie bisher)"
    fi
  else
    warn "EFI-Partition unter /boot/efi nicht gefunden – Umstellung uebersprungen"
  fi
fi
# Startbild beim Hochfahren (Plymouth): Theme, Kernel-Befehlszeile ("splash"), Ende vor X.
# Meldet 2, wenn das Initramfs neu gebaut werden muss – das passiert dann hier zusammen mit dem Rest.
say "Startbild beim Hochfahren"
SPL=0
/usr/local/sbin/voidstation-splash setup --no-rebuild --theme "$TV/plymouth" || SPL=$?
case "$SPL" in
  0) ;;
  2) [ "$KCHANGED" = 0 ] && KCHANGED=3 ;;
  *) warn "Startbild nicht vollstaendig eingerichtet (sudo voidstation-splash status)" ;;
esac
if [ "$KCHANGED" != 0 ]; then
  [ -f /etc/default/voidstation-efistub ] && /usr/local/sbin/voidstation-efistub --setup >/dev/null
  # Initramfs des neuesten Kernels neu bauen; der Hook legt ihn danach auf die EFI-Partition
  UKV="$(ls /boot/vmlinuz-* 2>/dev/null | sed 's|.*/vmlinuz-||' | sort -V | tail -1)"
  if [ -n "$UKV" ]; then
    echo "Initramfs fuer Kernel $UKV wird neu erzeugt (dauert etwas) ..."
    if xbps-reconfigure -f "linux$(echo "$UKV" | cut -d. -f1-2)" >/dev/null 2>&1 && [ -s "/boot/initramfs-$UKV.img" ]; then
      echo "Initramfs: $(( $(stat -c %s "/boot/initramfs-$UKV.img" 2>/dev/null || echo 0) / 1048576 )) MB"
      /usr/local/sbin/voidstation-splash stamp
    else
      warn "Kernel-Neukonfiguration fehlgeschlagen"
    fi
  fi
  if [ -f /etc/default/voidstation-efistub ]; then
    /usr/local/sbin/voidstation-efistub
    efibootmgr 2>/dev/null | sed -n '/^BootOrder/p;/VoidStation/p' || true
  fi
  df -h /boot/efi 2>/dev/null | tail -1 || true
fi

# ---------------------------------------------------------------------
say "Grafik-Server: XLibre (ersetzt ein noch vorhandenes X.Org)"
sh /usr/local/sbin/voidstation-pkg xserver ensure || warn "XLibre nicht eingerichtet – naechstes Update versucht es erneut"
# chdman (bin/cue -> CHD in der Spieleliste): Paket vs-chdman aus derselben Quelle, nur x86_64
if [ "$(xbps-uhelper arch 2>/dev/null)" = x86_64 ] && ! xbps-query vs-chdman >/dev/null 2>&1; then
  xbps-install -y vs-chdman >/dev/null 2>&1 || xbps-install -Sy vs-chdman >/dev/null 2>&1 \
    || warn "vs-chdman nicht installiert – In CHD umwandeln fehlt bis zum naechsten Update"
fi

say "4/8  Rechte ohne Passwort: Ausschalten, WLAN, AppCenter"
rm -f /etc/sudoers.d/voidstation /etc/sudoers.d/tvstart /etc/sudoers.d/zz-tvstart
cat > /etc/sudoers.d/zz-voidstation <<EOF
$VSUSER ALL=(root) NOPASSWD: /usr/bin/poweroff, /usr/bin/reboot, /usr/bin/nmcli, /usr/local/sbin/voidstation-pkg
EOF
chmod 440 /etc/sudoers.d/zz-voidstation
visudo -cf /etc/sudoers.d/zz-voidstation >/dev/null || { warn "sudoers-Regel fehlerhaft, entferne sie"; rm -f /etc/sudoers.d/zz-voidstation; }

say "5/8  Laufzeitordner fuer den Ton"
sed -i 's|^  exec startx -- -nolisten tcp vt1 >"$HOME/.xsession-errors" 2>&1$|  exec "$HOME/.local/share/voidstation/xstart"|' "$HOMEDIR/.bash_profile" 2>/dev/null || true
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
for d in ROMs/gba ROMs/gbc ROMs/nes ROMs/snes ROMs/psx ROMs/psp ROMs/nds ROMs/gamecube ROMs/wii ROMs/dreamcast \
         ROMs/dos ROMs/c64 ROMs/atari2600 ROMs/scummvm ROMs/ps2 ROMs/n64 ROMs/xbox ROMs/3ds ROMs/wiiu ROMs/mame \
         ROMs/megadrive ROMs/mastersystem ROMs/gamegear ROMs/saturn ROMs/pcengine \
         Musik Videos Bilder Screenshots; do
  mkdir -p "$SHARE/$d"
done
[ -f "$SHARE/LIESMICH.txt" ] || cat > "$SHARE/LIESMICH.txt" <<'EOF'
VoidStation Freigabe
=================
ROMs/<system>   Spiele fuer die Emulatoren (gba, gbc, nes, snes, psx, psp, nds …)
ROMs/<system>/bios  BIOS-Dateien aus der eigenen Konsole – was hineingehoert, steht im Hinweis im Ordner
Musik, Videos   eigene Medien (Kachel "Videos & Musik")
Bilder          fuer den Bildbetrachter
Screenshots     Bildschirmfotos (F12, Start + Select am Controller oder Befehl vsshot)
vs-reports      Fehlerberichte (Einstellungen → System → Fehlerbericht oder Befehl vsctl report)
EOF
# BIOS liegt seit Oktober 2026 je System in ROMs/<system>/bios (der Launcher verschiebt alte Dateien selbst)
sed -i 's|^BIOS  .*|ROMs/<system>/bios  BIOS-Dateien aus der eigenen Konsole – was hineingehoert, steht im Hinweis im Ordner|' \
  "$SHARE/LIESMICH.txt" 2>/dev/null || true
grep -q '^Screenshots ' "$SHARE/LIESMICH.txt" 2>/dev/null || \
  printf '%s\n' 'Screenshots     Bildschirmfotos (F12, Start + Select am Controller oder Befehl vsshot)' >> "$SHARE/LIESMICH.txt" 2>/dev/null || true
grep -q '^vs-reports ' "$SHARE/LIESMICH.txt" 2>/dev/null || \
  printf '%s\n' 'vs-reports      Fehlerberichte (Einstellungen → System → Fehlerbericht oder Befehl vsctl report)' >> "$SHARE/LIESMICH.txt" 2>/dev/null || true
rmdir "$SHARE/BIOS" 2>/dev/null || true
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
# Firefox-Richtlinien (FX OSK gesperrt, ersetzt durch die Bildschirmtastatur der Startseite)
install -d /etc/firefox/policies /usr/local/share/voidstation
[ -f "$TV/firefox/policies.json" ] && cp "$TV/firefox/policies.json" /etc/firefox/policies/policies.json
# Bildschirmtastatur in Firefox: eigene Erweiterung "VoidStation-Tastatur" (firefox/keyboard/) meldet angewaehlte
# Eingabefelder an die Startseite, die dann ihre Tastatur ueber Firefox oeffnet. Im Programmordner (App-Bereich) darf
# sie unsigniert sein: Void baut Firefox mit --with-unsigned-addon-scopes=app,system. FX OSK sperrt die Richtlinie.
# LibreWolf bekommt dieselbe Datei vor jedem Start ins Profil (librewolf_keyboard in launcher.py), Chromium, Brave und
# Brave Origin eine signierte .crx per Richtlinie, dazu uBlock Origin (Lite) – crxpack.py.
VSX=/usr/local/share/voidstation/keyboard.xpi
FXEXT=/usr/lib/firefox/browser/extensions
install -d /usr/local/share/voidstation
rm -f "$VSX.tmp"
if [ -f "$TV/firefox/keyboard/manifest.json" ] && \
   (cd "$TV/firefox/keyboard" && python3 -m zipfile -c "$VSX.tmp" manifest.json background.js focus.js); then
  chmod 644 "$VSX.tmp" && mv -f "$VSX.tmp" "$VSX"
  if [ -d /usr/lib/firefox ]; then
    install -d "$FXEXT" && install -m 644 "$VSX" "$FXEXT/keyboard@voidstation.de.xpi"
  fi
else
  rm -f "$VSX.tmp"; warn "Firefox-Erweiterung VoidStation-Tastatur nicht eingerichtet"
fi
python3 "$TV/crxpack.py" "$TV/firefox/keyboard" /usr/local/share/voidstation/chromium \
  || warn "VoidStation-Tastatur fuer Chromium/Brave nicht eingerichtet"
rm -f /usr/local/share/voidstation/fx_osk.xpi
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

say "8/8  Besitzrechte"
chown -R "$VSUSER:$VSUSER" "$HOMEDIR/.config" "$HOMEDIR/.local" "$HOMEDIR/.bash_profile" "$HOMEDIR/.xinitrc"

# Alles auf die Platte schreiben, bevor "Fertig" erscheint: ext4 haelt frisch geschriebene Dateien sonst noch
# Sekunden im Speicher – geht der Rechner dann hart aus (Netzschalter, VM-Fenster zu), bleiben sie leer
# (gesehen am 22.10.2026: xstart, Autostart, Web-Oberflaeche mit 0 Byte, Startseite kam nicht mehr).
sync

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
