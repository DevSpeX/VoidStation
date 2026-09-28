# Änderungen

Neueste Version oben. Die erste Überschrift bestimmt die Versionsnummer, die Geräte im Update-Dialog anzeigen.
Format: `## <Version> – <JJJJ-MM-TT>`, darunter Stichpunkte.

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
