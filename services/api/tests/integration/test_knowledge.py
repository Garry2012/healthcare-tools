"""Knowledge base over HTTP: approved answers only, red flags first, edits visible at once."""

from __future__ import annotations

from .conftest import AGENT, STAFF, call

SEARCH = "/agent/knowledge-search"


async def ask(client, question: str, language: str = "en", **extra) -> dict:
    r = await client.post(SEARCH, headers=call(), json={"question": question, "language": language, **extra})
    assert r.status_code == 200, r.text
    return r.json()


async def test_answer_in_the_callers_language(client):
    body = await ask(client, "ಪಾರ್ಕಿಂಗ್ ಇದೆಯಾ", "kn")
    assert body["outcome"] == "ANSWERED" and body["routing"] == {"action": "ANSWER"}
    assert body["answer"]["entryId"] == "kb_parking" and body["answer"]["language"] == "kn"
    assert body["answer"]["source"] == "CURATED"


async def test_red_flag_wins_over_any_answer(client):
    body = await ask(client, "my father has chest pain, is there parking")
    assert body["outcome"] == "TRANSFER"
    assert body["routing"] == {"action": "TRANSFER_EMERGENCY", "destination": "emergency"}
    assert "answer" not in body


async def test_transfer_entry_answers_then_routes(client):
    body = await ask(client, "do you accept cashless insurance")
    assert body["outcome"] == "ANSWERED"
    assert body["routing"] == {"action": "TRANSFER_DESK", "destination": "insurance"}


async def test_no_answer_routes_to_the_desk(client):
    body = await ask(client, "tell me a joke")
    assert body["outcome"] == "NO_ANSWER" and body["routing"]["action"] == "TRANSFER_DESK"


async def test_staff_edits_are_seen_on_the_next_question_and_drafts_never(client, app):
    draft = {"topic": "canteen", "questions": ["is there a canteen", "canteen timings"],
             "answers": {"en": "The canteen is on the ground floor, open 7 AM to 9 PM."}, "approved": False}
    created = await client.post("/knowledge", headers=STAFF, json=draft)
    assert created.status_code == 201, created.text
    entry_id = created.json()["id"]
    assert (await ask(client, "is there a canteen"))["outcome"] == "NO_ANSWER"

    approved = await client.put(f"/knowledge/{entry_id}", headers=STAFF, json={**draft, "approved": True})
    assert approved.status_code == 200
    body = await ask(client, "is there a canteen")
    assert body["outcome"] == "ANSWERED" and body["answer"]["entryId"] == entry_id

    assert (await client.delete(f"/knowledge/{entry_id}", headers=STAFF)).status_code == 204
    assert (await ask(client, "is there a canteen"))["outcome"] == "NO_ANSWER"
    assert (await client.delete(f"/knowledge/{entry_id}", headers=STAFF)).status_code == 404


async def test_index_is_built_once_per_version(client, app):
    cache = app.state.knowledge_cache
    for _ in range(5):
        await ask(client, "visiting hours")
    assert cache.builds == 1


async def test_transfer_entries_need_a_known_destination(client):
    bad = {"topic": "x", "questions": ["q"], "answers": {"en": "a"}, "action": "TRANSFER_DESK",
           "destination": "nowhere"}
    r = await client.post("/knowledge", headers=STAFF, json=bad)
    assert r.status_code == 400 and r.json()["error"]["details"][0]["field"] == "destination"


async def test_agent_cannot_edit_knowledge(client):
    r = await client.get("/knowledge", headers=AGENT)
    assert r.status_code == 403
