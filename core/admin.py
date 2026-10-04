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
from core.admin_marketing_ui import MarketingListUIMixin, visibility_badges
from core.billing import apply_plan_defaults, current_period_key, set_subscription_plan
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
    MarketingLandingPage,
    MarketingRagItem,
    MarketingReview,
    MarketingPricingPlan,
    MarketingPricingSettings,
    PasswordResetOTP,
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


class MarketingFeatureAdmin(MarketingListUIMixin, _MPModelAdmin):
    mp_mkt_title = "Features"
    mp_mkt_subtitle = "Homepage feature cards — icon, title, description, accent"
    mp_mkt_site_url = "/#features"
    list_display = (
        "sort_order",
        "feature_cell",
        "accent_preview",
        "visibility_cell",
        "updated_at",
    )
    list_display_links = ("feature_cell",)
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

    @admin.display(description="Feature", ordering="title")
    def feature_cell(self, obj):
        desc = (obj.description or "").strip().replace("\n", " ")
        preview = f"{desc[:90]}…" if len(desc) > 90 else desc
        return format_html(
            '<span class="mp-mkt-row">'
            '<span class="mp-mkt-ico" style="color:{};background:color-mix(in srgb,{} 14%, white)">'
            '<i class="{}"></i></span>'
            '<span class="mp-mkt-row__text">'
            '<span class="mp-mkt-row__title">{}</span>'
            '<span class="mp-mkt-row__meta">{}</span>'
            "</span></span>",
            obj.accent_color or "#5b5bf0",
            obj.accent_color or "#5b5bf0",
            obj.icon_class or "fa-solid fa-star",
            obj.title,
            preview or "—",
        )

    @admin.display(description="Accent")
    def accent_preview(self, obj):
        color = (obj.accent_color or "#5b5bf0").strip()
        return format_html(
            '<span class="mp-mkt-swatch" style="background:{}"></span> <span class="mp-mkt-swatch-label">{}</span>',
            color,
            color,
        )

    @admin.display(description="Visibility")
    def visibility_cell(self, obj):
        return visibility_badges(is_published=obj.is_published, show_on_homepage=obj.show_on_homepage)


class HowItWorksStepAdmin(MarketingListUIMixin, _MPModelAdmin):
    mp_mkt_title = "How it works"
    mp_mkt_subtitle = "Homepage pipeline steps — order matches the landing page"
    mp_mkt_site_url = "/#how-it-works"
    list_display = (
        "sort_order",
        "step_cell",
        "accent_badge",
        "visibility_cell",
        "updated_at",
    )
    list_display_links = ("step_cell",)
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

    @admin.display(description="Step", ordering="title")
    def step_cell(self, obj):
        desc = (obj.description or "").strip().replace("\n", " ")
        preview = f"{desc[:90]}…" if len(desc) > 90 else desc
        return format_html(
            '<span class="mp-mkt-row">'
            '<span class="mp-mkt-step">{}</span>'
            '<span class="mp-mkt-row__text">'
            '<span class="mp-mkt-row__title">{}</span>'
            '<span class="mp-mkt-row__meta">{}</span>'
            "</span></span>",
            obj.sort_order or "—",
            obj.title,
            preview or "—",
        )

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

    @admin.display(description="Visibility")
    def visibility_cell(self, obj):
        return visibility_badges(is_published=obj.is_published, show_on_homepage=obj.show_on_homepage)


class MarketingReviewAdmin(MarketingListUIMixin, _MPModelAdmin):
    mp_mkt_title = "Reviews"
    mp_mkt_subtitle = "Homepage testimonials — quote, author, rating, accents"
    mp_mkt_site_url = "/#testimonials"
    list_display = (
        "sort_order",
        "review_cell",
        "rating_badge",
        "visibility_cell",
        "updated_at",
    )
    list_display_links = ("review_cell",)
    list_editable = ("sort_order",)
    list_filter = ("is_published", "show_on_homepage", "rating")
    search_fields = ("author_name", "author_role", "quote", "metric")
    ordering = ("sort_order", "id")
    actions = [publish_marketing_reviews, unpublish_marketing_reviews]
    fieldsets = (
        (None, {"fields": ("quote", "metric")}),
        ("Author", {"fields": ("author_name", "author_role", "avatar_initials", "photo")}),
        ("Display", {"fields": ("rating", "accent_primary", "accent_secondary", "sort_order")}),
        ("Visibility", {"fields": ("is_published", "show_on_homepage")}),
        ("Meta", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Review", ordering="author_name")
    def review_cell(self, obj):
        initials = (obj.avatar_initials or (obj.author_name or "?")[:2]).upper()
        quote = (obj.quote or "").strip().replace("\n", " ")
        preview = f"{quote[:88]}…" if len(quote) > 88 else quote
        a1 = (obj.accent_primary or "#5b5bf0").strip()
        a2 = (obj.accent_secondary or "#8a5bf0").strip()
        role = obj.author_role or ""
        return format_html(
            '<span class="mp-mkt-row">'
            '<span class="mp-mkt-avatar" style="background:linear-gradient(135deg,{},{})">{}</span>'
            '<span class="mp-mkt-row__text">'
            '<span class="mp-mkt-row__title">{}</span>'
            '<span class="mp-mkt-row__meta">{}</span>'
            '<span class="mp-mkt-row__meta">{}</span>'
            "</span></span>",
            a1,
            a2,
            initials,
            obj.author_name or "—",
            role,
            preview or "—",
        )

    @admin.display(description="Rating", ordering="rating")
    def rating_badge(self, obj):
        return _badge(f"{obj.rating}★", "warn" if obj.rating >= 5 else "pro")

    @admin.display(description="Visibility")
    def visibility_cell(self, obj):
        return visibility_badges(is_published=obj.is_published, show_on_homepage=obj.show_on_homepage)


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


class MarketingLandingPageAdmin(_MPModelAdmin):
    change_form_outer_before_template = "admin/core/marketinglandingpage/edit_header.html"
    fieldsets = (
        (
            "Hero",
            {
                "description": "Top of homepage — headline, CTAs, and floating status cards.",
                "fields": (
                    "hero_overline",
                    "hero_title_before",
                    "hero_title_highlight",
                    "hero_sub_html",
                    "hero_cta_primary",
                    "hero_cta_secondary",
                    "float_1_title",
                    "float_1_sub",
                    "float_2_title",
                    "float_2_sub",
                    "float_3_title",
                    "float_3_sub",
                ),
            },
        ),
        (
            "Logos strip",
            {
                "classes": ("collapse",),
                "description": "Label above the scrolling tools marquee.",
                "fields": ("logos_label",),
            },
        ),
        (
            "Features header",
            {
                "description": "Section title only — edit cards under Website → Features.",
                "fields": ("features_tag", "features_title", "features_sub"),
            },
        ),
        (
            "How it works header",
            {
                "description": "Section title only — edit steps under Website → How it works.",
                "fields": ("hiw_tag", "hiw_title_lead", "hiw_title_highlight", "hiw_sub"),
            },
        ),
        (
            "Grounding header",
            {
                "description": "RAG section title — edit bullets under Website → Grounding.",
                "fields": ("rag_tag", "rag_title_html"),
            },
        ),
        (
            "Reviews header",
            {
                "description": "Testimonials intro — edit quotes under Website → Reviews.",
                "fields": (
                    "testimonials_tag",
                    "testimonials_title_lead",
                    "testimonials_title_highlight",
                    "testimonials_intro",
                    "trust_strip_label",
                    "trust_logos",
                ),
            },
        ),
        (
            "Contact",
            {
                "description": "Contact section copy around the form.",
                "fields": (
                    "contact_tag",
                    "contact_title_lead",
                    "contact_title_highlight",
                    "contact_intro",
                    "contact_aside_title",
                    "contact_aside_body",
                    "contact_perk_1",
                    "contact_perk_2",
                    "contact_perk_3",
                    "contact_form_title",
                    "contact_form_sub",
                    "contact_message_placeholder",
                    "contact_privacy",
                ),
            },
        ),
        (
            "Bottom CTA",
            {
                "description": "Final banner — copy plus optional floating agent images (leave empty for defaults).",
                "fields": (
                    "cta_title",
                    "cta_sub",
                    "cta_primary",
                    "cta_secondary",
                    "cta_image_1",
                    "cta_image_2",
                ),
            },
        ),
        ("Meta", {"fields": ("updated_at",), "classes": ("collapse",)}),
    )
    readonly_fields = ("updated_at",)

    class Media:
        js = ("js/mailpilot-landing-admin.js",)

    def has_add_permission(self, request):
        return not MarketingLandingPage.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        from core.marketing import get_landing_page

        obj = get_landing_page()
        return redirect(reverse("admin:core_marketinglandingpage_change", args=(obj.pk,)))

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["title"] = "Landing page"
        return super().changeform_view(request, object_id, form_url, extra_context=extra_context)


class MarketingRagItemAdmin(MarketingListUIMixin, _MPModelAdmin):
    mp_mkt_title = "Grounding"
    mp_mkt_subtitle = "Homepage grounding bullets — ingest, retrieve, refuse guesses, isolation"
    mp_mkt_site_url = "/#rag"
    list_display = ("sort_order", "rag_cell", "visibility_cell", "updated_at")
    list_display_links = ("rag_cell",)
    list_editable = ("sort_order",)
    list_filter = ("is_published", "show_on_homepage", "accent")
    search_fields = ("title", "description")
    ordering = ("sort_order", "id")
    fieldsets = (
        (None, {"fields": ("title", "description")}),
        ("Display", {"fields": ("icon_emoji", "accent", "sort_order")}),
        ("Visibility", {"fields": ("is_published", "show_on_homepage")}),
        ("Meta", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Point", ordering="title")
    def rag_cell(self, obj):
        return format_html(
            '<span class="mp-mkt-row">'
            '<span class="mp-mkt-ico">{}</span>'
            '<span class="mp-mkt-row__text">'
            '<span class="mp-mkt-row__title">{}</span>'
            '<span class="mp-mkt-row__meta">{}</span>'
            "</span></span>",
            obj.icon_emoji or "•",
            obj.title,
            (obj.description or "")[:90],
        )

    @admin.display(description="Visibility")
    def visibility_cell(self, obj):
        return visibility_badges(is_published=obj.is_published, show_on_homepage=obj.show_on_homepage)


class MarketingHeroInboxItemForm(forms.ModelForm):
    class Meta:
        model = MarketingHeroInboxItem
        fields = "__all__"
        widgets = {
            "sender_name": forms.TextInput(attrs={"placeholder": "Alice Kim"}),
            "sender_context": forms.TextInput(attrs={"placeholder": "Product Inquiry"}),
            "subject": forms.TextInput(
                attrs={"placeholder": "Do you support custom integrations?"}
            ),
            "avatar_initials": forms.TextInput(
                attrs={"placeholder": "AK", "maxlength": "4", "style": "text-transform:uppercase"}
            ),
            "avatar_color_start": forms.TextInput(
                attrs={"placeholder": "#4f6ef7", "spellcheck": "false", "autocomplete": "off"}
            ),
            "avatar_color_end": forms.TextInput(
                attrs={"placeholder": "#a78bfa", "spellcheck": "false", "autocomplete": "off"}
            ),
            "badge_label": forms.TextInput(attrs={"placeholder": "✓ Auto-Replied"}),
            "badge_icon_class": forms.TextInput(
                attrs={"placeholder": "fa-solid fa-brain"}
            ),
        }


class MarketingHeroInboxItemAdmin(MarketingListUIMixin, _MPModelAdmin):
    form = MarketingHeroInboxItemForm
    mp_mkt_title = "Hero inbox"
    mp_mkt_subtitle = "Homepage hero mock inbox rows — mirrors the product UI preview"
    mp_mkt_site_url = "/#"
    mp_mkt_settings_url_name = "admin:core_marketingherosettings_changelist"
    mp_mkt_settings_label = "Hero card settings"
    change_form_outer_before_template = "admin/core/marketingheroinboxitem/edit_header.html"
    change_form_before_template = "admin/core/marketingheroinboxitem/edit_preview.html"
    list_display = (
        "sort_order",
        "hero_cell",
        "badge_badge",
        "visibility_cell",
        "updated_at",
    )
    list_display_links = ("hero_cell",)
    list_editable = ("sort_order",)
    list_filter = ("is_published", "show_on_homepage", "badge_type")
    search_fields = ("sender_name", "sender_context", "subject", "badge_label")
    ordering = ("sort_order", "id")
    actions = [publish_hero_inbox_items, unpublish_hero_inbox_items]
    fieldsets = (
        (
            "Message",
            {
                "description": "Sender line and subject as shown in the homepage hero inbox card.",
                "fields": ("sender_name", "sender_context", "subject"),
            },
        ),
        (
            "Avatar",
            {
                "description": "Initials and gradient used for the circular avatar.",
                "fields": ("avatar_initials", "avatar_color_start", "avatar_color_end"),
            },
        ),
        (
            "Status badge",
            {
                "description": "Right-side pill — type controls color; label and icon are free text.",
                "fields": ("badge_type", "badge_label", "badge_icon_class"),
            },
        ),
        (
            "Publishing",
            {
                "fields": ("sort_order", "is_published", "show_on_homepage"),
            },
        ),
        ("Meta", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )
    readonly_fields = ("created_at", "updated_at")

    class Media:
        js = ("js/mailpilot-hero-inbox-admin.js",)

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        extra_context = extra_context or {}
        if object_id:
            extra_context["title"] = "Edit hero inbox row"
        else:
            extra_context["title"] = "Add hero inbox row"
        return super().changeform_view(request, object_id, form_url, extra_context=extra_context)

    @admin.display(description="Inbox row", ordering="sender_name")
    def hero_cell(self, obj):
        subject = (obj.subject or "").strip()
        preview = f"{subject[:80]}…" if len(subject) > 80 else subject
        return format_html(
            '<span class="mp-mkt-row">'
            '<span class="mp-mkt-avatar" style="{}">{}</span>'
            '<span class="mp-mkt-row__text">'
            '<span class="mp-mkt-row__title">{}</span>'
            '<span class="mp-mkt-row__meta">{}</span>'
            '<span class="mp-mkt-row__meta">{}</span>'
            "</span></span>",
            obj.avatar_gradient_style,
            obj.avatar_initials or "?",
            obj.sender_name or "—",
            obj.sender_context or "",
            preview or "—",
        )

    @admin.display(description="Badge", ordering="badge_type")
    def badge_badge(self, obj):
        tones = {
            MarketingHeroInboxItem.BADGE_REPLIED: "ok",
            MarketingHeroInboxItem.BADGE_RAG: "pro",
            MarketingHeroInboxItem.BADGE_PENDING: "warn",
            MarketingHeroInboxItem.BADGE_SKIPPED: "muted",
        }
        label = obj.badge_label or obj.get_badge_type_display()
        return _badge(label, tones.get(obj.badge_type, "muted"))

    @admin.display(description="Visibility")
    def visibility_cell(self, obj):
        return visibility_badges(is_published=obj.is_published, show_on_homepage=obj.show_on_homepage)


class LegalTermsSettingsForm(forms.ModelForm):
    class Meta:
        model = LegalTermsSettings
        fields = ("title", "effective_date", "is_published", "body_html")
        widgets = {
            "body_html": CKEditorWidget(attrs={"rows": 24}),
        }


class LegalTermsSettingsAdmin(_MPModelAdmin):
    form = LegalTermsSettingsForm
    change_form_before_template = "admin/core/legal_toolbar.html"
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

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        extra_context = extra_context or {}
        obj = None
        if object_id:
            obj = self.get_object(request, object_id)
        extra_context["title"] = "Terms of service"
        extra_context["mp_mkt"] = {
            "title": "Terms of service",
            "subtitle": "Legal page linked from the site footer",
            "site_url": "/terms",
            "is_published": bool(obj and obj.is_published),
            "effective_date": obj.effective_date if obj else "",
        }
        return super().changeform_view(request, object_id, form_url, extra_context)

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
    change_form_before_template = "admin/core/legal_toolbar.html"
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

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        extra_context = extra_context or {}
        obj = None
        if object_id:
            obj = self.get_object(request, object_id)
        extra_context["title"] = "Privacy policy"
        extra_context["mp_mkt"] = {
            "title": "Privacy policy",
            "subtitle": "Legal page linked from the site footer",
            "site_url": "/privacy",
            "is_published": bool(obj and obj.is_published),
            "effective_date": obj.effective_date if obj else "",
        }
        return super().changeform_view(request, object_id, form_url, extra_context)

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


class MarketingFaqItemAdmin(MarketingListUIMixin, _MPModelAdmin):
    mp_mkt_title = "FAQ"
    mp_mkt_subtitle = "Homepage FAQ accordion — question, answer, icon"
    mp_mkt_site_url = "/#faq"
    mp_mkt_settings_url_name = "admin:core_marketingfaqsettings_changelist"
    mp_mkt_settings_label = "FAQ section settings"
    list_display = (
        "sort_order",
        "faq_cell",
        "visibility_cell",
        "updated_at",
    )
    list_display_links = ("faq_cell",)
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

    @admin.display(description="Question", ordering="question")
    def faq_cell(self, obj):
        return format_html(
            '<span class="mp-mkt-row">'
            '<span class="mp-mkt-ico"><i class="{}"></i></span>'
            '<span class="mp-mkt-row__text">'
            '<span class="mp-mkt-row__title">{}</span>'
            "</span></span>",
            obj.icon_class or "fa-solid fa-circle-question",
            obj.question,
        )

    @admin.display(description="Visibility")
    def visibility_cell(self, obj):
        return visibility_badges(is_published=obj.is_published, show_on_homepage=obj.show_on_homepage)


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
        ("Body copy", {"fields": ("intro",)}),
        ("Legacy", {"fields": ("demo_note",), "classes": ("collapse",)}),
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


class MarketingPricingPlanAdmin(MarketingListUIMixin, _MPModelAdmin):
    mp_mkt_title = "Pricing"
    mp_mkt_subtitle = "Homepage pricing cards — monthly/yearly, ribbons, CTAs"
    mp_mkt_site_url = "/#pricing"
    mp_mkt_settings_url_name = "admin:core_marketingpricingsettings_changelist"
    mp_mkt_settings_label = "Pricing section settings"
    list_display = (
        "sort_order",
        "plan_cell",
        "plan_badge",
        "featured_badge",
        "visibility_cell",
        "updated_at",
    )
    list_display_links = ("plan_cell",)
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

    @admin.display(description="Plan card", ordering="tier_label")
    def plan_cell(self, obj):
        price = (obj.price_display or "—").strip()
        suffix = (obj.price_suffix or "").strip()
        desc = (obj.description or "").strip().replace("\n", " ")
        preview = f"{desc[:70]}…" if len(desc) > 70 else desc
        return format_html(
            '<span class="mp-mkt-row">'
            '<span class="mp-mkt-row__text">'
            '<span class="mp-mkt-row__title">{}</span>'
            '<span class="mp-mkt-row__meta"><strong>{}</strong> {}</span>'
            '<span class="mp-mkt-row__meta">{}</span>'
            "</span></span>",
            obj.tier_label,
            price,
            suffix,
            preview or "—",
        )

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
        return _badge("Featured" if obj.is_featured else "—", "pro" if obj.is_featured else "muted")

    @admin.display(description="Visibility")
    def visibility_cell(self, obj):
        return visibility_badges(is_published=obj.is_published, show_on_homepage=obj.show_on_homepage)


class ContactSubmissionAdmin(_MPModelAdmin):
    list_display = ("from_cell", "message_preview", "notified_badge", "received_at")
    list_display_links = ("from_cell", "message_preview")
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
    list_before_template = "admin/core/contactsubmission/inbox_toolbar.html"
    actions = ("mark_team_notified", "mark_fully_notified")

    def has_add_permission(self, request):
        # Inbox is fed by the public contact form — no manual creates.
        return False

    def changelist_view(self, request, extra_context=None):
        qs = ContactSubmission.objects.all()
        extra_context = extra_context or {}
        extra_context["mp_inbox"] = {
            "total": qs.count(),
            "pending": qs.filter(notified_team=False, notified_user=False).count(),
            "team_ok": qs.filter(notified_team=True).count(),
            "user_ok": qs.filter(notified_user=True).count(),
        }
        extra_context["title"] = "Contact inbox"
        return super().changelist_view(request, extra_context=extra_context)

    @admin.display(description="From", ordering="name")
    def from_cell(self, obj):
        name = (obj.name or "").strip() or "Unknown"
        email = (obj.email or "").strip()
        phone = (obj.phone or "").strip()
        initial = (name[:1] or email[:1] or "?").upper()
        meta = email
        if phone:
            meta = f"{email} · {phone}" if email else phone
        return format_html(
            '<span class="mp-inbox-from">'
            '<span class="mp-inbox-avatar" aria-hidden="true">{}</span>'
            '<span class="mp-inbox-from__text">'
            '<span class="mp-inbox-from__name">{}</span>'
            '<span class="mp-inbox-from__meta">{}</span>'
            "</span></span>",
            initial,
            name,
            meta or "—",
        )

    @admin.display(description="Status")
    def notified_badge(self, obj):
        if obj.notified_team and obj.notified_user:
            return _badge("Delivered", "ok")
        if obj.notified_team:
            return _badge("Team only", "warn")
        if obj.notified_user:
            return _badge("User only", "warn")
        return _badge("Pending", "danger")

    @admin.display(description="Message")
    def message_preview(self, obj):
        text = (obj.message or "").strip().replace("\n", " ")
        preview = f"{text[:110]}…" if len(text) > 110 else (text or "—")
        return format_html('<span class="mp-inbox-msg">{}</span>', preview)

    @admin.display(description="Received", ordering="created_at")
    def received_at(self, obj):
        if not obj.created_at:
            return "—"
        return format_html(
            '<span class="mp-inbox-time" title="{}">{}</span>',
            obj.created_at.strftime("%Y-%m-%d %H:%M:%S %Z"),
            obj.created_at.strftime("%b %d, %Y · %H:%M"),
        )

    @admin.action(description="Mark team notified")
    def mark_team_notified(self, request, queryset):
        updated = queryset.update(notified_team=True)
        self.message_user(request, f"Marked {updated} message(s) as team notified.")

    @admin.action(description="Mark fully notified")
    def mark_fully_notified(self, request, queryset):
        updated = queryset.update(notified_team=True, notified_user=True)
        self.message_user(request, f"Marked {updated} message(s) as fully notified.")


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
admin_site.register(MarketingLandingPage, MarketingLandingPageAdmin)
admin_site.register(MarketingRagItem, MarketingRagItemAdmin)
admin_site.register(MarketingFaqSettings, MarketingFaqSettingsAdmin)
admin_site.register(MarketingFaqItem, MarketingFaqItemAdmin)
admin_site.register(LegalTermsSettings, LegalTermsSettingsAdmin)
admin_site.register(LegalPrivacySettings, LegalPrivacySettingsAdmin)
admin_site.register(MarketingPricingSettings, MarketingPricingSettingsAdmin)
admin_site.register(MarketingPricingPlan, MarketingPricingPlanAdmin)
admin_site.register(ContactSubmission, ContactSubmissionAdmin)
admin_site.register(AuditLog, AuditLogAdmin)
admin_site.register(PasswordResetOTP, PasswordResetOTPAdmin)
