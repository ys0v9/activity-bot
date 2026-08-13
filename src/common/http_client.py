"""Small synchronous HTTP client with exact request metrics."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

import httpx


DEFAULT_USER_AGENT = "ContestRadar/1.0 (+https://github.com/ys0v9/activity-bot)"


@dataclass(slots=True)
class HttpMetrics:
    request_count: int = 0
    list_request_count: int = 0
    detail_request_count: int = 0


class HttpClient:
    """Wrap httpx to centralize safe defaults and request accounting."""

    def __init__(self, timeout_seconds: float = 15.0, user_agent: str = DEFAULT_USER_AGENT) -> None:
        self.metrics = HttpMetrics()
        self._metrics_lock = Lock()
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=True,
            headers={"User-Agent": user_agent, "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7"},
        )

    def get(self, url: str, *, request_type: str) -> httpx.Response:
        """Perform one GET request and record it before validation."""
        if request_type not in {"list", "detail"}:
            raise ValueError(f"Unsupported request_type: {request_type}")
        with self._metrics_lock:
            self.metrics.request_count += 1
            if request_type == "list":
                self.metrics.list_request_count += 1
            else:
                self.metrics.detail_request_count += 1

        response = self._client.get(url)
        response.raise_for_status()
        return response

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "HttpClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
