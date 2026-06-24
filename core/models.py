from __future__ import annotations

from datetime import date

from django.contrib.auth.models import User
from django.db import models


class UserProfile(models.Model):
    """Extended profile (Django User already has username, email, first_name, last_name)."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    avatar = models.FileField(upload_to="avatars/", blank=True, null=True)
    display_name = models.CharField(max_length=120, blank=True, default="")
    phone = models.CharField(max_length=32, blank=True, default="")
    company = models.CharField(max_length=160, blank=True, default="")
    timezone = models.CharField(max_length=64, blank=True, default="UTC")
    notes = models.TextField(blank=True, default="", help_text="Internal notes (optional)")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_userprofile"

    def __str__(self) -> str:
        return f"Profile({self.user_id})"


class UserMailSettings(models.Model):
    """Per-user mail automation config (non-global). Secrets stored encrypted."""

    MODE_GMAIL = "gmail"
    MODE_SMTP = "smtp"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="mail_settings")
    settings_json = models.JSONField(default=dict, blank=True)
    active_transport_mode = models.CharField(max_length=8, default=MODE_GMAIL)
    default_account_id = models.PositiveIntegerField(null=True, blank=True)
    smtp_password_enc = models.TextField(blank=True, default="")
    imap_password_enc = models.TextField(blank=True, default="")
    llm_api_key_enc = models.TextField(blank=True, default="")
    google_oauth_token_enc = models.TextField(blank=True, default="")
    client_secret_json_enc = models.TextField(blank=True, default="")
    telegram_bot_token_enc = models.TextField(blank=True, default="")
    whatsapp_access_token_enc = models.TextField(blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_usermailsettings"


class MailAccount(models.Model):
    """Per-user mailbox slot (up to 5 Gmail or 5 SMTP)."""

    TRANSPORT_GMAIL = "gmail_api"
    TRANSPORT_SMTP = "smtp"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="mail_accounts")
    slot = models.PositiveSmallIntegerField()
    transport = models.CharField(max_length=16)
    label = models.CharField(max_length=80, blank=True, default="")
    is_enabled = models.BooleanField(default=True)
    config_json = models.JSONField(default=dict, blank=True)
    oauth_token_enc = models.TextField(blank=True, default="")
    client_secret_enc = models.TextField(blank=True, default="")
    smtp_password_enc = models.TextField(blank=True, default="")
    imap_password_enc = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_mailaccount"
        constraints = [
            models.UniqueConstraint(fields=["user", "slot", "transport"], name="uq_mailaccount_user_slot_transport"),
        ]
        ordering = ["slot", "id"]

    def __str__(self) -> str:
        return f"MailAccount({self.user_id}, {self.transport}, slot={self.slot})"


class UserSubscription(models.Model):
    """Current billing plan and entitlement overrides for one user."""

    PLAN_STARTER = "starter"
    PLAN_PRO = "pro"
    PLAN_CUSTOM = "custom"
    PLAN_CHOICES = [
        (PLAN_STARTER, "Starter"),
        (PLAN_PRO, "Pro"),
        (PLAN_CUSTOM, "Custom"),
    ]

    STATUS_ACTIVE = "active"
    STATUS_TRIALING = "trialing"
    STATUS_PAST_DUE = "past_due"
    STATUS_CANCELED = "canceled"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_TRIALING, "Trialing"),
        (STATUS_PAST_DUE, "Past due"),
        (STATUS_CANCELED, "Canceled"),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="subscription")
    plan_code = models.CharField(max_length=24, choices=PLAN_CHOICES, default=PLAN_STARTER, db_index=True)
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_ACTIVE, db_index=True)
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    monthly_token_limit = models.PositiveIntegerField(null=True, blank=True)
    active_inbox_limit = models.PositiveIntegerField(null=True, blank=True)
    daily_send_limit = models.PositiveIntegerField(null=True, blank=True)
    kb_source_limit = models.PositiveIntegerField(null=True, blank=True)
    telegram_enabled = models.BooleanField(null=True, blank=True)
    whatsapp_enabled = models.BooleanField(null=True, blank=True)
    stripe_customer_id = models.CharField(max_length=128, blank=True, default="", db_index=True)
    stripe_subscription_id = models.CharField(max_length=128, blank=True, default="", db_index=True)
    payment_provider = models.CharField(
        max_length=16,
        blank=True,
        default="",
        help_text="Last successful checkout provider: stripe or paypal.",
    )
    paypal_subscription_id = models.CharField(max_length=128, blank=True, default="", db_index=True)
    starter_lifetime_sends = models.PositiveIntegerField(default=0)
    starter_expired_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set when Pro/Custom payment is confirmed (Stripe webhook or admin).",
    )
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "core_usersubscription"

    def __str__(self) -> str:
        return f"UserSubscription({self.user_id}, {self.plan_code}, {self.status})"


class UsageCounter(models.Model):
    """Monthly token usage for a user."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="usage_counters")
    period_key = models.CharField(max_length=7, db_index=True)  # YYYY-MM
    tokens_used = models.PositiveIntegerField(default=0)
    auto_sent_count = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_usagecounter"
        constraints = [
            models.UniqueConstraint(fields=["user", "period_key"], name="uq_usagecounter_user_period"),
        ]

    def __str__(self) -> str:
        return f"UsageCounter({self.user_id}, {self.period_key}, tokens={self.tokens_used})"


class DailySendCounter(models.Model):
    """Daily provider-safety send count for one mailbox."""

    PROVIDER_GMAIL_PERSONAL = "gmail_personal"
    PROVIDER_GOOGLE_WORKSPACE = "google_workspace"
    PROVIDER_SMTP_PERSONAL = "smtp_personal"
    PROVIDER_SMTP_BUSINESS = "smtp_business"
    PROVIDER_CHOICES = [
        (PROVIDER_GMAIL_PERSONAL, "Gmail personal"),
        (PROVIDER_GOOGLE_WORKSPACE, "Google Workspace"),
        (PROVIDER_SMTP_PERSONAL, "SMTP personal"),
        (PROVIDER_SMTP_BUSINESS, "SMTP business"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="daily_send_counters")
    mail_account = models.ForeignKey(MailAccount, on_delete=models.CASCADE, related_name="daily_send_counters")
    date = models.DateField(db_index=True)
    provider_profile = models.CharField(max_length=32, choices=PROVIDER_CHOICES, default=PROVIDER_GMAIL_PERSONAL)
    sends_used = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_dailysendcounter"
        constraints = [
            models.UniqueConstraint(fields=["mail_account", "date"], name="uq_dailysendcounter_account_date"),
        ]
        indexes = [models.Index(fields=["user", "-date"], name="idx_dailysendcounter_user_date")]


class UsageEvent(models.Model):
    """Idempotent ledger for token-consuming events."""

    TYPE_AUTO_SEND = "auto_send"
    TYPE_CHOICES = [(TYPE_AUTO_SEND, "Auto-send")]

    STATUS_RESERVED = "reserved"
    STATUS_COMMITTED = "committed"
    STATUS_FAILED = "failed"
    STATUS_REFUNDED = "refunded"
    STATUS_CHOICES = [
        (STATUS_RESERVED, "Reserved"),
        (STATUS_COMMITTED, "Committed"),
        (STATUS_FAILED, "Failed"),
        (STATUS_REFUNDED, "Refunded"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="usage_events")
    mail_account = models.ForeignKey(MailAccount, on_delete=models.CASCADE, related_name="usage_events")
    message_id = models.CharField(max_length=255)
    event_type = models.CharField(max_length=32, choices=TYPE_CHOICES, default=TYPE_AUTO_SEND)
    units = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_RESERVED, db_index=True)
    period_key = models.CharField(max_length=7, db_index=True)
    date = models.DateField(db_index=True)
    meta_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    committed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "core_usageevent"
        constraints = [
            models.UniqueConstraint(
                fields=["mail_account", "message_id", "event_type"],
                name="uq_usageevent_account_message_type",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "period_key", "status"], name="idx_usageevent_user_period"),
        ]


class PasswordResetOTP(models.Model):
    """One-time codes for email OTP password reset (hashed, time-limited)."""

    email = models.CharField(max_length=254, db_index=True)
    otp_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "core_passwordresetotp"

    def __str__(self) -> str:
        return f"PasswordResetOTP({self.email})"


class ContactSubmission(models.Model):
    """Landing page contact form submissions."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    name = models.CharField(max_length=120)
    email = models.EmailField(max_length=254)
    phone = models.CharField(max_length=32, blank=True, default="")
    message = models.TextField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    notified_team = models.BooleanField(default=False)
    notified_user = models.BooleanField(default=False)

    class Meta:
        db_table = "core_contactsubmission"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Contact({self.email}, {self.created_at:%Y-%m-%d})"


class MarketingFeature(models.Model):
    """Public marketing feature cards (/features and homepage)."""

    title = models.CharField(max_length=120)
    description = models.TextField()
    icon_class = models.CharField(
        max_length=80,
        default="fa-solid fa-star",
        help_text="Font Awesome class, e.g. fa-solid fa-brain",
    )
    accent_color = models.CharField(
        max_length=7,
        default="#4f6ef7",
        help_text="Hex color for card accent, e.g. #4f6ef7",
    )
    sort_order = models.PositiveIntegerField(
        default=0,
        db_index=True,
        help_text="Display order (1, 2, 3… - lower numbers appear first).",
    )
    is_published = models.BooleanField(default=True, db_index=True)
    show_on_homepage = models.BooleanField(
        default=True,
        help_text="Show on landing page features section",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_marketingfeature"
        ordering = ["sort_order", "id"]
        verbose_name = "marketing feature"
        verbose_name_plural = "marketing features"

    def __str__(self) -> str:
        return self.title

    @property
    def icon_background_style(self) -> str:
        raw = (self.accent_color or "#4f6ef7").strip().lstrip("#")
        if len(raw) != 6:
            return "background:rgba(79,110,247,0.15)"
        try:
            r = int(raw[0:2], 16)
            g = int(raw[2:4], 16)
            b = int(raw[4:6], 16)
        except ValueError:
            return "background:rgba(79,110,247,0.15)"
        return f"background:rgba({r},{g},{b},0.15)"


class HowItWorksStep(models.Model):
    """Workflow steps for /how-it-works and homepage section."""

    ACCENT_BLUE = "blue"
    ACCENT_SKY = "sky"
    ACCENT_PURPLE = "purple"
    ACCENT_PINK = "pink"
    ACCENT_GREEN = "green"
    ACCENT_ORANGE = "orange"
    ACCENT_CHOICES = [
        (ACCENT_BLUE, "Blue"),
        (ACCENT_SKY, "Sky"),
        (ACCENT_PURPLE, "Purple"),
        (ACCENT_PINK, "Pink"),
        (ACCENT_GREEN, "Green"),
        (ACCENT_ORANGE, "Orange"),
    ]

    title = models.CharField(max_length=120)
    description = models.TextField()
    accent = models.CharField(max_length=16, choices=ACCENT_CHOICES, default=ACCENT_BLUE)
    icon_svg = models.TextField(
        blank=True,
        default="",
        help_text="Inline SVG for homepage cards (optional on dedicated page).",
    )
    sort_order = models.PositiveIntegerField(
        default=0,
        db_index=True,
        help_text="Display order (1, 2, 3… - lower numbers appear first).",
    )
    is_published = models.BooleanField(default=True, db_index=True)
    show_on_homepage = models.BooleanField(
        default=True,
        help_text="Show on landing page how-it-works section",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_howitworksstep"
        ordering = ["sort_order", "id"]
        verbose_name = "how it works step"
        verbose_name_plural = "how it works"

    def __str__(self) -> str:
        return self.title


class MarketingReview(models.Model):
    """Customer review / testimonial cards (/reviews and homepage)."""

    quote = models.TextField()
    metric = models.CharField(max_length=160, blank=True, default="")
    author_name = models.CharField(max_length=80)
    author_role = models.CharField(max_length=160)
    avatar_initials = models.CharField(
        max_length=4,
        default="MP",
        help_text="Initials shown in the avatar circle, e.g. AK",
    )
    accent_primary = models.CharField(max_length=7, default="#4f6ef7")
    accent_secondary = models.CharField(max_length=7, default="#a78bfa")
    rating = models.PositiveSmallIntegerField(default=5)
    sort_order = models.PositiveIntegerField(
        default=0,
        db_index=True,
        help_text="Display order (1, 2, 3… - lower numbers appear first).",
    )
    is_published = models.BooleanField(default=True, db_index=True)
    show_on_homepage = models.BooleanField(
        default=True,
        help_text="Show on landing page testimonials section",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_marketingreview"
        ordering = ["sort_order", "id"]
        verbose_name = "review"
        verbose_name_plural = "reviews"

    def __str__(self) -> str:
        return self.author_name

    @property
    def stars_display(self) -> str:
        return "★" * max(1, min(5, int(self.rating or 5)))

    @property
    def avatar_style_page(self) -> str:
        a1 = (self.accent_primary or "#4f6ef7").strip()
        a2 = (self.accent_secondary or "#a78bfa").strip()
        return f"--a1:{a1};--a2:{a2}"

    @property
    def avatar_style_home(self) -> str:
        a1 = (self.accent_primary or "#4f6ef7").strip()
        a2 = (self.accent_secondary or "#a78bfa").strip()
        return f"--av1:{a1};--av2:{a2}"


class MarketingPricingSettings(models.Model):
    """Singleton copy for /pricing and homepage pricing section header."""

    singleton_key = models.PositiveSmallIntegerField(primary_key=True, default=1)
    section_tag = models.CharField(max_length=40, default="Pricing")
    title_lead = models.CharField(max_length=120, default="Simple plans for")
    title_highlight = models.CharField(max_length=120, default="every inbox size")
    intro = models.TextField(
        default="Simple token plans for every inbox size. Connect your inbox in Setup, then let MailPilot draft or send safely."
    )
    demo_note = models.TextField(
        default="Starter: 20 auto-sends total (80 tokens lifetime). Pro: monthly billing via Stripe. Draft mode does not use tokens."
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_marketingpricingsettings"
        verbose_name = "pricing page"
        verbose_name_plural = "pricing page"

    def __str__(self) -> str:
        return "Pricing page copy"


class MarketingPricingPlan(models.Model):
    """Public pricing plan cards (Starter / Pro / Custom)."""

    PLAN_STARTER = "starter"
    PLAN_PRO = "pro"
    PLAN_CUSTOM = "custom"
    PLAN_CHOICES = [
        (PLAN_STARTER, "Starter"),
        (PLAN_PRO, "Pro"),
        (PLAN_CUSTOM, "Custom"),
    ]

    RIBBON_NONE = ""
    RIBBON_FREE = "free"
    RIBBON_SOON = "soon"
    RIBBON_CHOICES = [
        (RIBBON_NONE, "None"),
        (RIBBON_FREE, "Free badge"),
        (RIBBON_SOON, "Soon / info badge"),
    ]

    CTA_PRIMARY = "primary"
    CTA_SECONDARY = "secondary"
    CTA_STYLE_CHOICES = [
        (CTA_PRIMARY, "Primary"),
        (CTA_SECONDARY, "Secondary"),
    ]

    plan_code = models.CharField(max_length=16, choices=PLAN_CHOICES, unique=True)
    tier_label = models.CharField(max_length=40)
    top_badge = models.CharField(max_length=80, blank=True, default="", help_text="Optional pill above card, e.g. 50% launch offer")
    ribbon_type = models.CharField(max_length=8, choices=RIBBON_CHOICES, blank=True, default=RIBBON_NONE)
    ribbon_label = models.CharField(max_length=80, blank=True, default="")
    ribbon_icon_class = models.CharField(max_length=80, blank=True, default="fa-solid fa-bolt")
    price_display = models.CharField(max_length=40, help_text='Main price, e.g. $0, $20, or "You choose"')
    price_suffix = models.CharField(max_length=24, blank=True, default="", help_text="Suffix in smaller text, e.g. /mo")
    price_was = models.CharField(max_length=24, blank=True, default="", help_text="Strikethrough compare price, e.g. $40")
    price_save_label = models.CharField(max_length=40, blank=True, default="", help_text='e.g. "Save 50%"')
    period_text = models.CharField(max_length=160)
    yearly_price_display = models.CharField(
        max_length=40,
        blank=True,
        default="",
        help_text='Yearly price shown when toggle is on, e.g. $200. Leave blank to reuse monthly price.',
    )
    yearly_price_suffix = models.CharField(
        max_length=24,
        blank=True,
        default="/yr",
        help_text="Suffix when yearly toggle is on, e.g. /yr",
    )
    yearly_price_was = models.CharField(
        max_length=24,
        blank=True,
        default="",
        help_text="Strikethrough compare price for yearly billing",
    )
    yearly_price_save_label = models.CharField(max_length=40, blank=True, default="")
    yearly_period_text = models.CharField(
        max_length=160,
        blank=True,
        default="",
        help_text="Period line when yearly toggle is on",
    )
    description = models.TextField()
    features = models.TextField(help_text="One bullet per line. HTML like <strong> is allowed.")
    cta_label = models.CharField(max_length=80, help_text="Button label for visitors")
    cta_label_authenticated = models.CharField(
        max_length=80,
        blank=True,
        default="",
        help_text="Starter: label when logged in (e.g. View my trial)",
    )
    cta_label_starter_expired = models.CharField(
        max_length=80,
        blank=True,
        default="",
        help_text="Starter: label when trial expired",
    )
    cta_style = models.CharField(max_length=12, choices=CTA_STYLE_CHOICES, default=CTA_SECONDARY)
    is_featured = models.BooleanField(
        default=False,
        help_text="Highlighted card (selected by default on the page)",
    )
    sort_order = models.PositiveIntegerField(
        default=0,
        db_index=True,
        help_text="Display order (1, 2, 3… - lower numbers appear first).",
    )
    is_published = models.BooleanField(default=True, db_index=True)
    show_on_homepage = models.BooleanField(
        default=True,
        help_text="Show on landing page pricing section",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_marketingpricingplan"
        ordering = ["sort_order", "id"]
        verbose_name = "pricing plan"
        verbose_name_plural = "pricing plans"

    def __str__(self) -> str:
        return self.tier_label

    @property
    def feature_lines(self) -> list[str]:
        return [line.strip() for line in (self.features or "").splitlines() if line.strip()]

    @property
    def yearly_price_resolved(self) -> str:
        return (self.yearly_price_display or "").strip() or self.price_display

    @property
    def yearly_suffix_resolved(self) -> str:
        if (self.yearly_price_display or "").strip():
            return (self.yearly_price_suffix or "/yr").strip()
        return self.price_suffix or ""

    @property
    def yearly_was_resolved(self) -> str:
        return (self.yearly_price_was or "").strip()

    @property
    def yearly_save_resolved(self) -> str:
        return (self.yearly_price_save_label or "").strip() or (self.price_save_label or "").strip()

    @property
    def yearly_period_resolved(self) -> str:
        return (self.yearly_period_text or "").strip() or self.period_text


class MarketingHeroSettings(models.Model):
    """Singleton copy for homepage hero inbox preview card."""

    singleton_key = models.PositiveSmallIntegerField(primary_key=True, default=1)
    card_title = models.CharField(max_length=120, default="MailPilot | Live Inbox")
    card_icon_class = models.CharField(
        max_length=80,
        default="fa-solid fa-inbox",
        help_text="Font Awesome class for the card title icon",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_marketingherosettings"
        verbose_name = "hero inbox card"
        verbose_name_plural = "hero inbox card"

    def __str__(self) -> str:
        return self.card_title


class MarketingHeroInboxItem(models.Model):
    """Demo inbox rows in the landing page hero card."""

    BADGE_REPLIED = "replied"
    BADGE_RAG = "rag"
    BADGE_PENDING = "pending"
    BADGE_SKIPPED = "skipped"
    BADGE_CHOICES = [
        (BADGE_REPLIED, "Auto-replied"),
        (BADGE_RAG, "RAG enhanced"),
        (BADGE_PENDING, "In queue"),
        (BADGE_SKIPPED, "Skipped"),
    ]

    sender_name = models.CharField(max_length=80)
    sender_context = models.CharField(
        max_length=80,
        blank=True,
        default="",
        help_text="Short label after the name, e.g. Product Inquiry",
    )
    subject = models.CharField(max_length=200)
    avatar_initials = models.CharField(max_length=4, default="AK")
    avatar_color_start = models.CharField(max_length=7, default="#4f6ef7")
    avatar_color_end = models.CharField(max_length=7, default="#a78bfa")
    badge_type = models.CharField(max_length=16, choices=BADGE_CHOICES, default=BADGE_REPLIED)
    badge_label = models.CharField(max_length=40, default="✓ Auto-Replied")
    badge_icon_class = models.CharField(
        max_length=80,
        blank=True,
        default="",
        help_text="Optional Font Awesome icon before badge text (e.g. fa-solid fa-brain)",
    )
    sort_order = models.PositiveIntegerField(
        default=0,
        db_index=True,
        help_text="Display order (1, 2, 3… - lower numbers appear first).",
    )
    is_published = models.BooleanField(default=True, db_index=True)
    show_on_homepage = models.BooleanField(
        default=True,
        help_text="Show on landing page hero inbox card",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_marketingheroinboxitem"
        ordering = ["sort_order", "id"]
        verbose_name = "hero inbox row"
        verbose_name_plural = "hero inbox rows"

    def __str__(self) -> str:
        return self.sender_name

    @property
    def sender_display(self) -> str:
        ctx = (self.sender_context or "").strip()
        if ctx:
            return f"{self.sender_name} - {ctx}"
        return self.sender_name

    @property
    def avatar_gradient_style(self) -> str:
        a1 = (self.avatar_color_start or "#4f6ef7").strip()
        a2 = (self.avatar_color_end or "#a78bfa").strip()
        return f"background:linear-gradient(135deg,{a1},{a2})"

    @property
    def badge_css_class(self) -> str:
        return f"badge-{self.badge_type}"


class MarketingFaqSettings(models.Model):
    """Singleton copy for landing page FAQ section header."""

    singleton_key = models.PositiveSmallIntegerField(primary_key=True, default=1)
    section_tag = models.CharField(max_length=40, default="FAQ")
    title_lead = models.CharField(max_length=80, default="Common")
    title_highlight = models.CharField(max_length=80, default="questions")
    intro_html = models.TextField(
        blank=True,
        default="",
        help_text="Short intro under the title. Basic HTML allowed (e.g. links).",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_marketingfaqsettings"
        verbose_name = "FAQ page"
        verbose_name_plural = "FAQ page"

    def __str__(self) -> str:
        return "FAQ section"


class MarketingFaqItem(models.Model):
    """FAQ accordion rows on the landing page."""

    question = models.CharField(max_length=200)
    answer_html = models.TextField(
        help_text="Answer body. Basic HTML allowed (strong, a, etc.).",
    )
    icon_class = models.CharField(
        max_length=80,
        default="fa-solid fa-circle-question",
        help_text="Font Awesome class shown before the question",
    )
    sort_order = models.PositiveIntegerField(
        default=0,
        db_index=True,
        help_text="Display order (1, 2, 3… - lower numbers appear first).",
    )
    is_published = models.BooleanField(default=True, db_index=True)
    show_on_homepage = models.BooleanField(
        default=True,
        help_text="Show on landing page FAQ section",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_marketingfaqitem"
        ordering = ["sort_order", "id"]
        verbose_name = "FAQ item"
        verbose_name_plural = "FAQ items"

    def __str__(self) -> str:
        return self.question


class LegalTermsSettings(models.Model):
    """Singleton content for /terms."""

    singleton_key = models.PositiveSmallIntegerField(primary_key=True, default=1)
    title = models.CharField(max_length=120, default="Terms of Service")
    effective_date = models.DateField(default=date(2026, 4, 13))
    intro_html = models.TextField(
        blank=True,
        default="",
        help_text="Deprecated - use body_html. Kept for legacy migrations only.",
    )
    notice_html = models.TextField(
        blank=True,
        default="",
        help_text="Deprecated - use body_html. Kept for legacy migrations only.",
    )
    body_html = models.TextField(
        blank=True,
        default="",
        help_text="Full terms page content (single rich-text document).",
    )
    is_published = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_legaltermssettings"
        verbose_name = "terms page"
        verbose_name_plural = "terms page"

    def __str__(self) -> str:
        return self.title


class LegalTermsSection(models.Model):
    """Ordered section blocks on the terms page."""

    page = models.ForeignKey(
        LegalTermsSettings,
        on_delete=models.CASCADE,
        related_name="sections",
        default=1,
    )
    heading = models.CharField(max_length=200)
    body_html = models.TextField(help_text="Section body. Basic HTML allowed (p, ul, li, strong, a).")
    sort_order = models.PositiveIntegerField(
        default=0,
        db_index=True,
        help_text="Display order (1, 2, 3… - lower numbers appear first).",
    )
    is_published = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_legaltermssection"
        ordering = ["sort_order", "id"]
        verbose_name = "terms section"
        verbose_name_plural = "terms sections"

    def __str__(self) -> str:
        return self.heading


class LegalPrivacySettings(models.Model):
    """Singleton content for /privacy."""

    singleton_key = models.PositiveSmallIntegerField(primary_key=True, default=1)
    title = models.CharField(max_length=120, default="Privacy Policy")
    effective_date = models.DateField(default=date(2026, 4, 13))
    body_html = models.TextField(
        blank=True,
        default="",
        help_text="Full privacy page content (single rich-text document).",
    )
    is_published = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_legalprivacysettings"
        verbose_name = "privacy page"
        verbose_name_plural = "privacy page"

    def __str__(self) -> str:
        return self.title


class CustomPlanQuote(models.Model):
    """User-built custom plan configuration pending or completed payment."""

    STATUS_DRAFT = "draft"
    STATUS_PENDING = "pending"
    STATUS_PAID = "paid"
    STATUS_EXPIRED = "expired"
    STATUS_CANCELED = "canceled"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_PENDING, "Pending payment"),
        (STATUS_PAID, "Paid"),
        (STATUS_EXPIRED, "Expired"),
        (STATUS_CANCELED, "Canceled"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="custom_plan_quotes")
    tokens = models.PositiveIntegerField()
    inboxes = models.PositiveIntegerField()
    price_cents = models.PositiveIntegerField()
    currency = models.CharField(
        max_length=3,
        default="usd",
        help_text="ISO currency for price_cents (usd, gbp, eur).",
    )
    billing_interval = models.CharField(max_length=8, default="monthly")
    daily_send_limit = models.PositiveIntegerField(default=100)
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)
    stripe_session_id = models.CharField(max_length=255, blank=True, default="")
    expires_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_customplanquote"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "-created_at"], name="idx_customquote_user_created")]

    def __str__(self) -> str:
        return f"CustomPlanQuote({self.user_id}, {self.tokens} tok, {self.inboxes} inbox, ${self.price_cents / 100:.2f})"


class BillingPaymentEvent(models.Model):
    """Checkout and payment ledger for admin (provider, amount, IP)."""

    EVENT_CHECKOUT_STARTED = "checkout_started"
    EVENT_CHECKOUT_COMPLETED = "checkout_completed"
    EVENT_CHECKOUT_FAILED = "checkout_failed"
    EVENT_WEBHOOK = "webhook"
    EVENT_CHOICES = [
        (EVENT_CHECKOUT_STARTED, "Checkout started"),
        (EVENT_CHECKOUT_COMPLETED, "Checkout completed"),
        (EVENT_CHECKOUT_FAILED, "Checkout failed"),
        (EVENT_WEBHOOK, "Webhook"),
    ]

    PROVIDER_STRIPE = "stripe"
    PROVIDER_PAYPAL = "paypal"
    PROVIDER_CHOICES = [
        (PROVIDER_STRIPE, "Stripe"),
        (PROVIDER_PAYPAL, "PayPal"),
    ]

    STATUS_PENDING = "pending"
    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"
    STATUS_CANCELED = "canceled"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SUCCEEDED, "Succeeded"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELED, "Canceled"),
    ]

    user = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="billing_payment_events",
    )
    event_type = models.CharField(max_length=32, choices=EVENT_CHOICES, db_index=True)
    provider = models.CharField(max_length=16, blank=True, default="", db_index=True)
    plan_code = models.CharField(max_length=24, blank=True, default="", db_index=True)
    amount_cents = models.PositiveIntegerField(null=True, blank=True)
    currency = models.CharField(max_length=3, blank=True, default="")
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    external_id = models.CharField(max_length=255, blank=True, default="", db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True, default="")
    detail = models.CharField(max_length=512, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "core_billingpaymentevent"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["provider", "-created_at"], name="idx_bp_provider_created"),
            models.Index(fields=["user", "-created_at"], name="idx_bp_user_created"),
        ]

    def __str__(self) -> str:
        who = self.user_id or "?"
        return f"BillingPaymentEvent({who}, {self.provider}, {self.event_type}, {self.status})"


class Stripe(models.Model):
    """Singleton Stripe credentials (admin-managed)."""

    PROVIDER_STRIPE = "stripe"
    PROVIDER_CHOICES = [(PROVIDER_STRIPE, "Stripe")]

    STRIPE_KEY_AUTO = "auto"
    STRIPE_KEY_TEST = "test"
    STRIPE_KEY_LIVE = "live"
    STRIPE_KEY_ENVIRONMENT_CHOICES = (
        (STRIPE_KEY_AUTO, "Auto — test keys when DEBUG, live keys on production"),
        (STRIPE_KEY_TEST, "Force test keys (localhost / staging)"),
        (STRIPE_KEY_LIVE, "Force live keys (production)"),
    )

    singleton_key = models.PositiveSmallIntegerField(default=1, unique=True)
    provider = models.CharField(max_length=32, choices=PROVIDER_CHOICES, default=PROVIDER_STRIPE)
    is_enabled = models.BooleanField(
        default=False,
        help_text="When enabled, stored credentials override STRIPE_* environment variables.",
    )
    stripe_key_environment = models.CharField(
        max_length=16,
        choices=STRIPE_KEY_ENVIRONMENT_CHOICES,
        default=STRIPE_KEY_AUTO,
        help_text="Which key set Checkout uses. Auto follows DEBUG (local=test, production=live).",
    )
    stripe_publishable_key = models.CharField(max_length=255, blank=True, default="")
    stripe_price_pro_monthly = models.CharField(
        max_length=128,
        blank=True,
        default="",
        help_text="Stripe Price ID for Pro monthly (price_...).",
    )
    stripe_price_pro_yearly = models.CharField(
        max_length=128,
        blank=True,
        default="",
        help_text="Optional Stripe Price ID for Pro yearly (price_...).",
    )
    stripe_secret_key_enc = models.TextField(
        blank=True,
        default="",
        help_text="Encrypted live secret key (sk_live_).",
    )
    stripe_restricted_key_enc = models.TextField(
        blank=True,
        default="",
        help_text="Encrypted live restricted key (rk_live_).",
    )
    stripe_test_secret_key_enc = models.TextField(
        blank=True,
        default="",
        help_text="Encrypted test secret key (sk_test_).",
    )
    stripe_test_restricted_key_enc = models.TextField(
        blank=True,
        default="",
        help_text="Encrypted test restricted key (rk_test_).",
    )
    stripe_webhook_secret_enc = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_paymentgatewayconfig"
        verbose_name = "Stripe"
        verbose_name_plural = "Stripe"

    def save(self, *args, **kwargs):
        self.singleton_key = 1
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return "Stripe"


class PayPal(models.Model):
    """Singleton PayPal credentials (admin-managed)."""

    PAYPAL_ENV_AUTO = "auto"
    PAYPAL_ENV_SANDBOX = "sandbox"
    PAYPAL_ENV_LIVE = "live"
    PAYPAL_ENVIRONMENT_CHOICES = (
        (PAYPAL_ENV_AUTO, "Auto — sandbox when DEBUG, live on production"),
        (PAYPAL_ENV_SANDBOX, "Force sandbox (localhost / staging)"),
        (PAYPAL_ENV_LIVE, "Force live (production)"),
    )

    singleton_key = models.PositiveSmallIntegerField(default=1, unique=True)
    is_enabled = models.BooleanField(
        default=False,
        help_text="When enabled, stored credentials override PAYPAL_* environment variables.",
    )
    paypal_environment = models.CharField(
        max_length=16,
        choices=PAYPAL_ENVIRONMENT_CHOICES,
        default=PAYPAL_ENV_AUTO,
        help_text="Which PayPal API to use. Auto follows DEBUG (local=sandbox, production=live).",
    )
    sandbox_mode = models.BooleanField(
        default=True,
        help_text="Legacy flag; prefer PayPal environment above. Used when environment is Auto.",
    )
    client_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Legacy sandbox client ID; prefer sandbox_client_id.",
    )
    sandbox_client_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="PayPal Sandbox Client ID from developer.paypal.com.",
    )
    live_client_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="PayPal Live Client ID for production checkout.",
    )
    plan_pro_monthly = models.CharField(
        max_length=128,
        blank=True,
        default="",
        help_text="PayPal Plan ID for Pro monthly subscription (P-...).",
    )
    client_secret_enc = models.TextField(
        blank=True,
        default="",
        help_text="Legacy encrypted secret; prefer sandbox_client_secret_enc.",
    )
    sandbox_client_secret_enc = models.TextField(
        blank=True,
        default="",
        help_text="Encrypted PayPal Sandbox client secret.",
    )
    live_client_secret_enc = models.TextField(
        blank=True,
        default="",
        help_text="Encrypted PayPal Live client secret.",
    )
    webhook_id = models.CharField(
        max_length=128,
        blank=True,
        default="",
        help_text="PayPal Webhook ID from the Developer Dashboard.",
    )
    notes = models.TextField(blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_paypalgatewayconfig"
        verbose_name = "PayPal"
        verbose_name_plural = "PayPal"

    def save(self, *args, **kwargs):
        self.singleton_key = 1
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return "PayPal"


class AuditLog(models.Model):
    """Security-relevant events (no PII in message)."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_logs")
    action = models.CharField(max_length=64, db_index=True)
    detail = models.CharField(max_length=512, blank=True, default="")
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = "core_auditlog"
        ordering = ["-created_at"]


class ProcessedMeta(models.Model):
    tenant_id = models.CharField(max_length=64, db_index=True, default="")
    message_id = models.CharField(max_length=255, default="")
    meta_json = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "core_processedmeta"
        constraints = [
            models.UniqueConstraint(fields=["tenant_id", "message_id"], name="uq_processedmeta_tenant_message")
        ]


class QueueItem(models.Model):
    tenant_id = models.CharField(max_length=64, db_index=True, default="")
    message_id = models.CharField(max_length=255, default="")
    status = models.CharField(max_length=32, db_index=True, default="")
    details_json = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        db_table = "core_queueitem"
        constraints = [
            models.UniqueConstraint(fields=["tenant_id", "message_id"], name="uq_queueitem_tenant_message")
        ]
        indexes = [models.Index(fields=["tenant_id", "-updated_at"], name="idx_queueitem_tenant_updated")]
