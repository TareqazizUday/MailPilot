from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import User
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth
from django.urls import reverse
from django.utils import timezone
from urllib.parse import urlencode

from core.billing import current_period_key, has_paid_entitlement, is_starter_expired
from core.models import (
    ContactSubmission,
    CustomPlanQuote,
    MailAccount,
    UsageCounter,
    UsageEvent,
    UserMailSettings,
    UserProfile,
    UserSubscription,
)

PRO_MRR_CENTS = 2000  # marketing Pro price ($20/mo) for estimates


def _user_label(user: User, profile: UserProfile | None = None) -> str:
    if profile and (profile.display_name or "").strip():
        return profile.display_name.strip()
    full = user.get_full_name().strip()
    if full:
        return full
    return user.email or user.username


def _profiles_for_users(user_ids: list[int]) -> dict[int, UserProfile]:
    if not user_ids:
        return {}
    return {p.user_id: p for p in UserProfile.objects.filter(user_id__in=user_ids)}


def _month_labels(n: int = 6) -> list[str]:
    today = timezone.localdate().replace(day=1)
    labels: list[str] = []
    y, m = today.year, today.month
    for _ in range(n):
        labels.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m < 1:
            m = 12
            y -= 1
    labels.reverse()
    return labels


def _series_from_month_map(labels: list[str], values: dict[str, int]) -> list[int]:
    return [int(values.get(label, 0)) for label in labels]


def _admin_changelist(route_name: str, params: dict | None = None) -> str:
    base = reverse(route_name)
    if not params:
        return base
    return f"{base}?{urlencode(params)}"


def build_kpi_links(*, period: str, today) -> dict[str, str]:
    today_s = today.isoformat()
    return {
        "users": _admin_changelist("admin:auth_user_changelist"),
        "subscriptions": _admin_changelist("admin:core_usersubscription_changelist"),
        "paid": _admin_changelist("admin:core_usersubscription_changelist"),
        "tokens": _admin_changelist(
            "admin:core_usagecounter_changelist",
            {"period_key": period},
        ),
        "mailboxes": _admin_changelist(
            "admin:core_mailaccount_changelist",
            {"is_enabled__exact": "1"},
        ),
        "auto_sends": _admin_changelist(
            "admin:core_usageevent_changelist",
            {"date": today_s, "status__exact": UsageEvent.STATUS_COMMITTED},
        ),
        "starter_expired": _admin_changelist(
            "admin:core_usersubscription_changelist",
            {
                "plan_code__exact": UserSubscription.PLAN_STARTER,
                "starter_expired_at__isnull": "False",
            },
        ),
        "contacts": _admin_changelist(
            "admin:core_contactsubmission_changelist",
            {"notified_team__exact": "0"},
        ),
    }


def build_dashboard_stats() -> dict:
    period = current_period_key()
    today = timezone.localdate()
    tokens_agg = UsageCounter.objects.filter(period_key=period).aggregate(total=Sum("tokens_used"))

    subs = UserSubscription.objects.all()
    starter_expired = sum(1 for s in subs.filter(plan_code=UserSubscription.PLAN_STARTER) if is_starter_expired(s))
    paid_subs = sum(1 for s in subs if has_paid_entitlement(s))

    pro_paid = subs.filter(plan_code=UserSubscription.PLAN_PRO)
    custom_paid = subs.filter(plan_code=UserSubscription.PLAN_CUSTOM)
    mrr_cents = 0
    for sub in pro_paid:
        if has_paid_entitlement(sub):
            mrr_cents += PRO_MRR_CENTS
    for sub in custom_paid:
        if not has_paid_entitlement(sub):
            continue
        quote = (
            CustomPlanQuote.objects.filter(user_id=sub.user_id, status=CustomPlanQuote.STATUS_PAID)
            .order_by("-paid_at", "-id")
            .first()
        )
        mrr_cents += int(quote.price_cents) if quote else 0

    return {
        "users": User.objects.count(),
        "subscriptions": subs.count(),
        "pro_plans": subs.filter(plan_code=UserSubscription.PLAN_PRO).count(),
        "custom_plans": subs.filter(plan_code=UserSubscription.PLAN_CUSTOM).count(),
        "paid_subscribers": paid_subs,
        "starter_expired": starter_expired,
        "active_mailboxes": MailAccount.objects.filter(is_enabled=True).count(),
        "tokens_this_month": int(tokens_agg.get("total") or 0),
        "auto_sends_today": UsageEvent.objects.filter(
            date=today,
            status=UsageEvent.STATUS_COMMITTED,
        ).count(),
        "open_contacts": ContactSubmission.objects.filter(notified_team=False).count(),
        "mrr_estimate_usd": round(mrr_cents / 100, 2),
        "today": today.isoformat(),
        "links": build_kpi_links(period=period, today=today),
    }


def build_chart_payload() -> dict:
    period = current_period_key()
    month_labels = _month_labels(6)

    plan_rows = (
        UserSubscription.objects.values("plan_code")
        .annotate(count=Count("id"))
        .order_by("plan_code")
    )
    plan_labels: list[str] = []
    plan_values: list[int] = []
    plan_colors: list[str] = []
    plan_user_names: list[list[str]] = []
    color_map = {
        UserSubscription.PLAN_STARTER: "#38bdf8",
        UserSubscription.PLAN_PRO: "#4f6ef7",
        UserSubscription.PLAN_CUSTOM: "#a78bfa",
    }
    label_map = {
        UserSubscription.PLAN_STARTER: "Starter",
        UserSubscription.PLAN_PRO: "Pro",
        UserSubscription.PLAN_CUSTOM: "Custom",
    }
    users_by_plan: dict[str, list[str]] = {
        UserSubscription.PLAN_STARTER: [],
        UserSubscription.PLAN_PRO: [],
        UserSubscription.PLAN_CUSTOM: [],
    }
    sub_user_ids = list(UserSubscription.objects.values_list("user_id", flat=True))
    sub_profiles = _profiles_for_users(sub_user_ids)
    for sub in UserSubscription.objects.select_related("user").order_by("user__email", "user__username"):
        profile = sub_profiles.get(sub.user_id)
        users_by_plan.setdefault(sub.plan_code, []).append(_user_label(sub.user, profile))
    for row in plan_rows:
        code = row["plan_code"]
        plan_labels.append(label_map.get(code, code))
        plan_values.append(int(row["count"]))
        plan_colors.append(color_map.get(code, "#94a3b8"))
        plan_user_names.append(users_by_plan.get(code, []))

    token_by_period = {
        row["period_key"]: int(row["total"] or 0)
        for row in UsageCounter.objects.values("period_key").annotate(total=Sum("tokens_used"))
    }
    token_series = _series_from_month_map(month_labels, token_by_period)

    signup_map: dict[str, int] = {}
    for row in (
        User.objects.annotate(month=TruncMonth("date_joined"))
        .values("month")
        .annotate(count=Count("id"))
        .order_by("month")
    ):
        if row["month"]:
            signup_map[row["month"].strftime("%Y-%m")] = int(row["count"])
    signup_series = _series_from_month_map(month_labels, signup_map)

    transport_rows = (
        MailAccount.objects.filter(is_enabled=True)
        .values("transport")
        .annotate(count=Count("id"))
    )
    gmail_count = 0
    smtp_count = 0
    for row in transport_rows:
        if row["transport"] == MailAccount.TRANSPORT_GMAIL:
            gmail_count = int(row["count"])
        elif row["transport"] == MailAccount.TRANSPORT_SMTP:
            smtp_count = int(row["count"])

    tg_entitled = UserSubscription.objects.filter(telegram_enabled=True).count()
    wa_entitled = UserSubscription.objects.filter(whatsapp_enabled=True).count()
    tg_configured = UserMailSettings.objects.exclude(telegram_bot_token_enc="").count()
    wa_configured = UserMailSettings.objects.exclude(whatsapp_access_token_enc="").count()

    today = timezone.localdate()
    start = today - timedelta(days=29)
    auto_map: dict[str, int] = {}
    for row in (
        UsageEvent.objects.filter(
            date__gte=start,
            date__lte=today,
            status=UsageEvent.STATUS_COMMITTED,
        )
        .values("date")
        .annotate(count=Count("id"))
        .order_by("date")
    ):
        auto_map[row["date"].isoformat()] = int(row["count"])
    auto_labels: list[str] = []
    auto_series: list[int] = []
    d = start
    while d <= today:
        auto_labels.append(d.strftime("%b %d"))
        auto_series.append(auto_map.get(d.isoformat(), 0))
        d += timedelta(days=1)

    paid_map: dict[str, int] = {k: 0 for k in month_labels}
    for sub in UserSubscription.objects.exclude(paid_at__isnull=True):
        if sub.paid_at:
            key = sub.paid_at.strftime("%Y-%m")
            if key in paid_map:
                paid_map[key] += 1
    for quote in CustomPlanQuote.objects.filter(status=CustomPlanQuote.STATUS_PAID).exclude(paid_at__isnull=True):
        key = quote.paid_at.strftime("%Y-%m")
        if key in paid_map:
            paid_map[key] += 1
    paid_series = [paid_map[k] for k in month_labels]

    top_users: list[dict] = []
    top_chart_labels: list[str] = []
    top_chart_series: list[int] = []
    counters = (
        UsageCounter.objects.filter(period_key=period)
        .select_related("user")
        .order_by("-tokens_used")[:10]
    )
    user_ids = [c.user_id for c in counters]
    profiles = _profiles_for_users(user_ids)
    subs_by_user = {s.user_id: s for s in UserSubscription.objects.filter(user_id__in=user_ids)}
    for counter in counters:
        sub = subs_by_user.get(counter.user_id)
        profile = profiles.get(counter.user_id)
        limit = int(sub.monthly_token_limit) if sub and sub.monthly_token_limit else None
        used = int(counter.tokens_used)
        pct = min(100, round((used / max(1, limit)) * 100)) if limit else None
        plan = sub.get_plan_code_display() if sub else "—"
        name = _user_label(counter.user, profile)
        email = counter.user.email or counter.user.username
        top_users.append(
            {
                "name": name,
                "email": email,
                "plan": plan,
                "used": used,
                "limit": limit,
                "pct": pct,
            }
        )
        top_chart_labels.append(name)
        top_chart_series.append(used)

    users_plan_labels: list[str] = []
    users_plan_series: list[int] = []
    users_plan_colors: list[str] = []
    users_plan_plans: list[str] = []
    usage_by_user = {
        row["user_id"]: int(row["tokens_used"])
        for row in UsageCounter.objects.filter(period_key=period).values("user_id", "tokens_used")
    }
    for sub in UserSubscription.objects.select_related("user").order_by("user__first_name", "user__email"):
        profile = sub_profiles.get(sub.user_id)
        users_plan_labels.append(_user_label(sub.user, profile))
        users_plan_series.append(usage_by_user.get(sub.user_id, 0))
        users_plan_colors.append(color_map.get(sub.plan_code, "#94a3b8"))
        users_plan_plans.append(label_map.get(sub.plan_code, sub.plan_code))

    mailbox_rows: list[dict] = []
    for row in (
        MailAccount.objects.filter(is_enabled=True)
        .values("user_id")
        .annotate(
            total=Count("id"),
            gmail=Count("id", filter=Q(transport=MailAccount.TRANSPORT_GMAIL)),
            smtp=Count("id", filter=Q(transport=MailAccount.TRANSPORT_SMTP)),
        )
        .order_by("-total")[:10]
    ):
        mailbox_rows.append(row)
    mb_user_ids = [r["user_id"] for r in mailbox_rows]
    mb_users = {u.id: u for u in User.objects.filter(id__in=mb_user_ids)}
    mb_profiles = _profiles_for_users(mb_user_ids)
    mailboxes_by_user = {
        "labels": [],
        "gmail": [],
        "smtp": [],
    }
    for row in mailbox_rows:
        user = mb_users.get(row["user_id"])
        if not user:
            continue
        mailboxes_by_user["labels"].append(_user_label(user, mb_profiles.get(row["user_id"])))
        mailboxes_by_user["gmail"].append(int(row["gmail"]))
        mailboxes_by_user["smtp"].append(int(row["smtp"]))

    integration_users: list[dict] = []
    integration_ids: list[int] = []
    for ms in UserMailSettings.objects.select_related("user").order_by("user__email"):
        tg = bool((ms.telegram_bot_token_enc or "").strip())
        wa = bool((ms.whatsapp_access_token_enc or "").strip())
        if not tg and not wa:
            continue
        integration_ids.append(ms.user_id)
        integration_users.append({"user": ms.user, "telegram": 1 if tg else 0, "whatsapp": 1 if wa else 0})
    int_profiles = _profiles_for_users(integration_ids)
    integration_payload = {
        "labels": [],
        "telegram": [],
        "whatsapp": [],
    }
    for row in integration_users[:12]:
        integration_payload["labels"].append(_user_label(row["user"], int_profiles.get(row["user"].id)))
        integration_payload["telegram"].append(row["telegram"])
        integration_payload["whatsapp"].append(row["whatsapp"])

    return {
        "plan_mix": {
            "labels": plan_labels,
            "series": plan_values,
            "colors": plan_colors,
            "user_names": plan_user_names,
        },
        "tokens_monthly": {
            "labels": month_labels,
            "series": token_series,
        },
        "signups_monthly": {
            "labels": month_labels,
            "series": signup_series,
        },
        "mail_transport": {
            "labels": ["Gmail", "SMTP/IMAP"],
            "series": [gmail_count, smtp_count],
            "colors": ["#4f6ef7", "#38bdf8"],
        },
        "integrations": {
            "labels": ["Telegram", "WhatsApp"],
            "entitled": [tg_entitled, wa_entitled],
            "configured": [tg_configured, wa_configured],
        },
        "auto_sends_daily": {
            "labels": auto_labels,
            "series": auto_series,
        },
        "paid_conversions": {
            "labels": month_labels,
            "series": paid_series,
        },
        "top_token_users": top_users,
        "top_token_chart": {
            "labels": top_chart_labels,
            "series": top_chart_series,
        },
        "users_by_plan": {
            "labels": users_plan_labels,
            "series": users_plan_series,
            "colors": users_plan_colors,
            "plans": users_plan_plans,
        },
        "mailboxes_by_user": mailboxes_by_user,
        "integration_users": integration_payload,
        "period": period,
    }
