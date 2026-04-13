from __future__ import annotations

import logging

from django.apps import AppConfig

log = logging.getLogger("mailpilot.core")


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    label = "core"
    verbose_name = "Mailpilot core"

    def ready(self) -> None:
        try:
            from core import runtime  # noqa: F401

            runtime.ensure_scheduler_started()
        except Exception:
            log.exception("Mailpilot runtime init failed")
