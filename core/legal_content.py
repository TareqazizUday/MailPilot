from __future__ import annotations

from datetime import date
from typing import Any

from core.models import LegalTermsSettings

# Voiexa-style terms (https://voiexa.com/terms.php), adapted for MailPilot.
TERMS_INTRO = (
    "These Terms explain how you may use MailPilot and the responsibilities that come with running "
    "AI email automation, connected mailboxes, knowledge bases, drafts, sends, payments, and integrations."
)

TERMS_HIGHLIGHTS: list[str] = [
    "Use MailPilot only where you have the right consent and lawful basis to access mailboxes, process messages, store contact data, and send replies.",
    "Your account content, mailbox connections, knowledge base, reply settings, and compliance choices remain your responsibility.",
    "Plans, tokens, inboxes, integrations, and add-ons are provided according to the plan or commercial agreement you purchase.",
]

TERMS_SECTIONS: list[dict[str, Any]] = [
    {
        "title": "1. Agreement and authority",
        "parts": [
            {
                "type": "p",
                "text": (
                    "Please read these Terms and Conditions carefully before using MailPilot, including this website, "
                    "the user portal, email automation tools, inbox connections, APIs, integrations, and any related support services we provide."
                ),
            },
            {
                "type": "p",
                "text": (
                    "These Terms, together with our Privacy policy and any separate order form, package terms, or written "
                    "commercial agreement, form the agreement between you and MailPilot. By accessing or using the Service, you accept these Terms."
                ),
            },
            {
                "type": "p",
                "text": (
                    'If you use MailPilot on behalf of a company, agency, client, or other entity, you confirm that you have '
                    'authority to accept these Terms for that entity. In that case, "you" includes that entity and anyone using '
                    "the Service through its account."
                ),
            },
        ],
    },
    {
        "title": "2. The MailPilot service",
        "parts": [
            {
                "type": "p",
                "text": (
                    "MailPilot is an AI email automation platform for support, sales, and operations teams. The Service may "
                    "include Gmail and IMAP inbox connections, relevance filtering, draft and auto-send replies, knowledge base / RAG "
                    "setup, usage tracking, Telegram or WhatsApp notifications, billing, and related integrations."
                ),
            },
            {
                "type": "p",
                "text": (
                    "MailPilot is not an email carrier, emergency service, legal adviser, medical provider, financial adviser, "
                    "or compliance authority. You are responsible for deciding whether your use case, reply content, mailbox access, "
                    "consent records, and disclosures comply with laws that apply to you."
                ),
            },
        ],
    },
    {
        "title": "3. Consent, messaging rules, and lawful use",
        "parts": [
            {
                "type": "p",
                "text": (
                    "You must use the Service only in a lawful, fair, and responsible manner. Before connecting mailboxes or sending "
                    "messages through MailPilot, you must have all required permissions, consents, notices, and lawful bases for the "
                    "relevant contacts, regions, industries, and channels."
                ),
            },
            {
                "type": "ul",
                "items": [
                    "Do not connect, process, or reply from mailboxes where you do not have permission or another lawful basis.",
                    "Do not use MailPilot to contact people on applicable do-not-contact, suppression, opt-out, blocked, or restricted lists.",
                    "Do not hide the nature of automated replies, impersonate another person or entity, or misrepresent your relationship with a prospect or customer.",
                    "Do not use MailPilot for emergency, safety-critical, medical, legal, financial, or other high-risk decisions where a qualified human professional is required.",
                    "Do not use the Service in any way that violates email marketing, privacy, consumer protection, anti-spam, anti-bribery, sanctions, export control, or other applicable laws.",
                ],
            },
        ],
    },
    {
        "title": "4. Account responsibility",
        "parts": [
            {
                "type": "p",
                "text": (
                    "You agree that the information you provide during registration, checkout, onboarding, and continued use of the "
                    "Service is true, accurate, current, and complete. You are responsible for safeguarding your account credentials "
                    "and for all activity under your account."
                ),
            },
            {
                "type": "ul",
                "items": [
                    "Do not share account passwords or allow unauthorized users to access your account.",
                    "Keep your billing, contact, company, and technical setup information up to date.",
                    "Maintain your own backups of important reply templates, knowledge base content, and reports.",
                    "Tell us promptly if you suspect unauthorized access, misuse, or a security issue involving your account.",
                ],
            },
        ],
    },
    {
        "title": "5. Acceptable use",
        "parts": [
            {
                "type": "p",
                "text": (
                    "You agree not to misuse the Service or interfere with its normal operation. We may suspend, restrict, or "
                    "terminate access if we reasonably believe your use creates legal, security, reputation, deliverability, "
                    "platform, or operational risk."
                ),
            },
            {
                "type": "ul",
                "items": [
                    "Do not attempt to gain unauthorized access to the Service, our systems, networks, data, APIs, providers, or other users' accounts.",
                    "Do not upload or transmit malicious code, spyware, viruses, abusive traffic, or content designed to disrupt or damage systems.",
                    "Do not scrape, harvest, data mine, reverse engineer, decompile, or extract code from the Service except where applicable law prohibits this restriction.",
                    "Do not submit content that is unlawful, harmful to children, threatening, abusive, harassing, defamatory, obscene, hateful, discriminatory, sexually explicit, or otherwise objectionable.",
                    "Do not upload content that infringes intellectual property, privacy, publicity, confidentiality, or other rights of any person or entity.",
                    "Do not resell, sublicense, rent, lease, distribute, or make the Service available to third parties unless your written agreement with MailPilot permits it.",
                    "Do not create accounts, sends, traffic, or data through unauthorized automated means.",
                ],
            },
        ],
    },
    {
        "title": "6. Your content and data",
        "parts": [
            {
                "type": "p",
                "text": (
                    "Your user content includes mailbox configuration, email content and metadata processed for automation, "
                    "knowledge base material, prompts, drafts, sent replies, feedback, files, messages, and other material you "
                    "submit to or generate through the Service."
                ),
            },
            {
                "type": "p",
                "text": (
                    "You retain ownership of your user content. You grant MailPilot a worldwide, non-exclusive, royalty-free license "
                    "to host, process, transmit, reproduce, adapt, display, and use that content as needed to provide, secure, "
                    "maintain, support, analyze, and improve the Service."
                ),
            },
            {
                "type": "p",
                "text": (
                    "You represent that you have all rights and permissions needed to upload, process, store, and use your user "
                    "content through MailPilot. We do not undertake to monitor every submission, but we may remove or restrict "
                    "content that we believe violates these Terms or applicable law."
                ),
            },
        ],
    },
    {
        "title": "7. Ownership and software license",
        "parts": [
            {
                "type": "p",
                "text": (
                    "MailPilot and its licensors own all rights, title, and interest in the Service, including the website, portal, "
                    "software, workflows, interfaces, designs, logos, branding, APIs, documentation, and related technology. Using "
                    "the Service does not transfer any ownership rights to you."
                ),
            },
            {
                "type": "p",
                "text": (
                    "Subject to your ongoing compliance with these Terms, we grant you a personal, limited, revocable, non-exclusive, "
                    "non-transferable license to access and use the Service for your internal business purposes or as otherwise "
                    "allowed in your written agreement with MailPilot."
                ),
            },
            {
                "type": "ul",
                "items": [
                    "Do not remove, obscure, or alter legal notices, branding, or proprietary markings.",
                    "Do not reproduce, modify, sell, trade, broadcast, publicly perform, create derivative works from, or commercially exploit the Service except as permitted in writing.",
                    "Software, integrations, and APIs may update automatically to improve security, reliability, compatibility, or functionality.",
                ],
            },
        ],
    },
    {
        "title": "8. Packages, tokens, fees, and payments",
        "parts": [
            {
                "type": "p",
                "text": (
                    "MailPilot may offer free trials, Starter limits, Pro and Custom plans, token top-ups, auto-renew options, "
                    "setup services, agency plans, and other paid features. Available features, usage limits, mailbox caps, "
                    "currencies, and provider support may differ by package, region, account status, and third-party provider availability."
                ),
            },
            {
                "type": "p",
                "text": (
                    "You agree to pay all fees and charges shown at checkout or agreed in writing. Payment processing may be handled "
                    "by third-party providers such as Stripe, PayPal, or other processors, whose own terms and privacy policies may apply."
                ),
            },
            {
                "type": "p",
                "text": (
                    "Tokens may be reserved or consumed when auto-sends, analyses, automations, or related provider actions are started "
                    "or completed. Unless MailPilot agrees otherwise in writing, paid fees and used tokens are non-refundable."
                ),
            },
            {
                "type": "ul",
                "items": [
                    "Taxes, duties, bank fees, currency conversion fees, and provider charges are your responsibility where applicable.",
                    "We may suspend or restrict paid services if payment fails, a chargeback occurs, or required billing information is missing.",
                    "Prices, packages, add-ons, and usage limits may change, but changes will not reduce a paid package you already purchased during its applicable term unless required by law or provider restrictions.",
                ],
            },
        ],
    },
    {
        "title": "9. Third-party providers and integrations",
        "parts": [
            {
                "type": "p",
                "text": (
                    "MailPilot may depend on third-party providers for email providers (for example Google), AI models, payment "
                    "processing, hosting, analytics, messaging, and other infrastructure. We are not responsible for third-party "
                    "outages, policy changes, pricing changes, account restrictions, regional limitations, or data handling outside our control."
                ),
            },
            {
                "type": "p",
                "text": (
                    "If you connect your own provider accounts, calendars, payment tools, email inboxes, CRMs, or other integrations, "
                    "you are responsible for those accounts, permissions, credentials, and provider terms."
                ),
            },
        ],
    },
    {
        "title": "10. Service availability and support",
        "parts": [
            {
                "type": "p",
                "text": (
                    "We aim to keep MailPilot reliable, but the Service may be interrupted for maintenance, upgrades, repairs, "
                    "provider issues, network failures, security incidents, force majeure events, or events beyond our reasonable "
                    "control. We may modify, suspend, discontinue, or limit parts of the Service at any time."
                ),
            },
            {
                "type": "p",
                "text": (
                    "Unless a separate written agreement says otherwise, support is provided at our discretion. Providing support "
                    "once does not mean we will continue to provide the same support in the future."
                ),
            },
        ],
    },
    {
        "title": "11. Disclaimers and limitation of liability",
        "parts": [
            {
                "type": "p",
                "text": (
                    'The Service is provided on an "as is" and "as available" basis. To the fullest extent permitted by law, MailPilot '
                    "disclaims warranties of merchantability, fitness for a particular purpose, non-infringement, uninterrupted operation, "
                    "error-free performance, and any guarantee that AI outputs, drafts, auto-sent replies, relevance decisions, or "
                    "summaries will be complete, accurate, compliant, or suitable for your use case."
                ),
            },
            {
                "type": "p",
                "text": (
                    "To the fullest extent permitted by law, MailPilot will not be liable for indirect, incidental, special, consequential, "
                    "exemplary, punitive, or lost-profit damages, or for loss of data, revenue, goodwill, business opportunity, mailbox "
                    "access, provider accounts, or compliance status arising from or related to your use of the Service."
                ),
            },
        ],
    },
    {
        "title": "12. Indemnity",
        "parts": [
            {
                "type": "p",
                "text": (
                    "If you use the Service on behalf of a business, agency, client, or other entity, or for commercial purposes, you "
                    "and that entity agree to defend, indemnify, and hold harmless MailPilot from claims, losses, damages, fines, "
                    "penalties, liabilities, expenses, and attorneys fees arising from or related to your use of the Service, your "
                    "user content, your emails or messages, your violation of these Terms, or your violation of applicable law or "
                    "third-party rights."
                ),
            },
        ],
    },
    {
        "title": "13. Language and translations",
        "parts": [
            {
                "type": "p",
                "text": (
                    "If these Terms or any Service content is translated into another language, the translation is provided for "
                    "convenience only. If there is any conflict between an English version and a translated version, the English "
                    "version controls unless applicable law requires otherwise."
                ),
            },
        ],
    },
    {
        "title": "14. Copyright notices and takedown requests",
        "parts": [
            {
                "type": "p",
                "text": (
                    "If you believe material available through MailPilot infringes your copyright or other rights, contact us with "
                    "enough detail for us to locate and assess the material. Include your name, contact information, a description "
                    "of the work, the location of the allegedly infringing material, and a statement that the information you provide "
                    "is accurate and that you are the owner or authorized to act for the owner."
                ),
            },
        ],
    },
    {
        "title": "15. Changes to these Terms",
        "parts": [
            {
                "type": "p",
                "text": (
                    "We may modify or replace these Terms from time to time. If a change is material, we may try to provide notice "
                    "before the new terms take effect. What counts as a material change is determined at our sole discretion. "
                    "Continued use of the Service after changes take effect means you accept the updated Terms."
                ),
            },
        ],
    },
    {
        "title": "16. Contact us",
        "parts": [
            {
                "type": "p",
                "text": (
                    "For questions about these Terms, contact MailPilot through the contact form on the home page or by email at "
                    "team@timerni.co.uk."
                ),
            },
        ],
    },
]


def _render_sectioned_body_html(*, highlights: list[str], sections: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for text in highlights:
        chunks.append(f'<div class="legal-highlight"><p>{text}</p></div>')
    for section in sections:
        parts_html: list[str] = []
        for part in section["parts"]:
            if part["type"] == "p":
                parts_html.append(f"<p>{part['text']}</p>")
            elif part["type"] == "ul":
                items = "".join(f"<li>{item}</li>" for item in part["items"])
                parts_html.append(f"<ul>{items}</ul>")
        chunks.append(
            f'<article class="legal-section"><h2>{section["title"]}</h2>'
            f'<div class="legal-section-body">{"".join(parts_html)}</div></article>'
        )
    return "\n".join(chunks)


DEFAULT_TERMS_BODY_HTML = _render_sectioned_body_html(
    highlights=TERMS_HIGHLIGHTS,
    sections=TERMS_SECTIONS,
)

DEFAULT_TERMS_SETTINGS = {
    "title": "Terms & Conditions",
    "effective_date": date(2026, 6, 16),
    "body_html": DEFAULT_TERMS_BODY_HTML,
    "is_published": True,
}

_OLD_TERMS_MARKERS = (
    "This is a general template to help you launch quickly",
    "MailPilot (“we”, “us”, “our”) and the MailPilot web application",
)


def get_terms_settings() -> LegalTermsSettings:
    """Return terms page settings; create or refresh defaults when missing/outdated."""
    obj, created = LegalTermsSettings.objects.get_or_create(
        singleton_key=1,
        defaults=DEFAULT_TERMS_SETTINGS,
    )
    if created:
        return obj

    body = (obj.body_html or "").strip()
    needs_refresh = (not body) or any(marker in body for marker in _OLD_TERMS_MARKERS)
    if needs_refresh:
        obj.title = DEFAULT_TERMS_SETTINGS["title"]
        obj.effective_date = DEFAULT_TERMS_SETTINGS["effective_date"]
        obj.body_html = DEFAULT_TERMS_BODY_HTML
        obj.is_published = True
        obj.save(update_fields=["title", "effective_date", "body_html", "is_published", "updated_at"])
    return obj


def get_terms_page_payload() -> dict[str, Any]:
    """Structured payload for the Voiexa-style terms layout."""
    settings_obj = get_terms_settings()
    return {
        "terms_page": settings_obj,
        "terms_intro": TERMS_INTRO,
        "terms_highlights": TERMS_HIGHLIGHTS,
        "terms_sections": TERMS_SECTIONS,
    }


# Voiexa-style privacy (https://voiexa.com/privacy.php), adapted for MailPilot.
PRIVACY_INTRO = (
    "This Policy explains how MailPilot handles personal information across the website, user portal, "
    "connected mailboxes, AI drafts and auto-sends, knowledge bases, payments, support, and integrations."
)

PRIVACY_HIGHLIGHTS: list[str] = [
    "We collect account, billing, mailbox, email, knowledge base, usage, and technical information to operate MailPilot.",
    "You are responsible for having the right permission to connect mailboxes, process messages, and use personal data in your workflows.",
    "We use trusted providers for payments, email, AI, hosting, analytics, and related infrastructure, and we do not store full card numbers.",
]

PRIVACY_SECTIONS: list[dict[str, Any]] = [
    {
        "title": "1. Scope of this Policy",
        "parts": [
            {
                "type": "p",
                "text": (
                    "MailPilot values your privacy. This Privacy Policy explains how we collect, use, disclose, store, and protect "
                    "information when you visit our website, create an account, use the user portal, connect mailboxes, run AI email "
                    "automation, purchase plans, connect integrations, contact support, or otherwise use our services."
                ),
            },
            {
                "type": "p",
                "text": (
                    "By using MailPilot, you agree that your information will be handled as described in this Policy. Your use of the "
                    "Service is also subject to our Terms and Conditions."
                ),
            },
            {
                "type": "p",
                "text": (
                    'In this Policy, "you" means a visitor, user, customer, company, agency, client, contact, or authorized '
                    'representative who interacts with MailPilot. "We", "us", and "our" mean MailPilot.'
                ),
            },
        ],
    },
    {
        "title": "2. Information we collect",
        "parts": [
            {
                "type": "p",
                "text": (
                    "We collect information you provide directly, information generated through your use of the Service, and "
                    "information we receive from third-party providers or integrations you connect."
                ),
            },
            {
                "type": "ul",
                "items": [
                    "Account and profile information, such as name, email address, password credentials, company, role, phone number, country, and account preferences.",
                    "Billing and transaction information, such as selected plans, token purchases, top-ups, invoices, payment status, tax details, and payment processor references.",
                    "Mailbox and email information, such as connected inbox identifiers, OAuth or IMAP credentials/config, subjects, sender/recipient data, message bodies, attachments, drafts, and send outcomes as needed for features you enable.",
                    "Knowledge base and automation content, such as uploaded sources, prompts, reply settings, filters, and instructions you provide for AI replies.",
                    "Integration information, such as Telegram or WhatsApp settings, OAuth tokens or provider references where needed, and configuration data for connected tools.",
                    "Technical and usage information, such as IP address, browser type, device information, operating system, pages visited, referring URLs, session identifiers, cookies, approximate location, logs, errors, and security events.",
                    "Support and contact information, such as messages sent through forms, emails, support tickets, feedback, and other communications with us.",
                ],
            },
        ],
    },
    {
        "title": "3. How we use information",
        "parts": [
            {
                "type": "p",
                "text": (
                    "We use information to provide, maintain, secure, support, personalize, analyze, and improve MailPilot. We also "
                    "use information to meet legal obligations, enforce our Terms, prevent abuse, and protect users, contacts, providers, and our business."
                ),
            },
            {
                "type": "ul",
                "items": [
                    "Create and manage accounts, authentication, sessions, plans, tokens, limits, and user portal access.",
                    "Run AI email workflows, including relevance filtering, drafting, auto-sending, knowledge base responses, usage tracking, and notifications.",
                    "Process payments, issue invoices, confirm purchases, handle refunds or disputes, prevent payment abuse, and administer plans or add-ons.",
                    "Communicate with you about onboarding, support, product updates, security notices, billing, service changes, and account activity.",
                    "Analyze usage, diagnose bugs, improve product performance, develop new features, train internal processes, and measure service reliability.",
                    "Detect, investigate, prevent, and respond to fraud, abuse, unauthorized access, security incidents, technical issues, policy violations, and unlawful activity.",
                    "Comply with applicable laws, privacy obligations, sanctions, tax requirements, court orders, government requests, and regulatory inquiries.",
                ],
            },
        ],
    },
    {
        "title": "4. Email content, drafts, and contact data",
        "parts": [
            {
                "type": "p",
                "text": (
                    "MailPilot is designed for email automation. Connected mailboxes may generate drafts, auto-sends, relevance "
                    "decisions, usage logs, and related metadata. These records may contain personal information about your team, "
                    "prospects, customers, and other contacts."
                ),
            },
            {
                "type": "p",
                "text": (
                    "You are responsible for ensuring that you have all required permissions, notices, consents, and lawful bases "
                    "to connect mailboxes, process email content, send replies, and use automation outcomes. This includes complying "
                    "with email marketing, opt-out, privacy, consumer protection, and industry-specific rules that apply to you."
                ),
            },
            {
                "type": "ul",
                "items": [
                    "Do not connect or process mailboxes where you do not have permission or another lawful basis.",
                    "Respect opt-out, suppression, blocked, and do-not-contact lists.",
                    "Review AI outputs, drafts, and send settings before relying on them for important decisions.",
                    "Remove or update inaccurate contact or mailbox data when you become aware of it.",
                ],
            },
        ],
    },
    {
        "title": "5. Cookies and similar technologies",
        "parts": [
            {
                "type": "p",
                "text": (
                    "We may use cookies, session storage, local storage, and similar technologies to keep you signed in, remember "
                    "preferences, protect forms with CSRF controls, support theme settings, measure usage, improve performance, "
                    "and protect against fraud or abuse."
                ),
            },
            {
                "type": "p",
                "text": (
                    "You can control cookies through your browser settings, but disabling some cookies may prevent parts of the "
                    "Service from working correctly."
                ),
            },
        ],
    },
    {
        "title": "6. Information sharing and disclosure",
        "parts": [
            {
                "type": "p",
                "text": (
                    "We do not sell your personal information as a standalone product. We may share information where needed to "
                    "operate MailPilot, comply with law, protect rights, or complete transactions you request."
                ),
            },
            {
                "type": "ul",
                "items": [
                    "With service providers that support hosting, databases, email providers, AI models, payment processing, analytics, security, customer support, and other infrastructure.",
                    "With payment processors, card networks, banks, or fraud-prevention services to process payments, verify transactions, manage disputes, and prevent abuse.",
                    "With email, messaging, CRM, or other providers when necessary to connect mailboxes, deliver notifications, or operate integrations.",
                    "With administrators or authorized users of your account or organization, including agencies or clients you authorize.",
                    "In response to a valid court order, search warrant, subpoena, regulator request, government request, legal process, or other demand we believe to be lawful.",
                    "To enforce our Terms, investigate potential violations, collect debts, protect safety, prevent fraud, defend claims, or protect the rights, property, and security of MailPilot, users, contacts, providers, or others.",
                    "In connection with a merger, acquisition, financing, reorganization, sale of assets, bankruptcy, or similar business transaction, subject to appropriate confidentiality and privacy protections where applicable.",
                ],
            },
        ],
    },
    {
        "title": "7. Third-party providers",
        "parts": [
            {
                "type": "p",
                "text": (
                    "MailPilot may rely on third-party providers such as payment processors, email providers (for example Google), "
                    "AI providers, hosting providers, analytics tools, and other infrastructure services. These providers may "
                    "process information according to their own terms and privacy policies."
                ),
            },
            {
                "type": "p",
                "text": (
                    "If you connect your own third-party accounts or integrations, you are responsible for those accounts, "
                    "permissions, provider settings, and any information shared through them."
                ),
            },
        ],
    },
    {
        "title": "8. Marketing and communications",
        "parts": [
            {
                "type": "p",
                "text": (
                    "We may use your information to send service messages, security notices, billing notices, onboarding emails, "
                    "support responses, product updates, offers, surveys, and research or feedback requests."
                ),
            },
            {
                "type": "p",
                "text": (
                    "You may opt out of non-essential marketing communications by using the unsubscribe instructions in the message "
                    "or contacting us. We may still send transactional or service-related messages where necessary to operate your "
                    "account or comply with law."
                ),
            },
        ],
    },
    {
        "title": "9. Storage, retention, and deletion",
        "parts": [
            {
                "type": "p",
                "text": (
                    "We retain information for as long as needed to provide the Service, maintain records, comply with legal "
                    "obligations, resolve disputes, enforce agreements, prevent fraud, support security, and operate backups. "
                    "Retention periods may vary depending on the type of information, account status, plan, legal requirements, "
                    "provider settings, and operational needs."
                ),
            },
            {
                "type": "p",
                "text": (
                    "You may request account deletion or data deletion by contacting us. We may need to retain certain information "
                    "where required for billing, legal, security, fraud prevention, backup, dispute, audit, or compliance purposes. "
                    "When you disconnect a mailbox, tokens and configuration may be removed according to your settings and operational constraints."
                ),
            },
        ],
    },
    {
        "title": "10. Security",
        "parts": [
            {
                "type": "p",
                "text": (
                    "We use administrative, technical, and organizational safeguards designed to protect information from "
                    "unauthorized access, alteration, disclosure, or destruction. No method of transmission or storage is fully "
                    "secure, so we cannot guarantee absolute security."
                ),
            },
            {
                "type": "ul",
                "items": [
                    "We restrict access to personal information to people and providers who need it to operate, support, secure, or improve the Service.",
                    "We review security, storage, and processing practices to reduce unauthorized access and misuse.",
                    "We may encrypt, hash, mask, or otherwise protect certain information where appropriate.",
                    "If we become aware of a security breach affecting your personal information, we will make reasonable efforts to notify you as required by applicable law.",
                ],
            },
        ],
    },
    {
        "title": "11. Your choices and responsibilities",
        "parts": [
            {
                "type": "p",
                "text": (
                    "You can update certain account details from the user portal or by contacting us. Depending on your location "
                    "and applicable law, you may have rights to access, correct, delete, restrict, object to, or receive a copy of "
                    "certain personal information."
                ),
            },
            {
                "type": "p",
                "text": (
                    "Because MailPilot processes mailbox and email data you connect or upload, you are responsible for responding "
                    "to privacy requests from those contacts where you are the data controller or business owner for that data."
                ),
            },
            {
                "type": "ul",
                "items": [
                    "Keep your account and contact data accurate and current.",
                    "Use strong passwords and protect your login credentials.",
                    "Do not submit sensitive personal data unless it is necessary for your lawful use of the Service and you have proper authority to process it.",
                    "Do not post private information in public reviews, comments, forums, or other public areas.",
                ],
            },
        ],
    },
    {
        "title": "12. International transfers",
        "parts": [
            {
                "type": "p",
                "text": (
                    "MailPilot and its providers may process information in countries other than where you or your contacts are "
                    "located. Privacy laws may differ between countries. Where required, we use reasonable safeguards for cross-border transfers."
                ),
            },
        ],
    },
    {
        "title": "13. Fraud prevention and investigations",
        "parts": [
            {
                "type": "p",
                "text": (
                    "To prevent, detect, investigate, or suppress fraud, abuse, unauthorized access, criminal activity, payment "
                    "misuse, platform abuse, or security threats, we may collect, use, preserve, analyze, and disclose information "
                    "to relevant providers, payment processors, fraud prevention services, regulators, government bodies, legal "
                    "advisers, insurers, financial institutions, or other organizations as permitted by law."
                ),
            },
        ],
    },
    {
        "title": "14. Changes to this Policy",
        "parts": [
            {
                "type": "p",
                "text": (
                    "We may update this Privacy Policy from time to time. If changes are significant, we may provide a more "
                    "prominent notice, such as a website notice, portal notice, or email notification. Continued use of the "
                    "Service after changes take effect means you accept the updated Policy."
                ),
            },
        ],
    },
    {
        "title": "15. Contact us",
        "parts": [
            {
                "type": "p",
                "text": (
                    "For privacy questions, requests, or complaints, contact MailPilot through the contact form on the home page "
                    "or by email at team@timerni.co.uk."
                ),
            },
        ],
    },
]


DEFAULT_PRIVACY_BODY_HTML = _render_sectioned_body_html(
    highlights=PRIVACY_HIGHLIGHTS,
    sections=PRIVACY_SECTIONS,
)

DEFAULT_PRIVACY_SETTINGS = {
    "title": "Privacy Policy",
    "effective_date": date(2026, 6, 16),
    "body_html": DEFAULT_PRIVACY_BODY_HTML,
    "is_published": True,
}

_OLD_PRIVACY_MARKERS = (
    "This is a launch-ready template",
    "This Policy explains how MailPilot collects, uses, and shares information when you use the Service.",
)


def get_privacy_settings() -> "LegalPrivacySettings":
    from core.models import LegalPrivacySettings

    obj, created = LegalPrivacySettings.objects.get_or_create(
        singleton_key=1,
        defaults=DEFAULT_PRIVACY_SETTINGS,
    )
    if created:
        return obj

    body = (obj.body_html or "").strip()
    needs_refresh = (not body) or any(marker in body for marker in _OLD_PRIVACY_MARKERS)
    if needs_refresh:
        obj.title = DEFAULT_PRIVACY_SETTINGS["title"]
        obj.effective_date = DEFAULT_PRIVACY_SETTINGS["effective_date"]
        obj.body_html = DEFAULT_PRIVACY_BODY_HTML
        obj.is_published = True
        obj.save(update_fields=["title", "effective_date", "body_html", "is_published", "updated_at"])
    return obj


def get_privacy_page_payload() -> dict[str, Any]:
    """Structured payload for the Voiexa-style privacy layout."""
    settings_obj = get_privacy_settings()
    return {
        "privacy_page": settings_obj,
        "privacy_intro": PRIVACY_INTRO,
        "privacy_highlights": PRIVACY_HIGHLIGHTS,
        "privacy_sections": PRIVACY_SECTIONS,
    }
