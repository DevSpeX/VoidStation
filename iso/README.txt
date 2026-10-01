VoidStation – live system with installer
========================================

Booting
  Plug in the stick and pick it in the PC's boot menu (usually F12, F11 or Esc) –
  preferably the entry starting with "UEFI:". Secure Boot must be off.
  Older PCs and virtual machines without UEFI boot in BIOS mode (Legacy) – that
  works too, but then VoidStation can only be installed on a whole SSD.

Boot menu
  VoidStation (English)               live system in English (nothing gets installed)
  Install VoidStation (English)       starts right away with the installer
  The entries without "(English)" are German.

Installing
  Tile "Install VoidStation" – or in a terminal: sudo voidstation-installer text
  Minimum: 64-bit PC, 4 GB RAM, 16 GB on the SSD. UEFI or BIOS (Legacy).
  Ways: whole SSD, next to Windows/Linux (shrink), into free space, manual (GParted).
  In BIOS mode only "whole SSD" is available; the SSD then boots in both modes.

Log
  /run/voidstation-installer/install.log (live system),
  /var/log/voidstation-install.log (installed system)

Project: https://github.com/Panther92/VoidStation
