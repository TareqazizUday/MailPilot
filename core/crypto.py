"""Fernet field encryption using FIELD_ENCRYPTION_KEY from environment."""
from __future__ import annotations

import base64
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


def _fernet() -> Optional[Fernet]:
    raw = (os.environ.get("FIELD_ENCRYPTION_KEY") or "").strip()
    if not raw:
        return None
    try:
        # Fernet key from `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
        return Fernet(raw.encode("ascii"))
    except Exception:
        return None


def encrypt_str(plain: str) -> str:
    if not plain:
        return ""
    f = _fernet()
    if f is None:
        # Dev fallback: store base64 (not secure — set FIELD_ENCRYPTION_KEY in production)
        return "plain:" + base64.b64encode(plain.encode("utf-8")).decode("ascii")
    return f.encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_str(enc: str) -> str:
    if not enc:
        return ""
    if enc.startswith("plain:"):
        try:
            return base64.b64decode(enc[6:].encode("ascii")).decode("utf-8")
        except Exception:
            return ""
    f = _fernet()
    if f is None:
        return ""
    try:
        return f.decrypt(enc.encode("ascii")).decode("utf-8")
    except InvalidToken:
        return ""
