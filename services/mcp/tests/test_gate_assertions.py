"""The external acceptance gates cannot be passed by an unavailable, refused or failing downstream. Each predicate
is exercised against the in-process stubs with injected failures: it must raise."""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from frontdesk_mcp import booking
from frontdesk_mcp.ops_client import OpsClient

from . import gates, harness


@pytest.fixture
async def h(make_settings):
    built = harness.build(make_settings())
    yield built
    await built.aclose()


async def run(h, ctx, **args):
    service = booking.BookingService(h.ops, h.settings, h.clock)
    return await service.manage(ctx, booking.BookingRequest(**args))


async def test_a_failed_list_cannot_satisfy_the_negative_gate(h):
    h.ops_state.fail_next.append(("/appointments", 503, {}))
    result = await run(h, h.ctx(), action="LIST")
    assert result.outcome == "COULD_NOT_CHECK"
    with pytest.raises(gates.GateFailure, match="did not succeed"):
        gates.assert_list_succeeded(result)


async def test_a_refused_list_cannot_satisfy_the_gate(h):
    result = await run(h, h.ctx(verification=None), action="LIST")
    assert result.outcome == "IDENTITY_UNAVAILABLE"
    with pytest.raises(gates.GateFailure):
        gates.assert_list_succeeded(result)


async def test_the_negative_gate_needs_a_successful_baseline_and_detects_a_created_appointment(h):
    before = gates.assert_list_succeeded(await run(h, h.ctx(), action="LIST"))
    assert before == []
    created = await run(h, h.ctx(operation_id="op-1"), action="CREATE", patientName="P", patientMobile="9000000101",
                        doctorId="doc_garima", visitDate="2026-10-01", preferredTime="09:30", callerConfirmed=True)
    assert created.outcome == "NOTED"
    after = gates.assert_list_succeeded(await run(h, h.ctx(), action="LIST"))
    with pytest.raises(gates.GateFailure, match="was created"):
        gates.assert_no_new_appointment(before, after, "doc_garima", "2026-10-01")
    gates.assert_no_new_appointment(before, after, "doc_garima", "2026-10-02")  # another date: nothing created


def test_identity_forwarding_is_not_backend_verification():
    gates.assert_identity_forwarded({"outcome": "COULD_NOT_CHECK"}, {"outcome": "IDENTITY_UNAVAILABLE"})
    with pytest.raises(gates.GateFailure, match="did not reach"):
        gates.assert_identity_forwarded({"outcome": "IDENTITY_UNAVAILABLE"}, {"outcome": "IDENTITY_UNAVAILABLE"})
    with pytest.raises(gates.GateFailure, match="not refused"):
        gates.assert_identity_forwarded({"outcome": "NOT_FOUND"}, {"outcome": "NOT_FOUND"})
    for bad in ({"outcome": "COULD_NOT_CHECK", "detail": "TRANSPORT"}, {"outcome": "IDENTITY_UNAVAILABLE"},
                {"outcome": "UNKNOWN_OUTCOME"}, {}):
        with pytest.raises(gates.GateFailure):
            gates.assert_backend_lookup_succeeded(bad)
    gates.assert_backend_lookup_succeeded({"outcome": "NOT_FOUND"})


@pytest.mark.parametrize("claims,allowed", [
    ({"tenant": "synthetic"}, True), ({"tenant": "another-hospital"}, False),
    ({}, False), ({"tenant": None}, False), ({"tenant": ["synthetic"]}, False), ([], False),
])
async def test_write_tenant_comes_from_the_credential_exchange(make_settings, claims, allowed):
    requests = []
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")

    def owner(request):
        requests.append(request)
        assert request.url.path == "/api/v1/auth/token"  # no appointment request may precede tenant validation
        assert request.headers["authorization"].startswith("Basic ")
        return httpx.Response(200, json={"access_token": f"header.{payload}.fixture", "token_type": "Bearer",
                                        "expires_in": 3600})

    async with OpsClient(make_settings(ops_base_url="https://owner.example/api/v1"),
                         transport=httpx.MockTransport(owner)) as ops:
        if allowed:
            await gates.assert_authenticated_write_tenant(ops, "synthetic")
        else:
            with pytest.raises(gates.GateFailure, match="BLOCKED"):
                await gates.assert_authenticated_write_tenant(ops, "synthetic")
    assert len(requests) == 1


@pytest.mark.parametrize("token", ["opaque-owner-token", "header.@@@.signature", "header.bm90LWpzb24.signature"])
async def test_opaque_or_malformed_identity_blocks_writes(make_settings, token):
    async with OpsClient(make_settings(ops_base_url="https://owner.example/api/v1"), transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={"access_token": token, "token_type": "Bearer", "expires_in": 3600})
    )) as ops:
        with pytest.raises(gates.GateFailure, match="no authoritative tenant"):
            await gates.assert_authenticated_write_tenant(ops, "synthetic")


async def test_write_tenant_auth_failure_does_not_allow_a_write(make_settings):
    async with OpsClient(make_settings(ops_base_url="https://owner.example/api/v1"),
                         transport=httpx.MockTransport(lambda _: httpx.Response(401))) as ops:
        with pytest.raises(gates.GateFailure, match="could not authenticate"):
            await gates.assert_authenticated_write_tenant(ops, "synthetic")


@pytest.mark.parametrize("url,tenant", [("http://owner.example", "synthetic"), ("https://owner.example", "")])
async def test_write_tenant_requires_https_and_a_designated_tenant(make_settings, url, tenant):
    def unexpected(_):
        pytest.fail("invalid configuration must not contact the auth service")

    async with OpsClient(make_settings(ops_base_url=url), transport=httpx.MockTransport(unexpected)) as ops:
        with pytest.raises(gates.GateFailure, match="HTTPS owner endpoint"):
            await gates.assert_authenticated_write_tenant(ops, tenant)


async def test_external_write_gate_checks_identity_before_proceeding(make_settings, monkeypatch):
    from .test_external import _write_gate

    monkeypatch.setenv("OPS_E2E_ALLOW_WRITES", "1")
    monkeypatch.setenv("OPS_E2E_MODE", "live")
    monkeypatch.setenv("OPS_E2E_WRITE_TENANT", "synthetic")
    monkeypatch.setenv("KNOWLEDGE_E2E_BASE_URL", "https://knowledge.example")
    payload = base64.urlsafe_b64encode(b'{"tenant":"production"}').decode()
    requests = []

    def owner(request):
        requests.append(request)
        return httpx.Response(200, json={"access_token": f"header.{payload}.fixture", "token_type": "Bearer",
                                        "expires_in": 3600})

    async with OpsClient(make_settings(ops_base_url="https://owner.example/api/v1"),
                         transport=httpx.MockTransport(owner)) as ops:
        with pytest.raises(gates.GateFailure, match="does not match"):
            await _write_gate(ops)
    assert [r.url.path for r in requests] == ["/api/v1/auth/token"]
