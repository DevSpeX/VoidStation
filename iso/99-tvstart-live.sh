# TV-Start Live-Stick: Netzwerk ueber NetworkManager (auch WLAN per nmtui),
# SSH-Zugang als root mit Passwort "voidlinux" (nur im Live-System!)
_d=/etc/runit/runsvdir/default
for _s in dbus NetworkManager sshd; do
  [ -d "/etc/sv/$_s" ] && [ ! -e "$_d/$_s" ] && ln -s "/etc/sv/$_s" "$_d/"
done
rm -f "$_d/dhcpcd" "$_d"/dhcpcd-* "$_d/wpa_supplicant"
grep -q '^PermitRootLogin yes' /etc/ssh/sshd_config 2>/dev/null || sed -i '1i PermitRootLogin yes' /etc/ssh/sshd_config
echo 'root:voidlinux' | chpasswd 2>/dev/null
unset _d _s
