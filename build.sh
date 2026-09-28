#!/bin/bash
# =====================================================================
#  Baut die fertigen Skripte (Standard: nach dist/, anders mit OUT=...):
#    install.sh              – VoidStation auf ein bestehendes Void installieren
#    update.sh               – VoidStation aktualisieren (behaelt eigene Kacheln/Favoriten)
#    voidstation-install.sh  – komplette Neuinstallation von der offiziellen Void-ISO aus
#    build-iso.sh            – eigene Live-ISO mit Installer bauen (auf einem Void-System)
#    version.json            – Versionsnummer, Build-Kennung, Aenderungen (fuer die Geraete)
#    version.txt             – nur die Build-Kennung (fuer aeltere Geraete)
#
#  Eingaben:
#    CHANGELOG.md                 – erste Ueberschrift = Versionsnummer
#    update-url                   – Update-Quelle der Geraete ({channel} = stable/main)
#    keys/voidstation-release.pub – oeffentlicher Signaturschluessel (optional)
#
#  Signiert wird nicht hier, sondern von tools/publish.sh (privater Schluessel).
# =====================================================================
set -euo pipefail
cd "$(dirname "$0")"
OUT="${OUT:-dist}"
rm -rf "$OUT" && mkdir -p "$OUT"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

(cd launcher && tar --owner=0 --group=0 --sort=name --mtime='2026-01-01' \
   --exclude='*.pyc' --exclude=__pycache__ -czf "$tmp/payload.tgz" \
   launcher.py voidstation-shell.py tiles.json catalog.json voidstation-pkg home.sh vsctl xstart web openbox firefox)

URL="$(head -n1 update-url)"
case "$URL" in https://*) ;; *) echo "update-url muss mit https:// beginnen" >&2; exit 1 ;; esac

# Signaturschluessel -> Zeile fuer ssh-keygen "allowed_signers"
SIGNERS=""
if [ -s keys/voidstation-release.pub ]; then
  read -r ktype kdata _ < keys/voidstation-release.pub
  case "$ktype" in ssh-ed25519|ssh-rsa|ecdsa-sha2-*) ;; *) echo "keys/voidstation-release.pub ist kein SSH-Schluessel" >&2; exit 1 ;; esac
  SIGNERS="voidstation-release namespaces=\"voidstation\" $ktype $kdata"
fi

# Build-Kennung = Pruefsumme ueber alles, was auf dem Geraet landet (reproduzierbar)
BUILD="$( { cat "$tmp/payload.tgz" install-head.sh update-head.sh CHANGELOG.md update-url; printf '%s' "$SIGNERS"; } \
          | sha256sum | cut -c1-12)"

# Versionsnummer und Aenderungen aus CHANGELOG.md
python3 - "$BUILD" > "$tmp/version.json" <<'PYEOF'
import json, re, sys
entries, cur = [], None
for line in open("CHANGELOG.md", encoding="utf-8"):
    m = re.match(r"^##\s+(\S+)\s+[–-]\s+(\d{4}-\d{2}-\d{2})", line)
    if m:
        cur = {"version": m.group(1), "date": m.group(2), "changes": []}
        entries.append(cur)
    elif cur and line.startswith("- "):
        cur["changes"].append(line[2:].strip())
if not entries:
    sys.exit("CHANGELOG.md: keine Version gefunden (Format: '## 0.4.0 – 2026-09-28')")
print(json.dumps({"version": entries[0]["version"], "build": sys.argv[1], "date": entries[0]["date"],
                  "history": entries[:10]}, ensure_ascii=False))
PYEOF
VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$tmp/version.json")"

b64() { printf '%s' "$1" | base64 -w0; }
V_B64="$(base64 -w0 < "$tmp/version.json")"
S_B64="$(b64 "$SIGNERS")"
subst() {
  sed -e "s|__VS_VERSION__|$BUILD|g" -e "s|__VS_UPDATE_URL__|$URL|g" \
      -e "s|__VS_VERSION_B64__|$V_B64|g" -e "s|__VS_SIGNERS_B64__|$S_B64|g" "$1"
}
{ subst install-head.sh; base64 -w 76 "$tmp/payload.tgz"; } > "$OUT/install.sh"
{ subst update-head.sh;  base64 -w 76 "$tmp/payload.tgz"; } > "$OUT/update.sh"
cp "$tmp/version.json" "$OUT/version.json"
echo "$BUILD" > "$OUT/version.txt"

# Einzeldatei fuer die offizielle Void-ISO
{ cat iso/voidstation-install; echo '__INSTALLER_BELOW__'; base64 -w 76 "$OUT/install.sh"; } > "$OUT/voidstation-install.sh"

# ISO-Bauskript
mkdir "$tmp/iso"
cp iso/voidstation-install iso/99-voidstation-live.sh iso/voidstation-live-profile.sh "$OUT/install.sh" "$tmp/iso/"
(cd "$tmp/iso" && tar --owner=0 --group=0 --sort=name --mtime='2026-01-01' -czf "$tmp/iso.tgz" .)
{ cat iso/build-iso-head.sh; base64 -w 76 "$tmp/iso.tgz"; } > "$OUT/build-iso.sh"

chmod +x "$OUT"/*.sh
for f in "$OUT"/*.sh; do bash -n "$f"; done
echo "Version: $VERSION (Build $BUILD)$([ -n "$SIGNERS" ] && echo ", mit Signaturschluessel" || echo ", OHNE Signaturschluessel")"
ls -l "$OUT"
