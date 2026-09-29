"""Booking, idempotent retries, atomic reschedule, cancellation identity and disclosure, through REST,
with what is stored checked directly in PostgreSQL."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import text

from ..conftest import STAFF, book_body, call, search_body, search_sessions
from ..oracle import SessionSpec

pytestmark = pytest.mark.postgres
NAME = "Dr Zenobia Quillfeather"
CALLER = "+919812300001"  # national number 9812300001


@pytest.fixture
async def queue(desk, clock):
    """One doctor, a 15:00-17:00 queue tomorrow (4 per hour, 25 % walk-in reserve: 6 phone positions)."""
    built = await desk.resource(NAME, {"s1": SessionSpec("15:00", "17:00", mode="PER_HOUR", value=4,
                                                         reserve_percent=25)})
    day = clock.today + timedelta(days=1)
    (session,) = [s for s in await desk.availability(built.resource_id, day) if s["status"] != "CANCELLED"]
    return built, day, session


async def _rows(owner_db, sql: str, **params):
    async with owner_db.connect() as conn:
        return (await conn.execute(text(sql), params)).all()


async def _booking(owner_db, booking_id: str):
    (row,) = await _rows(owner_db, "SELECT id, status, slot_id, session_id, resource_id, date, confirmation_code, "
                                   "caller_number, phone, customer_name FROM bookings WHERE id = :id", id=booking_id)
    return row


async def _history_count(owner_db, booking_id: str) -> int:
    (row,) = await _rows(owner_db, "SELECT count(*) AS n FROM booking_history WHERE booking_id = :id", id=booking_id)
    return row.n


def _slot(session: dict, position: int) -> str:
    return next(s["slotId"] for s in session["slots"] if s["position"] == position)


# ---------------------------------------------------------------- idempotency


async def test_retry_with_same_key_replays_and_writes_once(client, queue, owner_db):
    _, _, session = queue
    body = book_body(_slot(session, 1))
    first = await client.post("/agent/bookings", headers=call(key="retry-1"), json=body)
    again = await client.post("/agent/bookings", headers=call(key="retry-1"), json=body)
    assert first.status_code == 201 and again.status_code == 200
    assert again.headers.get("Idempotent-Replay") == "true"
    assert again.json() == first.json()
    rows = await _rows(owner_db, "SELECT id FROM bookings WHERE slot_id = :s", s=_slot(session, 1))
    assert [r.id for r in rows] == [first.json()["bookingId"]]
    assert await _history_count(owner_db, first.json()["bookingId"]) == 1


async def test_same_key_with_a_different_request_is_refused_without_writing(client, queue, owner_db):
    _, _, session = queue
    await client.post("/agent/bookings", headers=call(key="retry-2"), json=book_body(_slot(session, 1)))
    other = await client.post("/agent/bookings", headers=call(key="retry-2"), json=book_body(_slot(session, 2)))
    assert other.status_code == 409 and other.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert await _rows(owner_db, "SELECT id FROM bookings WHERE slot_id = :s", s=_slot(session, 2)) == []


async def test_concurrent_retries_with_one_key_create_one_booking(client, queue, owner_db):
    """A dropped packet retried while the first attempt is still running (separate connections)."""
    _, _, session = queue
    body = book_body(_slot(session, 3))
    responses = await asyncio.gather(*[
        client.post("/agent/bookings", headers=call(key="retry-3"), json=body) for _ in range(6)])
    ok = [r for r in responses if r.status_code in (200, 201)]
    rows = await _rows(owner_db, "SELECT id FROM bookings WHERE customer_name = 'Asha Review'")
    assert len(rows) == 1, [r.status_code for r in responses]
    assert {r.json()["bookingId"] for r in ok} == {rows[0].id}
    assert all(r.status_code in (200, 201, 409) for r in responses)


# ---------------------------------------------------------------- concurrency on one slot


async def test_concurrent_bookings_of_one_slot_have_exactly_one_winner(client, queue, owner_db):
    built, day, session = queue
    target = _slot(session, 2)
    responses = await asyncio.gather(*[
        client.post("/agent/bookings", headers=call(caller=f"+9198123{i:05d}", call_id=f"race-{i}", key=f"race-{i}"),
                    json=book_body(target, name=f"Racer Number {i}", phone=f"98123{i:05d}"))
        for i in range(10)])
    codes = sorted(r.status_code for r in responses)
    assert codes.count(201) == 1 and codes.count(409) == 9, codes
    for lost in (r for r in responses if r.status_code == 409):
        err = lost.json()["error"]
        assert err["code"] == "SLOT_UNAVAILABLE"
        assert target not in {s["slotId"] for s in err["currentSlots"]}
    live = await _rows(owner_db, "SELECT id FROM bookings WHERE slot_id = :s AND status IN "
                                 "('BOOKED','CONFIRMED_BY_DESK','RESCHEDULED','ARRIVED')", s=target)
    assert len(live) == 1
    (now,) = [s for s in await _desk_view(client, built.resource_id, day) if s["status"] != "CANCELLED"]
    assert now["capacity"]["booked"] == 1
    assert target not in {s["slotId"] for s in now["slots"] if s["available"]}


async def _desk_view(client, resource_id, day):
    r = await client.get("/availability", headers=STAFF, params={"resourceId": resource_id, "from": day.isoformat(),
                                                                  "to": day.isoformat()})
    return r.json()["items"]


# ---------------------------------------------------------------- reschedule


async def test_failed_reschedule_leaves_both_bookings_exactly_as_they_were(client, queue, owner_db):
    _, _, session = queue
    mine = (await client.post("/agent/bookings", headers=call(key="m1"), json=book_body(_slot(session, 1)))).json()
    theirs = (await client.post("/agent/bookings", headers=call(caller="+919812300099", call_id="c2", key="t1"),
                                json=book_body(_slot(session, 2), name="Other Patient", phone="9812300099"))).json()
    before = (await _booking(owner_db, mine["bookingId"]), await _booking(owner_db, theirs["bookingId"]))
    history_before = await _history_count(owner_db, mine["bookingId"])

    r = await client.post(f"/agent/bookings/{mine['bookingId']}/reschedule", headers=call(key="mv1"),
                          json={"customerName": "Asha Review", "newSlotId": _slot(session, 2)})
    assert r.status_code == 409 and r.json()["error"]["code"] == "SLOT_UNAVAILABLE"
    after = (await _booking(owner_db, mine["bookingId"]), await _booking(owner_db, theirs["bookingId"]))
    assert after == before
    assert await _history_count(owner_db, mine["bookingId"]) == history_before


async def test_successful_reschedule_releases_the_old_slot(client, queue, owner_db):
    built, day, session = queue
    mine = (await client.post("/agent/bookings", headers=call(key="m2"), json=book_body(_slot(session, 1)))).json()
    r = await client.post(f"/agent/bookings/{mine['bookingId']}/reschedule", headers=call(key="mv2"),
                          json={"customerName": "Asha Review", "newSlotId": _slot(session, 5)})
    assert r.status_code == 200, r.text
    assert r.json()["previousSlot"]["slotId"] == _slot(session, 1)
    assert r.json()["slot"]["slotId"] == _slot(session, 5)
    (now,) = [s for s in await _desk_view(client, built.resource_id, day) if s["status"] != "CANCELLED"]
    free = {s["slotId"] for s in now["slots"] if s["available"]}
    assert _slot(session, 1) in free and _slot(session, 5) not in free
    assert now["capacity"]["booked"] == 1


# ---------------------------------------------------------------- identity and neutral not-found


async def test_every_identity_failure_is_the_same_response_as_a_missing_booking(client, queue, owner_db):
    """RULE: any mismatch returns the same neutral 404 as a non-existent booking."""
    _, _, session = queue
    mine = (await client.post("/agent/bookings", headers=call(key="m3"), json=book_body(_slot(session, 1)))).json()
    before = await _booking(owner_db, mine["bookingId"])
    attempts = {
        "missing booking": ("bkg_000000000000", call(key="n1"), "Asha Review"),
        "wrong name": (mine["bookingId"], call(key="n2"), "Someone Else"),
        "other caller": (mine["bookingId"], call(caller="+919800000777", key="n3"), "Asha Review"),
        "withheld caller": (mine["bookingId"], call(caller=None, key="n4"), "Asha Review"),
    }
    seen = {}
    for label, (booking_id, headers, name) in attempts.items():
        r = await client.post(f"/agent/bookings/{booking_id}/cancel", headers=headers, json={"customerName": name})
        seen[label] = (r.status_code, r.json(), r.headers.get("content-type"))
    assert len({repr(v) for v in seen.values()}) == 1, seen
    assert seen["missing booking"][0] == 404
    assert await _booking(owner_db, mine["bookingId"]) == before


async def test_reschedule_identity_failures_are_neutral_too(client, queue, owner_db):
    _, _, session = queue
    mine = (await client.post("/agent/bookings", headers=call(key="m4"), json=book_body(_slot(session, 1)))).json()
    before = await _booking(owner_db, mine["bookingId"])
    bodies = set()
    for booking_id, headers, name in (("bkg_000000000000", call(key="r1"), "Asha Review"),
                                      (mine["bookingId"], call(key="r2"), "Someone Else"),
                                      (mine["bookingId"], call(caller="+919800000777", key="r3"), "Asha Review")):
        r = await client.post(f"/agent/bookings/{booking_id}/reschedule", headers=headers,
                              json={"customerName": name, "newSlotId": _slot(session, 4)})
        bodies.add((r.status_code, r.text))
    assert len(bodies) == 1 and next(iter(bodies))[0] == 404, bodies
    assert await _booking(owner_db, mine["bookingId"]) == before


async def test_contact_phone_or_booked_from_number_can_cancel(client, queue, owner_db):
    """The booking is reachable from the number it was made from AND from its contact phone."""
    _, _, session = queue
    child = (await client.post("/agent/bookings", headers=call(caller="+919812300050", key="p1"),
                               json=book_body(_slot(session, 1), name="Little Ravi", phone="9812300060"))).json()
    by_contact = await client.post(f"/agent/bookings/{child['bookingId']}/cancel",
                                   headers=call(caller="+919812300060", key="p2"), json={"customerName": "little ravi"})
    assert by_contact.status_code == 200 and by_contact.json()["outcome"] == "CANCELLED"
    again = await client.post(f"/agent/bookings/{child['bookingId']}/cancel",
                              headers=call(caller="+919812300050", key="p3"), json={"customerName": "Little Ravi"})
    assert again.status_code == 200 and again.json()["outcome"] == "ALREADY_CANCELLED"
    assert (await _booking(owner_db, child["bookingId"])).status == "CANCELLED_BY_CUSTOMER"


async def test_two_customers_on_one_number_need_a_name_and_nothing_leaks(client, queue):
    _, _, session = queue
    for i, name in enumerate(("Kavya Menon", "Arun Menon")):
        r = await client.post("/agent/bookings", headers=call(key=f"fam-{i}"),
                              json=book_body(_slot(session, i + 1), name=name))
        assert r.status_code == 201
    r = await client.get("/agent/bookings", headers=call())
    body = r.json()
    assert body["outcome"] == "NAME_REQUIRED" and body["items"] == [] and body["customersOnNumber"] == 2
    assert "Kavya" not in r.text and "Arun" not in r.text
    named = (await client.get("/agent/bookings", headers=call(), params={"customerName": "kavya menon"})).json()
    assert [i["customer"]["name"] for i in named["items"]] == ["Kavya Menon"]


async def test_different_number_and_withheld_number_callers(client, queue):
    _, _, session = queue
    await client.post("/agent/bookings", headers=call(key="dn-1"), json=book_body(_slot(session, 1)))
    stranger = (await client.get("/agent/bookings", headers=call(caller="+919800000777"),
                                 params={"customerName": "Asha Review"})).json()
    assert stranger["outcome"] == "NONE_FOUND" and stranger["items"] == []
    withheld = (await client.get("/agent/bookings", headers=call(caller=None))).json()
    assert withheld["outcome"] == "IDENTITY_UNAVAILABLE" and withheld["identityBasis"] == "NONE"
    spoken = (await client.get("/agent/bookings", headers=call(caller=None),
                               params={"phone": "9812300001", "customerName": "Asha Review"})).json()
    assert spoken["outcome"] == "FOUND" and spoken["identityBasis"] == "SPOKEN_NUMBER"
    spoken_no_name = (await client.get("/agent/bookings", headers=call(caller=None),
                                       params={"phone": "9812300001"})).json()
    assert spoken_no_name == {"outcome": "NAME_REQUIRED", "items": [], "customersOnNumber": 0,
                              "identityBasis": "SPOKEN_NUMBER"}


async def test_identity_in_the_body_never_overrides_the_trusted_header(client, queue, owner_db):
    _, _, session = queue
    body = {**book_body(_slot(session, 1)), "callerNumber": "+919800000777", "X-Caller-Number": "+919800000777",
            "callId": "forged"}
    r = await client.post("/agent/bookings", headers=call(key="forge-1"), json=body)
    assert r.status_code == 201
    row = await _booking(owner_db, r.json()["bookingId"])
    assert row.caller_number == CALLER
    (call_id,) = await _rows(owner_db, "SELECT call_id FROM bookings WHERE id = :id", id=r.json()["bookingId"])
    assert call_id.call_id == "rv-call-1"


async def test_a_stranger_cannot_learn_that_a_named_person_has_a_booking(client, desk, clock):
    """OPEN-QUESTIONS S9 claims a neutral 409 'so a stranger cannot learn of someone else's booking'.
    A stranger who knows a name and a phone number tries to book them into two sessions, one where
    the person really has a booking and one where they do not. The two answers must not reveal
    which is which."""
    built = await desk.resource(NAME, {"am": SessionSpec("09:00", "11:00", mode="PER_HOUR", value=4),
                                       "pm": SessionSpec("15:00", "17:00", mode="PER_HOUR", value=4)})
    day = clock.today + timedelta(days=1)
    am, pm = sorted((s for s in await desk.availability(built.resource_id, day)), key=lambda s: s["start"])
    victim = book_body(am["slots"][0]["slotId"], name="Meena Iyer", phone="9812300042")
    assert (await client.post("/agent/bookings", headers=call(caller="+919812300042", key="v1"),
                              json=victim)).status_code == 201

    probes = {}
    for label, session in (("has booking", am), ("no booking", pm)):
        r = await client.post("/agent/bookings", headers=call(caller="+919800000777", call_id=f"probe-{label}",
                                                               key=f"probe-{label}"),
                              json=book_body(session["slots"][1]["slotId"], name="Meena Iyer", phone="9812300042"))
        probes[label] = (r.status_code, r.json().get("error", {}).get("message"))
    assert probes["has booking"][0] == probes["no booking"][0], probes


# ---------------------------------------------------------------- confirmation and fee certainty


async def test_unconfirmed_fee_is_never_given_to_the_agent(client, desk, clock):
    built = await desk.resource(NAME, {"s1": SessionSpec("15:00", "17:00", mode="PER_HOUR", value=4)},
                                price={"amount": 800, "currency": "INR", "confirmed": False})
    day = clock.today + timedelta(days=1)
    found = (await client.post("/agent/availability-search", headers=call(), json=search_body(NAME, day))).json()
    assert [r["resource"].get("price") for r in found["results"]] == [None]
    slot = search_sessions(found)[0]["slots"][0]["slotId"]
    booked = (await client.post("/agent/bookings", headers=call(key="fee-1"), json=book_body(slot))).json()
    assert booked.get("price") is None
    listed = (await client.get("/agent/bookings", headers=call())).json()
    assert [i.get("price") for i in listed["items"]] == [None]
    staff = (await client.get(f"/resources/{built.resource_id}", headers=STAFF)).json()
    assert staff["price"] == {"amount": 800, "currency": "INR", "confirmed": False}


async def test_confirmed_fee_reaches_the_agent_as_confirmed(client, desk, clock):
    await desk.resource(NAME, {"s1": SessionSpec("15:00", "17:00", mode="PER_HOUR", value=4)},
                        price={"amount": 800, "currency": "INR", "confirmed": True})
    day = clock.today + timedelta(days=1)
    found = (await client.post("/agent/availability-search", headers=call(), json=search_body(NAME, day))).json()
    assert [r["resource"]["price"] for r in found["results"]] == [{"amount": 800, "currency": "INR", "confirmed": True}]


async def test_unsigned_resource_data_caps_every_certainty_at_expected(client, desk, clock):
    """RULE: dataConfirmed=false on the resource caps timingCertainty at EXPECTED — for the
    session (exception or board confirmation) and for what the agent hears about a booking."""
    built = await desk.resource(NAME, {"s1": SessionSpec("15:00", "17:00", mode="PER_HOUR", value=4)},
                                dataConfirmed=False)
    day = clock.today + timedelta(days=1)
    r = await desk.exception(resourceId=built.resource_id, dateFrom=day, dateTo=day, scope="SESSION",
                             templateSessionId="s1", effect="TIMING_CONFIRMED")
    assert r.status_code == 201, r.text
    found = (await client.post("/agent/availability-search", headers=call(), json=search_body(NAME, day))).json()
    (session,) = search_sessions(found)
    assert session["timingCertainty"] == "EXPECTED"
    booked = (await client.post("/agent/bookings", headers=call(key="cap-1"),
                                json=book_body(session["slots"][0]["slotId"]))).json()
    assert booked["timingCertainty"] == "EXPECTED"
    confirm = await client.post(f"/bookings/{booked['bookingId']}/confirm", headers=STAFF, json={})
    assert confirm.status_code == 200
    listed = (await client.get("/agent/bookings", headers=call())).json()
    assert [i["timingCertainty"] for i in listed["items"]] == ["EXPECTED"], (
        "desk confirmation of a booking on an unsigned resource reaches the agent as CONFIRMED")


async def test_pending_timing_reaches_the_agent_and_offers_desk_follow_up(client, desk, clock):
    built = await desk.resource(NAME, {"s1": SessionSpec("15:00", "17:00", mode="PER_HOUR", value=4)})
    day = clock.today + timedelta(days=1)
    await desk.exception(resourceId=built.resource_id, dateFrom=day, dateTo=day, scope="SESSION",
                         templateSessionId="s1", effect="TIMING_PENDING")
    found = (await client.post("/agent/availability-search", headers=call(), json=search_body(NAME, day))).json()
    (session,) = search_sessions(found)
    assert session["timingCertainty"] == "NOT_CONFIRMED"
    plain = (await client.post("/agent/bookings", headers=call(key="tp-1"),
                               json=book_body(session["slots"][0]["slotId"]))).json()
    assert plain["timingCertainty"] == "NOT_CONFIRMED" and plain["followUp"] == "NONE"
    asked = (await client.post("/agent/bookings", headers=call(key="tp-2"),
                               json=book_body(session["slots"][1]["slotId"], name="Second Person",
                                              requestTimingConfirmation=True))).json()
    assert asked["followUp"] == "DESK_WILL_CONFIRM_TIMING"


async def test_neutral_not_found_does_not_leak_through_response_headers(client, desk, clock, queue):
    """The body is identical for 'no such booking' and 'not yours'; the headers must not tell them
    apart either (Server-Timing carries the number of database queries)."""
    _, _, session = queue
    mine = (await client.post("/agent/bookings", headers=call(key="st-1"), json=book_body(_slot(session, 1)))).json()
    other = await desk.resource("Dr Octavian Brightwater", {"s1": SessionSpec("09:00", "11:00", value=4)},
                                category="cat_rv_other")
    (target,) = await desk.availability(other.resource_id, clock.today + timedelta(days=1))
    seen = {}
    for label, booking_id in (("missing", "bkg_000000000000"), ("someone else's", mine["bookingId"])):
        r = await client.post(f"/agent/bookings/{booking_id}/reschedule",
                              headers=call(caller="+919800000777", key=f"st-{label}"),
                              json={"customerName": "Asha Review", "newSlotId": target["slots"][0]["slotId"]})
        timing = r.headers.get("server-timing", "")
        seen[label] = (r.status_code, r.text, timing.split('desc="')[1].split('"')[0] if 'desc="' in timing else "")
    assert seen["missing"] == seen["someone else's"], seen
