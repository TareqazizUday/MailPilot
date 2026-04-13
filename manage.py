#!/usr/bin/env python
"""Django entrypoint for Mailpilot (Flask app migrated to Django)."""
from __future__ import annotations

import os
import sys


def main() -> None:
    mailpilot_root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(mailpilot_root)

    from mailpilot.path_setup import ensure_email_automation_on_path

    ensure_email_automation_on_path(mailpilot_root)

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mailpilot.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Is it installed and available on PYTHONPATH?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
