from django.db import migrations


def clear_pro_demo_ribbon(apps, schema_editor):
    MarketingPricingPlan = apps.get_model("core", "MarketingPricingPlan")
    MarketingPricingPlan.objects.filter(
        plan_code="pro",
        ribbon_label="Demo checkout on localhost",
    ).update(ribbon_type="", ribbon_label="", ribbon_icon_class="")


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0041_paypal_sandbox_live_credentials"),
    ]

    operations = [
        migrations.RunPython(clear_pro_demo_ribbon, migrations.RunPython.noop),
    ]
