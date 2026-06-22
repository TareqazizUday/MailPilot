"""Poll Telegram bots for inbound messages and reply using MailPilot LLM + KB."""
from __future__ import annotations

import logging
from typing import Any, Optional

import requests

from core.mail_chat_assistant import answer_mail_chat
from core.state_store import StateStore
from core.telegram_notify import TelegramConfig, load_telegram_config, send_telegram_message

log = logging.getLogger("mailpilot.telegram.bot")

_webhook_cleared: set[int] = set()


def _chat_ids_match(configured: str, incoming: Any) -> bool:
    return str(configured or "").strip() == str(incoming or "").strip()


def _reply_enabled(user_id: int) -> bool:
    from django.contrib.auth.models import User

    from core.mail_accounts import get_or_create_mail_settings

    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return False
    try:
        from core.billing import can_use_integration

        if not can_use_integration(user, "telegram").allowed:
            return False
    except Exception:
        pass
    sj = dict(get_or_create_mail_settings(user).settings_json or {})
    raw = sj.get("TELEGRAM_REPLY_ENABLED")
    if raw is None:
        return True
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _ensure_polling_mode(user_id: int, bot_token: str) -> None:
    if user_id in _webhook_cleared:
        return
    url = f"https://api.telegram.org/bot{bot_token}/deleteWebhook"
    try:
        requests.post(url, json={"drop_pending_updates": False}, timeout=10)
    except requests.RequestException as e:
        log.warning("Telegram deleteWebhook failed user=%s: %s", user_id, e)
    _webhook_cleared.add(user_id)


def _fetch_updates(bot_token: str, offset: Optional[int]) -> list[dict[str, Any]]:
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    params: dict[str, Any] = {"timeout": 0, "allowed_updates": ["message"]}
    if offset is not None:
        params["offset"] = int(offset)
    try:
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json() if resp.content else {}
        if not resp.ok or not data.get("ok"):
            desc = str(data.get("description") or resp.text or "getUpdates_failed")
            log.warning("Telegram getUpdates error: %s", desc)
            return []
        updates = data.get("result") or []
        return updates if isinstance(updates, list) else []
    except requests.RequestException as e:
        log.warning("Telegram getUpdates request failed: %s", e)
        return []


def _save_update_offset(user_id: int, offset: int) -> None:
    from django.contrib.auth.models import User

    from core.mail_accounts import get_or_create_mail_settings

    user = User.objects.get(pk=user_id)
    ms = get_or_create_mail_settings(user)
    sj = dict(ms.settings_json or {})
    sj["TELEGRAM_UPDATE_OFFSET"] = int(offset)
    ms.settings_json = sj
    ms.save(update_fields=["settings_json", "updated_at"])


def _load_update_offset(user_id: int) -> Optional[int]:
    from django.contrib.auth.models import User

    from core.mail_accounts import get_or_create_mail_settings

    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return None
    sj = dict(get_or_create_mail_settings(user).settings_json or {})
    raw = sj.get("TELEGRAM_UPDATE_OFFSET")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def compose_inbound_reply(user, *, text: str, sender_name: str, context_text: str = "") -> str:
    """Public entry for WhatsApp webhook (same logic as Telegram bot replies)."""
    return _compose_reply(user, text=text, sender_name=sender_name, context_text=context_text)


def _compose_reply(user, *, text: str, sender_name: str, context_text: str = "") -> str:
    return answer_mail_chat(user, text=text, channel="telegram", sender_name=sender_name, context_text=context_text)


def _handle_message(user_id: int, cfg: TelegramConfig, message: dict[str, Any]) -> None:
    if not message or message.get("from", {}).get("is_bot"):
        return
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if not _chat_ids_match(cfg.chat_id, chat_id):
        return
    text = str(message.get("text") or "").strip()
    if not text:
        return
    update_id = message.get("_update_id")
    if update_id is not None:
        st = StateStore(tenant_id=str(user_id))
        if not st.try_claim_message(f"tg:{update_id}"):
            return
    from django.contrib.auth.models import User

    user = User.objects.get(pk=user_id)
    sender = message.get("from") or {}
    sender_name = " ".join(
        [str(sender.get("first_name") or "").strip(), str(sender.get("last_name") or "").strip()]
    ).strip() or str(sender.get("username") or "user")
    reply_to = message.get("reply_to_message") or {}
    context_text = str(reply_to.get("text") or reply_to.get("caption") or "").strip() if isinstance(reply_to, dict) else ""
    reply = _compose_reply(user, text=text, sender_name=sender_name, context_text=context_text)
    ok, err = send_telegram_message(bot_token=cfg.bot_token, chat_id=str(chat_id), text=reply)
    if not ok:
        log.warning("Telegram reply failed user=%s chat=%s err=%s", user_id, chat_id, err)


def poll_user_telegram(user_id: int) -> int:
    """Poll one user's bot. Returns number of updates seen."""
    if not _reply_enabled(user_id):
        return 0
    cfg = load_telegram_config(user_id)
    if cfg is None or not cfg.enabled:
        return 0
    _ensure_polling_mode(user_id, cfg.bot_token)
    stored = _load_update_offset(user_id)
    updates = _fetch_updates(cfg.bot_token, stored if stored is not None else None)
    if not updates:
        return 0
    if stored is None:
        last = int(updates[-1].get("update_id") or 0)
        _save_update_offset(user_id, last + 1)
        return 0
    handled = 0
    last_id = stored or 0
    for upd in updates:
        try:
            uid = int(upd.get("update_id") or 0)
        except (TypeError, ValueError):
            continue
        if uid > last_id:
            last_id = uid
        msg = upd.get("message")
        if not isinstance(msg, dict):
            continue
        msg["_update_id"] = uid
        try:
            _handle_message(user_id, cfg, msg)
            handled += 1
        except Exception as e:
            log.warning("Telegram message handler failed user=%s: %s", user_id, e)
    if last_id >= (stored or 0):
        _save_update_offset(user_id, last_id + 1)
    return handled


def poll_all_telegram_inbound() -> None:
    from core.models import UserMailSettings

    user_ids = list(
        UserMailSettings.objects.exclude(telegram_bot_token_enc="")
        .values_list("user_id", flat=True)
        .distinct()
    )
    for uid in user_ids:
        try:
            poll_user_telegram(int(uid))
        except Exception as e:
            log.warning("Telegram poll user=%s failed: %s", uid, e)
