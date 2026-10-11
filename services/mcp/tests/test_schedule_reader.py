"""Shared retrieval tests at the real HTTP transport: ordering, limits, failure and cancellation."""
import asyncio
import random
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from pydantic import ValidationError

from frontdesk_mcp.cache import DirectoryCache
from frontdesk_mcp.clock import Deadline
from frontdesk_mcp.ops_client import OpsClient

from .test_availability_policy import NOW, policy


@pytest.mark.parametrize("values", [{"profile_batch_size": 0}, {"doctor_choice_limit": 0},
    {"profile_batch_size": 4, "ops_pool_max_connections": 3}, {"min_batch_headroom_seconds": -1}])
def test_invalid_search_bounds_are_refused(make_settings, values):
    with pytest.raises(ValidationError):
        make_settings(**values)


async def run_search(make_settings, *, statuses, delays=None, budget=0.3, repeat=False, total=None,
                     reverse=False, order_seed=None, capabilities=None):
    from frontdesk_mcp.schedule_reader import ScheduleReader
    p = policy()
    settings = make_settings(doctor_choice_limit=3, profile_batch_size=3)
    requests, active, peak = [], set(), [0]
    doctors = [{"id": str(i), "name": f"Doctor {i:02}", "active": True, "departments": [],
                "attendanceType": "ON_CALL" if status == "oncall" else "REGULAR"}
               for i, status in enumerate(statuses)]

    async def handle(request):
        path = request.url.path
        if path.endswith("/auth/token"):
            return httpx.Response(200, json={"access_token": "t", "token_type": "Bearer", "expires_in": 3600})
        if path.endswith("/capabilities"):
            return httpx.Response(200, json={"slots": {"enabled": False}} if capabilities is None else capabilities)
        if path.endswith("/doctors"):
            assert request.url.params["limit"] == "100"
            items = list(reversed(doctors)) if reverse else list(doctors)
            if order_seed is not None:
                random.Random(order_seed).shuffle(items)  # noqa: S311 — reproducible test permutations
            return httpx.Response(200, json={"items": items,
                                             "total": len(doctors) if total is None else total})
        assert "/availability" not in path, "future/working hours must not read today's board"
        i = int(path.rsplit("/", 1)[1])
        requests.append(i)
        active.add(i)
        peak[0] = max(peak[0], len(active))
        try:
            await asyncio.sleep((delays or {}).get(i, 0))
            if statuses[i] == "failure":
                return httpx.Response(503, json={})
            days = ["MON"] if statuses[i] == "match" else ["TUE"]
            return httpx.Response(200, json={**doctors[i], "usualSchedule": [
                {"label": "Morning", "daysOfWeek": days, "start": "09:00", "end": "12:00"}]})
        finally:
            active.remove(i)

    ops = OpsClient(settings, transport=httpx.MockTransport(handle))
    reader = ScheduleReader(ops, DirectoryCache(settings), settings)
    requested = p.resolve_date("2026-10-05", NOW, p.Purpose.AVAILABILITY)
    def evaluate(f):
        return p.decide_doctor(f, requested, session=None, now=NOW)
    try:
        start = time.monotonic()
        found = await reader.department("dept", None, requested, p.Purpose.AVAILABILITY,
                                        Deadline(budget), evaluate)
        elapsed = time.monotonic() - start
        first_requests = list(requests)
        if repeat:
            found = await reader.department("dept", None, requested, p.Purpose.AVAILABILITY,
                                            Deadline(budget), evaluate)
        assert not active
        return found, first_requests, requests, peak[0], elapsed
    finally:
        await ops.aclose()


async def test_stops_after_a_full_successful_batch_in_name_order(make_settings):
    found, first, _, peak, _ = await run_search(make_settings, statuses=["match"] * 8, reverse=True)
    assert first == [0, 1, 2] and peak <= 3
    assert found.search.matches_found == 3 and found.search.complete is False and found.total == 8
    assert [f.doctor.id for f in found.facts] == ["0", "1", "2"]


async def test_continues_to_later_batches_and_counts_all_matches_in_the_batch(make_settings):
    found, first, _, _, _ = await run_search(make_settings, statuses=["miss"] * 3 + ["match"] * 3)
    assert first == [0, 1, 2, 3, 4, 5]
    assert found.search.matches_found == 3 and found.search.complete is True


async def test_failed_read_keeps_search_incomplete(make_settings):
    found, _, _, _, _ = await run_search(make_settings, statuses=["failure", "miss"])
    assert found.search.complete is False and found.search.checked == 1
    p = policy()
    decisions = [p.decide_doctor(f, p.resolve_date("2026-10-05", NOW, p.Purpose.AVAILABILITY),
                                session=None, now=NOW) for f in found.facts]
    assert p.aggregate(decisions, found.search).reason == "SEARCH_INCOMPLETE"


async def test_deadline_cancels_batch_and_never_claims_unavailability(make_settings):
    found, first, _, peak, elapsed = await run_search(make_settings, statuses=["match"] * 5,
                                                     delays={0: .5, 1: .5, 2: .5}, budget=.08)
    assert first == [0, 1, 2] and peak <= 3 and elapsed < .15
    assert not found.search.complete and found.search.checked == 0 and found.search.matches_found == 0


async def test_headroom_prevents_a_new_batch(make_settings):
    found, first, _, _, _ = await run_search(make_settings, statuses=["match"] * 4, budget=.02)
    assert first == [] and found.search.complete is False


async def test_on_call_candidates_need_no_profile_reads(make_settings):
    found, first, _, _, _ = await run_search(make_settings, statuses=["oncall"] * 4)
    assert first == [] and found.search.complete is True and found.search.matches_found == 0


async def test_completed_profiles_are_cached(make_settings):
    found, first, repeated, _, _ = await run_search(make_settings, statuses=["miss"] * 4, repeat=True)
    assert first == [0, 1, 2, 3] and repeated == first and found.search.complete is True


async def test_directory_truncation_never_claims_complete(make_settings):
    found, _, _, _, _ = await run_search(make_settings, statuses=["miss"], total=101)
    assert found.total == 101 and found.search.complete is False


def test_facility_today_is_not_utc_today():
    p = policy()
    local = datetime(2026, 10, 2, 0, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert p.resolve_date("2026-10-02", local, p.Purpose.AVAILABILITY).kind == "TODAY"


async def test_twenty_owner_orders_produce_identical_sorted_candidates(make_settings):
    for seed in range(20):
        found, first, _, peak, _ = await run_search(make_settings, statuses=["match"] * 12, order_seed=seed)
        assert first == [0, 1, 2], seed
        assert [f.doctor.id for f in found.facts] == ["0", "1", "2"], seed
        assert found.search.matches_found == 3 and found.total == 12 and not found.search.complete
        assert peak <= 3


async def test_warm_cache_reaches_the_remaining_batch_after_cold_headroom_stop(make_settings):
    found, cold, all_reads, peak, elapsed = await run_search(
        make_settings, statuses=["miss"] * 6, delays={i: .04 for i in range(6)}, budget=.08, repeat=True)
    assert cold == [0, 1, 2]
    assert all_reads == [0, 1, 2, 3, 4, 5]
    assert found.search.complete and found.search.checked == 6 and found.search.matches_found == 0
    assert peak <= 3 and elapsed < .15


@pytest.mark.parametrize("date,with_summary,paths", [
    ("today", False, {"/doctors/doc_garima", "/availability", "/availability/doc_garima/slots"}),
    ("today", True, {"/availability", "/availability/doc_garima/slots"}),
    ("2026-10-05", False, {"/doctors/doc_garima", "/availability/doc_garima/slots"}),
    ("2026-10-05", True, {"/doctors/doc_garima", "/availability/doc_garima/slots"}),
])
async def test_selected_doctor_slot_reads_start_together(make_settings, date, with_summary, paths):
    from frontdesk_mcp import contract
    from frontdesk_mcp.schedule_reader import ScheduleReader

    from . import harness
    h = harness.build(make_settings())
    started, released = set(), asyncio.Event()

    async def owner(request):
        path = request.url.path.removeprefix("/api/v1")
        if path in paths:
            started.add(path)
            if started == paths:
                released.set()
            await released.wait()  # sequential reads cannot release the barrier
        return await h.ops.http._transport.handle_async_request(request)

    p = policy()
    requested = p.resolve_date(date, NOW, p.Purpose.AVAILABILITY)
    summary = contract.DoctorSummary.model_validate(h.ops_state.data["doctors"][0]) if with_summary else None
    try:
        async with OpsClient(h.settings, transport=httpx.MockTransport(owner)) as ops:
            reader = ScheduleReader(ops, h.cache, h.settings)
            facts = await reader.doctor("doc_garima", requested, p.Purpose.AVAILABILITY, Deadline(.3), summary)
        assert started == paths and facts.slots is None
        [slot] = [r for r in h.requests if r.url.path.endswith("/slots")]
        assert slot.method == "GET" and dict(slot.url.params) == {"date": requested.value.isoformat()}
    finally:
        await h.aclose()


async def test_selected_slots_are_uncached_and_enabled_plan_is_preserved(make_settings):
    from frontdesk_mcp.schedule_reader import ScheduleReader

    from . import harness
    h = harness.build(make_settings())
    p = policy()
    requested = p.resolve_date("today", NOW, p.Purpose.AVAILABILITY)
    reader = ScheduleReader(h.ops, h.cache, h.settings)
    try:
        first = await reader.doctor("doc_garima", requested, p.Purpose.AVAILABILITY, Deadline(.3))
        assert first.slots is None
        plan = harness.slot_plan()
        # Deliberately reverse the session list: only blocks within a session need ordered input.
        plan["sessions"].reverse()
        h.ops_state.set_slots("doc_garima", "2026-10-01", plan)
        second = await reader.doctor("doc_garima", requested, p.Purpose.AVAILABILITY, Deadline(.3))
        assert second.slots.model_dump(mode="json") == plan
        assert h.ops_paths().count("/availability/doc_garima/slots") == 2
        assert h.ops_paths().count("/doctors/doc_garima") == 1
    finally:
        await h.aclose()


@pytest.mark.parametrize("issue", ["doctor", "date", "duplicate", "blank", "overlap"])
@pytest.mark.parametrize("enabled", [False, True])
async def test_slot_consistency_is_checked_before_disabled_plan_is_discarded(make_settings, issue, enabled):
    from frontdesk_mcp.ops_client import Malformed
    from frontdesk_mcp.schedule_reader import ScheduleReader

    from . import harness
    h = harness.build(make_settings())
    p = policy()
    requested = p.resolve_date("today", NOW, p.Purpose.AVAILABILITY)
    h.ops_state.set_slots("doc_garima", "2026-10-01", harness.inconsistent_slot_plan(issue) | {"enabled": enabled})
    try:
        with pytest.raises(Malformed) as caught:
            await ScheduleReader(h.ops, h.cache, h.settings).slots("doc_garima", requested, Deadline(.3))
        assert caught.value.stage == "slots"
    finally:
        await h.aclose()


@pytest.mark.parametrize("failed_paths,winner", [
    (["/doctors/doc_garima", "/availability", "/availability/doc_garima/slots"], "profile"),
    (["/availability", "/availability/doc_garima/slots"], "board"),
])
async def test_slot_parallel_failure_order_preserves_profile_then_board(make_settings, failed_paths, winner):
    from frontdesk_mcp.ops_client import Unavailable
    from frontdesk_mcp.schedule_reader import ScheduleReader

    from . import harness
    h = harness.build(make_settings())
    seen = set()

    async def owner(request):
        path = request.url.path.removeprefix("/api/v1")
        if path in failed_paths:
            seen.add(path)
            return httpx.Response(503)
        return await h.ops.http._transport.handle_async_request(request)

    p = policy()
    requested = p.resolve_date("today", NOW, p.Purpose.AVAILABILITY)
    try:
        async with OpsClient(h.settings, transport=httpx.MockTransport(owner)) as ops:
            with pytest.raises(Unavailable) as caught:
                await ScheduleReader(ops, h.cache, h.settings).doctor(
                    "doc_garima", requested, p.Purpose.AVAILABILITY, Deadline(.3))
        assert caught.value.stage == winner and seen == set(failed_paths)
    finally:
        await h.aclose()


@pytest.mark.parametrize("day,paths", [
    ("today", {"/doctors", "/availability", "/capabilities"}),
    ("2026-10-05", {"/doctors", "/capabilities"}),
])
@pytest.mark.parametrize("enabled", [False, True])
async def test_department_capabilities_share_first_parallel_step_and_mark_every_candidate(make_settings, day, paths,
                                                                                        enabled):
    from frontdesk_mcp.schedule_reader import ScheduleReader

    from . import harness
    h = harness.build(make_settings())
    h.ops_state.capabilities["slots"]["enabled"] = enabled
    oncall = next(d for d in h.ops_state.data["doctors"] if d["id"] == "doc_vikram_desai")
    oncall["departments"] = [{"id": "dept_genmed", "name": "General Medicine"}]
    started, released = set(), asyncio.Event()

    async def owner(request):
        path = request.url.path.removeprefix("/api/v1")
        if path in paths:
            started.add(path)
            if started == paths:
                released.set()
            await released.wait()
        if path.startswith("/doctors/"):
            assert released.is_set(), "profiles follow the first parallel group"
        return await h.ops.http._transport.handle_async_request(request)

    p = policy()
    requested = p.resolve_date(day, NOW, p.Purpose.AVAILABILITY)
    try:
        async with OpsClient(h.settings, transport=httpx.MockTransport(owner)) as ops:
            found = await ScheduleReader(ops, h.cache, h.settings).department(
                "dept_genmed", None, requested, p.Purpose.AVAILABILITY, Deadline(.3),
                lambda f: p.decide_doctor(f, requested, session=None, now=NOW))
        assert started == paths and found.total == 3 and len(found.facts) == 3
        assert all(isinstance(f.slots, p.SlotsNotRead) if enabled else f.slots is None for f in found.facts)
        assert found.search.matches_found == (3 if day == "today" else 2) and found.search.complete
        assert not any(path.endswith("/slots") for path in h.ops_paths())
        assert "/doctors/doc_vikram_desai" not in h.ops_paths()
    finally:
        await h.aclose()


@pytest.mark.parametrize("day", ["today", "2026-10-05"])
@pytest.mark.parametrize("ttl,reads", [(300, 1), (0, 2)])
async def test_department_sequential_capability_cache_reuse_and_zero_ttl(make_settings, day, ttl, reads):
    from frontdesk_mcp.schedule_reader import ScheduleReader

    from . import harness
    h = harness.build(make_settings(directory_cache_seconds=ttl))
    reader, p = ScheduleReader(h.ops, h.cache, h.settings), policy()
    requested = p.resolve_date(day, NOW, p.Purpose.AVAILABILITY)
    try:
        assert "/capabilities" not in h.ops_paths(), "constructing a reader does not fetch capabilities"
        for _ in range(2):
            found = await reader.department("dept_genmed", None, requested, p.Purpose.AVAILABILITY, Deadline(.3),
                                            lambda f: p.decide_doctor(f, requested, session=None, now=NOW))
            assert found.search.matches_found == 2
        assert h.ops_paths().count("/capabilities") == reads
    finally:
        await h.aclose()


async def test_capability_cache_expiry_and_eviction_refetch_current_owner_flag(make_settings):
    from frontdesk_mcp.schedule_reader import ScheduleReader

    from . import harness
    h = harness.build(make_settings(directory_cache_seconds=10, directory_cache_max_entries=1))
    tick = [0.0]
    reader = ScheduleReader(h.ops, DirectoryCache(h.settings, monotonic=lambda: tick[0]), h.settings)
    try:
        assert not (await reader.capabilities(Deadline(.3))).slots.enabled
        h.ops_state.capabilities["slots"]["enabled"] = True
        assert not (await reader.capabilities(Deadline(.3))).slots.enabled
        tick[0] = 10.0
        assert (await reader.capabilities(Deadline(.3))).slots.enabled
        await reader.departments(Deadline(.3))  # the other directory entry evicts the capability value
        h.ops_state.capabilities["slots"]["enabled"] = False
        assert not (await reader.capabilities(Deadline(.3))).slots.enabled
        assert h.ops_paths().count("/capabilities") == 3
    finally:
        await h.aclose()


@pytest.mark.parametrize("day", ["today", "2026-10-05"])
async def test_concurrent_cold_department_searches_may_each_read_capabilities(make_settings, day):
    from frontdesk_mcp.schedule_reader import ScheduleReader

    from . import harness
    h = harness.build(make_settings())
    entered, release = [], asyncio.Event()

    async def owner(request):
        if request.url.path.endswith("/capabilities"):
            entered.append(request)
            if len(entered) == 2:
                release.set()
            await release.wait()
        return await h.ops.http._transport.handle_async_request(request)

    p = policy()
    requested = p.resolve_date(day, NOW, p.Purpose.AVAILABILITY)
    try:
        async with OpsClient(h.settings, transport=httpx.MockTransport(owner)) as ops:
            reader = ScheduleReader(ops, h.cache, h.settings)
            results = await asyncio.gather(*(reader.department(
                "dept_genmed", None, requested, p.Purpose.AVAILABILITY, Deadline(.3),
                lambda f: p.decide_doctor(f, requested, session=None, now=NOW)) for _ in range(2)))
        assert len(entered) == 2 and all(r.search.matches_found == 2 for r in results)
    finally:
        await h.aclose()


async def test_enabled_department_match_counts_stop_at_the_same_profile_batch(make_settings):
    found, first, _, peak, _ = await run_search(make_settings, statuses=["match"] * 8,
                                               capabilities={"slots": {"enabled": True}})
    assert first == [0, 1, 2] and peak <= 3
    assert found.search.matches_found == 3 and not found.search.complete
    assert all(isinstance(f.slots, policy().SlotsNotRead) for f in found.facts)
