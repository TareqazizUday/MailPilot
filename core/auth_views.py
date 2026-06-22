from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.db.models import F
from django.contrib.auth import login, logout
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.models import User
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.core.validators import validate_email
from django.http import HttpRequest
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods
try:
    from django_ratelimit.decorators import ratelimit  # type: ignore
except Exception:  # pragma: no cover
    # Optional dependency: app should still run without rate limiting.
    def ratelimit(*args, **kwargs):  # type: ignore
        def _decorator(fn):
            return fn

        return _decorator

from core.audit import log_audit
from core.models import PasswordResetOTP

logger = logging.getLogger("mailpilot.auth")

_OTP_TTL = timedelta(minutes=15)


def post_login_redirect_url(request: HttpRequest, user, *, next_url: str | None = None) -> str:
    from django.conf import settings
    from django.utils.http import url_has_allowed_host_and_scheme

    admin_index = reverse("admin:index")
    nxt = (next_url or "").strip()
    if nxt and "/admin/login" in nxt.rstrip("/"):
        nxt = ""
    allowed_hosts = {request.get_host(), *settings.ALLOWED_HOSTS}
    if nxt and url_has_allowed_host_and_scheme(
        nxt,
        allowed_hosts=allowed_hosts,
        require_https=request.is_secure(),
    ):
        return nxt
    if user.is_staff or user.is_superuser:
        return admin_index
    return reverse("dashboard")


_OTP_MAX_ATTEMPTS = 5
_OTP_LENGTH = 6


def _otp_hmac(email: str, otp: str) -> str:
    raw = f"{email.strip().lower()}:{otp.strip()}"
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        raw.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _generate_otp_digits() -> str:
    n = secrets.randbelow(10**_OTP_LENGTH)
    return str(n).zfill(_OTP_LENGTH)


def _send_password_reset_otp_email(to_email: str, otp: str, *, hello_name: str) -> None:
    ttl_minutes = int(_OTP_TTL.total_seconds() // 60)
    ctx = {
        "otp": otp,
        "ttl_minutes": ttl_minutes,
        "hello_name": (hello_name or "").strip(),
    }
    subject = "MailPilot password reset code"
    text_body = render_to_string("emails/password_reset_otp.txt", ctx).strip() + "\n"
    html_body = render_to_string("emails/password_reset_otp.html", ctx)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to_email],
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send(fail_silently=False)


@csrf_protect
@ratelimit(key="ip", rate="5/h", method="POST", block=True)
@require_http_methods(["GET", "POST"])
def password_reset_request_view(request: HttpRequest):
    """Step 1: collect identifier (email/username) and send OTP."""
    if request.user.is_authenticated:
        return redirect(reverse("dashboard"))
    err = ""
    if request.method == "POST":
        identifier = (request.POST.get("identifier") or "").strip()[:254]
        if not identifier:
            err = "Email or username is required."
        if not err:
            user = None
            to_email = ""
            if "@" in identifier:
                try:
                    validate_email(identifier)
                except Exception:
                    err = "Please enter a valid email address."
                else:
                    user = User.objects.filter(email__iexact=identifier, is_active=True).first()
                    to_email = identifier.strip().lower()
            else:
                user = User.objects.filter(username__iexact=identifier, is_active=True).only("id", "email").first()
                to_email = (user.email or "").strip().lower() if user else ""

            if not err and user is not None and to_email:
                otp = _generate_otp_digits()
                PasswordResetOTP.objects.filter(email__iexact=to_email).delete()
                PasswordResetOTP.objects.create(
                    email=to_email,
                    otp_hash=_otp_hmac(to_email, otp),
                    expires_at=timezone.now() + _OTP_TTL,
                )
                try:
                    hello_name = (
                        (user.get_full_name() or "").strip()
                        or (user.first_name or "").strip()
                        or user.username
                    )
                    _send_password_reset_otp_email(to_email, otp, hello_name=hello_name)
                except Exception as ex:
                    logger.exception("password reset email failed: %s", ex)
                    PasswordResetOTP.objects.filter(email__iexact=to_email).delete()
                    err = "Could not send email. Check mail settings or try again later."
                else:
                    request.session["pwreset_email"] = to_email
                    log_audit(request, "password_reset_otp_sent", "")
                    messages.info(
                        request,
                        "We sent a verification code to your email.",
                    )
                    return redirect(reverse("password_reset_verify"))
                # Sending failed; show error on the same page (do not redirect to 'no account').
                return render(
                    request,
                    "registration/password_reset_form.html",
                    {"error": err, "identifier_value": identifier},
                )
            log_audit(request, "password_reset_request", "")
            return redirect(reverse("password_reset_done"))
    return render(
        request,
        "registration/password_reset_form.html",
        {
            "error": err,
            "identifier_value": (request.POST.get("identifier") or "").strip() if request.method == "POST" else "",
        },
    )


@csrf_protect
@ratelimit(key="ip", rate="30/m", method="POST", block=True)
@require_http_methods(["GET", "POST"])
def password_reset_verify_view(request: HttpRequest):
    """Step 2: verify OTP from email."""
    if request.user.is_authenticated:
        return redirect(reverse("dashboard"))
    email = (request.session.get("pwreset_email") or "").strip().lower()
    if not email:
        messages.warning(request, "Start by entering your email on the password reset page.")
        return redirect(reverse("password_reset"))

    err = ""
    if request.method == "POST":
        code = "".join(ch for ch in (request.POST.get("otp") or "") if ch.isdigit())
        if len(code) != _OTP_LENGTH:
            err = f"Enter the {_OTP_LENGTH}-digit code from your email."
        if not err:
            row = (
                PasswordResetOTP.objects.filter(email__iexact=email)
                .order_by("-created_at")
                .first()
            )
            if row is None or row.expires_at < timezone.now():
                err = "This code has expired. Request a new one."
                PasswordResetOTP.objects.filter(email__iexact=email).delete()
                del request.session["pwreset_email"]
            elif row.attempts >= _OTP_MAX_ATTEMPTS:
                err = "Too many incorrect attempts. Request a new code."
                PasswordResetOTP.objects.filter(email__iexact=email).delete()
                del request.session["pwreset_email"]
            elif not hmac.compare_digest(row.otp_hash, _otp_hmac(email, code)):
                PasswordResetOTP.objects.filter(pk=row.pk).update(attempts=F("attempts") + 1)
                err = "That code is not correct. Try again."
            else:
                user = User.objects.filter(email__iexact=email, is_active=True).first()
                if user is None:
                    del request.session["pwreset_email"]
                    return redirect(reverse("password_reset"))
                PasswordResetOTP.objects.filter(email__iexact=email).delete()
                del request.session["pwreset_email"]
                request.session["pwreset_uid"] = user.pk
                log_audit(request, "password_reset_otp_ok", "")
                messages.info(request, "Choose a new password for your account.")
                return redirect(reverse("password_reset_set"))

    return render(
        request,
        "registration/password_reset_verify.html",
        {"error": err, "email": email},
    )


@csrf_protect
@ratelimit(key="ip", rate="20/h", method="POST", block=True)
@require_http_methods(["GET", "POST"])
def password_reset_set_view(request: HttpRequest):
    """Step 3: set new password after OTP verified."""
    if request.user.is_authenticated:
        return redirect(reverse("dashboard"))
    uid = request.session.get("pwreset_uid")
    if not uid:
        messages.warning(request, "Verify your email code first.")
        return redirect(reverse("password_reset"))

    user = User.objects.filter(pk=uid, is_active=True).first()
    if user is None:
        request.session.pop("pwreset_uid", None)
        return redirect(reverse("password_reset"))

    if request.method == "POST":
        form = SetPasswordForm(user, request.POST)
        if form.is_valid():
            form.save()
            request.session.pop("pwreset_uid", None)
            request.session.cycle_key()
            log_audit(request, "password_reset_ok", "")
            messages.success(request, "Reset your pass")
            return redirect(reverse("login"))
    else:
        form = SetPasswordForm(user)

    return render(
        request,
        "registration/password_reset_set.html",
        {"form": form},
    )


@require_http_methods(["GET"])
def password_reset_complete_view(request: HttpRequest):
    return render(
        request,
        "registration/password_reset_complete.html",
        {"login_url": reverse("login")},
    )


@require_http_methods(["GET"])
def password_reset_done_view(request: HttpRequest):
    return render(request, "registration/password_reset_done.html")



@csrf_protect
@ratelimit(key="ip", rate="20/m", method="POST", block=True)
@require_http_methods(["GET", "POST"])
def login_view(request: HttpRequest):
    if request.user.is_authenticated:
        return redirect(
            post_login_redirect_url(request, request.user, next_url=request.GET.get("next"))
        )
    err = ""
    if request.method == "POST":
        from django.contrib.auth import authenticate

        identifier = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""
        username = identifier
        if "@" in identifier:
            u = (
                User.objects.filter(email__iexact=identifier)
                .only("username")
                .first()
            )
            if u is not None:
                username = u.username
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            log_audit(request, "login_ok", "")
            nxt = request.POST.get("next") or request.GET.get("next")
            return redirect(post_login_redirect_url(request, user, next_url=nxt))
        err = "Invalid username or password."
        log_audit(request, "login_failed", "")
    return render(request, "login.html", {"error": err, "next": request.GET.get("next") or ""})


@csrf_protect
@ratelimit(key="ip", rate="10/h", method="POST", block=True)
@require_http_methods(["GET", "POST"])
def signup_view(request: HttpRequest):
    if request.user.is_authenticated:
        return redirect(reverse("dashboard"))
    err = ""
    if request.method == "POST":
        first_name = (request.POST.get("first_name") or "").strip()[:150]
        last_name = (request.POST.get("last_name") or "").strip()[:150]
        email = (request.POST.get("email") or "").strip()[:254]
        terms_ok = (request.POST.get("terms") or "").strip().lower() in ("1", "true", "yes", "on")
        u = (request.POST.get("username") or "").strip()
        p1 = request.POST.get("password") or ""
        p2 = request.POST.get("password2") or ""
        if not first_name:
            err = "First name is required."
        elif not email:
            err = "Email is required."
        else:
            try:
                validate_email(email)
            except Exception:
                err = "Please enter a valid email address."

        if not err and not terms_ok:
            err = "You must agree to the Terms of Service and Privacy Policy."

        if not err:
            if len(p1) < 8:
                err = "Password must be at least 8 characters."
            elif p1 != p2:
                err = "Passwords do not match."

        if not err:
            if not u:
                base = slugify(email.split("@", 1)[0]) or "user"
                candidate = base
                i = 0
                while User.objects.filter(username__iexact=candidate).exists():
                    i += 1
                    candidate = f"{base}{i}"
                u = candidate
            elif len(u) < 3:
                err = "Username must be at least 3 characters."
            elif User.objects.filter(username__iexact=u).exists():
                err = "Username already taken."

        if not err and User.objects.filter(email__iexact=email).exists():
            err = "An account with this email already exists."

        if not err:
            user = User.objects.create_user(username=u, password=p1, email=email)
            user.first_name = first_name
            user.last_name = last_name
            user.save(update_fields=["first_name", "last_name"])
            try:
                from core.billing import get_or_create_subscription

                get_or_create_subscription(user)
            except Exception:
                logger.exception("starter subscription create failed user=%s", user.pk)
            login(request, user)
            log_audit(request, "signup", "")
            return redirect(reverse("dashboard"))
    return render(request, "signup.html", {"error": err})


@require_http_methods(["POST", "GET"])
def logout_view(request: HttpRequest):
    logout(request)
    return redirect(reverse("login"))
