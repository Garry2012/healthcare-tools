"""Replacing a resource's template must never move existing bookings to another session
(tech-lead TL2): session ids are stable across template versions."""

from __future__ import annotations

from sqlalchemy import select

from frontdesk_api.db import tables as t
from frontdesk_api.services import schedule

from .conftest import STAFF, book_body, call, garima_slot, next_weekday


def session_def(tsid, start, end):
    return {"templateSessionId": tsid, "daysOfWeek": ["MON", "THU", "FRI"], "start": start, "end": end,
            "capacityModel": "SEQUENCE", "capacity": {"mode": "PER_HOUR", "value": 4}, "walkInReservePercent": 25}


async def test_adding_a_session_before_others_keeps_existing_session_ids(client, app, app_settings):
    monday = next_weekday(0, app_settings)
    booked = await client.post("/agent/bookings", headers=call(key="tpl-1"), json=book_body(garima_slot(monday, 1)))
    assert booked.status_code == 201
    session_id = booked.json()["slot"]["slotId"].rsplit("_", 1)[0].removeprefix("slot_")

    today = schedule.now_in(app_settings).date()
    r = await client.put("/resources/res_garima/schedule-template", headers=STAFF, json={
        "resourceId": "res_garima", "effectiveFrom": str(today), "sessions": [
            session_def("tpl_res_garima_early", "07:00", "08:30"),
            session_def("tpl_res_garima_am", "09:00", "12:00"),
            session_def("tpl_res_garima_pm", "15:00", "17:00")]})
    assert r.status_code == 200, r.text

    async with app.state.sessionmaker() as session:
        row = await session.get(t.Booking, booked.json()["bookingId"])
        ordinals = dict((await session.execute(
            select(t.TemplateSession.template_session_id, t.TemplateSession.ordinal)
            .join(t.ScheduleTemplate, t.ScheduleTemplate.id == t.TemplateSession.template_id)
            .where(t.ScheduleTemplate.effective_from == today))).all())
    assert row.status == "BOOKED" and row.session_id == session_id
    assert ordinals["tpl_res_garima_pm"] == 2 and ordinals["tpl_res_garima_am"] == 1
    assert ordinals["tpl_res_garima_early"] == 3

    view = await client.get("/availability", headers=STAFF, params={
        "resourceId": "res_garima", "from": str(monday), "to": str(monday), "includeSlots": "false"})
    by_id = {s["sessionId"]: s for s in view.json()["items"]}
    assert by_id[session_id]["start"] == "15:00"


async def test_deactivating_a_resource_moves_its_future_bookings_and_queues_notices(client, app, app_settings):
    """PO review: a doctor who leaves must not keep patients BOOKED for sessions that will not happen."""
    monday = next_weekday(0, app_settings)
    booked = await client.post("/agent/bookings", headers=call(key="leave-1"), json=book_body(garima_slot(monday, 2)))
    assert booked.status_code == 201
    current = (await client.get("/resources/res_garima", headers=STAFF)).json()
    update = {k: current[k] for k in ("name", "localizedNames", "nameVariants", "gender", "languagesSpoken",
                                      "price", "attendanceType", "bookingPolicy", "dataConfirmed") if k in current}
    update |= {"categoryIds": [c["id"] for c in current["categories"]], "active": False}
    r = await client.put("/resources/res_garima", headers=STAFF, json=update)
    assert r.status_code == 200, r.text
    async with app.state.sessionmaker() as session:
        row = await session.get(t.Booking, booked.json()["bookingId"])
    assert row.status == "NEEDS_RESCHEDULE"
    notices = [n for n in (await client.get("/notifications", headers=STAFF)).json()["items"]
               if n["bookingId"] == row.id]
    assert len(notices) == 1 and notices[0]["trigger"] == "SESSION_CANCELLED"


async def test_template_rejects_overlapping_sessions_and_a_foreign_resource_id(client, app_settings):
    today = str(schedule.now_in(app_settings).date())
    overlapping = [session_def("tpl_a", "09:00", "12:00"), session_def("tpl_b", "11:30", "13:00")]
    r = await client.put("/resources/res_garima/schedule-template", headers=STAFF,
                         json={"resourceId": "res_garima", "effectiveFrom": today, "sessions": overlapping})
    assert r.status_code == 400 and r.json()["error"]["details"][0]["field"] == "sessions[1]", r.text

    # the same hours on different days do not overlap
    evening = {**session_def("tpl_b", "11:30", "13:00"), "daysOfWeek": ["TUE"]}
    r = await client.put("/resources/res_garima/schedule-template", headers=STAFF, json={
        "resourceId": "res_garima", "effectiveFrom": today,
        "sessions": [session_def("tpl_res_garima_am", "09:00", "12:00"), evening]})
    assert r.status_code == 200, r.text

    r = await client.put("/resources/res_garima/schedule-template", headers=STAFF, json={
        "resourceId": "res_anil_sharma", "effectiveFrom": today,
        "sessions": [session_def("tpl_res_garima_am", "09:00", "12:00")]})
    assert r.status_code == 400 and r.json()["error"]["details"][0]["field"] == "resourceId", r.text
