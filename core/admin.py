from __future__ import annotations

from django.contrib import admin
from django import forms
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import Group, User
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html
from unfold.admin import ModelAdmin, StackedInline

from core.admin_site import admin_site
from core.billing import apply_plan_defaults, current_period_key, set_subscription_plan
from core.crypto import encrypt_str
from core.models import (
    AuditLog,
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
    Stripe,
    PayPal,
    UsageCounter,
    UsageEvent,
    UserMailSettings,
    UserProfile,
    UserSubscription,
)
from core.payment_gateway import masked_paypal_secret, masked_stripe_secret, masked_stripe_webhook
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
        return name or "—"

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
        "monthly_token_limit",
        "active_inbox_limit",
        "daily_send_limit",
        "integrations",
        "updated_at",
    )
    list_filter = ("plan_code", "status", "telegram_enabled", "whatsapp_enabled")
    list_select_related = ("user",)
    raw_id_fields = ("user",)
    search_fields = ("user__username", "user__email", "stripe_customer_id", "stripe_subscription_id")
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
            "Stripe",
            {"fields": ("stripe_customer_id", "stripe_subscription_id", "paid_at"), "classes": ("collapse",)},
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
        return f"${obj.price_cents / 100:.2f}/mo"

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
            return "—"
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
        return text or "—"


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
        return text or "—"


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


class StripeConfigForm(forms.ModelForm):
    stripe_secret_key = forms.CharField(
        required=False,
        label="Stripe secret key",
        help_text="Save demo values now; later replace with real sk_test_/sk_live_ from Stripe Dashboard.",
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
                "spellcheck": "false",
                "class": "vTextField",
                "style": "font-family: ui-monospace, monospace; width: 100%;",
            }
        ),
    )
    stripe_webhook_secret = forms.CharField(
        required=False,
        label="Stripe webhook secret",
        help_text="Demo whsec_ placeholder is OK for local test. Replace when Stripe webhook is configured.",
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
                "spellcheck": "false",
                "class": "vTextField",
                "style": "font-family: ui-monospace, monospace; width: 100%;",
            }
        ),
    )

    class Meta:
        model = Stripe
        fields = (
            "is_enabled",
            "provider",
            "stripe_publishable_key",
            "stripe_price_pro_monthly",
            "notes",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from core.crypto import decrypt_str
        from core.payment_gateway import (
            DEMO_STRIPE_REFERENCE,
            billing_demo_mode,
            is_demo_stripe_credentials,
        )

        ref = DEMO_STRIPE_REFERENCE
        mono = {
            "style": "font-family: ui-monospace, monospace; width: 100%;",
            "class": "vTextField",
            "spellcheck": "false",
        }

        for name in (
            "stripe_publishable_key",
            "stripe_price_pro_monthly",
            "stripe_secret_key",
            "stripe_webhook_secret",
        ):
            self.fields[name].widget.attrs.update(mono)

        inst = self.instance
        if not inst or not inst.pk:
            if billing_demo_mode():
                for key, field in (
                    ("publishable_key", "stripe_publishable_key"),
                    ("price_pro_monthly", "stripe_price_pro_monthly"),
                    ("secret_key", "stripe_secret_key"),
                    ("webhook_secret", "stripe_webhook_secret"),
                ):
                    self.initial[field] = ref[key]
            return

        pk = (inst.stripe_publishable_key or "").strip()
        price = (inst.stripe_price_pro_monthly or "").strip()
        secret = decrypt_str(inst.stripe_secret_key_enc).strip()
        webhook = decrypt_str(inst.stripe_webhook_secret_enc).strip()
        saved_demo = is_demo_stripe_credentials(
            secret_key=secret,
            price_pro_monthly=price,
            publishable_key=pk,
            webhook_secret=webhook,
        )

        def _set(field: str, value: str, *, demo_fallback: str) -> None:
            if value:
                self.initial[field] = value
            elif billing_demo_mode():
                self.initial[field] = demo_fallback

        _set("stripe_publishable_key", pk, demo_fallback=ref["publishable_key"])
        _set("stripe_price_pro_monthly", price, demo_fallback=ref["price_pro_monthly"])
        if secret and (saved_demo or billing_demo_mode()):
            self.initial["stripe_secret_key"] = secret
        elif billing_demo_mode():
            self.initial["stripe_secret_key"] = ref["secret_key"]
        elif secret:
            self.fields["stripe_secret_key"].widget.attrs["placeholder"] = "Saved — enter new value to replace"

        if webhook and (saved_demo or billing_demo_mode()):
            self.initial["stripe_webhook_secret"] = webhook
        elif billing_demo_mode():
            self.initial["stripe_webhook_secret"] = ref["webhook_secret"]
        elif webhook:
            self.fields["stripe_webhook_secret"].widget.attrs["placeholder"] = "Saved — enter new value to replace"

        if saved_demo and not (inst.notes or "").strip():
            self.initial["notes"] = "DEMO Stripe credentials — replace with real keys before production."


class StripeConfigAdmin(_MPModelAdmin):
    form = StripeConfigForm
    compressed_fields = False
    list_fullwidth = True
    list_display = ("provider", "is_enabled", "config_status", "updated_at")
    readonly_fields = (
        "provider",
        "config_status",
        "masked_secret_key",
        "masked_webhook_secret",
        "updated_at",
    )
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "is_enabled",
                    "provider",
                    "config_status",
                ),
                "description": "Enable to use database credentials. When disabled, MailPilot falls back to STRIPE_* values from the server environment.",
            },
        ),
        (
            "Stripe credentials",
            {
                "fields": (
                    "stripe_publishable_key",
                    "stripe_price_pro_monthly",
                    "stripe_secret_key",
                    "stripe_webhook_secret",
                    "masked_secret_key",
                    "masked_webhook_secret",
                ),
                "description": "Pre-filled demo placeholders on localhost — Save, test checkout, then replace with real Stripe keys.",
            },
        ),
        ("Notes", {"fields": ("notes",), "classes": ("collapse",)}),
        ("Meta", {"fields": ("updated_at",), "classes": ("collapse",)}),
    )

    def has_add_permission(self, request):
        return not Stripe.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj, _ = Stripe.objects.get_or_create(singleton_key=1)
        return redirect(reverse("admin:core_stripe_change", args=(obj.pk,)))

    @admin.display(description="Status")
    def config_status(self, obj):
        from core.crypto import decrypt_str
        from core.payment_gateway import (
            billing_demo_mode,
            get_stripe_credentials,
            is_demo_stripe_credentials,
            stripe_checkout_ready,
        )

        creds = get_stripe_credentials()
        if stripe_checkout_ready():
            return _badge("Checkout ready", "ok")
        if creds and is_demo_stripe_credentials(
            secret_key=creds.secret_key,
            price_pro_monthly=creds.price_pro_monthly,
            publishable_key=creds.publishable_key,
            webhook_secret=creds.webhook_secret,
        ):
            return _badge("Demo saved — replace keys", "warn")
        if obj.is_enabled:
            secret = decrypt_str(obj.stripe_secret_key_enc).strip()
            price = (obj.stripe_price_pro_monthly or "").strip()
            if secret and is_demo_stripe_credentials(
                secret_key=secret,
                price_pro_monthly=price,
                publishable_key=(obj.stripe_publishable_key or "").strip(),
                webhook_secret=decrypt_str(obj.stripe_webhook_secret_enc).strip(),
            ):
                return _badge("Demo saved — replace keys", "warn")
        if billing_demo_mode():
            return _badge("Demo mode (local)", "pro")
        if not obj.is_enabled:
            if creds and creds.source == "env":
                return _badge("Using .env", "warn")
            return _badge("Disabled", "muted")
        if creds and creds.secret_key:
            return _badge("Secret set (add price ID)", "warn")
        return _badge("Missing secret key", "danger")

    @admin.display(description="Current secret key")
    def masked_secret_key(self, obj):
        return masked_stripe_secret(obj.stripe_secret_key_enc)

    @admin.display(description="Current webhook secret")
    def masked_webhook_secret(self, obj):
        return masked_stripe_webhook(obj.stripe_webhook_secret_enc)

    def save_model(self, request, obj, form, change):
        secret = (form.cleaned_data.get("stripe_secret_key") or "").strip()
        webhook = (form.cleaned_data.get("stripe_webhook_secret") or "").strip()
        if secret:
            obj.stripe_secret_key_enc = encrypt_str(secret)
        if webhook:
            obj.stripe_webhook_secret_enc = encrypt_str(webhook)
        obj.singleton_key = 1
        super().save_model(request, obj, form, change)


class PayPalConfigForm(forms.ModelForm):
    client_secret = forms.CharField(
        required=False,
        label="PayPal client secret",
        help_text="Save demo values now; later replace with real secret from PayPal Developer Dashboard.",
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
                "spellcheck": "false",
                "class": "vTextField",
                "style": "font-family: ui-monospace, monospace; width: 100%;",
            }
        ),
    )

    class Meta:
        model = PayPal
        fields = (
            "is_enabled",
            "sandbox_mode",
            "client_id",
            "plan_pro_monthly",
            "webhook_id",
            "notes",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from core.crypto import decrypt_str
        from core.payment_gateway import (
            DEMO_PAYPAL_REFERENCE,
            billing_demo_mode,
            is_demo_paypal_credentials,
        )

        ref = DEMO_PAYPAL_REFERENCE
        mono = {
            "style": "font-family: ui-monospace, monospace; width: 100%;",
            "class": "vTextField",
            "spellcheck": "false",
        }

        for name in ("client_id", "plan_pro_monthly", "webhook_id", "client_secret"):
            self.fields[name].widget.attrs.update(mono)

        inst = self.instance
        if not inst or not inst.pk:
            if billing_demo_mode():
                for key, field in (
                    ("client_id", "client_id"),
                    ("plan_pro_monthly", "plan_pro_monthly"),
                    ("webhook_id", "webhook_id"),
                    ("client_secret", "client_secret"),
                ):
                    self.initial[field] = ref[key]
            return

        cid = (inst.client_id or "").strip()
        plan = (inst.plan_pro_monthly or "").strip()
        webhook = (inst.webhook_id or "").strip()
        secret = decrypt_str(inst.client_secret_enc).strip()
        saved_demo = is_demo_paypal_credentials(
            client_id=cid,
            client_secret=secret,
            plan_pro_monthly=plan,
            webhook_id=webhook,
        )

        def _set(field: str, value: str, *, demo_fallback: str) -> None:
            if value:
                self.initial[field] = value
            elif billing_demo_mode():
                self.initial[field] = demo_fallback

        _set("client_id", cid, demo_fallback=ref["client_id"])
        _set("plan_pro_monthly", plan, demo_fallback=ref["plan_pro_monthly"])
        _set("webhook_id", webhook, demo_fallback=ref["webhook_id"])
        if secret and (saved_demo or billing_demo_mode()):
            self.initial["client_secret"] = secret
        elif billing_demo_mode():
            self.initial["client_secret"] = ref["client_secret"]
        elif secret:
            self.fields["client_secret"].widget.attrs["placeholder"] = "Saved — enter new value to replace"

        if saved_demo and not (inst.notes or "").strip():
            self.initial["notes"] = "DEMO PayPal credentials — replace with real keys before production."


class PayPalConfigAdmin(_MPModelAdmin):
    form = PayPalConfigForm
    compressed_fields = False
    list_fullwidth = True
    list_display = ("sandbox_mode", "is_enabled", "config_status", "updated_at")
    readonly_fields = (
        "config_status",
        "masked_client_secret",
        "updated_at",
    )
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "is_enabled",
                    "sandbox_mode",
                    "config_status",
                ),
                "description": "Enable to use database credentials. When disabled, MailPilot falls back to PAYPAL_* values from the server environment.",
            },
        ),
        (
            "PayPal credentials",
            {
                "fields": (
                    "client_id",
                    "client_secret",
                    "plan_pro_monthly",
                    "webhook_id",
                    "masked_client_secret",
                ),
                "description": "Pre-filled demo placeholders on localhost — Save, then replace with real PayPal Developer Dashboard keys.",
            },
        ),
        ("Notes", {"fields": ("notes",), "classes": ("collapse",)}),
        ("Meta", {"fields": ("updated_at",), "classes": ("collapse",)}),
    )

    def has_add_permission(self, request):
        return not PayPal.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj, _ = PayPal.objects.get_or_create(singleton_key=1)
        return redirect(reverse("admin:core_paypal_change", args=(obj.pk,)))

    @admin.display(description="Status")
    def config_status(self, obj):
        from core.crypto import decrypt_str
        from core.payment_gateway import (
            billing_demo_mode,
            get_paypal_credentials,
            is_demo_paypal_credentials,
            paypal_checkout_ready,
        )

        creds = get_paypal_credentials()
        if paypal_checkout_ready():
            mode = "Sandbox" if (creds and creds.sandbox_mode) else "Live"
            return _badge(f"Checkout ready ({mode})", "ok")
        if creds and is_demo_paypal_credentials(
            client_id=creds.client_id,
            client_secret=creds.client_secret,
            plan_pro_monthly=creds.plan_pro_monthly,
            webhook_id=creds.webhook_id,
        ):
            return _badge("Demo saved — replace keys", "warn")
        if obj.is_enabled:
            secret = decrypt_str(obj.client_secret_enc).strip()
            if secret and is_demo_paypal_credentials(
                client_id=(obj.client_id or "").strip(),
                client_secret=secret,
                plan_pro_monthly=(obj.plan_pro_monthly or "").strip(),
                webhook_id=(obj.webhook_id or "").strip(),
            ):
                return _badge("Demo saved — replace keys", "warn")
        if billing_demo_mode():
            return _badge("Demo mode (local)", "pro")
        if not obj.is_enabled:
            if creds and creds.source == "env":
                return _badge("Using .env", "warn")
            return _badge("Disabled", "muted")
        if creds and creds.client_secret:
            return _badge("Secret set (add client ID + plan)", "warn")
        return _badge("Missing client secret", "danger")

    @admin.display(description="Current client secret")
    def masked_client_secret(self, obj):
        return masked_paypal_secret(obj.client_secret_enc)

    def save_model(self, request, obj, form, change):
        secret = (form.cleaned_data.get("client_secret") or "").strip()
        if secret:
            obj.client_secret_enc = encrypt_str(secret)
        obj.singleton_key = 1
        super().save_model(request, obj, form, change)


admin_site.register(User, MailPilotUserAdmin)
admin_site.register(Group, MailPilotGroupAdmin)
admin_site.register(UserProfile, UserProfileAdmin)
admin_site.register(UserMailSettings, UserMailSettingsAdmin)
admin_site.register(MailAccount, MailAccountAdmin)
admin_site.register(UserSubscription, UserSubscriptionAdmin)
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
admin_site.register(AuditLog, AuditLogAdmin)
admin_site.register(PasswordResetOTP, PasswordResetOTPAdmin)
admin_site.register(Stripe, StripeConfigAdmin)
admin_site.register(PayPal, PayPalConfigAdmin)
