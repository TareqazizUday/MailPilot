from __future__ import annotations

import logging

from django.contrib.auth import login, logout
from django.contrib.auth.models import User
from django.core.validators import validate_email
from django.http import HttpRequest
from django.shortcuts import redirect, render
from django.urls import reverse
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

logger = logging.getLogger("mailpilot.auth")


@csrf_protect
@ratelimit(key="ip", rate="20/m", method="POST", block=True)
@require_http_methods(["GET", "POST"])
def login_view(request: HttpRequest):
    if request.user.is_authenticated:
        return redirect(reverse("dashboard"))
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
            nxt = request.GET.get("next") or reverse("dashboard")
            return redirect(nxt)
        err = "Invalid username or password."
        log_audit(request, "login_failed", "")
    return render(request, "login.html", {"error": err})


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
            login(request, user)
            log_audit(request, "signup", "")
            return redirect(reverse("dashboard"))
    return render(request, "signup.html", {"error": err})


@require_http_methods(["POST", "GET"])
def logout_view(request: HttpRequest):
    logout(request)
    return redirect(reverse("login"))
