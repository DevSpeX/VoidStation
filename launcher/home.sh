#!/bin/sh
# Startet die Kacheloberflaeche im Vollbild und haelt sie am Leben.
# Oberflaeche (Datei "frontend", Einstellungen → System):
#   qt  (Standard) natives Programm, Python + Qt 6 (qt/voidstation-home.py)
#   web Web-Oberflaeche in der WebKit-Shell, Firefox als Rueckfall
#       (Firefox erzwingen mit:  touch ~/.local/share/voidstation/use-firefox)
# Das Live-System nimmt immer die Web-Oberflaeche (dort steckt der Installer).
# Beendet sich die Qt-Oberflaeche dreimal hintereinander gleich nach dem Start, geht es mit web weiter.
# Qt-Oberflaeche und WebKit-Shell starten sofort (zeigen Logo + Lade-Punkte und warten selbst auf den
# Launcher), nur fuer Firefox wird vorher auf den Launcher gewartet.
TV="$HOME/.local/share/voidstation"
mkdir -p "$TV/logs"
wait_launcher() {
  for i in $(seq 1 50); do
    curl -fs http://127.0.0.1:8765/api/status >/dev/null 2>&1 && break
    sleep 0.2
  done
}
QT_FAILS=0
want_qt() {
  [ ! -e /etc/voidstation-live ] && [ "$QT_FAILS" -lt 3 ] && [ -f "$TV/qt/voidstation-home.py" ] \
    && [ "$(cat "$TV/frontend" 2>/dev/null || echo qt)" != web ] \
    && python3 -c 'import PySide6.QtQuick' 2>/dev/null
}
use_shell() {
  [ ! -e "$TV/use-firefox" ] && python3 -c 'import gi; gi.require_version("Gtk","3.0"); gi.require_version("WebKit2","4.1"); from gi.repository import WebKit2' 2>/dev/null
}
while true; do
  if want_qt; then
    t0=$(date +%s)
    python3 "$TV/qt/voidstation-home.py" >"$TV/logs/home.log" 2>&1
    if [ $(( $(date +%s) - t0 )) -lt 15 ]; then QT_FAILS=$((QT_FAILS + 1)); else QT_FAILS=0; fi
    [ "$QT_FAILS" -ge 3 ] && echo "$(date '+%F %T') Qt-Oberflaeche startet nicht (siehe logs/home.log) – weiter mit der Web-Oberflaeche" >>"$TV/logs/home-fallback.log"
  elif use_shell; then
    python3 "$TV/voidstation-shell.py" >"$TV/logs/shell.log" 2>&1
  else
    wait_launcher
    firefox --kiosk --no-remote --profile "$TV/profiles/home" http://127.0.0.1:8765/
  fi
  sleep 1
done
