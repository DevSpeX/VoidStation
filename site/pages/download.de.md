# Download

VoidStation gibt es als Live-ISO: auf einen USB-Stick schreiben, davon starten, ausprobieren – und mit dem Installer im Kacheldesign auf die SSD bringen.

{{iso}}

{{latest}}

## Voraussetzungen {#voraussetzungen}

- 64-Bit-PC (x86_64) – Mini-PC, älterer Büro-PC oder Laptop
- mindestens 4 GB RAM und 16 GB auf der SSD
- Secure Boot aus (im BIOS/UEFI-Setup)
- Grafik von Intel oder AMD; NVIDIA mit dem freien Treiber nouveau oder – ab GeForce GTX 16xx und RTX 20xx – mit dem NVIDIA-Treiber
- USB-Stick ab 4 GB
- Internet für YouTube, Fernsehen, Radio und Updates – der Installer selbst kommt ohne aus

Im UEFI-Modus stehen alle Installationswege offen. Im älteren BIOS-Modus (Legacy/CSM, z. B. auch VirtualBox und QEMU mit Standardeinstellungen) gibt es den Weg „ganze SSD“.

Nicht dabei: Broadcom-WLAN, Festplattenverschlüsselung und andere Architekturen als x86_64 (also kein Raspberry Pi).

## Installieren {#installieren}

1. ISO herunterladen und die Prüfsumme kontrollieren (siehe unten).
2. Auf einen USB-Stick bringen: mit [Ventoy](https://www.ventoy.net) einfach auf den Stick kopieren, oder mit [Rufus](https://rufus.ie) bzw. [balenaEtcher](https://etcher.balena.io) schreiben.
3. Am PC Secure Boot ausschalten und vom Stick starten (Startmenü des PCs meist mit <kbd>F12</kbd>, <kbd>F11</kbd> oder <kbd>Esc</kbd>, am besten den Eintrag mit „UEFI:“ davor).
4. Im Startmenü des Sticks die Sprache wählen und dann **VoidStation Live starten**. Mit einer NVIDIA-Karte ab GTX 16xx / RTX 20xx **VoidStation Live starten (nur NVIDIA)** nehmen – dann bekommt auch das installierte System den NVIDIA-Treiber.
5. Das Live-System in Ruhe ausprobieren – installiert wird erst, wenn du es willst: Kachel **VoidStation installieren**.
6. Im Installer den Weg wählen: **ganze SSD**, **neben Windows oder Linux** (das vorhandene System wird verkleinert), **in freien Platz** oder **selbst einteilen** mit GParted.
7. Konto und Gerät einrichten, zum Bestätigen <kbd>A</kbd> bzw. <kbd>Enter</kbd> zwei Sekunden halten. Nach etwa fünf Minuten neu starten – fertig.

> Soll VoidStation neben Windows laufen, in Windows vorher den **Schnellstart** ausschalten und Windows richtig herunterfahren (nicht in den Ruhezustand). Sonst lässt der Installer die Windows-Partition aus gutem Grund in Ruhe. Bei BitLocker den Wiederherstellungsschlüssel bereithalten.

Nach der Installation kommen alle Updates über **Einstellungen → Updates** – die ISO brauchst du nur einmal.

## Prüfsumme kontrollieren {#pruefsumme}

So siehst du, dass die Datei vollständig und unverändert angekommen ist. Das Ergebnis muss mit der SHA-256-Summe oben übereinstimmen.

Windows (Eingabeaufforderung):

```
certutil -hashfile {{isofile}} SHA256
```

Linux:

```
sha256sum {{isofile}}
```

### Signatur prüfen (Linux) {#signatur}

Neben der ISO liegen auf SourceForge die Prüfsummendatei `.sha256` und ihre Signatur `.sha256.sig`. Mit dem öffentlichen Schlüssel des Projekts lässt sich prüfen, dass die Prüfsumme wirklich vom Herausgeber stammt:

```
curl -fsSL https://raw.githubusercontent.com/Panther92/VoidStation/stable/keys/voidstation-release.pub \
  | awk '{print "voidstation-release namespaces=\"voidstation\" "$1" "$2}' > voidstation-signers
ssh-keygen -Y verify -f voidstation-signers -I voidstation-release -n voidstation \
  -s {{isofile}}.sha256.sig < {{isofile}}.sha256
sha256sum -c {{isofile}}.sha256
```

Zweimal „Good“ bzw. „OK“ – dann passt alles.
