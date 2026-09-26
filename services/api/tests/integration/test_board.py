"""The live board overrides the template for today (QA review gap 13): what the desk marks
must change what the agent offers within the same minute, and nothing else."""

from __future__ import annotations

from datetime import datetime, time

import pytest

from frontdesk_api.services import schedule

from .conftest import STAFF, book_body, call, garima_slot, next_weekday


@pytest.fixture
def today(monkeypatch, app_settings):
    """Pretend it is Thursday 09:30: Dr. Garima's morning session (09:00-12:00) is running."""
    thursday = next_weekday(3, app_settings)
    now = datetime.combine(thursday, time(9, 30), app_settings.tz)
    monkeypatch.setattr(schedule, "now_in", lambda settings: now)
    return thursday


def morning(day) -> str:
    return f"ses_res_garima_{day.isoformat()}_1"


async def _board(client, day, **fields):
    return await client.put("/board/res_garima", headers=STAFF,
                            json={"date": str(day), "sessionId": morning(day), **fields})


async def _session(client, day, headers=STAFF):
    r = await client.get("/availability", headers=headers,
                         params={"resourceId": "res_garima", "from": str(day), "to": str(day)})
    assert r.status_code == 200, r.text
    return next(x for x in r.json()["items"] if x["sessionId"] == morning(day))


@pytest.mark.parametrize(("fields", "reason"), [
    ({"presence": "LEFT"}, "LEFT_FOR_DAY"),
    ({"sessionEnded": True}, "SESSION_ENDED"),
    ({"capacityState": "FULL"}, "FULL"),
])
async def test_board_closes_the_session_for_agent_and_desk(client, today, fields, reason):
    before = await _session(client, today)
    assert before["bookable"] is True
    free = next(x["slotId"] for x in before["slots"] if x["available"])

    r = await _board(client, today, **fields)
    assert r.status_code == 200, r.text

    after = await _session(client, today)
    assert after["bookable"] is False and after["notBookableReason"] == reason
    assert not any(x["available"] for x in after["slots"])

    agent = await client.post("/agent/bookings", headers=call(key="board-a"), json=book_body(free))
    assert agent.status_code == 409 and agent.json()["error"]["code"] == "SLOT_UNAVAILABLE"
    desk = await client.post("/bookings", headers=STAFF, json=book_body(free, phone="9000000202"))
    assert desk.status_code == 409 and desk.json()["error"]["code"] == "SLOT_UNAVAILABLE"


async def test_reopening_a_full_session_offers_it_again(client, today):
    await _board(client, today, capacityState="FULL")
    assert (await _session(client, today))["bookable"] is False
    await _board(client, today, capacityState="OPEN")
    reopened = await _session(client, today)
    assert reopened["bookable"] is True and any(x["available"] for x in reopened["slots"])


async def test_a_delay_reopens_queue_positions_whose_window_had_closed(client, today):
    on_time = await _session(client, today)
    first = on_time["slots"][0]
    # at 09:30 position 1 (expected 09:00-09:30) can no longer be reached
    assert first["position"] == 1 and first["expectedWindow"]["from"] == "09:00" and first["available"] is False

    assert (await _board(client, today, delayMinutes=45)).status_code == 200
    late = await _session(client, today)
    slot = next(x for x in late["slots"] if x["slotId"] == first["slotId"])
    # the doctor is 45 minutes late: position 1 is expected from 09:45 and is offered again
    assert slot["expectedWindow"]["from"] == "09:45" and slot["available"] is True


async def test_board_is_for_today_and_this_resource_only(client, today, app_settings):
    tomorrow = today.fromordinal(today.toordinal() + 1)
    r = await client.put("/board/res_garima", headers=STAFF,
                         json={"date": str(tomorrow), "sessionId": morning(tomorrow), "presence": "LEFT"})
    assert r.status_code == 400 and r.json()["error"]["details"][0]["field"] == "date"

    foreign = f"ses_res_anil_sharma_{today.isoformat()}_1"
    r = await client.put("/board/res_garima", headers=STAFF,
                         json={"date": str(today), "sessionId": foreign, "presence": "LEFT"})
    assert r.status_code == 400 and r.json()["error"]["details"][0]["field"] == "sessionId"

    r = await client.put("/board/res_garima", headers=STAFF,
                         json={"date": str(today), "sessionId": f"ses_res_garima_{today.isoformat()}_9",
                               "presence": "LEFT"})
    assert r.status_code == 404

    # the agent token cannot write the board
    r = await client.put("/board/res_garima", headers=call(),
                         json={"date": str(today), "sessionId": morning(today), "presence": "LEFT"})
    assert r.status_code == 403


async def test_board_does_not_touch_other_sessions_or_bookings(client, today):
    booked = await client.post("/agent/bookings", headers=call(key="board-b"),
                               json=book_body(garima_slot(today, 1)))
    assert booked.status_code == 201
    await client.put("/board/res_garima", headers=STAFF,
                     json={"date": str(today), "sessionId": morning(today), "presence": "LEFT"})
    lookup = (await client.get("/agent/bookings", headers=call())).json()
    assert [b["status"] for b in lookup["items"]] == ["BOOKED"]
    afternoon = [x for x in (await client.get("/availability", headers=STAFF, params={
        "resourceId": "res_garima", "from": str(today), "to": str(today)})).json()["items"]
        if x["sessionId"].endswith("_2")]
    assert afternoon[0]["bookable"] is True
