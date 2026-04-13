"""Celery application — optional when CELERY_BROKER_URL is set."""
from __future__ import annotations

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mailpilot.settings")

app = Celery("mailpilot")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
