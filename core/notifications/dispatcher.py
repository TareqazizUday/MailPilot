"""Single entry point for raising notifications: record once, deliver to many channels."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any, Optional

from django.conf import settings
from django.db import close_old_connections, transaction
from django.utils import timezone

from core.notifications.preferences import event_enabled, get_preferences

log = logging.getLogger("mailpilot.notifications")

DEDUPE_WINDOW = timedelta(minutes=5)

_executor: Optional[ThreadPoolExecutor] = None


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="notify")
    return _executor


def _deliver_in_thread(notification_id: int) -> None:
    from core.notifications.delivery import deliver

    try:
        deliver(notification_id)
    except Exception as e:
        log.warning("Notification delivery failed id=%s: %s", notification_id, e)
    finally:
        close_old_connections()


def schedule_delivery(notification_id: int) -> None:
    if getattr(settings, "NOTIFY_DELIVERY_SYNC", False):
        from core.notifications.delivery import deliver

        deliver(notification_id)
        return
    if getattr(settings, "CELERY_BROKER_URL", ""):
        try:
            from core.tasks import deliver_notification

            deliver_notification.delay(notification_id)
            return
        except Exception as e:
            log.warning("Celery enqueue failed, delivering in thread: %s", e)
    _get_executor().submit(_deliver_in_thread, notification_id)


def notify(
    user_id: int,
    event: str,
    title: str,
    body: str = "",
    data: Optional[dict[str, Any]] = None,
    *,
    tenant_id: str = "",
    account_id: Optional[int] = None,
    dedupe_key: str = "",
):
    """Create the in-app record and schedule push/external delivery. Never raises."""
    try:
        from django.contrib.auth.models import User

        from core.models import MailAccount, Notification

        user = User.objects.filter(pk=user_id).first()
        if user is None:
            return None
        prefs = get_preferences(user)
        if not event_enabled(prefs, event):
            return None
        now = timezone.now()
        if dedupe_key and Notification.objects.filter(
            user_id=user_id, dedupe_key=dedupe_key, created_at__gte=now - DEDUPE_WINDOW
        ).exists():
            return None
        if account_id is not None and not MailAccount.objects.filter(pk=account_id, user_id=user_id).exists():
            account_id = None
        n = Notification.objects.create(
            user_id=user_id,
            tenant_id=(tenant_id or "")[:64],
            account_id=account_id,
            event=event,
            title=(title or "")[:200],
            body=body or "",
            data=data or {},
            dedupe_key=(dedupe_key or "")[:300],
            read_at=None if prefs["in_app"] else now,
        )
        transaction.on_commit(lambda: schedule_delivery(n.pk))
        return n
    except Exception as e:
        log.warning("notify failed user=%s event=%s: %s", user_id, event, e)
        return None


def parse_tenant(tenant_id: str) -> tuple[Optional[int], Optional[int]]:
    """Tenant ids look like "<user_id>" or "<user_id>:<account_id>"."""
    parts = (tenant_id or "").strip().split(":")
    try:
        uid = int(parts[0])
    except (ValueError, IndexError):
        return None, None
    aid = None
    if len(parts) > 1:
        try:
            aid = int(parts[1])
        except ValueError:
            aid = None
    return uid, aid


_MAIL_TITLES = {
    "draft": "Draft saved",
    "sent": "Auto-reply sent",
    "error": "Send failed",
}


def notify_mail_event(
    tenant_id: str,
    event: str,
    *,
    subject: str = "",
    from_email: str = "",
    error: str = "",
    reply_subject: str = "",
    message_id: str = "",
    thread_id: str = "",
):
    uid, aid = parse_tenant(tenant_id)
    if uid is None:
        return None
    message_id = str(message_id or "")
    thread_id = str(thread_id or "")
    subj = (subject or reply_subject or "(No subject)").strip()
    sender = (from_email or "unknown").strip()
    body = f"From {sender}: {subj}"
    if event == "error" and error:
        body += f"\nError: {error.strip()[:500]}"
    deep_link = f"mailpilot://thread/{thread_id}" if thread_id else "mailpilot://notifications"
    data = {
        "kind": "mail",
        "subject": subject,
        "reply_subject": reply_subject,
        "from_email": from_email,
        "error": error[:1000] if error else "",
        "message_id": message_id,
        "thread_id": thread_id,
        "account_id": aid,
        "deep_link": deep_link,
        "url": "/inbox",
    }
    return notify(
        uid,
        event,
        _MAIL_TITLES.get(event, f"MailPilot: {event}"),
        body,
        data,
        tenant_id=tenant_id,
        account_id=aid,
        dedupe_key=f"{event}:{tenant_id}:{message_id}" if message_id else "",
    )
