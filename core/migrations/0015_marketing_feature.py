from django.db import migrations, models


DEFAULT_FEATURES = [
    {
        "title": "Multi-Inbox Intelligence",
        "description": (
            "Automatically reads multiple Gmail and SMTP/IMAP inboxes, filters noise, "
            "and identifies emails that need a response — powered by LLM relevance scoring."
        ),
        "icon_class": "fa-regular fa-envelope",
        "accent_color": "#4f6ef7",
        "sort_order": 1,
    },
    {
        "title": "RAG-Powered Replies",
        "description": (
            "Enriches every AI reply with your knowledge base. Answers are grounded in "
            "your documentation, website content, and FAQs."
        ),
        "icon_class": "fa-solid fa-brain",
        "accent_color": "#a78bfa",
        "sort_order": 2,
    },
    {
        "title": "Secure Multi-Tenancy",
        "description": (
            "Per-user isolation — scoped credentials, tenant-prefixed state, and audit logging built in."
        ),
        "icon_class": "fa-solid fa-shield-halved",
        "accent_color": "#38bdf8",
        "sort_order": 3,
    },
    {
        "title": "Flexible Scheduling",
        "description": (
            "Runs in-process or scales with Celery + Redis. Periodic polling, manual triggers, and queue support."
        ),
        "icon_class": "fa-solid fa-gear",
        "accent_color": "#4ade80",
        "sort_order": 4,
    },
    {
        "title": "Multi Gmail + SMTP/IMAP",
        "description": (
            "Connect multiple Gmail OAuth accounts or SMTP/IMAP mailboxes. Per-user encrypted credentials, "
            "token refresh, and callback handling included."
        ),
        "icon_class": "fa-solid fa-link",
        "accent_color": "#fb923c",
        "sort_order": 5,
    },
    {
        "title": "Telegram, WhatsApp & Dashboard",
        "description": (
            "See queue status in the dashboard and use live Telegram or WhatsApp alerts/chat commands "
            "for sent replies, drafts, errors, and mailbox actions."
        ),
        "icon_class": "fa-solid fa-chart-column",
        "accent_color": "#f472b6",
        "sort_order": 6,
    },
]


def seed_features(apps, schema_editor):
    MarketingFeature = apps.get_model("core", "MarketingFeature")
    if MarketingFeature.objects.exists():
        return
    MarketingFeature.objects.bulk_create(
        [
            MarketingFeature(
                **row,
                is_published=True,
                show_on_homepage=True,
            )
            for row in DEFAULT_FEATURES
        ]
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0014_custom_plan_quote"),
    ]

    operations = [
        migrations.CreateModel(
            name="MarketingFeature",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=120)),
                ("description", models.TextField()),
                (
                    "icon_class",
                    models.CharField(
                        default="fa-solid fa-star",
                        help_text="Font Awesome class, e.g. fa-solid fa-brain",
                        max_length=80,
                    ),
                ),
                (
                    "accent_color",
                    models.CharField(
                        default="#4f6ef7",
                        help_text="Hex color for card accent, e.g. #4f6ef7",
                        max_length=7,
                    ),
                ),
                ("sort_order", models.PositiveIntegerField(db_index=True, default=0)),
                ("is_published", models.BooleanField(db_index=True, default=True)),
                (
                    "show_on_homepage",
                    models.BooleanField(default=True, help_text="Show on landing page features section"),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "marketing feature",
                "verbose_name_plural": "marketing features",
                "db_table": "core_marketingfeature",
                "ordering": ["sort_order", "id"],
            },
        ),
        migrations.RunPython(seed_features, migrations.RunPython.noop),
    ]
