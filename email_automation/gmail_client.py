from __future__ import annotations

import base64
import re
from typing import Any, Dict, List, Tuple

from email_automation.settings import Settings


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

    def list_inbox_thread_summaries(self, max_threads: int = 40) -> List[Dict[str, Any]]:
        svc = self._service()
        # Get recent inbox threads. Use Threads.list for cheaper UI summary.
        resp = (
            svc.users()
            .threads()
            .list(userId="me", labelIds=["INBOX"], maxResults=int(max_threads), includeSpamTrash=False)
            .execute()
        )
        threads = resp.get("threads") or []
        out: List[Dict[str, Any]] = []
        for t in threads:
            tid = str(t.get("id") or "")
            if not tid:
                continue
            # Fetch minimal metadata for the latest message in thread.
            det = (
                svc.users()
                .threads()
                .get(userId="me", id=tid, format="metadata", metadataHeaders=["From", "Subject", "Date"])
                .execute()
            )
            msgs = det.get("messages") or []
            if not msgs:
                continue
            last = msgs[-1]
            payload = last.get("payload") or {}
            headers = payload.get("headers") or []
            from_v = self._header(headers, "From")
            subj = self._header(headers, "Subject")
            date_v = self._header(headers, "Date")
            internal_ms = int(last.get("internalDate") or 0)
            # unread: if INBOX + UNREAD label is on the thread/message
            label_ids = (last.get("labelIds") or []) + (det.get("labels") or [])
            unread = "UNREAD" in set(label_ids)
            snippet = str(last.get("snippet") or "")
            out.append(
                {
                    "thread_id": tid,
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

        det = svc.users().threads().get(userId="me", id=tid, format="full").execute()
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
            is_from_me = "me" in (from_v.lower() if from_v else "")
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
        m = (
            svc.users()
            .messages()
            .get(userId="me", id=mid, format="metadata", metadataHeaders=["From", "Subject"])
            .execute()
        )
        payload = m.get("payload") or {}
        headers = payload.get("headers") or []
        return self._header(headers, "From"), self._header(headers, "Subject")

