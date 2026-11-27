# Hilfe

Bedienung, Updates, Freigabe und die häufigsten Fragen. Fehlt etwas? Dann [frag in den Discussions](https://github.com/Panther92/VoidStation/discussions).

## Hilfe bekommen {#support}

- **Fragen, Ideen, Erfahrungen:** in den [Discussions auf GitHub](https://github.com/Panther92/VoidStation/discussions). Unter *Q&A* lassen sich Antworten als Lösung markieren, so finden andere sie später wieder.
- **Etwas funktioniert nicht:** als [Issue auf GitHub](https://github.com/Panther92/VoidStation/issues). Was dabei hilft, steht unter [Fehler melden](seite:contribute#fehler).

**Fehlerbericht:** Einstellungen → System → Fehlerbericht → **Bericht erstellen** (oder `vsctl report` im Terminal, geht auch per SSH, wenn die Oberfläche hängt) sammelt Version, Hardware und Protokolle in einer Textdatei in der Freigabe unter `vs-reports`. Passwörter, WLAN-Namen, die hintere Hälfte von MAC-Adressen, öffentliche IP-Adressen und E-Mail-Adressen sind entfernt. Verschickt wird nichts: Schau die Datei an (**Inhalt ansehen** oder vom PC aus) und häng sie an dein Issue. Die zehn neuesten Berichte bleiben liegen, ältere räumt VoidStation weg. `vsctl report --print` zeigt den Bericht nur an, ohne ihn zu speichern.

Zum Lesen brauchst du kein Konto, zum Schreiben ein kostenloses GitHub-Konto.

## Bedienung {#bedienung}

| | Controller | Tastatur | Maus |
|---|---|---|---|
| Bewegen | Steuerkreuz / linker Stick | Pfeiltasten | zeigen, Mausrad blättert |
| Öffnen / Auswählen | <kbd>A</kbd> | <kbd>Enter</kbd> | Klick |
| Zurück | <kbd>B</kbd> | <kbd>Esc</kbd> / Rücktaste | Rechtsklick |
| Programm schließen, Favorit | <kbd>X</kbd> / <kbd>Y</kbd> | <kbd>Entf</kbd>, <kbd>F</kbd>, <kbd>Y</kbd> | ✕ auf der Kachel |
| Gruppe vor / zurück | <kbd>RT</kbd> / <kbd>LT</kbd> | Bild ↓ / Bild ↑ | Pfeile oben rechts |
| Leiser / lauter | <kbd>LB</kbd> / <kbd>RB</kbd> | <kbd>−</kbd> / <kbd>+</kbd> | |
| Update öffnen (wenn unten rechts angezeigt) | <kbd>Select</kbd> | <kbd>U</kbd> | Klick auf den Hinweis |
| Ausschalten, Standby | <kbd>Start</kbd> | | ⏻ oben rechts |
| Zurück zur Startseite (aus jedem Programm) | <kbd>Guide</kbd> / Home | <kbd>Win</kbd> | Ecke unten rechts, dann **Startseite** |
| Programm schließen (aus dem Programm heraus) | | | Ecke unten rechts, dann **App schließen** |

**Standby** (⏻ → Standby, oder Einstellungen → System): Programme bleiben offen, das Radio geht aus. Aufwecken mit einer USB-Tastatur, -Maus oder einer Fernbedienung mit USB-Empfänger (Air-Mouse). Bluetooth weckt bewusst nicht – ein Controller verliert beim Einschlafen die Verbindung, und der Adapter hielt das für einen Weckruf. Nach dem Aufwachen verbindet sich der Controller von selbst wieder. Klappt das Wecken nicht, im BIOS/UEFI nach „Wake on USB“ o. Ä. schauen; wodurch das Gerät aufgewacht ist oder warum ein Standby abgebrochen wurde, steht in `~/.local/share/voidstation/launcher.log`.

Die Pfeile oben rechts erscheinen, sobald eine Seite breiter als der Bildschirm ist; der helle Punkt zeigt die aktuelle Gruppe. Gamepads per Bluetooth koppelst du unter **Einstellungen → Bluetooth**.

**Controller als Maus:** In Programmen wie Firefox/YouTube, FreeTube oder Discord bewegt der rechte Stick den Mauszeiger (je weiter, desto schneller), <kbd>R2</kbd> klickt (halten zieht), <kbd>L2</kbd> ist Rechtsklick, der linke Stick scrollt. In Spielen und Emulatoren ist das von selbst aus, weil Stick und Schultertasten dort zum Spiel gehören. <kbd>R3</kbd> (rechten Stick drücken) schaltet in jedem Programm um, ein kurzer Hinweis unten rechts zeigt den Stand. Ganz abschalten: **Einstellungen → System → Controller als Maus**.

## Fernsehen {#fernsehen}

Die Kachel *Fernsehen* öffnet die Senderliste mit Suche, Filtern nach Land und Thema und einer A–Z-Leiste. <kbd>A</kbd> schaltet einen Sender ein, danach bleibst du im Bild:

| | Controller | Tastatur / Fernbedienung | Maus |
|---|---|---|---|
| Sender weiter / zurück | ▲ / ▼ | ↑ / ↓, Bild ↑ / Bild ↓, CH+ / CH− | Pfeile oben rechts |
| Leiser / lauter | ◀ / ▶ | ← / →, <kbd>−</kbd> / <kbd>+</kbd> | Mausrad, − / + oben rechts |
| Info (Sender, Sendung jetzt und danach) | <kbd>A</kbd> | <kbd>Enter</kbd> | Klick |
| Senderliste (Liste, Favoriten, Zuletzt) | <kbd>X</kbd> | <kbd>L</kbd> | Doppelklick |
| Favorit an / aus | <kbd>Y</kbd> | <kbd>F</kbd> | ☆ oben rechts |
| Voriger Sender | <kbd>LB</kbd> / <kbd>RB</kbd> | | |
| Ton & Bild (Tonspur, Untertitel, Bildformat, Qualität) | <kbd>Start</kbd> | <kbd>M</kbd> | Menü oben rechts |
| Technik (Auflösung, Decoder, Darstellungsstufe) | <kbd>Select</kbd> | <kbd>I</kbd> | |
| Zur Startseite, Fernsehen läuft weiter | <kbd>Guide</kbd> | <kbd>Win</kbd> | ⊞ oben rechts |
| Fernsehen beenden | zweimal <kbd>B</kbd> | zweimal <kbd>Esc</kbd> | ✕ oben rechts |

Ist ein Sender nicht erreichbar, steht der Grund im Bild (gesperrt, Zeitüberschreitung, Stream gibt es nicht mehr, kein Internet). ▲ springt gleich zum nächsten, <kbd>A</kbd> versucht es noch einmal. In der Senderliste ist so ein Sender danach 24 Stunden lang mit ⚠ markiert. Startet das Fernsehen, geht das Radio aus.

## Videos & Musik {#medien}

Die Kachel *Videos & Musik* zeigt, was in der Freigabe unter `share/Videos` und `share/Musik` liegt, dazu eingesteckte USB-Laufwerke – mit Vorschaubildern und Album-Covern. Ganze Ordner spielst du mit *Alle abspielen*.

**Videos:**

| | Controller | Tastatur |
|---|---|---|
| Pause / weiter | <kbd>A</kbd> | <kbd>Enter</kbd>, Leertaste |
| 10 Sekunden zurück / vor | ◀ / ▶ | ← / → |
| 1 Minute zurück / vor | <kbd>LB</kbd> / <kbd>RB</kbd> | Bild ↓ / Bild ↑ |
| Leiser / lauter | ▼ / ▲ | ↓ / ↑, <kbd>−</kbd> / <kbd>+</kbd> |
| Ton & Untertitel | <kbd>Start</kbd> | <kbd>M</kbd> |
| Stopp – die Stelle wird gemerkt | <kbd>B</kbd> | <kbd>Esc</kbd> |

Unter *Weiterschauen* stehen angefangene Videos; beim nächsten Öffnen fragt VoidStation, ob es an der Stelle weitergehen soll.

**Musik:**

| | Controller | Tastatur |
|---|---|---|
| Pause / weiter | <kbd>A</kbd> | <kbd>Enter</kbd>, Leertaste |
| Voriger / nächster Titel | ◀ / ▶ | ← / → |
| 10 Sekunden zurück / vor | <kbd>LB</kbd> / <kbd>RB</kbd> | Bild ↓ / Bild ↑ |
| Leiser / lauter | ▼ / ▲ | ↓ / ↑ |
| Wiederholen umschalten | <kbd>Y</kbd> | <kbd>F</kbd> |
| Zufällige Reihenfolge | <kbd>X</kbd> | <kbd>L</kbd> |
| Menü *Wiedergabe* (Wiederholen, Reihenfolge, Ton, „Cover neu suchen“) | <kbd>Start</kbd> | <kbd>M</kbd> |
| Stopp | <kbd>B</kbd> | <kbd>Esc</kbd> |

*Wiederholen* funktioniert wie beim MP3-Player: **Weiter mit nächstem Ordner** (Standard – am Ende eines Albums geht es mit dem nächsten weiter, auch über Interpreten-Ordner hinweg), **Ordner wiederholen**, **Ordner, dann Stopp** und **Titel wiederholen**. Wahl und Reihenfolge bleiben gespeichert.

Mit <kbd>Guide</kbd> / <kbd>Win</kbd> oder *Start → Zur Startseite* (für Controller ohne Guide-Taste) geht es zur Startseite, ohne zu beenden: Musik spielt weiter, ein Video hält an. Die Kachel zeigt, was gerade läuft. Startet das Radio, hält die Musik an.

**Album-Cover** kommen von selbst: zuerst das in den Dateien eingebettete Bild, sonst sucht VoidStation Interpret und Album bei [MusicBrainz](https://musicbrainz.org) und lädt das Cover aus dem [Cover Art Archive](https://coverartarchive.org). Auf der Startseite der Mediathek:

- **Cover automatisch laden** (an/aus) – für die Ordner, die du gerade ansiehst.
- **Alle Cover laden** – geht die ganze Sammlung durch, mit Fortschritt.
- **Cover in Dateien speichern** (Standard aus) – schreibt gefundene Cover und fehlende Tags (Interpret, Titel, Album, Jahr, Titelnummer) in MP3-, M4A- und FLAC-Dateien, damit auch andere Player und das Handy sie sehen. Vorhandene Tags bleiben unangetastet.

### Musik suchen {#musik-suchen}

Unter *Herunterladen → Musik suchen* findest und lädst du Musik. Beim ersten Öffnen kreuzt du selbst an, wo gesucht wird – nichts ist vorausgewählt:

- **Freie Musik (Internet Archive):** Netlabels, Live-Mitschnitte und Alben unter Creative-Commons-Lizenz oder gemeinfrei, ganze Alben auf einmal.
- **YouTube** und **SoundCloud:** einzelne Titel als MP3. Bitte nur laden, was du laden darfst – die Nutzung erfolgt auf eigene Verantwortung, es gelten die Bedingungen der Plattform.

<kbd>Y</kbd> springt ins Suchfeld (mit Bildschirmtastatur), <kbd>A</kbd> lädt einen Treffer, <kbd>X</kbd> ändert die Quellen. Downloads laufen nacheinander, der Fortschritt steht am Treffer. Einzelne Titel bekommen Interpret, Album, Titelnummer, Jahr, Genre und Cover und landen unter `share/Musik/<Interpret>/<Album>/` (ohne Album unter `<Interpret>/Singles/`).

## Updates {#updates}

**Einstellungen → Updates → Aktualisieren** ist der einzige Update-Knopf. Er prüft und installiert alles in einem Durchgang: Void-Pakete (samt Kernel), Flatpaks, AppImages, Proton-GE und VoidStation selbst. Eigene Kacheln, Favoriten und Einstellungen bleiben erhalten.

- Die Geräte schauen kurz nach dem Start und dann alle sechs Stunden selbst nach. Eine neue VoidStation-Version meldet ein gelber Hinweis unten rechts sofort.
- Reine Systemupdates meldet der Hinweis erst, wenn das System seit 30, 60 oder 90 Tagen nicht aktualisiert wurde (Einstellungen → Updates, Standard 90).
- **Update-Kanal:** Alle Geräte bekommen *Stable*. Wer Fehler melden möchte, wechselt im Terminal mit `vsctl channel testing` auf den Entwicklerstand *Testing* (neue Versionen zuerst, ungeprüft); zurück mit `vsctl channel stable` – Updates kommen dann wieder, sobald Stable neuer ist.
- Im Terminal macht `vsctl update` dasselbe wie der Knopf. `sudo xbps-install -Su` aktualisiert nur die Void-Pakete – VoidStation erkennt das.

## Netzwerk {#netzwerk}

Einstellungen → Netzwerk zeigt, welche Verbindungen stehen; ✓ markiert die, über die das Internet gerade läuft.

- **WLAN verbinden und wechseln:** *Netze suchen*, dann ein Netz wählen. Das Passwort fragt VoidStation nur beim ersten Mal ab; danach genügt ein Klick, auch zum Wechseln zwischen zwei Netzen. Passt das gespeicherte Passwort nicht mehr, kommt die Abfrage von selbst.
- **Trennen:** *„Name“ trennen* oder ein Klick auf das verbundene Netz. Das WLAN bleibt aus, bis du wieder ein Netz wählst oder neu startest, das Passwort bleibt gespeichert. Das Kabel trennst und verbindest du unter *Verbindung*.
- **Internet bevorzugt über:** Sind Kabel und WLAN gleichzeitig verbunden, läuft das Internet über die gewählte Verbindung, praktisch etwa, wenn der Kabelanschluss streikt und ein Handy-Hotspot einspringt. Freigabe und Fernzugriff bleiben über beide erreichbar. Die Wahl erscheint nur auf Geräten mit Kabel- und WLAN-Anschluss.

## Freigabe: Dateien vom PC {#freigabe}

Jede VoidStation hat eine Windows-Freigabe. Am PC im Explorer `\\<rechnername>\share` eingeben (z. B. `\\wohnzimmer\share`) und mit Benutzername und Passwort aus der Installation anmelden. Dort hinein gehören Filme, Musik, Bilder und Spiele: Videos nach `share/Videos` und Musik nach `share/Musik` (beides zeigt die Kachel *Videos & Musik*), Spiele nach `share/ROMs/<System>`.

## Spiele und Emulatoren {#spiele}

Emulatoren gibt es im AppCenter unter *Emulatoren*. ROMs kommen in die Freigabe unter `share/ROMs/<System>`, zum Beispiel `gba`, `gbc`, `snes`, `nes`, `psx`, `psp`, `nds`, `gamecube` oder `dreamcast`. Die Emulator-Kachel zeigt dann eine Spieleliste; ohne Spiele startet der Emulator direkt. Game-Boy-Color-Spiele (`gbc`) zeigt die mGBA-Kachel zusammen mit `gba`; DOSBox Staging startet fertig eingerichtet mit `share/ROMs/dos` als Laufwerk C.

Ein laufendes Spiel gehört zur Kachel: Nach <kbd>Guide</kbd> / <kbd>Win</kbd> holt die Kachel es mit <kbd>A</kbd> zurück, <kbd>Y</kbd> oder *App schließen* in der Ecke beenden es. Solange die Startseite oder ein anderes Programm vorn ist, hält der Emulator an und läuft danach genau an der Stelle weiter (gilt nicht für Steam und Netzwerkspiele).

## Programmvorschau beim Fernsehen {#epg}

Laufende und nächste Sendung erscheinen beim Umschalten und mit <kbd>A</kbd> im Bild. Standardmäßig aus. Zum Einschalten die Adresse einer XMLTV-Datei (`.xml` oder `.xml.gz`) eintragen – sie wird täglich geladen:

```
echo 'https://…/epg.xml.gz' | sudo tee /usr/local/share/voidstation/epg-url
```

## Konten und Kindersicherung {#konten}

Unter **Einstellungen → Konten & Profile** lassen sich mehrere lokale Profile anlegen (**Eltern / Admin**, **Standard**, **Kind** und optional ein temporärer **Gast**). Favoriten, Verlauf, Mediathek-Fortschritt, Browser-Profile, Sprache und Erscheinungsbild bleiben je Profil getrennt; beim ersten Start nach dem Update übernimmt VoidStation bestehende Daten automatisch in das erste Admin-Konto.

- **Kindersicherung:** Kinder-Profile sperren standardmäßig Terminal, Dateimanager, Browser, AppCenter und Systemeinstellungen – sowohl in der Oberfläche als auch in der API. Je Kinder-Konto lassen sich Altersstufe, erlaubte/gesperrte Apps und Kategorien, ein Tageslimit sowie eine Ruhezeit festlegen; Eltern können mit ihrer PIN einmalig Apps freigeben oder Zeit verlängern.
- **Eltern-PIN erforderlich:** Ein Kinder-Konto lässt sich erst anlegen, wenn das Eltern-/Admin-Konto eine PIN oder ein Passwort hat, damit Kinder nicht einfach auf das Eltern-Konto wechseln können.
- **Grenzen des Kinderschutzes:** Die Kindersicherung richtet sich an die Nutzung am Wohnzimmer-Fernseher. Wer direkten Zugriff auf ein Terminal, eine Textkonsole (`Strg`+`Alt`+`F2`) oder SSH hat, handelt auf dem Gerät als Administrator und kann eine vergessene PIN ohne Anmeldung zurücksetzen (`vsctl account reset-pin`, `vsctl account unlock`). Sie ersetzt also keine Systemabschottung gegen lokalen Shell- oder SSH-Zugriff.

## Häufige Fragen {#faq}

### Brauche ich ein Konto?

Nein. VoidStation kennt keine Anmeldung bei irgendeinem Dienst. Nur Streaming-Apps wie Netflix wollen natürlich ihr eigenes Konto.

### Läuft das auf einem Raspberry Pi?

Nein, VoidStation läuft nur auf PCs: mit der normalen ISO auf 64-Bit-Rechnern (x86_64), mit der experimentellen 32-Bit-ISO von der [Download-Seite](seite:download) auch auf alten i686-Rechnern. Ein gebrauchter Mini-PC oder Büro-PC ist ideal.

### Kann ich Windows behalten?

Ja: Die Live-ISO installiert neben Windows (im UEFI-Modus). Vorher in Windows den Schnellstart ausschalten und Windows herunterfahren statt in den Ruhezustand zu schicken. Beim Start erscheint dann ein kurzes Auswahlmenü.

### Wo ist VLC hin?

„Videos & Musik“ ersetzt VLC; das Update entfernt VLC samt Kachel. Wer VLC für DVD-Menüs, Umwandeln oder exotische Formate braucht, holt es mit einem Klick zurück: **AppCenter → Medien → VLC**. Wer VLC schon selbst über das AppCenter installiert hatte, behält es.

### Cover fehlen oder sind falsch

Auf der Startseite der Mediathek **Alle Cover laden** wählen. Ist ein Cover falsch, im Musikbildschirm **Start → Wiedergabe → Weiteres → Cover neu suchen**: VoidStation nimmt heraus, was es selbst geschrieben hat (eigene Cover und Tags bleiben), und sucht neu. Am zuverlässigsten klappt die Suche mit Tags oder Dateinamen wie `Interpret - Titel.mp3`.

### Das Bild bleibt schwarz oder ruckelt

<kbd>Select</kbd> (bzw. <kbd>I</kbd>) im Player zeigt Auflösung, Decoder und Darstellungsstufe – bitte in jeden Fehlerbericht. Klappt die Darstellung auf einer Grafikkarte nicht, stuft VoidStation von selbst zurück, beim Fernsehen zuletzt bis zum einfachen Vollbild.

### Welche Sprachen gibt es?

Fünfzehn: Deutsch, English, Čeština, Español, Français, Italiano, Latviešu, Magyar, Nederlands, Polski, Português (Brasil), Slovenčina, Ελληνικά, Русский und Українська – **Einstellungen → Sprache**. Außer Deutsch und Englisch sind die Übersetzungen maschinell erstellt; Korrekturen gern als [Pull Request](seite:contribute#uebersetzen). Installer und Startmenü des Sticks sprechen ab der Live-ISO 2026.11 ebenfalls alle Sprachen.

### Eigene Programme als Kachel {#eigene-programme}

Programme, die du selbst installiert hast, erscheinen im AppCenter unter **Installiert → Auf diesem Gerät**. Dort legt **Kachel anlegen** eine Kachel an – Spiele landen in der Gruppe *Spiele*, alles andere unter *Programme*. Void-Pakete und Flatpaks bringen den nötigen Starteintrag (eine `.desktop`-Datei) selbst mit und tauchen dort von allein auf.

Ein **AppImage** braucht diesen Eintrag noch. Datei in die Freigabe legen, dann im Terminal (Name, Kurzname `ID` ohne Leerzeichen und Dateiname anpassen):

```
NAME="Mein Programm"; ID=meinprogramm
FILE=~/share/MeinProgramm-x86_64.AppImage

mkdir -p ~/Apps ~/.local/bin ~/.local/share/applications && cd ~/Apps
chmod +x "$FILE" && "$FILE" --appimage-extract
rm -rf "$ID" && mv squashfs-root "$ID"
printf '#!/bin/sh\nexec "%s" "$@"\n' "$HOME/Apps/$ID/AppRun" > ~/.local/bin/$ID
chmod +x ~/.local/bin/$ID
printf '[Desktop Entry]\nType=Application\nName=%s\nExec=%s\nCategories=Utility;\n' \
  "$NAME" "$HOME/.local/bin/$ID" > ~/.local/share/applications/$ID.desktop
```

Für ein Spiel `Categories=Game;` statt `Utility;` eintragen. Durch das Entpacken braucht das AppImage kein FUSE. Updates bekommen solche Programme nicht über VoidStation: neue Datei holen und die Befehle noch einmal ausführen.

### Die Oberfläche startet nicht – was nun?

Nach zwei Fehlstarts installiert VoidStation den Grafik-Server XLibre einmal neu. Klappt es dann immer noch nicht, erscheint eine Rettungskonsole. Dort hilft `sudo /usr/local/sbin/voidstation-pkg xserver status`.

### Wo finde ich Protokolle?

Unter `~/.local/share/voidstation/logs/`. Das Protokoll des Installers liegt während der Installation unter `/run/voidstation-installer/install.log` und lässt sich direkt auf einen USB-Stick speichern.

### Eigene Oberflächentöne {#eigene-toene}

Unter **Einstellungen → Ton → Oberflächentöne** wählst du einen der drei eingebauten Klangstile (**Void**, **Retro** oder **Minimal**), stellst ihre Lautstärke (1–100 %) ein oder schaltest die Töne ganz ab.

Eigene Tondateien (`.wav`, `.ogg`, `.flac`, `.oga`) im Ordner `~/.local/share/voidstation/sounds/` überschreiben die eingebauten Töne und bleiben bei Updates erhalten. Unterstützte Ereignisnamen sind `navigate`, `select`, `back`, `group`, `toggle`, `volume`, `notify`, `error`, `startup` und `shutdown` (z. B. `~/.local/share/voidstation/sounds/select.ogg`). Dateien in einem Unterordner des jeweiligen Stils (`void/`, `retro/`, `minimal/`) gelten nur für diesen Stil; eine leere 0-Byte-Datei schaltet gezielt ein einzelnes Ereignis stumm.

### 4K-Fernseher: nur 30 Hz oder kleinere Auflösung

Viele Fernseher stellen ihre HDMI-Anschlüsse ab Werk auf eine schmale Bandbreite. 4K gibt es dann höchstens mit 30 Hz, flüssig läuft es nur in kleinerer Auflösung. Abhilfe schafft eine Einstellung im Fernseher – für genau den Anschluss, an dem der VoidStation-PC hängt:

- **Samsung:** *Eingangssignal Plus*, bei Modellen ab 2025 *Externe Geräteverwaltung → Erweitertes Eingangssignal*, bis 2018 *HDMI UHD Color*
- **LG:** *HDMI ULTRA HD Deep Colour*
- **Sony:** *HDMI-Signalformat → Erweitertes Format*
- **Philips:** *HDMI Ultra HD → Optimal*

Bei anderen Marken heißt sie ähnlich (*HDMI 2.0*, *Erweitert*, *Enhanced*). Danach unter **Einstellungen → Anzeige** die volle Auflösung wählen. Klappt es trotzdem nicht, liegt es meist am Kabel: 4K mit 60 Hz braucht eines für 18 Gbit/s (*Premium High Speed*). Ob es geklappt hat, zeigt `xrandr` im Terminal – hinter `3840x2160` muss `60.00` stehen.

### Ist VoidStation ein offizielles Void-Linux-Projekt?

Nein. VoidStation ist ein eigenständiges Projekt, das auf Void Linux aufbaut. Fragen zu VoidStation bitte nicht an das Void-Team, sondern [in die Discussions](https://github.com/Panther92/VoidStation/discussions).
