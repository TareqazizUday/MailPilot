from __future__ import annotations

from django.db import migrations


# Recovery SQL for Postgres only (uses `ADD COLUMN IF NOT EXISTS`, `bigserial`,
# `jsonb`, `timestamptz`, `NOW()`). On non-Postgres backends (e.g. SQLite used
# for local dev preview) the table created by 0005 is already correct, so this
# migration is a safe no-op there.
_PG_SQL = [
    """
    ALTER TABLE IF EXISTS core_queueitem
        ADD COLUMN IF NOT EXISTS id bigserial PRIMARY KEY
    """,
    """
    ALTER TABLE IF EXISTS core_queueitem
        ADD COLUMN IF NOT EXISTS tenant_id varchar(64) NOT NULL DEFAULT ''
    """,
    """
    ALTER TABLE IF EXISTS core_queueitem
        ADD COLUMN IF NOT EXISTS message_id varchar(255) NOT NULL DEFAULT ''
    """,
    """
    ALTER TABLE IF EXISTS core_queueitem
        ADD COLUMN IF NOT EXISTS status varchar(32) NOT NULL DEFAULT ''
    """,
    """
    ALTER TABLE IF EXISTS core_queueitem
        ADD COLUMN IF NOT EXISTS details_json jsonb NOT NULL DEFAULT '{}'::jsonb
    """,
    """
    ALTER TABLE IF EXISTS core_queueitem
        ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT NOW()
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_queueitem_tenant_message
        ON core_queueitem (tenant_id, message_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_queueitem_tenant_updated
        ON core_queueitem (tenant_id, updated_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS core_queueitem_tenant_id_idx
        ON core_queueitem (tenant_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS core_queueitem_status_idx
        ON core_queueitem (status)
    """,
]


def _apply_pg_recovery(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cur:
        for stmt in _PG_SQL:
            cur.execute(stmt)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0005_processedmeta_queueitem"),
    ]

    operations = [
        migrations.RunPython(_apply_pg_recovery, migrations.RunPython.noop),
    ]

