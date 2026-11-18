"""Shared Gmail OAuth client config: .env vars and/or client_secret.json."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from django.conf import settings as dj_settings


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def shared_gmail_oauth_client_id() -> str:
    return _env("GOOGLE_OAUTH_CLIENT_ID") or _env("GMAIL_OAUTH_CLIENT_ID")


def shared_gmail_oauth_client_secret() -> str:
    return _env("GOOGLE_OAUTH_CLIENT_SECRET") or _env("GMAIL_OAUTH_CLIENT_SECRET")


def shared_gmail_client_secret_path() -> str:
    """Path to optional Web client JSON (fallback when env id/secret not set)."""
    raw = (
        _env("GMAIL_OAUTH_CLIENT_SECRET_FILE")
        or _env("GOOGLE_CLIENT_SECRET_FILE")
        or "client_secret.json"
    )
    p = Path(raw)
    if not p.is_absolute():
        p = Path(dj_settings.BASE_DIR) / p
    return str(p)


def _config_from_env() -> dict[str, Any] | None:
    client_id = shared_gmail_oauth_client_id()
    client_secret = shared_gmail_oauth_client_secret()
    if not client_id or not client_secret:
        return None
    redirect = _env("OAUTH_REDIRECT_URI") or "http://127.0.0.1:8000/api/gmail/oauth/callback"
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect],
        }
    }


def _config_from_file(path: str | None = None) -> dict[str, Any] | None:
    p = Path(path or shared_gmail_client_secret_path())
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if not (isinstance(data.get("web"), dict) or isinstance(data.get("installed"), dict)):
        return None
    return data


def shared_gmail_oauth_client_config() -> dict[str, Any] | None:
    """Prefer .env client id/secret; else Web/installed JSON file."""
    return _config_from_env() or _config_from_file()


def has_shared_gmail_oauth_client() -> bool:
    return shared_gmail_oauth_client_config() is not None


def load_oauth_client_config(secrets_file: str | None = None) -> dict[str, Any] | None:
    """Load config for a Flow: explicit file (BYO) first, else shared env/file."""
    if secrets_file and os.path.isfile(secrets_file):
        cfg = _config_from_file(secrets_file)
        if cfg is not None:
            return cfg
    return shared_gmail_oauth_client_config()


def build_gmail_oauth_flow(*, scopes: list[str], redirect_uri: str, secrets_file: str | None = None):
    """Create google_auth_oauthlib Flow from env and/or JSON file."""
    from google_auth_oauthlib.flow import Flow

    cfg = load_oauth_client_config(secrets_file)
    if cfg is None:
        raise FileNotFoundError("client_secret_missing")
    return Flow.from_client_config(
        cfg,
        scopes=scopes,
        redirect_uri=redirect_uri,
        autogenerate_code_verifier=False,
    )
