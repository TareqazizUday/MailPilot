from __future__ import annotations

import logging
from typing import Any

import requests
from django.conf import settings
from django.http import HttpRequest

logger = logging.getLogger("mailpilot.recaptcha")

_VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"
_SESSION_LOGIN_FAILS = "login_fail_count"


def recaptcha_configured() -> bool:
    return bool(settings.RECAPTCHA_SITE_KEY and settings.RECAPTCHA_SECRET_KEY)


def login_fail_count(request: HttpRequest) -> int:
    try:
        return max(0, int(request.session.get(_SESSION_LOGIN_FAILS) or 0))
    except (TypeError, ValueError):
        return 0


def bump_login_fail_count(request: HttpRequest) -> int:
    n = login_fail_count(request) + 1
    request.session[_SESSION_LOGIN_FAILS] = n
    return n


def clear_login_fail_count(request: HttpRequest) -> None:
    if _SESSION_LOGIN_FAILS in request.session:
        del request.session[_SESSION_LOGIN_FAILS]


def should_show_login_captcha(request: HttpRequest) -> bool:
    """Show captcha on login whenever keys are configured (same as signup).

    LOGIN_CAPTCHA_AFTER_FAILS=0 (or unset progressive) => always.
    Set LOGIN_CAPTCHA_AFTER_FAILS to 1+ to only show after that many failed attempts.
    """
    if not recaptcha_configured():
        return False
    after = int(getattr(settings, "LOGIN_CAPTCHA_AFTER_FAILS", 0) or 0)
    if after <= 0:
        return True
    return login_fail_count(request) >= after


def should_show_signup_captcha() -> bool:
    return recaptcha_configured()


def verify_recaptcha(request: HttpRequest, *, required: bool) -> tuple[bool, str]:
    """Verify Google reCAPTCHA v2 token from POST.

    When required=False (captcha not shown), always passes.
    When keys are not configured, always passes (dev mode).
    """
    if not required:
        return True, ""
    if not recaptcha_configured():
        return True, ""

    token = (request.POST.get("g-recaptcha-response") or "").strip()
    if not token:
        return False, "Please confirm you are not a robot."

    remote_ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get(
        "REMOTE_ADDR", ""
    )
    data: dict[str, Any] = {
        "secret": settings.RECAPTCHA_SECRET_KEY,
        "response": token,
    }
    if remote_ip:
        data["remoteip"] = remote_ip

    try:
        resp = requests.post(_VERIFY_URL, data=data, timeout=8)
        payload = resp.json() if resp.content else {}
    except Exception as exc:
        logger.warning("reCAPTCHA verify request failed: %s", exc)
        return False, "Captcha verification failed. Please try again."

    if payload.get("success") is True:
        return True, ""

    logger.info("reCAPTCHA rejected: %s", payload.get("error-codes"))
    return False, "Captcha verification failed. Please try again."


def captcha_template_context(*, show: bool) -> dict[str, Any]:
    return {
        "show_recaptcha": bool(show and recaptcha_configured()),
        "RECAPTCHA_SITE_KEY": settings.RECAPTCHA_SITE_KEY,
    }
