from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest

from src.repository.contest_repository import ContestRepository


class FakeBatchClient:
    def __init__(self, table_name: str, items: dict[str, dict[str, Any]], responses: list[dict[str, Any]] | None = None) -> None:
        self.table_name = table_name
        self.items = items
        self.calls: list[dict[str, Any]] = []
        self.responses = responses or []

    def batch_get_item(self, *, RequestItems: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(deepcopy(RequestItems))
        if self.responses:
            return self.responses.pop(0)
        request = RequestItems[self.table_name]
        found = [self.items[key["contest_id"]] for key in request["Keys"] if key["contest_id"] in self.items]
        return {"Responses": {self.table_name: list(reversed(found))}, "UnprocessedKeys": {}}


class FakeTable:
    def __init__(self, items: dict[str, dict[str, Any]], responses: list[dict[str, Any]] | None = None) -> None:
        self.name = "contest-table"
        self.meta = SimpleNamespace(client=FakeBatchClient(self.name, items, responses))


def contest_item(contest_id: str) -> dict[str, str]:
    return {"contest_id": contest_id}


def test_get_existing_ids_uses_one_strongly_consistent_batch_for_up_to_100_unique_ids() -> None:
    table = FakeTable({"contestkorea:1": contest_item("contestkorea:1"), "contestkorea:3": contest_item("contestkorea:3")})
    repository = ContestRepository(table)

    existing = repository.get_existing_ids(["contestkorea:1", "contestkorea:2", "contestkorea:1", "contestkorea:3"])

    assert existing == {"contestkorea:1", "contestkorea:3"}
    assert repository.read_count == 3
    assert repository.batch_get_request_count == 1
    request = table.meta.client.calls[0]["contest-table"]
    assert request["Keys"] == [{"contest_id": "contestkorea:1"}, {"contest_id": "contestkorea:2"}, {"contest_id": "contestkorea:3"}]
    assert request["ConsistentRead"] is True
    assert request["ProjectionExpression"] == "contest_id"


def test_get_existing_ids_chunks_101_candidates_into_two_requests() -> None:
    ids = [f"contestkorea:{index}" for index in range(101)]
    table = FakeTable({contest_id: contest_item(contest_id) for contest_id in ids[::2]})
    repository = ContestRepository(table)

    existing = repository.get_existing_ids(ids)

    assert existing == set(ids[::2])
    assert repository.read_count == 101
    assert repository.batch_get_request_count == 2
    assert len(table.meta.client.calls[0]["contest-table"]["Keys"]) == 100
    assert len(table.meta.client.calls[1]["contest-table"]["Keys"]) == 1


def test_get_existing_ids_retries_unprocessed_keys_and_keeps_prior_partial_results(monkeypatch) -> None:
    initial_request = {
        "contest-table": {
            "Keys": [{"contest_id": "contestkorea:1"}, {"contest_id": "contestkorea:2"}],
            "ConsistentRead": True,
            "ProjectionExpression": "contest_id",
        }
    }
    responses = [
        {
            "Responses": {"contest-table": [contest_item("contestkorea:1")]},
            "UnprocessedKeys": {"contest-table": initial_request["contest-table"]},
        },
        {"Responses": {"contest-table": [contest_item("contestkorea:2")]}, "UnprocessedKeys": {}},
    ]
    table = FakeTable({}, responses)
    repository = ContestRepository(table)
    monkeypatch.setattr("src.repository.contest_repository.time.sleep", lambda _seconds: None)

    existing = repository.get_existing_ids(["contestkorea:1", "contestkorea:2"])

    assert existing == {"contestkorea:1", "contestkorea:2"}
    assert repository.batch_get_request_count == 2
    assert repository.unprocessed_key_retry_count == 1
    assert table.meta.client.calls[1] == {"contest-table": initial_request["contest-table"]}


def test_get_existing_ids_fails_after_limited_unprocessed_key_retries(monkeypatch) -> None:
    unprocessed = {
        "contest-table": {
            "Keys": [{"contest_id": "contestkorea:1"}],
            "ConsistentRead": True,
            "ProjectionExpression": "contest_id",
        }
    }
    table = FakeTable({}, [{"Responses": {}, "UnprocessedKeys": unprocessed} for _ in range(4)])
    repository = ContestRepository(table)
    monkeypatch.setattr("src.repository.contest_repository.time.sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="unprocessed contest keys"):
        repository.get_existing_ids(["contestkorea:1"])

    assert repository.batch_get_request_count == 4
    assert repository.unprocessed_key_retry_count == 3
