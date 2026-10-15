"""Website sign-in / sign-up with Google (incl. Gmail) or GitHub (session login).

Google works through Firebase (popup) or the server redirect flow below; GitHub only
through Firebase. Independent of the Gmail-mailbox OAuth in ``core.views``: these
clients only ask for the user's identity (email + name), never mailbox scopes.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import requests
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.http import Http404, HttpRequest, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.text import slugify
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.audit import log_audit

logger = logging.getLogger("mailpilot.auth.social")

_SESSION_KEY = "social_login"
_HTTP_TIMEOUT = 15


@dataclass(frozen=True)
class Provider:
    name: str
    env_prefix: str
    authorize_url: str
    token_url: str
    scope: str


PROVIDERS: dict[str, Provider] = {
    "google": Provider(
        "google",
        "GOOGLE_LOGIN",
        "https://accounts.google.com/o/oauth2/v2/auth",
        "https://oauth2.googleapis.com/token",
        "openid email profile",
    ),
}

# Buttons served by the server redirect flow (button -> (provider, label)).
BUTTONS: dict[str, tuple[str, str]] = {
    "google": ("google", "Google"),
}

LABELS: dict[str, str] = {"google": "Google", "github": "GitHub"}

ERROR_MESSAGES = {
    "not_configured": "{label} sign-in is not available yet. Please use email and password.",
    "cancelled": "{label} sign-in was cancelled.",
    "state_mismatch": "Your {label} sign-in session expired. Please try again.",
    "failed": "Could not sign in with {label}. Please try again.",
    "email_missing": "{label} did not share an email address with MailPilot.",
    "email_unverified": "Your {label} email address is not verified.",
    "inactive": "This MailPilot account is disabled. Contact support.",
    "invalid_token": "Could not verify your {label} sign-in. Please try again.",
    "unauthorized_domain": "{label} sign-in is not allowed on this site address yet.",
    "account_exists": "This email already signs in with another provider. Use that one, or try again later.",
}


class SocialLoginError(Exception):
    """Carries one of the ``ERROR_MESSAGES`` codes."""


def social_error_message(params) -> str:
    """User-facing message for ``?social_error=<code>&provider=<button>``; '' if none."""
    template = ERROR_MESSAGES.get((params.get("social_error") or "").strip())
    if not template:
        return ""
    label = LABELS.get((params.get("provider") or "").strip(), "Social")
    return template.format(label=label)


def credentials(provider: Provider) -> tuple[str, str]:
    client_id = (os.environ.get(f"{provider.env_prefix}_CLIENT_ID") or "").strip()
    secret = (os.environ.get(f"{provider.env_prefix}_CLIENT_SECRET") or "").strip()
    return client_id, secret


def is_configured(provider: Provider) -> bool:
    return all(credentials(provider))


def configured_providers() -> list[dict]:
    firebase = bool(firebase_project_id())
    return [
        {"id": "google", "label": "Google", "configured": firebase or is_configured(PROVIDERS["google"])},
        {"id": "github", "label": "GitHub", "configured": firebase_web_config() is not None},
    ]


def firebase_project_id() -> str:
    return (os.environ.get("FIREBASE_PROJECT_ID") or "").strip()


def firebase_web_config() -> dict | None:
    """Public Firebase web config for the Google button; None keeps the redirect flow."""
    project_id = firebase_project_id()
    api_key = (os.environ.get("FIREBASE_API_KEY") or "").strip()
    if not (project_id and api_key):
        return None
    return {
        "apiKey": api_key,
        "authDomain": (os.environ.get("FIREBASE_AUTH_DOMAIN") or "").strip() or f"{project_id}.firebaseapp.com",
        "projectId": project_id,
        "appId": (os.environ.get("FIREBASE_APP_ID") or "").strip(),
    }


FIREBASE_SIGN_IN_PROVIDERS = {"google.com": "google", "github.com": "github"}


def _github_verified_email(access_token: str, github_uid: str) -> tuple[str, str]:
    """``(email, name)`` for the GitHub account behind the Firebase sign-in.

    Firebase never marks GitHub emails verified and a GitHub account can hold unverified
    addresses, so the verified one is read from GitHub with the popup's OAuth token.
    """
    if not access_token:
        raise SocialLoginError("access_token_required")
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"}
    r = requests.get("https://api.github.com/user", headers=headers, timeout=_HTTP_TIMEOUT)
    account = (r.json() or {}) if r.status_code == 200 else {}
    if not github_uid or str(account.get("id") or "") != github_uid:
        raise SocialLoginError("invalid_token")
    r = requests.get("https://api.github.com/user/emails", headers=headers, timeout=_HTTP_TIMEOUT)
    if r.status_code != 200:
        logger.warning("github emails fetch failed status=%s", r.status_code)
        raise SocialLoginError("failed")
    emails = [e for e in (r.json() or []) if isinstance(e, dict) and e.get("email")]
    verified = [e for e in emails if e.get("verified")]
    if not verified:
        raise SocialLoginError("email_unverified" if emails else "email_missing")
    best = next((e for e in verified if e.get("primary")), verified[0])
    return best["email"], (account.get("name") or "").strip()


def verify_firebase_id_token(token: str, *, provider_access_token: str = "") -> dict:
    return verify_firebase_sign_in(token, provider_access_token=provider_access_token)[0]


def verify_firebase_sign_in(token: str, *, provider_access_token: str = "") -> tuple[dict, str]:
    """``(profile, button)`` from a Firebase Auth ID token minted by a Google / GitHub sign-in for our project.

    GitHub also needs the GitHub OAuth ``provider_access_token`` from the same sign-in.
    """
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token as google_id_token

    project_id = firebase_project_id()
    if not project_id:
        raise SocialLoginError("not_configured")
    if not token:
        raise SocialLoginError("id_token_required")
    try:
        claims = google_id_token.verify_firebase_token(token, google_requests.Request(), audience=project_id)
    except ValueError:
        raise SocialLoginError("invalid_token") from None
    if not claims or claims.get("iss") != f"https://securetoken.google.com/{project_id}":
        raise SocialLoginError("invalid_token")
    firebase = claims.get("firebase") or {}
    button = FIREBASE_SIGN_IN_PROVIDERS.get(firebase.get("sign_in_provider"))
    if button is None:
        raise SocialLoginError("unsupported_sign_in_provider")
    name = (claims.get("name") or "").strip()
    email_verified = None
    if button == "github":
        uids = (firebase.get("identities") or {}).get("github.com") or []
        email, github_name = _github_verified_email(provider_access_token, str(uids[0]) if uids else "")
        claims = {**claims, "email": email}
        name = name or github_name
        email_verified = True
    first, _, last = name.partition(" ")
    profile = parse_profile({"given_name": first, "family_name": last, **claims}, email_verified=email_verified)
    return profile, button


def redirect_uri_for(request: HttpRequest, provider: Provider) -> str:
    return request.build_absolute_uri(reverse("social_login_callback", args=[provider.name]))


def authorization_url(provider: Provider, *, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": credentials(provider)[0],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": provider.scope,
        "state": state,
    }
    if provider.name == "google":
        params["prompt"] = "select_account"
    return f"{provider.authorize_url}?{urlencode(params)}"


def _back_url(origin: str, code: str, button: str) -> str:
    page = "signup" if origin == "signup" else "login"
    return f"{reverse(page)}?{urlencode({'social_error': code, 'provider': button})}"


def _back(origin: str, code: str, button: str):
    return redirect(_back_url(origin, code, button))


@require_GET
def social_login_start(request: HttpRequest, button: str):
    if button not in BUTTONS:
        raise Http404
    provider = PROVIDERS[BUTTONS[button][0]]
    origin = "signup" if request.GET.get("from") == "signup" else "login"
    if not is_configured(provider):
        return _back(origin, "not_configured", button)

    state = secrets.token_urlsafe(32)
    request.session[_SESSION_KEY] = {
        "state": state,
        "button": button,
        "origin": origin,
        "next": (request.GET.get("next") or "")[:500],
    }
    return redirect(authorization_url(provider, redirect_uri=redirect_uri_for(request, provider), state=state))


def _post_token(provider: Provider, code: str, redirect_uri: str) -> str:
    client_id, secret = credentials(provider)
    payload = {
        "client_id": client_id,
        "client_secret": secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    r = requests.post(provider.token_url, data=payload, timeout=_HTTP_TIMEOUT)
    if r.status_code != 200:
        logger.warning("social token exchange failed provider=%s status=%s", provider.name, r.status_code)
        raise SocialLoginError("failed")
    token = (r.json() or {}).get("access_token")
    if not token:
        raise SocialLoginError("failed")
    return token


def fetch_profile(provider: Provider, code: str, redirect_uri: str) -> dict:
    """Exchange an authorization ``code`` and return the verified profile."""
    return profile_from_access_token(provider, _post_token(provider, code, redirect_uri))


def profile_from_access_token(provider: Provider, token: str) -> dict:
    """Return ``{"email", "first_name", "last_name"}`` for a verified email."""
    r = requests.get(
        "https://openidconnect.googleapis.com/v1/userinfo",
        headers={"Authorization": f"Bearer {token}"},
        timeout=_HTTP_TIMEOUT,
    )
    if r.status_code != 200:
        logger.warning("social profile fetch failed provider=%s status=%s", provider.name, r.status_code)
        raise SocialLoginError("failed")
    return parse_profile(r.json() or {})


def parse_profile(data: dict, *, email_verified: bool | None = None) -> dict:
    """Normalize a userinfo / ID-token claims payload; ``email_verified`` overrides the payload's flag."""
    email = (data.get("email") or "").strip().lower()
    if not email:
        raise SocialLoginError("email_missing")
    if email_verified is None:
        email_verified = data.get("email_verified") in (True, "true")
    if not email_verified:
        raise SocialLoginError("email_unverified")
    return {
        "email": email,
        "first_name": (data.get("given_name") or data.get("first_name") or "").strip()[:150],
        "last_name": (data.get("family_name") or data.get("last_name") or "").strip()[:150],
    }


def _unique_username(email: str) -> str:
    base = slugify(email.split("@", 1)[0])[:140] or "user"
    candidate = base
    i = 0
    while User.objects.filter(username__iexact=candidate).exists():
        i += 1
        candidate = f"{base}{i}"
    return candidate


def _create_user(profile: dict) -> User:
    user = User.objects.create_user(
        username=_unique_username(profile["email"]),
        email=profile["email"],
        first_name=profile["first_name"],
        last_name=profile["last_name"],
    )
    user.set_unusable_password()
    user.save(update_fields=["password"])
    try:
        from core.billing import get_or_create_subscription

        get_or_create_subscription(user)
    except Exception:
        logger.exception("starter subscription create failed user=%s", user.pk)
    return user


def find_or_create_user(profile: dict) -> tuple[User, bool]:
    """Same verified email -> same account, whether it signs in on the web or in the app."""
    user = User.objects.filter(email__iexact=profile["email"]).order_by("id").first()
    if user is None:
        return _create_user(profile), True
    if not user.is_active:
        raise SocialLoginError("inactive")
    return user, False


@require_GET
def social_login_callback(request: HttpRequest, provider_name: str):
    provider = PROVIDERS.get(provider_name)
    if provider is None:
        raise Http404
    from core import social_mobile

    mobile = social_mobile.handle_callback(request, provider)
    if mobile is not None:
        return mobile

    pending = request.session.pop(_SESSION_KEY, None) or {}
    origin = pending.get("origin") or "login"
    button = pending.get("button") or provider.name

    state = request.GET.get("state") or ""
    if not pending.get("state") or not secrets.compare_digest(pending["state"], state):
        return _back(origin, "state_mismatch", button)
    if BUTTONS.get(button, ("",))[0] != provider.name:
        return _back(origin, "state_mismatch", button)
    code = request.GET.get("code") or ""
    if request.GET.get("error") or not code:
        return _back(origin, "cancelled", button)

    try:
        profile = fetch_profile(provider, code, redirect_uri_for(request, provider))
        user, created = find_or_create_user(profile)
    except SocialLoginError as e:
        return _back(origin, str(e), button)
    except Exception:
        logger.exception("social login failed provider=%s", provider.name)
        return _back(origin, "failed", button)

    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    log_audit(request, "signup_social" if created else "login_social", button)

    from core.auth_views import post_login_redirect_url

    return redirect(post_login_redirect_url(request, user, next_url=pending.get("next")))


def _firebase_button(value) -> str:
    """Button the user pressed (for error labels only; the token decides the real provider)."""
    return value if value in FIREBASE_SIGN_IN_PROVIDERS.values() else "google"


def _json_body(request: HttpRequest) -> dict:
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _firebase_sign_in_from(body: dict) -> tuple[dict, str]:
    return verify_firebase_sign_in(
        str(body.get("id_token") or "").strip(),
        provider_access_token=str(body.get("access_token") or "").strip(),
    )


@ensure_csrf_cookie
@require_http_methods(["GET", "POST"])
def social_firebase_app(request: HttpRequest):
    """Google / GitHub via Firebase for app builds without a native SDK (Expo Go, GitHub).

    GET renders a page with the provider button (the popup needs a tap); POST trades the
    Firebase ID token for a one-time code and returns the ``return_to`` deep link.
    """
    from core import social_mobile
    from core.gmail_mobile_oauth import is_allowed_return_to, with_query

    if request.method == "GET":
        return_to = (request.GET.get("return_to") or "").strip()
        button = _firebase_button(request.GET.get("provider"))
        return render(
            request,
            "social_firebase_app.html",
            {
                "return_to": return_to,
                "return_to_ok": is_allowed_return_to(return_to),
                "provider": button,
                "provider_label": LABELS[button],
            },
        )

    body = _json_body(request)
    return_to = str(body.get("return_to") or "").strip()
    if not is_allowed_return_to(return_to):
        return JsonResponse({"ok": False, "error": "invalid_return_to"}, status=400)
    button = _firebase_button(body.get("provider"))
    try:
        profile, button = _firebase_sign_in_from(body)
        user, created = find_or_create_user(profile)
    except SocialLoginError as e:
        url = with_query(return_to, {"status": "error", "error": str(e), "provider": button})
        return JsonResponse({"ok": False, "error": str(e), "redirect": url}, status=400)
    except Exception:
        logger.exception("firebase app login failed")
        url = with_query(return_to, {"status": "error", "error": "failed", "provider": button})
        return JsonResponse({"ok": False, "error": "failed", "redirect": url}, status=400)

    log_audit(request, "signup_social" if created else "login_social", f"{button} firebase app user={user.id}")
    return JsonResponse({"ok": True, "redirect": social_mobile.app_return_url(return_to, user, created, button)})


@require_POST
def social_firebase_login(request: HttpRequest):
    """Google / GitHub buttons on the website: Firebase popup ID token -> Django session."""
    body = _json_body(request)
    origin = "signup" if body.get("from") == "signup" else "login"
    button = _firebase_button(body.get("provider"))
    try:
        profile, button = _firebase_sign_in_from(body)
        user, created = find_or_create_user(profile)
    except SocialLoginError as e:
        return JsonResponse({"ok": False, "error": str(e), "redirect": _back_url(origin, str(e), button)}, status=400)
    except Exception:
        logger.exception("firebase web login failed")
        return JsonResponse({"ok": False, "error": "failed", "redirect": _back_url(origin, "failed", button)}, status=400)

    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    log_audit(request, "signup_social" if created else "login_social", f"{button} firebase")

    from core.auth_views import post_login_redirect_url

    next_url = str(body.get("next") or "")[:500]
    return JsonResponse({"ok": True, "created": created, "redirect": post_login_redirect_url(request, user, next_url=next_url)})
