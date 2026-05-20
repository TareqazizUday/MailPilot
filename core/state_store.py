from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from django.db import IntegrityError
from django.utils.dateparse import parse_datetime

from core.models import ProcessedMeta, QueueItem

# Actions that must not be processed again (prevents duplicate auto-replies).
_TERMINAL_ACTIONS = frozenset({"sent", "draft", "ignored", "processing", "error"})
_STALE_PROCESSING_MINUTES = 15


class StateStore:
    """DB-backed store used by UI endpoints (Django default database, e.g. PostgreSQL).

    Rows are scoped by tenant_id (string user id).
    """

    def __init__(self, *, tenant_id: str):
        self.tenant_id = tenant_id or ""

    def get_processed_meta(self, message_id: str) -> Optional[dict[str, Any]]:
        row = (
            ProcessedMeta.objects.filter(tenant_id=self.tenant_id, message_id=str(message_id))
            .only("meta_json")
            .first()
        )
        if not row:
            return None
        meta = row.meta_json or {}
        return meta if isinstance(meta, dict) else {}

    def list_queue_items(self, limit: int = 10) -> list[dict[str, Any]]:
        qs = (
            QueueItem.objects.filter(tenant_id=self.tenant_id)
            .order_by("-updated_at")
            .only("message_id", "status", "details_json", "updated_at")[: int(limit)]
        )
        out: list[dict[str, Any]] = []
        for r in qs:
            details = r.details_json if isinstance(r.details_json, dict) else {}
            out.append(
                {
                    "message_id": r.message_id,
                    "status": r.status,
                    "updated_at": r.updated_at.isoformat() if getattr(r, "updated_at", None) else "",
                    **details,
                }
            )
        return out

    def update_processed_details(self, message_id: str, from_email: str, subject: str) -> None:
        row = (
            QueueItem.objects.filter(tenant_id=self.tenant_id, message_id=str(message_id))
            .only("id", "details_json")
            .first()
        )
        if not row:
            return
        details = row.details_json if isinstance(row.details_json, dict) else {}
        changed = False
        if from_email and details.get("from_email") != from_email:
            details["from_email"] = from_email
            changed = True
        if subject and details.get("subject") != subject:
            details["subject"] = subject
            changed = True
        if changed:
            row.details_json = details
            row.save(update_fields=["details_json", "updated_at"])

    def try_claim_message(self, message_id: str, *, extra: Optional[dict[str, Any]] = None) -> bool:
        """Atomically reserve a message before LLM/send.

        Returns True only for the first concurrent poller (APScheduler, IMAP IDLE, manual, Celery).
        """
        if not message_id:
            return False
        mid = str(message_id)
        existing = self.get_processed_meta(mid)
        if existing is not None:
            action = str(existing.get("action") or "")
            if action in _TERMINAL_ACTIONS:
                if action == "processing" and self._processing_claim_is_stale(existing):
                    pass  # allow reclaim below
                else:
                    return False
        meta: dict[str, Any] = {
            "action": "processing",
            "claimed_at": datetime.now(timezone.utc).isoformat(),
        }
        if extra:
            meta.update(extra)
        try:
            ProcessedMeta.objects.create(
                tenant_id=self.tenant_id,
                message_id=mid,
                meta_json=meta,
            )
            return True
        except IntegrityError:
            row = (
                ProcessedMeta.objects.filter(tenant_id=self.tenant_id, message_id=mid)
                .only("meta_json")
                .first()
            )
            if not row:
                return False
            cur = row.meta_json if isinstance(row.meta_json, dict) else {}
            if str(cur.get("action") or "") == "processing" and self._processing_claim_is_stale(cur):
                row.meta_json = meta
                row.save(update_fields=["meta_json"])
                return True
            return False

    @staticmethod
    def _processing_claim_is_stale(meta: dict[str, Any]) -> bool:
        raw = meta.get("claimed_at")
        if not raw:
            return True
        dt = parse_datetime(str(raw))
        if dt is None:
            return True
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
        return age.total_seconds() > _STALE_PROCESSING_MINUTES * 60

    def mark_processed(self, message_id: str, meta: dict[str, Any]) -> None:
        """Upsert ProcessedMeta for this message_id."""
        if not message_id:
            return
        if not isinstance(meta, dict):
            meta = {}
        ProcessedMeta.objects.update_or_create(
            tenant_id=self.tenant_id,
            message_id=str(message_id),
            defaults={"meta_json": meta},
        )

    def mark_processed_aliases(
        self, message_id: str, aliases: list[str], meta: dict[str, Any]
    ) -> None:
        """Record the same outcome under alternate ids (e.g. imap uid + RFC Message-ID)."""
        self.mark_processed(message_id, meta)
        if not isinstance(meta, dict):
            meta = {}
        for alias in aliases:
            aid = str(alias or "").strip()
            if not aid or aid == str(message_id):
                continue
            alias_meta = dict(meta)
            alias_meta["canonical_id"] = str(message_id)
            self.mark_processed(aid, alias_meta)

    def upsert_queue_item(self, message_id: str, *, status: str, details: dict[str, Any]) -> None:
        """Upsert QueueItem used by the Dashboard queue panel."""
        if not message_id:
            return
        if not isinstance(details, dict):
            details = {}
        QueueItem.objects.update_or_create(
            tenant_id=self.tenant_id,
            message_id=str(message_id),
            defaults={"status": str(status or ""), "details_json": details},
        )
