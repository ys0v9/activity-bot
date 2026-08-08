"""Application service for baseline initialization and new contest detection."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

from src.domain.contest import Contest
from src.repository.contest_repository import ContestRepository
from src.repository.state_repository import StateRepository


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    initialized: bool
    total_contest_count: int
    new_contests: list[Contest]


class ContestDiscovery:
    """Apply the per-user baseline and return only never-seen contests."""

    def __init__(self, contest_repository: ContestRepository, state_repository: StateRepository) -> None:
        self.contests = contest_repository
        self.states = state_repository

    def process(self, discord_user_id: str, fetched_contests: Iterable[Contest], checked_at: str) -> DiscoveryResult:
        deduplicated = self._deduplicate(fetched_contests)
        state = self.states.get(discord_user_id)
        is_first_check = state is None or not state.initialized

        new_contests: list[Contest] = []
        for contest in deduplicated:
            stored = self.contests.get(contest.contest_id)
            observed = replace(contest, first_seen_at=checked_at, last_seen_at=checked_at)
            if stored is None:
                self.contests.save(observed)
                if not is_first_check:
                    new_contests.append(observed)
            else:
                self.contests.update_last_seen(contest.contest_id, checked_at)

        if is_first_check:
            self.states.initialize(discord_user_id, checked_at)
        else:
            self.states.update_last_checked_at(discord_user_id, checked_at)

        return DiscoveryResult(
            initialized=is_first_check,
            total_contest_count=len(deduplicated),
            new_contests=new_contests,
        )

    @staticmethod
    def _deduplicate(contests: Iterable[Contest]) -> list[Contest]:
        seen: set[str] = set()
        result: list[Contest] = []
        for contest in contests:
            if contest.contest_id not in seen:
                seen.add(contest.contest_id)
                result.append(contest)
        return result
