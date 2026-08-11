"""DynamoDB access for contest records."""

from __future__ import annotations

from typing import Any, Protocol

from src.domain.contest import Contest


class DynamoTable(Protocol):
    def get_item(self, **kwargs: Any) -> dict[str, Any]: ...

    def put_item(self, **kwargs: Any) -> dict[str, Any]: ...

    def update_item(self, **kwargs: Any) -> dict[str, Any]: ...


class ContestRepository:
    """Repository for the Contest Table keyed by contest_id."""

    def __init__(self, table: DynamoTable) -> None:
        self._table = table
        self.read_count = 0
        self.write_count = 0

    def get(self, contest_id: str) -> Contest | None:
        self.read_count += 1
        response = self._table.get_item(Key={"contest_id": contest_id}, ConsistentRead=True)
        item = response.get("Item")
        return Contest.from_item(item) if item else None

    def save(self, contest: Contest) -> None:
        self.write_count += 1
        self._table.put_item(Item=contest.to_item())

    def update_last_seen(self, contest_id: str, checked_at: str) -> None:
        self.write_count += 1
        self._table.update_item(
            Key={"contest_id": contest_id},
            UpdateExpression="SET last_seen_at = :checked_at",
            ExpressionAttributeValues={":checked_at": checked_at},
        )
