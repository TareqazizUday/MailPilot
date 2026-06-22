from django.db import migrations


def update_custom_plan_features(apps, schema_editor):
    Plan = apps.get_model("core", "MarketingPricingPlan")
    Plan.objects.filter(plan_code="custom").update(
        features=(
            "<strong>2,000 tokens</strong> + 4 Gmail/SMTP inboxes → <strong>$30/mo</strong>\n"
            "<strong>3,000 tokens</strong> + 5 Gmail/SMTP inboxes → <strong>$40/mo</strong>\n"
            "Or define your own tier (e.g. $50 → 5,000 sends)\n"
            "Provider-aware daily safety caps\n"
            "Telegram & WhatsApp alerts and chat commands\n"
            "Annual billing option\n"
            "Priority onboarding & team seats"
        )
    )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0031_billing_interval"),
    ]

    operations = [
        migrations.RunPython(update_custom_plan_features, migrations.RunPython.noop),
    ]
