"""The pinned Manoj contract is the integration authority. These tests fail if the snapshot,
its hash, or the labelled quoting-only test overlay disappear or drift, and they check our
client-side types against the contract's enums and examples (never the other way round)."""

from __future__ import annotations

import hashlib
import typing
from pathlib import Path

import pytest
import yaml

from frontdesk_mcp import contract

CONTRACTS = Path(__file__).resolve().parents[3] / "docs/handover/mcp-only/contracts"
PINNED = CONTRACTS / "manoj-openapi-20260930.yaml"
OVERLAY = CONTRACTS / "manoj-openapi-20260930.test-overlay.yaml"
PINNED_SHA256 = "b8f282718c2c45410dd0dd403369223b9cbe8dea045ee044207aa1e52ec2de78"
OVERLAY_SHA256 = "e21869b20a6c956d12d69873b138b721fc7676ba6e6f86b5ecc0a4a7af4dd1a3"
DEFECT_LINES = {1208, 1209, 1235, 1256, 1278}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_overlay() -> dict:
    """The labelled quoting-only overlay parses cleanly; the original's five defects do not."""
    return yaml.safe_load(OVERLAY.read_text(encoding="utf-8"))


def test_pinned_snapshot_and_overlay_are_present_with_recorded_hashes():
    assert PINNED.is_file(), "the pinned owner contract must stay tracked"
    assert OVERLAY.is_file(), "the labelled quoting-only overlay must stay tracked"
    assert _sha(PINNED) == PINNED_SHA256
    assert _sha(OVERLAY) == OVERLAY_SHA256


def test_overlay_differs_from_the_original_only_on_the_five_quoting_defects():
    original = PINNED.read_text(encoding="utf-8").split("\n")
    overlay = OVERLAY.read_text(encoding="utf-8").split("\n")
    assert len(original) == len(overlay)
    changed = {n + 1 for n, (a, b) in enumerate(zip(original, overlay, strict=True)) if a != b}
    assert changed == DEFECT_LINES
    for line in DEFECT_LINES:
        assert original[line - 1].replace('"', "") == overlay[line - 1].replace('"', "")  # quoting only


def test_the_original_defect_is_real_and_the_overlay_fixes_it():
    broken = yaml.safe_load(PINNED.read_text(encoding="utf-8"))
    fixed = load_overlay()
    bad = broken["components"]["schemas"]["CallSummaryCreate"]["properties"]["doctorId"]
    good = fixed["components"]["schemas"]["CallSummaryCreate"]["properties"]["doctorId"]
    assert set(bad) != {"type", "description"}  # the comma split the description into a bogus key
    assert set(good) == {"type", "description"}


@pytest.mark.parametrize("schema,literal", [
    ("AvailabilityStatus", contract.AvailabilityStatus),
    ("AppointmentStatus", contract.AppointmentStatus),
    ("AttendanceType", contract.AttendanceType),
    ("CallIntent", contract.CallIntent),
    ("CallOutcome", contract.CallOutcome),
])
def test_our_literals_are_exactly_the_contract_enums(schema, literal):
    spec = load_overlay()
    assert set(typing.get_args(literal)) == set(spec["components"]["schemas"][schema]["enum"])


def test_error_codes_and_languages_match_the_contract():
    spec = load_overlay()["components"]["schemas"]
    codes = spec["Error"]["properties"]["error"]["properties"]["code"]["enum"]
    assert set(typing.get_args(contract.ErrorCode)) == set(codes)
    languages = spec["CallSummaryCreate"]["properties"]["language"]["enum"]
    assert set(typing.get_args(contract.SummaryLanguage)) == set(languages)
    assert contract.MOBILE_PATTERN == spec["Mobile"]["pattern"]
    assert contract.APPROX_TIME_PATTERN == spec["ApproxTime"]["pattern"]


def test_the_contracts_own_board_example_parses_and_keeps_every_session():
    spec = load_overlay()
    response = spec["paths"]["/availability"]["get"]["responses"]["200"]
    example = response["content"]["application/json"]["schema"]["example"]
    board = contract.AvailabilityBoard.model_validate(example)
    assert board.date.isoformat() == "2026-09-29" and len(board.items) == 4
    unknown = [e for e in board.items if e.status == "UNKNOWN"][0]
    assert unknown.isStale is True and unknown.session is None and unknown.expectedTime is None
    late = [e for e in board.items if e.status == "LATE"][0]
    assert late.delayMinutes == 30 and late.expectedTime == "16:00" and late.expectedEndTime == "17:00"


def test_unknown_fields_are_preserved_not_rejected():
    detail = contract.DoctorDetail.model_validate({
        "id": "doc_1", "name": "Dr X", "departments": [{"id": "d", "name": "D"}], "attendanceType": "ON_CALL",
        "active": True, "futureField": 1})
    assert detail.usualSchedule == [] and detail.dataConfirmed is None
    assert detail.model_extra == {"futureField": 1}


def test_required_fields_are_enforced():
    with pytest.raises(ValueError):
        contract.AvailabilityEntry.model_validate({"doctorId": "x", "doctorName": "y", "date": "2026-01-01"})
