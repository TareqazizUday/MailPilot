"""IMAP IDLE — near real-time inbox notifications for SMTP/IMAP mailboxes."""
from __future__ import annotations

import imaplib
import logging
import socket
import ssl
import threading
import time
from typing import Optional

log = logging.getLogger("mailpilot.imap_idle")

_idle_threads: dict[int, threading.Thread] = {}
_idle_lock = threading.Lock()
_idle_enabled = True


def imap_idle_enabled() -> bool:
    import os

    return (os.environ.get("IMAP_IDLE_ENABLED") or "true").strip().lower() in ("1", "true", "yes")


def _connect_imap(settings):
    host = (settings.IMAP_HOST or "").strip()
    port = int(getattr(settings, "IMAP_PORT", 993) or 993)
    user = (settings.IMAP_USERNAME or "").strip()
    pw = settings.IMAP_PASSWORD.get_secret_value() if settings.IMAP_PASSWORD else ""
    if not (host and user and pw):
        raise RuntimeError("IMAP not configured")

    verify = bool(getattr(settings, "IMAP_VERIFY_TLS", True))
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    socket.setdefaulttimeout(30)
    if port == 993:
        conn = imaplib.IMAP4_SSL(host, port, ssl_context=ctx)
    else:
        conn = imaplib.IMAP4(host, port)
        try:
            conn.starttls(ssl_context=ctx)
        except Exception:
            pass
    typ, _ = conn.login(user, pw)
    if typ != "OK":
        raise RuntimeError("IMAP login failed")
    mailbox = (settings.IMAP_MAILBOX or "INBOX").strip() or "INBOX"
    typ, _ = conn.select(mailbox)
    if typ != "OK":
        raise RuntimeError(f"IMAP select failed: {mailbox}")
    return conn


def _server_supports_idle(conn: imaplib.IMAP4) -> bool:
    try:
        typ, data = conn.capability()
        if typ != "OK":
            return False
        blob = b" ".join(data or []).upper()
        return b"IDLE" in blob
    except Exception:
        return False


def _idle_wait_for_mail(conn: imaplib.IMAP4, stop: threading.Event, timeout_sec: int = 1740) -> bool:
    """Block until EXISTS/RECENT or stop. Returns True if new-mail hint seen."""
    tag = conn._new_tag()
    conn.send(f"{tag} IDLE\r\n".encode("utf-8"))
    got_mail = False
    deadline = time.time() + timeout_sec
    try:
        while not stop.is_set() and time.time() < deadline:
            if conn.sock is None:
                break
            conn.sock.settimeout(0.5)
            try:
                line = conn.readline()
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                break
            if not line:
                break
            text = line.decode("utf-8", errors="replace").upper()
            if "EXISTS" in text or "RECENT" in text:
                got_mail = True
                break
    finally:
        try:
            conn.send(b"DONE\r\n")
            conn.readline()
        except Exception:
            pass
    return got_mail


def _idle_worker(user_id: int, stop: threading.Event) -> None:
    from django.contrib.auth.models import User

    from core import runtime
    from core.user_settings import build_effective_settings
    from email_automation.imap_mailbox import imap_inbox_ready

    backoff = 5
    while not stop.is_set():
        conn: Optional[imaplib.IMAP4] = None
        try:
            user = User.objects.get(pk=user_id)
            settings = build_effective_settings(user)
            if str(settings.SEND_TRANSPORT or "").strip() != "smtp" or not imap_inbox_ready(settings):
                time.sleep(30)
                continue
            conn = _connect_imap(settings)
            if not _server_supports_idle(conn):
                log.warning("IMAP IDLE not supported for user %s — using interval poll only", user_id)
                time.sleep(60)
                continue
            log.info("IMAP IDLE listening user_id=%s mailbox=%s", user_id, settings.IMAP_MAILBOX)
            while not stop.is_set():
                if _idle_wait_for_mail(conn, stop):
                    log.info("IMAP IDLE: new mail signal user_id=%s — running poll", user_id)
                    try:
                        runtime.trigger_poll_fn(user=user, fast=True)
                    except Exception as e:
                        log.warning("IMAP IDLE poll failed user %s: %s", user_id, e)
                else:
                    break
        except Exception as e:
            log.warning("IMAP IDLE loop error user %s: %s (retry in %ss)", user_id, e, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 120)
        finally:
            if conn is not None:
                try:
                    conn.logout()
                except Exception:
                    pass
            if not stop.is_set():
                time.sleep(backoff)


def ensure_imap_idle_watchers() -> None:
    """Start one daemon thread per IMAP-ready user (SMTP transport)."""
    global _idle_enabled
    if not imap_idle_enabled():
        _idle_enabled = False
        return
    try:
        from django.contrib.auth.models import User

        from core.models import UserMailSettings
        from core.user_settings import build_effective_settings
        from email_automation.imap_mailbox import imap_inbox_ready
    except Exception as e:
        log.warning("IMAP IDLE watchers not started: %s", e)
        return

    user_ids = list(UserMailSettings.objects.values_list("user_id", flat=True).distinct())
    with _idle_lock:
        for uid in user_ids:
            if uid in _idle_threads and _idle_threads[uid].is_alive():
                continue
            try:
                u = User.objects.get(pk=uid)
                eff = build_effective_settings(u)
                if str(eff.SEND_TRANSPORT or "").strip() != "smtp" or not imap_inbox_ready(eff):
                    continue
            except Exception:
                continue
            stop = threading.Event()
            t = threading.Thread(target=_idle_worker, args=(int(uid), stop), daemon=True, name=f"imap-idle-{uid}")
            _idle_threads[int(uid)] = t
            t.start()
            log.info("Started IMAP IDLE watcher for user_id=%s", uid)


def imap_idle_active_count() -> int:
    with _idle_lock:
        return sum(1 for t in _idle_threads.values() if t.is_alive())
