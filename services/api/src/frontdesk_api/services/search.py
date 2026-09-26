"""`agentAvailabilitySearch` and `getAvailability` — one engine, two views."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, time, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from .. import schemas as s
from ..config import Settings
from ..db import tables as t
from ..domain import resolver as r
from ..domain.availability import SessionView
from ..domain.dates import resolve_when
from . import schedule, views
from .cache import VersionedCache
from .directory import DirectorySnapshot

_PRESENCE_ORDER = {"PRESENT": 0, "ARRIVING": 1}


def _overlaps(view: SessionView, part: str | None, ranges: dict[str, tuple[time, time]]) -> bool:
    if not part or part not in ranges:
        return True
    lo, hi = ranges[part]
    return view.start < hi and lo < view.end


class _LazyDays:
    """Sessions per day, computed on first use: the horizon beyond the requested range is only
    evaluated when an unavailable session needs a `nextBookable` (most searches never do)."""

    __slots__ = ("_compute", "_seen", "days")

    def __init__(self, compute: Callable[[date], list[SessionView]], days: list[date]) -> None:
        self._compute, self.days, self._seen = compute, days, {}

    def __getitem__(self, day: date) -> list[SessionView]:
        if day not in self._seen:
            self._seen[day] = self._compute(day)
        return self._seen[day]


def _next_bookable(views_by_date: _LazyDays, after: tuple[date, time]) -> s.NextBookable | None:
    for day in views_by_date.days:
        if day < after[0]:
            continue
        for v in views_by_date[day]:
            if v.bookable and (v.date, v.start) > after and v.available_slots():
                return s.NextBookable(date=v.date, start=views.clock(v.start), end=views.clock(v.end))
    return None


def _understood(res: r.Resolution, snap: DirectorySnapshot) -> s.Understood:
    resources = [
        s.UnderstoodResource(
            resource_id=m.resource_id,
            name=snap.resources[m.resource_id].name,
            localized_names=snap.resources[m.resource_id].localized_names or None,
            confidence=round(m.confidence, 2),
            matched_on=m.matched_on,
        )
        for m in res.resources
    ]
    categories = [
        s.UnderstoodCategory(
            id=m.category_id,
            name=snap.categories[m.category_id].name,
            localized_names=snap.categories[m.category_id].localized_names or None,
            confidence=round(m.confidence, 2),
            matched_on=m.matched_on,
        )
        for m in res.categories
    ]
    return s.Understood(resources=resources, categories=categories)


def _option(kind: str, concept_id: str, snap: DirectorySnapshot) -> s.ClarificationOption:
    if kind == "resource":
        doc = snap.resources[concept_id]
        cats = snap.categories_of(concept_id)
        return s.ClarificationOption(
            id=doc.id,
            label=doc.name,
            localized_labels=doc.localized_names or None,
            detail=cats[0].name if cats else None,
        )
    cat = snap.categories[concept_id]
    return s.ClarificationOption(id=cat.id, label=cat.name, localized_labels=cat.localized_names or None)


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
    session: AsyncSession, settings: Settings, body: s.AvailabilitySearchRequest,
    directory_cache: VersionedCache[DirectorySnapshot],
) -> s.AvailabilitySearchResponse:
    now = schedule.now_in(settings)
    today = now.date()
    snap = await directory_cache.get(session)
    res = r.resolve(
        utterance=body.utterance,
        directory=snap.resolver_directory(),
        resource_name=body.resource_name,
        category=body.category,
        need_text=body.need_text,
        thresholds=settings.thresholds,
    )
    empty = s.Understood(resources=[], categories=[])

    if res.action == "TRANSFER_EMERGENCY":
        return _response("TRANSFER", now, "TRANSFER_EMERGENCY", empty, destination=settings.pack.escalation_destination)
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
        # Not "none available": we did not understand, or do not offer, what was asked. The agent
        # asks the caller to rephrase once, or hands over to the desk; it never says "no doctor".
        return _response("TRANSFER", now, "NO_SERVICE", understood, destination="desk",
                         notes=["Not understood or not offered here: ask the caller to rephrase, "
                                "or transfer to the desk. Do not say that no one is available."])
    if resolved.date_to < today:
        return _response("NONE_AVAILABLE", now, "OFFER_SLOTS", understood,
                         notes=["Requested dates are in the past."])

    date_from = max(resolved.date_from, today)
    date_to = resolved.date_to
    notes: list[str] = []
    longest = timedelta(days=settings.tenant_search_max_days - 1)
    if date_to - date_from > longest:
        date_to = date_from + longest
        notes.append(f"The date range was shortened to {settings.tenant_search_max_days} days.")
        understood.dates = s.DateRange(from_=date_from, to=date_to)
    named = [m.resource_id for m in res.resources]
    cat_ids = [m.category_id for m in res.categories]
    anyone = not named and not cat_ids
    if anyone and not (when and (when.expression or when.date_from)):
        date_to = date_from  # "anyone available right now?" means today.

    def eligible(doc: t.Resource) -> bool:
        return doc.active and doc.booking_policy != "NOT_OFFERED"

    if named:
        candidates = [d for d in named if eligible(snap.resources[d])]
    elif cat_ids:
        candidates = [
            d.id for d in snap.resources.values()
            if eligible(d) and set(snap.resource_categories.get(d.id, [])) & set(cat_ids)
        ]
    else:
        candidates = [d.id for d in snap.resources.values() if eligible(d)]

    gender = body.preferences.gender.value if body.preferences and body.preferences.gender else None
    if gender:
        unknown = [d for d in candidates if snap.resources[d].gender is None]
        candidates = [d for d in candidates if snap.resources[d].gender in (gender, None)]
        if unknown:
            notes.append("Some resources have no recorded gender and are included as unknown.")
    spoken = body.preferences.language if body.preferences and body.preferences.language else None
    if spoken:
        # A resource with no recorded languages is kept (unknown), never silently dropped.
        candidates = [d for d in candidates if not snap.resources[d].languages_spoken
                      or spoken in snap.resources[d].languages_spoken]

    # Same-category alternatives are computed from the same load.
    alt_pool: list[str] = []
    if named:
        alt_depts = {dep for d in named for dep in snap.resource_categories.get(d, [])}
        alt_pool = [
            d.id for d in snap.resources.values()
            if eligible(d) and d.id not in named
            and set(snap.resource_categories.get(d.id, [])) & alt_depts
            and (not gender or d.gender in (gender, None))
        ]

    horizon_end = date_to + timedelta(days=settings.tenant_next_bookable_horizon_days)
    data = await schedule.load(session, settings, now, candidates + alt_pool, date_from, horizon_end,
                               known=snap.resources)
    parts = settings.day_parts
    in_range = schedule.daterange(date_from, date_to)

    def resource_result(resource_id: str, *, report_gaps: bool) -> tuple[s.ResourceResult, tuple] | None:
        doc = snap.resources[resource_id]
        by_date = _LazyDays(lambda day: data.sessions(resource_id, day),
                            schedule.daterange(date_from, horizon_end))
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
        result = s.ResourceResult(
            resource=views.result_resource(doc, snap.categories_of(resource_id)),
            sessions=sessions,
            unavailable=unavailable if report_gaps or not sessions else [],
        )
        presence_rank = min((_PRESENCE_ORDER.get(si.presence or "", 9) for si in sessions), default=9)
        return result, (presence_rank if anyone else 0, soonest, doc.name)

    ranked = [x for d in candidates if (x := resource_result(d, report_gaps=bool(named)))]
    ranked.sort(key=lambda pair: pair[1])
    results = [pair[0] for pair in ranked[: body.max_resources]]

    def bookable(result: s.ResourceResult) -> bool:
        return any(si.bookable for si in result.sessions)

    alternatives: list[s.ResourceResult] = []
    if named and not any(bookable(x) for x in results):
        alts = [x for d in alt_pool if (x := resource_result(d, report_gaps=False))]
        alts.sort(key=lambda pair: pair[1])
        alternatives = [pair[0] for pair in alts if bookable(pair[0])][: body.max_resources]

    desk_only = bool(results) and all(
        snap.resources[x.resource.resource_id].booking_policy == "DESK_ONLY" for x in results
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
    resource_id: str | None,
    category: str | None,
    date_from: date,
    date_to: date,
    include_slots: bool,
    directory_cache: VersionedCache[DirectorySnapshot],
) -> s.AvailabilityList:
    now = schedule.now_in(settings)
    snap = await directory_cache.get(session)
    if resource_id:
        resource_ids = [resource_id] if resource_id in snap.resources else []
    elif category:
        wanted = category.casefold()
        cat_ids = {
            d.id for d in snap.categories.values()
            if wanted in {d.id.casefold(), (d.code or "").casefold(), d.name.casefold()}
        }
        resource_ids = [d for d, deps in snap.resource_categories.items() if set(deps) & cat_ids]
    else:
        resource_ids = [d.id for d in snap.resources.values() if d.active]
    data = await schedule.load(session, settings, now, resource_ids, date_from, date_to, known=snap.resources)
    items = [
        views.session_instance(v, include_slots=include_slots)
        for d in sorted(resource_ids)
        for day in schedule.daterange(date_from, date_to)
        for v in data.sessions(d, day, channel="DESK")
    ]
    return s.AvailabilityList(as_of=now, items=items)
