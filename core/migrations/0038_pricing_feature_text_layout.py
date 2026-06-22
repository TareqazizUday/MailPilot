from __future__ import annotations

from django.db import migrations

_STARTER_FEATURES = """80 tokens lifetime (up to 20 auto-sent replies)
20 auto-sends/day safety cap while active
1 connected inbox (Gmail or IMAP)
Basic KB: 1 crawl or upload
Keyword filter + LLM relevance
Dashboard queue & unlimited drafts
No Telegram or WhatsApp"""

_PRO_FEATURES = """1,000 tokens per month (up to 200 auto-sent replies)
Up to 3 active Gmail or SMTP/IMAP inboxes
100 auto-sends/day/inbox safety cap
Full AI knowledge base (website crawl + file upload)
Multi Gmail OAuth + SMTP/IMAP mailbox support
Per-user encrypted credentials
Telegram & WhatsApp alerts and commands"""


def forwards(apps, schema_editor) -> None:
    MarketingPricingPlan = apps.get_model("core", "MarketingPricingPlan")
    MarketingPricingPlan.objects.filter(plan_code="starter").update(features=_STARTER_FEATURES)
    MarketingPricingPlan.objects.filter(plan_code="pro").update(features=_PRO_FEATURES)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0037_starter_remove_price_display"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
