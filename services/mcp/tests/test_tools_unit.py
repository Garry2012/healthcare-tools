"""Hermetic adapter tests. HTTP to the API is replaced at the transport boundary only."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import yaml
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from frontdesk_mcp import packs, tools
from frontdesk_mcp.server import build_mcp, create_app

from .conftest import serving

SPEC = Path(__file__).resolve().parents[3] / "docs/frontdesk-api/openapi.yaml"
FORBIDDEN = {"x-call-id", "xcallid", "callid", "x-caller-number", "xcallernumber", "callernumber",
             "idempotency-key", "idempotencykey"}


def _names(schema: dict) -> set[str]:
    found: set[str] = set()
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key == "properties" and isinstance(value, dict):
                found |= {k.lower().replace("_", "") for k in value}
            found |= _names(value)
    elif isinstance(schema, list):
        for item in schema:
            found |= _names(item)
    return found


def mcp_with(settings, handler=None, transport=None):
    transport = transport or (httpx.MockTransport(handler) if handler else None)
    return build_mcp(tools.ApiClient(settings, transport=transport))


async def test_exactly_three_tools_without_header_parameters(make_settings):
    async with Client(mcp_with(make_settings())) as client:
        listed = await client.list_tools()
    assert sorted(t.name for t in listed) == ["find_availability", "manage_booking", "search_knowledge"]
    for tool in listed:
        leaked = _names(tool.inputSchema) & FORBIDDEN
        assert leaked == set(), f"{tool.name} exposes {leaked}"


@pytest.mark.skipif(not SPEC.is_file(), reason="spec not available")
async def test_tool_set_matches_x_mcp_tools(make_settings):
    spec = yaml.safe_load(SPEC.read_text())["x-mcp-tools"]
    async with Client(mcp_with(make_settings())) as client:
        listed = {t.name for t in await client.list_tools()}
    assert listed == {name for name, entry in spec.items() if "operations" in entry}


@pytest.mark.parametrize("pack", ["healthcare", "hospitality"])
async def test_domain_pack_sets_the_words_but_not_the_schema(make_settings, pack):
    """Same tools and parameters in every domain; only descriptions change."""
    async with Client(mcp_with(make_settings(domain_pack="healthcare"))) as client:
        base = {t.name: t for t in await client.list_tools()}
    async with Client(mcp_with(make_settings(domain_pack=pack))) as client:
        listed = {t.name: t for t in await client.list_tools()}
        instructions = client.initialize_result.instructions
    text = packs.load(pack)
    assert instructions == text.instructions
    for name, tool in listed.items():
        assert tool.description == text.tools[name].description
        assert set(tool.inputSchema["properties"]) == set(base[name].inputSchema["properties"])
        for param, description in text.tools[name].parameters.items():
            assert tool.inputSchema["properties"][param]["description"] == description


def test_unknown_pack_is_refused(make_settings):
    with pytest.raises(ValueError, match="Unknown DOMAIN_PACK"):
        make_settings(domain_pack="nonexistent")


async def test_api_down_is_could_not_check_not_an_exception(make_settings):
    settings = make_settings(api_base_url="http://127.0.0.1:1/api/v1")
    async with Client(mcp_with(settings)) as client:
        result = await client.call_tool("find_availability", {"utterance": "Dr Garima tomorrow", "language": "en"})
        booked = await client.call_tool("manage_booking", {
            "action": "BOOK", "slotId": "slot_ses_res_garima_2026-09-28_2_01", "language": "en",
            "customer": {"name": "Lakshmi Rao", "phone": "9000000101"}})
        listed = await client.call_tool("manage_booking", {"action": "LIST"})
        answer = await client.call_tool("search_knowledge", {"question": "parking?", "language": "en"})
    assert result.is_error is False and result.structured_content["outcome"] == "COULD_NOT_CHECK"
    assert booked.structured_content["outcome"] == "COULD_NOT_RECORD"
    assert listed.structured_content["outcome"] == "COULD_NOT_CHECK"
    assert answer.structured_content["outcome"] == "COULD_NOT_CHECK"
    assert isinstance(result.structured_content["retryAfterSeconds"], int)


async def test_5xx_and_429_carry_retry_after(make_settings):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, headers={"Retry-After": "7"}, json={"error": {"code": "SERVICE_UNAVAILABLE"}})

    async with Client(mcp_with(make_settings(), handler)) as client:
        result = await client.call_tool("find_availability", {"utterance": "x", "language": "en"})
    assert result.structured_content == {"outcome": "COULD_NOT_CHECK", "retryAfterSeconds": 7}


async def test_rest_body_is_returned_unchanged(make_settings):
    body = {"outcome": "FOUND", "asOf": "2026-09-25T10:00:00+05:30", "routing": {"action": "OFFER_SLOTS"},
            "understood": {"resources": [], "categories": []}, "results": [], "alternatives": []}
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=body)

    async with Client(mcp_with(make_settings(), handler)) as client:
        result = await client.call_tool("find_availability", {
            "utterance": "ನಾಳೆ ಸಂಜೆ ಗರಿಮಾ", "language": "kn", "resourceName": "ಗರಿಮಾ",
            "when": {"expression": "ನಾಳೆ ಸಂಜೆ"}})
    assert result.structured_content == body
    sent = json.loads(seen[0].content)
    assert sent == {"utterance": "ನಾಳೆ ಸಂಜೆ ಗರಿಮಾ", "language": "kn", "resourceName": "ಗರಿಮಾ",
                    "when": {"expression": "ನಾಳೆ ಸಂಜೆ"}}
    assert seen[0].headers["authorization"] == "Bearer api-token"


async def test_4xx_error_bodies_pass_through(make_settings):
    conflict = {"error": {"code": "SLOT_UNAVAILABLE", "message": "taken", "currentSlots": []}}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json=conflict)

    async with Client(mcp_with(make_settings(), handler)) as client:
        result = await client.call_tool("manage_booking", {
            "action": "BOOK", "slotId": "slot_x", "language": "en",
            "customer": {"name": "A B", "phone": "9000000101"}})
    assert result.structured_content == conflict


async def test_write_timeout_retries_once_with_the_same_key(make_settings):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if len(seen) == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(201, json={"outcome": "BOOKED"})

    app = create_app(make_settings(), transport=httpx.MockTransport(handler))
    async with serving(app) as base:
        transport = StreamableHttpTransport(f"{base}/mcp/", headers={
            "Authorization": "Bearer mcp-token", "X-Call-Id": "call-77", "X-Caller-Number": "+919000000101"})
        async with Client(transport) as client:
            result = await client.call_tool("manage_booking", {
                "action": "BOOK", "slotId": "slot_x", "language": "en",
                "customer": {"name": "Lakshmi Rao", "phone": "9000000101"}})
    assert result.structured_content == {"outcome": "BOOKED"}
    assert len(seen) == 2
    expected = tools.idempotency_key("call-77", "BOOK", "Lakshmi Rao", "slot_x")
    assert [r.headers["idempotency-key"] for r in seen] == [expected, expected]
    assert seen[0].headers["x-call-id"] == "call-77" and seen[0].headers["x-caller-number"] == "+919000000101"


async def test_gateway_must_authenticate(make_settings):
    app = create_app(make_settings(), transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    async with serving(app) as base, httpx.AsyncClient() as http:
        denied = await http.post(f"{base}/mcp/", json={})
        health = await http.get(f"{base}/health")
    assert denied.status_code == 401 and health.status_code == 200


async def test_absent_caller_number_is_forwarded_as_absent(make_settings):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"outcome": "IDENTITY_UNAVAILABLE"})

    for settings, expected in ((make_settings(), None),
                               (make_settings(env="development", mcp_dev_caller_number="+919000000999"),
                                "+919000000999")):
        seen.clear()
        app = create_app(settings, transport=httpx.MockTransport(handler))
        async with serving(app) as base:
            transport = StreamableHttpTransport(f"{base}/mcp/", headers={
                "Authorization": "Bearer mcp-token", "X-Call-Id": "call-9"})
            async with Client(transport) as client:
                await client.call_tool("manage_booking", {"action": "LIST"})
        assert seen[0].headers.get("x-caller-number") == expected


async def test_write_that_times_out_twice_is_could_not_record(make_settings):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("slow", request=request)

    async with Client(mcp_with(make_settings(), handler)) as client:
        result = await client.call_tool("manage_booking", {
            "action": "CANCEL", "bookingId": "bkg_1", "customerName": "A B"})
    assert calls == 2
    assert result.structured_content["outcome"] == "COULD_NOT_RECORD"


async def test_missing_action_arguments_are_reported_without_a_call(make_settings):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    async with Client(mcp_with(make_settings(), handler)) as client:
        book = await client.call_tool("manage_booking", {"action": "BOOK"})
        cancel = await client.call_tool("manage_booking", {"action": "CANCEL", "bookingId": "bkg_1"})
        move = await client.call_tool("manage_booking", {
            "action": "RESCHEDULE", "bookingId": "bkg_1", "customerName": "A B"})
    assert book.structured_content["error"]["details"][0]["field"] == "slotId"
    assert cancel.structured_content["error"]["details"][0]["field"] == "customerName"
    assert move.structured_content["error"]["details"][0]["field"] == "newSlotId"


def test_idempotency_key_derivation():
    key = tools.idempotency_key("call-1", "BOOK", "Lakshmi Rao", "slot_a")
    assert key == tools.idempotency_key("call-1", "BOOK", "  lakshmi   rao ", "slot_a")  # retry after a drop
    assert key != tools.idempotency_key("call-1", "BOOK", "Aarav Rao", "slot_a")  # second customer, same call
    assert key != tools.idempotency_key("call-2", "BOOK", "Lakshmi Rao", "slot_a")
    assert len(key) == 64


def test_dev_caller_number_is_refused_in_production(make_settings):
    with pytest.raises(ValueError, match="MCP_DEV_CALLER_NUMBER"):
        make_settings(env="production", mcp_dev_caller_number="+919000000101")
