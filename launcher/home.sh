#!/bin/sh
# Startet die Kacheloberflaeche im Vollbild und haelt sie am Leben.
# Bevorzugt die schlanke WebKit-Shell; Firefox bleibt als Rueckfall
# (erzwingen mit:  touch ~/.local/share/voidstation/use-firefox).
TV="$HOME/.local/share/voidstation"
for i in $(seq 1 50); do
  curl -fs http://127.0.0.1:8765/api/status >/dev/null 2>&1 && break
  sleep 0.2
done
use_shell() {
  [ ! -e "$TV/use-firefox" ] && python3 -c 'import gi; gi.require_version("Gtk","3.0"); gi.require_version("WebKit2","4.1"); from gi.repository import WebKit2' 2>/dev/null
}
while true; do
  if use_shell; then
    python3 "$TV/voidstation-shell.py" >"$TV/logs/shell.log" 2>&1
  else
    firefox --kiosk --no-remote --profile "$TV/profiles/home" http://127.0.0.1:8765/
  fi
  sleep 1
done
