"""Stable cross-module contracts for assets.

Do not mirror SQLAlchemy models or Pydantic schemas here. Export existing canonical
types when a stable cross-module contract is required.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AssetReference:
    """Stored asset reference returned to callers without exposing its ORM row."""

    asset_id: str
    project_id: str
    kind: str
    storage_key: str
    mime_type: str
    size_bytes: int


__all__ = ["AssetReference"]
