"""Schedule changes and bookings racing each other, and withdrawing exceptions that bookings
depend on (tech-lead TL1/TL3/TL4, QA #7)."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from sqlalchemy import select

from frontdesk_api.db import tables as t

from .conftest import STAFF, book_body, call, garima_slot, next_weekday


async def statuses(app) -> dict[str, str]:
    async with app.state.sessionmaker() as session:
        return {r.id: r.status for r in (await session.scalars(select(t.Booking))).all()}


async def test_a_booking_racing_a_cancellation_never_survives_in_the_cancelled_session(client, app, app_settings):
    thursday = next_weekday(3, app_settings)
    surgery = {"resourceId": "res_garima", "dateFrom": str(thursday), "dateTo": str(thursday), "scope": "SESSION",
               "templateSessionId": "tpl_res_garima_pm", "effect": "UNAVAILABLE"}

    async def book(i: int):
        return await client.post("/agent/bookings", headers=call(caller=f"+91900000{i:04d}", call_id=f"r{i}",
                                                                 key=f"race-{i}"),
                                 json=book_body(garima_slot(thursday, i), name=f"Racer {i}", phone=f"900000{i:04d}"))

    results = await asyncio.gather(*(book(i) for i in range(1, 6)),
                                   client.post("/schedule-exceptions", headers=STAFF, json=surgery))
    assert results[-1].status_code == 201
    live = {r.json()["bookingId"] for r in results[:-1] if r.status_code == 201}
    after = await statuses(app)
    # Every booking that committed is either impacted or was made before; none is left BOOKED
    # in a session that no longer exists.
    assert all(after[b] == "NEEDS_RESCHEDULE" for b in live), {b: after[b] for b in live}
    refused = [r for r in results[:-1] if r.status_code != 201]
    assert all(r.status_code == 409 for r in refused)


async def test_identical_extra_sessions_in_parallel_create_one(client, app_settings):
    sunday = next_weekday(6, app_settings) + timedelta(days=7)
    extra = {"resourceId": "res_anil_sharma", "dateFrom": str(sunday), "dateTo": str(sunday), "scope": "TIME_RANGE",
             "effect": "EXTRA_SESSION", "newStart": "20:00", "newEnd": "21:00", "newCapacity": 4}
    results = await asyncio.gather(*(client.post("/schedule-exceptions", headers=STAFF, json=extra)
                                     for _ in range(4)))
    assert sorted(r.status_code for r in results) == [201, 409, 409, 409]


async def test_withdrawing_an_extra_session_impacts_the_bookings_made_in_it(client, app, app_settings):
    sunday = next_weekday(6, app_settings) + timedelta(days=7)
    extra = {"resourceId": "res_garima", "dateFrom": str(sunday), "dateTo": str(sunday), "scope": "TIME_RANGE",
             "effect": "EXTRA_SESSION", "newStart": "14:00", "newEnd": "15:00", "newCapacity": 4}
    exc = (await client.post("/schedule-exceptions", headers=STAFF, json=extra)).json()
    found = await client.post("/agent/availability-search", headers=call(), json={
        "utterance": "Dr Garima", "language": "en", "resourceName": "Dr Garima",
        "when": {"dateFrom": str(sunday), "dateTo": str(sunday)}})
    sessions = [s for r in found.json()["results"] for s in r["sessions"] if s["start"] == "14:00"]
    assert sessions, found.json()
    slot = sessions[0]["slots"][0]["slotId"]
    booked = await client.post("/agent/bookings", headers=call(key="extra-1"), json=book_body(slot))
    assert booked.status_code == 201

    assert (await client.delete(f"/schedule-exceptions/{exc['id']}", headers=STAFF)).status_code == 204
    assert (await statuses(app))[booked.json()["bookingId"]] == "NEEDS_RESCHEDULE"
    pending = (await client.get("/notifications", headers=STAFF)).json()["items"]
    mine = [n for n in pending if n["bookingId"] == booked.json()["bookingId"]]
    assert len(mine) == 1 and mine[0]["trigger"] == "SESSION_CANCELLED"


async def test_withdrawal_restores_the_status_the_booking_had(client, app, app_settings):
    thursday = next_weekday(3, app_settings)
    booked = await client.post("/agent/bookings", headers=call(key="conf-1"), json=book_body(garima_slot(thursday, 1)))
    booking_id = booked.json()["bookingId"]
    assert (await client.post(f"/bookings/{booking_id}/confirm", headers=STAFF, json={})).status_code == 200
    assert (await statuses(app))[booking_id] == "CONFIRMED_BY_DESK"
    exc = (await client.post("/schedule-exceptions", headers=STAFF, json={
        "resourceId": "res_garima", "dateFrom": str(thursday), "dateTo": str(thursday), "scope": "SESSION",
        "templateSessionId": "tpl_res_garima_pm", "effect": "UNAVAILABLE"})).json()
    assert (await statuses(app))[booking_id] == "NEEDS_RESCHEDULE"
    assert (await client.delete(f"/schedule-exceptions/{exc['id']}", headers=STAFF)).status_code == 204
    assert (await statuses(app))[booking_id] == "CONFIRMED_BY_DESK"
