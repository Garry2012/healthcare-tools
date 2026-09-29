"""Availability completeness across the domain result, the staff REST view and the agent REST view.

Property under test (docs/review/REVIEW.md, R-01): every slot that the specification makes
bookable for phone callers must reach the caller. It may be removed only by a rule the contract
states (booked, walk-in reserve, reachability today, day part asked for); never by an unstated
cut-off. Expected slots come from tests/review/oracle.py (the contract formulas), never from the
service's own helpers.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from ..conftest import STAFF, book_body, call, search_body, search_sessions
from ..oracle import (
    SessionSpec,
    expected_offered,
    expected_reserve,
    expected_sequence_windows,
    expected_total,
    minutes_of,
    window_overlaps,
)

pytestmark = pytest.mark.postgres
NAME = "Dr Zenobia Quillfeather"

# Session length × throughput × capacity model × reserve. Chosen so that the number of phone
# positions ranges from 2 to 36 and intervals from 5 to 30 minutes (and one 7.5-minute case).
SEQUENCE_CASES = {
    "2h-4ph-25pct (calibration shape)": SessionSpec("15:00", "17:00", mode="PER_HOUR", value=4, reserve_percent=25),
    "1h-2ph-0pct": SessionSpec("09:00", "10:00", mode="PER_HOUR", value=2),
    "3h-6ph-20pct": SessionSpec("10:00", "13:00", mode="PER_HOUR", value=6, reserve_percent=20),
    "4h-8ph-10pct": SessionSpec("08:00", "12:00", mode="PER_HOUR", value=8, reserve_percent=10),
    "3h-12ph-0pct": SessionSpec("16:00", "19:00", mode="PER_HOUR", value=12),
    "2h30-fixed10-20pct": SessionSpec("14:00", "16:30", mode="FIXED", value=10, reserve_percent=20),
    "2h-fixed16-0pct (7.5 min)": SessionSpec("09:00", "11:00", mode="FIXED", value=16),
    "3h-default-0pct": SessionSpec("14:00", "17:00", mode="DEFAULT", value=None),
    "90m-fixed3-50pct": SessionSpec("18:00", "19:30", mode="FIXED", value=3, reserve_percent=50),
}


def _only_session(items: list[dict]) -> dict:
    live = [i for i in items if i["status"] != "CANCELLED"]
    assert len(live) == 1, items
    return live[0]


def _available(session: dict) -> dict[str, dict]:
    return {s["slotId"]: s for s in session.get("slots") or [] if s["available"]}


def _window(slot: dict) -> tuple[str, str]:
    w = slot.get("expectedWindow")
    return (w["from"], w["to"]) if w else (slot["start"], slot["end"])


async def _search(client, day, **extra) -> dict:
    r = await client.post("/agent/availability-search", headers=call(), json=search_body(NAME, day, **extra))
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("spec", SEQUENCE_CASES.values(), ids=SEQUENCE_CASES.keys())
async def test_staff_view_matches_the_contract_formulas(desk, clock, spec):
    """Domain + staff REST: totals, reserve, positions and windows exactly as the contract states."""
    built = await desk.resource(NAME, {"s1": spec})
    day = clock.today + timedelta(days=1)
    session = _only_session(await desk.availability(built.resource_id, day))

    assert session["capacity"]["total"] == expected_total(spec)
    assert session["capacity"]["walkInReserve"] == expected_reserve(expected_total(spec), spec.reserve_percent)
    assert session["capacity"]["remaining"] == expected_offered(spec)
    windows = expected_sequence_windows(spec)
    got = {s["position"]: _window(s) for s in session["slots"]}
    assert got == windows, "positions or windows differ from boundary(n) = start + floor(n x interval)"
    assert all(s["available"] for s in session["slots"])


@pytest.mark.parametrize("spec", SEQUENCE_CASES.values(), ids=SEQUENCE_CASES.keys())
async def test_agent_search_returns_every_bookable_position(client, desk, clock, spec):
    """Nothing is booked: every non-reserved position must reach the agent, or the response must
    say that some were left out. `capacity.remaining` alone does not tell the agent *which*."""
    built = await desk.resource(NAME, {"s1": spec})
    day = clock.today + timedelta(days=1)
    staff_ids = set(_available(_only_session(await desk.availability(built.resource_id, day))))

    body = await _search(client, day)
    assert body["outcome"] == "FOUND", body
    (session,) = search_sessions(body)
    agent_ids = set(_available(session))

    assert agent_ids <= staff_ids, "the agent was offered a slot the schedule does not have"
    assert len(staff_ids) == expected_offered(spec)
    missing = sorted(staff_ids - agent_ids)
    assert not missing, (
        f"{len(missing)} of {len(staff_ids)} bookable positions silently omitted from the agent response "
        f"(remaining={session['capacity']['remaining']}); last offered window "
        f"{max((_window(s) for s in session['slots']), default=None)} vs session end {session['end']}; "
        f"first missing {missing[0]}, last missing {missing[-1]}")


async def test_booked_early_positions_do_not_hide_later_ones(client, desk, clock):
    """Existing bookings at the front of the queue: the rest of the queue is still offered."""
    spec = SessionSpec("15:00", "17:00", mode="PER_HOUR", value=4, reserve_percent=25)
    built = await desk.resource(NAME, {"s1": spec})
    day = clock.today + timedelta(days=1)
    staff = _only_session(await desk.availability(built.resource_id, day))
    ordered = sorted(_available(staff).values(), key=lambda s: s["position"])
    for i, slot in enumerate(ordered[:2]):
        r = await client.post("/agent/bookings", headers=call(key=f"k{i}", call_id=f"c{i}"),
                              json=book_body(slot["slotId"], name=f"Early Patient {i}", phone=f"98123000{i:02d}"))
        assert r.status_code == 201, r.text

    body = await _search(client, day)
    (session,) = search_sessions(body)
    expected = {s["slotId"] for s in ordered[2:]}
    assert session["capacity"]["remaining"] == len(expected) == 4
    assert set(_available(session)) == expected


async def test_day_part_offers_slots_inside_the_part_asked_for(client, desk, clock, review_settings):
    """'Evening' for a session that straddles the day-part boundary: the agent must get the
    evening positions, not the first positions of the session (which are in the afternoon)."""
    spec = SessionSpec("15:00", "19:00", mode="PER_HOUR", value=4)
    await desk.resource(NAME, {"s1": spec})
    day = clock.today + timedelta(days=1)
    lo, hi = (t.strftime("%H:%M") for t in review_settings.day_parts["EVENING"])

    body = await _search(client, day, when={"dateFrom": day.isoformat(), "dateTo": day.isoformat(),
                                            "dayPart": "EVENING"})
    (session,) = search_sessions(body)
    offered = list(_available(session).values())
    in_part = {p for p, w in expected_sequence_windows(spec).items() if window_overlaps(w, lo, hi)}

    outside = [(_window(s), s["position"]) for s in offered if not window_overlaps(_window(s), lo, hi)]
    assert not outside, f"asked for EVENING ({lo}-{hi}); offered windows outside it: {outside}"
    assert {s["position"] for s in offered} == in_part


async def test_same_day_offers_every_reachable_position(client, desk, clock):
    """Today at 15:40: positions whose window already closed are withheld (S8), every later one
    is still offered."""
    spec = SessionSpec("15:00", "17:00", mode="PER_HOUR", value=6, reserve_percent=0)
    built = await desk.resource(NAME, {"s1": spec})
    clock.set(clock.now.replace(hour=15, minute=40))
    now = minutes_of("15:40")
    reachable = {p for p, (lo, hi) in expected_sequence_windows(spec).items() if minutes_of(hi) > now}

    staff = _only_session(await desk.availability(built.resource_id, clock.today))
    assert {s["position"] for s in _available(staff).values()} == reachable

    body = await _search(client, clock.today)
    (session,) = search_sessions(body)
    assert {s["position"] for s in _available(session).values()} == reachable


async def test_every_returned_slot_belongs_to_its_session_and_lies_within_it(client, desk, clock):
    spec = SessionSpec("10:00", "13:00", mode="PER_HOUR", value=6, reserve_percent=20)
    await desk.resource(NAME, {"s1": spec, "s2": SessionSpec("17:00", "19:00", mode="FIXED", value=8)})
    day = clock.today + timedelta(days=1)
    body = await _search(client, day)
    sessions = search_sessions(body)
    assert len(sessions) == 2
    for session in sessions:
        for slot in session["slots"]:
            assert slot["slotId"].startswith(f"slot_{session['sessionId']}_")
            lo, hi = _window(slot)
            assert session["start"] <= lo < hi <= session["end"], (session["sessionId"], slot)


async def test_category_search_represents_every_bookable_doctor_of_the_category(client, desk, clock):
    """Same property one level up: 'any skin doctor tomorrow' must not silently drop doctors of
    that department who can be booked (maxResources defaults to 3 and the MCP tool cannot set it)."""
    spec = SessionSpec("10:00", "12:00", mode="PER_HOUR", value=4)
    names = ["Dr Quintessa Marlowe", "Dr Bartholomew Fenwick", "Dr Philippa Ashgrove", "Dr Leopold Hawthorne",
             "Dr Evangeline Thistlewood"]
    for name in names:
        await desk.resource(name, {"s1": spec}, category="cat_derm")
    day = clock.today + timedelta(days=1)
    r = await client.get("/resources", headers=STAFF, params={"category": "cat_derm", "limit": 100})
    in_category = [x["id"] for x in r.json()["items"]]
    bookable = []
    for resource_id in in_category:
        sessions = await desk.availability(resource_id, day)
        if any(s["bookable"] and _available(s) for s in sessions):
            bookable.append(resource_id)
    assert len(bookable) >= len(names)

    body = (await client.post("/agent/availability-search", headers=call(), json={
        "utterance": "any skin doctor tomorrow", "language": "en", "category": "skin doctor",
        "when": {"dateFrom": day.isoformat(), "dateTo": day.isoformat()}})).json()
    assert [c["id"] for c in body["understood"]["categories"]] == ["cat_derm"]
    shown = {res["resource"]["resourceId"] for res in body["results"] if any(s["bookable"] for s in res["sessions"])}
    missing = sorted(set(bookable) - shown)
    assert not missing, f"{len(missing)} of {len(bookable)} bookable dermatologists silently left out: {missing}"
