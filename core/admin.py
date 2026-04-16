from __future__ import annotations

from django.contrib import admin

from core.models import AuditLog, PasswordResetOTP, UserMailSettings, UserProfile


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
    list_display = ("user", "updated_at")
    raw_id_fields = ("user",)


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
