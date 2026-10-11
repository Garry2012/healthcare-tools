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
PINNED = CONTRACTS / "manoj-openapi-20261007.yaml"
OVERLAY = CONTRACTS / "manoj-openapi-20261007.test-overlay.yaml"
PINNED_SHA256 = "d3e93f45498fb86feeb5bb93c0adaba7cff47b48daa21ac810790b5483e96c80"
OVERLAY_SHA256 = "1217015de39f137ebef159915f4fa90dfcf2fa196277ee43b6e5ce192679ff2f"
DEFECT_LINES = {2327, 2328, 2351, 2370, 2396, 2460}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_overlay() -> dict:
    """The labelled quoting-only overlay parses cleanly; the original's six defects do not."""
    return yaml.safe_load(OVERLAY.read_text(encoding="utf-8"))


def test_pinned_snapshot_and_overlay_are_present_with_recorded_hashes():
    assert PINNED.is_file(), "the pinned owner contract must stay tracked"
    assert OVERLAY.is_file(), "the labelled quoting-only overlay must stay tracked"
    assert _sha(PINNED) == PINNED_SHA256
    assert _sha(OVERLAY) == OVERLAY_SHA256


def test_overlay_differs_from_the_original_only_on_the_six_quoting_defects():
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
    example = response["content"]["application/json"]["examples"]["facilityBoardMixedDay"]["value"]
    board = contract.AvailabilityBoard.model_validate(example)
    assert board.date.isoformat() == "2026-10-07" and len(board.items) == 6
    unknown = [e for e in board.items if e.status == "UNKNOWN"]
    assert [(e.doctorId, e.isStale, e.session, e.expectedTime, e.expectedEndTime) for e in unknown] == [
        ("doc_006", True, "Afternoon", None, None),
        ("doc_014", False, None, None, None),
    ]
    late = [e for e in board.items if e.status == "LATE"][0]
    assert late.delayMinutes == 30 and late.expectedTime == "11:00" and late.expectedEndTime == "12:30"


def test_unknown_fields_are_preserved_not_rejected():
    detail = contract.DoctorDetail.model_validate({
        "id": "doc_1", "name": "Dr X", "departments": [{"id": "d", "name": "D"}], "attendanceType": "ON_CALL",
        "active": True, "futureField": 1})
    assert detail.usualSchedule == [] and detail.dataConfirmed is None
    assert detail.model_extra == {"futureField": 1}


def test_required_fields_are_enforced():
    with pytest.raises(ValueError):
        contract.AvailabilityEntry.model_validate({"doctorId": "x", "doctorName": "y", "date": "2026-01-01"})


# Contract examples from the pinned 0.4.0 specification, not live captures.
def slot_example(name="enabledMorningFillingUp"):
    return load_overlay()["paths"]["/availability/{doctorId}/slots"]["get"]["responses"]["200"][
        "content"]["application/json"]["examples"][name]["value"]


def capability_example(name="sessionHospital"):
    return load_overlay()["paths"]["/capabilities"]["get"]["responses"]["200"][
        "content"]["application/json"]["examples"][name]["value"]


@pytest.mark.parametrize("name,status,bookable,counts", [
    ("enabledMorningFillingUp", "IN", True, [(3, 3, 0, True), (3, 1, 2, True), (3, 0, 3, True)]),
    ("lateClosesPassedBlocks", "LATE", True, [(3, 3, 0, False), (3, 0, 3, True), (3, 0, 3, True)]),
    ("morningCancelled", "CANCELLED", False, [(3, 2, 0, False), (3, 0, 0, False), (3, 0, 0, False)]),
    ("disabled", None, False, []),
])
def test_slot_contract_examples_keep_owner_facts(name, status, bookable, counts):
    raw = slot_example(name)
    plan = contract.SlotPlan.model_validate(raw)
    assert plan.doctorId == "doc_001" and plan.date.isoformat() == "2026-10-07" and plan.blockMinutes == 30
    assert plan.model_dump(mode="json") == raw
    if status is None:
        assert plan.enabled is False and plan.sessions == []
    else:
        assert plan.enabled is True
        morning = plan.sessions[0]
        assert (morning.session, morning.status, morning.bookable) == ("Morning", status, bookable)
        assert [(s.capacity, s.booked, s.available, s.bookable) for s in morning.slots] == counts
        assert [(s.start, s.end) for s in morning.slots] == [
            ("10:30", "11:00"), ("11:00", "11:30"), ("11:30", "12:00")]


@pytest.mark.parametrize("name,minutes", [("sessionHospital", 30), ("tokenHospital", 20)])
def test_capability_contract_examples_preserve_unused_fields(name, minutes):
    raw = capability_example(name)
    result = contract.Capabilities.model_validate(raw)
    assert result.slots.enabled is True and result.slots.blockMinutes == minutes
    assert result.model_extra == {k: raw[k] for k in ("availability", "appointments")}


def test_capabilities_require_enabled_but_not_block_minutes():
    result = contract.Capabilities.model_validate({"slots": {"enabled": False}})
    assert result.slots.enabled is False and result.slots.blockMinutes is None
    for raw in ({}, {"slots": {}}, {"slots": {"blockMinutes": 30}}):
        with pytest.raises(ValueError):
            contract.Capabilities.model_validate(raw)


@pytest.mark.parametrize("start,end", [("11:00", "11:00"), ("11:30", "11:00")])
def test_slot_block_rejects_empty_or_reversed_window(start, end):
    raw = slot_example()["sessions"][0]["slots"][0] | {"start": start, "end": end}
    with pytest.raises(ValueError):
        contract.SlotBlock.model_validate(raw)


@pytest.mark.parametrize("field", ["capacity", "booked", "available"])
def test_slot_block_rejects_negative_counts(field):
    raw = slot_example()["sessions"][0]["slots"][0] | {field: -1}
    with pytest.raises(ValueError):
        contract.SlotBlock.model_validate(raw)


def test_slot_block_rejects_available_above_capacity():
    raw = slot_example()["sessions"][0]["slots"][0] | {"available": 4}
    with pytest.raises(ValueError):
        contract.SlotBlock.model_validate(raw)


def test_slot_session_rejects_unordered_blocks():
    raw = slot_example()["sessions"][0]
    raw["slots"].reverse()
    with pytest.raises(ValueError):
        contract.SlotSession.model_validate(raw)


def test_slot_session_rejects_overlapping_blocks():
    raw = slot_example()["sessions"][0]
    raw["slots"][1]["start"] = "10:45"
    with pytest.raises(ValueError):
        contract.SlotSession.model_validate(raw)


def test_slot_session_accepts_adjacent_blocks_and_null_label_without_normalising():
    raw = slot_example()["sessions"][0] | {"session": None}
    result = contract.SlotSession.model_validate(raw)
    assert result.session is None and len(result.slots) == 3
    assert result.slots[0].end == result.slots[1].start == "11:00"
    assert contract.SlotSession.model_validate(raw | {"session": "  Morning  "}).session == "  Morning  "


@pytest.mark.parametrize("field", ["start", "end"])
@pytest.mark.parametrize("value", ["9:00", "24:00", "10:60"])
def test_slot_times_use_the_existing_approx_time_format(field, value):
    raw = slot_example()["sessions"][0]["slots"][0] | {field: value}
    with pytest.raises(ValueError):
        contract.SlotBlock.model_validate(raw)


def test_appointment_slot_time_is_optional_and_validated():
    from .test_ops_client import APPT

    assert contract.Appointment.model_validate(APPT).slotTime is None
    assert contract.Appointment.model_validate(APPT | {"slotTime": "11:00"}).slotTime == "11:00"
    assert contract.Appointment.model_validate(APPT | {"slotTime": None}).slotTime is None
    for value in ("9:00", "24:00", "11:60"):
        with pytest.raises(ValueError):
            contract.Appointment.model_validate(APPT | {"slotTime": value})


def test_appointment_expected_time_uses_the_contract_approx_time_format():
    from .test_ops_client import APPT

    with pytest.raises(ValueError):
        contract.Appointment.model_validate(APPT | {"expectedTime": "9:30"})
    assert contract.Appointment.model_validate(APPT | {"expectedTime": "09:30"}).expectedTime == "09:30"
    assert contract.Appointment.model_validate(APPT | {"expectedTime": None}).expectedTime is None


@pytest.mark.parametrize("name", ["SlotPlan", "SlotBlock", "SlotSession"])
def test_slot_model_fields_match_the_contract_required_properties(name):
    schemas = load_overlay()["components"]["schemas"]
    schema = schemas["SlotPlan"]["properties"]["sessions"]["items"] if name == "SlotSession" else schemas[name]
    model = getattr(contract, name)
    assert set(model.model_fields) == set(schema["required"]) == set(schema["properties"])
    assert all(f.is_required() for f in model.model_fields.values())


# Live capture 1: evidence/manoj-slots-live-20261007.txt, 2026-10-07T14:35:18+05:30.
# Owner profile had no usual schedule; these blocks came from a desk entry.
LIVE_SLOT_CAPTURE_1 = {'doctorId': 'a540cc21-8b1a-43e3-8296-43d5fe156278',
 'date': '2026-10-07',
 'enabled': True,
 'blockMinutes': 30,
 'sessions': [{'session': '',
               'status': 'IN',
               'bookable': True,
               'slots': [{'start': '10:30',
                          'end': '11:00',
                          'capacity': 5,
                          'booked': 0,
                          'available': 0,
                          'bookable': False},
                         {'start': '11:00',
                          'end': '11:30',
                          'capacity': 5,
                          'booked': 0,
                          'available': 0,
                          'bookable': False},
                         {'start': '11:30',
                          'end': '12:00',
                          'capacity': 5,
                          'booked': 0,
                          'available': 0,
                          'bookable': False}]}]}


# Live capture 2: evidence/manoj-slots-live-20261007.txt, 2026-10-07T14:35:42+05:30.
LIVE_SLOT_CAPTURE_2 = {'doctorId': '62476883-f54e-4a3a-878f-81782f48f6d7',
 'date': '2026-10-07',
 'enabled': True,
 'blockMinutes': 30,
 'sessions': [{'session': 'Morning',
               'status': 'NOT_CONFIRMED',
               'bookable': True,
               'slots': [{'start': '10:30',
                          'end': '11:00',
                          'capacity': 5,
                          'booked': 0,
                          'available': 0,
                          'bookable': False},
                         {'start': '11:00',
                          'end': '11:30',
                          'capacity': 5,
                          'booked': 0,
                          'available': 0,
                          'bookable': False},
                         {'start': '11:30',
                          'end': '12:00',
                          'capacity': 5,
                          'booked': 0,
                          'available': 0,
                          'bookable': False}]},
              {'session': 'Evening',
               'status': 'NOT_CONFIRMED',
               'bookable': True,
               'slots': [{'start': '18:30',
                          'end': '19:00',
                          'capacity': 5,
                          'booked': 0,
                          'available': 5,
                          'bookable': True},
                         {'start': '19:00',
                          'end': '19:30',
                          'capacity': 5,
                          'booked': 0,
                          'available': 5,
                          'bookable': True}]}]}


@pytest.mark.parametrize("raw,label,status", [(LIVE_SLOT_CAPTURE_1, "", "IN"),
                                            (LIVE_SLOT_CAPTURE_2, "Morning", "NOT_CONFIRMED")])
def test_live_slot_captures_preserve_closed_blocks_and_session_flag(raw, label, status):
    plan = contract.SlotPlan.model_validate(raw)
    assert plan.model_dump(mode="json") == raw
    morning = plan.sessions[0]
    assert (morning.session, morning.status, morning.bookable) == (label, status, True)
    assert [(s.capacity, s.booked, s.available, s.bookable) for s in morning.slots] == [(5, 0, 0, False)] * 3
    if label:
        assert plan.sessions[1].session == "Evening"
        assert [(s.available, s.bookable) for s in plan.sessions[1].slots] == [(5, True), (5, True)]
