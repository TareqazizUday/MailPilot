from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parseaddr
from typing import Any, Optional
from zoneinfo import ZoneInfo

from core import runtime
from core.mail_accounts import (
    TRANSPORT_GMAIL,
    TRANSPORT_SMTP,
    account_to_dict,
    enabled_accounts_for_active_mode,
    ensure_legacy_migrated,
    list_accounts_for_user,
)
from core.state_store import StateStore
from email_automation.gmail_auth import gmail_oauth_matches_configured, gmail_oauth_ready
from email_automation.gmail_client import GmailClient
from email_automation.imap_mailbox import ImapMailbox, imap_inbox_ready

MAX_CHAT_CHARS = 3900
RECENT_DEFAULT_LIMIT = 5
RECENT_ALL_LIMIT = 20


@dataclass
class MailAccountView:
    account: Any
    label: str
    email: str
    transport: str
    ready: bool
    error: str = ""


@dataclass
class MailThreadView:
    account: Any
    account_label: str
    account_email: str
    thread: dict[str, Any]
    meta: dict[str, Any] | None = None


def answer_mail_chat(user, *, text: str, channel: str, sender_name: str = "", context_text: str = "") -> str:
    """Answer one inbound Telegram/WhatsApp message using read-only mailbox data."""
    query = (text or "").strip()
    combined_query = (query + "\n\n" + (context_text or "").strip()).strip()
    lang = detect_language(query)
    intent, arg = detect_mail_intent(query)
    if context_text and intent in ("reply", "thread"):
        arg = (arg + "\n\n" + context_text).strip()
    ok = True
    err = ""
    account_id: int | None = None
    try:
        if intent == "empty":
            return _msg(lang, "empty")
        if intent == "secret":
            return _msg(lang, "secret_refusal")
        if intent == "off_topic":
            return _msg(lang, "scope_refusal")
        if intent == "help":
            return _format_help(lang)
        if intent == "thread":
            return format_thread_reply(user, arg, lang=lang)
        if intent == "reply":
            return format_reply_lookup(user, arg, lang=lang)
        if intent == "accounts":
            return format_account_list_reply(user, lang=lang)
        if intent == "account_detail":
            return format_account_detail_reply(user, arg, lang=lang)
        if intent == "important":
            return format_important_mail_reply(user, limit=_limit_from_query(query), lang=lang)
        if intent == "recent":
            return format_recent_mail_reply(user, limit=_limit_from_query(query), lang=lang)
        if intent == "ignored":
            return format_processed_activity_reply(user, action_filter="ignored", lang=lang)
        if intent == "stats":
            return format_mail_overview_reply(user, lang=lang)
        return format_broad_mail_answer(user, combined_query, lang=lang)
    except Exception as exc:
        ok = False
        err = str(exc)[:120]
        return _msg(lang, "unavailable")
    finally:
        _audit_chat_query(user, channel=channel, intent=intent, ok=ok, account_id=account_id, error=err)


def detect_language(text: str) -> str:
    t = (text or "").strip().lower()
    if re.search(r"[\u0980-\u09ff]", t):
        return "bn"
    banglish_words = (
        "amar",
        "amake",
        "ami",
        "ki",
        "kita",
        "koro",
        "dao",
        "daw",
        "dekhao",
        "koita",
        "koyta",
        "kon",
        "kont",
        "konta",
        "asche",
        "ache",
        "dicho",
        "diyecho",
        "dekhte",
        "chai",
        "gula",
        "mailer",
        "sob",
        "shob",
        "hobe",
        "mail er",
    )
    return "bn" if any(w in t for w in banglish_words) else "en"


def detect_mail_intent(text: str) -> tuple[str, str]:
    raw = (text or "").strip()
    t = raw.lower()
    if not raw:
        return "empty", ""
    if t.startswith("/start") or t in ("/help", "help", "commands", "command"):
        return "help", ""
    if _asks_for_secret(t):
        return "secret", ""

    m = re.match(r"^/thread(?:\s+(.+))?$", raw, flags=re.I)
    if m:
        return "thread", (m.group(1) or "").strip()
    m = re.match(r"^/reply(?:\s+(.+))?$", raw, flags=re.I)
    if m:
        return "reply", (m.group(1) or "").strip()
    m = re.match(r"^/account\s+(.+)$", raw, flags=re.I)
    if m:
        return "account_detail", m.group(1).strip()

    if t in ("/accounts", "/mailboxes", "/emails") or _has_any(
        t,
        (
            "connected emails",
            "email accounts",
            "accounts dekhao",
            "account gula",
            "gmail connect",
            "smtp account",
            "smtp connect",
            "কয়টা gmail",
            "কয়টা gmail",
            "কয়টা মেইল",
            "কয়টা মেইল",
        ),
    ):
        return "accounts", ""

    email_match = re.search(r"[\w.\-+]+@[\w.\-]+\.\w+", raw)
    if email_match and _has_any(t, ("detail", "details", "info", "তথ্য", "মেইল আছে", "mail ache")):
        return "account_detail", email_match.group(0)

    if t in ("/important", "/priority", "/starred") or _has_any(
        t, ("important", "priority", "starred", "গুরুত্ব", "জরুরি", "priority inbox")
    ):
        return "important", ""
    if _looks_like_mail_detail_request(t):
        return "thread", raw
    if t in ("/inbox", "/latest", "/recent", "/messages", "/list") or _has_any(
        t,
        (
            "recent mail",
            "recent email",
            "latest mail",
            "latest email",
            "last mail",
            "last email",
            "new mail",
            "new email",
            "inbox",
            "শেষ মেইল",
            "নতুন মেইল",
            "সর্বশেষ",
            "ki mail asche",
            "mail asche",
        ),
    ):
        return "recent", ""
    if t in ("/ignored", "/rejected", "/reject") or _has_any(
        t, ("ignored", "rejected", "ignore kor", "reject", "স্কিপ", "ইগনোর")
    ):
        return "ignored", ""
    if _has_any(t, ("pending", "queue", "processing", "unread beshi", "unread বেশি")):
        return "broad", raw
    if t in ("/mail", "/stats", "/dashboard") or _has_any(
        t,
        (
            "how many",
            "count",
            "stats",
            "summary",
            "overview",
            "koto",
            "koita",
            "dashboard",
        ),
    ):
        return "stats", ""
    if _has_any(t, ("reply", "উত্তর", "রিপ্লাই", "ki uttor", "ki reply", "dicho", "diyecho")):
        return "reply", raw
    if _is_mail_scope(t):
        return "broad", raw
    return "off_topic", ""


def format_recent_mail_reply(user, *, limit: int = RECENT_DEFAULT_LIMIT, lang: str | None = None) -> str:
    lang = lang or "en"
    threads = _collect_recent_threads(user, limit=limit)
    if not threads:
        return _msg(lang, "no_recent")
    title = "📬 আপনার সর্বশেষ মেইল:" if lang == "bn" else "📬 Your latest emails:"
    lines = [title, ""]
    for idx, item in enumerate(threads, start=1):
        lines.extend(_format_thread_summary_lines(item, idx=idx, lang=lang, include_reason=False))
    return _clip("\n".join(lines).strip())


def format_important_mail_reply(user, *, limit: int = RECENT_DEFAULT_LIMIT, lang: str | None = None) -> str:
    lang = lang or "en"
    candidates = _collect_recent_threads(user, limit=RECENT_ALL_LIMIT)
    scored: list[tuple[int, str, MailThreadView]] = []
    for item in candidates:
        score, reason = _importance_score(item)
        if score > 0:
            scored.append((score, reason, item))
    scored.sort(key=lambda x: (x[0], int(x[2].thread.get("internal_date") or 0)), reverse=True)
    if not scored:
        return _msg(lang, "no_important")
    title = "⭐ গুরুত্বপূর্ণ মেইল:" if lang == "bn" else "⭐ Important emails:"
    lines = [title, ""]
    for idx, (_score, reason, item) in enumerate(scored[:limit], start=1):
        lines.extend(_format_thread_summary_lines(item, idx=idx, lang=lang, include_reason=True, reason=reason))
    return _clip("\n".join(lines).strip())


def format_reply_lookup(user, ref: str = "", *, lang: str | None = None) -> str:
    lang = lang or "en"
    ref = (ref or "").strip()
    found = _find_reply_meta(user, ref)
    if not found:
        if ref and (
            _has_any(ref.lower(), ("last", "gula", "সব", "sob", "shob", "show", "dekhao", "dekhte", "body", "ei "))
            or _looks_like_natural_ref(ref)
        ):
            return format_processed_activity_reply(user, action_filter="sent", lang=lang)
        return _msg(lang, "no_reply")
    account, message_id, meta = found
    reply_body = str(meta.get("reply_body") or "").strip()
    reply_subject = str(meta.get("reply_subject") or meta.get("subject") or "(No subject)").strip()
    action = str(meta.get("action") or "").strip().lower()
    when = _format_iso_dt(meta.get("processed_at"), _user_timezone(user))
    prefix = "✉️ আপনার রিপ্লাই" if lang == "bn" else "✉️ Your reply"
    if action == "draft":
        prefix = "📝 আপনার draft reply" if lang == "bn" else "📝 Your draft reply"
    where = _account_label(account) if account is not None else "Mailbox"
    lines = [f"{prefix} — {where}", f"Subject: {reply_subject}"]
    if when:
        lines.append(("সময়: " if lang == "bn" else "Time: ") + when)
    lines.append("")
    lines.append("> " + (reply_body or _msg(lang, "no_reply_body")).replace("\n", "\n> "))
    if message_id:
        lines.append("")
        lines.append(f"/reply {message_id}")
    return _clip("\n".join(lines).strip())


def format_account_list_reply(user, *, lang: str | None = None) -> str:
    lang = lang or "en"
    accounts = _all_accounts(user)
    if not accounts:
        return _msg(lang, "no_accounts")
    title = (
        f"🔗 Connected Accounts — {len(accounts)}টি পাওয়া গেছে:"
        if lang == "bn"
        else f"🔗 Connected Accounts — {len(accounts)} found:"
    )
    lines = [title, ""]
    for idx, acc in enumerate(accounts, start=1):
        info = _safe_account_info(acc)
        typ = _transport_label(info.get("transport"))
        status = _account_status_label(info, lang=lang)
        last = _last_activity_for_account(user, acc)
        line = f"{idx}. {info.get('email') or info.get('label') or 'Mailbox'} — {typ} {status}"
        if last:
            line += f" | {('Last activity' if lang != 'bn' else 'শেষ activity')}: {last}"
        lines.append(line)
        lines.append(f"   /account {acc.id}")
    return _clip("\n".join(lines).strip())


def format_account_detail_reply(user, ref: str, *, lang: str | None = None) -> str:
    lang = lang or "en"
    acc = _resolve_account_ref(user, ref)
    if acc is None:
        return _msg(lang, "account_not_found")
    info = _safe_account_info(acc)
    threads = _fetch_account_threads(user, acc, max_threads=3)
    recent = threads[1] if threads[1] is not None else []
    unread = sum(1 for item in recent if item.thread.get("unread"))
    lines = [
        f"📮 {info.get('email') or info.get('label') or 'Mailbox'}",
        f"Type: {_transport_label(info.get('transport'))}",
        f"Status: {_account_status_label(info, lang=lang)}",
        f"Unread shown: {unread}",
        f"Recent shown: {len(recent)}",
    ]
    last = _last_activity_for_account(user, acc)
    if last:
        lines.append(f"{'শেষ activity' if lang == 'bn' else 'Last activity'}: {last}")
    if threads[2]:
        lines.append(f"Note: {threads[2]}")
    if recent:
        lines.extend(["", "Recent:" if lang != "bn" else "সাম্প্রতিক:"])
        for idx, item in enumerate(recent, start=1):
            lines.extend(_format_thread_summary_lines(item, idx=idx, lang=lang, include_reason=False))
    return _clip("\n".join(lines).strip())


def format_thread_reply(user, ref: str, *, lang: str | None = None) -> str:
    lang = lang or "en"
    acc_ref, thread_id = _resolve_thread_ref(user, ref)
    messages_info = _fetch_thread_messages(user, thread_id, account_ref=acc_ref)
    if messages_info is None:
        return _msg(lang, "thread_not_found")
    account, email, messages, meta = messages_info
    subj = _short_subject(str((messages[-1] if messages else {}).get("subject") or ""))
    lines = [f"MailPilot thread — {email or _account_label(account)}", subj, ""]
    tz = _user_timezone(user)
    for m in messages:
        sender = _short_addr(str(m.get("from") or ""))
        when = _fmt_ts(m.get("internal_date"), tz)
        who = "You" if m.get("is_from_me") else sender
        body = (m.get("body_text") or m.get("snippet") or "").strip() or "(No content)"
        head = f"— {who}"
        if when:
            head += f" · {when}"
        lines.extend([head, body, ""])
    if meta and str(meta.get("action") or "").lower() in ("sent", "draft"):
        rb = str(meta.get("reply_body") or "").strip()
        if rb:
            title = "Stored MailPilot reply:" if lang != "bn" else "Stored MailPilot reply:"
            lines.extend([title, rb, ""])
    lines.append(f"/reply {account.id}:{thread_id}")
    return _clip("\n".join(lines).strip())


def format_mail_overview_reply(user, *, lang: str | None = None) -> str:
    lang = lang or "en"
    accounts = _all_accounts(user)
    if not accounts:
        return _msg(lang, "no_accounts")
    lines = ["📊 Mail overview" if lang != "bn" else "📊 মেইল overview", ""]
    total_recent = total_unread = 0
    for acc in accounts:
        _email, threads, err = _fetch_account_threads(user, acc, max_threads=20)
        recent = len(threads or [])
        unread = sum(1 for item in (threads or []) if item.thread.get("unread"))
        total_recent += recent
        total_unread += unread
        status = err or "ready"
        lines.append(f"{_account_label(acc)}: recent {recent}, unread {unread}, {status}")
    lines.extend(["", f"Total recent shown: {total_recent}", f"Total unread shown: {total_unread}"])
    return _clip("\n".join(lines).strip())


def format_processed_activity_reply(
    user,
    *,
    action_filter: str | None = None,
    lang: str | None = None,
    limit: int = RECENT_DEFAULT_LIMIT,
) -> str:
    lang = lang or "en"
    rows = _recent_processed_items(user, limit=max(RECENT_ALL_LIMIT, limit * 4))
    if action_filter:
        rows = [r for r in rows if str(r[2].get("action") or "").lower() == action_filter]
    if not rows:
        return _msg(lang, "no_activity")
    title = "Recent activity" if lang != "bn" else "সাম্প্রতিক activity"
    lines = [title, ""]
    for idx, (acc, message_id, meta) in enumerate(rows[:limit], start=1):
        action = str(meta.get("action") or "").strip() or "unknown"
        subject = _short_subject(str(meta.get("subject") or meta.get("reply_subject") or ""))
        sender = _short_addr(str(meta.get("from_email") or ""))
        when = _format_iso_dt(meta.get("processed_at"), _user_timezone(user))
        lines.append(f"{idx}. {action} — {subject}")
        if sender:
            lines.append(f"   From: {sender}")
        if when:
            lines.append(f"   {when}")
        if message_id:
            lines.append(f"   /reply {acc.id}:{message_id}")
        lines.append("")
    return _clip("\n".join(lines).strip())


def format_broad_mail_answer(user, question: str, *, lang: str | None = None) -> str:
    lang = lang or detect_language(question)
    t = (question or "").lower()
    if _has_any(t, ("pending", "queue", "processing")):
        return _format_queue_reply(user, lang=lang)
    if _has_any(t, ("draft", "drafted")):
        return format_processed_activity_reply(user, action_filter="draft", lang=lang)
    if _has_any(t, ("sent reply", "last reply", "reply gula", "reply dekhao", "উত্তর", "রিপ্লাই")):
        return format_processed_activity_reply(user, action_filter="sent", lang=lang)
    if _has_any(t, ("ignored", "rejected", "ignore", "ইগনোর")):
        return format_processed_activity_reply(user, action_filter="ignored", lang=lang)
    if _has_any(t, ("unread", "পড়া হয়নি", "পড়া হয়নি")):
        return _format_unread_by_account(user, lang=lang)
    sender = _extract_email(question)
    if sender:
        return _format_sender_recent(user, sender, lang=lang)
    return format_mail_overview_reply(user, lang=lang)


def _collect_recent_threads(user, *, limit: int) -> list[MailThreadView]:
    out: list[MailThreadView] = []
    for acc in _all_enabled_accounts(user):
        _email, threads, _err = _fetch_account_threads(user, acc, max_threads=limit)
        if threads:
            out.extend(threads)
    out.sort(key=lambda x: int(x.thread.get("internal_date") or 0), reverse=True)
    return out[:limit]


def _fetch_account_threads(user, acc, *, max_threads: int) -> tuple[str, list[MailThreadView] | None, str]:
    effective = runtime.get_effective_settings(user, account_id=acc.id)
    email = _mailbox_email(acc, effective)
    try:
        if acc.transport == TRANSPORT_GMAIL:
            if not gmail_oauth_ready(effective):
                return email, None, "Gmail not connected"
            if not gmail_oauth_matches_configured(effective)[0]:
                return email, None, "Gmail OAuth mismatch"
            raw_threads = GmailClient(settings=effective).list_inbox_thread_summaries(max_threads=max_threads)
        elif acc.transport == TRANSPORT_SMTP:
            if not imap_inbox_ready(effective):
                return email, None, "IMAP not configured"
            raw_threads = ImapMailbox(settings=effective).list_inbox_summaries(max_threads=max_threads)
        else:
            return email, None, "Unknown transport"
    except Exception as exc:
        return email, None, str(exc)[:120] or "Mailbox unavailable"

    st = runtime.state_store_for_user(user, account_id=acc.id)
    items: list[MailThreadView] = []
    for thread in raw_threads or []:
        meta = _meta_for_thread(st, thread)
        if meta:
            status = _status_from_meta(meta)
            if status:
                thread["message_status"] = status
        items.append(
            MailThreadView(
                account=acc,
                account_label=_account_label(acc),
                account_email=email,
                thread=thread,
                meta=meta,
            )
        )
    return email, items, ""


def _fetch_thread_messages(user, thread_id: str, *, account_ref: str = ""):
    tid = (thread_id or "").strip()
    if not tid:
        return None
    accounts = [_resolve_account_ref(user, account_ref)] if account_ref else _all_enabled_accounts(user)
    for acc in [a for a in accounts if a is not None]:
        effective = runtime.get_effective_settings(user, account_id=acc.id)
        email = _mailbox_email(acc, effective)
        try:
            if acc.transport == TRANSPORT_GMAIL and gmail_oauth_ready(effective):
                if not gmail_oauth_matches_configured(effective)[0]:
                    continue
                data = GmailClient(settings=effective).get_thread_for_ui(tid)
            elif acc.transport == TRANSPORT_SMTP and tid.isdigit() and imap_inbox_ready(effective):
                data = ImapMailbox(settings=effective).get_thread_for_ui(uid=int(tid))
            else:
                continue
        except Exception:
            continue
        messages = list(data.get("messages") or [])
        if not messages:
            continue
        messages.sort(key=lambda m: int(m.get("internal_date") or 0))
        st = runtime.state_store_for_user(user, account_id=acc.id)
        meta = _find_meta_for_ref_in_store(st, tid, require_reply=False)
        return acc, email, messages, meta
    return None


def _resolve_thread_ref(user, ref: str) -> tuple[str, str]:
    raw = (ref or "").strip()
    acc_ref, thread_id = _split_scoped_ref(raw)
    if acc_ref and thread_id:
        return acc_ref, thread_id
    if thread_id and not _looks_like_natural_ref(thread_id):
        return "", thread_id

    recent = _collect_recent_threads(user, limit=RECENT_ALL_LIMIT)
    if not recent:
        return "", thread_id

    ordinal = _extract_ordinal(raw)
    if ordinal is not None and 1 <= ordinal <= len(recent):
        item = recent[ordinal - 1]
        return str(item.account.id), str(item.thread.get("thread_id") or "")

    query = _normalize_lookup_text(raw)
    if query:
        best = _best_thread_match(recent, query)
        if best is not None:
            return str(best.account.id), str(best.thread.get("thread_id") or "")

    # Natural body/detail requests after a recent list should show the latest mail.
    if _looks_like_mail_detail_request(raw.lower()) or not raw or raw.lower() == "/thread":
        item = recent[0]
        return str(item.account.id), str(item.thread.get("thread_id") or "")
    return "", thread_id


def _meta_for_thread(st: StateStore, thread: dict[str, Any]) -> dict[str, Any] | None:
    mid = str(thread.get("message_id") or "").strip()
    tid = str(thread.get("thread_id") or "").strip()
    for key in (mid, f"imap:{tid}" if tid else "", f"gthread:{tid}" if tid else "", tid):
        if not key:
            continue
        meta = st.get_processed_meta(key)
        if meta:
            if not meta.get("reply_body") and meta.get("message_id"):
                richer = st.get_processed_meta(str(meta.get("message_id")))
                if richer:
                    return richer
            return meta
    return _find_meta_for_ref_in_store(st, tid or mid, require_reply=False)


def _find_meta_for_ref_in_store(st: StateStore, ref: str, *, require_reply: bool) -> dict[str, Any] | None:
    from core.models import ProcessedMeta

    needle = (ref or "").strip().lower()
    if not needle:
        return None
    rows = ProcessedMeta.objects.filter(tenant_id=st.tenant_id).order_by("-id").only("message_id", "meta_json")[:200]
    for row in rows:
        meta = row.meta_json if isinstance(row.meta_json, dict) else {}
        if require_reply and not str(meta.get("reply_body") or "").strip():
            continue
        hay = " ".join(
            [
                str(row.message_id or ""),
                str(meta.get("message_id") or ""),
                str(meta.get("thread_id") or ""),
                str(meta.get("canonical_id") or ""),
                str(meta.get("subject") or ""),
                str(meta.get("reply_subject") or ""),
                str(meta.get("from_email") or ""),
            ]
        ).lower()
        if needle in hay:
            return meta
    return None


def _find_reply_meta(user, ref: str = ""):
    acc_ref, item_ref = _split_scoped_ref(ref)
    accounts = [_resolve_account_ref(user, acc_ref)] if acc_ref else _all_enabled_accounts(user)
    for acc in [a for a in accounts if a is not None]:
        st = runtime.state_store_for_user(user, account_id=acc.id)
        if item_ref:
            direct = st.get_processed_meta(item_ref)
            if direct and str(direct.get("reply_body") or "").strip():
                return acc, item_ref, direct
            meta = _find_meta_for_ref_in_store(st, item_ref, require_reply=True)
            if meta:
                return acc, item_ref, meta
            meta = _find_reply_meta_by_tokens(st, item_ref)
            if meta:
                return acc, item_ref, meta
        else:
            for row_acc, message_id, meta in _recent_processed_items(user, limit=40):
                if row_acc.id == acc.id and str(meta.get("reply_body") or "").strip():
                    if str(meta.get("action") or "").lower() in ("sent", "draft"):
                        return row_acc, message_id, meta
    return None


def _find_reply_meta_by_tokens(st: StateStore, ref: str) -> dict[str, Any] | None:
    from core.models import ProcessedMeta

    query = _normalize_lookup_text(ref)
    tokens = [tok for tok in re.split(r"\s+", query.lower()) if len(tok) >= 3]
    if not tokens:
        return None
    best: tuple[int, dict[str, Any]] | None = None
    rows = ProcessedMeta.objects.filter(tenant_id=st.tenant_id).order_by("-id").only("meta_json")[:200]
    for row in rows:
        meta = row.meta_json if isinstance(row.meta_json, dict) else {}
        if str(meta.get("action") or "").lower() not in ("sent", "draft"):
            continue
        if not str(meta.get("reply_body") or "").strip():
            continue
        hay = " ".join(
            [
                str(meta.get("subject") or ""),
                str(meta.get("reply_subject") or ""),
                str(meta.get("from_email") or ""),
                str(meta.get("thread_id") or ""),
            ]
        ).lower()
        score = sum(1 for tok in tokens if tok in hay)
        if score and (best is None or score > best[0]):
            best = (score, meta)
    return best[1] if best else None


def _recent_processed_items(user, *, limit: int) -> list[tuple[Any, str, dict[str, Any]]]:
    from core.models import ProcessedMeta

    out: list[tuple[Any, str, dict[str, Any]]] = []
    for acc in _all_enabled_accounts(user):
        st = runtime.state_store_for_user(user, account_id=acc.id)
        rows = ProcessedMeta.objects.filter(tenant_id=st.tenant_id).order_by("-id").only("message_id", "meta_json")[:limit]
        for row in rows:
            meta = row.meta_json if isinstance(row.meta_json, dict) else {}
            action = str(meta.get("action") or "").lower()
            if action in ("sent", "draft", "ignored", "error"):
                out.append((acc, str(row.message_id or ""), meta))
    out.sort(key=lambda item: str(item[2].get("processed_at") or ""), reverse=True)
    return out[:limit]


def _format_queue_reply(user, *, lang: str) -> str:
    lines = ["Queue / pending" if lang != "bn" else "Queue / pending", ""]
    found = False
    for acc in _all_enabled_accounts(user):
        st = runtime.state_store_for_user(user, account_id=acc.id)
        items = st.list_queue_items(limit=10)
        pending = [it for it in items if str(it.get("status") or "").lower() in ("pending", "processing")]
        if not pending:
            continue
        found = True
        lines.append(_account_label(acc))
        for it in pending[:5]:
            lines.append(f"- {it.get('subject') or it.get('message_id') or 'mail'} ({it.get('status')})")
    if not found:
        return _msg(lang, "no_pending")
    return _clip("\n".join(lines).strip())


def _format_unread_by_account(user, *, lang: str) -> str:
    lines = ["Unread by account" if lang != "bn" else "Unread by account", ""]
    found = False
    for acc in _all_enabled_accounts(user):
        _email, threads, err = _fetch_account_threads(user, acc, max_threads=RECENT_ALL_LIMIT)
        if err:
            lines.append(f"{_account_label(acc)}: {err}")
            continue
        unread = sum(1 for item in (threads or []) if item.thread.get("unread"))
        found = found or unread > 0
        lines.append(f"{_account_label(acc)}: {unread} unread")
    if not found:
        lines.append("No unread messages in the recent window.")
    return _clip("\n".join(lines).strip())


def _format_sender_recent(user, sender: str, *, lang: str) -> str:
    items = [item for item in _collect_recent_threads(user, limit=RECENT_ALL_LIMIT) if sender.lower() in str(item.thread.get("from") or "").lower()]
    if not items:
        return _msg(lang, "no_recent")
    lines = [f"Recent mail from {sender}:", ""]
    for idx, item in enumerate(items[:RECENT_DEFAULT_LIMIT], start=1):
        lines.extend(_format_thread_summary_lines(item, idx=idx, lang=lang, include_reason=False))
    return _clip("\n".join(lines).strip())


def _format_thread_summary_lines(
    item: MailThreadView,
    *,
    idx: int,
    lang: str,
    include_reason: bool,
    reason: str = "",
) -> list[str]:
    t = item.thread
    sender = str(t.get("from") or "").strip() or "unknown"
    subject = _short_subject(str(t.get("subject") or ""))
    preview = _preview(str(t.get("snippet") or ""))
    when = _fmt_ts(t.get("internal_date"), _user_timezone(getattr(item.account, "user", None)))
    ref = f"{item.account.id}:{t.get('thread_id') or ''}".strip()
    lines = [
        f"{idx}. 📌 Subject: {subject}",
        f"   👤 From: {sender}",
    ]
    if when:
        lines.append(f"   📅 Date: {when}")
    lines.append(f"   📝 Preview: {preview}")
    lines.append(f"   📮 Account: {item.account_email or item.account_label}")
    status = _status_from_meta(item.meta) if item.meta else _status_from_thread(t)
    if status:
        lines.append(f"   Status: {status}")
    if include_reason and reason:
        lines.append(f"   🏷️ Reason: {reason}")
    lines.append(f"   /thread {ref} · /reply {ref}")
    lines.append("")
    return lines


def _importance_score(item: MailThreadView) -> tuple[int, str]:
    t = item.thread
    reasons: list[str] = []
    score = 0
    if t.get("starred"):
        score += 100
        reasons.append("Starred")
    if t.get("important"):
        score += 90
        reasons.append("Gmail Important")
    meta = item.meta or {}
    action = str(meta.get("action") or "").lower()
    if action in ("sent", "draft"):
        score += 70
        reasons.append(f"MailPilot {action}")
    try:
        conf = float(meta.get("confidence") or 0)
    except Exception:
        conf = 0.0
    if conf >= 0.75:
        score += 60
        reasons.append(f"High confidence {conf:.2f}")
    if t.get("unread"):
        score += 25
        reasons.append("Unread")
    return score, " + ".join(reasons)


def _safe_account_info(acc) -> dict[str, Any]:
    raw = account_to_dict(acc, include_kb_count=False)
    return {
        "id": raw.get("id"),
        "slot": raw.get("slot"),
        "transport": raw.get("transport"),
        "label": raw.get("label"),
        "is_enabled": raw.get("is_enabled"),
        "email": raw.get("email") or raw.get("profile_email") or raw.get("label"),
        "gmail_connected": raw.get("gmail_connected"),
        "oauth_email_mismatch": raw.get("oauth_email_mismatch"),
        "imap_ready": raw.get("imap_ready"),
        "inbox_ready": raw.get("inbox_ready"),
        "smtp_last_test_ok": raw.get("smtp_last_test_ok"),
    }


def _all_accounts(user) -> list[Any]:
    ensure_legacy_migrated(user)
    return list(list_accounts_for_user(user))


def _all_enabled_accounts(user) -> list[Any]:
    ensure_legacy_migrated(user)
    return list(enabled_accounts_for_active_mode(user))


def _resolve_account_ref(user, ref: str):
    needle = (ref or "").strip().lower()
    if not needle:
        return None
    accounts = _all_accounts(user)
    if needle.isdigit():
        n = int(needle)
        for acc in accounts:
            if int(acc.id) == n:
                return acc
        for acc in accounts:
            if int(acc.slot) == n:
                return acc
    for acc in accounts:
        info = _safe_account_info(acc)
        values = [str(info.get("email") or ""), str(info.get("label") or ""), str(acc.id), str(acc.slot)]
        if any(needle in v.lower() for v in values if v):
            return acc
    return None


def _split_scoped_ref(ref: str) -> tuple[str, str]:
    raw = (ref or "").strip()
    if ":" not in raw:
        return "", raw
    head, tail = raw.split(":", 1)
    if head.strip().isdigit():
        return head.strip(), tail.strip()
    return "", raw


def _mailbox_email(acc, effective) -> str:
    cfg = dict(acc.config_json or {})
    if acc.transport == TRANSPORT_GMAIL:
        return str(effective.GMAIL_ADDRESS or cfg.get("GMAIL_ADDRESS") or acc.label or "Gmail").strip()
    return str(effective.outbound_from_email() or cfg.get("SMTP_FROM_EMAIL") or cfg.get("SMTP_USERNAME") or acc.label or "SMTP").strip()


def _account_label(acc) -> str:
    info = _safe_account_info(acc)
    return str(info.get("email") or info.get("label") or f"Account {acc.id}").strip()


def _last_activity_for_account(user, acc) -> str:
    st = runtime.state_store_for_user(user, account_id=acc.id)
    latest = ""
    for item in st.list_queue_items(limit=1):
        latest = str(item.get("updated_at") or "")
    if not latest:
        rows = _recent_processed_items(user, limit=40)
        for row_acc, _message_id, meta in rows:
            if row_acc.id == acc.id:
                latest = str(meta.get("processed_at") or "")
                break
    return _format_iso_dt(latest, _user_timezone(user))


def _status_from_meta(meta: dict[str, Any] | None) -> str:
    if not meta:
        return ""
    action = str(meta.get("action") or "").lower()
    if action == "sent":
        return "sent"
    if action == "draft":
        return "draft"
    if action == "ignored":
        return "ignored"
    if action == "error":
        return "error"
    return ""


def _status_from_thread(thread: dict[str, Any]) -> str:
    tags = []
    if thread.get("unread"):
        tags.append("unread")
    if thread.get("starred"):
        tags.append("starred")
    if thread.get("important"):
        tags.append("important")
    return ", ".join(tags)


def _account_status_label(info: dict[str, Any], *, lang: str) -> str:
    if not info.get("is_enabled"):
        return "⚠️ Inactive"
    if info.get("oauth_email_mismatch"):
        return "⚠️ OAuth mismatch"
    if info.get("inbox_ready"):
        return "✅ Active"
    if info.get("transport") == TRANSPORT_SMTP and info.get("smtp_last_test_ok"):
        return "✅ SMTP ready"
    return "⚠️ Not ready"


def _transport_label(transport: Any) -> str:
    if transport == TRANSPORT_GMAIL:
        return "Gmail OAuth"
    if transport == TRANSPORT_SMTP:
        return "SMTP"
    return str(transport or "Email")


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
        return datetime.fromtimestamp(n / 1000, tz=timezone.utc).astimezone(tz).strftime("%a, %Y-%m-%d %H:%M")
    except Exception:
        return ""


def _format_iso_dt(raw: Any, tz: ZoneInfo) -> str:
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(tz).strftime("%a, %Y-%m-%d %H:%M")
    except Exception:
        return ""


def _short_addr(from_header: str) -> str:
    name, addr = parseaddr(from_header or "")
    if name and addr:
        return f"{name} <{addr}>"
    return addr or (from_header or "unknown")[:100]


def _short_subject(subject: str) -> str:
    s = (subject or "").strip() or "(No subject)"
    return s if len(s) <= 100 else s[:97] + "..."


def _preview(text: str) -> str:
    s = re.sub(r"\s+", " ", (text or "").strip())
    if not s:
        return "(Preview not available)"
    return s if len(s) <= 220 else s[:217].rstrip() + "..."


def _extract_email(text: str) -> str:
    m = re.search(r"[\w.\-+]+@[\w.\-]+\.\w+", text or "")
    return m.group(0) if m else ""


def _limit_from_query(text: str) -> int:
    t = (text or "").lower()
    if _has_any(t, ("just last", "only last", "last mail send", "last email send", "shudhu last", "sudhu last")):
        return 1
    if _has_any(t, ("show all", "all", "সব", "sob", "shob")):
        return RECENT_ALL_LIMIT
    return RECENT_DEFAULT_LIMIT


def _looks_like_mail_detail_request(text: str) -> bool:
    t = (text or "").lower().strip()
    if not t:
        return False
    return _has_any(
        t,
        (
            "detail",
            "details",
            "body",
            "full mail",
            "full email",
            "ki likheche",
            "ki likhese",
            "ki lekha",
            "mail e",
            "mailer body",
            "mail er body",
            "show 1st",
            "1st mail",
            "first mail",
            "serial 1",
            "subject hosche",
            "subject hocche",
            "দেখতে চাই",
            "বডি",
            "কি লিখেছে",
        ),
    )


def _looks_like_natural_ref(text: str) -> bool:
    t = (text or "").lower()
    return _looks_like_mail_detail_request(t) or bool(re.search(r"\b(first|second|third|serial|subject|mail|body)\b", t))


def _extract_ordinal(text: str) -> int | None:
    t = (text or "").lower()
    m = re.search(r"\b(\d+)(?:st|nd|rd|th)?\b", t)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    word_map = {
        "first": 1,
        "second": 2,
        "third": 3,
        "fourth": 4,
        "fifth": 5,
        "prothom": 1,
        "ditiyo": 2,
        "tritiyo": 3,
        "প্রথম": 1,
        "দ্বিতীয়": 2,
        "দ্বিতীয়": 2,
        "তৃতীয়": 3,
        "তৃতীয়": 3,
    }
    for word, value in word_map.items():
        if word in t:
            return value
    return None


def _normalize_lookup_text(text: str) -> str:
    q = (text or "").lower()
    q = re.sub(r"/thread|/reply", " ", q)
    q = re.sub(r"\b(subject|hosche|hocche|details?|detail|body|mail|email|er|ta|daw|dao|show|please|serial|number|no)\b", " ", q)
    q = re.sub(r"\b\d+(?:st|nd|rd|th)?\b", " ", q)
    q = re.sub(r"[^\w@.\-\u0980-\u09ff]+", " ", q)
    return re.sub(r"\s+", " ", q).strip()


def _best_thread_match(items: list[MailThreadView], query: str) -> MailThreadView | None:
    q_tokens = [tok for tok in re.split(r"\s+", query.lower()) if len(tok) >= 3]
    if not q_tokens:
        return None
    best: tuple[int, MailThreadView] | None = None
    for item in items:
        hay = " ".join(
            [
                str(item.thread.get("subject") or ""),
                str(item.thread.get("from") or ""),
                str(item.thread.get("snippet") or ""),
                str(item.account_email or ""),
                str(item.account_label or ""),
            ]
        ).lower()
        score = sum(1 for tok in q_tokens if tok in hay)
        if score and (best is None or score > best[0]):
            best = (score, item)
    return best[1] if best else None


def _asks_for_secret(t: str) -> bool:
    return _has_any(
        t,
        (
            "password",
            "pass ",
            "token",
            "api key",
            "apikey",
            "oauth",
            "client secret",
            "credential",
            "credentials",
            "secret",
            "পাসওয়ার্ড",
            "পাসওয়ার্ড",
            "টোকেন",
        ),
    )


def _is_mail_scope(t: str) -> bool:
    return _has_any(
        t,
        (
            "mail",
            "email",
            "inbox",
            "gmail",
            "smtp",
            "imap",
            "reply",
            "draft",
            "sent",
            "account",
            "unread",
            "sender",
            "মেইল",
            "ইমেইল",
            "রিপ্লাই",
            "উত্তর",
            "ইনবক্স",
        ),
    )


def _has_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(n in text for n in needles)


def _format_help(lang: str) -> str:
    if lang == "bn":
        return _clip(
            "MailPilot assistant ready.\n"
            "আপনি জিজ্ঞেস করতে পারেন:\n"
            "- recent mail ki asche\n"
            "- important mail dekhao\n"
            "- Invoice mail er reply ki diyecho\n"
            "- connected emails dekhao\n"
            "- /thread <id> বা /reply <id>"
        )
    return _clip(
        "MailPilot assistant is ready.\n"
        "Try:\n"
        "- recent mail\n"
        "- important mail\n"
        "- show reply for Invoice\n"
        "- connected emails\n"
        "- /thread <id> or /reply <id>"
    )


def _msg(lang: str, key: str) -> str:
    bn = {
        "empty": "দয়া করে একটি email-management প্রশ্ন পাঠান।",
        "secret_refusal": "নিরাপত্তার কারণে credentials শেয়ার করা সম্ভব নয়।",
        "scope_refusal": "আমি শুধুমাত্র email management এর জন্য তৈরি। অন্য বিষয়ে সাহায্য করতে পারব না।",
        "unavailable": "এই তথ্য এই মুহূর্তে পাওয়া যাচ্ছে না। অনুগ্রহ করে আবার চেষ্টা করুন।",
        "no_recent": "সাম্প্রতিক কোনো মেইল পাওয়া যাচ্ছে না।",
        "no_important": "এই মুহূর্তে কোনো important mail পাওয়া যাচ্ছে না।",
        "no_reply": "এই মেইলে এখনো কোনো রিপ্লাই পাঠানো হয়নি।",
        "no_reply_body": "Reply body পাওয়া যায়নি।",
        "no_accounts": "কোনো connected email account পাওয়া যায়নি। Setup থেকে Gmail বা SMTP connect করুন।",
        "account_not_found": "এই account খুঁজে পাওয়া যায়নি। /accounts দিয়ে account list দেখুন।",
        "thread_not_found": "এই thread খুঁজে পাওয়া যায়নি। /inbox দিয়ে recent mail list দেখুন।",
        "no_activity": "সাম্প্রতিক activity পাওয়া যাচ্ছে না।",
        "no_pending": "এই মুহূর্তে কোনো pending mail পাওয়া যাচ্ছে না।",
    }
    en = {
        "empty": "Please send an email-management question.",
        "secret_refusal": "For security, I cannot share credentials.",
        "scope_refusal": "I am built only for email management. I cannot help with other topics.",
        "unavailable": "This information is unavailable right now. Please try again.",
        "no_recent": "No recent email is available right now.",
        "no_important": "No important email is available right now.",
        "no_reply": "No reply has been sent or drafted for that email yet.",
        "no_reply_body": "Reply body is unavailable.",
        "no_accounts": "No connected email account was found. Connect Gmail or SMTP in Setup.",
        "account_not_found": "I could not find that account. Use /accounts to see the list.",
        "thread_not_found": "I could not find that thread. Use /inbox to see recent mail.",
        "no_activity": "No recent activity is available.",
        "no_pending": "No pending mail is available right now.",
    }
    return (bn if lang == "bn" else en).get(key, en["unavailable"])


def _clip(text: str) -> str:
    body = (text or "").strip()
    if len(body) <= MAX_CHAT_CHARS:
        return body
    return body[: MAX_CHAT_CHARS - 40].rstrip() + "\n\n... (truncated)"


def _audit_chat_query(
    user,
    *,
    channel: str,
    intent: str,
    ok: bool,
    account_id: int | None = None,
    error: str = "",
) -> None:
    try:
        from core.models import AuditLog

        detail = f"channel={channel} intent={intent} ok={str(bool(ok)).lower()}"
        if account_id is not None:
            detail += f" account_id={account_id}"
        if error:
            detail += f" error={error[:120]}"
        AuditLog.objects.create(user=user, action="mail_chat_query", detail=detail[:512])
    except Exception:
        pass
