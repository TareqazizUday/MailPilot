from django.db import migrations, models

DEFAULT_FAQ_SETTINGS = {
    "section_tag": "FAQ",
    "title_lead": "Common",
    "title_highlight": "questions",
    "intro_html": (
        'Quick answers about setup, routing, knowledge base, and billing. Still stuck? '
        'Use the <a href="#contact" style="color:#a5b4fc;">contact form</a> on this page.'
    ),
}

DEFAULT_FAQ_ITEMS = [
    {
        "question": "What does MailPilot do?",
        "answer_html": (
            "MailPilot connects to your Gmail or IMAP inbox, filters incoming mail with keywords "
            "and AI relevance, grounds replies in your knowledge base, and can send or draft "
            "responses automatically."
        ),
        "icon_class": "fa-solid fa-envelope",
        "sort_order": 1,
    },
    {
        "question": "Does it reply to every email?",
        "answer_html": (
            "No. You set <strong>keywords</strong> and a <strong>relevance threshold</strong> so only "
            "service-related messages are handled. Unrelated mail is ignored. Start with "
            "<strong>draft</strong> mode to review before enabling auto-send."
        ),
        "icon_class": "fa-solid fa-filter",
        "sort_order": 2,
    },
    {
        "question": "Gmail or SMTP/IMAP—which should I use?",
        "answer_html": (
            "<strong>Gmail OAuth</strong> is the fastest setup for Google Workspace or personal Gmail. "
            "Use <strong>SMTP + IMAP</strong> for other providers. Pro and Custom plans can run multiple "
            "active mailboxes, and each connection can be tested in Setup before going live."
        ),
        "icon_class": "fa-brands fa-google",
        "sort_order": 3,
    },
    {
        "question": "How does the knowledge base work?",
        "answer_html": (
            "Upload JSON or text, or crawl your website. MailPilot finds the best matching content "
            "and uses it to ground each AI reply in your real business information."
        ),
        "icon_class": "fa-solid fa-brain",
        "sort_order": 4,
    },
    {
        "question": "Is there a free plan?",
        "answer_html": (
            "Yes. <strong>Starter</strong> is a free trial: one inbox and up to "
            "<strong>20 auto-sent emails</strong> total (80 tokens). When the trial ends, upgrade to "
            "Pro (Stripe) or contact us for a Custom plan."
        ),
        "icon_class": "fa-solid fa-gift",
        "sort_order": 5,
    },
    {
        "question": "How is my data protected?",
        "answer_html": (
            'Credentials and API keys are stored encrypted per account. See our '
            '<a href="/privacy">Privacy Policy</a> for more detail.'
        ),
        "icon_class": "fa-solid fa-shield-halved",
        "sort_order": 6,
    },
    {
        "question": "How do paid plans work?",
        "answer_html": (
            "<strong>Pro</strong> uses Stripe Checkout ($20/mo when configured). "
            "<strong>Custom</strong> lets you set tokens and inboxes on the "
            '<a href="/pricing/custom">plan builder</a> — pay via Stripe or contact us for a manual quote.'
        ),
        "icon_class": "fa-solid fa-credit-card",
        "sort_order": 7,
    },
]


def seed_faq(apps, schema_editor):
    Settings = apps.get_model("core", "MarketingFaqSettings")
    Item = apps.get_model("core", "MarketingFaqItem")
    if not Settings.objects.exists():
        Settings.objects.create(singleton_key=1, **DEFAULT_FAQ_SETTINGS)
    if Item.objects.exists():
        return
    Item.objects.bulk_create(
        [Item(**row, is_published=True, show_on_homepage=True) for row in DEFAULT_FAQ_ITEMS]
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0020_marketing_hero_inbox"),
    ]

    operations = [
        migrations.CreateModel(
            name="MarketingFaqSettings",
            fields=[
                ("singleton_key", models.PositiveSmallIntegerField(default=1, primary_key=True, serialize=False)),
                ("section_tag", models.CharField(default="FAQ", max_length=40)),
                ("title_lead", models.CharField(default="Common", max_length=80)),
                ("title_highlight", models.CharField(default="questions", max_length=80)),
                (
                    "intro_html",
                    models.TextField(
                        blank=True,
                        default="",
                        help_text="Short intro under the title. Basic HTML allowed (e.g. links).",
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "FAQ page",
                "verbose_name_plural": "FAQ page",
                "db_table": "core_marketingfaqsettings",
            },
        ),
        migrations.CreateModel(
            name="MarketingFaqItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("question", models.CharField(max_length=200)),
                (
                    "answer_html",
                    models.TextField(help_text="Answer body. Basic HTML allowed (strong, a, etc.)."),
                ),
                (
                    "icon_class",
                    models.CharField(
                        default="fa-solid fa-circle-question",
                        help_text="Font Awesome class shown before the question",
                        max_length=80,
                    ),
                ),
                ("sort_order", models.PositiveIntegerField(db_index=True, default=0)),
                ("is_published", models.BooleanField(db_index=True, default=True)),
                (
                    "show_on_homepage",
                    models.BooleanField(default=True, help_text="Show on landing page FAQ section"),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "FAQ item",
                "verbose_name_plural": "FAQ items",
                "db_table": "core_marketingfaqitem",
                "ordering": ["sort_order", "id"],
            },
        ),
        migrations.RunPython(seed_faq, migrations.RunPython.noop),
    ]
