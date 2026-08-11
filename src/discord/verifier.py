"""Discord Interaction Ed25519 request verification."""

from __future__ import annotations

from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey


def verify_discord_signature(public_key_hex: str, signature_hex: str | None, timestamp: str | None, body: str) -> bool:
    """Return true only for Discord's documented timestamp + body signature."""
    if not signature_hex or not timestamp:
        return False
    try:
        verify_key = VerifyKey(bytes.fromhex(public_key_hex))
        verify_key.verify(f"{timestamp}{body}".encode("utf-8"), bytes.fromhex(signature_hex))
    except (BadSignatureError, TypeError, ValueError):
        return False
    return True
