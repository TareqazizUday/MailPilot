"""Google / GitHub sign-in for the mobile app (JWT, no Django session).

Browser flow: the app opens a server page in a system browser (Google redirect flow or the
Firebase popup page); it deep-links back to ``return_to`` with a one-time ``code`` the app
trades for JWT. Tokens never travel in URLs.

Native flow: the app posts a Google Sign-In or Firebase ID token; it is verified to belong
to our app before the profile is trusted.
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import timedelta

from django.contrib.auth.models import User
from django.core import signing
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from django.utils import timezone

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
    merge_google_email,
    parse_profile,
    redirect_uri_for,
    verify_firebase_id_token,
)

logger = logging.getLogger("mailpilot.auth.social")

STATE_TTL_SECONDS = 10 * 60
CODE_TTL_SECONDS = 300


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


def _mobile_state(return_to: str, button: str, redirect_uri: str) -> str:
    """Signed state carried by GitHub itself, so a second server process can still finish the login."""
    blob = signing.dumps(
        {"r": return_to, "b": button, "u": redirect_uri},
        salt="mp-social-state",
        compress=True,
    )
    return f"m.{blob}"


def _read_mobile_state(state: str) -> dict | None:
    state = (state or "").strip()
    if state.startswith("m."):
        try:
            data = signing.loads(state[2:], salt="mp-social-state", max_age=STATE_TTL_SECONDS)
        except signing.BadSignature:
            return {"invalid": True}
        return data if isinstance(data, dict) else {"invalid": True}
    entry = cache.get(_state_key(state)) if state else None
    if not isinstance(entry, dict):
        return None
    cache.delete(_state_key(state))
    return {"r": entry.get("return_to"), "b": entry.get("button"), "u": entry.get("redirect_uri")}


def _state_hash(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


def _save_handoff(state: str, *, code: str = "", error: str = "") -> None:
    """Remember the login code where every worker can read it. The phone polls this."""
    from core.models import SocialAppHandoff

    SocialAppHandoff.objects.filter(created_at__lt=timezone.now() - timedelta(minutes=15)).delete()
    SocialAppHandoff.objects.update_or_create(
        state_hash=_state_hash(state),
        defaults={"code": code, "error": error},
    )


def peek_handoff(state: str) -> dict | None:
    """Return ``{"code"}`` or ``{"error"}`` once GitHub has finished, else None."""
    from core.models import SocialAppHandoff

    state = (state or "").strip()
    if not state.startswith("m."):
        raise SocialLoginError("invalid_or_expired_code")
    try:
        signing.loads(state[2:], salt="mp-social-state", max_age=STATE_TTL_SECONDS)
    except signing.BadSignature:
        raise SocialLoginError("invalid_or_expired_code")
    row = SocialAppHandoff.objects.filter(state_hash=_state_hash(state)).first()
    if row is None:
        return None
    if row.error:
        return {"error": row.error}
    if row.code:
        return {"code": row.code}
    return None


def start(request: HttpRequest, button: str, return_to: str) -> tuple[str, str]:
    """Return ``(authorization_url, state)`` for the in-app browser.

    GitHub opens github.com itself. The MailPilot website page is not used, so the phone
    does not show a second "Continue with GitHub" card.
    """
    return_to = (return_to or "").strip()
    if not is_allowed_return_to(return_to):
        raise SocialLoginError("invalid_return_to")
    provider = _provider_for(button)
    redirect_uri = redirect_uri_for(request, provider)
    state = _mobile_state(return_to, button, redirect_uri)
    return authorization_url(provider, redirect_uri=redirect_uri, state=state), state


def handle_callback(request: HttpRequest, provider: Provider) -> HttpResponse | None:
    """Finish a mobile flow, or return None so the web (session) flow runs."""
    state = (request.GET.get("state") or "").strip()
    entry = _read_mobile_state(state)
    if entry is None:
        return None
    if entry.get("invalid"):
        return HttpResponse("This sign-in expired. Go back to the MailPilot app and try again.", status=400)
    return_to = str(entry.get("r") or "")
    button = str(entry.get("b") or provider.name)

    def fail(error: str) -> HttpResponse:
        _save_handoff(state, error=error)
        return AppSchemeRedirect(with_query(return_to, {"status": "error", "error": error, "provider": button}))

    if BUTTONS.get(button, ("",))[0] != provider.name:
        return fail("state_mismatch")
    code = (request.GET.get("code") or "").strip()
    if request.GET.get("error") or not code:
        return fail("cancelled")
    try:
        profile = fetch_profile(provider, code, str(entry.get("u") or entry.get("redirect_uri") or ""))
        user, created = find_or_create_user(profile)
    except SocialLoginError as e:
        return fail(str(e))
    except Exception:
        logger.exception("mobile social login failed provider=%s", provider.name)
        return fail("failed")

    log_audit(request, "signup_social" if created else "login_social", f"{button} mobile user={user.id}")
    login_code = _login_code(user, created)
    _save_handoff(state, code=login_code)
    return AppSchemeRedirect(with_query(return_to, {"status": "ok", "code": login_code, "provider": button}))


def _login_code(user: User, created: bool) -> str:
    return signing.dumps({"u": user.id, "c": bool(created)}, salt="mp-social-code", compress=True)


def app_return_url(return_to: str, user: User, created: bool, button: str) -> str:
    """Deep link back into the app. The code is signed, so any server process can redeem it."""
    return with_query(return_to, {"status": "ok", "code": _login_code(user, created), "provider": button})


def redeem(code: str) -> tuple[User, bool]:
    """The phone trades the deep-link code for the user. Signed codes do not depend on server memory."""
    code = (code or "").strip()
    data = None
    if code:
        try:
            loaded = signing.loads(code, salt="mp-social-code", max_age=CODE_TTL_SECONDS)
        except signing.BadSignature:
            loaded = None
        if isinstance(loaded, dict):
            used = f"mailpilot:social_login_used:{code}"
            if not cache.add(used, 1, timeout=CODE_TTL_SECONDS):
                raise SocialLoginError("invalid_or_expired_code")
            data = loaded
        else:
            data = cache.get(_code_key(code))
            cache.delete(_code_key(code))
    if not isinstance(data, dict):
        raise SocialLoginError("invalid_or_expired_code")
    user = User.objects.filter(pk=data.get("u") or data.get("user_id"), is_active=True).first()
    if user is None:
        raise SocialLoginError("inactive")
    return user, bool(data.get("c") if "c" in data else data.get("created"))


# Public OAuth client IDs from the installed app (google-services.json / GoogleService-Info.plist).
# A release APK's Google ID token audience is the web client, even when GOOGLE_LOGIN_MOBILE_CLIENT_IDS is empty.
_APP_GOOGLE_CLIENT_IDS = (
    "251110989928-22s146m0cnnptr2je7j9i734n9snlph6.apps.googleusercontent.com",
    "251110989928-jr5ge5gnkr1bofteks72domuf73pnhot.apps.googleusercontent.com",
    "251110989928-sdmspvpr4ckhagrc7ncvk7rcfmpvoc0g.apps.googleusercontent.com",
)


def _google_audiences() -> set[str]:
    ids = {credentials(PROVIDERS["google"])[0]}
    ids.update((os.environ.get("GOOGLE_LOGIN_MOBILE_CLIENT_IDS") or "").split(","))
    ids.update(_APP_GOOGLE_CLIENT_IDS)
    return {i.strip() for i in ids if i and i.strip()}


def _verify_google_id_token(token: str, access_token: str = "") -> dict:
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
    # A second Google account on the phone can return an ID token with no email claim.
    # The access token from the same sign-in is checked against that token's subject.
    claims = merge_google_email(claims, access_token, subject=str(claims.get("sub") or ""))
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
        return _verify_google_id_token(id_token, access_token)
    raise SocialLoginError("unknown_provider")
