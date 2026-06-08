from __future__ import annotations

import base64
import email.utils
import re
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any, Dict, List, Tuple

from googleapiclient.errors import HttpError

from email_automation.settings import Settings


def gmail_retry_after_seconds(err: HttpError) -> float:
    """Seconds to wait before retrying after Gmail 429 (from header or error message)."""
    try:
        raw = (err.resp.get("retry-after") or err.resp.get("Retry-After") or "").strip()
        if raw:
            if raw.isdigit():
                return max(1.0, float(raw))
            dt = parsedate_to_datetime(raw)
            if dt is not None:
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return max(1.0, (dt.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds())
    except Exception:
        pass
    m = re.search(r"Retry after ([0-9T:\.\-+Z]+)", str(err), re.I)
    if m:
        try:
            deadline = datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            return max(
                1.0,
                min(300.0, (deadline.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds()),
            )
        except Exception:
            pass
    return 15.0


def is_gmail_rate_limit_error(err: BaseException) -> bool:
    return isinstance(err, HttpError) and getattr(err.resp, "status", None) == 429


class GmailClient:
    """Thin Gmail API wrapper used by the dashboard UI."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._svc = None

    def _service(self):
        if self._svc is not None:
            return self._svc
        token_file = (self.settings.GOOGLE_TOKEN_FILE or "").strip()
        if not token_file:
            raise RuntimeError("GOOGLE_TOKEN_FILE is not set")
        # Credentials are stored as an "authorized user" JSON (Flow.credentials.to_json()).
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials.from_authorized_user_file(token_file, scopes=self.settings.gmail_scopes())
        self._svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return self._svc

    def _execute(self, request, *, max_retries: int = 2):
        for attempt in range(max_retries + 1):
            try:
                return request.execute()
            except HttpError as e:
                if getattr(e.resp, "status", None) == 429 and attempt < max_retries:
                    time.sleep(gmail_retry_after_seconds(e))
                    continue
                raise

    @staticmethod
    def _header(headers: list[dict[str, str]] | None, name: str) -> str:
        if not headers:
            return ""
        n = name.lower()
        for h in headers:
            if str(h.get("name") or "").lower() == n:
                return str(h.get("value") or "")
        return ""

    @staticmethod
    def _decode_body(data: str) -> str:
        if not data:
            return ""
        try:
            raw = base64.urlsafe_b64decode(data.encode("utf-8"))
            return raw.decode("utf-8", errors="replace")
        except Exception:
            return ""

    def _owner_email_set(self) -> set[str]:
        """Addresses we treat as 'our' outbound identity (do not auto-reply to ourselves)."""
        out: set[str] = set()
        for raw in (
            self.settings.GMAIL_ADDRESS,
            self.settings.SMTP_FROM_EMAIL,
            self.settings.SMTP_USERNAME,
            self.settings.IMAP_USERNAME,
        ):
            addr = (raw or "").strip().lower()
            if addr and "@" in addr:
                out.add(addr)
        return out

    def is_from_account_owner(self, from_header: str) -> bool:
        """True if From is one of our configured mailbox addresses (not substring 'me' in address)."""
        _, addr = parseaddr(from_header or "")
        addr = (addr or "").strip().lower()
        if not addr:
            return False
        owners = self._owner_email_set()
        if owners and addr in owners:
            return True
        # Rare: header is literally "me" when Gmail UI omits address — treat as self only if no owners configured.
        if not owners and (from_header or "").strip().lower() == "me":
            return True
        return False

    def _extract_text_body(self, payload: dict) -> str:
        """Prefer text/plain, fall back to stripped text/html."""
        if not payload:
            return ""

        def walk_parts(p) -> List[dict]:
            out = [p]
            for ch in (p.get("parts") or []):
                out.extend(walk_parts(ch))
            return out

        parts = walk_parts(payload)
        plain = ""
        html = ""
        for p in parts:
            mime = (p.get("mimeType") or "").lower()
            body = p.get("body") or {}
            data = body.get("data") or ""
            if not data:
                continue
            if mime == "text/plain" and not plain:
                plain = self._decode_body(data)
            if mime == "text/html" and not html:
                html = self._decode_body(data)

        if plain.strip():
            return plain.strip()
        if html.strip():
            # Minimal HTML -> text for UI preview
            t = re.sub(r"<[^>]+>", "", html)
            return t.strip()
        return ""

    def get_profile_email(self) -> str:
        svc = self._service()
        prof = svc.users().getProfile(userId="me").execute()
        return str(prof.get("emailAddress") or "").strip()

    def _threads_list(
        self,
        svc,
        *,
        max_threads: int,
        label_ids: list[str] | None = None,
        q: str | None = None,
    ) -> tuple[list[dict[str, Any]], str]:
        """List thread stubs; returns (threads, source_label for UI)."""
        kwargs: dict[str, Any] = {
            "userId": "me",
            "maxResults": int(max_threads),
            "includeSpamTrash": False,
        }
        if label_ids:
            kwargs["labelIds"] = label_ids
        if q:
            kwargs["q"] = q
        resp = svc.users().threads().list(**kwargs).execute()
        threads = resp.get("threads") or []
        if label_ids == ["INBOX"]:
            return threads, "inbox"
        if q:
            return threads, "search"
        return threads, "all"

    def list_inbox_thread_summaries(self, max_threads: int = 40) -> List[Dict[str, Any]]:
        svc = self._service()
        max_n = max(1, int(max_threads or 40))

        threads, _source = self._threads_list(svc, max_threads=max_n, label_ids=["INBOX"])
        # Some Gmail accounts keep mail under category labels but not INBOX (API returns 0).
        if not threads:
            threads, _source = self._threads_list(svc, max_threads=max_n)

        out: List[Dict[str, Any]] = []
        for t in threads:
            tid = str(t.get("id") or "")
            if not tid:
                continue
            list_snippet = str(t.get("snippet") or "")
            try:
                det = self._execute(
                    svc.users()
                    .threads()
                    .get(userId="me", id=tid, format="metadata", metadataHeaders=["From", "Subject", "Date"])
                )
            except Exception:
                # Rate limits or transient errors: still show thread stub from list().
                out.append(
                    {
                        "thread_id": tid,
                        "message_id": "",
                        "from": "",
                        "subject": "(Could not load headers)",
                        "internal_date": 0,
                        "snippet": list_snippet,
                        "unread": False,
                        "date": "",
                    }
                )
                continue

            msgs = det.get("messages") or []
            if not msgs:
                continue
            last = msgs[-1]
            inbound = last
            for m in reversed(msgs):
                payload_m = m.get("payload") or {}
                headers_m = payload_m.get("headers") or []
                from_m = self._header(headers_m, "From")
                if not self.is_from_account_owner(from_m):
                    inbound = m
                    break
            payload = last.get("payload") or {}
            headers = payload.get("headers") or []
            from_v = self._header(headers, "From")
            subj = self._header(headers, "Subject")
            date_v = self._header(headers, "Date")
            internal_ms = int(last.get("internalDate") or 0)
            label_ids = (last.get("labelIds") or []) + (det.get("labels") or [])
            unread = "UNREAD" in set(label_ids)
            snippet = str(last.get("snippet") or "") or list_snippet
            out.append(
                {
                    "thread_id": tid,
                    "message_id": str(inbound.get("id") or ""),
                    "from": from_v,
                    "subject": subj,
                    "internal_date": internal_ms,
                    "snippet": snippet,
                    "unread": unread,
                    "date": date_v,
                }
            )
        return out

    def get_thread_for_ui(self, thread_id: str) -> Dict[str, Any]:
        svc = self._service()
        tid = str(thread_id or "").strip()
        if not tid:
            return {"ok": False, "error": "missing_thread_id"}

        det = self._execute(svc.users().threads().get(userId="me", id=tid, format="full"))
        msgs = det.get("messages") or []
        ui_msgs: List[Dict[str, Any]] = []
        for m in msgs:
            mid = str(m.get("id") or "")
            internal_ms = int(m.get("internalDate") or 0)
            snippet = str(m.get("snippet") or "")
            payload = m.get("payload") or {}
            headers = payload.get("headers") or []
            from_v = self._header(headers, "From")
            subj = self._header(headers, "Subject")
            to_v = self._header(headers, "To")
            is_from_me = self.is_from_account_owner(from_v)
            body_text = self._extract_text_body(payload)
            ui_msgs.append(
                {
                    "id": mid,
                    "from": from_v,
                    "to": to_v,
                    "subject": subj,
                    "internal_date": internal_ms,
                    "snippet": snippet,
                    "body_text": body_text,
                    "is_from_me": is_from_me,
                }
            )
        return {"ok": True, "thread_id": tid, "messages": ui_msgs}

    def get_message_from_and_subject(self, message_id: str) -> Tuple[str, str]:
        svc = self._service()
        mid = str(message_id or "").strip()
        if not mid:
            return "", ""
        m = self._execute(
            svc.users()
            .messages()
            .get(userId="me", id=mid, format="metadata", metadataHeaders=["From", "Subject"])
        )
        payload = m.get("payload") or {}
        headers = payload.get("headers") or []
        return self._header(headers, "From"), self._header(headers, "Subject")

    def send_reply(
        self,
        *,
        to_email: str,
        subject: str,
        body_text: str,
        thread_id: str | None = None,
        in_reply_to: str | None = None,
        references: str | None = None,
    ) -> str:
        """Send a simple text email (optionally within a thread). Returns Gmail message id."""
        svc = self._service()
        msg = EmailMessage()
        msg["To"] = to_email
        msg["From"] = self.settings.outbound_from_email() or "me"
        msg["Subject"] = subject or "(No subject)"
        msg["Message-ID"] = email.utils.make_msgid(domain=None)
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
        if references:
            msg["References"] = references
        msg.set_content(body_text or "")

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        body: dict[str, Any] = {"raw": raw}
        if thread_id:
            body["threadId"] = str(thread_id)
        sent = self._execute(svc.users().messages().send(userId="me", body=body))
        return str(sent.get("id") or "")

