from django.db import migrations, models


DEFAULT_STEPS = [
    {
        "title": "Poll inbox",
        "description": (
            "Gmail API (recent threads) or IMAP INBOX on a schedule, manual “Run poll”, "
            "or IMAP IDLE for faster SMTP inboxes."
        ),
        "accent": "blue",
        "icon_svg": (
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" '
            'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            '<path d="M22 12h-6l-2 3H10l-2-3H2"/>'
            '<path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>'
            "</svg>"
        ),
        "sort_order": 1,
    },
    {
        "title": "Keyword prefilter",
        "description": (
            "Optional SERVICE_KEYWORDS filter runs first—non-matching mail is skipped before any LLM call."
        ),
        "accent": "sky",
        "icon_svg": (
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" '
            'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            '<polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>'
            "</svg>"
        ),
        "sort_order": 2,
    },
    {
        "title": "RAG lookup",
        "description": (
            "If your knowledge base is configured, MailPilot finds the most relevant website, "
            "text, or JSON content before generating a reply."
        ),
        "accent": "purple",
        "icon_svg": (
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" '
            'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            '<path d="M12 5a3 3 0 1 0-5.997.125 7 7 0 0 0-2.526 9.375"/>'
            '<path d="M12 5a3 3 0 1 1 5.997.125 7 7 0 0 1 2.526 9.375"/>'
            '<path d="M12 5v14"/><path d="M6 19h12"/>'
            "</svg>"
        ),
        "sort_order": 3,
    },
    {
        "title": "AI relevance & reply",
        "description": (
            "One LLM call returns relevance, confidence, and reply text; must pass your RELEVANCE_THRESHOLD."
        ),
        "accent": "pink",
        "icon_svg": (
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" '
            'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            '<path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3z"/>'
            '<path d="M5 3v4"/><path d="M19 17v4"/><path d="M3 5h4"/><path d="M17 19h4"/>'
            "</svg>"
        ),
        "sort_order": 4,
    },
    {
        "title": "Draft or auto-send",
        "description": (
            "REPLY_MODE=draft saves the reply for dashboard review; send delivers immediately via Gmail API or SMTP."
        ),
        "accent": "green",
        "icon_svg": (
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" '
            'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            '<path d="M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z"/>'
            '<path d="m21.854 2.147-10.94 10.939"/>'
            "</svg>"
        ),
        "sort_order": 5,
    },
    {
        "title": "State & queue",
        "description": (
            "Per-user processed state avoids duplicates; the dashboard queue shows sent, draft, and ignored "
            "activity (account audit in admin)."
        ),
        "accent": "orange",
        "icon_svg": (
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" '
            'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            '<path d="M11 18H3"/><path d="M21 18h-8"/><path d="M11 6H3"/><path d="M21 6h-8"/><path d="M7 12h10"/>'
            '<circle cx="18" cy="6" r="2"/><circle cx="6" cy="18" r="2"/>'
            '<circle cx="18" cy="18" r="2"/><circle cx="6" cy="6" r="2"/>'
            "</svg>"
        ),
        "sort_order": 6,
    },
]


def seed_steps(apps, schema_editor):
    HowItWorksStep = apps.get_model("core", "HowItWorksStep")
    if HowItWorksStep.objects.exists():
        return
    HowItWorksStep.objects.bulk_create(
        [
            HowItWorksStep(
                **row,
                is_published=True,
                show_on_homepage=True,
            )
            for row in DEFAULT_STEPS
        ]
    )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0015_marketing_feature"),
    ]

    operations = [
        migrations.CreateModel(
            name="HowItWorksStep",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=120)),
                ("description", models.TextField()),
                (
                    "accent",
                    models.CharField(
                        choices=[
                            ("blue", "Blue"),
                            ("sky", "Sky"),
                            ("purple", "Purple"),
                            ("pink", "Pink"),
                            ("green", "Green"),
                            ("orange", "Orange"),
                        ],
                        default="blue",
                        max_length=16,
                    ),
                ),
                (
                    "icon_svg",
                    models.TextField(
                        blank=True,
                        default="",
                        help_text="Inline SVG for homepage cards (optional on dedicated page).",
                    ),
                ),
                ("sort_order", models.PositiveIntegerField(db_index=True, default=0)),
                ("is_published", models.BooleanField(db_index=True, default=True)),
                (
                    "show_on_homepage",
                    models.BooleanField(
                        default=True,
                        help_text="Show on landing page how-it-works section",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "how it works step",
                "verbose_name_plural": "how it works",
                "db_table": "core_howitworksstep",
                "ordering": ["sort_order", "id"],
            },
        ),
        migrations.RunPython(seed_steps, migrations.RunPython.noop),
    ]
