from __future__ import annotations

import email
import imaplib
import re
import socket
from datetime import timezone
from email.header import decode_header
from email.utils import parsedate_to_datetime
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
                    "from": from_decoded,
                    "subject": subject_decoded,
                    "internal_date": internal_ms,
                    "snippet": "",
                    "unread": unread,
                }
            )

        return out

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

        body_text = ""

        def decode_part_payload(part):
            try:
                payload = part.get_payload(decode=True)
                if payload is None:
                    return ""
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
            except Exception:
                return ""

        if msg.is_multipart():
            # Prefer text/plain parts
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
                # Minimal html->text.
                html = "\n".join([c for c in html_chunks if c])
                body_text = re.sub(r"<[^>]+>", "", html)
        else:
            # Single part
            ctype = (msg.get_content_type() or "").lower()
            if ctype == "text/plain":
                body_text = decode_part_payload(msg)
            elif ctype == "text/html":
                html = decode_part_payload(msg)
                body_text = re.sub(r"<[^>]+>", "", html)

        body_text = (body_text or "").strip()
        snippet = (body_text[:240] or "").strip() if body_text else ""

        return {
            "thread_id": uid_str,
            "messages": [
                {
                    "id": uid_str,
                    "from": from_decoded,
                    "subject": subject_decoded,
                    "internal_date": internal_ms,
                    "snippet": snippet,
                    "body_text": body_text,
                    "is_from_me": False,
                }
            ],
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

