from django.db import migrations, models


DEFAULT_TERMS_BODY_HTML = """<p>These Terms govern your use of MailPilot (“we”, “us”, “our”) and the MailPilot web application (the “Service”).</p>
<div class="notice"><p>This is a general template to help you launch quickly. For production use—especially if you process customer email, OAuth tokens, or business data—review with legal counsel and tailor it to your jurisdiction, pricing, refunds, and compliance obligations.</p></div>
<hr>
<h2>1) Eligibility and accounts</h2>
<p>You must be able to form a legally binding contract to use the Service. You are responsible for the activity on your account and for keeping your credentials secure.</p>
<h2>2) Acceptable use</h2>
<p>You agree not to misuse the Service. This includes attempting to access other users’ data, disrupting the Service, or using the Service to send spam, phishing, malware, or illegal content.</p>
<h2>3) Email access and automation</h2>
<p>MailPilot may access connected mailboxes (e.g., Gmail OAuth or IMAP/SMTP) only as authorized by you and to provide features such as relevance filtering, drafting replies, and sending messages according to your settings.</p>
<ul><li>You represent that you have the right to connect the mailbox and to grant access.</li><li>You are responsible for reviewing and configuring automation rules and approval modes.</li></ul>
<h2>4) Content and data</h2>
<p>You retain ownership of your content. You grant us permission to process your content solely to provide and improve the Service, including generating drafts and maintaining audit logs, subject to our Privacy Policy.</p>
<h2>5) Third-party services</h2>
<p>The Service may integrate with third-party providers (for example, Google OAuth). Your use of those services is governed by their terms, and we are not responsible for third-party outages or changes.</p>
<h2>6) Security</h2>
<p>We use reasonable technical measures to protect the Service. However, no method of transmission or storage is completely secure. You agree to use strong passwords and protect your environment and connected credentials.</p>
<h2>7) Service availability and changes</h2>
<p>We may modify, suspend, or discontinue the Service (in whole or part) at any time. We do not guarantee uninterrupted availability.</p>
<h2>8) Disclaimers</h2>
<p>The Service is provided “as is” and “as available”. Drafted replies are generated automatically and may be inaccurate or inappropriate. You are responsible for what gets sent from your mailbox.</p>
<h2>9) Limitation of liability</h2>
<p>To the maximum extent permitted by law, we will not be liable for indirect, incidental, special, consequential, or punitive damages, or any loss of profits or data.</p>
<h2>10) Termination</h2>
<p>You may stop using the Service at any time. We may suspend or terminate access if we reasonably believe you violated these Terms or if required by law.</p>
<h2>11) Contact</h2>
<p>Questions about these Terms? Contact support via your admin channels, or add a support email address to this document when you go live.</p>"""


def merge_terms_into_body(apps, schema_editor):
    Settings = apps.get_model("core", "LegalTermsSettings")
    Section = apps.get_model("core", "LegalTermsSection")
    for page in Settings.objects.all():
        if (page.body_html or "").strip():
            continue
        parts: list[str] = []
        if (page.intro_html or "").strip():
            parts.append(page.intro_html.strip())
        if (page.notice_html or "").strip():
            parts.append(f'<div class="notice">{page.notice_html.strip()}</div>')
        sections = Section.objects.filter(page_id=page.pk, is_published=True).order_by("sort_order", "id")
        if sections.exists():
            if parts:
                parts.append("<hr>")
            for sec in sections:
                parts.append(f"<h2>{sec.heading}</h2>{sec.body_html}")
        page.body_html = "\n".join(parts) if parts else DEFAULT_TERMS_BODY_HTML
        page.save(update_fields=["body_html"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0023_legal_terms_section_page"),
    ]

    operations = [
        migrations.AddField(
            model_name="legaltermssettings",
            name="body_html",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Full terms page content (single rich-text document).",
            ),
        ),
        migrations.RunPython(merge_terms_into_body, migrations.RunPython.noop),
    ]
