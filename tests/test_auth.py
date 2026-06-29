"""Tests for Codex API authentication helpers."""

from __future__ import annotations

from custom_components.codex_conversation.codex_api.auth import CodexAuth


class _CaptureSession:
    """Minimal aiohttp-like session that captures request headers."""

    def __init__(self) -> None:
        self.headers: dict[str, str] = {}

    async def request(self, method, endpoint, headers, **kwargs):
        self.headers = headers
        return object()


async def test_auth_headers_cannot_be_overridden() -> None:
    """Caller-supplied headers must not replace auth or fixed Codex headers."""
    session = _CaptureSession()
    auth = CodexAuth(
        session=session,
        endpoint="https://example.invalid/codex",
        access_token="test_access_token",
        account_id="test_account",
    )

    await auth.request(
        "post",
        headers={
            "Authorization": "Bearer attacker",
            "openai-beta": "bad",
            "openai-originator": "bad",
        },
    )

    assert session.headers["Authorization"] == "Bearer test_access_token"
    assert session.headers["openai-beta"] == "responses=experimental"
    assert session.headers["openai-originator"] == "codex_cli_rs"
