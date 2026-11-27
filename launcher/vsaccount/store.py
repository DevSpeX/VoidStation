# SPDX-License-Identifier: GPL-3.0-or-later
"""SQLite-Persistenz fuer Konten, Credentials, Throttling und Policies."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from .models import (
    DEFAULT_AVATARS,
    DEFAULT_COLORS,
    FACTORS,
    PERSISTENT_ROLES,
    Account,
    DevicePolicy,
    NotFoundError,
    ParentalPolicy,
    PolicyError,
    ThrottleState,
    ValidationError,
)

SCHEMA_VERSION = "1"
AUDIT_LIMIT = 200
BACKOFF_STEPS: tuple[int, ...] = (0, 0, 0, 15, 60, 300, 900)
PIN_HARD_LOCK_THRESHOLD = 8
_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

_ACCOUNTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL,
    parent_id TEXT,
    avatar TEXT NOT NULL,
    color TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    auto_login INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    last_login_at INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(parent_id) REFERENCES accounts(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS credentials (
    account_id TEXT NOT NULL,
    factor TEXT NOT NULL,
    hash TEXT NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY(account_id, factor),
    FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS auth_throttle (
    account_id TEXT NOT NULL,
    factor TEXT NOT NULL,
    failed_count INTEGER NOT NULL DEFAULT 0,
    locked_until INTEGER NOT NULL DEFAULT 0,
    last_failed_at INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(account_id, factor),
    FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS parental_policies (
    account_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    allowed_tiles_json TEXT NOT NULL,
    blocked_tiles_json TEXT NOT NULL,
    blocked_cats_json TEXT NOT NULL,
    max_age_rating INTEGER NOT NULL,
    daily_limit_min INTEGER NOT NULL,
    bedtime_start TEXT NOT NULL,
    bedtime_end TEXT NOT NULL,
    allow_yt_search INTEGER NOT NULL,
    allow_browser INTEGER NOT NULL,
    allow_power_menu INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS usage_daily (
    account_id TEXT NOT NULL,
    day TEXT NOT NULL,
    used_seconds INTEGER NOT NULL DEFAULT 0,
    bonus_seconds INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(account_id, day),
    FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    account_id TEXT,
    actor_id TEXT,
    event TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}'
);
"""


def _open_db(path: Path, schema: str) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    if not path.exists():
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
    else:
        os.chmod(path, 0o600)
    conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(schema)
    os.chmod(path, 0o600)
    return conn


class AccountStore:
    """Thread-sicherer SQLite-Store fuer accounts.db."""

    def __init__(self, accounts_dir: Path, clock: Callable[[], float] | None = None) -> None:
        self.accounts_dir = Path(accounts_dir)
        self.db_path = self.accounts_dir / "accounts.db"
        self._clock = clock or time.time
        self._lock = threading.RLock()
        self._conn = _open_db(self.db_path, _ACCOUNTS_SCHEMA)
        self._ensure_meta()

    def _now(self) -> int:
        return int(self._clock())

    def _ensure_meta(self) -> None:
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                self._conn.execute(
                    "INSERT OR IGNORE INTO meta(key, value) VALUES (?, ?)",
                    ("schema_version", SCHEMA_VERSION),
                )
                self._conn.execute(
                    "INSERT OR IGNORE INTO meta(key, value) VALUES (?, ?)",
                    ("device_id", uuid.uuid4().hex),
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def get_meta(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
            return str(row["value"]) if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )

    def get_device_policy(self) -> DevicePolicy:
        with self._lock:
            raw_tiles = self.get_meta("guest_allowed_tiles", "[]")
            try:
                tiles = tuple(str(x) for x in json.loads(raw_tiles) if str(x))
            except ValueError:
                tiles = ()
            return DevicePolicy(
                ask_on_boot=self.get_meta("ask_on_boot", "0") == "1",
                guest_enabled=self.get_meta("guest_enabled", "0") == "1",
                default_account_id=self.get_meta("default_account_id", ""),
                guest_allowed_tiles=tiles,
            )

    def set_device_policy(self, policy: DevicePolicy) -> DevicePolicy:
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                self.set_meta("ask_on_boot", "1" if policy.ask_on_boot else "0")
                self.set_meta("guest_enabled", "1" if policy.guest_enabled else "0")
                self.set_meta("default_account_id", policy.default_account_id)
                self.set_meta(
                    "guest_allowed_tiles",
                    json.dumps(list(policy.guest_allowed_tiles), ensure_ascii=False),
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
            return self.get_device_policy()

    def _row_to_account(self, row: sqlite3.Row) -> Account:
        creds = {
            r["factor"]
            for r in self._conn.execute(
                "SELECT factor FROM credentials WHERE account_id = ?",
                (row["id"],),
            ).fetchall()
        }
        return Account(
            id=str(row["id"]),
            display_name=str(row["display_name"]),
            role=str(row["role"]),
            parent_id=str(row["parent_id"]) if row["parent_id"] else None,
            avatar=str(row["avatar"]),
            color=str(row["color"]),
            active=bool(row["active"]),
            auto_login=bool(row["auto_login"]),
            created_at=int(row["created_at"]),
            last_login_at=int(row["last_login_at"]),
            has_password="password" in creds,
            has_pin="pin" in creds,
        )

    def list_accounts(self, include_inactive: bool = False) -> list[Account]:
        with self._lock:
            sql = "SELECT * FROM accounts"
            if not include_inactive:
                sql += " WHERE active = 1"
            sql += " ORDER BY CASE role WHEN 'admin' THEN 0 WHEN 'standard' THEN 1 ELSE 2 END, created_at ASC"
            return [self._row_to_account(r) for r in self._conn.execute(sql).fetchall()]

    def get_account(self, account_id: str) -> Account | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
            return self._row_to_account(row) if row else None

    def find_account(self, id_or_name: str) -> Account | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM accounts WHERE id = ?", (id_or_name,)).fetchone()
            if row:
                return self._row_to_account(row)
            rows = self._conn.execute(
                "SELECT * FROM accounts WHERE lower(display_name) = lower(?) AND active = 1",
                (id_or_name.strip(),),
            ).fetchall()
            return self._row_to_account(rows[0]) if len(rows) == 1 else None

    def _active_admin_count(self, exclude_id: str = "") -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM accounts WHERE role = 'admin' AND active = 1 AND id != ?",
            (exclude_id,),
        ).fetchone()
        return int(row["n"]) if row else 0

    def has_active_child_accounts(self) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM accounts WHERE role = 'child' AND active = 1 LIMIT 1"
            ).fetchone()
            return row is not None

    def _has_active_child_accounts(self) -> bool:
        return self.has_active_child_accounts()

    def create_account(
        self,
        display_name: str,
        role: str = "standard",
        parent_id: str | None = None,
        avatar: str | None = None,
        color: str | None = None,
        auto_login: bool = False,
        account_id: str | None = None,
    ) -> Account:
        name = str(display_name or "").strip()
        if not name or len(name) > 60:
            raise ValidationError("account.err.nameRequired", "Display name required")
        if role not in PERSISTENT_ROLES:
            raise ValidationError("account.err.invalid", f"Invalid role: {role}")

        with self._lock:
            if role == "child":
                if not parent_id:
                    raise PolicyError("account.err.parentRequired", "Child account requires parent admin")
                parent = self.get_account(parent_id)
                if not parent or not parent.active or parent.role != "admin":
                    raise PolicyError("account.err.parentRequired", "Parent must be an active admin")
                if not (parent.has_pin or parent.has_password):
                    raise PolicyError(
                        "account.err.parentAuthRequired",
                        "Parent PIN or password required before creating a child account",
                    )
            else:
                parent_id = None

            aid = account_id or uuid.uuid4().hex[:12]
            existing_count = len(self.list_accounts(include_inactive=True))
            chosen_avatar = avatar if avatar in DEFAULT_AVATARS else DEFAULT_AVATARS[existing_count % len(DEFAULT_AVATARS)]
            chosen_color = color if (color and color.startswith("#")) else DEFAULT_COLORS[existing_count % len(DEFAULT_COLORS)]
            now = self._now()

            self._conn.execute("BEGIN")
            try:
                if auto_login:
                    self._conn.execute("UPDATE accounts SET auto_login = 0")
                self._conn.execute(
                    "INSERT INTO accounts (id, display_name, role, parent_id, avatar, color, active, auto_login, created_at, last_login_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, 0)",
                    (aid, name, role, parent_id, chosen_avatar, chosen_color, 1 if auto_login else 0, now),
                )
                if role == "child":
                    self._insert_default_parental(aid, now)
                if not self.get_meta("default_account_id"):
                    self.set_meta("default_account_id", aid)
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
            acc = self.get_account(aid)
            assert acc is not None
            return acc

    def _insert_default_parental(self, account_id: str, now: int) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO parental_policies "
            "(account_id, mode, allowed_tiles_json, blocked_tiles_json, blocked_cats_json, "
            "max_age_rating, daily_limit_min, bedtime_start, bedtime_end, "
            "allow_yt_search, allow_browser, allow_power_menu, updated_at) "
            "VALUES (?, 'allowlist', '[]', '[\"terminal\",\"files\"]', '[\"Werkzeuge\"]', 12, 0, '', '', 0, 0, 0, ?)",
            (account_id, now),
        )

    def update_account(
        self,
        account_id: str,
        display_name: str | None = None,
        role: str | None = None,
        parent_id: str | None = None,
        avatar: str | None = None,
        color: str | None = None,
        active: bool | None = None,
        auto_login: bool | None = None,
    ) -> Account:
        with self._lock:
            cur = self.get_account(account_id)
            if not cur:
                raise NotFoundError("account.err.notFound", "Account not found")

            new_name = cur.display_name if display_name is None else str(display_name).strip()
            if not new_name or len(new_name) > 60:
                raise ValidationError("account.err.nameRequired", "Display name required")

            new_role = cur.role if role is None else role
            if new_role not in PERSISTENT_ROLES:
                raise ValidationError("account.err.invalid", f"Invalid role: {new_role}")

            new_active = cur.active if active is None else bool(active)
            if cur.role == "admin" and cur.active and (new_role != "admin" or not new_active):
                if self._active_admin_count(exclude_id=account_id) < 1:
                    raise PolicyError("account.err.lastAdmin", "Cannot demote or disable last admin")

            new_parent = cur.parent_id if parent_id is None else parent_id
            if new_role == "child":
                if not new_parent:
                    raise PolicyError("account.err.parentRequired", "Child account requires parent admin")
                parent = self.get_account(new_parent)
                if not parent or not parent.active or parent.role != "admin" or parent.id == account_id:
                    raise PolicyError("account.err.parentRequired", "Parent must be another active admin")
                if not (parent.has_pin or parent.has_password):
                    raise PolicyError(
                        "account.err.parentAuthRequired",
                        "Parent PIN or password required for child account",
                    )
            else:
                new_parent = None

            if avatar is not None and avatar not in DEFAULT_AVATARS:
                raise ValidationError("account.err.invalid", "Invalid avatar")
            if color is not None and not _HEX_COLOR_RE.fullmatch(str(color)):
                raise ValidationError("account.err.invalid", "Invalid color")
            new_avatar = cur.avatar if avatar is None else avatar
            new_color = cur.color if color is None else color
            new_auto = cur.auto_login if auto_login is None else bool(auto_login)
            if new_auto and (cur.has_pin or cur.has_password):
                new_auto = False

            self._conn.execute("BEGIN")
            try:
                if new_auto:
                    self._conn.execute("UPDATE accounts SET auto_login = 0")
                self._conn.execute(
                    "UPDATE accounts SET display_name = ?, role = ?, parent_id = ?, avatar = ?, color = ?, active = ?, auto_login = ? WHERE id = ?",
                    (
                        new_name,
                        new_role,
                        new_parent,
                        new_avatar,
                        new_color,
                        1 if new_active else 0,
                        1 if new_auto else 0,
                        account_id,
                    ),
                )
                if new_role == "child":
                    self._insert_default_parental(account_id, self._now())
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
            updated = self.get_account(account_id)
            assert updated is not None
            return updated

    def delete_account(self, account_id: str) -> None:
        with self._lock:
            cur = self.get_account(account_id)
            if not cur:
                raise NotFoundError("account.err.notFound", "Account not found")
            if cur.role == "admin" and cur.active and self._active_admin_count(exclude_id=account_id) < 1:
                raise PolicyError("account.err.lastAdmin", "Cannot delete last admin")

            self._conn.execute("BEGIN")
            try:
                self._conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
                if self.get_meta("default_account_id") == account_id:
                    rem = self.list_accounts()
                    self.set_meta("default_account_id", rem[0].id if rem else "")
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def set_credential_hash(self, account_id: str, factor: str, digest: str) -> None:
        if factor not in FACTORS:
            raise ValidationError("account.err.invalid", "Invalid factor")
        with self._lock:
            if not self.get_account(account_id):
                raise NotFoundError("account.err.notFound", "Account not found")
            now = self._now()
            self._conn.execute("BEGIN")
            try:
                self._conn.execute(
                    "INSERT INTO credentials(account_id, factor, hash, updated_at) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(account_id, factor) DO UPDATE SET hash = excluded.hash, updated_at = excluded.updated_at",
                    (account_id, factor, digest, now),
                )
                self._conn.execute(
                    "UPDATE accounts SET auto_login = 0 WHERE id = ?",
                    (account_id,),
                )
                self._conn.execute(
                    "DELETE FROM auth_throttle WHERE account_id = ? AND factor = ?",
                    (account_id, factor),
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def remove_credential(self, account_id: str, factor: str) -> None:
        if factor not in FACTORS:
            raise ValidationError("account.err.invalid", "Invalid factor")
        with self._lock:
            acc = self.get_account(account_id)
            if not acc:
                raise NotFoundError("account.err.notFound", "Account not found")
            if acc.role != "child":
                leaves_unprotected = (factor == "pin" and not acc.has_password) or (
                    factor == "password" and not acc.has_pin
                )
                if leaves_unprotected and self._has_active_child_accounts():
                    raise PolicyError(
                        "account.err.parentAuthRequired",
                        "Cannot remove last non-child credential while child accounts exist",
                    )
            self._conn.execute("BEGIN")
            try:
                self._conn.execute(
                    "DELETE FROM credentials WHERE account_id = ? AND factor = ?",
                    (account_id, factor),
                )
                self._conn.execute(
                    "DELETE FROM auth_throttle WHERE account_id = ? AND factor = ?",
                    (account_id, factor),
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def get_credential_hash(self, account_id: str, factor: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT hash FROM credentials WHERE account_id = ? AND factor = ?",
                (account_id, factor),
            ).fetchone()
            return str(row["hash"]) if row else None

    def get_throttle(self, account_id: str, factor: str) -> ThrottleState:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM auth_throttle WHERE account_id = ? AND factor = ?",
                (account_id, factor),
            ).fetchone()
            if not row:
                return ThrottleState(account_id=account_id, factor=factor)
            return ThrottleState(
                account_id=account_id,
                factor=factor,
                failed_count=int(row["failed_count"]),
                locked_until=int(row["locked_until"]),
                last_failed_at=int(row["last_failed_at"]),
            )

    def check_throttle(self, account_id: str, factor: str) -> tuple[bool, int]:
        """Liefert (hard_locked, retry_after_seconds)."""
        st = self.get_throttle(account_id, factor)
        if st.locked_until < 0:
            return True, 0
        now = self._now()
        if st.locked_until > now:
            return False, st.locked_until - now
        return False, 0

    def record_auth_failure(self, account_id: str, factor: str) -> ThrottleState:
        with self._lock:
            now = self._now()
            st = self.get_throttle(account_id, factor)
            count = st.failed_count + 1
            if factor == "pin" and count >= PIN_HARD_LOCK_THRESHOLD:
                locked_until = -1
            else:
                idx = min(count - 1, len(BACKOFF_STEPS) - 1)
                wait = BACKOFF_STEPS[idx]
                locked_until = now + wait if wait > 0 else 0
            self._conn.execute(
                "INSERT INTO auth_throttle(account_id, factor, failed_count, locked_until, last_failed_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(account_id, factor) DO UPDATE SET "
                "failed_count = excluded.failed_count, "
                "locked_until = excluded.locked_until, "
                "last_failed_at = excluded.last_failed_at",
                (account_id, factor, count, locked_until, now),
            )
            return ThrottleState(account_id, factor, count, locked_until, now)

    def clear_throttle(self, account_id: str, factor: str | None = None) -> None:
        with self._lock:
            if factor is None:
                self._conn.execute("DELETE FROM auth_throttle WHERE account_id = ?", (account_id,))
            else:
                self._conn.execute(
                    "DELETE FROM auth_throttle WHERE account_id = ? AND factor = ?",
                    (account_id, factor),
                )

    def touch_login(self, account_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE accounts SET last_login_at = ? WHERE id = ?",
                (self._now(), account_id),
            )

    def get_parental_policy(self, account_id: str) -> ParentalPolicy | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM parental_policies WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            if not row:
                return None
            return ParentalPolicy(
                account_id=str(row["account_id"]),
                mode=str(row["mode"]),
                allowed_tiles=tuple(json.loads(row["allowed_tiles_json"])),
                blocked_tiles=tuple(json.loads(row["blocked_tiles_json"])),
                blocked_cats=tuple(json.loads(row["blocked_cats_json"])),
                max_age_rating=int(row["max_age_rating"]),
                daily_limit_min=int(row["daily_limit_min"]),
                bedtime_start=str(row["bedtime_start"]),
                bedtime_end=str(row["bedtime_end"]),
                allow_yt_search=bool(row["allow_yt_search"]),
                allow_browser=bool(row["allow_browser"]),
                allow_power_menu=bool(row["allow_power_menu"]),
                updated_at=int(row["updated_at"]),
            )

    def set_parental_policy(self, policy: ParentalPolicy) -> ParentalPolicy:
        with self._lock:
            if not self.get_account(policy.account_id):
                raise NotFoundError("account.err.notFound", "Account not found")
            now = self._now()
            self._conn.execute(
                "INSERT INTO parental_policies "
                "(account_id, mode, allowed_tiles_json, blocked_tiles_json, blocked_cats_json, "
                "max_age_rating, daily_limit_min, bedtime_start, bedtime_end, "
                "allow_yt_search, allow_browser, allow_power_menu, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(account_id) DO UPDATE SET "
                "mode = excluded.mode, "
                "allowed_tiles_json = excluded.allowed_tiles_json, "
                "blocked_tiles_json = excluded.blocked_tiles_json, "
                "blocked_cats_json = excluded.blocked_cats_json, "
                "max_age_rating = excluded.max_age_rating, "
                "daily_limit_min = excluded.daily_limit_min, "
                "bedtime_start = excluded.bedtime_start, "
                "bedtime_end = excluded.bedtime_end, "
                "allow_yt_search = excluded.allow_yt_search, "
                "allow_browser = excluded.allow_browser, "
                "allow_power_menu = excluded.allow_power_menu, "
                "updated_at = excluded.updated_at",
                (
                    policy.account_id,
                    policy.mode,
                    json.dumps(list(policy.allowed_tiles), ensure_ascii=False),
                    json.dumps(list(policy.blocked_tiles), ensure_ascii=False),
                    json.dumps(list(policy.blocked_cats), ensure_ascii=False),
                    int(policy.max_age_rating),
                    int(policy.daily_limit_min),
                    policy.bedtime_start,
                    policy.bedtime_end,
                    1 if policy.allow_yt_search else 0,
                    1 if policy.allow_browser else 0,
                    1 if policy.allow_power_menu else 0,
                    now,
                ),
            )
            res = self.get_parental_policy(policy.account_id)
            assert res is not None
            return res

    def get_daily_usage(self, account_id: str, day: str) -> tuple[int, int]:
        """Liefert (used_seconds, bonus_seconds) fuer einen Kalendertag."""
        with self._lock:
            row = self._conn.execute(
                "SELECT used_seconds, bonus_seconds FROM usage_daily WHERE account_id = ? AND day = ?",
                (account_id, day),
            ).fetchone()
            if not row:
                return 0, 0
            return int(row["used_seconds"]), int(row["bonus_seconds"])

    def add_usage_seconds(self, account_id: str, day: str, delta_seconds: int) -> tuple[int, int]:
        """Addiert Nutzungssekunden atomar fuer einen Kalendertag."""
        delta = int(delta_seconds)
        with self._lock:
            if not self.get_account(account_id):
                raise NotFoundError("account.err.notFound", "Account not found")
            if delta > 0:
                self._conn.execute(
                    "INSERT INTO usage_daily(account_id, day, used_seconds, bonus_seconds) VALUES (?, ?, ?, 0) "
                    "ON CONFLICT(account_id, day) DO UPDATE SET "
                    "used_seconds = usage_daily.used_seconds + excluded.used_seconds",
                    (account_id, day, delta),
                )
            return self.get_daily_usage(account_id, day)

    def add_bonus_seconds(self, account_id: str, day: str, delta_seconds: int) -> tuple[int, int]:
        """Addiert Eltern-Bonussekunden atomar fuer einen Kalendertag."""
        delta = int(delta_seconds)
        with self._lock:
            if not self.get_account(account_id):
                raise NotFoundError("account.err.notFound", "Account not found")
            if delta > 0:
                self._conn.execute(
                    "INSERT INTO usage_daily(account_id, day, used_seconds, bonus_seconds) VALUES (?, ?, 0, ?) "
                    "ON CONFLICT(account_id, day) DO UPDATE SET "
                    "bonus_seconds = usage_daily.bonus_seconds + excluded.bonus_seconds",
                    (account_id, day, delta),
                )
            return self.get_daily_usage(account_id, day)

    def reset_daily_usage(self, account_id: str, day: str) -> None:
        """Loescht die Tagesnutzung eines Kontos."""
        with self._lock:
            self._conn.execute(
                "DELETE FROM usage_daily WHERE account_id = ? AND day = ?",
                (account_id, day),
            )

    def append_audit(
        self,
        event: str,
        account_id: str | None = None,
        actor_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            now = self._now()
            self._conn.execute("BEGIN")
            try:
                self._conn.execute(
                    "INSERT INTO audit_log(ts, account_id, actor_id, event, detail_json) VALUES (?, ?, ?, ?, ?)",
                    (now, account_id, actor_id, event, json.dumps(detail or {}, ensure_ascii=False)),
                )
                self._conn.execute(
                    "DELETE FROM audit_log WHERE id NOT IN "
                    "(SELECT id FROM audit_log ORDER BY id DESC LIMIT ?)",
                    (AUDIT_LIMIT,),
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def list_audit(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, ts, account_id, actor_id, event, detail_json FROM audit_log ORDER BY id DESC LIMIT ?",
                (max(1, min(AUDIT_LIMIT, int(limit))),),
            ).fetchall()
            out: list[dict[str, Any]] = []
            for r in rows:
                try:
                    detail = json.loads(r["detail_json"])
                except ValueError:
                    detail = {}
                out.append(
                    {
                        "id": int(r["id"]),
                        "ts": int(r["ts"]),
                        "account_id": r["account_id"],
                        "actor_id": r["actor_id"],
                        "event": str(r["event"]),
                        "detail": detail,
                    }
                )
            return out
