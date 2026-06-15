from __future__ import annotations

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
