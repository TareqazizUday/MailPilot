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
