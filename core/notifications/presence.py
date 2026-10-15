"""Tracks whether a user is currently active on web or in the app (used by the fallback rule)."""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

_WRITE_THROTTLE_SECONDS = 30


def online_window_seconds() -> int:
    return int(getattr(settings, "NOTIFY_FALLBACK_ONLINE_SECONDS", 120))


def mark_seen(user) -> None:
    if not getattr(user, "is_authenticated", False):
        return
    key = f"notif_seen:{user.pk}"
    if cache.get(key):
        return
    cache.set(key, 1, _WRITE_THROTTLE_SECONDS)
    from core.models import UserProfile

    now = timezone.now()
    if not UserProfile.objects.filter(user_id=user.pk).update(last_seen_at=now):
        UserProfile.objects.get_or_create(user_id=user.pk, defaults={"last_seen_at": now})


def is_online(user_id: int) -> bool:
    from core.models import UserProfile

    cutoff = timezone.now() - timedelta(seconds=online_window_seconds())
    return UserProfile.objects.filter(user_id=user_id, last_seen_at__gte=cutoff).exists()
