"""Google / GitHub sign-in for the mobile app (JWT, no Django session).

Browser flow: the app opens a server page in a system browser (Google redirect flow or the
Firebase popup page); it deep-links back to ``return_to`` with a one-time ``code`` the app
trades for JWT. Tokens never travel in URLs.

Native flow: the app posts a Google Sign-In or Firebase ID token; it is verified to belong
to our app before the profile is trusted.
"""

from __future__ import annotations

import logging
import os
import secrets

from django.contrib.auth.models import User
from django.core.cache import cache
from django.http import HttpRequest

from core.audit import log_audit
from core.gmail_mobile_oauth import AppSchemeRedirect, is_allowed_return_to, with_query
from core.social_auth import (
    BUTTONS,
    PROVIDERS,
    Provider,
    SocialLoginError,
    authorization_url,
    credentials,
    fetch_profile,
    find_or_create_user,
    is_configured,
    parse_profile,
    redirect_uri_for,
    verify_firebase_id_token,
)

logger = logging.getLogger("mailpilot.auth.social")

STATE_TTL_SECONDS = 10 * 60
CODE_TTL_SECONDS = 120


def _state_key(state: str) -> str:
    return f"mailpilot:social_login_mobile:{state}"


def _code_key(code: str) -> str:
    return f"mailpilot:social_login_code:{code}"


def _provider_for(button: str) -> Provider:
    if button not in BUTTONS:
        raise SocialLoginError("unknown_provider")
    provider = PROVIDERS[BUTTONS[button][0]]
    if not is_configured(provider):
        raise SocialLoginError("not_configured")
    return provider


def start(request: HttpRequest, button: str, return_to: str) -> tuple[str, str]:
    """Return ``(authorization_url, state)`` for the in-app browser."""
    provider = _provider_for(button)
    return_to = (return_to or "").strip()
    if not is_allowed_return_to(return_to):
        raise SocialLoginError("invalid_return_to")
    state = secrets.token_urlsafe(32)
    redirect_uri = redirect_uri_for(request, provider)
    cache.set(
        _state_key(state),
        {"button": button, "return_to": return_to, "redirect_uri": redirect_uri},
        timeout=STATE_TTL_SECONDS,
    )
    return authorization_url(provider, redirect_uri=redirect_uri, state=state), state


def handle_callback(request: HttpRequest, provider: Provider) -> AppSchemeRedirect | None:
    """Finish a mobile flow, or return None so the web (session) flow runs."""
    state = (request.GET.get("state") or "").strip()
    entry = cache.get(_state_key(state)) if state else None
    if not isinstance(entry, dict):
        return None
    cache.delete(_state_key(state))
    return_to = str(entry.get("return_to") or "")
    button = str(entry.get("button") or provider.name)

    def fail(error: str) -> AppSchemeRedirect:
        return AppSchemeRedirect(with_query(return_to, {"status": "error", "error": error, "provider": button}))

    if BUTTONS.get(button, ("",))[0] != provider.name:
        return fail("state_mismatch")
    code = (request.GET.get("code") or "").strip()
    if request.GET.get("error") or not code:
        return fail("cancelled")
    try:
        profile = fetch_profile(provider, code, str(entry.get("redirect_uri") or ""))
        user, created = find_or_create_user(profile)
    except SocialLoginError as e:
        return fail(str(e))
    except Exception:
        logger.exception("mobile social login failed provider=%s", provider.name)
        return fail("failed")

    log_audit(request, "signup_social" if created else "login_social", f"{button} mobile user={user.id}")
    return AppSchemeRedirect(app_return_url(return_to, user, created, button))


def app_return_url(return_to: str, user: User, created: bool, button: str) -> str:
    """Deep link back into the app carrying a one-time code for ``redeem``."""
    login_code = secrets.token_urlsafe(32)
    cache.set(_code_key(login_code), {"user_id": user.id, "created": created}, timeout=CODE_TTL_SECONDS)
    return with_query(return_to, {"status": "ok", "code": login_code, "provider": button})


def redeem(code: str) -> tuple[User, bool]:
    """Single use: the code is deleted on the first attempt, valid or not."""
    code = (code or "").strip()
    entry = cache.get(_code_key(code)) if code else None
    if code:
        cache.delete(_code_key(code))
    if not isinstance(entry, dict):
        raise SocialLoginError("invalid_or_expired_code")
    user = User.objects.filter(pk=entry.get("user_id"), is_active=True).first()
    if user is None:
        raise SocialLoginError("inactive")
    return user, bool(entry.get("created"))


def _google_audiences() -> set[str]:
    ids = {credentials(PROVIDERS["google"])[0]}
    ids.update((os.environ.get("GOOGLE_LOGIN_MOBILE_CLIENT_IDS") or "").split(","))
    return {i.strip() for i in ids if i and i.strip()}


def _verify_google_id_token(token: str) -> dict:
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token as google_id_token

    audiences = _google_audiences()
    if not audiences:
        raise SocialLoginError("not_configured")
    try:
        claims = google_id_token.verify_oauth2_token(token, google_requests.Request())
    except ValueError:
        raise SocialLoginError("invalid_token") from None
    if claims.get("aud") not in audiences:
        raise SocialLoginError("invalid_token")
    return parse_profile(claims)


def verify_native_token(button: str, *, id_token: str = "", access_token: str = "") -> dict:
    """Verify a Google Sign-In or Firebase ID token minted for our app; return the profile.

    Firebase GitHub sign-ins also send the GitHub OAuth ``access_token``.
    """
    if button == "firebase":
        return verify_firebase_id_token(id_token, provider_access_token=access_token)
    if button == "google":
        if not id_token:
            raise SocialLoginError("id_token_required")
        return _verify_google_id_token(id_token)
    raise SocialLoginError("unknown_provider")
