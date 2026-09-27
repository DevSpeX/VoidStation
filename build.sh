#!/bin/bash
# Baut die fertigen Skripte nach dist/:
#   install.sh          – VoidStation auf ein bestehendes Void installieren
#   update.sh           – VoidStation aktualisieren (behaelt eigene Kacheln/Favoriten)
#   voidstation-install.sh  – komplette Neuinstallation von der offiziellen Void-ISO aus
#   build-iso.sh        – eigene Live-ISO mit Installer bauen (auf einem Void-System)
set -euo pipefail
cd "$(dirname "$0")"
rm -rf dist && mkdir dist
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

(cd launcher && tar --owner=0 --group=0 --sort=name --mtime='2026-01-01' \
   --exclude='*.pyc' --exclude=__pycache__ -czf "$tmp/payload.tgz" \
   launcher.py voidstation-shell.py tiles.json catalog.json voidstation-pkg home.sh vsctl web openbox firefox)
{ cat install-head.sh; base64 -w 76 "$tmp/payload.tgz"; } > dist/install.sh
{ cat update-head.sh;  base64 -w 76 "$tmp/payload.tgz"; } > dist/update.sh

# Einzeldatei fuer die offizielle Void-ISO
{ cat iso/voidstation-install; echo '__INSTALLER_BELOW__'; base64 -w 76 dist/install.sh; } > dist/voidstation-install.sh

# ISO-Bauskript
mkdir "$tmp/iso"
cp iso/voidstation-install iso/99-voidstation-live.sh iso/voidstation-live-profile.sh dist/install.sh "$tmp/iso/"
(cd "$tmp/iso" && tar --owner=0 --group=0 --sort=name --mtime='2026-01-01' -czf "$tmp/iso.tgz" .)
{ cat iso/build-iso-head.sh; base64 -w 76 "$tmp/iso.tgz"; } > dist/build-iso.sh

chmod +x dist/*.sh
for f in dist/*.sh; do bash -n "$f"; done
ls -l dist
