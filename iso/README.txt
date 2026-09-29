VoidStation – live system with installer
========================================

Booting
  Plug in the stick and pick the entry starting with "UEFI:" in the PC's boot
  menu (usually F12, F11 or Esc). UEFI must be on (CSM/Legacy off), Secure Boot off.

Boot menu
  VoidStation (English)               live system in English (nothing gets installed)
  Install VoidStation (English)       starts right away with the installer
  The entries without "(English)" are German.

Installing
  Tile "Install VoidStation" – or in a terminal: sudo voidstation-installer text
  Minimum: 64-bit PC, UEFI, 4 GB RAM, 16 GB on the SSD.
  Ways: whole SSD, next to Windows/Linux (shrink), into free space, manual (GParted).

Log
  /run/voidstation-installer/install.log (live system),
  /var/log/voidstation-install.log (installed system)

Project: https://github.com/Panther92/VoidStation
