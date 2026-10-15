from __future__ import annotations

from core.whatsapp_notify import load_whatsapp_config, send_whatsapp_text, should_notify


def send(user_id: int, event: str, text: str) -> str:
    """Returns a delivery status: sent, failed, not_configured, disabled or filtered."""
    cfg = load_whatsapp_config(user_id)
    if cfg is None:
        return "not_configured"
    if not cfg.enabled:
        return "disabled"
    if event in ("sent", "draft", "error") and not should_notify(cfg.notify_events, event):
        return "filtered"
    ok, _err = send_whatsapp_text(
        access_token=cfg.access_token,
        phone_number_id=cfg.phone_number_id,
        to_phone=cfg.to_phone,
        text=text,
    )
    return "sent" if ok else "failed"
