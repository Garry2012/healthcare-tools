"""Template ⊕ exceptions ⊕ board: precedence, unbookable states, impacted customers and
notifications, through REST, with stored rows checked in PostgreSQL."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

from ..conftest import STAFF, book_body, call, search_body, search_sessions
from ..oracle import SessionSpec, expected_sequence_windows

pytestmark = pytest.mark.postgres
NAME = "Dr Zenobia Quillfeather"
PM = SessionSpec("15:00", "17:00", mode="PER_HOUR", value=4, reserve_percent=25)
LIVE = ("BOOKED", "CONFIRMED_BY_DESK", "RESCHEDULED", "ARRIVED")


async def _rows(owner_db, sql: str, **params):
    async with owner_db.connect() as conn:
        return (await conn.execute(text(sql), params)).all()


def _live(items):
    return [i for i in items if i["status"] != "CANCELLED"]


def _windows(session):
    return {s["position"]: (s["expectedWindow"]["from"], s["expectedWindow"]["to"]) for s in session["slots"]}


async def _book_positions(client, session, positions, tag="b"):
    out = []
    for p in positions:
        slot = next(s["slotId"] for s in session["slots"] if s["position"] == p)
        r = await client.post("/agent/bookings", headers=call(caller=f"+9198124{p:05d}", call_id=f"{tag}{p}",
                                                               key=f"{tag}{p}"),
                              json=book_body(slot, name=f"Queue Person {p}", phone=f"98124{p:05d}"))
        assert r.status_code == 201, r.text
        out.append(r.json()["bookingId"])
    return out


async def _notifications(client, resource_id):
    items = []
    for status in ("PENDING", "SENT", "FAILED", "ACKNOWLEDGED"):
        r = await client.get("/notifications", headers=STAFF, params={"status": status, "resourceId": resource_id})
        items += r.json()["items"]
    return items


# ---------------------------------------------------------------- precedence


async def test_exceptions_apply_in_creation_order_over_the_template(client, desk, clock):
    built = await desk.resource(NAME, {"s1": PM})
    day = clock.today + timedelta(days=2)
    base = dict(resourceId=built.resource_id, dateFrom=day, dateTo=day, scope="SESSION", templateSessionId="s1")

    assert (await desk.exception(**base, effect="TIME_CHANGE", newStart="16:00", newEnd="18:00")).status_code == 201
    (moved,) = _live(await desk.availability(built.resource_id, day))
    assert (moved["start"], moved["end"], moved["status"]) == ("16:00", "18:00", "CHANGED")
    assert _windows(moved) == expected_sequence_windows(SessionSpec("16:00", "18:00", value=4, reserve_percent=25))

    assert (await desk.exception(**base, effect="TIMING_PENDING")).status_code == 201
    assert (await desk.exception(**base, effect="TIMING_CONFIRMED")).status_code == 201
    (confirmed,) = _live(await desk.availability(built.resource_id, day))
    assert confirmed["timingCertainty"] == "CONFIRMED"

    assert (await desk.exception(**base, effect="UNAVAILABLE", reasonCategory="LEAVE")).status_code == 201
    sessions = await desk.availability(built.resource_id, day)
    assert [s["status"] for s in sessions] == ["CANCELLED"]
    assert not any(slot["available"] for s in sessions for slot in s.get("slots") or [])

    extra = await desk.exception(resourceId=built.resource_id, dateFrom=day, dateTo=day, scope="TIME_RANGE",
                                 effect="EXTRA_SESSION", newStart="16:00", newEnd="17:00", newCapacity=4)
    assert extra.status_code == 201, extra.text
    live = _live(await desk.availability(built.resource_id, day))
    assert [(s["start"], s["end"], s["status"], s.get("templateSessionId")) for s in live] == [
        ("16:00", "17:00", "CHANGED", None)]


async def test_exception_on_one_date_does_not_touch_the_next(desk, clock):
    built = await desk.resource(NAME, {"s1": PM})
    day = clock.today + timedelta(days=2)
    await desk.exception(resourceId=built.resource_id, dateFrom=day, dateTo=day, scope="WHOLE_DAY",
                         effect="UNAVAILABLE", reasonCategory="LEAVE")
    (after,) = await desk.availability(built.resource_id, day + timedelta(days=1))
    assert after["status"] == "SCHEDULED" and after["bookable"]


async def test_reason_category_and_note_never_reach_the_agent_path(client, desk, clock):
    built = await desk.resource(NAME, {"s1": PM})
    day = clock.today + timedelta(days=2)
    await desk.exception(resourceId=built.resource_id, dateFrom=day, dateTo=day, scope="WHOLE_DAY",
                         effect="UNAVAILABLE", reasonCategory="PERSONAL", note="hospitalised - do not disclose")
    r = await client.post("/agent/availability-search", headers=call(), json=search_body(NAME, day))
    assert "hospitalised" not in r.text and "PERSONAL" not in r.text
    agent_list = await client.get("/schedule-exceptions", headers=call(), params={"resourceId": built.resource_id})
    assert agent_list.status_code in (200, 403)
    if agent_list.status_code == 200:
        assert "hospitalised" not in agent_list.text and "PERSONAL" not in agent_list.text


# ---------------------------------------------------------------- unbookable states expose nothing


UNBOOKABLE = {
    "cancelled": ("exception", dict(scope="WHOLE_DAY", effect="UNAVAILABLE"), "CANCELLED"),
    "left": ("board", dict(presence="LEFT"), "LEFT_FOR_DAY"),
    "ended": ("board", dict(sessionEnded=True), "SESSION_ENDED"),
    "full": ("board", dict(capacityState="FULL"), "FULL"),
}


@pytest.mark.parametrize("how", UNBOOKABLE.values(), ids=UNBOOKABLE.keys())
async def test_unbookable_session_exposes_no_bookable_slot_anywhere(client, desk, clock, how):
    kind, fields, reason = how
    built = await desk.resource(NAME, {"s1": PM})
    clock.set(clock.now.replace(hour=14, minute=0))
    day = clock.today
    (session,) = await desk.availability(built.resource_id, day)
    if kind == "exception":
        r = await desk.exception(resourceId=built.resource_id, dateFrom=day, dateTo=day, **fields)
    else:
        r = await desk.board(built.resource_id, session["sessionId"], **fields)
    assert r.status_code in (200, 201), r.text

    (now,) = await desk.availability(built.resource_id, day)
    assert not now["bookable"] and now["notBookableReason"] == reason
    assert not [s for s in now.get("slots") or [] if s["available"]]
    found = (await client.post("/agent/availability-search", headers=call(), json=search_body(NAME, day))).json()
    assert [s for si in search_sessions(found) for s in si.get("slots") or [] if s["available"]] == []
    assert [u["reason"] for res in found["results"] for u in res["unavailable"]] == [reason]
    first = session["slots"][0]["slotId"]
    booked = await client.post("/agent/bookings", headers=call(key=f"x-{reason}"), json=book_body(first))
    assert booked.status_code == 409 and booked.json()["error"]["code"] == "SLOT_UNAVAILABLE"
    assert booked.json()["error"]["currentSlots"] == []


async def test_desk_only_resource_is_shown_but_never_bookable_by_the_agent(client, desk, clock):
    built = await desk.resource(NAME, {"s1": PM}, bookingPolicy="DESK_ONLY")
    day = clock.today + timedelta(days=1)
    found = (await client.post("/agent/availability-search", headers=call(), json=search_body(NAME, day))).json()
    assert found["routing"]["action"] == "TRANSFER_DESK"
    assert [s for si in search_sessions(found) for s in si.get("slots") or [] if s["available"]] == []
    (staff,) = await desk.availability(built.resource_id, day)
    r = await client.post("/agent/bookings", headers=call(key="do-1"), json=book_body(staff["slots"][0]["slotId"]))
    assert r.status_code == 409


# ---------------------------------------------------------------- board


async def test_late_board_shifts_windows_from_the_expected_start(desk, clock):
    built = await desk.resource(NAME, {"s1": PM})
    clock.set(clock.now.replace(hour=14, minute=30))
    (session,) = await desk.availability(built.resource_id, clock.today)
    r = await desk.board(built.resource_id, session["sessionId"], presence="ARRIVING", delayMinutes=20)
    assert r.status_code == 200, r.text
    (late,) = await desk.availability(built.resource_id, clock.today)
    assert late["presence"] == "ARRIVING" and late["expectedStart"] == "15:20" and late["delayMinutes"] == 20
    assert _windows(late) == expected_sequence_windows(PM, expected_start="15:20")


async def test_board_is_for_today_and_does_not_leak_into_tomorrow(desk, clock):
    built = await desk.resource(NAME, {"s1": PM})
    clock.set(clock.now.replace(hour=14, minute=0))
    (today,) = await desk.availability(built.resource_id, clock.today)
    assert (await desk.board(built.resource_id, today["sessionId"], presence="LEFT")).status_code == 200
    tomorrow = clock.today + timedelta(days=1)
    (next_day,) = await desk.availability(built.resource_id, tomorrow)
    assert next_day["bookable"] and next_day.get("presence") is None
    wrong_day = await desk.client.put(f"/board/{built.resource_id}", headers=STAFF, json={
        "date": tomorrow.isoformat(), "sessionId": next_day["sessionId"], "presence": "LEFT"})
    assert wrong_day.status_code == 400


async def test_board_facts_of_yesterday_expire(desk, clock):
    built = await desk.resource(NAME, {"s1": PM})
    clock.set(clock.now.replace(hour=14, minute=0))
    (today,) = await desk.availability(built.resource_id, clock.today)
    await desk.board(built.resource_id, today["sessionId"], capacityState="FULL", presence="PRESENT")
    clock.set(clock.now + timedelta(days=7))  # same weekday a week later
    (later,) = await desk.availability(built.resource_id, clock.today)
    assert later["bookable"] and later.get("presence") is None and later.get("notBookableReason") is None


# ---------------------------------------------------------------- impacted customers and notifications


async def test_cancelled_session_notifies_each_impacted_customer_exactly_once(client, desk, clock, owner_db):
    built = await desk.resource(NAME, {"s1": PM})
    day = clock.today + timedelta(days=2)
    (session,) = await desk.availability(built.resource_id, day)
    ids = await _book_positions(client, session, [1, 2, 5])

    first = await desk.exception(resourceId=built.resource_id, dateFrom=day, dateTo=day, scope="SESSION",
                                 templateSessionId="s1", effect="UNAVAILABLE", reasonCategory="OTHER_DUTY")
    assert first.status_code == 201
    assert first.json()["impact"] == {"bookingsImpacted": 3, "notificationsCreated": 3}
    again = await desk.exception(resourceId=built.resource_id, dateFrom=day, dateTo=day, scope="WHOLE_DAY",
                                 effect="UNAVAILABLE", reasonCategory="LEAVE")
    assert again.status_code == 201 and again.json()["impact"]["notificationsCreated"] == 0

    notes = await _notifications(client, built.resource_id)
    assert sorted(n["bookingId"] for n in notes) == sorted(ids)
    assert {n["trigger"] for n in notes} == {"SESSION_CANCELLED"}
    statuses = await _rows(owner_db, "SELECT status FROM bookings WHERE id = ANY(:ids)", ids=ids)
    assert {r.status for r in statuses} == {"NEEDS_RESCHEDULE"}
    impact = (await client.get(f"/schedule-exceptions/{first.json()['id']}/impact", headers=STAFF)).json()
    assert sorted(i["booking"]["id"] for i in impact["items"]) == sorted(ids)
    for n in notes:
        assert n["facts"]["previousSession"]["sessionId"] == session["sessionId"]
        assert n["facts"]["currentSession"] is None
        for suggestion in n["facts"]["suggestedSlots"]:
            assert suggestion["date"] != day.isoformat()


async def test_identical_time_change_twice_notifies_once(client, desk, clock):
    built = await desk.resource(NAME, {"s1": PM})
    day = clock.today + timedelta(days=2)
    (session,) = await desk.availability(built.resource_id, day)
    await _book_positions(client, session, [1])
    change = dict(resourceId=built.resource_id, dateFrom=day, dateTo=day, scope="SESSION", templateSessionId="s1",
                  effect="TIME_CHANGE", newStart="15:30", newEnd="17:30")
    assert (await desk.exception(**change)).json()["impact"]["notificationsCreated"] == 1
    assert (await desk.exception(**change)).json()["impact"]["notificationsCreated"] == 0
    assert len(await _notifications(client, built.resource_id)) == 1


async def test_withdrawn_cancellation_restores_bookings_and_takes_back_untold_notices(client, desk, clock, owner_db):
    built = await desk.resource(NAME, {"s1": PM})
    day = clock.today + timedelta(days=2)
    (session,) = await desk.availability(built.resource_id, day)
    ids = await _book_positions(client, session, [1, 2])
    exc = (await desk.exception(resourceId=built.resource_id, dateFrom=day, dateTo=day, scope="SESSION",
                                templateSessionId="s1", effect="UNAVAILABLE")).json()
    r = await client.delete(f"/schedule-exceptions/{exc['id']}", headers=STAFF)
    assert r.status_code == 204
    rows = await _rows(owner_db, "SELECT status FROM bookings WHERE id = ANY(:ids)", ids=ids)
    assert {x.status for x in rows} == {"BOOKED"}
    assert await _notifications(client, built.resource_id) == []
    (now,) = await desk.availability(built.resource_id, day)
    assert now["capacity"]["booked"] == 2


async def test_shorter_queue_moves_people_forward_before_bumping_anyone(client, desk, clock, owner_db):
    """RULE: when a SEQUENCE session only gets shorter, bookings whose position no longer exists
    first move, earliest first, to a free position; only those left over become NEEDS_RESCHEDULE."""
    spec = SessionSpec("15:00", "17:00", mode="FIXED", value=12)
    built = await desk.resource(NAME, {"s1": spec})
    day = clock.today + timedelta(days=2)
    (session,) = await desk.availability(built.resource_id, day)
    ids = dict(zip([2, 9, 10, 11, 12], await _book_positions(client, session, [2, 9, 10, 11, 12]), strict=True))
    r = await desk.exception(resourceId=built.resource_id, dateFrom=day, dateTo=day, scope="SESSION",
                             templateSessionId="s1", effect="CAPACITY_CHANGE", newCapacity=4)
    assert r.status_code == 201, r.text
    rows = {x.id: (x.status, x.slot_id) for x in await _rows(
        owner_db, "SELECT id, status, slot_id FROM bookings WHERE id = ANY(:ids)", ids=list(ids.values()))}
    positions = {p: (rows[i][0], int(rows[i][1].rsplit("_", 1)[1])) for p, i in ids.items()}
    assert positions[2] == ("BOOKED", 2)
    assert {positions[9], positions[10], positions[11]} == {("BOOKED", 1), ("BOOKED", 3), ("BOOKED", 4)}
    assert positions[9][1] < positions[10][1] < positions[11][1], "earliest in the queue must move first"
    assert positions[12][0] == "NEEDS_RESCHEDULE"
    notes = {n["bookingId"]: n for n in await _notifications(client, built.resource_id)}
    assert set(notes) == {ids[9], ids[10], ids[11], ids[12]}
    for p in (9, 10, 11):
        assert notes[ids[p]]["trigger"] == "SESSION_TIME_CHANGED"
        assert notes[ids[p]]["facts"]["previousSlotId"].endswith(f"_{p:02d}")
    live = await _rows(owner_db, "SELECT count(*) AS n FROM bookings WHERE session_id = :s AND status = ANY(:l)",
                       s=session["sessionId"], l=list(LIVE))
    (now,) = await desk.availability(built.resource_id, day)
    assert now["capacity"]["booked"] == live[0].n == 4


async def test_template_change_impacts_only_bookings_from_its_effective_date(client, desk, clock, owner_db):
    built = await desk.resource(NAME, {"s1": PM})
    near, far = clock.today + timedelta(days=1), clock.today + timedelta(days=8)
    (near_s,) = await desk.availability(built.resource_id, near)
    (far_s,) = await desk.availability(built.resource_id, far)
    kept = (await _book_positions(client, near_s, [1], tag="n"))[0]
    hit = (await _book_positions(client, far_s, [1], tag="f"))[0]
    # From Monday 28 Sep the doctor no longer sits on Thursdays; both bookings are on Thursdays.
    no_thursday = ["MON", "TUE", "WED", "FRI", "SAT", "SUN"]
    await desk.template(built.resource_id, {"s1": PM}, days=no_thursday,
                        effective_from=clock.today + timedelta(days=5))
    rows = {x.id: x.status for x in await _rows(owner_db, "SELECT id, status FROM bookings WHERE id = ANY(:ids)",
                                                ids=[kept, hit])}
    assert rows == {kept: "BOOKED", hit: "NEEDS_RESCHEDULE"}
    notes = await _notifications(client, built.resource_id)
    assert [(n["bookingId"], n["trigger"]) for n in notes] == [(hit, "TEMPLATE_CHANGED")]


@pytest.mark.xfail(strict=True, reason="SPEC AMBIGUITY A-03: a capacity increase moves booked customers' expected "
                                       "windows earlier without telling them; the contract does not say whether "
                                       "that is a change customers must hear about")
async def test_capacity_increase_does_not_silently_move_a_booked_window_earlier(client, desk, clock):
    spec = SessionSpec("15:00", "17:00", mode="FIXED", value=12)
    built = await desk.resource(NAME, {"s1": spec})
    day = clock.today + timedelta(days=2)
    (session,) = await desk.availability(built.resource_id, day)
    await _book_positions(client, session, [6])
    told = _windows(session)[6]
    r = await desk.exception(resourceId=built.resource_id, dateFrom=day, dateTo=day, scope="SESSION",
                             templateSessionId="s1", effect="CAPACITY_CHANGE", newCapacity=24)
    assert r.status_code == 201
    (now,) = await desk.availability(built.resource_id, day)
    moved_to = _windows(now)[6]
    notified = await _notifications(client, built.resource_id)
    assert moved_to[0] >= told[0] or notified, f"told {told}, now {moved_to}, no notification"
