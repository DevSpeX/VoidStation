# Download

VoidStation comes as a live ISO: write it to a USB stick, boot from it, try it out – and put it on your SSD with the installer in the tile design.

{{iso}}

{{latest}}

## Requirements {#requirements}

- 64-bit PC (x86_64) – mini PC, older office PC or laptop
- at least 4 GB RAM and 16 GB on the SSD
- Secure Boot off (in the BIOS/UEFI setup)
- Intel or AMD graphics; NVIDIA with the free nouveau driver or – from GeForce GTX 16xx and RTX 20xx on – with the NVIDIA driver
- USB stick with 4 GB or more
- Internet for YouTube, TV, radio and updates – the installer itself works offline

In UEFI mode, every installation option is available. In the older BIOS mode (Legacy/CSM, e.g. also VirtualBox and QEMU with default settings), “Use the whole SSD” is available.

Not included: Broadcom Wi-Fi, disk encryption and architectures other than x86_64 (so no Raspberry Pi).

## Installing {#install}

1. Download the ISO and check its checksum (see below).
2. Put it on a USB stick: simply copy it onto a [Ventoy](https://www.ventoy.net) stick, or write it with [Rufus](https://rufus.ie) or [balenaEtcher](https://etcher.balena.io).
3. Turn off Secure Boot on the PC and boot from the stick (the PC's boot menu is usually <kbd>F12</kbd>, <kbd>F11</kbd> or <kbd>Esc</kbd>; preferably pick the entry starting with “UEFI:”).
4. In the stick's boot menu, choose the language and then **Start VoidStation Live**. With an NVIDIA card from GTX 16xx / RTX 20xx on, take **Start VoidStation Live (NVIDIA only)** – the installed system then gets the NVIDIA driver too.
5. Take your time trying out the live system – nothing is installed until you want it: tile **Install VoidStation**.
6. Pick a path in the installer: **whole SSD**, **next to Windows or Linux** (the existing system is shrunk), **into free space** or **partition manually** with GParted.
7. Set up the account and device, then hold <kbd>A</kbd> or <kbd>Enter</kbd> for two seconds to confirm. After about five minutes, restart – done.

> If VoidStation is to live next to Windows, turn off **Fast Startup** in Windows first and shut Windows down properly (not hibernate). Otherwise the installer leaves the Windows partition alone, for good reason. With BitLocker, keep the recovery key at hand.

After installation, all updates come through **Settings → Updates** – you only need the ISO once.

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

### Verifying the signature (Linux) {#signature}

Next to the ISO, SourceForge has the checksum file `.sha256` and its signature `.sha256.sig`. With the project's public key you can check that the checksum really comes from the publisher:

```
curl -fsSL https://raw.githubusercontent.com/Panther92/VoidStation/stable/keys/voidstation-release.pub \
  | awk '{print "voidstation-release namespaces=\"voidstation\" "$1" "$2}' > voidstation-signers
ssh-keygen -Y verify -f voidstation-signers -I voidstation-release -n voidstation \
  -s {{isofile}}.sha256.sig < {{isofile}}.sha256
sha256sum -c {{isofile}}.sha256
```

“Good” and “OK” – then everything checks out.
