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

_django_application = get_wsgi_application()


def application(environ, start_response):
    """IIS terminates HTTPS and proxies HTTP to Waitress; inject forwarded headers when configured."""
    if (os.environ.get("DJANGO_BEHIND_HTTPS_PROXY") or "").strip().lower() in ("1", "true", "yes"):
        if not environ.get("HTTP_X_FORWARDED_PROTO"):
            environ["HTTP_X_FORWARDED_PROTO"] = "https"
        if not environ.get("HTTP_X_FORWARDED_HOST") and environ.get("HTTP_HOST"):
            environ["HTTP_X_FORWARDED_HOST"] = environ["HTTP_HOST"]
    return _django_application(environ, start_response)
