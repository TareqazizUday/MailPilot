from __future__ import annotations

from datetime import date

from core.models import LegalTermsSettings

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

DEFAULT_TERMS_SETTINGS = {
    "title": "Terms of Service",
    "effective_date": date(2026, 4, 13),
    "body_html": DEFAULT_TERMS_BODY_HTML,
    "is_published": True,
}


def get_terms_settings() -> LegalTermsSettings:
    """Return terms page settings; create defaults when missing."""
    obj, created = LegalTermsSettings.objects.get_or_create(
        singleton_key=1,
        defaults=DEFAULT_TERMS_SETTINGS,
    )
    if created:
        return obj
    if not (obj.body_html or "").strip():
        obj.body_html = DEFAULT_TERMS_BODY_HTML
        obj.save(update_fields=["body_html", "updated_at"])
    return obj


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


def get_privacy_settings() -> "LegalPrivacySettings":
    from core.models import LegalPrivacySettings

    obj, created = LegalPrivacySettings.objects.get_or_create(
        singleton_key=1,
        defaults=DEFAULT_PRIVACY_SETTINGS,
    )
    if created:
        return obj
    if not (obj.body_html or "").strip():
        obj.body_html = DEFAULT_PRIVACY_BODY_HTML
        obj.save(update_fields=["body_html", "updated_at"])
    return obj
