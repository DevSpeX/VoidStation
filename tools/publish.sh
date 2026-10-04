#!/bin/bash
# =====================================================================
#  VoidStation veroeffentlichen – laeuft auf dem Rechner des Herausgebers
#  (dort liegt der private Signaturschluessel).
#
#    vspub --init-key     einmalig: Signaturschluessel anlegen
#    vspub                Bundle einspielen, bauen, signieren, nach "main" (Kanal Testing) pushen
#    vspub --release      aktuellen Test-Stand fuer alle freigeben ("stable")
#    vspub --iso [datei]  Live-ISO pruefen, Pruefsumme signieren, nach SourceForge
#                         hochladen, Webseite umstellen, ISO hier loeschen
#                         (ohne Datei: neueste ISO in ~/share/ISO)
#
#  vspub ist ein Alias – einmalig in ~/.bashrc eintragen:
#     alias vspub='bash ~/VoidStation/tools/publish.sh'
#
#  Bundles: am Windows-PC nach \\<rechner>\share\Updates kopieren.
#
#  SourceForge (fuer --iso): Benutzer und Schluessel in ~/.ssh/config, z. B.
#     Host frs.sourceforge.net
#         User <SourceForge-Name>
#         IdentityFile ~/.ssh/sourceforge
#
#  Remotes:  origin   = GitHub (Hauptquelle, Pflicht)
#            codeberg = Spiegel (optional; wird mitgepusht, solange er existiert)
#  Einmalig, damit git sich das GitHub-Token merkt:
#     git config --global credential.helper store
# =====================================================================
set -euo pipefail

REPO="${VS_REPO:-$HOME/VoidStation}"
INBOX="${VS_INBOX:-$HOME/share/Updates}"
KEY="${VS_KEY:-$HOME/.ssh/voidstation-release}"
PUB="keys/voidstation-release.pub"
MIRROR="${VS_MIRROR:-codeberg}"
ISO_DIR="${VS_ISO_DIR:-$HOME/share/ISO}"
SF_HOST="${VS_SF_HOST:-frs.sourceforge.net}"
SF_PROJECT="${VS_SF_PROJECT:-voidstation}"
SF_KEY="${VS_SF_KEY:-$HOME/.ssh/sourceforge}"

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[!] %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m[x] %s\033[0m\n' "$*"; exit 1; }

has_mirror() { git remote get-url "$MIRROR" >/dev/null 2>&1; }
mirror_push() {            # Spiegel mitpflegen – Fehler dort brechen nichts ab
  has_mirror || return 0
  if git push -q "$MIRROR" "$@"; then echo "Spiegel ($MIRROR) aktualisiert."
  else warn "Spiegel ($MIRROR) nicht erreichbar – GitHub ist trotzdem aktuell."; fi
}

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

# ---------------------------------------------------------------------
#  Live-ISO veroeffentlichen (vspub --iso [datei])
#  Reihenfolge: pruefen -> fragen -> signieren -> hochladen -> kontrollieren
#  -> Webseite umstellen -> lokal loeschen. Geloescht wird nur, wenn alles oben ist.
# ---------------------------------------------------------------------
iso_set_site() {           # site/config.json auf die neue ISO stellen
  python3 - "$@" <<'PYEOF'
import json, sys
ver, date, url, size, sha, sf = sys.argv[1:]
p = "site/config.json"
c = json.load(open(p, encoding="utf-8"))
c["sourceforge"] = sf
c["iso"] = {"version": ver, "date": date, "url": url, "size_mb": int(size), "sha256": sha}
open(p, "w", encoding="utf-8").write(json.dumps(c, indent=2, ensure_ascii=False) + "\n")
PYEOF
}

iso_publish() {
  local iso="${1:-}" dir file ver stamp date sum old size_mb dest url sf_files
  local site_ok=1 why="" need_sign=1 a check stable_ver
  command -v rsync >/dev/null || die "rsync fehlt – einmalig:  sudo xbps-install -S rsync"

  if [ -z "$iso" ]; then
    iso="$(ls -t "$ISO_DIR"/voidstation-*.iso 2>/dev/null | head -n1 || true)"
    [ -n "$iso" ] || die "Keine ISO in $ISO_DIR – erst bauen:  sudo bash ~/VoidStation/dist/build-iso.sh"
  fi
  [ -f "$iso" ] || die "Datei nicht gefunden: $iso"
  dir="$(cd "$(dirname "$iso")" && pwd)"
  file="$(basename "$iso")"
  [[ "$file" =~ ^voidstation-([0-9][0-9A-Za-z.+-]*)-([0-9]{8})\.iso$ ]] \
    || die "Unerwarteter Dateiname: $file  (erwartet: voidstation-<version>-JJJJMMTT.iso)"
  ver="${BASH_REMATCH[1]}"; stamp="${BASH_REMATCH[2]}"
  date="${stamp:0:4}-${stamp:4:2}-${stamp:6:2}"
  dest="/home/frs/project/$SF_PROJECT/$ver/"
  url="https://sourceforge.net/projects/$SF_PROJECT/files/$ver/$file/download"
  sf_files="https://sourceforge.net/projects/$SF_PROJECT/files/"

  # Webseite nur umstellen, wenn das Repo sauber auf dem GitHub-Stand ist
  git fetch -q origin || true
  if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main 2>/dev/null || echo x)" ]; then
    site_ok=0; why="lokaler Stand weicht von GitHub ab – erst  vspub, dann nochmal  vspub --iso"
  elif ! git diff --quiet || ! git diff --cached --quiet; then
    site_ok=0; why="ungesicherte Aenderungen im Repo"
  fi
  stable_ver="$(git show origin/stable:dist/version.json 2>/dev/null \
    | python3 -c 'import json,sys;print(json.load(sys.stdin)["version"])' 2>/dev/null || true)"

  say "Pruefsumme"
  cd "$dir"
  echo "berechne SHA-256 von $file (dauert einen Moment) …"
  sum="$(sha256sum "$file" | cut -d' ' -f1)"
  if [ -s "$file.sha256" ]; then
    read -r old _ < "$file.sha256"
    [ "$old" = "$sum" ] || die "ISO passt nicht zu $file.sha256 – Datei kaputt oder veraendert? Neu bauen."
  fi
  # Format fuer  sha256sum -c : "<hash>  <dateiname>", ohne Pfad
  if [ "$(cat "$file.sha256" 2>/dev/null)" != "$sum  $file" ]; then
    printf '%s  %s\n' "$sum" "$file" > "$file.sha256"
  fi
  echo "OK  $sum"
  size_mb="$(du -m "$file" | cut -f1)"

  echo
  echo "  ISO:       $dir/$file  ($size_mb MB)"
  echo "  Version:   $ver vom $date"
  echo "  Ziel:      $SF_HOST:$dest"
  if [ "$site_ok" = 1 ]; then echo "  Webseite:  voidstation.de bietet danach diese ISO an"
  else echo "  Webseite:  bleibt unveraendert ($why)"; fi
  echo "  Danach:    ISO, .sha256 und .sig werden hier geloescht"
  if [ -n "$stable_ver" ] && [ "$stable_ver" != "$ver" ]; then
    warn "Stable steht auf $stable_ver – $ver ist bisher nur im Kanal Testing (Freigabe:  vspub --release)"
  fi
  echo
  read -r -p "Hochladen? [j/N] " a
  [ "$a" = j ] || [ "$a" = J ] || die "Abgebrochen – nichts hochgeladen, nichts geloescht."

  # Schluessel einmal in einen kurzlebigen ssh-agent laden -> jede Passphrase nur einmal
  ISO_SIGNERS="$(mktemp)"; signers_line "$REPO/$PUB" > "$ISO_SIGNERS"
  if [ -s "$file.sha256.sig" ] && ssh-keygen -Y verify -f "$ISO_SIGNERS" -I voidstation-release -n voidstation \
       -s "$file.sha256.sig" < "$file.sha256" >/dev/null 2>&1; then
    need_sign=0
  fi
  eval "$(ssh-agent -s)" >/dev/null || die "ssh-agent startet nicht."
  trap 'ssh-agent -k >/dev/null 2>&1; rm -f "$ISO_SIGNERS"' EXIT
  if [ "$need_sign" = 1 ]; then
    [ -e "$KEY" ] || die "Kein Signaturschluessel ($KEY)."
    ssh-add -q -t 3600 "$KEY" || die "Signaturschluessel nicht geladen."
  fi
  if [ -e "$SF_KEY" ]; then
    ssh-add -q -t 3600 "$SF_KEY" || warn "SourceForge-Schluessel nicht geladen – ssh fragt beim Hochladen selbst."
  fi

  say "Signieren"
  if [ "$need_sign" = 1 ]; then
    rm -f "$file.sha256.sig"
    ssh-keygen -q -Y sign -f "$KEY.pub" -n voidstation "$file.sha256"
    ssh-keygen -Y verify -f "$ISO_SIGNERS" -I voidstation-release -n voidstation \
      -s "$file.sha256.sig" < "$file.sha256" >/dev/null 2>&1 \
      || die "Signaturpruefung fehlgeschlagen (passt $KEY zu $PUB?)"
    echo "$file.sha256 signiert und geprueft"
  else
    echo "Signatur ist aktuell."
  fi

  say "Hochladen nach SourceForge ($SF_PROJECT/$ver)"
  [ -n "${TMUX:-}${STY:-}" ] || echo "Tipp: in tmux starten, dann laeuft der Upload weiter, wenn PuTTY zugeht."
  rsync -avP -e ssh "$file" "$file.sha256" "$file.sha256.sig" "$SF_HOST:$dest" \
    || die "Upload abgebrochen – nochmal  vspub --iso  setzt an der Stelle fort. Lokal ist nichts geloescht."
  # Kontrolle: liegt alles in voller Groesse oben?
  check="$(rsync -n -i --size-only -e ssh "$file" "$file.sha256" "$file.sha256.sig" "$SF_HOST:$dest" 2>/dev/null)" \
    || die "Kontrolle auf SourceForge fehlgeschlagen – lokal ist nichts geloescht."
  if printf '%s\n' "$check" | grep -q '^<f'; then
    die "Auf SourceForge fehlt noch etwas – nochmal  vspub --iso. Lokal ist nichts geloescht."
  fi
  echo "Alles oben."

  if [ "$site_ok" = 1 ]; then
    say "Webseite umstellen"
    cd "$REPO"
    iso_set_site "$ver" "$date" "$url" "$size_mb" "$sum" "$sf_files"
    if git diff --quiet -- site/config.json; then
      echo "Die Webseite zeigt diese ISO schon."
    else
      git add site/config.json
      git commit -q -m "Webseite: Live-ISO $ver ($date) auf SourceForge"
      if git push -q origin HEAD:main; then
        mirror_push HEAD:main
        echo "voidstation.de wird neu gebaut (dauert 1–2 Minuten)."
      else
        warn "Push fehlgeschlagen – der Commit liegt lokal, das naechste  vspub  nimmt ihn mit."
      fi
    fi
  fi

  say "Aufraeumen"
  rm -f "$dir/$file" "$dir/$file.sha256" "$dir/$file.sha256.sig"
  echo "geloescht: $dir/$file (+ .sha256, .sha256.sig)"

  cat <<EOF

Veroeffentlicht: VoidStation $ver – Live-ISO auf SourceForge
  Diese Version:  $url
  Immer aktuell:  https://sourceforge.net/projects/$SF_PROJECT/files/latest/download
Im Browser noch: Files -> $ver -> (i) neben der ISO -> "Default Download" (Linux + Windows)
Bis alle Mirrors die Datei haben, kann es etwas dauern.
EOF
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

Weiter mit:  vspub
EOF
  exit 0 ;;

# ---------------------------------------------------------------------
--release)
  say "Test-Stand fuer alle freigeben"
  git fetch -q origin
  [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || die "Lokaler Stand weicht von GitHub ab – erst  vspub"
  [ -s "$PUB" ] || die "Kein Signaturschluessel im Repo – erst  vspub --init-key"
  verify_dist || die "dist/ ist nicht korrekt signiert – erst  vspub"
  ver="$(python3 -c 'import json;print(json.load(open("dist/version.json"))["version"])')"
  if git rev-parse -q --verify origin/stable >/dev/null; then
    echo "Stable bisher: $(git log -1 --format='%h %s' origin/stable)"
  fi
  echo "Neu stabil:    $(git log -1 --format='%h %s' HEAD)  (Version $ver)"
  read -r -p "Freigeben? [j/N] " a
  [ "$a" = j ] || [ "$a" = J ] || die "Abgebrochen."
  git push origin HEAD:stable
  mirror_push HEAD:stable
  echo "Freigegeben: Version $ver ist jetzt fuer alle Geraete verfuegbar."
  exit 0 ;;

# ---------------------------------------------------------------------
--iso)
  [ -s "$PUB" ] || die "Kein Signaturschluessel im Repo – erst  vspub --init-key"
  iso_publish "${2:-}"
  exit 0 ;;

# ---------------------------------------------------------------------
"")
  ;;
*)
  die "Unbekannte Option: $1  (erlaubt: --init-key, --release, --iso)" ;;
esac

# ---- Normaler Lauf: Bundle einspielen, bauen, signieren, veroeffentlichen
[ -e "$KEY" ] || die "Kein Signaturschluessel ($KEY) – einmalig:  vspub --init-key"
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
# build.sh leert dist/ – Signaturen retten; der Bau ist reproduzierbar, bei
# unveraendertem Stand passen sie danach weiter (dann keine Passphrase noetig)
sigs="$(mktemp -d)"
cp dist/*.sig "$sigs/" 2>/dev/null || true
./build.sh | sed -n '/^Version:/p'
cp "$sigs"/*.sig dist/ 2>/dev/null || true
rm -rf "$sigs"

say "Signieren"
if verify_dist >/dev/null 2>&1; then
  echo "Signaturen sind aktuell."
else
  # Schluessel einmal in einen kurzlebigen ssh-agent laden -> Passphrase nur einmal
  signkey="$KEY"
  if command -v ssh-agent >/dev/null 2>&1 && eval "$(ssh-agent -s)" >/dev/null; then
    trap 'ssh-agent -k >/dev/null 2>&1' EXIT
    if ssh-add -q -t 300 "$KEY"; then signkey="$KEY.pub"; else ssh-agent -k >/dev/null 2>&1; trap - EXIT; fi
  fi
  for f in dist/update.sh dist/install.sh dist/voidstation-install.sh; do
    rm -f "$f.sig"
    ssh-keygen -q -Y sign -f "$signkey" -n voidstation "$f"
  done
  if [ "$signkey" = "$KEY.pub" ]; then ssh-agent -k >/dev/null 2>&1; trap - EXIT; fi
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

say "Veroeffentlichen (Kanal Testing)"
git push -q origin HEAD:main
if ! git ls-remote --exit-code --heads origin stable >/dev/null 2>&1; then
  if has_mirror && git fetch -q "$MIRROR" stable 2>/dev/null; then
    # Umzug: bisher freigegebenen Stand uebernehmen statt ungetestet freizugeben
    git push -q origin FETCH_HEAD:refs/heads/stable
    echo "Zweig 'stable' angelegt (bisheriger Stand vom Spiegel $MIRROR)."
  else
    git push -q origin HEAD:stable
    echo "Zweig 'stable' angelegt (erste Veroeffentlichung)."
  fi
fi
mirror_push HEAD:main

ver="$(python3 -c 'import json;print(json.load(open("dist/version.json"))["version"])')"
cat <<EOF

Veroeffentlicht: Version $ver im Kanal Testing (main).
Testen:    Geraet auf Kanal "Testing" -> Einstellungen -> VoidStation aktualisieren
Freigabe:  vspub --release
EOF
