# SPDX-License-Identifier: GPL-3.0-or-later
"""Strikter Profil- und Gast-Speicher unterhalb von ~/.local/share/voidstation/accounts/."""
from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import shutil
from pathlib import Path
from typing import Any

from .models import PROFILE_PREF_KEYS, ValidationError

SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
SAFE_FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
API_TOKEN_FILENAME = "voidstation-api.token"
API_TOKEN_HEADER = "X-VS-Token"
_API_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.-]{32,}$")


def default_runtime_dir() -> Path:
    env = os.environ.get("XDG_RUNTIME_DIR", "").strip()
    if env:
        return Path(env)
    return Path(f"/tmp/voidstation-runtime-{os.getuid()}")


def api_token_path(runtime_dir: Path | None = None) -> Path:
    """Pfad zum Laufzeit-API-Token ($XDG_RUNTIME_DIR/voidstation-api.token)."""
    base = Path(runtime_dir) if runtime_dir is not None else default_runtime_dir()
    return base / API_TOKEN_FILENAME


def read_api_token(runtime_dir: Path | None = None) -> str:
    """Liest das Laufzeit-API-Token sicher ein (ignoriert Symlinks)."""
    path = api_token_path(runtime_dir)
    try:
        if path.is_symlink() or not path.is_file():
            return ""
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def ensure_api_token(runtime_dir: Path | None = None) -> str:
    """Erzeugt oder laedt das Laufzeit-API-Token mit Rechten 0600."""
    path = api_token_path(runtime_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass

    if path.exists() and not path.is_symlink() and path.is_file():
        try:
            st = path.stat()
            if st.st_uid == os.getuid():
                existing = path.read_text(encoding="utf-8").strip()
                if _API_TOKEN_RE.fullmatch(existing):
                    os.chmod(path, 0o600)
                    return existing
        except OSError:
            pass

    if path.is_symlink():
        path.unlink(missing_ok=True)

    token = secrets.token_urlsafe(32)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(token + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return token


def verify_api_token(provided: str, expected: str) -> bool:
    """Vergleicht bereitgestelltes und erwartetes Laufzeit-Token konstantzeitlich."""
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided.strip(), expected)


def _ensure_private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def _atomic_write_json(path: Path, data: Any) -> None:
    _ensure_private_dir(path.parent)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


class ProfileStorage:
    """Verwaltet isolierte Profil-Ordner und fluchtige Gast-Daten."""

    def __init__(self, accounts_dir: Path, runtime_dir: Path | None = None) -> None:
        self.accounts_dir = Path(accounts_dir)
        self.data_dir = self.accounts_dir / "data"
        self.runtime_dir = Path(runtime_dir) if runtime_dir is not None else default_runtime_dir()
        self.guest_dir = self.runtime_dir / "voidstation-guest"

    def ensure_root(self) -> None:
        _ensure_private_dir(self.accounts_dir)
        _ensure_private_dir(self.data_dir)

    @staticmethod
    def _validate_id(account_id: str) -> str:
        if not isinstance(account_id, str) or not SAFE_ID_RE.fullmatch(account_id):
            raise ValidationError("account.err.invalid", "Invalid account id")
        return account_id

    @staticmethod
    def _validate_filename(filename: str) -> str:
        if (
            not isinstance(filename, str)
            or not SAFE_FILE_RE.fullmatch(filename)
            or "/" in filename
            or "\\" in filename
            or ".." in filename
        ):
            raise ValidationError("account.err.invalid", "Invalid profile filename")
        return filename

    def profile_dir(self, account_id: str, is_guest: bool = False) -> Path:
        if is_guest:
            return _ensure_private_dir(self.guest_dir)
        safe_id = self._validate_id(account_id)
        self.ensure_root()
        return _ensure_private_dir(self.data_dir / safe_id)

    def profile_file(self, account_id: str, filename: str, is_guest: bool = False) -> Path:
        safe_name = self._validate_filename(filename)
        pdir = self.profile_dir(account_id, is_guest=is_guest)
        return pdir / safe_name

    def browser_profile_dir(self, account_id: str, app_id: str, is_guest: bool = False) -> Path:
        safe_app = self._validate_id(app_id)
        pdir = self.profile_dir(account_id, is_guest=is_guest)
        browser_root = _ensure_private_dir(pdir / "browser")
        return _ensure_private_dir(browser_root / safe_app)

    def prefs_path(self, account_id: str, is_guest: bool = False) -> Path:
        return self.profile_file(account_id, "prefs.json", is_guest=is_guest)

    def load_raw_prefs(self, account_id: str, is_guest: bool = False) -> dict[str, Any]:
        p = self.prefs_path(account_id, is_guest=is_guest)
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {k: v for k, v in raw.items() if k in PROFILE_PREF_KEYS}

    def load_prefs(
        self,
        account_id: str,
        global_defaults: dict[str, Any] | None = None,
        is_guest: bool = False,
    ) -> dict[str, Any]:
        """Laedt Profil-Praeferenzen als Overlay ueber globale Defaults."""
        merged: dict[str, Any] = {}
        if global_defaults:
            for k in PROFILE_PREF_KEYS:
                if k in global_defaults:
                    merged[k] = global_defaults[k]
        merged.update(self.load_raw_prefs(account_id, is_guest=is_guest))
        return merged

    def save_prefs(
        self,
        account_id: str,
        updates: dict[str, Any],
        is_guest: bool = False,
    ) -> dict[str, Any]:
        """Speichert ausschliesslich erlaubte Profil-Praeferenzen in accounts/data/<id>/prefs.json."""
        cur = self.load_raw_prefs(account_id, is_guest=is_guest)
        for k, v in updates.items():
            if k in PROFILE_PREF_KEYS:
                cur[k] = v
        _atomic_write_json(self.prefs_path(account_id, is_guest=is_guest), cur)
        return cur

    def delete_profile_dir(self, account_id: str) -> None:
        safe_id = self._validate_id(account_id)
        target = self.data_dir / safe_id
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)

    def prepare_guest_dir(self) -> Path:
        self.cleanup_guest_dir()
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        return _ensure_private_dir(self.guest_dir)

    def cleanup_guest_dir(self) -> None:
        if self.guest_dir.exists():
            shutil.rmtree(self.guest_dir, ignore_errors=True)
