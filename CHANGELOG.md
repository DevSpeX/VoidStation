# Änderungen

Neueste Version oben. Die erste Überschrift bestimmt die Versionsnummer, die Geräte im Update-Dialog anzeigen.
Format: `## <Version> – <JJJJ-MM-TT>`, darunter Stichpunkte.
Jede Version steht auch in `CHANGELOG.en.md` (englisch) – sonst bricht `build.sh` ab.

## 0.13.0 – 2026-10-03
- Neue Startseite als eigenes Programm (Python + Qt 6) statt Webseite in WebKit: zeichnet direkt auf der Grafikkarte – auch mit dem NVIDIA-Treiber und in 4K – und braucht weniger Arbeitsspeicher
- Alles wie gewohnt: Kacheln, Radio, Fernsehen mit Programmanzeige, Spiele, AppCenter, Einstellungen, Bildschirmtastatur und Themes, bedienbar mit Gamepad, Tastatur und Maus
- Einstellungen → System → Oberfläche: zwischen „Neu (Qt)“ und „Klassisch (Web)“ wechseln. Startet die neue Oberfläche dreimal nicht, geht es automatisch mit der klassischen weiter
- Live-System und Installer bleiben vorerst bei der Web-Oberfläche
## 0.12.1 – 2026-10-02
- Kein dunkler Bildschirm mehr beim Start: Bis die Startseite steht, zeigt sie das Logo mit Lade-Punkten – nahtlos nach dem Startbild beim Hochfahren
- Die Startseite startet früher (wartet nicht mehr auf Ton und Launcher), der Hintergrund ist von Anfang an dunkelgrau statt schwarz
- Live-ISO: Startbild mit Logo auch im BIOS-Modus (Legacy/CSM) statt Textmeldungen

## 0.12.0 – 2026-10-02
- Startseite mit NVIDIA-Karten: die Oberfläche wählt die passende Darstellung selbst (ohne DMA-BUF bei NVIDIA, ganz ohne GPU, wenn keine da ist) und schaltet nach wiederholten Abstürzen eine Stufe robuster – statt schwarzem Bild mit Mauszeiger
- Live-ISO: neues Startmenü mit Logo im Kacheldesign, nur noch „Start VoidStation Live“, „Start VoidStation Live (NVIDIA only)“ und „Reboot“ (UEFI und BIOS)
- Live-ISO: NVIDIA-Treiber an Bord (GeForce GTX 16xx, RTX 20xx und neuer) – lädt nur über „NVIDIA only“; der normale Eintrag nutzt nouveau mit GSP-Firmware
- Live-ISO: Startbild mit Logo beim Hochfahren
- Installer: wer über „NVIDIA only“ installiert, behält den NVIDIA-Treiber; sonst wird er samt DKMS und Compiler entfernt. Startbild und GParted bleiben auf dem Stick

## 0.11.1 – 2026-10-01
- Bildschirmtastatur öffnet sich bei jedem Eingabefeld, auch per Mausklick – und jetzt auch in Firefox/YouTube (Erweiterung „FX OSK“, funktioniert offline)
- PlayStation-Controller (DualSense/DualShock) per Bluetooth; Steuerkreuz funktioniert auch bei Controllern, die es als Achse melden
- Logos und Kacheln lassen sich nicht mehr versehentlich ziehen, kein Markieren von Text beim Bedienen
- Installer: Größenaufteilung neben einem anderen System lässt sich mit der Maus ziehen
- Danke an DevSpeX!

## 0.11.0 – 2026-10-01
- Installation auch im BIOS-Modus (Legacy/CSM): ältere PCs und virtuelle Maschinen mit Standardeinstellungen (VirtualBox, QEMU) brauchen kein UEFI mehr. Im BIOS-Modus gibt es den Weg „Ganze SSD“; neben anderen Systemen und „Selbst einteilen“ bleiben dem UEFI-Modus vorbehalten
- Eine im BIOS-Modus installierte SSD startet auch, wenn die Firmware später auf UEFI umgestellt wird (GRUB für beide Modi)
- Startmenü des Sticks auch im BIOS-Modus mit „VoidStation installieren“ und den englischen Einträgen
- Der Installer verlangt nur noch, dass Secure Boot aus ist; die Anleitung dazu ist kürzer

## 0.10.1 – 2026-10-01
- AppCenter: sichtbare Scrollbalken neben Kategorien und Apps – so sieht man, dass es weitergeht; die Kategorienliste blendet unten weich aus, wenn noch mehr kommt

## 0.10.0 – 2026-10-01
- AppCenter neu aufgebaut: links „Installiert“ und die Kategorien, rechts die Apps als Kacheln – die Liste scrollt nach unten statt zur Seite, die Spaltenzahl passt sich Auflösung und Skalierung an
- „Installiert“ zeigt alles auf dem Gerät auf einen Blick, nach Kategorien gegliedert – auch Programme, die außerhalb des AppCenters installiert wurden
- Bedienung: hoch / runter wechselt die Kategorie und zeigt sie gleich an, rechts geht in die Apps, links zurück; LT / RT (Bild ↑↓) springt von überall zur vorigen / nächsten Kategorie; Mausrad scrollt die Liste
- Viel mehr Auswahl (60 statt 22 Apps), weiterhin kuratiert:
  - Gaming: Heroic Games Launcher, Lutris, itch, Prism Launcher (Minecraft), Steam Link, Discord
  - Emulatoren: PCSX2 (PS2), Rosalie's Mupen GUI (N64), Azahar (3DS), Cemu (Wii U), MAME (Arcade)
  - Spiele: SuperTuxKart, SuperTux, Neverball, Luanti, Xonotic, Hedgewars, Battle for Wesnoth, OpenTTD
  - Medien: Jellyfin, Plex HTPC, Spotify, FreeTube, Strawberry; Kodi bringt jetzt Controller-Unterstützung und Streaming-Add-ons mit
  - Streaming: Netflix, Prime Video, Disney+, Joyn, RTL+, Pluto TV, Twitch
  - Browser: Firefox (normal mit Adressleiste), Chromium, Brave, LibreWolf
  - Werkzeuge: Mission Center, LocalSend (Dateien vom Handy schicken), AntiMicroX (Controller-Belegung)
- Streaming-Apps mit Kopierschutz (Netflix & Co.) schalten in ihrem Firefox-Profil Widevine ein
- AppCenter öffnet schneller: der Installationsstand wird mit je einem Aufruf für alle Apps geprüft statt einzeln

## 0.9.0 – 2026-10-01
- Updates an einer Stelle: Einstellungen → Updates → „Aktualisieren“ prüft und installiert alles in einem Durchgang – Void-Pakete (inkl. Kernel), Flatpaks, AppImages, Proton-GE und VoidStation selbst; was aktuell ist, wird übersprungen
- Das AppCenter hat keine Update-Knöpfe mehr, es ist nur noch fürs Installieren und Entfernen da
- Die Geräte prüfen jetzt auch Systemupdates (alle 6 Stunden). Neue VoidStation-Versionen melden sich sofort und bringen wartende Systemupdates mit; reine Systemupdates meldet der Hinweis unten rechts erst nach 30, 60 oder 90 Tagen (Standard 90, Einstellungen → Updates) – kein tägliches Nachfragen beim Rolling Release. Die Bestätigung listet alle Pakete
- Updates im Terminal (`sudo xbps-install -Su`) werden erkannt: erledigte Updates verschwinden aus der Anzeige, nach einem neuen Kernel erscheint „Neustart nötig“
- Neustart wird nur noch verlangt, wenn er wirklich nötig ist (neuer Kernel oder neue VoidStation-Version)
- Neu im Terminal: `vsctl update` macht dasselbe wie der Knopf in den Einstellungen, mit mitlaufendem Protokoll

## 0.8.3 – 2026-10-01
- Einstellungen passen sich jeder Auflösung und Skalierung an: lange Listen (WLAN, Bluetooth) scrollen mit, statt unter der Hinweiszeile zu verschwinden; lange Namen brechen um
- Seitentitel werden bei wenig Platz kleiner, statt sich mit den Blätter-Pfeilen zu überlappen
- Behoben: bei großer Skalierung (z. B. 2,25× bei 720p) konnte sich die Oberfläche beim Öffnen von Radio aufhängen (Endlosschleife beim Einpassen)

## 0.8.2 – 2026-10-01
- Einstellungen: die obere Kachelreihe wird nicht mehr abgeschnitten, der Fokusrahmen der unteren Reihe überdeckt nicht mehr die Hinweiszeile

## 0.8.1 – 2026-10-01
- Einstellungen übersichtlicher: eine Kachel je Bereich (Sprache, Anzeige, Design, Ton, Netzwerk, Bluetooth, Freigabe, Updates, System) – jede Kachel zeigt den aktuellen Stand, Esc / B führt zurück zur Übersicht
- Wartet ein Update, ist das auf der Kachel „Updates“ zu sehen; U / Select springt direkt dorthin

## 0.8.0 – 2026-09-30
- Designs: Dunkel, Hell, Hoher Kontrast und Nord – unter Einstellungen → Anzeige
- Bildschirmtastatur für Suchfelder und WLAN-Passwort – bedienbar mit Controller, Fernbedienung oder Tastatur
- Bluetooth: Kopfhörer und Controller in den Einstellungen suchen, koppeln, verbinden und entkoppeln (nach dem Update einmal neu starten)
- Spiele: Emulator-Kacheln zeigen die Spiele aus der Freigabe (share/ROMs/<System>) und starten sie direkt
- Fernsehen: Programmvorschau (EPG) mit laufender und nächster Sendung – sobald eine EPG-Quelle eingetragen ist
- Danke an DevSpeX für diese Version!

## 0.7.8 – 2026-09-29
- Installer: Benutzer- und Root-Passwort werden jetzt wirklich gesetzt – bisher blieben beide Konten ohne Passwort, sudo und su schlugen fehl; der Installer prüft das jetzt und bricht sonst ab
- Installiertes System: keine Begrüßung des Live-Sticks („root:voidlinux …“) mehr auf der Textkonsole

## 0.7.7 – 2026-09-29
- Installer: das Passwort für die Windows-Freigabe „share“ wird jetzt wirklich gesetzt – vorher blieb die Freigabe gesperrt (Fehler 0x80004005)
- Dialoge mit langem Text (z. B. „Was ist neu“): Text scrollt mit ↑ ↓, Mausrad oder Steuerkreuz, die Knöpfe bleiben immer sichtbar

## 0.7.6 – 2026-09-29
- Intel-PCs bekommen beim Start den aktuellen CPU-Microcode (intel-ucode) – behebt Hänger älterer Skylake-Geräte mit altem BIOS; auch in der Live-ISO

## 0.7.5 – 2026-09-29
- Installer: nach dem Halten erscheint sofort der Fortschritt (große Kachel mit Prozent, Schritten und Erklärung) – zurück geht es erst nach dem Neustart
- Installer fertig: nur noch „Jetzt neu starten“

## 0.7.4 – 2026-09-29
- Installer: „Löschen und installieren“ blieb hängen – behoben
- mGBA ist nicht mehr vorinstalliert, sondern im AppCenter (Spiele); vorhandene Installationen bleiben
- AppCenter: neuer Bereich „Auf diesem Gerät“ – im Terminal installierte Programme bekommen auf Wunsch eine Kachel
- Bildbetrachter (GPicView) mit schwarzem Hintergrund

## 0.7.3 – 2026-09-29
- Kein „Update“ mehr auf eine ältere Version (z. B. wenn Stable noch hinter dem installierten Stand liegt)
- Live-System: keine Update-Anzeige in den Einstellungen

## 0.7.2 – 2026-09-29
- ISO-Bau: das Einrichtungsskript des Live-Systems ist jetzt ausführbar (Abbruch bei Schritt 7/13 behoben)

## 0.7.1 – 2026-09-29
- ISO-Bau: Pakete, die es in den Void-Quellen nicht mehr gibt (z. B. mesa-vdpau), werden weggelassen statt den Bau abzubrechen

## 0.7.0 – 2026-09-29
- Grafik-Server ist nur noch XLibre – X.Org wird beim Update entfernt, die Auswahl in den Einstellungen entfällt
- Startet die Oberfläche zweimal nicht, wird XLibre einmal neu installiert; danach folgt eine Rettungskonsole
- Fernzugriff (SSH) lässt sich unter Einstellungen → System ein- und ausschalten
- Update-Kanäle heißen jetzt in beiden Sprachen „Stable“ und „Testing“
- htop, nano, fastfetch und der Editor Mousepad sind jetzt immer dabei
- Neu: Live-ISO mit Installer im Kacheldesign – ganze SSD, neben Windows oder Linux, in freien Platz oder selbst einteilen mit GParted

## 0.6.1 – 2026-09-28
- Programme wie VLC, Dateimanager und YouTube starten in der gewählten Sprache
- Pfeile oben rechts zeigen, dass es links oder rechts weitergeht; ein Punkt je Gruppe
- Gruppenweise blättern: LT / RT am Controller, Bild ↑ / Bild ↓ auf der Tastatur
- Update-Hinweis unten rechts mit gelbem Warndreieck – öffnen mit U oder Select am Controller

## 0.6.0 – 2026-09-28
- Sprache: Deutsch oder Englisch, umschaltbar unter Einstellungen → Sprache · Language
- „Was ist neu“ erscheint in der gewählten Sprache
- Uhrzeit, Datum und Zahlen im Format der gewählten Sprache
- Standard-Kacheln werden mitübersetzt, eigene Kachelnamen bleiben unverändert

## 0.5.1 – 2026-09-28
- Umzug nach GitHub (github.com/Panther92/VoidStation) – Geräte beziehen Updates ab jetzt von dort
- Kurzbefehl zur Neuinstallation: xbps-fetch https://panther92.github.io/VoidStation/vs

## 0.5.0 – 2026-09-28
- Grafik-Server: XLibre statt X.Org (Paketquelle xlibre-void, Schlüssel fest hinterlegt)
- Sicherheitsnetz: startet die Oberfläche zweimal nicht, schaltet VoidStation automatisch auf X.Org zurück
- Wahl zwischen XLibre und X.Org unter Einstellungen → System → Grafik-Server

## 0.4.0 – 2026-09-28
- Update-Kanäle: „Stabil“ für alle, „Test“ zum Ausprobieren neuer Versionen
- Updates sind signiert – Geräte installieren nur Updates mit gültiger Signatur
- Automatische Update-Prüfung mit Hinweis auf der Startseite
- Versionsnummern und „Was ist neu“ im Update-Dialog
- Lizenz: GPL-3.0

## 0.3.0 – 2026-09-28
- Update-Knopf: VoidStation aktualisiert sich über die Einstellungen selbst
- Steam nativ aus dem Void-Repo (nonfree + multilib) mit aktuellem Proton-GE
- Startbildschirm bleibt stehen, bis ein Programm wirklich ein Fenster zeigt
- Auflösung: 60 Hz bevorzugt, Halbbild-Modi (1080i) werden vermieden
- Auslagerungsdatei auf Rechnern mit weniger als 8 GB RAM

## 0.2.0 – 2026-09-27
- Neuer Name: VoidStation
- Neuinstallation einer ganzen SSD mit einem Befehl von der offiziellen Void-ISO
- Screenshots, Raster passen sich dem Platz über der Hinweiszeile an

## 0.1.0 – 2026-09-27
- Kacheloberfläche mit WebKit-Startseite, Radio, Fernsehen, AppCenter, Einstellungen
- Samba-Freigabe, dunkles Theme, großer Mauszeiger, EFISTUB
