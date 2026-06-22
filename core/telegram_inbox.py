"""Read-only inbox/thread/ignored summaries for Telegram bot (no email flow changes)."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from core import runtime
from core.mail_accounts import TRANSPORT_GMAIL, TRANSPORT_SMTP, enabled_accounts_for_active_mode
from email_automation.gmail_auth import gmail_oauth_matches_configured, gmail_oauth_ready
from email_automation.gmail_client import GmailClient
from email_automation.imap_mailbox import ImapMailbox, imap_inbox_ready
from email_automation.settings import Settings

log = logging.getLogger("mailpilot.telegram.inbox")

TELEGRAM_MAX_CHARS = 4000
_INBOX_LIST_LIMIT = 15
_IGNORED_LIST_LIMIT = 15


def is_inbox_list_command(text: str) -> bool:
    t = (text or "").strip().lower()
    if t in ("/inbox", "/list", "/messages"):
        return True
    if t.startswith("/inbox ") or t.startswith("/list "):
        return True
    return False


def is_ignored_command(text: str) -> bool:
    t = (text or "").strip().lower()
    return t in ("/ignored", "/rejected", "/reject")


def parse_thread_command(text: str) -> Optional[str]:
    raw = (text or "").strip()
    if not raw.lower().startswith("/thread"):
        return None
    parts = raw.split(maxsplit=1)
    if len(parts) < 2:
        return ""
    return parts[1].strip()


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


def _fmt_ts(ms: Any, tz: ZoneInfo) -> str:
    try:
        n = int(ms or 0)
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    try:
        dt = datetime.fromtimestamp(n / 1000, tz=timezone.utc).astimezone(tz)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def _short_addr(from_header: str) -> str:
    s = (from_header or "").strip()
    if not s:
        return "unknown"
    m = re.search(r"<([^>]+)>", s)
    if m:
        return m.group(1).strip()
    return s[:80]


def _short_subject(subject: str) -> str:
    s = (subject or "").strip() or "(No subject)"
    return s if len(s) <= 72 else s[:69] + "..."


def _status_tag(status: str | None) -> str:
    s = (status or "").lower()
    if s == "reject":
        return "reject"
    if s == "sent":
        return "sent"
    if s == "draft":
        return "draft"
    return ""


def _reason_label(reason: str) -> str:
    r = (reason or "").strip().lower()
    labels = {
        "keyword_prefilter": "keyword filter",
        "not_relevant": "not relevant",
        "own_mailbox_sender": "own mailbox",
    }
    return labels.get(r, r or "ignored")


def _inbox_message_status(meta: dict[str, Any] | None) -> str | None:
    if not meta:
        return None
    action = (meta.get("action") or "").lower()
    reason = (meta.get("reason") or "").lower()
    if action == "ignored" and reason == "keyword_prefilter":
        return "reject"
    if action == "sent":
        return "sent"
    if action == "draft":
        return "draft"
    return None


def _annotate_inbox_threads(
    threads: list[dict[str, Any]], user, *, account_id: int | None
) -> list[dict[str, Any]]:
    st = runtime.state_store_for_user(user, account_id=account_id)
    for t in threads:
        mid = str(t.get("message_id") or "").strip()
        if not mid and t.get("thread_id") is not None:
            mid = f"imap:{t.get('thread_id')}"
        meta = st.get_processed_meta(mid) if mid else None
        status = _inbox_message_status(meta)
        if status:
            t["message_status"] = status
        else:
            t.pop("message_status", None)
    return threads


def _smtp_imap_inbox_active(effective: Settings) -> bool:
    return effective.SEND_TRANSPORT == "smtp" and imap_inbox_ready(effective)


def _primary_account(user):
    accounts = enabled_accounts_for_active_mode(user)
    return accounts[0] if accounts else None


def _mailbox_email(acc, effective: Settings) -> str:
    cfg = dict(acc.config_json or {})
    if acc.transport == TRANSPORT_GMAIL:
        return str(effective.GMAIL_ADDRESS or cfg.get("GMAIL_ADDRESS") or acc.label or "Gmail").strip()
    return str(
        effective.outbound_from_email() or cfg.get("SMTP_FROM_EMAIL") or cfg.get("SMTP_USERNAME") or acc.label or "SMTP"
    ).strip()


def _fetch_inbox_threads(user, *, max_threads: int = _INBOX_LIST_LIMIT) -> tuple[str, list[dict[str, Any]] | None, str]:
    acc = _primary_account(user)
    if acc is None:
        return "", None, "No enabled mailbox found. Connect Gmail or SMTP in Setup."
    effective = runtime.get_effective_settings(user, account_id=acc.id)
    email = _mailbox_email(acc, effective)
    try:
        g_ok = gmail_oauth_ready(effective) and acc.transport == TRANSPORT_GMAIL
        use_imap = acc.transport == TRANSPORT_SMTP and (
            _smtp_imap_inbox_active(effective) or (imap_inbox_ready(effective) and not g_ok)
        )
        if use_imap:
            threads = ImapMailbox(settings=effective).list_inbox_summaries(max_threads=max_threads)
        elif g_ok:
            if not gmail_oauth_matches_configured(effective)[0]:
                return email, None, "Gmail OAuth mismatch - reconnect on Setup."
            threads = GmailClient(settings=effective).list_inbox_thread_summaries(max_threads=max_threads)
        else:
            return email, None, "Mailbox not connected - check Setup."
        return email, _annotate_inbox_threads(threads, user, account_id=acc.id), ""
    except Exception as e:
        log.warning("Telegram inbox list failed user=%s: %s", user.id, e)
        return email, None, "Could not load inbox right now. Try again or open the Dashboard."


def _fetch_thread_messages(user, thread_id: str) -> tuple[str, list[dict[str, Any]] | None, str]:
    tid = (thread_id or "").strip()
    if not tid:
        return "", None, "Usage: /thread <thread_id>\nTip: run /inbox first - each row shows /thread <id>."
    acc = _primary_account(user)
    if acc is None:
        return "", None, "No enabled mailbox found. Connect Gmail or SMTP in Setup."
    effective = runtime.get_effective_settings(user, account_id=acc.id)
    email = _mailbox_email(acc, effective)
    try:
        g_ok = gmail_oauth_ready(effective) and acc.transport == TRANSPORT_GMAIL
        uid = int(tid) if tid.isdigit() else None
        use_imap = uid is not None and (
            _smtp_imap_inbox_active(effective) or (imap_inbox_ready(effective) and not g_ok)
        )
        if use_imap:
            data = ImapMailbox(settings=effective).get_thread_for_ui(uid=uid)
        elif g_ok:
            if not gmail_oauth_matches_configured(effective)[0]:
                return email, None, "Gmail OAuth mismatch - reconnect on Setup."
            data = GmailClient(settings=effective).get_thread_for_ui(tid)
        else:
            return email, None, "Mailbox not connected - check Setup."
        messages = list(data.get("messages") or [])
        messages.sort(key=lambda m: int(m.get("internal_date") or 0))
        if not messages:
            return email, None, "Thread not found or empty."
        return email, messages, ""
    except Exception as e:
        log.warning("Telegram thread fetch failed user=%s tid=%s: %s", user.id, tid, e)
        return email, None, "Could not open that thread. Check the id from /inbox or try the Dashboard."


def _collect_ignored(user, *, limit: int = _IGNORED_LIST_LIMIT) -> tuple[str, list[dict[str, Any]], str]:
    from core.models import ProcessedMeta

    acc = _primary_account(user)
    if acc is None:
        return "", [], "No enabled mailbox found. Connect Gmail or SMTP in Setup."
    effective = runtime.get_effective_settings(user, account_id=acc.id)
    email = _mailbox_email(acc, effective)
    st = runtime.state_store_for_user(user, account_id=acc.id)
    rows = (
        ProcessedMeta.objects.filter(tenant_id=st.tenant_id)
        .order_by("-id")
        .only("message_id", "meta_json")[: max(100, limit * 8)]
    )
    items: list[dict[str, Any]] = []
    for row in rows:
        meta = row.meta_json if isinstance(row.meta_json, dict) else {}
        if str(meta.get("action") or "").lower() != "ignored":
            continue
        items.append(
            {
                "message_id": str(row.message_id or ""),
                "from_email": str(meta.get("from_email") or ""),
                "subject": str(meta.get("subject") or meta.get("reply_subject") or ""),
                "reason": str(meta.get("reason") or "ignored"),
                "processed_at": str(meta.get("processed_at") or ""),
            }
        )
        if len(items) >= limit:
            break
    items.sort(key=lambda x: str(x.get("processed_at") or ""), reverse=True)
    return email, items, ""


def _clip(text: str, *, max_chars: int = TELEGRAM_MAX_CHARS) -> str:
    body = (text or "").strip()
    if len(body) <= max_chars:
        return body
    return body[: max_chars - 40].rstrip() + "\n\n… (truncated - open Dashboard for full content)"


def format_inbox_list_reply(user) -> str:
    tz = _user_timezone(user)
    email, threads, err = _fetch_inbox_threads(user)
    if err:
        return err
    lines = [f"MailPilot inbox list - {email}", ""]
    if not threads:
        lines.append("No messages in this folder.")
        lines.append("")
        lines.append("Commands: /mail (stats) · /ignored · /thread <id>")
        return _clip("\n".join(lines))
    for i, t in enumerate(threads, start=1):
        tid = str(t.get("thread_id") or "").strip()
        sender = _short_addr(str(t.get("from") or ""))
        subj = _short_subject(str(t.get("subject") or ""))
        when = _fmt_ts(t.get("internal_date"), tz)
        tags: list[str] = []
        if t.get("unread"):
            tags.append("unread")
        st = _status_tag(t.get("message_status"))
        if st:
            tags.append(st)
        tag = f" [{', '.join(tags)}]" if tags else ""
        lines.append(f"{i}.{tag} {sender}")
        lines.append(f"   {subj}")
        if when:
            lines.append(f"   {when}")
        if tid:
            lines.append(f"   /thread {tid}")
        lines.append("")
    lines.append(f"Showing {len(threads)} message(s). Commands: /mail · /ignored")
    return _clip("\n".join(lines).strip())


def format_ignored_reply(user) -> str:
    tz = _user_timezone(user)
    email, items, err = _collect_ignored(user)
    if err:
        return err
    lines = [f"MailPilot ignored mail - {email}", ""]
    if not items:
        lines.append("No ignored messages recorded for this mailbox.")
        lines.append("")
        lines.append("Ignored mail appears after MailPilot polls and skips a message.")
        lines.append("Commands: /inbox · /mail")
        return "\n".join(lines)
    for i, it in enumerate(items, start=1):
        sender = _short_addr(it.get("from_email") or "")
        subj = _short_subject(it.get("subject") or "")
        reason = _reason_label(it.get("reason") or "")
        when = ""
        raw_at = it.get("processed_at") or ""
        if raw_at:
            try:
                dt = datetime.fromisoformat(str(raw_at).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                when = dt.astimezone(tz).strftime("%Y-%m-%d %H:%M")
            except Exception:
                when = ""
        lines.append(f"{i}. {sender}")
        lines.append(f"   {subj}")
        lines.append(f"   reason: {reason}" + (f" · {when}" if when else ""))
        lines.append("")
    lines.append(f"Showing {len(items)} ignored message(s). Commands: /inbox · /mail")
    return _clip("\n".join(lines).strip())


def format_thread_reply(user, thread_id: str) -> str:
    tz = _user_timezone(user)
    email, messages, err = _fetch_thread_messages(user, thread_id)
    if err:
        return err
    assert messages is not None
    latest = messages[-1]
    subj = _short_subject(str(latest.get("subject") or messages[0].get("subject") or ""))
    lines = [f"MailPilot thread - {email}", subj, ""]
    for m in messages:
        sender = _short_addr(str(m.get("from") or ""))
        when = _fmt_ts(m.get("internal_date"), tz)
        body = (m.get("body_text") or "").strip()
        if not body:
            snippet = (m.get("snippet") or "").strip()
            body = f"(Preview) {snippet}" if snippet else "(No content)"
        who = "You" if m.get("is_from_me") else sender
        header = f"- {who}"
        if when:
            header += f" · {when}"
        lines.append(header)
        lines.append(body)
        lines.append("")
    lines.append("Commands: /inbox · /ignored · /mail")
    return _clip("\n".join(lines).strip())
