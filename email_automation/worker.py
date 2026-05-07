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


def poll_once(*, settings: Settings, state_store: StateStore, gmail_client: Any) -> PollResult:
    scanned = relevant = sent = drafts = ignored = queued = 0

    # Gmail: recent inbox threads; per thread, newest *inbound* message not yet handled (not only msgs[-1]).
    threads = gmail_client.list_inbox_thread_summaries(max_threads=40)
    for t in threads:
        tid = str(t.get("thread_id") or "")
        if not tid:
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
        if not _should_consider_email(settings, from_email=from_email, subject=subject, body=body):
            state_store.mark_processed(mid, {"action": "ignored", "reason": "keyword_prefilter", "processed_at": _now_iso()})
            ignored += 1
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
                _send_reply_via_transport(
                    settings=settings,
                    gmail_client=gmail_client,
                    to_email=from_email,
                    subject=reply_subject,
                    body_text=reply_body,
                    thread_id=tid,
                )
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
                        "processed_at": _now_iso(),
                    },
                )
            else:
                drafts += 1
                state_store.mark_processed(
                    mid,
                    {
                        "action": "draft",
                        "confidence": conf,
                        "reply_subject": reply_subject,
                        "processed_at": _now_iso(),
                    },
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


def poll_once_imap(*, settings: Settings, state_store: StateStore) -> PollResult:
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

        # Use ALL (not only UNSEEN). Users often open mail in the UI first,
        # which can mark it Seen before the worker runs.
        typ, data = conn.uid("search", None, "ALL")
        if typ != "OK" or not data or not data[0]:
            print("[mailpoll][imap] search ALL returned empty")
            return PollResult(scanned=0, relevant=0, sent=0, drafts=0, ignored=0, queued=0)
        all_uids = data[0].decode("utf-8", errors="ignore").split()
        # Process newest first, cap to avoid long runs
        uids = list(reversed(all_uids))[:20]
        print(f"[mailpoll][imap] uids_total={len(all_uids)} processing={len(uids)}")

        for uid in uids:
            msg_id = f"imap:{uid}"
            scanned += 1
            if state_store.get_processed_meta(msg_id) is not None:
                continue

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
            from_h = str(msg.get("From") or "")
            subject = _clean_text(str(msg.get("Subject") or ""))
            from_email = _extract_from_email(from_h)
            print(f"[mailpoll][imap] uid={uid} from={from_email!r} subject={subject!r}")

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
                state_store.mark_processed(msg_id, {"action": "ignored", "reason": "keyword_prefilter", "processed_at": _now_iso()})
                ignored += 1
                print(f"[mailpoll][imap] ignored uid={uid} reason=keyword_prefilter")
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
                    try:
                        _send_reply_via_transport(
                            settings=settings,
                            gmail_client=None,
                            to_email=from_email,
                            subject=reply_subject,
                            body_text=reply_body,
                            thread_id=None,
                        )
                        sent += 1
                        print(f"[mailpoll][imap] sent uid={uid} to={from_email!r}")
                        state_store.upsert_queue_item(
                            msg_id,
                            status="completed",
                            details={
                                "id": msg_id,
                                "from_email": from_email,
                                "subject": subject,
                                "reason": "auto_reply",
                            },
                        )
                        state_store.mark_processed(
                            msg_id,
                            {
                                "action": "sent",
                                "confidence": conf,
                                "reply_subject": reply_subject,
                                "processed_at": _now_iso(),
                            },
                        )
                        # Mark as seen to avoid reprocessing if state store is cleared.
                        try:
                            conn.uid("store", uid, "+FLAGS", r"(\Seen)")
                        except Exception:
                            pass
                    except Exception as e:
                        err = str(e)
                        print(f"[mailpoll][imap] send_failed uid={uid} err={err}")
                        state_store.upsert_queue_item(
                            msg_id,
                            status="error",
                            details={
                                "id": msg_id,
                                "from_email": from_email,
                                "subject": subject,
                                "reason": "send_failed",
                                "error": err,
                            },
                        )
                        state_store.mark_processed(
                            msg_id,
                            {
                                "action": "error",
                                "confidence": conf,
                                "reason": "send_failed",
                                "error": err,
                                "processed_at": _now_iso(),
                            },
                        )
                else:
                    drafts += 1
                    print(f"[mailpoll][imap] draft uid={uid} conf={conf}")
                    state_store.mark_processed(
                        msg_id,
                        {
                            "action": "draft",
                            "confidence": conf,
                            "reply_subject": reply_subject,
                            "processed_at": _now_iso(),
                        },
                    )
            else:
                ignored += 1
                print(f"[mailpoll][imap] not_relevant uid={uid} conf={conf} reason={decision.get('reason')!r}")
                state_store.mark_processed(
                    msg_id,
                    {
                        "action": "ignored",
                        "confidence": conf,
                        "reason": decision.get("reason") or "not_relevant",
                        "processed_at": _now_iso(),
                    },
                )

        return PollResult(scanned=scanned, relevant=relevant, sent=sent, drafts=drafts, ignored=ignored, queued=queued)
    finally:
        try:
            conn.logout()
        except Exception:
            pass

