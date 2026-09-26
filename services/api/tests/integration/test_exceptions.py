"""Exceptions move impacted bookings to NEEDS_RESCHEDULE and queue notifications;
withdrawing the exception restores them."""

from __future__ import annotations

from sqlalchemy import select

from frontdesk_api.db import tables as t

from .conftest import STAFF, book_body, call, garima_slot, next_weekday


async def _book_three(client, day):
    ids = []
    for i in range(1, 4):
        r = await client.post("/agent/bookings",
                              headers=call(caller=f"+91900000{i:04d}", call_id=f"c{i}", key=f"k{i}"),
                              json=book_body(garima_slot(day, i), name=f"Customer {i}", phone=f"900000{i:04d}"))
        assert r.status_code == 201
        ids.append(r.json()["bookingId"])
    return ids


def _surgery(day):
    return {"resourceId": "res_garima", "dateFrom": str(day), "dateTo": str(day), "scope": "SESSION",
            "templateSessionId": "tpl_res_garima_pm", "effect": "UNAVAILABLE", "reasonCategory": "OTHER_DUTY"}


async def test_exception_impacts_and_withdrawal_restores(client, app, app_settings):
    thursday = next_weekday(3, app_settings)
    ids = await _book_three(client, thursday)

    created = await client.post("/schedule-exceptions", headers=STAFF, json=_surgery(thursday))
    assert created.status_code == 201
    exc = created.json()
    assert exc["impact"] == {"bookingsImpacted": 3, "notificationsCreated": 3}

    async with app.state.sessionmaker() as session:
        statuses = {r.id: r.status for r in (await session.scalars(select(t.Booking))).all()}
    assert {statuses[i] for i in ids} == {"NEEDS_RESCHEDULE"}

    pending = (await client.get("/notifications", headers=STAFF)).json()["items"]
    assert len(pending) == 3 and {n["trigger"] for n in pending} == {"SESSION_CANCELLED"}
    facts = pending[0]["facts"]
    assert facts["resourceName"] == "Dr. Garima" and facts["currentSession"] is None
    assert facts["previousSession"]["start"] == "15:00" and facts["suggestedSlots"]

    impact = (await client.get(f"/schedule-exceptions/{exc['id']}/impact", headers=STAFF)).json()
    assert sorted(i["booking"]["id"] for i in impact["items"]) == sorted(ids)

    # the session is gone from availability
    avail = (await client.get("/availability", headers=STAFF,
                              params={"resourceId": "res_garima", "from": str(thursday), "to": str(thursday)})).json()
    pm = next(s for s in avail["items"] if s["sessionId"].endswith("_2"))
    assert pm["status"] == "CANCELLED" and pm["bookable"] is False

    # the caller hears it on lookup
    lookup = (await client.get("/agent/bookings", headers=call(caller="+919000000001"))).json()
    assert lookup["items"][0]["status"] == "NEEDS_RESCHEDULE"

    deleted = await client.delete(f"/schedule-exceptions/{exc['id']}", headers=STAFF)
    assert deleted.status_code == 204
    async with app.state.sessionmaker() as session:
        statuses = {r.id: r.status for r in (await session.scalars(select(t.Booking))).all()}
        leftover = (await session.scalars(select(t.Notification))).all()
    assert {statuses[i] for i in ids} == {"BOOKED"}
    assert leftover == []  # never delivered, so nothing to take back


async def test_withdrawal_after_delivery_sends_a_follow_up(client, app, app_settings):
    thursday = next_weekday(3, app_settings)
    [first, *_] = await _book_three(client, thursday)
    exc = (await client.post("/schedule-exceptions", headers=STAFF, json=_surgery(thursday))).json()
    note = next(n for n in (await client.get("/notifications", headers=STAFF)).json()["items"]
                if n["bookingId"] == first)
    delivered = await client.post(f"/notifications/{note['id']}/delivered", headers=STAFF,
                                  json={"channel": "PHONE", "outcome": "INFORMED"})
    assert delivered.status_code == 200 and delivered.json()["status"] == "ACKNOWLEDGED"

    await client.delete(f"/schedule-exceptions/{exc['id']}", headers=STAFF)
    follow_ups = (await client.get("/notifications", headers=STAFF)).json()["items"]
    assert [(n["bookingId"], n["trigger"], n["facts"]["change"]) for n in follow_ups] == [
        (first, "DESK_MESSAGE", "SESSION_RESTORED")
    ]


async def test_shortening_a_session_only_impacts_what_no_longer_fits(client, app, app_settings):
    thursday = next_weekday(3, app_settings)
    ids = await _book_three(client, thursday)  # positions 1..3 of 6 offered
    r = await client.post("/schedule-exceptions", headers=STAFF, json={
        "resourceId": "res_garima", "dateFrom": str(thursday), "dateTo": str(thursday), "scope": "SESSION",
        "templateSessionId": "tpl_res_garima_pm", "effect": "CAPACITY_CHANGE", "newCapacity": 3})
    # capacity 3, 25 % walk-in reserve → 2 phone positions: position 3 no longer exists
    assert r.json()["impact"] == {"bookingsImpacted": 1, "notificationsCreated": 1}
    async with app.state.sessionmaker() as session:
        statuses = [(await session.get(t.Booking, i)).status for i in ids]
    assert statuses == ["BOOKED", "BOOKED", "NEEDS_RESCHEDULE"]
    [note] = (await client.get("/notifications", headers=STAFF)).json()["items"]
    # the session keeps its hours: the desk must not tell the customer the time changed
    assert note["facts"]["reason"] == "CAPACITY_REDUCED"


async def test_exception_validation(client, app_settings):
    thursday = next_weekday(3, app_settings)
    bad = [
        {**_surgery(thursday), "templateSessionId": "tpl_nope"},
        {**_surgery(thursday), "dateTo": "2000-01-01"},
        {**_surgery(thursday), "effect": "TIME_CHANGE"},
        {**_surgery(thursday), "scope": "TIME_RANGE", "templateSessionId": None},
    ]
    for body in bad:
        r = await client.post("/schedule-exceptions", headers=STAFF, json=body)
        assert r.status_code == 400, body
    overlap = {"resourceId": "res_garima", "dateFrom": str(thursday), "dateTo": str(thursday),
               "scope": "TIME_RANGE", "effect": "EXTRA_SESSION", "newStart": "16:00", "newEnd": "18:00"}
    assert (await client.post("/schedule-exceptions", headers=STAFF, json=overlap)).status_code == 409


async def test_capacity_cut_moves_queue_bookings_into_free_positions(client, app, app_settings):
    """Positions 1-2 are free, 3-5 booked. Cutting to 2 phone positions keeps the two earliest
    in the queue by moving them forward (and telling them); only the last one is bumped."""
    thursday = next_weekday(3, app_settings)
    ids = []
    for i in (3, 4, 5):
        r = await client.post("/agent/bookings",
                              headers=call(caller=f"+91900000{i:04d}", call_id=f"c{i}", key=f"k{i}"),
                              json=book_body(garima_slot(thursday, i), name=f"Customer {i}", phone=f"900000{i:04d}"))
        assert r.status_code == 201
        ids.append(r.json()["bookingId"])
    r = await client.post("/schedule-exceptions", headers=STAFF, json={
        "resourceId": "res_garima", "dateFrom": str(thursday), "dateTo": str(thursday), "scope": "SESSION",
        "templateSessionId": "tpl_res_garima_pm", "effect": "CAPACITY_CHANGE", "newCapacity": 3})
    assert r.status_code == 201
    assert r.json()["impact"] == {"bookingsImpacted": 1, "notificationsCreated": 3}
    async with app.state.sessionmaker() as session:
        rows = [await session.get(t.Booking, i) for i in ids]
        history = (await session.scalars(select(t.BookingHistory).where(
            t.BookingHistory.booking_id == ids[0], t.BookingHistory.change == "SLOT_MOVED"))).all()
    assert [(b.status, b.slot_id) for b in rows] == [
        ("BOOKED", garima_slot(thursday, 1)),
        ("BOOKED", garima_slot(thursday, 2)),
        ("NEEDS_RESCHEDULE", garima_slot(thursday, 5)),
    ]
    assert history and history[0].details["previousSlotId"] == garima_slot(thursday, 3)

    notes = {n["bookingId"]: n for n in (await client.get("/notifications", headers=STAFF)).json()["items"]}
    moved = notes[ids[0]]
    assert moved["trigger"] == "SESSION_TIME_CHANGED"
    assert moved["facts"]["previousSlotId"] == garima_slot(thursday, 3)
    assert moved["facts"]["slotId"] == garima_slot(thursday, 1) and moved["facts"]["suggestedSlots"] == []
    assert notes[ids[2]]["facts"]["bookingStatus"] == "NEEDS_RESCHEDULE"
    assert "previousSlotId" not in notes[ids[2]]["facts"]

    # the moved caller hears the new position on lookup, and the freed slot 3 stays unoffered
    lookup = (await client.get("/agent/bookings", headers=call(caller="+919000000003"))).json()
    assert lookup["items"][0]["status"] == "BOOKED"
