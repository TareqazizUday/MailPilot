from django.db import migrations

_CUSTOM_FEATURES = (
    "<strong>Custom</strong> monthly tokens — set your own limit\n"
    "<strong>Custom</strong> Gmail inboxes — scale as you grow\n"
    "<strong>Custom</strong> SMTP/IMAP mailboxes — flexible slots\n"
    "Live price in the plan builder — no fixed tier\n"
    "Provider-aware daily safety caps\n"
    "Telegram & WhatsApp alerts and chat commands\n"
    "Annual or monthly billing in the builder\n"
    "Priority onboarding & team seats"
)


def update_custom_plan_features(apps, schema_editor):
    Plan = apps.get_model("core", "MarketingPricingPlan")
    Plan.objects.filter(plan_code="custom").update(features=_CUSTOM_FEATURES)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0033_customplanquote_currency"),
    ]

    operations = [
        migrations.RunPython(update_custom_plan_features, migrations.RunPython.noop),
    ]
