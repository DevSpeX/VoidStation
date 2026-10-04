#!/bin/sh
# Startet die Kacheloberflaeche im Vollbild und haelt sie am Leben.
# Oberflaeche (Datei "frontend", Einstellungen → System):
#   qt  (Standard) natives Programm, Python + Qt 6 (qt/voidstation-home.py)
#   web Web-Oberflaeche in der WebKit-Shell, Firefox als Rueckfall
#       (Firefox erzwingen mit:  touch ~/.local/share/voidstation/use-firefox)
# Auch das Live-System nimmt die Qt-Oberflaeche (mit Installer); die Web-Oberflaeche bleibt Rueckfall.
# Beendet sich die Qt-Oberflaeche dreimal hintereinander gleich nach dem Start, geht es mit web weiter.
# Web-Oberflaeche mit NVIDIA-Treiber: Firefox statt WebKit – WebKit muss dort jedes Bild ueber den
# Hauptspeicher kopieren (der schnelle DMA-BUF-Weg bleibt grau), in 4K ruckelt das. Firefox zeichnet
# direkt auf der Grafikkarte. Trotzdem WebKit:  touch ~/.local/share/voidstation/use-webkit
# Qt-Oberflaeche und WebKit-Shell starten sofort (zeigen Logo + Lade-Punkte und warten selbst auf den
# Launcher), nur fuer Firefox wird vorher auf den Launcher gewartet.
# Welche Oberflaeche wann lief: logs/frontend.log
TV="$HOME/.local/share/voidstation"
FLOG="$TV/logs/frontend.log"
mkdir -p "$TV/logs"
note() { echo "$(date '+%F %T') $*" >>"$FLOG"; tail -n 50 "$FLOG" >"$FLOG.tmp" 2>/dev/null && mv -f "$FLOG.tmp" "$FLOG"; }
wait_launcher() {
  for i in $(seq 1 50); do
    curl -fs http://127.0.0.1:8765/api/status >/dev/null 2>&1 && break
    sleep 0.2
  done
}
QT_FAILS=0
want_qt() {
  [ "$QT_FAILS" -lt 3 ] && [ -f "$TV/qt/voidstation-home.py" ] \
    && [ "$(cat "$TV/frontend" 2>/dev/null || echo qt)" != web ] \
    && python3 -c 'import PySide6.QtQuick' 2>/dev/null
}
nvidia_bound() {                       # haengt eine Grafikkarte am (proprietaeren) NVIDIA-Treiber?
  for d in /sys/bus/pci/devices/*; do
    case "$(cat "$d/class" 2>/dev/null)" in 0x03*) ;; *) continue ;; esac
    [ "$(basename "$(readlink "$d/driver" 2>/dev/null)")" = nvidia ] && return 0
  done
  return 1
}
WHY=""
use_shell() {
  if [ -e "$TV/use-firefox" ]; then WHY="Firefox (use-firefox)"; return 1; fi
  if [ ! -e "$TV/use-webkit" ] && nvidia_bound; then WHY="Firefox (NVIDIA-Treiber)"; return 1; fi
  if python3 -c 'import gi; gi.require_version("Gtk","3.0"); gi.require_version("WebKit2","4.1"); from gi.repository import WebKit2' 2>/dev/null; then
    WHY="WebKit"; return 0
  fi
  WHY="Firefox (WebKitGTK fehlt)"; return 1
}
while true; do
  if want_qt; then
    note "Startseite: Qt"
    t0=$(date +%s)
    python3 "$TV/qt/voidstation-home.py" >"$TV/logs/home.log" 2>&1
    if [ $(( $(date +%s) - t0 )) -lt 15 ]; then QT_FAILS=$((QT_FAILS + 1)); else QT_FAILS=0; fi
    [ "$QT_FAILS" -ge 3 ] && echo "$(date '+%F %T') Qt-Oberflaeche startet nicht (siehe logs/home.log) – weiter mit der Web-Oberflaeche" >>"$TV/logs/home-fallback.log"
  elif use_shell; then
    note "Startseite: $WHY"
    python3 "$TV/voidstation-shell.py" >"$TV/logs/shell.log" 2>&1
  else
    note "Startseite: $WHY"
    wait_launcher
    firefox --kiosk --no-remote --profile "$TV/profiles/home" http://127.0.0.1:8765/
  fi
  sleep 1
done
