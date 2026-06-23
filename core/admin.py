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
from core.payment_gateway import masked_paypal_secret, masked_stripe_restricted, masked_stripe_secret, masked_stripe_webhook
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


class StripeConfigForm(forms.ModelForm):
    clear_test_keys = forms.BooleanField(
        required=False,
        label="Clear test keys",
        help_text="Remove saved sk_test_ / rk_test_ keys.",
    )
    clear_live_keys = forms.BooleanField(
        required=False,
        label="Clear live keys",
        help_text="Remove saved sk_live_ / rk_live_ keys.",
    )
    stripe_test_restricted_key = forms.CharField(
        required=False,
        label="Test restricted key",
        help_text="rk_test_… from Dashboard → Test mode ON → Restricted keys.",
        widget=forms.TextInput(attrs={"autocomplete": "off", "spellcheck": "false"}),
    )
    stripe_test_secret_key = forms.CharField(
        required=False,
        label="Test secret key",
        help_text="sk_test_… — required for localhost checkout. Test card: 4242 4242 4242 4242.",
        widget=forms.TextInput(attrs={"autocomplete": "off", "spellcheck": "false"}),
    )
    stripe_live_restricted_key = forms.CharField(
        required=False,
        label="Live restricted key",
        help_text="rk_live_… from Dashboard → Live mode → Restricted keys.",
        widget=forms.TextInput(attrs={"autocomplete": "off", "spellcheck": "false"}),
    )
    stripe_live_secret_key = forms.CharField(
        required=False,
        label="Live secret key",
        help_text="sk_live_… — used on production when Key environment is Auto or Force live.",
        widget=forms.TextInput(attrs={"autocomplete": "off", "spellcheck": "false"}),
    )
    stripe_webhook_secret = forms.CharField(
        required=False,
        label="Webhook signing secret",
        help_text="whsec_… from Stripe Dashboard → Webhooks (optional; can also use STRIPE_WEBHOOK_SECRET in .env).",
        widget=forms.TextInput(attrs={"autocomplete": "off", "spellcheck": "false"}),
    )

    class Meta:
        model = Stripe
        fields = ("is_enabled", "stripe_key_environment")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from core.crypto import decrypt_str
        from core.payment_gateway import is_demo_stripe_credentials

        mono = {
            "style": "font-family: ui-monospace, monospace; width: 100%;",
            "class": "vTextField",
            "spellcheck": "false",
        }
        for name in (
            "stripe_test_restricted_key",
            "stripe_test_secret_key",
            "stripe_live_restricted_key",
            "stripe_live_secret_key",
            "stripe_webhook_secret",
        ):
            self.fields[name].widget.attrs.update(mono)

        inst = self.instance
        if not inst or not inst.pk:
            return

        test_rk = decrypt_str(getattr(inst, "stripe_test_restricted_key_enc", "") or "").strip()
        test_sk = decrypt_str(getattr(inst, "stripe_test_secret_key_enc", "") or "").strip()
        live_rk = decrypt_str(inst.stripe_restricted_key_enc or "").strip()
        live_sk = decrypt_str(inst.stripe_secret_key_enc or "").strip()

        if test_rk:
            self.initial["stripe_test_restricted_key"] = test_rk
        if test_sk and not is_demo_stripe_credentials(secret_key=test_sk):
            self.initial["stripe_test_secret_key"] = test_sk
        if live_rk:
            self.initial["stripe_live_restricted_key"] = live_rk
        if live_sk and not is_demo_stripe_credentials(secret_key=live_sk):
            self.initial["stripe_live_secret_key"] = live_sk
        webhook = decrypt_str(inst.stripe_webhook_secret_enc or "").strip()
        if webhook:
            self.initial["stripe_webhook_secret"] = webhook
            self.fields["stripe_webhook_secret"].widget.attrs["placeholder"] = "Saved — enter new value to replace"


class StripeConfigAdmin(_MPModelAdmin):
    form = StripeConfigForm
    compressed_fields = False
    list_fullwidth = True
    list_display = ("provider", "is_enabled", "config_status", "updated_at")
    readonly_fields = (
        "provider",
        "active_environment",
        "config_status",
        "deployment_guide",
        "test_keys_summary",
        "live_keys_summary",
        "webhook_summary",
        "updated_at",
    )
    fieldsets = (
        (
            "Environment",
            {
                "fields": (
                    "is_enabled",
                    "stripe_key_environment",
                    "provider",
                    "active_environment",
                    "config_status",
                    "deployment_guide",
                ),
                "description": (
                    "Save both test and live keys here once. "
                    "Key environment picks which set Checkout uses — Auto switches by server (DEBUG=local test, production=live)."
                ),
            },
        ),
        (
            "Local / test keys (sk_test_)",
            {
                "fields": (
                    "test_keys_summary",
                    "clear_test_keys",
                    "stripe_test_secret_key",
                    "stripe_test_restricted_key",
                ),
                "description": "Stripe Dashboard → turn Test mode ON → Developers → API keys.",
            },
        ),
        (
            "Production / live keys (sk_live_)",
            {
                "fields": (
                    "live_keys_summary",
                    "clear_live_keys",
                    "stripe_live_secret_key",
                    "stripe_live_restricted_key",
                ),
                "description": "Stripe Dashboard → Live mode → complete card_payments activation before going live.",
            },
        ),
        (
            "Webhooks (optional)",
            {
                "fields": ("webhook_summary", "stripe_webhook_secret"),
                "description": "Required only if you use Stripe webhooks for subscription events.",
                "classes": ("collapse",),
            },
        ),
        ("Meta", {"fields": ("updated_at",), "classes": ("collapse",)}),
    )

    def has_add_permission(self, request):
        return not Stripe.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj, _ = Stripe.objects.get_or_create(singleton_key=1)
        return redirect(reverse("admin:core_stripe_change", args=(obj.pk,)))

    @admin.display(description="Active now")
    def active_environment(self, obj):
        from django.conf import settings

        from core.payment_gateway import stripe_environment_label, stripe_resolved_environment

        env = stripe_resolved_environment()
        label = stripe_environment_label()
        mode = obj.get_stripe_key_environment_display() if obj else "Auto"
        server = "DEBUG (local)" if settings.DEBUG else "Production"
        return format_html(
            "<strong>{}</strong> keys · Admin: {} · Server: {}",
            label,
            mode,
            server,
        )

    @admin.display(description="Setup guide")
    def deployment_guide(self, obj):
        from django.conf import settings

        if settings.DEBUG:
            local = (
                "<strong>Local (now):</strong> Key environment = Auto or Force test. "
                "Save <code>sk_test_</code> above. Checkout uses test keys; card <code>4242 4242 4242 4242</code>."
            )
            deploy = (
                "<strong>After deploy:</strong> Set <code>DEBUG=false</code> on the server. "
                "Key environment = Auto uses live keys. Ensure <code>sk_live_</code> saved and Stripe card_payments active. "
                "Set <code>SITE_URL=https://yourdomain.com</code> and keep <code>FIELD_ENCRYPTION_KEY</code> identical to local."
            )
        else:
            local = (
                "<strong>Production (now):</strong> Auto or Force live uses <code>sk_live_</code>. "
                "Confirm Stripe Dashboard shows card payments enabled."
            )
            deploy = (
                "<strong>Local dev:</strong> On your machine keep <code>DEBUG=true</code> and save test keys; "
                "this server uses live keys only when deployed with <code>DEBUG=false</code>."
            )
        from django.utils.safestring import mark_safe

        return mark_safe(f"<p>{local}</p><p>{deploy}</p>")

    @admin.display(description="Status")
    def config_status(self, obj):
        from core.payment_gateway import (
            get_stripe_credentials,
            stripe_checkout_block_reason,
            stripe_checkout_ready,
            stripe_environment_label,
            stripe_keys_status_for_env,
            stripe_resolved_environment,
        )

        block = stripe_checkout_block_reason()
        if stripe_checkout_ready():
            return _badge(f"Checkout ready ({stripe_environment_label()})", "ok")

        env = stripe_resolved_environment()
        status = stripe_keys_status_for_env(env)
        if status["ready"] == "live_blocked" or block:
            return _badge("Live account cannot accept charges", "danger")
        if status["ready"] == "missing":
            if not obj.is_enabled:
                creds = get_stripe_credentials()
                if creds and creds.source == "env":
                    return _badge("Using .env", "warn")
                return _badge("Disabled", "muted")
            need = "test" if env == "test" else "live"
            return _badge(f"Missing {need} secret key", "danger")
        if status["ready"] == "ok" and env == "test":
            return _badge("Test keys saved", "warn")
        if status["ready"] == "saved":
            return _badge("Live keys saved (activation pending)", "warn")
        return _badge("Keys saved", "warn")

    @admin.display(description="Test keys (preview)")
    def test_keys_summary(self, obj):
        from core.payment_gateway import stripe_keys_status_for_env

        s = stripe_keys_status_for_env("test")
        if s["secret"] == "—":
            return "No test keys saved."
        return f"Secret: {s['secret']} · Restricted: {s['restricted']}"

    @admin.display(description="Live keys (preview)")
    def live_keys_summary(self, obj):
        from core.payment_gateway import stripe_keys_status_for_env

        s = stripe_keys_status_for_env("live")
        if s["secret"] == "—":
            return "No live keys saved."
        return f"Secret: {s['secret']} · Restricted: {s['restricted']}"

    @admin.display(description="Webhook (preview)")
    def webhook_summary(self, obj):
        from core.payment_gateway import masked_stripe_webhook

        masked = masked_stripe_webhook(obj.stripe_webhook_secret_enc)
        if masked == "—":
            return "Not saved (STRIPE_WEBHOOK_SECRET env may still work)."
        return masked

    def save_model(self, request, obj, form, change):
        if form.cleaned_data.get("clear_test_keys"):
            obj.stripe_test_restricted_key_enc = ""
            obj.stripe_test_secret_key_enc = ""
        else:
            test_rk = (form.cleaned_data.get("stripe_test_restricted_key") or "").strip()
            test_sk = (form.cleaned_data.get("stripe_test_secret_key") or "").strip()
            if test_rk:
                obj.stripe_test_restricted_key_enc = encrypt_str(test_rk)
            if test_sk:
                obj.stripe_test_secret_key_enc = encrypt_str(test_sk)

        if form.cleaned_data.get("clear_live_keys"):
            obj.stripe_restricted_key_enc = ""
            obj.stripe_secret_key_enc = ""
        else:
            live_rk = (form.cleaned_data.get("stripe_live_restricted_key") or "").strip()
            live_sk = (form.cleaned_data.get("stripe_live_secret_key") or "").strip()
            if live_rk:
                obj.stripe_restricted_key_enc = encrypt_str(live_rk)
            if live_sk:
                obj.stripe_secret_key_enc = encrypt_str(live_sk)

        webhook = (form.cleaned_data.get("stripe_webhook_secret") or "").strip()
        if webhook:
            obj.stripe_webhook_secret_enc = encrypt_str(webhook)

        obj.singleton_key = 1
        super().save_model(request, obj, form, change)


class PayPalConfigForm(forms.ModelForm):
    clear_sandbox_credentials = forms.BooleanField(
        required=False,
        label="Clear sandbox credentials",
        help_text="Remove saved sandbox Client ID and secret.",
    )
    clear_live_credentials = forms.BooleanField(
        required=False,
        label="Clear live credentials",
        help_text="Remove saved live Client ID and secret.",
    )
    sandbox_client_secret = forms.CharField(
        required=False,
        label="Sandbox client secret",
        help_text="Secret from developer.paypal.com → Apps → Sandbox.",
        widget=forms.TextInput(attrs={"autocomplete": "off", "spellcheck": "false"}),
    )
    live_client_secret = forms.CharField(
        required=False,
        label="Live client secret",
        help_text="Live secret for production (DEBUG=false).",
        widget=forms.TextInput(attrs={"autocomplete": "off", "spellcheck": "false"}),
    )

    class Meta:
        model = PayPal
        fields = (
            "is_enabled",
            "paypal_environment",
            "sandbox_client_id",
            "live_client_id",
            "plan_pro_monthly",
            "webhook_id",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from core.crypto import decrypt_str
        from core.payment_gateway import is_demo_paypal_credentials

        mono = {
            "style": "font-family: ui-monospace, monospace; width: 100%;",
            "class": "vTextField",
            "spellcheck": "false",
        }
        for name in (
            "sandbox_client_id",
            "live_client_id",
            "sandbox_client_secret",
            "live_client_secret",
            "plan_pro_monthly",
            "webhook_id",
        ):
            self.fields[name].widget.attrs.update(mono)

        inst = self.instance
        if not inst or not inst.pk:
            return

        sandbox_cid = (inst.sandbox_client_id or inst.client_id or "").strip()
        live_cid = (inst.live_client_id or "").strip()
        if sandbox_cid:
            self.initial["sandbox_client_id"] = sandbox_cid
        if live_cid:
            self.initial["live_client_id"] = live_cid

        sandbox_secret = decrypt_str(
            (inst.sandbox_client_secret_enc or inst.client_secret_enc or "")
        ).strip()
        live_secret = decrypt_str(inst.live_client_secret_enc or "").strip()
        if sandbox_secret and not is_demo_paypal_credentials(
            client_id=sandbox_cid, client_secret=sandbox_secret
        ):
            self.initial["sandbox_client_secret"] = sandbox_secret
            self.fields["sandbox_client_secret"].help_text = "Edit and save to update the sandbox secret."
        if live_secret and not is_demo_paypal_credentials(client_id=live_cid, client_secret=live_secret):
            self.initial["live_client_secret"] = live_secret
            self.fields["live_client_secret"].help_text = "Edit and save to update the live secret."


class PayPalConfigAdmin(_MPModelAdmin):
    form = PayPalConfigForm
    compressed_fields = False
    list_fullwidth = True
    list_display = ("is_enabled", "config_status", "updated_at")
    readonly_fields = (
        "active_paypal_environment",
        "config_status",
        "paypal_deployment_guide",
        "sandbox_credentials_summary",
        "live_credentials_summary",
        "updated_at",
    )
    fieldsets = (
        (
            "Environment",
            {
                "fields": (
                    "is_enabled",
                    "paypal_environment",
                    "active_paypal_environment",
                    "config_status",
                    "paypal_deployment_guide",
                ),
                "description": (
                    "Save sandbox and live credentials separately (like Stripe test/live keys). "
                    "Auto uses sandbox on localhost (DEBUG) and live API on production."
                ),
            },
        ),
        (
            "Sandbox credentials (local testing)",
            {
                "fields": (
                    "sandbox_credentials_summary",
                    "clear_sandbox_credentials",
                    "sandbox_client_id",
                    "sandbox_client_secret",
                ),
                "description": "developer.paypal.com → Dashboard → Sandbox → Apps & Credentials.",
            },
        ),
        (
            "Live credentials (production)",
            {
                "fields": (
                    "live_credentials_summary",
                    "clear_live_credentials",
                    "live_client_id",
                    "live_client_secret",
                ),
                "description": "Live Client ID + secret before go-live. Required when DEBUG=false and environment is Auto or Force live.",
            },
        ),
        (
            "Optional",
            {
                "fields": ("plan_pro_monthly", "webhook_id"),
                "classes": ("collapse",),
                "description": "PayPal Plan ID (P-…) for Pro monthly USD; otherwise a plan is created at checkout.",
            },
        ),
        ("Legacy", {"fields": ("sandbox_mode", "client_id"), "classes": ("collapse",)}),
        ("Meta", {"fields": ("updated_at",), "classes": ("collapse",)}),
    )

    def has_add_permission(self, request):
        return not PayPal.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj, _ = PayPal.objects.get_or_create(singleton_key=1)
        return redirect(reverse("admin:core_paypal_change", args=(obj.pk,)))

    @admin.display(description="Active now")
    def active_paypal_environment(self, obj):
        from django.conf import settings

        from core.payment_gateway import paypal_environment_label, paypal_resolved_environment

        label = paypal_environment_label()
        mode = obj.get_paypal_environment_display() if obj else "Auto"
        server = "DEBUG (local)" if settings.DEBUG else "Production"
        return format_html(
            "<strong>{}</strong> API · Admin: {} · Server: {}",
            label,
            mode,
            server,
        )

    @admin.display(description="Setup guide")
    def paypal_deployment_guide(self, obj):
        from django.conf import settings

        if settings.DEBUG:
            local = (
                "<strong>Local (now):</strong> PayPal environment = Auto or Force sandbox. "
                "Use sandbox Client ID + secret from developer.paypal.com."
            )
            deploy = (
                "<strong>After deploy:</strong> Set <code>DEBUG=false</code>. Auto uses <strong>live</strong> credentials above — "
                "save live Client ID + secret before go-live. Keep sandbox credentials for local dev."
            )
        else:
            local = (
                "<strong>Production (now):</strong> Auto or Force live uses live PayPal API."
            )
            deploy = (
                "<strong>Local dev:</strong> Keep sandbox credentials; Auto uses sandbox when <code>DEBUG=true</code>."
            )
        from django.utils.safestring import mark_safe

        return mark_safe(f"<p>{local}</p><p>{deploy}</p>")

    @admin.display(description="Status")
    def config_status(self, obj):
        from core.payment_gateway import (
            get_paypal_credentials,
            paypal_checkout_ready,
            paypal_environment_label,
            paypal_keys_status_for_env,
            paypal_resolved_environment,
        )

        if paypal_checkout_ready():
            return _badge(f"Checkout ready ({paypal_environment_label()})", "ok")

        env = paypal_resolved_environment()
        status = paypal_keys_status_for_env(env)
        if status["ready"] == "missing":
            if not obj.is_enabled:
                creds = get_paypal_credentials()
                if creds and creds.source == "env":
                    return _badge("Using .env", "warn")
                return _badge("Disabled", "muted")
            need = "sandbox" if env == "sandbox" else "live"
            return _badge(f"Missing {need} credentials", "danger")
        if status["ready"] == "ok" and env == "sandbox":
            return _badge("Sandbox credentials saved", "warn")
        return _badge("Credentials saved", "warn")

    @admin.display(description="Sandbox (preview)")
    def sandbox_credentials_summary(self, obj):
        from core.payment_gateway import paypal_keys_status_for_env

        s = paypal_keys_status_for_env("sandbox")
        if s["secret"] == "—":
            return "No sandbox credentials saved."
        return f"Client ID: {s['client_id']} · Secret: {s['secret']}"

    @admin.display(description="Live (preview)")
    def live_credentials_summary(self, obj):
        from core.payment_gateway import paypal_keys_status_for_env

        s = paypal_keys_status_for_env("live")
        if s["secret"] == "—":
            return "No live credentials saved."
        return f"Client ID: {s['client_id']} · Secret: {s['secret']}"

    def save_model(self, request, obj, form, change):
        if form.cleaned_data.get("clear_sandbox_credentials"):
            obj.sandbox_client_id = ""
            obj.sandbox_client_secret_enc = ""
            obj.client_id = ""
            obj.client_secret_enc = ""
        else:
            sandbox_cid = (form.cleaned_data.get("sandbox_client_id") or "").strip()
            sandbox_secret = (form.cleaned_data.get("sandbox_client_secret") or "").strip()
            if sandbox_cid:
                obj.sandbox_client_id = sandbox_cid
                obj.client_id = sandbox_cid
            if sandbox_secret:
                enc = encrypt_str(sandbox_secret)
                obj.sandbox_client_secret_enc = enc
                obj.client_secret_enc = enc

        if form.cleaned_data.get("clear_live_credentials"):
            obj.live_client_id = ""
            obj.live_client_secret_enc = ""
        else:
            live_cid = (form.cleaned_data.get("live_client_id") or "").strip()
            live_secret = (form.cleaned_data.get("live_client_secret") or "").strip()
            if live_cid:
                obj.live_client_id = live_cid
            if live_secret:
                obj.live_client_secret_enc = encrypt_str(live_secret)

        env = obj.paypal_environment or PayPal.PAYPAL_ENV_AUTO
        obj.sandbox_mode = env in (PayPal.PAYPAL_ENV_AUTO, PayPal.PAYPAL_ENV_SANDBOX)
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
