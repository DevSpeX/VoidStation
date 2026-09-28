#!/bin/bash
# =====================================================================
#  VoidStation veroeffentlichen – laeuft auf dem Rechner des Herausgebers
#  (dort liegt der private Signaturschluessel).
#
#    bash ~/VoidStation/tools/publish.sh --init-key   einmalig: Signaturschluessel anlegen
#    bash ~/VoidStation/tools/publish.sh              Bundle einspielen, bauen, signieren,
#                                                      nach "main" (Test-Kanal) pushen
#    bash ~/VoidStation/tools/publish.sh --release    aktuellen Test-Stand fuer alle
#                                                      freigeben ("stable")
#
#  Bundles: am Windows-PC nach \\<rechner>\share\Updates kopieren.
#  Einmalig, damit git sich das Codeberg-Token merkt:
#     git config --global credential.helper store
# =====================================================================
set -euo pipefail

REPO="${VS_REPO:-$HOME/VoidStation}"
INBOX="${VS_INBOX:-$HOME/share/Updates}"
KEY="${VS_KEY:-$HOME/.ssh/voidstation-release}"
PUB="keys/voidstation-release.pub"

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m[x] %s\033[0m\n' "$*"; exit 1; }

[ -d "$REPO/.git" ] || die "Kein Repo unter $REPO gefunden."
cd "$REPO"
# Commits auch ohne globale git-Identitaet moeglich
git config user.name  >/dev/null || git config user.name  "$(whoami)"
git config user.email >/dev/null || git config user.email "$(whoami)@$(cat /etc/hostname 2>/dev/null || echo localhost)"

signers_line() {           # oeffentlicher Schluessel -> Zeile fuer ssh-keygen -Y verify
  read -r t k _ < "$1"
  printf 'voidstation-release namespaces="voidstation" %s %s\n' "$t" "$k"
}

verify_dist() {            # prueft alle Signaturen in dist/ gegen keys/…pub
  local ok=0 f
  local signers; signers="$(mktemp)"; signers_line "$PUB" > "$signers"
  for f in dist/update.sh dist/install.sh dist/voidstation-install.sh; do
    if ! ssh-keygen -Y verify -f "$signers" -I voidstation-release -n voidstation -s "$f.sig" < "$f" >/dev/null 2>&1; then
      ok=1; echo "  Signatur fehlt/ungueltig: $f"
    fi
  done
  rm -f "$signers"
  return $ok
}

case "${1:-}" in
# ---------------------------------------------------------------------
--init-key)
  [ -e "$KEY" ] && die "Schluessel existiert schon: $KEY"
  mkdir -p "$(dirname "$KEY")"; chmod 700 "$(dirname "$KEY")"
  say "Signaturschluessel anlegen ($KEY)"
  echo "Tipp: Passwort vergeben – es wird bei jeder Veroeffentlichung abgefragt."
  ssh-keygen -t ed25519 -f "$KEY" -C "voidstation-release"
  mkdir -p keys && cp "$KEY.pub" "$PUB"
  cat <<EOF

Fertig. WICHTIG – Sicherungskopie des privaten Schluessels anlegen, z. B. auf den Windows-PC:
   pscp $(whoami)@<IP>:.ssh/voidstation-release  .
Ohne diesen Schluessel koennen Geraete keine Updates mehr annehmen.

Weiter mit:  bash tools/publish.sh
EOF
  exit 0 ;;

# ---------------------------------------------------------------------
--release)
  say "Test-Stand fuer alle freigeben"
  git fetch -q origin
  [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || die "Lokaler Stand weicht von Codeberg ab – erst  bash tools/publish.sh"
  [ -s "$PUB" ] || die "Kein Signaturschluessel im Repo – erst  bash tools/publish.sh --init-key"
  verify_dist || die "dist/ ist nicht korrekt signiert – erst  bash tools/publish.sh"
  ver="$(python3 -c 'import json;print(json.load(open("dist/version.json"))["version"])')"
  if git rev-parse -q --verify origin/stable >/dev/null; then
    echo "Stabil bisher: $(git log -1 --format='%h %s' origin/stable)"
  fi
  echo "Neu stabil:    $(git log -1 --format='%h %s' HEAD)  (Version $ver)"
  read -r -p "Freigeben? [j/N] " a
  [ "$a" = j ] || [ "$a" = J ] || die "Abgebrochen."
  git push origin HEAD:stable
  echo "Freigegeben: Version $ver ist jetzt fuer alle Geraete verfuegbar."
  exit 0 ;;

# ---------------------------------------------------------------------
"")
  ;;
*)
  die "Unbekannte Option: $1  (erlaubt: --init-key, --release)" ;;
esac

# ---- Normaler Lauf: Bundle einspielen, bauen, signieren, veroeffentlichen
[ -e "$KEY" ] || die "Kein Signaturschluessel ($KEY) – einmalig:  bash tools/publish.sh --init-key"
mkdir -p "$INBOX/erledigt"
git fetch -q origin || true

b="$(ls -t "$INBOX"/*.bundle 2>/dev/null | head -n1 || true)"
if [ -n "$b" ]; then
  say "Bundle: $(basename "$b")"
  git bundle verify -q "$b" >/dev/null 2>&1 || die "Bundle passt nicht zu diesem Repo (fehlende Vorgaenger-Commits)."
  before="$(git rev-parse HEAD)"
  if ! { git fetch -q "$b" main && git merge -q --no-edit -m "Bundle $(basename "$b") uebernommen" FETCH_HEAD; }; then
    git merge --abort 2>/dev/null || true
    die "Bundle liess sich nicht einspielen (Konflikt) – nichts veraendert."
  fi
  if [ "$(git rev-parse HEAD)" = "$before" ]; then echo "Nichts Neues im Bundle."
  else echo "Neu:"; git log --oneline --no-merges "$before"..HEAD | sed 's/^/  /'; fi
  mv "$b" "$INBOX/erledigt/$(date +%Y%m%d-%H%M)-$(basename "$b")"
else
  echo "Kein Bundle in $INBOX – baue und signiere den aktuellen Stand."
fi

say "Bauen"
mkdir -p keys
if ! cmp -s "$KEY.pub" "$PUB" 2>/dev/null; then cp "$KEY.pub" "$PUB"; echo "oeffentlicher Schluessel ins Repo uebernommen"; fi
./build.sh | sed -n '/^Version:/p'

say "Signieren"
if verify_dist >/dev/null 2>&1; then
  echo "Signaturen sind aktuell."
else
  for f in dist/update.sh dist/install.sh dist/voidstation-install.sh; do
    rm -f "$f.sig"
    ssh-keygen -q -Y sign -f "$KEY" -n voidstation "$f"
  done
  verify_dist || die "Signaturpruefung nach dem Signieren fehlgeschlagen."
  echo "signiert und geprueft"
fi

git add -A dist keys
if git diff --cached --quiet; then
  echo "Keine Aenderungen an dist/."
else
  ver="$(python3 -c 'import json;d=json.load(open("dist/version.json"));print(d["version"], "(Build " + d["build"] + ")")')"
  git commit -q -m "[build] $ver signiert"
fi

say "Veroeffentlichen (Test-Kanal)"
git push -q origin HEAD:main
if ! git ls-remote --exit-code --heads origin stable >/dev/null 2>&1; then
  git push -q origin HEAD:stable
  echo "Zweig 'stable' angelegt (erste Veroeffentlichung)."
fi

ver="$(python3 -c 'import json;print(json.load(open("dist/version.json"))["version"])')"
cat <<EOF

Veroeffentlicht: Version $ver im Test-Kanal (main).
Testen:    Geraet auf Kanal "Test" -> Einstellungen -> VoidStation aktualisieren
Freigabe:  bash tools/publish.sh --release
EOF
