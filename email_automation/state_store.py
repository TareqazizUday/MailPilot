from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Optional


class StateStore:
    """Very small persistent store used by UI endpoints.

    Schema is created on demand. Data model is intentionally minimal.
    """

    def __init__(self, db_path: str, tenant_id: str):
        self.db_path = db_path
        self.tenant_id = tenant_id or ""
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def _ensure_schema(self) -> None:
        con = self._connect()
        try:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS processed_meta (
                    tenant_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    meta_json TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, message_id)
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS queue_items (
                    tenant_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (tenant_id, message_id)
                )
                """
            )
            con.commit()
        finally:
            con.close()

    def get_processed_meta(self, message_id: str) -> Optional[dict[str, Any]]:
        con = self._connect()
        try:
            row = con.execute(
                "SELECT meta_json FROM processed_meta WHERE tenant_id=? AND message_id=?",
                (self.tenant_id, str(message_id)),
            ).fetchone()
            if not row:
                return None
            try:
                return json.loads(row["meta_json"] or "{}") or {}
            except Exception:
                return None
        finally:
            con.close()

    def list_queue_items(self, limit: int = 10) -> list[dict[str, Any]]:
        con = self._connect()
        try:
            rows = con.execute(
                "SELECT message_id, status, details_json, updated_at FROM queue_items WHERE tenant_id=? "
                "ORDER BY updated_at DESC LIMIT ?",
                (self.tenant_id, int(limit)),
            ).fetchall()
            out: list[dict[str, Any]] = []
            for r in rows:
                try:
                    details = json.loads(r["details_json"] or "{}") or {}
                except Exception:
                    details = {}
                out.append(
                    {
                        "message_id": r["message_id"],
                        "status": r["status"],
                        "updated_at": r["updated_at"],
                        **details,
                    }
                )
            return out
        finally:
            con.close()

    def update_processed_details(self, message_id: str, from_email: str, subject: str) -> None:
        con = self._connect()
        try:
            row = con.execute(
                "SELECT details_json, status FROM queue_items WHERE tenant_id=? AND message_id=?",
                (self.tenant_id, str(message_id)),
            ).fetchone()
            if not row:
                return
            try:
                details = json.loads(row["details_json"] or "{}") or {}
            except Exception:
                details = {}
            if from_email:
                details["from_email"] = from_email
            if subject:
                details["subject"] = subject
            con.execute(
                "UPDATE queue_items SET details_json=?, updated_at=datetime('now') WHERE tenant_id=? AND message_id=?",
                (json.dumps(details, ensure_ascii=False), self.tenant_id, str(message_id)),
            )
            con.commit()
        finally:
            con.close()

