"""Capacity-derived windows survive persistence, booking and subsequent searches."""

import pytest

from frontdesk_api.services import schedule

from .conftest import STAFF, book_body, call, garima_slot, next_weekday


@pytest.mark.parametrize(("rate", "third_window"), [
    (4, {"from": "09:30", "to": "09:45"}),
    (6, {"from": "09:20", "to": "09:30"}),
    (8, {"from": "09:15", "to": "09:22"}),
    (9, {"from": "09:13", "to": "09:20"}),
])
async def test_capacity_windows_and_occupied_positions(client, app_settings, rate, third_window):
    monday = next_weekday(0, app_settings)
    saved = await client.put("/resources/res_garima/schedule-template", headers=STAFF, json={
        "resourceId": "res_garima", "effectiveFrom": str(schedule.now_in(app_settings).date()),
        "sessions": [{
            "templateSessionId": "tpl_res_garima_am", "daysOfWeek": ["MON"],
            "start": "09:00", "end": "12:00", "capacityModel": "SEQUENCE",
            "capacity": {"mode": "PER_HOUR", "value": rate}, "walkInReservePercent": 0,
        }],
    })
    assert saved.status_code == 200, saved.text
    params = {"resourceId": "res_garima", "from": str(monday), "to": str(monday)}
    initial = await client.get("/availability", headers=STAFF, params=params)
    assert initial.status_code == 200
    slots = initial.json()["items"][0]["slots"]
    assert len(slots) == rate * 3
    assert slots[2]["expectedWindow"] == third_window
    assert slots[-1]["expectedWindow"]["to"] == "12:00"
    assert all(a["expectedWindow"]["to"] == b["expectedWindow"]["from"]
               for a, b in zip(slots, slots[1:], strict=False))

    booked = await client.post("/agent/bookings", headers=call(key="window-book"),
                               json=book_body(garima_slot(monday, 3, n=1)))
    assert booked.status_code == 201, booked.text
    assert booked.json()["slot"]["expectedWindow"] == third_window
    after = await client.get("/availability", headers=STAFF, params=params)
    session = after.json()["items"][0]
    assert session["capacity"]["remaining"] == rate * 3 - 1
    assert [s["position"] for s in session["slots"] if s["available"]] == [
        p for p in range(1, rate * 3 + 1) if p != 3]
    assert [s["expectedWindow"] for s in session["slots"]] == [s["expectedWindow"] for s in slots]

    searched = await client.post("/agent/availability-search", headers=call(), json={
        "utterance": "Dr Garima", "resourceName": "Dr Garima", "language": "en",
        "when": {"dateFrom": str(monday), "dateTo": str(monday)},
    })
    assert searched.status_code == 200, searched.text
    offered = searched.json()["results"][0]["sessions"][0]["slots"]
    assert [s["position"] for s in offered] == [1, 2, 4]


async def test_staff_template_rejects_sub_minute_sequence_capacity(client, app_settings):
    result = await client.put("/resources/res_garima/schedule-template", headers=STAFF, json={
        "resourceId": "res_garima", "effectiveFrom": str(schedule.now_in(app_settings).date()),
        "sessions": [{
            "templateSessionId": "tpl_res_garima_am", "daysOfWeek": ["MON"],
            "start": "09:00", "end": "12:00", "capacityModel": "SEQUENCE",
            "capacity": {"mode": "PER_HOUR", "value": 61},
        }],
    })
    assert result.status_code == 400
    assert result.json()["error"]["details"][0]["field"] == "sessions[0].capacity.value"
