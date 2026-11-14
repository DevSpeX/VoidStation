#!/bin/bash
# =====================================================================
#  VoidStation veroeffentlichen – laeuft auf dem Rechner des Herausgebers
#  (dort liegt der private Signaturschluessel). Ablauf und Regeln: RELEASING.md
#
#    vspub --init-key       einmalig: Signaturschluessel anlegen
#    vspub                  Bundle einspielen, bauen, signieren, nach "main" (Kanal Testing) pushen
#    vspub --status [tag]   was liegt in Testing, seit wann, was faehrt mit dem Release-Zug?
#                           tag = Tag des Zugs (JJJJ-MM-TT), ohne Angabe: diese Woche
#    vspub --release        Release-Zug: alles, was vor der Sperrfrist nach Testing kam, als
#                           Version JJJJ.MM fuer alle freigeben ("stable"). Die Sperrfrist
#                           beginnt am Montag der Woche, in der der Zug faehrt.
#    vspub --release <rev>  genau diesen Stand freigeben (z. B. HEAD = alles, auch was erst
#                           in der Sperrfrist kam)
#    vspub --hotfix <rev>…  einzelne Fehlerbehebungen aus Testing sofort als JJJJ.MM.N auf Stable
#    vspub --iso [datei]    Live-ISO pruefen, Pruefsumme signieren, nach SourceForge
#                           hochladen, Webseite umstellen, ISO hier loeschen
#                           (ohne Datei: neueste ISO in ~/share/ISO)
#
#  Versionsnummern vergibt vspub beim Freigeben: Neues steht im CHANGELOG unter
#  "## Testing – <datum>" und wird bei --release zu "## 2026.11 – <heute>".
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
TRAIN="${VS_TRAIN:-}"                    # Tag des Release-Zugs (JJJJ-MM-TT), leer = heute; legt die Sperrfrist fest
HOTFIX_DAYS="${VS_HOTFIX_DAYS:-2}"       # Mindestliegezeit fuer Hotfixes
# Was auf den Geraeten landet – nur Aenderungen hier zaehlen fuer Sperrfrist und Liegezeit
DEVICE_PATHS=(launcher install-head.sh update-head.sh iso build.sh update-url keys CHANGELOG.md CHANGELOG.en.md)

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[!] %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m[x] %s\033[0m\n' "$*"; exit 1; }
ask()  { local a; read -r -p "$1 [j/N] " a; [ "$a" = j ] || [ "$a" = J ]; }

# Aufraeumen am Ende (auch bei Abbruch): ssh-agent, Arbeitsverzeichnis fuer Freigaben, Temp-Dateien
AGENT_PID=""; WT=""; TMPS=()
cleanup() {
  if [ -n "$WT" ]; then git -C "$REPO" worktree remove --force "$WT" >/dev/null 2>&1 || true; fi
  if [ -n "$AGENT_PID" ]; then ssh-agent -k >/dev/null 2>&1 || true; fi
  [ ${#TMPS[@]} -eq 0 ] || rm -rf "${TMPS[@]}"
}
trap cleanup EXIT

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
CL=(python3 "$REPO/tools/changelog.py")

signers_line() {           # oeffentlicher Schluessel -> Zeile fuer ssh-keygen -Y verify
  read -r t k _ < "$1"
  printf 'voidstation-release namespaces="voidstation" %s %s\n' "$t" "$k"
}

all_signers() {            # <verzeichnis> – Zeilen aller gueltigen Schluessel (Herausgeber, Notfall), wie build.sh
  local p
  for p in "$1/$PUB" "$1/keys/voidstation-notfall.pub"; do
    if [ -s "$p" ]; then signers_line "$p"; fi
  done
}

verify_dist() {            # [verzeichnis] – prueft alle Signaturen in dist/ gegen keys/…pub
  local dir="${1:-.}" ok=0 f
  local signers; signers="$(mktemp)"; all_signers "$dir" > "$signers"
  for f in "$dir"/dist/update.sh "$dir"/dist/install.sh; do
    if ! ssh-keygen -Y verify -f "$signers" -I voidstation-release -n voidstation -s "$f.sig" < "$f" >/dev/null 2>&1; then
      ok=1; echo "  Signatur fehlt/ungueltig: ${f#"$dir"/}"
    fi
  done
  rm -f "$signers"
  return $ok
}

agent_start() {            # kurzlebiger ssh-agent fuer diesen Lauf (einmal)
  [ -n "$AGENT_PID" ] && return 0
  command -v ssh-agent >/dev/null 2>&1 || return 1
  eval "$(ssh-agent -s)" >/dev/null || return 1
  AGENT_PID="$SSH_AGENT_PID"
}

SIGNKEY=""
load_signkey() {           # Signaturschluessel einmal laden -> Passphrase nur einmal pro Lauf
  [ -n "$SIGNKEY" ] && return 0
  [ -e "$KEY" ] || die "Kein Signaturschluessel ($KEY) – einmalig:  vspub --init-key"
  if agent_start && ssh-add -q -t 1800 "$KEY"; then SIGNKEY="$KEY.pub"; else SIGNKEY="$KEY"; fi
}

build_sign() {             # <verzeichnis> – dist/ bauen und signieren (Signaturen bleiben, wenn unveraendert)
  local dir="$1" sigs f
  sigs="$(mktemp -d)"; TMPS+=("$sigs")
  cp "$dir"/dist/*.sig "$sigs/" 2>/dev/null || true       # build.sh leert dist/
  ( cd "$dir" && ./build.sh ) | sed -n '/^Version:/p'
  cp "$sigs"/*.sig "$dir/dist/" 2>/dev/null || true
  for f in "$dir"/dist/*.sig; do [ -e "${f%.sig}" ] || rm -f "$f"; done   # Signaturen weggefallener Dateien
  if verify_dist "$dir" >/dev/null 2>&1; then
    echo "Signaturen sind aktuell."
    return 0
  fi
  load_signkey
  for f in "$dir"/dist/update.sh "$dir"/dist/install.sh; do
    rm -f "$f.sig"
    ssh-keygen -q -Y sign -f "$SIGNKEY" -n voidstation "$f"
  done
  verify_dist "$dir" || die "Signaturpruefung nach dem Signieren fehlgeschlagen (passt $KEY zu $PUB?)"
  echo "signiert und geprueft"
}

catch_up() {               # Stand von GitHub nachziehen, z. B. direkt gepushte Doku-/Webseiten-Commits
  git rev-parse -q --verify origin/main >/dev/null || return 0
  git merge-base --is-ancestor origin/main HEAD && return 0                    # nichts Neues auf GitHub
  git diff --quiet && git diff --cached --quiet || die "Ungesicherte Aenderungen im Repo – erst committen oder verwerfen."
  if git merge-base --is-ancestor HEAD origin/main; then
    git merge -q --ff-only origin/main || die "GitHub-Stand liess sich nicht uebernehmen."
  elif ! git merge -q --no-edit -m "GitHub-Stand uebernommen" origin/main; then
    git merge --abort 2>/dev/null || true
    die "GitHub-Stand liess sich nicht zusammenfuehren (Konflikt) – nichts veraendert."
  fi
  echo "GitHub-Stand uebernommen:"
  git log --oneline --no-merges -n 5 "HEAD@{1}..HEAD" 2>/dev/null | sed 's/^/  /' || true
}

require_synced() {         # lokales main = GitHub, nichts Ungesichertes
  git fetch -q origin || die "GitHub nicht erreichbar."
  [ "$(git rev-parse --abbrev-ref HEAD)" = main ] || die "Bitte erst auf den Zweig main wechseln:  git checkout main"
  if git merge-base --is-ancestor HEAD origin/main; then catch_up; fi          # nur vorspulen, nie Eigenes verwerfen
  [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || die "Lokaler Stand weicht von GitHub ab – erst  vspub"
  git diff --quiet && git diff --cached --quiet || die "Ungesicherte Aenderungen im Repo – erst committen oder verwerfen."
  git rev-parse -q --verify origin/stable >/dev/null || die "Zweig stable fehlt auf GitHub."
  [ -s "$PUB" ] || die "Kein Signaturschluessel im Repo – erst  vspub --init-key"
}

show_file() { git show "$1:$2" 2>/dev/null; }                 # <rev> <datei>
top_of()    { show_file "$1" CHANGELOG.md > "$2" && "${CL[@]}" top "$2"; }   # <rev> <tmpdatei> -> "version datum"
fmt_date()  { date -d "@$1" +%d.%m.%Y; }
days_ago()  { echo $(( ($(date +%s) - $1) / 86400 )); }

# ---------------------------------------------------------------------
#  Was liegt in Testing? Erste-Eltern-Kette von main seit stable, nur Commits,
#  die etwas fuer die Geraete aendern (DEVICE_PATHS), ohne vspub-eigene
#  Freigabe-Commits (Zeile "VS-Release:"). Datum = wann der Commit auf main kam.
#  -> PEND_SHA / PEND_TS / PEND_TXT, neueste zuerst
# ---------------------------------------------------------------------
PEND_SHA=(); PEND_TS=(); PEND_TXT=()
collect_pending() {
  local c ts txt
  PEND_SHA=(); PEND_TS=(); PEND_TXT=()
  while read -r c ts; do
    [ -n "$c" ] || continue
    git rev-parse -q --verify "$c^1" >/dev/null || continue
    git diff --quiet "$c^1" "$c" -- "${DEVICE_PATHS[@]}" && continue
    case "$(git log -1 --format=%B "$c")" in *"VS-Release:"*) continue ;; esac
    if git rev-parse -q --verify "$c^2" >/dev/null; then       # Merge (Bundle, Pull Request): was kam herein?
      txt="$(git log --no-merges -n 3 --format=%s "$c^1..$c" | paste -sd '|' | sed 's/|/ · /g')"
    else
      txt="$(git log -1 --format=%s "$c")"
    fi
    PEND_SHA+=("$c"); PEND_TS+=("$ts"); PEND_TXT+=("${txt:0:90}")
  done < <(git log --first-parent --format='%H %ct' origin/stable..origin/main)
}

# Sperrfrist: beginnt am Montag (0 Uhr) der Woche, in der der Release-Zug faehrt, und dauert
# bis zum Zug. Was vorher nach Testing kam, faehrt mit; was in der Sperrfrist kommt, wartet
# auf den naechsten Zug. Tag des Zugs: Argument, sonst VS_TRAIN, sonst heute.
# -> TRAIN_DAY / FREEZE_DAY (JJJJ-MM-TT), FREEZE_TS, TRAIN_GIVEN (1 = Tag wurde angegeben)
TRAIN_DAY=""; FREEZE_DAY=""; FREEZE_TS=0; TRAIN_GIVEN=0
set_freeze() {             # [<JJJJ-MM-TT>]
  local d="${1:-$TRAIN}" wd
  TRAIN_GIVEN=1
  if [ -z "$d" ]; then d="$(date +%Y-%m-%d)"; TRAIN_GIVEN=0; fi
  if ! [[ "$d" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || [ "$(date -d "$d" +%Y-%m-%d 2>/dev/null)" != "$d" ]; then
    die "Tag des Release-Zugs nicht lesbar: $d  (erwartet JJJJ-MM-TT, z. B. 2026-12-04)"
  fi
  TRAIN_DAY="$d"
  wd="$(date -d "$d 12:00" +%u)"                                      # 1 = Montag
  FREEZE_DAY="$(date -d "$d 12:00 $(( wd - 1 )) days ago" +%Y-%m-%d)"
  FREEZE_TS="$(date -d "$FREEZE_DAY 00:00:00" +%s)"
}
fmt_day() { date -d "$1 12:00" +%d.%m.%Y; }                           # <JJJJ-MM-TT>

# Release-Zug: neuester Stand, in dem alles vor der Sperrfrist nach Testing kam -> RIPE
# (leer = nichts im Zug). Vorher set_freeze aufrufen.
RIPE=""; UNRIPE_IDX=-1
pick_ripe() {
  local i; RIPE=""; UNRIPE_IDX=-1
  [ ${#PEND_SHA[@]} -gt 0 ] || return 0
  for i in "${!PEND_SHA[@]}"; do
    if [ "${PEND_TS[i]}" -ge "$FREEZE_TS" ]; then UNRIPE_IDX=$i; fi
  done
  if [ "$UNRIPE_IDX" -lt 0 ]; then RIPE="$(git rev-parse origin/main)"
  elif [ "$UNRIPE_IDX" -lt $(( ${#PEND_SHA[@]} - 1 )) ]; then RIPE="$(git rev-parse "${PEND_SHA[UNRIPE_IDX]}^1")"
  fi
}

print_pending() {
  local i
  if [ ${#PEND_SHA[@]} -eq 0 ]; then echo "  (nichts – Testing enthaelt fuer die Geraete nichts Neues)"; return; fi
  for i in "${!PEND_SHA[@]}"; do
    if [ "$i" -le "$UNRIPE_IDX" ]; then
      printf '  wartet  %s  seit %s  %s\n' "${PEND_SHA[i]:0:7}" "$(fmt_date "${PEND_TS[i]}")" "${PEND_TXT[i]}"
    else
      printf '  im Zug  %s  seit %s  %s\n' "${PEND_SHA[i]:0:7}" "$(fmt_date "${PEND_TS[i]}")" "${PEND_TXT[i]}"
    fi
  done
}

# Freigabe-Commit zurueck nach main holen: main enthaelt alles, was in R steckt,
# ausser CHANGELOG (Testing -> Version) und dist/ – die werden neu zusammengesetzt.
merge_back() {             # <R> <version>
  local r="$1" ver="$2" f out
  if [ "$(git rev-parse HEAD)" = "$(git rev-parse "$r^1")" ]; then
    git merge -q --ff-only "$r"
    echo "main uebernimmt $ver direkt."
    return 0
  fi
  git merge -q -s ours --no-ff --no-commit "$r" >/dev/null 2>&1 || true
  git rev-parse -q --verify MERGE_HEAD >/dev/null || die "Zusammenfuehren mit main fehlgeschlagen."
  for f in CHANGELOG.md CHANGELOG.en.md; do
    out="$(mktemp)"; TMPS+=("$out")
    show_file "$r" "$f" > "$out.rel"; TMPS+=("$out.rel")
    "${CL[@]}" mergeback "$f" "$out.rel" > "$out" || die "CHANGELOG zusammenfuehren fehlgeschlagen ($f)."
    cat "$out" > "$f"
  done
  build_sign "$REPO"
  git add -A CHANGELOG.md CHANGELOG.en.md dist
  git commit -q -m "Version $ver nach main uebernommen" -m "VS-Release: $ver"
  echo "main: $ver uebernommen, noch nicht freigegebenes bleibt unter Testing."
}

push_release() {           # <R> <version>
  local r="$1" ver="$2"
  if ! git push -q --atomic origin "$r:refs/heads/stable" "HEAD:refs/heads/main"; then
    die "Push fehlgeschlagen – auf GitHub hat sich nichts geaendert. Lokal zuruecksetzen und nochmal:
    git reset -q --hard origin/main && vspub ${MODE:-}"
  fi
  mirror_push "$r:refs/heads/stable" HEAD:refs/heads/main
  echo "Freigegeben: VoidStation $ver ist jetzt fuer alle Geraete verfuegbar (Tag v$ver und GitHub-Release folgen automatisch)."
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
  local site_ok=1 why="" need_sign=1 a check stable_ver arch=x86_64
  command -v rsync >/dev/null || die "rsync fehlt – einmalig:  sudo xbps-install -S rsync"

  if [ -z "$iso" ]; then
    # ohne Angabe die neueste x86_64-ISO; 32-Bit-ISOs (…-i686-…) nur ausdruecklich:  vspub --iso <datei>
    iso="$(find "$ISO_DIR" -maxdepth 1 -name 'voidstation-*.iso' ! -name '*-i686-*' -printf '%T@ %p\n' 2>/dev/null \
           | sort -rn | head -n1 | cut -d' ' -f2- || true)"
    [ -n "$iso" ] || die "Keine ISO in $ISO_DIR – erst bauen:  sudo bash ~/VoidStation/dist/build-iso.sh"
  fi
  [ -f "$iso" ] || die "Datei nicht gefunden: $iso"
  dir="$(cd "$(dirname "$iso")" && pwd)"
  file="$(basename "$iso")"
  [[ "$file" =~ ^voidstation-([0-9][0-9A-Za-z.+]*)(-i686)?-([0-9]{8})\.iso$ ]] \
    || die "Unerwarteter Dateiname: $file  (erwartet: voidstation-<version>[-i686]-JJJJMMTT.iso)"
  ver="${BASH_REMATCH[1]}"; stamp="${BASH_REMATCH[3]}"
  [ -n "${BASH_REMATCH[2]}" ] && arch=i686
  case "$ver" in *+testing*) die "$file ist aus dem Testing-Stand gebaut – veroeffentlicht werden nur ISOs aus Stable (siehe RELEASING.md)" ;; esac
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
  # 32-Bit-ISO ist experimentell: kommt mit in den Versionsordner, die Webseite bleibt bei der x86_64-ISO
  if [ "$arch" = i686 ]; then
    site_ok=0; why="32-Bit-ISO (experimentell) – die Webseite bietet weiter die x86_64-ISO an"
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
  echo "  Version:   $ver vom $date ($arch)"
  echo "  Ziel:      $SF_HOST:$dest"
  if [ "$site_ok" = 1 ]; then echo "  Webseite:  voidstation.de bietet danach diese ISO an"
  else echo "  Webseite:  bleibt unveraendert ($why)"; fi
  echo "  Danach:    ISO, .sha256 und .sig werden hier geloescht"
  if [ -n "$stable_ver" ] && [ "$stable_ver" != "$ver" ]; then
    warn "Stable steht auf $stable_ver, die ISO enthaelt $ver – ISOs sollten den aktuellen Stable-Stand enthalten"
  fi
  echo
  read -r -p "Hochladen? [j/N] " a
  [ "$a" = j ] || [ "$a" = J ] || die "Abgebrochen – nichts hochgeladen, nichts geloescht."

  # Schluessel einmal in einen kurzlebigen ssh-agent laden -> jede Passphrase nur einmal
  ISO_SIGNERS="$(mktemp)"; TMPS+=("$ISO_SIGNERS"); all_signers "$REPO" > "$ISO_SIGNERS"
  if [ -s "$file.sha256.sig" ] && ssh-keygen -Y verify -f "$ISO_SIGNERS" -I voidstation-release -n voidstation \
       -s "$file.sha256.sig" < "$file.sha256" >/dev/null 2>&1; then
    need_sign=0
  fi
  agent_start || die "ssh-agent startet nicht."
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

  if [ "$arch" = i686 ]; then
    cat <<EOF

Veroeffentlicht: VoidStation $ver – 32-Bit-ISO (experimentell) auf SourceForge
  Link:  $url
NICHT als "Default Download" markieren – der bleibt die x86_64-ISO
(sonst zeigt .../files/latest/download auf die 32-Bit-Fassung).
Bis alle Mirrors die Datei haben, kann es etwas dauern.
EOF
    return
  fi
  cat <<EOF

Veroeffentlicht: VoidStation $ver – Live-ISO auf SourceForge
  Diese Version:  $url
  Immer aktuell:  https://sourceforge.net/projects/$SF_PROJECT/files/latest/download
Im Browser noch: Files -> $ver -> (i) neben der ISO -> "Default Download" (Linux + Windows)
Bis alle Mirrors die Datei haben, kann es etwas dauern.
EOF
}


# ---------------------------------------------------------------------
#  vspub --status
# ---------------------------------------------------------------------
do_status() {               # [<Tag des Zugs JJJJ-MM-TT>]
  local t sv sd mv
  set_freeze "${1:-}"
  git fetch -q origin || warn "GitHub nicht erreichbar – zeige den letzten bekannten Stand."
  t="$(mktemp)"; TMPS+=("$t")
  read -r sv sd < <(top_of origin/stable "$t") || die "CHANGELOG.md auf stable nicht lesbar."
  mv="$(show_file origin/main dist/version.json | python3 -c 'import json,sys;print(json.load(sys.stdin)["version"])' 2>/dev/null || echo "?")"
  echo "Stable:   $sv vom $sd  ($(git log -1 --format=%h origin/stable))"
  echo "Testing:  $mv  ($(git log -1 --format=%h origin/main))"
  collect_pending; pick_ripe
  echo
  if [ "$TRAIN_GIVEN" = 1 ]; then
    echo "Release-Zug am $(fmt_day "$TRAIN_DAY"): Sperrfrist ab Montag, $(fmt_day "$FREEZE_DAY")."
  else
    echo "Angenommen, der Release-Zug faehrt diese Woche: Sperrfrist ab Montag, $(fmt_day "$FREEZE_DAY")."
    echo "Anderer Termin:  vspub --status JJJJ-MM-TT"
  fi
  [ "$FREEZE_TS" -le "$(date +%s)" ] || echo "Die Sperrfrist hat noch nicht begonnen – was bis dahin nach Testing kommt, faehrt mit."
  echo
  echo "Seit Stable in Testing:"
  print_pending
  echo
  if [ ${#PEND_SHA[@]} -eq 0 ]; then
    echo "Nichts freizugeben."
  elif [ -n "$RIPE" ]; then
    echo "Im Zug:  Stand $(git log -1 --format=%h "$RIPE") als Version $("${CL[@]}" next --mode release --stable "$t" --month "${TRAIN_DAY:0:4}.${TRAIN_DAY:5:2}" 2>/dev/null || echo ?) – freigeben am Tag des Zugs mit  vspub --release"
  else
    echo "Nichts im Zug – alles kam erst in der Sperrfrist (ab $(fmt_day "$FREEZE_DAY")) nach Testing."
  fi
  echo "Hotfix (einzelne Fehlerbehebung sofort):  vspub --hotfix <commit>"
}

# ---------------------------------------------------------------------
#  vspub --release [<rev>]  – Release-Zug
#  Ohne <rev>: neuester Stand, in dem alles vor der Sperrfrist nach Testing kam
#  (Sperrfrist ab Montag dieser Woche; Zug an einem anderen Tag: VS_TRAIN=JJJJ-MM-TT).
#  Ablauf: Freigabe-Commit R = <stand> + CHANGELOG "Testing" -> "JJJJ.MM – heute"
#  + neu gebautes, signiertes dist/; R wird stable, main holt R zurueck.
# ---------------------------------------------------------------------
do_release() {
  local rev="${1:-}" x t sv sd ver i young=() r d f conf
  require_synced
  set_freeze
  t="$(mktemp)"; TMPS+=("$t")
  read -r sv sd < <(top_of origin/stable "$t") || die "CHANGELOG.md auf stable nicht lesbar."
  collect_pending; pick_ripe

  if [ -z "$rev" ]; then
    [ ${#PEND_SHA[@]} -gt 0 ] || die "Testing enthaelt seit $sv nichts Neues fuer die Geraete – nichts freizugeben."
    if [ -z "$RIPE" ]; then
      print_pending
      die "Nichts im Zug – alles kam erst in der Sperrfrist (ab $(fmt_day "$FREEZE_DAY")) nach Testing. Trotzdem alles freigeben:  vspub --release HEAD"
    fi
    x="$RIPE"
  else
    x="$(git rev-parse -q --verify "$rev^{commit}")" || die "Unbekannter Stand: $rev"
    git merge-base --is-ancestor "$x" origin/main || die "$rev ist nicht in main (Testing) – freigegeben wird nur, was getestet wurde."
    for i in "${!PEND_SHA[@]}"; do
      if git merge-base --is-ancestor "${PEND_SHA[i]}" "$x" && [ "${PEND_TS[i]}" -ge "$FREEZE_TS" ]; then
        young+=("  ${PEND_SHA[i]:0:7}  seit $(fmt_date "${PEND_TS[i]}") in Testing  ${PEND_TXT[i]}")
      fi
    done
  fi
  [ "$(top_of "$x" "$t" | cut -d' ' -f1)" = Testing ] \
    || die "In $(git log -1 --format=%h "$x") steht oben im CHANGELOG kein Abschnitt 'Testing' – nichts freizugeben."
  show_file origin/stable CHANGELOG.md > "$t"
  ver="$("${CL[@]}" next --mode release --stable "$t")" || die "Versionsnummer nicht bestimmbar."
  d="$(date +%Y-%m-%d)"

  say "Release-Zug $ver"
  echo "Stable bisher:  $sv vom $sd"
  echo "Neu:            $ver – Stand $(git log -1 --format='%h %s' "$x")"
  echo "Sperrfrist:     ab Montag, $(fmt_day "$FREEZE_DAY") (Zug am $(fmt_day "$TRAIN_DAY"); anderer Tag: VS_TRAIN=JJJJ-MM-TT)"
  [ "$x" = "$(git rev-parse origin/main)" ] || echo "Bleibt in Testing: alles nach $(git log -1 --format=%h "$x") (wartet auf den naechsten Zug)"
  echo
  echo "Aenderungen ($(show_file "$x" CHANGELOG.md | sed -n '/^## Testing/,/^## /p' | grep -c '^- ') Eintraege):"
  show_file "$x" CHANGELOG.md | sed -n '/^## Testing/,/^## /{/^- /p}' | cut -c1-110 | sed 's/^/  /'
  if [ ${#young[@]} -gt 0 ]; then
    echo
    warn "Erst in der Sperrfrist (ab $(fmt_day "$FREEZE_DAY")) nach Testing gekommen:"
    printf '%s\n' "${young[@]}"
  fi
  echo
  echo "Vorher abgehakt? Update vom letzten Stable auf beiden Geraeten, Neustart, Startseite, YouTube,"
  echo "Einstellungen -> Updates (und der Installer, falls er sich geaendert hat) – siehe RELEASING.md"
  ask "Als $ver freigeben?" || die "Abgebrochen – nichts veraendert."

  say "Freigabe-Commit bauen"
  WT="$(mktemp -d)"; TMPS+=("$WT"); WT="$WT/release"
  git worktree add -q --detach "$WT" "$x"
  if ! git merge-base --is-ancestor origin/stable "$x"; then
    # Seit diesem Stand gab es einen Hotfix: Stable mit hineinnehmen (dessen Code liegt
    # schon in main); bereits freigegebene Eintraege fallen aus "Testing" heraus.
    echo "Stable enthaelt einen Hotfix, der nach diesem Stand kam – wird mitgenommen."
    git -C "$WT" merge -q --no-ff --no-commit origin/stable >/dev/null 2>&1 || true
    git -C "$WT" rev-parse -q --verify MERGE_HEAD >/dev/null || die "Zusammenfuehren mit Stable fehlgeschlagen."
    git -C "$WT" checkout -q --ours -- CHANGELOG.md CHANGELOG.en.md 2>/dev/null \
      || git -C "$WT" checkout -q "$x" -- CHANGELOG.md CHANGELOG.en.md
    conf="$(git -C "$WT" diff --name-only --diff-filter=U | grep -v -e '^CHANGELOG' -e '^dist/' || true)"
    [ -z "$conf" ] || die "Stand $(git log -1 --format=%h "$x") und Stable passen nicht zusammen ($(echo $conf)) – einen neueren Stand waehlen (vspub --status)."
    for f in CHANGELOG.md CHANGELOG.en.md; do
      show_file "$x" "$f" > "$t.x"; show_file origin/stable "$f" > "$t.s"; TMPS+=("$t.x" "$t.s")
      "${CL[@]}" mergeback "$t.x" "$t.s" > "$WT/$f" || die "CHANGELOG zusammenfuehren fehlgeschlagen ($f)."
    done
    git -C "$WT" checkout -q "$x" -- dist 2>/dev/null || true
    git -C "$WT" add -A CHANGELOG.md CHANGELOG.en.md dist
  fi
  "${CL[@]}" stamp "$WT/CHANGELOG.md" "$ver" "$d"
  "${CL[@]}" stamp "$WT/CHANGELOG.en.md" "$ver" "$d"
  build_sign "$WT"
  git -C "$WT" add -A CHANGELOG.md CHANGELOG.en.md dist
  git -C "$WT" commit -q -m "Version $ver" -m "VS-Release: $ver"
  r="$(git -C "$WT" rev-parse HEAD)"

  say "main nachziehen"
  merge_back "$r" "$ver"

  say "Veroeffentlichen"
  push_release "$r" "$ver"
  echo "ISO dazu (Maerz, Juni, September, Dezember): siehe RELEASING.md – gebaut wird aus stable."
}

# ---------------------------------------------------------------------
#  vspub --hotfix <rev> [<rev> …]  – einzelne Fehlerbehebungen aus Testing sofort auf Stable
#  Die Commits muessen in main liegen und je einen neuen Eintrag unter "Testing" haben
#  (de + en). Ergebnis: Stable + diese Commits als Version JJJJ.MM.N.
# ---------------------------------------------------------------------
do_hotfix() {
  [ $# -gt 0 ] || die "Welche Commits?  vspub --hotfix <commit> [<commit> …]   (Kennung aus  git log  oder  vspub --status)"
  local t sv sd ver d c x m1 f now ts i landed e_de e_en conf picks=() young=()
  require_synced
  t="$(mktemp)"; TMPS+=("$t")
  read -r sv sd < <(top_of origin/stable "$t") || die "CHANGELOG.md auf stable nicht lesbar."
  collect_pending
  e_de="$(mktemp)"; e_en="$(mktemp)"; TMPS+=("$e_de" "$e_en")
  now="$(date +%s)"
  for c in "$@"; do
    x="$(git rev-parse -q --verify "$c^{commit}")" || die "Unbekannter Commit: $c"
    git merge-base --is-ancestor "$x" origin/main || die "$c ist nicht in main (Testing) – erst  vspub, dann testen."
    ! git merge-base --is-ancestor "$x" origin/stable || die "$c ist schon in Stable."
    # wann kam er auf main? (aeltester Erste-Eltern-Commit, der ihn enthaelt)
    landed=""
    for i in "${!PEND_SHA[@]}"; do
      if git merge-base --is-ancestor "$x" "${PEND_SHA[i]}"; then landed="${PEND_TS[i]}"; fi
    done
    ts="${landed:-$(git log -1 --format=%ct "$x")}"
    if [ $(( now - ts )) -lt $(( HOTFIX_DAYS * 86400 )) ]; then young+=("  ${x:0:7}  erst $(days_ago "$ts") Tage in Testing"); fi
    # neue Changelog-Eintraege dieses Commits (bei Merges: alles, was der Merge hereinholt)
    for f in CHANGELOG.md CHANGELOG.en.md; do
      show_file "$x^1" "$f" > "$t.old"; show_file "$x" "$f" > "$t.new"; TMPS+=("$t.old" "$t.new")
      if [ "$f" = CHANGELOG.md ]; then "${CL[@]}" added "$t.old" "$t.new" >> "$e_de"
      else "${CL[@]}" added "$t.old" "$t.new" >> "$e_en"; fi
    done
    picks+=("$x")
  done
  [ -s "$e_de" ] && [ -s "$e_en" ] \
    || die "Keine neuen Eintraege unter 'Testing' in CHANGELOG.md und CHANGELOG.en.md – ohne Changelog kein Hotfix."
  show_file origin/stable CHANGELOG.md > "$t"
  ver="$("${CL[@]}" next --mode hotfix --stable "$t")" || die "Versionsnummer nicht bestimmbar."
  d="$(date +%Y-%m-%d)"

  say "Hotfix $ver"
  echo "Stable bisher:  $sv vom $sd"
  echo "Dazu kommt:"
  for x in "${picks[@]}"; do echo "  $(git log -1 --format='%h %s' "$x")"; done
  echo "Changelog:"
  cut -c1-110 "$e_de" | sed 's/^/  /'
  if [ ${#young[@]} -gt 0 ]; then
    warn "Kuerzer als $HOTFIX_DAYS Tage in Testing:"; printf '%s\n' "${young[@]}"
  fi
  ask "Als $ver freigeben?" || die "Abgebrochen – nichts veraendert."

  say "Hotfix auf Stable anwenden"
  WT="$(mktemp -d)"; TMPS+=("$WT"); WT="$WT/hotfix"
  git worktree add -q --detach "$WT" origin/stable
  for x in "${picks[@]}"; do
    m1=(); if git rev-parse -q --verify "$x^2" >/dev/null; then m1=(-m 1); fi
    git -C "$WT" cherry-pick -n "${m1[@]}" "$x" >/dev/null 2>&1 || true
    # CHANGELOG und dist/ bleiben auf dem Stable-Stand (werden unten neu gesetzt)
    git -C "$WT" reset -q -- CHANGELOG.md CHANGELOG.en.md dist 2>/dev/null
    git -C "$WT" checkout -- CHANGELOG.md CHANGELOG.en.md dist
    git -C "$WT" clean -fdq -- dist
    conf="$(git -C "$WT" diff --name-only --diff-filter=U)"
    [ -z "$conf" ] || die "$(git log -1 --format=%h "$x") passt nicht sauber auf Stable ($(echo $conf)) – nichts veraendert.
    Bitte eine Fassung des Fixes fuer den Stable-Stand anfordern (Backport)."
  done
  git -C "$WT" diff --cached --quiet && die "Die Commits aendern am Stable-Stand nichts – nichts freizugeben."
  "${CL[@]}" insert "$WT/CHANGELOG.md" "$ver" "$d" "$e_de"
  "${CL[@]}" insert "$WT/CHANGELOG.en.md" "$ver" "$d" "$e_en"
  build_sign "$WT"
  git -C "$WT" add -A
  git -C "$WT" commit -q -m "Hotfix $ver" -m "Aus Testing: $(for x in "${picks[@]}"; do printf '%s ' "${x:0:7}"; done)" -m "VS-Release: $ver"
  r="$(git -C "$WT" rev-parse HEAD)"

  say "main nachziehen"
  merge_back "$r" "$ver"

  say "Veroeffentlichen"
  push_release "$r" "$ver"
}

MODE="${1:-}"
case "$MODE" in
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

--status)   do_status "${2:-}"; exit 0 ;;
--release)  do_release "${2:-}"; exit 0 ;;
--hotfix)   shift; do_hotfix "$@"; exit 0 ;;

# ---------------------------------------------------------------------
--iso)
  [ -s "$PUB" ] || die "Kein Signaturschluessel im Repo – erst  vspub --init-key"
  iso_publish "${2:-}"
  exit 0 ;;

# ---------------------------------------------------------------------
"")
  ;;
*)
  die "Unbekannte Option: $1  (erlaubt: --status [tag], --release [stand], --hotfix <commit>…, --iso [datei], --init-key)" ;;
esac

# ---- Normaler Lauf: Bundle einspielen, bauen, signieren, nach Testing
[ -e "$KEY" ] || die "Kein Signaturschluessel ($KEY) – einmalig:  vspub --init-key"
mkdir -p "$INBOX/erledigt"
git fetch -q origin || true
[ "$(git rev-parse --abbrev-ref HEAD)" = main ] || die "Bitte erst auf den Zweig main wechseln:  git checkout main"
catch_up

b="$(ls -t "$INBOX"/*.bundle 2>/dev/null | head -n1 || true)"
if [ -n "$b" ]; then
  say "Bundle: $(basename "$b")"
  git bundle verify -q "$b" >/dev/null 2>&1 || die "Bundle passt nicht zu diesem Repo (fehlende Vorgaenger-Commits)."
  git bundle list-heads "$b" | grep -q ' refs/heads/main$' || die "Bundle enthaelt keinen Zweig main (gebaut mit HEAD statt main?) – neu bauen mit  tools/mkbundle.sh"
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

say "Bauen und signieren"
mkdir -p keys
if ! cmp -s "$KEY.pub" "$PUB" 2>/dev/null; then cp "$KEY.pub" "$PUB"; echo "oeffentlicher Schluessel ins Repo uebernommen"; fi
build_sign "$REPO"

git add -A dist keys
if git diff --cached --quiet; then
  echo "Keine Aenderungen an dist/."
else
  ver="$(python3 -c 'import json;d=json.load(open("dist/version.json"));print(d["version"], "(Build " + d["build"] + ")")')"
  git commit -q -m "[build] $ver signiert"
fi

say "Veroeffentlichen (Kanal Testing)"
git push -q origin HEAD:main
mirror_push HEAD:main

ver="$(python3 -c 'import json;print(json.load(open("dist/version.json"))["version"])')"
cat <<EOF

Veroeffentlicht: $ver im Kanal Testing (main).
Testen:    Geraet auf Kanal "Testing" -> Einstellungen -> Updates
Stand:     vspub --status    (was faehrt mit dem naechsten Release-Zug?)
EOF
