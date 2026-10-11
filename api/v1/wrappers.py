from __future__ import annotations

from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication

from core import mail_account_views as ma_views
from core import views as legacy_views

from api.v1 import serializers as sz
from api.v1.views import _RESP_GENERIC, _call_legacy_json

_AUTH = [JWTAuthentication]
_PERM = [IsAuthenticated]


@extend_schema(operation_id="v1_mail_accounts_list", responses=_RESP_GENERIC)
@api_view(["GET"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def mail_accounts_list(request):
    return _call_legacy_json(ma_views.api_mail_accounts_list, request)


@extend_schema(request=OpenApiTypes.OBJECT, responses=_RESP_GENERIC)
@api_view(["POST"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def mail_accounts_create(request):
    return _call_legacy_json(ma_views.api_mail_accounts_create, request)


@extend_schema(
    methods=["GET"],
    responses={200: sz.MailAccountResponseSerializer, 404: sz.ErrorSerializer},
)
@extend_schema(
    methods=["PATCH"],
    request=OpenApiTypes.OBJECT,
    responses={200: sz.MailAccountResponseSerializer, 400: _RESP_GENERIC, 404: sz.ErrorSerializer},
    description="Partial update: `is_enabled`, `label`, and uppercase config keys "
    "(GMAIL_ADDRESS, SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, IMAP_*, ...).",
)
@extend_schema(
    methods=["DELETE"],
    request=None,
    responses={200: sz.OkSerializer, 404: sz.ErrorSerializer},
)
@api_view(["GET", "PATCH", "DELETE"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def mail_accounts_detail(request, account_id: int):
    return _call_legacy_json(ma_views.api_mail_accounts_detail, request, account_id=account_id)


@extend_schema(
    request={"multipart/form-data": sz.SetupCredentialsRequestSerializer},
    responses={200: sz.MailAccountResponseSerializer, 400: sz.ErrorSerializer, 404: sz.ErrorSerializer},
    description="Upload `gmail_address` + `client_secret` (.json) for one Gmail mailbox. "
    "Then call `/gmail/oauth/authorize-url?account_id=` to connect it.",
)
@api_view(["POST"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def mail_account_setup_credentials(request, account_id: int):
    return _call_legacy_json(ma_views.api_mail_account_setup_credentials_json, request, account_id=account_id)


@extend_schema(request=None, responses=_RESP_GENERIC)
@api_view(["POST"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def mail_account_test_smtp(request, account_id: int):
    return _call_legacy_json(ma_views.api_mail_account_test_smtp, request, account_id=account_id)


@extend_schema(request=None, responses=_RESP_GENERIC)
@api_view(["POST"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def mail_account_disconnect_gmail(request, account_id: int):
    return _call_legacy_json(ma_views.api_mail_account_disconnect_gmail, request, account_id=account_id)


@extend_schema(request=OpenApiTypes.OBJECT, responses=_RESP_GENERIC)
@api_view(["POST"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def transport_mode(request):
    return _call_legacy_json(ma_views.api_transport_mode, request)


@extend_schema(responses=_RESP_GENERIC)
@api_view(["GET"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def billing_summary(request):
    return _call_legacy_json(legacy_views.api_billing_summary, request)


@extend_schema(request=OpenApiTypes.OBJECT, responses=_RESP_GENERIC)
@api_view(["POST"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def billing_select_plan(request):
    return _call_legacy_json(legacy_views.api_billing_select_plan, request)


@extend_schema(responses=_RESP_GENERIC)
@api_view(["GET"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def telegram_status(request):
    return _call_legacy_json(legacy_views.api_telegram_status, request)


@extend_schema(request=OpenApiTypes.OBJECT, responses=_RESP_GENERIC)
@api_view(["POST"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def telegram_config(request):
    return _call_legacy_json(legacy_views.api_telegram_config, request)


@extend_schema(request=None, responses=_RESP_GENERIC)
@api_view(["POST"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def telegram_test(request):
    return _call_legacy_json(legacy_views.api_telegram_test, request)


@extend_schema(responses=_RESP_GENERIC)
@api_view(["GET"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def whatsapp_status(request):
    return _call_legacy_json(legacy_views.api_whatsapp_status, request)


@extend_schema(request=OpenApiTypes.OBJECT, responses=_RESP_GENERIC)
@api_view(["POST"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def whatsapp_config(request):
    return _call_legacy_json(legacy_views.api_whatsapp_config, request)


@extend_schema(request=None, responses=_RESP_GENERIC)
@api_view(["POST"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def whatsapp_test(request):
    return _call_legacy_json(legacy_views.api_whatsapp_test, request)
