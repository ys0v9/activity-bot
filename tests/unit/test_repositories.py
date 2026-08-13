from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

from src.domain.contest import Contest
from src.repository.contest_repository import ContestRepository
from src.repository.discovery import ContestDiscovery
from src.repository.state_repository import StateRepository


class FakeTable:
    def __init__(self, key_name: str) -> None:
        self.key_name = key_name
        self.name = key_name
        self.items: dict[str, dict[str, Any]] = {}
        self.meta = SimpleNamespace(client=self)

    def get_item(self, *, Key: dict[str, str], **_: Any) -> dict[str, Any]:
        item = self.items.get(Key[self.key_name])
        return {"Item": deepcopy(item)} if item else {}

    def batch_get_item(self, *, RequestItems: dict[str, Any]) -> dict[str, Any]:
        request = RequestItems[self.name]
        items = [self.items[key[self.key_name]] for key in request["Keys"] if key[self.key_name] in self.items]
        return {"Responses": {self.name: deepcopy(items)}, "UnprocessedKeys": {}}

    def put_item(self, *, Item: dict[str, Any], **_: Any) -> dict[str, Any]:
        self.items[Item[self.key_name]] = deepcopy(Item)
        return {}

    def update_item(
        self,
        *,
        Key: dict[str, str],
        ExpressionAttributeValues: dict[str, str],
        **_: Any,
    ) -> dict[str, Any]:
        self.items[Key[self.key_name]].update({"last_seen_at": ExpressionAttributeValues.get(":checked_at")})
        if ":checked_at" in ExpressionAttributeValues and self.key_name == "discord_user_id":
            self.items[Key[self.key_name]]["last_checked_at"] = ExpressionAttributeValues[":checked_at"]
        return {}


def contest(contest_id: str = "contestkorea:1") -> Contest:
    return Contest(
        contest_id=contest_id,
        source="contestkorea",
        title="테스트 공모전",
        category=None,
        organizer=None,
        target=None,
        application_start=None,
        application_end=None,
        status="접수중",
        detail_url="https://example.test/1",
    )


def test_first_request_saves_baseline_without_returning_new_contests() -> None:
    contest_table = FakeTable("contest_id")
    state_table = FakeTable("discord_user_id")
    service = ContestDiscovery(ContestRepository(contest_table), StateRepository(state_table))

    result = service.process("user-1", [contest("contestkorea:1"), contest("contestkorea:2")], "2026-08-09T00:00:00+00:00")

    assert result.initialized is True
    assert result.total_contest_count == 2
    assert result.new_contests == []
    assert state_table.items["user-1"]["initialized"] is True
    assert len(contest_table.items) == 2


def test_existing_contest_is_not_returned_and_last_seen_stays_at_first_seen() -> None:
    contest_table = FakeTable("contest_id")
    state_table = FakeTable("discord_user_id")
    contest_repository = ContestRepository(contest_table)
    state_repository = StateRepository(state_table)
    service = ContestDiscovery(contest_repository, state_repository)
    service.process("user-1", [contest()], "2026-08-09T00:00:00+00:00")

    result = service.process("user-1", [contest()], "2026-08-10T00:00:00+00:00")

    assert result.initialized is False
    assert result.new_contests == []
    assert contest_table.items["contestkorea:1"]["last_seen_at"] == "2026-08-09T00:00:00+00:00"
    assert contest_repository.write_count == 1
    assert state_repository.write_count == 2
    assert state_table.items["user-1"]["last_checked_at"] == "2026-08-10T00:00:00+00:00"


def test_only_unseen_contest_is_returned_after_initialization() -> None:
    contest_table = FakeTable("contest_id")
    state_table = FakeTable("discord_user_id")
    contest_repository = ContestRepository(contest_table)
    state_repository = StateRepository(state_table)
    service = ContestDiscovery(contest_repository, state_repository)
    service.process("user-1", [contest("contestkorea:1")], "2026-08-09T00:00:00+00:00")

    result = service.process(
        "user-1",
        [contest("contestkorea:1"), contest("contestkorea:2")],
        "2026-08-10T00:00:00+00:00",
    )

    assert [item.contest_id for item in result.new_contests] == ["contestkorea:2"]
    assert contest_repository.write_count == 2
    assert contest_table.items["contestkorea:1"]["last_seen_at"] == "2026-08-09T00:00:00+00:00"
    assert contest_table.items["contestkorea:2"]["last_seen_at"] == "2026-08-10T00:00:00+00:00"
    assert state_repository.write_count == 2


def test_duplicate_crawled_contests_are_saved_once() -> None:
    contest_table = FakeTable("contest_id")
    state_table = FakeTable("discord_user_id")
    service = ContestDiscovery(ContestRepository(contest_table), StateRepository(state_table))

    result = service.process("user-1", [contest(), contest()], "2026-08-09T00:00:00+00:00")

    assert result.total_contest_count == 1
    assert len(contest_table.items) == 1
