# SPDX-License-Identifier: GPL-3.0-or-later
"""Datenmodelle, Konstanten und Fehlerklassen fuer das VoidStation-Account-System."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ROLES: tuple[str, ...] = ("admin", "standard", "child", "guest")
PERSISTENT_ROLES: tuple[str, ...] = ("admin", "standard", "child")
FACTORS: tuple[str, ...] = ("password", "pin")

PROFILE_FILES: tuple[str, ...] = (
    "radio.json",
    "tvfavs.json",
    "tvrecent.json",
    "resume.json",
    "yt-subs.json",
    "yt-history.json",
    "yt-later.json",
)

PROFILE_PREF_KEYS: tuple[str, ...] = (
    "lang",
    "theme",
    "scale",
    "cursor_theme",
    "cursor_size",
    "osk_layout",
    "osk_mode",
    "ui_sounds",
    "ui_sounds_volume",
    "ui_sounds_preset",
    "region",
)

DEFAULT_AVATARS: tuple[str, ...] = ("user", "star", "gamepad", "music", "tv", "smile")
DEFAULT_COLORS: tuple[str, ...] = ("#2d4a6b", "#2f6d4f", "#553a6e", "#74461f", "#6e2b3c", "#2b5b66")

GUEST_ACCOUNT_ID = "guest"


class AccountError(Exception):
    """Basisfehler mit i18n-Fehlercode fuer UI und API."""

    def __init__(self, code: str, message: str = "", retry_after: int = 0) -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.retry_after = int(retry_after)


class ValidationError(AccountError):
    """Ungueltige Eingabe (Name, Rolle, PIN-/Passwort-Format, Pfad)."""


class AuthError(AccountError):
    """Fehlgeschlagene Authentifizierung, Cooldown oder PIN-Sperre."""


class PolicyError(AccountError):
    """Verstoss gegen Rollen-, Invarianten- oder Kindersicherungsregeln."""


class NotFoundError(AccountError):
    """Konto nicht gefunden."""


@dataclass(slots=True)
class Account:
    """Oeffentliche Kontometadaten (niemals Passwort-/PIN-Hashes oder Tokens)."""

    id: str
    display_name: str
    role: str
    parent_id: str | None
    avatar: str
    color: str
    active: bool
    auto_login: bool
    created_at: int
    last_login_at: int
    has_password: bool = False
    has_pin: bool = False

    def to_public_dict(self) -> dict[str, Any]:
        """Liefert ausschliesslich unkritische Felder fuer UI/API/CLI."""
        return {
            "id": self.id,
            "display_name": self.display_name,
            "role": self.role,
            "parent_id": self.parent_id,
            "avatar": self.avatar,
            "color": self.color,
            "active": self.active,
            "auto_login": self.auto_login,
            "created_at": self.created_at,
            "last_login_at": self.last_login_at,
            "has_password": self.has_password,
            "has_pin": self.has_pin,
            "auth_configured": self.has_password or self.has_pin,
        }


@dataclass(slots=True)
class AuthResult:
    """Ergebnis einer Passwort- oder PIN-Pruefung."""

    ok: bool
    account_id: str
    factor: str
    error: str = ""
    retry_after: int = 0
    hard_locked: bool = False


@dataclass(slots=True)
class ThrottleState:
    """Persistenter Fehlversuchs- und Sperrstand je Konto und Faktor."""

    account_id: str
    factor: str
    failed_count: int = 0
    locked_until: int = 0
    last_failed_at: int = 0


@dataclass(slots=True)
class DevicePolicy:
    """Geraeteweite Anmelde- und Gast-Einstellungen."""

    ask_on_boot: bool = False
    guest_enabled: bool = False
    default_account_id: str = ""
    guest_allowed_tiles: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ask_on_boot": self.ask_on_boot,
            "guest_enabled": self.guest_enabled,
            "default_account_id": self.default_account_id,
            "guest_allowed_tiles": list(self.guest_allowed_tiles),
        }


@dataclass(slots=True)
class ParentalPolicy:
    """Kindersicherungsregeln eines Kontos."""

    account_id: str
    mode: str = "allowlist"
    allowed_tiles: tuple[str, ...] = ()
    blocked_tiles: tuple[str, ...] = ()
    blocked_cats: tuple[str, ...] = ()
    max_age_rating: int = 12
    daily_limit_min: int = 0
    bedtime_start: str = ""
    bedtime_end: str = ""
    allow_yt_search: bool = False
    allow_browser: bool = False
    allow_power_menu: bool = False
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "mode": self.mode,
            "allowed_tiles": list(self.allowed_tiles),
            "blocked_tiles": list(self.blocked_tiles),
            "blocked_cats": list(self.blocked_cats),
            "max_age_rating": self.max_age_rating,
            "daily_limit_min": self.daily_limit_min,
            "bedtime_start": self.bedtime_start,
            "bedtime_end": self.bedtime_end,
            "allow_yt_search": self.allow_yt_search,
            "allow_browser": self.allow_browser,
            "allow_power_menu": self.allow_power_menu,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, account_id: str, data: dict[str, Any]) -> ParentalPolicy:
        mode = str(data.get("mode") or "allowlist")
        if mode not in ("allowlist", "denylist"):
            mode = "allowlist"
        return cls(
            account_id=account_id,
            mode=mode,
            allowed_tiles=tuple(str(x) for x in (data.get("allowed_tiles") or ()) if str(x)),
            blocked_tiles=tuple(str(x) for x in (data.get("blocked_tiles") or ()) if str(x)),
            blocked_cats=tuple(str(x) for x in (data.get("blocked_cats") or ()) if str(x)),
            max_age_rating=max(0, int(data.get("max_age_rating", 12))),
            daily_limit_min=max(0, int(data.get("daily_limit_min", 0))),
            bedtime_start=str(data.get("bedtime_start") or ""),
            bedtime_end=str(data.get("bedtime_end") or ""),
            allow_yt_search=bool(data.get("allow_yt_search", False)),
            allow_browser=bool(data.get("allow_browser", False)),
            allow_power_menu=bool(data.get("allow_power_menu", False)),
            updated_at=int(data.get("updated_at") or 0),
        )


@dataclass(slots=True)
class SessionState:
    """Aktiver Sitzungszustand."""

    account_id: str
    display_name: str
    role: str
    avatar: str
    color: str
    is_guest: bool
    locked: bool
    picker_required: bool
    elevated_until: int = 0

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "display_name": self.display_name,
            "role": self.role,
            "avatar": self.avatar,
            "color": self.color,
            "is_guest": self.is_guest,
            "locked": self.locked,
            "picker_required": self.picker_required,
            "elevated_until": self.elevated_until,
        }


@dataclass(slots=True)
class MigrationReport:
    """Ergebnis einer einmaligen Legacy-Migration."""

    migrated: bool
    admin_id: str = ""
    display_name: str = ""
    copied_files: list[str] = field(default_factory=list)
    extracted_prefs: list[str] = field(default_factory=list)
