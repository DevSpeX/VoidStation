#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit- & Integrations-Tests fuer das VoidStation-Account-System (Stufe 1 bis 6)."""
from __future__ import annotations

import ast
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "launcher"))

import launcher  # noqa: E402
import vsaccount  # noqa: E402
import vsreport  # noqa: E402
from vsaccount import (  # noqa: E402
    AccountService,
    PolicyError,
    ValidationError,
    cli as account_cli,
    crypto as account_crypto,
)


class FakeClock:
    """Deterministische Uhr fuer Cooldown- und Timestamp-Tests."""

    def __init__(self, now: float = 1_700_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


class VsAccountStage1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.base = self.root / "voidstation"
        self.runtime = self.root / "runtime"
        self.base.mkdir(parents=True)
        self.runtime.mkdir(parents=True)
        self.clock = FakeClock()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_crypto_scrypt_pbkdf2_and_validation(self) -> None:
        pw_hash = account_crypto.hash_secret("SuperGeheim!123", factor="password", preferred_algo="vs-scrypt")
        self.assertTrue(pw_hash.startswith("$vs-scrypt$"))
        ok, rehash = account_crypto.verify_secret("SuperGeheim!123", pw_hash, factor="password")
        self.assertTrue(ok)
        self.assertIsInstance(rehash, bool)
        self.assertEqual(account_crypto.verify_secret("falsch", pw_hash, factor="password")[0], False)

        pin_hash = account_crypto.hash_secret("4279", factor="pin", preferred_algo="vs-pbkdf2-sha256")
        self.assertTrue(pin_hash.startswith("$vs-pbkdf2-sha256$"))
        ok_pin, rehash_pin = account_crypto.verify_secret("4279", pin_hash, factor="pin")
        self.assertTrue(ok_pin)
        self.assertTrue(rehash_pin)  # Upgrade von PBKDF2 auf Standard-KDF gewuenscht

        with self.assertRaises(ValidationError) as ctx_pin:
            account_crypto.hash_secret("12ab", factor="pin")
        self.assertNotIn("12ab", str(ctx_pin.exception))

        with self.assertRaises(ValidationError) as ctx_pw:
            account_crypto.hash_secret("", factor="password")
        self.assertEqual(ctx_pw.exception.code, "account.err.pwFormat")

    def test_bruteforce_cooldown_persistence_and_pin_hard_lock(self) -> None:
        svc = AccountService(self.base, runtime_dir=self.runtime, clock=self.clock)
        admin = svc.list_accounts()[0]
        svc.set_credential(admin.id, "password", "ElternPass99")
        svc.set_credential(admin.id, "pin", "2580")

        # 3 Fehlversuche ohne Wartezeit
        for _ in range(3):
            r = svc.authenticate(admin.id, "pin", "9999")
            self.assertFalse(r.ok)
            self.assertEqual(r.retry_after, 0)

        # 4. Fehlversuch loest 15s Cooldown aus
        r4 = svc.authenticate(admin.id, "pin", "9999")
        self.assertFalse(r4.ok)
        self.assertEqual(r4.error, "account.cooldown")
        self.assertEqual(r4.retry_after, 15)

        # Cooldown bleibt nach Neustart des AccountService erhalten
        svc.close()
        svc2 = AccountService(self.base, runtime_dir=self.runtime, clock=self.clock)
        r_blocked = svc2.authenticate(admin.id, "pin", "2580")
        self.assertFalse(r_blocked.ok)
        self.assertEqual(r_blocked.error, "account.cooldown")
        self.assertGreater(r_blocked.retry_after, 0)

        # Nach Ablauf von 15s -> 5. Fehlversuch -> 60s; weiter bis zum Hard-Lock (8. Fehlversuch)
        expected_waits = [60, 300, 900]
        self.clock.advance(16)
        for wait in expected_waits:
            rx = svc2.authenticate(admin.id, "pin", "9999")
            self.assertFalse(rx.ok)
            self.assertEqual(rx.retry_after, wait)
            self.clock.advance(wait + 1)

        # 8. Fehlversuch -> PIN dauerhaft gesperrt, auch richtige PIN wird abgewiesen
        r8 = svc2.authenticate(admin.id, "pin", "9999")
        self.assertTrue(r8.hard_locked)
        self.assertEqual(r8.error, "account.err.pinLocked")
        r_locked = svc2.authenticate(admin.id, "pin", "2580")
        self.assertTrue(r_locked.hard_locked)

        # Entsperrung per Passwort hebt auch die PIN-Sperre auf
        r_pw = svc2.authenticate(admin.id, "password", "ElternPass99")
        self.assertTrue(r_pw.ok)
        self.assertTrue(svc2.authenticate(admin.id, "pin", "2580").ok)

        # Alternative Entsperrung per unlock_account()
        for _ in range(8):
            res = svc2.authenticate(admin.id, "pin", "0000")
            if res.retry_after > 0:
                self.clock.advance(res.retry_after + 1)
        self.assertTrue(svc2.authenticate(admin.id, "pin", "2580").hard_locked)
        svc2.unlock_account(admin.id, "pin")
        self.assertTrue(svc2.authenticate(admin.id, "pin", "2580").ok)
        svc2.close()

    def test_roles_invariants_and_public_dict(self) -> None:
        svc = AccountService(self.base, runtime_dir=self.runtime, clock=self.clock)
        admin = svc.list_accounts()[0]
        self.assertEqual(admin.role, "admin")

        # Letzter Admin darf nicht geloescht oder herabgestuft werden
        with self.assertRaises(PolicyError):
            svc.delete_account(admin.id)
        with self.assertRaises(PolicyError):
            svc.update_account(admin.id, role="standard")
        with self.assertRaises(PolicyError):
            svc.update_account(admin.id, active=False)

        # Kind braucht aktiven Admin mit PIN/Passwort als parent_id
        with self.assertRaises(PolicyError):
            svc.create_account("Kind Ohne Eltern", role="child")
        with self.assertRaises(PolicyError) as ctx_no_auth:
            svc.create_account("Kind Ohne Eltern-PIN", role="child", parent_id=admin.id)
        self.assertEqual(ctx_no_auth.exception.code, "account.err.parentAuthRequired")

        svc.set_credential(admin.id, "pin", "2580")

        std = svc.create_account("Alex", role="standard", pin="1357")
        with self.assertRaises(PolicyError):
            svc.create_account("Kind Falscher Parent", role="child", parent_id=std.id)

        child = svc.create_account("Lina", role="child", parent_id=admin.id, pin="2468")
        self.assertEqual(child.parent_id, admin.id)

        # Solange ein Kinderkonto existiert, darf der letzte Admin-Schutz nicht entfernt werden
        with self.assertRaises(PolicyError) as ctx_rm:
            svc.remove_credential(admin.id, "pin")
        self.assertEqual(ctx_rm.exception.code, "account.err.parentAuthRequired")

        pub = std.to_public_dict()
        self.assertTrue(pub["has_pin"])
        self.assertFalse(pub["has_password"])
        self.assertNotIn("hash", json.dumps(pub))
        self.assertNotIn("1357", json.dumps(pub))
        svc.close()

    def test_legacy_migration_and_strict_profile_isolation(self) -> None:
        # Legacy-Fixture anlegen
        (self.base / "tiles.json").write_text(json.dumps({"user": "Anna", "groups": []}), encoding="utf-8")
        legacy_settings = {
            "lang": "en",
            "theme": "nord",
            "scale": 1.5,
            "ui_sounds": False,
            "ui_sounds_preset": "retro",
            "resolution": "1920x1080",
            "sysupd_days": 60,
        }
        (self.base / "settings.json").write_text(json.dumps(legacy_settings), encoding="utf-8")
        legacy_radio = [{"name": "FM4", "url": "https://example.invalid/fm4"}]
        legacy_tv = [{"id": "arte", "name": "ARTE"}]
        (self.base / "radio.json").write_text(json.dumps(legacy_radio), encoding="utf-8")
        (self.base / "tvfavs.json").write_text(json.dumps(legacy_tv), encoding="utf-8")
        (self.base / "resume.json").write_text(json.dumps({"movie.mkv": 120}), encoding="utf-8")
        (self.base / "yt-subs.json").write_text(json.dumps([{"id": "UC1"}]), encoding="utf-8")

        svc = AccountService(self.base, runtime_dir=self.runtime, clock=self.clock)
        self.assertTrue(svc.migration_report.migrated)
        self.assertEqual(svc.migration_report.display_name, "Anna")
        admin_id = svc.migration_report.admin_id

        # Alte globale Dateien bleiben als unveraendertes Backup bestehen
        self.assertEqual(json.loads((self.base / "radio.json").read_text(encoding="utf-8")), legacy_radio)

        # Profil-Dateien und prefs liegen in accounts/data/<admin_id>/
        pdir = self.base / "accounts" / "data" / admin_id
        self.assertTrue((pdir / "radio.json").is_file())
        self.assertTrue((pdir / "tvfavs.json").is_file())
        self.assertTrue((pdir / "resume.json").is_file())
        self.assertTrue((pdir / "yt-subs.json").is_file())
        prefs = svc.load_profile_prefs({"lang": "de", "theme": "default-dark"})
        self.assertEqual(prefs["lang"], "en")
        self.assertEqual(prefs["theme"], "nord")
        self.assertEqual(prefs["ui_sounds_preset"], "retro")
        self.assertNotIn("resolution", prefs)  # geraeteweit, nicht im Profil

        # Aenderungen schreiben ausschliesslich ins Profil, nie in die alten globalen Dateien
        svc.save_profile_prefs({"theme": "high-contrast"})
        radio_path = svc.profile_path("radio.json")
        self.assertEqual(radio_path.parent, pdir)
        radio_path.write_text(json.dumps([{"name": "Changed"}]), encoding="utf-8")
        self.assertEqual(json.loads((self.base / "radio.json").read_text(encoding="utf-8")), legacy_radio)
        self.assertEqual(json.loads((self.base / "settings.json").read_text(encoding="utf-8"))["theme"], "nord")

        # Zweites Profil hat komplett getrennte Dateien
        bob = svc.create_account("Bob", role="standard")
        svc.switch_account(bob.id)
        self.assertNotEqual(svc.profile_path("radio.json"), radio_path)
        self.assertFalse(svc.profile_path("radio.json").exists())

        # Zweiter Start migriert nicht nochmal
        svc.close()
        svc2 = AccountService(self.base, runtime_dir=self.runtime, clock=self.clock)
        self.assertFalse(svc2.migration_report.migrated)
        self.assertEqual(len(svc2.list_accounts()), 2)
        svc2.close()

    def test_guest_session_ephemeral_and_permissions(self) -> None:
        svc = AccountService(self.base, runtime_dir=self.runtime, clock=self.clock)
        admin = svc.list_accounts()[0]

        with self.assertRaises(PolicyError):
            svc.start_guest_session()

        svc.set_device_policy(guest_enabled=True)
        guest = svc.start_guest_session()
        self.assertTrue(guest.is_guest)

        # Gast erbt auch ohne guest_allowed_tiles immer Terminal-, Dateimanager-, Browser-, Werkzeug- & AppCenter-Sperren
        self.assertFalse(svc.parental.check_tile("terminal").allowed)
        self.assertFalse(svc.parental.check_tile("files").allowed)
        self.assertFalse(svc.parental.check_tile("firefox").allowed)
        self.assertFalse(svc.parental.check_tile("custom_br", cmd=["chromium"]).allowed)
        self.assertFalse(svc.parental.check_tile("appcenter").allowed)
        self.assertFalse(svc.parental.check_tile("htop", cat="Werkzeuge").allowed)
        self.assertTrue(svc.parental.check_tile("tv").allowed)
        self.assertTrue(svc.parental.check_tile("youtube", cmd=["firefox", "--kiosk", "https://www.youtube.com"]).allowed)

        # Selbst wenn guest_allowed_tiles gesperrte Kacheln enthaelt, bleiben sie fuer den Gast gesperrt
        svc.set_device_policy(guest_allowed_tiles=["terminal", "files", "firefox", "tv"])
        self.assertFalse(svc.parental.check_tile("terminal").allowed)
        self.assertFalse(svc.parental.check_tile("files").allowed)
        self.assertFalse(svc.parental.check_tile("firefox").allowed)
        self.assertTrue(svc.parental.check_tile("tv").allowed)
        svc.set_device_policy(guest_allowed_tiles=[])

        guest_radio = svc.profile_path("radio.json")
        guest_radio.write_text("[]", encoding="utf-8")
        svc.save_profile_prefs({"lang": "en"})
        guest_dir = self.runtime / "voidstation-guest"
        self.assertTrue(guest_dir.is_dir())
        self.assertEqual(_mode(guest_dir), 0o700)

        # Berechtigungen pruefen
        self.assertEqual(_mode(self.base / "accounts"), 0o700)
        self.assertEqual(_mode(self.base / "accounts" / "accounts.db"), 0o600)
        self.assertEqual(_mode(self.base / "accounts" / "data" / admin.id), 0o700)

        # Wechsel oder Lock loescht Gast-Verzeichnis restlos
        svc.switch_account(admin.id)
        self.assertFalse(guest_dir.exists())

        svc.start_guest_session()
        svc.profile_path("tvfavs.json").write_text("[]", encoding="utf-8")
        self.assertTrue(guest_dir.exists())
        svc.lock_session()
        self.assertFalse(guest_dir.exists())

        svc.start_guest_session()
        self.assertTrue(guest_dir.exists())
        svc.close()
        self.assertFalse(guest_dir.exists())

    def test_vsreport_scrubs_hashes_pins_and_tokens(self) -> None:
        scrub = vsreport.Scrub()
        sample = "\n".join(
            [
                "hash=$vs-scrypt$n=32768,r=8,p=1$c2FsdA$aGFzaA",
                "pbkdf=$vs-pbkdf2-sha256$i=600000$c2FsdA$aGFzaA",
                "pin=2580",
                "X-VS-Token: super_secret_runtime_token_123456",
                "refresh_token=rt_secret_value_abc",
            ]
        )
        cleaned = scrub(sample)
        self.assertNotIn("c2FsdA", cleaned)
        self.assertNotIn("2580", cleaned)
        self.assertNotIn("super_secret_runtime_token_123456", cleaned)
        self.assertNotIn("rt_secret_value_abc", cleaned)
        self.assertIn("[hash]", cleaned)

    def test_cli_bootstrap_status_list_unlock(self) -> None:
        payload = json.dumps({"display_name": "Wohnzimmer", "password": "StartPass123", "pin": "5588"})
        orig_stdin = sys.stdin
        try:
            sys.stdin = io.StringIO(payload)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = account_cli.main(["--base", str(self.base), "bootstrap"])
            self.assertEqual(rc, 0)
            boot_out = json.loads(buf.getvalue())
            self.assertTrue(boot_out["ok"])
            self.assertEqual(boot_out["admin"]["display_name"], "Wohnzimmer")
            self.assertTrue(boot_out["admin"]["has_pin"])
            self.assertTrue(boot_out["admin"]["has_password"])
        finally:
            sys.stdin = orig_stdin

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = account_cli.main(["--base", str(self.base), "list"])
        self.assertEqual(rc, 0)
        listed = json.loads(buf.getvalue())
        self.assertEqual(len(listed), 1)
        self.assertNotIn("5588", buf.getvalue())
        self.assertNotIn("StartPass123", buf.getvalue())

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = account_cli.main(["--base", str(self.base), "status"])
        self.assertEqual(rc, 0)
        st = json.loads(buf.getvalue())
        self.assertEqual(st["accounts_count"], 1)

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = account_cli.main(["--base", str(self.base), "unlock", "Wohnzimmer"])
        self.assertEqual(rc, 0)

        # Ungueltige Permissions auf secret-file ablehnen
        bad_secret = self.root / "bad.json"
        bad_secret.write_text(payload, encoding="utf-8")
        os.chmod(bad_secret, 0o644)
        rc_bad = account_cli.main(["--base", str(self.base), "bootstrap", "--secret-file", str(bad_secret)])
        self.assertEqual(rc_bad, 1)


class VsAccountStage2BackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.base = self.root / "voidstation"
        self.runtime = self.root / "runtime"
        self.share = self.root / "share"
        self.base.mkdir(parents=True)
        self.runtime.mkdir(parents=True)
        self.share.mkdir(parents=True)
        self.clock = FakeClock()

        self._orig_env = {
            k: os.environ.get(k)
            for k in ("VS_NO_DESKTOP_SYNC", "VS_SOUNDS", "XDG_RUNTIME_DIR", "VOIDSTATION_BASE")
        }
        os.environ["VS_NO_DESKTOP_SYNC"] = "1"
        os.environ["VS_SOUNDS"] = "0"
        os.environ["XDG_RUNTIME_DIR"] = str(self.runtime)
        os.environ["VOIDSTATION_BASE"] = str(self.base)

        self._orig_settings = launcher.SETTINGS
        self._orig_config = launcher.CONFIG
        self._orig_share = launcher.MEDIA.share

        self.tiles_path = self.base / "tiles.json"
        self.settings_path = self.base / "settings.json"
        self.tiles_path.write_text(
            json.dumps(
                {
                    "title": "Start",
                    "user": "LegacyUser",
                    "groups": [{"name": "System", "tiles": [{"id": "settings", "label": "Settings"}]}],
                }
            ),
            encoding="utf-8",
        )
        self.settings_path.write_text(
            json.dumps({"lang": "de", "theme": "default-dark", "padmouse": True, "sysupd_days": 90}),
            encoding="utf-8",
        )
        launcher.CONFIG = self.tiles_path
        launcher.SETTINGS = self.settings_path
        launcher.MEDIA.share = lambda: self.share  # type: ignore[method-assign]

        self.token = launcher.init_api_token(runtime_dir=self.runtime)
        self.svc = launcher.init_accounts(base_dir=self.base, runtime_dir=self.runtime, clock=self.clock)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), launcher.Handler)
        self.port = self.httpd.server_port
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        launcher.close_accounts()
        launcher.CONFIG = self._orig_config
        launcher.SETTINGS = self._orig_settings
        launcher.MEDIA.share = self._orig_share  # type: ignore[method-assign]
        with launcher._API_TOKEN_LOCK:
            launcher._API_TOKEN = ""
            launcher._RUNTIME_DIR_OVERRIDE = None
        for k, v in self._orig_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def _req(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        xtv: bool = True,
        token: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        headers: dict[str, str] = {}
        if xtv:
            headers["X-TV"] = "1"
        tok = self.token if token is None else token
        if tok:
            headers[vsaccount.API_TOKEN_HEADER] = tok
        data: bytes | None = None
        if body is not None or method == "POST":
            headers["Content-Type"] = "application/json"
            data = json.dumps({} if body is None else body).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=data,
            method=method,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = resp.read().decode("utf-8", "replace")
                return resp.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            with exc:
                raw = exc.read().decode("utf-8", "replace")
                code = exc.code
            try:
                parsed = json.loads(raw) if raw else {}
            except ValueError:
                parsed = {"raw": raw}
            return code, parsed

    def test_runtime_token_permissions_enforcement_and_osk_compat(self) -> None:
        tok_file = self.runtime / vsaccount.API_TOKEN_FILENAME
        self.assertTrue(tok_file.is_file())
        self.assertEqual(_mode(tok_file), 0o600)
        self.assertEqual(tok_file.read_text(encoding="utf-8").strip(), self.token)

        for method, path in (
            ("GET", "/api/session"),
            ("GET", "/api/accounts"),
            ("POST", "/api/session/lock"),
            ("POST", "/api/accounts/create"),
        ):
            code_missing, _ = self._req(method, path, token="")
            self.assertEqual(code_missing, 403, f"expected 403 without token on {method} {path}")
            code_wrong, _ = self._req(method, path, token="wrong-token-value")
            self.assertEqual(code_wrong, 403, f"expected 403 with wrong token on {method} {path}")
            code_no_xtv, _ = self._req(method, path, xtv=False, token=self.token)
            self.assertEqual(code_no_xtv, 403, f"expected 403 without X-TV on {method} {path}")

        code_sess, sess_data = self._req("GET", "/api/session")
        self.assertEqual(code_sess, 200)
        self.assertEqual(sess_data["session"]["display_name"], "LegacyUser")

        # Browser-OSK-Erweiterung nutzt weiterhin ausschliesslich X-TV: 1 ohne Token
        code_osk, osk_data = self._req("POST", "/api/osk/field", {"ev": "blur"}, xtv=True, token="")
        self.assertEqual(code_osk, 200)
        self.assertTrue(osk_data["ok"])
        code_osk_no_xtv, _ = self._req("POST", "/api/osk/field", {"ev": "blur"}, xtv=False, token=self.token)
        self.assertEqual(code_osk_no_xtv, 403)

    def test_session_and_account_routes_rbac_and_tiles_compat(self) -> None:
        admin_id = self.svc.list_accounts()[0].id

        code_st, st = self._req("GET", "/api/status", xtv=False, token="")
        self.assertEqual(code_st, 200)
        self.assertEqual(st["account"]["id"], admin_id)
        self.assertEqual(st["account"]["name"], "LegacyUser")
        self.assertEqual(st["account"]["role"], "admin")
        self.assertEqual(st["account"]["count"], 1)

        code_tiles, tiles = self._req("GET", "/tiles.json", xtv=False, token="")
        self.assertEqual(code_tiles, 200)
        self.assertEqual(tiles["user"], "LegacyUser")

        # Konten anlegen
        c_std, d_std = self._req(
            "POST",
            "/api/accounts/create",
            {"display_name": "Alex", "role": "standard", "pin": "2468"},
        )
        self.assertEqual(c_std, 200)
        std_id = d_std["account"]["id"]
        self.assertTrue(d_std["account"]["has_pin"])

        c_child_fail, _ = self._req("POST", "/api/accounts/create", {"display_name": "Kind", "role": "child"})
        self.assertEqual(c_child_fail, 403)

        # Admin ohne PIN/Passwort darf kein Kinder-Konto anlegen
        c_child_noauth, d_child_noauth = self._req(
            "POST",
            "/api/accounts/create",
            {"display_name": "Lina", "role": "child", "parent_id": admin_id, "pin": "1357"},
        )
        self.assertEqual(c_child_noauth, 403)
        self.assertEqual(d_child_noauth["error"], "account.err.parentAuthRequired")

        # Nach Setzen einer Eltern-PIN klappt es
        self.assertEqual(
            self._req("POST", "/api/accounts/credentials", {"account_id": admin_id, "factor": "pin", "secret": "2580"})[0],
            200,
        )
        c_child, d_child = self._req(
            "POST",
            "/api/accounts/create",
            {"display_name": "Lina", "role": "child", "parent_id": admin_id, "pin": "1357"},
        )
        self.assertEqual(c_child, 200)
        child_id = d_child["account"]["id"]

        # Admin umbenennen -> /tiles.json["user"] spiegelt neuen Namen, Datei auf Platte bleibt unberuehrt
        c_upd, _ = self._req("POST", "/api/accounts/update", {"account_id": admin_id, "display_name": "Eltern"})
        self.assertEqual(c_upd, 200)
        _, tiles_after = self._req("GET", "/tiles.json", xtv=False, token="")
        self.assertEqual(tiles_after["user"], "Eltern")
        self.assertEqual(json.loads(self.tiles_path.read_text(encoding="utf-8"))["user"], "LegacyUser")

        # Credentials setzen (inkl. weak_pin-Hinweis), pruefen beim Wechsel + Cooldown
        c_cred, d_cred = self._req(
            "POST",
            "/api/accounts/credentials",
            {"account_id": std_id, "factor": "pin", "secret": "1234"},
        )
        self.assertEqual(c_cred, 200)
        self.assertTrue(d_cred["weak_pin"])

        c_acc, d_acc = self._req("GET", "/api/accounts")
        self.assertEqual(c_acc, 200)
        self.assertEqual(len(d_acc["accounts"]), 3)
        self.assertNotIn("hash", json.dumps(d_acc))
        self.assertNotIn("1234", json.dumps(d_acc))

        for _ in range(3):
            c_bad, _ = self._req("POST", "/api/session/switch", {"account_id": std_id, "pin": "9999"})
            self.assertEqual(c_bad, 401)
        c_cd, d_cd = self._req("POST", "/api/session/switch", {"account_id": std_id, "pin": "9999"})
        self.assertEqual(c_cd, 429)
        self.assertEqual(d_cd["error"], "account.cooldown")
        self.assertEqual(d_cd["retry_after"], 15)

        self.clock.advance(16)
        c_ok, d_ok = self._req("POST", "/api/session/switch", {"account_id": std_id, "pin": "1234"})
        self.assertEqual(c_ok, 200)
        self.assertEqual(d_ok["session"]["account_id"], std_id)

        _, st2 = self._req("GET", "/api/status", xtv=False, token="")
        self.assertEqual(st2["account"]["id"], std_id)
        self.assertEqual(st2["account"]["name"], "Alex")
        _, tiles2 = self._req("GET", "/tiles.json", xtv=False, token="")
        self.assertEqual(tiles2["user"], "Alex")

        # RBAC als Standard-User: verbotene Admin-Aktionen -> 403, eigenes kosmetisches Update -> 200
        self.assertEqual(self._req("POST", "/api/accounts/create", {"display_name": "X"})[0], 403)
        self.assertEqual(self._req("POST", "/api/accounts/delete", {"account_id": child_id})[0], 403)
        self.assertEqual(self._req("POST", "/api/accounts/device-policy", {"guest_enabled": True})[0], 403)
        self.assertEqual(self._req("POST", "/api/accounts/update", {"account_id": std_id, "role": "admin"})[0], 403)
        self.assertEqual(self._req("POST", "/api/accounts/update", {"account_id": admin_id, "display_name": "Hack"})[0], 403)
        self.assertEqual(self._req("POST", "/api/accounts/update", {"account_id": std_id, "avatar": "gamepad"})[0], 200)

        # Child darf keine Konto-Mutationen durchfuehren
        self.assertEqual(self._req("POST", "/api/session/switch", {"account_id": child_id, "pin": "1357"})[0], 200)
        self.assertEqual(self._req("POST", "/api/accounts/update", {"account_id": child_id, "avatar": "star"})[0], 403)

        # Lock sperrt geschuetzte Mutationen
        c_lock, d_lock = self._req("POST", "/api/session/lock")
        self.assertEqual(c_lock, 200)
        self.assertTrue(d_lock["session"]["locked"])
        self.assertEqual(self._req("POST", "/api/accounts/create", {"display_name": "Locked"})[0], 403)

        # Als Admin wieder anmelden (mit PIN), Policy setzen, Standard-Konto loeschen (letzter Admin bleibt geschuetzt)
        self.assertEqual(self._req("POST", "/api/session/switch", {"account_id": admin_id})[0], 401)
        self.assertEqual(self._req("POST", "/api/session/switch", {"account_id": admin_id, "pin": "2580"})[0], 200)
        c_pol, d_pol = self._req(
            "POST",
            "/api/accounts/device-policy",
            {"ask_on_boot": True, "guest_enabled": True, "guest_allowed_tiles": ["tv", "radio"]},
        )
        self.assertEqual(c_pol, 200)
        self.assertTrue(d_pol["device_policy"]["ask_on_boot"])
        self.assertEqual(d_pol["device_policy"]["guest_allowed_tiles"], ["tv", "radio"])

        self.assertEqual(self._req("POST", "/api/accounts/delete", {"account_id": admin_id})[0], 403)
        c_del, _ = self._req("POST", "/api/accounts/delete", {"account_id": std_id})
        self.assertEqual(c_del, 200)
        self.assertFalse((self.base / "accounts" / "data" / std_id).exists())

    def test_profile_files_and_prefs_strict_isolation_via_backend(self) -> None:
        admin_id = self.svc.list_accounts()[0].id
        _, d_bob = self._req("POST", "/api/accounts/create", {"display_name": "Bob", "role": "standard"})
        bob_id = d_bob["account"]["id"]

        # Legacy-Dateien in base_dir duerfen bei Profil-Schreibvorgaengen nie ueberschrieben werden
        legacy_radio = [{"name": "LegacyFM", "url": "https://legacy.invalid/fm"}]
        legacy_tvfavs = [{"key": "legacy1", "name": "LegacyTV", "url": "https://legacy.invalid/tv"}]
        legacy_tvrecent = [{"key": "legacy1", "name": "LegacyTV", "url": "https://legacy.invalid/tv"}]
        legacy_resume = {"legacy.mkv": {"pos": 90, "dur": 600, "t": 1}}
        legacy_yt = [{"id": "UClegacy"}]
        (self.base / "radio.json").write_text(json.dumps(legacy_radio), encoding="utf-8")
        (self.base / "tvfavs.json").write_text(json.dumps(legacy_tvfavs), encoding="utf-8")
        (self.base / "tvrecent.json").write_text(json.dumps(legacy_tvrecent), encoding="utf-8")
        (self.base / "resume.json").write_text(json.dumps(legacy_resume), encoding="utf-8")
        (self.base / "yt-subs.json").write_text(json.dumps(legacy_yt), encoding="utf-8")
        (self.base / "yt-history.json").write_text(json.dumps(legacy_yt), encoding="utf-8")
        (self.base / "yt-later.json").write_text(json.dumps(legacy_yt), encoding="utf-8")

        video_file = self.share / "Videos" / "demo.mkv"
        video_file.parent.mkdir(parents=True, exist_ok=True)
        video_file.write_bytes(b"demo")

        # Profil Admin schreibt Daten & Praeferenzen
        self.assertEqual(
            self._req(
                "POST",
                "/api/radio/fav",
                {"name": "AdminRadio", "url": "https://example.invalid/admin", "country": "DE"},
            )[0],
            200,
        )
        launcher.tvfavs_save([{"key": "admin_tv", "name": "AdminTV", "url": "https://example.invalid/tv"}])
        launcher.tvrecent_save([{"key": "admin_tv", "name": "AdminTV", "url": "https://example.invalid/tv"}])
        launcher.MEDIA.resume_set(str(video_file), 120, 600)
        launcher.YT.sub_set({"item": {"id": "UC1234567890123456789012", "title": "AdminChan"}, "on": True})
        launcher.YT.later_set({"item": {"id": "dQw4w9WgXcQ", "title": "AdminLater"}, "on": True})
        launcher.YT.progress({"id": "dQw4w9WgXcQ", "title": "AdminHist", "pos": 50, "dur": 200})

        self.assertEqual(self._req("POST", "/api/settings/lang", {"lang": "en"})[0], 200)
        self.assertEqual(self._req("POST", "/api/settings/theme", {"theme": "nord"})[0], 200)
        self.assertEqual(self._req("POST", "/api/settings/scale", {"scale": 1.5})[0], 200)
        self.assertEqual(self._req("POST", "/api/settings/sounds", {"on": False, "preset": "retro", "volume": 45})[0], 200)
        self.assertEqual(self._req("POST", "/api/settings/osk", {"layout": "us", "mode": "always"})[0], 200)

        # Globale Altdateien & settings.json bleiben unberuehrt
        self.assertEqual(json.loads((self.base / "radio.json").read_text(encoding="utf-8")), legacy_radio)
        self.assertEqual(json.loads((self.base / "tvfavs.json").read_text(encoding="utf-8")), legacy_tvfavs)
        self.assertEqual(json.loads((self.base / "tvrecent.json").read_text(encoding="utf-8")), legacy_tvrecent)
        self.assertEqual(json.loads((self.base / "resume.json").read_text(encoding="utf-8")), legacy_resume)
        self.assertEqual(json.loads((self.base / "yt-subs.json").read_text(encoding="utf-8")), legacy_yt)
        self.assertEqual(json.loads(self.settings_path.read_text(encoding="utf-8"))["theme"], "default-dark")
        self.assertEqual(json.loads(self.settings_path.read_text(encoding="utf-8"))["lang"], "de")

        # Geraeteweite Einstellung aendert settings.json, ohne Profil-Praeferenzen dorthin zu schreiben
        self.assertEqual(self._req("POST", "/api/settings/padmouse", {"on": False})[0], 200)
        raw_sett = json.loads(self.settings_path.read_text(encoding="utf-8"))
        self.assertFalse(raw_sett["padmouse"])
        self.assertEqual(raw_sett["theme"], "default-dark")
        self.assertEqual(raw_sett["lang"], "de")

        # Wechsel zu Bob: komplett getrennte Profildaten und Praeferenzen
        self.assertEqual(self._req("POST", "/api/session/switch", {"account_id": bob_id})[0], 200)
        _, bob_favs = self._req("GET", "/api/radio/favs")
        self.assertEqual(bob_favs, [])
        self.assertEqual(launcher.tvfavs_load(), [])
        self.assertEqual(launcher.tvrecent_load(), [])
        self.assertEqual(launcher.MEDIA.resume_load(), {})
        self.assertEqual(launcher.YT.subs(), [])
        self.assertEqual(launcher.YT.later()["items"], [])
        self.assertEqual(launcher.YT.history()["items"], [])

        _, bob_sett = self._req("GET", "/api/settings")
        self.assertEqual(bob_sett["lang"], "de")
        self.assertEqual(bob_sett["theme"], "default-dark")
        self.assertEqual(bob_sett["scale"], 1.75)
        self.assertFalse(bob_sett["padmouse"])

        # Zurueck zu Admin: dessen Dateien & Praeferenzen sind intakt
        self.assertEqual(self._req("POST", "/api/session/switch", {"account_id": admin_id})[0], 200)
        _, raw_admin_favs = self._req("GET", "/api/radio/favs")
        admin_favs: Any = raw_admin_favs
        self.assertEqual(len(admin_favs), 1)
        self.assertEqual(admin_favs[0]["name"], "AdminRadio")
        _, admin_sett = self._req("GET", "/api/settings")
        self.assertEqual(admin_sett["lang"], "en")
        self.assertEqual(admin_sett["theme"], "nord")
        self.assertEqual(admin_sett["sounds"]["preset"], "retro")

    def test_guest_mode_ephemeral_and_cleanup(self) -> None:
        admin_id = self.svc.list_accounts()[0].id
        guest_dir = self.runtime / "voidstation-guest"

        # Gast deaktiviert -> 403
        self.assertEqual(self._req("POST", "/api/session/guest")[0], 403)
        self.assertEqual(self._req("POST", "/api/accounts/device-policy", {"guest_enabled": True})[0], 200)

        # Gast starten & Daten schreiben -> liegen nur im fluchtigen Runtime-Ordner
        c_g, d_g = self._req("POST", "/api/session/guest", {"display_name": "Besucher"})
        self.assertEqual(c_g, 200)
        self.assertTrue(d_g["session"]["is_guest"])
        self.assertEqual(
            self._req("POST", "/api/radio/fav", {"name": "GuestFM", "url": "https://example.invalid/guest"})[0],
            200,
        )
        self.assertEqual(self._req("POST", "/api/settings/lang", {"lang": "en"})[0], 200)
        self.assertTrue((guest_dir / "radio.json").is_file())
        self.assertTrue((guest_dir / "prefs.json").is_file())

        # Cleanup (a) beim Profilwechsel
        self.assertEqual(self._req("POST", "/api/session/switch", {"account_id": admin_id})[0], 200)
        self.assertFalse(guest_dir.exists())

        # Cleanup (b) beim Sperren
        self.assertEqual(self._req("POST", "/api/session/guest")[0], 200)
        self.assertTrue(guest_dir.is_dir())
        self.assertEqual(self._req("POST", "/api/session/lock")[0], 200)
        self.assertFalse(guest_dir.exists())

        # Cleanup (c) beim Beenden des Backends
        self.assertEqual(self._req("POST", "/api/session/guest")[0], 200)
        self.assertTrue(guest_dir.is_dir())
        launcher.close_accounts()
        self.assertFalse(guest_dir.exists())

    def test_vsctl_and_token_helpers(self) -> None:
        env = dict(os.environ)
        env["VS_API"] = f"http://127.0.0.1:{self.port}"
        env["XDG_RUNTIME_DIR"] = str(self.runtime)

        proc = subprocess.run(
            [str(REPO / "launcher" / "vsctl"), "status"],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        status_json = json.loads(proc.stdout)
        self.assertIn("account", status_json)

        # Token-Hilfsfunktionen & Symlink-Abwehr
        self.assertTrue(vsaccount.verify_api_token(self.token, self.token))
        self.assertFalse(vsaccount.verify_api_token("invalid", self.token))
        sym_rt = self.root / "sym_rt"
        sym_rt.mkdir()
        target = self.root / "target.txt"
        target.write_text("evil", encoding="utf-8")
        (sym_rt / vsaccount.API_TOKEN_FILENAME).symlink_to(target)
        self.assertEqual(vsaccount.read_api_token(sym_rt), "")
        created = vsaccount.ensure_api_token(sym_rt)
        self.assertTrue(vsaccount.verify_api_token(created, vsaccount.read_api_token(sym_rt)))
        self.assertEqual(_mode(sym_rt / vsaccount.API_TOKEN_FILENAME), 0o600)

        # Statische Pruefung von launcher/qt/vscommon.py (ohne PySide6-Import)
        vscommon_src = (REPO / "launcher" / "qt" / "vscommon.py").read_text(encoding="utf-8")
        ast.parse(vscommon_src)
        self.assertIn("API_TOKEN_HEADER", vscommon_src)
        self.assertIn("read_api_token", vscommon_src)


class VsAccountStage4ParentalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.base = self.root / "voidstation"
        self.runtime = self.root / "runtime"
        self.base.mkdir(parents=True)
        self.runtime.mkdir(parents=True)
        # Mittags 12:00 lokale Zeit am Referenztag, leicht verschiebbar
        self.clock = FakeClock(1_700_046_000.0)

        self._orig_env = {
            k: os.environ.get(k)
            for k in ("VS_NO_DESKTOP_SYNC", "VS_SOUNDS", "XDG_RUNTIME_DIR", "VOIDSTATION_BASE")
        }
        os.environ["VS_NO_DESKTOP_SYNC"] = "1"
        os.environ["VS_SOUNDS"] = "0"
        os.environ["XDG_RUNTIME_DIR"] = str(self.runtime)
        os.environ["VOIDSTATION_BASE"] = str(self.base)

        self._orig_settings = launcher.SETTINGS
        self._orig_config = launcher.CONFIG

        self.tiles_path = self.base / "tiles.json"
        self.settings_path = self.base / "settings.json"
        self.tiles_path.write_text(
            json.dumps(
                {
                    "title": "Start",
                    "user": "Eltern",
                    "groups": [
                        {
                            "name": "Unterhaltung",
                            "tiles": [
                                {"id": "tv", "label": "Fernsehen", "type": "tv"},
                                {"id": "radio", "label": "Radio", "type": "radio"},
                                {"id": "youtube", "label": "YouTube", "cmd": ["firefox", "--kiosk", "--no-remote", "--profile", "/tmp/p", "https://youtube.com"]},
                            ],
                        },
                        {
                            "name": "Spiele",
                            "tiles": [
                                {"id": "gba", "label": "GBA", "cmd": ["mgba-qt"]},
                            ],
                        },
                        {
                            "name": "System",
                            "tiles": [
                                {"id": "clock", "type": "clock"},
                                {"id": "settings", "label": "Einstellungen", "type": "settings"},
                                {"id": "appcenter", "label": "AppCenter", "type": "apps"},
                                {"id": "firefox", "label": "Firefox", "cmd": ["firefox", "--no-remote", "--profile", "/tmp/ff", "about:home"]},
                                {"id": "terminal", "label": "Terminal", "cmd": ["xterm"]},
                            ],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.settings_path.write_text(
            json.dumps({"lang": "de", "theme": "default-dark", "padmouse": True, "sysupd_days": 90}),
            encoding="utf-8",
        )
        launcher.CONFIG = self.tiles_path
        launcher.SETTINGS = self.settings_path

        self.token = launcher.init_api_token(runtime_dir=self.runtime)
        self.svc = launcher.init_accounts(base_dir=self.base, runtime_dir=self.runtime, clock=self.clock)
        self.admin = self.svc.list_accounts()[0]
        self.svc.set_credential(self.admin.id, "pin", "2580")
        self.svc.set_credential(self.admin.id, "password", "ElternGeheim99")
        self.child = self.svc.create_account("Leo", role="child", parent_id=self.admin.id)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), launcher.Handler)
        self.port = self.httpd.server_port
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        launcher.close_accounts()
        launcher.CONFIG = self._orig_config
        launcher.SETTINGS = self._orig_settings
        with launcher._API_TOKEN_LOCK:
            launcher._API_TOKEN = ""
            launcher._RUNTIME_DIR_OVERRIDE = None
        for k, v in self._orig_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def _req(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        xtv: bool = True,
        token: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        headers: dict[str, str] = {}
        if xtv:
            headers["X-TV"] = "1"
        tok = self.token if token is None else token
        if tok:
            headers[vsaccount.API_TOKEN_HEADER] = tok
        data: bytes | None = None
        if body is not None or method == "POST":
            headers["Content-Type"] = "application/json"
            data = json.dumps({} if body is None else body).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=data,
            method=method,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = resp.read().decode("utf-8", "replace")
                return resp.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            with exc:
                raw = exc.read().decode("utf-8", "replace")
                code = exc.code
            try:
                parsed = json.loads(raw) if raw else {}
            except ValueError:
                parsed = {"raw": raw}
            return code, parsed

    def test_policy_validation_bedtime_and_browser_detection(self) -> None:
        from vsaccount import parental

        with self.assertRaises(ValidationError):
            parental.validate_policy_data(self.child.id, {"mode": "invalid"})
        with self.assertRaises(ValidationError):
            parental.validate_policy_data(self.child.id, {"max_age_rating": 21})
        with self.assertRaises(ValidationError):
            parental.validate_policy_data(self.child.id, {"bedtime_start": "20:00", "bedtime_end": ""})
        with self.assertRaises(ValidationError):
            parental.validate_policy_data(self.child.id, {"bedtime_start": "25:00", "bedtime_end": "07:00"})

        import datetime
        # Lokale Zeitpunkte deterministisch ueber datetime.timestamp() konstruieren
        ts_2230 = datetime.datetime(2026, 11, 26, 22, 30).timestamp()
        ts_0659 = datetime.datetime(2026, 11, 27, 6, 59).timestamp()
        ts_0700 = datetime.datetime(2026, 11, 27, 7, 0).timestamp()
        ts_1957 = datetime.datetime(2026, 11, 26, 19, 57).timestamp()
        self.assertEqual(parental.in_bedtime("20:00", "07:00", ts_2230), (True, None))
        self.assertEqual(parental.in_bedtime("20:00", "07:00", ts_0659), (True, None))
        self.assertFalse(parental.in_bedtime("20:00", "07:00", ts_0700)[0])
        self.assertEqual(parental.in_bedtime("20:00", "07:00", ts_1957), (False, 180))

        ts_1400 = datetime.datetime(2026, 11, 26, 14, 0).timestamp()
        ts_1256 = datetime.datetime(2026, 11, 26, 12, 56).timestamp()
        self.assertEqual(parental.in_bedtime("13:00", "15:00", ts_1400), (True, None))
        self.assertEqual(parental.in_bedtime("13:00", "15:00", ts_1256), (False, 240))

        self.assertTrue(parental.is_browser_tile("firefox", "Browser"))
        self.assertTrue(parental.is_browser_tile("braveorigin", "Browser"))
        self.assertFalse(parental.is_browser_tile("youtube", "Streaming", ["firefox", "--kiosk", "https://youtube.com"]))
        self.assertFalse(parental.is_browser_tile("ard", "Streaming", ["firefox", "--kiosk", "https://ardmediathek.de"]))

    def test_usage_tracker_warnings_lock_and_extra_minutes(self) -> None:
        import datetime

        day_start = datetime.datetime(2026, 11, 26, 19, 40, 0).timestamp()
        self.clock.now = day_start
        self.svc.set_parental_policy(
            self.child.id,
            {
                "mode": "allowlist",
                "allowed_tiles": ["tv", "gba"],
                "daily_limit_min": 10,
                "bedtime_start": "20:00",
                "bedtime_end": "07:00",
            },
        )
        self.svc.switch_account(self.child.id)

        # 9 x 30s = 270s genutzt, 330s uebrig -> noch keine Warnung
        for _ in range(9):
            self.clock.advance(30)
            self.assertEqual(self.svc.parental.tick(30), [])

        # 10. Tick -> 300s genutzt, 300s uebrig -> 5-Minuten-Warnung genau einmal
        self.clock.advance(30)
        evs_warn = self.svc.parental.tick(30)
        self.assertEqual(len(evs_warn), 1)
        self.assertEqual(evs_warn[0]["ev"], "account_warn")
        self.assertEqual(evs_warn[0]["reason"], "daily_limit")
        self.assertEqual(evs_warn[0]["minutes"], 5)

        # Weitere Ticks bis 570s (19:49:30) wiederholen Warnung nicht
        for _ in range(9):
            self.clock.advance(30)
            self.assertEqual(self.svc.parental.tick(30), [])

        # 20. Tick -> 600s genutzt -> Sperre
        self.clock.advance(30)
        evs_lock = self.svc.parental.tick(30)
        self.assertEqual(len(evs_lock), 1)
        self.assertEqual(evs_lock[0]["ev"], "account_locked")
        self.assertEqual(evs_lock[0]["reason"], "daily_limit")
        self.assertEqual(self.svc.parental.tick(30), [])  # keine Doppel-Meldung

        # Persistenz in usage_daily ueber Neustart
        launcher.close_accounts()
        self.svc = launcher.init_accounts(base_dir=self.base, runtime_dir=self.runtime, clock=self.clock)
        self.svc.switch_account(self.child.id)
        u = self.svc.parental.usage_summary(self.child.id)
        self.assertGreaterEqual(u["used_seconds"], 600)
        self.assertTrue(u["time_blocked"])

        # +15 Bonus-Minuten heben Sperre auf; um 19:57 folgt Ruhezeit-Warnung, um 20:00 Ruhezeit-Sperre
        self.svc.parental.grant_extra_minutes(self.child.id, 15)
        self.assertFalse(self.svc.parental.usage_summary(self.child.id)["time_blocked"])
        self.clock.now = datetime.datetime(2026, 11, 26, 19, 57, 0).timestamp()
        bed_warn = self.svc.parental.tick(0)
        self.assertEqual([e["reason"] for e in bed_warn], ["bedtime"])

        self.clock.now = datetime.datetime(2026, 11, 26, 20, 1, 0).timestamp()
        bed_lock = self.svc.parental.tick(0)
        self.assertEqual(len(bed_lock), 1)
        self.assertEqual(bed_lock[0]["ev"], "account_locked")
        self.assertEqual(bed_lock[0]["reason"], "bedtime")

        # +15 Minuten während Ruhezeit heben Ruhezeit temporär auf
        self.svc.parental.grant_extra_minutes(self.child.id, 15)
        self.assertFalse(self.svc.parental.usage_summary(self.child.id)["time_blocked"])

    def test_http_enforcement_tiles_launch_roms_apps_settings_power_yt(self) -> None:
        self.svc.set_parental_policy(
            self.child.id,
            {
                "mode": "allowlist",
                "allowed_tiles": ["tv", "gba"],
                "blocked_tiles": ["terminal"],
                "blocked_cats": ["Werkzeuge"],
                "max_age_rating": 12,
                "daily_limit_min": 60,
                "allow_browser": False,
                "allow_yt_search": False,
                "allow_power_menu": False,
            },
        )
        self.assertEqual(self._req("POST", "/api/session/switch", {"account_id": self.child.id})[0], 200)

        c_tiles, tiles_data = self._req("GET", "/tiles.json", xtv=False, token="")
        self.assertEqual(c_tiles, 200)
        visible_ids = [t["id"] for g in tiles_data["groups"] for t in g["tiles"]]
        self.assertEqual(set(visible_ids), {"tv", "gba", "clock", "settings"})

        # Gesperrte Kacheln -> 403 account.blocked mit jeweiligem Grund
        c_ff, d_ff = self._req("POST", "/api/launch/firefox")
        self.assertEqual(c_ff, 403)
        self.assertEqual(d_ff["error"], "account.blocked")
        self.assertEqual(d_ff["reason"], "browser_blocked")
        self.assertTrue(d_ff["override_allowed"])

        c_term, d_term = self._req("POST", "/api/launch/terminal")
        self.assertEqual(c_term, 403)
        self.assertEqual(d_term["reason"], "tile_blocked")

        c_rad, d_rad = self._req("POST", "/api/launch/radio")
        self.assertEqual(c_rad, 403)
        self.assertEqual(d_rad["reason"], "not_allowed")

        c_ac, d_ac = self._req("POST", "/api/launch/appcenter")
        self.assertEqual(c_ac, 403)
        self.assertEqual(d_ac["reason"], "admin_only")
        self.assertFalse(d_ac["override_allowed"])

        # Nicht erlaubter Emulator via /api/roms/launch -> 403
        c_rom, d_rom = self._req("POST", "/api/roms/launch", {"system": "psx", "file": "demo.chd"})
        self.assertEqual(c_rom, 403)
        self.assertEqual(d_rom["error"], "account.blocked")

        # AppCenter- & System-Settings -> 403; Power -> 403; Theme -> 200
        self.assertEqual(self._req("POST", "/api/apps/install", {"id": "gba"})[0], 403)
        self.assertEqual(self._req("POST", "/api/settings/ssh", {"on": True})[0], 403)
        self.assertEqual(self._req("POST", "/api/vpn/toggle", {})[0], 403)
        c_pwr, d_pwr = self._req("POST", "/api/power/poweroff", {})
        self.assertEqual(c_pwr, 403)
        self.assertEqual(d_pwr["reason"], "power_blocked")
        self.assertEqual(self._req("POST", "/api/settings/theme", {"theme": "nord"})[0], 200)

        # YouTube Light Suche gesperrt
        c_yt_st, d_yt_st = self._req("GET", "/api/yt/state", xtv=False, token="")
        self.assertEqual(c_yt_st, 200)
        self.assertFalse(d_yt_st["allow_search"])
        c_yt_s, d_yt_s = self._req("GET", "/api/yt/search?q=mario", xtv=False, token="")
        self.assertEqual(c_yt_s, 403)
        self.assertEqual(d_yt_s["reason"], "yt_search_blocked")

        # Gast-Modus ohne guest_allowed_tiles sperrt trotzdem Standardsperren (terminal, firefox, appcenter)
        self.assertEqual(self._req("POST", "/api/session/switch", {"account_id": self.admin.id, "pin": "2580"})[0], 200)
        self.assertEqual(
            self._req("POST", "/api/accounts/device-policy", {"guest_enabled": True, "guest_allowed_tiles": []})[0],
            200,
        )
        self.assertEqual(self._req("POST", "/api/session/guest", {"display_name": "Gast"})[0], 200)
        _, g_default_tiles = self._req("GET", "/tiles.json", xtv=False, token="")
        g_def_ids = {t["id"] for g in g_default_tiles["groups"] for t in g["tiles"]}
        self.assertIn("tv", g_def_ids)
        self.assertNotIn("terminal", g_def_ids)
        self.assertNotIn("firefox", g_def_ids)
        self.assertNotIn("appcenter", g_def_ids)
        self.assertEqual(self._req("POST", "/api/launch/terminal")[0], 403)
        self.assertEqual(self._req("POST", "/api/launch/firefox")[0], 403)

        # Gast-Modus mit guest_allowed_tiles filtert ebenfalls
        self.assertEqual(self._req("POST", "/api/session/switch", {"account_id": self.admin.id, "pin": "2580"})[0], 200)
        self.assertEqual(
            self._req("POST", "/api/accounts/device-policy", {"guest_enabled": True, "guest_allowed_tiles": ["tv"]})[0],
            200,
        )
        self.assertEqual(self._req("POST", "/api/session/guest", {"display_name": "Gast"})[0], 200)
        _, g_tiles = self._req("GET", "/tiles.json", xtv=False, token="")
        g_ids = {t["id"] for g in g_tiles["groups"] for t in g["tiles"]}
        self.assertEqual(g_ids, {"tv", "clock", "settings"})
        self.assertEqual(self._req("POST", "/api/launch/gba")[0], 403)

    def test_parent_pin_override_throttling_and_rbac(self) -> None:
        self.svc.set_parental_policy(
            self.child.id,
            {"mode": "allowlist", "allowed_tiles": ["tv"], "blocked_tiles": ["terminal"], "daily_limit_min": 1},
        )
        self.assertEqual(self._req("POST", "/api/session/switch", {"account_id": self.child.id})[0], 200)

        # RBAC auf /api/accounts/parental
        self.assertEqual(self._req("GET", "/api/accounts/parental", token="")[0], 403)
        self.assertEqual(self._req("GET", f"/api/accounts/parental?account_id={self.admin.id}")[0], 403)
        self.assertEqual(self._req("GET", "/api/accounts/parental")[0], 200)
        self.assertEqual(self._req("POST", "/api/accounts/parental", {"account_id": self.child.id, "mode": "denylist"})[0], 403)

        # Falsche Eltern-PIN -> 401 -> 429 Cooldown -> 423 Hard-Lock -> Entsperrung
        for _ in range(3):
            self.assertEqual(
                self._req("POST", "/api/accounts/parental/override", {"action": "allow_once", "tile_id": "terminal", "pin": "0000"})[0],
                401,
            )
        c_cd, d_cd = self._req(
            "POST", "/api/accounts/parental/override", {"action": "allow_once", "tile_id": "terminal", "pin": "0000"}
        )
        self.assertEqual(c_cd, 429)
        self.assertEqual(d_cd["error"], "account.cooldown")
        self.clock.advance(d_cd["retry_after"] + 1)
        for _ in range(4):
            c_step, d_step = self._req(
                "POST", "/api/accounts/parental/override", {"action": "allow_once", "tile_id": "terminal", "pin": "0000"}
            )
            if c_step == 423:
                break
            if d_step.get("retry_after"):
                self.clock.advance(d_step["retry_after"] + 1)
        self.assertEqual(c_step, 423)
        self.svc.unlock_account(self.admin.id, "pin")

        # Gueltige Eltern-PIN fuer "einmalig oeffnen" -> genau 1 Start erlaubt
        orig_launch = launcher.APPS.launch
        launched: list[str] = []

        def _fake_launch(tile: dict[str, Any]) -> str:
            launched.append(tile["id"])
            return "started"

        launcher.APPS.launch = _fake_launch  # type: ignore[method-assign]
        try:
            c_ov, d_ov = self._req(
                "POST",
                "/api/accounts/parental/override",
                {"action": "allow_once", "tile_id": "terminal", "pin": "2580"},
            )
            self.assertEqual(c_ov, 200)
            self.assertTrue(d_ov["ok"])
            self.assertEqual(self._req("POST", "/api/launch/terminal")[0], 200)
            self.assertEqual(launched, ["terminal"])
            self.assertEqual(self._req("POST", "/api/launch/terminal")[0], 403)

            # Tageslimit erschoepft -> +15 Minuten per Eltern-PIN entsperrt wieder
            from vsaccount import parental
            self.svc.store.add_usage_seconds(self.child.id, parental.local_day_key(self.clock.now), 60)
            self.assertEqual(self._req("POST", "/api/launch/tv")[0], 403)
            c_add, d_add = self._req(
                "POST",
                "/api/accounts/parental/override",
                {"action": "add_minutes", "minutes": 15, "pin": "2580"},
            )
            self.assertEqual(c_add, 200)
            self.assertFalse(d_add["parental"]["locked"])
            self.assertEqual(self._req("POST", "/api/launch/tv")[0], 200)
        finally:
            launcher.APPS.launch = orig_launch  # type: ignore[method-assign]

    def test_push_events_and_gentle_pause(self) -> None:
        orig_seq = launcher.OSK_FIELD.seq
        orig_pause = launcher.APPS.pause_background
        orig_close = launcher.APPS.close
        orig_raise = launcher.raise_home
        calls: list[str] = []

        def _fake_pause_bg(keep: Any = None) -> None:
            calls.append("pause_bg")

        def _fake_close(tid: str) -> None:
            calls.append(f"close:{tid}")

        def _fake_raise_home() -> bool:
            calls.append("raise_home")
            return True

        launcher.APPS.pause_background = _fake_pause_bg  # type: ignore[method-assign]
        launcher.APPS.close = _fake_close  # type: ignore[method-assign]
        launcher.raise_home = _fake_raise_home  # type: ignore[assignment]
        try:
            launcher._handle_parental_event({"ev": "account_warn", "reason": "daily_limit", "minutes": 4})
            c1, d1 = self._req("GET", f"/api/osk/wait?seq={orig_seq}", xtv=False, token="")
            self.assertEqual(c1, 200)
            self.assertEqual(d1["ev"], "account_warn")
            self.assertEqual(d1["minutes"], 4)

            launcher._handle_parental_event({"ev": "account_locked", "reason": "daily_limit", "remaining_seconds": 0})
            c2, d2 = self._req("GET", f"/api/osk/wait?seq={d1['seq']}", xtv=False, token="")
            self.assertEqual(c2, 200)
            self.assertEqual(d2["ev"], "account_locked")
            self.assertIn("raise_home", calls)
            self.assertFalse(any(c.startswith("close:") for c in calls))
        finally:
            launcher.APPS.pause_background = orig_pause  # type: ignore[method-assign]
            launcher.APPS.close = orig_close  # type: ignore[method-assign]
            launcher.raise_home = orig_raise  # type: ignore[assignment]

    def test_browser_profile_isolation_and_i18n_sync(self) -> None:
        # Admin nutzt unveraenderte Argumente
        admin_args = launcher.prepare_browser_args(
            "firefox",
            ["firefox", "--kiosk", "--no-remote", "--profile", "/legacy/yt", "https://youtube.com"],
            self.svc,
        )
        self.assertIn("/legacy/yt", admin_args)

        # Kind bekommt isolierten Profilordner unter accounts/data/<child_id>/browser/<app>
        self.svc.switch_account(self.child.id)
        ff_args = launcher.prepare_browser_args(
            "firefox",
            ["firefox", "--no-remote", "--profile", "/legacy/ff", "about:home"],
            self.svc,
        )
        expected_ff = str(self.base / "accounts" / "data" / self.child.id / "browser" / "firefox")
        self.assertEqual(ff_args[ff_args.index("--profile") + 1], expected_ff)
        self.assertTrue((Path(expected_ff) / "user.js").is_file())

        cr_args = launcher.prepare_browser_args("chromium", ["chromium", "https://example.com"], self.svc)
        expected_cr = str(self.base / "accounts" / "data" / self.child.id / "browser" / "chromium")
        self.assertIn(f"--user-data-dir={expected_cr}", cr_args)

        br_args = launcher.prepare_browser_args("braveorigin", ["/opt/braveorigin/AppRun"], self.svc)
        expected_br = str(self.base / "accounts" / "data" / self.child.id / "browser" / "braveorigin")
        self.assertIn(f"--user-data-dir={expected_br}", br_args)

        # i18n-Sync fuer parental.* in de.json und en.json
        import re as _re
        de = json.loads((REPO / "launcher" / "web" / "i18n" / "de.json").read_text(encoding="utf-8"))
        en = json.loads((REPO / "launcher" / "web" / "i18n" / "en.json").read_text(encoding="utf-8"))
        pkeys_de = {k for k in de if k.startswith("parental.")}
        pkeys_en = {k for k in en if k.startswith("parental.")}
        self.assertEqual(pkeys_de, pkeys_en)
        self.assertGreaterEqual(len(pkeys_de), 35)
        ph = _re.compile(r"\{[A-Za-z0-9_]+\}")
        for k in pkeys_de:
            self.assertEqual(set(ph.findall(de[k])), set(ph.findall(en[k])), f"Placeholder mismatch in {k}")


class VsAccountStage5Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.base = self.root / "voidstation"
        self.runtime = self.root / "runtime"
        self.share = self.root / "share"
        self.base.mkdir(parents=True)
        self.runtime.mkdir(parents=True)
        self.share.mkdir(parents=True)
        self.clock = FakeClock()

        self._orig_env = {
            k: os.environ.get(k)
            for k in ("VS_NO_DESKTOP_SYNC", "VS_SOUNDS", "XDG_RUNTIME_DIR", "VOIDSTATION_BASE")
        }
        os.environ["VS_NO_DESKTOP_SYNC"] = "1"
        os.environ["VS_SOUNDS"] = "0"
        os.environ["XDG_RUNTIME_DIR"] = str(self.runtime)
        os.environ["VOIDSTATION_BASE"] = str(self.base)

        self._orig_settings = launcher.SETTINGS
        self._orig_config = launcher.CONFIG
        self._orig_share = launcher.MEDIA.share

        self.tiles_path = self.base / "tiles.json"
        self.settings_path = self.base / "settings.json"
        self.tiles_path.write_text(
            json.dumps(
                {
                    "title": "Start",
                    "user": "LegacyUser",
                    "groups": [{"name": "System", "tiles": [{"id": "settings", "label": "Settings"}]}],
                }
            ),
            encoding="utf-8",
        )
        self.settings_path.write_text(
            json.dumps({"lang": "de", "theme": "default-dark", "padmouse": True, "sysupd_days": 90}),
            encoding="utf-8",
        )
        launcher.CONFIG = self.tiles_path
        launcher.SETTINGS = self.settings_path
        launcher.MEDIA.share = lambda: self.share  # type: ignore[method-assign]

        self.token = launcher.init_api_token(runtime_dir=self.runtime)
        self.svc = launcher.init_accounts(base_dir=self.base, runtime_dir=self.runtime, clock=self.clock)
        self.admin = self.svc.list_accounts()[0]
        self.httpd: ThreadingHTTPServer | None = ThreadingHTTPServer(("127.0.0.1", 0), launcher.Handler)
        self.port = self.httpd.server_port
        self.thread: threading.Thread | None = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
        if self.thread is not None:
            self.thread.join(timeout=2)
            self.thread = None
        launcher.close_accounts()
        launcher.CONFIG = self._orig_config
        launcher.SETTINGS = self._orig_settings
        launcher.MEDIA.share = self._orig_share  # type: ignore[method-assign]
        with launcher._API_TOKEN_LOCK:
            launcher._API_TOKEN = ""
            launcher._RUNTIME_DIR_OVERRIDE = None
        for k, v in self._orig_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def _load_installer(self) -> Any:
        path = REPO / "launcher" / "voidstation-installer"
        loader = importlib.machinery.SourceFileLoader("voidstation_installer_test", str(path))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _run_vsctl(
        self,
        *args: str,
        stdin_text: str | None = None,
        api_url: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env["VS_API"] = api_url if api_url is not None else f"http://127.0.0.1:{self.port}"
        env["XDG_RUNTIME_DIR"] = str(self.runtime)
        env["VOIDSTATION_BASE"] = str(self.base)
        env["HOME"] = str(self.root)
        return subprocess.run(
            [str(REPO / "launcher" / "vsctl"), "account", *args],
            input=stdin_text,
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )

    def test_installer_validation_scrubbing_and_chroot_bootstrap(self) -> None:
        inst = self._load_installer()
        base_cfg: dict[str, Any] = {
            "mode": "whole",
            "disk": "/dev/sda",
            "user": {"name": "Anna", "login": "vstestuser", "password": "StartPass!1", "pin": "2580", "auto_login": False},
            "hostname": "tv",
            "lang": "de",
            "keymap": "de",
        }

        with (
            mock.patch.object(inst, "dev_type", return_value="disk"),
            mock.patch.object(inst, "live_disks", return_value=set()),
            mock.patch.object(inst, "sh", return_value=subprocess.CompletedProcess([], 0, "sata 0\n", "")),
        ):
            self.assertIsNone(inst.validate(base_cfg))

            cfg_no_pin = json.loads(json.dumps(base_cfg))
            cfg_no_pin["user"]["pin"] = ""
            cfg_no_pin["user"]["auto_login"] = True
            self.assertIsNone(inst.validate(cfg_no_pin))

            cfg_pin_auto = json.loads(json.dumps(base_cfg))
            cfg_pin_auto["user"]["auto_login"] = True
            self.assertEqual(inst.validate(cfg_pin_auto), "bad_config")

            cfg_bad_pin = json.loads(json.dumps(base_cfg))
            cfg_bad_pin["user"]["pin"] = "12"
            self.assertEqual(inst.validate(cfg_bad_pin), "bad_pin")

            cfg_bad_pin2 = json.loads(json.dumps(base_cfg))
            cfg_bad_pin2["user"]["pin"] = "12ab"
            self.assertEqual(inst.validate(cfg_bad_pin2), "bad_pin")

            cfg_bad_auto = json.loads(json.dumps(base_cfg))
            cfg_bad_auto["user"]["auto_login"] = "yes"
            self.assertEqual(inst.validate(cfg_bad_auto), "bad_config")

        inst_qml = (REPO / "launcher" / "qt" / "qml" / "InstallLayer.qml").read_text(encoding="utf-8")
        self.assertIn("inst.autoLoginPinDisabled", inst_qml)
        self.assertIn("onPinChanged", inst_qml)

        # Secret-Scrubbing in log() und redact_state()
        log_dir = self.root / "inst-run"
        with (
            mock.patch.object(inst, "RUNDIR", log_dir),
            mock.patch.object(inst, "LOG", log_dir / "install.log"),
            mock.patch.object(inst, "SECRETS", ["TopSecret!"]),
        ):
            inst.log('SMBPASS=TopSecret! {"password":"TopSecret!","pin":"5588"} pin=5588 password=abc')
            logged = (log_dir / "install.log").read_text(encoding="utf-8")
            self.assertNotIn("TopSecret!", logged)
            self.assertNotIn("5588", logged)
            self.assertNotIn("abc", logged)

        raw_state = {"config": {"user": {"name": "Anna", "password": "pw", "pin": "5588"}}}
        redacted = inst.redact_state(raw_state)
        self.assertNotIn("password", redacted["config"]["user"])
        self.assertNotIn("pin", redacted["config"]["user"])
        self.assertEqual(raw_state["config"]["user"]["password"], "pw")

        # Chroot-Bootstrap ueber 0600-Datei inkl. Migration & Cleanup
        target = self.root / "target"
        vs_dir = target / "home" / "anna" / ".local" / "share" / "voidstation"
        vs_dir.mkdir(parents=True)
        (vs_dir / "settings.json").write_text(
            json.dumps({"lang": "en", "theme": "nord", "resolution": "1920x1080"}),
            encoding="utf-8",
        )
        (vs_dir / "radio.json").write_text(json.dumps([{"name": "FM4"}]), encoding="utf-8")
        secret_path = target / "root" / ".voidstation-account-bootstrap.json"
        seen_cmds: list[list[str]] = []
        seen_modes: list[int] = []

        def fake_chroot(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
            seen_cmds.append(list(cmd))
            self.assertNotIn("StartPass!1", " ".join(cmd))
            self.assertNotIn("5588", " ".join(cmd))
            self.assertTrue(secret_path.is_file())
            seen_modes.append(_mode(secret_path))
            return subprocess.run(
                [
                    sys.executable,
                    str(REPO / "launcher" / "vsaccount" / "cli.py"),
                    "--base",
                    str(vs_dir),
                    "bootstrap",
                    "--secret-file",
                    str(secret_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        inst.bootstrap_account(
            target,
            "anna",
            {"name": "Anna", "password": "StartPass!1", "pin": "5588", "auto_login": False},
            runner=fake_chroot,
        )
        self.assertFalse(secret_path.exists())
        self.assertEqual(seen_modes, [0o600])
        self.assertIn("--secret-file", seen_cmds[0])

        svc_boot = AccountService(vs_dir, runtime_dir=self.runtime / "boot-rt", clock=self.clock)
        try:
            accs = svc_boot.list_accounts()
            self.assertEqual(len(accs), 1)
            admin = accs[0]
            self.assertEqual(admin.display_name, "Anna")
            self.assertTrue(admin.has_password)
            self.assertTrue(admin.has_pin)
            self.assertFalse(admin.auto_login)
            self.assertTrue(svc_boot.get_device_policy().ask_on_boot)
            self.assertTrue(svc_boot.get_session().locked)
            prefs = svc_boot.load_profile_prefs({})
            self.assertEqual(prefs.get("lang"), "en")
            self.assertEqual(prefs.get("theme"), "nord")
            self.assertTrue((vs_dir / "accounts" / "data" / admin.id / "radio.json").is_file())
        finally:
            svc_boot.close()

        # Secret-Datei wird auch bei fehlgeschlagenem Chroot aufgeraeumt
        def fail_chroot(_cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
            self.assertTrue(secret_path.is_file())
            return subprocess.CompletedProcess([], 1, "", "boom")

        with self.assertRaises(inst.Fail):
            inst.bootstrap_account(
                target,
                "anna",
                {"name": "Anna", "password": "StartPass!1", "pin": "5588", "auto_login": True},
                runner=fail_chroot,
            )
        self.assertFalse(secret_path.exists())

    def test_vsctl_account_cli_and_emergency_fallback(self) -> None:
        self.svc.set_credential(self.admin.id, "password", "AdminPass!1")
        self.svc.set_credential(self.admin.id, "pin", "2580")
        alex = self.svc.create_account("Alex", role="standard", pin="2468", password="AlexPass99")
        self.svc.set_device_policy(guest_enabled=True)

        # CLI-Argumente fuer Secrets werden strikt abgelehnt
        r_bad = self._run_vsctl("switch", "Alex", "--pin=2468")
        self.assertEqual(r_bad.returncode, 2)
        self.assertIn("forbidden", r_bad.stderr)
        r_bad_pw = self._run_vsctl("switch", "Alex", "--password=AlexPass99")
        self.assertEqual(r_bad_pw.returncode, 2)

        # status & list (human und --json)
        r_st = self._run_vsctl("status", "--json")
        self.assertEqual(r_st.returncode, 0, r_st.stderr)
        st_json = json.loads(r_st.stdout)
        self.assertEqual(st_json["session"]["account_id"], self.admin.id)

        r_st_h = self._run_vsctl("status")
        self.assertEqual(r_st_h.returncode, 0, r_st_h.stderr)
        self.assertIn("LegacyUser", r_st_h.stdout)

        r_ls = self._run_vsctl("list", "--json")
        self.assertEqual(r_ls.returncode, 0, r_ls.stderr)
        ls_json = json.loads(r_ls.stdout)
        self.assertEqual(len(ls_json), 2)
        self.assertNotIn("2468", r_ls.stdout)
        self.assertNotIn("hash", r_ls.stdout)

        # switch mit PIN via stdin
        r_sw_pin = self._run_vsctl("switch", "Alex", "--json", stdin_text="2468\n")
        self.assertEqual(r_sw_pin.returncode, 0, r_sw_pin.stderr)
        self.assertEqual(json.loads(r_sw_pin.stdout)["session"]["account_id"], alex.id)

        # switch mit Passwort via stdin (--password ohne Wert)
        r_sw_pw = self._run_vsctl("switch", "LegacyUser", "--password", "--json", stdin_text="AdminPass!1\n")
        self.assertEqual(r_sw_pw.returncode, 0, r_sw_pw.stderr)
        self.assertEqual(json.loads(r_sw_pw.stdout)["session"]["account_id"], self.admin.id)

        # switch --guest und lock
        r_guest = self._run_vsctl("switch", "--guest", "--json")
        self.assertEqual(r_guest.returncode, 0, r_guest.stderr)
        self.assertTrue(json.loads(r_guest.stdout)["session"]["is_guest"])

        r_lock = self._run_vsctl("lock", "--json")
        self.assertEqual(r_lock.returncode, 0, r_lock.stderr)
        self.assertTrue(json.loads(r_lock.stdout)["session"]["locked"])

        # Hard-Lock auf Alex ausloesen und trotz gesperrter UI per Notfall-Fallback entsperren
        for _ in range(8):
            res = self.svc.authenticate(alex.id, "pin", "0000")
            if res.retry_after > 0:
                self.clock.advance(res.retry_after + 1)
        self.assertTrue(self.svc.authenticate(alex.id, "pin", "2468").hard_locked)

        r_ul = self._run_vsctl("unlock", "Alex", "--json")
        self.assertEqual(r_ul.returncode, 0, r_ul.stderr)
        self.assertTrue(json.loads(r_ul.stdout)["ok"])
        self.assertTrue(self.svc.authenticate(alex.id, "pin", "2468").ok)

        # reset-pin und reset-pin --remove ueber stdin (im Notfall-Fallback bei gesperrter UI)
        r_rp = self._run_vsctl("reset-pin", "Alex", "--json", stdin_text="7391\n7391\n")
        self.assertEqual(r_rp.returncode, 0, r_rp.stderr)
        self.assertNotIn("7391", r_rp.stdout)
        self.assertTrue(self.svc.authenticate(alex.id, "pin", "7391").ok)

        r_rm = self._run_vsctl("reset-pin", "Alex", "--remove", "--json")
        self.assertEqual(r_rm.returncode, 0, r_rm.stderr)
        self.assertFalse(json.loads(r_rm.stdout)["has_pin"])
        updated_alex = self.svc.get_account(alex.id)
        assert updated_alex is not None
        self.assertFalse(updated_alex.has_pin)

        # Offline-Fallback bei gestopptem Launcher
        assert self.httpd is not None
        self.httpd.shutdown()
        self.httpd.server_close()
        self.httpd = None
        if self.thread is not None:
            self.thread.join(timeout=2)
            self.thread = None

        r_off_st = self._run_vsctl("status", "--json", api_url=f"http://127.0.0.1:{self.port}")
        self.assertEqual(r_off_st.returncode, 0, r_off_st.stderr)
        self.assertTrue(json.loads(r_off_st.stdout).get("offline"))

        r_off_ls = self._run_vsctl("list", "--json", api_url=f"http://127.0.0.1:{self.port}")
        self.assertEqual(r_off_ls.returncode, 0, r_off_ls.stderr)
        self.assertEqual(len(json.loads(r_off_ls.stdout)), 2)

    def test_bash_completion_and_stage5_i18n_sync(self) -> None:
        bashrc = REPO / "launcher" / "shell" / "bashrc.sh"
        script = "\n".join(
            [
                f"source {json.dumps(str(bashrc))}",
                'COMP_WORDS=(vsctl ""); COMP_CWORD=1; _vsctl; printf "L1:%s\\n" "${COMPREPLY[*]}"',
                'COMP_WORDS=(vsctl account ""); COMP_CWORD=2; _vsctl; printf "L2:%s\\n" "${COMPREPLY[*]}"',
                'COMP_WORDS=(vsctl account reset-pin Alex "-"); COMP_CWORD=4; _vsctl; printf "L3:%s\\n" "${COMPREPLY[*]}"',
            ]
        )
        r = subprocess.run(
            ["bash", "--norc", "--noprofile", "-ic", script],
            capture_output=True,
            text=True,
            env={**os.environ, "HOME": str(self.root)},
            timeout=5,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("account", r.stdout)
        for sub in ("status", "list", "switch", "lock", "unlock", "reset-pin", "help"):
            self.assertIn(sub, r.stdout)
        self.assertIn("--remove", r.stdout)

        de = json.loads((REPO / "launcher" / "web" / "i18n" / "de.json").read_text(encoding="utf-8"))
        en = json.loads((REPO / "launcher" / "web" / "i18n" / "en.json").read_text(encoding="utf-8"))
        stage5_keys = (
            "inst.pin",
            "inst.pinOptional",
            "inst.pinInfo",
            "inst.autoLogin",
            "inst.autoLoginOn",
            "inst.autoLoginOff",
            "inst.errPin",
            "inst.err.bad_pin",
            "inst.sumPinSet",
            "inst.sumPinNone",
            "inst.sumAutoLoginOn",
            "inst.sumAutoLoginOff",
            "inst.loginAskText",
        )
        ph = re.compile(r"\{[A-Za-z0-9_]+\}")
        for k in stage5_keys:
            self.assertIn(k, de)
            self.assertIn(k, en)
            self.assertEqual(set(ph.findall(de[k])), set(ph.findall(en[k])), f"Placeholder mismatch in {k}")


class VsAccountRegressionAndCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.base = self.root / "voidstation"
        self.runtime = self.root / "runtime"
        self.base.mkdir(parents=True)
        self.runtime.mkdir(parents=True)
        self.clock = FakeClock(1_700_046_000.0)

        self._orig_env = {
            k: os.environ.get(k)
            for k in ("VS_NO_DESKTOP_SYNC", "VS_SOUNDS", "XDG_RUNTIME_DIR", "VOIDSTATION_BASE")
        }
        os.environ["VS_NO_DESKTOP_SYNC"] = "1"
        os.environ["VS_SOUNDS"] = "0"
        os.environ["XDG_RUNTIME_DIR"] = str(self.runtime)
        os.environ["VOIDSTATION_BASE"] = str(self.base)

        self._orig_settings = launcher.SETTINGS
        self._orig_config = launcher.CONFIG
        self._orig_catalog = launcher.CATALOG

        self.tiles_path = self.base / "tiles.json"
        self.settings_path = self.base / "settings.json"
        self.tiles_path.write_text(
            json.dumps(
                {
                    "title": "Start",
                    "user": "Eltern",
                    "groups": [
                        {
                            "name": "Spiele",
                            "tiles": [
                                {"id": "supertux", "label": "SuperTux", "cmd": ["supertux2"]},
                                {"id": "steam", "label": "Steam", "cmd": ["steam"]},
                                {"id": "custom16", "label": "Custom16", "cat": "Spiele", "age_rating": 16, "cmd": ["true"]},
                            ],
                        },
                        {
                            "name": "System",
                            "tiles": [{"id": "settings", "label": "Einstellungen", "type": "settings"}],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.settings_path.write_text(json.dumps({"lang": "de", "theme": "default-dark"}), encoding="utf-8")
        launcher.CONFIG = self.tiles_path
        launcher.SETTINGS = self.settings_path

        self.token = launcher.init_api_token(runtime_dir=self.runtime)
        self.svc = launcher.init_accounts(
            base_dir=self.base,
            runtime_dir=self.runtime,
            clock=self.clock,
        )
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), launcher.Handler)
        self.port = self.httpd.server_port
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        launcher.close_accounts()
        launcher.CONFIG = self._orig_config
        launcher.SETTINGS = self._orig_settings
        launcher.CATALOG = self._orig_catalog
        with launcher._API_TOKEN_LOCK:
            launcher._API_TOKEN = ""
            launcher._RUNTIME_DIR_OVERRIDE = None
        for k, v in self._orig_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def _req(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        xtv: bool = True,
        token: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        headers: dict[str, str] = {}
        if xtv:
            headers["X-TV"] = "1"
        tok = self.token if token is None else token
        if tok:
            headers[vsaccount.API_TOKEN_HEADER] = tok
        data: bytes | None = None
        if body is not None or method == "POST":
            headers["Content-Type"] = "application/json"
            data = json.dumps({} if body is None else body).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=data,
            method=method,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = resp.read().decode("utf-8", "replace")
                return resp.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            with exc:
                raw = exc.read().decode("utf-8", "replace")
                code = exc.code
            try:
                parsed = json.loads(raw) if raw else {}
            except ValueError:
                parsed = {"raw": raw}
            return code, parsed

    def test_child_account_requires_admin_auth_and_blocks_bypass(self) -> None:
        # Nach Legacy-Migration hat Admin weder PIN noch Passwort
        admin = self.svc.list_accounts()[0]
        self.assertFalse(admin.has_pin)
        self.assertFalse(admin.has_password)

        # 1. Kinder-Konto anlegen ohne Eltern-PIN/Passwort -> 403 account.err.parentAuthRequired
        c_create, d_create = self._req(
            "POST",
            "/api/accounts/create",
            {"display_name": "Kind", "role": "child", "parent_id": admin.id},
        )
        self.assertEqual(c_create, 403)
        self.assertEqual(d_create["error"], "account.err.parentAuthRequired")

        # 2. Standard-Konto nachtraeglich zum Kind machen ohne Eltern-PIN -> 403
        c_std, d_std = self._req("POST", "/api/accounts/create", {"display_name": "Tim", "role": "standard"})
        self.assertEqual(c_std, 200)
        std_id = d_std["account"]["id"]
        c_prom, d_prom = self._req(
            "POST",
            "/api/accounts/update",
            {"account_id": std_id, "role": "child", "parent_id": admin.id},
        )
        self.assertEqual(c_prom, 403)
        self.assertEqual(d_prom["error"], "account.err.parentAuthRequired")

        # 3. Eltern-PIN setzen -> Kinder-Konto anlegen klappt jetzt
        c_pin, _ = self._req(
            "POST",
            "/api/accounts/credentials",
            {"account_id": admin.id, "action": "set", "factor": "pin", "pin": "2580"},
        )
        self.assertEqual(c_pin, 200)
        c_child, d_child = self._req(
            "POST",
            "/api/accounts/create",
            {"display_name": "Kind", "role": "child", "parent_id": admin.id},
        )
        self.assertEqual(c_child, 200)
        child_id = d_child["account"]["id"]

        # 4. Letztes Credential des Admins darf nicht entfernt werden, solange Kinder-Konto existiert
        c_rm_fail, d_rm_fail = self._req(
            "POST",
            "/api/accounts/credentials",
            {"account_id": admin.id, "action": "remove", "factor": "pin"},
        )
        self.assertEqual(c_rm_fail, 403)
        self.assertEqual(d_rm_fail["error"], "account.err.parentAuthRequired")

        # Mit zusaetzlichem Passwort darf die PIN entfernt werden, letztes Passwort bleibt geschuetzt
        self.assertEqual(
            self._req("POST", "/api/accounts/credentials", {"account_id": admin.id, "action": "set", "factor": "password", "password": "ElternPass!1"})[0],
            200,
        )
        self.assertEqual(
            self._req("POST", "/api/accounts/credentials", {"account_id": admin.id, "action": "remove", "factor": "pin"})[0],
            200,
        )
        self.assertEqual(
            self._req("POST", "/api/accounts/credentials", {"account_id": admin.id, "action": "remove", "factor": "password"})[0],
            403,
        )
        # PIN wieder setzen fuer den Wechsel-Test
        self.assertEqual(
            self._req("POST", "/api/accounts/credentials", {"account_id": admin.id, "action": "set", "factor": "pin", "pin": "2580"})[0],
            200,
        )

        # 5. Gastmodus aktivieren + zweites Kinderkonto anlegen
        self.assertEqual(
            self._req("POST", "/api/accounts/device-policy", {"guest_enabled": True})[0],
            200,
        )
        c_child2, d_child2 = self._req(
            "POST",
            "/api/accounts/create",
            {"display_name": "Kind2", "role": "child", "parent_id": admin.id},
        )
        self.assertEqual(c_child2, 200)
        child2_id = d_child2["account"]["id"]

        # 6. In Kinderkonto wechseln -> Rueckwechsel zum Admin ohne/mit falscher PIN blockiert
        self.assertEqual(self._req("POST", "/api/session/switch", {"account_id": child_id})[0], 200)
        c_bypass, _ = self._req("POST", "/api/session/switch", {"account_id": admin.id})
        self.assertEqual(c_bypass, 401)
        c_wrong, _ = self._req("POST", "/api/session/switch", {"account_id": admin.id, "pin": "9999"})
        self.assertEqual(c_wrong, 401)

        # Defense-in-Depth: Zweiter ungeschuetzter Admin darf aus Kindersitzung ebenfalls nicht geoeffnet werden
        unprotected_admin = self.svc.create_account("ZweiterAdmin", role="admin")
        c_unprot, d_unprot = self._req("POST", "/api/session/switch", {"account_id": unprotected_admin.id})
        self.assertEqual(c_unprot, 403)
        self.assertEqual(d_unprot["error"], "account.err.parentAuthRequired")

        # Ungeschuetztes Standardkonto und Gast-Modus sind aus Kindersitzung ebenfalls gesperrt
        c_std_bypass, d_std_bypass = self._req("POST", "/api/session/switch", {"account_id": std_id})
        self.assertEqual(c_std_bypass, 403)
        self.assertEqual(d_std_bypass["error"], "account.err.parentAuthRequired")
        c_guest_bypass, d_guest_bypass = self._req("POST", "/api/session/guest")
        self.assertEqual(c_guest_bypass, 403)
        self.assertEqual(d_guest_bypass["error"], "account.err.blocked")

        # Auch nach Sperren der Kindersitzung bleibt der Umweg ueber Standardkonto ohne PIN und Gast gesperrt
        self.assertEqual(self._req("POST", "/api/session/lock")[0], 200)
        self.assertEqual(self._req("POST", "/api/session/switch", {"account_id": std_id})[0], 403)
        self.assertEqual(self._req("POST", "/api/session/guest")[0], 403)

        # Wechsel auf ein anderes Kinderkonto klappt ohne PIN
        c_c2, d_c2 = self._req("POST", "/api/session/switch", {"account_id": child2_id})
        self.assertEqual(c_c2, 200)
        self.assertEqual(d_c2["session"]["account_id"], child2_id)

        # Richtige PIN wechselt sauber zurueck zum Admin
        c_ok, d_ok = self._req("POST", "/api/session/switch", {"account_id": admin.id, "pin": "2580"})
        self.assertEqual(c_ok, 200)
        self.assertEqual(d_ok["session"]["account_id"], admin.id)

        # Standardkonto mit PIN schuetzen -> Wechsel aus Kindersitzung erfordert PIN, Gast bleibt ab Admin erlaubt
        self.assertEqual(
            self._req("POST", "/api/accounts/credentials", {"account_id": std_id, "action": "set", "factor": "pin", "pin": "1357"})[0],
            200,
        )
        self.assertEqual(self._req("POST", "/api/session/switch", {"account_id": child_id})[0], 200)
        self.assertEqual(self._req("POST", "/api/session/switch", {"account_id": std_id})[0], 401)
        c_std_ok, d_std_ok = self._req("POST", "/api/session/switch", {"account_id": std_id, "pin": "1357"})
        self.assertEqual(c_std_ok, 200)
        self.assertEqual(d_std_ok["session"]["account_id"], std_id)
        self.assertEqual(self._req("POST", "/api/session/guest")[0], 200)
        self.assertEqual(self._req("POST", "/api/session/switch", {"account_id": admin.id, "pin": "2580"})[0], 200)

        # UI- und i18n-Check fuer die direkte Eltern-PIN-Fuehrung und Picker-Filter
        edit_qml = (REPO / "launcher" / "qt" / "qml" / "AccountEditDialog.qml").read_text(encoding="utf-8")
        self.assertIn("childNeedsParentAuth", edit_qml)
        self.assertIn("startParentPinFlow", edit_qml)
        picker_qml = (REPO / "launcher" / "qt" / "qml" / "AccountPickerLayer.qml").read_text(encoding="utf-8")
        self.assertIn("fromChildSession", picker_qml)
        de = json.loads((REPO / "launcher" / "web" / "i18n" / "de.json").read_text(encoding="utf-8"))
        en = json.loads((REPO / "launcher" / "web" / "i18n" / "en.json").read_text(encoding="utf-8"))
        for k in ("account.childNeedsParentAuth", "account.setParentPin", "account.setParentPinTitle"):
            self.assertIn(k, de)
            self.assertIn(k, en)

    def test_restart_requires_picker_with_child_or_protected_account(self) -> None:
        # Nach Legacy-Migration: Admin ohne PIN/Passwort und ohne Kinder startet entsperrt
        admin = self.svc.list_accounts()[0]
        self.assertTrue(admin.auto_login)
        self.assertFalse(self.svc.get_session().locked)

        # Admin mit PIN schuetzen -> auto_login wird deaktiviert; selbst bei erzwungenem auto_login=1 greift kein Auto-Login
        self.svc.set_credential(admin.id, "pin", "2580")
        admin_after = self.svc.get_account(admin.id)
        assert admin_after is not None
        self.assertFalse(admin_after.auto_login)
        self.svc.store._conn.execute("UPDATE accounts SET auto_login = 1 WHERE id = ?", (admin.id,))
        self.svc.update_account(admin.id, auto_login=True)
        admin_recheck = self.svc.get_account(admin.id)
        assert admin_recheck is not None
        self.assertFalse(admin_recheck.auto_login)

        # Selbst wenn in der DB manuell auto_login=1 steht, darf ein geschuetztes Konto nicht entsperrt starten
        self.svc.store._conn.execute("UPDATE accounts SET auto_login = 1 WHERE id = ?", (admin.id,))
        self.svc = launcher.init_accounts(base_dir=self.base, runtime_dir=self.runtime, clock=self.clock)
        sess_prot = self.svc.get_session()
        self.assertTrue(sess_prot.locked)
        self.assertTrue(sess_prot.picker_required)

        # Als Admin anmelden, Kind anlegen + ungeschuetztes Standardkonto mit auto_login=True, ask_on_boot=False
        self.assertEqual(self._req("POST", "/api/session/switch", {"account_id": admin.id, "pin": "2580"})[0], 200)
        self.assertEqual(self._req("POST", "/api/accounts/device-policy", {"ask_on_boot": False})[0], 200)
        self.assertEqual(
            self._req("POST", "/api/accounts/create", {"display_name": "Kind", "role": "child", "parent_id": admin.id})[0],
            200,
        )
        c_std, d_std = self._req(
            "POST",
            "/api/accounts/create",
            {"display_name": "StandardAuto", "role": "standard", "auto_login": True},
        )
        self.assertEqual(c_std, 200)
        std_id = d_std["account"]["id"]

        # Dienst neu starten -> muss gesperrt in der Kontoauswahl landen (nie "admin, entsperrt")
        self.svc = launcher.init_accounts(base_dir=self.base, runtime_dir=self.runtime, clock=self.clock)
        restarted = self.svc.get_session()
        self.assertTrue(restarted.locked)
        self.assertTrue(restarted.picker_required)
        self.assertFalse(restarted.role == "admin" and not restarted.locked)

        c_sess, d_sess = self._req("GET", "/api/session")
        self.assertEqual(c_sess, 200)
        self.assertTrue(d_sess["session"]["locked"])
        self.assertTrue(d_sess["session"]["picker_required"])

        # In der Kontoauswahl nach Neustart darf das ungeschuetzte Standardkonto nicht ohne PIN geoeffnet werden
        c_std_boot, d_std_boot = self._req("POST", "/api/session/switch", {"account_id": std_id})
        self.assertEqual(c_std_boot, 403)
        self.assertEqual(d_std_boot["error"], "account.err.parentAuthRequired")

        # Admin-Wechsel ohne PIN abgelehnt, mit PIN erfolgreich; auch aus entsperrtem Admin heraus bleibt ungeschuetztes Standardkonto gesperrt
        self.assertEqual(self._req("POST", "/api/session/switch", {"account_id": admin.id})[0], 401)
        self.assertEqual(self._req("POST", "/api/session/switch", {"account_id": admin.id, "pin": "2580"})[0], 200)
        c_std_admin, d_std_admin = self._req("POST", "/api/session/switch", {"account_id": std_id})
        self.assertEqual(c_std_admin, 403)
        self.assertEqual(d_std_admin["error"], "account.err.parentAuthRequired")

        # Nach Setzen einer PIN auf das Standardkonto klappt der Wechsel mit PIN; Entfernen der letzten PIN bleibt blockiert
        self.assertEqual(
            self._req("POST", "/api/accounts/credentials", {"account_id": std_id, "action": "set", "factor": "pin", "pin": "1357"})[0],
            200,
        )
        self.assertEqual(self._req("POST", "/api/session/switch", {"account_id": std_id, "pin": "1357"})[0], 200)
        self.assertEqual(self._req("POST", "/api/session/switch", {"account_id": admin.id, "pin": "2580"})[0], 200)
        c_rm_std, d_rm_std = self._req(
            "POST",
            "/api/accounts/credentials",
            {"account_id": std_id, "action": "remove", "factor": "pin"},
        )
        self.assertEqual(c_rm_std, 403)
        self.assertEqual(d_rm_std["error"], "account.err.parentAuthRequired")

        # UI-Checks fuer Liste ungeschuetzter Konten und Picker-Filter
        edit_qml = (REPO / "launcher" / "qt" / "qml" / "AccountEditDialog.qml").read_text(encoding="utf-8")
        self.assertIn("unprotectedNonChildAccounts", edit_qml)
        picker_qml = (REPO / "launcher" / "qt" / "qml" / "AccountPickerLayer.qml").read_text(encoding="utf-8")
        self.assertIn("hasActiveChild", picker_qml)

    def test_catalog_age_rating_and_audit_regressions(self) -> None:
        # 1. catalog.json optional age_rating (rueckwaertskompatibel) + bool-Schutz
        cat_data = json.loads((REPO / "launcher" / "catalog.json").read_text(encoding="utf-8"))
        steam_entry = next(a for a in cat_data["apps"] if a["id"] == "steam")
        self.assertEqual(steam_entry.get("age_rating"), 16)
        apps_with_age = [a for a in cat_data["apps"] if "age_rating" in a]
        apps_without_age = [a for a in cat_data["apps"] if "age_rating" not in a]
        self.assertTrue(apps_with_age and apps_without_age)

        with mock.patch("launcher.installed_sets", return_value=(set(), set())), \
             mock.patch("launcher.local_apps", return_value=[]):
            ap = launcher.apps_payload()
        steam_payload = next(a for a in ap["apps"] if a["id"] == "steam")
        self.assertEqual(steam_payload["age_rating"], 16)

        cat, age_bool, _, _ = launcher._tile_meta("supertux", {"id": "supertux", "age_rating": True})
        self.assertIsNone(age_bool)

        admin = self.svc.list_accounts()[0]
        self.svc.set_credential(admin.id, "pin", "2580")
        child = self.svc.create_account("Mira", role="child", parent_id=admin.id)
        self.svc.set_parental_policy(
            child.id,
            {"mode": "denylist", "max_age_rating": 12, "allowed_tiles": [], "blocked_tiles": [], "blocked_cats": []},
        )
        self.svc.switch_account(child.id)
        _, child_tiles = self._req("GET", "/tiles.json", xtv=False, token="")
        shown_ids = {t["id"] for g in child_tiles["groups"] for t in g["tiles"]}
        self.assertIn("supertux", shown_ids)
        self.assertNotIn("custom16", shown_ids)
        self.svc.switch_account(admin.id, pin="2580")

        # 2. Audit-Fix: cleanup_guest=False zerstoert keine laufende Gast-Sitzung
        self.svc.set_device_policy(guest_enabled=True)
        self.svc.start_guest_session()
        guest_dir = self.runtime / "voidstation-guest"
        self.assertTrue(guest_dir.is_dir())
        cli_svc = AccountService(self.base, runtime_dir=self.runtime, cleanup_guest=False)
        cli_svc.close()
        self.assertTrue(guest_dir.is_dir())

        # 3. Audit-Fix: update_account validiert avatar & color, browser_profile_dir setzt 0700 auf browser/
        with self.assertRaises(ValidationError):
            self.svc.update_account(admin.id, avatar="invalid-avatar")
        with self.assertRaises(ValidationError):
            self.svc.update_account(admin.id, color="not-a-hex")
        bdir = self.svc.storage.browser_profile_dir(admin.id, "firefox")
        self.assertEqual(_mode(bdir.parent), 0o700)
        self.assertEqual(_mode(bdir), 0o700)

        # 4. QML-Gating
        sett_qml = (REPO / "launcher" / "qt" / "qml" / "SettingsLayer.qml").read_text(encoding="utf-8")
        self.assertIn("isRestrictedAccount", sett_qml)
        self.assertNotIn("Coming Soon", sett_qml)

        edit_qml = (REPO / "launcher" / "qt" / "qml" / "AccountEditDialog.qml").read_text(encoding="utf-8")
        self.assertIn("a.id !== ed.account.id", edit_qml)


if __name__ == "__main__":
    unittest.main()
