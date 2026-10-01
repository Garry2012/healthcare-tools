"""Walk the four tools against the in-process development stubs and print each result.

    uv run python dev/demo.py

Development only: it proves the adapter's composition and outcomes with fixtures, not the owners'
services. Trusted context is supplied the way the platform would: as headers on the MCP request.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))  # the shared serving() helper

from conftest import serving  # noqa: E402

from frontdesk_mcp.clock import FixedClock  # noqa: E402
from frontdesk_mcp.config import Settings  # noqa: E402
from frontdesk_mcp.server import create_app  # noqa: E402
from frontdesk_stubs import knowledge as knowledge_stub  # noqa: E402
from frontdesk_stubs import ops as ops_stub  # noqa: E402

SETTINGS = Settings(
    env="development", log_level="WARNING", provider_id="demo-hospital", domain_pack="healthcare",
    tenant_supported_languages="en,kn,hi", tenant_timezone="Asia/Kolkata", tenant_country_calling_code="91",
    ops_base_url="http://ops-stub.local/api/v1", ops_client_id="mcp-dev", ops_client_secret="dev-secret",
    knowledge_base_url="http://knowledge-stub.local", knowledge_bearer_token="dev-knowledge-secret",
    mcp_bearer_token="gateway", mcp_lifecycle_bearer_token="lifecycle")
NOW = datetime(2026, 10, 1, 4, 30, tzinfo=UTC)  # Thursday 10:00 IST


def turn(utterance: str, language: str = "en") -> str:
    payload = json.dumps({"utterance": utterance, "language": language}).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def show(title: str, result: dict) -> None:
    print(f"\n== {title}\n{json.dumps(result, indent=2, ensure_ascii=False)}")


async def call(c: Client, title: str, tool: str, args: dict) -> None:
    show(title, (await c.call_tool(tool, args)).structured_content)


async def main() -> None:
    clock = FixedClock(NOW)
    scopes = {"appointments.write", "calls.write"}
    ops_state = ops_stub.OpsStubState(clock=clock, clients={"mcp-dev": ("dev-secret", scopes)})
    kb_state = knowledge_stub.KnowledgeStubState(bearer="dev-knowledge-secret")
    app = create_app(SETTINGS, clock=clock,
                     ops_transport=httpx.ASGITransport(app=ops_stub.create_app(ops_state, prefix="/api/v1")),
                     knowledge_transport=httpx.ASGITransport(app=knowledge_stub.create_app(kb_state)))
    async with serving(app) as base:
        gateway = {"Authorization": "Bearer gateway", "X-Call-Id": "demo-call-1",
                   "X-Caller-Number": "+919000000101"}
        async with Client(StreamableHttpTransport(f"{base}/mcp/", headers={
                **gateway, "X-Turn-Context": turn("ಡಾಕ್ಟರ್ ಗರಿಮಾ ಇವತ್ತು ಇದ್ದಾರಾ", "kn"),
                "X-Operation-Id": "demo-op-1"})) as c:
            show("tools visible to the gateway", {"tools": [t.name for t in await c.list_tools()]})
            await call(c, "get_doctor_availability: Dr Garima today (board IN + NOT_CONFIRMED)",
                       "get_doctor_availability", {"doctorName": "garima", "date": "today"})
            await call(c, "get_doctor_availability: Dr Kiran Hegde (stale board → callback only)",
                       "get_doctor_availability", {"doctorName": "kiran", "date": "today"})
            await call(c, "get_doctor_availability: Dr Sharma (two matches → clarification)",
                       "get_doctor_availability", {"doctorName": "Dr Sharma", "date": "today"})
            await call(c, "manage_booking CREATE (NOTED, not a reserved time)", "manage_booking", {
                     "action": "CREATE", "patientName": "Lakshmi Rao", "patientMobile": "9000000101",
                     "doctorId": "doc_garima", "visitDate": "2026-10-02", "preferredTime": "09:30",
                     "reasonVerbatim": "ಜ್ವರ ಮೂರು ದಿನದಿಂದ", "callerConfirmed": True})
            await call(c, "manage_booking LIST (trusted caller number only)", "manage_booking", {"action": "LIST"})
            await call(c, "search_knowledge: ಪಾರ್ಕಿಂಗ್ ಇದೆಯಾ", "search_knowledge",
                       {"question": "ಪಾರ್ಕಿಂಗ್ ಇದೆಯಾ", "language": "kn"})
        async with Client(StreamableHttpTransport(f"{base}/mcp/", headers={
                **gateway, "X-Turn-Context": turn("Dr Garima, I have chest pain"),
                "X-Operation-Id": "demo-op-2"})) as c:
            await call(c, "get_doctor_availability with a danger sign in the trusted turn (routing decides)",
                       "get_doctor_availability", {"doctorName": "garima", "date": "today"})
        async with Client(StreamableHttpTransport(f"{base}/mcp/", headers={
                "Authorization": "Bearer lifecycle", "X-Call-Id": "demo-call-1",
                "X-Call-Started-At": "2026-10-01T09:58:00+05:30", "X-Call-Duration-Seconds": "184"})) as c:
            show("tools visible to the call-end lifecycle", {"tools": [t.name for t in await c.list_tools()]})
            await call(c, "record_call_summary (CALLBACK_NOTED)", "record_call_summary", {
                "intent": "AVAILABILITY", "outcome": "CALLBACK_NOTED", "callerName": "Lakshmi Rao",
                "callerMobile": "9000000101", "doctorId": "doc_kiran_hegde", "language": "kn",
                "summaryText": "Asked for Dr. Kiran Hegde this evening; board status UNKNOWN."})


if __name__ == "__main__":
    asyncio.run(main())
