from __future__ import annotations

from django.contrib import admin

from core.models import (
    AuditLog,
    ContactSubmission,
    DailySendCounter,
    MailAccount,
    PasswordResetOTP,
    UsageCounter,
    UsageEvent,
    UserMailSettings,
    UserProfile,
    UserSubscription,
)


admin.site.site_header = "MailPilot Admin"
admin.site.site_title = "MailPilot Admin"
admin.site.index_title = "Operations & Security"


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "display_name", "company", "updated_at")
    raw_id_fields = ("user",)
    search_fields = ("user__username", "user__email", "display_name")


@admin.register(UserMailSettings)
class UserMailSettingsAdmin(admin.ModelAdmin):
    list_display = ("user", "active_transport_mode", "default_account_id", "updated_at")
    raw_id_fields = ("user",)


@admin.register(MailAccount)
class MailAccountAdmin(admin.ModelAdmin):
    list_display = ("user", "slot", "transport", "label", "is_enabled", "updated_at")
    list_filter = ("transport", "is_enabled")
    raw_id_fields = ("user",)
    search_fields = ("label", "user__username", "user__email")


@admin.register(UserSubscription)
class UserSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "plan_code", "status", "monthly_token_limit", "active_inbox_limit", "updated_at")
    list_filter = ("plan_code", "status", "telegram_enabled", "whatsapp_enabled")
    raw_id_fields = ("user",)
    search_fields = ("user__username", "user__email", "stripe_customer_id", "stripe_subscription_id")


@admin.register(UsageCounter)
class UsageCounterAdmin(admin.ModelAdmin):
    list_display = ("user", "period_key", "tokens_used", "auto_sent_count", "updated_at")
    list_filter = ("period_key",)
    raw_id_fields = ("user",)
    search_fields = ("user__username", "user__email")


@admin.register(DailySendCounter)
class DailySendCounterAdmin(admin.ModelAdmin):
    list_display = ("user", "mail_account", "date", "provider_profile", "sends_used", "updated_at")
    list_filter = ("provider_profile", "date")
    raw_id_fields = ("user", "mail_account")
    search_fields = ("user__username", "user__email", "mail_account__label")


@admin.register(UsageEvent)
class UsageEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "mail_account", "event_type", "status", "units", "period_key", "date")
    list_filter = ("event_type", "status", "period_key", "date")
    raw_id_fields = ("user", "mail_account")
    search_fields = ("user__username", "user__email", "message_id")
    readonly_fields = ("created_at", "committed_at")


@admin.register(ContactSubmission)
class ContactSubmissionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "name", "email", "phone", "notified_team", "notified_user")
    list_filter = ("notified_team", "notified_user", "created_at")
    search_fields = ("name", "email", "phone", "message")
    readonly_fields = (
        "created_at",
        "name",
        "email",
        "phone",
        "message",
        "ip_address",
        "notified_team",
        "notified_user",
    )
    ordering = ("-created_at",)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "user", "ip_address")
    list_filter = ("action",)
    readonly_fields = ("created_at", "user", "action", "detail", "ip_address")


@admin.register(PasswordResetOTP)
class PasswordResetOTPAdmin(admin.ModelAdmin):
    list_display = ("email", "created_at", "expires_at", "attempts")
    search_fields = ("email",)
    list_filter = ("created_at",)
    readonly_fields = ("email", "otp_hash", "created_at", "expires_at", "attempts")
