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
            return {"nav_avatar_url": "", "support_unread_count": 0, "support_staff_unread_count": 0}

        from core.models import UserProfile
        from core.support import support_open_count_for_staff, support_unread_count_for_user

        prof, _ = UserProfile.objects.get_or_create(user=u)
        url = ""
        try:
            if prof.avatar and prof.avatar.name and prof.avatar.storage.exists(prof.avatar.name):
                url = prof.avatar.url
        except Exception:
            url = ""
        unread = 0
        staff_unread = 0
        try:
            unread = support_unread_count_for_user(u)
        except Exception:
            unread = 0
        if getattr(u, "is_staff", False):
            try:
                staff_unread = support_open_count_for_staff()
            except Exception:
                staff_unread = 0
        return {
            "nav_avatar_url": url,
            "support_unread_count": unread,
            "support_staff_unread_count": staff_unread,
        }
    except Exception:
        return {"nav_avatar_url": "", "support_unread_count": 0, "support_staff_unread_count": 0}

