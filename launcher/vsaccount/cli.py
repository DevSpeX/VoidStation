#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""CLI-Werkzeug fuer Notfall-Wiederherstellung, Inspektion, `vsctl account` und Installer-Bootstrap.

Wichtig: Passwoerter und PINs werden niemals ueber Kommandozeilenargumente entgegengenommen,
sondern ausschliesslich ueber stdin, 0600-Dateien oder interaktives getpass().
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import stat
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vsaccount import (
    API_TOKEN_HEADER,
    AccountError,
    AccountService,
    read_api_token,
    validate_pin,
)


def _default_base() -> Path:
    env = os.environ.get("VOIDSTATION_BASE", "").strip()
    if env:
        return Path(env)
    return Path.home() / ".local" / "share" / "voidstation"


def _read_secret_json(secret_file: str | None) -> dict[str, Any]:
    if secret_file:
        p = Path(secret_file)
        st = p.stat()
        if stat.S_IMODE(st.st_mode) & 0o077:
            raise AccountError("account.err.invalid", "Secret file permissions must be 0600 or stricter")
        raw = p.read_text(encoding="utf-8")
    else:
        raw = sys.stdin.read()
    data = json.loads(raw or "{}")
    if not isinstance(data, dict):
        raise AccountError("account.err.invalid", "Bootstrap payload must be a JSON object")
    return data


def _reject_secret_cli_args(argv: list[str]) -> str | None:
    """Verhindert, dass Passwoerter, PINs oder Tokens in Prozessliste/Shell-History landen."""
    for arg in argv:
        low = arg.lower()
        if low in ("--pin", "--secret", "--token", "--access-token", "--refresh-token") or low.startswith(
            ("--pin=", "--password=", "--secret=", "--token=", "--access-token=", "--refresh-token=")
        ):
            return arg.split("=", 1)[0]
    return None


def _read_token_file(token_file: Path | None) -> str:
    if token_file is not None:
        try:
            if token_file.is_symlink() or not token_file.is_file():
                return ""
            return token_file.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
    return read_api_token()


def _http_json(
    api_base: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    token: str = "",
) -> tuple[int | None, dict[str, Any]]:
    url = api_base.rstrip("/") + path
    headers: dict[str, str] = {"X-TV": "1"}
    if token:
        headers[API_TOKEN_HEADER] = token
    data: bytes | None = None
    if method == "POST":
        headers["Content-Type"] = "application/json"
        data = json.dumps({} if body is None else body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode("utf-8", "replace")
            parsed = json.loads(raw) if raw.strip() else {}
            return resp.status, parsed if isinstance(parsed, dict) else {"data": parsed}
    except urllib.error.HTTPError as exc:
        with exc:
            raw = exc.read().decode("utf-8", "replace")
            code = exc.code
        try:
            parsed = json.loads(raw) if raw.strip() else {}
        except ValueError:
            parsed = {"error": raw or f"HTTP {code}"}
        return code, parsed if isinstance(parsed, dict) else {"error": str(parsed)}
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
        return None, {"error": "connection_error", "msg": str(exc)}


def _resolve_account_from_list(accounts: list[dict[str, Any]], target: str) -> dict[str, Any] | None:
    needle = target.strip()
    if not needle:
        return None
    for acc in accounts:
        if str(acc.get("id") or "") == needle:
            return acc
    low = needle.lower()
    matches = [a for a in accounts if str(a.get("display_name") or "").strip().lower() == low and a.get("active", True)]
    return matches[0] if len(matches) == 1 else None


def _read_secret_line(prompt: str) -> str:
    if sys.stdin.isatty():
        return getpass.getpass(prompt)
    line = sys.stdin.readline()
    return line.rstrip("\r\n")


def _read_new_pin() -> str:
    if sys.stdin.isatty():
        p1 = getpass.getpass("New PIN (4-8 digits): ")
        p2 = getpass.getpass("Repeat PIN: ")
        if p1 != p2:
            raise ValueError("PINs do not match")
    else:
        lines = [ln.rstrip("\r\n") for ln in sys.stdin.read().splitlines()]
        if not lines:
            raise ValueError("PIN required on stdin")
        if len(lines) >= 2 and lines[0] != lines[1]:
            raise ValueError("PINs do not match")
        p1 = lines[0]
    return validate_pin(p1)


def _format_api_error(status: int | None, data: dict[str, Any]) -> str:
    code = str(data.get("error") or "")
    msg = str(data.get("msg") or "")
    if status == 429 or code == "account.cooldown":
        secs = int(data.get("retry_after") or 0)
        return f"Too many failed attempts – wait {secs} s"
    if status == 423 or code == "account.err.pinLocked":
        return "PIN is hard-locked – use --password or 'vsctl account unlock <target>'"
    if status == 401 or code == "account.err.invalid":
        return "Invalid credentials"
    if code == "account.err.guestDisabled":
        return "Guest mode is disabled"
    if code == "account.err.locked":
        return "Session is locked"
    if code == "account.err.adminRequired":
        return "Admin account required"
    if code == "account.err.notFound":
        return "Account not found"
    if status == 403 and code == "forbidden":
        return "API authorization failed (check runtime token)"
    return msg or code or f"Request failed (HTTP {status})"


def _print_human_status(data: dict[str, Any], offline: bool = False) -> None:
    sess = data.get("session") or {}
    pol = data.get("device_policy") or {}
    par = data.get("parental") or {}
    name = sess.get("display_name") or "-"
    aid = sess.get("account_id") or "-"
    role = sess.get("role") or "-"
    flags = []
    if sess.get("is_guest"):
        flags.append("guest")
    if sess.get("locked") or sess.get("picker_required"):
        flags.append("locked")
    else:
        flags.append("unlocked")
    if offline:
        flags.append("offline")
    print(f"Active profile: {name} ({aid}, role={role}, {', '.join(flags)})")
    print(f"Accounts:       {data.get('accounts_count', 0)}")
    print(
        "Device policy:  "
        f"ask_on_boot={'yes' if pol.get('ask_on_boot') else 'no'}, "
        f"guest={'yes' if pol.get('guest_enabled') else 'no'}, "
        f"default={pol.get('default_account_id') or '-'}"
    )
    if par.get("restricted"):
        rem = par.get("remaining_seconds")
        rem_txt = f"{max(0, int(rem) // 60)} min left" if rem is not None else "no daily limit"
        if par.get("locked"):
            rem_txt += f" (blocked: {par.get('reason') or 'parental'})"
        print(f"Parental:       {rem_txt}")


def _print_human_list(accounts: list[dict[str, Any]], active_id: str = "", is_guest: bool = False, offline: bool = False) -> None:
    if offline:
        print("Accounts (offline):")
    for a in accounts:
        mark = "*" if (not is_guest and a.get("id") == active_id) else " "
        auth = []
        if a.get("has_pin"):
            auth.append("PIN")
        if a.get("has_password"):
            auth.append("PW")
        auth_txt = "+".join(auth) if auth else "none"
        auto_txt = " [auto]" if a.get("auto_login") else ""
        print(f"{mark} {a.get('id')}  {a.get('display_name')}  ({a.get('role')}, auth={auth_txt}{auto_txt})")


def _db_exists(base_dir: Path) -> bool:
    return (base_dir / "accounts" / "accounts.db").is_file()


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    bad_arg = _reject_secret_cli_args(raw_argv)
    if bad_arg:
        print(
            f"Error: {bad_arg} is forbidden – PINs and passwords must never be passed as command-line arguments.",
            file=sys.stderr,
        )
        return 2

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--base", type=Path, default=argparse.SUPPRESS, help="VoidStation data directory")
    common.add_argument("--api", default=argparse.SUPPRESS, help="Launcher HTTP API base URL")
    common.add_argument("--token-file", type=Path, default=argparse.SUPPRESS, help="Path to runtime API token file")
    common.add_argument("--human", action="store_true", default=argparse.SUPPRESS, help="Human-readable terminal output")
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Force JSON output")

    ap = argparse.ArgumentParser(prog="vsaccount.cli", description="VoidStation Account CLI", parents=[common])
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Show account system status", parents=[common])
    sub.add_parser("list", help="List public account metadata", parents=[common])

    p_switch = sub.add_parser("switch", help="Switch active profile (or start guest session)", parents=[common])
    p_switch.add_argument("target", nargs="?", help="Account id or display name")
    p_switch.add_argument("--password", action="store_true", help="Authenticate with password instead of PIN")
    p_switch.add_argument("--guest", action="store_true", help="Start temporary guest session")

    sub.add_parser("lock", help="Lock current session and show profile picker", parents=[common])

    p_unlock = sub.add_parser("unlock", help="Clear auth cooldown and PIN lock for an account", parents=[common])
    p_unlock.add_argument("target", help="Account id or display name")

    p_pin = sub.add_parser("reset-pin", help="Interactively set or remove an account PIN", parents=[common])
    p_pin.add_argument("target", help="Account id or display name")
    p_pin.add_argument("--remove", action="store_true", help="Remove PIN instead of setting a new one")

    p_boot = sub.add_parser("bootstrap", help="Create/update initial admin from stdin or 0600 JSON file", parents=[common])
    p_boot.add_argument("--secret-file", default=None, help="Path to 0600 JSON file")

    args = ap.parse_args(raw_argv)
    base_dir: Path = getattr(args, "base", None) or _default_base()
    api_base: str = str(getattr(args, "api", "") or "").strip()
    token_file: Path | None = getattr(args, "token_file", None)
    token = _read_token_file(token_file) if api_base else ""
    human = bool(getattr(args, "human", False)) and not bool(getattr(args, "json", False))

    if args.cmd == "switch":
        if not api_base:
            print("Error: 'switch' requires a running VoidStation session (--api).", file=sys.stderr)
            return 1
        if args.guest or (args.target or "").strip().lower() == "guest":
            code, data = _http_json(api_base, "POST", "/api/session/guest", {}, token)
            if code is None:
                print("Error: VoidStation API is not reachable.", file=sys.stderr)
                return 1
            if code != 200:
                print(f"Error: {_format_api_error(code, data)}", file=sys.stderr)
                return 1
            if human:
                sess = data.get("session") or {}
                print(f"Switched to guest profile: {sess.get('display_name') or 'Guest'}")
            else:
                print(json.dumps(data, ensure_ascii=False, indent=2))
            return 0

        target = (args.target or "").strip()
        if not target:
            print("Error: account id/name or --guest required.", file=sys.stderr)
            return 2

        c_acc, d_acc = _http_json(api_base, "GET", "/api/accounts", token=token)
        if c_acc is None:
            print("Error: VoidStation API is not reachable.", file=sys.stderr)
            return 1
        if c_acc != 200:
            print(f"Error: {_format_api_error(c_acc, d_acc)}", file=sys.stderr)
            return 1
        acc = _resolve_account_from_list(d_acc.get("accounts") or [], target)
        if not acc:
            print(f"Account not found: {target}", file=sys.stderr)
            return 1

        payload: dict[str, Any] = {"account_id": acc["id"]}
        has_pin = bool(acc.get("has_pin"))
        has_pw = bool(acc.get("has_password"))
        try:
            if args.password:
                payload["password"] = _read_secret_line(f"Password for {acc['display_name']}: ")
            elif has_pin:
                payload["pin"] = _read_secret_line(f"PIN for {acc['display_name']}: ")
            elif has_pw:
                payload["password"] = _read_secret_line(f"Password for {acc['display_name']}: ")
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.", file=sys.stderr)
            return 1

        c_sw, d_sw = _http_json(api_base, "POST", "/api/session/switch", payload, token)
        if c_sw is None:
            print("Error: VoidStation API is not reachable.", file=sys.stderr)
            return 1
        if c_sw != 200:
            print(f"Error: {_format_api_error(c_sw, d_sw)}", file=sys.stderr)
            return 1
        if human:
            sess = d_sw.get("session") or {}
            print(f"Switched active profile to: {sess.get('display_name')} ({sess.get('account_id')})")
        else:
            print(json.dumps(d_sw, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "lock":
        if not api_base:
            print("Error: 'lock' requires a running VoidStation session (--api).", file=sys.stderr)
            return 1
        c_lk, d_lk = _http_json(api_base, "POST", "/api/session/lock", {}, token)
        if c_lk is None:
            print("Error: VoidStation API is not reachable.", file=sys.stderr)
            return 1
        if c_lk != 200:
            print(f"Error: {_format_api_error(c_lk, d_lk)}", file=sys.stderr)
            return 1
        if human:
            print("Session locked.")
        else:
            print(json.dumps(d_lk, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "status" and api_base:
        c_st, d_st = _http_json(api_base, "GET", "/api/session", token=token)
        if c_st == 200:
            if human:
                _print_human_status(d_st, offline=False)
            else:
                print(json.dumps(d_st, ensure_ascii=False, indent=2))
            return 0
        if c_st is not None:
            print(f"Error: {_format_api_error(c_st, d_st)}", file=sys.stderr)
            return 1

    if args.cmd == "list" and api_base:
        c_ls, d_ls = _http_json(api_base, "GET", "/api/accounts", token=token)
        if c_ls == 200:
            accounts_list = d_ls.get("accounts") or []
            sess = d_ls.get("session") or {}
            if human:
                _print_human_list(
                    accounts_list,
                    active_id=str(sess.get("account_id") or ""),
                    is_guest=bool(sess.get("is_guest")),
                    offline=False,
                )
            else:
                print(json.dumps(accounts_list, ensure_ascii=False, indent=2))
            return 0
        if c_ls is not None:
            print(f"Error: {_format_api_error(c_ls, d_ls)}", file=sys.stderr)
            return 1

    if args.cmd == "unlock" and api_base:
        c_acc, d_acc = _http_json(api_base, "GET", "/api/accounts", token=token)
        if c_acc == 200:
            acc = _resolve_account_from_list(d_acc.get("accounts") or [], args.target)
            if not acc:
                print(f"Account not found: {args.target}", file=sys.stderr)
                return 1
            c_ul, d_ul = _http_json(
                api_base,
                "POST",
                "/api/accounts/credentials",
                {"account_id": acc["id"], "action": "unlock"},
                token,
            )
            if c_ul == 200:
                if human:
                    print(f"Unlocked account: {acc['display_name']} ({acc['id']})")
                else:
                    print(json.dumps({"ok": True, "account_id": acc["id"]}, ensure_ascii=False))
                return 0
            err_code = str(d_ul.get("error") or "")
            if not (c_ul == 403 and err_code in ("account.err.locked", "account.err.adminRequired") and _db_exists(base_dir)):
                if c_ul is not None:
                    print(f"Error: {_format_api_error(c_ul, d_ul)}", file=sys.stderr)
                    return 1
        elif c_acc is not None:
            print(f"Error: {_format_api_error(c_acc, d_acc)}", file=sys.stderr)
            return 1

    new_pin_val: str | None = None
    if args.cmd == "reset-pin" and not args.remove:
        try:
            new_pin_val = _read_new_pin()
        except (AccountError, ValueError, EOFError, KeyboardInterrupt) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    if args.cmd == "reset-pin" and api_base:
        c_acc, d_acc = _http_json(api_base, "GET", "/api/accounts", token=token)
        if c_acc == 200:
            acc = _resolve_account_from_list(d_acc.get("accounts") or [], args.target)
            if not acc:
                print(f"Account not found: {args.target}", file=sys.stderr)
                return 1
            if args.remove:
                req_body: dict[str, Any] = {"account_id": acc["id"], "action": "remove", "factor": "pin"}
            else:
                req_body = {"account_id": acc["id"], "action": "set", "factor": "pin", "pin": new_pin_val}
            c_rp, d_rp = _http_json(api_base, "POST", "/api/accounts/credentials", req_body, token)
            if c_rp == 200:
                out_obj: dict[str, Any] = {
                    "ok": True,
                    "account_id": acc["id"],
                    "has_pin": not args.remove,
                }
                if "weak_pin" in d_rp:
                    out_obj["weak_pin"] = bool(d_rp["weak_pin"])
                if human:
                    if args.remove:
                        print(f"PIN removed for {acc['display_name']} ({acc['id']}).")
                    else:
                        note = " (note: weak PIN)" if out_obj.get("weak_pin") else ""
                        print(f"PIN updated for {acc['display_name']} ({acc['id']}){note}.")
                else:
                    print(json.dumps(out_obj, ensure_ascii=False))
                return 0
            err_code = str(d_rp.get("error") or "")
            if not (c_rp == 403 and err_code in ("account.err.locked", "account.err.adminRequired") and _db_exists(base_dir)):
                if c_rp is not None:
                    print(f"Error: {_format_api_error(c_rp, d_rp)}", file=sys.stderr)
                    return 1
        elif c_acc is not None:
            print(f"Error: {_format_api_error(c_acc, d_acc)}", file=sys.stderr)
            return 1

    # Offline- & Notfall-Pfad (direkter SQLite-Zugriff auf base_dir/accounts/accounts.db, ohne laufende Gast-Session zu loeschen)
    svc = AccountService(base_dir, cleanup_guest=False)
    try:
        if args.cmd == "status":
            accounts = svc.list_accounts()
            out: dict[str, Any] = {
                "base": str(base_dir),
                "accounts_count": len(accounts),
                "migrated": svc.migration_report.migrated,
                "device_policy": svc.get_device_policy().to_dict(),
                "session": svc.get_session().to_public_dict(),
            }
            if api_base:
                out["offline"] = True
            if human:
                _print_human_status(out, offline=bool(api_base))
            else:
                print(json.dumps(out, ensure_ascii=False, indent=2))
            return 0

        if args.cmd == "list":
            accounts = svc.list_accounts()
            out_list = [a.to_public_dict() for a in accounts]
            if human:
                sess_obj = svc.get_session()
                _print_human_list(out_list, active_id=sess_obj.account_id, is_guest=sess_obj.is_guest, offline=bool(api_base))
            else:
                print(json.dumps(out_list, ensure_ascii=False, indent=2))
            return 0

        if args.cmd == "unlock":
            acc_obj = svc.find_account(args.target)
            if not acc_obj:
                print(f"Account not found: {args.target}", file=sys.stderr)
                return 1
            svc.unlock_account(acc_obj.id)
            if human:
                suffix = " (offline fallback)" if api_base else ""
                print(f"Unlocked account: {acc_obj.display_name} ({acc_obj.id}){suffix}")
            else:
                print(json.dumps({"ok": True, "account_id": acc_obj.id}, ensure_ascii=False))
            return 0

        if args.cmd == "reset-pin":
            acc_obj = svc.find_account(args.target)
            if not acc_obj:
                print(f"Account not found: {args.target}", file=sys.stderr)
                return 1
            if args.remove:
                svc.remove_credential(acc_obj.id, "pin")
                if human:
                    suffix = " (offline fallback)" if api_base else ""
                    print(f"PIN removed for {acc_obj.display_name} ({acc_obj.id}){suffix}.")
                else:
                    print(json.dumps({"ok": True, "account_id": acc_obj.id, "has_pin": False}, ensure_ascii=False))
                return 0
            assert new_pin_val is not None
            updated = svc.set_credential(acc_obj.id, "pin", new_pin_val)
            if human:
                suffix = " (offline fallback)" if api_base else ""
                print(f"PIN updated for {updated.display_name} ({updated.id}){suffix}.")
            else:
                print(json.dumps({"ok": True, "account_id": updated.id, "has_pin": updated.has_pin}, ensure_ascii=False))
            return 0

        if args.cmd == "bootstrap":
            payload = _read_secret_json(args.secret_file)
            name = str(payload.get("display_name") or "").strip()
            auto_login = payload.get("auto_login")
            ask_on_boot = payload.get("ask_on_boot")
            password = payload.get("password")
            raw_pin = payload.get("pin")
            pin_val = str(raw_pin) if raw_pin is not None and str(raw_pin) != "" else None
            pw_val = str(password) if password is not None and str(password) != "" else None
            accounts = svc.list_accounts()
            admin = next((a for a in accounts if a.role == "admin"), None)
            if admin is None:
                admin = svc.create_account(
                    display_name=name or "VoidStation",
                    role="admin",
                    auto_login=True if auto_login is None else bool(auto_login),
                    password=pw_val,
                    pin=pin_val,
                )
            else:
                if name or auto_login is not None:
                    admin = svc.update_account(
                        admin.id,
                        display_name=name or None,
                        auto_login=bool(auto_login) if auto_login is not None else None,
                    )
                if pw_val is not None:
                    admin = svc.set_credential(admin.id, "password", pw_val)
                if pin_val is not None:
                    admin = svc.set_credential(admin.id, "pin", pin_val)
            if ask_on_boot is not None:
                svc.set_device_policy(ask_on_boot=bool(ask_on_boot), default_account_id=admin.id)
            else:
                svc.set_device_policy(default_account_id=admin.id)
            print(json.dumps({"ok": True, "admin": admin.to_public_dict()}, ensure_ascii=False))
            return 0
    except (AccountError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        svc.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
