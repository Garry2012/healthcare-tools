"""Shared retrieval tests at the real HTTP transport: ordering, limits, failure and cancellation."""
import asyncio
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


async def run_search(make_settings, *, statuses, delays=None, budget=0.3, repeat=False, total=None, reverse=False):
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
        if path.endswith("/doctors"):
            assert request.url.params["limit"] == "100"
            return httpx.Response(200, json={"items": list(reversed(doctors)) if reverse else doctors,
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
    assert found.search.bookable_found == 3 and found.search.complete is False and found.total == 8
    assert [f.doctor.id for f in found.facts] == ["0", "1", "2"]


async def test_continues_to_later_batches_and_counts_all_matches_in_the_batch(make_settings):
    found, first, _, _, _ = await run_search(make_settings, statuses=["miss"] * 3 + ["match"] * 3)
    assert first == [0, 1, 2, 3, 4, 5]
    assert found.search.bookable_found == 3 and found.search.complete is True


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
    assert not found.search.complete and found.search.checked == 0 and found.search.bookable_found == 0


async def test_headroom_prevents_a_new_batch(make_settings):
    found, first, _, _, _ = await run_search(make_settings, statuses=["match"] * 4, budget=.02)
    assert first == [] and found.search.complete is False


async def test_on_call_candidates_need_no_profile_reads(make_settings):
    found, first, _, _, _ = await run_search(make_settings, statuses=["oncall"] * 4)
    assert first == [] and found.search.complete is True and found.search.bookable_found == 0


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
