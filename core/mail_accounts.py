"""Multi-mailbox accounts: slots, transport mode, settings merge, tenant scoping."""
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

    from core.models import MailAccount, UserMailSettings

MAX_SLOTS_PER_TRANSPORT = 5


def max_active_accounts() -> int:
    try:
        return max(1, min(20, int(os.environ.get("MAILPILOT_MAX_ACTIVE_ACCOUNTS", "5"))))
    except ValueError:
        return MAX_SLOTS_PER_TRANSPORT


def count_enabled(user: User, transport: str) -> int:
    return list_accounts_for_user(user, transport=transport).filter(is_enabled=True).count()


def can_enable_more(user: User, transport: str, *, excluding_account_id: int | None = None) -> bool:
    qs = list_accounts_for_user(user, transport=transport).filter(is_enabled=True)
    if excluding_account_id:
        qs = qs.exclude(pk=excluding_account_id)
    return qs.count() < max_active_accounts()


TRANSPORT_GMAIL = "gmail_api"
TRANSPORT_SMTP = "smtp"
MODE_GMAIL = "gmail"
MODE_SMTP = "smtp"


def user_data_dir(user_id: int) -> Path:
    base = Path(dj_settings.BASE_DIR) / "data" / "users" / str(user_id)
    base.mkdir(parents=True, exist_ok=True)
    return base


def account_data_dir(user_id: int, account_id: int) -> Path:
    p = user_data_dir(user_id) / "accounts" / str(account_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def token_path_for_account(user_id: int, account_id: int) -> str:
    return str(account_data_dir(user_id, account_id) / "token.json")


def client_secret_path_for_account(user_id: int, account_id: int) -> str:
    return str(account_data_dir(user_id, account_id) / "client_secret.json")


def token_path_for_user(user_id: int) -> str:
    """Legacy path (migration / fallback)."""
    return str(user_data_dir(user_id) / "token.json")


def client_secret_path_for_user(user_id: int) -> str:
    return str(user_data_dir(user_id) / "client_secret.json")


def tenant_id_for_account(user_id: int, account_id: int) -> str:
    return f"{user_id}:{account_id}"


def transport_for_mode(mode: str) -> str:
    return TRANSPORT_SMTP if mode == MODE_SMTP else TRANSPORT_GMAIL


def mode_for_transport(transport: str) -> str:
    return MODE_SMTP if transport == TRANSPORT_SMTP else MODE_GMAIL


def get_or_create_mail_settings(user: User) -> UserMailSettings:
    from core.models import UserMailSettings

    o, _ = UserMailSettings.objects.get_or_create(
        user=user,
        defaults={"settings_json": {}, "active_transport_mode": MODE_GMAIL},
    )
    return o


def active_transport_mode(user: User) -> str:
    ms = get_or_create_mail_settings(user)
    mode = str(ms.active_transport_mode or "").strip()
    if mode in (MODE_GMAIL, MODE_SMTP):
        return mode
    sj = dict(ms.settings_json or {})
    st = str(sj.get("SEND_TRANSPORT") or "").strip()
    return MODE_SMTP if st == TRANSPORT_SMTP else MODE_GMAIL


def set_active_transport_mode(user: User, mode: str) -> None:
    if mode not in (MODE_GMAIL, MODE_SMTP):
        raise ValueError("mode must be gmail or smtp")
    ms = get_or_create_mail_settings(user)
    ms.active_transport_mode = mode
    sj = dict(ms.settings_json or {})
    sj["SEND_TRANSPORT"] = transport_for_mode(mode)
    ms.settings_json = sj
    ms.save(update_fields=["active_transport_mode", "settings_json", "updated_at"])


def list_accounts_for_user(user: User, *, transport: str | None = None):
    from core.models import MailAccount

    qs = MailAccount.objects.filter(user=user).order_by("slot", "id")
    if transport:
        qs = qs.filter(transport=transport)
    return qs


def count_accounts(user: User, transport: str) -> int:
    return list_accounts_for_user(user, transport=transport).count()


def next_free_slot(user: User, transport: str) -> int | None:
    used = set(list_accounts_for_user(user, transport=transport).values_list("slot", flat=True))
    for s in range(1, MAX_SLOTS_PER_TRANSPORT + 1):
        if s not in used:
            return s
    return None


def get_account(user: User, account_id: int) -> MailAccount | None:
    from core.models import MailAccount

    try:
        return MailAccount.objects.get(pk=account_id, user=user)
    except MailAccount.DoesNotExist:
        return None


def resolve_account(
    user: User,
    account_id: int | None = None,
    *,
    transport: str | None = None,
    require_enabled: bool = False,
) -> MailAccount | None:
    if account_id is not None:
        acc = get_account(user, account_id)
        if acc is None:
            return None
        if transport and acc.transport != transport:
            return None
        if require_enabled and not acc.is_enabled:
            return None
        return acc

    mode = active_transport_mode(user)
    tr = transport or transport_for_mode(mode)
    qs = list_accounts_for_user(user, transport=tr)
    if require_enabled:
        qs = qs.filter(is_enabled=True)
    acc = qs.first()
    return acc


def ensure_legacy_migrated(user: User) -> None:
    """One-time: copy UserMailSettings single mailbox into MailAccount slot 1."""
    from core.models import MailAccount

    if MailAccount.objects.filter(user=user).exists():
        return

    ms = get_or_create_mail_settings(user)
    sj = dict(ms.settings_json or {})
    st = str(sj.get("SEND_TRANSPORT") or TRANSPORT_GMAIL).strip()
    if st not in (TRANSPORT_GMAIL, TRANSPORT_SMTP):
        st = TRANSPORT_GMAIL
    mode = mode_for_transport(st)
    ms.active_transport_mode = mode
    ms.save(update_fields=["active_transport_mode", "updated_at"])

    if st == TRANSPORT_GMAIL:
        ga = str(sj.get("GMAIL_ADDRESS") or "").strip()
        if ga or ms.google_oauth_token_enc or ms.client_secret_json_enc:
            acc = MailAccount.objects.create(
                user=user,
                slot=1,
                transport=TRANSPORT_GMAIL,
                label=ga or "Gmail 1",
                is_enabled=True,
                config_json={"GMAIL_ADDRESS": ga} if ga else {},
                oauth_token_enc=ms.google_oauth_token_enc or "",
                client_secret_enc=ms.client_secret_json_enc or "",
            )
            sync_account_files_to_disk(user.id, acc)
            ms.default_account_id = acc.id
            ms.save(update_fields=["default_account_id", "updated_at"])
    else:
        cfg = {k: sj[k] for k in sj if k.startswith(("SMTP_", "IMAP_")) or k in ("SMTP_LAST_TEST_OK", "SMTP_LAST_TEST_AT", "SMTP_LAST_TEST_ERROR")}
        if cfg or ms.smtp_password_enc:
            acc = MailAccount.objects.create(
                user=user,
                slot=1,
                transport=TRANSPORT_SMTP,
                label=str(cfg.get("SMTP_USERNAME") or cfg.get("SMTP_FROM_EMAIL") or "SMTP 1"),
                is_enabled=True,
                config_json=cfg,
                smtp_password_enc=ms.smtp_password_enc or "",
                imap_password_enc=ms.imap_password_enc or "",
            )
            ms.default_account_id = acc.id
            ms.save(update_fields=["default_account_id", "updated_at"])


def create_account(
    user: User,
    *,
    transport: str,
    label: str = "",
    gmail_address: str = "",
) -> MailAccount:
    from core.models import MailAccount

    ensure_legacy_migrated(user)
    slot = next_free_slot(user, transport)
    if slot is None:
        raise ValueError(f"Maximum {MAX_SLOTS_PER_TRANSPORT} {transport} accounts reached")

    cfg: dict[str, Any] = {}
    if transport == TRANSPORT_GMAIL and gmail_address:
        cfg["GMAIL_ADDRESS"] = gmail_address.strip()

    acc = MailAccount.objects.create(
        user=user,
        slot=slot,
        transport=transport,
        label=(label or "").strip() or f"{'Gmail' if transport == TRANSPORT_GMAIL else 'SMTP'} {slot}",
        is_enabled=True,
        config_json=cfg,
    )
    ms = get_or_create_mail_settings(user)
    if not ms.default_account_id:
        ms.default_account_id = acc.id
        ms.save(update_fields=["default_account_id", "updated_at"])
    return acc


def _write_file_if_needed(path: str, content: str) -> None:
    if not content.strip():
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def sync_account_files_to_disk(user_id: int, account: MailAccount) -> None:
    tp = token_path_for_account(user_id, account.id)
    if account.oauth_token_enc:
        raw = decrypt_str(account.oauth_token_enc)
        if raw.strip():
            _write_file_if_needed(tp, raw)
    sp = client_secret_path_for_account(user_id, account.id)
    if account.client_secret_enc:
        raw = decrypt_str(account.client_secret_enc)
        if raw.strip():
            _write_file_if_needed(sp, raw)


def save_account_oauth_token(account: MailAccount, token_json: str) -> None:
    account.oauth_token_enc = encrypt_str(token_json)
    account.save(update_fields=["oauth_token_enc", "updated_at"])
    sync_account_files_to_disk(account.user_id, account)


def save_account_client_secret(account: MailAccount, secret_json: str) -> None:
    account.client_secret_enc = encrypt_str(secret_json)
    account.save(update_fields=["client_secret_enc", "updated_at"])
    sync_account_files_to_disk(account.user_id, account)


def clear_account_oauth(account: MailAccount) -> None:
    account.oauth_token_enc = ""
    account.save(update_fields=["oauth_token_enc", "updated_at"])
    tp = token_path_for_account(account.user_id, account.id)
    if os.path.exists(tp):
        try:
            os.remove(tp)
        except OSError:
            pass


def account_display_email(account: MailAccount) -> str:
    cfg = dict(account.config_json or {})
    if account.transport == TRANSPORT_GMAIL:
        return str(cfg.get("GMAIL_ADDRESS") or "").strip()
    return str(cfg.get("SMTP_FROM_EMAIL") or cfg.get("SMTP_USERNAME") or "").strip()


def account_to_dict(account: MailAccount, *, include_kb_count: bool = False) -> dict[str, Any]:
    from email_automation.gmail_auth import gmail_oauth_matches_configured, gmail_oauth_ready

    cfg = dict(account.config_json or {})
    settings = build_effective_settings(account.user, account_id=account.id)
    g_ready = account.transport == TRANSPORT_GMAIL and gmail_oauth_ready(settings)
    profile_email = ""
    oauth_mismatch = False
    if g_ready:
        matches, profile_email, _configured = gmail_oauth_matches_configured(settings)
        oauth_mismatch = not matches and bool(profile_email)
    imap_ok = False
    if account.transport == TRANSPORT_SMTP:
        from email_automation.imap_mailbox import imap_inbox_ready

        imap_ok = imap_inbox_ready(settings)
    inbox_ready = (g_ready and not oauth_mismatch) if account.transport == TRANSPORT_GMAIL else imap_ok

    out: dict[str, Any] = {
        "id": account.id,
        "slot": account.slot,
        "transport": account.transport,
        "label": account.label,
        "is_enabled": account.is_enabled,
        "email": account_display_email(account),
        "gmail_connected": g_ready,
        "gmail_inbox_ready": inbox_ready,
        "oauth_email_mismatch": oauth_mismatch,
        "profile_email": profile_email,
        "imap_ready": imap_ok,
        "inbox_ready": inbox_ready,
        "has_client_secret": bool(account.client_secret_enc) or os.path.exists(settings.GOOGLE_CLIENT_SECRET_FILE),
        "has_token": g_ready,
        "smtp_last_test_ok": bool(cfg.get("SMTP_LAST_TEST_OK")),
        "config": {k: v for k, v in cfg.items() if not k.endswith("PASSWORD")},
    }
    if include_kb_count:
        try:
            from email_automation.kb.store import VectorStore, is_vector_db_configured

            if is_vector_db_configured(settings):
                vs = VectorStore(settings=settings, tenant_id=tenant_id_for_account(account.user_id, account.id))
                st = vs.stats()
                out["kb_chunk_count"] = int(st.get("chunks") or 0)
            else:
                out["kb_chunk_count"] = 0
        except Exception:
            out["kb_chunk_count"] = 0
    return out


def _derive_imap_from_smtp(d: dict[str, Any]) -> dict[str, Any]:
    out = dict(d or {})
    if str(out.get("SEND_TRANSPORT") or "").strip() != TRANSPORT_SMTP:
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
        imap_pass_str = imap_pass.get_secret_value() if hasattr(imap_pass, "get_secret_value") else str(imap_pass or "")
    except Exception:
        imap_pass_str = str(imap_pass or "")
    if smtp_pass is not None and (imap_pass is None or not str(imap_pass_str).strip()):
        out["IMAP_PASSWORD"] = smtp_pass
    if out.get("IMAP_PORT") in (None, "", 0):
        out["IMAP_PORT"] = 993
    if str(out.get("SMTP_TLS_SERVERNAME") or "").strip() and not str(out.get("IMAP_TLS_SERVERNAME") or "").strip():
        out["IMAP_TLS_SERVERNAME"] = str(out.get("SMTP_TLS_SERVERNAME") or "").strip()
    return out


def _merge_env_defaults_into_merged(merged: dict[str, Any], settings_json_keys: dict[str, Any]) -> dict[str, Any]:
    def _secret_nonempty(val: Any) -> bool:
        if val is None:
            return False
        if hasattr(val, "get_secret_value"):
            return bool((val.get_secret_value() or "").strip())
        return bool(str(val or "").strip())

    if not _secret_nonempty(merged.get("LLM_API_KEY")):
        for ek in ("OPENAI_API_KEY", "LLM_API_KEY"):
            v = (os.environ.get(ek) or "").strip()
            if v:
                merged["LLM_API_KEY"] = SecretStr(v)
                break
    if not str(merged.get("GMAIL_ADDRESS") or "").strip():
        ga = (os.environ.get("GMAIL_ADDRESS") or "").strip()
        if ga:
            merged["GMAIL_ADDRESS"] = ga
    if "REPLY_MODE" not in settings_json_keys:
        rm = (os.environ.get("REPLY_MODE") or "").strip()
        if rm:
            merged["REPLY_MODE"] = rm
    if not str(merged.get("OAUTH_REDIRECT_URI") or "").strip():
        uri = (os.environ.get("OAUTH_REDIRECT_URI") or "").strip()
        if uri:
            merged["OAUTH_REDIRECT_URI"] = uri
    return merged


def build_effective_settings(user: User, account_id: int | None = None):
    """Return email_automation.settings.Settings for user (+ optional mail account)."""
    from email_automation.settings import Settings

    ensure_legacy_migrated(user)
    ms = get_or_create_mail_settings(user)
    global_patch: dict[str, Any] = dict(ms.settings_json or {})
    if ms.llm_api_key_enc:
        global_patch["LLM_API_KEY"] = SecretStr(decrypt_str(ms.llm_api_key_enc))

    account = resolve_account(user, account_id)
    if account is None:
        base = Settings()
        merged = base.model_dump(mode="python")
        merged.update({k: v for k, v in global_patch.items() if k in Settings.model_fields})
        mode = active_transport_mode(user)
        merged["SEND_TRANSPORT"] = transport_for_mode(mode)
        merged["GOOGLE_TOKEN_FILE"] = token_path_for_user(user.id)
        merged["GOOGLE_CLIENT_SECRET_FILE"] = client_secret_path_for_user(user.id)
        merged = _derive_imap_from_smtp(merged)
        merged = _merge_env_defaults_into_merged(merged, global_patch)
        try:
            return Settings.model_validate(merged)
        except ValidationError:
            return Settings.model_validate(base.model_dump(mode="python"))

    sync_account_files_to_disk(user.id, account)
    acc_patch: dict[str, Any] = dict(account.config_json or {})
    if account.smtp_password_enc:
        acc_patch["SMTP_PASSWORD"] = SecretStr(decrypt_str(account.smtp_password_enc))
    if account.imap_password_enc:
        acc_patch["IMAP_PASSWORD"] = SecretStr(decrypt_str(account.imap_password_enc))

    merged = Settings().model_dump(mode="python")
    merged.update({k: v for k, v in global_patch.items() if k in Settings.model_fields and k not in (
        "SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_USE_TLS", "SMTP_USE_SSL",
        "SMTP_VERIFY_TLS", "SMTP_TLS_SERVERNAME", "SMTP_FROM_EMAIL",
        "IMAP_HOST", "IMAP_PORT", "IMAP_USERNAME", "IMAP_MAILBOX", "IMAP_VERIFY_TLS", "IMAP_TLS_SERVERNAME",
        "GMAIL_ADDRESS", "SEND_TRANSPORT",
    )})
    merged.update({k: v for k, v in acc_patch.items() if k in Settings.model_fields})
    merged["SEND_TRANSPORT"] = account.transport
    merged["GOOGLE_TOKEN_FILE"] = token_path_for_account(user.id, account.id)
    merged["GOOGLE_CLIENT_SECRET_FILE"] = client_secret_path_for_account(user.id, account.id)
    merged = _derive_imap_from_smtp(merged)
    merged = _merge_env_defaults_into_merged(merged, {**global_patch, **acc_patch})
    try:
        return Settings.model_validate(merged)
    except ValidationError:
        return Settings.model_validate(Settings().model_dump(mode="python"))


def patch_account_config(account: MailAccount, patch: dict[str, Any]) -> None:
    secret_keys = {"SMTP_PASSWORD", "IMAP_PASSWORD"}
    data = dict(account.config_json or {})
    for k, v in patch.items():
        if k in secret_keys:
            continue
        if v is None:
            data.pop(k, None)
        else:
            data[k] = v
    account.config_json = data
    if "SMTP_PASSWORD" in patch:
        p = patch["SMTP_PASSWORD"]
        if p:
            s = p.get_secret_value() if hasattr(p, "get_secret_value") else str(p)
            account.smtp_password_enc = encrypt_str(s)
        else:
            account.smtp_password_enc = ""
    if "IMAP_PASSWORD" in patch:
        p = patch["IMAP_PASSWORD"]
        if p:
            s = p.get_secret_value() if hasattr(p, "get_secret_value") else str(p)
            account.imap_password_enc = encrypt_str(s)
        else:
            account.imap_password_enc = ""
    account.save()


def enabled_accounts_for_active_mode(user: User):
    mode = active_transport_mode(user)
    tr = transport_for_mode(mode)
    return list(list_accounts_for_user(user, transport=tr).filter(is_enabled=True))


def all_owner_emails_for_user(user: User) -> set[str]:
    """All mailbox addresses configured for this user (any transport/account).

    Used to skip auto-replies to the user's own inboxes and prevent ping-pong loops
    when testing or when multiple accounts are connected.
    """
    out: set[str] = set()
    uemail = (getattr(user, "email", None) or "").strip().lower()
    if uemail and "@" in uemail:
        out.add(uemail)
    for acc in list_accounts_for_user(user):
        cfg = dict(acc.config_json or {})
        for key in ("GMAIL_ADDRESS", "SMTP_FROM_EMAIL", "SMTP_USERNAME", "IMAP_USERNAME"):
            addr = str(cfg.get(key) or "").strip().lower()
            if addr and "@" in addr:
                out.add(addr)
    return out


def transport_summary(user: User) -> dict[str, Any]:
    ensure_legacy_migrated(user)
    mode = active_transport_mode(user)
    tr = transport_for_mode(mode)
    accounts = list(list_accounts_for_user(user, transport=tr))
    enabled = [a for a in accounts if a.is_enabled]
    return {
        "active_mode": mode,
        "send_transport": tr,
        "total_slots": len(accounts),
        "enabled_count": len(enabled),
        "max_slots": MAX_SLOTS_PER_TRANSPORT,
        "max_active": max_active_accounts(),
    }
