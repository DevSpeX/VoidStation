#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fehlerbericht: Version, Hardware und Protokolle in einer Textdatei unter ~/share/vs-reports.

Ueber die Freigabe erreichbar und zum Anhaengen an ein Issue auf GitHub gedacht. Verschickt wird nichts.

    python3 vsreport.py            Bericht speichern, Pfad ausgeben (vsctl report)
    python3 vsreport.py --print    Bericht nur ausgeben, nichts speichern (vsctl report --print)

Der Launcher ruft create() fuer Einstellungen → System → Fehlerbericht auf.

Entfernt wird, bevor etwas in die Datei kommt (Scrub, Platzhalter wie [removed], [Wi-Fi]): Passwoerter und Schluessel (key=wert, Tokens, Mullvad-
Kontonummern), WLAN-Namen (alle bekannten und sichtbaren Netze, ssid=…), die hintere Haelfte jeder MAC-Adresse,
oeffentliche IP-Adressen, E-Mail-Adressen und der Benutzerordner (-> ~). Gelesen werden nur die Dateien unten –
nie NetworkManager-Profile, wpa_supplicant, ~/.ssh, accounts/accounts.db oder Zugangsdaten. Seriennummern (DMI) bleiben draussen.
"""
from __future__ import annotations

import datetime
import ipaddress
import json
import os
import platform
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent              # ~/.local/share/voidstation
REPORT_DIR = Path.home() / "share" / "vs-reports"
PREFIX = "voidstation-report_"
KEEP = 10                                           # aeltere Berichte raeumt create() weg (nur eigene Dateien)
LOCK = threading.Lock()
API = "http://127.0.0.1:%s/api" % os.environ.get("VOIDSTATION_PORT", "8765")
MAX_LINE = 1000                                     # Zeichen je Zeile (Fortschrittsbalken, Binaerschrott)
# Pakete, deren Stand bei Fehlern meist zaehlt
PKGS = ("linux", "linux-firmware", "mesa", "mesa-dri", "xlibre-xserver", "xorg-server", "openbox", "pipewire",
        "wireplumber", "python3", "python3-pyside6", "qt6-base", "qt6-declarative", "mpv", "ffmpeg", "firefox",
        "NetworkManager", "bluez", "nvidia", "intel-ucode", "linux-firmware-amd", "flatpak")


# ---------------------------------------------------------------------------
#  Entfernen, was nicht in einen Bericht gehoert
# ---------------------------------------------------------------------------
_KEY = r"\w*(?:pass(?:word|wd|phrase)?|password[-_]?hash|passwort|kennwort|pin(?:[-_]?hash)?|psk|secret|token|" \
       r"(?:refresh|access|session|elevation)[-_]?token|x[-_]vs[-_]token|api[-_]?key|private[-_]?key|" \
       r"account(?:[-_ ]?(?:number|nr|id))?|kontonummer|wep[-_]?key\d?)\w*"
SECRET_KV = re.compile(r"(?i)(\b" + _KEY + r"[\"']?)(\s*[=:]\s*)(?!\[)(\"[^\"]*\"|'[^']*'|[^\s,;}\]]+)")
PHC_HASH = re.compile(r"\$vs-(?:scrypt|pbkdf2-sha256)\$[A-Za-z0-9$,=._+/-]+(?<![,.])")
BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
TOKENS = re.compile(r"\b(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|glpat-[A-Za-z0-9_-]{20,})")
URL_CRED = re.compile(r"(\b[a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@")          # https://user:pass@host
ACCOUNT = re.compile(r"(?<![\d.:/-])\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}(?![\d.:/-])")   # Mullvad: 16 Ziffern
SSID_KV = re.compile(r"(?i)(\be?ssid[\"']?)(\s*[=:]\s*|\s+)(?!\[)(\"[^\"]*\"|'[^']*'|[^\s,;]+)")
WLAN_LOG = re.compile(r"(\bWLAN: )(.+?)( -> )")                           # launcher.log: "WLAN: <Name> -> Fehler"
MAC = re.compile(r"\b([0-9A-Fa-f]{2}([:-])[0-9A-Fa-f]{2}\2[0-9A-Fa-f]{2})\2[0-9A-Fa-f]{2}\2[0-9A-Fa-f]{2}\2[0-9A-Fa-f]{2}\b")
MAC_BLUEZ = re.compile(r"\b(dev_[0-9A-Fa-f]{2}_[0-9A-Fa-f]{2}_[0-9A-Fa-f]{2})_[0-9A-Fa-f]{2}_[0-9A-Fa-f]{2}_[0-9A-Fa-f]{2}\b")
IPV4 = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])")
IPV6 = re.compile(r"(?<![\w:.])((?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4})(?![\w:])")
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
HOMEDIR = re.compile(r"/home/[^/\s'\"]+")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\r")


def _ip4(m: "re.Match[str]") -> str:
    try:
        return "[IP]" if ipaddress.IPv4Address(m.group(1)).is_global else m.group(0)
    except ValueError:
        return m.group(0)


def _ip6(m: "re.Match[str]") -> str:
    s = m.group(1)
    if s.count(":") < 2 or "::::" in s:
        return s
    try:
        return "[IPv6]" if ipaddress.IPv6Address(s).is_global else s
    except ValueError:
        return s


class Scrub:
    """Text bereinigen. ssids: Namen aller bekannten und sichtbaren WLANs (werden ueberall ersetzt)."""

    def __init__(self, ssids=()):
        # laengste zuerst ("Casa Luna 5G" vor "Casa Luna"); sehr kurze Namen wuerden normale Woerter treffen
        self.ssids = sorted({s for s in ssids if len(s.strip()) >= 3}, key=len, reverse=True)
        self.home = str(Path.home())

    def __call__(self, text: str) -> str:
        # Platzhalter englisch wie der ganze Bericht (geht an ein Issue auf GitHub)
        t = ANSI.sub("", text)
        if self.home not in ("/", ""):
            t = t.replace(self.home, "~")
        t = HOMEDIR.sub("~", t)
        for s in self.ssids:
            t = t.replace(s, "[Wi-Fi]")
        t = URL_CRED.sub(r"\1[removed]@", t)
        t = TOKENS.sub("[token]", t)
        t = BEARER.sub(r"\1 [removed]", t)
        t = ACCOUNT.sub("[number]", t)                  # vor SECRET_KV: "account: 1234 5678 …" ganz erfassen
        t = PHC_HASH.sub("[hash]", t)
        t = SECRET_KV.sub(r"\1\2[removed]", t)
        t = SSID_KV.sub(r"\1\2[Wi-Fi]", t)
        t = WLAN_LOG.sub(r"\1[Wi-Fi]\3", t)
        t = MAC.sub(lambda m: m.group(1) + (m.group(2) + "xx") * 3, t)
        t = MAC_BLUEZ.sub(r"\1_xx_xx_xx", t)
        t = EMAIL.sub("[e-mail]", t)
        t = IPV4.sub(_ip4, t)
        t = IPV6.sub(_ip6, t)
        return "\n".join(ln if len(ln) <= MAX_LINE else ln[:MAX_LINE] + " …" for ln in t.split("\n"))


# ---------------------------------------------------------------------------
#  Werte sammeln
# ---------------------------------------------------------------------------
def _env() -> dict[str, str]:
    env = dict(os.environ, LC_ALL="C", LANG="C")
    env.setdefault("DISPLAY", ":0")                                  # per SSH (vsctl report)
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")    # wpctl
    return env


def run(args: list[str], timeout: float = 8) -> str:
    """Ausgabe eines Befehls (stdout + stderr) oder "" – fehlende Programme sind kein Fehler."""
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=_env(),
                           stdin=subprocess.DEVNULL, errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (r.stdout + (("\n" + r.stderr) if r.stderr.strip() and r.returncode else "")).strip()


def read(p: Path | str, limit: int = 200_000) -> str:
    try:
        with open(p, "rb") as f:
            return f.read(limit).decode("utf-8", "replace").strip()
    except OSError:
        return ""


def mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def tail(p: Path, n: int) -> tuple[str, int]:
    """Letzte n Zeilen und Gesamtzahl der Zeilen (liest hoechstens die letzten 4 MB)."""
    try:
        size = p.stat().st_size
        with open(p, "rb") as f:
            f.seek(max(0, size - 4 * 1024 * 1024))
            data = f.read().decode("utf-8", "replace")
    except OSError:
        return "", 0
    lines = data.rstrip("\n").split("\n") if data.strip() else []
    return "\n".join(lines[-n:]), len(lines)


def ssids() -> list[str]:
    """Namen aller gespeicherten und sichtbaren WLANs (nur fuers Entfernen, kommen nie in den Bericht)."""
    out: set[str] = set()
    names = []
    for ln in run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"]).splitlines():
        name, _, typ = ln.replace("\\:", "\x00").rpartition(":")
        if typ in ("802-11-wireless", "wifi"):
            names.append(name.replace("\x00", ":"))
    out.update(names)
    for name in names[:40]:
        s = run(["nmcli", "-t", "-g", "802-11-wireless.ssid", "connection", "show", name], timeout=4)
        if s and "\n" not in s:
            out.add(s.replace("\\:", ":"))
    for ln in run(["nmcli", "-t", "-f", "SSID", "device", "wifi", "list", "--rescan", "no"]).splitlines():
        if ln.strip():
            out.add(ln.replace("\\:", ":"))
    for d in Path("/sys/class/net").glob("*/wireless"):              # gerade verbunden, falls nmcli fehlt
        s = run(["iw", "dev", d.parent.name, "link"], timeout=3)
        m = re.search(r"SSID: (.+)", s)
        if m:
            out.add(m.group(1).strip())
    return [s for s in out if s and s != "--"]


def version() -> dict[str, Any]:
    try:
        v = json.loads(read(BASE / "version.json") or "{}")
    except ValueError:
        v = {}
    ch = read("/usr/local/share/voidstation/channel").split("\n")[0]
    return {"version": v.get("version") or "?", "build": v.get("build") or "",
            "channel": {"stable": "Stable", "main": "Testing"}.get(ch, ch or "?"),
            "live": Path("/etc/voidstation-live").exists()}


def os_release() -> str:
    d = {}
    for ln in read("/etc/os-release").splitlines():
        k, _, v = ln.partition("=")
        d[k] = v.strip().strip('"')
    return d.get("PRETTY_NAME") or d.get("NAME") or "?"


def uptime() -> str:
    try:
        s = int(float(read("/proc/uptime").split()[0]))
    except (IndexError, ValueError):
        return "?"
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    return (f"{d} d " if d else "") + f"{h} h {s // 60} min"


def cpu() -> str:
    txt = read("/proc/cpuinfo", 2_000_000)
    model = next((ln.split(":", 1)[1].strip() for ln in txt.splitlines() if ln.startswith("model name")), platform.machine())
    cores = len({ln for ln in txt.splitlines() if ln.startswith("core id")}) or "?"
    return f"{model} ({cores} cores, {os.cpu_count() or '?'} threads)"


def memory() -> str:
    m = {}
    for ln in read("/proc/meminfo").splitlines():
        k, _, v = ln.partition(":")
        try:
            m[k] = int(v.split()[0]) // 1024
        except (IndexError, ValueError):
            pass
    swaps = [ln.split() for ln in read("/proc/swaps").splitlines()[1:] if ln.strip()]
    sw = ", ".join(f"{s[0]} {int(s[2]) // 1024} MB ({int(s[3]) // 1024} MB used)" for s in swaps if len(s) >= 4) or "none"
    return (f"{m.get('MemTotal', '?')} MB total, {m.get('MemAvailable', '?')} MB available\n"
            f"Swap:     {sw}")


def board() -> str:
    d = Path("/sys/class/dmi/id")
    parts = [read(d / f) for f in ("sys_vendor", "product_name", "board_name")]   # keine Seriennummern
    bios = " ".join(x for x in (read(d / "bios_version"), read(d / "bios_date")) if x)
    s = " / ".join(dict.fromkeys(x for x in parts if x)) or "?"
    return s + (f" (BIOS {bios})" if bios else "")


def pci() -> str:
    """Grafik, Ton, Netzwerk: lspci, sonst sysfs (IDs + Treiber)."""
    out = run(["lspci", "-nnk"])
    if out:
        keep, blocks = ("VGA", "3D", "Display", "Audio", "Ethernet", "Network", "Wireless", "USB controller"), []
        cur: list[str] = []
        for ln in out.splitlines():
            if ln and not ln[0].isspace():
                if cur:
                    blocks.append(cur)
                cur = [ln]
            elif cur and ("driver in use" in ln or "Kernel modules" in ln):
                cur.append(ln)
        if cur:
            blocks.append(cur)
        return "\n".join("\n".join(b) for b in blocks if any(k in b[0] for k in keep))
    lines = []
    for dev in sorted(Path("/sys/bus/pci/devices").glob("*")):
        cls = read(dev / "class")
        if not cls.startswith(("0x03", "0x0403", "0x02", "0x0c03")):
            continue
        drv = (dev / "driver").resolve().name if (dev / "driver").exists() else "-"
        lines.append(f"{dev.name} class {cls} [{read(dev / 'vendor')[2:]}:{read(dev / 'device')[2:]}] driver {drv}")
    return "\n".join(lines)


def usb() -> str:
    out = run(["lsusb"])
    if out:
        return re.sub(r"^Bus \d+ Device \d+: ", "", out, flags=re.M)
    lines = []
    for dev in sorted(Path("/sys/bus/usb/devices").glob("*")):
        if (dev / "idVendor").exists():
            lines.append(f"{read(dev / 'idVendor')}:{read(dev / 'idProduct')} {read(dev / 'manufacturer')} {read(dev / 'product')}".strip())
    return "\n".join(lines)


def inputs() -> str:
    names = re.findall(r'^N: Name="(.*)"', read("/proc/bus/input/devices"), flags=re.M)
    return "\n".join(dict.fromkeys(names))


def packages() -> str:
    lines = []
    for p in PKGS:
        v = run(["xbps-query", "-p", "pkgver", p], timeout=4)
        if v and "\n" not in v:
            lines.append(v)
    return "\n".join(lines)


def services() -> str:
    try:
        return " ".join(sorted(p.name for p in Path("/var/service").iterdir()))
    except OSError:
        return ""


def network() -> str:
    # ohne Spalte CONNECTION: dort stuende der WLAN-Name
    out = run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device"])
    if not out:
        out = "\n".join(f"{p.name}: {read(p / 'operstate')}" for p in sorted(Path("/sys/class/net").glob("*")))
    gen = run(["nmcli", "-t", "-f", "STATE,CONNECTIVITY,WIFI", "general"])
    return out + (f"\nGeneral: {gen}" if gen else "")


def settings() -> str:
    try:
        s = json.loads(read(BASE / "settings.json") or "{}")
    except ValueError:
        return "(unreadable)"
    if not isinstance(s, dict):
        return ""
    return "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in sorted(s.items()))


def launcher_status() -> str:
    try:
        with urllib.request.urlopen(API + "/status", timeout=2) as r:
            return json.dumps(json.load(r), ensure_ascii=False)
    except (OSError, ValueError) as e:
        return f"not reachable ({e.__class__.__name__})"


def files() -> str:
    """Welche Protokolle es gibt (Groesse, Zeit) – auch die, die nicht im Bericht stehen."""
    rows = []
    for p in sorted((BASE / "logs").glob("*"), key=mtime, reverse=True):
        try:
            st = p.stat()
        except OSError:
            continue
        rows.append(f"{datetime.datetime.fromtimestamp(st.st_mtime):%Y-%m-%d %H:%M}  {st.st_size:>9}  logs/{p.name}")
    return "\n".join(rows)


def root_logs() -> dict[str, str]:
    """Kernel-Meldungen (Fehler, Warnungen), Installer-Protokoll, socklog – ueber den Root-Helfer (sudo ohne
    Passwort). Fehlt der (alte Version), wenigstens dmesg als Benutzer."""
    out = run(["sudo", "-n", "/usr/local/sbin/voidstation-pkg", "syslog"], timeout=15)
    parts: dict[str, str] = {}
    if "@@ " in out:
        name = ""
        buf: list[str] = []
        for ln in out.splitlines():
            if ln.startswith("@@ "):
                if name:
                    parts[name] = "\n".join(buf).strip()
                name, buf = ln[3:].strip(), []
            else:
                buf.append(ln)
        if name:
            parts[name] = "\n".join(buf).strip()
    if not parts.get("dmesg"):
        d = run(["dmesg", "--level=emerg,alert,crit,err,warn", "-T"])
        if d and "Operation not permitted" not in d:
            parts["dmesg"] = "\n".join(d.splitlines()[-300:])
    live_log = Path("/run/voidstation-installer/install.log")      # Live-System: Installer-Protokoll
    if not parts.get("install.log") and os.access(live_log, os.R_OK):
        parts["install.log"], _ = tail(live_log, 300)
    return {k: v for k, v in parts.items() if v}


def logs() -> list[tuple[str, str, int]]:
    """(Name, Inhalt, Zeilen gesamt) der Protokolle, wichtigste zuerst."""
    out: list[tuple[str, str, int]] = []
    seen: set[Path] = set()

    def add(p: Path, n: int, name: str = "") -> None:
        if p in seen or not p.is_file():
            return
        seen.add(p)
        txt, total = tail(p, n)
        if txt:
            out.append((name or (str(p.relative_to(BASE)) if p.is_relative_to(BASE) else p.name), txt, total))

    lg = BASE / "logs"
    add(BASE / "launcher.log", 400)
    for name in ("update.log", "frontend.log", "home.log", "xserver-reparatur.log"):
        add(lg / name, 300 if name == "update.log" else 120)
    for p in sorted(lg.glob("xstart-fehler-*.log"), key=mtime, reverse=True)[:2]:
        add(p, 120)
    for name in ("pipewire.log", "wireplumber.log", "pipewire-pulse.log"):
        add(lg / name, 60)
    # Programme (logs/<kachel>.log): die acht zuletzt geschriebenen
    rest = [p for p in lg.glob("*.log") if p not in seen]
    for p in sorted(rest, key=mtime, reverse=True)[:8]:
        add(p, 120)
    # X-Server: Fehler und Warnungen, dazu das Ende
    xlog = next((p for p in (Path.home() / ".local/share/xorg/Xorg.0.log", Path("/var/log/Xorg.0.log")) if p.is_file()), None)
    if xlog:
        full, total = tail(xlog, 100000)
        ee = [ln for ln in full.splitlines() if "(EE)" in ln or "(WW)" in ln][-80:]
        end = "\n".join(full.splitlines()[-40:])
        out.append((xlog.name, "\n".join(ee) + ("\n…\n" if ee else "") + end, total))
    add(Path.home() / ".xsession-errors", 80, ".xsession-errors")
    for name, txt in root_logs().items():
        out.append((name, txt, txt.count("\n") + 1))
    return out


# ---------------------------------------------------------------------------
#  Bericht
# ---------------------------------------------------------------------------
def section(title: str, body: str) -> str:
    return f"\n== {title}\n{body.strip() or '-'}\n"


def build(status: Any = None) -> dict[str, Any]:
    """Bericht als Text. status: laufende Programme (Launcher reicht APPS.running() durch, sonst per HTTP)."""
    t0 = time.monotonic()
    scrub = Scrub(ssids())
    v = version()
    now = datetime.datetime.now().astimezone()
    host = socket.gethostname()
    head = ("VoidStation error report\n"
            "========================\n"
            f"Created:  {now:%Y-%m-%d %H:%M:%S %z}\n"
            f"Version:  {v['version']}" + (f" (Build {v['build']})" if v["build"] else "") + "\n"
            f"Channel:  {v['channel']}\n"
            f"System:   {'live system' if v['live'] else 'installed'}\n"
            f"Host:     {host}\n"
            "Removed:  passwords and keys, Wi-Fi names, second half of MAC addresses, public IP addresses,\n"
            "          e-mail addresses, the user's home folder (shown as ~).\n")
    st = json.dumps(status, ensure_ascii=False) if status is not None else launcher_status()
    xr = run(["xrandr", "--current"])
    overview = [
        head,
        section("System", "\n".join([
            f"OS:       {os_release()}",
            f"Kernel:   {platform.release()} {platform.machine()}",
            f"Cmdline:  {read('/proc/cmdline')}",
            f"Boot:     {'UEFI' if Path('/sys/firmware/efi').exists() else 'BIOS'}",
            f"Uptime:   {uptime()}  (load {' '.join(read('/proc/loadavg').split()[:3])})",
            f"Board:    {board()}",
            f"CPU:      {cpu()}",
            f"Memory:   {memory()}"])),
        section("PCI (graphics, audio, network)", pci()),
        section("Display (xrandr)", xr or "not available (no X server reachable)"),
        section("Disks", run(["lsblk", "-e7", "-o", "NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS,MODEL,TRAN"]) + "\n\n"
                + "\n".join(dict.fromkeys(run(["df", "-hT", "/", str(Path.home()), str(Path.home() / "share")]).splitlines()))),
        section("Audio (wpctl status)", run(["wpctl", "status"])),
        section("Network", network()),
        section("USB", usb()),
        section("Input devices", inputs()),
        section("Packages", packages()),
        section("Services (/var/service)", services()),
        section("VoidStation settings", settings()),
        section("Launcher (running programs)", st),
        section("Log files", files()),
    ]
    lg = logs()
    parts = overview + [section(f"Log: {name}" + (f" (last {txt.count(chr(10)) + 1} of {total} lines)"
                                                   if total > txt.count("\n") + 1 else ""), txt)
                        for name, txt, total in lg]
    text = scrub("".join(parts)) + "\n"
    return {"text": text, "overview": scrub("".join(overview)).strip(), "host": host, "time": now,
            "logs": [{"name": name, "lines": min(total, txt.count("\n") + 1)} for name, txt, total in lg],
            "seconds": round(time.monotonic() - t0, 1)}


def safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.") or "voidstation"


def cleanup(keep: int = KEEP) -> None:
    old = sorted(REPORT_DIR.glob(PREFIX + "*.txt"), key=mtime, reverse=True)
    for p in old[keep:]:
        try:
            p.unlink()
        except OSError:
            pass


def create(status: Any = None) -> dict[str, Any]:
    """Bericht nach ~/share/vs-reports schreiben. Rueckgabe: path, name, size, overview, logs, seconds.
    Laeuft schon einer (Knopf und vsctl zugleich): RuntimeError("busy")."""
    if not LOCK.acquire(blocking=False):
        raise RuntimeError("busy")
    try:
        r = build(status)
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        base = f"{PREFIX}{safe(r['host'])}_{r['time']:%Y-%m-%d_%H-%M-%S}"
        dest = REPORT_DIR / f"{base}.txt"
        n = 2
        while dest.exists():
            dest = REPORT_DIR / f"{base}-{n}.txt"
            n += 1
        tmp = dest.with_name("." + dest.name + ".tmp")              # erst fertig, dann in der Freigabe sichtbar
        tmp.write_text(r["text"], encoding="utf-8")
        os.replace(tmp, dest)
        cleanup()
        return {"path": str(dest), "name": dest.name, "size": dest.stat().st_size, "overview": r["overview"],
                "logs": r["logs"], "seconds": r["seconds"]}
    finally:
        LOCK.release()


def _de() -> bool:
    try:
        lang = json.loads(read(BASE / "settings.json") or "{}").get("lang") or ""
    except (ValueError, AttributeError):
        lang = ""
    return (lang or os.environ.get("LANGUAGE") or os.environ.get("LANG") or "").startswith("de")


def main(argv: list[str]) -> int:
    de = _de()
    if argv and argv[0] in ("-h", "--help"):
        print("vsctl report          " + ("Fehlerbericht nach ~/share/vs-reports speichern" if de else "save an error report to ~/share/vs-reports"))
        print("vsctl report --print  " + ("Bericht nur anzeigen, nichts speichern" if de else "only print the report, save nothing"))
        return 0
    if argv and argv[0] in ("-p", "--print"):
        sys.stdout.write(build()["text"])
        return 0
    if argv:
        print(("vsctl report: unbekannte Option " if de else "vsctl report: unknown option ") + argv[0], file=sys.stderr)
        return 2
    print("Erstelle Fehlerbericht …" if de else "Creating error report …", file=sys.stderr, flush=True)
    try:
        r = create()
    except RuntimeError:
        print("Es wird gerade schon ein Bericht erstellt." if de else "A report is already being created.", file=sys.stderr)
        return 1
    except OSError as e:
        print(("Speichern fehlgeschlagen: " if de else "Saving failed: ") + str(e), file=sys.stderr)
        return 1
    kb = max(1, round(r["size"] / 1024))
    print((f"Gespeichert ({kb} KB, ohne Passwörter und WLAN-Daten):" if de else
           f"Saved ({kb} KB, without passwords and Wi-Fi data):"))
    print(r["path"])
    print(("Über die Freigabe: share\\vs-reports\\" if de else "On the network share: share\\vs-reports\\") + r["name"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
