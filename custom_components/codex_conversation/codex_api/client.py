"""
CodexClient — high-level async client for the Codex Responses API.

Depends only on ``AbstractAuth`` for authenticated HTTP; never touches raw
tokens or session management directly.

Mirrors ``ResponsesClient`` from codex-api/src/endpoint/responses.rs.
"""

from __future__ import annotations

from typing import AsyncIterator

from ..security import redact_sensitive_text
from .auth import AbstractAuth
from .errors import CodexApiError, CodexRateLimited, CodexServerOverloaded
from .models import ResponseEvent
from .requests import CodexRequest
from .sse import sse_iter

CODEX_ENDPOINT = "https://chatgpt.com/backend-api/codex/responses"

_STREAM_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "text/event-stream",
}


async def _redacted_response_text(resp) -> str:
    """Return a safe API error message without exposing the response body."""
    await resp.text()
    reason = redact_sensitive_text(resp.reason or "request failed")
    return f"Codex API returned HTTP {resp.status}: {reason}"


class CodexClient:
    """
    Async client for the OpenAI Codex ``/responses`` endpoint.

    Requires an ``AbstractAuth`` instance — token refresh and session
    management are delegated entirely to the auth layer.

    Example (standalone, using ``CodexAuth``)::

        async with aiohttp.ClientSession() as session:
            auth = CodexAuth(session, CODEX_ENDPOINT, access_token, account_id)
            client = CodexClient(auth)
            async for event in client.stream(request):
                if isinstance(event, OutputTextDelta):
                    print(event.delta, end="", flush=True)

    Example (Home Assistant, using ``CodexHAAuth`` from oauth.py)::

        auth = CodexHAAuth(ha_session, oauth_session)
        client = CodexClient(auth)
        async for event in client.stream(request):
            ...
    """

    def __init__(self, auth: AbstractAuth) -> None:
        self._auth = auth

    async def stream(self, request: CodexRequest) -> AsyncIterator[ResponseEvent]:
        """Submit *request* and stream back typed ``ResponseEvent`` objects.

        Raises a ``CodexError`` subclass on HTTP-level or fatal API errors.
        """
        resp = await self._auth.request(
            "post",
            headers=_STREAM_HEADERS,
            json=request.to_body(),
        )
        try:
            if resp.status == 401:
                raise CodexApiError(
                    401, "Unauthorized — bearer token expired or invalid"
                )
            if resp.status == 429:
                retry_after: float | None = None
                ra = resp.headers.get("Retry-After")
                if ra and ra.isdigit():
                    retry_after = float(ra)
                raise CodexRateLimited(
                    await _redacted_response_text(resp), retry_after=retry_after
                )
            if resp.status == 503:
                raise CodexServerOverloaded(await _redacted_response_text(resp))
            if resp.status >= 400:
                raise CodexApiError(resp.status, await _redacted_response_text(resp))

            async for event in sse_iter(resp):
                yield event
        finally:
            resp.release()
