"""API Gateway handler for Discord HTTP Interactions."""

from __future__ import annotations

import base64
import json
from typing import Any, Protocol

from src.common.config import ConfigurationError, InteractionSettings
from src.common.logging import log_event
from src.discord.verifier import verify_discord_signature


PING = 1
APPLICATION_COMMAND = 2
PONG_RESPONSE = 1
CHANNEL_MESSAGE_RESPONSE = 4
DEFERRED_CHANNEL_MESSAGE_RESPONSE = 5
EPHEMERAL_FLAG = 1 << 6
LATEST_COMMAND_NAME = "최신"


class LambdaInvoker(Protocol):
    def invoke(self, **kwargs: Any) -> dict[str, Any]: ...


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point."""
    import boto3

    return handle(event, context, lambda_client=boto3.client("lambda"))


def handle(event: dict[str, Any], context: Any, *, lambda_client: LambdaInvoker) -> dict[str, Any]:
    request_id = getattr(context, "aws_request_id", "unknown")
    try:
        settings = InteractionSettings.from_env()
        body = _raw_body(event)
        headers = {str(key).lower(): value for key, value in event.get("headers", {}).items()}
        if not verify_discord_signature(
            settings.discord_public_key,
            headers.get("x-signature-ed25519"),
            headers.get("x-signature-timestamp"),
            body,
        ):
            log_event("discord_interaction_rejected", request_id=request_id, reason="invalid_signature")
            return _response(401, {"error": "invalid request signature"})

        payload = json.loads(body)
        if payload.get("type") == PING:
            return _response(200, {"type": PONG_RESPONSE})
        if payload.get("type") != APPLICATION_COMMAND or payload.get("data", {}).get("name") != LATEST_COMMAND_NAME:
            return _ephemeral_message("지원하지 않는 명령어입니다.")

        discord_user_id = _discord_user_id(payload)
        if discord_user_id != settings.allowed_discord_user_id:
            log_event("discord_interaction_rejected", request_id=request_id, reason="user_not_allowed")
            return _ephemeral_message("이 명령어를 사용할 권한이 없습니다.")

        worker_event = {
            "discord_user_id": discord_user_id,
            "application_id": payload["application_id"],
            "interaction_token": payload["token"],
            "request_id": request_id,
        }
        lambda_client.invoke(
            FunctionName=settings.worker_function_name,
            InvocationType="Event",
            Payload=json.dumps(worker_event).encode("utf-8"),
        )
        log_event("discord_interaction_deferred", request_id=request_id, discord_user_id=discord_user_id)
        return _response(200, {"type": DEFERRED_CHANNEL_MESSAGE_RESPONSE, "data": {"flags": EPHEMERAL_FLAG}})
    except (ConfigurationError, KeyError, ValueError, json.JSONDecodeError) as exc:
        log_event("discord_interaction_error", request_id=request_id, error_type=type(exc).__name__)
        return _response(500, {"error": "interaction processing failed"})


def _raw_body(event: dict[str, Any]) -> str:
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        return base64.b64decode(body).decode("utf-8")
    return body


def _discord_user_id(payload: dict[str, Any]) -> str | None:
    member_user = payload.get("member", {}).get("user", {}).get("id")
    return member_user or payload.get("user", {}).get("id")


def _response(status_code: int, payload: dict[str, Any]) -> dict[str, Any]:
    return {"statusCode": status_code, "headers": {"content-type": "application/json"}, "body": json.dumps(payload)}


def _ephemeral_message(content: str) -> dict[str, Any]:
    return _response(
        200,
        {"type": CHANNEL_MESSAGE_RESPONSE, "data": {"content": content, "flags": EPHEMERAL_FLAG}},
    )
