# SPDX-License-Identifier: GPL-3.0-or-later
"""Kindersicherung: App-/Kategorie-/Alters-Pruefung, Tageslimit, Ruhezeiten, 30-s-Tracker und Overrides."""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .models import DevicePolicy, ParentalPolicy, SessionState, ValidationError
from .store import AccountStore

AGE_RATINGS: tuple[int, ...] = (0, 6, 12, 16, 18)
WARN_THRESHOLD_SECONDS = 300
USAGE_TICK_SECONDS = 30
EXTRA_MINUTE_CHOICES: tuple[int, ...] = (15, 30, 60)

BROWSER_TILE_IDS: frozenset[str] = frozenset({"firefox", "chromium", "brave", "braveorigin", "librewolf"})
BROWSER_BINARIES: frozenset[str] = frozenset(
    {"firefox", "librewolf", "chromium", "brave", "brave-browser", "google-chrome"}
)
ALWAYS_VISIBLE_TILES: frozenset[str] = frozenset({"clock", "settings"})
ADMIN_ONLY_TILES: frozenset[str] = frozenset({"appcenter"})
GUEST_BLOCKED_TILES: frozenset[str] = frozenset({"terminal", "files"})
GUEST_BLOCKED_CATS: frozenset[str] = frozenset({"Werkzeuge"})

DEFAULT_CAT_AGE_RATINGS: dict[str, int] = {
    "Gaming": 12,
    "Emulatoren": 6,
    "Spiele": 6,
    "Medien": 6,
    "Streaming": 12,
    "Browser": 16,
    "Werkzeuge": 16,
}

DEFAULT_APP_AGE_RATINGS: dict[str, int] = {
    "radio": 0,
    "media": 0,
    "supertux": 0,
    "supertuxkart": 0,
    "neverball": 0,
    "tv": 6,
    "ard": 6,
    "zdf": 6,
    "arte": 6,
    "disneyplus": 6,
    "luanti": 6,
    "openttd": 6,
    "youtube": 12,
    "ytlight": 12,
    "freetube": 12,
    "netflix": 12,
    "primevideo": 12,
    "twitch": 12,
    "wesnoth": 12,
    "hedgewars": 12,
    "steam": 16,
    "heroic": 16,
    "lutris": 16,
    "discord": 16,
    "xonotic": 16,
    "files": 16,
    "mullvad": 16,
    "htop": 16,
    "missioncenter": 16,
    "firefox": 16,
    "chromium": 16,
    "brave": 16,
    "braveorigin": 16,
    "librewolf": 16,
    "terminal": 18,
}

BEDTIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_SECONDS_PER_DAY = 86400


@dataclass(slots=True)
class ParentalDecision:
    """Ergebnis einer Kindersicherungs- oder Rollenpruefung."""

    allowed: bool
    reason: str = ""
    code: str = ""
    override_allowed: bool = False
    remaining_seconds: int | None = None
    tile_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "code": self.code,
            "override_allowed": self.override_allowed,
            "remaining_seconds": self.remaining_seconds,
            "tile_id": self.tile_id,
        }


def validate_bedtime(value: str) -> str:
    """Prueft und normiert eine Uhrzeit im Format HH:MM (oder '')."""
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    if not BEDTIME_RE.fullmatch(cleaned):
        raise ValidationError("account.err.invalid", f"Invalid bedtime format: {cleaned}")
    return cleaned


def _dedup_str_tuple(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple, set)):
        raise ValidationError("account.err.invalid", "Expected list of identifiers")
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        val = str(item or "").strip()
        if val and val not in seen:
            seen.add(val)
            out.append(val)
    return tuple(out)


def validate_policy_data(account_id: str, data: dict[str, Any]) -> ParentalPolicy:
    """Validiert eingehende Kindersicherungsregeln und erzeugt eine ParentalPolicy."""
    if not isinstance(data, dict):
        raise ValidationError("account.err.invalid", "Policy payload must be an object")

    mode = str(data.get("mode") or "allowlist").strip().lower()
    if mode not in ("allowlist", "denylist"):
        raise ValidationError("account.err.invalid", f"Invalid parental mode: {mode}")

    try:
        max_age = int(data.get("max_age_rating", 12))
    except (TypeError, ValueError) as exc:
        raise ValidationError("account.err.invalid", "Invalid max_age_rating") from exc
    if max_age < 0 or max_age > 18:
        raise ValidationError("account.err.invalid", "max_age_rating must be between 0 and 18")

    try:
        daily_limit = int(data.get("daily_limit_min", 0))
    except (TypeError, ValueError) as exc:
        raise ValidationError("account.err.invalid", "Invalid daily_limit_min") from exc
    if daily_limit < 0 or daily_limit > 1440:
        raise ValidationError("account.err.invalid", "daily_limit_min must be between 0 and 1440")

    bedtime_start = validate_bedtime(str(data.get("bedtime_start") or ""))
    bedtime_end = validate_bedtime(str(data.get("bedtime_end") or ""))
    if bool(bedtime_start) != bool(bedtime_end):
        raise ValidationError("account.err.invalid", "Both bedtime_start and bedtime_end must be set or empty")

    return ParentalPolicy(
        account_id=account_id,
        mode=mode,
        allowed_tiles=_dedup_str_tuple(data.get("allowed_tiles")),
        blocked_tiles=_dedup_str_tuple(data.get("blocked_tiles")),
        blocked_cats=_dedup_str_tuple(data.get("blocked_cats")),
        max_age_rating=max_age,
        daily_limit_min=daily_limit,
        bedtime_start=bedtime_start,
        bedtime_end=bedtime_end,
        allow_yt_search=bool(data.get("allow_yt_search", False)),
        allow_browser=bool(data.get("allow_browser", False)),
        allow_power_menu=bool(data.get("allow_power_menu", False)),
        updated_at=int(data.get("updated_at") or 0),
    )


def local_day_key(ts: float) -> str:
    """Lokaler Kalendertag YYYY-MM-DD."""
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def _hhmm_to_sec(hhmm: str) -> int | None:
    m = BEDTIME_RE.fullmatch(hhmm)
    if not m:
        return None
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60


def in_bedtime(start: str, end: str, ts: float) -> tuple[bool, int | None]:
    """Prueft, ob ts in [start, end) liegt, und liefert (aktiv, sekunden_bis_beginn)."""
    s_sec = _hhmm_to_sec(start)
    e_sec = _hhmm_to_sec(end)
    if s_sec is None or e_sec is None or s_sec == e_sec:
        return False, None

    tm = time.localtime(ts)
    now_sec = tm.tm_hour * 3600 + tm.tm_min * 60 + tm.tm_sec

    if s_sec < e_sec:
        if s_sec <= now_sec < e_sec:
            return True, None
        until = (s_sec - now_sec) if now_sec < s_sec else (_SECONDS_PER_DAY - now_sec + s_sec)
        return False, until

    # Ueber-Nacht-Fenster (z. B. 20:00 -> 07:00)
    if now_sec >= s_sec or now_sec < e_sec:
        return True, None
    return False, s_sec - now_sec


def effective_age_rating(tile_id: str, cat: str = "", explicit: int | None = None) -> int:
    """Altersstufe einer Kachel/App (explizit -> App-Tabelle -> Kategorie-Tabelle -> 0)."""
    if explicit is not None:
        return max(0, int(explicit))
    if tile_id in DEFAULT_APP_AGE_RATINGS:
        return DEFAULT_APP_AGE_RATINGS[tile_id]
    if cat and cat in DEFAULT_CAT_AGE_RATINGS:
        return DEFAULT_CAT_AGE_RATINGS[cat]
    return 0


def is_browser_tile(tile_id: str, cat: str = "", cmd: list[str] | None = None) -> bool:
    """Erkennt freie Webbrowser-Kacheln (Streaming-Kiosk-Apps zaehlen nicht als Browser)."""
    if tile_id in BROWSER_TILE_IDS or cat == "Browser":
        return True
    if cmd and isinstance(cmd, list) and cmd:
        exe = Path(str(cmd[0])).name.lower()
        if exe in BROWSER_BINARIES and "--kiosk" not in cmd and cat != "Streaming" and tile_id != "youtube":
            return True
    return False


class ParentalController:
    """Erzwingt Kindersicherungsregeln, trackt Nutzungszeit im 30-s-Takt und verwaltet Eltern-Overrides."""

    def __init__(
        self,
        store: AccountStore,
        get_session: Callable[[], SessionState],
        get_device_policy: Callable[[], DevicePolicy],
        clock: Callable[[], float] | None = None,
        lock: threading.RLock | None = None,
    ) -> None:
        self._store = store
        self._get_session = get_session
        self._get_device_policy = get_device_policy
        self._clock = clock or time.time
        self._lock = lock or threading.RLock()

        self._allow_once: dict[str, set[str]] = {}
        self._bedtime_override_until: dict[str, int] = {}
        self._warned_limit: dict[tuple[str, str], int] = {}
        self._warned_bedtime: dict[tuple[str, str], int] = {}
        self._locked_notified: dict[str, str] = {}

        self._tracker_stop = threading.Event()
        self._tracker_thread: threading.Thread | None = None

    def _now(self) -> float:
        return float(self._clock())

    def policy_for(self, account_id: str) -> ParentalPolicy:
        with self._lock:
            return self._store.get_parental_policy(account_id) or ParentalPolicy(account_id=account_id)

    def usage_summary(self, account_id: str) -> dict[str, Any]:
        with self._lock:
            now = self._now()
            day = local_day_key(now)
            policy = self.policy_for(account_id)
            used_seconds, bonus_seconds = self._store.get_daily_usage(account_id, day)
            if policy.daily_limit_min > 0:
                limit_seconds = policy.daily_limit_min * 60 + bonus_seconds
                remaining_seconds: int | None = max(0, limit_seconds - used_seconds)
            else:
                limit_seconds = 0
                remaining_seconds = None

            bedtime_active, seconds_to_bedtime = in_bedtime(policy.bedtime_start, policy.bedtime_end, now)
            override_until = self._bedtime_override_until.get(account_id, 0)
            if override_until > int(now):
                bedtime_blocked = False
                rem_override = max(1, override_until - int(now))
                if bedtime_active:
                    seconds_to_bedtime = rem_override
                elif seconds_to_bedtime is not None:
                    seconds_to_bedtime = min(seconds_to_bedtime, rem_override)
            else:
                if override_until and override_until <= int(now):
                    self._bedtime_override_until.pop(account_id, None)
                bedtime_blocked = bedtime_active

            limit_blocked = policy.daily_limit_min > 0 and remaining_seconds is not None and remaining_seconds <= 0
            time_blocked = bedtime_blocked or limit_blocked
            time_reason = "bedtime" if bedtime_blocked else ("daily_limit" if limit_blocked else "")

            return {
                "day": day,
                "used_seconds": used_seconds,
                "bonus_seconds": bonus_seconds,
                "daily_limit_min": policy.daily_limit_min,
                "limit_seconds": limit_seconds,
                "remaining_seconds": remaining_seconds,
                "in_bedtime": bedtime_blocked,
                "seconds_to_bedtime": seconds_to_bedtime,
                "bedtime_override_until": override_until if override_until > int(now) else 0,
                "time_blocked": time_blocked,
                "time_reason": time_reason,
            }

    def status_for_session(self, account_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            if account_id is not None:
                acc = self._store.get_account(account_id)
                if not acc or acc.role != "child":
                    return {
                        "restricted": False,
                        "locked": False,
                        "reason": "",
                        "remaining_seconds": None,
                        "allow_yt_search": True,
                        "allow_browser": True,
                        "allow_power_menu": True,
                    }
                aid = acc.id
                role = acc.role
                is_guest = False
                sess_locked = False
            else:
                sess = self._get_session()
                aid = sess.account_id
                role = sess.role
                is_guest = sess.is_guest
                sess_locked = sess.locked

            if is_guest:
                return {
                    "restricted": True,
                    "locked": sess_locked,
                    "reason": "session_locked" if sess_locked else "",
                    "remaining_seconds": None,
                    "allow_yt_search": True,
                    "allow_browser": False,
                    "allow_power_menu": True,
                }

            if role != "child" or not aid:
                return {
                    "restricted": False,
                    "locked": sess_locked,
                    "reason": "session_locked" if sess_locked else "",
                    "remaining_seconds": None,
                    "allow_yt_search": True,
                    "allow_browser": True,
                    "allow_power_menu": True,
                }

            policy = self.policy_for(aid)
            usage = self.usage_summary(aid)
            return {
                "restricted": True,
                "locked": bool(sess_locked or usage["time_blocked"]),
                "reason": "session_locked" if sess_locked else usage["time_reason"],
                "remaining_seconds": usage["remaining_seconds"],
                "used_seconds": usage["used_seconds"],
                "bonus_seconds": usage["bonus_seconds"],
                "limit_seconds": usage["limit_seconds"],
                "in_bedtime": usage["in_bedtime"],
                "seconds_to_bedtime": usage["seconds_to_bedtime"],
                "allow_yt_search": policy.allow_yt_search,
                "allow_browser": policy.allow_browser,
                "allow_power_menu": policy.allow_power_menu,
                "allowed_once_tiles": sorted(self._allow_once.get(aid, set())),
                "policy": policy.to_dict(),
                "usage": usage,
            }

    def check_tile(
        self,
        tile_id: str,
        *,
        cat: str = "",
        age_rating: int | None = None,
        is_browser: bool | None = None,
        cmd: list[str] | None = None,
        consume_once: bool = False,
        already_running: bool = False,
        ignore_time: bool = False,
    ) -> ParentalDecision:
        with self._lock:
            sess = self._get_session()
            if sess.locked:
                return ParentalDecision(False, "session_locked", "account.err.locked", False, None, tile_id)

            if sess.is_guest:
                if tile_id in ALWAYS_VISIBLE_TILES:
                    return ParentalDecision(True, tile_id=tile_id)
                if tile_id in ADMIN_ONLY_TILES:
                    return ParentalDecision(False, "admin_only", "account.blocked", False, None, tile_id)
                browser = is_browser_tile(tile_id, cat, cmd) if is_browser is None else bool(is_browser)
                if browser:
                    return ParentalDecision(False, "browser_blocked", "account.blocked", False, None, tile_id)
                if tile_id in GUEST_BLOCKED_TILES or (cat and cat in GUEST_BLOCKED_CATS):
                    return ParentalDecision(False, "guest_restricted", "account.blocked", False, None, tile_id)
                dev = self._get_device_policy()
                if dev.guest_allowed_tiles and tile_id not in dev.guest_allowed_tiles:
                    return ParentalDecision(False, "guest_restricted", "account.blocked", False, None, tile_id)
                return ParentalDecision(True, tile_id=tile_id)

            if sess.role != "child":
                return ParentalDecision(True, tile_id=tile_id)

            if tile_id in ALWAYS_VISIBLE_TILES:
                return ParentalDecision(True, tile_id=tile_id)

            usage = self.usage_summary(sess.account_id)
            remaining = usage["remaining_seconds"]
            if not ignore_time and usage["time_blocked"]:
                return ParentalDecision(False, usage["time_reason"], "account.blocked", True, 0, tile_id)

            if already_running:
                return ParentalDecision(True, remaining_seconds=remaining, tile_id=tile_id)

            once_set = self._allow_once.get(sess.account_id)
            if once_set and tile_id in once_set:
                if consume_once:
                    once_set.discard(tile_id)
                return ParentalDecision(True, remaining_seconds=remaining, tile_id=tile_id)

            if tile_id in ADMIN_ONLY_TILES:
                return ParentalDecision(False, "admin_only", "account.blocked", False, remaining, tile_id)

            policy = self.policy_for(sess.account_id)
            browser = is_browser_tile(tile_id, cat, cmd) if is_browser is None else bool(is_browser)
            if browser and not policy.allow_browser:
                return ParentalDecision(False, "browser_blocked", "account.blocked", True, remaining, tile_id)

            if tile_id in policy.blocked_tiles:
                return ParentalDecision(False, "tile_blocked", "account.blocked", True, remaining, tile_id)

            if cat and cat in policy.blocked_cats:
                return ParentalDecision(False, "category_blocked", "account.blocked", True, remaining, tile_id)

            eff_age = effective_age_rating(tile_id, cat, age_rating)
            if eff_age > policy.max_age_rating:
                return ParentalDecision(False, "age_rating", "account.blocked", True, remaining, tile_id)

            if policy.mode == "allowlist" and tile_id not in policy.allowed_tiles:
                return ParentalDecision(False, "not_allowed", "account.blocked", True, remaining, tile_id)

            return ParentalDecision(True, remaining_seconds=remaining, tile_id=tile_id)

    def check_action(self, action: str) -> ParentalDecision:
        with self._lock:
            sess = self._get_session()
            if sess.locked:
                return ParentalDecision(False, "session_locked", "account.err.locked", False)

            if action in ("apps_manage", "settings_system"):
                if sess.is_guest or sess.role == "child":
                    return ParentalDecision(False, "admin_only", "account.err.adminRequired", False)
                return ParentalDecision(True)

            if sess.is_guest or sess.role != "child":
                return ParentalDecision(True)

            usage = self.usage_summary(sess.account_id)
            remaining = usage["remaining_seconds"]
            if action == "yt_play":
                if usage["time_blocked"]:
                    return ParentalDecision(False, usage["time_reason"], "account.blocked", True, 0)
                return ParentalDecision(True, remaining_seconds=remaining)

            policy = self.policy_for(sess.account_id)
            if action == "yt_search":
                if usage["time_blocked"]:
                    return ParentalDecision(False, usage["time_reason"], "account.blocked", True, 0)
                if not policy.allow_yt_search:
                    return ParentalDecision(False, "yt_search_blocked", "account.blocked", False, remaining)
                return ParentalDecision(True, remaining_seconds=remaining)

            if action == "power_menu":
                if not policy.allow_power_menu:
                    return ParentalDecision(False, "power_blocked", "account.blocked", True, remaining)
                return ParentalDecision(True, remaining_seconds=remaining)

            return ParentalDecision(True, remaining_seconds=remaining)

    def grant_allow_once(self, account_id: str, tile_id: str) -> None:
        tid = str(tile_id or "").strip()
        if not tid:
            raise ValidationError("account.err.invalid", "tile_id required")
        with self._lock:
            self._allow_once.setdefault(account_id, set()).add(tid)

    def grant_extra_minutes(self, account_id: str, minutes: int) -> dict[str, Any]:
        try:
            mins = int(minutes)
        except (TypeError, ValueError) as exc:
            raise ValidationError("account.err.invalid", "Invalid minutes") from exc
        if mins < 1 or mins > 240:
            raise ValidationError("account.err.invalid", "Minutes must be between 1 and 240")

        with self._lock:
            now = self._now()
            day = local_day_key(now)
            delta = mins * 60
            self._store.add_bonus_seconds(account_id, day, delta)
            policy = self.policy_for(account_id)
            if policy.bedtime_start and policy.bedtime_end:
                bed_active, _ = in_bedtime(policy.bedtime_start, policy.bedtime_end, now)
                if bed_active:
                    cur_until = self._bedtime_override_until.get(account_id, 0)
                    base_ts = max(int(now), cur_until)
                    self._bedtime_override_until[account_id] = base_ts + delta
            self._locked_notified.pop(account_id, None)
            self._warned_limit.pop((account_id, day), None)
            self._warned_bedtime.pop((account_id, day), None)
            return self.usage_summary(account_id)

    def on_policy_updated(self, account_id: str) -> None:
        with self._lock:
            day = local_day_key(self._now())
            self._locked_notified.pop(account_id, None)
            self._warned_limit.pop((account_id, day), None)
            self._warned_bedtime.pop((account_id, day), None)

    def on_session_changed(self, prev_id: str, new_id: str, *, locked: bool = False) -> None:
        with self._lock:
            if prev_id and (prev_id != new_id or locked):
                self._allow_once.pop(prev_id, None)
                self._locked_notified.pop(prev_id, None)
            if new_id and locked:
                self._allow_once.pop(new_id, None)
                self._locked_notified.pop(new_id, None)

    def tick(self, elapsed_seconds: int = USAGE_TICK_SECONDS) -> list[dict[str, Any]]:
        """Zaehlt Nutzungszeit fuer aktive Kinderkonten und erzeugt Warn-/Sperr-Events."""
        events: list[dict[str, Any]] = []
        with self._lock:
            sess = self._get_session()
            if sess.locked or sess.is_guest or sess.role != "child" or not sess.account_id:
                return events

            aid = sess.account_id
            now = self._now()
            day = local_day_key(now)
            if elapsed_seconds > 0:
                self._store.add_usage_seconds(aid, day, int(elapsed_seconds))

            usage = self.usage_summary(aid)
            if usage["time_blocked"]:
                reason = usage["time_reason"]
                if self._locked_notified.get(aid) != reason:
                    self._locked_notified[aid] = reason
                    events.append(
                        {
                            "ev": "account_locked",
                            "account_id": aid,
                            "reason": reason,
                            "remaining_seconds": 0,
                            "used_seconds": usage["used_seconds"],
                            "limit_seconds": usage["limit_seconds"],
                        }
                    )
                return events

            self._locked_notified.pop(aid, None)
            rem = usage["remaining_seconds"]
            if rem is not None and 0 < rem <= WARN_THRESHOLD_SECONDS:
                limit_key = int(usage["limit_seconds"])
                if self._warned_limit.get((aid, day)) != limit_key:
                    self._warned_limit[(aid, day)] = limit_key
                    events.append(
                        {
                            "ev": "account_warn",
                            "account_id": aid,
                            "reason": "daily_limit",
                            "remaining_seconds": rem,
                            "minutes": max(1, (rem + 59) // 60),
                        }
                    )

            bed_sec = usage["seconds_to_bedtime"]
            if bed_sec is not None and 0 < bed_sec <= WARN_THRESHOLD_SECONDS:
                target_min = int((now + bed_sec) // 60)
                if self._warned_bedtime.get((aid, day)) != target_min:
                    self._warned_bedtime[(aid, day)] = target_min
                    events.append(
                        {
                            "ev": "account_warn",
                            "account_id": aid,
                            "reason": "bedtime",
                            "remaining_seconds": bed_sec,
                            "minutes": max(1, (bed_sec + 59) // 60),
                        }
                    )
        return events

    def start_tracker(
        self,
        on_event: Callable[[dict[str, Any]], None],
        interval: float = USAGE_TICK_SECONDS,
    ) -> None:
        with self._lock:
            if self._tracker_thread and self._tracker_thread.is_alive():
                return
            self._tracker_stop.clear()
            tick_sec = max(1, int(round(interval)))

            def _run() -> None:
                while not self._tracker_stop.wait(interval):
                    try:
                        evs = self.tick(tick_sec)
                    except Exception:
                        continue
                    for ev in evs:
                        try:
                            on_event(ev)
                        except Exception:
                            pass

            self._tracker_thread = threading.Thread(target=_run, daemon=True)
            self._tracker_thread.start()

    def stop_tracker(self) -> None:
        self._tracker_stop.set()
        th = self._tracker_thread
        self._tracker_thread = None
        if th and th.is_alive() and th is not threading.current_thread():
            th.join(timeout=1.0)
