"""Every input the voice agent or the desk can send is bounded: extreme dates, huge ranges,
deep nesting and oversized bodies are 4xx, never 5xx and never minutes of work (QA review)."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from frontdesk_api.services import schedule

from .conftest import STAFF, book_body, call

FAR = "9999-12-31"


def today(settings):
    return schedule.now_in(settings).date()


@pytest.mark.parametrize("when", [
    {"dateFrom": FAR, "dateTo": FAR},
    {"dateFrom": "0001-01-01", "dateTo": "0001-01-02"},
])
async def test_search_with_extreme_dates_is_a_validation_error(client, when):
    r = await client.post("/agent/availability-search", headers=call(),
                          json={"utterance": "Dr Garima", "language": "en", "resourceName": "Dr Garima", "when": when})
    assert r.status_code == 400 and r.json()["error"]["code"] == "VALIDATION_FAILED"


async def test_a_ten_year_search_is_clamped_not_computed(client, app_settings):
    start = today(app_settings)
    when = {"dateFrom": start.isoformat(), "dateTo": (start + timedelta(days=3650)).isoformat()}
    r = await client.post("/agent/availability-search", headers=call(),
                          json={"utterance": "any doctor", "language": "en", "category": "general doctor",
                                "when": when})
    assert r.status_code == 200
    body = r.json()
    got_to = body["understood"]["dates"]["to"]
    assert got_to <= (start + timedelta(days=app_settings.tenant_search_max_days - 1)).isoformat()
    assert any("shortened" in n for n in body.get("notes", []))
    assert len(r.content) < 500_000


async def test_booking_beyond_the_horizon_is_refused(client, app_settings):
    for day in ("9999-12-27", (today(app_settings) + timedelta(days=400)).isoformat()):
        slot = f"slot_ses_res_garima_{day}_1_01"
        r = await client.post("/agent/bookings", headers=call(key=f"far-{day}"), json=book_body(slot))
        assert r.status_code == 400, (day, r.text)


@pytest.mark.parametrize("days", [-1, -400])
async def test_exceptions_cannot_rewrite_the_past(client, app_settings, days):
    day = (today(app_settings) + timedelta(days=days)).isoformat()
    r = await client.post("/schedule-exceptions", headers=STAFF, json={
        "resourceId": "res_garima", "dateFrom": day, "dateTo": day, "scope": "WHOLE_DAY", "effect": "UNAVAILABLE"})
    assert r.status_code == 400 and r.json()["error"]["details"][0]["field"] == "dateFrom"


async def test_exception_in_year_9999_is_a_validation_error(client):
    r = await client.post("/schedule-exceptions", headers=STAFF, json={
        "resourceId": "res_garima", "dateFrom": FAR, "dateTo": FAR, "scope": "WHOLE_DAY", "effect": "UNAVAILABLE"})
    assert r.status_code == 400


async def test_template_cannot_start_in_the_past_or_far_future(client, app_settings):
    sessions = [{"templateSessionId": "tpl_res_garima_am", "daysOfWeek": ["MON"], "start": "09:00", "end": "12:00",
                 "capacityModel": "SEQUENCE", "capacity": {"mode": "PER_HOUR", "value": 4}}]
    for start in ((today(app_settings) - timedelta(days=30)).isoformat(), FAR):
        r = await client.put("/resources/res_garima/schedule-template", headers=STAFF,
                             json={"resourceId": "res_garima", "effectiveFrom": start, "sessions": sessions})
        assert r.status_code == 400, (start, r.text)


async def test_call_summary_dates_are_bounded(client):
    calls = {**STAFF}
    r = await client.get("/call-summaries", headers=calls, params={"from": FAR, "to": FAR})
    assert r.status_code == 400
    r = await client.post("/call-summaries", headers=calls, json={
        "callId": "cs-bounds", "startedAt": "0001-01-01T00:00:00+05:30", "intent": "OTHER", "outcome": "ABANDONED"})
    assert r.status_code == 400


async def test_deeply_nested_json_is_a_validation_error_not_a_crash(client):
    body = '{"question":"x","language":"en","d":' + "[" * 5000 + "]" * 5000 + "}"
    r = await client.post("/agent/knowledge-search", headers={**call(), "Content-Type": "application/json"},
                          content=body)
    assert r.status_code == 400


async def test_chunked_body_cannot_bypass_the_size_limit(client):
    payload = json.dumps({"utterance": "x" * 200_000, "language": "en"}).encode()

    async def chunks():
        for i in range(0, len(payload), 8192):
            yield payload[i:i + 8192]

    r = await client.post("/agent/availability-search", headers={**call(), "Content-Type": "application/json"},
                          content=chunks())
    assert r.status_code == 413


@pytest.mark.parametrize("path", ["/board/res_garima", "/bookings", "/notifications", "/availability"])
async def test_every_date_query_parameter_is_bounded(client, path):
    params = {"date": "0225-04-03"} if path != "/availability" else {"from": "0225-04-03", "to": "0225-04-04"}
    r = await client.get(path, headers=STAFF, params=params)
    assert r.status_code == 400, (path, r.status_code, r.text)
