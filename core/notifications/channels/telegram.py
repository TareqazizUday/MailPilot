from __future__ import annotations

from core.telegram_notify import load_telegram_config, send_telegram_message, should_notify


def send(user_id: int, event: str, text: str) -> str:
    """Returns a delivery status: sent, failed, not_configured, disabled or filtered."""
    cfg = load_telegram_config(user_id)
    if cfg is None:
        return "not_configured"
    if not cfg.enabled:
        return "disabled"
    if event in ("sent", "draft", "error") and not should_notify(cfg.notify_events, event):
        return "filtered"
    ok, _err = send_telegram_message(bot_token=cfg.bot_token, chat_id=cfg.chat_id, text=text)
    return "sent" if ok else "failed"
