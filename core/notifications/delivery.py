"""Channel routing for a stored Notification: push, then Telegram/WhatsApp per the user's external mode."""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

from core.notifications.channels import expo_push
from core.notifications.channels import telegram as telegram_channel
from core.notifications.channels import whatsapp as whatsapp_channel
from core.notifications.preferences import EXTERNAL_FALLBACK, EXTERNAL_OFF, get_preferences
from core.notifications.presence import is_online

log = logging.getLogger("mailpilot.notifications")

EXTERNAL_CHANNELS = (("telegram", telegram_channel), ("whatsapp", whatsapp_channel))

_CLAIMED = "delivering"


def _parse_hhmm(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


def in_quiet_hours(prefs: dict[str, Any], tz_name: str, now: datetime | None = None) -> bool:
    qh = prefs.get("quiet_hours") or {}
    if not qh.get("enabled"):
        return False
    try:
        tz = ZoneInfo(tz_name or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    local = (now or timezone.now()).astimezone(tz).time()
    start, end = _parse_hhmm(qh["start"]), _parse_hhmm(qh["end"])
    if start == end:
        return False
    if start < end:
        return start <= local < end
    return local >= start or local < end


def _user_timezone(user) -> str:
    profile = getattr(user, "profile", None)
    return getattr(profile, "timezone", "") or "UTC"


def _external_text(n) -> str:
    data = n.data or {}
    if data.get("kind") == "mail":
        from core.telegram_notify import _format_message

        return _format_message(
            n.event,
            subject=str(data.get("subject") or ""),
            from_email=str(data.get("from_email") or ""),
            error=str(data.get("error") or ""),
            reply_subject=str(data.get("reply_subject") or ""),
        )
    return f"MailPilot: {n.title}\n{n.body}".strip()


def _send_external(user, event: str, text: str) -> dict[str, str]:
    """Plan entitlement is enforced when Telegram/WhatsApp is configured, not per message."""
    out: dict[str, str] = {}
    for name, channel in EXTERNAL_CHANNELS:
        status = "failed"
        for _attempt in range(2):
            try:
                status = channel.send(user.pk, event, text)
            except Exception as e:
                log.warning("%s delivery error user=%s: %s", name, user.pk, e)
                status = "failed"
            if status != "failed":
                break
        out[name] = status
    return out


def _external_rate_limited(user_id: int) -> bool:
    from core.models import Notification

    limit = int(getattr(settings, "NOTIFY_EXTERNAL_RATE_LIMIT", 10))
    since = timezone.now() - timedelta(seconds=60)
    recent = Notification.objects.filter(
        user_id=user_id, created_at__gte=since, delivered_channels__external="sent"
    ).count()
    return recent >= limit


def deliver(notification_id: int) -> None:
    from core.models import Notification, PushDevice

    claimed = Notification.objects.filter(pk=notification_id, delivered_channels={}).update(
        delivered_channels={"status": _CLAIMED}
    )
    if not claimed:
        return
    n = Notification.objects.select_related("user", "user__profile").get(pk=notification_id)
    user = n.user
    prefs = get_preferences(user)
    quiet = n.event != Notification.EVENT_ERROR and in_quiet_hours(prefs, _user_timezone(user))
    result: dict[str, Any] = {}

    push_ok = False
    devices = list(PushDevice.objects.filter(user=user, is_active=True))
    if not prefs["push"]:
        result["push"] = "disabled"
    elif quiet:
        result["push"] = "quiet_hours"
    elif not devices:
        result["push"] = "no_device"
    else:
        unread = Notification.objects.filter(user=user, read_at__isnull=True).count()
        data = {**(n.data or {}), "notification_id": n.pk, "event": n.event}
        ok, _failed = expo_push.send_push(devices, title=n.title, body=n.body, data=data, badge=unread)
        push_ok = ok > 0
        result["push"] = "sent" if push_ok else "failed"

    mode = prefs["external_mode"]
    if mode == EXTERNAL_OFF:
        result["external"] = "disabled"
    elif quiet:
        result["external"] = "quiet_hours"
    elif mode == EXTERNAL_FALLBACK and (push_ok or is_online(user.pk)):
        result["external"] = "skipped_user_active"
    elif _external_rate_limited(user.pk):
        result["external"] = "suppressed"
    else:
        channels = _send_external(user, n.event, _external_text(n))
        result.update(channels)
        result["external"] = "sent" if "sent" in channels.values() else "none"

    n.delivered_channels = result
    n.save(update_fields=["delivered_channels"])


_DIGEST_LABELS = {
    "draft": "draft saved",
    "sent": "auto-reply sent",
    "error": "send error",
}


def flush_digests() -> int:
    """Send one summary message per user for notifications held back by the external rate limit."""
    from django.contrib.auth.models import User

    from core.models import Notification

    pending = list(
        Notification.objects.filter(delivered_channels__external="suppressed").values_list("pk", "user_id", "event")
    )
    if not pending:
        return 0
    by_user: dict[int, list[tuple[int, str]]] = {}
    for pk, uid, event in pending:
        by_user.setdefault(uid, []).append((pk, event))
    sent_users = 0
    for uid, items in by_user.items():
        user = User.objects.filter(pk=uid).first()
        if user is None:
            continue
        counts = Counter(ev for _pk, ev in items)
        lines = [f"MailPilot: {len(items)} new notifications"]
        for ev, cnt in counts.most_common():
            lines.append(f"- {cnt} {_DIGEST_LABELS.get(ev, ev)}")
        channels = _send_external(user, Notification.EVENT_DIGEST, "\n".join(lines))
        status = "digested" if "sent" in channels.values() else "digest_failed"
        for pk, _ev in items:
            n = Notification.objects.filter(pk=pk).first()
            if n is None:
                continue
            n.delivered_channels = {**(n.delivered_channels or {}), "external": status}
            n.save(update_fields=["delivered_channels"])
        sent_users += 1
    return sent_users


def cleanup_old_notifications() -> int:
    from core.models import Notification

    days = int(getattr(settings, "NOTIFY_RETENTION_DAYS", 90))
    deleted, _ = Notification.objects.filter(created_at__lt=timezone.now() - timedelta(days=days)).delete()
    return deleted
