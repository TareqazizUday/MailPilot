"""Microsoft Graph OAuth readiness helpers (token file / MailAccount)."""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from email_automation.settings import Settings

logger = logging.getLogger(__name__)


def microsoft_oauth_configured() -> bool:
    cid = (os.environ.get("MICROSOFT_OAUTH_CLIENT_ID") or "").strip()
    secret = (os.environ.get("MICROSOFT_OAUTH_CLIENT_SECRET") or "").strip()
    return bool(cid and secret)


def microsoft_oauth_ready(settings: Settings) -> bool:
    token_file = (settings.GOOGLE_TOKEN_FILE or "").strip()
    if not token_file or not os.path.isfile(token_file):
        return False
    try:
        with open(token_file, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return False
        # MSAL serialised cache or our compact token blob
        if data.get("access_token") or data.get("refresh_token"):
            return True
        if data.get("Account") or data.get("RefreshToken") or data.get("AccessToken"):
            return True
        return bool(data.get("token_cache") or data.get("home_account_id"))
    except Exception:
        return False


def load_token_blob(settings: Settings) -> dict[str, Any]:
    token_file = (settings.GOOGLE_TOKEN_FILE or "").strip()
    if not token_file or not os.path.isfile(token_file):
        return {}
    try:
        with open(token_file, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def invalidate_microsoft_oauth(settings: Settings, *, account=None) -> None:
    token_file = (settings.GOOGLE_TOKEN_FILE or "").strip()
    if token_file and os.path.isfile(token_file):
        try:
            os.remove(token_file)
        except OSError:
            pass
    if account is not None:
        try:
            from core.mail_accounts import clear_account_oauth

            clear_account_oauth(account)
        except Exception:
            logger.exception("clear microsoft oauth failed account=%s", getattr(account, "id", None))
