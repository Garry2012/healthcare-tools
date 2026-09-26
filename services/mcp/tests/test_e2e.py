"""End to end through the running adapter and a running, seeded frontdesk-api:
find_availability → BOOK → LIST → RESCHEDULE → CANCEL, with identity from HTTP headers."""

from __future__ import annotations

import os
import uuid

import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from frontdesk_mcp.server import create_app

from .conftest import serving

API_URL = os.environ.get("MCP_E2E_API_URL")
API_TOKEN = os.environ.get("MCP_E2E_API_TOKEN")
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not (API_URL and API_TOKEN), reason="MCP_E2E_API_URL / MCP_E2E_API_TOKEN not set"),
]
CALLER = "+919000000555"


def slots_of(result: dict) -> list[str]:
    return [
        slot["slotId"]
        for resource in result["results"]
        for session in resource["sessions"]
        for slot in session.get("slots", [])
        if slot["available"]
    ]


async def test_book_list_reschedule_cancel(make_settings):
    app = create_app(make_settings(api_base_url=API_URL, api_bearer_token=API_TOKEN))
    call_id = f"e2e-{uuid.uuid4().hex[:8]}"
    customer = {"name": f"Test Customer {uuid.uuid4().hex[:6]}", "phone": CALLER[3:]}
    async with serving(app) as base:
        transport = StreamableHttpTransport(f"{base}/mcp/", headers={
            "Authorization": "Bearer mcp-token", "X-Call-Id": call_id, "X-Caller-Number": CALLER})
        async with Client(transport) as client:

            async def tool(name: str, args: dict) -> dict:
                result = await client.call_tool(name, args)
                assert result.is_error is False
                return result.structured_content

            found = await tool("find_availability", {
                "utterance": "is Dr Garima there next monday", "language": "en",
                "resourceName": "Dr Garima", "when": {"expression": "next monday"}})
            assert found["outcome"] == "FOUND" and found["routing"]["action"] == "OFFER_SLOTS"
            first, second, *_ = slots_of(found)

            book_args = {"action": "BOOK", "slotId": first, "customer": customer, "language": "en",
                         "reasonVerbatim": "follow-up"}
            booked = await tool("manage_booking", book_args)
            assert booked["outcome"] == "BOOKED" and booked["status"] == "BOOKED"
            booking_id = booked["bookingId"]

            replay = await tool("manage_booking", book_args)  # a retry in the same call
            assert replay["bookingId"] == booking_id

            listed = await tool("manage_booking", {"action": "LIST", "customerName": customer["name"]})
            assert listed["outcome"] == "FOUND" and listed["identityBasis"] == "CALLER_NUMBER"
            assert [i["bookingId"] for i in listed["items"]] == [booking_id]

            moved = await tool("manage_booking", {
                "action": "RESCHEDULE", "bookingId": booking_id, "customerName": customer["name"],
                "newSlotId": second})
            assert moved["outcome"] == "RESCHEDULED"
            assert moved["slot"]["slotId"] == second and moved["previousSlot"]["slotId"] == first

            cancelled = await tool("manage_booking", {
                "action": "CANCEL", "bookingId": booking_id, "customerName": customer["name"]})
            assert cancelled["outcome"] == "CANCELLED" and cancelled["status"] == "CANCELLED_BY_CUSTOMER"

            stranger = await tool("manage_booking", {
                "action": "CANCEL", "bookingId": booking_id, "customerName": "Somebody Else"})
            assert stranger["error"]["code"] == "NOT_FOUND"
