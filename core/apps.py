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
        # Defer scheduler/IMAP startup until Django finishes AppConfig.ready() — avoids
        # RuntimeWarning: Accessing the database during app initialization.
        import threading

        def _start_runtime() -> None:
            try:
                from core import runtime

                runtime.ensure_scheduler_started()
            except Exception:
                log.exception("Mailpilot runtime init failed")

        threading.Thread(target=_start_runtime, daemon=True, name="mailpilot-runtime-init").start()
