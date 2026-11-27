#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# (wird nur eingelesen, nicht ausgefuehrt – die erste Zeile ist fuer shellcheck)
# VoidStation: Komfort im Terminal – liegt als /etc/bash/bashrc.d/voidstation.sh und gilt fuer jede
# interaktive bash (Terminal-Kachel, SSH, sudo -i). Eigene Einstellungen in ~/.bashrc werden danach gelesen
# und gehen vor (eigenes PS1, eigene Aliase, eigene bind-Zeilen).
# Tab-Vervollstaendigung kommt aus dem Paket bash-completion (eigene Datei in /etc/bash/bashrc.d).

[ -n "${BASH_VERSION:-}" ] || return 0
case $- in *i*) ;; *) return 0 ;; esac
[ -z "${__VS_BASHRC:-}" ] || return 0              # nur einmal je Shell (Login-Shells lesen bashrc ueber profile.d)
__VS_BASHRC=1

# --- Verlauf: gross, ohne Doppelte, sofort gespeichert; mehrere Terminals ueberschreiben sich nicht
HISTSIZE=10000
HISTFILESIZE=20000
HISTCONTROL=ignoreboth:erasedups
HISTIGNORE='ls:ll:la:cd:pwd:exit:clear:history'
shopt -s histappend checkwinsize cmdhist

# --- Eingabe: ↑/↓ suchen im Verlauf nach dem schon Getippten (leere Zeile: wie bisher Zeile fuer Zeile),
#     Tab zeigt bei mehreren Treffern gleich die Liste, Gross-/Kleinschreibung egal, Treffer farbig
bind '"\e[A": history-search-backward' 2>/dev/null
bind '"\e[B": history-search-forward' 2>/dev/null
bind '"\eOA": history-search-backward' 2>/dev/null
bind '"\eOB": history-search-forward' 2>/dev/null
bind 'set show-all-if-ambiguous on' 2>/dev/null
bind 'set completion-ignore-case on' 2>/dev/null
bind 'set colored-stats on' 2>/dev/null
bind 'set colored-completion-prefix on' 2>/dev/null
bind 'set mark-symlinked-directories on' 2>/dev/null

# --- Farben und Kuerzel
alias ls='ls --color=auto'
alias ll='ls -lh --group-directories-first'
alias la='ls -lAh --group-directories-first'
alias grep='grep --color=auto'
alias diff='diff --color=auto'
alias ip='ip -color=auto'
alias ..='cd ..'
alias ...='cd ../..'

# --- Eingabeaufforderung: benutzer@rechner in Cyan (im VoidStation-Terminal Petrol), als root in Rot,
#     Ordner in Blau; nach einem Fehler steht der Rueckgabewert rot davor, z. B. "paul@Wohnzimmer ~ 127 $".
#     Wer in ~/.bashrc ein eigenes PS1 setzt, behaelt es: neu gebaut wird nur, solange PS1 noch von hier stammt.
__vs_ps1() {
  local who='\[\e[1;36m\]' err=''
  [ "$EUID" = 0 ] && who='\[\e[1;31m\]'
  [ "${1:-0}" != 0 ] && err="\[\e[31m\]$1\[\e[0m\] "
  __VS_PS1="${who}\u@\h\[\e[0m\] \[\e[1;34m\]\w\[\e[0m\] ${err}\\\$ "
  PS1="$__VS_PS1"
}
__vs_prompt() {
  local rc=$?
  history -a
  [ "$PS1" = "${__VS_PS1:-}" ] && __vs_ps1 "$rc"
  return "$rc"
}
__vs_ps1 0
case ";${PROMPT_COMMAND:-};" in
  *";__vs_prompt;"*) ;;
  *) PROMPT_COMMAND="__vs_prompt${PROMPT_COMMAND:+;$PROMPT_COMMAND}" ;;
esac

# --- vsctl: Befehle, Kachel-IDs und Konten vervollstaendigen
_vsctl() {
  local cur=${COMP_WORDS[COMP_CWORD]} ids accounts_db accts
  COMPREPLY=()
  if [ "$COMP_CWORD" = 1 ]; then
    mapfile -t COMPREPLY < <(compgen -W "home launch status update version channel report account help" -- "$cur")
  elif [ "$COMP_CWORD" = 2 ] && [ "${COMP_WORDS[1]}" = channel ]; then
    mapfile -t COMPREPLY < <(compgen -W "stable testing" -- "$cur")
  elif [ "$COMP_CWORD" = 2 ] && [ "${COMP_WORDS[1]}" = report ]; then
    mapfile -t COMPREPLY < <(compgen -W "--print" -- "$cur")
  elif [ "$COMP_CWORD" = 2 ] && [ "${COMP_WORDS[1]}" = launch ]; then
    ids="$(sed -n 's/^ *"id": *"\([^"]*\)".*/\1/p' "$HOME/.local/share/voidstation/tiles.json" 2>/dev/null)"
    mapfile -t COMPREPLY < <(compgen -W "$ids" -- "$cur")
  elif [ "${COMP_WORDS[1]}" = account ]; then
    if [ "$COMP_CWORD" = 2 ]; then
      mapfile -t COMPREPLY < <(compgen -W "status list switch lock unlock reset-pin help" -- "$cur")
    else
      accounts_db="$HOME/.local/share/voidstation/accounts/accounts.db"
      accts=""
      if [ -r "$accounts_db" ] && command -v python3 >/dev/null 2>&1; then
        accts="$(python3 - "$accounts_db" <<'PYEOF' 2>/dev/null
import sqlite3, sys
from pathlib import Path
uri = Path(sys.argv[1]).resolve().as_uri() + "?mode=ro"
con = sqlite3.connect(uri, uri=True, timeout=0.5)
for row in con.execute("SELECT id, display_name FROM accounts WHERE active = 1"):
    for val in row:
        if val:
            print(val)
con.close()
PYEOF
)"
      fi
      case "${COMP_WORDS[2]}" in
        status|list|lock)
          mapfile -t COMPREPLY < <(compgen -W "--json" -- "$cur")
          ;;
        switch)
          if [[ "$cur" == -* ]]; then
            mapfile -t COMPREPLY < <(compgen -W "--guest --password --json" -- "$cur")
          elif [ "$COMP_CWORD" = 3 ]; then
            mapfile -t COMPREPLY < <(compgen -W "$accts --guest" -- "$cur")
          else
            mapfile -t COMPREPLY < <(compgen -W "--password --guest --json" -- "$cur")
          fi
          ;;
        unlock)
          if [[ "$cur" == -* ]]; then
            mapfile -t COMPREPLY < <(compgen -W "--json" -- "$cur")
          elif [ "$COMP_CWORD" = 3 ]; then
            mapfile -t COMPREPLY < <(compgen -W "$accts" -- "$cur")
          else
            mapfile -t COMPREPLY < <(compgen -W "--json" -- "$cur")
          fi
          ;;
        reset-pin)
          if [[ "$cur" == -* ]]; then
            mapfile -t COMPREPLY < <(compgen -W "--remove --json" -- "$cur")
          elif [ "$COMP_CWORD" = 3 ]; then
            mapfile -t COMPREPLY < <(compgen -W "$accts" -- "$cur")
          else
            mapfile -t COMPREPLY < <(compgen -W "--remove --json" -- "$cur")
          fi
          ;;
      esac
    fi
  fi
}
complete -F _vsctl vsctl
