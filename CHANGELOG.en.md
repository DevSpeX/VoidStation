# Changes

English version of `CHANGELOG.md`, shown in the update dialog when the interface is set to English.
Same format and the same version headings: `## <version> – <YYYY-MM-DD>`, followed by bullet points.

## 0.7.7 – 2026-09-29
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
