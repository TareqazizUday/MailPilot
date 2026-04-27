from __future__ import annotations

import json
import os
import sqlite3
from typing import Any

from django.core.management.base import BaseCommand

from core.models import ProcessedMeta, QueueItem


class Command(BaseCommand):
    help = "One-time migration: import legacy SQLite StateStore (data/state.db) into Django DB tables."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--sqlite-path",
            default=None,
            help="Path to legacy SQLite state.db (default: <BASE_DIR>/data/state.db)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Read and validate but do not write to DB.",
        )

    def handle(self, *args: Any, **opts: Any) -> None:
        from django.conf import settings

        sqlite_path = opts.get("sqlite_path") or os.path.join(str(settings.BASE_DIR), "data", "state.db")
        dry_run = bool(opts.get("dry_run"))

        if not os.path.exists(sqlite_path):
            self.stdout.write(self.style.WARNING(f"SQLite file not found: {sqlite_path}"))
            return

        con = sqlite3.connect(sqlite_path)
        con.row_factory = sqlite3.Row
        try:
            pm_rows = con.execute("SELECT tenant_id, message_id, meta_json FROM processed_meta").fetchall()
            qi_rows = con.execute(
                "SELECT tenant_id, message_id, status, details_json, updated_at FROM queue_items"
            ).fetchall()
        finally:
            con.close()

        pm_created = 0
        qi_created = 0
        pm_seen = 0
        qi_seen = 0

        for r in pm_rows:
            pm_seen += 1
            tenant_id = str(r["tenant_id"] or "")
            message_id = str(r["message_id"] or "")
            try:
                meta = json.loads(r["meta_json"] or "{}") or {}
            except Exception:
                meta = {}
            if not isinstance(meta, dict):
                meta = {}
            if dry_run:
                continue
            _, created = ProcessedMeta.objects.get_or_create(
                tenant_id=tenant_id, message_id=message_id, defaults={"meta_json": meta}
            )
            if created:
                pm_created += 1

        for r in qi_rows:
            qi_seen += 1
            tenant_id = str(r["tenant_id"] or "")
            message_id = str(r["message_id"] or "")
            status = str(r["status"] or "")
            try:
                details = json.loads(r["details_json"] or "{}") or {}
            except Exception:
                details = {}
            if not isinstance(details, dict):
                details = {}
            if dry_run:
                continue
            _, created = QueueItem.objects.get_or_create(
                tenant_id=tenant_id,
                message_id=message_id,
                defaults={"status": status, "details_json": details},
            )
            if created:
                qi_created += 1

        self.stdout.write(
            f"processed_meta: seen={pm_seen} created={pm_created} | queue_items: seen={qi_seen} created={qi_created}"
            + (" (dry-run)" if dry_run else "")
        )

