"""The development stubs simulate the two owner contracts for tests and local demos. Their operational
responses are validated against the pinned Manoj contract (via the quoting-only overlay); the knowledge
stub follows the PROVISIONAL knowledge_contract. They are fixtures, never engines or production config."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import jsonschema
import pytest
import yaml

from frontdesk_mcp import knowledge_contract
from frontdesk_mcp.clock import FixedClock
from frontdesk_stubs import knowledge as knowledge_stub
from frontdesk_stubs import ops as ops_stub

CONTRACTS = Path(__file__).resolve().parents[3] / "docs/handover/mcp-only/contracts"
OVERLAY = CONTRACTS / "manoj-openapi-20261007.test-overlay.yaml"
SPEC = yaml.safe_load(OVERLAY.read_text(encoding="utf-8"))
TOKEN_URL = "http://ops/auth/token"
# Wednesday 1 Oct 2026 10:00 IST
NOW = datetime(2026, 10, 1, 4, 30, tzinfo=UTC)


def conforms(instance, schema_name: str) -> None:
    root = {"$ref": f"#/components/schemas/{schema_name}", "components": {"schemas": SPEC["components"]["schemas"]}}
    jsonschema.Draft7Validator(root, format_checker=jsonschema.Draft7Validator.FORMAT_CHECKER).validate(instance)


async def test_policy_fixture_has_later_matches_and_records_profile_reads(make_settings):
    from frontdesk_mcp.availability import AvailabilityRequest, AvailabilityService

    from . import harness
    h = harness.build(make_settings())
    try:
        result = await AvailabilityService(h.ops, h.cache, h.settings, h.clock).get(
            h.ctx(), AvailabilityRequest(departmentId="dept_policy", date="2026-10-05"))
        assert result.outcome == "AVAILABILITY" and len(result.doctors) == 3
        assert result.bookableFound == 5 and result.totalMatches == 12 and result.complete is False
        assert [d.doctorId for d in result.doctors] == ["doc_fixture_01", "doc_fixture_06", "doc_fixture_07"]
        paths = [r["path"] for r in h.ops_state.requests]
        assert "/doctors/doc_fixture_00" not in paths and "/availability" not in paths
        assert "/doctors/doc_fixture_09" in paths and "/doctors/doc_fixture_10" not in paths
    finally:
        await h.aclose()


@pytest.fixture
def ops():
    state = ops_stub.OpsStubState(clock=FixedClock(NOW), zone="Asia/Kolkata",
                                  clients={"mcp-test": ("ops-secret", {"appointments.write", "calls.write"}),
                                           "readonly": ("ro-secret", set())})
    return state, httpx.AsyncClient(transport=httpx.ASGITransport(app=ops_stub.create_app(state)), base_url="http://ops")


async def token(http, client_id="mcp-test", secret="ops-secret") -> dict[str, str]:
    response = await http.post("/auth/token", data={"grant_type": "client_credentials"}, auth=(client_id, secret))
    assert response.status_code == 200, response.text
    conforms(response.json(), "TokenResponse")
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_token_endpoint_accepts_basic_or_form_credentials_and_refuses_others(ops):
    state, http = ops
    form = await http.post("/auth/token", data={"grant_type": "client_credentials", "client_id": "mcp-test",
                                                "client_secret": "ops-secret"})
    assert form.status_code == 200
    wrong = await http.post("/auth/token", data={"grant_type": "client_credentials"}, auth=("mcp-test", "nope"))
    unknown = await http.post("/auth/token", data={"grant_type": "client_credentials"}, auth=("ghost", "x"))
    assert wrong.status_code == unknown.status_code == 401  # the same neutral 401
    conforms(wrong.json(), "Error")
    bad_grant = await http.post("/auth/token", data={"grant_type": "password"}, auth=("mcp-test", "ops-secret"))
    assert bad_grant.status_code == 400


async def test_every_read_requires_a_valid_bearer(ops):
    state, http = ops
    for path in ("/departments", "/doctors?query=garima", "/doctors/doc_garima", "/availability?doctorId=doc_garima",
                 "/appointments?mobile=9000000101"):
        assert (await http.get(path)).status_code == 401
        assert (await http.get(path, headers={"Authorization": "Bearer forged"})).status_code == 401


async def test_directory_responses_conform_to_the_contract(ops):
    state, http = ops
    auth = await token(http)
    departments = (await http.get("/departments", headers=auth)).json()
    for department in departments["items"]:
        conforms(department, "Department")
    assert {d["id"] for d in departments["items"]} >= {"dept_genmed", "dept_paed", "dept_dental"}
    assert not next(d for d in departments["items"] if d["id"] == "dept_dental")["hasConsultant"]

    page = (await http.get("/doctors", params={"query": "sharma"}, headers=auth)).json()
    for doctor in page["items"]:
        conforms(doctor, "DoctorSummary")
    assert {d["id"] for d in page["items"]} == {"doc_anil_sharma", "doc_ravi_sharma"} and page["total"] == 2

    by_department = (await http.get("/doctors", params={"department": "dept_genmed", "gender": "FEMALE"},
                                    headers=auth)).json()
    assert [d["id"] for d in by_department["items"]] == ["doc_garima"]

    paged = (await http.get("/doctors", params={"limit": 3, "offset": 0}, headers=auth)).json()
    assert len(paged["items"]) == 3 and paged["total"] == 22

    detail = (await http.get("/doctors/doc_garima", headers=auth)).json()
    conforms(detail, "DoctorDetail")
    assert [s["label"] for s in detail["usualSchedule"]] == ["Morning", "Afternoon"]
    assert (await http.get("/doctors/doc_nobody", headers=auth)).status_code == 404


async def test_board_is_per_session_and_marks_stale_or_missing_entries_unknown(ops):
    state, http = ops
    auth = await token(http)
    board = (await http.get("/availability", params={"doctorId": "doc_garima", "date": "today"}, headers=auth)).json()
    for entry in board["items"]:
        conforms(entry, "AvailabilityEntry")
    assert board["date"] == "2026-10-01"
    assert [(e["session"], e["status"]) for e in board["items"]] == [("Morning", "IN"), ("Afternoon", "NOT_CONFIRMED")]

    stale = (await http.get("/availability", params={"doctorId": "doc_kiran_hegde"}, headers=auth)).json()
    assert stale["items"][0]["status"] == "UNKNOWN" and stale["items"][0]["isStale"] is True

    missing = (await http.get("/availability", params={"doctorId": "doc_rohan_shetty"}, headers=auth)).json()
    assert len(missing["items"]) == 1 and missing["items"][0]["status"] == "UNKNOWN"
    conforms(missing["items"][0], "AvailabilityEntry")

    future = (await http.get("/availability", params={"doctorId": "doc_garima", "date": "2026-10-05"},
                             headers=auth)).json()
    assert future["date"] == "2026-10-05" and all(e["status"] == "UNKNOWN" for e in future["items"])

    department = (await http.get("/availability", params={"department": "dept_cardio"}, headers=auth)).json()
    assert {e["doctorId"] for e in department["items"]} == {"doc_anil_sharma", "doc_ravi_sharma"}

    both = await http.get("/availability", params={"doctorId": "x", "department": "y"}, headers=auth)
    neither = await http.get("/availability", headers=auth)
    assert both.status_code == neither.status_code == 400 and both.json()["error"]["code"] == "VALIDATION_FAILED"


async def test_appointment_lifecycle_with_idempotent_replay(ops):
    state, http = ops
    auth = await token(http)
    body = {"patientName": "Lakshmi Rao", "mobile": "9000000101", "doctorId": "doc_garima", "visitDate": "2026-10-02",
            "expectedTime": "09:30", "reasonVerbatim": "fever for three days", "callId": "call-1"}
    created = await http.post("/appointments", json=body, headers={**auth, "Idempotency-Key": "k1"})
    assert created.status_code == 201, created.text
    conforms(created.json(), "Appointment")
    assert created.json()["status"] == "NOTED"
    appointment_id = created.json()["id"]

    replay = await http.post("/appointments", json=body, headers={**auth, "Idempotency-Key": "k1"})
    assert replay.status_code == 201 and replay.json() == created.json()
    assert len(state.appointments) == 1

    changed = await http.post("/appointments", json={**body, "expectedTime": "10:00"},
                              headers={**auth, "Idempotency-Key": "k1"})
    assert changed.status_code == 409 and changed.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    listed = (await http.get("/appointments", params={"mobile": "9000000101"}, headers=auth)).json()
    assert [a["id"] for a in listed["items"]] == [appointment_id]
    assert (await http.get("/appointments", params={"mobile": "9000000999"}, headers=auth)).json()["items"] == []

    moved = await http.post(f"/appointments/{appointment_id}/reschedule",
                            json={"callerMobile": "9000000101", "newVisitDate": "2026-10-03",
                                  "newExpectedTime": "11:00"},
                            headers={**auth, "Idempotency-Key": "k2"})
    assert moved.status_code == 200 and moved.json()["status"] == "CHANGED"
    assert moved.json()["visitDate"] == "2026-10-03"

    stranger = await http.post(f"/appointments/{appointment_id}/cancel", json={"callerMobile": "9000000102"},
                               headers={**auth, "Idempotency-Key": "k3"})
    assert stranger.status_code == 404  # neutral: same as absent
    cancelled = await http.post(f"/appointments/{appointment_id}/cancel",
                                json={"callerMobile": "9000000101", "reason": "coming another day"},
                                headers={**auth, "Idempotency-Key": "k4"})
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "CANCELLED"
    again = await http.post(f"/appointments/{appointment_id}/cancel", json={"callerMobile": "9000000101"},
                            headers={**auth, "Idempotency-Key": "k5"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "CONFLICT"


async def test_appointment_validation_and_scope(ops):
    state, http = ops
    auth = await token(http)
    bad = await http.post("/appointments", json={"patientName": "A", "mobile": "12", "doctorId": "doc_garima",
                                                 "visitDate": "2026-10-02"}, headers=auth)
    assert bad.status_code == 400 and bad.json()["error"]["details"][0]["field"] == "mobile"
    both = await http.post("/appointments", json={"patientName": "A", "mobile": "9000000101", "doctorId": "doc_garima",
                                                  "department": "dept_genmed", "visitDate": "2026-10-02"}, headers=auth)
    assert both.status_code == 400
    readonly = await token(http, "readonly", "ro-secret")
    forbidden = await http.post("/appointments", json={"patientName": "A", "mobile": "9000000101",
                                                       "doctorId": "doc_garima", "visitDate": "2026-10-02"},
                                headers=readonly)
    assert forbidden.status_code == 403 and forbidden.json()["error"]["code"] == "FORBIDDEN"


async def test_call_summary_is_stored_once_per_call_id(ops):
    state, http = ops
    auth = await token(http)
    body = {"callId": "call-9", "startedAt": "2026-10-01T09:58:00+05:30", "language": "KN",
            "callerMobile": "9000000101", "intent": "AVAILABILITY", "outcome": "CALLBACK_NOTED",
            "doctorId": "doc_garima",
            "summaryText": "Lakshmi Rao asked for Dr. Garima tomorrow; board UNKNOWN; callback requested."}
    first = await http.post("/call-summaries", json=body, headers=auth)
    assert first.status_code == 201
    conforms(first.json(), "CallSummary")
    second = await http.post("/call-summaries", json={**body, "summaryText": "different wording"}, headers=auth)
    assert second.status_code == 200 and second.json() == first.json()  # original returned unchanged
    invalid = await http.post("/call-summaries", json={**body, "callId": "call-10", "outcome": "BOOKED"}, headers=auth)
    assert invalid.status_code == 400
    too_long = await http.post("/call-summaries", json={**body, "callId": "call-11", "summaryText": "x" * 501},
                               headers=auth)
    assert too_long.status_code == 400


async def test_scenarios_commit_then_fail_and_injected_failures(ops):
    state, http = ops
    auth = await token(http)
    state.commit_then["/appointments"] = 504
    body = {"patientName": "A B", "mobile": "9000000101", "doctorId": "doc_garima", "visitDate": "2026-10-02"}
    response = await http.post("/appointments", json=body, headers={**auth, "Idempotency-Key": "lost"})
    assert response.status_code == 504 and len(state.appointments) == 1  # committed, response lost
    replay = await http.post("/appointments", json=body, headers={**auth, "Idempotency-Key": "lost"})
    assert replay.status_code == 201 and replay.json()["id"] == next(iter(state.appointments))

    state.fail_next.append(("/departments", 503, {"Retry-After": "3"}))
    failed = await http.get("/departments", headers=auth)
    assert failed.status_code == 503 and failed.headers["retry-after"] == "3"
    assert (await http.get("/departments", headers=auth)).status_code == 200  # consumed once

    state.malformed_next.append("/doctors/doc_garima")
    assert (await http.get("/doctors/doc_garima", headers=auth)).json() == {"unexpected": True}


async def test_board_can_be_scripted_for_a_scenario(ops):
    state, http = ops
    auth = await token(http)
    state.set_board("2026-10-02", [{"doctorId": "doc_garima", "session": "Morning", "status": "IN",
                                   "expectedTime": "09:00", "expectedEndTime": "12:00", "updatedMinutesAgo": 5}])
    board = (await http.get("/availability", params={"doctorId": "doc_garima", "date": "2026-10-02"},
                            headers=auth)).json()
    assert [e["status"] for e in board["items"]] == ["IN"] and board["items"][0]["isStale"] is False


@pytest.fixture
def knowledge():
    state = knowledge_stub.KnowledgeStubState(bearer="knowledge-secret")
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=knowledge_stub.create_app(state)), base_url="http://kb")
    return state, http


async def test_knowledge_stub_requires_its_bearer(knowledge):
    state, http = knowledge
    response = await http.post(knowledge_contract.ANSWER_PATH, json={"question": "x", "language": "en"})
    assert response.status_code == 401


async def test_routing_fixtures_are_an_exact_match_table_not_a_classifier(knowledge):
    state, http = knowledge
    auth = {"Authorization": "Bearer knowledge-secret"}

    async def route(utterance: str) -> dict:
        response = await http.post(knowledge_contract.ANSWER_PATH, json={"question": utterance, "language": "en"},
                                   headers=auth)
        assert response.status_code == 200
        return knowledge_contract.AnswerResponse.model_validate(response.json()).model_dump()

    assert (await route("Dr Garima, I have chest pain"))["outcome"] == "EMERGENCY_TRANSFER"
    assert (await route("severe stomach pain"))["outcome"] == "DESK_TRANSFER"
    assert (await route("my child has stomach pain"))["outcome"] == "CLARIFY"
    routed = await route("I need a children's doctor")
    assert routed["outcome"] == "ROUTE_DEPARTMENT" and routed["department"]["name"] == "Paediatrics"
    assert routed["answer"]["text"] == "I can check the Paediatrics department for you."
    general = await route("pet mein dard hai")
    assert general["answer"]["text"] == "I can check the General Medicine department for you."
    assert (await route("is Dr Garima there tomorrow"))["outcome"] == "NO_ANSWER"
    # a near miss of an emergency phrase is NOT matched: the stub does not interpret words
    assert (await route("chest pain"))["outcome"] == "NO_ANSWER"


async def test_answers_come_back_verbatim_in_the_requested_language(knowledge):
    state, http = knowledge
    auth = {"Authorization": "Bearer knowledge-secret"}
    answered = (await http.post(knowledge_contract.ANSWER_PATH, json={"question": "ಪಾರ್ಕಿಂಗ್ ಇದೆಯಾ", "language": "kn"},
                                headers=auth)).json()
    parsed = knowledge_contract.AnswerResponse.model_validate(answered)
    assert parsed.outcome == "ANSWERED" and parsed.sourceId == "kb_parking" and parsed.answer.language == "kn"
    assert parsed.answer.text.startswith("ಹೌದು")
    desk = knowledge_contract.AnswerResponse.model_validate((await http.post(
        knowledge_contract.ANSWER_PATH, json={"question": "cashless", "language": "en"}, headers=auth)).json())
    assert desk.outcome == "DESK_TRANSFER" and desk.destination == "insurance"
    unknown = knowledge_contract.AnswerResponse.model_validate((await http.post(
        knowledge_contract.ANSWER_PATH, json={"question": "what is the meaning of life", "language": "en"},
        headers=auth)).json())
    assert unknown.outcome == "NO_ANSWER" and unknown.answer is None


async def test_knowledge_scenarios(knowledge):
    state, http = knowledge
    auth = {"Authorization": "Bearer knowledge-secret"}
    state.fail_next.append(503)
    assert (await http.post(knowledge_contract.ANSWER_PATH, json={"question": "x", "language": "en"},
                            headers=auth)).status_code == 503
    state.malformed_next.append(True)
    body = (await http.post(knowledge_contract.ANSWER_PATH, json={"question": "x", "language": "en"},
                            headers=auth)).json()
    assert "outcome" not in body
    state.answers.append({"id": "test", "questions": ["test phrase"], "outcome": "DESK_TRANSFER",
                          "answers": {"en": "Ask the desk"}})
    scripted = (await http.post(knowledge_contract.ANSWER_PATH, json={"question": "test phrase", "language": "en"},
                                headers=auth)).json()
    assert scripted["outcome"] == "DESK_TRANSFER"


def test_fixture_data_is_contract_shaped():
    data = json.loads((Path(ops_stub.__file__).parent / "data/demo_hospital.json").read_text(encoding="utf-8"))
    for department in data["departments"]:
        conforms(department, "Department")
    for doctor in data["doctors"]:
        conforms(doctor, "DoctorDetail")


async def test_summary_ignores_supplied_idempotency_keys_and_keeps_first_call_body(ops):
    state, http = ops
    auth = {**await token(http), "Idempotency-Key": "same-key"}
    body = {"callId": "first-call", "startedAt": "2026-10-01T09:58:00+05:30",
            "intent": "GENERAL_INFO", "outcome": "RESOLVED_BY_AGENT", "summaryText": "First answer."}
    first = await http.post("/call-summaries", json=body, headers=auth)
    second = await http.post("/call-summaries", json={**body, "callId": "second-call"}, headers=auth)
    assert first.status_code == second.status_code == 201
    repeated = await http.post("/call-summaries", json={**body, "summaryText": "Changed", "outcome": "ABANDONED"},
                               headers={**auth, "Idempotency-Key": "different-key"})
    assert repeated.status_code == 200 and repeated.json() == first.json()
    assert len(state.summaries) == 2 and state.idempotency == {}


@pytest.mark.parametrize("code,status", [("SLOT_FULL", 409), ("UNSUPPORTED_CAPABILITY", 400),
                                        ("NOT_A_CONTRACT_CODE", 409)])
async def test_scripted_write_outcomes_are_checked_against_the_owner_contract(ops, code, status):
    state, http = ops
    auth = {**await token(http), "Idempotency-Key": "scripted"}
    state.write_outcomes = {"/appointments": [{"status": status, "code": code}]}
    body = {"patientName": "A B", "mobile": "9000000101", "doctorId": "doc_garima", "visitDate": "2026-10-02"}
    response = await http.post("/appointments", json=body, headers=auth)
    assert response.status_code == status and state.appointments == {}
    assert response.json()["error"] == {"code": code, "message": "scripted owner response"}
    if code == "NOT_A_CONTRACT_CODE":
        with pytest.raises(jsonschema.ValidationError):
            conforms(response.json(), "Error")
    else:
        conforms(response.json(), "Error")


async def test_scripted_write_queue_over_http_keeps_auth_replay_fifo_and_read_boundaries(ops):
    state, http = ops
    auth = await token(http)
    body = {"patientName": "A B", "mobile": "9000000101", "doctorId": "doc_garima", "visitDate": "2026-10-02"}
    created = await http.post("/appointments", json=body, headers={**auth, "Idempotency-Key": "original"})
    assert created.status_code == 201
    configured = await http.post("/__stub/scenario", json={"writeOutcomes": {
        "/appointments": [{"status": 409, "code": "SLOT_FULL"}, {"status": 400, "code": "UNSUPPORTED_CAPABILITY"}]}})
    assert configured.status_code == 200
    assert (await http.post("/appointments", json=body)).status_code == 401
    readonly = await token(http, "readonly", "ro-secret")
    assert (await http.post("/appointments", json=body, headers=readonly)).status_code == 403
    replay = await http.post("/appointments", json=body, headers={**auth, "Idempotency-Key": "original"})
    assert replay.json() == created.json() and replay.status_code == 201
    conflict = await http.post("/appointments", json={**body, "patientName": "Changed"},
                               headers={**auth, "Idempotency-Key": "original"})
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert (await http.get("/appointments", params={"mobile": "9000000101"}, headers=auth)).status_code == 200
    for key, status, code in [("full", 409, "SLOT_FULL"), ("unsupported", 400, "UNSUPPORTED_CAPABILITY")]:
        response = await http.post("/appointments", json=body, headers={**auth, "Idempotency-Key": key})
        assert response.status_code == status and response.json()["error"]["code"] == code
        conforms(response.json(), "Error")
    assert len(state.appointments) == 1
    # A rejection is not saved as a successful replay; the consumed queue leaves normal handling intact.
    accepted = await http.post("/appointments", json=body, headers={**auth, "Idempotency-Key": "full"})
    assert accepted.status_code == 201 and len(state.appointments) == 2


async def test_scripted_write_queue_is_path_specific_and_reset_clears_it(ops):
    state, http = ops
    auth = await token(http)
    state.write_outcomes = {"/appointments/other/reschedule": [{"status": 409, "code": "SLOT_FULL"}]}
    body = {"patientName": "A B", "mobile": "9000000101", "doctorId": "doc_garima", "visitDate": "2026-10-02"}
    assert (await http.post("/appointments", json=body, headers=auth)).status_code == 201
    # Infrastructure failure must not consume the later owner decision.
    state.fail_next.append(("/appointments/other/reschedule", 503, {}))
    response = await http.post("/appointments/other/reschedule", json={}, headers=auth)
    assert response.status_code == 503 and response.json()["error"]["code"] == "INTERNAL"
    response = await http.post("/appointments/other/reschedule", json={}, headers=auth)
    assert response.status_code == 409 and response.json()["error"]["code"] == "SLOT_FULL"
    state.write_outcomes = {"/appointments": [{"status": 409, "code": "SLOT_FULL"}]}
    assert (await http.post("/__stub/reset")).status_code == 200
    assert (await http.post("/appointments", json=body, headers=auth)).status_code == 201


async def test_capabilities_default_scripting_and_reset(ops):
    from .test_contract import capability_example

    state, http = ops
    auth = await token(http)
    response = await http.get("/capabilities", headers=auth)
    assert response.status_code == 200
    default = response.json()
    conforms(default, "Capabilities")
    assert default["slots"] == {"enabled": False, "blockMinutes": 30}
    assert default["availability"] == {"supportedModes": ["SESSION", "TIME_WINDOW"], "defaultMode": "SESSION",
                                        "stalenessThresholdHours": 4}
    assert default["appointments"] == {"verification": "MOBILE_MATCH", "confirmation": "DESK_ONLY"}
    state.capabilities = capability_example("tokenHospital")  # contract example, not a live capture
    scripted = (await http.get("/capabilities", headers=auth)).json()
    conforms(scripted, "Capabilities")
    assert scripted["slots"] == {"enabled": True, "blockMinutes": 20}
    configured = capability_example()
    assert (await http.post("/__stub/scenario", json={"capabilities": configured})).status_code == 200
    scripted = (await http.get("/capabilities", headers=auth)).json()
    conforms(scripted, "Capabilities")
    assert scripted == configured
    assert (await http.post("/__stub/reset")).status_code == 200
    assert (await http.get("/capabilities", headers=auth)).json() == default


@pytest.mark.parametrize("query,date", [({}, "2026-10-01"), ({"date": "today"}, "2026-10-01"),
                                       ({"date": "2026-10-07"}, "2026-10-07")])
async def test_slots_default_is_complete_disabled_and_never_calculated(ops, query, date):
    state, http = ops
    auth = await token(http)
    # Contract-shaped override: even an enabled facility does not synthesize unscripted plans.
    await http.post("/__stub/scenario", json={"capabilities": {
        "availability": {}, "slots": {"enabled": True, "blockMinutes": 20}, "appointments": {}}})
    response = await http.get("/availability/doc_garima/slots", params=query, headers=auth)
    assert response.status_code == 200
    conforms(response.json(), "SlotPlan")
    assert response.json() == {"doctorId": "doc_garima", "date": date, "enabled": False,
                               "blockMinutes": 20, "sessions": []}


async def test_slot_today_uses_the_existing_facility_clock(ops):
    state, http = ops
    state.clock = FixedClock(datetime(2026, 10, 1, 20, 30, tzinfo=UTC))  # Oct 2 in India
    auth = await token(http)
    response = await http.get("/availability/doc_garima/slots", headers=auth)
    assert response.status_code == 200 and response.json()["date"] == "2026-10-02"
    conforms(response.json(), "SlotPlan")


async def test_slot_plans_are_scripted_by_doctor_and_date_and_reset(ops):
    from .test_contract import slot_example

    state, http = ops
    auth = await token(http)
    first = slot_example() | {"doctorId": "doc_garima"}  # contract example, not a live capture
    state.set_slots("doc_garima", "2026-10-07", first)
    second = slot_example("morningCancelled") | {"doctorId": "doc_meera_kulkarni", "date": "2026-10-08"}
    configured = await http.post("/__stub/scenario", json={"slots": {"doc_meera_kulkarni": {"2026-10-08": second}}})
    assert configured.status_code == 200
    for expected in (first, second):
        response = await http.get(f"/availability/{expected['doctorId']}/slots",
                                  params={"date": expected["date"]}, headers=auth)
        assert response.status_code == 200 and response.json() == expected
        conforms(response.json(), "SlotPlan")
    for doctor, date in [("doc_garima", "2026-10-08"), ("doc_meera_kulkarni", "2026-10-07")]:
        response = await http.get(f"/availability/{doctor}/slots", params={"date": date}, headers=auth)
        conforms(response.json(), "SlotPlan")
        assert response.json()["enabled"] is False and response.json()["sessions"] == []
    assert (await http.post("/__stub/reset")).status_code == 200
    for expected in (first, second):
        response = await http.get(f"/availability/{expected['doctorId']}/slots",
                                  params={"date": expected["date"]}, headers=auth)
        conforms(response.json(), "SlotPlan")
        assert response.json()["enabled"] is False and response.json()["sessions"] == []


@pytest.mark.parametrize("path", ["/capabilities", "/availability/doc_garima/slots"])
async def test_new_stub_reads_keep_auth_and_failure_scenarios(ops, path):
    state, http = ops
    for headers in ({}, {"Authorization": "Bearer forged"}):
        denied = await http.get(path, headers=headers)
        assert denied.status_code == 401
        conforms(denied.json(), "Error")
    auth = await token(http, "readonly", "ro-secret")  # no write scopes needed to read
    assert (await http.get(path, headers=auth)).status_code == 200
    state.fail_next.append((path, 503, {}))
    failed = await http.get(path, headers=auth)
    assert failed.status_code == 503
    conforms(failed.json(), "Error")
    state.malformed_next.append(path)
    assert (await http.get(path, headers=auth)).json() == {"unexpected": True}


@pytest.mark.parametrize("doctor,date,status,code", [("doc_missing", "today", 404, "NOT_FOUND"),
                                                    ("doc_garima", "tomorrow", 400, "VALIDATION_FAILED")])
async def test_slot_stub_owner_rejections_conform(ops, doctor, date, status, code):
    state, http = ops
    response = await http.get(f"/availability/{doctor}/slots", params={"date": date}, headers=await token(http))
    assert response.status_code == status and response.json()["error"]["code"] == code
    conforms(response.json(), "Error")


@pytest.mark.parametrize("action", ["CREATE", "RESCHEDULE"])
@pytest.mark.parametrize("configuration", ["in_process", "http"])
async def test_mixed_write_outcomes_commit_slot_time_and_preserve_fifo_replay(ops, action, configuration):
    state, http = ops
    auth = await token(http)
    body = {"patientName": "A B", "mobile": "9000000101", "doctorId": "doc_garima", "visitDate": "2026-10-02",
            "expectedTime": "10:45"}  # contract-shaped synthetic write, not a live capture
    path = "/appointments"
    if action == "RESCHEDULE":
        created = await http.post(path, json=body, headers={**auth, "Idempotency-Key": "create"})
        assert created.status_code == 201 and "slotTime" not in created.json()
        path = f"/appointments/{created.json()['id']}/reschedule"
        body = {"callerMobile": "9000000101", "newVisitDate": "2026-10-03", "newExpectedTime": "10:45"}
    before = json.loads(json.dumps(state.appointments))
    # Contract-shaped error/success fixtures: cancelled/unknown-time 400, moved slotTime, then full.
    script = [{"status": 400, "code": "VALIDATION_FAILED"}, {"slotTime": "11:00"},
              {"status": 409, "code": "SLOT_FULL"}]
    if configuration == "in_process":
        state.write_outcomes = {path: script}
    else:
        assert (await http.post("/__stub/scenario", json={"writeOutcomes": {path: script}})).status_code == 200
    rejected = await http.post(path, json=body, headers={**auth, "Idempotency-Key": "invalid"})
    assert rejected.status_code == 400 and rejected.json()["error"]["code"] == "VALIDATION_FAILED"
    conforms(rejected.json(), "Error")
    assert state.appointments == before
    state.commit_then[path] = 504
    lost = await http.post(path, json=body, headers={**auth, "Idempotency-Key": "move"})
    assert lost.status_code == 504  # handler committed before the response was lost
    assert len(state.appointments) == 1
    stored = next(iter(state.appointments.values()))
    assert stored["slotTime"] == "11:00" and stored["expectedTime"] == "10:45"
    assert stored["status"] == ("NOTED" if action == "CREATE" else "CHANGED")
    replay = await http.post(path, json=body, headers={**auth, "Idempotency-Key": "move"})
    assert replay.status_code == (201 if action == "CREATE" else 200) and replay.json() == stored
    conforms(replay.json(), "Appointment")
    full = await http.post(path, json=body, headers={**auth, "Idempotency-Key": "full"})
    assert full.status_code == 409 and full.json()["error"]["code"] == "SLOT_FULL"
    conforms(full.json(), "Error")
    assert state.appointments == {stored["id"]: replay.json()}


async def test_success_fixture_does_not_turn_a_handler_rejection_into_success(ops):
    state, http = ops
    auth = await token(http)
    state.write_outcomes = {"/appointments": [{"slotTime": "11:00"}]}
    rejected = await http.post("/appointments", json={}, headers={**auth, "Idempotency-Key": "bad"})
    assert rejected.status_code == 400 and "slotTime" not in rejected.json()
    conforms(rejected.json(), "Error")
    assert state.appointments == {} and state.idempotency == {}
    assert state.write_outcomes == {"/appointments": []}
    body = {"patientName": "A B", "mobile": "9000000101", "doctorId": "doc_garima", "visitDate": "2026-10-02"}
    next_write = await http.post("/appointments", json=body, headers={**auth, "Idempotency-Key": "valid"})
    assert next_write.status_code == 201 and "slotTime" not in next_write.json()
    conforms(next_write.json(), "Appointment")


async def test_unscripted_slots_default_minutes_when_capabilities_omit_them(ops):
    state, http = ops
    capabilities = {"availability": {}, "slots": {"enabled": False}, "appointments": {}}
    conforms(capabilities, "Capabilities")
    configured = await http.post("/__stub/scenario", json={"capabilities": capabilities})
    assert configured.status_code == 200
    response = await http.get("/availability/doc_garima/slots", headers=await token(http))
    assert response.status_code == 200
    assert response.json() == {"doctorId": "doc_garima", "date": "2026-10-01", "enabled": False,
                               "blockMinutes": 30, "sessions": []}
    conforms(response.json(), "SlotPlan")


async def test_http_write_outcomes_normalise_string_status_before_consumption(ops):
    state, http = ops
    configured = await http.post("/__stub/scenario", json={"writeOutcomes": {
        "/appointments": [{"status": "409", "code": "SLOT_FULL"}, {"slotTime": "11:00"}]}})
    assert configured.status_code == 200
    auth = await token(http)
    body = {"patientName": "A B", "mobile": "9000000101", "doctorId": "doc_garima", "visitDate": "2026-10-02"}
    full = await http.post("/appointments", json=body, headers={**auth, "Idempotency-Key": "full"})
    assert full.status_code == 409 and full.json()["error"]["code"] == "SLOT_FULL"
    conforms(full.json(), "Error")
    saved = await http.post("/appointments", json=body, headers={**auth, "Idempotency-Key": "saved"})
    assert saved.status_code == 201 and saved.json()["slotTime"] == "11:00"
    conforms(saved.json(), "Appointment")


@pytest.mark.parametrize("item", [
    {}, {"status": 409}, {"code": "SLOT_FULL"},
    {"status": "bad", "code": "SLOT_FULL"}, {"status": None, "code": "SLOT_FULL"},
    {"status": 200, "code": "SLOT_FULL"}, {"status": 600, "code": "SLOT_FULL"},
    {"status": 409, "code": "NOT_A_CONTRACT_CODE"},
    {"status": 409, "code": "SLOT_FULL", "slotTime": "11:00"},
    {"slotTime": None}, {"slotTime": "25:00"}, {"slotTime": "11:00", "extra": True},
    None, "invalid", [],
])
async def test_http_write_outcomes_reject_invalid_items_without_partial_scripting(ops, item):
    state, http = ops
    state.write_outcomes = {"/appointments": [{"slotTime": "10:30"}]}
    response = await http.post("/__stub/scenario", json={
        "failNext": [{"path": "/appointments", "status": 503}],
        "writeOutcomes": {"/appointments": [{"status": 409, "code": "SLOT_FULL"}],
                          "/appointments/other/reschedule": [item]}})
    assert response.status_code == 400 and response.json()["error"]["code"] == "VALIDATION_FAILED"
    conforms(response.json(), "Error")
    assert state.write_outcomes == {"/appointments": [{"slotTime": "10:30"}]}
    assert state.fail_next == []


@pytest.mark.parametrize("capabilities", [
    {}, None, [], {"slots": None}, {"slots": {}}, {"slots": {"enabled": "false"}},
    {"slots": {"enabled": 0}},
    *({"slots": {"enabled": True, "blockMinutes": value}} for value in (None, "30", 0, -1, 1.5, True)),
])
async def test_http_capabilities_rejected_before_any_scenario_mutation(ops, capabilities):
    state, http = ops
    original = json.loads(json.dumps(state.capabilities))
    response = await http.post("/__stub/scenario", json={
        "capabilities": capabilities, "writeOutcomes": {"/appointments": [{"slotTime": "11:00"}]},
        "failNext": [{"path": "/doctors", "status": 503}], "malformedNext": ["/availability"],
        "commitThen": {"/appointments": 504}, "delaySeconds": 1, "delayForPrefix": {"/doctors": 1},
        "boards": {"2026-10-01": []}, "slots": {"doc_garima": {"2026-10-01": {}}}})
    assert response.status_code == 400 and response.json()["error"]["code"] == "VALIDATION_FAILED"
    conforms(response.json(), "Error")
    assert state.capabilities == original and state.write_outcomes == {} and state.fail_next == []
    assert state.malformed_next == [] and state.commit_then == {} and state.delay_seconds == 0
    assert state.delay_for_prefix == {} and state.boards == {} and state.slots == {}


async def test_http_capabilities_keep_unconsumed_owner_sections(ops):
    state, http = ops
    capabilities = {"slots": {"enabled": True, "blockMinutes": 20},
                    "availability": {"ownerFact": "unchanged"}, "appointments": {"ownerFact": [1, 2]}}
    assert (await http.post("/__stub/scenario", json={"capabilities": capabilities})).status_code == 200
    assert (await http.get("/capabilities", headers=await token(http))).json() == capabilities
