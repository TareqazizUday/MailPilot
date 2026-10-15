from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db.models import F
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    parser_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from drf_spectacular.utils import OpenApiParameter, extend_schema

from api.v1 import serializers as sz
from core.audit import log_audit
from core.models import PasswordResetOTP, UserProfile

logger = logging.getLogger("mailpilot.api.v1.auth")

_OTP_TTL = timedelta(minutes=15)
_OTP_MAX_ATTEMPTS = 5
_OTP_LENGTH = 6
_RESET_TOKEN_TTL = 900  # seconds


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


def _tokens_for_user(user: User) -> dict:
    refresh = RefreshToken.for_user(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def _profile_payload(user: User, request=None) -> dict:
    from core.avatar import avatar_url as _avatar_url

    prof, _ = UserProfile.objects.get_or_create(user=user)
    avatar_url = _avatar_url(prof, request) or None
    return {
        "id": user.pk,
        "username": user.username,
        "email": user.email or "",
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
        "display_name": prof.display_name or "",
        "phone": prof.phone or "",
        "company": prof.company or "",
        "timezone": prof.timezone or "UTC",
        "notes": prof.notes or "",
        "avatar_url": avatar_url,
    }


class EmailOrUsernameTokenSerializer(TokenObtainPairSerializer):
    """Accept email or username in the `username` field (web login parity)."""

    def validate(self, attrs):
        identifier = (attrs.get("username") or "").strip()
        if "@" in identifier:
            u = User.objects.filter(email__iexact=identifier).only("username").first()
            if u is not None:
                attrs = {**attrs, "username": u.username}
        return super().validate(attrs)


class EmailOrUsernameTokenView(TokenObtainPairView):
    serializer_class = EmailOrUsernameTokenSerializer


@extend_schema(
    request=sz.SignupRequestSerializer,
    responses={201: sz.SignupResponseSerializer, 400: sz.ErrorSerializer},
)
@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([])
def signup(request):
    data = request.data if hasattr(request, "data") else {}
    first_name = str(data.get("first_name") or "").strip()[:150]
    last_name = str(data.get("last_name") or "").strip()[:150]
    email = str(data.get("email") or "").strip()[:254]
    terms_ok = str(data.get("terms") or "").strip().lower() in ("1", "true", "yes", "on")
    username = str(data.get("username") or "").strip()
    p1 = str(data.get("password") or "")
    p2 = str(data.get("password2") or "")

    err = ""
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
        if not username:
            base = slugify(email.split("@", 1)[0]) or "user"
            candidate = base
            i = 0
            while User.objects.filter(username__iexact=candidate).exists():
                i += 1
                candidate = f"{base}{i}"
            username = candidate
        elif len(username) < 3:
            err = "Username must be at least 3 characters."
        elif User.objects.filter(username__iexact=username).exists():
            err = "Username already taken."

    if not err and User.objects.filter(email__iexact=email).exists():
        err = "An account with this email already exists."

    if err:
        return Response({"ok": False, "error": err}, status=status.HTTP_400_BAD_REQUEST)

    user = User.objects.create_user(username=username, password=p1, email=email)
    user.first_name = first_name
    user.last_name = last_name
    user.save(update_fields=["first_name", "last_name"])
    try:
        from core.billing import get_or_create_subscription

        get_or_create_subscription(user)
    except Exception:
        logger.exception("starter subscription create failed user=%s", user.pk)

    UserProfile.objects.get_or_create(user=user)
    log_audit(request, "signup_api", "")
    tokens = _tokens_for_user(user)
    return Response({"ok": True, "user": _profile_payload(user, request), **tokens}, status=status.HTTP_201_CREATED)


def _send_reset_email(to_email: str, otp: str, hello_name: str) -> None:
    from core.auth_views import _send_password_reset_otp_email

    _send_password_reset_otp_email(to_email, otp, hello_name=hello_name)


@extend_schema(
    request=sz.PasswordResetRequestSerializer,
    responses={200: sz.PasswordResetRequestResponseSerializer, 400: sz.ErrorSerializer, 500: sz.ErrorSerializer},
)
@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([])
def password_reset_request(request):
    identifier = str(request.data.get("identifier") or "").strip()[:254]
    if not identifier:
        return Response({"ok": False, "error": "Email or username is required."}, status=400)

    user = None
    to_email = ""
    if "@" in identifier:
        try:
            validate_email(identifier)
        except Exception:
            return Response({"ok": False, "error": "Please enter a valid email address."}, status=400)
        user = User.objects.filter(email__iexact=identifier, is_active=True).first()
        to_email = identifier.strip().lower()
    else:
        user = User.objects.filter(username__iexact=identifier, is_active=True).only("id", "email").first()
        to_email = (user.email or "").strip().lower() if user else ""

    # Always return ok to avoid account enumeration; only send when user exists.
    if user is not None and to_email:
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
            _send_reset_email(to_email, otp, hello_name)
        except Exception as ex:
            logger.exception("password reset email failed: %s", ex)
            PasswordResetOTP.objects.filter(email__iexact=to_email).delete()
            return Response(
                {"ok": False, "error": "Could not send email. Check mail settings or try again later."},
                status=500,
            )
        log_audit(request, "password_reset_otp_sent_api", "")
        # Return full email so mobile verify can proceed without Django session.
        return Response({"ok": True, "email": to_email, "email_hint": to_email})

    return Response({"ok": True, "email": "", "email_hint": identifier})


@extend_schema(
    request=sz.PasswordResetVerifyRequestSerializer,
    responses={200: sz.PasswordResetVerifyResponseSerializer, 400: sz.ErrorSerializer},
)
@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([])
def password_reset_verify(request):
    email = str(request.data.get("email") or "").strip().lower()
    code = "".join(ch for ch in str(request.data.get("otp") or "") if ch.isdigit())
    if not email or len(code) != _OTP_LENGTH:
        return Response({"ok": False, "error": f"Enter the {_OTP_LENGTH}-digit code from your email."}, status=400)

    row = PasswordResetOTP.objects.filter(email__iexact=email).order_by("-created_at").first()
    if row is None or row.expires_at < timezone.now():
        PasswordResetOTP.objects.filter(email__iexact=email).delete()
        return Response({"ok": False, "error": "This code has expired. Request a new one."}, status=400)
    if row.attempts >= _OTP_MAX_ATTEMPTS:
        PasswordResetOTP.objects.filter(email__iexact=email).delete()
        return Response({"ok": False, "error": "Too many incorrect attempts. Request a new code."}, status=400)
    if not hmac.compare_digest(row.otp_hash, _otp_hmac(email, code)):
        PasswordResetOTP.objects.filter(pk=row.pk).update(attempts=F("attempts") + 1)
        return Response({"ok": False, "error": "That code is not correct. Try again."}, status=400)

    user = User.objects.filter(email__iexact=email, is_active=True).first()
    if user is None:
        return Response({"ok": False, "error": "Account not found."}, status=400)

    PasswordResetOTP.objects.filter(email__iexact=email).delete()
    reset_token = secrets.token_urlsafe(32)
    cache.set(f"pwreset:{reset_token}", user.pk, timeout=_RESET_TOKEN_TTL)
    log_audit(request, "password_reset_otp_ok_api", "")
    return Response({"ok": True, "reset_token": reset_token})


@extend_schema(
    request=sz.PasswordResetConfirmRequestSerializer,
    responses={200: sz.OkSerializer, 400: sz.ErrorSerializer},
)
@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([])
def password_reset_confirm(request):
    reset_token = str(request.data.get("reset_token") or "").strip()
    p1 = str(request.data.get("password") or "")
    p2 = str(request.data.get("password2") or "")
    uid = cache.get(f"pwreset:{reset_token}") if reset_token else None
    if not uid:
        return Response({"ok": False, "error": "Reset session expired. Start again."}, status=400)
    if len(p1) < 8:
        return Response({"ok": False, "error": "Password must be at least 8 characters."}, status=400)
    if p1 != p2:
        return Response({"ok": False, "error": "Passwords do not match."}, status=400)

    user = User.objects.filter(pk=uid, is_active=True).first()
    if user is None:
        cache.delete(f"pwreset:{reset_token}")
        return Response({"ok": False, "error": "Account not found."}, status=400)

    try:
        validate_password(p1, user=user)
    except ValidationError as ex:
        return Response({"ok": False, "error": "; ".join(ex.messages)}, status=400)

    user.set_password(p1)
    user.save(update_fields=["password"])
    cache.delete(f"pwreset:{reset_token}")
    log_audit(request, "password_reset_ok_api", "")
    return Response({"ok": True})


@extend_schema(methods=["GET"], responses={200: sz.UserProfileResponseSerializer})
@extend_schema(
    methods=["PATCH"],
    request=sz.ProfileUpdateRequestSerializer,
    responses={200: sz.UserProfileResponseSerializer, 400: sz.ErrorSerializer},
)
@api_view(["GET", "PATCH"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def me(request):
    if request.method == "GET":
        return Response({"ok": True, "user": _profile_payload(request.user, request)})

    data = request.data if hasattr(request, "data") else {}
    u = request.user
    if "first_name" in data:
        u.first_name = str(data.get("first_name") or "").strip()[:150]
    if "last_name" in data:
        u.last_name = str(data.get("last_name") or "").strip()[:150]
    if "email" in data:
        email = str(data.get("email") or "").strip()[:254]
        if email:
            try:
                validate_email(email)
            except Exception:
                return Response({"ok": False, "error": "Invalid email."}, status=400)
            if User.objects.filter(email__iexact=email).exclude(pk=u.pk).exists():
                return Response({"ok": False, "error": "Email already in use."}, status=400)
            u.email = email
    u.save()

    prof, _ = UserProfile.objects.get_or_create(user=u)
    for field, maxlen in (
        ("display_name", 120),
        ("phone", 32),
        ("company", 160),
        ("timezone", 64),
        ("notes", 2000),
    ):
        if field in data:
            setattr(prof, field, str(data.get(field) or "").strip()[:maxlen])
    if "timezone" in data and not (prof.timezone or "").strip():
        prof.timezone = "UTC"
    prof.save()
    log_audit(request, "profile_updated_api", "")
    return Response({"ok": True, "user": _profile_payload(u, request)})


@extend_schema(
    methods=["POST"],
    request={"multipart/form-data": sz.AvatarUploadRequestSerializer},
    responses={200: sz.UserProfileResponseSerializer, 400: sz.ErrorSerializer},
)
@extend_schema(methods=["DELETE"], request=None, responses={200: sz.UserProfileResponseSerializer})
@api_view(["POST", "DELETE"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def me_avatar(request):
    """Upload (multipart field `avatar`) or remove the signed-in user's profile photo."""
    from core.avatar import remove_avatar, save_avatar, validate_avatar

    prof, _ = UserProfile.objects.get_or_create(user=request.user)
    if request.method == "DELETE":
        remove_avatar(prof)
        log_audit(request, "avatar_removed_api", "")
        return Response({"ok": True, "user": _profile_payload(request.user, request)})

    upload = request.FILES.get("avatar")
    if upload is None:
        return Response({"ok": False, "error": "Attach an image in the `avatar` field."}, status=400)
    err = validate_avatar(upload)
    if err:
        return Response({"ok": False, "error": err}, status=400)
    save_avatar(prof, upload)
    log_audit(request, "avatar_updated_api", "")
    return Response({"ok": True, "user": _profile_payload(request.user, request)})


@extend_schema(
    request=sz.ChangePasswordRequestSerializer,
    responses={200: sz.OkSerializer, 400: sz.ErrorSerializer},
)
@api_view(["POST"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def change_password(request):
    current = str(request.data.get("current_password") or "")
    new = str(request.data.get("new_password") or "")
    if not request.user.check_password(current):
        return Response({"ok": False, "error": "Current password is incorrect."}, status=400)
    if len(new) < 8:
        return Response({"ok": False, "error": "Password must be at least 8 characters."}, status=400)
    try:
        validate_password(new, user=request.user)
    except ValidationError as ex:
        return Response({"ok": False, "error": "; ".join(ex.messages)}, status=400)
    request.user.set_password(new)
    request.user.save(update_fields=["password"])
    log_audit(request, "password_changed_api", "")
    return Response({"ok": True})


class SocialLoginThrottle(AnonRateThrottle):
    scope = "social_login"
    rate = "30/min"


_SOCIAL_ERROR_STATUS = {
    "unknown_provider": 404,
    "not_configured": 503,
    "inactive": 403,
    "invalid_token": 401,
}


def _social_error(code: str) -> Response:
    return Response({"ok": False, "error": code}, status=_SOCIAL_ERROR_STATUS.get(code, 400))


def _social_login_response(request, user: User, created: bool) -> Response:
    UserProfile.objects.get_or_create(user=user)
    return Response(
        {"ok": True, "created": created, "user": _profile_payload(user, request), **_tokens_for_user(user)}
    )


@extend_schema(request=None, responses={200: sz.SocialProvidersResponseSerializer})
@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([])
def social_providers(request):
    """Buttons the app can show; `configured=false` means the server has no keys for it yet."""
    from core.social_auth import configured_providers

    return Response({"ok": True, "providers": configured_providers()})


@extend_schema(
    request=None,
    parameters=[
        OpenApiParameter(
            "return_to",
            str,
            required=True,
            description="App deep link, e.g. `mailpilot://auth/social` (also `exp://`, `http://localhost:8081`).",
        )
    ],
    responses={
        200: sz.SocialAuthorizeUrlResponseSerializer,
        400: sz.ErrorSerializer,
        404: sz.ErrorSerializer,
        503: sz.ErrorSerializer,
    },
    description=(
        "Open `authorization_url` in a browser. After sign-in the server redirects to "
        "`return_to?status=ok&code=...&provider=...` (or `status=error&error=...`). "
        "Send `code` to `POST /api/v1/auth/social/exchange`."
    ),
)
@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([])
@throttle_classes([SocialLoginThrottle])
def social_authorize_url(request, provider: str):
    from core import social_mobile
    from core.social_auth import SocialLoginError

    try:
        url, state = social_mobile.start(request, provider, request.query_params.get("return_to") or "")
    except SocialLoginError as e:
        return _social_error(str(e))
    return Response({"ok": True, "authorization_url": url, "state": state})


@extend_schema(
    request=sz.SocialExchangeRequestSerializer,
    responses={200: sz.SocialLoginResponseSerializer, 400: sz.ErrorSerializer, 403: sz.ErrorSerializer},
)
@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([])
@throttle_classes([SocialLoginThrottle])
def social_exchange(request):
    """Trade the one-time deep-link `code` for JWT."""
    from core import social_mobile
    from core.social_auth import SocialLoginError

    try:
        user, created = social_mobile.redeem(str(request.data.get("code") or ""))
    except SocialLoginError as e:
        return _social_error(str(e))
    return _social_login_response(request, user, created)


@extend_schema(
    request=sz.SocialTokenRequestSerializer,
    responses={
        200: sz.SocialLoginResponseSerializer,
        400: sz.ErrorSerializer,
        401: sz.ErrorSerializer,
        403: sz.ErrorSerializer,
        503: sz.ErrorSerializer,
    },
    description=(
        "Native sign-in. `provider=firebase` with the Firebase `id_token` (Google or GitHub via Firebase Auth); "
        "GitHub also sends the GitHub OAuth `access_token` so the server can confirm a verified email. "
        "`provider=google` with a Google Sign-In `id_token`."
    ),
)
@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([])
@throttle_classes([SocialLoginThrottle])
def social_token(request):
    from core import social_mobile
    from core.social_auth import SocialLoginError, find_or_create_user

    provider = str(request.data.get("provider") or "").strip().lower()
    try:
        profile = social_mobile.verify_native_token(
            provider,
            id_token=str(request.data.get("id_token") or "").strip(),
            access_token=str(request.data.get("access_token") or "").strip(),
        )
        user, created = find_or_create_user(profile)
    except SocialLoginError as e:
        return _social_error(str(e))
    except Exception:
        logger.exception("native social login failed provider=%s", provider)
        return _social_error("failed")
    log_audit(request, "signup_social" if created else "login_social", f"{provider} native user={user.id}")
    return _social_login_response(request, user, created)
