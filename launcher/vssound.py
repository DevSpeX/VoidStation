# SPDX-License-Identifier: GPL-3.0-or-later
"""
VoidStation System-Sounds (zweistufig: Standard-Presets + Nutzer-Overrides).

1. Nutzer-Overrides unter ~/.local/share/voidstation/sounds/ (ueberleben Updates):
   - <user_dir>/<preset>/<event>.{wav,ogg,flac,oga}
   - <user_dir>/<event>.{wav,ogg,flac,oga}
   Eine leere 0-Byte-Datei schaltet gezielt ein einzelnes Ereignis stumm.
2. Standard-Sounds unter launcher/web/sounds/<preset>/<event>.wav (mit Updates gepflegt).

Wiedergabe ueber pw-play (PipeWire), paplay (Pulse), aplay (ALSA, nur .wav) oder afplay (macOS-Preview).
Fehlt ein Backend oder schlaegt das Geraet fehl, bleibt alles stumm ohne Fehler oder UI-Verzoegerung.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

PRESETS = ("void", "retro", "minimal")
EVENTS = ("navigate", "select", "back", "group", "toggle", "volume", "notify", "error", "startup", "shutdown")
EXTS = (".wav", ".ogg", ".flac", ".oga")
DEFAULT_VOLUME = 70

COOLDOWNS: dict[str, float] = {
    "navigate": 0.060,
    "volume": 0.100,
    "group": 0.120,
    "select": 0.060,
    "back": 0.060,
    "toggle": 0.060,
    "notify": 0.200,
    "error": 0.200,
    "startup": 1.0,
    "shutdown": 1.0,
}
REPLACE_EVENTS = {"navigate", "volume", "group"}
NOTIFY_AFTER_TOGGLE_SUPPRESS = 0.160
MAX_ACTIVE = 3
AUDIO_BACKOFF_S = 3.0


def default_user_dir() -> Path:
    env = os.environ.get("VS_USER_SOUNDS", "").strip()
    if env:
        return Path(env)
    return Path.home() / ".local" / "share" / "voidstation" / "sounds"


def clamp_volume(val: Any, default: int = DEFAULT_VOLUME) -> int:
    try:
        n = int(round(float(val)))
    except (TypeError, ValueError):
        return default
    return max(1, min(100, n))


def normalize_preset(name: Any, default: str = "void") -> str:
    s = str(name or "").strip().lower()
    return s if s in PRESETS else default


def _headless_muted() -> bool:
    return (
        os.environ.get("VS_SOUNDS") == "0"
        or bool(os.environ.get("VS_KEYS"))
        or bool(os.environ.get("VS_SCREENSHOT"))
    )


def _boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


class SoundEngine:
    """Thread-sicherer Event-Audioplayer mit mtime-Cache, Rate-Limiting und Backoff."""

    def __init__(self, system_dir: Path, user_dir: Path | None = None):
        self.system_dir = Path(system_dir)
        self.user_dir = Path(user_dir) if user_dir is not None else default_user_dir()
        self.enabled = True
        self.volume = DEFAULT_VOLUME
        self.preset = "void"

        self._lock = threading.Lock()
        self._backend: str | None = None
        self._backend_checked = False
        self._dir_cache: dict[Path, tuple[int | None, dict[str, tuple[Path, int]]]] = {}
        self._last_played: dict[str, float] = {}
        self._last_toggle: float | None = None
        self._backoff_until: float = 0.0
        self._active: list[tuple[str, subprocess.Popen[bytes]]] = []

    def configure(
        self,
        enabled: bool | None = None,
        volume: int | None = None,
        preset: str | None = None,
    ) -> None:
        with self._lock:
            if enabled is not None:
                self.enabled = bool(enabled)
            if volume is not None:
                self.volume = clamp_volume(volume, self.volume)
            if preset is not None:
                self.preset = normalize_preset(preset, self.preset)

    def _scan_dir(self, d: Path) -> dict[str, tuple[Path, int]]:
        """Liest Sounddateien eines Ordners; neu gescannt nur bei geaenderter Ordner-mtime."""
        try:
            mtime_ns: int | None = d.stat().st_mtime_ns
        except OSError:
            mtime_ns = None
        cached = self._dir_cache.get(d)
        if cached is not None and cached[0] == mtime_ns:
            return cached[1]
        found: dict[str, tuple[Path, int]] = {}
        if mtime_ns is not None:
            entries: dict[str, tuple[Path, int]] = {}
            try:
                with os.scandir(d) as it:
                    for ent in it:
                        if not ent.is_file():
                            continue
                        p = Path(ent.path)
                        ext = p.suffix.lower()
                        if ext in EXTS:
                            try:
                                sz = ent.stat().st_size
                            except OSError:
                                sz = 0
                            entries[f"{p.stem}{ext}"] = (p, sz)
            except OSError:
                entries = {}
            for ev in EVENTS:
                for ext in EXTS:
                    hit = entries.get(f"{ev}{ext}")
                    if hit is not None:
                        found[ev] = hit
                        break
        self._dir_cache[d] = (mtime_ns, found)
        return found

    def resolve(self, event: str, preset: str | None = None) -> Path | None:
        """Loest User-Override -> Standard-Preset -> Fallback None auf (0-Byte = stumm)."""
        if event not in EVENTS:
            return None
        pr = normalize_preset(preset if preset is not None else self.preset)
        dirs = [
            self.user_dir / pr,
            self.user_dir,
            self.system_dir / pr,
        ]
        if pr != "void":
            dirs.append(self.system_dir / "void")
        for d in dirs:
            hit = self._scan_dir(d).get(event)
            if hit is not None:
                path, size = hit
                return None if size == 0 else path
        return None

    def custom_events(self, preset: str | None = None) -> list[str]:
        """Namen aller aktuell im Nutzer-Ordner ueberschriebenen Ereignisse."""
        with self._lock:
            pr = normalize_preset(preset if preset is not None else self.preset)
            over = set(self._scan_dir(self.user_dir)) | set(self._scan_dir(self.user_dir / pr))
            return [ev for ev in EVENTS if ev in over]

    def _detect_backend(self) -> str | None:
        if not self._backend_checked:
            self._backend_checked = True
            for cmd in ("pw-play", "paplay", "aplay", "afplay"):
                if shutil.which(cmd):
                    self._backend = cmd
                    break
        return self._backend

    def _build_cmd(self, backend: str, path: Path, volume: int) -> list[str] | None:
        gain = max(0.01, min(1.0, (volume / 100.0) ** 1.5))
        if backend == "pw-play":
            return ["pw-play", "--volume", f"{gain:.3f}", "--properties", "media.role=event", str(path)]
        if backend == "paplay":
            pa_vol = max(1, min(65536, int(round(gain * 65536))))
            return [
                "paplay",
                "--client-name=VoidStation",
                "--property=media.role=event",
                f"--volume={pa_vol}",
                str(path),
            ]
        if backend == "aplay":
            if path.suffix.lower() != ".wav":
                return None
            return ["aplay", "-q", str(path)]
        if backend == "afplay":
            return ["afplay", "-v", f"{gain:.3f}", str(path)]
        return None

    def _reap_locked(self) -> None:
        alive: list[tuple[str, subprocess.Popen[bytes]]] = []
        for ev, p in self._active:
            if p.poll() is None:
                alive.append((ev, p))
        self._active = alive

    def _reap_proc(self, ev: str, proc: subprocess.Popen[bytes]) -> None:
        rc = proc.wait()
        with self._lock:
            self._active = [(e, p) for e, p in self._active if p is not proc]
            if rc not in (0, -15, -9):  # SIGTERM/SIGKILL durch Replace ist kein Audiofehler
                self._backoff_until = time.monotonic() + AUDIO_BACKOFF_S

    def _prepare(self, event: str, *, force: bool = False) -> tuple[list[str], list[subprocess.Popen[bytes]]] | None:
        if event not in EVENTS or _headless_muted():
            return None
        now = time.monotonic()
        with self._lock:
            if not self.enabled:
                return None
            if not force and now < self._backoff_until:
                return None
            if not force:
                if event == "notify" and self._last_toggle is not None and (now - self._last_toggle) < NOTIFY_AFTER_TOGGLE_SUPPRESS:
                    return None
                cd = COOLDOWNS.get(event, 0.06)
                last = self._last_played.get(event)
                if last is not None and (now - last) < cd:
                    return None
            backend = self._detect_backend()
            if not backend:
                return None
            path = self.resolve(event)
            if path is None:
                return None
            cmd = self._build_cmd(backend, path, self.volume)
            if not cmd:
                return None

            self._reap_locked()
            to_kill: list[subprocess.Popen[bytes]] = []
            if event in REPLACE_EVENTS:
                keep: list[tuple[str, subprocess.Popen[bytes]]] = []
                for ev, p in self._active:
                    if ev == event:
                        to_kill.append(p)
                    else:
                        keep.append((ev, p))
                self._active = keep
            if len(self._active) >= MAX_ACTIVE:
                for idx, (ev, p) in enumerate(self._active):
                    if ev in REPLACE_EVENTS:
                        to_kill.append(p)
                        self._active.pop(idx)
                        break
                else:
                    return None

            self._last_played[event] = now
            if event == "toggle":
                self._last_toggle = now
            return cmd, to_kill

    def play(self, event: str, *, force: bool = False) -> bool:
        """Spielt ein Sound-Ereignis asynchron ab. Rueckgabe: ob ein Abspielvorgang gestartet wurde."""
        prep = self._prepare(event, force=force)
        if prep is None:
            return False
        cmd, to_kill = prep
        for p in to_kill:
            try:
                p.terminate()
            except OSError:
                pass
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            with self._lock:
                self._backoff_until = time.monotonic() + AUDIO_BACKOFF_S
            return False
        with self._lock:
            self._active.append((event, proc))
        threading.Thread(target=self._reap_proc, args=(event, proc), daemon=True).start()
        return True

    def play_sync(self, event: str, timeout: float = 1.4) -> bool:
        """Spielt ein Sound-Ereignis synchron ab (z. B. shutdown vor poweroff)."""
        prep = self._prepare(event, force=True)
        if prep is None:
            return False
        cmd, to_kill = prep
        for p in to_kill:
            try:
                p.terminate()
            except OSError:
                pass
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            proc.wait(timeout=timeout)
            return proc.returncode == 0
        except subprocess.TimeoutExpired:
            try:
                proc.terminate()
            except OSError:
                pass
            return False
        except OSError:
            return False

    def play_startup_once(
        self,
        wait_pipewire: float = 3.5,
        *,
        runtime_dir: Path | None = None,
        boot_id: str | None = None,
    ) -> None:
        """Spielt den Start-Ton genau einmal je Systemstart (ueberlebt kein Reboot, nicht bei vs.restart())."""
        if _headless_muted():
            return
        rt = runtime_dir if runtime_dir is not None else Path(
            os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/voidstation-runtime-{os.getuid()}"
        )
        mark = rt / "voidstation-started"
        bid = _boot_id() if boot_id is None else boot_id
        try:
            rt.mkdir(parents=True, exist_ok=True)
            if bid:
                try:
                    if mark.read_text(encoding="utf-8").strip() == bid:
                        return
                except OSError:
                    pass
                tmp = mark.with_name(f".{mark.name}.{os.getpid()}.tmp")
                tmp.write_text(bid + "\n", encoding="utf-8")
                os.replace(tmp, mark)
            else:
                fd = os.open(mark, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
        except FileExistsError:
            return
        except OSError:
            return

        def _worker() -> None:
            if sys.platform.startswith("linux"):
                sock = rt / "pipewire-0"
                deadline = time.monotonic() + wait_pipewire
                while not sock.exists() and time.monotonic() < deadline:
                    time.sleep(0.15)
            self.play("startup", force=True)

        threading.Thread(target=_worker, daemon=True).start()
