"""Build per-user email_automation Settings from DB + env defaults."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from django.conf import settings as dj_settings
from pydantic import SecretStr

from core.crypto import decrypt_str, encrypt_str
from core.mail_accounts import (
    build_effective_settings,
    client_secret_path_for_user,
    ensure_legacy_migrated,
    get_or_create_mail_settings,
    save_account_client_secret,
    save_account_oauth_token,
    sync_account_files_to_disk,
    token_path_for_user,
    user_data_dir,
)

if TYPE_CHECKING:
    from django.contrib.auth.models import User

# Re-export paths for backward compatibility
__all__ = [
    "user_data_dir",
    "token_path_for_user",
    "client_secret_path_for_user",
    "get_or_create_mail_settings",
    "build_effective_settings",
    "save_settings_patch",
    "save_google_token_json",
    "save_client_secret_json",
    "migrate_legacy_file_config_if_needed",
    "sync_encrypted_files_to_disk",
]


def sync_encrypted_files_to_disk(user_id: int, ms) -> None:
    """Legacy: sync user-level + all account files."""
    from core.mail_accounts import list_accounts_for_user

    tp = token_path_for_user(user_id)
    if ms.google_oauth_token_enc:
        raw = decrypt_str(ms.google_oauth_token_enc)
        if raw.strip():
            _write_file_if_needed(tp, raw)
    sp = client_secret_path_for_user(user_id)
    if ms.client_secret_json_enc:
        raw = decrypt_str(ms.client_secret_json_enc)
        if raw.strip():
            _write_file_if_needed(sp, raw)
    for acc in list_accounts_for_user(ms.user):
        sync_account_files_to_disk(user_id, acc)


def _write_file_if_needed(path: str, content: str) -> None:
    if not content.strip():
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def save_settings_patch(user: User, patch: dict[str, Any]) -> None:
    """Merge non-secret keys into user-level settings_json; LLM key stays global."""
    secret_keys = {"SMTP_PASSWORD", "IMAP_PASSWORD", "LLM_API_KEY"}
    ms = get_or_create_mail_settings(user)
    ensure_legacy_migrated(user)
    data = dict(ms.settings_json or {})
    for k, v in patch.items():
        if k in secret_keys:
            continue
        if v is None:
            data.pop(k, None)
        else:
            data[k] = v
    ms.settings_json = data

    if "SMTP_PASSWORD" in patch:
        p = patch["SMTP_PASSWORD"]
        if p:
            s = p.get_secret_value() if hasattr(p, "get_secret_value") else str(p)
            ms.smtp_password_enc = encrypt_str(s)
        else:
            ms.smtp_password_enc = ""
    if "IMAP_PASSWORD" in patch:
        p = patch["IMAP_PASSWORD"]
        if p:
            s = p.get_secret_value() if hasattr(p, "get_secret_value") else str(p)
            ms.imap_password_enc = encrypt_str(s)
        else:
            ms.imap_password_enc = ""
    if "LLM_API_KEY" in patch:
        p = patch["LLM_API_KEY"]
        if p:
            s = p.get_secret_value() if hasattr(p, "get_secret_value") else str(p)
            ms.llm_api_key_enc = encrypt_str(s)
        else:
            ms.llm_api_key_enc = ""

    ms.save()

    # Also patch first SMTP account if exists (backward compat for admin config API)
    from core.mail_accounts import TRANSPORT_SMTP, list_accounts_for_user, patch_account_config, resolve_account

    acc = resolve_account(user, transport=TRANSPORT_SMTP)
    if acc and any(k.startswith("SMTP_") or k.startswith("IMAP_") for k in patch):
        patch_account_config(acc, patch)


def save_google_token_json(user: User, token_json: str) -> None:
    ms = get_or_create_mail_settings(user)
    ms.google_oauth_token_enc = encrypt_str(token_json)
    ms.save()
    ensure_legacy_migrated(user)
    from core.mail_accounts import TRANSPORT_GMAIL, resolve_account

    acc = resolve_account(user, transport=TRANSPORT_GMAIL)
    if acc:
        save_account_oauth_token(acc, token_json)
    sync_encrypted_files_to_disk(user.id, ms)


def save_client_secret_json(user: User, secret_json: str) -> None:
    ms = get_or_create_mail_settings(user)
    ms.client_secret_json_enc = encrypt_str(secret_json)
    ms.save()
    ensure_legacy_migrated(user)
    from core.mail_accounts import TRANSPORT_GMAIL, resolve_account

    acc = resolve_account(user, transport=TRANSPORT_GMAIL)
    if acc:
        save_account_client_secret(acc, secret_json)
    sync_encrypted_files_to_disk(user.id, ms)


def migrate_legacy_file_config_if_needed(user: User) -> None:
    if (os.environ.get("MAILPILOT_MIGRATE_LEGACY_CONFIG") or "").strip().lower() not in ("1", "true", "yes"):
        return

    legacy = Path(dj_settings.BASE_DIR) / "data" / "app_config.json"
    if not legacy.exists():
        return
    ms = get_or_create_mail_settings(user)
    if ms.settings_json or ms.smtp_password_enc:
        return
    try:
        raw = json.loads(legacy.read_text(encoding="utf-8"))
    except Exception:
        return
    secrets = {}
    for k in ("SMTP_PASSWORD", "IMAP_PASSWORD", "LLM_API_KEY"):
        if k in raw and raw[k]:
            secrets[k] = raw.pop(k)
    ms.settings_json = raw
    if "SMTP_PASSWORD" in secrets:
        ms.smtp_password_enc = encrypt_str(str(secrets["SMTP_PASSWORD"]))
    if "IMAP_PASSWORD" in secrets:
        ms.imap_password_enc = encrypt_str(str(secrets["IMAP_PASSWORD"]))
    if "LLM_API_KEY" in secrets:
        ms.llm_api_key_enc = encrypt_str(str(secrets["LLM_API_KEY"]))
    ms.save()

    legacy_token = Path(dj_settings.BASE_DIR) / "data" / "token.json"
    if legacy_token.exists():
        try:
            t = legacy_token.read_text(encoding="utf-8")
            if t.strip():
                ms.google_oauth_token_enc = encrypt_str(t)
                ms.save()
        except Exception:
            pass
    ensure_legacy_migrated(user)
    sync_encrypted_files_to_disk(user.id, ms)
