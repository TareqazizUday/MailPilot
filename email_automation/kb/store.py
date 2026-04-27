from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Iterable
from typing import Any, Tuple
from urllib.parse import quote_plus

import psycopg
from email_automation.settings import Settings
from pgvector.psycopg import register_vector

log = logging.getLogger("mailpilot.kb.store")

_KB_TABLE = "mailpilot_kb_chunks"
_TENANT_DOC_INDEX = "mailpilot_kb_chunks_tenant_doc_idx"
_HNSW_INDEX = "mailpilot_kb_chunks_embedding_hnsw_idx"

_schema_lock = threading.Lock()
_ensured_table: set[tuple[str, int]] = set()
_hnsw_tried: set[str] = set()


def _django_dsn_from_env() -> str:
    u = (os.environ.get("DJANGO_DB_USER") or "").strip()
    p = os.environ.get("DJANGO_DB_PASSWORD") or ""
    h = (os.environ.get("DJANGO_DB_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    port = (os.environ.get("DJANGO_DB_PORT") or "5432").strip() or "5432"
    db = (os.environ.get("DJANGO_DB_NAME") or "mailpilot").strip() or "mailpilot"
    if not u:
        return ""
    return f"postgresql://{quote_plus(u)}:{quote_plus(p)}@{h}:{port}/{db}"


def _resolve_dsn(settings: Settings) -> str:
    dsn = (getattr(settings, "VECTOR_DB_DSN", None) or "").strip()
    if dsn:
        return dsn
    dsn = (os.environ.get("VECTOR_DB_DSN") or "").strip()
    if dsn:
        return dsn
    return _django_dsn_from_env().strip()


def is_vector_db_configured(settings: Settings) -> bool:
    """True if a KB DSN can be resolved (VECTOR_DB_DSN, env, or same DB as DJANGO_*).

    The PostgreSQL instance must have the `vector` extension; run `CREATE EXTENSION vector;`
    once (superuser) — see `docs/kb-pgvector-setup.md`.
    """
    return bool(_resolve_dsn(settings).strip())


class VectorStore:
    """KB chunks persisted in PostgreSQL with pgvector (cosine HNSW index for search)."""

    def __init__(self, *, settings: Settings, tenant_id: str):
        self.settings = settings
        self.tenant_id = tenant_id or ""
        self._dsn = _resolve_dsn(settings)
        self._dim = int(getattr(settings, "EMBEDDING_DIM", 1536) or 1536)

    def _connect(self) -> psycopg.Connection:
        if not self._dsn:
            raise RuntimeError(
                "No vector/KB connection string. Set VECTOR_DB_DSN or DJANGO_DB_* in .env. "
                "The database must have the pgvector extension: CREATE EXTENSION vector;"
            )
        conn = psycopg.connect(self._dsn)
        try:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        except Exception as e:
            msg = str(e)
            if "vector" in msg or "not available" in msg or "FeatureNotSupported" in type(e).__name__:
                raise RuntimeError(
                    "The pgvector extension is not available on this PostgreSQL server, or the user "
                    "cannot create it. A superuser must run: CREATE EXTENSION vector; "
                    "— see https://github.com/pgvector/pgvector#installation and docs/kb-pgvector-setup.md"
                ) from e
            raise
        register_vector(conn)
        return conn

    def _ensure_schema(self, conn: psycopg.Connection) -> None:
        tkey = (self._dsn, self._dim)
        with _schema_lock:
            if tkey in _ensured_table:
                return

        safe_dim = int(self._dim) if 1 <= self._dim <= 16000 else 1536
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {_KB_TABLE} (
                        tenant_id text NOT NULL,
                        doc_id text NOT NULL,
                        chunk_id int NOT NULL,
                        source text NOT NULL DEFAULT '',
                        url text NOT NULL DEFAULT '',
                        title text NOT NULL DEFAULT '',
                        metadata_json jsonb NOT NULL DEFAULT '{{}}',
                        chunk_text text NOT NULL,
                        embedding vector({safe_dim}) NOT NULL,
                        created_at timestamptz NOT NULL DEFAULT now(),
                        updated_at timestamptz NOT NULL DEFAULT now(),
                        PRIMARY KEY (tenant_id, doc_id, chunk_id)
                    );
                    """
                )
                cur.execute(
                    f"CREATE INDEX IF NOT EXISTS {_TENANT_DOC_INDEX} ON {_KB_TABLE} (tenant_id, doc_id);"
                )

        if self._dsn not in _hnsw_tried:
            _hnsw_tried.add(self._dsn)
            try:
                aconn = psycopg.connect(self._dsn, autocommit=True)
                try:
                    with aconn.cursor() as cur:
                        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                    register_vector(aconn)
                    with aconn.cursor() as cur:
                        cur.execute(
                            f"""
                            CREATE INDEX IF NOT EXISTS {_HNSW_INDEX}
                            ON {_KB_TABLE} USING hnsw (embedding vector_cosine_ops)
                            WITH (m = 16, ef_construction = 64);
                            """
                        )
                finally:
                    aconn.close()
            except Exception as e:
                log.info("HNSW index skipped (optional): %s", e)

        with _schema_lock:
            _ensured_table.add(tkey)

    def upsert_document_with_chunks(
        self,
        *,
        doc_id: str,
        source: str,
        url: str,
        title: str,
        metadata: dict[str, Any],
        chunks: Iterable[Tuple[str, list[float]]],
    ) -> None:
        pairs = list(chunks)
        if not self.tenant_id or not (doc_id or "").strip():
            return
        meta = metadata if isinstance(metadata, dict) else {}
        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        f"DELETE FROM {_KB_TABLE} WHERE tenant_id = %s AND doc_id = %s",
                        (self.tenant_id, doc_id),
                    )
                    for i, (text, emb) in enumerate(pairs):
                        if len(emb) != self._dim:
                            raise ValueError(
                                f"Embedding dim {len(emb)} != EMBEDDING_DIM {self._dim}."
                            )
                        cur.execute(
                            f"""
                            INSERT INTO {_KB_TABLE} (
                                tenant_id, doc_id, chunk_id, source, url, title, metadata_json, chunk_text, embedding, updated_at
                            ) VALUES (
                                %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, now()
                            )
                            """,
                            (
                                self.tenant_id,
                                doc_id,
                                i,
                                str(source)[:2000],
                                str(url)[:4000],
                                str(title)[:2000],
                                json.dumps(meta, ensure_ascii=False),
                                str(text),
                                emb,
                            ),
                        )

    def stats(self) -> dict[str, Any]:
        if not self._dsn or not self.tenant_id:
            return {"documents": 0, "chunks": 0}
        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        COALESCE(COUNT(DISTINCT doc_id), 0)::int,
                        COALESCE(COUNT(*), 0)::int
                    FROM {_KB_TABLE}
                    WHERE tenant_id = %s
                    """,
                    (self.tenant_id,),
                )
                row = cur.fetchone()
        if not row:
            return {"documents": 0, "chunks": 0}
        return {"documents": int(row[0]), "chunks": int(row[1])}

    def clear(self) -> dict[str, int]:
        """
        Delete all KB chunks for this tenant_id.

        Returns {"deleted_chunks": int, "deleted_documents": int}.
        """
        if not self._dsn or not self.tenant_id:
            return {"deleted_chunks": 0, "deleted_documents": 0}
        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT COALESCE(COUNT(DISTINCT doc_id), 0)::int, COALESCE(COUNT(*), 0)::int FROM {_KB_TABLE} WHERE tenant_id = %s",
                        (self.tenant_id,),
                    )
                    row = cur.fetchone() or (0, 0)
                    deleted_docs = int(row[0] or 0)
                    deleted_chunks = int(row[1] or 0)
                    cur.execute(
                        f"DELETE FROM {_KB_TABLE} WHERE tenant_id = %s",
                        (self.tenant_id,),
                    )
        return {"deleted_chunks": deleted_chunks, "deleted_documents": deleted_docs}

    def export_documents(self, *, limit: int = 200) -> list[dict[str, Any]]:
        """
        Export KB docs for this tenant by stitching chunk_text in chunk_id order.

        Returns a list of dicts: {doc_id, source, url, title, text, metadata}.
        """
        if not self._dsn or not self.tenant_id:
            return []
        lim = max(1, min(int(limit or 200), 2000))
        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        doc_id,
                        MAX(source) as source,
                        MAX(url) as url,
                        MAX(title) as title,
                        MAX(metadata_json) as metadata_json,
                        STRING_AGG(chunk_text, '' ORDER BY chunk_id) as full_text
                    FROM {_KB_TABLE}
                    WHERE tenant_id = %s
                    GROUP BY doc_id
                    ORDER BY MAX(updated_at) DESC
                    LIMIT %s
                    """,
                    (self.tenant_id, lim),
                )
                rows = cur.fetchall() or []
        out: list[dict[str, Any]] = []
        for r in rows:
            meta = r[4]
            if meta is not None and not isinstance(meta, dict):
                try:
                    meta = json.loads(meta) if isinstance(meta, (bytes, str)) else {}
                except Exception:
                    meta = {}
            if not isinstance(meta, dict):
                meta = {}
            out.append(
                {
                    "doc_id": r[0],
                    "source": r[1] or "",
                    "url": r[2] or "",
                    "title": r[3] or "",
                    "metadata": meta,
                    "text": r[5] or "",
                }
            )
        return out

    def search_by_embedding(
        self,
        query_embedding: list[float],
        *,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        if not self._dsn or not self.tenant_id:
            return []
        if len(query_embedding) != self._dim:
            raise ValueError(
                f"query_embedding len {len(query_embedding)} != EMBEDDING_DIM {self._dim}"
            )
        k = max(1, int(limit))
        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        doc_id, chunk_id, source, url, title, metadata_json, chunk_text,
                        (embedding <=> %s) AS distance
                    FROM {_KB_TABLE}
                    WHERE tenant_id = %s
                    ORDER BY embedding <=> %s
                    LIMIT %s
                    """,
                    (query_embedding, self.tenant_id, query_embedding, k),
                )
                rows = cur.fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            m = r[5]
            if m is not None and not isinstance(m, dict):
                try:
                    m = json.loads(m) if isinstance(m, (bytes, str)) else {}
                except Exception:
                    m = {}
            if not isinstance(m, dict):
                m = {}
            out.append(
                {
                    "doc_id": r[0],
                    "chunk_id": int(r[1]),
                    "source": r[2],
                    "url": r[3],
                    "title": r[4],
                    "metadata": m,
                    "chunk_text": r[6],
                    "distance": float(r[7]) if r[7] is not None else 0.0,
                }
            )
        return out
