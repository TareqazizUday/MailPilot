from __future__ import annotations

import json
from typing import Any

from django.http import HttpResponseBase, JsonResponse
from django.core.cache import cache
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication
from drf_spectacular.utils import OpenApiTypes, extend_schema
from google_auth_oauthlib.flow import Flow

from core import views as legacy_views
from core import runtime
from core.user_settings import save_google_token_json

from api.v1 import serializers as sz


def _json_from_legacy(resp: HttpResponseBase) -> tuple[dict[str, Any], int]:
    code = int(getattr(resp, "status_code", 200) or 200)
    if isinstance(resp, JsonResponse):
        try:
            raw = resp.content.decode("utf-8") if getattr(resp, "content", None) else ""
            return (json.loads(raw or "{}") if raw else {}), code
        except Exception:
            return {"ok": False, "error": "invalid_json_from_legacy"}, status.HTTP_502_BAD_GATEWAY
    return {"ok": False, "error": "non_json_response_from_legacy"}, status.HTTP_502_BAD_GATEWAY


def _call_legacy_json(fn, drf_request, *args, **kwargs) -> Response:
    # Legacy views expect Django HttpRequest
    dj_req = getattr(drf_request, "_request", drf_request)
    legacy_resp = fn(dj_req, *args, **kwargs)
    payload, code = _json_from_legacy(legacy_resp)

    # Normalize: always return {ok, ...}. Keep legacy keys if present.
    if "ok" not in payload:
        payload = {"ok": code < 400, **payload}
    return Response(payload, status=code)


# All v1 endpoints are JWT-based and require an authenticated user.
_AUTH = [JWTAuthentication]
_PERM = [IsAuthenticated]


_RESP_GENERIC = OpenApiTypes.OBJECT


@extend_schema(
    request=sz.SetupCredentialsRequestSerializer,
    responses=sz.OkSerializer,
)
@api_view(["POST"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def setup_credentials(request):
    return _call_legacy_json(legacy_views.api_setup_credentials, request)


@extend_schema(responses=sz.GmailConnectionStatusResponseSerializer)
@api_view(["GET"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def gmail_connection_status(request):
    return _call_legacy_json(legacy_views.api_gmail_connection_status, request)


@extend_schema(request=None, responses=sz.OkSerializer)
@api_view(["POST"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def gmail_disconnect(request):
    return _call_legacy_json(legacy_views.api_gmail_disconnect, request)


@extend_schema(responses=sz.GmailInboxResponseSerializer)
@api_view(["GET"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def gmail_inbox(request):
    return _call_legacy_json(legacy_views.api_gmail_inbox, request)


@extend_schema(responses=_RESP_GENERIC)
@api_view(["GET"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def gmail_thread_detail(request, thread_id: str):
    return _call_legacy_json(legacy_views.api_gmail_thread_detail, request, thread_id=thread_id)


@extend_schema(request=None, responses=sz.TriggerPollResponseSerializer)
@api_view(["POST"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def trigger_poll(request):
    return _call_legacy_json(legacy_views.api_trigger_poll, request)


@extend_schema(responses=_RESP_GENERIC)
@api_view(["GET"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def kb_status(request):
    return _call_legacy_json(legacy_views.api_kb_status, request)


@extend_schema(
    request=sz.KBUploadJsonRequestSerializer,
    responses=sz.KBUploadJsonResponseSerializer,
)
@api_view(["POST"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def kb_upload_json(request):
    return _call_legacy_json(legacy_views.api_kb_upload_json, request)


@extend_schema(
    request=sz.KBCrawlRequestSerializer,
    responses=sz.KBCrawlResponseSerializer,
)
@api_view(["POST"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def kb_crawl(request):
    return _call_legacy_json(legacy_views.api_kb_crawl, request)


@extend_schema(responses=sz.PendingResponseSerializer)
@api_view(["GET"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def pending(request):
    return _call_legacy_json(legacy_views.api_pending, request)


@extend_schema(methods=["GET"], responses=sz.AdminConfigGetResponseSerializer)
@extend_schema(methods=["POST"], request=OpenApiTypes.OBJECT, responses=sz.AdminConfigPostResponseSerializer)
@api_view(["GET", "POST"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def admin_config(request):
    return _call_legacy_json(legacy_views.api_admin_config, request)


@extend_schema(request=None, responses=sz.SMTPTestResponseSerializer)
@api_view(["POST"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def smtp_test(request):
    return _call_legacy_json(legacy_views.api_smtp_test, request)


@extend_schema(responses=sz.SMTPStatusResponseSerializer)
@api_view(["GET"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def smtp_status(request):
    return _call_legacy_json(legacy_views.api_smtp_status, request)


@extend_schema(request=None, responses=sz.OkSerializer)
@api_view(["POST"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def smtp_disconnect(request):
    return _call_legacy_json(legacy_views.api_smtp_disconnect, request)


def _oauth_cache_key(user_id: int) -> str:
    return f"mailpilot:gmail_oauth_state:{user_id}"


@extend_schema(
    responses=sz.OAuthAuthorizeUrlResponseSerializer,
)
@api_view(["GET"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def gmail_oauth_authorize_url(request):
    """
    Mobile-friendly OAuth start: returns Google's authorization URL + state.
    The mobile app should open the URL in a browser/webview, then call `oauth/exchange` with the code.
    """
    try:
        effective = runtime.get_effective_settings(request.user)
        client_secret_path = effective.GOOGLE_CLIENT_SECRET_FILE
        callback_url = (effective.OAUTH_REDIRECT_URI or "").strip() or ""
        if not callback_url:
            # Mobile app should register a deep-link callback and set OAUTH_REDIRECT_URI per environment.
            return Response(
                {"ok": False, "error": "OAUTH_REDIRECT_URI_not_set"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        flow = Flow.from_client_secrets_file(
            client_secret_path,
            scopes=effective.gmail_scopes(),
            redirect_uri=callback_url.rstrip("/"),
            autogenerate_code_verifier=False,
        )
        authorization_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        cache.set(_oauth_cache_key(request.user.id), state, timeout=10 * 60)
        return Response({"ok": True, "authorization_url": authorization_url, "state": state})
    except Exception as e:
        return Response({"ok": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema(
    request=sz.OAuthExchangeRequestSerializer,
    responses=sz.OAuthExchangeResponseSerializer,
)
@api_view(["POST"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def gmail_oauth_exchange(request):
    """
    Mobile-friendly OAuth exchange: exchange `code` for tokens and save them for this user.
    """
    ser = sz.OAuthExchangeRequestSerializer(data=request.data)
    if not ser.is_valid():
        return Response({"ok": False, "error": ser.errors}, status=status.HTTP_400_BAD_REQUEST)
    code = ser.validated_data["code"]
    state = (ser.validated_data.get("state") or "").strip()
    expected = (cache.get(_oauth_cache_key(request.user.id)) or "").strip()
    if expected and state and state != expected:
        return Response({"ok": False, "error": "oauth_state_mismatch"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        effective = runtime.get_effective_settings(request.user)
        client_secret_path = effective.GOOGLE_CLIENT_SECRET_FILE
        callback_url = (effective.OAUTH_REDIRECT_URI or "").strip() or ""
        if not callback_url:
            return Response(
                {"ok": False, "error": "OAUTH_REDIRECT_URI_not_set"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        flow = Flow.from_client_secrets_file(
            client_secret_path,
            scopes=effective.gmail_scopes(),
            redirect_uri=callback_url.rstrip("/"),
            autogenerate_code_verifier=False,
        )
        flow.fetch_token(code=code)
        creds = flow.credentials
        save_google_token_json(request.user, creds.to_json())
        cache.delete(_oauth_cache_key(request.user.id))
        return Response({"ok": True})
    except Exception as e:
        return Response({"ok": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

