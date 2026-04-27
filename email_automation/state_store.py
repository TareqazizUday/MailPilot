from __future__ import annotations

"""
Compatibility shim.

The project previously used a dedicated SQLite file for StateStore.
StateStore is now backed by the Django database (PostgreSQL in the target setup).
"""

from core.state_store import StateStore  # noqa: F401

