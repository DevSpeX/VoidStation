# Funktionen

Alles, was man vom Sofa aus braucht – auf einem kleinen PC am Fernseher, ohne Konto und ohne Werbung im System.

## Screenshots {#screenshots}

{{screens}}

## Oberfläche {#oberflaeche}

- Kacheln im Stil von Windows 8, in Gruppen sortiert – eigene Kacheln lassen sich ergänzen
- Bedienung mit Gamepad, Fernbedienung, Maus oder Tastatur; Xbox- und PlayStation-Controller (DualSense, DualShock) auch per Bluetooth
- Bildschirmtastatur für jedes Eingabefeld – auch in Firefox und auf YouTube
- Designs: Dunkel, Hell, Hoher Kontrast und Nord; eigene Designs als einzelne CSS-Datei
- Skalierung und Auflösung einstellbar, 60 Hz werden bevorzugt
- Deutsch oder Englisch, inklusive der gestarteten Programme
- Mehrere Programme gleichzeitig – mit <kbd>Guide</kbd> bzw. <kbd>Win</kbd> geht es aus jedem Programm zurück zur Startseite

## Fernsehen {#fernsehen}

- Frei empfangbare Sender aus aller Welt (Senderliste von [iptv-org](https://github.com/iptv-org/iptv)), mit Suche und Favoriten
- Programmvorschau mit laufender und nächster Sendung, sobald eine XMLTV-Quelle eingetragen ist
- Mediatheken von ARD, ZDF und ARTE sowie Pluto TV im AppCenter

## Radio {#radio}

- Zehntausende Sender über [radio-browser.info](https://www.radio-browser.info), mit Suche und Favoriten
- Die Radio-Kachel zeigt Sender und laufenden Titel – das Radio spielt weiter, während du andere Kacheln benutzt

## YouTube und Streaming {#streaming}

- YouTube im Vollbild (Firefox im Kioskmodus), auf Wunsch auch mit der TV-Oberfläche
- Netflix, Prime Video, Disney+, Joyn, RTL+ und Twitch aus dem AppCenter – Kopierschutz (Widevine) wird dafür eingeschaltet
- Kodi, Jellyfin, Plex HTPC, Spotify, FreeTube und VLC für die eigene Sammlung

## AppCenter {#appcenter}

60 ausgesuchte Apps in sieben Bereichen – installieren und entfernen mit einem Klick:

- **Gaming:** Steam mit Proton-GE, Heroic Games Launcher, Lutris, itch, Prism Launcher (Minecraft), Moonlight, Steam Link, Discord
- **Emulatoren:** DuckStation, PCSX2, PPSSPP, Dolphin, Cemu, Flycast, mGBA, melonDS, Azahar, Snes9x, Nestopia, Rosalie's Mupen GUI, MAME, DOSBox Staging, ScummVM, VICE, Stella, RetroArch
- **Spiele:** SuperTuxKart, SuperTux, Neverball, Luanti, Xonotic, Hedgewars, Battle for Wesnoth, OpenTTD
- **Medien, Streaming, Browser und Werkzeuge:** von Kodi bis LocalSend (Dateien vom Handy schicken)

Native Void-Pakete haben Vorrang; Flatpak oder AppImage gibt es nur, wo kein Void-Paket existiert. „Installiert“ zeigt alles auf dem Gerät – auch Programme aus dem Terminal.

## Spiele {#spiele}

- Steam nativ aus den Void-Paketquellen, Proton-GE wird automatisch aktuell gehalten
- Emulator-Kacheln zeigen die Spiele aus der Freigabe (`share/ROMs/<System>`) und starten sie direkt
- Spiele vom Gaming-PC streamen mit Moonlight oder Steam Link

## Updates {#updates}

- Ein Knopf für alles: Void-Pakete samt Kernel, Flatpaks, AppImages, Proton-GE und VoidStation selbst
- Updates von VoidStation sind signiert – Geräte installieren nur, was der Herausgeber unterschrieben hat
- Kanäle **Stable** (für alle) und **Testing** (neue Versionen zuerst)
- Kein tägliches Nachfragen: reine Systemupdates meldet VoidStation erst nach 30, 60 oder 90 Tagen; ein Neustart wird nur verlangt, wenn er nötig ist

## Unter der Haube {#technik}

- [Void Linux](https://voidlinux.org) (glibc, Rolling Release) mit runit, Openbox und PipeWire
- Grafik-Server [XLibre](https://github.com/X11Libre/xserver); startet die Oberfläche zweimal nicht, repariert VoidStation sich selbst, danach gibt es eine Rettungskonsole
- Startseite als schlanke WebKitGTK-Anwendung – rund 250 MB Arbeitsspeicher
- Windows-Freigabe `\\<rechner>\share` für Filme, Musik und ROMs; Fernzugriff per SSH auf Wunsch
- Live-ISO mit Installer im selben Kacheldesign: ganze SSD, neben Windows oder Linux, in freien Platz oder selbst einteilen
