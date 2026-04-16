from __future__ import annotations

import json
import os
from typing import Any


class ConfigStore:
    def __init__(self, path: str):
        self.path = path

    def load(self) -> dict[str, Any]:
        p = (self.path or "").strip()
        if not p or not os.path.exists(p):
            return {}
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.loads(f.read() or "{}") or {}
        except Exception:
            return {}

    def save(self, data: dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data or {}, f, ensure_ascii=False, indent=2)

