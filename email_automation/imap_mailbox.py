from __future__ import annotations

from typing import Any, Dict, List, Optional

from email_automation.settings import Settings


def imap_inbox_ready(settings: Settings) -> bool:
    host = (settings.IMAP_HOST or "").strip()
    user = (settings.IMAP_USERNAME or "").strip()
    pw = settings.IMAP_PASSWORD
    return bool(host and user and pw and (pw.get_secret_value() or "").strip())


class ImapMailbox:
    """Minimal IMAP shim used by the UI endpoints.

    Real IMAP operations are not implemented in this compatibility package.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    def list_inbox_summaries(self, max_threads: int = 40) -> List[Dict[str, Any]]:
        return []

    def get_thread_for_ui(self, uid: int) -> Dict[str, Any]:
        return {"uid": uid, "messages": []}

    def close(self) -> None:
        return

    def __enter__(self) -> "ImapMailbox":
        return self

    def __exit__(self, exc_type, exc, tb) -> Optional[bool]:
        self.close()
        return None

