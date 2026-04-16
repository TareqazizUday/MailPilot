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

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="mail_settings")
    settings_json = models.JSONField(default=dict, blank=True)
    smtp_password_enc = models.TextField(blank=True, default="")
    imap_password_enc = models.TextField(blank=True, default="")
    llm_api_key_enc = models.TextField(blank=True, default="")
    google_oauth_token_enc = models.TextField(blank=True, default="")
    client_secret_json_enc = models.TextField(blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_usermailsettings"


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
