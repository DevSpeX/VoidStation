# Hilfe

Bedienung, Updates, Freigabe und die häufigsten Fragen. Fehlt etwas? Dann [frag in den Discussions](https://github.com/Panther92/VoidStation/discussions).

## Hilfe bekommen {#support}

- **Fragen, Ideen, Erfahrungen:** in den [Discussions auf GitHub](https://github.com/Panther92/VoidStation/discussions). Unter *Q&A* lassen sich Antworten als Lösung markieren, so finden andere sie später wieder.
- **Etwas funktioniert nicht:** als [Issue auf GitHub](https://github.com/Panther92/VoidStation/issues). Was dabei hilft, steht unter [Fehler melden](seite:contribute#fehler).

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
| Ausschalten | <kbd>Start</kbd> | | ⏻ oben rechts |
| Zurück zur Startseite (aus jedem Programm) | <kbd>Guide</kbd> / Home | <kbd>Win</kbd> | |

Die Pfeile oben rechts erscheinen, sobald eine Seite breiter als der Bildschirm ist; der helle Punkt zeigt die aktuelle Gruppe. Gamepads per Bluetooth koppelst du unter **Einstellungen → Bluetooth**.

## Updates {#updates}

**Einstellungen → Updates → Aktualisieren** ist der einzige Update-Knopf. Er prüft und installiert alles in einem Durchgang: Void-Pakete (samt Kernel), Flatpaks, AppImages, Proton-GE und VoidStation selbst. Eigene Kacheln, Favoriten und Einstellungen bleiben erhalten.

- Die Geräte schauen kurz nach dem Start und dann alle sechs Stunden selbst nach. Eine neue VoidStation-Version meldet ein gelber Hinweis unten rechts sofort.
- Reine Systemupdates meldet der Hinweis erst, wenn das System seit 30, 60 oder 90 Tagen nicht aktualisiert wurde (Einstellungen → Updates, Standard 90).
- **Update-Kanal:** *Stable* für alle oder *Testing*, wenn du neue Versionen zuerst haben möchtest.
- Im Terminal macht `vsctl update` dasselbe wie der Knopf. `sudo xbps-install -Su` aktualisiert nur die Void-Pakete – VoidStation erkennt das.

## Freigabe: Dateien vom PC {#freigabe}

Jede VoidStation hat eine Windows-Freigabe. Am PC im Explorer `\\<rechnername>\share` eingeben (z. B. `\\wohnzimmer\share`) und mit Benutzername und Passwort aus der Installation anmelden. Dort hinein gehören Filme, Musik, Bilder und Spiele.

## Spiele und Emulatoren {#spiele}

Emulatoren gibt es im AppCenter unter *Emulatoren*. ROMs kommen in die Freigabe unter `share/ROMs/<System>`, zum Beispiel `gba`, `snes`, `nes`, `psx`, `psp`, `nds`, `gamecube` oder `dreamcast`. Die Emulator-Kachel zeigt dann eine Spieleliste; ohne Spiele startet der Emulator direkt.

## Programmvorschau beim Fernsehen {#epg}

Standardmäßig aus. Zum Einschalten die Adresse einer XMLTV-Datei (`.xml` oder `.xml.gz`) eintragen – sie wird täglich geladen:

```
echo 'https://…/epg.xml.gz' | sudo tee /usr/local/share/voidstation/epg-url
```

## Häufige Fragen {#faq}

### Brauche ich ein Konto?

Nein. VoidStation kennt keine Anmeldung bei irgendeinem Dienst. Nur Streaming-Apps wie Netflix wollen natürlich ihr eigenes Konto.

### Läuft das auf einem Raspberry Pi?

Nein, nur auf 64-Bit-PCs (x86_64). Ein gebrauchter Mini-PC oder Büro-PC ist ideal.

### Kann ich Windows behalten?

Ja: Die Live-ISO installiert neben Windows (im UEFI-Modus). Vorher in Windows den Schnellstart ausschalten und Windows herunterfahren statt in den Ruhezustand zu schicken. Beim Start erscheint dann ein kurzes Auswahlmenü.

### Die Oberfläche startet nicht – was nun?

Nach zwei Fehlstarts installiert VoidStation den Grafik-Server XLibre einmal neu. Klappt es dann immer noch nicht, erscheint eine Rettungskonsole. Dort hilft `sudo /usr/local/sbin/voidstation-pkg xserver status`.

### Wo finde ich Protokolle?

Unter `~/.local/share/voidstation/logs/`. Das Protokoll des Installers liegt während der Installation unter `/run/voidstation-installer/install.log` und lässt sich direkt auf einen USB-Stick speichern.

### Ist VoidStation ein offizielles Void-Linux-Projekt?

Nein. VoidStation ist ein eigenständiges Projekt, das auf Void Linux aufbaut. Fragen zu VoidStation bitte nicht an das Void-Team, sondern [in die Discussions](https://github.com/Panther92/VoidStation/discussions).
