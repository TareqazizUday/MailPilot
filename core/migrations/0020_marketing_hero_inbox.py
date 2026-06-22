from django.db import migrations, models

DEFAULT_HERO_SETTINGS = {
    "card_title": "MailPilot — Live Inbox",
    "card_icon_class": "fa-solid fa-inbox",
}

DEFAULT_HERO_INBOX_ITEMS = [
    {
        "sender_name": "Alice Kim",
        "sender_context": "Product Inquiry",
        "subject": "What pricing plans do you offer for enterprise?",
        "avatar_initials": "AK",
        "avatar_color_start": "#4f6ef7",
        "avatar_color_end": "#a78bfa",
        "badge_type": "replied",
        "badge_label": "✓ Auto-Replied",
        "sort_order": 1,
    },
    {
        "sender_name": "Raj Joshi",
        "sender_context": "Support Request",
        "subject": "How do I integrate the Gmail OAuth flow?",
        "avatar_initials": "RJ",
        "avatar_color_start": "#38bdf8",
        "avatar_color_end": "#4f6ef7",
        "badge_type": "rag",
        "badge_label": "RAG Enhanced",
        "badge_icon_class": "fa-solid fa-brain",
        "sort_order": 2,
    },
    {
        "sender_name": "Maria Lopez",
        "sender_context": "Partnership",
        "subject": "Interested in co-marketing collaboration...",
        "avatar_initials": "ML",
        "avatar_color_start": "#a78bfa",
        "avatar_color_end": "#ec4899",
        "badge_type": "pending",
        "badge_label": "⏳ In Queue",
        "sort_order": 3,
    },
    {
        "sender_name": "Newsletter",
        "sender_context": "Daily Digest",
        "subject": "Top stories in AI this week...",
        "avatar_initials": "NO",
        "avatar_color_start": "#94a3b8",
        "avatar_color_end": "#475569",
        "badge_type": "skipped",
        "badge_label": "— Skipped",
        "sort_order": 4,
    },
]


def seed_hero_inbox(apps, schema_editor):
    Settings = apps.get_model("core", "MarketingHeroSettings")
    Item = apps.get_model("core", "MarketingHeroInboxItem")
    if not Settings.objects.exists():
        Settings.objects.create(singleton_key=1, **DEFAULT_HERO_SETTINGS)
    if Item.objects.exists():
        return
    Item.objects.bulk_create(
        [
            Item(**row, is_published=True, show_on_homepage=True)
            for row in DEFAULT_HERO_INBOX_ITEMS
        ]
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0019_marketing_pricing"),
    ]

    operations = [
        migrations.CreateModel(
            name="MarketingHeroSettings",
            fields=[
                ("singleton_key", models.PositiveSmallIntegerField(default=1, primary_key=True, serialize=False)),
                ("card_title", models.CharField(default="MailPilot — Live Inbox", max_length=120)),
                (
                    "card_icon_class",
                    models.CharField(
                        default="fa-solid fa-inbox",
                        help_text="Font Awesome class for the card title icon",
                        max_length=80,
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "hero inbox card",
                "verbose_name_plural": "hero inbox card",
                "db_table": "core_marketingherosettings",
            },
        ),
        migrations.CreateModel(
            name="MarketingHeroInboxItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sender_name", models.CharField(max_length=80)),
                (
                    "sender_context",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Short label after the name, e.g. Product Inquiry",
                        max_length=80,
                    ),
                ),
                ("subject", models.CharField(max_length=200)),
                ("avatar_initials", models.CharField(default="AK", max_length=4)),
                ("avatar_color_start", models.CharField(default="#4f6ef7", max_length=7)),
                ("avatar_color_end", models.CharField(default="#a78bfa", max_length=7)),
                (
                    "badge_type",
                    models.CharField(
                        choices=[
                            ("replied", "Auto-replied"),
                            ("rag", "RAG enhanced"),
                            ("pending", "In queue"),
                            ("skipped", "Skipped"),
                        ],
                        default="replied",
                        max_length=16,
                    ),
                ),
                ("badge_label", models.CharField(default="✓ Auto-Replied", max_length=40)),
                (
                    "badge_icon_class",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Optional Font Awesome icon before badge text (e.g. fa-solid fa-brain)",
                        max_length=80,
                    ),
                ),
                ("sort_order", models.PositiveIntegerField(db_index=True, default=0)),
                ("is_published", models.BooleanField(db_index=True, default=True)),
                (
                    "show_on_homepage",
                    models.BooleanField(default=True, help_text="Show on landing page hero inbox card"),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "hero inbox row",
                "verbose_name_plural": "hero inbox rows",
                "db_table": "core_marketingheroinboxitem",
                "ordering": ["sort_order", "id"],
            },
        ),
        migrations.RunPython(seed_hero_inbox, migrations.RunPython.noop),
    ]
