"""Red flags first, multilingual resolution and clarification, verbatim knowledge answers,
credential scopes, technical failure never reported as 'nothing available', and facility-time
date boundaries. Expected wording comes from the rollout file, not from the service."""

from __future__ import annotations

from datetime import datetime

import httpx
import pytest
import yaml

from frontdesk_api.app import create_app
from tests.conftest import DEMO_HOSPITAL

from ..conftest import AGENT, STAFF, book_body, call

pytestmark = pytest.mark.postgres
DATA = yaml.safe_load((DEMO_HOSPITAL / "data.yaml").read_text())
APPROVED = {k["id"]: k["answers"] for k in DATA["knowledge"]}


async def _search(client, **body):
    r = await client.post("/agent/availability-search", headers=call(), json={"language": "en", **body})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- red flags before everything


@pytest.mark.parametrize("body", [
    {"utterance": "book Dr Garima tomorrow, my father has chest pain", "resourceName": "Dr Garima",
     "when": {"expression": "tomorrow"}},
    {"utterance": "I want an appointment", "needText": "chest pain since morning"},
    {"utterance": "skin doctor please", "category": "skin doctor", "needText": "breathing difficulty"},
    {"utterance": "ಅಪ್ಪನಿಗೆ ಎದೆ ನೋವು, ಡಾಕ್ಟರ್ ಗರಿಮಾ ನಾಳೆ", "language": "kn", "resourceName": "ಡಾಕ್ಟರ್ ಗರಿಮಾ"},
    {"utterance": "सीने में दर्द है, Dr Sharma चाहिए", "language": "hi", "resourceName": "Dr Sharma"},
], ids=["with-a-named-doctor", "in-needText-only", "with-a-category", "kannada", "hindi-ambiguous-name"])
async def test_red_flag_wins_over_every_other_resolution_and_returns_nothing_else(client, body):
    """RULE: if the safety check fires, return routing.action=TRANSFER_EMERGENCY and nothing else."""
    found = await _search(client, **body)
    assert found["routing"]["action"] == "TRANSFER_EMERGENCY" and found["outcome"] == "TRANSFER"
    assert found["results"] == [] and found["alternatives"] == []
    assert found["understood"]["resources"] == [] and found["understood"]["categories"] == []
    assert found.get("clarification") is None


async def test_red_flag_in_a_knowledge_question_transfers_too(client):
    r = await client.post("/agent/knowledge-search", headers=call(),
                          json={"question": "where is parking, my mother has chest pain", "language": "en"})
    body = r.json()
    assert body["routing"]["action"] == "TRANSFER_EMERGENCY" and body.get("answer") is None


# ---------------------------------------------------------------- multilingual and ambiguous names


async def test_two_doctors_with_one_surname_are_clarified_never_guessed(client):
    body = await _search(client, utterance="I want to see Dr Sharma", resourceName="Dr Sharma")
    assert body["outcome"] == "CLARIFICATION_NEEDED" and body["routing"]["action"] == "CLARIFY"
    assert body["results"] == []
    options = body["clarification"]["options"]
    assert body["clarification"]["type"] == "WHICH_RESOURCE"
    assert sorted(o["id"] for o in options) == ["res_anil_sharma", "res_ravi_sharma"]
    assert len({o.get("detail") for o in options}) == 2, "the two options must read differently"


@pytest.mark.parametrize(("language", "name"), [("kn", "ಡಾಕ್ಟರ್ ಗರಿಮಾ"), ("hi", "डॉक्टर गरिमा"),
                                                 ("en", "gareema madam"), ("kn", "garima madam")])
async def test_a_name_in_any_script_resolves_to_the_same_doctor(client, language, name):
    body = await _search(client, utterance=name, language=language, resourceName=name,
                         when={"expression": "next monday"})
    assert [r["resourceId"] for r in body["understood"]["resources"]] == ["res_garima"]


@pytest.mark.parametrize("entry", sorted(APPROVED))
@pytest.mark.parametrize("language", ["en", "kn", "hi"])
async def test_knowledge_answers_are_the_approved_text_verbatim(client, entry, language):
    """Every approved answer, asked with its own first question: the text must be exactly the
    provider's words for that language (or the answer's stated language), never composed."""
    question = next(k["questions"][0] for k in DATA["knowledge"] if k["id"] == entry)
    r = await client.post("/agent/knowledge-search", headers=call(), json={"question": question, "language": language})
    body = r.json()
    assert body["outcome"] == "ANSWERED", (entry, language, body["outcome"])
    answer = body["answer"]
    assert answer["entryId"] == entry
    assert answer["text"] == APPROVED[answer["entryId"]][answer["language"]]


# ---------------------------------------------------------------- credentials and scopes


@pytest.mark.parametrize(("method", "path", "json"), [
    ("PUT", "/resources/res_garima/schedule-template", {"resourceId": "res_garima", "effectiveFrom": "2026-10-01",
                                                          "sessions": []}),
    ("POST", "/schedule-exceptions", {"resourceId": "res_garima", "dateFrom": "2026-10-01", "dateTo": "2026-10-01",
                                      "scope": "WHOLE_DAY", "effect": "UNAVAILABLE"}),
    ("GET", "/bookings", None), ("GET", "/notifications", None), ("GET", "/call-summaries", None),
])
async def test_the_agent_credential_cannot_reach_staff_operations(client, method, path, json):
    r = await client.request(method, path, headers={**AGENT, "X-Acting-User": "agent", "Idempotency-Key": "s1"},
                             json=json)
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"


async def test_a_staff_credential_cannot_act_as_the_voice_agent(client):
    r = await client.post("/agent/availability-search", headers={**STAFF, "X-Call-Id": "x"},
                          json={"utterance": "Dr Garima", "language": "en"})
    assert r.status_code == 403


async def test_no_credential_and_an_unknown_credential_are_refused(client):
    for headers in ({}, {"Authorization": "Bearer not-a-token"}):
        r = await client.post("/agent/availability-search", headers={**headers, "X-Call-Id": "x"},
                              json={"utterance": "Dr Garima", "language": "en"})
        assert r.status_code == 401


# ---------------------------------------------------------------- technical failure


@pytest.fixture
async def broken_client(make_settings, clock):
    """The real application with its database unreachable (a closed local port)."""
    settings = make_settings(database_url="postgresql://nobody:x@127.0.0.1:9/none",
                             database_pool_timeout_seconds=1)
    application = create_app(settings)
    # As a real server would: an exception inside the app becomes the app's own 500 response.
    transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1") as c:
        yield c
    await application.state.engine.dispose()


async def test_database_down_is_could_not_check_never_nothing_available(broken_client):
    r = await broken_client.post("/agent/availability-search", headers=call(), json={
        "utterance": "Dr Garima tomorrow", "language": "en", "resourceName": "Dr Garima"})
    body = r.json()
    assert body["outcome"] == "COULD_NOT_CHECK" and body["routing"]["action"] == "TRANSFER_DESK"
    assert body["results"] == [] and body.get("partial") is True
    k = await broken_client.post("/agent/knowledge-search", headers=call(),
                                 json={"question": "parking", "language": "en"})
    assert k.json()["outcome"] == "COULD_NOT_CHECK"


async def test_database_down_on_writes_and_lookups_is_a_retryable_server_error(broken_client):
    booked = await broken_client.post("/agent/bookings", headers=call(key="dd-1"),
                                      json=book_body("slot_ses_res_garima_2026-09-24_2_01"))
    listed = await broken_client.get("/agent/bookings", headers=call())
    for r in (booked, listed):
        assert r.status_code >= 500, (r.status_code, r.text)
        assert r.json()["error"]["code"] in ("SERVICE_UNAVAILABLE", "INTERNAL", "UPSTREAM_TIMEOUT")


# ---------------------------------------------------------------- facility timezone and date boundaries


@pytest.mark.parametrize(("local", "today", "tomorrow"), [
    ("2026-09-23T23:50", "2026-09-23", "2026-09-24"),  # 18:20 UTC, same UTC date
    ("2026-09-24T00:10", "2026-09-24", "2026-09-25"),  # 18:40 UTC on the 23rd: the UTC date is still yesterday
    ("2026-09-24T05:20", "2026-09-24", "2026-09-25"),  # 23:50 UTC on the 23rd
])
async def test_relative_days_are_facility_days(client, clock, local, today, tomorrow):
    clock.set(datetime.fromisoformat(local))
    for expression, expected in (("today", today), ("tomorrow", tomorrow)):
        body = await _search(client, utterance=f"Dr Garima {expression}", resourceName="Dr Garima",
                             when={"expression": expression})
        assert body["understood"]["dates"] == {"from": expected, "to": expected}, (local, expression)


async def test_board_accepts_the_facility_date_just_after_midnight(client, desk, clock):
    clock.set(datetime.fromisoformat("2026-09-24T00:10"))  # Thursday in India, still Wednesday in UTC
    (utc_day, facility_day) = ("2026-09-23", "2026-09-24")
    sessions = await desk.availability("res_arjun_menon", clock.today)
    sid = sessions[0]["sessionId"]
    assert facility_day in sid
    ok = await client.put("/board/res_arjun_menon", headers=STAFF,
                          json={"date": facility_day, "sessionId": sid, "presence": "PRESENT"})
    assert ok.status_code == 200, ok.text
    stale = await client.put("/board/res_arjun_menon", headers=STAFF,
                             json={"date": utc_day, "sessionId": sid.replace(facility_day, utc_day)})
    assert stale.status_code == 400


async def test_a_session_that_ended_yesterday_evening_is_not_offered_after_midnight(client, desk, clock):
    clock.set(datetime.fromisoformat("2026-09-24T00:10"))
    body = await _search(client, utterance="Dr Arjun Menon", resourceName="Dr Arjun Menon",
                         when={"dateFrom": "2026-09-23", "dateTo": "2026-09-24"})
    offered = {s["date"] for r in body["results"] for s in r["sessions"] if s["bookable"]}
    assert offered and all(d >= clock.today.isoformat() for d in offered), offered


async def test_a_draft_answer_is_never_spoken_and_an_approved_one_is_heard_next_question(client):
    body = {"topic": "review_valet", "questions": ["is there a valet for wheelchairs at gate nine"],
            "answers": {"en": "Yes, gate nine has a wheelchair valet from 8 AM."}, "approved": False}
    r = await client.post("/knowledge", headers=STAFF, json=body)
    assert r.status_code == 201, r.text
    ask = {"question": "is there a valet for wheelchairs at gate nine", "language": "en"}
    draft = (await client.post("/agent/knowledge-search", headers=call(), json=ask)).json()
    assert draft["outcome"] != "ANSWERED" and "gate nine has" not in str(draft)
    r = await client.put(f"/knowledge/{r.json()['id']}", headers=STAFF, json={**body, "approved": True})
    assert r.status_code == 200, r.text
    approved = (await client.post("/agent/knowledge-search", headers=call(), json=ask)).json()
    assert approved["outcome"] == "ANSWERED"
    assert approved["answer"]["text"] == "Yes, gate nine has a wheelchair valet from 8 AM."
