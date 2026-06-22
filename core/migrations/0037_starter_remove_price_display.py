from __future__ import annotations

from django.db import migrations


def forwards(apps, schema_editor) -> None:
    MarketingPricingPlan = apps.get_model("core", "MarketingPricingPlan")
    MarketingPricingPlan.objects.filter(plan_code="starter").update(
        price_display="",
        price_suffix="",
    )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0036_custom_plan_remove_you_choose"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
