from src.domain.contest import Contest
from src.repository.discovery import DiscoveryResult
from src.worker.handler import format_discord_messages


def _contest(index: int) -> Contest:
    return Contest(
        contest_id=f"contestkorea:{index}",
        source="contestkorea",
        title=f"테스트 공모전 {index}",
        category="학문·과학·IT",
        organizer="테스트 기관",
        target="대학생",
        application_start="2026-08-10",
        application_end="2026-09-01",
        status="접수중",
        detail_url=f"https://example.test/{index}",
    )


def test_initialization_message() -> None:
    messages = format_discord_messages(DiscoveryResult(True, 3, []))

    assert "기준 데이터 저장 완료" in messages[0]


def test_empty_new_contests_message() -> None:
    messages = format_discord_messages(DiscoveryResult(False, 3, []))

    assert messages == ["✅ 마지막 확인 이후 새로 등록된 공모전이 없습니다."]


def test_new_contests_are_split_within_discord_limit() -> None:
    messages = format_discord_messages(DiscoveryResult(False, 80, [_contest(index) for index in range(1, 90)]))

    assert len(messages) > 1
    assert all(len(message) <= 2000 for message in messages)


def test_single_long_contest_entry_is_split_within_discord_limit() -> None:
    long_contest = _contest(1)
    long_contest = Contest(**{**long_contest.to_item(), "target": "가" * 4_000})

    messages = format_discord_messages(DiscoveryResult(False, 1, [long_contest]))

    assert len(messages) > 1
    assert all(len(message) <= 2000 for message in messages)
