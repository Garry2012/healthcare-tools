"""Identity, disclosure and scope enforcement over HTTP."""

from __future__ import annotations

from .conftest import AGENT, STAFF, book_body, call, garima_slot, next_weekday


async def _book(client, slot, name, phone, caller, key):
    r = await client.post("/agent/bookings", headers=call(caller=caller, key=key),
                          json=book_body(slot, name=name, phone=phone))
    assert r.status_code == 201, r.text
    return r.json()["bookingId"]


async def test_mismatches_are_indistinguishable_from_not_found(client, app_settings):
    monday = next_weekday(0, app_settings)
    booking = await _book(client, garima_slot(monday, 1), "Ramesh Iyer", "9000000202", "+919000000303", "i1")
    body = {"customerName": "Ramesh Iyer"}
    missing = await client.post("/agent/bookings/bkg_doesnotexist/cancel", headers=call(key="c1"), json=body)
    wrong_caller = await client.post(f"/agent/bookings/{booking}/cancel",
                                     headers=call(caller="+919999999999", key="c2"), json=body)
    wrong_name = await client.post(f"/agent/bookings/{booking}/cancel",
                                   headers=call(caller="+919000000303", key="c3"),
                                   json={"customerName": "Someone Else"})
    no_caller = await client.post(f"/agent/bookings/{booking}/cancel", headers=call(caller=None, key="c4"),
                                  json=body)
    responses = [missing, wrong_caller, wrong_name, no_caller]
    assert {r.status_code for r in responses} == {404}
    assert len({r.text for r in responses}) == 1

    # booked-from number (the daughter) and the customer's own number both work
    ok = await client.post(f"/agent/bookings/{booking}/cancel", headers=call(caller="+919000000202", key="c5"),
                           json={"customerName": "ramesh  iyer"})
    assert ok.status_code == 200 and ok.json()["status"] == "CANCELLED_BY_CUSTOMER"


async def test_two_customers_on_one_number_need_a_name(client, app_settings):
    monday = next_weekday(0, app_settings)
    await _book(client, garima_slot(monday, 1), "Lakshmi Rao", "9000000101", "+919000000101", "n1")
    await _book(client, garima_slot(monday, 2), "Aarav Rao", "9000000101", "+919000000101", "n2")

    r = await client.get("/agent/bookings", headers=call(caller="+919000000101"))
    body = r.json()
    assert body == {"outcome": "NAME_REQUIRED", "items": [], "customersOnNumber": 2, "identityBasis": "CALLER_NUMBER"}
    assert "Lakshmi" not in r.text and "Aarav" not in r.text

    r = await client.get("/agent/bookings", headers=call(caller="+919000000101"),
                         params={"customerName": "Aarav Rao"})
    body = r.json()
    assert body["outcome"] == "FOUND" and [i["customer"]["name"] for i in body["items"]] == ["Aarav Rao"]


async def test_lookup_without_any_number_is_identity_unavailable(client):
    r = await client.get("/agent/bookings", headers=call(caller=None))
    assert r.json()["outcome"] == "IDENTITY_UNAVAILABLE" and r.json()["identityBasis"] == "NONE"


async def test_spoken_number_lookup_is_read_only(client, app_settings):
    monday = next_weekday(0, app_settings)
    booking = await _book(client, garima_slot(monday, 1), "Lakshmi Rao", "9000000101", "+919000000101", "s1")
    r = await client.get("/agent/bookings", headers=call(caller=None),
                         params={"phone": "9000000101", "customerName": "Lakshmi Rao"})
    assert r.json()["outcome"] == "FOUND" and r.json()["identityBasis"] == "SPOKEN_NUMBER"
    r = await client.post(f"/agent/bookings/{booking}/cancel", headers=call(caller=None, key="s2"),
                          json={"customerName": "Lakshmi Rao"})
    assert r.status_code == 404


async def test_a_spoken_number_never_discloses_bookings_without_the_name(client, app_settings):
    """Anyone can say a number: without the customer's name, no booking, name or count leaks,
    whether or not the number has bookings, and whether or not the call has caller ID."""
    monday = next_weekday(0, app_settings)
    await _book(client, garima_slot(monday, 1), "Lakshmi Rao", "9000000101", "+919000000101", "d1")
    for caller in (None, "+919000000999"):
        for number in ("9000000101", "9000000888"):
            r = await client.get("/agent/bookings", headers=call(caller=caller), params={"phone": number})
            body = r.json()
            assert body["outcome"] == "NAME_REQUIRED", (caller, number, body)
            assert body["items"] == [] and body["customersOnNumber"] == 0
    r = await client.get("/agent/bookings", headers=call(caller="+919000000999"),
                         params={"phone": "9000000101", "customerName": "Somebody Else"})
    assert r.json()["outcome"] == "NONE_FOUND" and r.json()["items"] == []
    r = await client.get("/agent/bookings", headers=call(caller="+919000000999"),
                         params={"phone": "9000000101", "customerName": "lakshmi  rao"})
    assert r.json()["outcome"] == "FOUND" and len(r.json()["items"]) == 1


async def test_agent_token_cannot_reach_staff_endpoints(client):
    agent = {**AGENT, "X-Acting-User": "intruder"}
    checks = [
        ("GET", "/bookings", None),
        ("GET", "/notifications", None),
        ("GET", "/lexicon", None),
        ("POST", "/schedule-exceptions", {"resourceId": "res_garima", "dateFrom": "2030-01-01",
                                          "dateTo": "2030-01-01", "scope": "WHOLE_DAY", "effect": "UNAVAILABLE"}),
        ("PUT", "/board/res_garima", {"date": "2030-01-01", "sessionId": "x"}),
        ("POST", "/resources", {"name": "Dr. X", "categoryIds": ["cat_genmed"]}),
        ("GET", "/call-summaries", None),
    ]
    for method, path, body in checks:
        r = await client.request(method, path, headers=agent, json=body)
        assert r.status_code == 403, (method, path, r.status_code)
        assert r.json()["error"]["code"] == "FORBIDDEN"


async def test_missing_or_bad_token_is_401(client):
    assert (await client.get("/categories")).status_code == 401
    r = await client.get("/categories", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHORIZED"


async def test_staff_sees_staff_fields_and_agent_does_not(client, app_settings):
    monday = next_weekday(0, app_settings)
    r = await client.post("/agent/bookings", headers=call(caller="+919000000303", key="f1"),
                          json=book_body(garima_slot(monday, 1), name="Ramesh Iyer", phone="9000000202",
                                         reasonVerbatim="BP check"))
    booking = r.json()
    assert "callerNumber" not in booking and "reasonVerbatim" not in booking
    staff = (await client.get(f"/bookings/{booking['bookingId']}", headers=STAFF)).json()
    assert staff["callerNumber"] == "+919000000303" and staff["reasonVerbatim"] == "BP check"
    assert [h["change"] for h in staff["history"]] == ["BOOKED"]


async def test_board_and_exception_internals_are_redacted_for_the_agent(client, app_settings):
    from frontdesk_api.services import schedule

    today = schedule.now_in(app_settings).date()
    sid = f"ses_res_arjun_menon_{today}_2"
    r = await client.put("/board/res_arjun_menon", headers=STAFF,
                         json={"date": str(today), "sessionId": sid, "presence": "ARRIVING", "delayMinutes": 10})
    assert r.status_code == 200 and r.json()["updatedBy"] == "desk-1"
    seen = (await client.get("/board/res_arjun_menon", headers=AGENT)).json()
    assert seen["sessions"][0]["updatedBy"] == "staff"

    thursday = next_weekday(3, app_settings)
    await client.post("/schedule-exceptions", headers=STAFF, json={
        "resourceId": "res_garima", "dateFrom": str(thursday), "dateTo": str(thursday), "scope": "SESSION",
        "templateSessionId": "tpl_res_garima_pm", "effect": "UNAVAILABLE", "reasonCategory": "OTHER_DUTY",
        "note": "private"})
    items = (await client.get("/schedule-exceptions", headers=AGENT)).json()["items"]
    assert "reasonCategory" not in items[0] and "note" not in items[0]
    items = (await client.get("/schedule-exceptions", headers=STAFF)).json()["items"]
    assert items[0]["reasonCategory"] == "OTHER_DUTY"


async def test_preferences_filter_by_gender_and_language(client, app, app_settings):
    from frontdesk_api.db import tables as t

    async with app.state.sessionmaker() as session:
        (await session.get(t.Resource, "res_arjun_menon")).languages_spoken = ["en", "ml"]
        await session.commit()
    body = {"utterance": "general physician", "language": "en", "category": "general physician",
            "when": {"expression": "next monday"}}
    everyone = (await client.post("/agent/availability-search", headers=call(), json=body)).json()
    ladies = (await client.post("/agent/availability-search", headers=call(),
                                json={**body, "preferences": {"gender": "FEMALE"}})).json()
    kannada = (await client.post("/agent/availability-search", headers=call(),
                                 json={**body, "preferences": {"language": "kn"}})).json()
    names = lambda r: sorted(x["resource"]["name"] for x in r["results"])  # noqa: E731
    assert names(everyone) == ["Dr. Arjun Menon", "Dr. Garima"]
    assert names(ladies) == ["Dr. Garima"]
    assert names(kannada) == ["Dr. Garima"]


async def test_only_the_agent_scope_reaches_the_agent_operations(client):
    """Spec defect S3 closed: a staff (or any other) token cannot act as the voice agent."""
    staff = {**STAFF, "X-Call-Id": "c-staff", "X-Caller-Number": "+919000000101", "Idempotency-Key": "k-staff"}
    checks = [
        ("POST", "/agent/availability-search", {"utterance": "Dr Garima", "language": "en"}),
        ("POST", "/agent/knowledge-search", {"question": "parking", "language": "en"}),
        ("GET", "/agent/bookings", None),
        ("POST", "/agent/bookings", {"slotId": "slot_x_01", "customer": {"name": "A", "phone": "9000000101"},
                                     "language": "en"}),
        ("POST", "/agent/bookings/bkg_x/cancel", {"customerName": "A"}),
        ("POST", "/agent/bookings/bkg_x/reschedule", {"customerName": "A", "newSlotId": "slot_x_02"}),
    ]
    for method, path, body in checks:
        r = await client.request(method, path, headers=staff, json=body)
        assert r.status_code == 403, (path, r.status_code, r.text)
        assert r.json()["error"]["code"] == "FORBIDDEN"


async def test_a_duplicate_booking_reveals_nothing_to_another_caller(client, app_settings):
    """ALREADY_BOOKED returns the existing booking (id, confirmation code) only to the number it
    belongs to; anyone else who knows a name and phone learns nothing (tech-lead N7)."""
    monday = next_weekday(0, app_settings)
    first = await client.post("/agent/bookings", headers=call(key="dup-1"),
                              json=book_body(garima_slot(monday, 1)))
    assert first.status_code == 201
    stranger = await client.post("/agent/bookings", headers=call(caller="+919000000999", key="dup-2"),
                                 json=book_body(garima_slot(monday, 2)))
    assert stranger.status_code == 409
    text = stranger.text
    assert first.json()["bookingId"] not in text and first.json()["confirmationCode"] not in text
    owner = await client.post("/agent/bookings", headers=call(key="dup-3"), json=book_body(garima_slot(monday, 3)))
    assert owner.status_code == 200 and owner.json()["outcome"] == "ALREADY_BOOKED"
    assert owner.json()["bookingId"] == first.json()["bookingId"]
