"""Record billing checkout / payment events for admin payment history."""
from __future__ import annotations

from django.http import HttpRequest

from core.models import BillingPaymentEvent


def client_ip(request: HttpRequest | None) -> str | None:
    if request is None:
        return None
    xff = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
    if xff:
        return xff[:45]
    raw = (request.META.get("REMOTE_ADDR") or "").strip()
    return raw[:45] if raw else None


def client_user_agent(request: HttpRequest | None) -> str:
    if request is None:
        return ""
    return (request.META.get("HTTP_USER_AGENT") or "").strip()[:255]


def log_billing_payment(
    *,
    user=None,
    request: HttpRequest | None = None,
    event_type: str,
    provider: str = "",
    plan_code: str = "",
    amount_cents: int | None = None,
    currency: str = "",
    status: str = BillingPaymentEvent.STATUS_PENDING,
    external_id: str = "",
    detail: str = "",
) -> None:
    try:
        BillingPaymentEvent.objects.create(
            user=user,
            event_type=event_type,
            provider=(provider or "").strip()[:16],
            plan_code=(plan_code or "").strip()[:24],
            amount_cents=amount_cents,
            currency=(currency or "").strip()[:3].lower(),
            status=status,
            external_id=(external_id or "").strip()[:255],
            ip_address=client_ip(request),
            user_agent=client_user_agent(request),
            detail=(detail or "").strip()[:512],
        )
    except Exception:
        pass
