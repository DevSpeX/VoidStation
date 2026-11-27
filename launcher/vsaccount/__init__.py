# SPDX-License-Identifier: GPL-3.0-or-later
"""VoidStation Account-System (Kern, Krypto, Store, Profile, Kindersicherung, CLI, API)."""
from __future__ import annotations

import atexit
import threading
import time
from pathlib import Path
from typing import Any, Callable

from . import api
from .crypto import hash_secret, is_weak_pin, validate_password, validate_pin, verify_secret
from .migration import migrate_legacy_if_needed
from .models import (
    FACTORS,
    GUEST_ACCOUNT_ID,
    Account,
    AccountError,
    AuthError,
    AuthResult,
    DevicePolicy,
    MigrationReport,
    NotFoundError,
    ParentalPolicy,
    PolicyError,
    SessionState,
    ValidationError,
)
from .parental import (
    AGE_RATINGS,
    BROWSER_TILE_IDS,
    EXTRA_MINUTE_CHOICES,
    USAGE_TICK_SECONDS,
    WARN_THRESHOLD_SECONDS,
    ParentalController,
    ParentalDecision,
    validate_policy_data,
)
from .storage import (
    API_TOKEN_FILENAME,
    API_TOKEN_HEADER,
    ProfileStorage,
    api_token_path,
    ensure_api_token,
    read_api_token,
    verify_api_token,
)
from .store import AccountStore

__all__ = [
    "AGE_RATINGS",
    "API_TOKEN_FILENAME",
    "API_TOKEN_HEADER",
    "Account",
    "AccountError",
    "AccountService",
    "AuthError",
    "AuthResult",
    "BROWSER_TILE_IDS",
    "DevicePolicy",
    "EXTRA_MINUTE_CHOICES",
    "MigrationReport",
    "NotFoundError",
    "ParentalController",
    "ParentalDecision",
    "ParentalPolicy",
    "PolicyError",
    "SessionState",
    "USAGE_TICK_SECONDS",
    "ValidationError",
    "WARN_THRESHOLD_SECONDS",
    "api",
    "api_token_path",
    "ensure_api_token",
    "is_weak_pin",
    "read_api_token",
    "validate_password",
    "validate_pin",
    "validate_policy_data",
    "verify_api_token",
]


class AccountService:
    """Zentrale Backend-Fassade fuer Konten, Authentifizierung, Session und Kindersicherung."""

    def __init__(
        self,
        base_dir: Path,
        runtime_dir: Path | None = None,
        clock: Callable[[], float] | None = None,
        *,
        cleanup_guest: bool = True,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.accounts_dir = self.base_dir / "accounts"
        self._clock = clock or time.time
        self._lock = threading.RLock()
        self._cleanup_guest = bool(cleanup_guest)

        self.storage = ProfileStorage(self.accounts_dir, runtime_dir=runtime_dir)
        self.storage.ensure_root()
        # Altlasten einer abgestuerzten Gast-Sitzung beim Backend-Start bereinigen (nicht bei CLI-Hilfsaufrufen)
        if self._cleanup_guest:
            self.storage.cleanup_guest_dir()

        self.store = AccountStore(self.accounts_dir, clock=self._clock)
        self.migration_report = migrate_legacy_if_needed(self.base_dir, self.store, self.storage)
        self._session = self._initial_session()
        self.parental = ParentalController(
            self.store,
            self.get_session,
            self.get_device_policy,
            clock=self._clock,
            lock=self._lock,
        )
        self._closed = False
        if self._cleanup_guest:
            atexit.register(self._atexit_cleanup)

    def _now(self) -> int:
        return int(self._clock())

    def _atexit_cleanup(self) -> None:
        if self._cleanup_guest:
            self.storage.cleanup_guest_dir()

    def _initial_session(self) -> SessionState:
        accounts = self.store.list_accounts()
        policy = self.store.get_device_policy()
        has_active_child = any(a.role == "child" and a.active for a in accounts)
        target: Account | None = None
        for acc in accounts:
            if acc.auto_login and not (acc.has_pin or acc.has_password):
                target = acc
                break
        if target is None and policy.default_account_id:
            target = next((a for a in accounts if a.id == policy.default_account_id), None)
        if target is None and accounts:
            target = accounts[0]

        if target is None:
            return SessionState(
                account_id="",
                display_name="VoidStation",
                role="standard",
                avatar="user",
                color="#2d4a6b",
                is_guest=False,
                locked=True,
                picker_required=True,
            )

        target_has_auth = target.has_pin or target.has_password
        needs_auth = policy.ask_on_boot or has_active_child or target_has_auth
        return SessionState(
            account_id=target.id,
            display_name=target.display_name,
            role=target.role,
            avatar=target.avatar,
            color=target.color,
            is_guest=False,
            locked=needs_auth,
            picker_required=needs_auth,
        )

    def _ensure_open(self) -> None:
        if self._closed:
            raise AccountError("account.err.closed", "AccountService is closed")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self.parental.stop_tracker()
            if self._cleanup_guest:
                self.storage.cleanup_guest_dir()
            self.store.close()

    # --- Konten ---
    def list_accounts(self) -> list[Account]:
        with self._lock:
            self._ensure_open()
            return self.store.list_accounts()

    def get_account(self, account_id: str) -> Account | None:
        with self._lock:
            self._ensure_open()
            return self.store.get_account(account_id)

    def find_account(self, id_or_name: str) -> Account | None:
        with self._lock:
            self._ensure_open()
            return self.store.find_account(id_or_name)

    def get_session(self) -> SessionState:
        with self._lock:
            self._ensure_open()
            return self._session

    def get_device_policy(self) -> DevicePolicy:
        with self._lock:
            self._ensure_open()
            return self.store.get_device_policy()

    def set_device_policy(
        self,
        ask_on_boot: bool | None = None,
        guest_enabled: bool | None = None,
        default_account_id: str | None = None,
        guest_allowed_tiles: tuple[str, ...] | list[str] | None = None,
    ) -> DevicePolicy:
        with self._lock:
            self._ensure_open()
            cur = self.store.get_device_policy()
            new_default = cur.default_account_id if default_account_id is None else default_account_id
            if new_default and not self.store.get_account(new_default):
                raise NotFoundError("account.err.notFound", "Default account not found")
            nxt = DevicePolicy(
                ask_on_boot=cur.ask_on_boot if ask_on_boot is None else bool(ask_on_boot),
                guest_enabled=cur.guest_enabled if guest_enabled is None else bool(guest_enabled),
                default_account_id=new_default,
                guest_allowed_tiles=(
                    cur.guest_allowed_tiles
                    if guest_allowed_tiles is None
                    else tuple(str(x) for x in guest_allowed_tiles if str(x))
                ),
            )
            saved = self.store.set_device_policy(nxt)
            if not saved.guest_enabled and self._session.is_guest:
                self.lock_session()
            self.store.append_audit("device_policy_updated", actor_id=self._session.account_id)
            return saved

    def create_account(
        self,
        display_name: str,
        role: str = "standard",
        parent_id: str | None = None,
        avatar: str | None = None,
        color: str | None = None,
        auto_login: bool = False,
        password: str | None = None,
        pin: str | None = None,
    ) -> Account:
        with self._lock:
            self._ensure_open()
            acc = self.store.create_account(
                display_name=display_name,
                role=role,
                parent_id=parent_id,
                avatar=avatar,
                color=color,
                auto_login=auto_login,
            )
            self.storage.profile_dir(acc.id)
            try:
                if password is not None:
                    self.store.set_credential_hash(acc.id, "password", hash_secret(password, "password"))
                if pin is not None:
                    self.store.set_credential_hash(acc.id, "pin", hash_secret(pin, "pin"))
            except Exception:
                self.store.delete_account(acc.id)
                self.storage.delete_profile_dir(acc.id)
                raise
            self.store.append_audit(
                "account_created",
                account_id=acc.id,
                actor_id=self._session.account_id,
                detail={"role": acc.role},
            )
            refreshed = self.store.get_account(acc.id)
            assert refreshed is not None
            return refreshed

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
            self._ensure_open()
            updated = self.store.update_account(
                account_id=account_id,
                display_name=display_name,
                role=role,
                parent_id=parent_id,
                avatar=avatar,
                color=color,
                active=active,
                auto_login=auto_login,
            )
            if self._session.account_id == updated.id and not self._session.is_guest:
                self._session = SessionState(
                    account_id=updated.id,
                    display_name=updated.display_name,
                    role=updated.role,
                    avatar=updated.avatar,
                    color=updated.color,
                    is_guest=False,
                    locked=self._session.locked,
                    picker_required=self._session.picker_required,
                    elevated_until=self._session.elevated_until,
                )
            self.store.append_audit(
                "account_updated",
                account_id=updated.id,
                actor_id=self._session.account_id,
            )
            return updated

    def delete_account(self, account_id: str) -> None:
        with self._lock:
            self._ensure_open()
            was_current = self._session.account_id == account_id and not self._session.is_guest
            self.store.delete_account(account_id)
            self.storage.delete_profile_dir(account_id)
            self.store.append_audit(
                "account_deleted",
                account_id=account_id,
                actor_id=self._session.account_id,
            )
            if was_current:
                prev_id = self._session.account_id
                self._session = self._initial_session()
                self._session.locked = True
                self._session.picker_required = True
                self.parental.on_session_changed(prev_id, self._session.account_id, locked=True)

    # --- Authentifizierung & Cooldown ---
    def set_credential(self, account_id: str, factor: str, secret: str) -> Account:
        with self._lock:
            self._ensure_open()
            if factor not in FACTORS:
                raise ValidationError("account.err.invalid", "Invalid factor")
            digest = hash_secret(secret, factor)
            self.store.set_credential_hash(account_id, factor, digest)
            self.store.append_audit(
                f"{factor}_set",
                account_id=account_id,
                actor_id=self._session.account_id,
            )
            acc = self.store.get_account(account_id)
            assert acc is not None
            return acc

    def remove_credential(self, account_id: str, factor: str) -> Account:
        with self._lock:
            self._ensure_open()
            self.store.remove_credential(account_id, factor)
            self.store.append_audit(
                f"{factor}_removed",
                account_id=account_id,
                actor_id=self._session.account_id,
            )
            acc = self.store.get_account(account_id)
            assert acc is not None
            return acc

    def unlock_account(self, account_id: str, factor: str | None = None) -> None:
        with self._lock:
            self._ensure_open()
            if not self.store.get_account(account_id):
                raise NotFoundError("account.err.notFound", "Account not found")
            self.store.clear_throttle(account_id, factor)
            self.store.append_audit(
                "account_unlocked",
                account_id=account_id,
                actor_id=self._session.account_id,
                detail={"factor": factor or "all"},
            )

    def authenticate(self, account_id: str, factor: str, secret: str) -> AuthResult:
        with self._lock:
            self._ensure_open()
            if factor not in FACTORS:
                raise ValidationError("account.err.invalid", "Invalid factor")
            acc = self.store.get_account(account_id)
            if not acc or not acc.active:
                raise NotFoundError("account.err.notFound", "Account not found")

            hard_locked, retry_after = self.store.check_throttle(account_id, factor)
            if hard_locked:
                return AuthResult(
                    ok=False,
                    account_id=account_id,
                    factor=factor,
                    error="account.err.pinLocked",
                    hard_locked=True,
                )
            if retry_after > 0:
                return AuthResult(
                    ok=False,
                    account_id=account_id,
                    factor=factor,
                    error="account.cooldown",
                    retry_after=retry_after,
                )

            stored_hash = self.store.get_credential_hash(account_id, factor)
            if not stored_hash:
                return AuthResult(
                    ok=False,
                    account_id=account_id,
                    factor=factor,
                    error="account.err.invalid",
                )

            valid, needs_rehash = verify_secret(secret, stored_hash, factor=factor)
            if not valid:
                st = self.store.record_auth_failure(account_id, factor)
                self.store.append_audit(
                    "auth_failed",
                    account_id=account_id,
                    actor_id=self._session.account_id,
                    detail={"factor": factor, "failed_count": st.failed_count},
                )
                if st.locked_until < 0:
                    return AuthResult(
                        ok=False,
                        account_id=account_id,
                        factor=factor,
                        error="account.err.pinLocked",
                        hard_locked=True,
                    )
                wait = max(0, st.locked_until - self._now()) if st.locked_until > 0 else 0
                return AuthResult(
                    ok=False,
                    account_id=account_id,
                    factor=factor,
                    error="account.cooldown" if wait > 0 else "account.err.invalid",
                    retry_after=wait,
                )

            self.store.clear_throttle(account_id, factor)
            # Ein erfolgreiches Passwort-Login entsperrt auch eine gesperrte PIN.
            if factor == "password":
                self.store.clear_throttle(account_id, "pin")
            if needs_rehash:
                self.store.set_credential_hash(account_id, factor, hash_secret(secret, factor))
            self.store.touch_login(account_id)
            return AuthResult(ok=True, account_id=account_id, factor=factor)

    # --- Session & Profilwechsel ---
    def switch_account(
        self,
        account_id: str,
        pin: str | None = None,
        password: str | None = None,
    ) -> SessionState:
        with self._lock:
            self._ensure_open()
            acc = self.store.get_account(account_id)
            if not acc or not acc.active:
                raise NotFoundError("account.err.notFound", "Account not found")

            if acc.has_pin or acc.has_password:
                if password is not None:
                    res = self.authenticate(acc.id, "password", password)
                elif pin is not None:
                    res = self.authenticate(acc.id, "pin", pin)
                else:
                    raise AuthError("account.err.invalid", "Authentication required")
                if not res.ok:
                    raise AuthError(res.error, res.error, retry_after=res.retry_after)
            else:
                if acc.role != "child" and self.store.has_active_child_accounts():
                    raise PolicyError(
                        "account.err.parentAuthRequired",
                        "Non-child account requires a PIN or password while child accounts exist",
                    )
                self.store.touch_login(acc.id)

            if self._session.is_guest:
                self.storage.cleanup_guest_dir()

            prev_id = self._session.account_id
            self.storage.profile_dir(acc.id)
            self._session = SessionState(
                account_id=acc.id,
                display_name=acc.display_name,
                role=acc.role,
                avatar=acc.avatar,
                color=acc.color,
                is_guest=False,
                locked=False,
                picker_required=False,
                elevated_until=0,
            )
            self.parental.on_session_changed(prev_id, acc.id, locked=False)
            self.store.append_audit("session_switched", account_id=acc.id, actor_id=acc.id)
            return self._session

    def start_guest_session(self, display_name: str = "Gast") -> SessionState:
        with self._lock:
            self._ensure_open()
            policy = self.store.get_device_policy()
            if not policy.guest_enabled:
                raise PolicyError("account.err.guestDisabled", "Guest mode is disabled")
            if self._session.role == "child" and not self._session.is_guest:
                raise PolicyError("account.err.blocked", "Guest mode is not available from a child session")
            prev_id = self._session.account_id
            self.storage.prepare_guest_dir()
            self._session = SessionState(
                account_id=GUEST_ACCOUNT_ID,
                display_name=display_name.strip() or "Gast",
                role="guest",
                avatar="user",
                color="#3a3f46",
                is_guest=True,
                locked=False,
                picker_required=False,
                elevated_until=0,
            )
            self.parental.on_session_changed(prev_id, GUEST_ACCOUNT_ID, locked=False)
            self.store.append_audit("guest_started", account_id=GUEST_ACCOUNT_ID)
            return self._session

    def lock_session(self) -> SessionState:
        with self._lock:
            self._ensure_open()
            prev_id = self._session.account_id
            if self._session.is_guest:
                self.storage.cleanup_guest_dir()
                fallback = self._initial_session()
                self._session = SessionState(
                    account_id=fallback.account_id,
                    display_name=fallback.display_name,
                    role=fallback.role,
                    avatar=fallback.avatar,
                    color=fallback.color,
                    is_guest=False,
                    locked=True,
                    picker_required=True,
                    elevated_until=0,
                )
            else:
                self._session = SessionState(
                    account_id=self._session.account_id,
                    display_name=self._session.display_name,
                    role=self._session.role,
                    avatar=self._session.avatar,
                    color=self._session.color,
                    is_guest=False,
                    locked=True,
                    picker_required=True,
                    elevated_until=0,
                )
            self.parental.on_session_changed(prev_id, self._session.account_id, locked=True)
            self.store.append_audit("session_locked", account_id=self._session.account_id)
            return self._session

    # --- Strikte Profil-Dateipfade & Einstellungen ---
    def profile_path(self, filename: str) -> Path:
        """Liefert ausschliesslich den isolierten Dateipfad des aktiven Profils bzw. Gastes."""
        with self._lock:
            self._ensure_open()
            if not self._session.account_id:
                raise PolicyError("account.err.notFound", "No active account")
            return self.storage.profile_file(
                self._session.account_id,
                filename,
                is_guest=self._session.is_guest,
            )

    def browser_profile_dir(self, app_id: str) -> Path:
        with self._lock:
            self._ensure_open()
            if not self._session.account_id:
                raise PolicyError("account.err.notFound", "No active account")
            return self.storage.browser_profile_dir(
                self._session.account_id,
                app_id,
                is_guest=self._session.is_guest,
            )

    def load_profile_prefs(self, global_defaults: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            self._ensure_open()
            if not self._session.account_id:
                return dict(global_defaults or {})
            return self.storage.load_prefs(
                self._session.account_id,
                global_defaults=global_defaults,
                is_guest=self._session.is_guest,
            )

    def save_profile_prefs(self, updates: dict[str, Any]) -> dict[str, Any]:
        """Schreibt Profil-Praeferenzen strikt in accounts/data/<id>/prefs.json (oder Gast-Runtime)."""
        with self._lock:
            self._ensure_open()
            if not self._session.account_id:
                raise PolicyError("account.err.notFound", "No active account")
            return self.storage.save_prefs(
                self._session.account_id,
                updates,
                is_guest=self._session.is_guest,
            )

    # --- Kindersicherung ---
    def get_parental_policy(self, account_id: str) -> ParentalPolicy:
        with self._lock:
            self._ensure_open()
            acc = self.store.get_account(account_id)
            if not acc:
                raise NotFoundError("account.err.notFound", "Account not found")
            return self.store.get_parental_policy(account_id) or ParentalPolicy(account_id=account_id)

    def set_parental_policy(self, account_id: str, policy_data: dict[str, Any]) -> ParentalPolicy:
        with self._lock:
            self._ensure_open()
            policy = validate_policy_data(account_id, policy_data)
            saved = self.store.set_parental_policy(policy)
            self.parental.on_policy_updated(account_id)
            self.store.append_audit(
                "parental_updated",
                account_id=account_id,
                actor_id=self._session.account_id,
            )
            return saved

    def verify_parent_override(
        self,
        *,
        factor: str,
        secret: str,
        action: str,
        admin_id: str | None = None,
        child_id: str | None = None,
        tile_id: str = "",
        minutes: int = 0,
    ) -> dict[str, Any]:
        """Prueft Eltern-PIN/Passwort (inkl. Cooldown/Hard-Lock) und erteilt eine temporaere Freigabe."""
        with self._lock:
            self._ensure_open()
            target_child_id = (child_id or "").strip() or (
                self._session.account_id if not self._session.is_guest else ""
            )
            child = self.store.get_account(target_child_id) if target_child_id else None
            if not child or not child.active or child.role != "child":
                raise PolicyError("account.err.invalid", "Child account required for override")

            all_accounts = self.store.list_accounts()
            admins = [a for a in all_accounts if a.role == "admin" and a.active]
            admin: Account | None = None
            if admin_id:
                cand = self.store.get_account(admin_id.strip())
                if not cand or not cand.active or cand.role != "admin":
                    raise PolicyError("account.err.adminRequired", "Admin account required")
                admin = cand
            else:
                if child.parent_id:
                    cand = next((a for a in admins if a.id == child.parent_id and (a.has_pin or a.has_password)), None)
                    if cand:
                        admin = cand
                if admin is None:
                    admin = next((a for a in admins if a.has_pin or a.has_password), None)

            if admin is None or not (admin.has_pin or admin.has_password):
                raise PolicyError("account.err.parentAuthRequired", "Parent PIN or password required")

            use_factor = factor.strip().lower()
            if use_factor not in FACTORS:
                raise ValidationError("account.err.invalid", "Invalid factor")

            res = self.authenticate(admin.id, use_factor, secret)
            if not res.ok:
                raise AuthError(res.error, res.error, retry_after=res.retry_after)

            act = action.strip().lower()
            if act == "allow_once":
                self.parental.grant_allow_once(child.id, tile_id)
            elif act == "add_minutes":
                self.parental.grant_extra_minutes(child.id, int(minutes))
            else:
                raise ValidationError("account.err.invalid", "Invalid override action")

            self.store.append_audit(
                "parental_override",
                account_id=child.id,
                actor_id=admin.id,
                detail={"action": act, "tile_id": tile_id, "minutes": int(minutes)},
            )
            return {
                "ok": True,
                "action": act,
                "account_id": child.id,
                "admin_id": admin.id,
                "tile_id": tile_id,
                "minutes": int(minutes),
                "parental": self.parental.status_for_session(child.id),
            }

    def audit_entries(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_open()
            return self.store.list_audit(limit=limit)
