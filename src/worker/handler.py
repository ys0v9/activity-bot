"""Asynchronous Worker Lambda for crawl, persistence, and Discord output."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Iterable

import boto3

from src.common.config import WorkerSettings
from src.common.http_client import HttpClient
from src.common.logging import log_event, utc_now_iso
from src.crawler.contestkorea import ContestKoreaCrawler
from src.discord.client import DISCORD_MESSAGE_LIMIT, DiscordClient
from src.domain.contest import Contest
from src.repository.contest_repository import ContestRepository
from src.repository.discovery import ContestDiscovery, DiscoveryResult
from src.repository.state_repository import StateRepository


VERSION = "v1-contestkorea"


def handler(event: dict[str, Any], context: Any) -> None:
    """Lambda entry point. Interaction tokens are deliberately never logged."""
    request_id = event.get("request_id") or getattr(context, "aws_request_id", "unknown")
    started_at = utc_now_iso()
    started = time.perf_counter()
    http_client = HttpClient()
    crawler = ContestKoreaCrawler(http_client)
    contest_repository: ContestRepository | None = None
    state_repository: StateRepository | None = None
    success = False
    result: DiscoveryResult | None = None
    error_type: str | None = None
    list_candidate_count = 0
    known_contest_count = 0
    new_candidate_count = 0
    skipped_detail_count = 0
    dynamodb_lookup_duration_ms = 0
    dynamodb_write_duration_ms = 0

    try:
        settings = WorkerSettings.from_env()
        dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
        contest_repository = ContestRepository(dynamodb.Table(settings.contest_table_name))
        state_repository = StateRepository(dynamodb.Table(settings.state_table_name))

        list_items = crawler.fetch_list_items()
        list_candidate_count = len(list_items)
        discovery = ContestDiscovery(contest_repository, state_repository)

        lookup_started = time.perf_counter()
        classification = discovery.classify_candidates(
            event["discord_user_id"],
            (item.contest_id for item in list_items),
        )
        dynamodb_lookup_duration_ms = int((time.perf_counter() - lookup_started) * 1000)
        known_contest_count = len(classification.known_contest_ids)
        new_candidate_count = len(classification.new_contest_ids)
        skipped_detail_count = known_contest_count

        items_by_id = {item.contest_id: item for item in list_items}
        crawled = [crawler.fetch_detail(items_by_id[contest_id]) for contest_id in classification.new_contest_ids]
        checked_at = datetime.now(timezone.utc).isoformat()
        write_started = time.perf_counter()
        result = discovery.process_classified(
            event["discord_user_id"],
            classification,
            crawled,
            checked_at,
            total_contest_count=list_candidate_count,
        )
        dynamodb_write_duration_ms = int((time.perf_counter() - write_started) * 1000)
        messages = format_discord_messages(result)
        DiscordClient().send_deferred_response(event["application_id"], event["interaction_token"], messages)
        success = True
    except Exception as exc:  # Lambda must log and try to inform the interaction user.
        error_type = type(exc).__name__
        try:
            if event.get("application_id") and event.get("interaction_token"):
                DiscordClient().send_deferred_response(
                    event["application_id"], event["interaction_token"], ["⚠️ 공모전 조회 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."],
                )
        except Exception:
            pass
        raise
    finally:
        finished_at = utc_now_iso()
        log_event(
            "contest_worker_completed",
            request_id=request_id,
            version=VERSION,
            source="contestkorea",
            started_at=started_at,
            finished_at=finished_at,
            total_duration_ms=int((time.perf_counter() - started) * 1000),
            crawl_duration_ms=crawler.metrics.list_fetch_duration_ms + crawler.metrics.detail_fetch_duration_ms,
            list_fetch_duration_ms=crawler.metrics.list_fetch_duration_ms,
            detail_fetch_duration_ms=crawler.metrics.detail_fetch_duration_ms,
            dynamodb_lookup_duration_ms=dynamodb_lookup_duration_ms,
            dynamodb_write_duration_ms=dynamodb_write_duration_ms,
            http_request_count=http_client.metrics.request_count,
            list_request_count=http_client.metrics.list_request_count,
            detail_request_count=http_client.metrics.detail_request_count,
            list_page_count=crawler.metrics.list_page_count,
            list_candidate_count=list_candidate_count,
            known_contest_count=known_contest_count,
            new_candidate_count=new_candidate_count,
            skipped_detail_count=skipped_detail_count,
            contest_count=result.total_contest_count if result else list_candidate_count,
            new_contest_count=len(result.new_contests) if result else 0,
            dynamodb_read_count=(contest_repository.read_count if contest_repository else 0)
            + (state_repository.read_count if state_repository else 0),
            dynamodb_write_count=(contest_repository.write_count if contest_repository else 0)
            + (state_repository.write_count if state_repository else 0),
            crawler_error_count=crawler.metrics.crawler_error_count,
            success=success,
            error_type=error_type,
        )
        http_client.close()


def format_discord_messages(result: DiscoveryResult) -> list[str]:
    if result.initialized:
        return [
            "✅ 기준 데이터 저장 완료\n"
            f"현재 확인 가능한 공모전 {result.total_contest_count}개를 저장했습니다.\n"
            "다음 /최신 요청부터 새로 등록된 공모전만 알려드릴게요."
        ]
    if not result.new_contests:
        return ["✅ 마지막 확인 이후 새로 등록된 공모전이 없습니다."]

    header = f"🏆 마지막 확인 이후 새로운 공모전 {len(result.new_contests)}개"
    entries = [_format_contest(index, contest) for index, contest in enumerate(result.new_contests, start=1)]
    return _chunk_messages(header, entries)


def _format_contest(index: int, contest: Contest) -> str:
    period = " ~ ".join(value for value in (contest.application_start, contest.application_end) if value) or "확인 필요"
    return "\n".join(
        [
            f"{index}. {contest.title}",
            f"분야: {contest.category or '확인 필요'}",
            f"주최: {contest.organizer or '확인 필요'}",
            f"대상: {contest.target or '확인 필요'}",
            f"접수: {period}",
            f"링크: {contest.detail_url}",
        ]
    )


def _chunk_messages(header: str, entries: Iterable[str]) -> list[str]:
    chunks: list[str] = []
    current = header
    for entry in entries:
        candidate = f"{current}\n\n{entry}"
        while len(candidate) > DISCORD_MESSAGE_LIMIT:
            chunks.append(candidate[:DISCORD_MESSAGE_LIMIT])
            candidate = candidate[DISCORD_MESSAGE_LIMIT:]
        current = candidate
    chunks.append(current)
    return chunks
