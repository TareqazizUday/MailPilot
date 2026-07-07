from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from django.contrib import admin
from django import forms
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import Group, User
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html
from unfold.admin import ModelAdmin, StackedInline

from core.admin_site import admin_site
from core.billing import (
    apply_plan_defaults,
    current_period_key,
    plan_defaults,
    set_subscription_plan,
    tokens_per_auto_send_for_plan,
)
from core.models import (
    AuditLog,
    BillingPaymentEvent,
    ContactSubmission,
    CustomPlanQuote,
    DailySendCounter,
    MailAccount,
    HowItWorksStep,
    LegalTermsSettings,
    LegalPrivacySettings,
    MarketingFeature,
    MarketingFaqItem,
    MarketingFaqSettings,
    MarketingHeroInboxItem,
    MarketingHeroSettings,
    MarketingReview,
    MarketingPricingPlan,
    MarketingPricingSettings,
    PasswordResetOTP,
    SupportAttachment,
    SupportMessage,
    SupportTicket,
    UsageCounter,
    UsageEvent,
    UserMailSettings,
    UserProfile,
    UserSubscription,
)
from core.widgets import CKEditorWidget


admin_site.site_header = "MailPilot Admin"
admin_site.site_title = "MailPilot Admin"
admin_site.index_title = "Operations dashboard"


class _MPModelAdmin(ModelAdmin):
    list_fullwidth = True
    compressed_fields = True
    warn_unsaved_form = True


def _badge(label: str, tone: str) -> str:
    return format_html('<span class="mp-badge mp-badge-{}">{}</span>', tone, label)


@admin.action(description="Apply plan defaults (sync limits from plan code)")
def apply_plan_defaults_action(modeladmin, request, queryset):
    for sub in queryset:
        apply_plan_defaults(sub)
    modeladmin.message_user(request, f"Updated {queryset.count()} subscription(s).")


@admin.action(description="Set plan → Starter")
def set_plan_starter(modeladmin, request, queryset):
    for sub in queryset:
        set_subscription_plan(sub, UserSubscription.PLAN_STARTER)
    modeladmin.message_user(request, f"Set {queryset.count()} subscription(s) to Starter.")


@admin.action(description="Set plan → Pro")
def set_plan_pro(modeladmin, request, queryset):
    for sub in queryset:
        set_subscription_plan(sub, UserSubscription.PLAN_PRO)
    modeladmin.message_user(request, f"Set {queryset.count()} subscription(s) to Pro.")


@admin.action(description="Reset monthly tokens (current billing period)")
def reset_monthly_tokens(modeladmin, request, queryset):
    period = current_period_key()
    user_ids = list(queryset.values_list("user_id", flat=True))
    updated = UsageCounter.objects.filter(user_id__in=user_ids, period_key=period).update(
        tokens_used=0,
        auto_sent_count=0,
    )
    modeladmin.message_user(request, f"Reset token counters for {updated} row(s) in {period}.")


class UserProfileInline(StackedInline):
    model = UserProfile
    extra = 0
    can_delete = False
    fields = ("display_name", "company", "phone", "timezone", "notes")


class UserSubscriptionInline(StackedInline):
    model = UserSubscription
    extra = 0
    can_delete = False
    fields = (
        "plan_code",
        "status",
        "monthly_token_limit",
        "active_inbox_limit",
        "daily_send_limit",
        "telegram_enabled",
        "whatsapp_enabled",
    )


class MailPilotUserAdmin(ModelAdmin, DjangoUserAdmin):
    list_display = ("username", "email", "full_name", "plan_badge", "is_staff", "is_active", "date_joined")
    list_filter = ("is_staff", "is_active", "is_superuser", "date_joined")
    search_fields = ("username", "email", "first_name", "last_name")
    ordering = ("-date_joined",)
    inlines = [UserProfileInline, UserSubscriptionInline]

    @admin.display(description="Name")
    def full_name(self, obj):
        name = obj.get_full_name().strip()
        return name or "-"

    @admin.display(description="Plan")
    def plan_badge(self, obj):
        try:
            sub = obj.subscription
        except UserSubscription.DoesNotExist:
            return _badge("No plan", "muted")
        tones = {
            UserSubscription.PLAN_STARTER: "starter",
            UserSubscription.PLAN_PRO: "pro",
            UserSubscription.PLAN_CUSTOM: "custom",
        }
        return _badge(sub.get_plan_code_display(), tones.get(sub.plan_code, "muted"))


class MailPilotGroupAdmin(_MPModelAdmin):
    search_fields = ("name",)


class UserProfileAdmin(_MPModelAdmin):
    list_display = ("user", "display_name", "company", "phone", "updated_at")
    list_select_related = ("user",)
    raw_id_fields = ("user",)
    search_fields = ("user__username", "user__email", "display_name", "company")
    fieldsets = (
        (None, {"fields": ("user", "display_name", "avatar")}),
        ("Contact", {"fields": ("phone", "company", "timezone")}),
        ("Internal", {"fields": ("notes",), "classes": ("collapse",)}),
    )


class UserMailSettingsAdmin(_MPModelAdmin):
    list_display = ("user", "active_transport_mode", "default_account_id", "updated_at")
    list_filter = ("active_transport_mode",)
    list_select_related = ("user",)
    raw_id_fields = ("user",)
    search_fields = ("user__username", "user__email")
    readonly_fields = ("updated_at",)


class MailAccountAdmin(_MPModelAdmin):
    list_display = ("user", "slot", "transport_badge", "label", "enabled_badge", "updated_at")
    list_filter = ("transport", "is_enabled")
    list_select_related = ("user",)
    raw_id_fields = ("user",)
    search_fields = ("label", "user__username", "user__email")
    ordering = ("-updated_at",)
    fieldsets = (
        (None, {"fields": ("user", "slot", "transport", "label", "is_enabled")}),
        ("Configuration", {"fields": ("config_json",), "classes": ("collapse",)}),
    )

    @admin.display(description="Transport", ordering="transport")
    def transport_badge(self, obj):
        tone = "pro" if obj.transport == MailAccount.TRANSPORT_GMAIL else "starter"
        return _badge(obj.transport.replace("_", " "), tone)

    @admin.display(description="Status", ordering="is_enabled")
    def enabled_badge(self, obj):
        return _badge("Active" if obj.is_enabled else "Disabled", "ok" if obj.is_enabled else "muted")


class UserSubscriptionAdmin(_MPModelAdmin):
    list_display = (
        "user",
        "plan_badge",
        "status_badge",
        "payment_provider_badge",
        "monthly_token_limit",
        "active_inbox_limit",
        "daily_send_limit",
        "integrations",
        "updated_at",
    )
    list_filter = ("plan_code", "status", "payment_provider", "telegram_enabled", "whatsapp_enabled")
    list_select_related = ("user",)
    raw_id_fields = ("user",)
    search_fields = (
        "user__username",
        "user__email",
        "stripe_customer_id",
        "stripe_subscription_id",
        "paypal_subscription_id",
    )
    ordering = ("-updated_at",)
    actions = [apply_plan_defaults_action, set_plan_starter, set_plan_pro, reset_monthly_tokens]
    fieldsets = (
        ("User & plan", {"fields": ("user", "plan_code", "status")}),
        (
            "Limits",
            {
                "fields": (
                    "monthly_token_limit",
                    "active_inbox_limit",
                    "daily_send_limit",
                    "kb_source_limit",
                ),
                "description": "Leave blank on Custom plan for unlimited. Use “Apply plan defaults” to sync from plan code.",
            },
        ),
        ("Integrations", {"fields": ("telegram_enabled", "whatsapp_enabled")}),
        (
            "Billing period",
            {"fields": ("current_period_start", "current_period_end"), "classes": ("collapse",)},
        ),
        (
            "Payment providers",
            {
                "fields": (
                    "payment_provider",
                    "paid_at",
                    "stripe_customer_id",
                    "stripe_subscription_id",
                    "paypal_subscription_id",
                ),
            },
        ),
        (
            "Starter trial",
            {
                "fields": ("starter_lifetime_sends", "starter_expired_at"),
                "classes": ("collapse",),
                "description": "Starter allows 20 lifetime auto-sends (80 tokens). Set paid_at when Custom is sold manually.",
            },
        ),
    )

    @admin.display(description="Provider", ordering="payment_provider")
    def payment_provider_badge(self, obj):
        raw = (obj.payment_provider or "").strip().lower()
        if not raw:
            return _badge("—", "muted")
        tones = {"stripe": "pro", "paypal": "ok"}
        return _badge(raw.title(), tones.get(raw, "muted"))

    @admin.display(description="Plan", ordering="plan_code")
    def plan_badge(self, obj):
        tones = {
            UserSubscription.PLAN_STARTER: "starter",
            UserSubscription.PLAN_PRO: "pro",
            UserSubscription.PLAN_CUSTOM: "custom",
        }
        return _badge(obj.get_plan_code_display(), tones.get(obj.plan_code, "muted"))

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        tones = {
            UserSubscription.STATUS_ACTIVE: "ok",
            UserSubscription.STATUS_TRIALING: "pro",
            UserSubscription.STATUS_PAST_DUE: "warn",
            UserSubscription.STATUS_CANCELED: "danger",
        }
        return _badge(obj.get_status_display(), tones.get(obj.status, "muted"))

    @admin.display(description="Channels")
    def integrations(self, obj):
        from django.utils.safestring import mark_safe

        badges = []
        if obj.telegram_enabled:
            badges.append(str(_badge("Telegram", "pro")))
        if obj.whatsapp_enabled:
            badges.append(str(_badge("WhatsApp", "pro")))
        if not badges:
            return _badge("None", "muted")
        return mark_safe(" ".join(badges))


class UsageCounterAdmin(_MPModelAdmin):
    list_display = ("user", "period_key", "tokens_used", "usage_bar", "auto_sent_count", "updated_at")
    list_filter = ("period_key",)
    list_select_related = ("user",)
    raw_id_fields = ("user",)
    search_fields = ("user__username", "user__email")
    ordering = ("-period_key", "-tokens_used")
    actions = [reset_monthly_tokens]

    @admin.display(description="Usage")
    def usage_bar(self, obj):
        try:
            limit = obj.user.subscription.monthly_token_limit
        except UserSubscription.DoesNotExist:
            limit = None
        if not limit:
            return _badge(f"{obj.tokens_used} tokens", "custom")
        pct = min(100, round((obj.tokens_used / max(1, limit)) * 100))
        tone = "ok" if pct < 70 else ("warn" if pct < 95 else "danger")
        return format_html(
            '<span class="mp-usage"><span class="mp-usage-bar mp-usage-{}"><i style="width:{}%"></i></span>'
            '<span class="mp-usage-label">{}%</span></span>',
            tone,
            pct,
            pct,
        )


class DailySendCounterAdmin(_MPModelAdmin):
    list_display = ("user", "mail_account", "date", "provider_profile", "sends_used", "updated_at")
    list_filter = ("provider_profile", "date")
    date_hierarchy = "date"
    list_select_related = ("user", "mail_account")
    raw_id_fields = ("user", "mail_account")
    search_fields = ("user__username", "user__email", "mail_account__label")
    ordering = ("-date", "-sends_used")


class UsageEventAdmin(_MPModelAdmin):
    list_display = (
        "created_at",
        "user",
        "mail_account",
        "event_type",
        "status_badge",
        "units",
        "period_key",
        "date",
    )
    list_filter = ("event_type", "status", "period_key", "date")
    date_hierarchy = "created_at"
    list_select_related = ("user", "mail_account")
    raw_id_fields = ("user", "mail_account")
    search_fields = ("user__username", "user__email", "message_id")
    readonly_fields = ("created_at", "committed_at")
    ordering = ("-created_at",)
    fieldsets = (
        (None, {"fields": ("user", "mail_account", "message_id", "event_type", "status", "units")}),
        ("Period", {"fields": ("period_key", "date", "created_at", "committed_at")}),
        ("Meta", {"fields": ("meta_json",), "classes": ("collapse",)}),
    )

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        tones = {
            UsageEvent.STATUS_COMMITTED: "ok",
            UsageEvent.STATUS_RESERVED: "warn",
            UsageEvent.STATUS_FAILED: "danger",
            UsageEvent.STATUS_REFUNDED: "muted",
        }
        return _badge(obj.get_status_display(), tones.get(obj.status, "muted"))


class BillingPaymentEventAdmin(_MPModelAdmin):
    list_display = (
        "created_at",
        "user",
        "provider_badge",
        "event_badge",
        "plan_code",
        "amount_display",
        "status_badge",
        "ip_address",
        "external_id_short",
    )
    list_filter = ("provider", "event_type", "status", "plan_code", "created_at")
    list_select_related = ("user",)
    search_fields = (
        "user__username",
        "user__email",
        "external_id",
        "ip_address",
        "detail",
        "user_agent",
    )
    readonly_fields = (
        "user",
        "event_type",
        "provider",
        "plan_code",
        "amount_cents",
        "currency",
        "status",
        "external_id",
        "ip_address",
        "user_agent",
        "detail",
        "created_at",
    )
    ordering = ("-created_at",)
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    @admin.display(description="Provider", ordering="provider")
    def provider_badge(self, obj):
        raw = (obj.provider or "").strip().lower()
        if not raw:
            return _badge("—", "muted")
        tones = {"stripe": "pro", "paypal": "ok"}
        return _badge(raw.title(), tones.get(raw, "muted"))

    @admin.display(description="Event", ordering="event_type")
    def event_badge(self, obj):
        return _badge(obj.get_event_type_display(), "pro")

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        tones = {
            BillingPaymentEvent.STATUS_SUCCEEDED: "ok",
            BillingPaymentEvent.STATUS_PENDING: "warn",
            BillingPaymentEvent.STATUS_FAILED: "danger",
            BillingPaymentEvent.STATUS_CANCELED: "muted",
        }
        return _badge(obj.get_status_display(), tones.get(obj.status, "muted"))

    @admin.display(description="Amount")
    def amount_display(self, obj):
        if obj.amount_cents is None:
            return "—"
        cur = (obj.currency or "usd").upper()
        return f"{cur} {obj.amount_cents / 100:.2f}"

    @admin.display(description="Reference")
    def external_id_short(self, obj):
        text = (obj.external_id or "").strip()
        if len(text) > 24:
            return f"{text[:21]}…"
        return text or "—"


class CustomPlanQuoteAdmin(_MPModelAdmin):
    list_display = ("user", "tokens", "inboxes", "price_display", "status_badge", "created_at", "expires_at")
    list_filter = ("status", "created_at")
    list_select_related = ("user",)
    raw_id_fields = ("user",)
    search_fields = ("user__username", "user__email", "stripe_session_id")
    readonly_fields = ("created_at", "updated_at", "paid_at")
    ordering = ("-created_at",)

    @admin.display(description="Price")
    def price_display(self, obj):
        from core.pricing_currency import format_cents, normalize_currency

        cur = normalize_currency(getattr(obj, "currency", None) or "usd")
        return f"{format_cents(obj.price_cents, cur)}/mo"

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        tones = {
            CustomPlanQuote.STATUS_PAID: "ok",
            CustomPlanQuote.STATUS_PENDING: "warn",
            CustomPlanQuote.STATUS_DRAFT: "muted",
            CustomPlanQuote.STATUS_EXPIRED: "danger",
            CustomPlanQuote.STATUS_CANCELED: "danger",
        }
        return _badge(obj.get_status_display(), tones.get(obj.status, "muted"))


@admin.action(description="Publish selected features")
def publish_marketing_features(modeladmin, request, queryset):
    queryset.update(is_published=True)
    modeladmin.message_user(request, f"Published {queryset.count()} feature(s).")


@admin.action(description="Unpublish selected features")
def unpublish_marketing_features(modeladmin, request, queryset):
    queryset.update(is_published=False)
    modeladmin.message_user(request, f"Unpublished {queryset.count()} feature(s).")


@admin.action(description="Publish selected steps")
def publish_how_it_works_steps(modeladmin, request, queryset):
    queryset.update(is_published=True)
    modeladmin.message_user(request, f"Published {queryset.count()} step(s).")


@admin.action(description="Unpublish selected steps")
def unpublish_how_it_works_steps(modeladmin, request, queryset):
    queryset.update(is_published=False)
    modeladmin.message_user(request, f"Unpublished {queryset.count()} step(s).")


@admin.action(description="Publish selected reviews")
def publish_marketing_reviews(modeladmin, request, queryset):
    queryset.update(is_published=True)
    modeladmin.message_user(request, f"Published {queryset.count()} review(s).")


@admin.action(description="Unpublish selected reviews")
def unpublish_marketing_reviews(modeladmin, request, queryset):
    queryset.update(is_published=False)
    modeladmin.message_user(request, f"Unpublished {queryset.count()} review(s).")


class MarketingFeatureAdmin(_MPModelAdmin):
    list_display = (
        "sort_order",
        "title",
        "icon_preview",
        "accent_preview",
        "published_badge",
        "homepage_badge",
        "updated_at",
    )
    list_display_links = ("title",)
    list_editable = ("sort_order",)
    list_filter = ("is_published", "show_on_homepage")
    search_fields = ("title", "description", "icon_class")
    ordering = ("sort_order", "id")
    actions = [publish_marketing_features, unpublish_marketing_features]
    fieldsets = (
        (None, {"fields": ("title", "description")}),
        ("Display", {"fields": ("icon_class", "accent_color", "sort_order")}),
        ("Visibility", {"fields": ("is_published", "show_on_homepage")}),
        ("Meta", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Icon")
    def icon_preview(self, obj):
        return format_html('<i class="{}" style="font-size:1.1rem"></i> {}', obj.icon_class, obj.icon_class)

    @admin.display(description="Accent")
    def accent_preview(self, obj):
        color = (obj.accent_color or "#4f6ef7").strip()
        return format_html(
            '<span style="display:inline-block;width:14px;height:14px;border-radius:4px;background:{};'
            'border:1px solid rgba(255,255,255,.2);vertical-align:middle"></span> {}',
            color,
            color,
        )

    @admin.display(description="Published", ordering="is_published")
    def published_badge(self, obj):
        return _badge("Yes" if obj.is_published else "No", "ok" if obj.is_published else "muted")

    @admin.display(description="Homepage", ordering="show_on_homepage")
    def homepage_badge(self, obj):
        return _badge("Yes" if obj.show_on_homepage else "No", "pro" if obj.show_on_homepage else "muted")


class HowItWorksStepAdmin(_MPModelAdmin):
    list_display = (
        "sort_order",
        "title",
        "accent_badge",
        "icon_preview",
        "published_badge",
        "homepage_badge",
        "updated_at",
    )
    list_display_links = ("title",)
    list_editable = ("sort_order",)
    list_filter = ("is_published", "show_on_homepage", "accent")
    search_fields = ("title", "description")
    ordering = ("sort_order", "id")
    actions = [publish_how_it_works_steps, unpublish_how_it_works_steps]
    fieldsets = (
        (None, {"fields": ("title", "description")}),
        ("Display", {"fields": ("accent", "icon_svg", "sort_order")}),
        ("Visibility", {"fields": ("is_published", "show_on_homepage")}),
        ("Meta", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Accent", ordering="accent")
    def accent_badge(self, obj):
        tones = {
            HowItWorksStep.ACCENT_BLUE: "pro",
            HowItWorksStep.ACCENT_SKY: "starter",
            HowItWorksStep.ACCENT_PURPLE: "custom",
            HowItWorksStep.ACCENT_PINK: "warn",
            HowItWorksStep.ACCENT_GREEN: "ok",
            HowItWorksStep.ACCENT_ORANGE: "danger",
        }
        return _badge(obj.get_accent_display(), tones.get(obj.accent, "muted"))

    @admin.display(description="Icon")
    def icon_preview(self, obj):
        from django.utils.safestring import mark_safe

        if not (obj.icon_svg or "").strip():
            return "-"
        return format_html(
            '<span style="display:inline-block;width:22px;height:22px;color:#a5b4fc">{}</span>',
            mark_safe(obj.icon_svg),
        )

    @admin.display(description="Published", ordering="is_published")
    def published_badge(self, obj):
        return _badge("Yes" if obj.is_published else "No", "ok" if obj.is_published else "muted")

    @admin.display(description="Homepage", ordering="show_on_homepage")
    def homepage_badge(self, obj):
        return _badge("Yes" if obj.show_on_homepage else "No", "pro" if obj.show_on_homepage else "muted")


class MarketingReviewAdmin(_MPModelAdmin):
    list_display = (
        "sort_order",
        "author_name",
        "author_role",
        "rating_badge",
        "accent_preview",
        "published_badge",
        "homepage_badge",
        "updated_at",
    )
    list_display_links = ("author_name",)
    list_editable = ("sort_order",)
    list_filter = ("is_published", "show_on_homepage", "rating")
    search_fields = ("author_name", "author_role", "quote", "metric")
    ordering = ("sort_order", "id")
    actions = [publish_marketing_reviews, unpublish_marketing_reviews]
    fieldsets = (
        (None, {"fields": ("quote", "metric")}),
        ("Author", {"fields": ("author_name", "author_role", "avatar_initials")}),
        ("Display", {"fields": ("rating", "accent_primary", "accent_secondary", "sort_order")}),
        ("Visibility", {"fields": ("is_published", "show_on_homepage")}),
        ("Meta", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Rating", ordering="rating")
    def rating_badge(self, obj):
        return _badge(f"{obj.rating}★", "warn" if obj.rating >= 5 else "pro")

    @admin.display(description="Accent")
    def accent_preview(self, obj):
        a1 = (obj.accent_primary or "#4f6ef7").strip()
        a2 = (obj.accent_secondary or "#a78bfa").strip()
        return format_html(
            '<span style="display:inline-block;width:14px;height:14px;border-radius:4px;background:linear-gradient(135deg,{},{});'
            'border:1px solid rgba(255,255,255,.2);vertical-align:middle"></span> {} / {}',
            a1,
            a2,
            a1,
            a2,
        )

    @admin.display(description="Published", ordering="is_published")
    def published_badge(self, obj):
        return _badge("Yes" if obj.is_published else "No", "ok" if obj.is_published else "muted")

    @admin.display(description="Homepage", ordering="show_on_homepage")
    def homepage_badge(self, obj):
        return _badge("Yes" if obj.show_on_homepage else "No", "pro" if obj.show_on_homepage else "muted")


@admin.action(description="Publish selected hero inbox rows")
def publish_hero_inbox_items(modeladmin, request, queryset):
    queryset.update(is_published=True)
    modeladmin.message_user(request, f"Published {queryset.count()} row(s).")


@admin.action(description="Unpublish selected hero inbox rows")
def unpublish_hero_inbox_items(modeladmin, request, queryset):
    queryset.update(is_published=False)
    modeladmin.message_user(request, f"Unpublished {queryset.count()} row(s).")


class MarketingHeroSettingsAdmin(_MPModelAdmin):
    list_display = ("card_title", "updated_at")
    fieldsets = (
        (None, {"fields": ("card_title", "card_icon_class")}),
        ("Meta", {"fields": ("updated_at",), "classes": ("collapse",)}),
    )
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        return not MarketingHeroSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj, _ = MarketingHeroSettings.objects.get_or_create(singleton_key=1)
        return redirect(reverse("admin:core_marketingherosettings_change", args=(obj.pk,)))


class MarketingHeroInboxItemAdmin(_MPModelAdmin):
    list_display = (
        "sort_order",
        "sender_name",
        "sender_context",
        "badge_badge",
        "avatar_preview",
        "published_badge",
        "homepage_badge",
        "updated_at",
    )
    list_display_links = ("sender_name",)
    list_editable = ("sort_order",)
    list_filter = ("is_published", "show_on_homepage", "badge_type")
    search_fields = ("sender_name", "sender_context", "subject", "badge_label")
    ordering = ("sort_order", "id")
    actions = [publish_hero_inbox_items, unpublish_hero_inbox_items]
    fieldsets = (
        (None, {"fields": ("sender_name", "sender_context", "subject")}),
        ("Avatar", {"fields": ("avatar_initials", "avatar_color_start", "avatar_color_end")}),
        ("Badge", {"fields": ("badge_type", "badge_label", "badge_icon_class")}),
        ("Visibility", {"fields": ("sort_order", "is_published", "show_on_homepage")}),
        ("Meta", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Badge", ordering="badge_type")
    def badge_badge(self, obj):
        tones = {
            MarketingHeroInboxItem.BADGE_REPLIED: "ok",
            MarketingHeroInboxItem.BADGE_RAG: "pro",
            MarketingHeroInboxItem.BADGE_PENDING: "warn",
            MarketingHeroInboxItem.BADGE_SKIPPED: "muted",
        }
        return _badge(obj.get_badge_type_display(), tones.get(obj.badge_type, "muted"))

    @admin.display(description="Avatar")
    def avatar_preview(self, obj):
        return format_html(
            '<span style="display:inline-flex;align-items:center;justify-content:center;'
            'width:22px;height:22px;border-radius:50%;font-size:0.6rem;font-weight:700;{}">{}</span>',
            obj.avatar_gradient_style,
            obj.avatar_initials,
        )

    @admin.display(description="Published", ordering="is_published")
    def published_badge(self, obj):
        return _badge("Yes" if obj.is_published else "No", "ok" if obj.is_published else "muted")

    @admin.display(description="Homepage", ordering="show_on_homepage")
    def homepage_badge(self, obj):
        return _badge("Yes" if obj.show_on_homepage else "No", "pro" if obj.show_on_homepage else "muted")


class LegalTermsSettingsForm(forms.ModelForm):
    class Meta:
        model = LegalTermsSettings
        fields = ("title", "effective_date", "is_published", "body_html")
        widgets = {
            "body_html": CKEditorWidget(attrs={"rows": 24}),
        }


class LegalTermsSettingsAdmin(_MPModelAdmin):
    form = LegalTermsSettingsForm
    list_display = ("title", "effective_date", "published_badge", "updated_at")
    fieldsets = (
        (None, {"fields": ("title", "effective_date", "is_published")}),
        ("Content", {"fields": ("body_html",)}),
        ("Meta", {"fields": ("updated_at",), "classes": ("collapse",)}),
    )
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        return not LegalTermsSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        from core.legal_content import get_terms_settings

        obj = get_terms_settings()
        return redirect(reverse("admin:core_legaltermssettings_change", args=(obj.pk,)))

    @admin.display(description="Published", ordering="is_published")
    def published_badge(self, obj):
        return _badge("Yes" if obj.is_published else "No", "ok" if obj.is_published else "muted")

    class Media:
        js = (
            "https://cdn.ckeditor.com/ckeditor5/41.4.2/classic/ckeditor.js",
            "js/mailpilot-ckeditor-admin.js",
        )


class LegalPrivacySettingsForm(forms.ModelForm):
    class Meta:
        model = LegalPrivacySettings
        fields = ("title", "effective_date", "is_published", "body_html")
        widgets = {
            "body_html": CKEditorWidget(attrs={"rows": 24}),
        }


class LegalPrivacySettingsAdmin(_MPModelAdmin):
    form = LegalPrivacySettingsForm
    list_display = ("title", "effective_date", "published_badge", "updated_at")
    fieldsets = (
        (None, {"fields": ("title", "effective_date", "is_published")}),
        ("Content", {"fields": ("body_html",)}),
        ("Meta", {"fields": ("updated_at",), "classes": ("collapse",)}),
    )
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        return not LegalPrivacySettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        from core.legal_content import get_privacy_settings

        obj = get_privacy_settings()
        return redirect(reverse("admin:core_legalprivacysettings_change", args=(obj.pk,)))

    @admin.display(description="Published", ordering="is_published")
    def published_badge(self, obj):
        return _badge("Yes" if obj.is_published else "No", "ok" if obj.is_published else "muted")

    class Media:
        js = (
            "https://cdn.ckeditor.com/ckeditor5/41.4.2/classic/ckeditor.js",
            "js/mailpilot-ckeditor-admin.js",
        )


@admin.action(description="Publish selected FAQ items")
def publish_faq_items(modeladmin, request, queryset):
    queryset.update(is_published=True)
    modeladmin.message_user(request, f"Published {queryset.count()} FAQ item(s).")


@admin.action(description="Unpublish selected FAQ items")
def unpublish_faq_items(modeladmin, request, queryset):
    queryset.update(is_published=False)
    modeladmin.message_user(request, f"Unpublished {queryset.count()} FAQ item(s).")


class MarketingFaqSettingsAdmin(_MPModelAdmin):
    list_display = ("section_tag", "title_lead", "updated_at")
    fieldsets = (
        (None, {"fields": ("section_tag", "title_lead", "title_highlight")}),
        ("Intro", {"fields": ("intro_html",)}),
        ("Meta", {"fields": ("updated_at",), "classes": ("collapse",)}),
    )
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        return not MarketingFaqSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj, _ = MarketingFaqSettings.objects.get_or_create(singleton_key=1)
        return redirect(reverse("admin:core_marketingfaqsettings_change", args=(obj.pk,)))


class MarketingFaqItemAdmin(_MPModelAdmin):
    list_display = (
        "sort_order",
        "question",
        "icon_preview",
        "published_badge",
        "homepage_badge",
        "updated_at",
    )
    list_display_links = ("question",)
    list_editable = ("sort_order",)
    list_filter = ("is_published", "show_on_homepage")
    search_fields = ("question", "answer_html")
    ordering = ("sort_order", "id")
    actions = [publish_faq_items, unpublish_faq_items]
    fieldsets = (
        (None, {"fields": ("question", "answer_html")}),
        ("Display", {"fields": ("icon_class", "sort_order")}),
        ("Visibility", {"fields": ("is_published", "show_on_homepage")}),
        ("Meta", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Icon")
    def icon_preview(self, obj):
        return format_html('<i class="{}" style="font-size:1.1rem"></i> {}', obj.icon_class, obj.icon_class)

    @admin.display(description="Published", ordering="is_published")
    def published_badge(self, obj):
        return _badge("Yes" if obj.is_published else "No", "ok" if obj.is_published else "muted")

    @admin.display(description="Homepage", ordering="show_on_homepage")
    def homepage_badge(self, obj):
        return _badge("Yes" if obj.show_on_homepage else "No", "pro" if obj.show_on_homepage else "muted")


@admin.action(description="Publish selected plans")
def publish_pricing_plans(modeladmin, request, queryset):
    queryset.update(is_published=True)
    modeladmin.message_user(request, f"Published {queryset.count()} plan(s).")


@admin.action(description="Unpublish selected plans")
def unpublish_pricing_plans(modeladmin, request, queryset):
    queryset.update(is_published=False)
    modeladmin.message_user(request, f"Unpublished {queryset.count()} plan(s).")


class MarketingPricingSettingsAdmin(_MPModelAdmin):
    list_display = ("section_tag", "title_lead", "updated_at")
    fieldsets = (
        (None, {"fields": ("section_tag", "title_lead", "title_highlight")}),
        ("Body copy", {"fields": ("intro", "demo_note")}),
        (
            "Profit assumptions (admin only)",
            {"fields": ("profit_api_cost_per_send_usd", "profit_token_cost_per_1k_usd")},
        ),
        ("Meta", {"fields": ("updated_at",), "classes": ("collapse",)}),
    )
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        return not MarketingPricingSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj, _ = MarketingPricingSettings.objects.get_or_create(singleton_key=1)
        return redirect(reverse("admin:core_marketingpricingsettings_change", args=(obj.pk,)))


class MarketingPricingPlanAdmin(_MPModelAdmin):
    list_display = (
        "sort_order",
        "tier_label",
        "plan_badge",
        "price_display",
        "economics_summary",
        "estimated_profit",
        "estimated_margin",
        "featured_badge",
        "published_badge",
        "homepage_badge",
        "updated_at",
    )
    list_display_links = ("tier_label",)
    list_editable = ("sort_order",)
    list_filter = ("is_published", "show_on_homepage", "plan_code", "is_featured")
    search_fields = ("tier_label", "description", "features", "top_badge")
    ordering = ("sort_order", "id")
    actions = [publish_pricing_plans, unpublish_pricing_plans]
    fieldsets = (
        (None, {"fields": ("plan_code", "tier_label", "is_featured")}),
        ("Pricing (monthly)", {"fields": ("price_display", "price_suffix", "price_was", "price_save_label", "period_text")}),
        (
            "Pricing (yearly toggle)",
            {
                "fields": (
                    "yearly_price_display",
                    "yearly_price_suffix",
                    "yearly_price_was",
                    "yearly_price_save_label",
                    "yearly_period_text",
                ),
            },
        ),
        ("Details", {"fields": ("description",)}),
        ("Badges", {"fields": ("top_badge", "ribbon_type", "ribbon_label", "ribbon_icon_class")}),
        ("Features", {"fields": ("features",)}),
        (
            "Call to action",
            {"fields": ("cta_label", "cta_label_authenticated", "cta_label_starter_expired", "cta_style")},
        ),
        ("Visibility", {"fields": ("sort_order", "is_published", "show_on_homepage")}),
        ("Meta", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Plan", ordering="plan_code")
    def plan_badge(self, obj):
        tones = {
            MarketingPricingPlan.PLAN_STARTER: "starter",
            MarketingPricingPlan.PLAN_PRO: "pro",
            MarketingPricingPlan.PLAN_CUSTOM: "custom",
        }
        return _badge(obj.get_plan_code_display(), tones.get(obj.plan_code, "muted"))

    @admin.display(description="Featured", ordering="is_featured")
    def featured_badge(self, obj):
        return _badge("Yes" if obj.is_featured else "No", "pro" if obj.is_featured else "muted")

    @admin.display(description="Published", ordering="is_published")
    def published_badge(self, obj):
        return _badge("Yes" if obj.is_published else "No", "ok" if obj.is_published else "muted")

    @admin.display(description="Homepage", ordering="show_on_homepage")
    def homepage_badge(self, obj):
        return _badge("Yes" if obj.show_on_homepage else "No", "pro" if obj.show_on_homepage else "muted")

    @staticmethod
    def _parse_usd_price(raw: str) -> Decimal | None:
        text = (raw or "").strip()
        if not text:
            return None
        m = re.search(r"(\d+(?:\.\d+)?)", text.replace(",", ""))
        if not m:
            return None
        try:
            return Decimal(m.group(1))
        except (InvalidOperation, TypeError):
            return None

    @staticmethod
    def _plan_tokens(plan_code: str) -> int | None:
        defaults = plan_defaults(plan_code)
        limit = defaults.get("monthly_token_limit")
        if limit is None:
            return None
        try:
            return int(limit)
        except (TypeError, ValueError):
            return None

    def _profit_inputs(self, obj: MarketingPricingPlan) -> dict[str, Decimal | int | None]:
        cfg, _ = MarketingPricingSettings.objects.get_or_create(singleton_key=1)
        price = self._parse_usd_price(obj.price_display)
        tokens = self._plan_tokens(obj.plan_code)
        if price is None or tokens is None:
            return {"tokens": tokens, "sends": None, "profit": None, "margin": None}

        per_send = tokens_per_auto_send_for_plan(obj.plan_code)
        sends = int(tokens // max(1, per_send))
        api_cost = Decimal(str(cfg.profit_api_cost_per_send_usd or 0))
        token_cost_per_1k = Decimal(str(cfg.profit_token_cost_per_1k_usd or 0))
        total_cost = (Decimal(sends) * api_cost) + (Decimal(tokens) / Decimal(1000) * token_cost_per_1k)
        profit = price - total_cost
        margin = (profit / price * Decimal(100)) if price > 0 else None
        return {
            "tokens": tokens,
            "sends": sends,
            "profit": profit,
            "margin": margin,
        }

    @admin.display(description="Economics")
    def economics_summary(self, obj):
        data = self._profit_inputs(obj)
        sends = data.get("sends")
        tokens = data.get("tokens")
        if sends is None or tokens is None:
            return _badge("Custom builder", "muted")
        return format_html("{} tok · {} sends", f"{tokens:,}", f"{sends:,}")

    @admin.display(description="Est. Profit")
    def estimated_profit(self, obj):
        profit = self._profit_inputs(obj).get("profit")
        if profit is None:
            return _badge("n/a", "muted")
        p = Decimal(profit).quantize(Decimal("0.01"))
        tone = "ok" if p > 0 else ("warn" if p == 0 else "danger")
        return _badge(f"${p}", tone)

    @admin.display(description="Margin")
    def estimated_margin(self, obj):
        margin = self._profit_inputs(obj).get("margin")
        if margin is None:
            return _badge("n/a", "muted")
        m = Decimal(margin).quantize(Decimal("0.1"))
        tone = "ok" if m >= 50 else ("warn" if m >= 20 else "danger")
        return _badge(f"{m}%", tone)


class ContactSubmissionAdmin(_MPModelAdmin):
    list_display = ("created_at", "name", "email", "phone", "notified_badge", "message_preview")
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
    date_hierarchy = "created_at"

    @admin.display(description="Notified")
    def notified_badge(self, obj):
        if obj.notified_team and obj.notified_user:
            return _badge("Both", "ok")
        if obj.notified_team:
            return _badge("Team", "warn")
        if obj.notified_user:
            return _badge("User", "warn")
        return _badge("Pending", "danger")

    @admin.display(description="Message")
    def message_preview(self, obj):
        text = (obj.message or "").strip().replace("\n", " ")
        if len(text) > 80:
            return f"{text[:77]}…"
        return text or "-"


class AuditLogAdmin(_MPModelAdmin):
    list_display = ("created_at", "action_badge", "user", "ip_address", "detail_preview")
    list_filter = ("action", "created_at")
    readonly_fields = ("created_at", "user", "action", "detail", "ip_address")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    search_fields = ("action", "detail", "user__username", "ip_address")

    @admin.display(description="Action", ordering="action")
    def action_badge(self, obj):
        return _badge(obj.action, "pro")

    @admin.display(description="Detail")
    def detail_preview(self, obj):
        text = (obj.detail or "").strip()
        if len(text) > 60:
            return f"{text[:57]}…"
        return text or "-"


class PasswordResetOTPAdmin(_MPModelAdmin):
    list_display = ("email", "created_at", "expires_at", "attempts", "expired_badge")
    search_fields = ("email",)
    list_filter = ("created_at",)
    readonly_fields = ("email", "otp_hash", "created_at", "expires_at", "attempts")
    ordering = ("-created_at",)

    @admin.display(description="State")
    def expired_badge(self, obj):
        from django.utils import timezone

        if obj.expires_at and obj.expires_at < timezone.now():
            return _badge("Expired", "muted")
        return _badge("Valid", "ok")


class SupportAttachmentInline(admin.TabularInline):
    model = SupportAttachment
    extra = 0
    fields = ("original_name", "content_type", "size_bytes", "file", "created_at")
    readonly_fields = ("original_name", "content_type", "size_bytes", "created_at")
    can_delete = False


class SupportMessageInline(admin.StackedInline):
    model = SupportMessage
    extra = 1
    fields = ("body", "is_staff_reply", "sender", "created_at")
    readonly_fields = ("sender", "created_at")
    show_change_link = True

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if not request.user.is_superuser:
            ro.append("is_staff_reply")
        return ro


class SupportTicketAdmin(_MPModelAdmin):
    list_display = (
        "id",
        "subject",
        "user",
        "category",
        "status",
        "unread_by_staff",
        "open_chat",
        "last_message_at",
        "created_at",
    )
    list_filter = ("status", "category", "unread_by_staff", "created_at")
    search_fields = ("subject", "user__username", "user__email")
    readonly_fields = ("created_at", "updated_at", "last_message_at")
    inlines = [SupportMessageInline]
    ordering = ("-last_message_at", "-id")

    @admin.display(description="Chat")
    def open_chat(self, obj: SupportTicket):
        url = reverse("admin:support_inbox_detail", args=[obj.pk])
        if obj.status == SupportTicket.STATUS_CLOSED:
            return format_html(
                '<span class="text-base-400 dark:text-base-500">Chat closed</span>'
                ' · <a href="{}" class="text-base-500 hover:text-base-700 dark:hover:text-base-300">View</a>',
                url,
            )
        return format_html('<a href="{}" class="text-primary-600">Open chat</a>', url)

    def save_formset(self, request, form, formset, change):
        if formset.model is not SupportMessage:
            super().save_formset(request, form, formset, change)
            return
        ticket = form.instance
        instances = formset.save(commit=False)
        for obj in instances:
            is_new = not obj.pk
            if is_new and ticket.status == SupportTicket.STATUS_CLOSED:
                continue
            if is_new:
                obj.sender = request.user
                obj.is_staff_reply = True
            obj.save()
            if not is_new:
                continue
            ticket = obj.ticket
            ticket.last_message_at = obj.created_at
            ticket.status = SupportTicket.STATUS_WAITING_USER
            ticket.unread_by_user = True
            ticket.unread_by_staff = False
            ticket.save(
                update_fields=[
                    "last_message_at",
                    "status",
                    "unread_by_user",
                    "unread_by_staff",
                    "updated_at",
                ]
            )
        for obj in formset.deleted_objects:
            obj.delete()
        formset.save_m2m()


admin_site.register(User, MailPilotUserAdmin)
admin_site.register(Group, MailPilotGroupAdmin)
admin_site.register(UserProfile, UserProfileAdmin)
admin_site.register(UserMailSettings, UserMailSettingsAdmin)
admin_site.register(MailAccount, MailAccountAdmin)
admin_site.register(UserSubscription, UserSubscriptionAdmin)
admin_site.register(BillingPaymentEvent, BillingPaymentEventAdmin)
admin_site.register(UsageCounter, UsageCounterAdmin)
admin_site.register(DailySendCounter, DailySendCounterAdmin)
admin_site.register(UsageEvent, UsageEventAdmin)
admin_site.register(CustomPlanQuote, CustomPlanQuoteAdmin)
admin_site.register(MarketingFeature, MarketingFeatureAdmin)
admin_site.register(HowItWorksStep, HowItWorksStepAdmin)
admin_site.register(MarketingReview, MarketingReviewAdmin)
admin_site.register(MarketingHeroSettings, MarketingHeroSettingsAdmin)
admin_site.register(MarketingHeroInboxItem, MarketingHeroInboxItemAdmin)
admin_site.register(MarketingFaqSettings, MarketingFaqSettingsAdmin)
admin_site.register(MarketingFaqItem, MarketingFaqItemAdmin)
admin_site.register(LegalTermsSettings, LegalTermsSettingsAdmin)
admin_site.register(LegalPrivacySettings, LegalPrivacySettingsAdmin)
admin_site.register(MarketingPricingSettings, MarketingPricingSettingsAdmin)
admin_site.register(MarketingPricingPlan, MarketingPricingPlanAdmin)
admin_site.register(ContactSubmission, ContactSubmissionAdmin)
admin_site.register(SupportTicket, SupportTicketAdmin)
admin_site.register(AuditLog, AuditLogAdmin)
admin_site.register(PasswordResetOTP, PasswordResetOTPAdmin)
