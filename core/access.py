"""API and page access control."""
from __future__ import annotations

import secrets

from django.http import JsonResponse

from core import runtime


def check_api_access(request) -> bool:
    """Require logged-in user, or valid X-Admin-Api-Key when ADMIN_API_KEY is set in env."""
    if request.user.is_authenticated:
        return True
    s = runtime.base_settings()
    if s.ADMIN_API_KEY is not None:
        provided = (request.headers.get("X-Admin-Api-Key") or "").strip()
        try:
            if provided and secrets.compare_digest(provided, s.ADMIN_API_KEY.get_secret_value()):
                return True
        except Exception:
            return False
    return False


def api_unauthorized():
    return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)
