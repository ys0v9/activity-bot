"""DynamoDB access for Discord user check state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.repository.contest_repository import DynamoTable


@dataclass(frozen=True, slots=True)
class UserState:
    discord_user_id: str
    initialized: bool
    initialized_at: str | None
    last_checked_at: str | None

    @classmethod
    def from_item(cls, item: dict[str, Any]) -> "UserState":
        return cls(
            discord_user_id=item["discord_user_id"],
            initialized=bool(item.get("initialized", False)),
            initialized_at=item.get("initialized_at"),
            last_checked_at=item.get("last_checked_at"),
        )


class StateRepository:
    """Repository for State Table keyed by discord_user_id."""

    def __init__(self, table: DynamoTable) -> None:
        self._table = table
        self.read_count = 0
        self.write_count = 0

    def get(self, discord_user_id: str) -> UserState | None:
        self.read_count += 1
        response = self._table.get_item(Key={"discord_user_id": discord_user_id}, ConsistentRead=True)
        item = response.get("Item")
        return UserState.from_item(item) if item else None

    def initialize(self, discord_user_id: str, initialized_at: str) -> None:
        self.write_count += 1
        self._table.put_item(
            Item={
                "discord_user_id": discord_user_id,
                "initialized": True,
                "initialized_at": initialized_at,
                "last_checked_at": initialized_at,
            }
        )

    def update_last_checked_at(self, discord_user_id: str, checked_at: str) -> None:
        self.write_count += 1
        self._table.update_item(
            Key={"discord_user_id": discord_user_id},
            UpdateExpression="SET last_checked_at = :checked_at",
            ExpressionAttributeValues={":checked_at": checked_at},
        )
