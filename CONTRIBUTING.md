# Contributing to VoidStation

Thanks for helping out! Bug reports, ideas, translations, themes and code are all welcome.
You can write in **English or German** – issues, discussions and pull requests alike.

VoidStation follows [No Code of Conduct](CODE_OF_CONDUCT.md): we are all adults, we accept anyone's contributions, nothing else matters.
Security problems please **don't** report in a public issue – see [SECURITY.md](SECURITY.md).

## Where to go

| You want to … | Go to |
|---|---|
| ask a question, share an idea, show your setup | [Discussions](https://github.com/Panther92/VoidStation/discussions) |
| report a bug | [New issue → Bug report](https://github.com/Panther92/VoidStation/issues/new/choose) |
| suggest a feature | [New issue → Feature request](https://github.com/Panther92/VoidStation/issues/new/choose) |
| contribute code, texts or a theme | a pull request against `main` (see below) |

## Branches and channels

| Branch | Update channel | Contents |
|---|---|---|
| `main` | *Testing* (only on request: `vsctl channel testing`) | the next version – **all pull requests go here** |
| `stable` | *Stable* (default on devices) | what every device gets; only the maintainer releases here (`vspub --release` / `--hotfix`) |

Devices download their updates straight from these branches (`update-url`), so both names are part of the
update mechanism and must not be renamed. Released versions are tagged `v<version>` and listed under
[Releases](https://github.com/Panther92/VoidStation/releases) – the tags and releases are created automatically.

Versions follow the calendar (`2026.11`, hotfixes `2026.11.1`). Merged changes go to *Testing* first; the monthly
release train takes to *Stable* what arrived before the feature freeze (the Monday of the release week) –
see [RELEASING.md](RELEASING.md).

## Pull requests

1. Fork the repository and create a branch from `main`.
2. Make your change. Keep a pull request to one topic – several small PRs are easier to review than one big one.
3. Run the checks (needs Python 3; `shellcheck`, `ruff` and `mypy` are optional but recommended):

   ```sh
   tools/check.sh
   ```

   They run automatically on every pull request as well. `ruff` only looks for real errors, not style;
   `mypy` checks types step by step. Both read their settings from `pyproject.toml`.
   `VS_CHECK_INSTALL=1 tools/check.sh` fetches the pinned versions into a throwaway venv.
4. Try it out:
   - Qt interface without a Void system: `python3 tools/qt-preview.py` (needs `pip install PySide6-Essentials`),
     installer with `--live` (plus `--fail` for the error page, `--bios` for BIOS mode).
   - On a VoidStation device: switch it to the *Testing* channel in the terminal (`vsctl channel testing`) or
     copy the changed files over SSH.
5. Open the pull request against `main` and describe what changed and how you tested it.
   Screenshots help a lot for anything visible.

### Rules of thumb

- **Don't touch `dist/` or `keys/`.** `dist/` is generated and signed by `tools/publish.sh` on the maintainer's
  machine; a pull request that changes it fails the checks.
- **Texts in both languages.** Every new interface text goes into `launcher/web/i18n/de.json` **and** `en.json`
  with the same `{placeholders}` – `build.sh` refuses to build otherwise. If you only speak one of the two
  languages, write that one and say so in the PR; the other gets filled in during review.
  The other language files may stay behind – missing texts appear in English until someone translates them.
- **Translations:** the twenty-five extra languages (`cs`, `da`, `et`, `es`, `fr`, `is`, `it`, `lv`, `hu`, `nl`, `nb`, `pl`, `pt-BR`,
  `ro`, `sk`, `fi`, `sv`, `tr`, `el`, `ru`, `uk`, `ja`, `ko`, `zh-CN`, `zh-TW`)
  were machine-translated. Fixing wording in your native language is one of the most helpful contributions –
  just edit `launcher/web/i18n/<language>.json`, keep the `{placeholders}` and `<b>` tags as they are.
- **Changelog:** don't add version headings to `CHANGELOG.md` – the maintainer writes the entry under
  `## Testing` (German and English) when merging, and the version number is assigned at release time.
  A short line in the PR description about what users will notice is perfect.
- **Packages:** native Void packages first. Otherwise the maker's own build (AppImage, zip, tarball or .deb) that VoidStation downloads and unpacks into `apps/<id>` (catalog source `appimage`, see `app_release()` in `launcher.py`). No Flatpaks in the catalog – only apps that exist as a direct download.
  AppCenter apps are listed in `launcher/catalog.json`.
- **New files** start with an SPDX line, e.g. `# SPDX-License-Identifier: GPL-3.0-or-later`.
- **Code comments** may be German or English – most existing comments are German (written without umlauts, `ae`/`oe`/`ue`).
- **Themes** are plain CSS files in `launcher/web/themes/` – see [Themes](README.md#themes) in the README.
- **AI-assisted code is fine** – large parts of VoidStation were written with AI assistance. You are responsible
  for what you submit, though: read it, understand it and test it.

## Reporting bugs

The bug report form asks for the important bits. Most helpful are:

- the VoidStation version and channel (Settings → Updates),
- the hardware (CPU, GPU, TV/monitor, controller),
- the logs from `~/.local/share/voidstation/logs/` – for installer problems `/run/voidstation-installer/install.log`
  (the error screen can save it to a USB stick).

## License

VoidStation is licensed under the [GPL-3.0-or-later](LICENSE). By submitting a contribution you agree that it is
published under the same license.
