from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from core.models import Notification, PushDevice
from core.notifications.channels.expo_push import is_expo_token
from core.notifications.preferences import get_preferences, save_preferences
from core.notifications.presence import mark_seen

# JWT for the mobile app, session (+ CSRF) for the web bell.
_AUTH = [JWTAuthentication, SessionAuthentication]
_PERM = [IsAuthenticated]

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100


def _serialize(n: Notification) -> dict[str, Any]:
    return {
        "id": n.pk,
        "event": n.event,
        "title": n.title,
        "body": n.body,
        "data": n.data or {},
        "account_id": n.account_id,
        "read": n.read_at is not None,
        "read_at": n.read_at.isoformat() if n.read_at else None,
        "created_at": n.created_at.isoformat(),
    }


def _int_param(raw: Any, default: int | None) -> int | None:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


@extend_schema(
    parameters=[
        OpenApiParameter("unread", OpenApiTypes.BOOL, description="Only unread notifications"),
        OpenApiParameter("cursor", OpenApiTypes.INT, description="`next_cursor` from the previous page"),
        OpenApiParameter("limit", OpenApiTypes.INT, description="Page size (max 100, default 20)"),
    ],
    responses=OpenApiTypes.OBJECT,
)
@api_view(["GET"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def notifications_list(request):
    qs = Notification.objects.filter(user=request.user).order_by("-id")
    if str(request.query_params.get("unread") or "").lower() in ("1", "true", "yes"):
        qs = qs.filter(read_at__isnull=True)
    cursor = _int_param(request.query_params.get("cursor"), None)
    if cursor is not None:
        qs = qs.filter(id__lt=cursor)
    limit = max(1, min(_int_param(request.query_params.get("limit"), _DEFAULT_LIMIT) or _DEFAULT_LIMIT, _MAX_LIMIT))
    page = list(qs[: limit + 1])
    has_more = len(page) > limit
    page = page[:limit]
    unread = Notification.objects.filter(user=request.user, read_at__isnull=True).count()
    return Response(
        {
            "ok": True,
            "items": [_serialize(n) for n in page],
            "next_cursor": page[-1].pk if has_more and page else None,
            "unread_count": unread,
        }
    )


@extend_schema(responses=OpenApiTypes.OBJECT, description="Cheap poll target; also marks the user as active.")
@api_view(["GET"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def notifications_unread_count(request):
    mark_seen(request.user)
    qs = Notification.objects.filter(user=request.user)
    latest = qs.order_by("-id").first()
    return Response(
        {
            "ok": True,
            "unread_count": qs.filter(read_at__isnull=True).count(),
            "latest": _serialize(latest) if latest else None,
        }
    )


@extend_schema(request=None, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def notification_read(request, notification_id: int):
    n = Notification.objects.filter(pk=notification_id, user=request.user).first()
    if n is None:
        return Response({"ok": False, "error": "not_found"}, status=status.HTTP_404_NOT_FOUND)
    if n.read_at is None:
        n.read_at = timezone.now()
        n.save(update_fields=["read_at"])
    return Response({"ok": True, "notification": _serialize(n)})


@extend_schema(request=None, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def notifications_read_all(request):
    updated = Notification.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
    return Response({"ok": True, "updated": updated})


@extend_schema(
    methods=["PUT", "PATCH"],
    request=OpenApiTypes.OBJECT,
    responses=OpenApiTypes.OBJECT,
    description="Partial update of `in_app`, `push`, `external_mode` (off/always/fallback), "
    "`events` {draft, sent, error} and `quiet_hours` {enabled, start, end}.",
)
@extend_schema(methods=["GET"], responses=OpenApiTypes.OBJECT)
@api_view(["GET", "PUT", "PATCH"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def notification_preferences(request):
    if request.method == "GET":
        return Response({"ok": True, "preferences": get_preferences(request.user)})
    if not isinstance(request.data, dict):
        return Response({"ok": False, "error": "expected_object"}, status=status.HTTP_400_BAD_REQUEST)
    return Response({"ok": True, "preferences": save_preferences(request.user, dict(request.data))})


@extend_schema(
    request=OpenApiTypes.OBJECT,
    responses=OpenApiTypes.OBJECT,
    description="Register an Expo push token: `expo_token`, `platform` (ios/android), optional `device_name`.",
)
@api_view(["POST"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def device_register(request):
    token = str(request.data.get("expo_token") or "").strip()
    if not is_expo_token(token):
        return Response({"ok": False, "error": "invalid_expo_token"}, status=status.HTTP_400_BAD_REQUEST)
    platform = str(request.data.get("platform") or "").strip().lower()
    if platform not in (PushDevice.PLATFORM_IOS, PushDevice.PLATFORM_ANDROID):
        platform = ""
    device_name = str(request.data.get("device_name") or "").strip()[:120]
    with transaction.atomic():
        device, created = PushDevice.objects.select_for_update().get_or_create(
            expo_token=token,
            defaults={"user": request.user, "platform": platform, "device_name": device_name},
        )
        if not created:
            device.user = request.user
            device.platform = platform or device.platform
            device.device_name = device_name or device.device_name
            device.is_active = True
            device.save()
    mark_seen(request.user)
    return Response({"ok": True, "device_id": device.pk, "created": created})


@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def device_unregister(request):
    token = str(request.data.get("expo_token") or "").strip()
    if not token:
        return Response({"ok": False, "error": "expo_token_required"}, status=status.HTTP_400_BAD_REQUEST)
    updated = PushDevice.objects.filter(user=request.user, expo_token=token).update(is_active=False)
    return Response({"ok": True, "updated": updated})
