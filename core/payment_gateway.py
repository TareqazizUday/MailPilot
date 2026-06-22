from __future__ import annotations

import os
from dataclasses import dataclass

from core.crypto import decrypt_str


@dataclass(frozen=True)
class StripeCredentials:
    secret_key: str
    webhook_secret: str
    price_pro_monthly: str
    price_pro_yearly: str
    publishable_key: str
    source: str


def _mask_secret(value: str, *, prefix_len: int = 7, suffix_len: int = 4) -> str:
    raw = (value or "").strip()
    if not raw:
        return "—"
    if len(raw) <= prefix_len + suffix_len + 3:
        return "••••••••"
    return f"{raw[:prefix_len]}…{raw[-suffix_len:]}"


def _from_db() -> StripeCredentials | None:
    from core.models import Stripe

    row = Stripe.objects.filter(singleton_key=1).first()
    if not row or not row.is_enabled:
        return None
    secret_key = decrypt_str(row.stripe_secret_key_enc).strip()
    if not secret_key:
        return None
    return StripeCredentials(
        secret_key=secret_key,
        webhook_secret=decrypt_str(row.stripe_webhook_secret_enc).strip(),
        price_pro_monthly=(row.stripe_price_pro_monthly or "").strip(),
        price_pro_yearly=(row.stripe_price_pro_yearly or "").strip(),
        publishable_key=(row.stripe_publishable_key or "").strip(),
        source="db",
    )


def _from_env() -> StripeCredentials | None:
    secret_key = (os.environ.get("STRIPE_SECRET_KEY") or "").strip()
    if not secret_key:
        return None
    return StripeCredentials(
        secret_key=secret_key,
        webhook_secret=(os.environ.get("STRIPE_WEBHOOK_SECRET") or "").strip(),
        price_pro_monthly=(os.environ.get("STRIPE_PRICE_PRO_MONTHLY") or "").strip(),
        price_pro_yearly=(os.environ.get("STRIPE_PRICE_PRO_YEARLY") or "").strip(),
        publishable_key=(os.environ.get("STRIPE_PUBLISHABLE_KEY") or "").strip(),
        source="env",
    )


def get_stripe_credentials() -> StripeCredentials | None:
    return _from_db() or _from_env()


# Reference values for local admin — save these, then replace with real Stripe Dashboard keys.
DEMO_STRIPE_REFERENCE: dict[str, str] = {
    "publishable_key": "pk_test_51DemoMailPilotPublishableKeyFromStripeDashboard",
    "secret_key": "sk_test_51DemoMailPilotSecretKeyFromStripeDashboard",
    "price_pro_monthly": "price_1DemoMailPilotPro20Monthly",
    "webhook_secret": "whsec_from_stripe_listen_or_dashboard_webhook",
    "test_card": "4242 4242 4242 4242",
    "test_expiry": "12/34",
    "test_cvc": "123",
}

_DEMO_STRIPE_MARKERS = ("DemoMailPilot", "from_stripe_listen_or_dashboard")


def is_demo_stripe_credentials(
    *,
    secret_key: str = "",
    price_pro_monthly: str = "",
    publishable_key: str = "",
    webhook_secret: str = "",
) -> bool:
    """True when saved values are MailPilot demo placeholders (not real Stripe keys)."""
    ref = DEMO_STRIPE_REFERENCE
    parts = (secret_key, price_pro_monthly, publishable_key, webhook_secret)
    if any(p == ref[k] for p, k in zip(parts, ("secret_key", "price_pro_monthly", "publishable_key", "webhook_secret"))):
        return True
    blob = " ".join(parts)
    return any(marker in blob for marker in _DEMO_STRIPE_MARKERS)


def _credentials_are_demo(creds: StripeCredentials | None) -> bool:
    if not creds:
        return False
    return is_demo_stripe_credentials(
        secret_key=creds.secret_key,
        price_pro_monthly=creds.price_pro_monthly,
        publishable_key=creds.publishable_key,
        webhook_secret=creds.webhook_secret,
    )


def demo_stripe_defaults() -> dict[str, str]:
    return dict(DEMO_STRIPE_REFERENCE)


def stripe_is_configured() -> bool:
    creds = get_stripe_credentials()
    return bool(creds and creds.secret_key and not _credentials_are_demo(creds))


def stripe_checkout_ready() -> bool:
    creds = get_stripe_credentials()
    if not creds or not creds.secret_key or not creds.price_pro_monthly:
        return False
    return not _credentials_are_demo(creds)


def billing_demo_mode() -> bool:
    from django.conf import settings

    return bool(getattr(settings, "BILLING_DEMO_MODE", False))


PAYMENT_STRIPE = "stripe"
PAYMENT_PAYPAL = "paypal"
PAYMENT_PROVIDER_CHOICES = (
    (PAYMENT_STRIPE, "Stripe"),
    (PAYMENT_PAYPAL, "PayPal"),
)


def available_payment_providers() -> list[str]:
    """Providers the user may choose at checkout."""
    if billing_demo_mode():
        return [PAYMENT_STRIPE, PAYMENT_PAYPAL]
    providers: list[str] = []
    if stripe_checkout_ready():
        providers.append(PAYMENT_STRIPE)
    if paypal_checkout_ready():
        providers.append(PAYMENT_PAYPAL)
    return providers


def payment_choice_required() -> bool:
    return len(available_payment_providers()) > 1


def pro_checkout_available() -> bool:
    return bool(available_payment_providers())


def custom_checkout_available() -> bool:
    return bool(available_payment_providers())


def provider_label(provider: str) -> str:
    if provider == PAYMENT_PAYPAL:
        return "PayPal"
    return "Stripe"


def masked_stripe_secret(enc: str) -> str:
    return _mask_secret(decrypt_str(enc))


def masked_stripe_webhook(enc: str) -> str:
    return _mask_secret(decrypt_str(enc))


@dataclass(frozen=True)
class PayPalCredentials:
    client_id: str
    client_secret: str
    plan_pro_monthly: str
    webhook_id: str
    sandbox_mode: bool
    source: str


def _paypal_from_db() -> PayPalCredentials | None:
    from core.models import PayPal

    row = PayPal.objects.filter(singleton_key=1).first()
    if not row or not row.is_enabled:
        return None
    client_secret = decrypt_str(row.client_secret_enc).strip()
    if not client_secret:
        return None
    return PayPalCredentials(
        client_id=(row.client_id or "").strip(),
        client_secret=client_secret,
        plan_pro_monthly=(row.plan_pro_monthly or "").strip(),
        webhook_id=(row.webhook_id or "").strip(),
        sandbox_mode=bool(row.sandbox_mode),
        source="db",
    )


def _paypal_from_env() -> PayPalCredentials | None:
    client_secret = (os.environ.get("PAYPAL_CLIENT_SECRET") or "").strip()
    if not client_secret:
        return None
    sandbox_raw = (os.environ.get("PAYPAL_SANDBOX") or "true").strip().lower()
    return PayPalCredentials(
        client_id=(os.environ.get("PAYPAL_CLIENT_ID") or "").strip(),
        client_secret=client_secret,
        plan_pro_monthly=(os.environ.get("PAYPAL_PLAN_PRO_MONTHLY") or "").strip(),
        webhook_id=(os.environ.get("PAYPAL_WEBHOOK_ID") or "").strip(),
        sandbox_mode=sandbox_raw in ("1", "true", "yes"),
        source="env",
    )


def get_paypal_credentials() -> PayPalCredentials | None:
    return _paypal_from_db() or _paypal_from_env()


DEMO_PAYPAL_REFERENCE: dict[str, str] = {
    "client_id": "DemoMailPilotPayPalClientIdFromDeveloperDashboard",
    "client_secret": "DemoMailPilotPayPalClientSecretFromDeveloperDashboard",
    "plan_pro_monthly": "P-DemoMailPilotPro20Monthly",
    "webhook_id": "WH-DemoMailPilotWebhookFromPayPalDashboard",
}

_DEMO_PAYPAL_MARKERS = ("DemoMailPilot", "FromPayPalDashboard", "FromDeveloperDashboard")


def is_demo_paypal_credentials(
    *,
    client_id: str = "",
    client_secret: str = "",
    plan_pro_monthly: str = "",
    webhook_id: str = "",
) -> bool:
    """True when saved values are MailPilot demo placeholders (not real PayPal keys)."""
    ref = DEMO_PAYPAL_REFERENCE
    parts = (client_id, client_secret, plan_pro_monthly, webhook_id)
    if any(p == ref[k] for p, k in zip(parts, ("client_id", "client_secret", "plan_pro_monthly", "webhook_id"))):
        return True
    blob = " ".join(parts)
    return any(marker in blob for marker in _DEMO_PAYPAL_MARKERS)


def _paypal_credentials_are_demo(creds: PayPalCredentials | None) -> bool:
    if not creds:
        return False
    return is_demo_paypal_credentials(
        client_id=creds.client_id,
        client_secret=creds.client_secret,
        plan_pro_monthly=creds.plan_pro_monthly,
        webhook_id=creds.webhook_id,
    )


def demo_paypal_defaults() -> dict[str, str]:
    return dict(DEMO_PAYPAL_REFERENCE)


def paypal_is_configured() -> bool:
    creds = get_paypal_credentials()
    return bool(creds and creds.client_secret and not _paypal_credentials_are_demo(creds))


def paypal_checkout_ready() -> bool:
    creds = get_paypal_credentials()
    if not creds or not creds.client_secret or not creds.client_id or not creds.plan_pro_monthly:
        return False
    return not _paypal_credentials_are_demo(creds)


def masked_paypal_secret(enc: str) -> str:
    return _mask_secret(decrypt_str(enc))
