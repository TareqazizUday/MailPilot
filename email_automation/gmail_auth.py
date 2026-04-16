from __future__ import annotations

import os
from typing import Optional, Tuple

from email_automation.settings import Settings


def gmail_oauth_ready(settings: Settings) -> bool:
    token_path = (settings.GOOGLE_TOKEN_FILE or "").strip()
    if not token_path:
        return False
    return os.path.exists(token_path)


def gmail_oauth_try(settings: Settings) -> Tuple[bool, Optional[str]]:
    """Best-effort check that OAuth token exists.

    Full token validation requires live API calls; this shim only checks file presence.
    """
    if gmail_oauth_ready(settings):
        return True, None
    return False, "missing_token"

