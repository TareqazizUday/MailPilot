from django.db import migrations


class Migration(migrations.Migration):
    """Drop orphan currency columns left after reverted geo-pricing work."""

    dependencies = [
        ("core", "0029_marketingpricingplan_yearly"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "ALTER TABLE core_customplanquote "
                "DROP COLUMN IF EXISTS currency;"
                "ALTER TABLE core_customplanquote "
                "DROP COLUMN IF EXISTS fx_rate;"
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
