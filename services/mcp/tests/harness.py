"""Shared test harness: the adapter's clients wired to the in-process stubs with a fixed clock."""

from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from frontdesk_mcp import context
from frontdesk_mcp.cache import DirectoryCache
from frontdesk_mcp.clock import FixedClock
from frontdesk_mcp.knowledge_client import KnowledgeClient
from frontdesk_mcp.ops_client import OpsClient
from frontdesk_stubs import knowledge as knowledge_stub
from frontdesk_stubs import ops as ops_stub

# Thursday 1 October 2026, 10:00 IST (04:30 UTC)
NOW = datetime(2026, 10, 1, 4, 30, tzinfo=UTC)
CALLER = "+919000000101"


def turn_header(utterance: str, language: str = "en", turn_id: str | None = None) -> str:
    payload = {"utterance": utterance, "language": language}
    if turn_id:
        payload["turnId"] = turn_id
    return base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode().rstrip("=")


def headers(*, call_id: str | None = "call-1", caller: str | None = CALLER, turn: str | None = "is Dr Garima in today",
            language: str = "en", operation_id: str | None = None, verification: str | None = None,
            started_at: str | None = None, duration: str | None = None) -> dict[str, str]:
    out: dict[str, str] = {}
    if call_id:
        out["X-Call-Id"] = call_id
    if caller:
        out["X-Caller-Number"] = caller
    if verification:
        out["X-Caller-Verification"] = verification
    if turn is not None:
        out["X-Turn-Context"] = turn_header(turn, language)
    if operation_id:
        out["X-Operation-Id"] = operation_id
    if started_at:
        out["X-Call-Started-At"] = started_at
    if duration:
        out["X-Call-Duration-Seconds"] = duration
    return out


@dataclass
class Harness:
    settings: object
    clock: FixedClock
    ops_state: ops_stub.OpsStubState
    knowledge_state: knowledge_stub.KnowledgeStubState
    ops: OpsClient
    knowledge: KnowledgeClient
    requests: list[httpx.Request]
    cache: DirectoryCache

    def ctx(self, **kwargs) -> context.CallContext:
        return context.from_headers(headers(**kwargs), self.settings)

    def ops_paths(self) -> list[str]:
        prefix = httpx.URL(self.settings.ops_base_url).path.rstrip("/")
        return [r.url.path.removeprefix(prefix) for r in self.requests
                if r.url.host == "ops-stub.test" and not r.url.path.endswith("/auth/token")]

    async def aclose(self) -> None:
        await self.ops.aclose()
        await self.knowledge.aclose()


def build(settings, now: datetime = NOW, ops_secret: str = "ops-secret") -> Harness:
    """The stub's registered credential is fixed (like a real registration), not copied from settings."""
    clock = FixedClock(now)
    scopes = {"appointments.write", "calls.write"}
    ops_state = ops_stub.OpsStubState(clock=clock, zone=settings.tenant_timezone,
                                      clients={settings.ops_client_id: (ops_secret, scopes)})
    knowledge_state = knowledge_stub.KnowledgeStubState(bearer=settings.knowledge_bearer_token.get_secret_value())
    requests: list[httpx.Request] = []

    class Recording(httpx.AsyncBaseTransport):
        def __init__(self, app):
            self.inner = httpx.ASGITransport(app=app)

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            """In-process ASGI ignores timeouts; enforce the request's read timeout so deadlines are real."""
            requests.append(request)
            timeout = (request.extensions.get("timeout") or {}).get("read")
            try:
                return await asyncio.wait_for(self.inner.handle_async_request(request), timeout)
            except TimeoutError as exc:
                raise httpx.ReadTimeout("stub too slow", request=request) from exc

    prefix = httpx.URL(settings.ops_base_url).path.rstrip("/")
    ops = OpsClient(settings, transport=Recording(ops_stub.create_app(ops_state, prefix=prefix)))
    knowledge = KnowledgeClient(settings, transport=Recording(knowledge_stub.create_app(knowledge_state)))
    return Harness(settings, clock, ops_state, knowledge_state, ops, knowledge, requests, DirectoryCache(settings))
