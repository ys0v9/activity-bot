"""Typed environment configuration without logging secret values."""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigurationError(RuntimeError):
    """Raised when a required runtime environment variable is absent."""


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigurationError(f"Required environment variable is not configured: {name}")
    return value


@dataclass(frozen=True, slots=True)
class InteractionSettings:
    discord_public_key: str
    allowed_discord_user_id: str
    worker_function_name: str

    @classmethod
    def from_env(cls) -> "InteractionSettings":
        return cls(
            discord_public_key=required_env("DISCORD_PUBLIC_KEY"),
            allowed_discord_user_id=required_env("ALLOWED_DISCORD_USER_ID"),
            worker_function_name=required_env("WORKER_FUNCTION_NAME"),
        )


@dataclass(frozen=True, slots=True)
class WorkerSettings:
    contest_table_name: str
    state_table_name: str
    aws_region: str

    @classmethod
    def from_env(cls) -> "WorkerSettings":
        return cls(
            contest_table_name=required_env("CONTEST_TABLE_NAME"),
            state_table_name=required_env("STATE_TABLE_NAME"),
            aws_region=os.environ.get("AWS_REGION", "ap-northeast-2"),
        )
