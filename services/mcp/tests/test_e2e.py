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


async def test_general_question_through_the_gateway_path(make_settings):
    app = create_app(make_settings(api_base_url=API_URL, api_bearer_token=API_TOKEN))
    async with serving(app) as base:
        transport = StreamableHttpTransport(f"{base}/mcp/", headers={
            "Authorization": "Bearer mcp-token", "X-Call-Id": f"e2e-{uuid.uuid4().hex[:8]}", "X-Caller-Number": CALLER})
        async with Client(transport) as client:
            result = await client.call_tool("search_knowledge", {"question": "पार्किंग है क्या", "language": "hi"})
    body = result.structured_content
    assert body["outcome"] == "ANSWERED" and body["answer"]["language"] == "hi"
    assert body["answer"]["entryId"] == "kb_parking"


async def test_book_cancel_book_again_in_one_call_is_really_booked(make_settings):
    """The same patient and slot in one call derive the same key; the caller must never be told
    'booked' about a booking that was cancelled a moment ago (QA/tech-lead N1)."""
    app = create_app(make_settings(api_base_url=API_URL, api_bearer_token=API_TOKEN))
    customer = {"name": f"Test Customer {uuid.uuid4().hex[:6]}", "phone": CALLER[3:]}
    async with serving(app) as base:
        transport = StreamableHttpTransport(f"{base}/mcp/", headers={
            "Authorization": "Bearer mcp-token", "X-Call-Id": f"e2e-{uuid.uuid4().hex[:8]}", "X-Caller-Number": CALLER})
        async with Client(transport) as client:

            async def tool(name: str, args: dict) -> dict:
                return (await client.call_tool(name, args)).structured_content

            found = await tool("find_availability", {
                "utterance": "Dr Garima next monday", "language": "en", "resourceName": "Dr Garima",
                "when": {"expression": "next monday"}})
            slot = slots_of(found)[-1]
            book = {"action": "BOOK", "slotId": slot, "customer": customer, "language": "en"}
            first = await tool("manage_booking", book)
            await tool("manage_booking", {"action": "CANCEL", "bookingId": first["bookingId"],
                                          "customerName": customer["name"]})
            again = await tool("manage_booking", book)
            listed = await tool("manage_booking", {"action": "LIST", "customerName": customer["name"]})
            await tool("manage_booking", {"action": "CANCEL", "bookingId": again["bookingId"],
                                          "customerName": customer["name"]})
    assert again["outcome"] == "BOOKED" and again["bookingId"] != first["bookingId"]
    assert [i["bookingId"] for i in listed["items"]] == [again["bookingId"]]


async def test_losing_a_slot_race_offers_the_live_alternatives(make_settings):
    """Two callers pick the same slot. The second must hear 'that one just went' plus slots that
    are really free now, and booking one of those must work (QA gap 15)."""
    app = create_app(make_settings(api_base_url=API_URL, api_bearer_token=API_TOKEN))
    tag = uuid.uuid4().hex[:6]
    callers = [("+919000000661", f"Race One {tag}"), ("+919000000662", f"Race Two {tag}")]
    async with serving(app) as base:
        clients = [Client(StreamableHttpTransport(f"{base}/mcp/", headers={
            "Authorization": "Bearer mcp-token", "X-Call-Id": f"e2e-{uuid.uuid4().hex[:8]}",
            "X-Caller-Number": number})) for number, _ in callers]
        async with clients[0] as one, clients[1] as two:

            async def tool(client, name: str, args: dict) -> dict:
                return (await client.call_tool(name, args)).structured_content

            found = await tool(one, "find_availability", {
                "utterance": "Dr Garima next monday", "language": "en", "resourceName": "Dr Garima",
                "when": {"expression": "next monday"}})
            slot = slots_of(found)[0]

            def book(i: int, slot_id: str) -> dict:
                number, name = callers[i]
                return {"action": "BOOK", "slotId": slot_id, "language": "en",
                        "customer": {"name": name, "phone": number[3:]}}

            won = await tool(one, "manage_booking", book(0, slot))
            lost = await tool(two, "manage_booking", book(1, slot))
            assert won["outcome"] == "BOOKED"
            assert lost["error"]["code"] == "SLOT_UNAVAILABLE"
            offered = [s["slotId"] for s in lost["error"]["currentSlots"]]
            assert offered and slot not in offered

            second_try = await tool(two, "manage_booking", book(1, offered[0]))
            assert second_try["outcome"] == "BOOKED" and second_try["slot"]["slotId"] == offered[0]

            # a number someone says aloud, without a name, discloses nothing
            probe = await tool(two, "manage_booking", {"action": "LIST", "phone": callers[0][0][3:]})
            assert probe["outcome"] == "NAME_REQUIRED" and probe["items"] == [] and probe["customersOnNumber"] == 0

            for client, (_, name), booking in ((one, callers[0], won), (two, callers[1], second_try)):
                await tool(client, "manage_booking", {"action": "CANCEL", "bookingId": booking["bookingId"],
                                                      "customerName": name})
