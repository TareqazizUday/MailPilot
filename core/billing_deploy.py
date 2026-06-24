"""Production billing / deploy readiness checks (env-only credentials)."""
from __future__ import annotations

import os
from typing import Any


def _check(ok: bool, *, label: str, detail: str = "", severity: str = "error") -> dict[str, Any]:
    return {
        "ok": ok,
        "label": label,
        "detail": detail,
        "severity": "ok" if ok else severity,
    }


def billing_deploy_checks(*, production: bool | None = None) -> list[dict[str, Any]]:
    """
    Validate env + gateway state for live checkout.
    production=None → infer from DEBUG (False = production checks).
    """
    from django.conf import settings

    from core.payment_gateway import (
        billing_demo_mode,
        billing_site_url_missing,
        billing_use_local_checkout,
        get_paypal_credentials,
        get_stripe_credentials,
        paypal_checkout_ready,
        paypal_resolved_environment,
        stripe_checkout_block_reason,
        stripe_checkout_ready,
        stripe_resolved_environment,
    )

    is_prod = (not settings.DEBUG) if production is None else production
    checks: list[dict[str, Any]] = []

    checks.append(
        _check(
            not settings.DEBUG if is_prod else True,
            label="DJANGO_DEBUG=false on server",
            detail="Set DJANGO_DEBUG=false (or unset) on production.",
            severity="error" if is_prod else "warn",
        )
    )

    site = (getattr(settings, "SITE_URL", "") or "").strip()
    checks.append(
        _check(
            bool(site) if is_prod else True,
            label="SITE_URL set",
            detail=site or "Example: SITE_URL=https://yourdomain.com",
            severity="error" if is_prod else "warn",
        )
    )

    secret = (os.environ.get("DJANGO_SECRET_KEY") or "").strip()
    weak = not secret or "CHANGE-FOR-PRODUCTION" in secret or secret == "dev-only-secret-CHANGE-FOR-PRODUCTION-9f8e7d6c5b4a3210"
    checks.append(
        _check(
            not weak if is_prod else True,
            label="DJANGO_SECRET_KEY (strong, unique)",
            detail="Generate a long random secret for production.",
            severity="error" if is_prod else "warn",
        )
    )

    fkey = (os.environ.get("FIELD_ENCRYPTION_KEY") or "").strip()
    checks.append(
        _check(
            bool(fkey) if is_prod else True,
            label="FIELD_ENCRYPTION_KEY",
            detail=(
                "Run: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
                if not fkey
                else "Set — keep identical across deploys."
            ),
            severity="error" if is_prod else "warn",
        )
    )

    checks.append(
        _check(
            not billing_demo_mode() if is_prod else True,
            label="BILLING_DEMO_MODE=false",
            detail="Demo/simulated checkout must be off on production.",
            severity="error" if is_prod else "warn",
        )
    )

    checks.append(
        _check(
            not billing_use_local_checkout() if is_prod else True,
            label="Real gateway checkout (not local form)",
            detail="Production uses Stripe/PayPal redirect, not /billing/checkout/pay.",
            severity="error" if is_prod else "ok",
        )
    )

    stripe_env = stripe_resolved_environment()
    checks.append(
        _check(
            stripe_env == "live" if is_prod else True,
            label="Stripe environment = live",
            detail=f"Active: {stripe_env} · STRIPE_KEY_ENVIRONMENT=auto on production.",
            severity="error" if is_prod and stripe_env != "live" else "ok",
        )
    )

    sc = get_stripe_credentials()
    checks.append(
        _check(
            bool(sc and sc.secret_key.startswith("sk_live_")) if is_prod else bool(sc),
            label="STRIPE_LIVE_SECRET_KEY",
            detail="sk_live_… in .env",
            severity="error" if is_prod else "warn",
        )
    )

    from core.payment_gateway import (
        _credentials_are_demo,
        stripe_live_charges_enabled,
        stripe_secret_key_mode,
    )

    stripe_block = stripe_checkout_block_reason()
    stripe_ready = stripe_checkout_ready()
    if is_prod and sc and not _credentials_are_demo(sc):
        if stripe_secret_key_mode(sc.secret_key) == "live":
            charges = stripe_live_charges_enabled()
            if charges is False:
                stripe_ready = False
                stripe_block = (
                    "Your Stripe live account cannot accept card payments yet "
                    "(card_payments capability is inactive). "
                    "Complete activation in the Stripe Dashboard."
                )
        elif not sc.secret_key.startswith("sk_live_"):
            stripe_ready = False
            stripe_block = "Production requires STRIPE_LIVE_SECRET_KEY (sk_live_…)."
    checks.append(
        _check(
            stripe_ready if is_prod else True,
            label="Stripe checkout ready",
            detail=stripe_block or "OK",
            severity="error" if is_prod and not stripe_ready else ("warn" if stripe_block else "ok"),
        )
    )

    wh = (os.environ.get("STRIPE_WEBHOOK_SECRET") or "").strip() or (sc.webhook_secret if sc else "")
    checks.append(
        _check(
            bool(wh),
            label="STRIPE_WEBHOOK_SECRET (recommended)",
            detail=(
                f"Stripe Dashboard → Webhooks → {site}/billing/webhook/stripe"
                if site
                else "Endpoint: /billing/webhook/stripe"
            ),
            severity="warn",
        )
    )

    paypal_env = paypal_resolved_environment() if not is_prod else "live"
    checks.append(
        _check(
            paypal_env == "live" if is_prod else True,
            label="PayPal environment = live",
            detail=f"Active: {paypal_env} · PAYPAL_ENVIRONMENT=auto on production.",
            severity="error" if is_prod and paypal_env != "live" else "ok",
        )
    )

    live_cid = (os.environ.get("PAYPAL_LIVE_CLIENT_ID") or "").strip()
    live_sec = (os.environ.get("PAYPAL_LIVE_CLIENT_SECRET") or "").strip()
    checks.append(
        _check(
            bool(live_cid and live_sec) if is_prod else True,
            label="PayPal live credentials",
            detail="PAYPAL_LIVE_CLIENT_ID + PAYPAL_LIVE_CLIENT_SECRET in .env",
            severity="error" if is_prod else "warn",
        )
    )

    pc = get_paypal_credentials()
    paypal_ready = paypal_checkout_ready()
    if is_prod:
        from core.payment_gateway import is_demo_paypal_credentials

        paypal_ready = bool(
            live_cid
            and live_sec
            and not is_demo_paypal_credentials(client_id=live_cid, client_secret=live_sec)
        )
    checks.append(
        _check(
            paypal_ready if is_prod else bool(pc),
            label="PayPal checkout ready",
            detail=(
                "Live REST credentials missing or invalid."
                if is_prod and not paypal_ready
                else ("Sandbox OK for local" if pc and pc.sandbox_mode else "OK")
            ),
            severity="error" if is_prod and not paypal_ready else "ok",
        )
    )

    if is_prod and site:
        checks.append(
            _check(
                not billing_site_url_missing(),
                label="Checkout redirect URLs",
                detail=f"Success/cancel use {site}",
                severity="error",
            )
        )

    oauth = (os.environ.get("OAUTH_REDIRECT_URI") or "").strip()
    if is_prod and site:
        checks.append(
            _check(
                oauth.startswith(site),
                label="OAUTH_REDIRECT_URI matches SITE_URL",
                detail=oauth or "Set OAUTH_REDIRECT_URI to your production callback URL.",
                severity="warn",
            )
        )

    return checks


def billing_deploy_ready(*, production: bool | None = None) -> bool:
    checks = billing_deploy_checks(production=production)
    return not any(not c["ok"] and c["severity"] == "error" for c in checks)
