from __future__ import annotations

import email
import imaplib
import re
import socket
from datetime import timezone
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any, Dict, List, Optional, Tuple

from email_automation.settings import Settings


def imap_inbox_ready(settings: Settings) -> bool:
    host = (settings.IMAP_HOST or "").strip()
    user = (settings.IMAP_USERNAME or "").strip()
    pw = settings.IMAP_PASSWORD
    return bool(host and user and pw and (pw.get_secret_value() or "").strip())


class ImapMailbox:
    """Minimal IMAP shim used by the UI endpoints.

    This implementation is "good enough" for dashboard inbox previews:
    - list inbox message summaries (from/subject/date/unread)
    - fetch one message for thread preview (body_text/snippet)
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._conn: Optional[imaplib.IMAP4] = None

    def _mailbox_name(self) -> str:
        return (self.settings.IMAP_MAILBOX or "INBOX").strip() or "INBOX"

    def _select_mailbox(self, conn: imaplib.IMAP4) -> None:
        mailbox = self._mailbox_name()
        typ, _ = conn.select(mailbox, readonly=True)
        if typ != "OK":
            raise RuntimeError(f"IMAP select failed for mailbox: {mailbox}")

    def _ssl_context(self):
        # Import lazily so this module still imports even if ssl isn't used.
        import ssl

        verify = bool(getattr(self.settings, "IMAP_VERIFY_TLS", True))
        if verify:
            return ssl.create_default_context()

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    def _connect(self) -> imaplib.IMAP4:
        if self._conn is not None:
            return self._conn

        host = (self.settings.IMAP_HOST or "").strip()
        port = int(getattr(self.settings, "IMAP_PORT", 993) or 993)
        user = (self.settings.IMAP_USERNAME or "").strip()
        pw = self.settings.IMAP_PASSWORD.get_secret_value() if self.settings.IMAP_PASSWORD else ""

        timeout_sec = 15
        socket.setdefaulttimeout(timeout_sec)

        use_ssl = port == 993
        ctx = self._ssl_context()

        if use_ssl:
            self._conn = imaplib.IMAP4_SSL(host, port, ssl_context=ctx)
        else:
            self._conn = imaplib.IMAP4(host, port)
            # Try STARTTLS when possible (only if not using implicit SSL)
            try:
                self._conn.starttls(ssl_context=ctx)
            except Exception:
                # Some servers don't support STARTTLS; continue and let LOGIN/SELECT fail if needed.
                pass

        typ, _ = self._conn.login(user, pw)
        if typ != "OK":
            raise RuntimeError("IMAP login failed")

        return self._conn

    @staticmethod
    def _decode_mime_words(value: str) -> str:
        try:
            if not value:
                return ""
            parts = decode_header(value)
            out = ""
            for s, enc in parts:
                if isinstance(s, bytes):
                    out += s.decode(enc or "utf-8", errors="replace")
                else:
                    out += str(s)
            return out
        except Exception:
            return str(value or "")

    @staticmethod
    def _to_epoch_ms(dt) -> int:
        if not dt:
            return 0
        try:
            if dt.tzinfo is None:
                # Assume UTC if server didn't send tz info.
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except Exception:
            return 0

    def _fetch_flags(self, conn: imaplib.IMAP4, uid: str) -> List[str]:
        self._select_mailbox(conn)
        typ, data = conn.uid("fetch", uid, "(FLAGS)")
        if typ != "OK" or not data:
            return []
        flags: List[str] = []
        for item in data:
            if isinstance(item, tuple) and item and item[0]:
                raw = item[0].decode("utf-8", errors="ignore")
                flags.extend(re.findall(r"\\[A-Za-z]+", raw))
        return flags

    def _search_recent_uids(self, conn: imaplib.IMAP4, max_threads: int) -> List[str]:
        # Use UID ordering; grab only the latest N UIDs for performance.
        self._select_mailbox(conn)

        typ, data = conn.uid("search", None, "ALL")
        if typ != "OK" or not data or not data[0]:
            return []
        all_uids = data[0].decode("utf-8", errors="ignore").split()
        if not all_uids:
            return []
        n = max(1, int(max_threads or 40))
        # Return newest-first so the UI shows the latest mail at the top.
        return list(reversed(all_uids[-n:]))

    def list_inbox_summaries(self, max_threads: int = 40) -> List[Dict[str, Any]]:
        conn = self._connect()
        uids = self._search_recent_uids(conn, max_threads=max_threads)
        out: List[Dict[str, Any]] = []

        for uid in uids:
            # Lightweight header-only fetch.
            typ, data = conn.uid("fetch", uid, '(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)] FLAGS)')
            if typ != "OK" or not data:
                continue

            header_bytes = b""
            flags: List[str] = []
            for item in data:
                if isinstance(item, tuple):
                    header_bytes = item[1] or b""
                    raw0 = item[0].decode("utf-8", errors="ignore") if item[0] else ""
                    flags = re.findall(r"\\[A-Za-z]+", raw0)

            # Parse headers
            msg = email.message_from_bytes(header_bytes or b"")
            from_raw = msg.get("From", "") or ""
            subject_raw = msg.get("Subject", "") or ""
            date_raw = msg.get("Date", "") or ""
            from_decoded = self._decode_mime_words(from_raw)
            subject_decoded = self._decode_mime_words(subject_raw)

            dt = None
            try:
                dt = parsedate_to_datetime(date_raw)
            except Exception:
                dt = None
            internal_ms = self._to_epoch_ms(dt)

            # unread if not seen
            unread = not any(f.lower() == r"\seen".lower() for f in (flags or []))

            out.append(
                {
                    "thread_id": str(uid),  # IMAP UID
                    "message_id": f"imap:{uid}",
                    "from": from_decoded,
                    "subject": subject_decoded,
                    "internal_date": internal_ms,
                    "snippet": "",
                    "unread": unread,
                }
            )

        return out

    def _owner_emails(self) -> set[str]:
        out: set[str] = set()
        for raw in (
            self.settings.outbound_from_email(),
            self.settings.SMTP_USERNAME,
            self.settings.IMAP_USERNAME,
            self.settings.GMAIL_ADDRESS,
        ):
            v = (raw or "").strip().lower()
            if v and "@" in v:
                out.add(v)
        return out

    def _is_from_me_header(self, from_header: str) -> bool:
        _, addr = parseaddr(from_header or "")
        return (addr or "").strip().lower() in self._owner_emails()

    @staticmethod
    def _normalize_msg_id(value: str) -> str:
        v = (value or "").strip().lower()
        if v.startswith("<") and v.endswith(">"):
            return v[1:-1]
        return v

    def _subject_replies_to(self, reply_subj: str, original_subj: str) -> bool:
        def _norm(s: str) -> str:
            s = (s or "").strip()
            while True:
                m = re.match(r"^(re|fwd):\s*", s, flags=re.I)
                if not m:
                    break
                s = s[m.end() :].strip()
            return s.lower()

        a = _norm(reply_subj)
        b = _norm(original_subj)
        return bool(a and b and a == b)

    def _extract_body_text(self, msg: email.message.Message) -> str:
        def decode_part_payload(part: email.message.Message) -> str:
            try:
                payload = part.get_payload(decode=True)
                if payload is None:
                    return ""
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
            except Exception:
                return ""

        body_text = ""
        if msg.is_multipart():
            plain_chunks: List[str] = []
            html_chunks: List[str] = []
            for part in msg.walk():
                if part.is_multipart():
                    continue
                ctype = (part.get_content_type() or "").lower()
                disp = str(part.get("Content-Disposition") or "").lower()
                if "attachment" in disp:
                    continue
                if ctype == "text/plain":
                    plain_chunks.append(decode_part_payload(part))
                elif ctype == "text/html":
                    html_chunks.append(decode_part_payload(part))
            if plain_chunks:
                body_text = "\n".join([c for c in plain_chunks if c])
            elif html_chunks:
                html = "\n".join([c for c in html_chunks if c])
                body_text = re.sub(r"<[^>]+>", "", html)
        else:
            ctype = (msg.get_content_type() or "").lower()
            if ctype == "text/plain":
                body_text = decode_part_payload(msg)
            elif ctype == "text/html":
                html = decode_part_payload(msg)
                body_text = re.sub(r"<[^>]+>", "", html)
        return (body_text or "").strip()

    def _ui_message_from_rfc822(self, raw_bytes: bytes, *, uid: str, is_from_me: Optional[bool] = None) -> Dict[str, Any]:
        msg = email.message_from_bytes(raw_bytes)
        from_decoded = self._decode_mime_words(msg.get("From", "") or "")
        subject_decoded = self._decode_mime_words(msg.get("Subject", "") or "")
        date_raw = msg.get("Date", "") or ""
        dt = None
        try:
            dt = parsedate_to_datetime(date_raw)
        except Exception:
            dt = None
        internal_ms = self._to_epoch_ms(dt)
        body_text = self._extract_body_text(msg)
        snippet = (body_text[:240] or "").strip() if body_text else ""
        if is_from_me is None:
            is_from_me = self._is_from_me_header(from_decoded)
        return {
            "id": uid,
            "from": from_decoded,
            "subject": subject_decoded,
            "internal_date": internal_ms,
            "snippet": snippet,
            "body_text": body_text,
            "is_from_me": bool(is_from_me),
        }

    def _sent_mailbox_names(self) -> List[str]:
        return ["Sent", "Sent Items", "INBOX.Sent", "[Gmail]/Sent Mail", "Sent Messages"]

    def _discover_sent_mailboxes(self, conn: imaplib.IMAP4) -> List[str]:
        names = list(self._sent_mailbox_names())
        seen = {n.lower() for n in names}
        try:
            typ, data = conn.list()
            if typ == "OK" and data:
                for raw in data:
                    if not raw:
                        continue
                    line = raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw)
                    m = re.search(r'"([^"]+)"\s*$', line)
                    if not m:
                        continue
                    folder = m.group(1)
                    fl = folder.lower()
                    if "sent" in fl and fl not in seen:
                        names.append(folder)
                        seen.add(fl)
        except Exception:
            pass
        return names

    def _find_sent_replies(self, conn: imaplib.IMAP4, original: email.message.Message) -> List[Dict[str, Any]]:
        """Load outbound replies from Sent that belong to this inbox message."""
        orig_mid = self._normalize_msg_id(original.get("Message-ID") or "")
        orig_subj = self._decode_mime_words(original.get("Subject") or "")
        owners = self._owner_emails()
        found: List[Dict[str, Any]] = []
        seen_uids: set[str] = set()

        for folder in self._discover_sent_mailboxes(conn):
            try:
                typ, _ = conn.select(folder, readonly=True)
                if typ != "OK":
                    continue
            except Exception:
                continue

            typ, data = conn.uid("search", None, "ALL")
            if typ != "OK" or not data or not data[0]:
                continue
            uids = data[0].decode("utf-8", errors="ignore").split()
            for uid in reversed(uids[-30:]):
                if not uid or uid in seen_uids:
                    continue
                try:
                    typ, data = conn.uid(
                        "fetch",
                        uid,
                        "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE IN-REPLY-TO REFERENCES)])",
                    )
                except Exception:
                    continue
                if typ != "OK" or not data:
                    continue

                header_bytes = b""
                for item in data:
                    if isinstance(item, tuple):
                        header_bytes = item[1] or b""
                        break
                if not header_bytes:
                    continue

                hdr = email.message_from_bytes(header_bytes)
                _, from_addr = parseaddr(self._decode_mime_words(hdr.get("From") or ""))
                from_addr = (from_addr or "").strip().lower()
                if owners and from_addr not in owners:
                    continue

                in_reply = self._normalize_msg_id(hdr.get("In-Reply-To") or "")
                refs = (hdr.get("References") or "").lower()
                mid_match = bool(orig_mid) and (orig_mid == in_reply or orig_mid in refs)
                subj_match = self._subject_replies_to(hdr.get("Subject") or "", orig_subj)
                if not mid_match and not subj_match:
                    continue

                try:
                    typ, full = conn.uid("fetch", uid, "(RFC822)")
                except Exception:
                    continue
                if typ != "OK" or not full:
                    continue
                raw_bytes = b""
                for item in full:
                    if isinstance(item, tuple):
                        raw_bytes = item[1] or b""
                        break
                if not raw_bytes:
                    continue

                seen_uids.add(uid)
                ui = self._ui_message_from_rfc822(raw_bytes, uid=f"sent-{uid}", is_from_me=True)
                found.append(ui)

        try:
            self._select_mailbox(conn)
        except Exception:
            pass
        return found

    def get_thread_for_ui(self, uid: int) -> Dict[str, Any]:
        conn = self._connect()
        self._select_mailbox(conn)
        uid_str = str(int(uid))

        # Fetch full RFC822 to reliably extract text/plain.
        try:
            typ, data = conn.uid("fetch", uid_str, "(RFC822)")
        except imaplib.IMAP4.error as e:
            msg = str(e or "")
            # Some servers require SELECT again if state resets to AUTH.
            if ("state AUTH" in msg) or ("states SELECTED" in msg) or ("only allowed in states" in msg):
                self._select_mailbox(conn)
                typ, data = conn.uid("fetch", uid_str, "(RFC822)")
            else:
                raise
        if typ != "OK" or not data:
            return {"thread_id": uid_str, "messages": []}

        raw_bytes = b""
        for item in data:
            if isinstance(item, tuple):
                raw_bytes = item[1] or b""
                break

        msg = email.message_from_bytes(raw_bytes)
        inbound = self._ui_message_from_rfc822(raw_bytes, uid=uid_str, is_from_me=False)
        replies = self._find_sent_replies(conn, msg)
        messages = [inbound] + replies
        messages.sort(key=lambda m: int(m.get("internal_date") or 0))

        return {
            "thread_id": uid_str,
            "messages": messages,
        }

    def close(self) -> None:
        if self._conn is None:
            return
        try:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn.logout()
        except Exception:
            pass
        finally:
            self._conn = None

    def __enter__(self) -> "ImapMailbox":
        return self

    def __exit__(self, exc_type, exc, tb) -> Optional[bool]:
        self.close()
        return None

