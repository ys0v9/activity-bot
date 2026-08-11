"""Normalized contest domain model."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Contest:
    """A contest observed on a public source."""

    contest_id: str
    source: str
    title: str
    category: str | None
    organizer: str | None
    target: str | None
    application_start: str | None
    application_end: str | None
    status: str | None
    detail_url: str
    first_seen_at: str | None = None
    last_seen_at: str | None = None

    def to_item(self) -> dict[str, Any]:
        """Return a DynamoDB-compatible plain dictionary without null values."""
        return {key: value for key, value in asdict(self).items() if value is not None}

    @classmethod
    def from_item(cls, item: dict[str, Any]) -> "Contest":
        """Build the model from a DynamoDB item."""
        fields = {field: item.get(field) for field in cls.__dataclass_fields__}
        return cls(**fields)
