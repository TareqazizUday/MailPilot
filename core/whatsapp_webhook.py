"""WhatsApp Cloud API webhook (inbound messages → same replies as Telegram bot)."""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from core.mail_chat_assistant import answer_mail_chat
from core.state_store import StateStore
from core.whatsapp_notify import (
    find_user_for_inbound,
    load_whatsapp_config,
    send_whatsapp_text,
    webhook_verify_token_matches,
    whatsapp_reply_enabled,
)

log = logging.getLogger("mailpilot.whatsapp.webhook")


def _extract_inbound_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, dict):
                continue
            value = change.get("value") or {}
            if not isinstance(value, dict):
                continue
            meta = value.get("metadata") or {}
            phone_number_id = str(meta.get("phone_number_id") or "").strip()
            for msg in value.get("messages") or []:
                if not isinstance(msg, dict):
                    continue
                if str(msg.get("type") or "").lower() != "text":
                    continue
                text_obj = msg.get("text") or {}
                body = str(text_obj.get("body") or "").strip() if isinstance(text_obj, dict) else ""
                if not body:
                    continue
                out.append(
                    {
                        "phone_number_id": phone_number_id,
                        "from_phone": str(msg.get("from") or ""),
                        "message_id": str(msg.get("id") or ""),
                        "text": body,
                        "context_text": _extract_context_text(msg),
                    }
                )
    return out


def _extract_context_text(msg: dict[str, Any]) -> str:
    ctx = msg.get("context") or {}
    if not isinstance(ctx, dict):
        return ""
    candidates: list[str] = []
    for key in ("body", "text", "message"):
        value = ctx.get(key)
        if isinstance(value, str):
            candidates.append(value)
        elif isinstance(value, dict):
            candidates.append(str(value.get("body") or value.get("text") or ""))
    quoted = ctx.get("quoted_message") or ctx.get("quotedMessage")
    if isinstance(quoted, dict):
        text_obj = quoted.get("text") or {}
        if isinstance(text_obj, dict):
            candidates.append(str(text_obj.get("body") or ""))
        candidates.append(str(quoted.get("body") or quoted.get("text") or ""))
    for value in candidates:
        text = str(value or "").strip()
        if text:
            return text
    ctx_id = str(ctx.get("id") or "").strip()
    return f"WhatsApp context id: {ctx_id}" if ctx_id else ""


def handle_webhook_verification(*, mode: str, token: str, challenge: str) -> Optional[str]:
    if (mode or "").lower() != "subscribe":
        return None
    if not webhook_verify_token_matches(token):
        return None
    return challenge or ""


def process_webhook_payload(payload: dict[str, Any]) -> int:
    """Process inbound WhatsApp messages. Returns count handled."""
    handled = 0
    for item in _extract_inbound_messages(payload):
        try:
            if _handle_one_inbound(item):
                handled += 1
        except Exception as e:
            log.warning("WhatsApp inbound handler failed: %s", e)
    return handled


def _handle_one_inbound(item: dict[str, Any]) -> bool:
    phone_number_id = str(item.get("phone_number_id") or "")
    from_phone = str(item.get("from_phone") or "")
    text = str(item.get("text") or "").strip()
    context_text = str(item.get("context_text") or "").strip()
    wa_msg_id = str(item.get("message_id") or "")
    if not text:
        return False

    user = find_user_for_inbound(phone_number_id=phone_number_id, from_phone=from_phone)
    if user is None:
        return False
    try:
        from core.billing import can_use_integration

        if not can_use_integration(user, "whatsapp").allowed:
            return False
    except Exception:
        pass
    if not whatsapp_reply_enabled(user):
        return False

    if wa_msg_id:
        st = StateStore(tenant_id=str(user.id))
        if not st.try_claim_message(f"wa:{wa_msg_id}"):
            return False

    reply = answer_mail_chat(user, text=text, channel="whatsapp", sender_name=f"WhatsApp:{from_phone}", context_text=context_text)
    cfg = load_whatsapp_config(user.id)
    if cfg is None:
        return False
    ok, err = send_whatsapp_text(
        access_token=cfg.access_token,
        phone_number_id=cfg.phone_number_id,
        to_phone=from_phone or cfg.to_phone,
        text=reply,
    )
    if not ok:
        log.warning("WhatsApp reply failed user=%s err=%s", user.id, err)
    return ok


def parse_webhook_body(raw: bytes) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw.decode("utf-8") or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}
