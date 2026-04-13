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

        from core.models import UserProfile

        prof, _ = UserProfile.objects.get_or_create(user=u)
        url = ""
        try:
            if prof.avatar and prof.avatar.name and prof.avatar.storage.exists(prof.avatar.name):
                url = prof.avatar.url
        except Exception:
            url = ""
        return {"nav_avatar_url": url}
    except Exception:
        return {"nav_avatar_url": ""}

