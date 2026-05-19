from __future__ import annotations

import os
from typing import TYPE_CHECKING, Optional, Tuple

from email_automation.settings import Settings

if TYPE_CHECKING:
    from django.contrib.auth.models import User


def is_invalid_grant_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    if "invalid_grant" in msg:
        return True
    err = getattr(exc, "error", None)
    if isinstance(err, str) and err.lower() == "invalid_grant":
        return True
    return False


def invalidate_gmail_oauth(settings: Settings, *, user: "User | None" = None) -> None:
    """Remove stale OAuth token file (and per-user DB field when user is set)."""
    token_path = (settings.GOOGLE_TOKEN_FILE or "").strip()
    if token_path and os.path.exists(token_path):
        try:
            os.remove(token_path)
        except OSError:
            pass
    if user is not None:
        try:
            from core.user_settings import get_or_create_mail_settings

            ms = get_or_create_mail_settings(user)
            if ms.google_oauth_token_enc:
                ms.google_oauth_token_enc = ""
                ms.save(update_fields=["google_oauth_token_enc", "updated_at"])
        except Exception:
            pass


def gmail_oauth_ready(settings: Settings) -> bool:
    token_path = (settings.GOOGLE_TOKEN_FILE or "").strip()
    if not token_path:
        return False
    return os.path.exists(token_path)


def gmail_oauth_try(settings: Settings) -> Tuple[bool, Optional[str]]:
    """Best-effort check that OAuth token exists.

    Full token validation requires live API calls; this shim only checks file presence.
    """
    if gmail_oauth_ready(settings):
        return True, None
    return False, "missing_token"

