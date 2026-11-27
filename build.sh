#!/bin/bash
# =====================================================================
#  Baut die fertigen Skripte (Standard: nach dist/, anders mit OUT=...):
#    install.sh              – VoidStation einrichten (laeuft beim ISO-Bau und im Installer)
#    update.sh               – VoidStation aktualisieren (behaelt eigene Kacheln/Favoriten)
#    build-iso.sh            – Live-ISO mit Installer im Kacheldesign bauen (auf einem Void-System)
#    version.json            – Versionsnummer, Build-Kennung, Aenderungen (fuer die Geraete)
#    version.txt             – nur die Build-Kennung (fuer aeltere Geraete)
#
#  Eingaben:
#    CHANGELOG.md                 – erste Ueberschrift = Versionsnummer (JJJJ.MM[.N]) oder "Testing"
#    CHANGELOG.en.md              – englische Fassung, oberster Abschnitt muss drinstehen
#    launcher/web/i18n/*.json     – Texte der Oberflaeche (en.json muss alle Schluessel aus de.json haben,
#                                   weitere Sprachen nur bekannte Schluessel; fehlende = Englisch)
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
   launcher.py launcher-start.py tvindex.py discid.py gameprofiles.py vsx11.py vsreport.py vssound.py crxpack.py vsaccount tiles.json catalog.json voidstation-pkg voidstation-efistub voidstation-splash voidstation-zram voidstation-tune voidstation-mullvad voidstation-issue \
   dracut-voidstation.conf home.sh vsctl vsshot xstart sysfix.sh web qt openbox firefox shell gamedb \
   shaders \
   -C ../iso/art plymouth)                         # Startbild (Theme) fuer installierte Geraete, s. voidstation-splash

URL="$(head -n1 update-url)"
case "$URL" in https://*) ;; *) echo "update-url muss mit https:// beginnen" >&2; exit 1 ;; esac

# Signaturschluessel -> Zeile fuer ssh-keygen "allowed_signers"
# Fest benannte Dateien statt keys/*.pub: Ein weiterer Schluessel darf nicht durch eine neue Datei unbemerkt gueltig werden.
# voidstation-notfall.pub: zweiter Schluessel, offline gelagert, falls der auf dem Herausgeber-Rechner verloren geht.
SIGNERS=""
for keyfile in keys/voidstation-release.pub keys/voidstation-notfall.pub; do
  [ -s "$keyfile" ] || continue
  read -r ktype kdata _ < "$keyfile"
  case "$ktype" in ssh-ed25519|ssh-rsa|ecdsa-sha2-*) ;; *) echo "$keyfile ist kein SSH-Schluessel" >&2; exit 1 ;; esac
  SIGNERS="${SIGNERS:+$SIGNERS$'\n'}voidstation-release namespaces=\"voidstation\" $ktype $kdata"
done

# Sprachdateien: jeder Text aus de.json muss in en.json stehen, mit denselben {Platzhaltern}.
# Weitere Sprachen (es.json, fr.json, ...) duerfen unvollstaendig sein (es gilt dann Englisch), aber nur bekannte
# Schluessel enthalten (zusaetzlich region.XX fuer Laendernamen) – mit denselben Platzhaltern wie en.json.
# Jede Sprachdatei braucht ihre Zeile in LANG_TABLE (launcher/launcher.py) und umgekehrt.
python3 - launcher/web/i18n launcher/launcher.py <<'PYEOF'
import json, re, sys
from pathlib import Path
d = Path(sys.argv[1])
de, en = (json.load(open(d / f"{l}.json", encoding="utf-8")) for l in ("de", "en"))
ph = lambda s: sorted(re.findall(r"\{(\w+)\}", s)) if isinstance(s, str) else []
missing = [k for k in de if k != "labels" and k not in en]
wrong = [k for k in de if k in en and ph(de[k]) != ph(en[k])]
for k in missing: print(f"  fehlt in en.json: {k}", file=sys.stderr)
for k in wrong:   print(f"  andere Platzhalter in en.json: {k}", file=sys.stderr)
if missing or wrong:
    sys.exit("i18n: en.json ist unvollstaendig – jeder neue Text gehoert in de.json UND en.json")
src = Path(sys.argv[2]).read_text(encoding="utf-8")
block = src[src.index("LANG_TABLE = ["):]
table = set(re.findall(r'^\s*\("([A-Za-z-]+)",', block[:block.index("\n]")], re.M))
files = {p.stem for p in d.glob("*.json")}
bad = [f"  {l}.json ohne Zeile in LANG_TABLE" for l in sorted(files - table)]
bad += [f"  LANG_TABLE: {l}.json fehlt" for l in sorted(table - files)]
known = set(de) | set(en)
for f in sorted(files - {"de", "en"}):
    x = json.load(open(d / f"{f}.json", encoding="utf-8"))
    for k, v in x.items():
        if k == "labels":                        # deutsche Kachel-/Gruppennamen -> Uebersetzung (frei)
            bad += [f"  {f}.json: Label {n!r} ist kein Text" for n, t in v.items() if not isinstance(t, str)]
        elif k.startswith("region."):
            continue
        elif k not in known:
            bad.append(f"  {f}.json: unbekannter Schluessel {k}")
        elif ph(v) != ph(en.get(k, de.get(k))):
            bad.append(f"  {f}.json: andere Platzhalter in {k}")
    left = [k for k in en if k not in x]           # seit 2026.11 auch die Installer-Texte (inst.*, hint.inst*)
    if left:
        print(f"  {f}.json: {len(left)} Texte noch englisch", file=sys.stderr)
for b in bad: print(b, file=sys.stderr)
if bad:
    sys.exit("i18n: Sprachdateien passen nicht zu de.json/en.json bzw. LANG_TABLE")
PYEOF

# Build-Kennung = Pruefsumme ueber alles, was auf dem Geraet landet (reproduzierbar)
BUILD="$( { cat "$tmp/payload.tgz" install-head.sh update-head.sh CHANGELOG.md CHANGELOG.en.md update-url; printf '%s' "$SIGNERS"; } \
          | sha256sum | cut -c1-12)"

# Versionsnummer und Aenderungen aus CHANGELOG.md (deutsch) und CHANGELOG.en.md (englisch)
#  Freigegebene Versionen: Kalenderversion JJJJ.MM bzw. JJJJ.MM.N (Hotfix), aeltere 0.x.y bleiben gueltig.
#  Oben darf ein Abschnitt "## Testing – JJJJ-MM-TT" stehen (noch nicht freigegeben); die Geraete
#  sehen dann z. B. "2026.11.1+testing.20261020" (= Stand nach 2026.11.1, letzte Aenderung am 20.10.).
#  Die echte Nummer vergibt  vspub --release  bzw.  --hotfix  beim Freigeben.
python3 - "$BUILD" > "$tmp/version.json" <<'PYEOF'
import json, re, sys
HEAD = re.compile(r"^##\s+(\S+)\s+[–-]\s+(\d{4}-\d{2}-\d{2})")
CALVER = re.compile(r"^(\d{4})\.(0[1-9]|1[0-2])(?:\.([1-9]\d*))?$")
LEGACY = re.compile(r"^0\.\d+\.\d+$")
def parse(fn):
    entries, cur = [], None
    for line in open(fn, encoding="utf-8"):
        m = HEAD.match(line)
        if m:
            cur = {"version": m.group(1), "date": m.group(2), "changes": []}
            entries.append(cur)
        elif cur and line.startswith("- "):
            cur["changes"].append(line[2:].strip())
    return entries
def key(v):
    return tuple(int(x) for x in v.split("."))
def check(fn, entries):
    """Format und Reihenfolge: Testing nur ganz oben, sonst Kalender- oder alte 0.x-Versionen, absteigend."""
    seen_calver, last = False, None
    for i, e in enumerate(entries):
        v = e["version"]
        if v == "Testing":
            if i:
                sys.exit(f"{fn}: 'Testing' darf nur ganz oben stehen")
            continue
        if CALVER.match(v):
            seen_calver = True
        elif LEGACY.match(v):
            pass
        else:
            sys.exit(f"{fn}: ungueltige Version '{v}' (erwartet: JJJJ.MM, JJJJ.MM.N oder 'Testing')")
        if last and key(v) >= key(last):
            sys.exit(f"{fn}: Versionen muessen absteigend sortiert sein ({last} steht ueber {v})")
        last = v
    return seen_calver
entries = parse("CHANGELOG.md")
if not entries:
    sys.exit("CHANGELOG.md: keine Version gefunden (Format: '## 2026.11 – 2026-11-07' oder '## Testing – 2026-10-20')")
check("CHANGELOG.md", entries)
try:
    en_list = parse("CHANGELOG.en.md")
except FileNotFoundError:
    sys.exit("CHANGELOG.en.md fehlt (englische Fassung von CHANGELOG.md)")
check("CHANGELOG.en.md", en_list)
en = {e["version"]: e for e in en_list}
top = entries[0]["version"]
if not en.get(top, {}).get("changes"):
    sys.exit(f"CHANGELOG.en.md: Abschnitt {top} fehlt – jede Aenderung braucht auch einen englischen Eintrag")
for e in entries:
    if en.get(e["version"], {}).get("changes"):
        e["changes_en"] = en[e["version"]]["changes"]
if top == "Testing":
    base = next((e["version"] for e in entries[1:]), "0.0.0")
    top = f"{base}+testing.{entries[0]['date'].replace('-', '')}"
    entries[0]["version"] = top
print(json.dumps({"version": top, "build": sys.argv[1], "date": entries[0]["date"],
                  "history": entries[:10]}, ensure_ascii=False))
PYEOF
VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$tmp/version.json")"

b64() { printf '%s' "$1" | base64 -w0; }
V_B64="$(base64 -w0 < "$tmp/version.json")"
S_B64="$(b64 "$SIGNERS")"
# Ersetzungen als sed-Skript in einer Datei: version.json (mit Changelog-Verlauf) ist base64 laenger als
# 128 KiB – mehr nimmt Linux fuer ein einzelnes Programm-Argument nicht an ("Argument list too long").
# printf ist eingebaut, kennt die Grenze also nicht.
printf 's|__VS_VERSION__|%s|g\ns|__VS_UPDATE_URL__|%s|g\ns|__VS_VERSION_B64__|%s|g\ns|__VS_SIGNERS_B64__|%s|g\n' \
  "$BUILD" "$URL" "$V_B64" "$S_B64" > "$tmp/subst.sed"
subst() { sed -f "$tmp/subst.sed" "$1"; }
{ subst install-head.sh; base64 -w 76 "$tmp/payload.tgz"; } > "$OUT/install.sh"
{ subst update-head.sh;  base64 -w 76 "$tmp/payload.tgz"; } > "$OUT/update.sh"
cp "$tmp/version.json" "$OUT/version.json"
echo "$BUILD" > "$OUT/version.txt"

# ISO-Bauskript (Live-System mit Installer): install.sh, Installer und die Live-Teile im Anhang
mkdir "$tmp/iso"
cp iso/postsetup.sh iso/99-voidstation-live.sh iso/sudoers-installer iso/grub-entries.py iso/LIESMICH.txt iso/README.txt \
   launcher/voidstation-installer launcher/voidstation-pkg "$OUT/install.sh" "$tmp/iso/"
cp -r iso/art "$tmp/iso/art"                      # Startmenue-Theme, BIOS-Hintergrund, Startbild (tools/boot-art.py)
for f in grub/theme.txt grub/logo.png grub/background.png isolinux/splash.png plymouth/voidstation.plymouth plymouth/voidstation.script; do
  [ -s "iso/art/$f" ] || { echo "iso/art/$f fehlt (tools/boot-art.py)" >&2; exit 1; }
done
python3 -m py_compile launcher/voidstation-installer iso/grub-entries.py
(cd "$tmp/iso" && tar --owner=0 --group=0 --sort=name --mtime='2026-01-01' -czf "$tmp/iso.tgz" .)
{ sed "s|__VS_RELEASE__|$VERSION|g" iso/build-iso-head.sh; base64 -w 76 "$tmp/iso.tgz"; } > "$OUT/build-iso.sh"

chmod +x "$OUT"/*.sh
for f in "$OUT"/*.sh; do bash -n "$f"; done
echo "Version: $VERSION (Build $BUILD)$([ -n "$SIGNERS" ] && echo ", mit Signaturschluessel" || echo ", OHNE Signaturschluessel")"
ls -l "$OUT"
