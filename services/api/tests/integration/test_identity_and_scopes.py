"""Identity, disclosure and scope enforcement over HTTP."""

from __future__ import annotations

from .conftest import AGENT, STAFF, book_body, call, garima_slot, next_weekday


async def _book(client, slot, name, phone, caller, key):
    r = await client.post("/agent/appointments", headers=call(caller=caller, key=key),
                          json=book_body(slot, name=name, phone=phone))
    assert r.status_code == 201, r.text
    return r.json()["appointmentId"]


async def test_mismatches_are_indistinguishable_from_not_found(client, app_settings):
    monday = next_weekday(0, app_settings)
    appt = await _book(client, garima_slot(monday, 1), "Ramesh Iyer", "9000000202", "+919000000303", "i1")
    body = {"patientName": "Ramesh Iyer"}
    missing = await client.post("/agent/appointments/appt_doesnotexist/cancel", headers=call(key="c1"), json=body)
    wrong_caller = await client.post(f"/agent/appointments/{appt}/cancel",
                                     headers=call(caller="+919999999999", key="c2"), json=body)
    wrong_name = await client.post(f"/agent/appointments/{appt}/cancel",
                                   headers=call(caller="+919000000303", key="c3"),
                                   json={"patientName": "Someone Else"})
    no_caller = await client.post(f"/agent/appointments/{appt}/cancel", headers=call(caller=None, key="c4"),
                                  json=body)
    responses = [missing, wrong_caller, wrong_name, no_caller]
    assert {r.status_code for r in responses} == {404}
    assert len({r.text for r in responses}) == 1

    # booked-from number (the daughter) and the patient's own number both work
    ok = await client.post(f"/agent/appointments/{appt}/cancel", headers=call(caller="+919000000202", key="c5"),
                           json={"patientName": "ramesh  iyer"})
    assert ok.status_code == 200 and ok.json()["status"] == "CANCELLED_BY_PATIENT"


async def test_two_patients_on_one_number_need_a_name(client, app_settings):
    monday = next_weekday(0, app_settings)
    await _book(client, garima_slot(monday, 1), "Lakshmi Rao", "9000000101", "+919000000101", "n1")
    await _book(client, garima_slot(monday, 2), "Aarav Rao", "9000000101", "+919000000101", "n2")

    r = await client.get("/agent/appointments", headers=call(caller="+919000000101"))
    body = r.json()
    assert body == {"outcome": "NAME_REQUIRED", "items": [], "patientsOnNumber": 2, "identityBasis": "CALLER_NUMBER"}
    assert "Lakshmi" not in r.text and "Aarav" not in r.text

    r = await client.get("/agent/appointments", headers=call(caller="+919000000101"),
                         params={"patientName": "Aarav Rao"})
    body = r.json()
    assert body["outcome"] == "FOUND" and [i["patient"]["name"] for i in body["items"]] == ["Aarav Rao"]


async def test_lookup_without_any_number_is_identity_unavailable(client):
    r = await client.get("/agent/appointments", headers=call(caller=None))
    assert r.json()["outcome"] == "IDENTITY_UNAVAILABLE" and r.json()["identityBasis"] == "NONE"


async def test_spoken_number_lookup_is_read_only(client, app_settings):
    monday = next_weekday(0, app_settings)
    appt = await _book(client, garima_slot(monday, 1), "Lakshmi Rao", "9000000101", "+919000000101", "s1")
    r = await client.get("/agent/appointments", headers=call(caller=None), params={"phone": "9000000101"})
    assert r.json()["outcome"] == "FOUND" and r.json()["identityBasis"] == "SPOKEN_NUMBER"
    r = await client.post(f"/agent/appointments/{appt}/cancel", headers=call(caller=None, key="s2"),
                          json={"patientName": "Lakshmi Rao"})
    assert r.status_code == 404


async def test_agent_token_cannot_reach_staff_endpoints(client):
    agent = {**AGENT, "X-Acting-User": "intruder"}
    checks = [
        ("GET", "/appointments", None),
        ("GET", "/notifications", None),
        ("GET", "/lexicon", None),
        ("POST", "/schedule-exceptions", {"doctorId": "doc_garima", "dateFrom": "2030-01-01",
                                          "dateTo": "2030-01-01", "scope": "WHOLE_DAY", "effect": "UNAVAILABLE"}),
        ("PUT", "/board/doc_garima", {"date": "2030-01-01", "sessionId": "x"}),
        ("POST", "/doctors", {"name": "Dr. X", "departmentIds": ["dept_genmed"]}),
        ("GET", "/call-summaries", None),
    ]
    for method, path, body in checks:
        r = await client.request(method, path, headers=agent, json=body)
        assert r.status_code == 403, (method, path, r.status_code)
        assert r.json()["error"]["code"] == "FORBIDDEN"


async def test_missing_or_bad_token_is_401(client):
    assert (await client.get("/departments")).status_code == 401
    r = await client.get("/departments", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHORIZED"


async def test_staff_sees_staff_fields_and_agent_does_not(client, app_settings):
    monday = next_weekday(0, app_settings)
    r = await client.post("/agent/appointments", headers=call(caller="+919000000303", key="f1"),
                          json=book_body(garima_slot(monday, 1), name="Ramesh Iyer", phone="9000000202",
                                         reasonVerbatim="BP check"))
    appt = r.json()
    assert "callerNumber" not in appt and "reasonVerbatim" not in appt
    staff = (await client.get(f"/appointments/{appt['appointmentId']}", headers=STAFF)).json()
    assert staff["callerNumber"] == "+919000000303" and staff["reasonVerbatim"] == "BP check"
    assert [h["change"] for h in staff["history"]] == ["BOOKED"]


async def test_board_and_exception_internals_are_redacted_for_the_agent(client, app_settings):
    from healthcare_api.services import schedule

    today = schedule.now_in(app_settings).date()
    sid = f"ses_doc_arjun_menon_{today}_2"
    r = await client.put("/board/doc_arjun_menon", headers=STAFF,
                         json={"date": str(today), "sessionId": sid, "presence": "ARRIVING", "delayMinutes": 10})
    assert r.status_code == 200 and r.json()["updatedBy"] == "desk-1"
    seen = (await client.get("/board/doc_arjun_menon", headers=AGENT)).json()
    assert seen["sessions"][0]["updatedBy"] == "staff"

    thursday = next_weekday(3, app_settings)
    await client.post("/schedule-exceptions", headers=STAFF, json={
        "doctorId": "doc_garima", "dateFrom": str(thursday), "dateTo": str(thursday), "scope": "SESSION",
        "templateSessionId": "tpl_doc_garima_pm", "effect": "UNAVAILABLE", "reasonCategory": "SURGERY",
        "note": "private"})
    items = (await client.get("/schedule-exceptions", headers=AGENT)).json()["items"]
    assert "reasonCategory" not in items[0] and "note" not in items[0]
    items = (await client.get("/schedule-exceptions", headers=STAFF)).json()["items"]
    assert items[0]["reasonCategory"] == "SURGERY"
