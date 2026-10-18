"""Overview dashboard numbers shared by the web /dashboard page and the mobile app API."""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from django.core.cache import cache
from django.db.models import Count, Max
from django.db.models.fields.json import KeyTextTransform

from core.mail_accounts import (
    TRANSPORT_GMAIL,
    account_display_email,
    build_effective_settings,
    list_accounts_for_user,
    tenant_id_for_account,
)
from core.models import ProcessedMeta, QueueItem

logger = logging.getLogger(__name__)

ACTIONS = ("sent", "draft", "ignored", "error")
ACTION_KEYS = {"sent": "sent", "draft": "drafts", "ignored": "filtered", "error": "failed"}
ACTION_LABELS = {"sent": "Sent", "draft": "Drafts", "ignored": "Filtered", "error": "Failed"}
RECENT_LIMIT = 10
_OAUTH_MATCH_TTL = 300


def _user_timezone(user):
    from core.telegram_mail_stats import _user_timezone as tz_for_user

    return tz_for_user(user)


def _parse_iso(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _account_label(acc) -> str:
    kind = "Gmail" if acc.transport == TRANSPORT_GMAIL else "SMTP"
    return account_display_email(acc) or (acc.label or "").strip() or f"{kind} {acc.slot}"


def _warm_oauth_match(key: str, settings) -> None:
    """Gmail profile lookup is a network call. Dashboard must not wait on it."""
    pending = f"{key}:pending"
    if cache.get(pending):
        return
    cache.set(pending, True, 60)

    def run() -> None:
        from email_automation.gmail_auth import gmail_oauth_matches_configured

        try:
            matches, profile, _configured = gmail_oauth_matches_configured(settings)
            mismatch = not matches and bool(profile)
        except Exception:
            mismatch = False
        cache.set(key, mismatch, _OAUTH_MATCH_TTL)

    threading.Thread(target=run, name="mailpilot-oauth-match", daemon=True).start()


def _oauth_mismatch(acc, settings) -> bool:
    """Cached Gmail profile check. A cold cache returns immediately and fills in the background."""
    token_file = (settings.GOOGLE_TOKEN_FILE or "").strip()
    try:
        version = int(os.path.getmtime(token_file))
    except OSError:
        version = 0
    key = f"mailpilot:dash:oauth_match:{acc.id}:{version}"
    cached = cache.get(key)
    if cached is not None:
        return bool(cached)
    _warm_oauth_match(key, settings)
    return False


def _account_health(acc) -> dict[str, Any]:
    from email_automation.gmail_auth import gmail_oauth_ready
    from email_automation.imap_mailbox import imap_inbox_ready

    mismatch = False
    try:
        settings = build_effective_settings(acc.user, account_id=acc.id)
        if acc.transport == TRANSPORT_GMAIL:
            ready = gmail_oauth_ready(settings)
            mismatch = ready and _oauth_mismatch(acc, settings)
            inbox_ready = ready and not mismatch
        else:
            inbox_ready = imap_inbox_ready(settings)
    except Exception:
        logger.exception("dashboard health failed account=%s", acc.id)
        inbox_ready = False

    if not acc.is_enabled:
        status = "disabled"
    elif mismatch:
        status = "oauth_mismatch"
    elif inbox_ready:
        status = "ok"
    else:
        status = "needs_setup"
    return {
        "id": acc.id,
        "slot": acc.slot,
        "transport": acc.transport,
        "label": _account_label(acc),
        "email": account_display_email(acc),
        "is_enabled": acc.is_enabled,
        "inbox_ready": bool(inbox_ready),
        "status": status,
        "processed": 0,
        "last_processed_at": None,
    }


def _processed_rows(tenants: list[str]):
    """Real outcomes only: alias rows (canonical_id) and Gmail thread keys duplicate a message."""
    return (
        ProcessedMeta.objects.filter(tenant_id__in=tenants)
        .exclude(message_id__startswith="gthread:")
        .exclude(meta_json__has_key="canonical_id")
        .annotate(
            action=KeyTextTransform("action", "meta_json"),
            processed_at=KeyTextTransform("processed_at", "meta_json"),
        )
        .filter(action__in=ACTIONS)
    )


def _usage(user) -> dict[str, Any]:
    try:
        from core.billing import usage_summary

        return usage_summary(user)
    except Exception:
        logger.exception("dashboard usage summary failed user=%s", user.pk)
        return {}


def dashboard_summary(user, *, days: int = 7) -> dict[str, Any]:
    days = max(1, min(int(days or 7), 31))
    tz = _user_timezone(user)
    now_local = datetime.now(tz)

    accounts = list(list_accounts_for_user(user))
    health = {acc.id: _account_health(acc) for acc in accounts}
    tenant_to_account: dict[str, int | None] = {
        tenant_id_for_account(user.id, acc.id): acc.id for acc in accounts
    }
    tenant_to_account[str(user.id)] = None
    tenants = list(tenant_to_account)

    rows = _processed_rows(tenants)

    totals = {key: 0 for key in ACTION_KEYS.values()}
    for row in rows.values("tenant_id", "action").annotate(n=Count("id")):
        n = int(row["n"])
        totals[ACTION_KEYS[row["action"]]] += n
        acc_id = tenant_to_account.get(row["tenant_id"])
        if acc_id in health:
            health[acc_id]["processed"] += n
    processed_total = sum(totals.values())

    latest: datetime | None = None
    for row in rows.values("tenant_id").annotate(latest=Max("processed_at")):
        dt = _parse_iso(row["latest"])
        if dt is None:
            continue
        acc_id = tenant_to_account.get(row["tenant_id"])
        if acc_id in health:
            health[acc_id]["last_processed_at"] = dt.isoformat()
        if latest is None or dt > latest:
            latest = dt

    first_day = (now_local - timedelta(days=days - 1)).date()
    window_start = datetime.combine(first_day, datetime.min.time(), tzinfo=tz).astimezone(timezone.utc)
    buckets = {
        first_day + timedelta(days=i): {"auto_replied": 0, "other": 0} for i in range(days)
    }
    for raw_at, action in rows.filter(processed_at__gte=window_start.isoformat()).values_list(
        "processed_at", "action"
    ):
        dt = _parse_iso(raw_at)
        if dt is None:
            continue
        bucket = buckets.get(dt.astimezone(tz).date())
        if bucket is None:
            continue
        bucket["auto_replied" if action == "sent" else "other"] += 1
    daily = [
        {
            "date": day.isoformat(),
            "label": day.strftime("%a"),
            "auto_replied": b["auto_replied"],
            "other": b["other"],
            "total": b["auto_replied"] + b["other"],
        }
        for day, b in buckets.items()
    ]

    labels = {acc_id: h["label"] for acc_id, h in health.items()}
    recent = []
    for row in rows.order_by("-processed_at", "-id").values("tenant_id", "message_id", "meta_json")[:RECENT_LIMIT]:
        meta = row["meta_json"] if isinstance(row["meta_json"], dict) else {}
        action = str(meta.get("action") or "")
        acc_id = tenant_to_account.get(row["tenant_id"])
        recent.append(
            {
                "action": action,
                "label": ACTION_LABELS.get(action, action.title()),
                "subject": str(meta.get("subject") or meta.get("reply_subject") or "").strip() or "(No subject)",
                "from_email": str(meta.get("from_email") or "").strip(),
                "reason": str(meta.get("reason") or ""),
                "processed_at": str(meta.get("processed_at") or ""),
                "thread_id": str(meta.get("thread_id") or ""),
                "message_id": str(row["message_id"] or ""),
                "account_id": acc_id,
                "account_label": labels.get(acc_id, ""),
            }
        )

    usage = _usage(user)
    plan = usage.get("plan") or {}
    plan_code = str(plan.get("code") or "starter")
    mailbox_list = [health[acc.id] for acc in accounts]

    return {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "timezone": str(tz),
        "window_days": days,
        "plan": {
            "code": plan_code,
            "label": f"{plan_code.title()} plan",
            "starter_expired": bool(plan.get("starter_expired")),
        },
        "mailboxes": {
            "connected": sum(1 for h in mailbox_list if h["is_enabled"] and h["inbox_ready"]),
            "total": len(mailbox_list),
            "items": mailbox_list,
        },
        "totals": {
            "processed": processed_total,
            **totals,
            "pending": QueueItem.objects.filter(
                tenant_id__in=tenants, status__in=("pending", "processing")
            ).count(),
            "latest_processed_at": latest.isoformat() if latest else None,
        },
        "breakdown": [
            {
                "key": ACTION_KEYS[action],
                "label": ACTION_LABELS[action],
                "count": totals[ACTION_KEYS[action]],
                "percent": round(totals[ACTION_KEYS[action]] * 100 / processed_total) if processed_total else 0,
            }
            for action in ACTIONS
        ],
        "daily": daily,
        "week_total": sum(d["total"] for d in daily),
        "recent": recent,
        "usage": usage,
    }
