from __future__ import annotations

import os
from typing import TYPE_CHECKING, Optional, Tuple

from email_automation.settings import Settings

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from core.models import MailAccount


def is_invalid_grant_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    if "invalid_grant" in msg:
        return True
    err = getattr(exc, "error", None)
    if isinstance(err, str) and err.lower() == "invalid_grant":
        return True
    return False


def invalidate_gmail_oauth(
    settings: Settings,
    *,
    user: "User | None" = None,
    account: "MailAccount | None" = None,
) -> None:
    """Remove stale OAuth token file (and DB field when user/account is set)."""
    token_path = (settings.GOOGLE_TOKEN_FILE or "").strip()
    if token_path and os.path.exists(token_path):
        try:
            os.remove(token_path)
        except OSError:
            pass
    if account is not None:
        try:
            from core.mail_accounts import clear_account_oauth

            clear_account_oauth(account)
        except Exception:
            pass
        return
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
    """Best-effort check that OAuth token exists."""
    if gmail_oauth_ready(settings):
        return True, None
    return False, "missing_token"


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def gmail_profile_email(settings: Settings) -> str:
    """Authenticated Gmail address for this token file, or '' if unknown."""
    if not gmail_oauth_ready(settings):
        return ""
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        token_file = (settings.GOOGLE_TOKEN_FILE or "").strip()
        creds = Credentials.from_authorized_user_file(token_file, scopes=settings.gmail_scopes())
        svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return str(svc.users().getProfile(userId="me").execute().get("emailAddress") or "").strip()
    except Exception:
        return ""


def gmail_oauth_matches_configured(settings: Settings) -> Tuple[bool, str, str]:
    """
    True when OAuth profile email matches settings.GMAIL_ADDRESS (or either is unset).
    Returns (matches, profile_email, configured_email).
    """
    configured = _normalize_email(settings.GMAIL_ADDRESS or "")
    profile = _normalize_email(gmail_profile_email(settings))
    if not profile:
        return True, "", configured
    if not configured:
        return True, profile, configured
    return profile == configured, profile, configured
