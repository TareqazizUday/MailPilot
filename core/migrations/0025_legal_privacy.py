from datetime import date

from django.db import migrations, models

DEFAULT_PRIVACY_BODY_HTML = """<p>This Policy explains how MailPilot collects, uses, and shares information when you use the Service.</p>
<div class="notice"><p>This is a launch-ready template. If you process email content, OAuth tokens, or customer data in production, tailor retention periods, subprocessors, and legal bases (GDPR/CCPA as applicable).</p></div>
<hr>
<h2>1) Information we collect</h2>
<ul>
<li><strong>Account data</strong>: name, email address, and authentication details.</li>
<li><strong>Connected mailbox data</strong>: mailbox identifiers, OAuth tokens (when applicable), and configuration needed to connect.</li>
<li><strong>Email content and metadata</strong>: subject lines, sender/recipient info, message bodies, and attachments only as needed to provide automation features you enable.</li>
<li><strong>Usage data</strong>: pages viewed, features used, logs, and diagnostics.</li>
</ul>
<h2>2) How we use information</h2>
<ul>
<li>Provide, maintain, and improve the Service (including drafting replies and relevance filtering).</li>
<li>Authenticate users, prevent abuse, and enforce security controls.</li>
<li>Operate support, audits, and incident response.</li>
</ul>
<h2>3) AI / automated processing</h2>
<p>When you enable automation, the Service may process email content to generate drafts and recommendations. You remain responsible for messages that are sent and for reviewing your automation settings.</p>
<h2>4) Sharing and disclosure</h2>
<p>We do not sell your personal information. We may share information with:</p>
<ul>
<li><strong>Service providers</strong> (hosting, monitoring, email APIs) who process data on our behalf.</li>
<li><strong>Legal and safety</strong> where required by law or to protect rights and safety.</li>
</ul>
<h2>5) Data retention</h2>
<p>We retain information only as long as necessary for the purposes described in this Policy, unless a longer retention period is required by law. When you disconnect a mailbox, tokens and configuration may be removed according to your settings and operational constraints.</p>
<h2>6) Security</h2>
<p>We use reasonable safeguards designed to protect information. No security measure is perfect; you are responsible for securing your account credentials.</p>
<h2>7) Your choices</h2>
<ul>
<li>Update your account information in the app.</li>
<li>Disconnect mailbox integrations you no longer want to use.</li>
<li>Request deletion of your account (add a support contact method for production).</li>
</ul>
<h2>8) International transfers</h2>
<p>Your information may be processed in countries other than your own depending on where the Service and its providers operate.</p>
<h2>9) Changes to this Policy</h2>
<p>We may update this Policy from time to time. The effective date above reflects the latest version.</p>
<h2>10) Contact</h2>
<p>For privacy questions, add a support email address or contact channel here when you go live.</p>"""

DEFAULT_PRIVACY_SETTINGS = {
    "title": "Privacy Policy",
    "effective_date": date(2026, 4, 13),
    "body_html": DEFAULT_PRIVACY_BODY_HTML,
    "is_published": True,
}


def seed_privacy(apps, schema_editor):
    Settings = apps.get_model("core", "LegalPrivacySettings")
    Settings.objects.get_or_create(singleton_key=1, defaults=DEFAULT_PRIVACY_SETTINGS)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0024_legal_terms_body_html"),
    ]

    operations = [
        migrations.CreateModel(
            name="LegalPrivacySettings",
            fields=[
                ("singleton_key", models.PositiveSmallIntegerField(default=1, primary_key=True, serialize=False)),
                ("title", models.CharField(default="Privacy Policy", max_length=120)),
                ("effective_date", models.DateField(default=date(2026, 4, 13))),
                (
                    "body_html",
                    models.TextField(
                        blank=True,
                        default="",
                        help_text="Full privacy page content (single rich-text document).",
                    ),
                ),
                ("is_published", models.BooleanField(default=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "privacy page",
                "verbose_name_plural": "privacy page",
                "db_table": "core_legalprivacysettings",
            },
        ),
        migrations.RunPython(seed_privacy, migrations.RunPython.noop),
    ]
