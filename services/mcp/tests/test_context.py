"""Trusted call context comes only from the MCP request headers the platform forwards through the
gateway; the model never supplies it. Deadlines are one budget per invocation; the clock is injectable."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime

import pytest

from frontdesk_mcp import clock, context, identity


def b64(obj) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")


def test_deadline_counts_down_and_caps_each_request():
    ticks = iter([0.0, 0.5, 1.9, 2.5])
    deadline = clock.Deadline(2.0, monotonic=lambda: next(ticks))
    assert deadline.remaining() == pytest.approx(1.5)
    assert deadline.timeout(cap=1.0) == pytest.approx(0.1)  # remaining 0.1 < cap
    with pytest.raises(clock.DeadlineExceeded):
        deadline.timeout(cap=1.0)  # 2.5 > 2.0


def test_fixed_clock_reports_facility_local_date(make_settings):
    fixed = clock.FixedClock(datetime(2026, 10, 1, 19, 30, tzinfo=UTC))  # 01:00 IST on 2 Oct
    assert fixed.now().isoformat() == "2026-10-01T19:30:00+00:00"
    assert clock.local_now(fixed, make_settings().zone).date().isoformat() == "2026-10-02"


def test_headers_become_a_call_context(make_settings):
    headers = {
        "x-call-id": "call-77", "x-caller-number": "+919000000101", "x-caller-verification": "SIP_CALLER_ID",
        "x-turn-context": b64({"utterance": "ನಾಳೆ ಡಾ ಗರಿಮಾ ಇರ್ತಾರಾ", "language": "kn", "turnId": "t3"}),
        "x-operation-id": "op-1", "x-call-started-at": "2026-10-01T10:00:00+05:30", "x-call-duration-seconds": "184",
    }
    ctx = context.from_headers(headers, make_settings())
    assert ctx.call_id == "call-77" and ctx.caller_number == "+919000000101"
    assert ctx.caller_verification == "SIP_CALLER_ID" and ctx.operation_id == "op-1"
    assert ctx.turn.utterance == "ನಾಳೆ ಡಾ ಗರಿಮಾ ಇರ್ತಾರಾ" and ctx.turn.language == "kn" and ctx.turn.turn_id == "t3"
    assert ctx.call_started_at == datetime.fromisoformat("2026-10-01T10:00:00+05:30")
    assert ctx.call_duration_seconds == 184


def test_absent_headers_are_absent_not_defaulted(make_settings):
    ctx = context.from_headers({}, make_settings())
    assert ctx.call_id is None and ctx.caller_number is None and ctx.turn is None
    assert ctx.operation_id is None and ctx.call_started_at is None and ctx.call_duration_seconds is None
    assert ctx.caller_verification is None


def test_a_forwarded_number_without_a_verification_header_is_unverified(make_settings):
    """The platform must assert what it verified; a bare number authorises nothing (review finding)."""
    ctx = context.from_headers({"x-caller-number": "+919000000101"}, make_settings())
    assert ctx.caller_number == "+919000000101" and ctx.caller_verification is None
    assert identity.authorised_mobile(ctx, make_settings()) is None


@pytest.mark.parametrize("header,value", [
    ("x-call-id", "x" * 65), ("x-call-id", "bad id/with?chars"), ("x-operation-id", "../op"),
    ("x-turn-context", "not-base64!"), ("x-turn-context", b64({"language": "kn"})),
    ("x-turn-context", b64(["utterance"])), ("x-call-started-at", "yesterday"), ("x-call-duration-seconds", "-1"),
    ("x-call-duration-seconds", "ten"),
])
def test_malformed_trusted_headers_are_treated_as_absent(make_settings, header, value):
    ctx = context.from_headers({header: value}, make_settings())
    assert getattr(ctx, context.FIELD_OF_HEADER[header]) is None


def test_dev_caller_number_applies_only_in_development_and_counts_as_sip_caller_id(make_settings):
    dev = make_settings(env="development", mcp_dev_caller_number="+919000000999")
    ctx = context.from_headers({}, dev)
    assert ctx.caller_number == "+919000000999" and ctx.caller_verification == "SIP_CALLER_ID"
    assert context.from_headers({"x-caller-number": "+919000000101"}, dev).caller_number == "+919000000101"
    with pytest.raises(ValueError, match="MCP_DEV_CALLER_NUMBER"):
        make_settings(env="staging", mcp_dev_caller_number="+919000000999")
    with pytest.raises(ValueError, match="MCP_DEV_CALLER_NUMBER"):
        make_settings(env="test", mcp_dev_caller_number="+919000000999")


def test_contract_mobile_requires_the_configured_country_and_ten_digits():
    assert identity.contract_mobile("+919000000101", "91") == "9000000101"
    assert identity.contract_mobile("919000000101", "91") is None  # no arbitrary prefix stripping
    assert identity.contract_mobile("+449000000101", "91") is None  # another country
    assert identity.contract_mobile("+91900000010", "91") is None  # nine digits
    assert identity.contract_mobile("+9190000001011", "91") is None  # eleven digits: never take the last ten
    assert identity.contract_mobile("+91 9000000101", "91") is None


def test_authorised_mobile_needs_number_and_accepted_verification(make_settings):
    settings = make_settings()
    ok = context.from_headers({"x-caller-number": "+919000000101", "x-caller-verification": "SIP_CALLER_ID"}, settings)
    assert identity.authorised_mobile(ok, settings) == "9000000101"
    unverified = context.from_headers({"x-caller-number": "+919000000101", "x-caller-verification": "NONE"}, settings)
    assert identity.authorised_mobile(unverified, settings) is None
    absent = context.from_headers({}, settings)
    assert identity.authorised_mobile(absent, settings) is None
    foreign = context.from_headers({"x-caller-number": "+449000000101", "x-caller-verification": "SIP_CALLER_ID"},
                                   settings)
    assert identity.authorised_mobile(foreign, settings) is None
    strict = make_settings(accepted_caller_verification="OTP")
    assert identity.authorised_mobile(ok, strict) is None


def test_mobile_fields_match_the_contract_pattern():
    assert identity.is_contract_mobile("9000000101") and not identity.is_contract_mobile("+919000000101")
    assert identity.is_approx_time("09:05")
    assert not identity.is_approx_time("9:05") and not identity.is_approx_time("24:00")
