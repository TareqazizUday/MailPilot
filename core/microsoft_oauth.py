"""Microsoft Graph OAuth (MSAL) for mailbox connect on Setup / API."""
from __future__ import annotations

import json
import logging
import os
import secrets
from typing import Any
from urllib.parse import quote

from django.core.cache import cache
from django.http import HttpRequest
from django.shortcuts import redirect
from django.urls import reverse

logger = logging.getLogger(__name__)

STATE_TTL_SECONDS = 10 * 60
# MSAL reserved scopes (openid/profile/offline_access) must NOT be passed —
# MSAL injects them. Passing offline_access raises ValueError.
GRAPH_SCOPES = [
    "Mail.ReadWrite",
    "Mail.Send",
    "User.Read",
]
_MSAL_RESERVED_SCOPES = frozenset({"openid", "profile", "offline_access"})


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def client_id() -> str:
    return _env("MICROSOFT_OAUTH_CLIENT_ID")


def client_secret() -> str:
    return _env("MICROSOFT_OAUTH_CLIENT_SECRET")


def tenant() -> str:
    return _env("MICROSOFT_OAUTH_TENANT", "common") or "common"


def is_configured() -> bool:
    return bool(client_id() and client_secret())


def state_cache_key(state: str) -> str:
    return f"mailpilot:microsoft_oauth:{state}"


def build_msal_app(*, token_cache=None):
    import msal

    if not is_configured():
        raise RuntimeError("microsoft_oauth_not_configured")
    authority = f"https://login.microsoftonline.com/{tenant()}"
    # Default TokenCache has no serialize(); SerializableTokenCache is required to persist.
    cache_obj = token_cache if token_cache is not None else msal.SerializableTokenCache()
    return msal.ConfidentialClientApplication(
        client_id(),
        authority=authority,
        client_credential=client_secret(),
        token_cache=cache_obj,
    )


def _serialize_token_cache(app) -> str:
    tc = getattr(app, "token_cache", None)
    if tc is None:
        return ""
    serialize = getattr(tc, "serialize", None)
    if not callable(serialize):
        return ""
    try:
        return serialize() or ""
    except Exception:
        logger.debug("msal token_cache serialize failed", exc_info=True)
        return ""


def _load_token_cache(app, cache_data: str) -> None:
    if not cache_data:
        return
    tc = getattr(app, "token_cache", None)
    deserialize = getattr(tc, "deserialize", None) if tc is not None else None
    if not callable(deserialize):
        return
    try:
        deserialize(cache_data)
    except Exception:
        logger.debug("msal token_cache deserialize failed", exc_info=True)


def _msal_api_scopes() -> list[str]:
    """Scopes safe to pass into MSAL (no reserved openid/profile/offline_access)."""
    return [s for s in GRAPH_SCOPES if s not in _MSAL_RESERVED_SCOPES]


def redirect_uri_for_request(request: HttpRequest) -> str:
    configured = _env("MICROSOFT_OAUTH_REDIRECT_URI")
    if configured:
        return configured
    try:
        return request.build_absolute_uri(reverse("microsoft_oauth_callback"))
    except Exception:
        return request.build_absolute_uri("/api/microsoft/oauth/callback")


def _needs_localhost_host_align(request: HttpRequest) -> bool:
    """True when browser is 127.0.0.1 but Azure redirect_uri is localhost."""
    from urllib.parse import urlsplit

    redirect_uri = redirect_uri_for_request(request)
    try:
        redir_host = (urlsplit(redirect_uri).hostname or "").lower()
        req_host = (request.get_host() or "").split(":")[0].lower()
    except Exception:
        return False
    return redir_host == "localhost" and req_host == "127.0.0.1"


def localhost_bounce_url(request: HttpRequest) -> str | None:
    """Rewrite current request URL onto localhost (same path/query)."""
    from urllib.parse import urlsplit, urlunsplit

    if not _needs_localhost_host_align(request):
        return None
    parts = urlsplit(request.build_absolute_uri())
    port = parts.port
    netloc = f"localhost:{port}" if port else "localhost"
    qs = request.GET.urlencode()
    return urlunsplit((parts.scheme or "http", netloc, parts.path, qs, ""))


def localhost_oauth_start_bounce(request: HttpRequest, *, account_id: int) -> str | None:
    """Send the browser to /api/microsoft/oauth/start on localhost before authorize."""
    from urllib.parse import urlsplit, urlunsplit

    if not _needs_localhost_host_align(request):
        return None
    parts = urlsplit(request.build_absolute_uri())
    port = parts.port
    netloc = f"localhost:{port}" if port else "localhost"
    try:
        path = reverse("microsoft_oauth_start")
    except Exception:
        path = "/api/microsoft/oauth/start"
    return urlunsplit(
        (parts.scheme or "http", netloc, path, f"account_id={int(account_id)}", "")
    )


def start_authorization(request: HttpRequest, *, user_id: int, account_id: int) -> str:
    """Return Microsoft authorize URL; remember state in cache + session."""
    app = build_msal_app()
    state = secrets.token_urlsafe(24)
    redirect_uri = redirect_uri_for_request(request)
    cache.set(
        state_cache_key(state),
        {"user_id": user_id, "account_id": account_id, "redirect_uri": redirect_uri},
        timeout=STATE_TTL_SECONDS,
    )
    request.session["microsoft_oauth_state"] = state
    request.session["microsoft_oauth_account_id"] = account_id
    request.session.modified = True
    return app.get_authorization_request_url(
        scopes=_msal_api_scopes(),
        state=state,
        redirect_uri=redirect_uri,
        prompt="select_account",
    )


def _with_expiry(blob: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    import time

    out = dict(blob)
    try:
        expires_in = int(result.get("expires_in") or 3600)
    except (TypeError, ValueError):
        expires_in = 3600
    out["expires_in"] = expires_in
    out["expires_at"] = int(time.time()) + max(60, expires_in)
    return out


def exchange_code(*, code: str, redirect_uri: str) -> dict[str, Any]:
    app = build_msal_app()
    result = app.acquire_token_by_authorization_code(
        code,
        scopes=_msal_api_scopes(),
        redirect_uri=redirect_uri,
    )
    if not isinstance(result, dict) or "access_token" not in result:
        err = (result or {}).get("error_description") or (result or {}).get("error") or "token_exchange_failed"
        raise RuntimeError(str(err))
    # Compact blob: keep tokens + account hints; MSAL cache optional for refresh
    blob = {
        "access_token": result.get("access_token"),
        "refresh_token": result.get("refresh_token"),
        "token_type": result.get("token_type"),
        "scope": result.get("scope"),
        "id_token_claims": result.get("id_token_claims") or {},
        "client_info": result.get("client_info"),
        "token_cache": _serialize_token_cache(app),
    }
    return _with_expiry(blob, result)


def refresh_access_token(token_blob: dict[str, Any]) -> dict[str, Any]:
    """Return updated token blob with a fresh access_token when possible."""
    app = build_msal_app()
    _load_token_cache(app, str(token_blob.get("token_cache") or ""))
    accounts = app.get_accounts()
    result = None
    token_scopes = _msal_api_scopes()
    if accounts:
        result = app.acquire_token_silent(token_scopes, account=accounts[0])
    if not result or "access_token" not in result:
        refresh = (token_blob.get("refresh_token") or "").strip()
        if not refresh:
            raise RuntimeError("microsoft_refresh_missing")
        result = app.acquire_token_by_refresh_token(refresh, scopes=token_scopes)
    if not isinstance(result, dict) or "access_token" not in result:
        err = (result or {}).get("error_description") or (result or {}).get("error") or "refresh_failed"
        raise RuntimeError(str(err))
    out = dict(token_blob)
    out["access_token"] = result.get("access_token")
    if result.get("refresh_token"):
        out["refresh_token"] = result.get("refresh_token")
    out["scope"] = result.get("scope") or out.get("scope")
    out["token_cache"] = _serialize_token_cache(app)
    return _with_expiry(out, result)


def fetch_profile(access_token: str) -> dict[str, str]:
    import requests

    r = requests.get(
        "https://graph.microsoft.com/v1.0/me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
        params={"$select": "mail,userPrincipalName,displayName"},
    )
    r.raise_for_status()
    data = r.json() if r.content else {}
    mail = str(data.get("mail") or "").strip()
    upn = str(data.get("userPrincipalName") or "").strip()
    return {
        "email": mail or upn,
        "mail": mail,
        "upn": upn,
        "display_name": str(data.get("displayName") or "").strip(),
    }


def fetch_profile_email(access_token: str) -> str:
    return str(fetch_profile(access_token).get("email") or "").strip()


def handle_callback(request: HttpRequest):
    """Complete OAuth; redirect to Setup. Returns HttpResponse."""
    from core.mail_accounts import (
        TRANSPORT_MICROSOFT,
        get_account,
        patch_account_config,
        save_account_oauth_token,
    )

    err = (request.GET.get("error_description") or request.GET.get("error") or "").strip()
    if err and not request.GET.get("code"):
        return redirect(f"{reverse('setup')}?oauth_error={quote(err, safe='')}")

    state = (request.GET.get("state") or "").strip()
    expected = (request.session.get("microsoft_oauth_state") or "").strip()
    entry = cache.get(state_cache_key(state)) if state else None
    if expected and state and state != expected:
        return redirect(f"{reverse('setup')}?oauth_error=oauth_state_mismatch")
    if not isinstance(entry, dict):
        # Fall back to session account id when cache expired but state matches
        if not request.user.is_authenticated:
            return redirect(f"{reverse('setup')}?oauth_error=oauth_state_expired")
        account_id = request.session.get("microsoft_oauth_account_id")
        redirect_uri = redirect_uri_for_request(request)
        user_id = request.user.id
    else:
        user_id = int(entry.get("user_id") or 0)
        account_id = entry.get("account_id")
        redirect_uri = str(entry.get("redirect_uri") or redirect_uri_for_request(request))

    if not request.user.is_authenticated or request.user.id != user_id:
        from django.contrib.auth.views import redirect_to_login

        return redirect_to_login(request.get_full_path(), "/login")

    code = (request.GET.get("code") or "").strip()
    if not code:
        return redirect(f"{reverse('setup')}?oauth_error=missing_code")

    try:
        blob = exchange_code(code=code, redirect_uri=redirect_uri)
        acc = get_account(request.user, int(account_id)) if account_id else None
        if acc is None or acc.transport != TRANSPORT_MICROSOFT:
            return redirect(f"{reverse('setup')}?oauth_error=microsoft_account_missing")
        # Save token first so a Graph /me hiccup does not drop a successful consent.
        save_account_oauth_token(acc, json.dumps(blob))
        profile = ""
        upn = ""
        try:
            info = fetch_profile(str(blob.get("access_token") or ""))
            profile = str(info.get("email") or "").strip()
            upn = str(info.get("upn") or "").strip()
        except Exception:
            logger.warning(
                "microsoft profile fetch failed after token save account_id=%s",
                acc.id,
                exc_info=True,
            )
        if profile or upn:
            patch = {
                "MICROSOFT_ADDRESS": profile or upn,
                "GMAIL_ADDRESS": profile or upn,
            }
            if upn:
                patch["MICROSOFT_UPN"] = upn
            patch_account_config(acc, patch)
            if not (acc.label or "").strip() or acc.label.startswith("Microsoft"):
                acc.label = profile or upn
                acc.save(update_fields=["label", "updated_at"])
    except Exception as e:
        logger.exception("microsoft oauth callback failed")
        return redirect(f"{reverse('setup')}?oauth_error={quote(f'microsoft_oauth_failed: {e}', safe='')}")
    finally:
        if state:
            cache.delete(state_cache_key(state))
        request.session.pop("microsoft_oauth_state", None)
        request.session.pop("microsoft_oauth_account_id", None)

    return redirect(f"{reverse('setup')}?account_id={account_id}")
