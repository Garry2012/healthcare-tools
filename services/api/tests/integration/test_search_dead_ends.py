"""A search never leaves the agent with nothing to say but 'no one is available' (PO review)."""

from __future__ import annotations

from .conftest import STAFF, call, next_weekday


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


async def test_which_sharma_tells_the_caller_how_they_differ(client):
    """PO review F: both Sharmas are cardiologists, so 'Cardiology' twice does not help the caller
    choose. When options would read the same, each carries when that doctor sits."""
    body = await search(client, utterance="I want to see Dr Sharma", resourceName="Dr Sharma")
    assert body["outcome"] == "CLARIFICATION_NEEDED"
    details = {o["id"]: o["detail"] for o in body["clarification"]["options"]}
    assert details == {
        "res_anil_sharma": "Cardiology, MON WED FRI 10:00-13:00",
        "res_ravi_sharma": "Cardiology, TUE THU SAT 16:00-19:00",
    }



async def test_an_unconfirmed_fee_never_reaches_the_agent(client):
    """PO review: 'never speak an unconfirmed price' was only as safe as the prompt. The agent now
    gets no amount at all until the hospital confirms it; staff still see the draft value."""
    body = await search(client, utterance="bone doctor", category="bone doctor")
    [result] = [r for r in body["results"] if r["resource"]["resourceId"] == "res_rohan_shetty"]
    assert result["resource"].get("price") is None

    staff = await client.get("/resources/res_rohan_shetty", headers=STAFF)
    assert staff.json()["price"] == {"amount": 800, "currency": "INR", "confirmed": False}


async def test_wrong_part_of_the_day_is_not_reported_as_no_session_that_day(client, app_settings):
    """PO review: 'Dr Anil Sharma Monday evening' said NO_SESSION_THAT_DAY and then offered Monday
    10:00 as the next free time, a contradiction. He does sit that day, only not in the evening."""
    monday = next_weekday(0, app_settings)
    body = await search(client, utterance="Dr Anil Sharma monday evening", resourceName="Dr Anil Sharma",
                        when={"dateFrom": str(monday), "dateTo": str(monday), "dayPart": "EVENING"})
    [result] = body["results"]
    [gap] = result["unavailable"]
    assert gap["reason"] == "NO_SESSION_IN_DAY_PART"
    assert gap["nextBookable"]["date"] == str(monday) and gap["nextBookable"]["start"] == "10:00"

    tuesday = monday.fromordinal(monday.toordinal() + 1)
    body = await search(client, utterance="Dr Anil Sharma tuesday", resourceName="Dr Anil Sharma",
                        when={"dateFrom": str(tuesday), "dateTo": str(tuesday)})
    assert body["results"][0]["unavailable"][0]["reason"] == "NO_SESSION_THAT_DAY"


async def test_unconfirmed_hours_are_not_used_to_tell_doctors_apart(client):
    doc = (await client.get("/resources/res_ravi_sharma", headers=STAFF)).json()
    body = {k: v for k, v in doc.items() if k not in ("id", "categories")}
    r = await client.put("/resources/res_ravi_sharma", headers=STAFF,
                         json={**body, "categoryIds": ["cat_cardio"], "dataConfirmed": False})
    assert r.status_code == 200, r.text
    found = await search(client, utterance="I want to see Dr Sharma", resourceName="Dr Sharma")
    details = {o["id"]: o["detail"] for o in found["clarification"]["options"]}
    assert details["res_ravi_sharma"] == "Cardiology"
    assert details["res_anil_sharma"] == "Cardiology, MON WED FRI 10:00-13:00"
