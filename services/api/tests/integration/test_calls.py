"""Call summaries: one per call, days in facility time, stable paging (QA review gap 14)."""

from __future__ import annotations

from .conftest import STAFF, call


def summary(call_id: str, started_at: str, **extra) -> dict:
    return {"callId": call_id, "startedAt": started_at, "intent": "BOOKING", "outcome": "BOOKING_CREATED",
            **extra}


async def test_a_second_summary_for_a_call_is_ignored(client):
    first = await client.post("/call-summaries", headers=STAFF,
                              json=summary("c-dup", "2026-09-20T10:00:00+05:30", summaryText="booked Garima"))
    assert first.status_code == 201
    again = await client.post("/call-summaries", headers=STAFF,
                              json=summary("c-dup", "2026-09-20T11:00:00+05:30", summaryText="different"))
    assert again.status_code == 200
    assert again.json()["id"] == first.json()["id"] and again.json()["summaryText"] == "booked Garima"


async def test_days_are_facility_days_not_utc_days(client):
    # 23:30 in India is still the 20th locally but 18:00 UTC; 00:15 on the 21st is 18:45 UTC on the 20th
    await client.post("/call-summaries", headers=STAFF, json=summary("late", "2026-09-20T23:30:00+05:30"))
    await client.post("/call-summaries", headers=STAFF, json=summary("after-midnight", "2026-09-20T18:45:00Z"))

    def ids(r):
        assert r.status_code == 200, r.text
        return [x["callId"] for x in r.json()["items"]]

    on_20 = await client.get("/call-summaries", headers=STAFF, params={"from": "2026-09-20", "to": "2026-09-20"})
    on_21 = await client.get("/call-summaries", headers=STAFF, params={"from": "2026-09-21", "to": "2026-09-21"})
    assert ids(on_20) == ["late"] and ids(on_21) == ["after-midnight"]


async def test_paging_returns_every_call_once_even_with_equal_times(client):
    for i in range(7):
        r = await client.post("/call-summaries", headers=STAFF, json=summary(f"p{i}", "2026-09-22T10:00:00+05:30"))
        assert r.status_code == 201
    seen: list[str] = []
    for offset in range(0, 8, 2):
        page = (await client.get("/call-summaries", headers=STAFF,
                                 params={"limit": 2, "offset": offset})).json()
        assert page["total"] == 7
        seen += [x["callId"] for x in page["items"]]
    assert sorted(seen) == [f"p{i}" for i in range(7)]


async def test_reversed_range_is_refused(client):
    r = await client.get("/call-summaries", headers=STAFF, params={"from": "2026-09-21", "to": "2026-09-20"})
    assert r.status_code == 400 and r.json()["error"]["details"][0]["field"] == "to"


async def test_the_voice_agent_cannot_read_call_history(client):
    r = await client.get("/call-summaries", headers=call())
    assert r.status_code == 403
