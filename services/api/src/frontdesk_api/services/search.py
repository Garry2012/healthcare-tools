"""`agentAvailabilitySearch` and `getAvailability` — one engine, two views."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from .. import schemas as s
from ..config import Settings
from ..db import tables as t
from ..domain import resolver as r
from ..domain.availability import SessionView
from ..domain.dates import resolve_when
from . import directory, schedule, views
from .directory import DirectorySnapshot

_PRESENCE_ORDER = {"PRESENT": 0, "ARRIVING": 1}


def _overlaps(view: SessionView, part: str | None, ranges: dict[str, tuple[time, time]]) -> bool:
    if not part or part not in ranges:
        return True
    lo, hi = ranges[part]
    return view.start < hi and lo < view.end


def _next_bookable(
    views_by_date: dict[date, list[SessionView]], after: tuple[date, time]
) -> s.NextBookable | None:
    for day in sorted(views_by_date):
        for v in views_by_date[day]:
            if v.bookable and (v.date, v.start) > after and v.available_slots():
                return s.NextBookable(date=v.date, start=views.clock(v.start), end=views.clock(v.end))
    return None


def _understood(res: r.Resolution, snap: DirectorySnapshot) -> s.Understood:
    doctors = [
        s.UnderstoodDoctor(
            doctor_id=m.doctor_id,
            name=snap.doctors[m.doctor_id].name,
            localized_names=snap.doctors[m.doctor_id].localized_names or None,
            confidence=round(m.confidence, 2),
            matched_on=m.matched_on,
        )
        for m in res.doctors
    ]
    departments = [
        s.UnderstoodDepartment(
            id=m.department_id,
            name=snap.departments[m.department_id].name,
            localized_names=snap.departments[m.department_id].localized_names or None,
            confidence=round(m.confidence, 2),
            matched_on=m.matched_on,
        )
        for m in res.departments
    ]
    return s.Understood(doctors=doctors, departments=departments)


def _option(kind: str, concept_id: str, snap: DirectorySnapshot) -> s.ClarificationOption:
    if kind == "doctor":
        doc = snap.doctors[concept_id]
        depts = snap.departments_of(concept_id)
        return s.ClarificationOption(
            id=doc.id,
            label=doc.name,
            localized_labels=doc.localized_names or None,
            detail=depts[0].name if depts else None,
        )
    dept = snap.departments[concept_id]
    return s.ClarificationOption(id=dept.id, label=dept.name, localized_labels=dept.localized_names or None)


def _response(
    outcome: str, now: datetime, action: str, understood: s.Understood, **extra
) -> s.AvailabilitySearchResponse:
    return s.AvailabilitySearchResponse(
        outcome=outcome,
        as_of=now,
        routing=s.Routing(action=action, destination=extra.pop("destination", None)),
        understood=understood,
        results=extra.pop("results", []),
        alternatives=extra.pop("alternatives", []),
        **extra,
    )


async def agent_search(
    session: AsyncSession, settings: Settings, body: s.AvailabilitySearchRequest
) -> s.AvailabilitySearchResponse:
    now = schedule.now_in(settings)
    today = now.date()
    snap = await directory.snapshot(session)
    res = r.resolve(
        utterance=body.utterance,
        directory=snap.resolver_directory(),
        doctor_name=body.doctor_name,
        department=body.department,
        symptom_text=body.symptom_text,
        thresholds=settings.thresholds,
    )
    empty = s.Understood(doctors=[], departments=[])

    if res.action == "TRANSFER_EMERGENCY":
        return _response("TRANSFER", now, "TRANSFER_EMERGENCY", empty, destination="emergency")
    if res.action == "TRANSFER_DESK":
        return _response("TRANSFER", now, "TRANSFER_DESK", empty, destination=res.destination)

    understood = _understood(res, snap)
    when = body.when
    resolved = resolve_when(
        today=today,
        expression=when.expression if when else None,
        date_from=when.date_from if when else None,
        date_to=when.date_to if when else None,
        day_part=when.day_part.value if when and when.day_part else None,
        utterance=body.utterance,
        day_parts=snap.day_parts(),
        default_days=settings.tenant_search_default_days,
    )
    understood.dates = s.DateRange(from_=resolved.date_from, to=resolved.date_to)
    understood.day_part = s.DayPart(resolved.day_part) if resolved.day_part else None

    if res.action == "CLARIFY":
        options = [_option(kind, cid, snap) for kind, cid in res.clarification_options]
        return _response(
            "CLARIFICATION_NEEDED", now, "CLARIFY", understood,
            clarification=s.Clarification(type=res.clarification_type, options=options),
        )
    if not resolved.resolved:
        options = [
            s.ClarificationOption(id=d.isoformat(), label=d.strftime("%A %d %B"))
            for d in (today + timedelta(days=i) for i in range(3))
        ]
        return _response(
            "CLARIFICATION_NEEDED", now, "CLARIFY", understood,
            clarification=s.Clarification(type="WHICH_DATE", options=options),
        )
    if res.action == "NO_SERVICE":
        return _response("NONE_AVAILABLE", now, "NO_SERVICE", understood)
    if resolved.date_to < today:
        return _response("NONE_AVAILABLE", now, "OFFER_SLOTS", understood,
                         notes=["Requested dates are in the past."])

    date_from = max(resolved.date_from, today)
    date_to = resolved.date_to
    named = [m.doctor_id for m in res.doctors]
    dept_ids = [m.department_id for m in res.departments]
    anyone = not named and not dept_ids
    if anyone and not (when and (when.expression or when.date_from)):
        date_to = date_from  # "anyone available right now?" means today.

    def eligible(doc: t.Doctor) -> bool:
        return doc.active and doc.booking_policy != "NO_OPD"

    if named:
        candidates = [d for d in named if eligible(snap.doctors[d])]
    elif dept_ids:
        candidates = [
            d.id for d in snap.doctors.values()
            if eligible(d) and set(snap.doctor_departments.get(d.id, [])) & set(dept_ids)
        ]
    else:
        candidates = [d.id for d in snap.doctors.values() if eligible(d)]

    notes: list[str] = []
    gender = body.preferences.gender.value if body.preferences and body.preferences.gender else None
    if gender:
        unknown = [d for d in candidates if snap.doctors[d].gender is None]
        candidates = [d for d in candidates if snap.doctors[d].gender in (gender, None)]
        if unknown:
            notes.append("Some doctors have no recorded gender and are included as unknown.")
    spoken = body.preferences.language if body.preferences and body.preferences.language else None
    if spoken:
        # A doctor with no recorded languages is kept (unknown), never silently dropped.
        candidates = [d for d in candidates if not snap.doctors[d].languages_spoken
                      or spoken in snap.doctors[d].languages_spoken]

    # Same-department alternatives are computed from the same load.
    alt_pool: list[str] = []
    if named:
        alt_depts = {dep for d in named for dep in snap.doctor_departments.get(d, [])}
        alt_pool = [
            d.id for d in snap.doctors.values()
            if eligible(d) and d.id not in named
            and set(snap.doctor_departments.get(d.id, [])) & alt_depts
            and (not gender or d.gender in (gender, None))
        ]

    horizon_end = date_to + timedelta(days=settings.tenant_next_bookable_horizon_days)
    data = await schedule.load(session, settings, now, candidates + alt_pool, date_from, horizon_end)
    parts = settings.day_parts
    in_range = schedule.daterange(date_from, date_to)

    def doctor_result(doctor_id: str, *, report_gaps: bool) -> tuple[s.DoctorResult, tuple] | None:
        doc = snap.doctors[doctor_id]
        by_date = {
            day: data.sessions(doctor_id, day)
            for day in schedule.daterange(date_from, horizon_end)
        }
        sessions: list[s.SessionInstance] = []
        unavailable: list[s.UnavailableSession] = []
        soonest: tuple = (date.max, time.max)
        for day in in_range:
            day_views = [v for v in by_date[day] if _overlaps(v, resolved.day_part, parts)]
            if not day_views and report_gaps:
                reason = "ON_CALL_ONLY" if doc.attendance_type == "ON_CALL" else "NO_SESSION_THAT_DAY"
                unavailable.append(s.UnavailableSession(
                    date=day, reason=reason, next_bookable=_next_bookable(by_date, (day, time.min))
                ))
            for v in day_views:
                offerable = v.bookable and v.available_slots()
                if offerable or v.not_bookable_reason == "DESK_ONLY":
                    sessions.append(views.session_instance(
                        v, max_slots=body.max_slots_per_session, only_available=True
                    ))
                    if offerable:
                        soonest = min(soonest, (v.date, v.start))
                else:
                    unavailable.append(s.UnavailableSession(
                        date=v.date,
                        session_id=v.session_id,
                        reason=v.not_bookable_reason or "FULL",
                        next_bookable=_next_bookable(by_date, (v.date, v.start)),
                    ))
        if not sessions and not report_gaps:
            return None
        if anyone:
            sessions.sort(key=lambda si: _PRESENCE_ORDER.get(si.presence or "", 9))
        result = s.DoctorResult(
            doctor=views.result_doctor(doc, snap.departments_of(doctor_id)),
            sessions=sessions,
            unavailable=unavailable if report_gaps or not sessions else [],
        )
        presence_rank = min((_PRESENCE_ORDER.get(si.presence or "", 9) for si in sessions), default=9)
        return result, (presence_rank if anyone else 0, soonest, doc.name)

    ranked = [x for d in candidates if (x := doctor_result(d, report_gaps=bool(named)))]
    ranked.sort(key=lambda pair: pair[1])
    results = [pair[0] for pair in ranked[: body.max_doctors]]

    def bookable(result: s.DoctorResult) -> bool:
        return any(si.bookable for si in result.sessions)

    alternatives: list[s.DoctorResult] = []
    if named and not any(bookable(x) for x in results):
        alts = [x for d in alt_pool if (x := doctor_result(d, report_gaps=False))]
        alts.sort(key=lambda pair: pair[1])
        alternatives = [pair[0] for pair in alts if bookable(pair[0])][: body.max_doctors]

    desk_only = bool(results) and all(
        snap.doctors[x.doctor.doctor_id].booking_policy == "DESK_ONLY" for x in results
    ) and any(x.sessions for x in results)
    if desk_only:
        return _response("TRANSFER", now, "TRANSFER_DESK", understood, destination="desk",
                         results=results, notes=notes or None)

    found = any(bookable(x) for x in results)
    return _response(
        "FOUND" if found else "NONE_AVAILABLE",
        now,
        "OFFER_SLOTS",
        understood,
        results=results,
        alternatives=alternatives,
        notes=notes or None,
    )


async def staff_availability(
    session: AsyncSession,
    settings: Settings,
    *,
    doctor_id: str | None,
    department: str | None,
    date_from: date,
    date_to: date,
    include_slots: bool,
) -> s.AvailabilityList:
    now = schedule.now_in(settings)
    snap = await directory.snapshot(session, approved_lexicon_only=True)
    if doctor_id:
        doctor_ids = [doctor_id] if doctor_id in snap.doctors else []
    elif department:
        wanted = department.casefold()
        dept_ids = {
            d.id for d in snap.departments.values()
            if wanted in {d.id.casefold(), (d.code or "").casefold(), d.name.casefold()}
        }
        doctor_ids = [d for d, deps in snap.doctor_departments.items() if set(deps) & dept_ids]
    else:
        doctor_ids = [d.id for d in snap.doctors.values() if d.active]
    data = await schedule.load(session, settings, now, doctor_ids, date_from, date_to)
    items = [
        views.session_instance(v, include_slots=include_slots)
        for d in sorted(doctor_ids)
        for day in schedule.daterange(date_from, date_to)
        for v in data.sessions(d, day, channel="DESK")
    ]
    return s.AvailabilityList(as_of=now, items=items)
