"""Ensure the `email_automation` package is importable (sibling repo layout)."""
from __future__ import annotations

import os
import sys


def ensure_email_automation_on_path(mailpilot_root: str) -> None:
    """Prepend the directory that contains the `email_automation` package to sys.path.

    Layout: ``<parent>/MailPilot/`` (this app) and ``<parent>/email_automation/src/email_automation/``.
    Also supports a monorepo layout with ``<parent>/src/email_automation/``.
    """
    repo_root = os.path.dirname(os.path.abspath(mailpilot_root))
    candidates = [
        os.path.join(repo_root, "email_automation", "src"),
        os.path.join(repo_root, "src"),
    ]
    for p in candidates:
        init_py = os.path.join(p, "email_automation", "__init__.py")
        if os.path.isfile(init_py):
            ap = os.path.abspath(p)
            if ap not in sys.path:
                sys.path.insert(0, ap)
            return
