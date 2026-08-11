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


@dataclass(frozen=True, slots=True)
class CandidateClassification:
    """Existing and unseen contest IDs found in one current list scan."""

    is_first_check: bool
    known_contest_ids: tuple[str, ...]
    new_contest_ids: tuple[str, ...]


class ContestDiscovery:
    """Apply the per-user baseline and return only never-seen contests."""

    def __init__(self, contest_repository: ContestRepository, state_repository: StateRepository) -> None:
        self.contests = contest_repository
        self.states = state_repository

    def process(self, discord_user_id: str, fetched_contests: Iterable[Contest], checked_at: str) -> DiscoveryResult:
        """Keep the existing full-contest API for callers and repository tests."""
        deduplicated = self._deduplicate(fetched_contests)
        classification = self.classify_candidates(discord_user_id, (contest.contest_id for contest in deduplicated))
        contests_by_id = {contest.contest_id: contest for contest in deduplicated}
        new_contests = [contests_by_id[contest_id] for contest_id in classification.new_contest_ids]
        return self.process_classified(
            discord_user_id,
            classification,
            new_contests,
            checked_at,
            total_contest_count=len(deduplicated),
        )

    def classify_candidates(
        self,
        discord_user_id: str,
        contest_ids: Iterable[str],
    ) -> CandidateClassification:
        """Check list-level IDs before deciding whether their details are needed."""
        state = self.states.get(discord_user_id)
        deduplicated_ids = tuple(dict.fromkeys(contest_ids))
        known_contest_ids: list[str] = []
        new_contest_ids: list[str] = []

        for contest_id in deduplicated_ids:
            if self.contests.get(contest_id) is None:
                new_contest_ids.append(contest_id)
            else:
                known_contest_ids.append(contest_id)

        return CandidateClassification(
            is_first_check=state is None or not state.initialized,
            known_contest_ids=tuple(known_contest_ids),
            new_contest_ids=tuple(new_contest_ids),
        )

    def process_classified(
        self,
        discord_user_id: str,
        classification: CandidateClassification,
        new_contests: Iterable[Contest],
        checked_at: str,
        *,
        total_contest_count: int,
    ) -> DiscoveryResult:
        """Persist a list classification after fetching details only for new IDs."""
        deduplicated_new = self._deduplicate(new_contests)
        new_ids = tuple(contest.contest_id for contest in deduplicated_new)
        if set(new_ids) != set(classification.new_contest_ids):
            raise ValueError("Detailed contests must exactly match unseen list candidates")

        for contest_id in classification.known_contest_ids:
            self.contests.update_last_seen(contest_id, checked_at)

        observed_new: list[Contest] = []
        for contest in deduplicated_new:
            observed = replace(contest, first_seen_at=checked_at, last_seen_at=checked_at)
            self.contests.save(observed)
            observed_new.append(observed)

        if classification.is_first_check:
            self.states.initialize(discord_user_id, checked_at)
        else:
            self.states.update_last_checked_at(discord_user_id, checked_at)

        return DiscoveryResult(
            initialized=classification.is_first_check,
            total_contest_count=total_contest_count,
            new_contests=[] if classification.is_first_check else observed_new,
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
