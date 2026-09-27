# VoidStation Live-Stick: Hinweis beim Anmelden
if [ "$(id -u)" = 0 ] && [ -z "${VOIDSTATION_HINT:-}" ]; then
  export VOIDSTATION_HINT=1
  _ip=$(ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | paste -sd' ')
  printf '\n\033[1;36m  ===  VoidStation Installer  ===\033[0m\n\n'
  printf '  Installation starten:   \033[1mvoidstation-install\033[0m\n'
  printf '  WLAN verbinden:         nmtui\n'
  printf '  Per PuTTY:              root@%s   Passwort: voidlinux\n\n' "${_ip:-(noch keine IP – LAN stecken oder nmtui)}"
  unset _ip
fi
