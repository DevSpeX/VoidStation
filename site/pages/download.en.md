# Download

VoidStation comes as a live ISO to try out and install – or as a one-command installation from the official Void ISO.

{{iso}}

{{latest}}

## Requirements {#requirements}

- 64-bit PC (x86_64) – mini PC, older office PC or laptop
- at least 4 GB RAM and 16 GB on the SSD
- Secure Boot off (in the BIOS/UEFI setup)
- Intel, AMD or NVIDIA graphics (free nouveau driver)
- Internet for YouTube, TV, radio and updates – the live ISO's installer itself works offline

In UEFI mode, every installation option is available. In the older BIOS mode (Legacy/CSM, e.g. also VirtualBox and QEMU with default settings), “Use the whole SSD” is available.

Not included: the proprietary NVIDIA driver, Broadcom Wi-Fi, disk encryption and architectures other than x86_64 (so no Raspberry Pi).

## Installing with the live ISO {#install}

1. Download the ISO and check its checksum (see below).
2. Put it on a USB stick: simply copy it onto a [Ventoy](https://www.ventoy.net) stick, or write it with [Rufus](https://rufus.ie) or [balenaEtcher](https://etcher.balena.io).
3. Turn off Secure Boot on the PC and boot from the stick. In the boot menu, choose **VoidStation (English)** to try it out first, or go straight to **Install VoidStation (English)**.
4. Pick a path in the installer: **whole SSD**, **next to Windows or Linux** (the existing system is shrunk), **into free space** or **partition manually** with GParted.
5. Set up the account and device, then hold <kbd>A</kbd> or <kbd>Enter</kbd> for two seconds to confirm. After about five minutes, restart – done.

> If VoidStation is to live next to Windows, turn off **Fast Startup** in Windows first and shut Windows down properly (not hibernate). Otherwise the installer leaves the Windows partition alone, for good reason. With BitLocker, keep the recovery key at hand.

## Checking the checksum {#checksum}

This shows that the file arrived complete and unaltered. The result must match the SHA-256 sum above.

Windows (Command Prompt):

```
certutil -hashfile {{isofile}} SHA256
```

Linux:

```
sha256sum {{isofile}}
```

## Without the live ISO: from the official Void ISO {#void-iso}

1. Put the official [Void Linux ISO](https://voidlinux.org/download/) “base” for x86_64 (glibc) on a stick, turn off Secure Boot and boot from it.
2. Log in as `root` with the password `voidlinux` and type:

```
xbps-fetch https://voidstation.de/vs
bash vs
```

(On a German keyboard, run `loadkeys de` first.) The script asks for the target SSD, hostname, name and password and sets everything up – it picks the graphics driver for Intel, AMD or NVIDIA by itself.

> This path **erases the entire SSD**. Only the live ISO installs next to another system.

## On an existing Void Linux {#existing-void}

```
xbps-fetch https://voidstation.de/stable/dist/install.sh
sudo bash install.sh
```

With `sudo EFISTUB=1 bash install.sh`, the PC boots directly via EFISTUB afterwards.
