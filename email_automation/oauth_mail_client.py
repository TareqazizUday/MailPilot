"""Resolve Gmail vs Microsoft Graph client from SEND_TRANSPORT / account transport."""
from __future__ import annotations

from typing import Any

from email_automation.settings import Settings


def is_microsoft_transport(transport: str | None = None, *, settings: Settings | None = None) -> bool:
    t = (transport or "").strip()
    if not t and settings is not None:
        t = str(getattr(settings, "SEND_TRANSPORT", "") or "").strip()
    return t == "microsoft_graph"


def build_oauth_mail_client(settings: Settings, *, transport: str | None = None) -> Any:
    """Return GmailClient or MicrosoftClient with the same poll/send UI surface."""
    if is_microsoft_transport(transport, settings=settings):
        from email_automation.microsoft_client import MicrosoftClient

        return MicrosoftClient(settings=settings)
    from email_automation.gmail_client import GmailClient

    return GmailClient(settings=settings)
