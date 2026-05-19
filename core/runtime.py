"""Process-wide state: settings merge, stores, worker poll, APScheduler or Celery."""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from pydantic import ValidationError

if TYPE_CHECKING:
    from django.contrib.auth.models import User

log = logging.getLogger("mailpilot.runtime")

_CONFIG_SECRET_KEYS = frozenset({"SMTP_PASSWORD", "IMAP_PASSWORD", "LLM_API_KEY"})

_scheduler: Optional[BackgroundScheduler] = None
_scheduler_started = False
_warned_smtp_without_inbox = False
_gmail_invalid_grant_seen: set[int | None] = set()
_mail_poll_backend: str = "none"
_mail_poll_interval_sec: Optional[int] = None


def _strip_empty_secret_overrides(overrides: dict[str, Any]) -> dict[str, Any]:
    out = dict(overrides)
    for k in _CONFIG_SECRET_KEYS:
        if k in out and (out[k] is None or (isinstance(out[k], str) and not str(out[k]).strip())):
            del out[k]
    return out


@dataclass
class WorkerState:
    running: bool = False
    last_run_at: Optional[str] = None
    last_result: Optional[dict] = None
    last_error: Optional[str] = None
    lock: threading.Lock = threading.Lock()


_settings = None
_config_store = None
_state_store_singleton = None
_worker_state = WorkerState()


def _repo_root() -> str:
    from django.conf import settings as dj

    return str(dj.BASE_DIR)


def _ensure_imports():
    global _settings, _config_store, _state_store_singleton
    if _settings is not None:
        return
    from email_automation.config_store import ConfigStore
    from email_automation.settings import Settings

    rr = _repo_root()
    _settings = Settings()
    _config_store = ConfigStore(path=os.path.join(rr, "data", "app_config.json"))
    from core.state_store import StateStore

    _state_store_singleton = StateStore(tenant_id="")


def base_settings():
    _ensure_imports()
    return _settings


def config_store():
    _ensure_imports()
    return _config_store


def state_store_for_user(user: Optional[User] = None):
    """Rows scoped by tenant_id = str(user.id)."""
    from core.state_store import StateStore

    _ensure_imports()
    tid = str(user.id) if user is not None and getattr(user, "is_authenticated", False) else ""
    return StateStore(tenant_id=tid)


def state_store():
    """Legacy global (tenant_id='') for scripts; prefer state_store_for_user."""
    return state_store_for_user(None)


def worker_state() -> WorkerState:
    return _worker_state


def mail_poll_backend() -> str:
    """How automatic mail polling runs: apscheduler, celery, or none."""
    return _mail_poll_backend


def mail_poll_interval_seconds() -> Optional[int]:
    """APScheduler interval when backend is apscheduler; None otherwise."""
    return _mail_poll_interval_sec


def settings_field_names() -> set[str]:
    from email_automation.settings import Settings

    return set(Settings.model_fields.keys())


def get_effective_settings(user: Optional[User] = None):
    from email_automation.settings import Settings

    def _derive_imap_from_smtp(d: dict[str, Any]) -> dict[str, Any]:
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
        if str(out.get("SMTP_TLS_SERVERNAME") or "").strip() and not str(out.get("IMAP_TLS_SERVERNAME") or "").strip():
            out["IMAP_TLS_SERVERNAME"] = str(out.get("SMTP_TLS_SERVERNAME") or "").strip()
        return out

    if user is not None and getattr(user, "is_authenticated", False):
        from core.user_settings import build_effective_settings

        return build_effective_settings(user)

    _ensure_imports()
    overrides = _strip_empty_secret_overrides(config_store().load())
    filtered = {k: v for k, v in overrides.items() if k in settings_field_names()}
    merged: dict = _settings.model_dump(mode="python")
    merged.update(filtered)
    merged = _derive_imap_from_smtp(merged)
    try:
        return Settings.model_validate(merged)
    except ValidationError as e:
        log.warning("Ignoring invalid data in app_config.json (using .env defaults): %s", e)
        return _settings


def trigger_poll_fn(user: Optional[User] = None, user_id: Optional[int] = None, *, fast: bool = False):
    from email_automation.gmail_auth import gmail_oauth_ready
    from email_automation.gmail_client import GmailClient
    from email_automation.imap_mailbox import imap_inbox_ready
    from email_automation.worker import PollResult, poll_once, poll_once_imap

    if user_id is not None and user is None:
        from django.contrib.auth.models import User

        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return PollResult(scanned=0, relevant=0, sent=0, drafts=0, ignored=0, queued=0)

    effective = get_effective_settings(user)
    g_ok = gmail_oauth_ready(effective)
    out_from = (effective.outbound_from_email() or "").strip()
    # Gmail send uses OAuth "me" when From is unset; do not block poll solely on missing SMTP_FROM.
    if not out_from and not g_ok:
        return PollResult(scanned=0, relevant=0, sent=0, drafts=0, ignored=0, queued=0)

    st = state_store_for_user(user)

    # Prefer Gmail API poll when OAuth token exists — matches users who connected Gmail in the UI
    # but still have SEND_TRANSPORT=smtp + derived IMAP from .env (otherwise IMAP branch ran first and skipped Gmail).
    if g_ok:
        try:
            gmail_client = GmailClient(settings=effective)
            return poll_once(settings=effective, state_store=st, gmail_client=gmail_client)
        except Exception as e:
            from email_automation.gmail_auth import invalidate_gmail_oauth, is_invalid_grant_error

            uid = getattr(user, "id", None) if user is not None else None
            if is_invalid_grant_error(e):
                if uid not in _gmail_invalid_grant_seen:
                    _gmail_invalid_grant_seen.add(uid)
                    invalidate_gmail_oauth(effective, user=user)
                    log.warning(
                        "Gmail OAuth token expired or revoked (user_id=%s). "
                        "Reconnect Gmail in Setup/Settings — stale token removed.",
                        uid,
                    )
            else:
                log.warning("Gmail poll failed: %s", e)

    if effective.SEND_TRANSPORT == "smtp" and imap_inbox_ready(effective):
        try:
            return poll_once_imap(settings=effective, state_store=st, fast=fast)
        except Exception as e:
            log.warning("IMAP poll failed: %s", e)

    global _warned_smtp_without_inbox
    if (
        effective.SEND_TRANSPORT == "smtp"
        and not imap_inbox_ready(effective)
        and not g_ok
        and not _warned_smtp_without_inbox
    ):
        _warned_smtp_without_inbox = True
        log.warning(
            "SEND_TRANSPORT=smtp but no usable inbox: configure IMAP (host + user + password, "
            "same as SMTP) or connect Gmail OAuth. Worker cannot read mail until one of these works."
        )

    return PollResult(scanned=0, relevant=0, sent=0, drafts=0, ignored=0, queued=0)


def _scheduled_job():
    from email_automation.worker import PollResult

    ws = worker_state()
    with ws.lock:
        ws.running = True
        ws.last_error = None
        try:
            from django.contrib.auth.models import User

            from core.models import UserMailSettings

            user_ids = list(UserMailSettings.objects.values_list("user_id", flat=True).distinct())
            if not user_ids:
                result = trigger_poll_fn(user=None)
            else:
                total = PollResult(scanned=0, relevant=0, sent=0, drafts=0, ignored=0, queued=0)
                for uid in user_ids:
                    try:
                        u = User.objects.get(pk=uid)
                        r = trigger_poll_fn(user=u)
                        total = PollResult(
                            scanned=total.scanned + r.scanned,
                            relevant=total.relevant + r.relevant,
                            sent=total.sent + r.sent,
                            drafts=total.drafts + r.drafts,
                            ignored=total.ignored + r.ignored,
                            queued=total.queued + r.queued,
                        )
                    except Exception as e:
                        log.warning("poll user %s failed: %s", uid, e)
                result = total
            ws.last_result = {
                "scanned": result.scanned,
                "relevant": result.relevant,
                "sent": result.sent,
                "drafts": result.drafts,
                "ignored": result.ignored,
                "queued": result.queued,
            }
        except Exception as e:
            ws.last_error = str(e)
        finally:
            ws.last_run_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            ws.running = False


def ensure_scheduler_started() -> None:
    global _scheduler, _scheduler_started, _mail_poll_backend, _mail_poll_interval_sec
    if _scheduler_started:
        return
    if "runserver" in sys.argv and os.environ.get("RUN_MAIN") != "true":
        _mail_poll_backend = "none"
        _mail_poll_interval_sec = None
        return
    if os.environ.get("CELERY_BROKER_URL"):
        _mail_poll_backend = "celery"
        _mail_poll_interval_sec = None
        log.info("CELERY_BROKER_URL set — in-process APScheduler disabled (use Celery beat).")
        return
    _ensure_imports()
    if _settings.WORKER_ONCE:
        _mail_poll_backend = "none"
        _mail_poll_interval_sec = None
        return
    from datetime import datetime, timezone

    from django.conf import settings as dj_settings

    sec = max(10, int(getattr(dj_settings, "MAIL_POLL_INTERVAL_SECONDS", 60)))
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        _scheduled_job,
        trigger="interval",
        seconds=sec,
        id="mail_poll_job",
        max_instances=1,
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),
    )
    _scheduler.start()
    _scheduler_started = True
    _mail_poll_backend = "apscheduler"
    _mail_poll_interval_sec = sec
    log.info("APScheduler started (interval=%ss) — automatic inbox poll", sec)
    try:
        from core.imap_idle import ensure_imap_idle_watchers

        ensure_imap_idle_watchers()
    except Exception as e:
        log.warning("IMAP IDLE watchers failed to start: %s", e)
