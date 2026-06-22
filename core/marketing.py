from __future__ import annotations

from core.models import HowItWorksStep, MarketingFaqItem, MarketingFaqSettings, MarketingFeature, MarketingHeroInboxItem, MarketingHeroSettings, MarketingPricingPlan, MarketingPricingSettings, MarketingReview

DEFAULT_MARKETING_FEATURES: list[dict[str, str | int | bool]] = [
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


def marketing_features_queryset(*, homepage_only: bool = False):
    qs = MarketingFeature.objects.filter(is_published=True).order_by("sort_order", "pk")
    if homepage_only:
        qs = qs.filter(show_on_homepage=True)
    return qs


def seed_default_marketing_features() -> None:
    if MarketingFeature.objects.exists():
        return
    MarketingFeature.objects.bulk_create(
        [MarketingFeature(**row, is_published=True, show_on_homepage=True) for row in DEFAULT_MARKETING_FEATURES]
    )


DEFAULT_HOW_IT_WORKS_STEPS: list[dict[str, str | int | bool]] = [
    {
        "title": "Poll inbox",
        "description": (
            "Gmail API (recent threads) or IMAP INBOX on a schedule, manual “Run poll”, "
            "or IMAP IDLE for faster SMTP inboxes."
        ),
        "accent": HowItWorksStep.ACCENT_BLUE,
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
        "accent": HowItWorksStep.ACCENT_SKY,
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
        "accent": HowItWorksStep.ACCENT_PURPLE,
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
        "accent": HowItWorksStep.ACCENT_PINK,
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
        "accent": HowItWorksStep.ACCENT_GREEN,
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
        "accent": HowItWorksStep.ACCENT_ORANGE,
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


def how_it_works_steps_queryset(*, homepage_only: bool = False):
    qs = HowItWorksStep.objects.filter(is_published=True).order_by("sort_order", "pk")
    if homepage_only:
        qs = qs.filter(show_on_homepage=True)
    return qs


def seed_default_how_it_works_steps() -> None:
    if HowItWorksStep.objects.exists():
        return
    HowItWorksStep.objects.bulk_create(
        [HowItWorksStep(**row, is_published=True, show_on_homepage=True) for row in DEFAULT_HOW_IT_WORKS_STEPS]
    )


DEFAULT_MARKETING_REVIEWS: list[dict[str, str | int | bool]] = [
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


def marketing_reviews_queryset(*, homepage_only: bool = False):
    qs = MarketingReview.objects.filter(is_published=True).order_by("sort_order", "pk")
    if homepage_only:
        qs = qs.filter(show_on_homepage=True)
    return qs


def seed_default_marketing_reviews() -> None:
    if MarketingReview.objects.exists():
        return
    MarketingReview.objects.bulk_create(
        [MarketingReview(**row, is_published=True) for row in DEFAULT_MARKETING_REVIEWS]
    )


DEFAULT_PRICING_SETTINGS = {
    "section_tag": "Pricing",
    "title_lead": "Simple plans for",
    "title_highlight": "every inbox size",
    "intro": (
        "Simple token plans for every inbox size. Connect your inbox in Setup, "
        "then let MailPilot draft or send safely."
    ),
    "demo_note": (
        "Starter: 20 auto-sends total (80 tokens lifetime). Pro: monthly billing via Stripe. "
        "Draft mode does not use tokens."
    ),
}

_STARTER_FEATURES = """<strong>80 tokens</strong> lifetime (up to <strong>20</strong> auto-sent replies)
<strong>20 auto-sends/day</strong> safety cap while active
1 connected inbox (Gmail or IMAP)
Basic KB: 1 crawl or upload
Keyword filter + LLM relevance
Dashboard queue & unlimited drafts
No Telegram or WhatsApp"""

_PRO_FEATURES = """<strong>1,000 tokens</strong> per month (up to 200 auto-sent replies)
Up to 3 active Gmail or SMTP/IMAP inboxes
100 auto-sends/day/inbox safety cap
Full AI knowledge base (website crawl + file upload)
Multi Gmail OAuth + SMTP/IMAP mailbox support
Per-user encrypted credentials
Telegram & WhatsApp alerts and commands"""

_CUSTOM_FEATURES = """<strong>2,000 tokens</strong> + 4 Gmail/SMTP inboxes → <strong>$30/mo</strong>
<strong>3,000 tokens</strong> + 5 Gmail/SMTP inboxes → <strong>$40/mo</strong>
Or define your own tier (e.g. $50 → 5,000 sends)
Provider-aware daily safety caps
Telegram & WhatsApp alerts and chat commands
Annual billing option
Priority onboarding & team seats"""

DEFAULT_PRICING_PLANS: list[dict[str, str | int | bool]] = [
    {
        "plan_code": MarketingPricingPlan.PLAN_STARTER,
        "tier_label": "Starter",
        "ribbon_type": MarketingPricingPlan.RIBBON_FREE,
        "ribbon_label": "Free",
        "ribbon_icon_class": "fa-solid fa-circle-check",
        "price_display": "$0",
        "price_suffix": "/trial",
        "period_text": "20 auto-sends total · then upgrade",
        "description": (
            "Connect one inbox, test AI replies, and keep draft mode unlimited. "
            "After 20 auto-sent emails, upgrade to Pro or Custom."
        ),
        "features": _STARTER_FEATURES,
        "cta_label": "Start free trial",
        "cta_label_authenticated": "View my trial",
        "cta_label_starter_expired": "Upgrade required",
        "cta_style": MarketingPricingPlan.CTA_SECONDARY,
        "is_featured": False,
        "sort_order": 1,
    },
    {
        "plan_code": MarketingPricingPlan.PLAN_PRO,
        "tier_label": "Pro",
        "top_badge": "50% launch offer",
        "ribbon_type": MarketingPricingPlan.RIBBON_SOON,
        "ribbon_label": "Demo checkout on localhost",
        "ribbon_icon_class": "fa-solid fa-bolt",
        "price_display": "$20",
        "price_suffix": "/mo",
        "price_was": "$40",
        "price_save_label": "Save 50%",
        "period_text": "Billed monthly · cancel anytime",
        "yearly_price_display": "$200",
        "yearly_price_suffix": "/yr",
        "yearly_price_was": "$400",
        "yearly_price_save_label": "Save 50%",
        "yearly_period_text": "Billed annually · cancel anytime",
        "description": (
            "Production volume for growing teams—RAG knowledge base, polling, and reliable auto-send limits."
        ),
        "features": _PRO_FEATURES,
        "cta_label": "Get Pro",
        "cta_style": MarketingPricingPlan.CTA_PRIMARY,
        "is_featured": True,
        "sort_order": 2,
    },
    {
        "plan_code": MarketingPricingPlan.PLAN_CUSTOM,
        "tier_label": "Custom",
        "top_badge": "Most popular",
        "ribbon_type": MarketingPricingPlan.RIBBON_SOON,
        "ribbon_label": "Build your plan",
        "ribbon_icon_class": "fa-solid fa-sliders",
        "price_display": "You choose",
        "period_text": "Live price as you adjust",
        "yearly_period_text": "Annual or monthly in the builder",
        "description": (
            "Slide tokens and inbox count — see your monthly price instantly, then checkout or contact us."
        ),
        "features": _CUSTOM_FEATURES,
        "cta_label": "Build Custom plan",
        "cta_style": MarketingPricingPlan.CTA_SECONDARY,
        "is_featured": False,
        "sort_order": 3,
    },
]


def get_pricing_settings() -> MarketingPricingSettings:
    obj, _ = MarketingPricingSettings.objects.get_or_create(
        singleton_key=1,
        defaults=DEFAULT_PRICING_SETTINGS,
    )
    return obj


def marketing_pricing_plans_queryset(*, homepage_only: bool = False):
    qs = MarketingPricingPlan.objects.filter(is_published=True).order_by("sort_order", "pk")
    if homepage_only:
        qs = qs.filter(show_on_homepage=True)
    return qs


def seed_default_pricing() -> None:
    if not MarketingPricingSettings.objects.exists():
        MarketingPricingSettings.objects.create(singleton_key=1, **DEFAULT_PRICING_SETTINGS)
    if MarketingPricingPlan.objects.exists():
        return
    MarketingPricingPlan.objects.bulk_create(
        [MarketingPricingPlan(**row, is_published=True, show_on_homepage=True) for row in DEFAULT_PRICING_PLANS]
    )


DEFAULT_HERO_SETTINGS = {
    "card_title": "MailPilot — Live Inbox",
    "card_icon_class": "fa-solid fa-inbox",
}

DEFAULT_HERO_INBOX_ITEMS: list[dict[str, str | int | bool]] = [
    {
        "sender_name": "Alice Kim",
        "sender_context": "Product Inquiry",
        "subject": "What pricing plans do you offer for enterprise?",
        "avatar_initials": "AK",
        "avatar_color_start": "#4f6ef7",
        "avatar_color_end": "#a78bfa",
        "badge_type": MarketingHeroInboxItem.BADGE_REPLIED,
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
        "badge_type": MarketingHeroInboxItem.BADGE_RAG,
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
        "badge_type": MarketingHeroInboxItem.BADGE_PENDING,
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
        "badge_type": MarketingHeroInboxItem.BADGE_SKIPPED,
        "badge_label": "— Skipped",
        "sort_order": 4,
    },
]


def get_hero_settings() -> MarketingHeroSettings:
    obj, _ = MarketingHeroSettings.objects.get_or_create(
        singleton_key=1,
        defaults=DEFAULT_HERO_SETTINGS,
    )
    return obj


def marketing_hero_inbox_queryset(*, homepage_only: bool = False):
    qs = MarketingHeroInboxItem.objects.filter(is_published=True).order_by("sort_order", "pk")
    if homepage_only:
        qs = qs.filter(show_on_homepage=True)
    return qs


def seed_default_hero_inbox() -> None:
    if not MarketingHeroSettings.objects.exists():
        MarketingHeroSettings.objects.create(singleton_key=1, **DEFAULT_HERO_SETTINGS)
    if MarketingHeroInboxItem.objects.exists():
        return
    MarketingHeroInboxItem.objects.bulk_create(
        [MarketingHeroInboxItem(**row, is_published=True, show_on_homepage=True) for row in DEFAULT_HERO_INBOX_ITEMS]
    )


DEFAULT_FAQ_SETTINGS = {
    "section_tag": "FAQ",
    "title_lead": "Common",
    "title_highlight": "questions",
    "intro_html": (
        'Quick answers about setup, routing, knowledge base, and billing. Still stuck? '
        'Use the <a href="#contact" style="color:#a5b4fc;">contact form</a> on this page.'
    ),
}

DEFAULT_FAQ_ITEMS: list[dict[str, str | int | bool]] = [
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


def get_faq_settings() -> MarketingFaqSettings:
    obj, _ = MarketingFaqSettings.objects.get_or_create(
        singleton_key=1,
        defaults=DEFAULT_FAQ_SETTINGS,
    )
    return obj


def marketing_faq_queryset(*, homepage_only: bool = False):
    qs = MarketingFaqItem.objects.filter(is_published=True).order_by("sort_order", "pk")
    if homepage_only:
        qs = qs.filter(show_on_homepage=True)
    return qs


def seed_default_faq() -> None:
    if not MarketingFaqSettings.objects.exists():
        MarketingFaqSettings.objects.create(singleton_key=1, **DEFAULT_FAQ_SETTINGS)
    if MarketingFaqItem.objects.exists():
        return
    MarketingFaqItem.objects.bulk_create(
        [MarketingFaqItem(**row, is_published=True, show_on_homepage=True) for row in DEFAULT_FAQ_ITEMS]
    )
