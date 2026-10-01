"""The external acceptance gates cannot be passed by an unavailable, refused or failing downstream. Each predicate
is exercised against the in-process stubs with injected failures: it must raise."""

from __future__ import annotations

import pytest

from frontdesk_mcp import booking

from . import gates, harness


@pytest.fixture
async def h(make_settings):
    built = harness.build(make_settings())
    yield built
    await built.aclose()


async def run(h, ctx, **args):
    service = booking.BookingService(h.ops, h.knowledge, h.settings, h.clock)
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
                {"outcome": "ROUTING_UNAVAILABLE"}, {}):
        with pytest.raises(gates.GateFailure):
            gates.assert_backend_lookup_succeeded(bad)
    gates.assert_backend_lookup_succeeded({"outcome": "NOT_FOUND"})
