"""Per-user notification preferences, stored in UserMailSettings.settings_json["notifications"]."""
from __future__ import annotations

import copy
import re
from typing import Any

from core.mail_accounts import get_or_create_mail_settings

EXTERNAL_OFF = "off"
EXTERNAL_ALWAYS = "always"
EXTERNAL_FALLBACK = "fallback"
EXTERNAL_MODES = (EXTERNAL_OFF, EXTERNAL_ALWAYS, EXTERNAL_FALLBACK)

TOGGLEABLE_EVENTS = ("draft", "sent", "error")

DEFAULT_PREFERENCES: dict[str, Any] = {
    "in_app": True,
    "push": True,
    "external_mode": EXTERNAL_FALLBACK,
    "events": {"draft": True, "sent": True, "error": True},
    "quiet_hours": {"enabled": False, "start": "23:00", "end": "07:00"},
}

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _coerce_bool(v: Any, default: bool) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def normalize_preferences(raw: Any, base: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate `raw`; invalid or missing values keep whatever `base` (default: DEFAULT_PREFERENCES) has."""
    prefs = copy.deepcopy(base or DEFAULT_PREFERENCES)
    if not isinstance(raw, dict):
        return prefs
    prefs["in_app"] = _coerce_bool(raw.get("in_app"), prefs["in_app"])
    prefs["push"] = _coerce_bool(raw.get("push"), prefs["push"])
    mode = str(raw.get("external_mode") or "").strip().lower()
    if mode in EXTERNAL_MODES:
        prefs["external_mode"] = mode
    events = raw.get("events")
    if isinstance(events, dict):
        for ev in TOGGLEABLE_EVENTS:
            if ev in events:
                prefs["events"][ev] = _coerce_bool(events.get(ev), True)
    qh = raw.get("quiet_hours")
    if isinstance(qh, dict):
        prefs["quiet_hours"]["enabled"] = _coerce_bool(qh.get("enabled"), prefs["quiet_hours"]["enabled"])
        for key in ("start", "end"):
            val = str(qh.get(key) or "").strip()
            if _HHMM.match(val):
                prefs["quiet_hours"][key] = val
    return prefs


def get_preferences(user) -> dict[str, Any]:
    sj = dict(get_or_create_mail_settings(user).settings_json or {})
    return normalize_preferences(sj.get("notifications"))


def save_preferences(user, patch: dict[str, Any]) -> dict[str, Any]:
    """Merge a partial patch into stored preferences and return the normalized result."""
    ms = get_or_create_mail_settings(user)
    sj = dict(ms.settings_json or {})
    current = normalize_preferences(sj.get("notifications"))
    prefs = normalize_preferences(patch, base=current)
    sj["notifications"] = prefs
    ms.settings_json = sj
    ms.save(update_fields=["settings_json", "updated_at"])
    return prefs


def event_enabled(prefs: dict[str, Any], event: str) -> bool:
    if event not in TOGGLEABLE_EVENTS:
        return True
    return bool(prefs.get("events", {}).get(event, True))
