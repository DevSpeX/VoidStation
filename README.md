# VoidStation

Void Linux als TV-Station: Kacheloberfläche im Stil von Windows 8, dunkel, bedienbar mit Maus, Tastatur und Gamepad.
Läuft auf Openbox mit einer schlanken WebKitGTK-Startseite (etwa 250 MB RAM).

**Funktionen:** YouTube (Firefox im Kiosk-Modus), Radio mit Suche und Favoriten, TV-Sender aus aller Welt (iptv-org),
Emulatoren, AppCenter für optionale Apps (xbps, Flatpak, AppImage, Web), Einstellungen (Skalierung, Auflösung,
Tonausgang, WLAN, Mauszeiger), Samba-Freigabe `\\<rechner>\share`, mehrere Apps parallel mit Umschalten.

![Startseite](docs/screenshots/1-start.webp)

| Fernsehen | AppCenter | Radio |
|---|---|---|
| ![Fernsehen](docs/screenshots/2-fernsehen.webp) | ![AppCenter](docs/screenshots/3-appcenter.webp) | ![Radio](docs/screenshots/4-radio.webp) |

## Neuinstallation (ganze SSD, von der offiziellen Void-ISO)

1. Offizielle Void-Base-ISO (x86_64, glibc) auf einen Stick oder Ventoy-Stick kopieren. Im BIOS Secure Boot ausschalten und im UEFI-Modus vom Stick booten.
2. Als `root` mit Passwort `voidlinux` anmelden, dann:

```sh
loadkeys de
xbps-fetch https://goldhahn.codeberg.page/vs
bash vs
```

`vs` ist ein kleiner Starter (siehe `pages/vs`, veröffentlicht über das Repo `goldhahn/pages`):
Er lädt jedes Mal den aktuellen `dist/voidstation-install.sh` aus diesem Repo und startet ihn.
Lange Variante ohne Starter:
`xbps-fetch https://codeberg.org/goldhahn/VoidStation/raw/branch/main/dist/voidstation-install.sh`

Das Skript fragt Ziel-SSD, Rechnername, Name und Passwort ab. **Es löscht die komplette SSD.**
Danach installiert es Void, VoidStation, EFISTUB (GRUB als Rückfall) und die Samba-Freigabe.
Grafiktreiber für Intel, AMD oder NVIDIA (nouveau) wählt es automatisch.

## Auf ein bestehendes Void

```sh
sudo bash install.sh              # Erstinstallation
sudo EFISTUB=1 bash install.sh    # zusätzlich direkt per EFISTUB booten
sudo bash update.sh               # Aktualisieren, eigene Kacheln/Favoriten bleiben
```

## Updates

**Am Fernseher:** Einstellungen → *VoidStation aktualisieren* (oder im AppCenter *Alles aktualisieren*).
Das Gerät vergleicht seine Version mit `dist/version.txt` in diesem Repo, lädt bei Bedarf `dist/update.sh`
und bietet danach einen Neustart an. Eigene Kacheln, Favoriten und Einstellungen bleiben erhalten.
Die Update-Quelle steht in der Datei `update-url` (für Forks anpassen, dann `./build.sh`).

**Veröffentlichen:** Änderungen landen per Git im Repo. Ein Git-Bundle lässt sich direkt auf dem Gerät einspielen:
Bundle nach `\\<rechner>\share\Updates` kopieren, dann `bash ~/VoidStation/tools/publish.sh`
(einmalig vorher `git config --global credential.helper store`, damit git sich das Codeberg-Token merkt).

## Eigene Live-ISO bauen (optional, für Installation ohne Internet-Download des Skripts)

Auf einem Void-System: `sudo bash dist/build-iso.sh`. Die ISO landet unter `~/share/ISO/`.
Sie enthält `voidstation-install`, `nmtui` für WLAN, SSH mit root/voidlinux und die eigenen Radio- und TV-Favoriten.

## Aufbau

| Pfad | Inhalt |
|---|---|
| `launcher/launcher.py` | Backend: HTTP-API auf 127.0.0.1:8765, Apps starten/umschalten, Radio, TV, AppCenter, Einstellungen |
| `launcher/web/index.html` | Oberfläche (Kacheln, Radio, TV, AppCenter, Einstellungen) |
| `launcher/voidstation-shell.py` | Vollbild-Fenster (WebKitGTK) für die Startseite; Firefox als Rückfall |
| `launcher/tiles.json` | Standard-Kacheln |
| `launcher/catalog.json` | App-Katalog für das AppCenter |
| `launcher/voidstation-pkg` | root-Helfer, installiert nur freigegebene Pakete |
| `launcher/openbox/`, `launcher/firefox/` | Openbox-Konfiguration, Firefox-Profile und Richtlinien |
| `install-head.sh`, `update-head.sh` | Kopf der Installations- und Update-Skripte (Payload wird angehängt) |
| `iso/` | Neuinstallation (`voidstation-install`) und ISO-Bau |
| `tools/` | `publish.sh` (Bundle einspielen und pushen), `screenshots.py` (README-Bilder) |
| `update-url` | Update-Quelle der Geräte |
| `dist/` | **fertige Skripte**, erzeugt mit `./build.sh` |

Nach Änderungen am Code: `./build.sh`, dann `dist/` mit einchecken.
Screenshots neu erzeugen (mit Beispieldaten, ohne Void): `python3 tools/screenshots.py`
(braucht `pip install playwright pillow` und `playwright install chromium`).

## Auf dem Gerät

- Kacheln anpassen: `~/.local/share/voidstation/tiles.json`
- Logs: `~/.local/share/voidstation/logs/`
- Startseite wieder über Firefox statt WebKit: `touch ~/.local/share/voidstation/use-firefox`
