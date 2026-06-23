from __future__ import annotations

import base64
import logging
import re
from typing import Any

from core.payment_gateway import PayPalCredentials, paypal_resolved_environment

logger = logging.getLogger(__name__)

_plan_cache: dict[str, str] = {}


def paypal_api_base() -> str:
    if paypal_resolved_environment() == "sandbox":
        return "https://api-m.sandbox.paypal.com"
    return "https://api-m.paypal.com"


def _cents_to_value(cents: int) -> str:
    return f"{int(cents) / 100:.2f}"


def _interval_frequency(interval: str) -> tuple[str, int]:
    if interval == "yearly":
        return "YEAR", 1
    return "MONTH", 1


def paypal_access_token(creds: PayPalCredentials) -> str:
    import requests

    auth = base64.b64encode(f"{creds.client_id}:{creds.client_secret}".encode()).decode()
    resp = requests.post(
        f"{paypal_api_base()}/v1/oauth2/token",
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"grant_type": "client_credentials"},
        timeout=20,
    )
    payload = resp.json() if resp.content else {}
    if not resp.ok:
        logger.warning("paypal oauth failed: %s", payload or resp.text)
        raise PayPalAPIError("oauth_failed", payload)
    token = str(payload.get("access_token") or "").strip()
    if not token:
        raise PayPalAPIError("oauth_empty", payload)
    return token


class PayPalAPIError(Exception):
    def __init__(self, code: str, payload: Any = None):
        super().__init__(code)
        self.code = code
        self.payload = payload


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def paypal_get_subscription(creds: PayPalCredentials, subscription_id: str) -> dict[str, Any]:
    import requests

    token = paypal_access_token(creds)
    resp = requests.get(
        f"{paypal_api_base()}/v1/billing/subscriptions/{subscription_id}",
        headers=_auth_headers(token),
        timeout=20,
    )
    payload = resp.json() if resp.content else {}
    if not resp.ok:
        logger.warning("paypal get subscription failed: %s", payload or resp.text)
        raise PayPalAPIError("subscription_fetch_failed", payload)
    return payload if isinstance(payload, dict) else {}


def _create_product(token: str, name: str, description: str) -> str:
    import requests

    resp = requests.post(
        f"{paypal_api_base()}/v1/catalogs/products",
        headers=_auth_headers(token),
        json={
            "name": name[:127],
            "description": description[:127],
            "type": "SERVICE",
            "category": "SOFTWARE",
        },
        timeout=20,
    )
    payload = resp.json() if resp.content else {}
    if not resp.ok:
        raise PayPalAPIError("product_create_failed", payload)
    product_id = str(payload.get("id") or "").strip()
    if not product_id:
        raise PayPalAPIError("product_missing_id", payload)
    return product_id


def paypal_ensure_billing_plan(
    creds: PayPalCredentials,
    *,
    name: str,
    description: str,
    amount_cents: int,
    currency: str,
    interval: str,
) -> str:
    currency_code = (currency or "usd").upper()
    cache_key = f"{paypal_api_base()}:{interval}:{currency_code}:{amount_cents}:{name}"
    cached = _plan_cache.get(cache_key)
    if cached:
        return cached

    token = paypal_access_token(creds)
    unit, count = _interval_frequency(interval)
    product_id = _create_product(token, name, description)

    import requests

    resp = requests.post(
        f"{paypal_api_base()}/v1/billing/plans",
        headers=_auth_headers(token),
        json={
            "product_id": product_id,
            "name": name[:127],
            "description": description[:127],
            "status": "ACTIVE",
            "billing_cycles": [
                {
                    "frequency": {"interval_unit": unit, "interval_count": count},
                    "tenure_type": "REGULAR",
                    "sequence": 1,
                    "total_cycles": 0,
                    "pricing_scheme": {
                        "fixed_price": {
                            "value": _cents_to_value(amount_cents),
                            "currency_code": currency_code,
                        }
                    },
                }
            ],
            "payment_preferences": {
                "auto_bill_outstanding": True,
                "setup_fee_failure_action": "CONTINUE",
                "payment_failure_threshold": 3,
            },
        },
        timeout=20,
    )
    payload = resp.json() if resp.content else {}
    if not resp.ok:
        logger.warning("paypal plan create failed: %s", payload or resp.text)
        raise PayPalAPIError("plan_create_failed", payload)
    plan_id = str(payload.get("id") or "").strip()
    if not plan_id:
        raise PayPalAPIError("plan_missing_id", payload)
    _plan_cache[cache_key] = plan_id
    return plan_id


def paypal_resolve_plan_id(
    creds: PayPalCredentials,
    *,
    name: str,
    description: str,
    amount_cents: int,
    currency: str,
    interval: str,
) -> str:
    preset = (creds.plan_pro_monthly or "").strip()
    if interval == "monthly" and (currency or "usd").lower() == "usd" and preset.startswith("P-"):
        return preset
    return paypal_ensure_billing_plan(
        creds,
        name=name,
        description=description,
        amount_cents=amount_cents,
        currency=currency,
        interval=interval,
    )


def paypal_build_custom_id(*, user_id: int, plan: str, interval: str = "", quote_id: int | None = None) -> str:
    parts = [f"uid={user_id}", f"plan={plan}"]
    if interval:
        parts.append(f"interval={interval}")
    if quote_id:
        parts.append(f"quote={quote_id}")
    return "mailpilot:" + ":".join(parts)


_CUSTOM_ID_RE = re.compile(
    r"mailpilot:uid=(?P<uid>\d+):plan=(?P<plan>\w+)(?::interval=(?P<interval>\w+))?(?::quote=(?P<quote>\d+))?"
)


def paypal_parse_custom_id(custom_id: str) -> dict[str, str]:
    m = _CUSTOM_ID_RE.match((custom_id or "").strip())
    if not m:
        return {}
    out = {"uid": m.group("uid"), "plan": m.group("plan")}
    if m.group("interval"):
        out["interval"] = m.group("interval")
    if m.group("quote"):
        out["quote"] = m.group("quote")
    return out


def paypal_create_subscription(
    creds: PayPalCredentials,
    *,
    plan_id: str,
    email: str,
    return_url: str,
    cancel_url: str,
    custom_id: str,
) -> dict[str, Any]:
    import requests

    token = paypal_access_token(creds)
    body: dict[str, Any] = {
        "plan_id": plan_id,
        "custom_id": custom_id[:127],
        "application_context": {
            "brand_name": "MailPilot",
            "locale": "en-US",
            "shipping_preference": "NO_SHIPPING",
            "user_action": "SUBSCRIBE_NOW",
            "payment_method": {
                "payer_selected": "PAYPAL",
                "payee_preferred": "IMMEDIATE_PAYMENT_REQUIRED",
            },
            "return_url": return_url,
            "cancel_url": cancel_url,
        },
    }
    email = (email or "").strip()
    if email:
        body["subscriber"] = {"email_address": email}

    resp = requests.post(
        f"{paypal_api_base()}/v1/billing/subscriptions",
        headers=_auth_headers(token),
        json=body,
        timeout=20,
    )
    payload = resp.json() if resp.content else {}
    if not resp.ok:
        logger.warning("paypal subscription create failed: %s", payload or resp.text)
        raise PayPalAPIError("subscription_create_failed", payload)
    return payload if isinstance(payload, dict) else {}


def paypal_approval_url(subscription_payload: dict[str, Any]) -> str:
    for link in subscription_payload.get("links") or []:
        if isinstance(link, dict) and link.get("rel") == "approve":
            return str(link.get("href") or "").strip()
    return ""


def paypal_subscription_is_paid(status: str) -> bool:
    return (status or "").upper() in ("ACTIVE", "APPROVED")
