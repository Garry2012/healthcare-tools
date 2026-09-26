"""Booking under contention, atomic reschedule, idempotency (IMPLEMENTATION.md §2.5)."""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from frontdesk_api.db import tables as t

from .conftest import STAFF, book_body, call, garima_slot, next_weekday


async def test_twenty_five_callers_one_slot(client, app_settings):
    monday = next_weekday(0, app_settings)
    slot = garima_slot(monday, 1)

    async def attempt(i: int):
        return await client.post(
            "/agent/appointments",
            headers=call(caller=f"+9190000{i:05d}", call_id=f"race-{i}", key=f"race-key-{i}"),
            json=book_body(slot, name=f"Patient {i}", phone=f"90000{i:05d}"),
        )

    responses = await asyncio.gather(*(attempt(i) for i in range(25)))
    codes = sorted(r.status_code for r in responses)
    assert codes.count(201) == 1 and codes.count(409) == 24
    for r in responses:
        if r.status_code == 409:
            error = r.json()["error"]
            assert error["code"] == "SLOT_UNAVAILABLE"
            assert error["currentSlots"], "every loser gets the session's current slots"
            assert slot not in {s["slotId"] for s in error["currentSlots"]}
    winner = next(r for r in responses if r.status_code == 201).json()
    assert winner["outcome"] == "BOOKED" and winner["slot"]["slotId"] == slot


async def test_booking_response_closes_the_call(client, app_settings):
    monday = next_weekday(0, app_settings)
    r = await client.post("/agent/appointments", headers=call(key="k-close"),
                          json=book_body(garima_slot(monday, 4), reasonVerbatim="knee pain"))
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "BOOKED" and body["outcome"] == "BOOKED"
    assert body["doctor"]["name"] == "Dr. Garima"
    assert body["session"] == {"sessionId": f"ses_doc_garima_{monday}_2", "label": "Afternoon",
                               "start": "15:00", "end": "17:00"}
    assert body["slot"]["expectedWindow"] == {"from": "15:45", "to": "16:05"}
    assert body["arriveBy"] == "16:45" and body["timingCertainty"] == "EXPECTED"
    assert body["fee"] == {"amount": 600.0, "currency": "INR", "confirmed": True}
    assert len(body["confirmationCode"]) == 4
    # staff-only fields never reach the agent
    assert "callerNumber" not in body and "reasonVerbatim" not in body


async def test_idempotent_replay_and_conflict(client, app_settings):
    monday = next_weekday(0, app_settings)
    body = book_body(garima_slot(monday, 2))
    first = await client.post("/agent/appointments", headers=call(key="same-key"), json=body)
    again = await client.post("/agent/appointments", headers=call(key="same-key"), json=body)
    assert first.status_code == 201 and "Idempotent-Replay" not in first.headers
    assert again.status_code == 200 and again.headers["Idempotent-Replay"] == "true"
    assert again.json() == first.json()

    other = book_body(garima_slot(monday, 3))
    clash = await client.post("/agent/appointments", headers=call(key="same-key"), json=other)
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


async def test_agent_writes_require_an_idempotency_key(client, app_settings):
    monday = next_weekday(0, app_settings)
    r = await client.post("/agent/appointments", headers=call(), json=book_body(garima_slot(monday, 2)))
    assert r.status_code == 400 and r.json()["error"]["code"] == "VALIDATION_FAILED"


async def test_same_patient_same_session_is_already_booked(client, app_settings):
    monday = next_weekday(0, app_settings)
    first = await client.post("/agent/appointments", headers=call(key="a1"), json=book_body(garima_slot(monday, 1)))
    second = await client.post("/agent/appointments", headers=call(key="a2"), json=book_body(garima_slot(monday, 2)))
    assert first.status_code == 201
    assert second.status_code == 200 and second.json()["outcome"] == "ALREADY_BOOKED"
    assert second.json()["appointmentId"] == first.json()["appointmentId"]


async def test_unknown_or_unbookable_slots(client, app_settings):
    tuesday = next_weekday(1, app_settings)  # Dr. Garima does not sit on Tuesdays
    r = await client.post("/agent/appointments", headers=call(key="u1"), json=book_body(garima_slot(tuesday, 1)))
    assert r.status_code == 409 and r.json()["error"]["code"] == "SLOT_UNAVAILABLE"
    r = await client.post("/agent/appointments", headers=call(key="u2"), json=book_body("not-a-slot"))
    assert r.status_code == 400
    monday = next_weekday(0, app_settings)
    r = await client.post("/agent/appointments", headers=call(key="u3"),
                          json=book_body(garima_slot(monday, 7)))  # beyond the phone share (6 of 8)
    assert r.status_code == 409


async def test_desk_only_doctor_cannot_be_booked_by_the_agent(client, app_settings):
    thursday = next_weekday(3, app_settings)
    r = await client.post(
        "/schedule-exceptions",
        headers=STAFF,
        json={"doctorId": "doc_vikram_desai", "dateFrom": str(thursday), "dateTo": str(thursday),
              "scope": "TIME_RANGE", "effect": "EXTRA_SESSION", "newStart": "18:00", "newEnd": "19:00"},
    )
    assert r.status_code == 201
    slot = f"slot_ses_doc_vikram_desai_{thursday}_e1_01"  # identities restart per test
    r = await client.post("/agent/appointments", headers=call(key="d1"), json=book_body(slot))
    assert r.status_code == 409 and r.json()["error"]["currentSlots"] == []
    desk = await client.post("/appointments", headers=STAFF, json=book_body(slot))
    assert desk.status_code == 201 and desk.json()["createdVia"] == "DESK"


async def test_reschedule_releases_old_and_holds_new(client, app, app_settings):
    monday = next_weekday(0, app_settings)
    booked = (await client.post("/agent/appointments", headers=call(key="r1"),
                                json=book_body(garima_slot(monday, 1)))).json()
    moved = await client.post(
        f"/agent/appointments/{booked['appointmentId']}/reschedule",
        headers=call(key="r2"),
        json={"patientName": "Lakshmi Rao", "newSlotId": garima_slot(monday, 5)},
    )
    assert moved.status_code == 200
    body = moved.json()
    assert body["outcome"] == "RESCHEDULED" and body["status"] == "RESCHEDULED"
    assert body["slot"]["slotId"] == garima_slot(monday, 5)
    assert body["previousSlot"]["slotId"] == garima_slot(monday, 1)
    # the old slot is free again: someone else can take it
    other = await client.post("/agent/appointments", headers=call(caller="+919000000999", key="r3"),
                              json=book_body(garima_slot(monday, 1), name="Someone Else", phone="9000000999"))
    assert other.status_code == 201


async def test_reschedule_race_leaves_losers_on_their_original_slots(client, app, app_settings):
    monday = next_weekday(0, app_settings)
    ids = []
    for i in range(1, 6):
        r = await client.post("/agent/appointments",
                              headers=call(caller=f"+91900000{i:04d}", call_id=f"c{i}", key=f"b{i}"),
                              json=book_body(garima_slot(monday, i, n=1), name=f"Patient {i}",
                                             phone=f"900000{i:04d}"))
        assert r.status_code == 201
        ids.append((i, r.json()["appointmentId"]))
    target = garima_slot(monday, 9, n=1)

    async def move(i: int, appointment_id: str):
        return await client.post(
            f"/agent/appointments/{appointment_id}/reschedule",
            headers=call(caller=f"+91900000{i:04d}", call_id=f"c{i}", key=f"m{i}"),
            json={"patientName": f"Patient {i}", "newSlotId": target},
        )

    results = await asyncio.gather(*(move(i, a) for i, a in ids))
    assert sorted(r.status_code for r in results) == [200, 409, 409, 409, 409]
    async with app.state.sessionmaker() as session:
        rows = {r.id: r for r in (await session.scalars(select(t.Appointment))).all()}
    for (i, appointment_id), r in zip(ids, results, strict=True):
        row = rows[appointment_id]
        if r.status_code == 200:
            assert row.slot_id == target
        else:
            assert r.json()["error"]["code"] == "SLOT_UNAVAILABLE"
            assert row.slot_id == garima_slot(monday, i, n=1) and row.status == "BOOKED"


async def test_reschedule_into_a_taken_slot_changes_nothing(client, app, app_settings):
    monday = next_weekday(0, app_settings)
    mine = (await client.post("/agent/appointments", headers=call(key="x1"),
                              json=book_body(garima_slot(monday, 1)))).json()
    await client.post("/agent/appointments", headers=call(caller="+919000000888", key="x2"),
                      json=book_body(garima_slot(monday, 2), name="Other Person", phone="9000000888"))
    r = await client.post(f"/agent/appointments/{mine['appointmentId']}/reschedule", headers=call(key="x3"),
                          json={"patientName": "Lakshmi Rao", "newSlotId": garima_slot(monday, 2)})
    assert r.status_code == 409
    async with app.state.sessionmaker() as session:
        row = await session.get(t.Appointment, mine["appointmentId"])
    assert (row.slot_id, row.status) == (garima_slot(monday, 1), "BOOKED")
