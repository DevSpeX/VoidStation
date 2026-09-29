# Änderungen

Neueste Version oben. Die erste Überschrift bestimmt die Versionsnummer, die Geräte im Update-Dialog anzeigen.
Format: `## <Version> – <JJJJ-MM-TT>`, darunter Stichpunkte.
Jede Version steht auch in `CHANGELOG.en.md` (englisch) – sonst bricht `build.sh` ab.

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
