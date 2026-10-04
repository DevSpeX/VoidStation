VoidStation – live system with installer
========================================

Booting
  Plug in the stick and pick it in the PC's boot menu (usually F12, F11 or Esc) –
  preferably the entry starting with "UEFI:". Secure Boot must be off.
  Older PCs and virtual machines without UEFI boot in BIOS mode (Legacy) – that
  works too, but then VoidStation can only be installed on a whole SSD.

Boot menu
  First pick the language (Deutsch / English), then one of the two entries below it:
  Start VoidStation Live                 live system (nothing gets installed), open graphics drivers
  Start VoidStation Live (NVIDIA only)   with the NVIDIA driver – for GeForce GTX 16xx, RTX 20xx and newer
  Reboot                                 restart
  The language applies to the interface, the installer and the keyboard (English: US layout); change
  it in the live system under Settings and for the installed system in the installer. Esc goes back.
  With an NVIDIA card, boot "NVIDIA only" and install from there – the installed system then
  gets the NVIDIA driver too. If the interface doesn't come up that way, use the first entry.

Installing
  Tile "Install VoidStation" – or in a terminal: sudo voidstation-installer text
  Minimum: 64-bit PC, 4 GB RAM, 16 GB on the SSD. UEFI or BIOS (Legacy).
  Ways: whole SSD, next to Windows/Linux (shrink), into free space, manual (GParted).
  In BIOS mode only "whole SSD" is available; the SSD then boots in both modes.

Log
  /run/voidstation-installer/install.log (live system),
  /var/log/voidstation-install.log (installed system)

Project: https://github.com/Panther92/VoidStation
