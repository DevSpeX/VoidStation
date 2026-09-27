#!/bin/bash
# Baut die fertigen Skripte nach dist/:
#   install.sh          – TV-Start auf ein bestehendes Void installieren
#   update.sh           – TV-Start aktualisieren (behaelt eigene Kacheln/Favoriten)
#   tvstart-install.sh  – komplette Neuinstallation von der offiziellen Void-ISO aus
#   build-iso.sh        – eigene Live-ISO mit Installer bauen (auf einem Void-System)
set -euo pipefail
cd "$(dirname "$0")"
rm -rf dist && mkdir dist
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

(cd launcher && tar --owner=0 --group=0 --sort=name --mtime='2026-01-01' \
   --exclude='*.pyc' --exclude=__pycache__ -czf "$tmp/payload.tgz" \
   launcher.py tvstart-shell.py tiles.json catalog.json tvstart-pkg home.sh tvctl web openbox firefox)
{ cat install-head.sh; base64 -w 76 "$tmp/payload.tgz"; } > dist/install.sh
{ cat update-head.sh;  base64 -w 76 "$tmp/payload.tgz"; } > dist/update.sh

# Einzeldatei fuer die offizielle Void-ISO
{ cat iso/tvstart-install; echo '__INSTALLER_BELOW__'; base64 -w 76 dist/install.sh; } > dist/tvstart-install.sh

# ISO-Bauskript
mkdir "$tmp/iso"
cp iso/tvstart-install iso/99-tvstart-live.sh iso/tvstart-live-profile.sh dist/install.sh "$tmp/iso/"
(cd "$tmp/iso" && tar --owner=0 --group=0 --sort=name --mtime='2026-01-01' -czf "$tmp/iso.tgz" .)
{ cat iso/build-iso-head.sh; base64 -w 76 "$tmp/iso.tgz"; } > dist/build-iso.sh

chmod +x dist/*.sh
for f in dist/*.sh; do bash -n "$f"; done
ls -l dist
