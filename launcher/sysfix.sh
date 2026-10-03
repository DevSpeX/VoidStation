#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# =====================================================================
#  VoidStation: Systemkorrekturen – als root, beliebig oft ausfuehrbar.
#  Aufgerufen von install.sh (auch im chroot des Installers / beim ISO-Bau) und update.sh.
#
#   1. elogind: eigener Dienst voidstation-elogind statt /etc/sv/elogind. Startet D-Bus elogind
#      beim Hochfahren schon selbst (NetworkManager, automatische Anmeldung), lief /etc/sv/elogind
#      in eine Schleife ("elogind is already running", jede Sekunde, sichtbar auf der Konsole).
#      Umgestellt wird beim naechsten Start (core-service), damit kein laufender Dienst stoppt.
#   2. WLAN: Funkregeln des Landes (sonst Kanaele 12/13 und viele 5-GHz-Kanaele nur passiv),
#      USB-Sticks: keine Zufalls-MAC beim Suchen, kein Stromsparmodus.
#   3. GRUB-Start ohne Meldungsflut (quiet), wie beim EFISTUB-Start.
# =====================================================================
CHROOT="${VOIDSTATION_CHROOT:-0}"
say() { printf '%s\n' "$*"; }

# ---------------------------------------------------------------------
# 1. elogind
mkdir -p /etc/sv/voidstation-elogind /etc/runit/core-services
cat > /etc/sv/voidstation-elogind/run <<'EOF'
#!/bin/sh
# VoidStation: elogind wie /etc/sv/elogind, aber ohne Doppelstart. Hat D-Bus elogind beim
# Hochfahren schon selbst gestartet, wird diese Kopie nur ueberwacht; endet sie, startet runit
# elogind wieder regulaer (ueber den Wrapper des Pakets).
exec 2>&1
sv check dbus >/dev/null || exit 1
pid="$(pgrep -xo 'elogind|elogind-daemon')"
if [ -n "$pid" ]; then
  echo "elogind laeuft schon (PID $pid) – ueberwache nur"
  while kill -0 "$pid" 2>/dev/null; do sleep 15; done
  exit 0
fi
exec /usr/libexec/elogind/elogind.wrapper
EOF
chmod 755 /etc/sv/voidstation-elogind/run
cat > /etc/runit/core-services/91-voidstation-elogind.sh <<'EOF'
# SPDX-License-Identifier: GPL-3.0-or-later
# VoidStation (runit core-service): elogind ueber /etc/sv/voidstation-elogind statt /etc/sv/elogind
# (dort Neustart-Schleife, wenn D-Bus elogind schon gestartet hat). Laeuft vor allen Diensten.
if [ -x /etc/sv/voidstation-elogind/run ] && [ -d /etc/runit/runsvdir/default ]; then
  rm -f /etc/runit/runsvdir/default/elogind
  [ -e /etc/runit/runsvdir/default/voidstation-elogind ] || ln -s /etc/sv/voidstation-elogind /etc/runit/runsvdir/default/
fi
EOF
chmod 644 /etc/runit/core-services/91-voidstation-elogind.sh
say "elogind: voidstation-elogind (aktiv ab dem naechsten Start)"

# ---------------------------------------------------------------------
# 2. WLAN
mkdir -p /etc/NetworkManager/conf.d /etc/modprobe.d
cat > /etc/NetworkManager/conf.d/90-voidstation-wifi.conf <<'EOF'
# VoidStation: WLAN robuster, vor allem mit USB-Sticks
[device]
# viele Sticks (Realtek u. a.) verbinden nicht, wenn beim Suchen eine Zufalls-MAC benutzt wird
wifi.scan-rand-mac-address=no

[connection]
# Stromsparen fuehrt bei USB-Sticks zu Zeitueberschreitungen und Abbruechen (2 = aus)
wifi.powersave=2
EOF
# Land fuer die Funkregeln: aus der Zeitzone, sonst aus der Sprache, sonst Deutschland
cc=""
tz="$(readlink /etc/localtime 2>/dev/null | sed 's|.*zoneinfo/||')"
if [ -n "$tz" ] && [ -r /usr/share/zoneinfo/zone.tab ]; then
  cc="$(awk -v z="$tz" '$3 == z { print $1; exit }' /usr/share/zoneinfo/zone.tab)"
fi
if [ -z "$cc" ] && [ -r /etc/locale.conf ]; then
  cc="$(sed -n 's/^LANG=[a-z]*_\([A-Z][A-Z]\).*/\1/p' /etc/locale.conf | head -1)"
fi
[ -n "$cc" ] || cc=DE
printf '# VoidStation: Funkregeln fuer WLAN (Land %s, aus Zeitzone/Sprache)\noptions cfg80211 ieee80211_regdom=%s\n' "$cc" "$cc" \
  > /etc/modprobe.d/voidstation-wlan.conf
if [ "$CHROOT" != 1 ] && command -v iw >/dev/null 2>&1; then
  iw reg set "$cc" 2>/dev/null || true
fi
[ -f /usr/lib/firmware/regulatory.db ] || say "Hinweis: wireless-regdb fehlt (Funkregeln wirken erst damit)"
say "WLAN: Funkregeln $cc, ohne Zufalls-MAC und Stromsparen"

# ---------------------------------------------------------------------
# 3. GRUB: still starten (Void-Standard ist "loglevel=4" ohne quiet)
if [ -f /etc/default/grub ] && ! grep -q '^GRUB_CMDLINE_LINUX_DEFAULT=.*quiet' /etc/default/grub; then
  if grep -q '^GRUB_CMDLINE_LINUX_DEFAULT="' /etc/default/grub; then
    sed -i -e '/^GRUB_CMDLINE_LINUX_DEFAULT="/s/loglevel=[0-9]*/loglevel=3/' \
           -e '/^GRUB_CMDLINE_LINUX_DEFAULT="/s/"$/ quiet"/' /etc/default/grub
  else
    echo 'GRUB_CMDLINE_LINUX_DEFAULT="loglevel=3 quiet"' >> /etc/default/grub
  fi
  grep -q '^GRUB_CMDLINE_LINUX_DEFAULT=.*loglevel=' /etc/default/grub \
    || sed -i '/^GRUB_CMDLINE_LINUX_DEFAULT="/s/ quiet"$/ loglevel=3 quiet"/' /etc/default/grub
  say "GRUB: $(grep '^GRUB_CMDLINE_LINUX_DEFAULT=' /etc/default/grub)"
  if [ "$CHROOT" != 1 ] && [ -f /boot/grub/grub.cfg ]; then
    update-grub >/dev/null 2>&1 || grub-mkconfig -o /boot/grub/grub.cfg >/dev/null 2>&1 || say "GRUB-Menue nicht erneuert"
  fi
fi
exit 0
