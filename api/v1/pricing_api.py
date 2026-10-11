"""Public pricing feed — same admin-managed plans the website #pricing section renders."""

from __future__ import annotations

import logging

from django.urls import reverse
from django.utils.html import strip_tags
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from core.marketing import get_pricing_settings, marketing_pricing_plans_queryset
from core.pricing_currency import (
    CURRENCY_EUR,
    CURRENCY_GBP,
    CURRENCY_USD,
    currency_label,
    currency_symbol,
    get_pricing_currency,
    normalize_currency,
    plan_currency_variants,
)

logger = logging.getLogger("mailpilot.api.v1.pricing")

_CURRENCIES = (CURRENCY_USD, CURRENCY_GBP, CURRENCY_EUR)


class _OptionalJWTAuthentication(JWTAuthentication):
    """Attach the user when a valid token is sent; ignore bad/expired tokens on this public feed."""

    def authenticate(self, request):
        try:
            return super().authenticate(request)
        except Exception:
            return None


def _account_state(user) -> tuple[str, bool]:
    if not getattr(user, "is_authenticated", False):
        return "", False
    try:
        from core.billing import get_or_create_subscription, is_starter_expired

        sub = get_or_create_subscription(user)
        return sub.plan_code, bool(is_starter_expired(sub))
    except Exception:
        logger.exception("pricing feed subscription lookup failed user=%s", getattr(user, "pk", None))
        return "starter", False


def _cta(plan, request, *, authenticated: bool, starter_expired: bool) -> dict:
    """Mirror the website card buttons so the app can label and route them identically."""
    code = plan.plan_code
    if code == "starter":
        if not authenticated:
            label, action, path = plan.cta_label, "login", reverse("login")
        elif starter_expired:
            label = plan.cta_label_starter_expired or "Upgrade required"
            action, path = "upgrade", f"{reverse('home')}#pricing"
        else:
            label = plan.cta_label_authenticated or plan.cta_label
            action, path = "profile", reverse("profile")
    elif code == "pro":
        label = plan.cta_label
        if authenticated:
            action, path = "checkout_pro", reverse("billing_checkout_pro")
        else:
            action, path = "signup", reverse("signup")
    elif code == "custom":
        label, action, path = plan.cta_label, "custom_builder", reverse("custom_plan_builder")
    else:
        label, action, path = plan.cta_label, "signup", reverse("signup")
    return {
        "label": label,
        "style": plan.cta_style,
        "action": action,
        "url": request.build_absolute_uri(path),
    }


def _interval_block(variant: dict, prefix: str) -> dict:
    return {
        "price": variant[f"{prefix}_price"],
        "suffix": variant[f"{prefix}_suffix"],
        "was": variant[f"{prefix}_was"],
        "save_label": variant[f"{prefix}_save"],
        "period": variant[f"{prefix}_period"],
    }


def _plan_payload(plan, request, *, currency: str, authenticated: bool, starter_expired: bool, current_plan: str) -> dict:
    variants = plan_currency_variants(plan)
    lines = plan.feature_lines
    return {
        "code": plan.plan_code,
        "tier_label": plan.tier_label,
        "top_badge": plan.top_badge,
        "ribbon": {
            "type": plan.ribbon_type,
            "label": plan.ribbon_label,
            "icon_class": plan.ribbon_icon_class,
        }
        if plan.ribbon_type and plan.ribbon_label
        else None,
        "description": plan.description,
        "features": [strip_tags(line) for line in lines],
        "features_html": lines,
        "is_featured": plan.is_featured,
        "is_current": bool(current_plan) and current_plan == plan.plan_code,
        "sort_order": plan.sort_order,
        "monthly": _interval_block(variants[currency], "monthly"),
        "yearly": _interval_block(variants[currency], "yearly"),
        "currencies": {
            cur: {
                "monthly": _interval_block(variants[cur], "monthly"),
                "yearly": _interval_block(variants[cur], "yearly"),
            }
            for cur in _CURRENCIES
        },
        "cta": _cta(plan, request, authenticated=authenticated, starter_expired=starter_expired),
    }


@extend_schema(
    parameters=[
        OpenApiParameter("currency", OpenApiTypes.STR, description="usd, gbp, or eur. Defaults to the same geo rule as the website."),
        OpenApiParameter("interval", OpenApiTypes.STR, description="monthly or yearly — echoed back as `billing_interval`."),
    ],
    responses=OpenApiTypes.OBJECT,
)
@api_view(["GET"])
@authentication_classes([_OptionalJWTAuthentication])
@permission_classes([AllowAny])
def pricing(request):
    raw_currency = (request.query_params.get("currency") or "").strip()
    currency = normalize_currency(raw_currency) if raw_currency else get_pricing_currency(request)
    interval = "yearly" if (request.query_params.get("interval") or "").strip().lower() == "yearly" else "monthly"

    user = request.user
    authenticated = bool(getattr(user, "is_authenticated", False))
    current_plan, starter_expired = _account_state(user)

    settings_obj = get_pricing_settings()
    plans = list(marketing_pricing_plans_queryset(homepage_only=True))

    stamps = [settings_obj.updated_at] + [p.updated_at for p in plans]
    updated_at = max(s for s in stamps if s) if any(stamps) else None

    return Response(
        {
            "ok": True,
            "currency": currency,
            "currency_label": currency_label(currency),
            "currency_symbol": currency_symbol(currency),
            "available_currencies": [
                {"code": cur, "label": currency_label(cur), "symbol": currency_symbol(cur)} for cur in _CURRENCIES
            ],
            "billing_interval": interval,
            "header": {
                "tag": settings_obj.section_tag,
                "title_lead": settings_obj.title_lead,
                "title_highlight": settings_obj.title_highlight,
                "intro": settings_obj.intro,
            },
            "plans": [
                _plan_payload(
                    p,
                    request,
                    currency=currency,
                    authenticated=authenticated,
                    starter_expired=starter_expired,
                    current_plan=current_plan,
                )
                for p in plans
            ],
            "account": {
                "authenticated": authenticated,
                "current_plan": current_plan or None,
                "starter_expired": starter_expired,
            },
            "updated_at": updated_at.isoformat() if updated_at else None,
        }
    )
