"""Build per-user email_automation Settings from DB + env defaults."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from django.conf import settings as dj_settings
from pydantic import SecretStr, ValidationError

from core.crypto import decrypt_str, encrypt_str

if TYPE_CHECKING:
    from django.contrib.auth.models import User


def user_data_dir(user_id: int) -> Path:
    base = Path(dj_settings.BASE_DIR) / "data" / "users" / str(user_id)
    base.mkdir(parents=True, exist_ok=True)
    return base


def token_path_for_user(user_id: int) -> str:
    return str(user_data_dir(user_id) / "token.json")


def client_secret_path_for_user(user_id: int) -> str:
    return str(user_data_dir(user_id) / "client_secret.json")


def get_or_create_mail_settings(user: User):
    from core.models import UserMailSettings

    o, _ = UserMailSettings.objects.get_or_create(user=user, defaults={"settings_json": {}})
    return o


def _write_file_if_needed(path: str, content: str) -> None:
    if not content.strip():
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def sync_encrypted_files_to_disk(user_id: int, ms) -> None:
    """Write decrypted OAuth token and client secret JSON to user-scoped paths for libraries that expect files."""
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


def build_effective_settings(user: User):
    """Return email_automation.settings.Settings for this user."""
    from email_automation.settings import Settings

    from core.models import UserMailSettings

    def _derive_imap_from_smtp(d: dict[str, Any]) -> dict[str, Any]:
        """
        Dashboard reads inbox via IMAP when SEND_TRANSPORT=smtp.
        Setup UI stores SMTP creds and expects IMAP to use the same user/pass.
        Derive IMAP_* fields from SMTP_* when missing so inbox can load reliably.
        """
        out = dict(d or {})
        if str(out.get("SEND_TRANSPORT") or "").strip() != "smtp":
            return out

        smtp_host = str(out.get("SMTP_HOST") or "").strip()
        smtp_user = str(out.get("SMTP_USERNAME") or "").strip()
        smtp_pass = out.get("SMTP_PASSWORD")

        if smtp_host and not str(out.get("IMAP_HOST") or "").strip():
            host_l = smtp_host.lower()
            if host_l.startswith("smtp."):
                domain = smtp_host[5:]
            else:
                parts = smtp_host.split(".", 1)
                domain = parts[1] if len(parts) == 2 else smtp_host
            if domain:
                out["IMAP_HOST"] = f"imap.{domain}"

        if smtp_user and not str(out.get("IMAP_USERNAME") or "").strip():
            out["IMAP_USERNAME"] = smtp_user

        imap_pass = out.get("IMAP_PASSWORD")
        imap_pass_str = ""
        try:
            imap_pass_str = (
                imap_pass.get_secret_value() if hasattr(imap_pass, "get_secret_value") else str(imap_pass or "")
            )
        except Exception:
            imap_pass_str = str(imap_pass or "")
        if smtp_pass is not None and (imap_pass is None or not str(imap_pass_str).strip()):
            out["IMAP_PASSWORD"] = smtp_pass

        if out.get("IMAP_PORT") in (None, "", 0):
            out["IMAP_PORT"] = 993

        # Carry over TLS servername to IMAP if present.
        if str(out.get("SMTP_TLS_SERVERNAME") or "").strip() and not str(out.get("IMAP_TLS_SERVERNAME") or "").strip():
            out["IMAP_TLS_SERVERNAME"] = str(out.get("SMTP_TLS_SERVERNAME") or "").strip()

        return out

    base = Settings()
    try:
        ms = UserMailSettings.objects.get(user=user)
    except UserMailSettings.DoesNotExist:
        merged = base.model_dump(mode="python")
        merged["GOOGLE_TOKEN_FILE"] = token_path_for_user(user.id)
        merged["GOOGLE_CLIENT_SECRET_FILE"] = client_secret_path_for_user(user.id)
        merged = _derive_imap_from_smtp(merged)
        return Settings.model_validate(merged)

    sync_encrypted_files_to_disk(user.id, ms)

    patch: dict[str, Any] = dict(ms.settings_json or {})
    if ms.smtp_password_enc:
        patch["SMTP_PASSWORD"] = SecretStr(decrypt_str(ms.smtp_password_enc))
    if ms.imap_password_enc:
        patch["IMAP_PASSWORD"] = SecretStr(decrypt_str(ms.imap_password_enc))
    if ms.llm_api_key_enc:
        patch["LLM_API_KEY"] = SecretStr(decrypt_str(ms.llm_api_key_enc))

    merged = base.model_dump(mode="python")
    merged.update({k: v for k, v in patch.items() if k in Settings.model_fields})
    merged["GOOGLE_TOKEN_FILE"] = token_path_for_user(user.id)
    merged["GOOGLE_CLIENT_SECRET_FILE"] = client_secret_path_for_user(user.id)
    merged = _derive_imap_from_smtp(merged)

    # Per-user VECTOR_DB_DSN can include schema or we scope by tenant_id in DSN — use same DSN, tenant in tables
    try:
        return Settings.model_validate(merged)
    except ValidationError:
        return Settings.model_validate(base.model_dump(mode="python"))


def save_settings_patch(user: User, patch: dict[str, Any]) -> None:
    """Merge non-secret keys into settings_json; extract secrets to encrypted columns."""
    from core.models import UserMailSettings

    secret_keys = {"SMTP_PASSWORD", "IMAP_PASSWORD", "LLM_API_KEY"}
    ms = get_or_create_mail_settings(user)
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


def save_google_token_json(user: User, token_json: str) -> None:
    from core.models import UserMailSettings

    ms = get_or_create_mail_settings(user)
    ms.google_oauth_token_enc = encrypt_str(token_json)
    ms.save()
    sync_encrypted_files_to_disk(user.id, ms)


def save_client_secret_json(user: User, secret_json: str) -> None:
    from core.models import UserMailSettings

    ms = get_or_create_mail_settings(user)
    ms.client_secret_json_enc = encrypt_str(secret_json)
    ms.save()
    sync_encrypted_files_to_disk(user.id, ms)


def migrate_legacy_file_config_if_needed(user: User) -> None:
    """One-time: copy global data/app_config.json into first user's settings if user has empty DB row."""
    # IMPORTANT: Do NOT auto-provision legacy/global SMTP/IMAP credentials for newly created users.
    # This could make a brand-new account appear "connected" without user intent.
    #
    # If you need the old behavior (e.g. single-tenant migration), explicitly enable it via env:
    #   MAILPILOT_MIGRATE_LEGACY_CONFIG=1
    if (os.environ.get("MAILPILOT_MIGRATE_LEGACY_CONFIG") or "").strip().lower() not in ("1", "true", "yes"):
        return

    from django.conf import settings as dj

    from core.models import UserMailSettings

    legacy = Path(dj.BASE_DIR) / "data" / "app_config.json"
    if not legacy.exists():
        return
    ms, created = UserMailSettings.objects.get_or_create(user=user, defaults={"settings_json": {}})
    if not created and (ms.settings_json or ms.smtp_password_enc):
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

    legacy_token = Path(dj.BASE_DIR) / "data" / "token.json"
    if legacy_token.exists():
        try:
            t = legacy_token.read_text(encoding="utf-8")
            if t.strip():
                ms.google_oauth_token_enc = encrypt_str(t)
                ms.save()
        except Exception:
            pass
    sync_encrypted_files_to_disk(user.id, ms)
