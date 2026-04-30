from __future__ import annotations

import sys

from django.core.management.commands.runserver import Command as RunserverCommand
from django.core.servers.basehttp import WSGIServer


class QuietTimeoutWSGIServer(WSGIServer):
    """Drop noisy stacktraces for harmless client socket timeouts."""

    def handle_error(self, request, client_address):  # noqa: ANN001
        exc_type, exc, _tb = sys.exc_info()
        if exc_type is TimeoutError:
            return
        return super().handle_error(request, client_address)


class Command(RunserverCommand):
    """Override Django's runserver to silence TimeoutError noise."""

    server_cls = QuietTimeoutWSGIServer

