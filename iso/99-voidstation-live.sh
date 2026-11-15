# SPDX-License-Identifier: GPL-3.0-or-later
# VoidStation Live-System (runit core-service, laeuft beim Start als root)
# Tastatur der grafischen Oberflaeche passend zur Sprache im Startmenue (voidstation.kb=de|us|fr|…, siehe
# iso/grub-entries.py; aeltere Sticks: vconsole.keymap=de|us|uk). Griechisch, Russisch und Ukrainisch bekommen
# zusaetzlich US (Anmeldename, Rechnername), Alt+Umschalt wechselt. Der Installer kann sie danach umstellen.
_kb=$(sed -n 's/.*voidstation\.kb=\([^ ]*\).*/\1/p' /proc/cmdline)
if [ -z "$_kb" ]; then
  _km=$(sed -n 's/.*vconsole\.keymap=\([^ ]*\).*/\1/p' /proc/cmdline)
  case "$_km" in us*) _kb=us ;; uk*|gb*) _kb=gb ;; *) _kb=de ;; esac
fi
_xo=""
case "$_kb" in
  gr|ru|ua|th) _xk="us,$_kb"; _xo="grp:alt_shift_toggle" ;;
  de|us|gb|fr|es|it|lv|hu|pl|br|cz|sk|jp|ro|tr|dk|se|no|fi|is|ee) _xk="$_kb" ;;
  *) _xk=de ;;
esac
mkdir -p /etc/X11/xorg.conf.d
{
  printf 'Section "InputClass"\n  Identifier "system-keyboard"\n  MatchIsKeyboard "on"\n  Option "XkbLayout" "%s"\n' "$_xk"
  if [ -n "$_xo" ]; then printf '  Option "XkbOptions" "%s"\n' "$_xo"; fi
  printf 'EndSection\n'
} > /etc/X11/xorg.conf.d/00-keyboard.conf
# Netzwerk nur ueber NetworkManager (auch WLAN aus der Oberflaeche)
_d=/etc/runit/runsvdir/default
rm -f "$_d/dhcpcd" "$_d"/dhcpcd-* "$_d/wpa_supplicant"
[ -e "$_d/NetworkManager" ] || ln -s /etc/sv/NetworkManager "$_d/"
echo voidstation-live > /etc/hostname
# Begruessung der Textkonsole statt des Void-Textes (void-mklive legt ihn beim Bau ab), in der Sprache des Startmenues
[ -x /usr/local/sbin/voidstation-issue ] && /usr/local/sbin/voidstation-issue --live
# Startbild (Plymouth) beenden, bevor X startet – sonst haelt es den Bildschirm fest.
# --retain-splash: das Logo bleibt stehen, bis die Oberflaeche uebernimmt.
if command -v plymouth >/dev/null 2>&1 && plymouth --ping 2>/dev/null; then
  plymouth quit --retain-splash
fi
# Eintrag "NVIDIA only": nouveau ist per Befehlszeile gesperrt, hier kommt der NVIDIA-Treiber mit
# Kernel-Modesetting dazu (Optionen in /etc/modprobe.d/voidstation-nvidia.conf). Ohne passende Karte
# (vor GTX 16xx / RTX 20xx) schlaegt das fehl – dann laeuft die Oberflaeche ohne Beschleunigung weiter.
if grep -qw 'voidstation.gpu=nvidia' /proc/cmdline; then
  modprobe nvidia_drm 2>/dev/null || echo "VoidStation: NVIDIA-Treiber nicht geladen (keine unterstuetzte NVIDIA-Karte?)"
else
  # Normaler Eintrag: modprobe.blacklist sperrt nur das automatische Laden. nvidia-modprobe (aus den
  # NVIDIA-Bibliotheken, sobald ein Programm GPU-Beschleunigung anfragt) laedt sonst trotzdem nach.
  mkdir -p /run/modprobe.d
  printf 'install %s /bin/false\n' nvidia nvidia_drm nvidia_modeset nvidia_uvm > /run/modprobe.d/voidstation-no-nvidia.conf
fi
unset _km _kb _xk _xo _d
