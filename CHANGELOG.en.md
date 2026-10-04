# Changes

English version of `CHANGELOG.md`, shown in the update dialog when the interface is set to English.
Same format and the same version headings: `## <version> – <YYYY-MM-DD>`, followed by bullet points.

## 0.14.0 – 2026-10-04
- The installer is now a Qt program as well: the live system and the installation run without WebKit – smooth even with the NVIDIA driver in 4K, mouse included
- All paths as before: whole SSD, next to another system (move the boundary with the d-pad or drag it with the mouse), free space, manual partitioning with GParted; account and hostname via the on-screen keyboard or a real keyboard; “hold A” to install; progress, error page with “Try another way” and log
- “Wi-Fi” in the installer opens the Wi-Fi settings directly
- Stick boot menu: pick the language first (Deutsch / English), then the two boot entries in that language – interface, installer and keyboard start out matching (English with a US keyboard)
- The page arrows at the top right work again (they had no effect with the Qt start page)
- The web interface stays as a fallback: if the Qt interface fails to start three times, it takes over – in the live system too

## 0.13.3 – 2026-10-03
- Wi-Fi: a wrong password now shows “Wrong password? Please enter it again.” instead of the raw nmcli message, the field is cleared and the on-screen keyboard opens again; “network not found”, “not responding” and “no Wi-Fi adapter” are shown in plain words too
- Wi-Fi: connecting with a password replaces an old saved profile for the same network, and a failed attempt no longer leaves a half-made profile behind (it used to block the next attempt)

## 0.13.2 – 2026-10-03
- Keyboard and gamepad no longer jump back to the tile under the mouse pointer – the mouse only sets the focus when it is moved

## 0.13.1 – 2026-10-03
- Wi-Fi: scanning gets enough time for USB adapters (instead of “nmcli not available”), connecting waits up to 90 s; country radio rules (wireless-regdb package, country from the time zone), no random MAC while scanning and no power saving – helps many USB adapters
- Keyboard: the interface uses the layout chosen in the installer (it was always German before, e.g. wrong with a US keyboard)
- elogind no longer restarts every second (“elogind is already running” flooding the console); booting via GRUB without a flood of messages
- Web interface (live system, installer, “Classic”) with the NVIDIA driver: runs in Firefox instead of WebKit – smooth even in 4K
- Live ISO: the boot menu never runs in 4K (barely reacted to keys on some NVIDIA cards), 15 s countdown; the regular entry reliably blocks the NVIDIA driver, and the installer only keeps it when the card really uses it

## 0.13.0 – 2026-10-03
- New start page as a program of its own (Python + Qt 6) instead of a web page in WebKit: draws directly on the graphics card – also with the NVIDIA driver and in 4K – and needs less memory
- Everything as before: tiles, radio, TV with programme info, games, AppCenter, settings, on-screen keyboard and themes, controlled by gamepad, keyboard and mouse
- Settings → System → Interface: switch between “New (Qt)” and “Classic (web)”. If the new interface fails to start three times, the classic one takes over automatically
- The live system and the installer keep the web interface for now

## 0.12.1 – 2026-10-02
- No more dark screen while starting: until the home screen is ready it shows the logo with loading dots – seamlessly following the boot splash
- The home screen starts earlier (no longer waits for audio and the launcher), and the background is dark grey from the start instead of black
- Live ISO: boot splash with logo in BIOS mode (Legacy/CSM) too, instead of text messages

## 0.12.0 – 2026-10-02
- Home screen on NVIDIA cards: the interface picks a suitable rendering path by itself (no DMA-BUF on NVIDIA, no GPU at all if none is available) and steps down to a safer mode after repeated crashes – instead of a black screen with a mouse pointer
- Live ISO: new boot menu with logo in the tile design, just “Start VoidStation Live”, “Start VoidStation Live (NVIDIA only)” and “Reboot” (UEFI and BIOS)
- Live ISO: NVIDIA driver included (GeForce GTX 16xx, RTX 20xx and newer) – only loaded via “NVIDIA only”; the regular entry uses nouveau with GSP firmware
- Live ISO: boot splash with logo
- Installer: installing from “NVIDIA only” keeps the NVIDIA driver; otherwise it is removed along with DKMS and the compiler. Boot splash and GParted stay on the stick

## 0.11.1 – 2026-10-01
- The on-screen keyboard opens for every input field, also on mouse click – and now in Firefox/YouTube too (“FX OSK” extension, works offline)
- PlayStation controllers (DualSense/DualShock) via Bluetooth; the D-pad also works on controllers that report it as an axis
- Logos and tiles can no longer be dragged by accident, no text selection while navigating
- Installer: the size split next to another system can be dragged with the mouse
- Thanks to DevSpeX!

## 0.11.0 – 2026-10-01
- Installation also works in BIOS mode (Legacy/CSM): older PCs and virtual machines with default settings (VirtualBox, QEMU) no longer need UEFI. BIOS mode offers “Use the whole SSD”; installing next to other systems and manual partitioning remain UEFI-only
- An SSD installed in BIOS mode also boots when the firmware is later switched to UEFI (GRUB for both modes)
- The stick's boot menu now offers “Install VoidStation” and the English entries in BIOS mode too
- The installer only requires Secure Boot to be off; the instructions for that are shorter

## 0.10.1 – 2026-10-01
- AppCenter: visible scrollbars next to the categories and the apps, so you can tell there is more; the category list fades out at the bottom when more follows

## 0.10.0 – 2026-10-01
- AppCenter rebuilt: “Installed” and the categories on the left, the apps as tiles on the right – the list scrolls down instead of sideways, and the number of columns adapts to resolution and scaling
- “Installed” shows everything on the device at a glance, grouped by category – including programs installed outside the AppCenter
- Controls: up / down switches the category and shows it right away, right goes into the apps, left goes back; LT / RT (PgUp/PgDn) jumps to the previous / next category from anywhere; the mouse wheel scrolls the list
- Much more choice (60 instead of 22 apps), still curated:
  - Gaming: Heroic Games Launcher, Lutris, itch, Prism Launcher (Minecraft), Steam Link, Discord
  - Emulators: PCSX2 (PS2), Rosalie's Mupen GUI (N64), Azahar (3DS), Cemu (Wii U), MAME (arcade)
  - Games: SuperTuxKart, SuperTux, Neverball, Luanti, Xonotic, Hedgewars, Battle for Wesnoth, OpenTTD
  - Media: Jellyfin, Plex HTPC, Spotify, FreeTube, Strawberry; Kodi now comes with controller support and streaming add-ons
  - Streaming: Netflix, Prime Video, Disney+, Joyn, RTL+, Pluto TV, Twitch
  - Browsers: Firefox (normal, with address bar), Chromium, Brave, LibreWolf
  - Tools: Mission Center, LocalSend (send files from your phone), AntiMicroX (controller mapping)
- Streaming apps with copy protection (Netflix & co.) enable Widevine in their Firefox profile
- The AppCenter opens faster: installation status is checked with one call for all apps instead of one per app

## 0.9.0 – 2026-10-01
- Updates in one place: Settings → Updates → “Update” checks and installs everything in one go – Void packages (incl. the kernel), Flatpaks, AppImages, Proton-GE and VoidStation itself; anything already up to date is skipped
- The AppCenter no longer has update buttons, it is only for installing and removing programs
- Devices now also check for system updates (every 6 hours). New VoidStation versions show up right away and bring pending system updates along; system-only updates are flagged at the bottom right only after 30, 60 or 90 days (default 90, Settings → Updates) – no daily nagging on a rolling release. The confirmation lists all packages
- Updates done in a terminal (`sudo xbps-install -Su`) are detected: finished updates disappear from the display, and after a new kernel “Restart required” appears
- A restart is only requested when it is really needed (new kernel or new VoidStation version)
- New in the terminal: `vsctl update` does the same as the button in Settings, with a live log

## 0.8.3 – 2026-10-01
- Settings adapt to every resolution and scale: long lists (Wi-Fi, Bluetooth) scroll along instead of disappearing under the hint line; long names wrap
- Page titles shrink when space is tight instead of overlapping the page arrows
- Fixed: at large scales (e.g. 2.25× at 720p) opening Radio could hang the interface (endless re-layout loop)

## 0.8.2 – 2026-10-01
- Settings: the top row of tiles is no longer cut off, and the focus frame on the bottom row no longer covers the hint line

## 0.8.1 – 2026-10-01
- Tidier settings: one tile per area (Language, Display, Appearance, Sound, Network, Bluetooth, Shared folder, Updates, System) – each tile shows the current state, Esc / B returns to the overview
- A pending update shows up on the “Updates” tile; U / Select jumps straight there

## 0.8.0 – 2026-09-30
- Themes: Dark, Light, High Contrast and Nord – under Settings → Display
- On-screen keyboard for search fields and the Wi-Fi password – works with a controller, a remote or a keyboard
- Bluetooth: find, pair, connect and unpair headphones and controllers in Settings (restart once after the update)
- Games: emulator tiles list the games from the share (share/ROMs/<system>) and launch them directly
- TV: program guide (EPG) with the current and next show – as soon as an EPG source is set
- Thanks to DevSpeX for this release!

## 0.7.8 – 2026-09-29
- Installer: the user and root passwords are now actually set – before, both accounts were left without a password and sudo and su failed; the installer now checks this and stops otherwise
- Installed system: the live stick's greeting (“root:voidlinux …”) no longer appears on the text console

## 0.7.7 – 2026-09-29
- Installer: the password for the Windows share “share” is now actually set – before, the share stayed locked (error 0x80004005)
- Dialogs with long text (e.g. “What's new”): the text scrolls with ↑ ↓, the mouse wheel or the D-pad, the buttons always stay visible

## 0.7.6 – 2026-09-29
- Intel PCs load the current CPU microcode at boot (intel-ucode) – fixes freezes on older Skylake machines with an old BIOS; also in the live ISO

## 0.7.5 – 2026-09-29
- Installer: the progress screen appears right after holding (large tile with percentage, steps and explanation) – no going back until the restart
- Installer finished: only “Restart now” remains

## 0.7.4 – 2026-09-29
- Installer: “Erase and install” got stuck – fixed
- mGBA is no longer preinstalled but available in the AppCenter (Games); existing installations keep it
- AppCenter: new section “On this device” – programs installed in a terminal can get a tile
- Image viewer (GPicView) with a black background

## 0.7.3 – 2026-09-29
- No more “update” to an older version (e.g. when Stable is still behind the installed version)
- Live system: no update status in Settings

## 0.7.2 – 2026-09-29
- ISO build: the live-system setup script is now executable (fixes the abort at step 7/13)

## 0.7.1 – 2026-09-29
- ISO build: packages that no longer exist in the Void repositories (e.g. mesa-vdpau) are skipped instead of aborting the build

## 0.7.0 – 2026-09-29
- XLibre is now the only display server – the update removes X.Org, and the choice in Settings is gone
- If the interface fails to start twice, XLibre gets reinstalled once; after that a rescue console follows
- Remote access (SSH) can be switched on and off under Settings → System
- The update channels are now called “Stable” and “Testing” in both languages
- htop, nano, fastfetch and the Mousepad editor are now always included
- New: live ISO with an installer in the tile design – whole SSD, next to Windows or Linux, into free space, or partition manually with GParted

## 0.6.1 – 2026-09-28
- Programs like VLC, the file manager and YouTube start in the selected language
- Arrows at the top right show that there is more to the left or right; one dot per group
- Jump group by group: LT / RT on the controller, Page Up / Page Down on the keyboard
- Update notice at the bottom right with a yellow warning triangle – open it with U or Select on the controller

## 0.6.0 – 2026-09-28
- Language: German or English, switch under Settings → Language · Sprache
- “What's new” is shown in the selected language
- Time, date and numbers in the format of the selected language
- Default tiles are translated too, your own tile names stay as they are

## 0.5.1 – 2026-09-28
- Moved to GitHub (github.com/Panther92/VoidStation) – devices now get their updates from there
- Short command for a fresh install: xbps-fetch https://panther92.github.io/VoidStation/vs

## 0.5.0 – 2026-09-28
- Display server: XLibre instead of X.Org (xlibre-void repository, key pinned)
- Safety net: if the interface fails to start twice, VoidStation automatically switches back to X.Org
- Choose between XLibre and X.Org under Settings → System → Display server

## 0.4.0 – 2026-09-28
- Update channels: “Stable” for everyone, “Testing” to try new versions early
- Updates are signed – devices only install updates with a valid signature
- Automatic update check with a notice on the start page
- Version numbers and “What's new” in the update dialog
- License: GPL-3.0

## 0.3.0 – 2026-09-28
- Update button: VoidStation updates itself from the settings
- Steam natively from the Void repository (nonfree + multilib) with the latest Proton-GE
- The splash screen stays until a program really shows a window
- Resolution: 60 Hz preferred, interlaced modes (1080i) are avoided
- Swap file on computers with less than 8 GB of RAM

## 0.2.0 – 2026-09-27
- New name: VoidStation
- Fresh install of a whole SSD with one command from the official Void ISO
- Screenshots; grids adapt to the space above the hint bar

## 0.1.0 – 2026-09-27
- Tile interface with a WebKit start page, radio, TV, AppCenter, settings
- Samba share, dark theme, large mouse pointer, EFISTUB
