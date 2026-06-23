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


def _mask_secret(value: str, *, prefix_len: int = 7, suffix_len: int = 4) -> str:
    raw = (value or "").strip()
    if not raw:
        return "—"
    if len(raw) <= prefix_len + suffix_len + 3:
        return "••••••••"
    return f"{raw[:prefix_len]}…{raw[-suffix_len:]}"


def _stripe_row():
    from core.models import Stripe

    return Stripe.objects.filter(singleton_key=1).first()


def stripe_resolved_environment() -> str:
    """Return 'test' or 'live' for the active Stripe key set."""
    from django.conf import settings

    from core.models import Stripe

    row = _stripe_row()
    choice = (row.stripe_key_environment if row else Stripe.STRIPE_KEY_AUTO) or Stripe.STRIPE_KEY_AUTO
    if choice == Stripe.STRIPE_KEY_TEST:
        return "test"
    if choice == Stripe.STRIPE_KEY_LIVE:
        return "live"
    return "test" if settings.DEBUG else "live"


def stripe_environment_label() -> str:
    env = stripe_resolved_environment()
    return "Test" if env == "test" else "Live"


def _stripe_secret_enc_for_env(row, env: str) -> str:
    if env == "test":
        return (row.stripe_test_secret_key_enc or "").strip()
    return (row.stripe_secret_key_enc or "").strip()


def _stripe_restricted_enc_for_env(row, env: str) -> str:
    if env == "test":
        return (row.stripe_test_restricted_key_enc or "").strip()
    return (row.stripe_restricted_key_enc or "").strip()


def _from_db() -> StripeCredentials | None:
    from core.models import Stripe

    row = _stripe_row()
    if not row or not row.is_enabled:
        return None
    env = stripe_resolved_environment()
    secret_key = decrypt_str(_stripe_secret_enc_for_env(row, env)).strip()
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
    creds = _from_db() or _from_env()
    if not creds:
        return None
    if not (creds.webhook_secret or "").strip():
        env_wh = (os.environ.get("STRIPE_WEBHOOK_SECRET") or "").strip()
        if env_wh:
            creds = replace(creds, webhook_secret=env_wh)
    return creds


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
    row = _stripe_row()
    if not row or not row.is_enabled:
        creds = get_stripe_credentials()
        return bool(creds and creds.secret_key and not _credentials_are_demo(creds))
    # "Configured" means we have at least one real Stripe secret key saved.
    # This keeps Stripe visible as a provider even if the currently active
    # environment key is missing (e.g. local DEBUG expects test key, but only
    # live key is saved yet).
    active_env = stripe_resolved_environment()
    candidates = [
        decrypt_str(_stripe_secret_enc_for_env(row, active_env)).strip(),
        decrypt_str(row.stripe_test_secret_key_enc).strip(),
        decrypt_str(row.stripe_secret_key_enc).strip(),
    ]
    for secret in candidates:
        if secret and not is_demo_stripe_credentials(secret_key=secret):
            return True
    return False


def stripe_secret_key_mode(secret_key: str = "") -> str:
    """Return 'test', 'live', or '' for a Stripe secret key prefix."""
    key = (secret_key or "").strip()
    if key.startswith("sk_live_"):
        return "live"
    if key.startswith("sk_test_"):
        return "test"
    return ""


def stripe_live_charges_enabled() -> bool | None:
    """For sk_live_ keys: True/False from Stripe account. None for test keys or API errors."""
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
    """True when a real secret key is configured (Checkout uses price_data if no Price ID)."""
    creds = get_stripe_credentials()
    if not creds or not creds.secret_key:
        return False
    if _credentials_are_demo(creds):
        return False
    charges = stripe_live_charges_enabled()
    if charges is False:
        return False
    return True


def stripe_checkout_block_reason() -> str | None:
    """Human-readable reason Stripe checkout is unavailable, if any."""
    creds = get_stripe_credentials()
    if not creds or not creds.secret_key or _credentials_are_demo(creds):
        return None
    if stripe_secret_key_mode(creds.secret_key) == "test":
        return None
    charges = stripe_live_charges_enabled()
    if charges is False:
        from django.conf import settings

        base = (
            "Your Stripe live account cannot accept card payments yet "
            "(card_payments capability is inactive). "
            "Complete activation in the Stripe Dashboard."
        )
        if settings.DEBUG or stripe_resolved_environment() == "test":
            return (
                f"{base} Save test keys below and set Key environment to Auto or Force test."
            )
        return base
    return None


def stripe_keys_status_for_env(env: str) -> dict[str, str]:
    """Masked preview + readiness hints for admin (test or live)."""
    row = _stripe_row()
    if not row:
        return {"secret": "—", "restricted": "—", "ready": "missing"}
    secret_enc = _stripe_secret_enc_for_env(row, env)
    restricted_enc = _stripe_restricted_enc_for_env(row, env)
    secret = masked_stripe_secret(secret_enc)
    restricted = masked_stripe_restricted(restricted_enc)
    if secret == "—":
        return {"secret": secret, "restricted": restricted, "ready": "missing"}
    raw = decrypt_str(secret_enc).strip()
    if is_demo_stripe_credentials(secret_key=raw):
        return {"secret": secret, "restricted": restricted, "ready": "demo"}
    mode = stripe_secret_key_mode(raw)
    if mode == "live":
        charges = None
        if raw:
            try:
                import requests

                resp = requests.get(
                    "https://api.stripe.com/v1/account",
                    auth=(raw, ""),
                    timeout=10,
                )
                if resp.ok:
                    charges = bool(resp.json().get("charges_enabled"))
            except Exception:
                pass
        if charges is False:
            return {"secret": secret, "restricted": restricted, "ready": "live_blocked"}
        if charges is True:
            return {"secret": secret, "restricted": restricted, "ready": "ok"}
        return {"secret": secret, "restricted": restricted, "ready": "saved"}
    return {"secret": secret, "restricted": restricted, "ready": "ok"}


def billing_demo_mode() -> bool:
    from django.conf import settings

    return bool(getattr(settings, "BILLING_DEMO_MODE", False))


PAYMENT_STRIPE = "stripe"
PAYMENT_PAYPAL = "paypal"
PAYMENT_PROVIDER_CHOICES = (
    (PAYMENT_STRIPE, "Stripe"),
    (PAYMENT_PAYPAL, "PayPal"),
)


def paypal_supports_live_checkout() -> bool:
    """True when PayPal REST checkout (not simulated UI) is implemented."""
    return True


def paypal_available_at_checkout() -> bool:
    """PayPal may appear on the payment picker and complete checkout."""
    if paypal_checkout_ready():
        return True
    return billing_demo_mode()


def billing_site_url_missing() -> bool:
    """Production needs SITE_URL for Stripe success/cancel URLs behind a proxy."""
    from django.conf import settings

    if settings.DEBUG:
        return False
    return not (getattr(settings, "SITE_URL", "") or "").strip()


def billing_choose_payment_is_demo() -> bool:
    """True when the payment picker only offers simulated checkout (no live gateway)."""
    if stripe_checkout_ready():
        return False
    if paypal_supports_live_checkout() and paypal_checkout_ready():
        return False
    return billing_demo_mode()


def available_payment_providers() -> list[str]:
    """Providers the user may choose at checkout."""
    providers: list[str] = []
    if stripe_checkout_ready() or stripe_is_configured():
        providers.append(PAYMENT_STRIPE)
    if paypal_checkout_ready() or paypal_is_configured():
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


def masked_stripe_secret(enc: str) -> str:
    return _mask_secret(decrypt_str(enc))


def masked_stripe_restricted(enc: str) -> str:
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


def _paypal_row():
    from core.models import PayPal

    return PayPal.objects.filter(singleton_key=1).first()


def paypal_resolved_environment() -> str:
    """Return 'sandbox' or 'live' for the active PayPal API."""
    from django.conf import settings

    from core.models import PayPal

    row = _paypal_row()
    choice = (row.paypal_environment if row else PayPal.PAYPAL_ENV_AUTO) or PayPal.PAYPAL_ENV_AUTO
    if choice == PayPal.PAYPAL_ENV_SANDBOX:
        return "sandbox"
    if choice == PayPal.PAYPAL_ENV_LIVE:
        return "live"
    if choice == PayPal.PAYPAL_ENV_AUTO:
        return "sandbox" if settings.DEBUG else "live"
    return "sandbox" if row and row.sandbox_mode else "live"


def paypal_environment_label() -> str:
    env = paypal_resolved_environment()
    return "Sandbox" if env == "sandbox" else "Live"


def _paypal_client_id_for_env(row, env: str) -> str:
    if env == "sandbox":
        return ((row.sandbox_client_id if row else "") or (row.client_id if row else "") or "").strip()
    return ((row.live_client_id if row else "") or "").strip()


def _paypal_secret_enc_for_env(row, env: str) -> str:
    if env == "sandbox":
        enc = (row.sandbox_client_secret_enc if row else "") or (row.client_secret_enc if row else "")
        return (enc or "").strip()
    return ((row.live_client_secret_enc if row else "") or "").strip()


def _paypal_from_db() -> PayPalCredentials | None:
    from core.models import PayPal

    row = _paypal_row()
    if not row or not row.is_enabled:
        return None
    env = paypal_resolved_environment()
    client_id = _paypal_client_id_for_env(row, env)
    secret_enc = _paypal_secret_enc_for_env(row, env)
    client_secret = decrypt_str(secret_enc).strip()
    if not client_secret or not client_id:
        return None
    return PayPalCredentials(
        client_id=client_id,
        client_secret=client_secret,
        plan_pro_monthly=(row.plan_pro_monthly or "").strip(),
        webhook_id=(row.webhook_id or "").strip(),
        sandbox_mode=env == "sandbox",
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
    row = _paypal_row()
    if not row or not row.is_enabled:
        creds = get_paypal_credentials()
        return bool(creds and creds.client_secret and not _paypal_credentials_are_demo(creds))
    active_env = paypal_resolved_environment()
    for env in (active_env, "sandbox", "live"):
        cid = _paypal_client_id_for_env(row, env)
        secret = decrypt_str(_paypal_secret_enc_for_env(row, env)).strip()
        if secret and cid and not is_demo_paypal_credentials(client_id=cid, client_secret=secret):
            return True
    return False


def paypal_keys_status_for_env(env: str) -> dict[str, str]:
    """Masked preview + readiness hints for admin (sandbox or live)."""
    row = _paypal_row()
    if not row:
        return {"client_id": "—", "secret": "—", "ready": "missing"}
    cid = _paypal_client_id_for_env(row, env)
    secret_enc = _paypal_secret_enc_for_env(row, env)
    secret = masked_paypal_secret(secret_enc)
    client_preview = _mask_secret(cid, prefix_len=8, suffix_len=4) if cid else "—"
    if not cid or secret == "—":
        return {"client_id": client_preview, "secret": secret, "ready": "missing"}
    raw = decrypt_str(secret_enc).strip()
    if is_demo_paypal_credentials(client_id=cid, client_secret=raw):
        return {"client_id": client_preview, "secret": secret, "ready": "demo"}
    return {"client_id": client_preview, "secret": secret, "ready": "ok"}


def paypal_checkout_ready() -> bool:
    creds = get_paypal_credentials()
    if not creds or not creds.client_secret or not creds.client_id:
        return False
    return not _paypal_credentials_are_demo(creds)


def masked_paypal_secret(enc: str) -> str:
    return _mask_secret(decrypt_str(enc))
