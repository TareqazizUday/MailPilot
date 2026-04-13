"""WSGI config for Mailpilot."""
from __future__ import annotations

import os
import sys

_here = os.path.abspath(__file__)
mailpilot_root = os.path.dirname(os.path.dirname(_here))
os.chdir(mailpilot_root)

from mailpilot.path_setup import ensure_email_automation_on_path  # noqa: E402

ensure_email_automation_on_path(mailpilot_root)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mailpilot.settings")

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()
