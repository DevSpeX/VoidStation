# Contribute

VoidStation is free software. Report bugs, translate, build themes or contribute code – all help is welcome.

## Source code {#source}

Everything is on [GitHub](https://github.com/Panther92/VoidStation): the start screen and backend (`launcher/`), the installer, the ISO build (`iso/`), the update and install scripts and this website (`site/`). The README in the repository explains the layout in detail.

## Reporting bugs {#bugs}

Ideally as an [issue on GitHub](https://github.com/Panther92/VoidStation/issues). Questions, ideas and "how do I …?" belong in the [Discussions](https://github.com/Panther92/VoidStation/discussions) instead. Helpful details for bugs:

- the VoidStation version (shown in the update dialog and in the news)
- the device (CPU, graphics) and how VoidStation was installed
- what you did, what should have happened and what happened instead
- logs from `~/.local/share/voidstation/logs/` or the installer log

## Translating {#translating}

All interface texts live in `launcher/web/i18n/de.json` and `en.json`, the website's in `site/i18n.json` and `site/pages/`. New texts always go into both languages. Fancy adding another language? Open an issue.

## Your own themes {#themes}

A theme is a single CSS file with color values in `launcher/web/themes/`. VoidStation picks up new files there automatically and offers them under Settings → Appearance.

## Contributing code {#code}

Pull requests are welcome. New versions get an entry in `CHANGELOG.md` and `CHANGELOG.en.md`. Releases are published and signed by the maintainer – so devices only install reviewed updates.

## Built with AI {#ai}

Credit where credit is due: a large part of the code was written with the help of Claude (Anthropic). Ideas, testing on real hardware, decisions and releases are down to the human behind the project.

## Thanks {#thanks}

- **DevSpeX** for themes, the on-screen keyboard, Bluetooth, game lists, the program guide and controller support
- [Void Linux](https://voidlinux.org), [XLibre](https://github.com/X11Libre/xserver) and [xlibre-void](https://github.com/xlibre-void/xlibre)
- [iptv-org](https://github.com/iptv-org/iptv) for the channel list and [radio-browser.info](https://www.radio-browser.info) for the radio stations
- everyone who tries VoidStation and reports bugs

## License {#license}

VoidStation is licensed under the [GNU General Public License v3.0 or later](https://github.com/Panther92/VoidStation/blob/main/LICENSE) (GPL-3.0-or-later). Third-party software installed alongside keeps its own licenses. This website's typeface is Noto Sans (SIL Open Font License).
