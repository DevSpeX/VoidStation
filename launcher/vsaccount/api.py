# SPDX-License-Identifier: GPL-3.0-or-later
"""HTTP-Routen-Logik fuer /api/session/* und /api/accounts/* (von launcher.py delegiert)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from .crypto import is_weak_pin
from .models import (
    AccountError,
    AuthError,
    NotFoundError,
    PolicyError,
    SessionState,
    ValidationError,
)

if TYPE_CHECKING:
    from . import AccountService
    from .parental import ParentalDecision


def error_response(exc: AccountError) -> tuple[int, dict[str, Any]]:
    if isinstance(exc, AuthError):
        if exc.code == "account.cooldown" or exc.retry_after > 0:
            return 429, {"error": exc.code, "msg": exc.message, "retry_after": exc.retry_after}
        if exc.code == "account.err.pinLocked":
            return 423, {"error": exc.code, "msg": exc.message, "hard_locked": True}
        return 401, {"error": exc.code, "msg": exc.message}
    if isinstance(exc, PolicyError):
        return 403, {"error": exc.code, "msg": exc.message}
    if isinstance(exc, NotFoundError):
        return 404, {"error": exc.code, "msg": exc.message}
    return 400, {"error": exc.code, "msg": exc.message}


def parental_denied_response(dec: ParentalDecision) -> tuple[int, dict[str, Any]]:
    return 403, {
        "error": dec.code or "account.blocked",
        "reason": dec.reason,
        "tile_id": dec.tile_id,
        "override_allowed": dec.override_allowed,
        "remaining_seconds": dec.remaining_seconds,
    }


def _require_admin(svc: AccountService) -> tuple[SessionState | None, tuple[int, dict[str, Any]] | None]:
    sess = svc.get_session()
    if sess.locked:
        return None, (403, {"error": "account.err.locked", "msg": "Session is locked"})
    if sess.is_guest or sess.role != "admin":
        return None, (403, {"error": "account.err.adminRequired", "msg": "Admin account required"})
    return sess, None


def handle_get(
    svc: AccountService,
    path: str,
    qs: dict[str, list[str]],
    *,
    catalog_meta: Callable[[], tuple[list[str], list[dict[str, Any]]]],
) -> tuple[int, dict[str, Any]] | None:
    if path == "/api/session":
        return 200, {
            "session": svc.get_session().to_public_dict(),
            "device_policy": svc.get_device_policy().to_dict(),
            "accounts_count": len(svc.list_accounts()),
            "migrated": svc.migration_report.migrated,
            "parental": svc.parental.status_for_session(),
        }
    if path == "/api/accounts":
        return 200, {
            "accounts": [a.to_public_dict() for a in svc.list_accounts()],
            "session": svc.get_session().to_public_dict(),
            "device_policy": svc.get_device_policy().to_dict(),
        }
    if path == "/api/accounts/parental":
        sess = svc.get_session()
        if sess.locked:
            return 403, {"error": "account.err.locked", "msg": "Session is locked"}
        req_id = qs.get("account_id", [""])[0].strip()
        cats, tiles = catalog_meta()
        if req_id:
            if sess.role != "admin" and (sess.is_guest or req_id != sess.account_id):
                return 403, {"error": "account.err.adminRequired", "msg": "Admin account required"}
            try:
                pol = svc.get_parental_policy(req_id).to_dict()
                st = svc.parental.status_for_session(req_id)
            except AccountError as exc:
                return error_response(exc)
            return 200, {"policy": pol, "status": st, "categories": cats, "tiles": tiles}
        if sess.role == "admin" and not sess.is_guest:
            children = [a for a in svc.list_accounts() if a.role == "child"]
            return 200, {
                "policies": {c.id: svc.get_parental_policy(c.id).to_dict() for c in children},
                "statuses": {c.id: svc.parental.status_for_session(c.id) for c in children},
                "categories": cats,
                "tiles": tiles,
            }
        if sess.role == "child" and not sess.is_guest:
            return 200, {
                "policy": svc.get_parental_policy(sess.account_id).to_dict(),
                "status": svc.parental.status_for_session(sess.account_id),
                "categories": cats,
                "tiles": tiles,
            }
        return 403, {"error": "account.err.adminRequired", "msg": "Admin account required"}
    return None


def handle_post(
    svc: AccountService,
    parts: list[str],
    b: dict[str, Any],
    *,
    defaults: dict[str, Any],
    on_session_changed: Callable[[SessionState, SessionState], None],
) -> tuple[int, dict[str, Any]] | None:
    try:
        if parts == ["api", "session", "switch"]:
            aid = str(b.get("account_id") or b.get("id") or "").strip()
            if not aid:
                raise ValidationError("account.err.notFound", "Account id required")
            pin = str(b["pin"]) if "pin" in b and b["pin"] is not None else None
            password = str(b["password"]) if "password" in b and b["password"] is not None else None
            prev = svc.get_session()
            sess = svc.switch_account(aid, pin=pin, password=password)
            on_session_changed(prev, sess)
            return 200, {
                "ok": True,
                "session": sess.to_public_dict(),
                "prefs": svc.load_profile_prefs(defaults),
                "parental": svc.parental.status_for_session(),
            }

        if parts == ["api", "session", "lock"]:
            prev = svc.get_session()
            sess = svc.lock_session()
            on_session_changed(prev, sess)
            return 200, {"ok": True, "session": sess.to_public_dict()}

        if parts == ["api", "session", "guest"]:
            name = str(b.get("display_name") or "").strip() or "Gast"
            prev = svc.get_session()
            sess = svc.start_guest_session(display_name=name)
            on_session_changed(prev, sess)
            return 200, {
                "ok": True,
                "session": sess.to_public_dict(),
                "prefs": svc.load_profile_prefs(defaults),
                "parental": svc.parental.status_for_session(),
            }

        if parts == ["api", "accounts", "create"]:
            _, err = _require_admin(svc)
            if err is not None:
                return err
            parent_raw = b.get("parent_id")
            acc = svc.create_account(
                display_name=str(b.get("display_name") or ""),
                role=str(b.get("role") or "standard"),
                parent_id=(str(parent_raw).strip() or None) if parent_raw is not None else None,
                avatar=str(b["avatar"]) if b.get("avatar") is not None else None,
                color=str(b["color"]) if b.get("color") is not None else None,
                auto_login=bool(b.get("auto_login", False)),
                password=str(b["password"]) if "password" in b and b["password"] is not None else None,
                pin=str(b["pin"]) if "pin" in b and b["pin"] is not None else None,
            )
            return 200, {
                "ok": True,
                "account": acc.to_public_dict(),
                "accounts": [a.to_public_dict() for a in svc.list_accounts()],
            }

        if parts == ["api", "accounts", "update"]:
            sess = svc.get_session()
            if sess.locked:
                return 403, {"error": "account.err.locked", "msg": "Session is locked"}
            if sess.is_guest or sess.role == "child":
                return 403, {"error": "account.err.adminRequired", "msg": "Admin account required"}
            aid = str(b.get("account_id") or b.get("id") or "").strip()
            if not aid:
                raise ValidationError("account.err.notFound", "Account id required")
            if sess.role != "admin":
                if aid != sess.account_id or any(k in b for k in ("role", "parent_id", "active", "auto_login")):
                    return 403, {"error": "account.err.adminRequired", "msg": "Admin account required"}
            updated = svc.update_account(
                account_id=aid,
                display_name=str(b["display_name"]) if "display_name" in b and b["display_name"] is not None else None,
                role=str(b["role"]) if "role" in b and b["role"] is not None else None,
                parent_id=(str(b["parent_id"]).strip() or None) if "parent_id" in b and b["parent_id"] is not None else None,
                avatar=str(b["avatar"]) if "avatar" in b and b["avatar"] is not None else None,
                color=str(b["color"]) if "color" in b and b["color"] is not None else None,
                active=bool(b["active"]) if "active" in b and b["active"] is not None else None,
                auto_login=bool(b["auto_login"]) if "auto_login" in b and b["auto_login"] is not None else None,
            )
            return 200, {
                "ok": True,
                "account": updated.to_public_dict(),
                "session": svc.get_session().to_public_dict(),
            }

        if parts == ["api", "accounts", "credentials"]:
            sess = svc.get_session()
            if sess.locked:
                return 403, {"error": "account.err.locked", "msg": "Session is locked"}
            if sess.is_guest or sess.role == "child":
                return 403, {"error": "account.err.adminRequired", "msg": "Admin account required"}
            aid = str(b.get("account_id") or b.get("id") or sess.account_id).strip()
            if not aid:
                raise ValidationError("account.err.notFound", "Account id required")
            action = str(b.get("action") or "set").strip().lower()
            factor = str(b.get("factor") or "").strip().lower()
            if action == "set" and not factor:
                if "pin" in b:
                    factor = "pin"
                elif "password" in b:
                    factor = "password"

            if action == "unlock":
                if sess.role != "admin":
                    return 403, {"error": "account.err.adminRequired", "msg": "Admin account required"}
                svc.unlock_account(aid, factor=factor or None)
                unlocked_acc = svc.get_account(aid)
                assert unlocked_acc is not None
                return 200, {"ok": True, "account": unlocked_acc.to_public_dict()}

            if sess.role != "admin":
                if aid != sess.account_id:
                    return 403, {"error": "account.err.adminRequired", "msg": "Admin account required"}
                cur = svc.get_account(aid)
                if cur and (cur.has_password or cur.has_pin):
                    if "current_password" in b and b["current_password"] is not None:
                        res = svc.authenticate(aid, "password", str(b["current_password"]))
                    elif "current_pin" in b and b["current_pin"] is not None:
                        res = svc.authenticate(aid, "pin", str(b["current_pin"]))
                    else:
                        raise AuthError("account.err.invalid", "Current credential required")
                    if not res.ok:
                        raise AuthError(res.error, res.error, retry_after=res.retry_after)

            if action == "remove":
                acc = svc.remove_credential(aid, factor)
                return 200, {"ok": True, "account": acc.to_public_dict()}
            if action == "set":
                secret_val = b.get("secret") if "secret" in b else (
                    b.get("pin") if factor == "pin" else b.get("password") if factor == "password" else None
                )
                secret = "" if secret_val is None else str(secret_val)
                acc = svc.set_credential(aid, factor, secret)
                resp: dict[str, Any] = {"ok": True, "account": acc.to_public_dict()}
                if factor == "pin":
                    resp["weak_pin"] = is_weak_pin(secret)
                return 200, resp
            raise ValidationError("account.err.invalid", "Invalid credential action")

        if parts == ["api", "accounts", "delete"]:
            _, err = _require_admin(svc)
            if err is not None:
                return err
            aid = str(b.get("account_id") or b.get("id") or "").strip()
            if not aid:
                raise ValidationError("account.err.notFound", "Account id required")
            prev = svc.get_session()
            svc.delete_account(aid)
            new_sess = svc.get_session()
            if new_sess != prev:
                on_session_changed(prev, new_sess)
            return 200, {
                "ok": True,
                "deleted": aid,
                "session": new_sess.to_public_dict(),
                "accounts": [a.to_public_dict() for a in svc.list_accounts()],
            }

        if parts == ["api", "accounts", "device-policy"]:
            _, err = _require_admin(svc)
            if err is not None:
                return err
            if "guest_allowed_tiles" in b and b["guest_allowed_tiles"] is not None and not isinstance(b["guest_allowed_tiles"], list):
                raise ValidationError("account.err.invalid", "guest_allowed_tiles must be a list")
            prev = svc.get_session()
            policy = svc.set_device_policy(
                ask_on_boot=bool(b["ask_on_boot"]) if "ask_on_boot" in b and b["ask_on_boot"] is not None else None,
                guest_enabled=bool(b["guest_enabled"]) if "guest_enabled" in b and b["guest_enabled"] is not None else None,
                default_account_id=str(b["default_account_id"]) if "default_account_id" in b and b["default_account_id"] is not None else None,
                guest_allowed_tiles=b["guest_allowed_tiles"] if "guest_allowed_tiles" in b and b["guest_allowed_tiles"] is not None else None,
            )
            new_sess = svc.get_session()
            if new_sess != prev:
                on_session_changed(prev, new_sess)
            return 200, {
                "ok": True,
                "device_policy": policy.to_dict(),
                "session": new_sess.to_public_dict(),
            }

        if parts == ["api", "accounts", "parental"]:
            _, err = _require_admin(svc)
            if err is not None:
                return err
            aid = str(b.get("account_id") or b.get("id") or "").strip()
            if not aid:
                raise ValidationError("account.err.notFound", "Account id required")
            pol_data = b["policy"] if isinstance(b.get("policy"), dict) else b
            saved = svc.set_parental_policy(aid, pol_data)
            return 200, {
                "ok": True,
                "policy": saved.to_dict(),
                "status": svc.parental.status_for_session(aid),
            }

        if parts == ["api", "accounts", "parental", "override"]:
            action = str(b.get("action") or "").strip()
            tile_id = str(b.get("tile_id") or "").strip()
            try:
                minutes = int(b.get("minutes") or 0)
            except (TypeError, ValueError) as exc:
                raise ValidationError("account.err.invalid", "Invalid minutes") from exc
            admin_id = str(b.get("admin_id") or "").strip() or None
            child_id = str(b.get("child_id") or "").strip() or None
            factor = str(b.get("factor") or "").strip().lower()
            if not factor:
                if "pin" in b and b["pin"] is not None:
                    factor = "pin"
                elif "password" in b and b["password"] is not None:
                    factor = "password"
            if "secret" in b and b["secret"] is not None:
                secret = str(b["secret"])
            elif factor == "pin":
                secret = str(b.get("pin") or "")
            elif factor == "password":
                secret = str(b.get("password") or "")
            else:
                secret = ""
            ov_res = svc.verify_parent_override(
                factor=factor,
                secret=secret,
                action=action,
                admin_id=admin_id,
                child_id=child_id,
                tile_id=tile_id,
                minutes=minutes,
            )
            return 200, ov_res
    except AccountError as exc:
        return error_response(exc)
    return None
