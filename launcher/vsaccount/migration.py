# SPDX-License-Identifier: GPL-3.0-or-later
"""Verlustfreie Erst-Migration vom bisherigen Single-User-Setup ins Account-System."""
from __future__ import annotations

import json
import os
import pwd
import shutil
import time
from pathlib import Path
from typing import Any

from .models import PROFILE_FILES, PROFILE_PREF_KEYS, MigrationReport
from .storage import ProfileStorage
from .store import AccountStore


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _legacy_display_name(base_dir: Path) -> str:
    tiles = _read_json(base_dir / "tiles.json")
    if isinstance(tiles, dict):
        u = str(tiles.get("user") or "").strip()
        if u:
            return u[:60]

    try:
        pw = pwd.getpwuid(os.getuid())
        gecos = pw.pw_gecos.split(",", 1)[0].strip()
        if gecos:
            return gecos[:60]
        if pw.pw_name:
            return pw.pw_name[:1].upper() + pw.pw_name[1:60]
    except KeyError:
        pass

    env_user = os.environ.get("USER", "").strip()
    if env_user:
        return env_user[:1].upper() + env_user[1:60]
    return "VoidStation"


def migrate_legacy_if_needed(
    base_dir: Path,
    store: AccountStore,
    storage: ProfileStorage,
) -> MigrationReport:
    """Uebernimmt genau einmalig den bisherigen Single-User-Stand in accounts/data/<admin_id>/."""
    if store.get_meta("migrated_from_legacy") == "1" or store.list_accounts(include_inactive=True):
        existing = store.list_accounts()
        admin = next((a for a in existing if a.role == "admin"), existing[0] if existing else None)
        return MigrationReport(
            migrated=False,
            admin_id=admin.id if admin else "",
            display_name=admin.display_name if admin else "",
        )

    display_name = _legacy_display_name(base_dir)
    admin = store.create_account(
        display_name=display_name,
        role="admin",
        auto_login=True,
    )
    pdir = storage.profile_dir(admin.id)

    copied: list[str] = []
    for fname in PROFILE_FILES:
        src = base_dir / fname
        if src.is_file():
            dst = pdir / fname
            if not dst.exists():
                shutil.copy2(src, dst)
                os.chmod(dst, 0o600)
            copied.append(fname)

    extracted: list[str] = []
    sett = _read_json(base_dir / "settings.json")
    if isinstance(sett, dict):
        prefs = {k: sett[k] for k in PROFILE_PREF_KEYS if k in sett}
        if prefs:
            storage.save_prefs(admin.id, prefs)
            extracted = sorted(prefs.keys())

    store.set_meta("default_account_id", admin.id)
    store.set_meta("migrated_at", str(int(time.time())))
    store.set_meta("migrated_from_legacy", "1")
    store.append_audit(
        "legacy_migrated",
        account_id=admin.id,
        actor_id=admin.id,
        detail={"copied_files": copied, "extracted_prefs": extracted},
    )

    return MigrationReport(
        migrated=True,
        admin_id=admin.id,
        display_name=admin.display_name,
        copied_files=copied,
        extracted_prefs=extracted,
    )
