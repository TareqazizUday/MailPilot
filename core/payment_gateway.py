from __future__ import annotations

import os
from dataclasses import dataclass, replace

from core.crypto import decrypt_str


@dataclass(frozen=True)
class StripeCredentials:
    secret_key: str
    webhook_secret: str
    price_pro_monthly: str
    price_pro_yearly: str
    publishable_key: str
    source: str


@dataclass(frozen=True)
class PayPalCredentials:
    client_id: str
    client_secret: str
    plan_pro_monthly: str
    webhook_id: str
    sandbox_mode: bool
    source: str


def _env_bool(name: str, *, default: bool = False) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes")


def _mask_secret(value: str, *, prefix_len: int = 7, suffix_len: int = 4) -> str:
    raw = (value or "").strip()
    if not raw:
        return "—"
    if len(raw) <= prefix_len + suffix_len + 3:
        return "••••••••"
    return f"{raw[:prefix_len]}…{raw[-suffix_len:]}"


def stripe_resolved_environment() -> str:
    """Return 'test' or 'live' from STRIPE_KEY_ENVIRONMENT + DEBUG."""
    from django.conf import settings

    choice = (os.environ.get("STRIPE_KEY_ENVIRONMENT") or "auto").strip().lower()
    if choice == "test":
        return "test"
    if choice == "live":
        return "live"
    if settings.DEBUG:
        if _stripe_test_secret_raw():
            return "test"
        if _stripe_live_secret_raw():
            return "live"
        return "test"
    return "live"


def stripe_environment_label() -> str:
    return "Test" if stripe_resolved_environment() == "test" else "Live"


def _stripe_test_secret_raw() -> str:
    key = (os.environ.get("STRIPE_TEST_SECRET_KEY") or "").strip()
    if key:
        return key
    fallback = (os.environ.get("STRIPE_SECRET_KEY") or "").strip()
    return fallback if fallback.startswith("sk_test_") else ""


def _stripe_live_secret_raw() -> str:
    key = (os.environ.get("STRIPE_LIVE_SECRET_KEY") or "").strip()
    if key:
        return key
    fallback = (os.environ.get("STRIPE_SECRET_KEY") or "").strip()
    return fallback if fallback.startswith("sk_live_") else ""


def _stripe_secret_from_env(env: str) -> str:
    if env == "test":
        return _stripe_test_secret_raw()
    return _stripe_live_secret_raw()


def _stripe_publishable_from_env(env: str) -> str:
    if env == "test":
        return (
            (os.environ.get("STRIPE_TEST_PUBLISHABLE_KEY") or "").strip()
            or (os.environ.get("STRIPE_PUBLISHABLE_KEY") or "").strip()
        )
    return (
        (os.environ.get("STRIPE_LIVE_PUBLISHABLE_KEY") or "").strip()
        or (os.environ.get("STRIPE_PUBLISHABLE_KEY") or "").strip()
    )


def _from_env() -> StripeCredentials | None:
    env = stripe_resolved_environment()
    secret_key = _stripe_secret_from_env(env)
    if not secret_key:
        return None
    return StripeCredentials(
        secret_key=secret_key,
        webhook_secret=(os.environ.get("STRIPE_WEBHOOK_SECRET") or "").strip(),
        price_pro_monthly=(os.environ.get("STRIPE_PRICE_PRO_MONTHLY") or "").strip(),
        price_pro_yearly=(os.environ.get("STRIPE_PRICE_PRO_YEARLY") or "").strip(),
        publishable_key=_stripe_publishable_from_env(env),
        source="env",
    )


def get_stripe_credentials() -> StripeCredentials | None:
    creds = _from_env()
    if not creds:
        return None
    if not (creds.webhook_secret or "").strip():
        env_wh = (os.environ.get("STRIPE_WEBHOOK_SECRET") or "").strip()
        if env_wh:
            creds = replace(creds, webhook_secret=env_wh)
    return creds


# Reference values for simulated checkout — not real Stripe keys.
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


def _stripe_env_secrets() -> list[str]:
    keys = []
    for name in ("STRIPE_TEST_SECRET_KEY", "STRIPE_LIVE_SECRET_KEY", "STRIPE_SECRET_KEY"):
        value = (os.environ.get(name) or "").strip()
        if value:
            keys.append(value)
    return keys


def stripe_is_configured() -> bool:
    for secret in _stripe_env_secrets():
        if secret and not is_demo_stripe_credentials(secret_key=secret):
            return True
    return False


def stripe_secret_key_mode(secret_key: str = "") -> str:
    key = (secret_key or "").strip()
    if key.startswith("sk_live_"):
        return "live"
    if key.startswith("sk_test_"):
        return "test"
    return ""


def stripe_live_charges_enabled() -> bool | None:
    creds = get_stripe_credentials()
    if not creds or not creds.secret_key.strip().startswith("sk_live_"):
        return None
    if _credentials_are_demo(creds):
        return None
    try:
        import requests

        resp = requests.get(
            "https://api.stripe.com/v1/account",
            auth=(creds.secret_key, ""),
            timeout=15,
        )
        if resp.ok:
            return bool(resp.json().get("charges_enabled"))
    except Exception:
        pass
    return None


def stripe_checkout_ready() -> bool:
    creds = get_stripe_credentials()
    if not creds or not creds.secret_key:
        return False
    if _credentials_are_demo(creds):
        return False
    from django.conf import settings

    if not settings.DEBUG and stripe_secret_key_mode(creds.secret_key) == "live":
        charges = stripe_live_charges_enabled()
        if charges is False:
            return False
    return True


def stripe_checkout_block_reason() -> str | None:
    creds = get_stripe_credentials()
    if not creds or not creds.secret_key or _credentials_are_demo(creds):
        if not _stripe_test_secret_raw() and not _stripe_live_secret_raw():
            return "Stripe secret key missing. Set STRIPE_TEST_SECRET_KEY or STRIPE_LIVE_SECRET_KEY in .env."
        return None
    if stripe_secret_key_mode(creds.secret_key) == "test":
        return None
    from django.conf import settings

    if settings.DEBUG:
        return None
    charges = stripe_live_charges_enabled()
    if charges is False:
        return (
            "Your Stripe live account cannot accept card payments yet "
            "(card_payments capability is inactive). "
            "Complete activation in the Stripe Dashboard."
        )
    return None


def billing_demo_mode() -> bool:
    from django.conf import settings

    return bool(getattr(settings, "BILLING_DEMO_MODE", False))


def billing_use_local_checkout() -> bool:
    """Show the in-app payment form (localhost) instead of Stripe/PayPal redirect."""
    from django.conf import settings

    if _env_bool("BILLING_LIVE_CHECKOUT"):
        return False
    if settings.DEBUG:
        return True
    return billing_demo_mode()


PAYMENT_STRIPE = "stripe"
PAYMENT_PAYPAL = "paypal"
PAYMENT_PROVIDER_CHOICES = (
    (PAYMENT_STRIPE, "Stripe"),
    (PAYMENT_PAYPAL, "PayPal"),
)


def paypal_supports_live_checkout() -> bool:
    return True


def paypal_resolved_environment() -> str:
    """Return 'sandbox' or 'live' from PAYPAL_ENVIRONMENT + DEBUG."""
    from django.conf import settings

    choice = (os.environ.get("PAYPAL_ENVIRONMENT") or "auto").strip().lower()
    if choice == "sandbox":
        return "sandbox"
    if choice == "live":
        return "live"
    if choice == "auto":
        return "sandbox" if settings.DEBUG else "live"
    if _env_bool("PAYPAL_SANDBOX", default=True):
        return "sandbox"
    return "live"


def paypal_environment_label() -> str:
    return "Sandbox" if paypal_resolved_environment() == "sandbox" else "Live"


def _paypal_client_id_for_env(env: str) -> str:
    if env == "sandbox":
        return (
            (os.environ.get("PAYPAL_SANDBOX_CLIENT_ID") or "").strip()
            or (os.environ.get("PAYPAL_CLIENT_ID") or "").strip()
        )
    return (
        (os.environ.get("PAYPAL_LIVE_CLIENT_ID") or "").strip()
        or (os.environ.get("PAYPAL_CLIENT_ID") or "").strip()
    )


def _paypal_secret_for_env(env: str) -> str:
    if env == "sandbox":
        return (
            (os.environ.get("PAYPAL_SANDBOX_CLIENT_SECRET") or "").strip()
            or (os.environ.get("PAYPAL_CLIENT_SECRET") or "").strip()
        )
    return (
        (os.environ.get("PAYPAL_LIVE_CLIENT_SECRET") or "").strip()
        or (os.environ.get("PAYPAL_CLIENT_SECRET") or "").strip()
    )


def _paypal_from_env() -> PayPalCredentials | None:
    env = paypal_resolved_environment()
    client_id = _paypal_client_id_for_env(env)
    client_secret = _paypal_secret_for_env(env)
    if not client_secret or not client_id:
        return None
    return PayPalCredentials(
        client_id=client_id,
        client_secret=client_secret,
        plan_pro_monthly=(os.environ.get("PAYPAL_PLAN_PRO_MONTHLY") or "").strip(),
        webhook_id=(os.environ.get("PAYPAL_WEBHOOK_ID") or "").strip(),
        sandbox_mode=env == "sandbox",
        source="env",
    )


def get_paypal_credentials() -> PayPalCredentials | None:
    return _paypal_from_env()


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


def _paypal_env_credential_pairs() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for env in ("sandbox", "live"):
        cid = _paypal_client_id_for_env(env)
        secret = _paypal_secret_for_env(env)
        if cid and secret:
            pairs.append((cid, secret))
    return pairs


def paypal_is_configured() -> bool:
    for cid, secret in _paypal_env_credential_pairs():
        if not is_demo_paypal_credentials(client_id=cid, client_secret=secret):
            return True
    return False


def paypal_available_at_checkout() -> bool:
    if paypal_checkout_ready():
        return True
    return billing_demo_mode()


def billing_site_url_missing() -> bool:
    from django.conf import settings

    if settings.DEBUG:
        return False
    return not (getattr(settings, "SITE_URL", "") or "").strip()


def available_payment_providers() -> list[str]:
    providers: list[str] = []
    local = billing_use_local_checkout()
    if stripe_checkout_ready() or local:
        providers.append(PAYMENT_STRIPE)
    if paypal_checkout_ready() or local:
        providers.append(PAYMENT_PAYPAL)
    elif billing_demo_mode():
        providers.append(PAYMENT_PAYPAL)
    if providers:
        return providers
    if billing_demo_mode():
        return [PAYMENT_STRIPE, PAYMENT_PAYPAL]
    return []


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


def paypal_checkout_ready() -> bool:
    creds = get_paypal_credentials()
    if not creds or not creds.client_secret or not creds.client_id:
        return False
    return not _paypal_credentials_are_demo(creds)


def masked_stripe_secret(enc: str) -> str:
    return _mask_secret(decrypt_str(enc))


def masked_stripe_restricted(enc: str) -> str:
    return _mask_secret(decrypt_str(enc))


def masked_stripe_webhook(enc: str) -> str:
    return _mask_secret(decrypt_str(enc))


def masked_paypal_secret(enc: str) -> str:
    return _mask_secret(decrypt_str(enc))
