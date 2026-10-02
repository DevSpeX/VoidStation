# Mitmachen

VoidStation ist freie Software. Fehler melden, übersetzen, Designs bauen oder Code beisteuern – jede Hilfe ist willkommen.

## Quellcode {#quellcode}

Alles liegt auf [GitHub](https://github.com/Panther92/VoidStation): Startseite und Backend (`launcher/`), Installer, ISO-Bau (`iso/`), Update- und Installationsskripte und diese Webseite (`site/`). Die README im Repo erklärt den Aufbau im Detail.

## Fehler melden {#fehler}

Am besten als [Issue auf GitHub](https://github.com/Panther92/VoidStation/issues). Hilfreich sind:

- die VoidStation-Version (steht im Update-Dialog und in den News)
- das Gerät (Prozessor, Grafik) und wie VoidStation installiert wurde
- was du gemacht hast, was passieren sollte und was passiert ist
- Protokolle aus `~/.local/share/voidstation/logs/` bzw. das Installer-Protokoll

## Übersetzen {#uebersetzen}

Alle Texte der Oberfläche stehen in `launcher/web/i18n/de.json` und `en.json`, die der Webseite in `site/i18n.json` und `site/pages/`. Neue Texte gehören immer in beide Sprachen. Lust auf eine weitere Sprache? Schreib ein Issue.

## Eigene Designs {#designs}

Ein Design ist eine einzelne CSS-Datei mit Farbwerten in `launcher/web/themes/`. VoidStation erkennt neue Dateien dort von selbst und bietet sie unter Einstellungen → Design an.

## Code beitragen {#code}

Pull Requests sind willkommen. Neue Versionen bekommen einen Eintrag in `CHANGELOG.md` und `CHANGELOG.en.md`. Veröffentlicht und signiert wird vom Herausgeber – so installieren die Geräte nur geprüfte Updates.

## Entwickelt mit KI {#ki}

Ehre, wem Ehre gebührt: Ein großer Teil des Codes ist mit Hilfe von Claude (Anthropic) entstanden. Ideen, Tests auf echter Hardware, Entscheidungen und Veröffentlichung liegen beim Menschen hinter dem Projekt.

## Danke {#danke}

- **DevSpeX** für Designs, Bildschirmtastatur, Bluetooth, Spielelisten, Programmvorschau und Controller-Unterstützung
- [Void Linux](https://voidlinux.org), [XLibre](https://github.com/X11Libre/xserver) und [xlibre-void](https://github.com/xlibre-void/xlibre)
- [iptv-org](https://github.com/iptv-org/iptv) für die Senderliste und [radio-browser.info](https://www.radio-browser.info) für die Radiosender
- allen, die VoidStation ausprobieren und Fehler melden

## Lizenz {#lizenz}

VoidStation steht unter der [GNU General Public License v3.0 oder später](https://github.com/Panther92/VoidStation/blob/main/LICENSE) (GPL-3.0-or-later). Mitinstallierte Fremdsoftware behält ihre eigenen Lizenzen. Die Schrift dieser Webseite ist Noto Sans (SIL Open Font License).
