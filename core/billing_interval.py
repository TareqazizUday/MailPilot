"""Billing interval (monthly vs yearly) for pricing display and checkout."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.http import HttpRequest

BILLING_MONTHLY = "monthly"
BILLING_YEARLY = "yearly"
_BILLING_INTERVALS = frozenset({BILLING_MONTHLY, BILLING_YEARLY})
_SESSION_KEY = "billing_interval"

# Pro fallback when admin plan row is missing.
PRO_MONTHLY_CENTS = 2000
PRO_YEARLY_CENTS = 20000

# Custom yearly = 10× monthly (2 months free), matching Pro $20/mo → $200/yr.
CUSTOM_YEARLY_MONTHS_PAID = 10

_USD_RE = re.compile(r"\$?\s*(\d+(?:\.\d{1,2})?)")


def normalize_billing_interval(raw: str | None) -> str:
    value = (raw or "").strip().lower()
    if value in _BILLING_INTERVALS:
        return value
    return BILLING_MONTHLY


def parse_usd_display_to_cents(value: str) -> int | None:
    match = _USD_RE.search((value or "").strip())
    if not match:
        return None
    amount = Decimal(match.group(1))
    return int((amount * 100).quantize(Decimal("1")))


def get_billing_interval(request: HttpRequest) -> str:
    """Pinned interval for this session (defaults to monthly)."""
    session_val = normalize_billing_interval(request.session.get(_SESSION_KEY))
    if request.session.get(_SESSION_KEY):
        return session_val
    query_val = normalize_billing_interval(request.GET.get("interval") or request.GET.get("billing_interval"))
    if query_val != BILLING_MONTHLY or request.GET.get("interval") or request.GET.get("billing_interval"):
        return query_val
    return BILLING_MONTHLY


def set_billing_interval(request: HttpRequest, interval: str) -> str:
    normalized = normalize_billing_interval(interval)
    request.session[_SESSION_KEY] = normalized
    return normalized


def interval_suffix(interval: str) -> str:
    return "/yr" if interval == BILLING_YEARLY else "/mo"


def interval_label(interval: str) -> str:
    return "Yearly" if interval == BILLING_YEARLY else "Monthly"


def custom_cents_for_interval(monthly_cents: int, interval: str) -> int:
    if interval == BILLING_YEARLY:
        return int(monthly_cents) * CUSTOM_YEARLY_MONTHS_PAID
    return int(monthly_cents)


def pro_checkout_cents(interval: str) -> int:
    from core.models import MarketingPricingPlan

    plan = MarketingPricingPlan.objects.filter(
        plan_code=MarketingPricingPlan.PLAN_PRO,
        is_published=True,
    ).first()
    if plan:
        if interval == BILLING_YEARLY:
            parsed = parse_usd_display_to_cents(plan.yearly_price_resolved)
            if parsed is not None:
                return parsed
        else:
            parsed = parse_usd_display_to_cents(plan.price_display)
            if parsed is not None:
                return parsed
    return PRO_YEARLY_CENTS if interval == BILLING_YEARLY else PRO_MONTHLY_CENTS


def stripe_recurring_interval(interval: str) -> str:
    return "year" if interval == BILLING_YEARLY else "month"


def checkout_url_with_interval(url: str, interval: str) -> str:
    if interval == BILLING_MONTHLY:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}interval={interval}"
