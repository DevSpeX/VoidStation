# VoidStation

Void Linux als TV-Station: Kacheloberfläche im Stil von Windows 8, dunkel, bedienbar mit Maus, Tastatur und Gamepad.
Läuft auf Openbox mit einer schlanken WebKitGTK-Startseite (etwa 250 MB RAM).

**Funktionen:** YouTube (Firefox im Kiosk-Modus), Radio mit Suche und Favoriten, TV-Sender aus aller Welt (iptv-org),
Emulatoren, AppCenter für optionale Apps (xbps, Flatpak, AppImage, Web), Einstellungen (Skalierung, Auflösung,
Tonausgang, WLAN, Mauszeiger), Samba-Freigabe `\\<rechner>\share`, mehrere Apps parallel mit Umschalten.
Grafik-Server ist [XLibre](https://github.com/X11Libre/xserver) (Pakete von [xlibre-void](https://github.com/xlibre-void/xlibre));
startet die Oberfläche damit zweimal nicht, schaltet VoidStation automatisch auf X.Org zurück.
Manuell: Einstellungen → System → Grafik-Server, oder `sudo /usr/local/sbin/voidstation-pkg xserver xlibre|xorg|status`.

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
`xbps-fetch https://codeberg.org/goldhahn/VoidStation/raw/branch/stable/dist/voidstation-install.sh`

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
Die Geräte prüfen kurz nach dem Start und dann alle 6 Stunden selbst und zeigen oben rechts einen Hinweis,
wenn eine neue Version bereitsteht. Der Update-Dialog zeigt, was neu ist. Eigene Kacheln, Favoriten und
Einstellungen bleiben erhalten.

**Kanäle:** *Stabil* (Zweig `stable`, Standard) oder *Test* (Zweig `main`, neue Versionen zuerst) –
umschaltbar unter Einstellungen → System → Update-Kanal.

**Signaturen:** Updates laufen als root, deshalb installieren Geräte nur Updates, die mit dem Schlüssel des
Herausgebers signiert sind (`ssh-keygen -Y`, Namensraum `voidstation`). Der öffentliche Schlüssel liegt in
`keys/voidstation-release.pub` und wird bei der Installation hinterlegt. Die allererste Installation vertraut
HTTPS und diesem Repo.

## Veröffentlichen (Herausgeber)

Gebaut und signiert wird auf dem Rechner des Herausgebers mit `tools/publish.sh` – dort liegt der private Schlüssel.

```sh
git config --global credential.helper store      # einmalig: Codeberg-Zugang merken
bash tools/publish.sh --init-key                 # einmalig: Signaturschlüssel anlegen (Sicherungskopie!)
bash tools/publish.sh                            # Bundle aus ~/share/Updates übernehmen, bauen, signieren,
                                                 # nach main (Test-Kanal) pushen
bash tools/publish.sh --release                  # Test-Stand für alle freigeben (stable)
```

Neue Versionen bekommen einen Eintrag oben in `CHANGELOG.md` (`## 0.4.1 – JJJJ-MM-TT` plus Stichpunkte).
`dist/` wird nur von `publish.sh` erzeugt und nicht von Hand geändert.
Forks tragen ihre eigene Adresse in `update-url` ein und legen einen eigenen Schlüssel an.

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
| `update-url` | Update-Quelle der Geräte (`{channel}` = stable/main) |
| `CHANGELOG.md` | Versionsnummer und Änderungen (erscheinen im Update-Dialog) |
| `keys/` | öffentlicher Signaturschlüssel |
| `dist/` | **fertige Skripte**, erzeugt mit `./build.sh` |

Zum Ausprobieren ohne Veröffentlichung: `OUT=/tmp/vs ./build.sh`.
Screenshots neu erzeugen (mit Beispieldaten, ohne Void): `python3 tools/screenshots.py`
(braucht `pip install playwright pillow` und `playwright install chromium`).

## Auf dem Gerät

- Kacheln anpassen: `~/.local/share/voidstation/tiles.json`
- Logs: `~/.local/share/voidstation/logs/`
- Startseite wieder über Firefox statt WebKit: `touch ~/.local/share/voidstation/use-firefox`

## Lizenz

VoidStation steht unter der GNU General Public License v3.0 oder später (GPL-3.0-or-later), siehe [LICENSE](LICENSE).
Mitinstallierte Fremdsoftware (Void-Pakete, Bibata-Mauszeiger, Proton-GE, …) behält ihre eigenen Lizenzen.
