"""Geo-based pricing currency (USD / GBP / EUR) for display and Stripe checkout."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from core.billing_interval import parse_usd_display_to_cents

if TYPE_CHECKING:
    from django.http import HttpRequest

CURRENCY_USD = "usd"
CURRENCY_GBP = "gbp"
CURRENCY_EUR = "eur"
_CURRENCIES = frozenset({CURRENCY_USD, CURRENCY_GBP, CURRENCY_EUR})
_SESSION_KEY = "pricing_currency"

# UK → GBP; Eurozone → EUR; all others → USD.
_COUNTRY_GBP = frozenset({"GB"})
_EUROZONE = frozenset(
    {
        "AT",
        "BE",
        "CY",
        "EE",
        "FI",
        "FR",
        "DE",
        "GR",
        "IE",
        "IT",
        "LV",
        "LT",
        "LU",
        "MT",
        "NL",
        "PT",
        "SK",
        "SI",
        "ES",
        "HR",
    }
)

# Display + checkout conversion from USD base (e.g. Pro $20 → £16 / €18).
_GBP_FACTOR = Decimal("0.80")
_EUR_FACTOR = Decimal("0.90")

_CURRENCY_SYMBOL = {
    CURRENCY_USD: "$",
    CURRENCY_GBP: "£",
    CURRENCY_EUR: "€",
}

_CURRENCY_LABEL = {
    CURRENCY_USD: "USD",
    CURRENCY_GBP: "GBP",
    CURRENCY_EUR: "EUR",
}


def normalize_currency(raw: str | None) -> str:
    value = (raw or "").strip().lower()
    if value in _CURRENCIES:
        return value
    aliases = {
        "us": CURRENCY_USD,
        "usd": CURRENCY_USD,
        "$": CURRENCY_USD,
        "uk": CURRENCY_GBP,
        "gb": CURRENCY_GBP,
        "gbp": CURRENCY_GBP,
        "£": CURRENCY_GBP,
        "eu": CURRENCY_EUR,
        "eur": CURRENCY_EUR,
        "€": CURRENCY_EUR,
    }
    return aliases.get(value, CURRENCY_USD)


def currency_symbol(currency: str) -> str:
    return _CURRENCY_SYMBOL.get(normalize_currency(currency), "$")


def currency_label(currency: str) -> str:
    return _CURRENCY_LABEL.get(normalize_currency(currency), "USD")


def currency_from_country(country_code: str | None) -> str:
    code = (country_code or "").strip().upper()
    if code in _COUNTRY_GBP:
        return CURRENCY_GBP
    if code in _EUROZONE:
        return CURRENCY_EUR
    return CURRENCY_USD


def _country_from_request(request: HttpRequest) -> str:
    for header in ("HTTP_CF_IPCOUNTRY", "CF-IPCountry"):
        raw = (request.META.get(header) or "").strip().upper()
        if raw and raw != "XX":
            return raw
    return ""


def get_pricing_currency(request: HttpRequest) -> str:
    """Active currency for this request (session → query → geo → USD)."""
    session_val = request.session.get(_SESSION_KEY)
    if session_val:
        return normalize_currency(session_val)
    query_val = normalize_currency(request.GET.get("currency"))
    if query_val != CURRENCY_USD or request.GET.get("currency"):
        return query_val
    return currency_from_country(_country_from_request(request))


def set_pricing_currency(request: HttpRequest, currency: str) -> str:
    normalized = normalize_currency(currency)
    request.session[_SESSION_KEY] = normalized
    return normalized


def sync_pricing_currency_session(request: HttpRequest) -> str:
    """Pin currency from session, ?currency=, or geo on first marketing visit."""
    if request.session.get(_SESSION_KEY):
        return normalize_currency(request.session[_SESSION_KEY])
    raw_query = request.GET.get("currency")
    if raw_query:
        return set_pricing_currency(request, raw_query)
    detected = currency_from_country(_country_from_request(request))
    request.session[_SESSION_KEY] = detected
    return detected


def convert_usd_cents(usd_cents: int, currency: str) -> int:
    """Convert a USD-cent amount to the target currency's minor units."""
    cur = normalize_currency(currency)
    amount = int(usd_cents)
    if cur == CURRENCY_GBP:
        return int((Decimal(amount) * _GBP_FACTOR).quantize(Decimal("1")))
    if cur == CURRENCY_EUR:
        return int((Decimal(amount) * _EUR_FACTOR).quantize(Decimal("1")))
    return amount


def format_cents(cents: int, currency: str) -> str:
    """Format minor units with the correct symbol (no suffix)."""
    cur = normalize_currency(currency)
    symbol = currency_symbol(cur)
    value = int(cents) / 100
    if value == int(value):
        return f"{symbol}{int(value)}"
    return f"{symbol}{value:.2f}"


def convert_price_display(usd_display: str, currency: str) -> str:
    """Convert an admin USD price string (e.g. $20) for display."""
    cur = normalize_currency(currency)
    text = (usd_display or "").strip()
    if not text or cur == CURRENCY_USD:
        return text
    cents = parse_usd_display_to_cents(text)
    if cents is None:
        return text
    return format_cents(convert_usd_cents(cents, cur), cur)


def plan_currency_variants(plan) -> dict[str, dict[str, str]]:
    """All currency variants for a marketing pricing plan card."""
    monthly_price = plan.price_display
    monthly_suffix = plan.price_suffix or ""
    monthly_was = plan.price_was or ""
    monthly_save = plan.price_save_label or ""
    monthly_period = plan.period_text or ""

    yearly_price = plan.yearly_price_resolved
    yearly_suffix = plan.yearly_suffix_resolved or ""
    yearly_was = plan.yearly_was_resolved or ""
    yearly_save = plan.yearly_save_resolved or ""
    yearly_period = plan.yearly_period_resolved or ""

    variants: dict[str, dict[str, str]] = {}
    for cur in (CURRENCY_USD, CURRENCY_GBP, CURRENCY_EUR):
        variants[cur] = {
            "monthly_price": convert_price_display(monthly_price, cur),
            "monthly_suffix": monthly_suffix,
            "monthly_was": convert_price_display(monthly_was, cur) if monthly_was else "",
            "monthly_save": monthly_save,
            "monthly_period": monthly_period,
            "yearly_price": convert_price_display(yearly_price, cur),
            "yearly_suffix": yearly_suffix,
            "yearly_was": convert_price_display(yearly_was, cur) if yearly_was else "",
            "yearly_save": yearly_save,
            "yearly_period": yearly_period,
        }
    return variants


def enrich_pricing_plans(plans, *, currency: str) -> list[Any]:
    """Attach currency variant data and active display fields to plan instances."""
    cur = normalize_currency(currency)
    enriched: list[Any] = []
    for plan in plans:
        variants = plan_currency_variants(plan)
        active = variants[cur]
        plan.currency_variants = variants  # type: ignore[attr-defined]
        plan.price_display = active["monthly_price"]
        plan.price_suffix = active["monthly_suffix"]
        plan.price_was = active["monthly_was"]
        plan.price_save_label = active["monthly_save"]
        plan.period_text = active["monthly_period"]
        plan.display_yearly_price = active["yearly_price"]  # type: ignore[attr-defined]
        plan.display_yearly_suffix = active["yearly_suffix"]  # type: ignore[attr-defined]
        plan.display_yearly_was = active["yearly_was"]  # type: ignore[attr-defined]
        plan.display_yearly_save = active["yearly_save"]  # type: ignore[attr-defined]
        plan.display_yearly_period = active["yearly_period"]  # type: ignore[attr-defined]
        enriched.append(plan)
    return enriched


def pro_checkout_cents(interval: str, currency: str = CURRENCY_USD) -> int:
    from core.billing_interval import pro_checkout_cents as pro_usd_cents

    usd = pro_usd_cents(interval)
    return convert_usd_cents(usd, currency)


def stripe_currency_code(currency: str) -> str:
    return normalize_currency(currency)


def checkout_url_with_currency(url: str, currency: str) -> str:
    cur = normalize_currency(currency)
    if cur == CURRENCY_USD:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}currency={cur}"


def append_checkout_query_params(url: str, request: HttpRequest) -> str:
    from core.billing_interval import checkout_url_with_interval, get_billing_interval

    interval = get_billing_interval(request)
    currency = get_pricing_currency(request)
    url = checkout_url_with_interval(url, interval)
    return checkout_url_with_currency(url, currency)


def pricing_context(request: HttpRequest) -> dict[str, Any]:
    """Shared template context for marketing pricing pages."""
    currency = sync_pricing_currency_session(request)
    from core.billing_interval import get_billing_interval, set_billing_interval

    raw_interval = request.GET.get("interval") or request.GET.get("billing_interval")
    if raw_interval:
        set_billing_interval(request, raw_interval)
    interval = get_billing_interval(request)
    return {
        "pricing_currency": currency,
        "pricing_currency_label": currency_label(currency),
        "pricing_currency_symbol": currency_symbol(currency),
        "billing_interval": interval,
    }


def seo_price_currency(currency: str) -> str:
    return currency_label(currency)
