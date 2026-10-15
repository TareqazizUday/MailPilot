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
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from google_auth_oauthlib.flow import Flow

from core import views as legacy_views
from core import runtime
from core.mail_accounts import build_effective_settings
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
    # Legacy views expect Django HttpRequest with an authenticated user.
    # JWT auth lives on the DRF Request — sync user onto the underlying HttpRequest.
    dj_req = getattr(drf_request, "_request", drf_request)
    try:
        user = getattr(drf_request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            dj_req.user = user
    except Exception:
        pass
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
    request={"multipart/form-data": sz.SetupCredentialsRequestSerializer},
    responses={200: sz.MailAccountResponseSerializer, 400: sz.ErrorSerializer, 403: sz.ErrorSerializer},
    description="Save Gmail credentials on the user's first Gmail mailbox (created if missing; 403 "
    "`upgrade_required` when the plan has no free mailbox). "
    "Prefer `/mail-accounts/{account_id}/setup-credentials` for a specific mailbox.",
)
@api_view(["POST"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def setup_credentials(request):
    return _call_legacy_json(legacy_views.api_setup_credentials_json, request)


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
    request=sz.KBUploadTextRequestSerializer,
    responses=sz.KBUploadJsonResponseSerializer,
)
@api_view(["POST"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def kb_upload_text(request):
    return _call_legacy_json(legacy_views.api_kb_upload_text, request)


@extend_schema(
    request=sz.KBCrawlRequestSerializer,
    responses={200: sz.KBCrawlResponseSerializer, 400: sz.ErrorSerializer, 403: sz.ErrorSerializer},
    description="Start a background crawl. `start_url` must be a valid http:// or https:// URL (400 otherwise).",
)
@api_view(["POST"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def kb_crawl(request):
    return _call_legacy_json(legacy_views.api_kb_crawl, request)


@extend_schema(responses=sz.KBCrawlResponseSerializer)
@api_view(["GET"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def kb_crawl_status(request):
    return _call_legacy_json(legacy_views.api_kb_crawl_status, request)


@extend_schema(responses=sz.KBUploadJsonResponseSerializer)
@api_view(["GET"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def kb_export_bundle(request):
    return _call_legacy_json(legacy_views.api_kb_export_bundle, request)


@extend_schema(
    request=None,
    parameters=[OpenApiParameter("account_id", int, required=False)],
    responses={200: sz.KBClearResponseSerializer, 403: sz.ErrorSerializer},
)
@api_view(["POST"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def kb_clear(request):
    return _call_legacy_json(legacy_views.api_kb_clear, request)


@extend_schema(responses=sz.KBUploadJsonResponseSerializer)
@api_view(["GET"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def kb_export_json(request):
    return _call_legacy_json(legacy_views.api_kb_export_json, request)


@extend_schema(request=OpenApiTypes.OBJECT, responses=sz.KBUploadJsonResponseSerializer)
@api_view(["POST"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def kb_replace_json(request):
    return _call_legacy_json(legacy_views.api_kb_replace_json, request)


@extend_schema(responses=sz.PendingResponseSerializer)
@api_view(["GET"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def pending(request):
    return _call_legacy_json(legacy_views.api_pending, request)


@extend_schema(
    parameters=[OpenApiParameter("days", int, description="Days in the activity chart (1-31, default 7)")],
    responses=_RESP_GENERIC,
    description="Overview dashboard: mailbox health, processed totals, breakdown, daily chart, recent activity, usage.",
)
@api_view(["GET"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def dashboard_summary(request):
    return _call_legacy_json(legacy_views.api_dashboard_summary, request)


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


def _gmail_account_or_none(user, account_id):
    from core.mail_accounts import TRANSPORT_GMAIL, get_account

    try:
        acc = get_account(user, int(account_id))
    except (TypeError, ValueError):
        return None
    return acc if acc is not None and acc.transport == TRANSPORT_GMAIL else None


@extend_schema(
    parameters=[
        OpenApiParameter("account_id", int, required=True, description="Gmail mailbox to connect"),
        OpenApiParameter(
            "return_to",
            str,
            required=True,
            description="App URL opened after Google consent, with `status=ok&account_id=` or `status=error&error=`. "
            "Allowed: mailpilot://, exp://, exps://, http://localhost:8081, http://127.0.0.1:8081 or SITE_URL.",
        ),
    ],
    responses={200: sz.OAuthAuthorizeUrlResponseSerializer, 400: sz.ErrorSerializer, 404: sz.ErrorSerializer},
)
@api_view(["GET"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def gmail_oauth_authorize_url(request):
    """
    Per-mailbox OAuth start for the mobile app. Open `authorization_url` in a browser; Google returns to the
    website callback, which saves the token on the mailbox and redirects to `return_to`.
    """
    from core import gmail_mobile_oauth

    acc = _gmail_account_or_none(request.user, request.query_params.get("account_id"))
    if acc is None:
        return Response({"ok": False, "error": "not_found"}, status=status.HTTP_404_NOT_FOUND)
    return_to = (request.query_params.get("return_to") or "").strip()
    if not gmail_mobile_oauth.is_allowed_return_to(return_to):
        return Response({"ok": False, "error": "invalid_return_to"}, status=status.HTTP_400_BAD_REQUEST)
    try:
        effective = build_effective_settings(request.user, account_id=acc.id)
        redirect_uri = legacy_views._oauth_callback_url(request._request, effective)
        authorization_url, state = gmail_mobile_oauth.start(
            request.user, acc, redirect_uri=redirect_uri, return_to=return_to
        )
    except FileNotFoundError:
        return Response({"ok": False, "error": "client_secret_missing"}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return Response({"ok": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    cache.set(_oauth_cache_key(request.user.id), state, timeout=gmail_mobile_oauth.STATE_TTL_SECONDS)
    return Response({"ok": True, "authorization_url": authorization_url, "state": state})


@extend_schema(
    request=sz.OAuthExchangeRequestSerializer,
    responses={200: sz.OAuthExchangeResponseSerializer, 400: sz.ErrorSerializer, 404: sz.ErrorSerializer},
)
@api_view(["POST"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def gmail_oauth_exchange(request):
    """
    Exchange `code` for tokens. With `account_id` the token is saved on that Gmail mailbox,
    otherwise on the user-level token (legacy).
    """
    ser = sz.OAuthExchangeRequestSerializer(data=request.data)
    if not ser.is_valid():
        return Response({"ok": False, "error": ser.errors}, status=status.HTTP_400_BAD_REQUEST)
    code = ser.validated_data["code"]
    state = (ser.validated_data.get("state") or "").strip()
    expected = (cache.get(_oauth_cache_key(request.user.id)) or "").strip()
    if expected and state and state != expected:
        return Response({"ok": False, "error": "oauth_state_mismatch"}, status=status.HTTP_400_BAD_REQUEST)

    if ser.validated_data.get("account_id") is not None:
        return _exchange_for_account(request, ser.validated_data["account_id"], code=code, state=state)

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


def _exchange_for_account(request, account_id: int, *, code: str, state: str) -> Response:
    from core import gmail_mobile_oauth

    acc = _gmail_account_or_none(request.user, account_id)
    if acc is None:
        return Response({"ok": False, "error": "not_found"}, status=status.HTTP_404_NOT_FOUND)
    entry = gmail_mobile_oauth.pending(state)
    if entry and (entry.get("user_id") != request.user.id or entry.get("account_id") != acc.id):
        return Response({"ok": False, "error": "oauth_state_mismatch"}, status=status.HTTP_400_BAD_REQUEST)
    if entry:
        redirect_uri = str(entry.get("redirect_uri") or "")
    else:
        effective = build_effective_settings(request.user, account_id=acc.id)
        redirect_uri = legacy_views._oauth_callback_url(request._request, effective)
    err = gmail_mobile_oauth.exchange_and_save(acc, code=code, redirect_uri=redirect_uri)
    if err:
        return Response({"ok": False, "error": err}, status=status.HTTP_400_BAD_REQUEST)
    if entry:
        cache.delete(gmail_mobile_oauth.state_cache_key(state))
    cache.delete(_oauth_cache_key(request.user.id))
    return Response({"ok": True, "account_id": acc.id})

