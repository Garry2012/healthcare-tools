"""Staff operations under concurrency and in the wrong order (QA review, tech-lead TL8)."""

from __future__ import annotations

import asyncio

from .conftest import STAFF, book_body, call, garima_slot, next_weekday


async def test_parallel_resources_with_one_name_all_succeed_with_distinct_ids(client):
    body = {"name": "Dr Race", "categoryIds": ["cat_derm"]}
    results = await asyncio.gather(*(client.post("/resources", headers=STAFF, json=body) for _ in range(8)))
    assert [r.status_code for r in results] == [201] * 8
    assert len({r.json()["id"] for r in results}) == 8


async def test_parallel_call_summaries_for_one_call_store_one(client):
    summary = {"callId": "race-call", "startedAt": "2026-09-26T10:00:00+05:30", "intent": "BOOKING",
               "outcome": "BOOKING_CREATED"}
    results = await asyncio.gather(*(client.post("/call-summaries", headers=STAFF, json=summary) for _ in range(6)))
    assert all(r.status_code in (200, 201) for r in results), [r.status_code for r in results]
    assert len({r.json()["id"] for r in results}) == 1


async def test_future_bookings_cannot_be_completed_or_marked_no_show(client, app_settings):
    monday = next_weekday(0, app_settings)
    booking = (await client.post("/agent/bookings", headers=call(key="fut"),
                                 json=book_body(garima_slot(monday, 1)))).json()["bookingId"]
    for status in ("COMPLETED", "NO_SHOW", "ARRIVED"):
        r = await client.post(f"/bookings/{booking}/status", headers=STAFF, json={"status": status})
        assert r.status_code == 409, (status, r.text)


async def test_an_acknowledged_notification_keeps_what_the_customer_said(client, app_settings):
    thursday = next_weekday(3, app_settings)
    await client.post("/agent/bookings", headers=call(key="n1"), json=book_body(garima_slot(thursday, 1)))
    await client.post("/schedule-exceptions", headers=STAFF, json={
        "resourceId": "res_garima", "dateFrom": str(thursday), "dateTo": str(thursday), "scope": "SESSION",
        "templateSessionId": "tpl_res_garima_pm", "effect": "UNAVAILABLE"})
    [notice] = (await client.get("/notifications", headers=STAFF)).json()["items"]
    first = await client.post(f"/notifications/{notice['id']}/delivered", headers=STAFF,
                              json={"channel": "PHONE", "outcome": "CANCELLED"})
    assert first.json()["status"] == "ACKNOWLEDGED"
    second = await client.post(f"/notifications/{notice['id']}/delivered", headers=STAFF, json={"channel": "SMS"})
    assert second.status_code == 409
    kept = [n for n in (await client.get("/notifications", headers=STAFF,
                                         params={"status": "ACKNOWLEDGED"})).json()["items"] if n["id"] == notice["id"]]
    assert kept[0]["outcome"] == "CANCELLED" and kept[0]["channel"] == "PHONE"
