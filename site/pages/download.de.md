# Download

VoidStation gibt es als Live-ISO zum Ausprobieren und Installieren – oder als Ein-Befehl-Installation von der offiziellen Void-ISO aus.

{{iso}}

{{latest}}

## Voraussetzungen {#voraussetzungen}

- 64-Bit-PC (x86_64) – Mini-PC, älterer Büro-PC oder Laptop
- mindestens 4 GB RAM und 16 GB auf der SSD
- Secure Boot aus (im BIOS/UEFI-Setup)
- Grafik von Intel, AMD oder NVIDIA (freier Treiber nouveau)
- Internet für YouTube, Fernsehen, Radio und Updates – der Installer der Live-ISO selbst kommt ohne aus

Im UEFI-Modus stehen alle Installationswege offen. Im älteren BIOS-Modus (Legacy/CSM, z. B. auch VirtualBox und QEMU mit Standardeinstellungen) gibt es den Weg „ganze SSD“.

Nicht dabei: der proprietäre NVIDIA-Treiber, Broadcom-WLAN, Festplattenverschlüsselung und andere Architekturen als x86_64 (also kein Raspberry Pi).

## Installieren mit der Live-ISO {#installieren}

1. ISO herunterladen und die Prüfsumme kontrollieren (siehe unten).
2. Auf einen USB-Stick bringen: mit [Ventoy](https://www.ventoy.net) einfach auf den Stick kopieren, oder mit [Rufus](https://rufus.ie) bzw. [balenaEtcher](https://etcher.balena.io) schreiben.
3. Am PC Secure Boot ausschalten und vom Stick starten. Im Startmenü **VoidStation** wählen, um erst einmal auszuprobieren, oder gleich **VoidStation installieren**.
4. Im Installer den Weg wählen: **ganze SSD**, **neben Windows oder Linux** (das vorhandene System wird verkleinert), **in freien Platz** oder **selbst einteilen** mit GParted.
5. Konto und Gerät einrichten, zum Bestätigen <kbd>A</kbd> bzw. <kbd>Enter</kbd> zwei Sekunden halten. Nach etwa fünf Minuten neu starten – fertig.

> Soll VoidStation neben Windows laufen, in Windows vorher den **Schnellstart** ausschalten und Windows richtig herunterfahren (nicht in den Ruhezustand). Sonst lässt der Installer die Windows-Partition aus gutem Grund in Ruhe. Bei BitLocker den Wiederherstellungsschlüssel bereithalten.

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

## Ohne Live-ISO: von der offiziellen Void-ISO {#void-iso}

1. Die offizielle [Void-Linux-ISO](https://voidlinux.org/download/) „base“ für x86_64 (glibc) auf einen Stick bringen, Secure Boot ausschalten und davon starten.
2. Als `root` mit dem Passwort `voidlinux` anmelden und eintippen:

```
loadkeys de
xbps-fetch https://voidstation.de/vs
bash vs
```

Das Skript fragt Ziel-SSD, Rechnername, Name und Passwort ab und richtet alles ein – Grafiktreiber für Intel, AMD oder NVIDIA wählt es selbst.

> Dieser Weg **löscht die komplette SSD**. Neben einem anderen System installiert nur die Live-ISO.

## Auf ein bestehendes Void Linux {#bestehendes-void}

```
xbps-fetch https://voidstation.de/stable/dist/install.sh
sudo bash install.sh
```

Mit `sudo EFISTUB=1 bash install.sh` startet der Rechner danach direkt per EFISTUB.
