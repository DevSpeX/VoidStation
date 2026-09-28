#!/bin/bash
# =====================================================================
#  VoidStation veroeffentlichen: neuestes Git-Bundle aus der Freigabe
#  einspielen und zu Codeberg pushen.
#
#  1. Bundle am Windows-PC nach \\<rechner>\share\Updates kopieren
#  2. Auf dem Geraet:  bash ~/VoidStation/tools/publish.sh
#  3. Am Fernseher:    Einstellungen -> VoidStation aktualisieren
#
#  Einmalig, damit git nicht jedes Mal nach dem Passwort fragt:
#     git config --global credential.helper store
# =====================================================================
set -euo pipefail

REPO="${VS_REPO:-$HOME/VoidStation}"
INBOX="${VS_INBOX:-$HOME/share/Updates}"

mkdir -p "$INBOX/erledigt"
[ -d "$REPO/.git" ] || { echo "Kein Repo unter $REPO gefunden."; exit 1; }

b="$(ls -t "$INBOX"/*.bundle 2>/dev/null | head -n1 || true)"
if [ -z "$b" ]; then
  echo "Kein Bundle in $INBOX."
  echo "Datei vom Windows-PC nach \\\\$(cat /etc/hostname 2>/dev/null || hostname)\\share\\Updates kopieren."
  exit 1
fi
echo "Bundle: $(basename "$b")"

cd "$REPO"
git bundle verify -q "$b" >/dev/null 2>&1 || { echo "Bundle passt nicht zu diesem Repo (fehlende Vorgaenger-Commits)."; exit 1; }
before="$(git rev-parse HEAD)"
git pull -q --ff-only "$b" main
if [ "$(git rev-parse HEAD)" = "$before" ]; then
  echo "Nichts Neues im Bundle."
else
  echo "Neu:"; git log --oneline "$before"..HEAD | sed 's/^/  /'
fi
git push -q
mv "$b" "$INBOX/erledigt/$(date +%Y%m%d-%H%M)-$(basename "$b")"

echo
echo "Veroeffentlicht (Version $(cat dist/version.txt 2>/dev/null || echo ?))."
echo "Am Fernseher: Einstellungen -> VoidStation aktualisieren."
