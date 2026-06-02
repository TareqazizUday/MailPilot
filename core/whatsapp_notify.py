"""Optional WhatsApp Cloud API alerts (demo; does not affect email flow)."""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Optional

import requests

from core.crypto import decrypt_str, encrypt_str
from core.mail_accounts import get_or_create_mail_settings

log = logging.getLogger("mailpilot.whatsapp")

NOTIFY_ALL = "all"
NOTIFY_SENT = "sent"
NOTIFY_ERRORS = "errors"

_GRAPH_VERSION = os.environ.get("WHATSAPP_GRAPH_VERSION", "v21.0").strip() or "v21.0"


@dataclass(frozen=True)
class WhatsAppConfig:
    enabled: bool
    access_token: str
    phone_number_id: str
    to_phone: str
    notify_events: str
    verify_token: str


def user_id_from_tenant(tenant_id: str) -> Optional[int]:
    tid = (tenant_id or "").strip()
    if not tid:
        return None
    head = tid.split(":", 1)[0]
    try:
        return int(head)
    except ValueError:
        return None


def normalize_phone(value: str) -> str:
    return re.sub(r"\D", "", (value or "").strip())


def _coerce_bool(v: Any, default: bool = True) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def load_whatsapp_config(user_id: int) -> Optional[WhatsAppConfig]:
    from django.contrib.auth.models import User

    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return None
    ms = get_or_create_mail_settings(user)
    sj = dict(ms.settings_json or {})
    token = decrypt_str(ms.whatsapp_access_token_enc or "")
    phone_number_id = str(sj.get("WHATSAPP_PHONE_NUMBER_ID") or "").strip()
    to_phone = normalize_phone(str(sj.get("WHATSAPP_TO_PHONE") or ""))
    if not token or not phone_number_id or not to_phone:
        return None
    return WhatsAppConfig(
        enabled=_coerce_bool(sj.get("WHATSAPP_ENABLED"), default=True),
        access_token=token,
        phone_number_id=phone_number_id,
        to_phone=to_phone,
        notify_events=str(sj.get("WHATSAPP_NOTIFY_EVENTS") or NOTIFY_ALL).strip().lower() or NOTIFY_ALL,
        verify_token=str(sj.get("WHATSAPP_VERIFY_TOKEN") or "").strip(),
    )


def whatsapp_reply_enabled(user) -> bool:
    sj = dict(get_or_create_mail_settings(user).settings_json or {})
    raw = sj.get("WHATSAPP_REPLY_ENABLED")
    if raw is None:
        return True
    return _coerce_bool(raw, default=True)


def whatsapp_status_for_user(user) -> dict[str, Any]:
    ms = get_or_create_mail_settings(user)
    sj = dict(ms.settings_json or {})
    token = decrypt_str(ms.whatsapp_access_token_enc or "")
    phone_number_id = str(sj.get("WHATSAPP_PHONE_NUMBER_ID") or "").strip()
    to_phone = str(sj.get("WHATSAPP_TO_PHONE") or "").strip()
    notify_events = str(sj.get("WHATSAPP_NOTIFY_EVENTS") or NOTIFY_ALL).strip().lower() or NOTIFY_ALL
    enabled = _coerce_bool(sj.get("WHATSAPP_ENABLED"), default=True)
    reply_enabled = whatsapp_reply_enabled(user)
    configured = bool(token and phone_number_id and to_phone)
    return {
        "enabled": enabled,
        "reply_enabled": reply_enabled,
        "configured": configured,
        "phone_number_id": phone_number_id,
        "to_phone": to_phone,
        "notify_events": notify_events,
        "has_access_token": bool(token),
        "access_token_hint": (token[:8] + "…") if len(token) > 10 else ("set" if token else ""),
        "verify_token_set": bool(str(sj.get("WHATSAPP_VERIFY_TOKEN") or "").strip()),
    }


def save_whatsapp_settings(user, patch: dict[str, Any]) -> None:
    ms = get_or_create_mail_settings(user)
    sj = dict(ms.settings_json or {})

    def _set_str(key: str, field: str) -> None:
        if key not in patch:
            return
        v = str(patch.get(key) or "").strip()
        if v:
            sj[field] = v
        else:
            sj.pop(field, None)

    _set_str("WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_PHONE_NUMBER_ID")
    _set_str("WHATSAPP_TO_PHONE", "WHATSAPP_TO_PHONE")
    _set_str("WHATSAPP_VERIFY_TOKEN", "WHATSAPP_VERIFY_TOKEN")

    if "WHATSAPP_NOTIFY_EVENTS" in patch:
        ne = str(patch.get("WHATSAPP_NOTIFY_EVENTS") or NOTIFY_ALL).strip().lower() or NOTIFY_ALL
        if ne not in (NOTIFY_ALL, NOTIFY_SENT, NOTIFY_ERRORS):
            ne = NOTIFY_ALL
        sj["WHATSAPP_NOTIFY_EVENTS"] = ne
    if "WHATSAPP_ENABLED" in patch:
        sj["WHATSAPP_ENABLED"] = _coerce_bool(patch.get("WHATSAPP_ENABLED"), default=True)
    if "WHATSAPP_REPLY_ENABLED" in patch:
        sj["WHATSAPP_REPLY_ENABLED"] = _coerce_bool(patch.get("WHATSAPP_REPLY_ENABLED"), default=True)
    if "WHATSAPP_ACCESS_TOKEN" in patch:
        raw = str(patch.get("WHATSAPP_ACCESS_TOKEN") or "").strip()
        if raw:
            ms.whatsapp_access_token_enc = encrypt_str(raw)
        elif patch.get("WHATSAPP_ACCESS_TOKEN") is None:
            pass
        else:
            ms.whatsapp_access_token_enc = ""

    ms.settings_json = sj
    ms.save(update_fields=["settings_json", "whatsapp_access_token_enc", "updated_at"])


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
        return f"✅ MailPilot auto-reply sent\nFrom: {sender}\nSubject: {subj}"
    if event == "draft":
        return f"📝 MailPilot draft saved\nFrom: {sender}\nSubject: {subj}"
    if event == "error":
        err = (error or "unknown error").strip()
        return f"⚠️ MailPilot send error\nFrom: {sender}\nSubject: {subj}\nError: {err}"
    return f"MailPilot: {event}\nFrom: {sender}\nSubject: {subj}"


def send_whatsapp_text(*, access_token: str, phone_number_id: str, to_phone: str, text: str) -> tuple[bool, str]:
    token = (access_token or "").strip()
    pid = (phone_number_id or "").strip()
    to_n = normalize_phone(to_phone)
    body = (text or "").strip()
    if not token or not pid or not to_n or not body:
        return False, "missing_token_phone_or_text"
    if len(body) > 4096:
        body = body[:4050].rstrip() + "\n… (truncated)"
    url = f"https://graph.facebook.com/{_GRAPH_VERSION}/{pid}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to_n,
        "type": "text",
        "text": {"body": body},
    }
    try:
        resp = requests.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        data = resp.json() if resp.content else {}
        if resp.ok and not data.get("error"):
            return True, ""
        err = data.get("error") if isinstance(data.get("error"), dict) else {}
        desc = str(err.get("message") or data or resp.text or resp.reason or "send_failed")
        return False, desc
    except requests.RequestException as e:
        log.warning("WhatsApp send failed: %s", e)
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
        cfg = load_whatsapp_config(uid)
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
        ok, err = send_whatsapp_text(
            access_token=cfg.access_token,
            phone_number_id=cfg.phone_number_id,
            to_phone=cfg.to_phone,
            text=text,
        )
        if not ok:
            log.warning("WhatsApp notify skipped/failed user=%s event=%s err=%s", uid, event, err)
    except Exception as e:
        log.warning("WhatsApp notify error: %s", e)


def send_test_message(user) -> tuple[bool, str]:
    cfg = load_whatsapp_config(user.id)
    if cfg is None:
        return False, "Configure access token, phone number ID, and your WhatsApp number first"
    if not cfg.enabled:
        return False, "WhatsApp notifications are disabled"
    text = "✅ MailPilot WhatsApp test\nYour Cloud API connection is ready for alerts."
    return send_whatsapp_text(
        access_token=cfg.access_token,
        phone_number_id=cfg.phone_number_id,
        to_phone=cfg.to_phone,
        text=text,
    )


def find_user_for_inbound(*, phone_number_id: str, from_phone: str):
    """Resolve MailPilot user from webhook metadata (demo: one business number per user)."""
    from core.models import UserMailSettings

    pid = str(phone_number_id or "").strip()
    frm = normalize_phone(from_phone)
    if not pid or not frm:
        return None

    for ms in UserMailSettings.objects.exclude(whatsapp_access_token_enc="").select_related("user"):
        sj = dict(ms.settings_json or {})
        if str(sj.get("WHATSAPP_PHONE_NUMBER_ID") or "").strip() != pid:
            continue
        expected = normalize_phone(str(sj.get("WHATSAPP_TO_PHONE") or ""))
        if expected and frm != expected:
            continue
        if not _coerce_bool(sj.get("WHATSAPP_ENABLED"), default=True):
            continue
        return ms.user
    return None


def webhook_verify_token_matches(token: str) -> bool:
    t = (token or "").strip()
    if not t:
        return False
    env_tok = (os.environ.get("WHATSAPP_VERIFY_TOKEN") or "").strip()
    if env_tok and t == env_tok:
        return True
    from core.models import UserMailSettings

    for ms in UserMailSettings.objects.all().only("settings_json"):
        sj = dict(ms.settings_json or {})
        if str(sj.get("WHATSAPP_VERIFY_TOKEN") or "").strip() == t:
            return True
    return False
