from __future__ import annotations

from typing import Any, Optional

from core.models import ProcessedMeta, QueueItem


class StateStore:
    """DB-backed store used by UI endpoints.

    Previously this used a per-project SQLite file. It now uses the Django database.
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
