from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from src.common.http_client import HttpMetrics
from src.crawler.contestkorea import ContestKoreaCrawler, ContestKoreaListItem
from src.repository.contest_repository import ContestRepository
from src.repository.discovery import CandidateClassification, ContestDiscovery
from src.repository.state_repository import StateRepository


FIXTURES = Path(__file__).parents[1] / "unit" / "fixtures"
CHECKED_AT = "2026-08-11T00:00:00+00:00"


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
        item = self.items[Key[self.key_name]]
        if self.key_name == "contest_id":
            item["last_seen_at"] = ExpressionAttributeValues[":checked_at"]
        else:
            item["last_checked_at"] = ExpressionAttributeValues[":checked_at"]
        return {}


class FixtureHttpClient:
    def __init__(self) -> None:
        self.metrics = HttpMetrics()
        self.detail_urls: list[str] = []
        self._list_calls = 0
        self._list_html = (FIXTURES / "contestkorea_list.html").read_text()
        self._detail_html = (FIXTURES / "contestkorea_detail.html").read_text()

    def get(self, url: str, *, request_type: str) -> SimpleNamespace:
        self.metrics.request_count += 1
        if request_type == "list":
            self.metrics.list_request_count += 1
            self._list_calls += 1
            html = self._list_html if self._list_calls == 1 else '<div class="list_style_2"><ul></ul></div>'
            return SimpleNamespace(text=html)
        if request_type == "detail":
            self.metrics.detail_request_count += 1
            self.detail_urls.append(url)
            return SimpleNamespace(text=self._detail_html)
        raise ValueError(request_type)


def make_service() -> tuple[ContestDiscovery, FakeTable, FakeTable]:
    contest_table = FakeTable("contest_id")
    state_table = FakeTable("discord_user_id")
    return ContestDiscovery(ContestRepository(contest_table), StateRepository(state_table)), contest_table, state_table


def list_items() -> list[ContestKoreaListItem]:
    client = FixtureHttpClient()
    crawler = ContestKoreaCrawler(client, max_pages=2)
    items = crawler.fetch_list_items()
    assert crawler.metrics.list_page_count == 2
    return [
        *items,
        ContestKoreaListItem(
            "세 번째 기존 공모전",
            None,
            None,
            None,
            "접수중",
            "https://www.contestkorea.com/sub/view.php?str_no=202608060001",
        ),
    ]


def process_list(
    service: ContestDiscovery,
    items: list[ContestKoreaListItem],
    client: FixtureHttpClient,
    *,
    checked_at: str = CHECKED_AT,
):
    crawler = ContestKoreaCrawler(client)
    classification = service.classify_candidates("user-1", (item.contest_id for item in items))
    by_id = {item.contest_id: item for item in items}
    detailed = [crawler.fetch_detail(by_id[contest_id]) for contest_id in classification.new_contest_ids]
    result = service.process_classified(
        "user-1",
        classification,
        detailed,
        checked_at,
        total_contest_count=len(items),
    )
    return classification, result


def test_initialization_fetches_every_new_list_candidate_detail() -> None:
    service, contest_table, _ = make_service()
    client = FixtureHttpClient()
    items = list_items()

    classification, result = process_list(service, items, client)

    assert classification.known_contest_ids == ()
    assert len(classification.new_contest_ids) == 3
    assert client.metrics.detail_request_count == 3
    assert result.initialized is True
    assert result.new_contests == []
    assert len(contest_table.items) == 3


def test_repeat_with_no_new_contests_skips_all_detail_requests_and_updates_last_seen() -> None:
    service, contest_table, _ = make_service()
    items = list_items()
    process_list(service, items, FixtureHttpClient(), checked_at="2026-08-10T00:00:00+00:00")
    client = FixtureHttpClient()

    classification, result = process_list(service, items, client)

    assert len(classification.known_contest_ids) == 3
    assert classification.new_contest_ids == ()
    assert len(classification.known_contest_ids) == 3  # skipped_detail_count invariant
    assert client.metrics.detail_request_count == 0
    assert result.new_contests == []
    assert all(item["last_seen_at"] == CHECKED_AT for item in contest_table.items.values())


def test_repeat_fetches_only_one_new_contest_detail() -> None:
    service, _, _ = make_service()
    existing_items = list_items()
    process_list(service, existing_items, FixtureHttpClient())
    new_item = replace(
        existing_items[0],
        title="새 공모전",
        detail_url="https://www.contestkorea.com/sub/view.php?int_gbn=1&Txt_bcode=030310001&str_no=202699990001",
    )
    client = FixtureHttpClient()

    classification, result = process_list(service, [*existing_items, new_item], client)

    assert len(classification.known_contest_ids) == 3
    assert classification.new_contest_ids == ("contestkorea:202699990001",)
    assert client.metrics.detail_request_count == 1
    assert client.detail_urls == [new_item.detail_url]
    assert [contest.contest_id for contest in result.new_contests] == ["contestkorea:202699990001"]


def test_known_contest_with_changed_list_title_is_not_new_or_fetched_again() -> None:
    service, _, _ = make_service()
    items = list_items()
    process_list(service, items, FixtureHttpClient())
    changed_title = replace(items[0], title="수정된 목록 제목")
    client = FixtureHttpClient()

    classification, result = process_list(service, [changed_title, *items[1:]], client)

    assert classification == CandidateClassification(
        is_first_check=False,
        known_contest_ids=tuple(item.contest_id for item in items),
        new_contest_ids=(),
    )
    assert client.metrics.detail_request_count == 0
    assert result.new_contests == []
