"""MCP → REST → PostgreSQL, with nothing faked in between (docs/review/).

Each test drives the adapter the way the gateway does (streamable HTTP, identity in HTTP headers)
and compares what the model receives with what the REST service says, and with what is stored.

Processes: `frontdesk-api serve` (real, against the throwaway database in TEST_DATABASE_URL, freshly
seeded with the demo rollout) and `frontdesk-mcp serve` (real). Only the transport-failure tests
point an adapter at a local fake upstream (a closed port, a server that never answers, a server
that answers 5xx/429): that is the one external boundary those tests are about.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from ..conftest import free_port

ROOT = Path(__file__).resolve().parents[4]
API_DIR = ROOT / "services/api"
API_PYTHON = API_DIR / ".venv/bin/python"
ROLLOUT = ROOT / "rollouts/demo-hospital"
APP_URL = os.environ.get("TEST_DATABASE_URL")
AGENT_TOKEN = f"review-agent-{uuid.uuid4().hex[:8]}"
STAFF_TOKEN = f"review-staff-{uuid.uuid4().hex[:8]}"
MCP_TOKEN = "review-mcp-token"
CALLER = "+919812700001"
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not (APP_URL and API_PYTHON.exists()), reason="TEST_DATABASE_URL / services/api/.venv missing"),
]
IDENTITY_NAMES = {"x-call-id", "x-caller-number", "idempotency-key", "callid", "callernumber", "caller_number"}


def _rollout_env() -> dict[str, str]:
    env = {}
    for line in (ROLLOUT / "rollout.env").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            key, _, value = line.partition("=")
            env[key.strip()] = value
    return env


def _wait(url: str, proc: subprocess.Popen) -> None:
    for _ in range(150):
        with contextlib.suppress(httpx.HTTPError):
            if httpx.get(url, timeout=1).status_code == 200:
                return
        if proc.poll() is not None:
            raise RuntimeError(proc.stderr.read().decode()[-3000:])
        time.sleep(0.1)
    raise RuntimeError(f"{url} did not come up")


@contextlib.contextmanager
def _process(cmd: list[str], env: dict[str, str], ready: str, cwd: Path | None = None):
    proc = subprocess.Popen(cmd, env=env, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        _wait(ready, proc)
        yield proc
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture(scope="module")
def api_url():
    port = free_port()
    env = {**os.environ, **_rollout_env(), "ROLLOUT_DIR": str(ROLLOUT), "ENV": "test", "DATABASE_URL": APP_URL,
           "HOST": "127.0.0.1", "PORT": str(port), "LOG_LEVEL": "WARNING",
           "AUTH_TOKENS_JSON": json.dumps({AGENT_TOKEN: ["agent"], STAFF_TOKEN: [
               "agent", "bookings.staff", "schedule.write", "board.write", "directory.write", "knowledge.write",
               "calls.write", "calls.read"]})}
    seeded = subprocess.run([str(API_PYTHON), "-m", "frontdesk_api.cli", "seed", "--reset"], env=env, cwd=API_DIR,
                            capture_output=True, text=True)
    assert seeded.returncode == 0, seeded.stderr[-2000:]
    with _process([str(API_PYTHON), "-m", "frontdesk_api.cli", "serve"], env, f"http://127.0.0.1:{port}/ready",
                  cwd=API_DIR):
        yield f"http://127.0.0.1:{port}/api/v1"


@contextlib.contextmanager
def _adapter(upstream: str, **extra: str):
    port = free_port()
    env = {**os.environ, "ENV": "test", "PROVIDER_ID": "demo-hospital", "DOMAIN_PACK": "healthcare",
           "TENANT_SUPPORTED_LANGUAGES": "en,kn,hi", "API_BASE_URL": upstream, "API_BEARER_TOKEN": AGENT_TOKEN,
           "MCP_BEARER_TOKEN": MCP_TOKEN, "HOST": "127.0.0.1", "PORT": str(port), "LOG_LEVEL": "WARNING", **extra}
    with _process([sys.executable, "-m", "frontdesk_mcp.cli", "serve"], env, f"http://127.0.0.1:{port}/health"):
        yield f"http://127.0.0.1:{port}"


@pytest.fixture(scope="module")
def adapter_url(api_url):
    with _adapter(api_url) as url:
        yield url


def _client(adapter: str, call_id: str | None = None, caller: str | None = CALLER) -> Client:
    headers = {"Authorization": f"Bearer {MCP_TOKEN}"}
    if call_id:
        headers["X-Call-Id"] = call_id
    if caller:
        headers["X-Caller-Number"] = caller
    return Client(StreamableHttpTransport(f"{adapter}/mcp/", headers=headers))


async def _tool(client: Client, name: str, args: dict) -> dict:
    result = await client.call_tool(name, args)
    assert result.is_error is False, result
    return result.structured_content


def _rest(token: str, call_id: str | None = None, caller: str | None = CALLER, **extra) -> dict:
    headers = {"Authorization": f"Bearer {token}", **extra}
    if call_id:
        headers["X-Call-Id"] = call_id
    if caller:
        headers["X-Caller-Number"] = caller
    return headers


def _next_monday() -> date:
    # The API runs on the real clock in facility time (Asia/Kolkata); Monday is never "today" here
    # unless the suite runs on a Monday, in which case the next one is a week away.
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    return today + timedelta(days=((0 - today.weekday()) % 7) or 7)


def _available(body: dict) -> dict[str, list[str]]:
    return {si["sessionId"]: [s["slotId"] for s in si.get("slots") or [] if s["available"]]
            for r in body.get("results", []) for si in r["sessions"]}


# ---------------------------------------------------------------- schemas and identity


async def test_no_tool_lets_the_model_supply_identity_or_a_key(adapter_url):
    async with _client(adapter_url, call_id="rv-schema") as client:
        tools = await client.list_tools()
    assert {t.name for t in tools} == {"find_availability", "manage_booking", "search_knowledge"}
    for tool in tools:
        props = {p.lower() for p in tool.inputSchema.get("properties", {})}
        assert not props & IDENTITY_NAMES, (tool.name, props & IDENTITY_NAMES)


async def test_find_availability_is_the_rest_answer_unchanged(adapter_url, api_url):
    """Certainty, price, notes and slots must cross the adapter unchanged (never upgraded)."""
    request = {"utterance": "Dr Garima next monday", "language": "en", "resourceName": "Dr Garima",
               "when": {"expression": "next monday"}}
    async with _client(adapter_url, call_id="rv-same") as client:
        via_mcp = await _tool(client, "find_availability", request)
    async with httpx.AsyncClient() as http:
        direct = (await http.post(f"{api_url}/agent/availability-search", json=request,
                                  headers=_rest(AGENT_TOKEN, call_id="rv-same"))).json()
    via_mcp.pop("asOf"), direct.pop("asOf")
    assert via_mcp == direct


async def test_mcp_offers_every_bookable_position_of_a_session(adapter_url, api_url):
    """The calibration property end to end: every phone-bookable position the schedule has for a
    session must reach the model (or the result must say that some were left out)."""
    monday = _next_monday()
    async with httpx.AsyncClient() as http:
        staff = (await http.get(f"{api_url}/availability", headers=_rest(STAFF_TOKEN), params={
            "resourceId": "res_garima", "from": monday.isoformat(), "to": monday.isoformat()})).json()["items"]
    schedule = {s["sessionId"]: [x["slotId"] for x in s["slots"] if x["available"]] for s in staff if s["bookable"]}
    async with _client(adapter_url, call_id="rv-complete") as client:
        found = await _tool(client, "find_availability", {
            "utterance": "Dr Garima next monday", "language": "en", "resourceName": "Dr Garima",
            "when": {"dateFrom": monday.isoformat(), "dateTo": monday.isoformat()}})
    offered = _available(found)
    assert set(offered) == set(schedule)
    for sid, expected in schedule.items():
        missing = sorted(set(expected) - set(offered[sid]))
        assert not missing, f"{sid}: {len(missing)} of {len(expected)} bookable positions never reach the model"


async def test_every_action_reaches_its_operation_with_header_identity(adapter_url, api_url):
    call_id = f"rv-{uuid.uuid4().hex[:8]}"
    name = f"Mcp Review {uuid.uuid4().hex[:5]}"
    async with _client(adapter_url, call_id=call_id) as client:
        found = await _tool(client, "find_availability", {
            "utterance": "Dr Garima next monday", "language": "en", "resourceName": "Dr Garima",
            "when": {"expression": "next monday"}})
        first, second = [s for slots in _available(found).values() for s in slots][:2]
        booked = await _tool(client, "manage_booking", {"action": "BOOK", "slotId": first, "language": "en",
                                                        "customer": {"name": name, "phone": CALLER[3:]}})
        again = await _tool(client, "manage_booking", {"action": "BOOK", "slotId": first, "language": "en",
                                                       "customer": {"name": name, "phone": CALLER[3:]}})
        listed = await _tool(client, "manage_booking", {"action": "LIST", "customerName": name})
        moved = await _tool(client, "manage_booking", {"action": "RESCHEDULE", "bookingId": booked["bookingId"],
                                                       "customerName": name, "newSlotId": second})
        async with httpx.AsyncClient() as http:
            stored = (await http.get(f"{api_url}/bookings/{booked['bookingId']}",
                                     headers=_rest(STAFF_TOKEN, **{"X-Acting-User": "rv"}))).json()
            same_phone = (await http.get(f"{api_url}/bookings", headers=_rest(STAFF_TOKEN),
                                         params={"phone": CALLER[3:], "limit": 100})).json()
        cancelled = await _tool(client, "manage_booking", {"action": "CANCEL", "bookingId": booked["bookingId"],
                                                           "customerName": name})
    assert booked["outcome"] == "BOOKED" and again["bookingId"] == booked["bookingId"]
    assert [i["bookingId"] for i in listed["items"]] == [booked["bookingId"]]
    assert moved["outcome"] == "RESCHEDULED" and moved["slot"]["slotId"] == second
    assert stored["callerNumber"] == CALLER and stored["callId"] == call_id and stored["slotId"] == second
    assert stored["createdVia"] == "AGENT"
    assert [b["id"] for b in same_phone["items"] if b["customer"]["name"] == name] == [booked["bookingId"]]
    assert cancelled["outcome"] == "CANCELLED" and cancelled["status"] == "CANCELLED_BY_CUSTOMER"


async def test_model_arguments_cannot_override_the_caller(adapter_url, api_url):
    call_id = f"rv-{uuid.uuid4().hex[:8]}"
    name = f"Forge Review {uuid.uuid4().hex[:5]}"
    async with _client(adapter_url, call_id=call_id) as client:
        found = await _tool(client, "find_availability", {
            "utterance": "Dr Garima next monday", "language": "en", "resourceName": "Dr Garima",
            "when": {"expression": "next monday"}})
        slot = [s for slots in _available(found).values() for s in slots][-1]
        forged = await client.call_tool("manage_booking", {
            "action": "BOOK", "slotId": slot, "language": "en", "customer": {"name": name, "phone": "9812799999"},
            "callerNumber": "+919812799999", "X-Caller-Number": "+919812799999"}, raise_on_error=False)
    body = forged.structured_content or {}
    if forged.is_error or "bookingId" not in body:
        return  # refused outright: nothing was written under a forged identity
    async with httpx.AsyncClient() as http:
        stored = (await http.get(f"{api_url}/bookings/{body['bookingId']}",
                                 headers=_rest(STAFF_TOKEN))).json()
        await http.post(f"{api_url}/agent/bookings/{body['bookingId']}/cancel", json={"customerName": name},
                        headers=_rest(AGENT_TOKEN, call_id=call_id, caller="+919812799999",
                                      **{"Idempotency-Key": f"cleanup-{call_id}"}))
    assert stored["callerNumber"] == CALLER


async def test_a_write_without_call_context_is_never_recorded(adapter_url, api_url):
    name = f"No Call {uuid.uuid4().hex[:5]}"
    async with _client(adapter_url, call_id="rv-find") as client:
        found = await _tool(client, "find_availability", {
            "utterance": "Dr Garima next monday", "language": "en", "resourceName": "Dr Garima",
            "when": {"expression": "next monday"}})
    slot = [s for slots in _available(found).values() for s in slots][0]
    async with _client(adapter_url, call_id=None) as client:
        body = await _tool(client, "manage_booking", {"action": "BOOK", "slotId": slot, "language": "en",
                                                      "customer": {"name": name, "phone": CALLER[3:]}})
    assert "bookingId" not in body
    async with httpx.AsyncClient() as http:
        rows = (await http.get(f"{api_url}/bookings", headers=_rest(STAFF_TOKEN),
                               params={"phone": CALLER[3:], "limit": 100})).json()["items"]
    assert name not in {b["customer"]["name"] for b in rows}


# ---------------------------------------------------------------- transport failures (fake upstreams)


class Upstream:
    """A local HTTP peer that records requests and then hangs, or answers with a fixed status."""

    def __init__(self, status: int | None, headers: dict[str, str] | None = None) -> None:
        self.status, self.headers, self.requests = status, headers or {}, []

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = await reader.readuntil(b"\r\n\r\n")
        lines = head.decode().split("\r\n")
        fields = {k.lower(): v.strip() for k, _, v in (x.partition(":") for x in lines[1:] if x)}
        length = int(fields.get("content-length", "0"))
        if length:
            await reader.readexactly(length)
        self.requests.append((lines[0], fields))
        if self.status is None:
            await asyncio.sleep(3600)
        body = b'{"error":{"code":"X","message":"x"}}'
        extra = "".join(f"{k}: {v}\r\n" for k, v in self.headers.items())
        writer.write(f"HTTP/1.1 {self.status} X\r\ncontent-type: application/json\r\ncontent-length: {len(body)}\r\n"
                     f"{extra}\r\n".encode() + body)
        await writer.drain()
        writer.close()


@contextlib.asynccontextmanager
async def _serve(upstream: Upstream):
    server = await asyncio.start_server(upstream.handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}/api/v1"
    finally:
        server.close()


BOOK = {"action": "BOOK", "slotId": "slot_ses_res_garima_2030-01-07_2_01", "language": "en",
        "customer": {"name": "Timeout Person", "phone": "9812700009"}}
FIND = {"utterance": "Dr Garima tomorrow", "language": "en", "resourceName": "Dr Garima"}


async def test_unreachable_api_is_could_not_check_or_could_not_record():
    with _adapter(f"http://127.0.0.1:{free_port()}/api/v1") as adapter:
        async with _client(adapter, call_id="rv-down") as client:
            read = await _tool(client, "find_availability", FIND)
            write = await _tool(client, "manage_booking", BOOK)
            listed = await _tool(client, "manage_booking", {"action": "LIST"})
    assert read["outcome"] == "COULD_NOT_CHECK" and write["outcome"] == "COULD_NOT_RECORD"
    assert listed["outcome"] == "COULD_NOT_CHECK"


async def test_a_hanging_api_times_out_and_a_write_is_retried_once_with_the_same_key():
    upstream = Upstream(status=None)
    async with _serve(upstream) as url:
        with _adapter(url, READ_TIMEOUT_SECONDS="1", WRITE_TIMEOUT_SECONDS="1") as adapter:
            async with _client(adapter, call_id="rv-hang") as client:
                started = time.monotonic()
                read = await _tool(client, "find_availability", FIND)
                read_seconds = time.monotonic() - started
                reads = len(upstream.requests)
                write = await _tool(client, "manage_booking", BOOK)
    assert read["outcome"] == "COULD_NOT_CHECK" and read_seconds < 5
    assert write["outcome"] == "COULD_NOT_RECORD"
    writes = upstream.requests[reads:]
    assert reads == 1 and len(writes) == 2, [r[0] for r in upstream.requests]
    keys = {fields.get("idempotency-key") for _, fields in writes}
    assert len(keys) == 1 and None not in keys
    assert {fields.get("x-call-id") for _, fields in writes} == {"rv-hang"}


@pytest.mark.parametrize(("status", "headers", "wait"), [(500, {}, 2), (503, {"retry-after": "7"}, 7),
                                                         (429, {"retry-after": "11"}, 11)])
async def test_server_errors_and_rate_limits_are_failures_never_answers(status, headers, wait):
    upstream = Upstream(status=status, headers=headers)
    async with _serve(upstream) as url:
        with _adapter(url) as adapter:
            async with _client(adapter, call_id="rv-5xx") as client:
                read = await _tool(client, "find_availability", FIND)
                write = await _tool(client, "manage_booking", BOOK)
    assert read == {"outcome": "COULD_NOT_CHECK", "retryAfterSeconds": wait}
    assert write == {"outcome": "COULD_NOT_RECORD", "retryAfterSeconds": wait}
