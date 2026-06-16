from django.db import migrations, models


DEFAULT_REVIEWS = [
    {
        "quote": (
            "We were drowning in tier‑1 inbox questions. Replies now pull from our product docs automatically—"
            "CSAT went up and our queue actually clears by end of day."
        ),
        "metric": "First-response time cut by roughly half in six weeks",
        "author_name": "Sarah Chen",
        "author_role": "VP of Operations · Northline Logistics",
        "avatar_initials": "SC",
        "accent_primary": "#4f6ef7",
        "accent_secondary": "#6366f1",
        "rating": 5,
        "sort_order": 1,
        "show_on_homepage": True,
    },
    {
        "quote": (
            "The RAG piece sold us. Generic AI drafts were embarrassing; grounded answers from our own KB "
            "sound like us. Onboarding took an afternoon, not a sprint."
        ),
        "metric": "Audit trail per rep—compliance finally stopped asking for screenshots",
        "author_name": "Marcus Webb",
        "author_role": "Head of Customer Experience · Brightstack",
        "avatar_initials": "MW",
        "accent_primary": "#a78bfa",
        "accent_secondary": "#c084fc",
        "rating": 5,
        "sort_order": 2,
        "show_on_homepage": True,
    },
    {
        "quote": (
            "I run a small agency—no room for a 24/7 inbox. MailPilot skips newsletters and cold outreach, "
            "and only surfaces what needs a human touch. Game changer."
        ),
        "metric": "~15 hours a week back for billable work",
        "author_name": "Elena Ruiz",
        "author_role": "Founder · Studio Meridian",
        "avatar_initials": "ER",
        "accent_primary": "#38bdf8",
        "accent_secondary": "#4f6ef7",
        "rating": 5,
        "sort_order": 3,
        "show_on_homepage": True,
    },
    {
        "quote": "We cut response time by hours. The drafts are surprisingly accurate once we uploaded our FAQ JSON.",
        "metric": "~40% fewer “where is…” tickets",
        "author_name": "Ayesha Khan",
        "author_role": "Ops Lead · GrowthDesk",
        "avatar_initials": "AK",
        "accent_primary": "#38bdf8",
        "accent_secondary": "#4f6ef7",
        "rating": 5,
        "sort_order": 4,
        "show_on_homepage": False,
    },
    {
        "quote": "The relevance filter is the win. MailPilot skips newsletters and only surfaces what needs action.",
        "metric": "~15 hours/week saved",
        "author_name": "Elena Ruiz",
        "author_role": "Founder · Studio Meridian",
        "avatar_initials": "ER",
        "accent_primary": "#a78bfa",
        "accent_secondary": "#ec4899",
        "rating": 5,
        "sort_order": 5,
        "show_on_homepage": False,
    },
    {
        "quote": (
            "RAG grounding makes replies consistent with our docs. We reduced escalations after enabling approval mode."
        ),
        "metric": "Fewer escalations, better tone",
        "author_name": "Mehedi Labib",
        "author_role": "CX Manager · Brightstack",
        "avatar_initials": "ML",
        "accent_primary": "#4ade80",
        "accent_secondary": "#22c55e",
        "rating": 5,
        "sort_order": 6,
        "show_on_homepage": False,
    },
]


def seed_reviews(apps, schema_editor):
    MarketingReview = apps.get_model("core", "MarketingReview")
    if MarketingReview.objects.exists():
        return
    MarketingReview.objects.bulk_create(
        [MarketingReview(**row, is_published=True) for row in DEFAULT_REVIEWS]
    )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0017_renumber_marketing_sort_orders"),
    ]

    operations = [
        migrations.CreateModel(
            name="MarketingReview",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("quote", models.TextField()),
                ("metric", models.CharField(blank=True, default="", max_length=160)),
                ("author_name", models.CharField(max_length=80)),
                ("author_role", models.CharField(max_length=160)),
                (
                    "avatar_initials",
                    models.CharField(
                        default="MP",
                        help_text="Initials shown in the avatar circle, e.g. AK",
                        max_length=4,
                    ),
                ),
                ("accent_primary", models.CharField(default="#4f6ef7", max_length=7)),
                ("accent_secondary", models.CharField(default="#a78bfa", max_length=7)),
                ("rating", models.PositiveSmallIntegerField(default=5)),
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
                        help_text="Show on landing page testimonials section",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "review",
                "verbose_name_plural": "reviews",
                "db_table": "core_marketingreview",
                "ordering": ["sort_order", "id"],
            },
        ),
        migrations.RunPython(seed_reviews, migrations.RunPython.noop),
    ]
