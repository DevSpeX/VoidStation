# Releasing VoidStation

How a change travels from a pull request to every device and onto the live ISO.
The tool for all of this is `tools/publish.sh` (alias `vspub`) on the maintainer's machine.

## Version numbers

VoidStation is built on Void Linux, a rolling release. So version numbers say **when** something was released,
not how big it is:

| Version | Meaning |
|---|---|
| `2026.11` | the release of November 2026 (a regular *release train*) |
| `2026.11.1`, `2026.11.2` | hotfixes to 2026.11 – or, rarely, a second train in the same month |
| `2026.11+testing.20261120` | what *Testing* devices show: the state after 2026.11, last change on 20 Nov 2026 |
| `0.1.0` … `0.15.0` | releases before the switch (October 2026), kept as they are |

The live ISO carries the number of the Stable version it contains, e.g. `voidstation-2026.11-20261109.iso`
(the second part is the build date – a respin with fresher Void packages keeps the version and gets a new date).
GitHub tags are `v<version>`.

Nobody types a version number by hand: `vspub --release` and `vspub --hotfix` assign it when releasing.

## Changelog

`CHANGELOG.md` (German) and `CHANGELOG.en.md` (English) have the same headings. New changes go under a section
at the very top:

```markdown
## Testing – 2026-11-20
- What users will notice, in one line
```

The date is the day of the latest change in that section. When releasing, `vspub` renames the section to
`## 2026.12 – <release date>`; changes that stay in Testing remain under `## Testing`. `build.sh` refuses to
build if the English section is missing, if `Testing` is not at the top or if versions are out of order.

## Channels

| Branch | Channel | Contents |
|---|---|---|
| `main` | *Testing* | everything merged – new features land here first |
| `stable` | *Stable* (default) | released versions only; written by `vspub --release` / `--hotfix`, never by hand |

**Testing only on request (since 2026.11).** The installer and the settings no longer offer a choice; every
installation runs on Stable. Testing is for the reference devices and for testers who report bugs, and is turned
on in the terminal of the device: `vsctl channel testing` (asks for confirmation, writes the marker
`/usr/local/share/voidstation/testing-optin`), back with `vsctl channel stable` – updates then resume once Stable
is newer than the device (`vs_state()` never offers an older version).

Devices that picked Testing earlier in the installer or the settings have no marker and return to Stable by
themselves: the update script does it as soon as `main` is at a released state (version without `+testing`,
i.e. right after a release), the launcher as soon as Stable is newer than the device. For the reference devices
this means: after a release they are on Stable too – put them back with `vsctl channel testing`.

## Who writes what

Only `vspub` on the publisher's machine builds and signs `dist/` – so code reaches `main` only through `vspub`.

| Change | Way in |
|---|---|
| Code, device files (`launcher/`, `iso/`, install/update scripts, changelog), `tools/`, `.github/` | Claude: branch `claude/<topic>` → `vsget` → `vspub`; otherwise bundle → `~/share/Updates` → `vspub` (or a pull request, merged and then published with `vspub`) |
| Pure documentation and website (`README*.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `RELEASING.md`, `site/`, `docs/screenshots/`) | may also be pushed to `main` directly; `site/` goes live on voidstation.de right away |
| `stable`, `dist/`, `keys/`, releases, hotfixes, ISO | `vspub --release` / `--hotfix` / `--iso` only, run by the publisher |

**Emergency signing key:** `keys/voidstation-notfall.pub` is a second public key; `build.sh` adds it to the
devices' `allowed_signers`. Its private key is kept offline. It only works on devices that already received an
update containing it. If the release key is lost, sign with it from a copy of the key:
`VS_KEY=/path/to/voidstation-notfall vspub` (the `.pub` file must lie next to the key).
Only these two file names count: a new file in `keys/` does not become a valid key.

`vspub` pulls in anything pushed directly to `main` before applying a bundle, so direct documentation pushes
don't get in its way.

**Claude branches and `vsget`:** Claude never pushes code to `main`. Each chat pushes its work to its own branch
`claude/<topic>`, based on the current `origin/main` (rebased before every push). On the publisher's machine,
`tools/vsget.sh` (alias `vsget`) lists the open `claude/*` branches, checks each one against the current GitHub state
(merges cleanly into `main`? touches `dist/` or `keys/`?), merges the chosen ones onto `main` and turns the result
into one bundle in `~/share/Updates`, then offers to run `vspub` right away. Several branches at once (`1,3`, `1-3`,
`alle`) mean one bundle, one build and one passphrase. Because every branch adds its entry at the top of
`CHANGELOG.md`/`CHANGELOG.en.md`, vsget keeps both sides there (Git's `union` merge driver, set only in vsget's own
helper repository) instead of reporting a conflict. A conflict in any other file is refused – the chat it came from
rebases the branch onto `origin/main` and pushes again. Branches already contained in `main` are offered for deletion. `vsget` only reads
from GitHub and writes the bundle; it never changes the local repository, so `vspub` stays the only way in.

```sh
echo "alias vsget='bash ~/VoidStation/tools/vsget.sh'" >> ~/.bashrc   # once, then log in again
vsget              # show open claude/* branches, fetch one as a bundle, optionally run vspub
vsget 2            # fetch branch no. 2 (or: vsget claude/<topic>)
vsget 1,3          # fetch several as one bundle (also: 1 3, 1-3, alle)
vsget --liste      # only show
```

**Building a bundle:** `tools/mkbundle.sh <folder>` – always cumulative (everything since the current GitHub
state, `origin/main..main`), always with the ref `refs/heads/main`, test-applied before it is written. Only the
newest bundle is needed; older ones in `~/share/Updates` can be deleted. Never build one by hand with `HEAD` or a
commit hash as the end point – `vspub` then fails with "Konnte Remote-Referenz main nicht finden".

## Release train (monthly)

Once a month – at the beginning of the month, usually on a Friday – *Stable* is updated:

1. **Feature freeze from the Monday of the release week.** The train takes what reached Testing before that
   Monday. Whatever arrives during the freeze (Monday up to the train) waits for the next one.
   Only changes that reach the devices count (`launcher/`, `iso/`, install/update scripts, keys, changelog) –
   website or tooling changes don't hold anything up.
   The freeze replaces the earlier rule of 14 days in Testing (decided on 14 Nov 2026).
2. **Checklist** before releasing, on both reference devices (Intel: Esprimo, AMD: NiPoGi):
   update from the previous Stable version, restart, start screen, YouTube, Settings → Updates.
   If the installer changed: a run in QEMU + OVMF.
3. **No blockers:** an open bug that came in with one of the changes stops that change (release an older state
   with `vspub --release <commit>` or fix it first).
4. **Nothing new before the freeze, no train.** No empty releases just because of the calendar.

**One-off exception for 2026.11** (decided on 29 Oct 2026): this train takes *everything* up to 6 Nov, so that
every device – Testing included – ends up on the same state; that is what lets former Testing devices return to
Stable without a downgrade. To keep the risk small: feature freeze on 3 Nov (only fixes after that), the
checklist also covers everything that came after 23 Oct, and the weekend until the ISO (Monday, 9 Nov) is the buffer for a
`2026.11.1` hotfix. Released with `vspub --release HEAD` (it warns about the young commits and asks).
From 2026.12 on the feature freeze described above applies.

```sh
vspub --status             # what's in Testing, since when, what goes along if the train leaves this week?
vspub --status 2026-12-04  # the same for a train on that day
vspub --release            # release everything that reached Testing before the freeze, as YYYY.MM
vspub --release <commit>   # release exactly this state (e.g. HEAD – warns about anything that came during the freeze)
```

`vspub --release` takes the Monday of the current week as the start of the freeze and shows that date before it
asks. If the train leaves in another week than planned (say, on the Monday after), name the planned day:
`VS_TRAIN=2026-12-04 vspub --release`.

`vspub --release` builds a release commit (changelog section renamed, `dist/` rebuilt and signed), pushes it to
`stable` and merges it back into `main`, so that `main` always contains `stable`. GitHub tag and release follow
automatically (`.github/workflows/release.yml`), as does the version news on voidstation.de.

## Hotfixes

A bug in *Stable* doesn't wait for the train:

1. The fix goes to *Testing* like everything else (`vspub`), with a changelog line under `## Testing`.
2. After 2–3 days on both reference devices: `vspub --hotfix <commit>` (several commits allowed).
   For a boot or update problem, it may go faster – `vspub` warns but lets you continue.
3. `vspub` applies just these commits to `stable`, moves their changelog lines into a new section
   (`## 2026.11.1 – …`) and merges back into `main`.

If the fix doesn't apply cleanly to *Stable* (because it builds on something only in Testing), `vspub` stops
without changing anything – then a separate version of the fix for Stable is needed.

## Live ISO (quarterly)

A new ISO every three months: **March, June, September, December**, on the day of that month's train or up to three days
after it, always **after** `vspub --release`. (Until November 2026 the months were February, May, August, November;
ISO 2026.11 was the last one in that rhythm, so the next one follows with 2026.12.) If a serious bug turns up in the new Stable version that also affects
new installations, the ISO waits for the hotfix; otherwise it goes out, and installed devices get later fixes as a
normal update.

1. Build **from `stable`**, never from Testing (the build script refuses a Testing state):

   ```sh
   git -C ~/VoidStation fetch -q origin
   git -C ~/VoidStation show origin/stable:dist/build-iso.sh > /var/tmp/build-iso.sh
   sudo bash /var/tmp/build-iso.sh
   ```

2. Test in QEMU + OVMF (UEFI) and BIOS mode, and install on real hardware (NiPoGi).
3. `vspub --iso` – checksum, signature, upload to SourceForge, download page on voidstation.de.

**Respin** outside the schedule when the ISO itself has a problem (installer bug, a Void update breaks the build,
important hardware support): same procedure, same version number, new build date.

## A quarter at a glance

| When | What |
|---|---|
| Monday of the release week | feature freeze begins |
| beginning of December | train → Stable 2026.12, then ISO 2026.12 (same day or up to three days later) |
| beginning of January | train → Stable 2027.01 (no ISO) |
| beginning of February | train → Stable 2027.02 (no ISO) |
| beginning of March | train → Stable 2027.03, then ISO 2027.03 |
| any time | hotfixes `.1`, `.2` … |

## Settings

`vspub` reads a few environment variables: `VS_TRAIN` (day of the release train as `YYYY-MM-DD`, default today;
the freeze starts on the Monday of that week), `VS_HOTFIX_DAYS` (default 2, e.g. shorter while testing the tool
itself), `VS_REPO`, `VS_INBOX`, `VS_KEY`.
