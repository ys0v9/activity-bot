"""Discord webhook client for completing deferred interaction responses."""

from __future__ import annotations

from typing import Iterable
from urllib.parse import quote

import httpx


DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_MESSAGE_LIMIT = 2_000


class DiscordClient:
    """Use an interaction token only in HTTP paths, never in logs."""

    def __init__(self, timeout_seconds: float = 10.0) -> None:
        self._client = httpx.Client(timeout=httpx.Timeout(timeout_seconds))

    def send_deferred_response(self, application_id: str, interaction_token: str, messages: Iterable[str]) -> None:
        chunks = list(messages)
        if not chunks:
            chunks = ["✅ 마지막 확인 이후 새로 등록된 공모전이 없습니다."]
        application = quote(application_id, safe="")
        token = quote(interaction_token, safe="")
        self._request(
            "PATCH",
            f"{DISCORD_API_BASE}/webhooks/{application}/{token}/messages/@original",
            {"content": chunks[0]},
        )
        for chunk in chunks[1:]:
            self._request(
                "POST",
                f"{DISCORD_API_BASE}/webhooks/{application}/{token}",
                {"content": chunk, "flags": 64},
            )

    def _request(self, method: str, url: str, payload: dict[str, object]) -> None:
        response = self._client.request(method, url, json=payload)
        response.raise_for_status()

    def close(self) -> None:
        self._client.close()
