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
OVERLAY = CONTRACTS / "manoj-openapi-20260930.test-overlay.yaml"
SPEC = yaml.safe_load(OVERLAY.read_text(encoding="utf-8"))
TOKEN_URL = "http://ops/auth/token"
# Wednesday 1 Oct 2026 10:00 IST
NOW = datetime(2026, 10, 1, 4, 30, tzinfo=UTC)


def conforms(instance, schema_name: str) -> None:
    root = {"$ref": f"#/components/schemas/{schema_name}", "components": {"schemas": SPEC["components"]["schemas"]}}
    jsonschema.Draft7Validator(root, format_checker=jsonschema.Draft7Validator.FORMAT_CHECKER).validate(instance)


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
    assert len(paged["items"]) == 3 and paged["total"] == 10

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
    body = {"callId": "call-9", "startedAt": "2026-10-01T09:58:00+05:30", "durationSeconds": 184, "language": "KN",
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
