from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from email_automation.settings import Settings
from email_automation.state_store import StateStore


@dataclass(frozen=True)
class PollResult:
    scanned: int
    relevant: int
    sent: int
    drafts: int
    ignored: int
    queued: int


def poll_once(*, settings: Settings, state_store: StateStore, gmail_client: Any) -> PollResult:
    # Shim: no-op
    return PollResult(scanned=0, relevant=0, sent=0, drafts=0, ignored=0, queued=0)


def poll_once_imap(*, settings: Settings, state_store: StateStore) -> PollResult:
    # Shim: no-op
    return PollResult(scanned=0, relevant=0, sent=0, drafts=0, ignored=0, queued=0)

