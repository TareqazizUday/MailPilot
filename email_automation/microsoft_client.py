"""Microsoft Graph mail client — same poll/send surface as GmailClient for worker reuse."""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from email.utils import parseaddr
from pathlib import Path
from typing import Any, Dict, List

import requests

from email_automation.microsoft_auth import load_token_blob, microsoft_oauth_ready
from email_automation.settings import Settings

logger = logging.getLogger(__name__)

GRAPH = "https://graph.microsoft.com/v1.0"
_TOKEN_SKEW_SECONDS = 90


class MicrosoftClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._token_blob: dict[str, Any] | None = None

    def _owner_email_set(self) -> set[str]:
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
        _, addr = parseaddr(from_header or "")
        addr = (addr or "").strip().lower()
        if not addr:
            return False
        owners = self._owner_email_set()
        return bool(owners and addr in owners)

    def _load_blob(self) -> dict[str, Any]:
        if self._token_blob is None:
            self._token_blob = load_token_blob(self.settings)
        return self._token_blob

    def _persist_blob(self, blob: dict[str, Any]) -> None:
        self._token_blob = blob
        path = (self.settings.GOOGLE_TOKEN_FILE or "").strip()
        if not path:
            return
        raw = json.dumps(blob)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(raw)
        # build_effective_settings re-syncs DB → disk; keep encrypted token current after refresh.
        try:
            parts = Path(path).resolve().parts
            if "accounts" in parts:
                i = parts.index("accounts")
                account_id = int(parts[i + 1])
                from core.models import MailAccount
                from core.mail_accounts import save_account_oauth_token

                acc = MailAccount.objects.filter(id=account_id).first()
                if acc is not None:
                    save_account_oauth_token(acc, raw)
        except Exception:
            logger.debug("microsoft token DB sync skipped", exc_info=True)

    @staticmethod
    def _access_token_fresh(blob: dict[str, Any]) -> bool:
        token = str(blob.get("access_token") or "").strip()
        if not token:
            return False
        try:
            expires_at = float(blob.get("expires_at") or 0)
        except (TypeError, ValueError):
            expires_at = 0
        if expires_at <= 0:
            # Legacy blobs without expires_at — use until Graph returns 401.
            return True
        return time.time() < (expires_at - _TOKEN_SKEW_SECONDS)

    def _access_token(self) -> str:
        if not microsoft_oauth_ready(self.settings):
            raise RuntimeError("microsoft_oauth_not_ready")
        blob = dict(self._load_blob())
        if self._access_token_fresh(blob):
            return str(blob.get("access_token") or "").strip()
        from core.microsoft_oauth import refresh_access_token

        blob = refresh_access_token(blob)
        self._persist_blob(blob)
        return str(blob.get("access_token") or "").strip()

    def _request(self, method: str, path: str, *, params=None, json_body=None) -> Any:
        from core.microsoft_oauth import refresh_access_token

        url = path if path.startswith("http") else f"{GRAPH}{path}"
        for attempt in range(2):
            headers = {
                "Authorization": f"Bearer {self._access_token()}",
                "Accept": "application/json",
            }
            if json_body is not None:
                headers["Content-Type"] = "application/json"
            resp = requests.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_body,
                timeout=45,
            )
            if resp.status_code == 401 and attempt == 0:
                blob = refresh_access_token(dict(self._load_blob()))
                self._persist_blob(blob)
                continue
            if resp.status_code >= 400:
                raise RuntimeError(f"graph_error_{resp.status_code}: {resp.text[:400]}")
            if resp.status_code == 204 or not resp.content:
                return {}
            return resp.json()
        raise RuntimeError("graph_unauthorized")

    @staticmethod
    def _ms_to_internal(dt_str: str) -> int:
        if not dt_str:
            return 0
        try:
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except Exception:
            return 0

    @staticmethod
    def _addr_header(obj: dict | None) -> str:
        if not obj:
            return ""
        ea = obj.get("emailAddress") or {}
        name = str(ea.get("name") or "").strip()
        addr = str(ea.get("address") or "").strip()
        if name and addr:
            return f"{name} <{addr}>"
        return addr or name

    def get_profile_email(self) -> str:
        data = self._request("GET", "/me", params={"$select": "mail,userPrincipalName"})
        return str(data.get("mail") or data.get("userPrincipalName") or "").strip()

    def list_inbox_thread_summaries(self, max_threads: int = 40) -> List[Dict[str, Any]]:
        max_n = max(1, min(int(max_threads or 40), 50))
        data = self._request(
            "GET",
            "/me/mailFolders/inbox/messages",
            params={
                "$top": max_n,
                "$orderby": "receivedDateTime desc",
                "$select": "id,conversationId,subject,from,receivedDateTime,bodyPreview,isRead,flag",
            },
        )
        items = data.get("value") or []
        # One summary per conversation (latest message)
        seen: set[str] = set()
        out: List[Dict[str, Any]] = []
        for m in items:
            tid = str(m.get("conversationId") or m.get("id") or "").strip()
            if not tid or tid in seen:
                continue
            seen.add(tid)
            mid = str(m.get("id") or "")
            from_v = self._addr_header(m.get("from"))
            flag = m.get("flag") or {}
            out.append(
                {
                    "thread_id": tid,
                    "message_id": mid,
                    "from": from_v,
                    "subject": str(m.get("subject") or ""),
                    "internal_date": self._ms_to_internal(str(m.get("receivedDateTime") or "")),
                    "snippet": str(m.get("bodyPreview") or ""),
                    "unread": not bool(m.get("isRead")),
                    "important": False,
                    "starred": str(flag.get("flagStatus") or "").lower() == "flagged",
                    "label_ids": [],
                    "date": str(m.get("receivedDateTime") or ""),
                }
            )
        return out

    def get_thread_for_ui(self, thread_id: str) -> Dict[str, Any]:
        tid = str(thread_id or "").strip()
        if not tid:
            return {"ok": False, "error": "missing_thread_id"}
        # Escape single quotes in OData filter
        safe = tid.replace("'", "''")
        data = self._request(
            "GET",
            "/me/messages",
            params={
                "$filter": f"conversationId eq '{safe}'",
                "$orderby": "receivedDateTime asc",
                "$top": 50,
                "$select": "id,conversationId,subject,from,toRecipients,receivedDateTime,bodyPreview,body",
            },
        )
        ui_msgs: List[Dict[str, Any]] = []
        for m in data.get("value") or []:
            from_v = self._addr_header(m.get("from"))
            to_list = m.get("toRecipients") or []
            to_v = ", ".join(self._addr_header(x) for x in to_list if x)
            body = m.get("body") or {}
            body_text = str(body.get("content") or "")
            if str(body.get("contentType") or "").lower() == "html":
                import re

                body_text = re.sub(r"<[^>]+>", "", body_text)
            ui_msgs.append(
                {
                    "id": str(m.get("id") or ""),
                    "from": from_v,
                    "to": to_v,
                    "subject": str(m.get("subject") or ""),
                    "internal_date": self._ms_to_internal(str(m.get("receivedDateTime") or "")),
                    "snippet": str(m.get("bodyPreview") or ""),
                    "body_text": body_text.strip(),
                    "is_from_me": self.is_from_account_owner(from_v),
                }
            )
        return {"ok": True, "thread_id": tid, "messages": ui_msgs}

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
        del in_reply_to, references  # Graph reply uses message id path when available
        # Prefer createReply on latest message in conversation when thread_id is a conversation id
        message_id = ""
        if thread_id:
            det = self.get_thread_for_ui(str(thread_id))
            msgs = det.get("messages") or []
            if msgs:
                message_id = str(msgs[-1].get("id") or "")
        if message_id:
            # createReply then send
            draft = self._request("POST", f"/me/messages/{message_id}/createReply")
            draft_id = str(draft.get("id") or "")
            if draft_id:
                self._request(
                    "PATCH",
                    f"/me/messages/{draft_id}",
                    json_body={
                        "body": {"contentType": "Text", "content": body_text or ""},
                    },
                )
                self._request("POST", f"/me/messages/{draft_id}/send")
                return draft_id

        payload = {
            "message": {
                "subject": subject or "(No subject)",
                "body": {"contentType": "Text", "content": body_text or ""},
                "toRecipients": [{"emailAddress": {"address": to_email}}],
            },
            "saveToSentItems": True,
        }
        self._request("POST", "/me/sendMail", json_body=payload)
        return ""
