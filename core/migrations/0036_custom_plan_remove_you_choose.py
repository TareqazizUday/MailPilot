from __future__ import annotations

from django.db import migrations


def forwards(apps, schema_editor) -> None:
    MarketingPricingPlan = apps.get_model("core", "MarketingPricingPlan")
    MarketingPricingPlan.objects.filter(plan_code="custom", price_display="You choose").update(price_display="")


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0035_strip_em_dash_content"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
