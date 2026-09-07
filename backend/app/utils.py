"""Tiny shared helpers."""
from __future__ import annotations

import uuid


def is_valid_uuid(value: object) -> bool:
    """True when value parses as a UUID (asyncpg errors on malformed input)."""
    if not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False