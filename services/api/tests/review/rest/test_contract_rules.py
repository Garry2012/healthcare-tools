"""Contract RULEs that the existing suite checks only shallowly or not at all (docs/review/TEST-AUDIT.md §C)."""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest

from frontdesk_api.app import create_app

from ..conftest import STAFF, book_body, call, search_body
from ..oracle import SessionSpec

pytestmark = pytest.mark.postgres
NAME = "Dr Zenobia Quillfeather"
PM = SessionSpec("15:00", "17:00", mode="PER_HOUR", value=4, reserve_percent=25)


async def test_slot_conflict_carries_every_current_bookable_slot_of_that_session(client, desk, clock):
    """RULE: 409 SLOT_UNAVAILABLE with the session's current bookable slots (all of them)."""
    built = await desk.resource(NAME, {"s1": PM})
    day = clock.today + timedelta(days=1)
    (session,) = await desk.availability(built.resource_id, day)
    taken = session["slots"][2]["slotId"]
    assert (await client.post("/agent/bookings", headers=call(key="c1"), json=book_body(taken))).status_code == 201
    lost = await client.post("/agent/bookings", headers=call(caller="+919812300077", key="c2"),
                             json=book_body(taken, name="Late Caller", phone="9812300077"))
    (now,) = await desk.availability(built.resource_id, day)
    expected = [s["slotId"] for s in now["slots"] if s["available"]]
    assert [s["slotId"] for s in lost.json()["error"]["currentSlots"]] == expected


@pytest.mark.parametrize(("ahead", "allowed"), [(180, True), (181, False)])
async def test_booking_horizon_boundary(client, desk, clock, review_settings, ahead, allowed):
    assert review_settings.tenant_booking_horizon_days == 180
    built = await desk.resource(NAME, {"s1": PM})
    day = clock.today + timedelta(days=ahead)
    (session,) = await desk.availability(built.resource_id, day)
    slot = session["slots"][0]["slotId"]
    r = await client.post("/agent/bookings", headers=call(key=f"h{ahead}"), json=book_body(slot))
    assert (r.status_code == 201) == allowed, r.text


@pytest.mark.parametrize(("days", "shortened"), [(31, False), (32, True)])
async def test_search_range_is_capped_at_31_days_and_says_so(client, desk, clock, days, shortened):
    await desk.resource(NAME, {"s1": PM})
    start = clock.today + timedelta(days=1)
    end = start + timedelta(days=days - 1)
    r = await client.post("/agent/availability-search", headers=call(), json={
        "utterance": NAME, "language": "en", "resourceName": NAME,
        "when": {"dateFrom": start.isoformat(), "dateTo": end.isoformat()}})
    body = r.json()
    got = body["understood"]["dates"]
    assert got["from"] == start.isoformat()
    assert got["to"] == ((start + timedelta(days=30)).isoformat() if shortened else end.isoformat())
    assert any("shortened" in n for n in body.get("notes") or []) == shortened


async def test_same_day_lookup_embeds_the_resource_state_today(client, desk, clock):
    """RULE: each LIST item embeds the resource's current session state ('is my doctor coming?')."""
    built = await desk.resource(NAME, {"s1": PM})
    clock.set(clock.now.replace(hour=13, minute=0))
    (session,) = await desk.availability(built.resource_id, clock.today)
    await client.post("/agent/bookings", headers=call(key="t1"), json=book_body(session["slots"][0]["slotId"]))
    await desk.board(built.resource_id, session["sessionId"], presence="ARRIVING", delayMinutes=30)
    listed = (await client.get("/agent/bookings", headers=call())).json()
    (item,) = listed["items"]
    today = item["resourceToday"]
    assert today["sessionId"] == session["sessionId"]
    assert (today["presence"], today["delayMinutes"], today["expectedStart"]) == ("ARRIVING", 30, "15:30")


async def test_a_named_doctor_on_leave_gets_same_category_alternatives(client, desk, clock):
    """IMPLEMENTATION: requested doctor on leave -> unavailable[] with the reason and alternatives[]
    in the same department."""
    wanted = await desk.resource(NAME, {"s1": PM}, category="cat_rv_ent")
    colleague = await desk.resource("Dr Octavian Brightwater", {"s1": PM}, category="cat_rv_ent")
    day = clock.today + timedelta(days=1)
    await desk.exception(resourceId=wanted.resource_id, dateFrom=day, dateTo=day, scope="WHOLE_DAY",
                         effect="UNAVAILABLE", reasonCategory="LEAVE")
    body = (await client.post("/agent/availability-search", headers=call(), json=search_body(NAME, day))).json()
    assert body["outcome"] == "NONE_AVAILABLE"
    (result,) = body["results"]
    assert [u["reason"] for u in result["unavailable"]] == ["CANCELLED"]
    assert [a["resource"]["resourceId"] for a in body["alternatives"]] == [colleague.resource_id]
    assert all(s["bookable"] for a in body["alternatives"] for s in a["sessions"])


async def test_switching_a_resource_to_not_offered_impacts_its_future_bookings(client, desk, clock):
    """x-rules (updateResource): bookingPolicy=NOT_OFFERED -> future live bookings NEEDS_RESCHEDULE,
    one SESSION_CANCELLED notification each."""
    built = await desk.resource(NAME, {"s1": PM})
    day = clock.today + timedelta(days=3)
    (session,) = await desk.availability(built.resource_id, day)
    ids = []
    for i, slot in enumerate(session["slots"][:2]):
        r = await client.post("/agent/bookings", headers=call(caller=f"+91981230010{i}", key=f"no{i}"),
                              json=book_body(slot["slotId"], name=f"Offered Person {i}", phone=f"981230010{i}"))
        ids.append(r.json()["bookingId"])
    r = await client.put(f"/resources/{built.resource_id}", headers=STAFF, json={
        "name": NAME, "categoryIds": [built.category_id], "bookingPolicy": "NOT_OFFERED", "dataConfirmed": True})
    assert r.status_code == 200, r.text
    for booking_id in ids:
        assert (await client.get(f"/bookings/{booking_id}", headers=STAFF)).json()["status"] == "NEEDS_RESCHEDULE"
    notes = (await client.get("/notifications", headers=STAFF, params={"resourceId": built.resource_id})).json()
    assert sorted((n["bookingId"], n["trigger"]) for n in notes["items"]) == sorted(
        (b, "SESSION_CANCELLED") for b in ids)


async def test_an_approved_answer_reaches_every_replica_on_its_next_question(app, review_settings, client):
    """RULE: the agent sees a change from its next question on (every replica): two application
    instances on one database, the edit made through one, the question asked of the other."""
    other = create_app(review_settings)
    ask = {"question": "do you have a lift for the fourth floor ward", "language": "en"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=other), base_url="http://test/api/v1") as second:
        before = (await second.post("/agent/knowledge-search", headers=call(), json=ask)).json()
        assert before["outcome"] != "ANSWERED"
        r = await client.post("/knowledge", headers=STAFF, json={
            "topic": "review_lift", "questions": [ask["question"]], "approved": True,
            "answers": {"en": "Yes, lift B goes to the fourth floor."}})
        assert r.status_code == 201, r.text
        after = (await second.post("/agent/knowledge-search", headers=call(), json=ask)).json()
    await other.state.engine.dispose()
    assert after["outcome"] == "ANSWERED" and after["answer"]["text"] == "Yes, lift B goes to the fourth floor."
