# Security policy

## Supported versions

| Version | Supported |
|---|---|
| newest version on the *Stable* channel | ✅ |
| newest version on the *Testing* channel | ✅ (fixes may land here first) |
| anything older | ❌ – please update under *Settings → Updates* |

Installations from an older live ISO are supported as soon as they have updated: VoidStation itself and all
Void packages come through the regular update, there is no need to reinstall.

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

- Preferred: [report it privately on GitHub](https://github.com/Panther92/VoidStation/security/advisories/new)
  (*Security* tab → *Report a vulnerability*).
- Alternatively by e-mail to **security@voidstation.de** with “VoidStation security” in the subject.

English or German is fine. Helpful details: the VoidStation version and channel (*Settings → Updates*),
what an attacker needs (local user, same network, physical access …), and steps to reproduce.

VoidStation is maintained in spare time, so there are no guaranteed reaction times. You can expect a first reply
within about a week. Fixes are published through the update channels; with your permission you will be credited
in the changelog.

## Scope

Especially interesting:

- **Update signing** – devices only install updates signed with the release key (`ssh-keygen -Y`, namespace
  `voidstation`, public key in `keys/voidstation-release.pub`).
- **Root helpers** – `voidstation-pkg` (passwordless `sudo`, installs only approved packages),
  `voidstation-efistub`, `voidstation-installer` and their sudoers rules.
- **Local services** – the launcher API on `127.0.0.1:8765`, the Samba share, SSH (switchable in *Settings → System*).
- **Live ISO** – the downloads are covered by a signed SHA-256 file, see
  [Verifying the download](README.md#verifying-the-download).

Not in scope: vulnerabilities in Void Linux packages or third-party apps themselves (Firefox, Steam, emulators …) –
please report those upstream. If VoidStation ships or configures them in an unsafe way, that is in scope.
