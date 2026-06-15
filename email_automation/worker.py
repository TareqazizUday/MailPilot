from __future__ import annotations

import email
import imaplib
import re
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.state_store import StateStore
from email_automation.kb.embedder import embed_texts
from email_automation.kb.store import VectorStore, is_vector_db_configured
from email_automation.llm import decide_and_write_reply
from email_automation.settings import Settings
from email_automation.smtp_client import SMTPClient


@dataclass(frozen=True)
class PollResult:
    scanned: int
    relevant: int
    sent: int
    drafts: int
    ignored: int
    queued: int


def _effective_relevance_threshold(settings: Settings) -> float:
    """Match UI: 0 means 'accept any confidence'; do not use `or 0.35` because float(0) is falsy."""
    raw = getattr(settings, "RELEVANCE_THRESHOLD", None)
    if raw is None:
        return 0.35
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.35


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _extract_from_email(from_header: str) -> str:
    h = (from_header or "").strip()
    m = re.search(r"<([^>]+)>", h)
    return (m.group(1) if m else h).strip()


def _hdr_message_id_key(email_msg: Any) -> Optional[str]:
    """Stable dedupe key from RFC Message-ID (IMAP/Gmail)."""
    raw = str(email_msg.get("Message-ID") or email_msg.get("Message-Id") or "").strip()
    if not raw:
        return None
    return "hdr:" + raw.strip("<>").lower()


def _imap_dedupe_id(uid: str, email_msg: Any) -> str:
    hdr = _hdr_message_id_key(email_msg)
    return hdr if hdr else f"imap:{uid}"


def _dedupe_aliases(*, primary_id: str, uid: str | None = None, email_msg: Any | None = None) -> list[str]:
    aliases: list[str] = []
    if uid:
        imap_id = f"imap:{uid}"
        if imap_id != primary_id:
            aliases.append(imap_id)
    if email_msg is not None:
        hdr = _hdr_message_id_key(email_msg)
        if hdr and hdr != primary_id:
            aliases.append(hdr)
    return aliases


def _try_begin_processing(
    state_store: StateStore,
    dedupe_id: str,
    *,
    from_email: str = "",
    subject: str = "",
    transport_id: str = "",
) -> bool:
    extra: dict[str, Any] = {}
    if from_email:
        extra["from_email"] = from_email
    if subject:
        extra["subject"] = subject
    if transport_id:
        extra["transport_id"] = transport_id
    return state_store.try_claim_message(dedupe_id, extra=extra or None)


def _build_kb_context(*, settings: Settings, tenant_id: str, query_text: str, k: int = 6) -> str:
    if not query_text.strip():
        return ""
    if not is_vector_db_configured(settings):
        return ""
    vs = VectorStore(settings=settings, tenant_id=str(tenant_id or ""))
    emb = embed_texts(settings=settings, texts=[query_text])
    if not emb or not emb[0]:
        return ""
    rows = vs.search_by_embedding(emb[0], limit=k)
    if not rows:
        return ""
    parts: list[str] = []
    for r in rows:
        src = _clean_text(str(r.get("source") or ""))
        title = _clean_text(str(r.get("title") or ""))
        url = _clean_text(str(r.get("url") or ""))
        txt = (r.get("chunk_text") or "").strip()
        if not txt:
            continue
        head = " | ".join([x for x in [title, url, src] if x])
        parts.append((f"[{head}]\n{txt}\n").strip())
    return "\n\n".join(parts[:k]).strip()


def _thread_already_handled(msgs: List[Dict[str, Any]], state_store: StateStore) -> bool:
    """True if any message in this Gmail thread was already auto-sent or drafted."""
    for m in msgs or []:
        mid = str(m.get("id") or "")
        if not mid:
            continue
        meta = state_store.get_processed_meta(mid)
        if meta and str(meta.get("action") or "") in ("sent", "draft"):
            return True
    return False


def _gmail_latest_inbound_unprocessed(msgs: List[Dict[str, Any]], state_store: StateStore) -> Optional[Dict[str, Any]]:
    """Newest peer message in the thread not yet processed (skips our own messages, e.g. after we replied)."""
    for m in reversed(msgs or []):
        mid = str(m.get("id") or "")
        if not mid:
            continue
        if state_store.get_processed_meta(mid) is not None:
            continue
        if bool(m.get("is_from_me")):
            continue
        return m
    return None


def _mark_ignored_message(
    state_store: StateStore,
    *,
    message_id: str,
    from_email: str,
    subject: str,
    reason: str,
) -> None:
    processed_at = _now_iso()
    state_store.mark_processed(
        message_id,
        {
            "action": "ignored",
            "reason": reason,
            "from_email": from_email,
            "subject": subject,
            "processed_at": processed_at,
        },
    )
    state_store.upsert_queue_item(
        message_id,
        status="reject",
        details={
            "id": message_id,
            "from_email": from_email,
            "subject": subject,
            "reason": reason,
        },
    )


def _mark_keyword_rejected(
    state_store: StateStore,
    *,
    message_id: str,
    from_email: str,
    subject: str,
) -> None:
    _mark_ignored_message(
        state_store,
        message_id=message_id,
        from_email=from_email,
        subject=subject,
        reason="keyword_prefilter",
    )


def _is_skipped_sender(from_email: str, skip_from_emails: frozenset[str] | None) -> bool:
    if not skip_from_emails:
        return False
    return (from_email or "").strip().lower() in skip_from_emails


def _should_consider_email(settings: Settings, *, from_email: str, subject: str, body: str) -> bool:
    # Cheap keyword prefilter to avoid expensive LLM calls on obvious noise.
    toks = [t.lower() for t in (settings.SERVICE_KEYWORDS or []) if str(t).strip()]
    if not toks:
        return True
    # Setup: add a single * or __all__ keyword to consider every inbound message (still LLM-gated).
    if "*" in toks or "__all__" in toks:
        return True
    hay = (" ".join([from_email or "", subject or "", body or ""])).lower()
    return any(t in hay for t in toks)


def _maybe_telegram_notify(
    state_store: StateStore,
    event: str,
    *,
    subject: str = "",
    from_email: str = "",
    error: str = "",
    reply_subject: str = "",
) -> None:
    try:
        from core.telegram_notify import notify_mail_event

        notify_mail_event(
            state_store.tenant_id,
            event,
            subject=subject,
            from_email=from_email,
            error=error,
            reply_subject=reply_subject,
        )
    except Exception:
        pass
    try:
        from core.whatsapp_notify import notify_mail_event as whatsapp_notify_mail_event

        whatsapp_notify_mail_event(
            state_store.tenant_id,
            event,
            subject=subject,
            from_email=from_email,
            error=error,
            reply_subject=reply_subject,
        )
    except Exception:
        pass


def _send_reply_via_transport(
    *,
    settings: Settings,
    gmail_client: Any | None,
    to_email: str,
    subject: str,
    body_text: str,
    thread_id: str | None = None,
) -> str:
    if settings.SEND_TRANSPORT == "gmail_api" and gmail_client is not None:
        return str(
            gmail_client.send_reply(
                to_email=to_email,
                subject=subject,
                body_text=body_text,
                thread_id=thread_id,
            )
            or ""
        )
    # SMTP transport
    SMTPClient(settings=settings).send_text_email(to_email=to_email, subject=subject, body_text=body_text)
    return ""


def poll_once(
    *,
    settings: Settings,
    state_store: StateStore,
    gmail_client: Any,
    mail_account: Any | None = None,
    skip_from_emails: frozenset[str] | None = None,
) -> PollResult:
    scanned = relevant = sent = drafts = ignored = queued = 0

    # Gmail: recent inbox threads; per thread, newest *inbound* message not yet handled (not only msgs[-1]).
    threads = gmail_client.list_inbox_thread_summaries(max_threads=40)
    for t in threads:
        tid = str(t.get("thread_id") or "")
        if not tid:
            continue
        mid = str(t.get("message_id") or "")
        if mid and state_store.get_processed_meta(mid) is not None:
            continue
        det = gmail_client.get_thread_for_ui(tid)
        msgs = det.get("messages") or []
        if not msgs:
            continue
        last = _gmail_latest_inbound_unprocessed(msgs, state_store)
        if last is None:
            continue
        mid = str(last.get("id") or "")
        if not mid:
            continue
        scanned += 1

        from_h = str(last.get("from") or "")
        from_email = _extract_from_email(from_h)
        subject = _clean_text(str(last.get("subject") or ""))
        body = str(last.get("body_text") or last.get("snippet") or "").strip()
        if _is_skipped_sender(from_email, skip_from_emails):
            _mark_ignored_message(
                state_store,
                message_id=mid,
                from_email=from_email,
                subject=subject,
                reason="own_mailbox_sender",
            )
            ignored += 1
            continue
        if state_store.has_replied_to_thread(tid) or _thread_already_handled(msgs, state_store):
            _mark_ignored_message(
                state_store,
                message_id=mid,
                from_email=from_email,
                subject=subject,
                reason="thread_already_replied",
            )
            ignored += 1
            continue
        if not _should_consider_email(settings, from_email=from_email, subject=subject, body=body):
            _mark_keyword_rejected(state_store, message_id=mid, from_email=from_email, subject=subject)
            ignored += 1
            continue

        if not _try_begin_processing(
            state_store, mid, from_email=from_email, subject=subject, transport_id=mid
        ):
            continue

        query = _clean_text(subject + "\n\n" + body)[:6000]
        kb_ctx = _build_kb_context(settings=settings, tenant_id=state_store.tenant_id, query_text=query, k=6)
        decision = decide_and_write_reply(
            settings=settings,
            mail_from=from_h,
            mail_subject=subject,
            mail_body=query,
            kb_context=kb_ctx,
            service_keywords=settings.SERVICE_KEYWORDS or [],
        )
        conf = float(decision.get("confidence") or 0.0)
        is_rel = bool(decision.get("is_relevant"))
        thr = _effective_relevance_threshold(settings)
        if is_rel and conf >= thr:
            relevant += 1
            reply_subject = _clean_text(decision.get("reply_subject") or ("Re: " + subject))
            reply_body = str(decision.get("reply_body") or "").strip()
            if (settings.REPLY_MODE or "").lower() == "send":
                reservation = None
                if mail_account is not None:
                    from core.billing import reserve_auto_send

                    reservation = reserve_auto_send(mail_account.user, mail_account, mid)
                    if not reservation.allowed:
                        drafts += 1
                        state_store.upsert_queue_item(
                            mid,
                            status="quota_blocked",
                            details={
                                "id": mid,
                                "from_email": from_email,
                                "subject": subject,
                                "reason": reservation.reason or "quota_blocked",
                                "reply_subject": reply_subject,
                                "upgrade_required": True,
                            },
                        )
                        state_store.mark_processed(
                            mid,
                            {
                                "action": "draft",
                                "confidence": conf,
                                "reply_subject": reply_subject,
                                "reply_body": reply_body,
                                "from_email": from_email,
                                "subject": subject,
                                "reason": reservation.reason or "quota_blocked",
                                "thread_id": tid,
                                "processed_at": _now_iso(),
                                "quota_blocked": True,
                            },
                        )
                        _maybe_telegram_notify(
                            state_store,
                            "draft",
                            subject=subject,
                            from_email=from_email,
                            reply_subject=reply_subject,
                        )
                        continue
                try:
                    _send_reply_via_transport(
                        settings=settings,
                        gmail_client=gmail_client,
                        to_email=from_email,
                        subject=reply_subject,
                        body_text=reply_body,
                        thread_id=tid,
                    )
                    if reservation is not None:
                        from core.billing import commit_auto_send

                        commit_auto_send(reservation)
                except Exception as e:
                    if reservation is not None:
                        from core.billing import fail_auto_send

                        fail_auto_send(reservation, str(e))
                    raise
                sent += 1
                state_store.upsert_queue_item(
                    mid,
                    status="completed",
                    details={
                        "id": mid,
                        "from_email": from_email,
                        "subject": subject,
                        "reason": "auto_reply",
                    },
                )
                state_store.mark_processed(
                    mid,
                    {
                        "action": "sent",
                        "confidence": conf,
                        "reply_subject": reply_subject,
                        "reply_body": reply_body,
                        "from_email": from_email,
                        "subject": subject,
                        "reason": "auto_reply",
                        "thread_id": tid,
                        "processed_at": _now_iso(),
                        "usage_event_id": getattr(reservation, "event_id", None),
                    },
                )
                state_store.mark_thread_replied(
                    tid,
                    meta={
                        "action": "sent",
                        "message_id": mid,
                        "from_email": from_email,
                        "subject": subject,
                        "processed_at": _now_iso(),
                    },
                )
                _maybe_telegram_notify(
                    state_store,
                    "sent",
                    subject=subject,
                    from_email=from_email,
                    reply_subject=reply_subject,
                )
            else:
                drafts += 1
                state_store.mark_processed(
                    mid,
                    {
                        "action": "draft",
                        "confidence": conf,
                        "reply_subject": reply_subject,
                        "reply_body": reply_body,
                        "thread_id": tid,
                        "processed_at": _now_iso(),
                    },
                )
                state_store.mark_thread_replied(
                    tid,
                    meta={
                        "action": "draft",
                        "message_id": mid,
                        "from_email": from_email,
                        "subject": subject,
                        "processed_at": _now_iso(),
                    },
                )
                _maybe_telegram_notify(
                    state_store,
                    "draft",
                    subject=subject,
                    from_email=from_email,
                    reply_subject=reply_subject,
                )
        else:
            ignored += 1
            state_store.mark_processed(
                mid,
                {
                    "action": "ignored",
                    "confidence": conf,
                    "reason": decision.get("reason") or "not_relevant",
                    "processed_at": _now_iso(),
                },
            )

    return PollResult(scanned=scanned, relevant=relevant, sent=sent, drafts=drafts, ignored=ignored, queued=queued)


def poll_once_imap(
    *,
    settings: Settings,
    state_store: StateStore,
    fast: bool = False,
    mail_account: Any | None = None,
    skip_from_emails: frozenset[str] | None = None,
) -> PollResult:
    scanned = relevant = sent = drafts = ignored = queued = 0

    host = (settings.IMAP_HOST or "").strip()
    port = int(getattr(settings, "IMAP_PORT", 993) or 993)
    user = (settings.IMAP_USERNAME or "").strip()
    pw = settings.IMAP_PASSWORD.get_secret_value() if settings.IMAP_PASSWORD else ""
    if not host or not user or not pw:
        return PollResult(scanned=0, relevant=0, sent=0, drafts=0, ignored=0, queued=0)

    mailbox = (settings.IMAP_MAILBOX or "INBOX").strip() or "INBOX"
    use_ssl = port == 993
    if use_ssl:
        conn: imaplib.IMAP4 = imaplib.IMAP4_SSL(host, port)
    else:
        conn = imaplib.IMAP4(host, port)
        try:
            conn.starttls()
        except Exception:
            pass
    try:
        print(
            f"[mailpoll][imap] connect host={host} port={port} user={user} mailbox={mailbox} "
            f"reply_mode={settings.REPLY_MODE} threshold={getattr(settings,'RELEVANCE_THRESHOLD',None)}"
        )
        typ, _ = conn.login(user, pw)
        if typ != "OK":
            print("[mailpoll][imap] login failed")
            return PollResult(scanned=0, relevant=0, sent=0, drafts=0, ignored=0, queued=0)

        typ, _ = conn.select(mailbox, readonly=False)
        if typ != "OK":
            print("[mailpoll][imap] select failed")
            return PollResult(scanned=0, relevant=0, sent=0, drafts=0, ignored=0, queued=0)

        # Fast path (IMAP IDLE): only UNSEEN — quick reply for new mail.
        # Full path (interval poll): ALL, newest first — catches mail opened in UI before worker runs.
        if fast:
            typ, data = conn.uid("search", None, "UNSEEN")
            search_label = "UNSEEN"
            cap = 10
        else:
            typ, data = conn.uid("search", None, "ALL")
            search_label = "ALL"
            cap = 20
        if typ != "OK" or not data or not data[0]:
            print(f"[mailpoll][imap] search {search_label} returned empty")
            return PollResult(scanned=0, relevant=0, sent=0, drafts=0, ignored=0, queued=0)
        all_uids = data[0].decode("utf-8", errors="ignore").split()
        uids = list(reversed(all_uids))[:cap]
        print(f"[mailpoll][imap] search={search_label} uids_total={len(all_uids)} processing={len(uids)} fast={fast}")

        for uid in uids:
            scanned += 1

            ftyp, fdata = conn.uid("fetch", uid, "(RFC822)")
            if ftyp != "OK" or not fdata:
                print(f"[mailpoll][imap] fetch failed uid={uid} typ={ftyp}")
                continue
            raw_bytes = b""
            for item in fdata:
                if isinstance(item, tuple) and item[1]:
                    raw_bytes = item[1]
                    break
            if not raw_bytes:
                continue

            msg = email.message_from_bytes(raw_bytes)
            dedupe_id = _imap_dedupe_id(uid, msg)
            imap_id = f"imap:{uid}"
            from_h = str(msg.get("From") or "")
            subject = _clean_text(str(msg.get("Subject") or ""))
            from_email = _extract_from_email(from_h)
            print(f"[mailpoll][imap] uid={uid} from={from_email!r} subject={subject!r}")

            already_handled = state_store.get_processed_meta(dedupe_id) is not None
            if not already_handled:
                for alias in _dedupe_aliases(primary_id=dedupe_id, uid=uid, email_msg=msg):
                    if state_store.get_processed_meta(alias) is not None:
                        already_handled = True
                        break
            if already_handled:
                continue

            if _is_skipped_sender(from_email, skip_from_emails):
                _mark_ignored_message(
                    state_store,
                    message_id=dedupe_id,
                    from_email=from_email,
                    subject=subject,
                    reason="own_mailbox_sender",
                )
                aliases = _dedupe_aliases(primary_id=dedupe_id, uid=uid, email_msg=msg)
                if aliases:
                    state_store.mark_processed_aliases(
                        dedupe_id,
                        aliases,
                        {
                            "action": "ignored",
                            "reason": "own_mailbox_sender",
                            "processed_at": _now_iso(),
                        },
                    )
                ignored += 1
                print(f"[mailpoll][imap] ignored uid={uid} reason=own_mailbox_sender")
                continue

            # Extract body text (simple)
            body_text = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.is_multipart():
                        continue
                    ctype = (part.get_content_type() or "").lower()
                    disp = str(part.get("Content-Disposition") or "").lower()
                    if "attachment" in disp:
                        continue
                    if ctype == "text/plain":
                        try:
                            payload = part.get_payload(decode=True) or b""
                            cs = part.get_content_charset() or "utf-8"
                            body_text = payload.decode(cs, errors="replace")
                            break
                        except Exception:
                            continue
            else:
                try:
                    payload = msg.get_payload(decode=True) or b""
                    cs = msg.get_content_charset() or "utf-8"
                    body_text = payload.decode(cs, errors="replace")
                except Exception:
                    body_text = ""
            body_text = (body_text or "").strip()

            if not _should_consider_email(settings, from_email=from_email, subject=subject, body=body_text):
                _mark_keyword_rejected(
                    state_store, message_id=dedupe_id, from_email=from_email, subject=subject
                )
                aliases = _dedupe_aliases(primary_id=dedupe_id, uid=uid, email_msg=msg)
                if aliases:
                    state_store.mark_processed_aliases(
                        dedupe_id,
                        aliases,
                        {
                            "action": "ignored",
                            "reason": "keyword_prefilter",
                            "processed_at": _now_iso(),
                        },
                    )
                ignored += 1
                print(f"[mailpoll][imap] ignored uid={uid} reason=keyword_prefilter")
                continue

            if not _try_begin_processing(
                state_store,
                dedupe_id,
                from_email=from_email,
                subject=subject,
                transport_id=imap_id,
            ):
                continue

            query = _clean_text(subject + "\n\n" + body_text)[:6000]
            kb_ctx = _build_kb_context(settings=settings, tenant_id=state_store.tenant_id, query_text=query, k=6)
            decision = decide_and_write_reply(
                settings=settings,
                mail_from=from_h,
                mail_subject=subject,
                mail_body=query,
                kb_context=kb_ctx,
                service_keywords=settings.SERVICE_KEYWORDS or [],
            )
            conf = float(decision.get("confidence") or 0.0)
            is_rel = bool(decision.get("is_relevant"))
            thr = _effective_relevance_threshold(settings)
            if is_rel and conf >= thr:
                relevant += 1
                print(f"[mailpoll][imap] relevant uid={uid} conf={conf}")
                reply_subject = _clean_text(decision.get("reply_subject") or ("Re: " + subject))
                reply_body = str(decision.get("reply_body") or "").strip()
                if (settings.REPLY_MODE or "").lower() == "send":
                    reservation = None
                    if mail_account is not None:
                        from core.billing import reserve_auto_send

                        reservation = reserve_auto_send(mail_account.user, mail_account, dedupe_id)
                        if not reservation.allowed:
                            drafts += 1
                            quota_meta = {
                                "action": "draft",
                                "confidence": conf,
                                "reply_subject": reply_subject,
                                "reply_body": reply_body,
                                "from_email": from_email,
                                "subject": subject,
                                "mail_body": body_text[:8000],
                                "reason": reservation.reason or "quota_blocked",
                                "processed_at": _now_iso(),
                                "imap_uid": uid,
                                "quota_blocked": True,
                            }
                            state_store.upsert_queue_item(
                                dedupe_id,
                                status="quota_blocked",
                                details={
                                    "id": dedupe_id,
                                    "from_email": from_email,
                                    "subject": subject,
                                    "reason": reservation.reason or "quota_blocked",
                                    "reply_subject": reply_subject,
                                    "upgrade_required": True,
                                },
                            )
                            state_store.mark_processed_aliases(
                                dedupe_id,
                                _dedupe_aliases(primary_id=dedupe_id, uid=uid, email_msg=msg),
                                quota_meta,
                            )
                            _maybe_telegram_notify(
                                state_store,
                                "draft",
                                subject=subject,
                                from_email=from_email,
                                reply_subject=reply_subject,
                            )
                            print(f"[mailpoll][imap] quota_blocked uid={uid} reason={reservation.reason!r}")
                            continue
                    try:
                        _send_reply_via_transport(
                            settings=settings,
                            gmail_client=None,
                            to_email=from_email,
                            subject=reply_subject,
                            body_text=reply_body,
                            thread_id=None,
                        )
                        if reservation is not None:
                            from core.billing import commit_auto_send

                            commit_auto_send(reservation)
                        sent += 1
                        print(f"[mailpoll][imap] sent uid={uid} to={from_email!r}")
                        sent_meta = {
                            "action": "sent",
                            "confidence": conf,
                            "reply_subject": reply_subject,
                            "reply_body": reply_body,
                            "from_email": from_email,
                            "subject": subject,
                            "mail_body": body_text[:8000],
                            "reason": "auto_reply",
                            "processed_at": _now_iso(),
                            "imap_uid": uid,
                            "usage_event_id": getattr(reservation, "event_id", None),
                        }
                        state_store.upsert_queue_item(
                            dedupe_id,
                            status="completed",
                            details={
                                "id": dedupe_id,
                                "from_email": from_email,
                                "subject": subject,
                                "reason": "auto_reply",
                            },
                        )
                        state_store.mark_processed_aliases(
                            dedupe_id,
                            _dedupe_aliases(primary_id=dedupe_id, uid=uid, email_msg=msg),
                            sent_meta,
                        )
                        # Mark as seen to avoid reprocessing if state store is cleared.
                        try:
                            conn.uid("store", uid, "+FLAGS", r"(\Seen)")
                        except Exception:
                            pass
                        _maybe_telegram_notify(
                            state_store,
                            "sent",
                            subject=subject,
                            from_email=from_email,
                            reply_subject=reply_subject,
                        )
                    except Exception as e:
                        err = str(e)
                        if reservation is not None:
                            from core.billing import fail_auto_send

                            fail_auto_send(reservation, err)
                        print(f"[mailpoll][imap] send_failed uid={uid} err={err}")
                        err_meta = {
                            "action": "error",
                            "confidence": conf,
                            "reason": "send_failed",
                            "error": err,
                            "processed_at": _now_iso(),
                        }
                        state_store.upsert_queue_item(
                            dedupe_id,
                            status="error",
                            details={
                                "id": dedupe_id,
                                "from_email": from_email,
                                "subject": subject,
                                "reason": "send_failed",
                                "error": err,
                            },
                        )
                        state_store.mark_processed_aliases(
                            dedupe_id,
                            _dedupe_aliases(primary_id=dedupe_id, uid=uid, email_msg=msg),
                            err_meta,
                        )
                        _maybe_telegram_notify(
                            state_store,
                            "error",
                            subject=subject,
                            from_email=from_email,
                            error=err,
                        )
                else:
                    drafts += 1
                    print(f"[mailpoll][imap] draft uid={uid} conf={conf}")
                    draft_meta = {
                        "action": "draft",
                        "confidence": conf,
                        "reply_subject": reply_subject,
                        "reply_body": reply_body,
                        "from_email": from_email,
                        "subject": subject,
                        "mail_body": body_text[:8000],
                        "processed_at": _now_iso(),
                    }
                    state_store.mark_processed_aliases(
                        dedupe_id,
                        _dedupe_aliases(primary_id=dedupe_id, uid=uid, email_msg=msg),
                        draft_meta,
                    )
                    _maybe_telegram_notify(
                        state_store,
                        "draft",
                        subject=subject,
                        from_email=from_email,
                        reply_subject=reply_subject,
                    )
            else:
                ignored += 1
                print(f"[mailpoll][imap] not_relevant uid={uid} conf={conf} reason={decision.get('reason')!r}")
                ignored_meta = {
                    "action": "ignored",
                    "confidence": conf,
                    "reason": decision.get("reason") or "not_relevant",
                    "processed_at": _now_iso(),
                }
                state_store.mark_processed_aliases(
                    dedupe_id,
                    _dedupe_aliases(primary_id=dedupe_id, uid=uid, email_msg=msg),
                    ignored_meta,
                )

        return PollResult(scanned=scanned, relevant=relevant, sent=sent, drafts=drafts, ignored=ignored, queued=queued)
    finally:
        try:
            conn.logout()
        except Exception:
            pass

