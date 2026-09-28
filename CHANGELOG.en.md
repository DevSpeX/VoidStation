# Changes

English version of `CHANGELOG.md`, shown in the update dialog when the interface is set to English.
Same format and the same version headings: `## <version> – <YYYY-MM-DD>`, followed by bullet points.

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
