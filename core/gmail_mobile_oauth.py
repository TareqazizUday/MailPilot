"""Per-mailbox Gmail OAuth for the mobile app.

The app opens Google's consent page in a system browser that has no Django session, so the
flow is keyed by OAuth `state` in the cache. Google redirects to the same web callback URL as
the website flow; the callback then bounces back into the app via `return_to`.
"""
from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings as dj_settings
from django.core.cache import cache
from django.http import HttpResponseRedirect

logger = logging.getLogger(__name__)

STATE_TTL_SECONDS = 10 * 60
_RETURN_TO_PREFIXES = ("mailpilot://", "exp://", "exps://")
_RETURN_TO_ORIGINS = ("http://localhost:8081", "http://127.0.0.1:8081")


class AppSchemeRedirect(HttpResponseRedirect):
    allowed_schemes = ["http", "https", "mailpilot", "exp", "exps"]


def state_cache_key(state: str) -> str:
    return f"mailpilot:gmail_oauth_mobile:{state}"


def _matches_origin(url: str, origin: str) -> bool:
    return url == origin or url.startswith(origin + "/") or url.startswith(origin + "?")


def is_allowed_return_to(url: str) -> bool:
    url = (url or "").strip()
    if not url:
        return False
    if url.lower().startswith(_RETURN_TO_PREFIXES):
        return True
    origins = list(_RETURN_TO_ORIGINS)
    site = (getattr(dj_settings, "SITE_URL", "") or "").strip().rstrip("/")
    if site:
        origins.append(site)
    return any(_matches_origin(url, o) for o in origins)


def with_query(url: str, params: dict[str, Any]) -> str:
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    query.extend((k, str(v)) for k, v in params.items())
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def build_flow(effective, redirect_uri: str):
    from google_auth_oauthlib.flow import Flow

    return Flow.from_client_secrets_file(
        effective.GOOGLE_CLIENT_SECRET_FILE,
        scopes=effective.gmail_scopes(),
        redirect_uri=redirect_uri,
        autogenerate_code_verifier=False,
    )


def start(user, account, *, redirect_uri: str, return_to: str) -> tuple[str, str]:
    """Return (authorization_url, state) and remember who started the flow."""
    from core.mail_accounts import build_effective_settings

    effective = build_effective_settings(user, account_id=account.id)
    if not os.path.exists(effective.GOOGLE_CLIENT_SECRET_FILE):
        raise FileNotFoundError("client_secret_missing")
    flow = build_flow(effective, redirect_uri)
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    cache.set(
        state_cache_key(state),
        {"user_id": user.id, "account_id": account.id, "return_to": return_to, "redirect_uri": redirect_uri},
        timeout=STATE_TTL_SECONDS,
    )
    return authorization_url, state


def pending(state: str) -> dict[str, Any] | None:
    if not state:
        return None
    entry = cache.get(state_cache_key(state))
    return entry if isinstance(entry, dict) else None


def email_mismatch_error(account, creds) -> str:
    expected = str((account.config_json or {}).get("GMAIL_ADDRESS") or "").strip()
    if not expected:
        return ""
    from googleapiclient.discovery import build

    svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
    profile = str(svc.users().getProfile(userId="me").execute().get("emailAddress") or "").strip()
    if profile.lower() == expected.lower():
        return ""
    return f"oauth_email_mismatch: signed in as {profile}, this mailbox expects {expected}"


def exchange_and_save(account, *, code: str, redirect_uri: str) -> str:
    """Exchange `code`, save the token on `account`. Returns an error string, or '' on success."""
    from core.mail_accounts import build_effective_settings, save_account_oauth_token

    effective = build_effective_settings(account.user, account_id=account.id)
    if not os.path.exists(effective.GOOGLE_CLIENT_SECRET_FILE):
        return "client_secret_missing"
    flow = build_flow(effective, redirect_uri)
    try:
        flow.fetch_token(code=code)
    except Exception as e:
        logger.exception("mobile oauth fetch_token failed account=%s", account.id)
        return f"token_exchange_failed: {e}"
    creds = flow.credentials
    try:
        mismatch = email_mismatch_error(account, creds)
    except Exception:
        logger.exception("mobile oauth profile lookup failed account=%s", account.id)
        mismatch = ""
    if mismatch:
        return mismatch
    save_account_oauth_token(account, creds.to_json())
    return ""


def handle_callback(request) -> HttpResponseRedirect | None:
    """Finish a mobile flow, or return None so the caller runs the web (session) flow."""
    from django.contrib.auth.models import User

    from core.mail_accounts import TRANSPORT_GMAIL, get_account

    state = (request.GET.get("state") or "").strip()
    entry = pending(state)
    if entry is None:
        return None
    cache.delete(state_cache_key(state))
    return_to = str(entry.get("return_to") or "")

    def fail(message: str) -> AppSchemeRedirect:
        return AppSchemeRedirect(with_query(return_to, {"status": "error", "error": message[:300]}))

    user = User.objects.filter(pk=entry.get("user_id"), is_active=True).first()
    acc = get_account(user, int(entry.get("account_id") or 0)) if user else None
    if acc is None or acc.transport != TRANSPORT_GMAIL:
        return fail("account_not_found")
    code = (request.GET.get("code") or "").strip()
    if not code:
        return fail((request.GET.get("error") or "missing_code").strip())
    err = exchange_and_save(acc, code=code, redirect_uri=str(entry.get("redirect_uri") or ""))
    if err:
        return fail(err)
    return AppSchemeRedirect(with_query(return_to, {"status": "ok", "account_id": acc.id}))
