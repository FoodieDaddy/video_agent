"""Identifier helpers and small time utilities."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime


def new_id(prefix: str) -> str:
    """Readable, sortable-enough identifiers, e.g. ``shot_1f2c3d4e5f60``."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def utcnow() -> datetime:
    """Naive UTC timestamp (SQLite friendly, comparable everywhere)."""
    return datetime.now(UTC).replace(tzinfo=None)


def slugify(value: str, fallback: str = "item") -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fa5_-]+", "-", value or "").strip("-").lower()
    return cleaned[:60] or fallback


def short_hash(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
