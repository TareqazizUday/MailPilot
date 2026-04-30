from __future__ import annotations

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0005_processedmeta_queueitem"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                # If someone previously created an empty `core_queueitem` table (0 columns)
                # or faked the migration, this brings the schema back in line with the model.
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
            ],
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]

