"""Dashboard-style mail stats for Telegram bot (read-only, no email flow changes)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from core import runtime
from core.mail_accounts import TRANSPORT_GMAIL, TRANSPORT_SMTP, enabled_accounts_for_active_mode
from core.state_store import StateStore
from email_automation.gmail_auth import gmail_oauth_matches_configured, gmail_oauth_ready
from email_automation.gmail_client import GmailClient
from email_automation.imap_mailbox import ImapMailbox, imap_inbox_ready


def is_mail_stats_query(text: str) -> bool:
    t = (text or "").lower().strip()
    if t in ("/mail", "/stats", "/dashboard"):
        return True
    if "dashboard" in t or "recent mail" in t:
        return True
    mail_words = ("mail", "mails", "inbox", "email", "emails", "message", "messages")
    time_words = ("today", "recent", "aj", "aaj", "now", "current")
    stat_words = (
        "how many",
        "count",
        "koto",
        "number",
        "total",
        "inform",
        "tell me",
        "show me",
        "show",
        "received",
        "stats",
        "pending",
        "queue",
        "unread",
    )
    has_mail = any(w in t for w in mail_words)
    has_time = any(w in t for w in time_words)
    has_stat = any(w in t for w in stat_words)
    return bool(has_mail and (has_time or has_stat))


def _user_timezone(user) -> ZoneInfo:
    tz_name = "UTC"
    try:
        prof = getattr(user, "profile", None)
        if prof is not None:
            tz_name = str(getattr(prof, "timezone", None) or "UTC").strip() or "UTC"
    except Exception:
        pass
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("UTC")


def _start_of_today_ms(tz: ZoneInfo) -> int:
    now = datetime.now(tz)
    sod = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(sod.timestamp() * 1000)


def _today_label(tz: ZoneInfo) -> str:
    return datetime.now(tz).strftime("%Y-%m-%d")


def _parse_processed_at(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _is_today_ms(ms: int, *, sod_ms: int) -> bool:
    try:
        return int(ms or 0) >= sod_ms
    except (TypeError, ValueError):
        return False


@dataclass
class AccountMailStats:
    label: str
    email: str = ""
    transport: str = ""
    connected: bool = False
    error: str = ""
    inbox_recent: int = 0
    inbox_today: int = 0
    unread: int = 0
    pending: int = 0
    sent_today: int = 0
    handled_today: int = 0


@dataclass
class MailStatsSummary:
    date_label: str = ""
    accounts: list[AccountMailStats] = field(default_factory=list)


def _account_label(acc) -> str:
    cfg = dict(acc.config_json or {})
    if acc.transport == TRANSPORT_GMAIL:
        return str(cfg.get("GMAIL_ADDRESS") or acc.label or f"Gmail slot {acc.slot}").strip()
    return str(cfg.get("SMTP_FROM_EMAIL") or cfg.get("SMTP_USERNAME") or acc.label or f"SMTP slot {acc.slot}").strip()


def _count_queue_pending(st: StateStore) -> int:
    items = st.list_queue_items(limit=50)
    n = 0
    for it in items:
        s = str(it.get("status") or "").lower()
        if s in ("pending", "processing"):
            n += 1
    return n


def _count_processed_today(st: StateStore, *, sod_ms: int, tz: ZoneInfo) -> tuple[int, int]:
    from core.models import ProcessedMeta

    sent = handled = 0
    sod_dt = datetime.fromtimestamp(sod_ms / 1000, tz=timezone.utc).astimezone(tz)
    rows = ProcessedMeta.objects.filter(tenant_id=st.tenant_id).only("meta_json")
    for row in rows:
        meta = row.meta_json if isinstance(row.meta_json, dict) else {}
        action = str(meta.get("action") or "").lower()
        if action not in ("sent", "draft", "ignored", "error"):
            continue
        dt = _parse_processed_at(meta.get("processed_at"))
        if dt is None:
            continue
        if dt.astimezone(tz).date() < sod_dt.date():
            continue
        handled += 1
        if action == "sent":
            sent += 1
    return sent, handled


def _summarize_inbox_threads(threads: list[dict[str, Any]], *, sod_ms: int) -> tuple[int, int, int]:
    recent = len(threads or [])
    today = unread = 0
    for t in threads or []:
        ms = int(t.get("internal_date") or 0)
        if _is_today_ms(ms, sod_ms=sod_ms):
            today += 1
        if bool(t.get("unread")):
            unread += 1
    return recent, today, unread


def _stats_for_account(user, acc, *, sod_ms: int, tz: ZoneInfo) -> AccountMailStats:
    label = _account_label(acc)
    out = AccountMailStats(label=label, transport=acc.transport)
    effective = runtime.get_effective_settings(user, account_id=acc.id)
    st = runtime.state_store_for_user(user, account_id=acc.id)
    out.pending = _count_queue_pending(st)
    out.sent_today, out.handled_today = _count_processed_today(st, sod_ms=sod_ms, tz=tz)

    try:
        if acc.transport == TRANSPORT_GMAIL:
            out.email = str(effective.GMAIL_ADDRESS or label).strip()
            if not gmail_oauth_ready(effective):
                out.error = "Gmail not connected"
                return out
            if not gmail_oauth_matches_configured(effective)[0]:
                out.error = "Gmail OAuth mismatch"
                return out
            client = GmailClient(settings=effective)
            threads = client.list_inbox_thread_summaries(max_threads=40)
            out.connected = True
            out.inbox_recent, out.inbox_today, out.unread = _summarize_inbox_threads(threads, sod_ms=sod_ms)
        elif acc.transport == TRANSPORT_SMTP:
            out.email = str(effective.outbound_from_email() or effective.SMTP_USERNAME or label).strip()
            if not imap_inbox_ready(effective):
                out.error = "IMAP not configured"
                return out
            mb = ImapMailbox(settings=effective)
            threads = mb.list_inbox_summaries(max_threads=40)
            out.connected = True
            out.inbox_recent, out.inbox_today, out.unread = _summarize_inbox_threads(threads, sod_ms=sod_ms)
        else:
            out.error = "Unknown transport"
    except Exception as e:
        out.error = str(e)[:120]
    return out


def collect_mail_stats(user) -> MailStatsSummary:
    tz = _user_timezone(user)
    sod_ms = _start_of_today_ms(tz)
    summary = MailStatsSummary(date_label=_today_label(tz))
    accounts = enabled_accounts_for_active_mode(user)
    if not accounts:
        return summary
    for acc in accounts:
        summary.accounts.append(_stats_for_account(user, acc, sod_ms=sod_ms, tz=tz))
    return summary


def format_mail_stats_reply(user) -> str:
    summary = collect_mail_stats(user)
    lines = [f"MailPilot inbox - {summary.date_label}", ""]
    if not summary.accounts:
        lines.append("No enabled mailbox found. Connect Gmail or SMTP in Setup.")
        return "\n".join(lines)
    totals = {"recent": 0, "today": 0, "unread": 0, "pending": 0, "sent": 0}
    for acc in summary.accounts:
        name = acc.email or acc.label or "Mailbox"
        lines.append(f"{name} ({'Gmail' if acc.transport == TRANSPORT_GMAIL else 'SMTP'}):")
        if not acc.connected:
            lines.append(f"  Not connected - {acc.error or 'check Setup'}")
            lines.append("")
            continue
        lines.append(f"  Inbox today: {acc.inbox_today}")
        lines.append(f"  Recent in inbox (last 40): {acc.inbox_recent}")
        lines.append(f"  Unread: {acc.unread}")
        lines.append(f"  Auto-replies sent today: {acc.sent_today}")
        lines.append(f"  Pending in queue: {acc.pending}")
        lines.append("")
        totals["recent"] += acc.inbox_recent
        totals["today"] += acc.inbox_today
        totals["unread"] += acc.unread
        totals["pending"] += acc.pending
        totals["sent"] += acc.sent_today
    if len(summary.accounts) > 1:
        lines.append("All mailboxes total:")
        lines.append(f"  Inbox today: {totals['today']}")
        lines.append(f"  Recent: {totals['recent']} · Unread: {totals['unread']}")
        lines.append(f"  Auto-replies sent today: {totals['sent']} · Pending: {totals['pending']}")
    lines.append("")
    lines.append("Tip: /mail (stats) · /inbox (list) · /ignored · /thread <id>")
    return "\n".join(lines).strip()
