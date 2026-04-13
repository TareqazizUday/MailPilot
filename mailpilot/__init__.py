# Django project package (Mailpilot)
from __future__ import annotations

try:
    from .celery import app as celery_app
except ImportError:
    celery_app = None
