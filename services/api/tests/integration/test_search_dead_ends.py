"""A search never leaves the agent with nothing to say but 'no one is available' (PO review)."""

from __future__ import annotations

from .conftest import call, next_weekday


async def search(client, **body):
    r = await client.post("/agent/availability-search", headers=call(), json={"language": "en", **body})
    assert r.status_code == 200, r.text
    return r.json()


async def test_department_with_nothing_that_day_offers_the_next_date(client, app_settings):
    monday = next_weekday(0, app_settings)  # the dermatologist sits Tue/Fri only
    body = await search(client, utterance="skin doctor on monday", category="skin doctor",
                        when={"dateFrom": str(monday), "dateTo": str(monday)})
    assert body["outcome"] == "NONE_AVAILABLE"
    [result] = body["results"]
    assert result["resource"]["resourceId"] == "res_priya_nair" and result["sessions"] == []
    nxt = result["unavailable"][0]["nextBookable"]
    assert nxt["date"] > str(monday) and nxt["start"] == "14:00"


async def test_desk_only_department_is_handed_to_the_desk(client):
    body = await search(client, utterance="I need a neurologist", category="neurologist")
    assert body["outcome"] == "TRANSFER"
    assert body["routing"] == {"action": "TRANSFER_DESK", "destination": "desk"}


async def test_desk_only_doctor_by_name_is_handed_to_the_desk(client):
    body = await search(client, utterance="Dr Vikram Desai", resourceName="Dr Vikram Desai")
    assert body["routing"] == {"action": "TRANSFER_DESK", "destination": "desk"}


async def test_anyone_next_week_covers_the_week_not_one_day(client):
    body = await search(client, utterance="is anyone available next week")
    dates = body["understood"]["dates"]
    assert dates["from"] != dates["to"]
