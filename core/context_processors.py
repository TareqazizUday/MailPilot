from __future__ import annotations

from typing import Any


def nav_context(request) -> dict[str, Any]:
    """
    Lightweight global context for app navigation (avatar, etc.).
    Keep this fast and safe: no exceptions should bubble into templates.
    """

    try:
        u = getattr(request, "user", None)
        if not u or not getattr(u, "is_authenticated", False):
            return {"nav_avatar_url": ""}

        from core.models import Notification, UserProfile

        prof, _ = UserProfile.objects.get_or_create(user=u)
        url = ""
        try:
            if prof.avatar and prof.avatar.name and prof.avatar.storage.exists(prof.avatar.name):
                url = prof.avatar.url
        except Exception:
            url = ""
        try:
            unread = Notification.objects.filter(user=u, read_at__isnull=True).count()
        except Exception:
            unread = 0
        return {"nav_avatar_url": url, "nav_unread_count": unread}
    except Exception:
        return {"nav_avatar_url": "", "nav_unread_count": 0}


def social_login_context(request) -> dict[str, Any]:
    """Firebase web config for the Google button (public values, env only)."""
    from core.social_auth import firebase_web_config

    return {"firebase_web": firebase_web_config()}

