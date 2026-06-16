from django.db import migrations, models


DEFAULT_SETTINGS = {
    "section_tag": "Pricing",
    "title_lead": "Simple plans for",
    "title_highlight": "every inbox size",
    "intro": (
        "Simple token plans for every inbox size. Connect your inbox in Setup, "
        "then let MailPilot draft or send safely."
    ),
    "demo_note": (
        "Starter: 20 auto-sends total (80 tokens lifetime). Pro: monthly billing via Stripe. "
        "Draft mode does not use tokens."
    ),
}

_STARTER_FEATURES = """<strong>80 tokens</strong> lifetime (up to <strong>20</strong> auto-sent replies)
<strong>20 auto-sends/day</strong> safety cap while active
1 connected inbox (Gmail or IMAP)
Basic KB: 1 crawl or upload
Keyword filter + LLM relevance
Dashboard queue & unlimited drafts
No Telegram or WhatsApp"""

_PRO_FEATURES = """<strong>1,000 tokens</strong> per month (up to 200 auto-sent replies)
Up to 3 active Gmail or SMTP/IMAP inboxes
100 auto-sends/day/inbox safety cap
Full AI knowledge base (website crawl + file upload)
Multi Gmail OAuth + SMTP/IMAP mailbox support
Per-user encrypted credentials
Telegram & WhatsApp alerts and commands"""

_CUSTOM_FEATURES = """<strong>2,000 tokens</strong> + 4 Gmail/SMTP inboxes → <strong>$30/mo</strong>
<strong>3,000 tokens</strong> + 6 Gmail/SMTP inboxes → <strong>$40/mo</strong>
Or define your own tier (e.g. $50 → 5,000 sends)
Provider-aware daily safety caps
Telegram & WhatsApp alerts and chat commands
Annual billing option
Priority onboarding & team seats"""

DEFAULT_PLANS = [
    {
        "plan_code": "starter",
        "tier_label": "Starter",
        "ribbon_type": "free",
        "ribbon_label": "Free",
        "ribbon_icon_class": "fa-solid fa-circle-check",
        "price_display": "$0",
        "price_suffix": "/trial",
        "period_text": "20 auto-sends total · then upgrade",
        "description": (
            "Connect one inbox, test AI replies, and keep draft mode unlimited. "
            "After 20 auto-sent emails, upgrade to Pro or Custom."
        ),
        "features": _STARTER_FEATURES,
        "cta_label": "Start free trial",
        "cta_label_authenticated": "View my trial",
        "cta_label_starter_expired": "Upgrade required",
        "cta_style": "secondary",
        "is_featured": False,
        "sort_order": 1,
    },
    {
        "plan_code": "pro",
        "tier_label": "Pro",
        "top_badge": "50% launch offer",
        "ribbon_type": "soon",
        "ribbon_label": "Demo checkout on localhost",
        "ribbon_icon_class": "fa-solid fa-bolt",
        "price_display": "$20",
        "price_suffix": "/mo",
        "price_was": "$40",
        "price_save_label": "Save 50%",
        "period_text": "Billed monthly · cancel anytime",
        "description": (
            "Production volume for growing teams—RAG knowledge base, polling, and reliable auto-send limits."
        ),
        "features": _PRO_FEATURES,
        "cta_label": "Get Pro",
        "cta_style": "primary",
        "is_featured": True,
        "sort_order": 2,
    },
    {
        "plan_code": "custom",
        "tier_label": "Custom",
        "top_badge": "Most popular",
        "ribbon_type": "soon",
        "ribbon_label": "Build your plan",
        "ribbon_icon_class": "fa-solid fa-sliders",
        "price_display": "You choose",
        "period_text": "Live price as you adjust",
        "description": (
            "Slide tokens and inbox count — see your monthly price instantly, then checkout or contact us."
        ),
        "features": _CUSTOM_FEATURES,
        "cta_label": "Build Custom plan",
        "cta_style": "secondary",
        "is_featured": False,
        "sort_order": 3,
    },
]


def seed_pricing(apps, schema_editor):
    Settings = apps.get_model("core", "MarketingPricingSettings")
    Plan = apps.get_model("core", "MarketingPricingPlan")
    if not Settings.objects.exists():
        Settings.objects.create(singleton_key=1, **DEFAULT_SETTINGS)
    if Plan.objects.exists():
        return
    Plan.objects.bulk_create(
        [
            Plan(
                **row,
                is_published=True,
                show_on_homepage=True,
            )
            for row in DEFAULT_PLANS
        ]
    )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0018_marketing_review"),
    ]

    operations = [
        migrations.CreateModel(
            name="MarketingPricingSettings",
            fields=[
                ("singleton_key", models.PositiveSmallIntegerField(default=1, primary_key=True, serialize=False)),
                ("section_tag", models.CharField(default="Pricing", max_length=40)),
                ("title_lead", models.CharField(default="Simple plans for", max_length=120)),
                ("title_highlight", models.CharField(default="every inbox size", max_length=120)),
                ("intro", models.TextField(default="Simple token plans for every inbox size. Connect your inbox in Setup, then let MailPilot draft or send safely.")),
                ("demo_note", models.TextField(default="Starter: 20 auto-sends total (80 tokens lifetime). Pro: monthly billing via Stripe. Draft mode does not use tokens.")),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "pricing page",
                "verbose_name_plural": "pricing page",
                "db_table": "core_marketingpricingsettings",
            },
        ),
        migrations.CreateModel(
            name="MarketingPricingPlan",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "plan_code",
                    models.CharField(
                        choices=[("starter", "Starter"), ("pro", "Pro"), ("custom", "Custom")],
                        max_length=16,
                        unique=True,
                    ),
                ),
                ("tier_label", models.CharField(max_length=40)),
                (
                    "top_badge",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Optional pill above card, e.g. 50% launch offer",
                        max_length=80,
                    ),
                ),
                (
                    "ribbon_type",
                    models.CharField(
                        blank=True,
                        choices=[("", "None"), ("free", "Free badge"), ("soon", "Soon / info badge")],
                        default="",
                        max_length=8,
                    ),
                ),
                ("ribbon_label", models.CharField(blank=True, default="", max_length=80)),
                ("ribbon_icon_class", models.CharField(blank=True, default="fa-solid fa-bolt", max_length=80)),
                ("price_display", models.CharField(help_text='Main price, e.g. $0, $20, or "You choose"', max_length=40)),
                ("price_suffix", models.CharField(blank=True, default="", help_text="Suffix in smaller text, e.g. /mo", max_length=24)),
                ("price_was", models.CharField(blank=True, default="", help_text="Strikethrough compare price, e.g. $40", max_length=24)),
                ("price_save_label", models.CharField(blank=True, default="", help_text='e.g. "Save 50%"', max_length=40)),
                ("period_text", models.CharField(max_length=160)),
                ("description", models.TextField()),
                ("features", models.TextField(help_text="One bullet per line. HTML like <strong> is allowed.")),
                ("cta_label", models.CharField(help_text="Button label for visitors", max_length=80)),
                (
                    "cta_label_authenticated",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Starter: label when logged in (e.g. View my trial)",
                        max_length=80,
                    ),
                ),
                (
                    "cta_label_starter_expired",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Starter: label when trial expired",
                        max_length=80,
                    ),
                ),
                (
                    "cta_style",
                    models.CharField(
                        choices=[("primary", "Primary"), ("secondary", "Secondary")],
                        default="secondary",
                        max_length=12,
                    ),
                ),
                (
                    "is_featured",
                    models.BooleanField(
                        default=False,
                        help_text="Highlighted card (selected by default on the page)",
                    ),
                ),
                (
                    "sort_order",
                    models.PositiveIntegerField(
                        db_index=True,
                        default=0,
                        help_text="Display order (1, 2, 3… — lower numbers appear first).",
                    ),
                ),
                ("is_published", models.BooleanField(db_index=True, default=True)),
                (
                    "show_on_homepage",
                    models.BooleanField(
                        default=True,
                        help_text="Show on landing page pricing section",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "pricing plan",
                "verbose_name_plural": "pricing plans",
                "db_table": "core_marketingpricingplan",
                "ordering": ["sort_order", "id"],
            },
        ),
        migrations.RunPython(seed_pricing, migrations.RunPython.noop),
    ]
