"""Optional Telegram alerts for mail automation events (does not affect email flow)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import requests

from core.crypto import decrypt_str, encrypt_str
from core.mail_accounts import get_or_create_mail_settings

log = logging.getLogger("mailpilot.telegram")

NOTIFY_ALL = "all"
NOTIFY_SENT = "sent"
NOTIFY_ERRORS = "errors"


@dataclass(frozen=True)
class TelegramConfig:
    enabled: bool
    bot_token: str
    chat_id: str
    notify_events: str


def user_id_from_tenant(tenant_id: str) -> Optional[int]:
    tid = (tenant_id or "").strip()
    if not tid:
        return None
    head = tid.split(":", 1)[0]
    try:
        return int(head)
    except ValueError:
        return None


def _coerce_bool(v: Any, default: bool = True) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def load_telegram_config(user_id: int) -> Optional[TelegramConfig]:
    from django.contrib.auth.models import User

    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return None
    ms = get_or_create_mail_settings(user)
    sj = dict(ms.settings_json or {})
    token = decrypt_str(ms.telegram_bot_token_enc or "")
    chat_id = str(sj.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        return None
    return TelegramConfig(
        enabled=_coerce_bool(sj.get("TELEGRAM_ENABLED"), default=True),
        bot_token=token,
        chat_id=chat_id,
        notify_events=str(sj.get("TELEGRAM_NOTIFY_EVENTS") or NOTIFY_ALL).strip().lower() or NOTIFY_ALL,
    )


def telegram_reply_enabled(user) -> bool:
    sj = dict(get_or_create_mail_settings(user).settings_json or {})
    raw = sj.get("TELEGRAM_REPLY_ENABLED")
    if raw is None:
        return True
    return _coerce_bool(raw, default=True)


def telegram_status_for_user(user) -> dict[str, Any]:
    ms = get_or_create_mail_settings(user)
    sj = dict(ms.settings_json or {})
    token = decrypt_str(ms.telegram_bot_token_enc or "")
    chat_id = str(sj.get("TELEGRAM_CHAT_ID") or "").strip()
    notify_events = str(sj.get("TELEGRAM_NOTIFY_EVENTS") or NOTIFY_ALL).strip().lower() or NOTIFY_ALL
    enabled = _coerce_bool(sj.get("TELEGRAM_ENABLED"), default=True)
    reply_enabled = telegram_reply_enabled(user)
    configured = bool(token and chat_id)
    return {
        "enabled": enabled,
        "reply_enabled": reply_enabled,
        "configured": configured,
        "chat_id": chat_id,
        "notify_events": notify_events,
        "has_bot_token": bool(token),
        "bot_token_hint": (token[:8] + "…") if len(token) > 10 else ("set" if token else ""),
    }


def save_telegram_settings(user, patch: dict[str, Any]) -> None:
    ms = get_or_create_mail_settings(user)
    sj = dict(ms.settings_json or {})
    if "TELEGRAM_CHAT_ID" in patch:
        v = str(patch.get("TELEGRAM_CHAT_ID") or "").strip()
        if v:
            sj["TELEGRAM_CHAT_ID"] = v
        else:
            sj.pop("TELEGRAM_CHAT_ID", None)
    if "TELEGRAM_NOTIFY_EVENTS" in patch:
        ne = str(patch.get("TELEGRAM_NOTIFY_EVENTS") or NOTIFY_ALL).strip().lower() or NOTIFY_ALL
        if ne not in (NOTIFY_ALL, NOTIFY_SENT, NOTIFY_ERRORS):
            ne = NOTIFY_ALL
        sj["TELEGRAM_NOTIFY_EVENTS"] = ne
    if "TELEGRAM_ENABLED" in patch:
        sj["TELEGRAM_ENABLED"] = _coerce_bool(patch.get("TELEGRAM_ENABLED"), default=True)
    if "TELEGRAM_REPLY_ENABLED" in patch:
        sj["TELEGRAM_REPLY_ENABLED"] = _coerce_bool(patch.get("TELEGRAM_REPLY_ENABLED"), default=True)
    if "TELEGRAM_BOT_TOKEN" in patch:
        raw = str(patch.get("TELEGRAM_BOT_TOKEN") or "").strip()
        if raw:
            ms.telegram_bot_token_enc = encrypt_str(raw)
        elif patch.get("TELEGRAM_BOT_TOKEN") is None:
            pass
        else:
            ms.telegram_bot_token_enc = ""
    if any(
        k in patch
        for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_REPLY_ENABLED", "TELEGRAM_ENABLED")
    ):
        sj.pop("TELEGRAM_UPDATE_OFFSET", None)
    ms.settings_json = sj
    ms.save(update_fields=["settings_json", "telegram_bot_token_enc", "updated_at"])


def should_notify(notify_events: str, event: str) -> bool:
    ne = (notify_events or NOTIFY_ALL).lower()
    ev = (event or "").lower()
    if ne == NOTIFY_ERRORS:
        return ev == "error"
    if ne == NOTIFY_SENT:
        return ev == "sent"
    return ev in ("sent", "draft", "error")


def _format_message(event: str, *, subject: str, from_email: str, error: str, reply_subject: str) -> str:
    subj = (subject or reply_subject or "(No subject)").strip()
    sender = (from_email or "unknown").strip()
    if event == "sent":
        return f"MailPilot auto-reply sent\nFrom: {sender}\nSubject: {subj}"
    if event == "draft":
        return f"MailPilot draft saved\nFrom: {sender}\nSubject: {subj}"
    if event == "error":
        err = (error or "unknown error").strip()
        return f"MailPilot send error\nFrom: {sender}\nSubject: {subj}\nError: {err}"
    return f"MailPilot: {event}\nFrom: {sender}\nSubject: {subj}"


def send_telegram_message(*, bot_token: str, chat_id: str, text: str) -> tuple[bool, str]:
    token = (bot_token or "").strip()
    cid = (chat_id or "").strip()
    body = (text or "").strip()
    if not token or not cid or not body:
        return False, "missing_token_chat_or_text"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": cid, "text": body, "disable_web_page_preview": True},
            timeout=12,
        )
        data = resp.json() if resp.content else {}
        if resp.ok and data.get("ok"):
            return True, ""
        desc = str(data.get("description") or resp.text or resp.reason or "send_failed")
        return False, desc
    except requests.RequestException as e:
        log.warning("Telegram send failed: %s", e)
        return False, str(e)


def notify_mail_event(
    tenant_id: str,
    event: str,
    *,
    subject: str = "",
    from_email: str = "",
    error: str = "",
    reply_subject: str = "",
) -> None:
    """Fire-and-forget alert; never raises."""
    try:
        uid = user_id_from_tenant(tenant_id)
        if uid is None:
            return
        cfg = load_telegram_config(uid)
        if cfg is None or not cfg.enabled:
            return
        if not should_notify(cfg.notify_events, event):
            return
        text = _format_message(
            event,
            subject=subject,
            from_email=from_email,
            error=error,
            reply_subject=reply_subject,
        )
        ok, err = send_telegram_message(bot_token=cfg.bot_token, chat_id=cfg.chat_id, text=text)
        if not ok:
            log.warning("Telegram notify skipped/failed user=%s event=%s err=%s", uid, event, err)
    except Exception as e:
        log.warning("Telegram notify error: %s", e)


def send_test_message(user) -> tuple[bool, str]:
    cfg = load_telegram_config(user.id)
    if cfg is None:
        return False, "Configure bot token and chat ID first"
    if not cfg.enabled:
        return False, "Telegram notifications are disabled"
    text = "MailPilot Telegram test\nYour bot is connected and ready for alerts."
    return send_telegram_message(bot_token=cfg.bot_token, chat_id=cfg.chat_id, text=text)
