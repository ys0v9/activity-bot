"""Small structured logging helper for CloudWatch Logs Insights."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any


LOGGER = logging.getLogger("contest_radar")
LOGGER.setLevel(logging.INFO)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_event(event: str, **fields: Any) -> None:
    """Emit one JSON object. Callers must never pass secrets or interaction tokens."""
    payload = {"event": event, **fields}
    LOGGER.info(json.dumps(payload, ensure_ascii=False, default=str))
