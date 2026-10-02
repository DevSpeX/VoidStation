# Help

Controls, updates, the shared folder and the most common questions. Something missing? [Ask on GitHub](https://github.com/Panther92/VoidStation/issues).

## Controls {#controls}

| | Controller | Keyboard | Mouse |
|---|---|---|---|
| Move | D-pad / left stick | Arrow keys | point, wheel scrolls |
| Open / select | <kbd>A</kbd> | <kbd>Enter</kbd> | Click |
| Back | <kbd>B</kbd> | <kbd>Esc</kbd> / Backspace | Right-click |
| Close program, favorite | <kbd>X</kbd> / <kbd>Y</kbd> | <kbd>Del</kbd>, <kbd>F</kbd>, <kbd>Y</kbd> | ✕ on the tile |
| Next / previous group | <kbd>RT</kbd> / <kbd>LT</kbd> | PgDn / PgUp | Arrows at the top right |
| Volume down / up | <kbd>LB</kbd> / <kbd>RB</kbd> | <kbd>−</kbd> / <kbd>+</kbd> | |
| Open update (when shown at the bottom right) | <kbd>Select</kbd> | <kbd>U</kbd> | Click the notice |
| Power off | <kbd>Start</kbd> | | ⏻ at the top right |
| Back to the start screen (from any program) | <kbd>Guide</kbd> / Home | <kbd>Win</kbd> | |

The arrows at the top right appear as soon as a page is wider than the screen; the bright dot marks the current group. Pair Bluetooth gamepads under **Settings → Bluetooth**.

## Updates {#updates}

**Settings → Updates → Update** is the only update button. It checks and installs everything in one go: Void packages (including the kernel), Flatpaks, AppImages, Proton-GE and VoidStation itself. Your tiles, favorites and settings are kept.

- Devices check shortly after startup and then every six hours. A yellow notice at the bottom right announces a new VoidStation version right away.
- Plain system updates are only flagged once the system hasn't been updated for 30, 60 or 90 days (Settings → Updates, default 90).
- **Update channel:** *Stable* for everyone, or *Testing* if you want new versions first.
- In the terminal, `vsctl update` does the same as the button. `sudo xbps-install -Su` updates only the Void packages – VoidStation notices that.

## Shared folder: files from your PC {#share}

Every VoidStation has a Windows share. On your PC, type `\\<hostname>\share` into Explorer (e.g. `\\livingroom\share`) and log in with the user name and password from the installation. Movies, music, pictures and games go in there.

## Games and emulators {#games}

Emulators are in the AppCenter under *Emulators*. ROMs go into the shared folder under `share/ROMs/<system>`, for example `gba`, `snes`, `nes`, `psx`, `psp`, `nds`, `gamecube` or `dreamcast`. The emulator tile then shows a game list; without games, the emulator starts directly.

## TV program guide {#epg}

Off by default. To turn it on, enter the address of an XMLTV file (`.xml` or `.xml.gz`) – it is downloaded daily:

```
echo 'https://…/epg.xml.gz' | sudo tee /usr/local/share/voidstation/epg-url
```

## Frequently asked questions {#faq}

### Do I need an account?

No. VoidStation does not sign you in to any service. Only streaming apps like Netflix want their own account, of course.

### Does it run on a Raspberry Pi?

No, only on 64-bit PCs (x86_64). A used mini PC or office PC is ideal.

### Can I keep Windows?

Yes: the live ISO installs next to Windows (in UEFI mode). Turn off Fast Startup in Windows first and shut Windows down instead of hibernating it. A short boot menu then appears at startup.

### The interface doesn't start – what now?

After two failed starts, VoidStation reinstalls the XLibre display server once. If it still fails, a rescue console appears. `sudo /usr/local/sbin/voidstation-pkg xserver status` helps there.

### Where are the logs?

In `~/.local/share/voidstation/logs/`. During installation, the installer's log is at `/run/voidstation-installer/install.log` and can be saved straight to a USB stick.

### Is VoidStation an official Void Linux project?

No. VoidStation is a private hobby project built on Void Linux. Please don't take questions about VoidStation to the Void team – ask [here](https://github.com/Panther92/VoidStation/issues) instead.
