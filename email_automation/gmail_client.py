from __future__ import annotations

from typing import Any, Dict, List, Tuple

from email_automation.settings import Settings


class GmailClient:
    """Minimal Gmail client shim.

    This avoids import-time failures; real Gmail API operations are out of scope here.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    def list_inbox_thread_summaries(self, max_threads: int = 40) -> List[Dict[str, Any]]:
        return []

    def get_thread_for_ui(self, thread_id: str) -> Dict[str, Any]:
        return {"thread_id": thread_id, "messages": []}

    def get_message_from_and_subject(self, message_id: str) -> Tuple[str, str]:
        return "", ""

