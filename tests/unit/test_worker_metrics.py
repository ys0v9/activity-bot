from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import src.worker.handler as worker_handler
from src.common.http_client import HttpMetrics
from src.crawler.contestkorea import ContestKoreaListItem
from src.domain.contest import Contest


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


class FakeHttpClient:
    def __init__(self) -> None:
        self.metrics = HttpMetrics()

    def close(self) -> None:
        pass


def contest(contest_id: str) -> Contest:
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
        detail_url=f"https://www.contestkorea.com/sub/view.php?str_no={contest_id.split(':')[-1]}",
        first_seen_at="2026-08-10T00:00:00+00:00",
        last_seen_at="2026-08-10T00:00:00+00:00",
    )


class FakeCrawler:
    def __init__(self, http_client: FakeHttpClient) -> None:
        self.http_client = http_client
        self.metrics = SimpleNamespace(
            list_page_count=2,
            list_fetch_duration_ms=7,
            list_request_duration_ms_total=7,
            detail_fetch_duration_ms=0,
            list_parallelism=5,
            prefetched_list_page_count=0,
            crawler_error_count=0,
        )
        self.items = [
            ContestKoreaListItem("기존 A", None, None, None, "접수중", "https://www.contestkorea.com/sub/view.php?str_no=1"),
            ContestKoreaListItem("기존 B", None, None, None, "접수중", "https://www.contestkorea.com/sub/view.php?str_no=2"),
            ContestKoreaListItem("신규 C", None, None, None, "접수중", "https://www.contestkorea.com/sub/view.php?str_no=3"),
        ]

    def fetch_list_items(self) -> list[ContestKoreaListItem]:
        self.http_client.metrics.request_count += 2
        self.http_client.metrics.list_request_count += 2
        return self.items

    def fetch_detail(self, item: ContestKoreaListItem) -> Contest:
        self.http_client.metrics.request_count += 1
        self.http_client.metrics.detail_request_count += 1
        self.metrics.detail_fetch_duration_ms += 5
        return Contest(
            contest_id=item.contest_id,
            source="contestkorea",
            title=item.title,
            category=item.category,
            organizer=item.organizer,
            target=item.target,
            application_start=None,
            application_end=None,
            status=item.status,
            detail_url=item.detail_url,
        )


def test_worker_records_list_classification_and_detail_skip_metrics(monkeypatch) -> None:
    contest_table = FakeTable("contest_id")
    contest_table.items = {"contestkorea:1": contest("contestkorea:1").to_item(), "contestkorea:2": contest("contestkorea:2").to_item()}
    state_table = FakeTable("discord_user_id")
    state_table.items = {
        "user-1": {
            "discord_user_id": "user-1",
            "initialized": True,
            "initialized_at": "2026-08-10T00:00:00+00:00",
            "last_checked_at": "2026-08-10T00:00:00+00:00",
        }
    }
    tables = {"contest-table": contest_table, "state-table": state_table}
    captured: dict[str, Any] = {}

    monkeypatch.setattr(worker_handler, "HttpClient", FakeHttpClient)
    monkeypatch.setattr(worker_handler, "ContestKoreaCrawler", FakeCrawler)
    monkeypatch.setattr(
        worker_handler,
        "boto3",
        SimpleNamespace(resource=lambda *_args, **_kwargs: SimpleNamespace(Table=lambda name: tables[name])),
    )
    monkeypatch.setattr(
        worker_handler.WorkerSettings,
        "from_env",
        classmethod(lambda _cls: SimpleNamespace(contest_table_name="contest-table", state_table_name="state-table", aws_region="ap-northeast-2")),
    )
    monkeypatch.setattr(worker_handler, "DiscordClient", lambda: SimpleNamespace(send_deferred_response=lambda *_args: None))
    monkeypatch.setattr(worker_handler, "log_event", lambda event, **fields: captured.update(event=event, **fields))

    worker_handler.handler(
        {"request_id": "worker-request", "discord_user_id": "user-1", "application_id": "app", "interaction_token": "token"},
        SimpleNamespace(aws_request_id="context-request"),
    )

    assert captured["event"] == "contest_worker_completed"
    assert captured["list_page_count"] == 2
    assert captured["list_parallelism"] == 5
    assert captured["prefetched_list_page_count"] == 0
    assert captured["list_request_duration_ms_total"] == 7
    assert captured["list_candidate_count"] == 3
    assert captured["known_contest_count"] == 2
    assert captured["new_candidate_count"] == 1
    assert captured["skipped_detail_count"] == 2
    assert captured["list_candidate_count"] == captured["known_contest_count"] + captured["new_candidate_count"]
    assert captured["detail_request_count"] == 1
    assert captured["http_request_count"] == 3
    assert captured["contest_count"] == 3
    assert captured["new_contest_count"] == 1
    assert isinstance(captured["dynamodb_lookup_duration_ms"], int)
    assert isinstance(captured["dynamodb_write_duration_ms"], int)
    assert captured["dynamodb_batch_get_request_count"] == 1
    assert captured["dynamodb_unprocessed_key_retry_count"] == 0
    assert captured["dynamodb_write_count"] == 2
