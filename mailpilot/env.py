"""Local vs production settings helpers (read by settings.py; pure functions so they can be tested)."""
from __future__ import annotations

import os
from urllib.parse import urlparse

LOCAL = "local"
PRODUCTION = "production"

DEV_SECRET_KEYS = frozenset(
    {
        "",
        "dev-email-automation-secret",
        "change-me-in-production",
        "dev-only-secret-CHANGE-FOR-PRODUCTION-9f8e7d6c5b4a3210",
    }
)


def env_flag(name: str, environ=None) -> bool | None:
    """True/False for an explicit yes/no value, None when the variable is unset or blank."""
    raw = ((environ if environ is not None else os.environ).get(name) or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return None


def env_list(name: str, environ=None) -> list[str]:
    raw = (environ if environ is not None else os.environ).get(name) or ""
    return [p.strip() for p in raw.split(",") if p.strip()]


def resolve_env(environ=None, *, runserver: bool = False) -> tuple[str, bool]:
    """
    (environment name, explicitly_set). MAILPILOT_ENV wins; otherwise the old rule:
    DJANGO_DEBUG=false outside runserver means production.
    """
    environ = environ if environ is not None else os.environ
    name = (environ.get("MAILPILOT_ENV") or "").strip().lower()
    if name in (LOCAL, PRODUCTION):
        return name, True
    debug = env_flag("DJANGO_DEBUG", environ)
    if debug is None:
        debug = env_flag("FLASK_DEBUG", environ)
    return (PRODUCTION if debug is False and not runserver else LOCAL), False


def site_hosts(site_url: str) -> list[str]:
    """Host of SITE_URL plus its www / bare twin: https://mailpilots.net -> [mailpilots.net, www.mailpilots.net]."""
    host = (urlparse(site_url).hostname or "").lower() if site_url else ""
    if not host:
        return []
    if host in ("localhost",) or host.replace(".", "").isdigit():
        return [host]
    twin = host[4:] if host.startswith("www.") else f"www.{host}"
    return [host, twin]


def production_problems(*, secret_key: str, site_url: str) -> list[str]:
    problems = []
    if secret_key in DEV_SECRET_KEYS or "CHANGE-FOR-PRODUCTION" in secret_key:
        problems.append("DJANGO_SECRET_KEY must be a long random value on production.")
    if not site_url:
        problems.append("SITE_URL must be set on production, e.g. SITE_URL=https://mailpilots.net")
    elif not site_url.startswith("https://"):
        problems.append("SITE_URL must use https:// on production.")
    return problems
