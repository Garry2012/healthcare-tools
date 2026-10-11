"""Shared test harness: the adapter's clients wired to the in-process stubs with a fixed clock."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from frontdesk_mcp import context
from frontdesk_mcp.cache import DirectoryCache
from frontdesk_mcp.clock import FixedClock
from frontdesk_mcp.ops_client import OpsClient
from frontdesk_stubs import ops as ops_stub

# Thursday 1 October 2026, 10:00 IST (04:30 UTC)
NOW = datetime(2026, 10, 1, 4, 30, tzinfo=UTC)
CALLER = "+919000000101"


def headers(*, call_id: str | None = "call-1", caller: str | None = CALLER,
            operation_id: str | None = None, verification: str | None = "SIP_CALLER_ID",
            started_at: str | None = None) -> dict[str, str]:
    out: dict[str, str] = {}
    if call_id:
        out["X-Call-Id"] = call_id
    if caller:
        out["X-Caller-Number"] = caller
    if verification:
        out["X-Caller-Verification"] = verification
    if operation_id:
        out["X-Operation-Id"] = operation_id
    if started_at:
        out["X-Call-Started-At"] = started_at
    return out


@dataclass
class Harness:
    settings: object
    clock: FixedClock
    ops_state: ops_stub.OpsStubState
    ops: OpsClient
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


def build(settings, now: datetime = NOW, ops_secret: str = "ops-secret") -> Harness:
    """The stub's registered credential is fixed (like a real registration), not copied from settings."""
    clock = FixedClock(now)
    scopes = {"appointments.write", "calls.write"}
    ops_state = ops_stub.OpsStubState(clock=clock, zone=settings.tenant_timezone,
                                      clients={settings.ops_client_id: (ops_secret, scopes)})
    requests: list[httpx.Request] = []

    class Recording(httpx.AsyncBaseTransport):
        def __init__(self, app):
            self.inner = httpx.ASGITransport(app=app)

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            """In-process ASGI ignores httpx timeouts; the clients' own asyncio.timeout caps the exchange."""
            requests.append(request)
            return await self.inner.handle_async_request(request)

    prefix = httpx.URL(settings.ops_base_url).path.rstrip("/")
    ops = OpsClient(settings, transport=Recording(ops_stub.create_app(ops_state, prefix=prefix)))
    return Harness(settings, clock, ops_state, ops, requests, DirectoryCache(settings))


def slot_plan(doctor_id="doc_garima", date="2026-10-01") -> dict:
    """Synthetic contract-shaped fixture, not a live capture; distinct adjacent sessions."""
    return {"doctorId": doctor_id, "date": date, "enabled": True, "blockMinutes": 30, "sessions": [
        {"session": "Morning", "status": "IN", "bookable": True, "slots": [
            {"start": "10:30", "end": "11:00", "capacity": 3, "booked": 0, "available": 3, "bookable": True}]},
        {"session": "Later", "status": "IN", "bookable": True, "slots": [
            {"start": "11:00", "end": "11:30", "capacity": 3, "booked": 0, "available": 3, "bookable": True}]}]}


SLOT_INCONSISTENCIES = ("doctor", "date", "duplicate", "blank", "overlap")


def inconsistent_slot_plan(issue, date="2026-10-01") -> dict:
    plan = slot_plan(date=date)
    if issue == "doctor":
        plan["doctorId"] = "doc_other"
    elif issue == "date":
        plan["date"] = "2026-10-09"
    elif issue == "duplicate":
        plan["sessions"][1]["session"] = "  MORNING  "
    elif issue == "blank":
        plan["sessions"][0]["session"], plan["sessions"][1]["session"] = "", None
    elif issue == "overlap":
        plan["sessions"][1]["slots"][0]["start"] = "10:45"
    else:
        raise AssertionError(issue)
    return plan


SLOT_FAILURES = ("timeout", "upstream", "400", "404", "malformed", "unsupported", "401", "403")


def slot_failure(request: httpx.Request, failure: str) -> httpx.Response:
    """Transport fault fixture shared by availability and booking tests."""
    if failure == "timeout":
        raise httpx.ReadTimeout("scripted timeout", request=request)
    if failure == "malformed":
        return httpx.Response(200, json={"unexpected": True})
    status, code = {"upstream": (503, "INTERNAL"), "400": (400, "VALIDATION_FAILED"),
                    "404": (404, "NOT_FOUND"), "unsupported": (400, "UNSUPPORTED_CAPABILITY"),
                    "401": (401, "UNAUTHORIZED"), "403": (403, "FORBIDDEN")}[failure]
    return httpx.Response(status, json={"error": {"code": code, "message": "owner-only text"}},
                          headers={"Retry-After": "4"} if failure == "upstream" else {})
