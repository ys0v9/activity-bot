from __future__ import annotations

import json
from dataclasses import dataclass

from nacl.signing import SigningKey

from src.discord.verifier import verify_discord_signature
from src.interaction.handler import handle


class FakeLambda:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def invoke(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        return {"StatusCode": 202}


@dataclass
class Context:
    aws_request_id: str = "request-1"


def signed_event(signing_key: SigningKey, payload: dict[str, object]) -> dict[str, object]:
    body = json.dumps(payload, ensure_ascii=False)
    timestamp = "1723161600"
    signature = signing_key.sign(f"{timestamp}{body}".encode()).signature.hex()
    return {
        "headers": {"X-Signature-Ed25519": signature, "X-Signature-Timestamp": timestamp},
        "body": body,
    }


def configure(monkeypatch: object, public_key: str) -> None:
    monkeypatch.setenv("DISCORD_PUBLIC_KEY", public_key)
    monkeypatch.setenv("ALLOWED_DISCORD_USER_ID", "allowed-user")
    monkeypatch.setenv("WORKER_FUNCTION_NAME", "worker-function")


def test_discord_signature_validation() -> None:
    signing_key = SigningKey.generate()
    body = '{"type":1}'
    timestamp = "1723161600"
    signature = signing_key.sign(f"{timestamp}{body}".encode()).signature.hex()

    assert verify_discord_signature(signing_key.verify_key.encode().hex(), signature, timestamp, body) is True
    assert verify_discord_signature(signing_key.verify_key.encode().hex(), signature, timestamp, "{}") is False


def test_allowed_user_invokes_worker(monkeypatch: object) -> None:
    signing_key = SigningKey.generate()
    configure(monkeypatch, signing_key.verify_key.encode().hex())
    event = signed_event(
        signing_key,
        {
            "type": 2,
            "application_id": "application-id",
            "token": "secret-interaction-token",
            "data": {"name": "최신"},
            "member": {"user": {"id": "allowed-user"}},
        },
    )
    fake_lambda = FakeLambda()

    response = handle(event, Context(), lambda_client=fake_lambda)

    assert response["statusCode"] == 200
    assert json.loads(response["body"])["type"] == 5
    assert len(fake_lambda.calls) == 1


def test_unallowed_user_is_blocked_without_worker_invocation(monkeypatch: object) -> None:
    signing_key = SigningKey.generate()
    configure(monkeypatch, signing_key.verify_key.encode().hex())
    event = signed_event(
        signing_key,
        {
            "type": 2,
            "application_id": "application-id",
            "token": "secret-interaction-token",
            "data": {"name": "최신"},
            "member": {"user": {"id": "other-user"}},
        },
    )
    fake_lambda = FakeLambda()

    response = handle(event, Context(), lambda_client=fake_lambda)

    assert response["statusCode"] == 200
    assert "권한" in json.loads(response["body"])["data"]["content"]
    assert fake_lambda.calls == []


def test_invalid_signature_is_rejected(monkeypatch: object) -> None:
    signing_key = SigningKey.generate()
    configure(monkeypatch, signing_key.verify_key.encode().hex())
    event = signed_event(signing_key, {"type": 1})
    event["headers"]["X-Signature-Ed25519"] = "00" * 64

    response = handle(event, Context(), lambda_client=FakeLambda())

    assert response["statusCode"] == 401
