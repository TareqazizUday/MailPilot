"""Server readiness checks for `manage.py deploy_check` (environment, security, DB, static, billing)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from django.conf import settings

from core.billing_deploy import _check, billing_deploy_checks
from mailpilot.env import production_problems, site_hosts

# Covered by deploy_checks() itself; dropped from the billing list to avoid duplicates.
_GENERAL_BILLING_LABELS = frozenset(
    {
        "DJANGO_DEBUG=false on server",
        "SITE_URL set",
        "DJANGO_SECRET_KEY (strong, unique)",
        "FIELD_ENCRYPTION_KEY",
        "OAUTH_REDIRECT_URI matches SITE_URL",
    }
)


def _fernet_key_ok(raw: str) -> bool:
    from cryptography.fernet import Fernet

    try:
        Fernet(raw.encode("ascii"))
    except Exception:
        return False
    return True


def _pending_migrations() -> list[str]:
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connection)
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    return [f"{m.app_label}.{m.name}" for m, _backwards in plan]


def _missing_static() -> list[str]:
    root = Path(settings.STATIC_ROOT)
    missing = []
    for src in settings.STATICFILES_DIRS:
        src = Path(src)
        for f in src.rglob("*"):
            if f.is_file() and not (root / f.relative_to(src)).is_file():
                missing.append(f.relative_to(src).as_posix())
    return missing


def deploy_checks(*, production: bool, billing: bool = True) -> list[dict[str, Any]]:
    sev = "error" if production else "warn"
    site = getattr(settings, "SITE_URL", "") or ""
    checks: list[dict[str, Any]] = []

    checks.append(
        _check(
            settings.IS_PRODUCTION or not production,
            label="MAILPILOT_ENV=production",
            detail=f"Current: {settings.MAILPILOT_ENV}",
            severity=sev,
        )
    )
    checks.append(_check(not settings.DEBUG or not production, label="DEBUG off", detail="DJANGO_DEBUG=false", severity=sev))

    problems = production_problems(secret_key=settings.SECRET_KEY, site_url=site) if production else []
    checks.append(
        _check(
            not problems,
            label="SITE_URL (https) + DJANGO_SECRET_KEY",
            detail=" ".join(problems) or site or "local: SITE_URL optional",
            severity=sev,
        )
    )
    missing_hosts = [h for h in site_hosts(site) if h not in settings.ALLOWED_HOSTS and "*" not in settings.ALLOWED_HOSTS]
    checks.append(
        _check(
            not missing_hosts,
            label="ALLOWED_HOSTS covers SITE_URL",
            detail=", ".join(missing_hosts) or ", ".join(settings.ALLOWED_HOSTS),
            severity=sev,
        )
    )
    checks.append(
        _check(
            (settings.SECURE_SSL_REDIRECT and settings.SESSION_COOKIE_SECURE) or not production,
            label="HTTPS redirect + secure cookies",
            detail="Proxy must send X-Forwarded-Proto: https (or set DJANGO_BEHIND_HTTPS_PROXY=true).",
            severity=sev,
        )
    )

    fkey = (os.environ.get("FIELD_ENCRYPTION_KEY") or "").strip()
    checks.append(
        _check(
            _fernet_key_ok(fkey) if fkey else not production,
            label="FIELD_ENCRYPTION_KEY",
            detail="Keep the key the server already uses; a new one cannot read saved credentials."
            if fkey
            else "Missing: mailbox passwords are stored unencrypted.",
            severity=sev,
        )
    )

    oauth = (os.environ.get("OAUTH_REDIRECT_URI") or "").strip()
    checks.append(
        _check(
            oauth.startswith(site) if (production and site) else True,
            label="OAUTH_REDIRECT_URI uses SITE_URL",
            detail=oauth or f"Set OAUTH_REDIRECT_URI={site or 'https://<domain>'}/api/gmail/oauth/callback",
            severity="warn",
        )
    )
    secret_file = Path(settings.BASE_DIR) / (os.environ.get("GOOGLE_CLIENT_SECRET_FILE") or "client_secret.json")
    checks.append(
        _check(
            secret_file.is_file(),
            label="Gmail OAuth client_secret.json",
            detail=str(secret_file),
            severity="warn",
        )
    )

    from core.social_auth import firebase_web_config

    checks.append(
        _check(
            firebase_web_config() is not None,
            label="Firebase (Google + GitHub sign-in)",
            detail="FIREBASE_PROJECT_ID, FIREBASE_API_KEY, FIREBASE_AUTH_DOMAIN, FIREBASE_APP_ID",
            severity="warn",
        )
    )

    try:
        pending = _pending_migrations()
        checks.append(
            _check(
                not pending,
                label="Database reachable, migrations applied",
                detail=("Run: python manage.py migrate  (" + ", ".join(pending[:5]) + ")") if pending else "OK",
                severity=sev,
            )
        )
    except Exception as e:
        checks.append(_check(False, label="Database reachable", detail=str(e)[:200], severity="error"))

    missing_static = _missing_static()
    checks.append(
        _check(
            not missing_static,
            label="collectstatic up to date",
            detail=f"Run: python manage.py collectstatic --noinput  ({len(missing_static)} missing)"
            if missing_static
            else str(settings.STATIC_ROOT),
            severity="warn",
        )
    )

    if billing:
        checks += [
            c for c in billing_deploy_checks(production=production) if c["label"] not in _GENERAL_BILLING_LABELS
        ]
    return checks
