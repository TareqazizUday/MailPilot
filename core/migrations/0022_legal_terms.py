from datetime import date

from django.db import migrations, models

DEFAULT_TERMS_SETTINGS = {
    "title": "Terms of Service",
    "effective_date": date(2026, 4, 13),
    "intro_html": (
        "These Terms govern your use of MailPilot (“we”, “us”, “our”) and the MailPilot "
        "web application (the “Service”)."
    ),
    "notice_html": (
        "This is a general template to help you launch quickly. For production use—especially if "
        "you process customer email, OAuth tokens, or business data—review with legal counsel and "
        "tailor it to your jurisdiction, pricing, refunds, and compliance obligations."
    ),
    "is_published": True,
}

DEFAULT_TERMS_SECTIONS = [
    {
        "heading": "1) Eligibility and accounts",
        "body_html": (
            "<p>You must be able to form a legally binding contract to use the Service. You are "
            "responsible for the activity on your account and for keeping your credentials secure.</p>"
        ),
        "sort_order": 1,
    },
    {
        "heading": "2) Acceptable use",
        "body_html": (
            "<p>You agree not to misuse the Service. This includes attempting to access other users’ "
            "data, disrupting the Service, or using the Service to send spam, phishing, malware, or "
            "illegal content.</p>"
        ),
        "sort_order": 2,
    },
    {
        "heading": "3) Email access and automation",
        "body_html": (
            "<p>MailPilot may access connected mailboxes (e.g., Gmail OAuth or IMAP/SMTP) only as "
            "authorized by you and to provide features such as relevance filtering, drafting replies, "
            "and sending messages according to your settings.</p>"
            "<ul>"
            "<li>You represent that you have the right to connect the mailbox and to grant access.</li>"
            "<li>You are responsible for reviewing and configuring automation rules and approval modes.</li>"
            "</ul>"
        ),
        "sort_order": 3,
    },
    {
        "heading": "4) Content and data",
        "body_html": (
            "<p>You retain ownership of your content. You grant us permission to process your content "
            "solely to provide and improve the Service, including generating drafts and maintaining "
            "audit logs, subject to our Privacy Policy.</p>"
        ),
        "sort_order": 4,
    },
    {
        "heading": "5) Third-party services",
        "body_html": (
            "<p>The Service may integrate with third-party providers (for example, Google OAuth). "
            "Your use of those services is governed by their terms, and we are not responsible for "
            "third-party outages or changes.</p>"
        ),
        "sort_order": 5,
    },
    {
        "heading": "6) Security",
        "body_html": (
            "<p>We use reasonable technical measures to protect the Service. However, no method of "
            "transmission or storage is completely secure. You agree to use strong passwords and "
            "protect your environment and connected credentials.</p>"
        ),
        "sort_order": 6,
    },
    {
        "heading": "7) Service availability and changes",
        "body_html": (
            "<p>We may modify, suspend, or discontinue the Service (in whole or part) at any time. "
            "We do not guarantee uninterrupted availability.</p>"
        ),
        "sort_order": 7,
    },
    {
        "heading": "8) Disclaimers",
        "body_html": (
            "<p>The Service is provided “as is” and “as available”. Drafted replies are generated "
            "automatically and may be inaccurate or inappropriate. You are responsible for what gets "
            "sent from your mailbox.</p>"
        ),
        "sort_order": 8,
    },
    {
        "heading": "9) Limitation of liability",
        "body_html": (
            "<p>To the maximum extent permitted by law, we will not be liable for indirect, incidental, "
            "special, consequential, or punitive damages, or any loss of profits or data.</p>"
        ),
        "sort_order": 9,
    },
    {
        "heading": "10) Termination",
        "body_html": (
            "<p>You may stop using the Service at any time. We may suspend or terminate access if we "
            "reasonably believe you violated these Terms or if required by law.</p>"
        ),
        "sort_order": 10,
    },
    {
        "heading": "11) Contact",
        "body_html": (
            "<p>Questions about these Terms? Contact support via your admin channels, or add a support "
            "email address to this document when you go live.</p>"
        ),
        "sort_order": 11,
    },
]


def seed_terms(apps, schema_editor):
    Settings = apps.get_model("core", "LegalTermsSettings")
    Section = apps.get_model("core", "LegalTermsSection")
    Settings.objects.get_or_create(singleton_key=1, defaults=DEFAULT_TERMS_SETTINGS)
    if Section.objects.exists():
        return
    Section.objects.bulk_create([Section(**row, is_published=True) for row in DEFAULT_TERMS_SECTIONS])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0021_marketing_faq"),
    ]

    operations = [
        migrations.CreateModel(
            name="LegalTermsSettings",
            fields=[
                ("singleton_key", models.PositiveSmallIntegerField(default=1, primary_key=True, serialize=False)),
                ("title", models.CharField(default="Terms of Service", max_length=120)),
                ("effective_date", models.DateField(default=date(2026, 4, 13))),
                (
                    "intro_html",
                    models.TextField(
                        blank=True,
                        default="",
                        help_text="Short summary under the title. Basic HTML allowed.",
                    ),
                ),
                (
                    "notice_html",
                    models.TextField(
                        blank=True,
                        default="",
                        help_text="Highlighted notice box below the intro.",
                    ),
                ),
                ("is_published", models.BooleanField(default=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "terms page",
                "verbose_name_plural": "terms page",
                "db_table": "core_legaltermssettings",
            },
        ),
        migrations.CreateModel(
            name="LegalTermsSection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("heading", models.CharField(max_length=200)),
                (
                    "body_html",
                    models.TextField(help_text="Section body. Basic HTML allowed (p, ul, li, strong, a)."),
                ),
                ("sort_order", models.PositiveIntegerField(db_index=True, default=0)),
                ("is_published", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "terms section",
                "verbose_name_plural": "terms sections",
                "db_table": "core_legaltermssection",
                "ordering": ["sort_order", "id"],
            },
        ),
        migrations.RunPython(seed_terms, migrations.RunPython.noop),
    ]
