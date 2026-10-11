"""Walk the three tools against the in-process development stubs and print each result.

    uv run python dev/demo.py

Development only: it proves the adapter's composition and outcomes with fixtures, not the owners'
services. Trusted context is supplied the way the platform would: as headers on the MCP request.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))  # the shared serving() helper

from conftest import serving  # noqa: E402
from harness import slot_plan  # noqa: E402

from frontdesk_mcp.clock import FixedClock  # noqa: E402
from frontdesk_mcp.config import Settings  # noqa: E402
from frontdesk_mcp.server import create_app  # noqa: E402
from frontdesk_stubs import ops as ops_stub  # noqa: E402

SETTINGS = Settings(
    env="development", log_level="WARNING", provider_id="demo-hospital", domain_pack="healthcare",
    tenant_supported_languages="en,kn,hi", tenant_timezone="Asia/Kolkata", tenant_country_calling_code="91",
    ops_base_url="http://ops-stub.local/api/v1", ops_client_id="mcp-dev", ops_client_secret="dev-secret",
    mcp_bearer_token="gateway")
NOW = datetime(2026, 10, 1, 4, 30, tzinfo=UTC)  # Thursday 10:00 IST


def show(title: str, result: dict) -> None:
    print(f"\n== {title}\n{json.dumps(result, indent=2, ensure_ascii=False)}")


async def call(c: Client, title: str, tool: str, args: dict) -> dict:
    result = (await c.call_tool(tool, args)).structured_content
    show(title, result)
    return result


async def main() -> None:
    clock = FixedClock(NOW)
    scopes = {"appointments.write", "calls.write"}
    ops_state = ops_stub.OpsStubState(clock=clock, clients={"mcp-dev": ("dev-secret", scopes)})
    app = create_app(SETTINGS, clock=clock,
                     ops_transport=httpx.ASGITransport(app=ops_stub.create_app(ops_state, prefix="/api/v1")))
    async with serving(app) as base:
        gateway = {"Authorization": "Bearer gateway", "X-Call-Id": "demo-call-1",
                   "X-Caller-Number": "+919000000101", "X-Caller-Verification": "SIP_CALLER_ID"}
        async with Client(StreamableHttpTransport(f"{base}/mcp/", headers={
                **gateway,
                "X-Operation-Id": "demo-op-1"})) as c:
            show("tools visible to the gateway", {"tools": [t.name for t in await c.list_tools()]})
            await call(c, "get_doctor_availability: Dr Garima today (board IN + NOT_CONFIRMED)",
                       "get_doctor_availability", {"doctorName": "garima", "date": "today"})
            await call(c, "get_doctor_availability: Dr Kiran Hegde (stale board → callback only)",
                       "get_doctor_availability", {"doctorName": "kiran", "date": "today"})
            await call(c, "get_doctor_availability: Dr Sharma (two matches → clarification)",
                       "get_doctor_availability", {"doctorName": "Dr Sharma", "date": "today"})
            await call(c, "usual hours without a date", "get_doctor_availability",
                       {"doctorName": "garima", "purpose": "WORKING_HOURS"})
            await call(c, "future department from usual schedules", "get_doctor_availability",
                       {"departmentId": "dept_policy", "date": "2026-10-05"})
            await call(c, "manage_booking CREATE (NOTED, not a reserved time)", "manage_booking", {
                     "action": "CREATE", "patientName": "Lakshmi Rao", "patientMobile": "9000000101",
                     "doctorId": "doc_garima", "visitDate": "2026-10-02", "preferredTime": "09:30",
                     "reasonVerbatim": "ಜ್ವರ ಮೂರು ದಿನದಿಂದ", "callerConfirmed": True})
            await call(c, "manage_booking LIST (trusted caller number only)", "manage_booking", {"action": "LIST"})
        async with Client(StreamableHttpTransport(f"{base}/mcp/", headers={
                **gateway,
                "X-Call-Started-At": "2026-10-01T09:58:00+05:30"})) as c:
            show("all three tools visible to the gateway", {"tools": [t.name for t in await c.list_tools()]})
            await call(c, "record_call_summary (CALLBACK_NOTED)", "record_call_summary", {
                "intent": "AVAILABILITY", "outcome": "CALLBACK_NOTED",
                "callerMobile": "9000000101", "doctorId": "doc_kiran_hegde", "language": "kn",
                "summaryText": "Lakshmi Rao, 9000000101, asked for Dr. Kiran Hegde this evening; "
                               "board UNKNOWN; callback promised."})

        ops_state.capabilities["slots"]["enabled"] = True
        ops_state.set_slots("doc_garima", "2026-10-01", slot_plan())
        async with Client(StreamableHttpTransport(f"{base}/mcp/", headers={
                **gateway, "X-Operation-Id": "demo-slots-create"})) as c:
            available = await call(c, "slots: availability today", "get_doctor_availability", {
                "doctorId": "doc_garima", "date": "today"})
            offered = next((block for doctor in available["doctors"] for session in doctor["board"]
                            for block in session["openSlots"] or []), None)
            if offered is None:
                raise RuntimeError("slots demo: availability offered no open block")
            create = {"action": "CREATE", "doctorId": "doc_garima", "visitDate": "2026-10-01",
                      "patientName": "Demo Patient", "patientMobile": "9000000101", "callerConfirmed": True}
            await call(c, "slots: CREATE without a time", "manage_booking", create)
            await call(c, "slots: CREATE with an offered time", "manage_booking", {
                **create, "preferredTime": offered["start"]})


if __name__ == "__main__":
    asyncio.run(main())
