"""Expo Push Service (one token works for Android FCM and iOS APNs)."""
from __future__ import annotations

import logging
from typing import Any

import requests
from django.conf import settings

log = logging.getLogger("mailpilot.notifications.push")

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
_BATCH_SIZE = 100


def is_expo_token(token: str) -> bool:
    t = (token or "").strip()
    return (t.startswith("ExponentPushToken[") or t.startswith("ExpoPushToken[")) and t.endswith("]")


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    access = (getattr(settings, "EXPO_ACCESS_TOKEN", "") or "").strip()
    if access:
        headers["Authorization"] = f"Bearer {access}"
    return headers


def send_push(
    devices: list[Any],
    *,
    title: str,
    body: str,
    data: dict[str, Any],
    badge: int | None = None,
) -> tuple[int, int]:
    """Send to every device; deactivates tokens Expo reports as unregistered. Returns (ok, failed)."""
    ok = failed = 0
    for start in range(0, len(devices), _BATCH_SIZE):
        batch = devices[start : start + _BATCH_SIZE]
        messages = []
        for dev in batch:
            msg: dict[str, Any] = {
                "to": dev.expo_token,
                "title": title,
                "body": body,
                "data": data,
                "sound": "default",
                "priority": "high",
                "channelId": "default",
            }
            if badge is not None:
                msg["badge"] = badge
            messages.append(msg)
        try:
            resp = requests.post(EXPO_PUSH_URL, json=messages, headers=_headers(), timeout=15)
            tickets = (resp.json() or {}).get("data") if resp.content else None
        except (requests.RequestException, ValueError) as e:
            log.warning("Expo push request failed: %s", e)
            failed += len(batch)
            continue
        if not resp.ok or not isinstance(tickets, list):
            log.warning("Expo push rejected status=%s", resp.status_code)
            failed += len(batch)
            continue
        for dev, ticket in zip(batch, tickets):
            if isinstance(ticket, dict) and ticket.get("status") == "ok":
                ok += 1
                continue
            failed += 1
            details = ticket.get("details") if isinstance(ticket, dict) else None
            if isinstance(details, dict) and details.get("error") == "DeviceNotRegistered":
                type(dev).objects.filter(pk=dev.pk).update(is_active=False)
    return ok, failed
