# VoidStation

**[English](README.md)** · Deutsch · [voidstation.de](https://voidstation.de) · [Download](https://voidstation.de/download/) · [Fragen](https://github.com/Panther92/VoidStation/discussions) · [Fehler melden](https://github.com/Panther92/VoidStation/issues/new/choose)

[![Stable](https://img.shields.io/github/v/release/Panther92/VoidStation?label=stable)](https://github.com/Panther92/VoidStation/releases/latest) [![Checks](https://github.com/Panther92/VoidStation/actions/workflows/checks.yml/badge.svg)](https://github.com/Panther92/VoidStation/actions/workflows/checks.yml) [![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPL--3.0--or--later-blue)](LICENSE) [![ISO downloads](https://img.shields.io/sourceforge/dt/voidstation?label=ISO%20downloads)](https://sourceforge.net/projects/voidstation/files/) [![DistroWatch](https://img.shields.io/badge/DistroWatch-listed-2f6f4f)](https://distrowatch.com/table.php?distribution=voidstation)

Void Linux als TV-Station: Kacheloberfläche im Stil von Windows 8, dunkel, bedienbar mit Gamepad, Fernbedienung, Maus und Tastatur.
Läuft auf Openbox; die Startseite ist ein eigenes Programm in Python + Qt 6, das direkt auf der Grafikkarte zeichnet.
Auch der Installer im Live-System ist Qt. Die frühere Web-Oberfläche (WebKitGTK) ist seit 2026.12 entfernt.

**Funktionen:** YouTube (Firefox im Kiosk-Modus), Radio mit Suche und Favoriten, TV-Sender aus aller Welt (iptv-org) im eigenen Player
(umschalten im Bild, Senderliste, Programminfo), **Videos & Musik** (Mediathek für Freigabe und USB-Laufwerke mit Covern,
Weiterschauen, Wiederholen/Zufall, „Musik suchen“ mit Download samt Tags und Cover), Emulatoren, AppCenter für optionale Apps (Void-Pakete, entpackte Programme der Hersteller, Web), Einstellungen (Sprache, Skalierung, Auflösung,
Tonausgang, WLAN, Bluetooth, Mauszeiger), Samba-Freigabe `\\<rechner>\share`, mehrere Apps parallel mit Umschalten.
Oberfläche auf **Deutsch oder Englisch**, dazu fünfundzwanzig maschinell übersetzte Sprachen: Čeština, Dansk, Eesti, Español, Français, Íslenska, Italiano,
Latviešu, Magyar, Nederlands, Norsk bokmål, Polski, Português (Brasil), Română, Slovenčina, Suomi, Svenska, Türkçe, Ελληνικά, Русский, Українська, 日本語, 한국어, 简体中文, 繁體中文 (Einstellungen → Sprache). Installer und Startmenü des Sticks sprechen ab der Live-ISO 2026.11 ebenfalls alle Sprachen (alle seit der Live-ISO 2026.11 hinzugekommenen ab der nächsten Live-ISO).
Grafik-Server ist [XLibre](https://github.com/X11Libre/xserver) (Templates von [xlibre-void](https://github.com/xlibre-void/xlibre), gebaut und signiert in der eigenen Paketquelle [voidstation-packages](https://github.com/Panther92/voidstation-packages));
X.Org wird nicht verwendet. Startet die Oberfläche zweimal nicht, installiert VoidStation XLibre einmal neu;
danach folgt eine Rettungskonsole. Von Hand: `sudo /usr/local/sbin/voidstation-pkg xserver ensure|repair|status`.
Fernzugriff per SSH lässt sich unter Einstellungen → System ein- und ausschalten.

![Startseite](docs/screenshots/1-start.webp)

| Fernsehen | AppCenter | Radio |
|---|---|---|
| ![Fernsehen](docs/screenshots/2-fernsehen.webp) | ![AppCenter](docs/screenshots/3-appcenter.webp) | ![Radio](docs/screenshots/4-radio.webp) |

| Fernseh-Player | Videos | Musik |
|---|---|---|
| ![Fernseh-Player](docs/screenshots/7-tv-player.webp) | ![Video](docs/screenshots/12-video.webp) | ![Musik](docs/screenshots/9-musik.webp) |

| Mediathek | Musik suchen | Ton |
|---|---|---|
| ![Mediathek](docs/screenshots/8-mediathek.webp) | ![Musik suchen](docs/screenshots/10-musik-suchen.webp) | ![Ton](docs/screenshots/11-ton.webp) |

| Installer | Installer: Ziel-SSD |
|---|---|
| ![Installer](docs/screenshots/5-installer.webp) | ![Ziel-SSD](docs/screenshots/6-ziel-ssd.webp) |

Bild im Fernseh-Player und in „Videos“: „Big Buck Bunny“ © Blender Foundation | [peach.blender.org](https://peach.blender.org), [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/deed.de). Alle übrigen Inhalte der Screenshots sind Beispieldaten.

## Installation

VoidStation wird **ausschließlich über die Live-ISO** installiert:
**[Download auf voidstation.de](https://voidstation.de/download/)** (gehostet auf [SourceForge](https://sourceforge.net/projects/voidstation/files/)).

1. ISO herunterladen und prüfen (siehe [Download prüfen](#download-prüfen)).
2. Mit [Ventoy](https://www.ventoy.net) auf den Stick kopieren oder mit [Rufus](https://rufus.ie) / [balenaEtcher](https://etcher.balena.io) schreiben.
3. Secure Boot ausschalten, vom Stick starten, im Startmenü die Sprache und dann *VoidStation Live starten* wählen
   (mit NVIDIA ab GTX 16xx / RTX 20xx: *… (nur NVIDIA)*).
4. Live-System ausprobieren, dann Kachel **VoidStation installieren**: ganze SSD, neben Windows oder Linux,
   in freien Platz oder selbst einteilen mit GParted. Etwa fünf Minuten, ohne Internet.

**Mindestens:** 64-Bit-PC (x86_64), 4 GB RAM, 16 GB auf der SSD, Secure Boot aus.

## Live-ISO mit Installer

Die Live-ISO ist eine komplette VoidStation zum Ausprobieren (YouTube, Fernsehen, Radio, Videos & Musik) mit der Kachel
**VoidStation installieren**. Der Installer läuft im selben Kacheldesign, auf Deutsch oder Englisch, und kopiert
das Live-System auf die SSD – dafür braucht er kein Internet.

- **Wege:** ganze SSD · neben Windows oder Linux (NTFS, ext4 oder btrfs wird verkleinert) · in freien Platz
  (z. B. neben FreeBSD) · selbst einteilen mit GParted. Bei mehreren Systemen gibt es ein kurzes GRUB-Startmenü;
  neben Windows läuft die Hardware-Uhr auf Ortszeit.
- **Mindestens:** 64-Bit-PC, 4 GB RAM, 16 GB auf der SSD, Secure Boot aus. Fehlt etwas, sagt der Installer, was zu tun ist.
- **Startmodus:** UEFI kann alle Wege. Im BIOS-Modus (Legacy/CSM, z. B. ältere PCs oder VirtualBox/QEMU mit
  Standardeinstellungen) gibt es nur „ganze SSD“: GPT mit BIOS-Boot-Partition, GRUB für BIOS und zusätzlich
  für UEFI – die SSD startet danach in beiden Modi.
- **Startmenü des Sticks:** mit Logo – oben die Sprache (*Deutsch* / *English*, stellt Oberfläche, Installer und Tastatur ein),
  darunter je *VoidStation Live starten* (freie Treiber) und *… (nur NVIDIA)* bzw. *Start VoidStation Live* / *… (NVIDIA only)*
  (NVIDIA-Treiber für GeForce GTX 16xx / RTX 20xx und neuer) · *Reboot*. Beim Hochfahren zeigt ein Startbild das Logo.
  Wer über „nur NVIDIA“ installiert, bekommt den NVIDIA-Treiber auch im installierten System – sonst entfernt der
  Installer ihn wieder (samt DKMS und Compiler).
- **Fehler:** Jeder Schritt lässt sich wiederholen, der Startmanager auch „anders“ (Standard-Starter statt NVRAM-Eintrag).
  Protokoll: `/run/voidstation-installer/install.log`, lässt sich auf einen USB-Stick speichern.
- **Terminal:** `sudo voidstation-installer text` (nur ganze SSD) · `probe` zeigt, was der Installer erkennt.

### Download prüfen

Neben jeder ISO auf SourceForge liegen `.sha256` und die Signatur `.sha256.sig`:

```sh
sha256sum -c voidstation-<version>-<datum>.iso.sha256
curl -fsSL https://raw.githubusercontent.com/Panther92/VoidStation/stable/keys/voidstation-release.pub \
  | awk '{print "voidstation-release namespaces=\"voidstation\" "$1" "$2}' > voidstation-signers
ssh-keygen -Y verify -f voidstation-signers -I voidstation-release -n voidstation \
  -s voidstation-<version>-<datum>.iso.sha256.sig < voidstation-<version>-<datum>.iso.sha256
```

Unter Windows: `certutil -hashfile voidstation-<version>-<datum>.iso SHA256` und mit der Summe auf der Download-Seite vergleichen.

### ISO bauen

Auf einem Void-System (z. B. einer VoidStation), dauert 25–50 Minuten. Offizielle ISOs werden aus dem Zweig `stable` gebaut:

```sh
git clone https://github.com/Panther92/VoidStation && cd VoidStation   # oder: git fetch im vorhandenen Klon
git show origin/stable:dist/build-iso.sh > /var/tmp/build-iso.sh
sudo bash /var/tmp/build-iso.sh
```

Die ISO landet unter `~/share/ISO/` (mit `.sha256`), eigene Radio- und TV-Favoriten kommen mit.

## Updates

**Am Fernseher:** Einstellungen → Updates → *Aktualisieren* – der einzige Update-Knopf. Er prüft und installiert
alles in einem Durchgang: Void-Pakete (inkl. Kernel), Flatpaks, AppImages, Proton-GE und VoidStation selbst
(in dieser Reihenfolge; was aktuell ist, wird übersprungen). Die Geräte prüfen kurz nach dem Start und dann alle
6 Stunden selbst. Neue VoidStation-Versionen zeigt unten rechts sofort ein Hinweis – das Update bringt wartende
Systemupdates gleich mit. Reine Systemupdates meldet der Hinweis erst, wenn das System seit 30, 60 oder 90 Tagen
nicht mehr aktuell war (Einstellungen → Updates → *Systemupdates melden nach*, Standard 90). Der Update-Dialog zeigt,
was neu ist und welche Pakete kommen. Eigene Kacheln, Favoriten und Einstellungen bleiben erhalten. Ein Neustart wird
nur verlangt, wenn ein neuer Kernel oder eine neue VoidStation-Version installiert wurde.

**Im Terminal:** `vsctl update` macht dasselbe wie der Knopf (Protokoll läuft mit). `sudo xbps-install -Su`
aktualisiert nur die Void-Pakete – das geht weiterhin, VoidStation erkennt es (erledigte Updates verschwinden aus
der Anzeige, nach einem neuen Kernel steht „Neustart nötig“ unten rechts). VoidStation selbst ist kein
xbps-Paket und kommt nur über den Knopf bzw. `vsctl update`.

**Kanäle:** *Stable* (Zweig `stable`) für alle Geräte und *Testing* (Zweig `main`), der Entwicklerstand –
neue Versionen zuerst, ungeprüft. Seit 2026.11 bieten Installer und Einstellungen Testing nicht mehr an; Tester
wechseln im Terminal mit `vsctl channel testing` (zurück mit `vsctl channel stable`).
Jede für *Stable* freigegebene Version bekommt den Tag `v<version>` und steht unter
[Releases](https://github.com/Panther92/VoidStation/releases) – mit Link zur Live-ISO, falls es für diese Version eine gibt.

**Versionen** richten sich nach dem Kalender: `2026.11` ist die Version vom November 2026, Hotfixes dazu heißen
`2026.11.1`, `2026.11.2` … Neues kommt zuerst nach *Testing*; der monatliche Release-Zug bringt nach *Stable*, was vor
der Sperrfrist dort lag (sie beginnt am Montag der Release-Woche). Eine neue Live-ISO gibt es alle drei Monate. Einzelheiten: [RELEASING.md](RELEASING.md) (englisch).

**Signaturen:** Updates laufen als root, deshalb installieren Geräte nur Updates, die mit dem Schlüssel des
Herausgebers signiert sind (`ssh-keygen -Y`, Namensraum `voidstation`). Der öffentliche Schlüssel liegt in
`keys/voidstation-release.pub` und kommt mit der ISO aufs Gerät.

## Bedienung

| | Controller | Tastatur | Maus |
|---|---|---|---|
| Bewegen | Steuerkreuz / linker Stick | Pfeiltasten | zeigen, Mausrad blättert |
| Öffnen / Auswählen | A | Enter | Klick |
| Zurück | B | Esc / Rücktaste | Rechtsklick |
| Programm schließen, Favorit | X / Y | Entf, F, Y | ✕ auf der Kachel |
| Gruppe vor / zurück | RT / LT | Bild ↓ / Bild ↑ | Pfeile oben rechts |
| Leiser / lauter | LB / RB | − / + | |
| Update öffnen (wenn unten rechts angezeigt) | Select | U | Klick auf den Hinweis |
| Ausschalten, Standby | Start | – | ⏻ oben rechts |
| Zurück zur Startseite (aus jedem Programm) | Guide / Home | Win | Ecke unten rechts, dann **Startseite** |
| Programm schließen (aus dem Programm heraus) | | | Ecke unten rechts, dann **App schließen** |

In Programmen wie Firefox steuert der rechte Stick den Mauszeiger (R2 Klick, L2 Rechtsklick, R3 an/aus).
Tasten im Fernseh-Player und in „Videos & Musik“: siehe [Hilfe](https://voidstation.de/hilfe/#fernsehen).

Die Pfeile oben rechts erscheinen, sobald eine Seite breiter als der Bildschirm ist; der helle Punkt zeigt die aktuelle Gruppe.
Warten Updates (oder ist nach einem neuen Kernel ein Neustart nötig), steht unten rechts ein gelber Hinweis.

## Sprachen

Alle Texte der Oberfläche stehen in `launcher/web/i18n/<sprache>.json` (Schlüssel → Text, `{name}` = Platzhalter).
Im Code: `T('schlüssel', { name })` für Texte, `L(text)` für Kachel-, Gruppen- und App-Namen.
Deutsch und Englisch werden von Hand gepflegt: Neue Texte gehören immer in **beide** Dateien `de.json` und `en.json` –
`build.sh` bricht ab, wenn in `en.json` ein Schlüssel oder Platzhalter fehlt.

Die übrigen Sprachen (`es`, `fr`, `it`, `lv`, `hu`, `nl`, `pl`, `pt-BR`, `el`, `ru`, `uk`) sind maschinell übersetzt –
Korrekturen von Muttersprachlern sind sehr willkommen. Fehlt ein Text, gilt Englisch, dann Deutsch; ein neues Feature
macht also keine Sprache kaputt. `build.sh` zeigt, wie viele Texte noch englisch sind, und lehnt unbekannte Schlüssel oder
falsche Platzhalter ab. Installer-Texte (`inst.*`) sind noch nicht übersetzt.

- Neue Sprache: eine Zeile in `LANG_TABLE` in `launcher/launcher.py` (Kennung, Name in der Sprache, Locale, Firefox-Sprache)
  plus `launcher/web/i18n/<kennung>.json`. Formate stehen in der Datei selbst: `fmt.locale`, `fmt.date` / `fmt.dateYear`
  (Qt-Datumsmuster), `fmt.clock` (`12`/`24`), `fmt.pct`; Ländernamen für den TV-Filter als `region.XX`.

- Sprache wählen: Einstellungen → Sprache. Ohne Wahl gilt `LANG` der Sitzung (`fr_FR…` → Französisch, `pt_BR…` → Portugiesisch (Brasilien), Unbekanntes → Deutsch).
- Programme aus den Kacheln starten mit `LANG`/`LANGUAGE` der gewählten Sprache (PCManFM, GTK/Qt); Firefox-Profile bekommen
  vor jedem Start `intl.locale.requested` und `intl.accept_languages`. Programme mit eigener Spracheinstellung (Steam, Kodi) bleiben dabei.
- Kacheln: Deutsche Standardnamen (z. B. „Fernsehen“) übersetzt `labels` in der jeweiligen Sprachdatei; eigene Namen bleiben, wie sie sind.
  Eigene Kacheln können auch zweisprachig sein: `"label": {"de": "Fernsehen", "en": "TV"}`.
- AppCenter: Beschreibungen über `app.<id>.desc` in der Sprachdatei, sonst gilt der Text aus `catalog.json`; Hinweise nach der
  Installation (`note` im Katalog) über `app.<id>.note`. Kategorien kommen aus `categories` in `catalog.json` (Reihenfolge =
  Seitenleiste, Name über `labels`, Untertitel über `apps.catDesc.<Kategorie>`); „Installiert“ baut die Oberfläche selbst.
- Englisch heißt `en_US`: 12-Stunden-Uhr (8:15 PM), Datum und Zahlen im US-Format.

## Themes & Designs

Unter **Einstellungen → Design → Farbschema** stehen verschiedene Themes zur Auswahl (z. B. `Dunkel`, `Hell`, `Hoher Kontrast`, `Nord`). Das gewählte Theme wird in `settings.json` gespeichert und bleibt bei Updates erhalten.

### Eigene Themes hinzufügen (Drop-in)
Neue Themes können als CSS-Datei direkt in `launcher/web/themes/<theme-name>.css` abgelegt werden:

```css
/* launcher/web/themes/matrix.css */
:root[data-theme="matrix"] {
  --bg-main: #051008;
  --bg-radial-1: #0d2814;
  --bg-radial-2: #020a04;
  --surface-base: #0a1f10;
  --surface-raised: #10331b;
  --surface-card: #143d20;
  --surface-card-hover: #1c542c;
  --surface-active: #00ff66;
  --text-primary: #a3ffc2;
  --text-secondary: rgba(163, 255, 194, 0.75);
  --border-focus: #00ff66;
  --border-subtle: #1c542c;
  /* ... */
}
```

VoidStation erkennt neue CSS-Dateien im Theme-Ordner automatisch und bietet sie direkt in den Einstellungen an.

## Spiele, Bluetooth, Programmvorschau

- **Spiele:** ROMs in die Freigabe unter `share/ROMs/<System>` kopieren (`gba`, `gbc`, `snes`, `nes`, `psx`, `psp`, `nds`, `gamecube`, `dreamcast` …). Die Emulator-Kachel zeigt dann eine Spieleliste; ohne Spiele startet der Emulator direkt.
- **Bluetooth:** Einstellungen → Bluetooth. Bringt `bluez` und `libspa-bluetooth` (Ton über PipeWire) mit; der Benutzer ist in der Gruppe `bluetooth`. VoidStation koppelt mit eigenem Agenten über D-Bus: „Just Works“ wird bestätigt, alte PIN-Geräte bekommen 0000/1234/1111, Tastatur-Codes stehen auf dem Bildschirm; Anfragen nur während der Suche (+3 Min.). Bei mehreren Adaptern gewinnt die neueste Bluetooth-Version (fest wählen: Adresse in `/usr/local/share/voidstation/bt-adapter`).
- **Controller:** udev-Regeln geben Steam, Emulatoren und SDL direkten Zugriff (hidraw, uinput) auf Controller aller gängigen Hersteller. Die Startseite versteht Standard-Pads, einfache USB-Pads, Joysticks und Arcade-Sticks; eigene Belegung in `~/.config/voidstation/pads.json` (`{"<Name oder vid:pid>": {"<evdev-Code>": "a|b|x|y|lb|rb|lt|rt|select|start|up|down|left|right"}}`).
- **Programmvorschau (EPG):** standardmäßig aus. Einschalten, indem man die Adresse einer XMLTV-Datei (`.xml` oder `.xml.gz`) einträgt:
  `echo 'https://…/epg.xml.gz' | sudo tee /usr/local/share/voidstation/epg-url`
  Die Datei wird täglich geladen, im Hintergrund eingelesen und als kleine `~/.local/share/voidstation/cache/epg.json` zwischengespeichert.

## Auf dem Gerät

- Kacheln anpassen: `~/.local/share/voidstation/tiles.json`
- Logs: `~/.local/share/voidstation/logs/`
- Startseite neu starten (per SSH): `pkill -f voidstation-home.py` – `home.sh` startet sie sofort wieder

## Aufbau

| Pfad | Inhalt |
|---|---|
| `launcher/launcher.py` | Backend: HTTP-API auf 127.0.0.1:8765, Apps starten/umschalten, Radio, TV, AppCenter, Einstellungen |
| `launcher/qt/` | Startseite, Player und Installer (Python + Qt 6): `voidstation-home.py` (Fenster, Gamepad, Texte, Farben), `voidstation-player.py` (Fernsehen, Videos & Musik über libmpv), `vscommon.py` (Gemeinsames), `qml/` (Oberfläche), `icons.py` |
| `launcher/web/themes/` | Themes als modulare CSS-Dateien (`default-dark`, `default-light`, `high-contrast`, `nord`) – auch Launcher (Openbox, GTK, Firefox) und Player lesen sie |
| `launcher/web/i18n/` | Texte der Oberfläche, eine Datei je Sprache (`de.json`, `en.json`, …); dazu `web/logo.png` fürs Ladebild |
| `launcher/home.sh` | startet die Startseite und hält sie am Leben (Protokoll: `logs/frontend.log`, `logs/home.log`) |
| `launcher/tiles.json` | Standard-Kacheln |
| `launcher/catalog.json` | App-Katalog für das AppCenter |
| `launcher/voidstation-pkg` | root-Helfer, installiert nur freigegebene Pakete |
| `launcher/voidstation-installer` | Installer-Backend (root, nur im Live-System): prüft das Gerät, partitioniert, kopiert, richtet ein |
| `launcher/openbox/`, `launcher/firefox/` | Openbox-Konfiguration, Firefox-Profile und Richtlinien |
| `install-head.sh`, `update-head.sh` | Kopf der Einrichtungs- und Update-Skripte (Payload wird angehängt; die Einrichtung läuft beim ISO-Bau und im Installer) |
| `iso/` | ISO-Bau (`build-iso-head.sh`, `postsetup.sh`, Startmenü `grub-entries.py`, Grafiken `art/`) |
| `docs/screenshots/` | Screenshots (deutsch, `en/` englisch) |
| `site/`, `tools/build-site.py` | Webseite voidstation.de (Quellen und Bau), veröffentlicht von `.github/workflows/pages.yml` |
| `.github/` | Workflows (Webseite, Prüfungen, Releases), Issue-Formulare, Vorlage für Pull Requests |
| `tools/` | `publish.sh` (veröffentlichen), `changelog.py` (Changelog-Helfer fürs Veröffentlichen), `check.sh` (Prüfungen vor einem Pull Request), `gh-release.py` (GitHub-Releases), `qt-preview.py` (Qt-Oberfläche mit Beispieldaten), `qt-screenshots.py` (Screenshots), `sampledata.py` (Beispieldaten für beide), `boot-art.py` (Grafiken für Startmenü und Startbild → `iso/art/`) |
| `update-url` | Update-Quelle der Geräte (`{channel}` = stable/main) |
| `CHANGELOG.md`, `CHANGELOG.en.md` | Versionsnummer und Änderungen, deutsch und englisch (erscheinen im Update-Dialog) |
| `RELEASING.md` | Versionsnummern, Release-Zug, Hotfixes, ISO-Rhythmus |
| `keys/` | öffentlicher Signaturschlüssel |
| `dist/` | **fertige Skripte**, erzeugt mit `./build.sh` |

Zum Ausprobieren ohne Veröffentlichung: `OUT=/tmp/vs ./build.sh`.
Qt-Oberfläche ohne Void ausprobieren: `python3 tools/qt-preview.py` (braucht `pip install PySide6-Essentials`), Installer: `--live`
(dazu `--fail` für die Fehlerseite, `--bios` für den BIOS-Modus).
Screenshots neu erzeugen (Beispieldaten, ohne Void, deutsch und englisch): `python3 tools/qt-screenshots.py`
(braucht `pip install PySide6-Essentials pillow` und die Schrift Noto Sans).

## Veröffentlichen (Herausgeber)

Gebaut und signiert wird auf dem Rechner des Herausgebers mit `tools/publish.sh` – dort liegt der private Schlüssel.
Wann was freigegeben wird – Release-Zug, Hotfixes, ISO-Rhythmus – steht in [RELEASING.md](RELEASING.md).

```sh
git config --global credential.helper store      # einmalig: GitHub-Zugang (Token) merken
echo "alias vspub='bash ~/VoidStation/tools/publish.sh'" >> ~/.bashrc   # einmalig, dann neu anmelden
echo "alias vsget='bash ~/VoidStation/tools/vsget.sh'" >> ~/.bashrc   # einmalig
vspub --init-key                                 # einmalig: Signaturschlüssel anlegen (Sicherungskopie!)
vsget                                            # Claude-Zweige (claude/*) als ein Bundle -> ~/share/Updates holen (Auswahl: 2, 1,3, 1-3, alle)
vspub                                            # Bundle aus ~/share/Updates übernehmen, bauen, signieren,
                                                 # nach main (Kanal Testing) pushen
vspub --status                                   # was liegt in Testing, seit wann, was fährt mit dem Release-Zug?
vspub --release                                  # Release-Zug: alles von vor der Sperrfrist -> stable als JJJJ.MM
vspub --hotfix <commit>                          # einzelne Fehlerbehebung aus Testing sofort -> stable als JJJJ.MM.N
vspub --iso                                      # neueste Live-ISO aus ~/share/ISO nach SourceForge
```

`vspub --iso` prüft die Prüfsumme der ISO, signiert die `.sha256` mit dem Release-Schlüssel (`.sha256.sig`),
lädt alles per rsync nach `frs.sourceforge.net:/home/frs/project/voidstation/<version>/` (ein Abbruch setzt beim
nächsten Aufruf fort), stellt den Download auf voidstation.de um (`site/config.json`) und löscht die ISO danach
lokal. Am besten in `tmux` starten. Einmalig nötig: SSH-Schlüssel bei SourceForge hinterlegen und in `~/.ssh/config`
eintragen (`Host frs.sourceforge.net` · `User <SourceForge-Name>` · `IdentityFile ~/.ssh/sourceforge`).
Danach im Browser die ISO als *Default Download* markieren.

**GitHub-Releases** legt `.github/workflows/release.yml` an – von Hand ist nichts zu tun: `vspub --release`
erzeugt den Tag `v<version>` und ein Release mit dem englischen Changelog; sobald `vspub --iso` die ISO dieser
Version hochgeladen hat, bekommt das Release einen Download-Abschnitt (Link, Größe, SHA-256, Signatur). Die ISO selbst
bleibt auf SourceForge – GitHub erlaubt pro Release-Datei höchstens 2 GiB. Tags bitte nicht von Hand anlegen.

Neues kommt oben in `CHANGELOG.md` unter `## Testing – JJJJ-MM-TT` (Stichpunkte) und dasselbe auf Englisch in
`CHANGELOG.en.md` – fehlt es, bricht `build.sh` ab. Die Versionsnummer vergibt `vspub` beim Freigeben.
`dist/` wird nur von `publish.sh` erzeugt und nicht von Hand geändert.
Forks tragen ihre eigene Adresse in `update-url` ein und legen einen eigenen Schlüssel an.
Ist ein Remote `codeberg` eingerichtet, pflegt `publish.sh` ihn als Spiegel mit (früherer Standort des Projekts).

## Webseite (voidstation.de)

Die Webseite liegt in `site/` und wird mit `tools/build-site.py` gebaut (nur Python 3, keine Fremdpakete).
GitHub Actions (`.github/workflows/pages.yml`) baut und veröffentlicht sie bei jedem Push nach `main` oder `stable` –
`vspub` reicht also, um sie zu aktualisieren.

- **Seiten:** `site/pages/<seite>.de.md` und `.en.md` (Markdown, erste Zeile `# Titel`, erster Absatz = Vorspann).
  Links auf andere Seiten als `seite:hilfe#bedienung`; Bausteine wie `{{iso}}` stehen allein in einer Zeile.
- **News:** jede Version aus `CHANGELOG.md`/`CHANGELOG.en.md` des Zweigs `stable` erscheint automatisch.
  Eigene Beiträge: `site/news/JJJJ-MM-TT-name.de.md` (+ `.en.md`), erste Zeile `# Titel`.
- **ISO-Download:** steht in `site/config.json` unter `iso` – `vspub --iso` trägt ihn selbst ein.
- **Screenshots:** aus `docs/screenshots/`, englische Seiten nehmen `docs/screenshots/en/`.
- **Impressum:** `site/impressum.json`. Solange Name und E-Mail fehlen, veröffentlicht der Workflow nur eine
  Baustellenseite (plus die Update-Kanäle). Die Anschrift (`street`, `city`) ist optional und erscheint, sobald sie eingetragen ist.
- Unter der Domain liegen außerdem die Update-Kanäle `/stable/dist/` und `/main/dist/`.

Ansehen ohne Veröffentlichen:

```sh
python3 tools/build-site.py --preview      # --preview zeigt alles, auch ohne Impressum
python3 -m http.server -d _site 8000       # dann http://<rechner>:8000
```

## Mitmachen

Fehlerberichte, Ideen, Übersetzungen, Themes und Pull Requests sind willkommen – auf Deutsch oder Englisch.
Siehe [CONTRIBUTING.md](CONTRIBUTING.md) (Pull Requests gehen an `main`), [No Code of Conduct](CODE_OF_CONDUCT.md)
und für Sicherheitsprobleme [SECURITY.md](SECURITY.md).

## Lizenz

VoidStation steht unter der GNU General Public License v3.0 oder später (GPL-3.0-or-later), siehe [LICENSE](LICENSE).
Mitinstallierte Fremdsoftware (Void-Pakete, Bibata-Mauszeiger, Proton-GE, …) behält ihre eigenen Lizenzen.

Große Teile des Codes sind mit KI-Unterstützung (Claude von Anthropic) entstanden.
