"""TIMED grids, same-day reachability, capacity changes and the booking horizon, through REST.

Expected values come from the contract (tests/review/oracle.py and the quoted RULE text), not from
the service's helpers.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

from ..conftest import STAFF, book_body, call, search_body, search_sessions
from ..oracle import SessionSpec, expected_timed_grid, minutes_of

pytestmark = pytest.mark.postgres
NAME = "Dr Zenobia Quillfeather"


def _live(items: list[dict]) -> list[dict]:
    return [i for i in items if i["status"] != "CANCELLED"]


def _available(session: dict) -> list[dict]:
    return [s for s in session.get("slots") or [] if s["available"]]


async def _book(client, slot_id: str, i: int) -> dict:
    r = await client.post("/agent/bookings", headers=call(key=f"bk-{i}", call_id=f"bk-call-{i}"),
                          json=book_body(slot_id, name=f"Patient Number {i}", phone=f"98123{i:05d}"))
    assert r.status_code == 201, r.text
    return r.json()


async def _statuses(owner_db, booking_ids: list[str]) -> dict[str, tuple[str, str]]:
    async with owner_db.connect() as conn:
        rows = (await conn.execute(text("SELECT id, status, slot_id FROM bookings WHERE id = ANY(:ids)"),
                                   {"ids": booking_ids})).all()
    return {r.id: (r.status, r.slot_id) for r in rows}


# ---------------------------------------------------------------- TIMED


@pytest.mark.parametrize("spec", [
    SessionSpec("10:00", "13:00", model="TIMED", mode="FIXED", value=6, slot_minutes=15),
    SessionSpec("10:00", "12:00", model="TIMED", mode="PER_HOUR", value=2, slot_minutes=15),
    SessionSpec("14:00", "18:00", model="TIMED", mode="FIXED", value=4, slot_minutes=30),
], ids=["fixed6-of-12-quarter-hours", "2-per-hour-of-8-quarter-hours", "fixed4-of-8-half-hours"])
async def test_timed_session_offers_times_across_the_whole_session(desk, clock, spec):
    """RULE (IMPLEMENTATION §2.2): TIMED slots = start..end step slotMinutes. Capacity limits how
    many can be booked, not which times exist. A capacity below the grid must not make the second
    half of the clinic unbookable before anyone has booked."""
    built = await desk.resource(NAME, {"t1": spec})
    day = clock.today + timedelta(days=1)
    (session,) = _live(await desk.availability(built.resource_id, day))
    offered = [(s["start"], s["end"]) for s in session["slots"]]
    grid = expected_timed_grid(spec)
    assert session["capacity"]["remaining"] == session["capacity"]["total"] < len(grid)
    assert offered == grid, f"offered {offered[0]}..{offered[-1]}, session runs {spec.start}-{spec.end}"


async def test_timed_clinic_with_spare_capacity_is_bookable_later_in_the_day(client, desk, clock):
    """Same shape, today at 11:30, nothing booked: 6 bookings allowed, 0 made, clinic open to 13:00.
    The agent must be able to offer a time from 11:30 on; it must not hear FULL / nothing."""
    spec = SessionSpec("10:00", "13:00", model="TIMED", mode="FIXED", value=6, slot_minutes=15)
    await desk.resource(NAME, {"t1": spec})
    clock.set(clock.now.replace(hour=11, minute=30))
    r = await client.post("/agent/availability-search", headers=call(), json=search_body(NAME, clock.today))
    body = r.json()
    offered = [s["start"] for si in search_sessions(body) for s in _available(si)]
    reasons = [u["reason"] for res in body["results"] for u in res["unavailable"]]
    assert body["outcome"] == "FOUND", (body["outcome"], reasons)
    assert offered and min(offered) >= "11:30"


# ---------------------------------------------------------------- same day: session-level facts


async def test_same_day_session_level_facts_agree_with_its_slots(desk, clock):
    """RULE (§2.2): bookable=false when remaining == 0. Today at 16:35, no one booked, arrive-by
    16:45: the service may withhold closed positions (S8), but then bookable/remaining/reason must
    say the same thing as the slots, and the reason must not claim FULL when nobody booked."""
    spec = SessionSpec("15:00", "17:00", mode="PER_HOUR", value=4, reserve_percent=25)
    built = await desk.resource(NAME, {"s1": spec})
    clock.set(clock.now.replace(hour=16, minute=35))
    (session,) = _live(await desk.availability(built.resource_id, clock.today))
    available = _available(session)
    assert session["capacity"]["booked"] == 0
    assert session["bookable"] == bool(available), (
        f"bookable={session['bookable']} remaining={session['capacity']['remaining']} "
        f"available slots={len(available)}")
    assert session["capacity"]["remaining"] == len(available)


async def test_same_day_search_never_reports_full_for_an_empty_session(client, desk, clock):
    spec = SessionSpec("15:00", "17:00", mode="PER_HOUR", value=4, reserve_percent=25)
    await desk.resource(NAME, {"s1": spec})
    clock.set(clock.now.replace(hour=16, minute=35))
    r = await client.post("/agent/availability-search", headers=call(), json=search_body(NAME, clock.today))
    body = r.json()
    reasons = [u["reason"] for res in body["results"] for u in res["unavailable"] if u.get("sessionId")]
    assert "FULL" not in reasons, f"nobody is booked, yet the agent is told {reasons}"


# ---------------------------------------------------------------- capacity changes


async def test_raising_capacity_never_cancels_existing_bookings(client, desk, clock, owner_db):
    """RULE (createScheduleException): only an exception that *removes or shortens* a session
    moves bookings to NEEDS_RESCHEDULE. A capacity increase does neither."""
    spec = SessionSpec("15:00", "17:00", mode="FIXED", value=12)
    built = await desk.resource(NAME, {"s1": spec})
    day = clock.today + timedelta(days=1)
    (session,) = _live(await desk.availability(built.resource_id, day))
    booked = [await _book(client, s["slotId"], i) for i, s in enumerate(session["slots"][:2])]
    before = await _statuses(owner_db, [b["bookingId"] for b in booked])

    r = await desk.exception(resourceId=built.resource_id, dateFrom=day, dateTo=day, scope="SESSION",
                             templateSessionId="s1", effect="CAPACITY_CHANGE", newCapacity=150)
    after = await _statuses(owner_db, [b["bookingId"] for b in booked])
    notices = await client.get("/notifications", headers=STAFF, params={"resourceId": built.resource_id})

    assert after == before, f"capacity 12 -> 150 (HTTP {r.status_code}) changed bookings: {before} -> {after}"
    assert notices.json()["items"] == []
    if r.status_code == 201:
        (now,) = _live(await desk.availability(built.resource_id, day))
        assert now["bookable"], f"accepted, but the session is now {now['notBookableReason']}"


async def test_explicit_extra_session_capacity_is_either_refused_or_offered(client, desk, clock):
    """An EXTRA_SESSION with an explicit capacity the service cannot represent (30 people in
    20 minutes) must not be recorded as 201 and then silently never offered to callers."""
    built = await desk.resource(NAME, {"s1": SessionSpec("09:00", "10:00", mode="PER_HOUR", value=4)},
                                days=["MON"])
    day = clock.today + timedelta(days=1)  # Thursday: no template session
    r = await desk.exception(resourceId=built.resource_id, dateFrom=day, dateTo=day, scope="TIME_RANGE",
                             effect="EXTRA_SESSION", newStart="18:00", newEnd="18:20", newCapacity=30)
    if r.status_code == 400:
        return
    assert r.status_code == 201, r.text
    (session,) = _live(await desk.availability(built.resource_id, day))
    assert session["bookable"], (
        f"201 Created, yet the extra session is notBookableReason={session['notBookableReason']} "
        f"with {len(session['slots'])} slots")


# ---------------------------------------------------------------- booking horizon


async def test_search_never_offers_a_slot_that_booking_refuses(client, desk, clock, review_settings):
    """RULE (agentCreateBooking): slots more than TENANT_BOOKING_HORIZON_DAYS ahead are refused.
    The discovery call must not offer them as bookable (the agent would promise, then fail)."""
    await desk.resource(NAME, {"s1": SessionSpec("10:00", "12:00", mode="PER_HOUR", value=4)})
    far = clock.today + timedelta(days=review_settings.tenant_booking_horizon_days + 20)
    r = await client.post("/agent/availability-search", headers=call(), json=search_body(NAME, far))
    body = r.json()
    offered = [s["slotId"] for si in search_sessions(body) for s in _available(si)]
    if not offered:
        return
    booked = await client.post("/agent/bookings", headers=call(key="far"), json=book_body(offered[0]))
    assert booked.status_code in (200, 201), (
        f"search offered {offered[0]} as available (outcome {body['outcome']}); booking it -> "
        f"{booked.status_code} {booked.json()['error']['message']}")


async def test_reschedule_applies_the_same_horizon_as_booking(client, desk, clock, review_settings, owner_db):
    built = await desk.resource(NAME, {"s1": SessionSpec("10:00", "12:00", mode="PER_HOUR", value=4)})
    day = clock.today + timedelta(days=1)
    far = clock.today + timedelta(days=review_settings.tenant_booking_horizon_days + 20)
    (near,) = _live(await desk.availability(built.resource_id, day))
    (distant,) = _live(await desk.availability(built.resource_id, far))
    booking = await _book(client, near["slots"][0]["slotId"], 1)

    direct = await client.post("/agent/bookings", headers=call(key="direct-far"),
                               json=book_body(distant["slots"][0]["slotId"], name="Other Person"))
    assert direct.status_code == 400  # the rule, as the service applies it to BOOK

    moved = await client.post(f"/agent/bookings/{booking['bookingId']}/reschedule",
                              headers=call(caller="+919812300001", key="move-far", call_id="bk-call-1"),
                              json={"customerName": "Patient Number 1", "newSlotId": distant["slots"][0]["slotId"]})
    after = await _statuses(owner_db, [booking["bookingId"]])
    assert moved.status_code == 400, (
        f"BOOK of that slot is 400, RESCHEDULE to it is {moved.status_code}; booking now {after}")


async def test_arrive_by_is_the_earlier_of_offset_and_desk_last_arrival(desk, clock):
    """RULE: arriveBy = min(lastArrivalTime from board, end − lastArrivalOffset)."""
    spec = SessionSpec("15:00", "17:00", mode="PER_HOUR", value=4, last_arrival_offset=30)
    built = await desk.resource(NAME, {"s1": spec})
    clock.set(clock.now.replace(hour=14, minute=0))
    (session,) = _live(await desk.availability(built.resource_id, clock.today))
    assert session["arriveBy"] == "16:30"
    r = await desk.board(built.resource_id, session["sessionId"], lastArrivalTime="16:10")
    assert r.status_code == 200, r.text
    (session,) = _live(await desk.availability(built.resource_id, clock.today))
    assert session["arriveBy"] == "16:10"
    r = await desk.board(built.resource_id, session["sessionId"], lastArrivalTime="16:50")
    (session,) = _live(await desk.availability(built.resource_id, clock.today))
    assert session["arriveBy"] == "16:30"
    clock.set(clock.now.replace(hour=16, minute=31))
    (session,) = _live(await desk.availability(built.resource_id, clock.today))
    assert not session["bookable"] and session["notBookableReason"] == "ARRIVE_BY_PASSED"
    assert _available(session) == []
    assert minutes_of(session["arriveBy"]) < minutes_of("16:31")
