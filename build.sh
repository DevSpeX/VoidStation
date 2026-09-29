#!/bin/bash
# =====================================================================
#  Baut die fertigen Skripte (Standard: nach dist/, anders mit OUT=...):
#    install.sh              – VoidStation auf ein bestehendes Void installieren
#    update.sh               – VoidStation aktualisieren (behaelt eigene Kacheln/Favoriten)
#    voidstation-install.sh  – komplette Neuinstallation von der offiziellen Void-ISO aus
#    build-iso.sh            – Live-ISO mit Installer im Kacheldesign bauen (auf einem Void-System)
#    version.json            – Versionsnummer, Build-Kennung, Aenderungen (fuer die Geraete)
#    version.txt             – nur die Build-Kennung (fuer aeltere Geraete)
#
#  Eingaben:
#    CHANGELOG.md                 – erste Ueberschrift = Versionsnummer
#    CHANGELOG.en.md              – englische Fassung, neueste Version muss drinstehen
#    launcher/web/i18n/*.json     – Texte der Oberflaeche (en.json muss alle Schluessel aus de.json haben)
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

# Sprachdateien: jeder Text aus de.json muss in en.json stehen, mit denselben {Platzhaltern}
python3 - launcher/web/i18n/de.json launcher/web/i18n/en.json <<'PYEOF'
import json, re, sys
de, en = (json.load(open(p, encoding="utf-8")) for p in sys.argv[1:3])
ph = lambda s: sorted(re.findall(r"\{(\w+)\}", s)) if isinstance(s, str) else []
missing = [k for k in de if k != "labels" and k not in en]
wrong = [k for k in de if k in en and ph(de[k]) != ph(en[k])]
for k in missing: print(f"  fehlt in en.json: {k}", file=sys.stderr)
for k in wrong:   print(f"  andere Platzhalter in en.json: {k}", file=sys.stderr)
if missing or wrong:
    sys.exit("i18n: en.json ist unvollstaendig – jeder neue Text gehoert in de.json UND en.json")
PYEOF

# Build-Kennung = Pruefsumme ueber alles, was auf dem Geraet landet (reproduzierbar)
BUILD="$( { cat "$tmp/payload.tgz" install-head.sh update-head.sh CHANGELOG.md CHANGELOG.en.md update-url; printf '%s' "$SIGNERS"; } \
          | sha256sum | cut -c1-12)"

# Versionsnummer und Aenderungen aus CHANGELOG.md (deutsch) und CHANGELOG.en.md (englisch)
python3 - "$BUILD" > "$tmp/version.json" <<'PYEOF'
import json, re, sys
def parse(fn):
    entries, cur = [], None
    for line in open(fn, encoding="utf-8"):
        m = re.match(r"^##\s+(\S+)\s+[–-]\s+(\d{4}-\d{2}-\d{2})", line)
        if m:
            cur = {"version": m.group(1), "date": m.group(2), "changes": []}
            entries.append(cur)
        elif cur and line.startswith("- "):
            cur["changes"].append(line[2:].strip())
    return entries
entries = parse("CHANGELOG.md")
if not entries:
    sys.exit("CHANGELOG.md: keine Version gefunden (Format: '## 0.4.0 – 2026-09-28')")
try:
    en = {e["version"]: e for e in parse("CHANGELOG.en.md")}
except FileNotFoundError:
    sys.exit("CHANGELOG.en.md fehlt (englische Fassung von CHANGELOG.md)")
top = entries[0]["version"]
if not en.get(top, {}).get("changes"):
    sys.exit(f"CHANGELOG.en.md: Version {top} fehlt – jede neue Version braucht auch einen englischen Eintrag")
for e in entries:
    if en.get(e["version"], {}).get("changes"):
        e["changes_en"] = en[e["version"]]["changes"]
print(json.dumps({"version": top, "build": sys.argv[1], "date": entries[0]["date"],
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

# ISO-Bauskript (Live-System mit Installer): install.sh, Installer und die Live-Teile im Anhang
mkdir "$tmp/iso"
cp iso/postsetup.sh iso/99-voidstation-live.sh iso/sudoers-installer iso/grub-entries.py iso/LIESMICH.txt iso/README.txt \
   launcher/voidstation-installer launcher/voidstation-pkg "$OUT/install.sh" "$tmp/iso/"
python3 -m py_compile launcher/voidstation-installer iso/grub-entries.py
(cd "$tmp/iso" && tar --owner=0 --group=0 --sort=name --mtime='2026-01-01' -czf "$tmp/iso.tgz" .)
{ sed "s|__VS_RELEASE__|$VERSION|g" iso/build-iso-head.sh; base64 -w 76 "$tmp/iso.tgz"; } > "$OUT/build-iso.sh"

chmod +x "$OUT"/*.sh
for f in "$OUT"/*.sh; do bash -n "$f"; done
echo "Version: $VERSION (Build $BUILD)$([ -n "$SIGNERS" ] && echo ", mit Signaturschluessel" || echo ", OHNE Signaturschluessel")"
ls -l "$OUT"
