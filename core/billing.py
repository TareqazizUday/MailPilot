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

TOKENS_PER_AUTO_SEND = 5  # default (Pro); Starter uses 4 via plan defaults
STARTER_LIFETIME_SEND_LIMIT = 20
STARTER_LIFETIME_TOKEN_LIMIT = 80


PLAN_DEFAULTS: dict[str, dict[str, Any]] = {
    PLAN_STARTER: {
        "monthly_token_limit": 80,
        "tokens_per_auto_send": 4,
        "active_inbox_limit": 1,
        "daily_send_limit": 20,
        "kb_source_limit": 1,
        "telegram_enabled": False,
        "whatsapp_enabled": False,
    },
    PLAN_PRO: {
        "monthly_token_limit": 1000,
        "tokens_per_auto_send": 5,
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


def tokens_per_auto_send_for_plan(plan_code: str) -> int:
    return int(plan_defaults(plan_code).get("tokens_per_auto_send") or TOKENS_PER_AUTO_SEND)


def is_starter_expired(sub: UserSubscription) -> bool:
    if sub.plan_code != PLAN_STARTER:
        return False
    if sub.starter_expired_at is not None:
        return True
    return int(sub.starter_lifetime_sends or 0) >= STARTER_LIFETIME_SEND_LIMIT


def has_paid_entitlement(sub: UserSubscription) -> bool:
    """True when Pro/Custom was purchased or manually confirmed by admin."""
    if sub.plan_code == PLAN_PRO:
        return bool(sub.paid_at) or bool((sub.stripe_subscription_id or "").strip())
    if sub.plan_code == PLAN_CUSTOM:
        return bool(sub.paid_at)
    return False


def _expire_starter_trial_if_needed(sub: UserSubscription) -> None:
    if sub.plan_code != PLAN_STARTER:
        return
    if int(sub.starter_lifetime_sends or 0) < STARTER_LIFETIME_SEND_LIMIT:
        return
    if sub.starter_expired_at is None:
        sub.starter_expired_at = timezone.now()
        sub.save(update_fields=["starter_expired_at", "updated_at"])


def starter_trial_gate(user) -> GateResult:
    sub = get_or_create_subscription(user)
    if sub.plan_code == PLAN_STARTER and is_starter_expired(sub):
        return GateResult(False, "starter_trial_expired", usage_summary(user))
    return GateResult(True, "", usage_summary(user))


def payment_required_gate(user) -> GateResult | None:
    """Paid plans need checkout/admin confirmation before mailbox setup."""
    sub = get_or_create_subscription(user)
    if sub.plan_code in (PLAN_PRO, PLAN_CUSTOM) and not has_paid_entitlement(sub):
        return GateResult(False, "payment_required", usage_summary(user))
    return None


def get_or_create_subscription(user) -> UserSubscription:
    sub, created = UserSubscription.objects.get_or_create(
        user=user,
        defaults={
            "plan_code": PLAN_STARTER,
            "status": UserSubscription.STATUS_ACTIVE,
        },
    )
    apply_plan_defaults(sub)
    return sub


def apply_plan_defaults(sub: UserSubscription) -> UserSubscription:
    defaults = plan_defaults(sub.plan_code)
    model_keys = (
        "monthly_token_limit",
        "active_inbox_limit",
        "daily_send_limit",
        "kb_source_limit",
        "telegram_enabled",
        "whatsapp_enabled",
    )
    changed: list[str] = []
    for key in model_keys:
        value = defaults.get(key)
        current = getattr(sub, key)
        if sub.plan_code == PLAN_CUSTOM:
            if current is None and value is not None:
                setattr(sub, key, value)
                changed.append(key)
        elif current != value:
            setattr(sub, key, value)
            changed.append(key)
    if changed:
        sub.save(update_fields=[*changed, "updated_at"])
    return sub


def set_subscription_plan(sub: UserSubscription, plan_code: str, *, status: str | None = None) -> UserSubscription:
    sub.plan_code = plan_code if plan_code in PLAN_DEFAULTS else PLAN_STARTER
    if status:
        sub.status = status
    if plan_code in (PLAN_PRO, PLAN_CUSTOM) and status == UserSubscription.STATUS_ACTIVE:
        if not sub.paid_at and plan_code == PLAN_PRO and (sub.stripe_subscription_id or "").strip():
            sub.paid_at = timezone.now()
    defaults = plan_defaults(sub.plan_code)
    model_keys = (
        "monthly_token_limit",
        "active_inbox_limit",
        "daily_send_limit",
        "kb_source_limit",
        "telegram_enabled",
        "whatsapp_enabled",
    )
    for key in model_keys:
        setattr(sub, key, defaults.get(key))
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
        "tokens_per_auto_send": tokens_per_auto_send_for_plan(sub.plan_code),
        "stripe_customer_id": sub.stripe_customer_id,
        "stripe_subscription_id": sub.stripe_subscription_id,
        "starter_lifetime_sends": int(sub.starter_lifetime_sends or 0),
        "starter_lifetime_send_limit": STARTER_LIFETIME_SEND_LIMIT,
        "starter_expired": is_starter_expired(sub),
        "paid": has_paid_entitlement(sub),
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
    sub = get_or_create_subscription(user)
    plan_code = limits["plan_code"]

    if plan_code == PLAN_STARTER:
        lifetime_sends = int(limits.get("starter_lifetime_sends") or 0)
        per_send = int(limits.get("tokens_per_auto_send") or tokens_per_auto_send_for_plan(PLAN_STARTER))
        monthly_limit = STARTER_LIFETIME_TOKEN_LIMIT
        tokens_used = lifetime_sends * per_send
        monthly_left = max(0, monthly_limit - tokens_used)
        if limits.get("starter_expired"):
            monthly_left = 0
    else:
        monthly = get_monthly_counter(user, period_key=period_key)
        monthly_limit = limits.get("monthly_token_limit")
        tokens_used = int(monthly.tokens_used)
        monthly_left = None if monthly_limit is None else max(0, int(monthly_limit) - tokens_used)

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
            "starter_expired": bool(limits.get("starter_expired")),
            "paid": bool(limits.get("paid")),
        },
        "period_key": period_key,
        "tokens": {
            "limit": monthly_limit,
            "used": tokens_used,
            "left": monthly_left,
            "per_send": limits.get("tokens_per_auto_send") or tokens_per_auto_send_for_plan(limits["plan_code"]),
        },
        "starter_trial": {
            "sends_used": int(limits.get("starter_lifetime_sends") or 0),
            "sends_limit": STARTER_LIFETIME_SEND_LIMIT,
            "sends_left": max(0, STARTER_LIFETIME_SEND_LIMIT - int(limits.get("starter_lifetime_sends") or 0)),
            "expired": bool(limits.get("starter_expired")),
            "lifetime": plan_code == PLAN_STARTER,
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


def profile_billing_display(billing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Flatten billing summary for profile template display."""
    b = billing or {}
    plan = str((b.get("plan") or {}).get("code") or PLAN_STARTER)
    starter_trial = b.get("starter_trial") or {}
    starter_expired = bool((b.get("plan") or {}).get("starter_expired") or starter_trial.get("expired"))
    tokens = b.get("tokens") or {}
    inboxes = b.get("active_inboxes") or {}
    used = int(tokens.get("used") or 0)
    limit = tokens.get("limit")
    left = tokens.get("left")
    unlimited = limit is None
    if plan == PLAN_STARTER:
        limit = STARTER_LIFETIME_TOKEN_LIMIT
        unlimited = False
        left = 0 if starter_expired else max(0, int(limit) - used)
    elif unlimited and plan != PLAN_CUSTOM:
        limit = int(plan_defaults(plan).get("monthly_token_limit") or 80)
        unlimited = False
        left = max(0, int(limit) - used)
    elif left is None and limit is not None:
        left = max(0, int(limit) - used)
    inbox_limit = inboxes.get("limit")
    inbox_used = int(inboxes.get("used") or 0)
    inbox_unlimited = inbox_limit is None
    if inbox_unlimited and plan != PLAN_CUSTOM:
        inbox_limit = int(plan_defaults(plan).get("active_inbox_limit") or 1)
        inbox_unlimited = False
    pct = 0
    if not unlimited and limit:
        pct = min(100, round((used / max(1, int(limit))) * 100))
    tok_left_int = int(left) if left is not None else 0
    tok_limit_int = int(limit) if limit is not None else 0
    per_send = tokens_per_auto_send_for_plan(plan)
    sends_max = None if unlimited else max(0, tok_limit_int // per_send)
    sends_left = None if unlimited else max(0, tok_left_int // per_send)
    sends_used = used // per_send if per_send else 0
    return {
        "bill_plan": plan,
        "bill_period": str(b.get("period_key") or current_period_key()),
        "bill_tok_used": used,
        "bill_tok_limit": tok_limit_int,
        "bill_tok_left": tok_left_int,
        "bill_tok_unlimited": unlimited,
        "bill_tok_pct": pct,
        "bill_tok_per_send": per_send,
        "bill_sends_max": sends_max if sends_max is not None else 0,
        "bill_sends_left": sends_left if sends_left is not None else 0,
        "bill_sends_used": sends_used,
        "bill_inbox_used": inbox_used,
        "bill_inbox_limit": int(inbox_limit) if inbox_limit is not None else inbox_used,
        "bill_inbox_unlimited": inbox_unlimited,
        "bill_starter_expired": starter_expired,
        "bill_starter_lifetime": plan == PLAN_STARTER,
        "bill_starter_sends_used": int(starter_trial.get("sends_used") or sends_used),
        "bill_starter_sends_limit": int(starter_trial.get("sends_limit") or STARTER_LIFETIME_SEND_LIMIT),
    }


def can_enable_mailbox(user, *, excluding_account_id: int | None = None) -> GateResult:
    expired = starter_trial_gate(user)
    if not expired.allowed:
        return expired
    pay_gate = payment_required_gate(user)
    if pay_gate is not None:
        return pay_gate
    limits = get_plan_limits(user)
    limit = limits.get("active_inbox_limit")
    used = _enabled_inbox_count(user, excluding_account_id=excluding_account_id)
    if limit is not None and used >= int(limit):
        return GateResult(False, "plan_inbox_limit_reached", usage_summary(user))
    return GateResult(True, "", usage_summary(user))


def can_use_integration(user, integration: str) -> GateResult:
    expired = starter_trial_gate(user)
    if not expired.allowed:
        return expired
    pay_gate = payment_required_gate(user)
    if pay_gate is not None:
        return pay_gate
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

    expired = starter_trial_gate(user)
    if not expired.allowed:
        return BillingReservation(False, expired.reason, None, expired.summary)

    now = timezone.now()
    day = today_for_user(user)
    period_key = current_period_key(now)
    limits = get_plan_limits(user)
    plan_code = limits["plan_code"]
    units = int(limits.get("tokens_per_auto_send") or tokens_per_auto_send_for_plan(plan_code))
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
        if plan_code == PLAN_STARTER:
            lifetime_sends = int(limits.get("starter_lifetime_sends") or 0)
            if lifetime_sends >= STARTER_LIFETIME_SEND_LIMIT:
                return BillingReservation(False, "starter_trial_expired", None, usage_summary(user, account=account))
            lifetime_tokens = lifetime_sends * units
            if lifetime_tokens + units > STARTER_LIFETIME_TOKEN_LIMIT:
                return BillingReservation(False, "starter_trial_expired", None, usage_summary(user, account=account))
        else:
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

        sub = UserSubscription.objects.select_for_update().filter(user_id=event.user_id).first()
        if sub and sub.plan_code == PLAN_STARTER:
            UserSubscription.objects.filter(pk=sub.pk).update(
                starter_lifetime_sends=F("starter_lifetime_sends") + 1,
            )
            sub.refresh_from_db()
            _expire_starter_trial_if_needed(sub)


def fail_auto_send(reservation: BillingReservation | int | None, reason: str = "") -> None:
    event_id = reservation.event_id if isinstance(reservation, BillingReservation) else reservation
    if not event_id:
        return
    now = timezone.now()
    UsageEvent.objects.filter(pk=event_id, status=UsageEvent.STATUS_RESERVED).update(
        status=UsageEvent.STATUS_FAILED,
        meta_json={"failed_at": now.isoformat(), "reason": str(reason or "")[:500]},
    )


# --- Custom plan builder (user-configurable tokens + inboxes) ---

CUSTOM_BASE_FEE_CENTS = 1000
CUSTOM_PER_1000_TOKENS_CENTS = 500
CUSTOM_PER_INBOX_CENTS = 250
CUSTOM_MIN_TOKENS = 1000
CUSTOM_MAX_TOKENS = 20000
CUSTOM_MIN_INBOXES = 1
CUSTOM_MAX_INBOXES = 10
CUSTOM_MIN_PRICE_CENTS = 2000
CUSTOM_TOKENS_PER_SEND = 5
CUSTOM_QUOTE_TTL_HOURS = 48

CUSTOM_PRESETS: list[dict[str, Any]] = [
    {"id": "bundle_a", "label": "$30 bundle", "tokens": 2000, "inboxes": 4},
    {"id": "bundle_b", "label": "$40 bundle", "tokens": 3000, "inboxes": 5},
]


def custom_pricing_config(*, billing_interval: str = "monthly", currency: str = "usd") -> dict[str, Any]:
    from core.billing_interval import BILLING_YEARLY, interval_suffix, normalize_billing_interval
    from core.pricing_currency import (
        convert_usd_cents,
        currency_symbol,
        format_cents,
        normalize_currency,
    )

    interval = normalize_billing_interval(billing_interval)
    cur = normalize_currency(currency)
    sym = currency_symbol(cur)
    yearly_note = ""
    if interval == BILLING_YEARLY:
        yearly_note = " Yearly total = 10× monthly (2 months free)."
    base_fee = format_cents(convert_usd_cents(CUSTOM_BASE_FEE_CENTS, cur), cur)
    per_1k = format_cents(convert_usd_cents(CUSTOM_PER_1000_TOKENS_CENTS, cur), cur)
    per_inbox = format_cents(convert_usd_cents(CUSTOM_PER_INBOX_CENTS, cur), cur)
    min_price = format_cents(convert_usd_cents(CUSTOM_MIN_PRICE_CENTS, cur), cur)
    return {
        "billing_interval": interval,
        "pricing_currency": cur,
        "currency_symbol": sym,
        "interval_suffix": interval_suffix(interval),
        "base_fee_cents": convert_usd_cents(CUSTOM_BASE_FEE_CENTS, cur),
        "per_1000_tokens_cents": convert_usd_cents(CUSTOM_PER_1000_TOKENS_CENTS, cur),
        "per_inbox_cents": convert_usd_cents(CUSTOM_PER_INBOX_CENTS, cur),
        "min_tokens": CUSTOM_MIN_TOKENS,
        "max_tokens": CUSTOM_MAX_TOKENS,
        "min_inboxes": CUSTOM_MIN_INBOXES,
        "max_inboxes": CUSTOM_MAX_INBOXES,
        "min_price_cents": convert_usd_cents(CUSTOM_MIN_PRICE_CENTS, cur),
        "tokens_per_send": CUSTOM_TOKENS_PER_SEND,
        "presets": CUSTOM_PRESETS,
        "yearly_months_paid": 10,
        "formula_note": (
            f"Pricing: {base_fee} base + {per_1k} per 1,000 tokens + {per_inbox} per inbox. "
            f"Minimum {min_price}/mo. Draft mode does not use tokens.{yearly_note}"
        ),
    }


def clamp_custom_inputs(tokens: int, inboxes: int) -> tuple[int, int]:
    tok = max(CUSTOM_MIN_TOKENS, min(CUSTOM_MAX_TOKENS, int(tokens)))
    tok = int(round(tok / 100) * 100)
    if tok < CUSTOM_MIN_TOKENS:
        tok = CUSTOM_MIN_TOKENS
    boxes = max(CUSTOM_MIN_INBOXES, min(CUSTOM_MAX_INBOXES, int(inboxes)))
    return tok, boxes


def custom_daily_send_limit(inboxes: int) -> int:
    return max(20, min(int(inboxes) * 25, 200))


def calculate_custom_price_cents(tokens: int, inboxes: int) -> int:
    tok, boxes = clamp_custom_inputs(tokens, inboxes)
    token_units = max(1, tok // 1000)
    raw = CUSTOM_BASE_FEE_CENTS + (token_units * CUSTOM_PER_1000_TOKENS_CENTS) + (boxes * CUSTOM_PER_INBOX_CENTS)
    return max(CUSTOM_MIN_PRICE_CENTS, int(raw))


def custom_plan_quote_summary(
    tokens: int,
    inboxes: int,
    *,
    billing_interval: str = "monthly",
    currency: str = "usd",
) -> dict[str, Any]:
    from core.billing_interval import custom_cents_for_interval, interval_suffix, normalize_billing_interval
    from core.pricing_currency import convert_usd_cents, currency_symbol, normalize_currency

    tok, boxes = clamp_custom_inputs(tokens, inboxes)
    monthly_usd_cents = calculate_custom_price_cents(tok, boxes)
    interval = normalize_billing_interval(billing_interval)
    cur = normalize_currency(currency)
    monthly_cents = convert_usd_cents(monthly_usd_cents, cur)
    price_cents = custom_cents_for_interval(monthly_cents, interval)
    per_send = CUSTOM_TOKENS_PER_SEND
    sends_max = tok // per_send if per_send else 0
    return {
        "tokens": tok,
        "inboxes": boxes,
        "billing_interval": interval,
        "pricing_currency": cur,
        "currency_symbol": currency_symbol(cur),
        "price_cents": price_cents,
        "monthly_price_cents": monthly_cents,
        "price_usd": round(price_cents / 100, 2),
        "interval_suffix": interval_suffix(interval),
        "tokens_per_send": per_send,
        "sends_max": sends_max,
        "daily_send_limit": custom_daily_send_limit(boxes),
    }


def apply_custom_limits(sub: UserSubscription, *, tokens: int, inboxes: int) -> UserSubscription:
    tok, boxes = clamp_custom_inputs(tokens, inboxes)
    sub.plan_code = PLAN_CUSTOM
    sub.status = UserSubscription.STATUS_ACTIVE
    sub.monthly_token_limit = tok
    sub.active_inbox_limit = boxes
    sub.daily_send_limit = custom_daily_send_limit(boxes)
    sub.kb_source_limit = None
    sub.telegram_enabled = True
    sub.whatsapp_enabled = True
    sub.save()
    return sub


def activate_custom_plan_quote(user, quote) -> UserSubscription:
    """Apply a paid CustomPlanQuote to the user's subscription."""
    from core.models import CustomPlanQuote

    if not isinstance(quote, CustomPlanQuote):
        quote = CustomPlanQuote.objects.filter(pk=quote, user=user).first()
    if quote is None:
        raise ValueError("quote_not_found")
    sub = get_or_create_subscription(user)
    apply_custom_limits(sub, tokens=quote.tokens, inboxes=quote.inboxes)
    if not sub.paid_at:
        sub.paid_at = timezone.now()
    sub.save(update_fields=["paid_at", "updated_at"])
    quote.status = CustomPlanQuote.STATUS_PAID
    quote.paid_at = timezone.now()
    quote.save(update_fields=["status", "paid_at", "updated_at"])
    return sub

