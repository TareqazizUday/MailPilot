from __future__ import annotations

import sys

from django.contrib.staticfiles.management.commands.runserver import Command as StaticfilesRunserverCommand
from django.core.servers.basehttp import WSGIServer


class QuietTimeoutWSGIServer(WSGIServer):
    """Drop noisy stacktraces for harmless client socket timeouts."""

    def handle_error(self, request, client_address):  # noqa: ANN001
        exc_type, exc, _tb = sys.exc_info()
        if isinstance(exc, TimeoutError):
            return
        return super().handle_error(request, client_address)


class Command(StaticfilesRunserverCommand):
    """Override Django's runserver to silence TimeoutError noise."""

    server_cls = QuietTimeoutWSGIServer

