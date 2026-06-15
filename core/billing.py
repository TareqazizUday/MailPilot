from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from core.models import DailySendCounter, MailAccount, UsageCounter, UsageEvent, UserSubscription


PLAN_STARTER = UserSubscription.PLAN_STARTER
PLAN_PRO = UserSubscription.PLAN_PRO
PLAN_CUSTOM = UserSubscription.PLAN_CUSTOM

PROVIDER_GMAIL_PERSONAL = DailySendCounter.PROVIDER_GMAIL_PERSONAL
PROVIDER_GOOGLE_WORKSPACE = DailySendCounter.PROVIDER_GOOGLE_WORKSPACE
PROVIDER_SMTP_PERSONAL = DailySendCounter.PROVIDER_SMTP_PERSONAL
PROVIDER_SMTP_BUSINESS = DailySendCounter.PROVIDER_SMTP_BUSINESS

PROVIDER_SAFE_CAPS = {
    PROVIDER_GMAIL_PERSONAL: 400,
    PROVIDER_GOOGLE_WORKSPACE: 1500,
    PROVIDER_SMTP_PERSONAL: 100,
    PROVIDER_SMTP_BUSINESS: 1500,
}

TOKENS_PER_AUTO_SEND = 5


PLAN_DEFAULTS: dict[str, dict[str, Any]] = {
    PLAN_STARTER: {
        "monthly_token_limit": 20,
        "active_inbox_limit": 1,
        "daily_send_limit": 5,
        "kb_source_limit": 1,
        "telegram_enabled": False,
        "whatsapp_enabled": False,
    },
    PLAN_PRO: {
        "monthly_token_limit": 1000,
        "active_inbox_limit": 3,
        "daily_send_limit": 100,
        "kb_source_limit": None,
        "telegram_enabled": True,
        "whatsapp_enabled": True,
    },
    PLAN_CUSTOM: {
        "monthly_token_limit": None,
        "active_inbox_limit": None,
        "daily_send_limit": None,
        "kb_source_limit": None,
        "telegram_enabled": True,
        "whatsapp_enabled": True,
    },
}


@dataclass(frozen=True)
class GateResult:
    allowed: bool
    reason: str = ""
    summary: dict[str, Any] | None = None


@dataclass(frozen=True)
class BillingReservation:
    allowed: bool
    reason: str = ""
    event_id: int | None = None
    summary: dict[str, Any] | None = None


def current_period_key(now=None) -> str:
    dt = now or timezone.localtime()
    return f"{dt.year:04d}-{dt.month:02d}"


def today_for_user(user) -> date:
    return timezone.localdate()


def plan_defaults(plan_code: str) -> dict[str, Any]:
    return dict(PLAN_DEFAULTS.get(plan_code or PLAN_STARTER) or PLAN_DEFAULTS[PLAN_STARTER])


def get_or_create_subscription(user) -> UserSubscription:
    sub, created = UserSubscription.objects.get_or_create(
        user=user,
        defaults={
            "plan_code": PLAN_STARTER,
            "status": UserSubscription.STATUS_ACTIVE,
        },
    )
    if created:
        apply_plan_defaults(sub)
    return sub


def apply_plan_defaults(sub: UserSubscription) -> UserSubscription:
    defaults = plan_defaults(sub.plan_code)
    changed: list[str] = []
    for key, value in defaults.items():
        if getattr(sub, key) is None:
            setattr(sub, key, value)
            changed.append(key)
    if changed:
        sub.save(update_fields=[*changed, "updated_at"])
    return sub


def set_subscription_plan(sub: UserSubscription, plan_code: str, *, status: str | None = None) -> UserSubscription:
    sub.plan_code = plan_code if plan_code in PLAN_DEFAULTS else PLAN_STARTER
    if status:
        sub.status = status
    defaults = plan_defaults(sub.plan_code)
    for key, value in defaults.items():
        setattr(sub, key, value)
    sub.save()
    return sub


def get_plan_limits(user) -> dict[str, Any]:
    sub = apply_plan_defaults(get_or_create_subscription(user))
    defaults = plan_defaults(sub.plan_code)

    def pick(key: str):
        value = getattr(sub, key, None)
        return defaults.get(key) if value is None else value

    return {
        "plan_code": sub.plan_code,
        "status": sub.status,
        "monthly_token_limit": pick("monthly_token_limit"),
        "active_inbox_limit": pick("active_inbox_limit"),
        "daily_send_limit": pick("daily_send_limit"),
        "kb_source_limit": pick("kb_source_limit"),
        "telegram_enabled": bool(pick("telegram_enabled")),
        "whatsapp_enabled": bool(pick("whatsapp_enabled")),
        "stripe_customer_id": sub.stripe_customer_id,
        "stripe_subscription_id": sub.stripe_subscription_id,
    }


def _enabled_inbox_count(user, *, excluding_account_id: int | None = None) -> int:
    qs = MailAccount.objects.filter(user=user, is_enabled=True)
    if excluding_account_id:
        qs = qs.exclude(pk=excluding_account_id)
    return qs.count()


def get_monthly_counter(user, *, period_key: str | None = None) -> UsageCounter:
    key = period_key or current_period_key()
    counter, _ = UsageCounter.objects.get_or_create(user=user, period_key=key)
    return counter


def _provider_profile_for_account(account: MailAccount) -> str:
    cfg = dict(account.config_json or {})
    raw = str(cfg.get("PROVIDER_PROFILE") or "").strip()
    if raw in PROVIDER_SAFE_CAPS:
        return raw
    if account.transport == MailAccount.TRANSPORT_SMTP:
        return PROVIDER_SMTP_PERSONAL
    email = str(cfg.get("GMAIL_ADDRESS") or "").strip().lower()
    if email.endswith("@gmail.com") or email.endswith("@googlemail.com"):
        return PROVIDER_GMAIL_PERSONAL
    return PROVIDER_GOOGLE_WORKSPACE


def daily_limit_for_account(user, account: MailAccount) -> int | None:
    limits = get_plan_limits(user)
    plan_limit = limits.get("daily_send_limit")
    provider_profile = _provider_profile_for_account(account)
    provider_limit = PROVIDER_SAFE_CAPS.get(provider_profile)
    if plan_limit is None:
        return provider_limit
    if provider_limit is None:
        return int(plan_limit)
    return min(int(plan_limit), int(provider_limit))


def usage_summary(user, *, account: MailAccount | None = None) -> dict[str, Any]:
    limits = get_plan_limits(user)
    period_key = current_period_key()
    monthly = get_monthly_counter(user, period_key=period_key)
    monthly_limit = limits.get("monthly_token_limit")
    monthly_left = None if monthly_limit is None else max(0, int(monthly_limit) - int(monthly.tokens_used))
    active_inbox_limit = limits.get("active_inbox_limit")
    active_inboxes = _enabled_inbox_count(user)
    active_inbox_left = None if active_inbox_limit is None else max(0, int(active_inbox_limit) - active_inboxes)

    daily: dict[str, Any] = {
        "date": today_for_user(user).isoformat(),
        "provider_profile": "",
        "limit": None,
        "used": 0,
        "left": None,
    }
    if account is not None:
        day = today_for_user(user)
        provider_profile = _provider_profile_for_account(account)
        daily_limit = daily_limit_for_account(user, account)
        row = DailySendCounter.objects.filter(mail_account=account, date=day).first()
        used = int(row.sends_used) if row else 0
        daily = {
            "date": day.isoformat(),
            "provider_profile": provider_profile,
            "limit": daily_limit,
            "used": used,
            "left": None if daily_limit is None else max(0, int(daily_limit) - used),
        }

    return {
        "plan": {
            "code": limits["plan_code"],
            "status": limits["status"],
            "telegram_enabled": limits["telegram_enabled"],
            "whatsapp_enabled": limits["whatsapp_enabled"],
        },
        "period_key": period_key,
        "tokens": {
            "limit": monthly_limit,
            "used": int(monthly.tokens_used),
            "left": monthly_left,
        },
        "active_inboxes": {
            "limit": active_inbox_limit,
            "used": active_inboxes,
            "left": active_inbox_left,
        },
        "kb_sources": {
            "limit": limits.get("kb_source_limit"),
        },
        "daily": daily,
        "features": {
            "telegram": bool(limits.get("telegram_enabled")),
            "whatsapp": bool(limits.get("whatsapp_enabled")),
        },
    }


def can_enable_mailbox(user, *, excluding_account_id: int | None = None) -> GateResult:
    limits = get_plan_limits(user)
    limit = limits.get("active_inbox_limit")
    used = _enabled_inbox_count(user, excluding_account_id=excluding_account_id)
    if limit is not None and used >= int(limit):
        return GateResult(False, "plan_inbox_limit_reached", usage_summary(user))
    return GateResult(True, "", usage_summary(user))


def can_use_integration(user, integration: str) -> GateResult:
    limits = get_plan_limits(user)
    key = "telegram_enabled" if integration == "telegram" else "whatsapp_enabled"
    if not bool(limits.get(key)):
        return GateResult(False, "upgrade_required", usage_summary(user))
    return GateResult(True, "", usage_summary(user))


def can_use_kb_source(user, *, account_id: int | None = None, replacing: bool = False) -> GateResult:
    limits = get_plan_limits(user)
    limit = limits.get("kb_source_limit")
    if limit is None:
        return GateResult(True, "", usage_summary(user))
    if replacing:
        return GateResult(True, "", usage_summary(user))
    try:
        from core import runtime
        from email_automation.kb.store import VectorStore, is_vector_db_configured
        from core.mail_accounts import tenant_id_for_account

        effective = runtime.get_effective_settings(user, account_id=account_id)
        if not is_vector_db_configured(effective):
            return GateResult(True, "", usage_summary(user))
        tenant_id = tenant_id_for_account(user.id, int(account_id)) if account_id else str(user.id)
        stats = VectorStore(settings=effective, tenant_id=tenant_id).stats()
        existing = int(stats.get("documents") or 0)
    except Exception:
        existing = 0
    if existing >= int(limit):
        return GateResult(False, "plan_kb_source_limit_reached", usage_summary(user))
    return GateResult(True, "", usage_summary(user))


def reserve_auto_send(user, account: MailAccount, message_id: str) -> BillingReservation:
    if not user or not getattr(user, "is_authenticated", False):
        return BillingReservation(False, "unauthorized")
    if not account or not message_id:
        return BillingReservation(False, "missing_account_or_message")

    now = timezone.now()
    day = today_for_user(user)
    period_key = current_period_key(now)
    units = TOKENS_PER_AUTO_SEND
    daily_send_units = 1

    with transaction.atomic():
        try:
            event = UsageEvent.objects.select_for_update().get(
                mail_account=account,
                message_id=str(message_id),
                event_type=UsageEvent.TYPE_AUTO_SEND,
            )
            if event.status == UsageEvent.STATUS_COMMITTED:
                return BillingReservation(False, "already_committed", event.id, usage_summary(user, account=account))
            if event.status == UsageEvent.STATUS_RESERVED:
                return BillingReservation(True, "", event.id, usage_summary(user, account=account))
            event.status = UsageEvent.STATUS_RESERVED
            event.units = units
            event.period_key = period_key
            event.date = day
            event.meta_json = {**(event.meta_json or {}), "re_reserved_at": now.isoformat()}
            event.save(update_fields=["status", "units", "period_key", "date", "meta_json"])
            return BillingReservation(True, "", event.id, usage_summary(user, account=account))
        except UsageEvent.DoesNotExist:
            pass

        counter = UsageCounter.objects.select_for_update().filter(user=user, period_key=period_key).first()
        if counter is None:
            counter = UsageCounter.objects.create(user=user, period_key=period_key)
        limits = get_plan_limits(user)
        monthly_limit = limits.get("monthly_token_limit")
        if monthly_limit is not None and int(counter.tokens_used) + units > int(monthly_limit):
            return BillingReservation(False, "monthly_token_limit_reached", None, usage_summary(user, account=account))

        daily_limit = daily_limit_for_account(user, account)
        provider_profile = _provider_profile_for_account(account)
        daily = DailySendCounter.objects.select_for_update().filter(mail_account=account, date=day).first()
        if daily is None:
            daily = DailySendCounter.objects.create(
                user=user,
                mail_account=account,
                date=day,
                provider_profile=provider_profile,
            )
        elif daily.provider_profile != provider_profile:
            daily.provider_profile = provider_profile
            daily.save(update_fields=["provider_profile", "updated_at"])
        if daily_limit is not None and int(daily.sends_used) + daily_send_units > int(daily_limit):
            return BillingReservation(False, "daily_send_limit_reached", None, usage_summary(user, account=account))

        try:
            event = UsageEvent.objects.create(
                user=user,
                mail_account=account,
                message_id=str(message_id),
                event_type=UsageEvent.TYPE_AUTO_SEND,
                units=units,
                status=UsageEvent.STATUS_RESERVED,
                period_key=period_key,
                date=day,
                meta_json={"reserved_at": now.isoformat(), "provider_profile": provider_profile},
            )
        except IntegrityError:
            event = UsageEvent.objects.select_for_update().get(
                mail_account=account,
                message_id=str(message_id),
                event_type=UsageEvent.TYPE_AUTO_SEND,
            )
        return BillingReservation(True, "", event.id, usage_summary(user, account=account))


def commit_auto_send(reservation: BillingReservation | int | None) -> None:
    event_id = reservation.event_id if isinstance(reservation, BillingReservation) else reservation
    if not event_id:
        return
    now = timezone.now()
    with transaction.atomic():
        event = UsageEvent.objects.select_for_update().select_related("mail_account", "user").filter(pk=event_id).first()
        if event is None or event.status == UsageEvent.STATUS_COMMITTED:
            return
        if event.status != UsageEvent.STATUS_RESERVED:
            return
        counter, _ = UsageCounter.objects.select_for_update().get_or_create(user=event.user, period_key=event.period_key)
        daily, _ = DailySendCounter.objects.select_for_update().get_or_create(
            user=event.user,
            mail_account=event.mail_account,
            date=event.date,
            defaults={"provider_profile": _provider_profile_for_account(event.mail_account)},
        )
        UsageCounter.objects.filter(pk=counter.pk).update(
            tokens_used=F("tokens_used") + event.units,
            auto_sent_count=F("auto_sent_count") + 1,
        )
        DailySendCounter.objects.filter(pk=daily.pk).update(sends_used=F("sends_used") + 1)
        event.status = UsageEvent.STATUS_COMMITTED
        event.committed_at = now
        event.meta_json = {**(event.meta_json or {}), "committed_at": now.isoformat()}
        event.save(update_fields=["status", "committed_at", "meta_json"])


def fail_auto_send(reservation: BillingReservation | int | None, reason: str = "") -> None:
    event_id = reservation.event_id if isinstance(reservation, BillingReservation) else reservation
    if not event_id:
        return
    now = timezone.now()
    UsageEvent.objects.filter(pk=event_id, status=UsageEvent.STATUS_RESERVED).update(
        status=UsageEvent.STATUS_FAILED,
        meta_json={"failed_at": now.isoformat(), "reason": str(reason or "")[:500]},
    )

