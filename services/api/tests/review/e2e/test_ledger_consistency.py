"""A seeded random day at the front desk: many callers book, retry, move and cancel through the
agent API. After every step the published availability must agree with the booking records in
PostgreSQL. Deterministic (fixed seed); a failure prints the step that broke the ledger."""

from __future__ import annotations

import random
from collections import Counter
from datetime import timedelta

import pytest
from sqlalchemy import text

from ..conftest import STAFF, book_body, call
from ..oracle import SessionSpec, expected_offered

pytestmark = pytest.mark.postgres
NAME = "Dr Zenobia Quillfeather"
HOLDS = ("BOOKED", "CONFIRMED_BY_DESK", "RESCHEDULED", "ARRIVED")
SPECS = {"am": SessionSpec("09:00", "11:00", mode="PER_HOUR", value=4, reserve_percent=25),
         "pm": SessionSpec("15:00", "17:30", mode="FIXED", value=10, reserve_percent=20)}
CUSTOMERS = [(f"Ledger Person {i}", f"98125{i:05d}", f"+9198125{i:05d}") for i in range(12)]


async def _live_rows(owner_db):
    async with owner_db.connect() as conn:
        return (await conn.execute(text(
            "SELECT id, slot_id, session_id, customer_name, phone, caller_number FROM bookings "
            "WHERE status = ANY(:h)"), {"h": list(HOLDS)})).all()


async def _published(client, resource_id, days):
    out = {}
    for day in days:
        r = await client.get("/availability", headers=STAFF, params={
            "resourceId": resource_id, "from": day.isoformat(), "to": day.isoformat()})
        for s in r.json()["items"]:
            out[s["sessionId"]] = s
    return out


async def _check(client, owner_db, resource_id, days, step):
    rows = await _live_rows(owner_db)
    slots = [r.slot_id for r in rows]
    assert len(slots) == len(set(slots)), f"step {step}: two live bookings hold one slot"
    published = await _published(client, resource_id, days)
    for sid, s in published.items():
        held = {r.slot_id for r in rows if r.session_id == sid}
        key = "am" if s["start"] == "09:00" else "pm"
        booked = s["capacity"]["booked"]
        assert booked == len(held), f"step {step}: {sid} booked={booked} db={len(held)}"
        assert s["capacity"]["remaining"] == expected_offered(SPECS[key]) - len(held), f"step {step}: {sid}"
        for slot in s["slots"]:
            assert slot["available"] == (slot["slotId"] not in held), f"step {step}: {slot['slotId']}"
    return rows, published


async def test_published_availability_always_matches_the_booking_ledger(client, desk, clock, owner_db):
    rng = random.Random(20260923)
    built = await desk.resource(NAME, SPECS)
    days = [clock.today + timedelta(days=1), clock.today + timedelta(days=2)]
    sent: list[tuple[str, dict, dict]] = []
    done: Counter[str] = Counter()
    rows, published = await _check(client, owner_db, built.resource_id, days, 0)

    for step in range(1, 61):
        free = [slot["slotId"] for s in published.values() for slot in s["slots"] if slot["available"]]
        action = rng.choice(["book", "book", "book", "cancel", "move", "replay"])
        if action == "book" and free:
            name, phone, caller = rng.choice(CUSTOMERS)
            headers = call(caller=caller, call_id=f"lc-{step}", key=f"lc-{step}")
            body = book_body(rng.choice(free), name=name, phone=phone)
            r = await client.post("/agent/bookings", headers=headers, json=body)
            assert r.status_code in (200, 201, 409), (step, r.text)
            done["book"] += r.status_code == 201
            sent.append(("/agent/bookings", headers, body))
        elif action in ("cancel", "move") and rows:
            row = rng.choice(rows)
            headers = call(caller=row.caller_number, call_id=f"lc-{step}", key=f"lc-{step}")
            if action == "cancel":
                path, body = f"/agent/bookings/{row.id}/cancel", {"customerName": row.customer_name}
            elif free:
                path, body = f"/agent/bookings/{row.id}/reschedule", {"customerName": row.customer_name,
                                                                      "newSlotId": rng.choice(free)}
            else:
                continue
            r = await client.post(path, headers=headers, json=body)
            assert r.status_code in (200, 409), (step, action, r.text)
            done[action] += r.status_code == 200
            sent.append((path, headers, body))
        elif action == "replay" and sent:
            path, headers, body = rng.choice(sent)
            r = await client.post(path, headers=headers, json=body)
            assert r.status_code in (200, 201, 404, 409), (step, r.text)
            done["replay"] += 1
        rows, published = await _check(client, owner_db, built.resource_id, days, step)

    assert rows, "the scenario should end with some bookings"
    assert min(done[a] for a in ("book", "cancel", "move", "replay")) >= 3, done
