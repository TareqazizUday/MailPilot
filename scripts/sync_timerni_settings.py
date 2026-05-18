"""One-off: sync sohelrananull mail settings to timerni official ports."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mailpilot.settings")

import django

django.setup()

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

from django.contrib.auth.models import User

from core import runtime
from core.crypto import encrypt_str
from core.user_settings import build_effective_settings, get_or_create_mail_settings, save_settings_patch

u = User.objects.get(username="sohelrananull")
save_settings_patch(
    u,
    {
        "SMTP_HOST": "smtp.timerni.com",
        "SMTP_PORT": 465,
        "SMTP_USERNAME": "test3@timerni.com",
        "SMTP_USE_SSL": True,
        "SMTP_USE_TLS": False,
        "SMTP_VERIFY_TLS": False,
        "SMTP_TLS_SERVERNAME": "timerni.com",
        "SMTP_FROM_EMAIL": "test3@timerni.com",
        "IMAP_HOST": "imap.timerni.com",
        "IMAP_PORT": 993,
        "IMAP_USERNAME": "test3@timerni.com",
        "SEND_TRANSPORT": "smtp",
        "REPLY_MODE": "send",
    },
)
pw = (os.environ.get("SMTP_PASSWORD") or "").strip().strip("'\"")
if pw:
    ms = get_or_create_mail_settings(u)
    ms.smtp_password_enc = encrypt_str(pw)
    ms.imap_password_enc = encrypt_str(pw)
    ms.save()

e = build_effective_settings(u)
print("SMTP", e.SMTP_HOST, e.SMTP_PORT, "SSL", e.SMTP_USE_SSL)
print("IMAP", e.IMAP_HOST, e.IMAP_PORT)
print("POLL", runtime.trigger_poll_fn(user=u))
