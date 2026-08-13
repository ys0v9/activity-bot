"""DynamoDB access for contest records."""

from __future__ import annotations

import time
from typing import Any, Protocol

from src.domain.contest import Contest


class DynamoTable(Protocol):
    name: str
    meta: Any

    def get_item(self, **kwargs: Any) -> dict[str, Any]: ...

    def put_item(self, **kwargs: Any) -> dict[str, Any]: ...



class ContestRepository:
    """Repository for the Contest Table keyed by contest_id."""

    _BATCH_GET_SIZE = 100
    _MAX_UNPROCESSED_KEY_RETRIES = 3
    _INITIAL_BACKOFF_SECONDS = 0.05

    def __init__(self, table: DynamoTable) -> None:
        self._table = table
        self.read_count = 0
        self.write_count = 0
        self.batch_get_request_count = 0
        self.unprocessed_key_retry_count = 0

    def get(self, contest_id: str) -> Contest | None:
        self.read_count += 1
        response = self._table.get_item(Key={"contest_id": contest_id}, ConsistentRead=True)
        item = response.get("Item")
        return Contest.from_item(item) if item else None

    def get_existing_ids(self, contest_ids: list[str] | tuple[str, ...]) -> set[str]:
        """Return existing IDs with strongly consistent BatchGetItem calls.

        DynamoDB accepts up to 100 keys per request and can return partial
        responses. Requested IDs are deduplicated before batching; returned IDs
        are deliberately treated as an unordered set.
        """
        unique_ids = tuple(dict.fromkeys(contest_ids))
        self.read_count += len(unique_ids)
        existing_ids: set[str] = set()

        for index in range(0, len(unique_ids), self._BATCH_GET_SIZE):
            request_items: dict[str, Any] = {
                self._table.name: {
                    "Keys": [{"contest_id": contest_id} for contest_id in unique_ids[index : index + self._BATCH_GET_SIZE]],
                    "ConsistentRead": True,
                    "ProjectionExpression": "contest_id",
                }
            }
            existing_ids.update(self._batch_get_ids(request_items))

        return existing_ids

    def _batch_get_ids(self, request_items: dict[str, Any]) -> set[str]:
        existing_ids: set[str] = set()
        for retry_number in range(self._MAX_UNPROCESSED_KEY_RETRIES + 1):
            self.batch_get_request_count += 1
            response = self._table.meta.client.batch_get_item(RequestItems=request_items)
            found = response.get("Responses", {}).get(self._table.name, [])
            existing_ids.update(item["contest_id"] for item in found if item.get("contest_id"))
            unprocessed = response.get("UnprocessedKeys", {})
            if not unprocessed:
                return existing_ids
            if retry_number == self._MAX_UNPROCESSED_KEY_RETRIES:
                raise RuntimeError("DynamoDB BatchGetItem left unprocessed contest keys after retry limit")

            self.unprocessed_key_retry_count += 1
            time.sleep(self._INITIAL_BACKOFF_SECONDS * (2**retry_number))
            request_items = unprocessed

        raise AssertionError("unreachable")

    def save(self, contest: Contest) -> None:
        self.write_count += 1
        self._table.put_item(Item=contest.to_item())
