# SPDX-License-Identifier: GPL-3.0-or-later
# VoidStation Live-System (runit core-service, laeuft beim Start als root)
# Tastatur der grafischen Oberflaeche passend zum Eintrag im Startmenue (vconsole.keymap=de|us|uk)
_km=$(sed -n 's/.*vconsole\.keymap=\([^ ]*\).*/\1/p' /proc/cmdline)
case "$_km" in us*) _xk=us ;; uk*|gb*) _xk=gb ;; *) _xk=de ;; esac
mkdir -p /etc/X11/xorg.conf.d
printf 'Section "InputClass"\n  Identifier "system-keyboard"\n  MatchIsKeyboard "on"\n  Option "XkbLayout" "%s"\nEndSection\n' "$_xk" \
  > /etc/X11/xorg.conf.d/00-keyboard.conf
# Netzwerk nur ueber NetworkManager (auch WLAN aus der Oberflaeche)
_d=/etc/runit/runsvdir/default
rm -f "$_d/dhcpcd" "$_d"/dhcpcd-* "$_d/wpa_supplicant"
[ -e "$_d/NetworkManager" ] || ln -s /etc/sv/NetworkManager "$_d/"
echo voidstation-live > /etc/hostname
unset _km _xk _d
