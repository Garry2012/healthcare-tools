"""Tool round-trip latency: agent → MCP (streamable HTTP over TCP) → owner service(s) → result.

Default: the in-process development stubs (fixture timings, NOT production evidence). With
BENCH_OPS_BASE_URL (and optionally BENCH_KNOWLEDGE_BASE_URL + credentials) the adapter is pointed at
real hosts and the same scenarios are measured there. Reports p50/p95/p99, failures and the boundary.

    uv run python dev/bench.py [--samples 50] [--concurrency 1]
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import statistics
import sys
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from conftest import serving  # noqa: E402
from gates import GateFailure, assert_authenticated_write_tenant  # noqa: E402
from harness import slot_plan  # noqa: E402

from frontdesk_mcp.clock import Deadline, FixedClock, SystemClock  # noqa: E402
from frontdesk_mcp.config import Settings  # noqa: E402
from frontdesk_mcp.ops_client import OpsClient  # noqa: E402
from frontdesk_mcp.server import create_app  # noqa: E402
from frontdesk_stubs import knowledge as knowledge_stub  # noqa: E402
from frontdesk_stubs import ops as ops_stub  # noqa: E402

# name → (tool, arguments, outcomes that count as the intended success, owner paths the call must have hit:
#          only the owner paths needed by that tool)
# Directory values the scenarios need. Defaults are the development fixtures; a real host needs its own
# (BENCH_DOCTOR_ID: a doctor id; BENCH_DOCTOR_NAME: a name matching exactly one doctor; BENCH_AMBIGUOUS_NAME:
# a name matching several; BENCH_DEPARTMENT: a department name present in the tenant).
DOCTOR_ID = os.environ.get("BENCH_DOCTOR_ID", "doc_garima")
DOCTOR_NAME = os.environ.get("BENCH_DOCTOR_NAME", "garima")
AMBIGUOUS_NAME = os.environ.get("BENCH_AMBIGUOUS_NAME", "sharma")
DEPARTMENT = os.environ.get("BENCH_DEPARTMENT", "cardiology")
SCENARIOS = {
    "availability_known_doctor": ("get_doctor_availability", {"doctorId": DOCTOR_ID, "date": "today"},
                                  {"AVAILABILITY", "CALLBACK_REQUIRED"}, ("GET /availability",)),
    "availability_name_search": ("get_doctor_availability", {"doctorName": DOCTOR_NAME, "date": "today"},
                                 {"AVAILABILITY", "CALLBACK_REQUIRED"}, ("GET /doctors", "GET /availability")),
    "availability_ambiguous": ("get_doctor_availability", {"doctorName": AMBIGUOUS_NAME, "date": "today"},
                               {"CLARIFICATION_NEEDED"}, ("GET /doctors",)),
    # departments are cached across samples: the board is the per-call owner read that must be observed
    "availability_department": ("get_doctor_availability", {"departmentName": DEPARTMENT, "date": "today"},
                                {"AVAILABILITY", "CALLBACK_REQUIRED"}, ("GET /availability",)),
    "knowledge_answer": ("search_knowledge", {"question": "parking", "language": "en"}, {"ANSWERED", "NO_ANSWER"},
                         ("POST /v1/answer",)),
    "booking_list": ("manage_booking", {"action": "LIST"}, {"FOUND", "NOT_FOUND"}, ("GET /appointments",)),
    "booking_create": ("manage_booking", {"action": "CREATE", "patientName": "Bench Patient",
                                          "patientMobile": "9000000101", "doctorId": DOCTOR_ID, "visitDate": "today",
                                          "callerConfirmed": True},
                       {"NOTED"}, ("GET /availability", "POST /appointments")),
}


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))]


OWNER_CALLS: list[tuple[str, str]] = []  # (call id, path) seen by the recording transports (stub mode only)
BUDGET_MS = 300.0  # the in-call tool share (config default): samples above it are reported separately


async def measure(base: str, name: str, tool: str, args: dict, expected: set[str], paths: tuple[str, ...],
                  i: int, sem: asyncio.Semaphore, check: Callable[[dict], object] | None = None) -> float | str:
    """One tool round trip in ms when the outcome is the scenario's intended success AND the intended owner
    operation was observed (stub mode); otherwise the outcome/detail label, counted as a rejected sample."""
    call_id = f"bench-{name}-{i}"
    headers = {"Authorization": "Bearer gateway", "X-Call-Id": call_id, "X-Operation-Id": f"{call_id}-op",
               "X-Caller-Number": "+919000000101", "X-Caller-Verification": "SIP_CALLER_ID"}
    async with sem, Client(StreamableHttpTransport(f"{base}/mcp/", headers=headers)) as c:
        started = time.perf_counter()
        result = await c.call_tool(tool, args, raise_on_error=False)
        elapsed = (time.perf_counter() - started) * 1000
    body = result.structured_content or {}
    if result.is_error:
        return "TOOL_ERROR"
    outcome = body.get("outcome")
    if outcome not in expected:
        return f"{outcome}:{body.get('detail')}"
    if check is not None and not check(body):
        return f"{outcome}:result check failed"
    if RECORDING_OWNER_CALLS:
        seen = [path for cid, path in OWNER_CALLS if cid == call_id]  # attributed by call id, safe under concurrency
        if tool == "get_doctor_availability":
            department = args.get("departmentId") or args.get("departmentName")
            if department and any(path.endswith("/slots") for path in seen):
                return "WRONG_OWNER_READ:department called slots"
            if not department and "GET /capabilities" in seen:
                return "WRONG_OWNER_READ:selected doctor called capabilities"
            if args.get("date") != "today" and "GET /availability" in seen:
                return "WRONG_OWNER_READ:future called the live board"
        for path in paths:
            if path not in seen:
                return f"{outcome}:owner call {path} not observed"
    return elapsed


RECORDING_OWNER_CALLS = False


async def selected_scenarios(settings: Settings, *, external: bool) -> dict:
    """External benchmarking is read-only unless explicitly bound to an owner-designated test tenant."""
    if not external:
        return SCENARIOS
    if os.environ.get("BENCH_ALLOW_WRITES") != "1":
        return {name: scenario for name, scenario in SCENARIOS.items() if name != "booking_create"}
    if os.environ.get("OPS_E2E_MODE") != "live":
        raise GateFailure("BLOCKED: write benchmarking requires OPS_E2E_MODE=live and a synthetic tenant")
    ops = OpsClient(settings)
    try:
        await assert_authenticated_write_tenant(ops, os.environ.get("BENCH_WRITE_TENANT", ""))
    finally:
        await ops.aclose()
    return SCENARIOS


async def run(base: str, samples: int, concurrency: int, scenarios: dict) -> dict:
    report: dict = {}
    for name, (tool, args, expected, paths, *checks) in scenarios.items():
        sem = asyncio.Semaphore(concurrency)
        start = len(OWNER_CALLS)
        results = await asyncio.gather(*(measure(base, name, tool, args, expected, paths, i, sem,
                                                checks[0] if checks else None) for i in range(samples)))
        report[name] = {**summarise(results, expected, paths), "observed_owner_calls": observed_calls(start),
                        "arguments": {k: v for k, v in args.items()
                                      if k in {"doctorId", "date", "visitDate", "session", "preferredTime"}}}
    return report


def observed_calls(start: int) -> dict | None:
    return dict(Counter(path for _, path in OWNER_CALLS[start:])) if RECORDING_OWNER_CALLS else None


def open_blocks(body: dict) -> list[dict]:
    return [block for doctor in body.get("doctors", [])
            for session in [*doctor["board"], *(doctor["usualSessions"] or [])]
            for block in session["openSlots"] or []]


async def prepare_booking(base: str, scenario: tuple, mode: str) -> tuple[tuple | None, dict]:
    """Untimed availability selects the offered time; a missing block never falls back to a day-level write."""
    tool, args, expected, paths = scenario
    started = time.perf_counter()
    async with Client(StreamableHttpTransport(f"{base}/mcp/", headers={
            "Authorization": "Bearer gateway", "X-Call-Id": f"bench-prepare-{mode}"})) as client:
        result = await client.call_tool("get_doctor_availability", {
            "doctorId": args["doctorId"], "date": args["visitDate"]}, raise_on_error=False)
    preparation = {"elapsed_ms": (time.perf_counter() - started) * 1000, "timed_in_booking": False,
                   "outcome": (result.structured_content or {}).get("outcome")}
    if result.is_error:
        return None, {**preparation, "failure": "TOOL_ERROR"}
    body = result.structured_content or {}
    if mode == "enabled":
        blocks = open_blocks(body)
        if not blocks:
            return None, {**preparation, "failure": "NO_OPEN_BLOCK"}
        args = {**args, "preferredTime": blocks[0]["start"]}
        preparation["selected_time"] = blocks[0]["start"]
    elif RECORDING_OWNER_CALLS:
        # The disabled stub day has mixed session decisions. Choose an offered session, not an invented time.
        session = next((s["session"] for d in body.get("doctors", []) for s in d["board"]
                        if s["decision"] == "APPOINTMENT_REQUEST"), None)
        if session:
            args = {**args, "session": session}
    return (tool, args, expected, paths), preparation


def summarise(results: list[float | str], expected: set[str], paths: tuple[str, ...]) -> dict:
    samples = len(results)
    timings = [r for r in results if isinstance(r, float)]
    failed = [r for r in results if isinstance(r, str)]
    failures = len(failed)
    outcomes = {}
    for r in results:
        label = r if isinstance(r, str) else "ok"
        outcomes[label] = outcomes.get(label, 0) + 1
    return {"samples": samples, "ok": len(timings), "rejected_or_failed": failures,
                    "over_budget_ms": BUDGET_MS, "over_budget": sum(1 for t in timings if t > BUDGET_MS),
                    "expected_outcomes": sorted(expected), "required_owner_calls": list(paths),
                    "outcomes": outcomes,
                    "first_call_ms": (round(results[0], 1) if isinstance(results[0], float) else results[0])
                                     if results else None,
                    "p50_ms": round(percentile(timings, 50), 1) if timings else None,
                    "p95_ms": round(percentile(timings, 95), 1) if timings else None,
                    "p99_ms": round(percentile(timings, 99), 1) if timings else None,
                    "mean_ms": round(statistics.fmean(timings), 1) if timings else None}


def preparation_failure(evidence: dict, paths: tuple[str, ...]) -> dict:
    return {**summarise([], {"NOTED"}, paths), "preparation_failure": evidence["failure"]}


async def department_cache_modes(app, base: str, samples: int, *, query: dict, name: str,
                                 expected: set[str]) -> dict:
    # Cache is reset only in this local benchmark adapter, never on an owner service.
    report = {}
    sem = asyncio.Semaphore(1)  # serialize cache experiments so one sample cannot warm another
    for mode in ("cold", "warm"):
        scenario_name = f"{name}_{mode}"
        paths = ("GET /doctors", "GET /availability") if query["date"] == "today" else ("GET /doctors",)
        if mode == "cold":
            paths += ("GET /capabilities",)
        results = []
        start = len(OWNER_CALLS)
        for i in range(samples):
            if mode == "cold":
                app.state.services.cache.clear()
            results.append(await measure(base, scenario_name, "get_doctor_availability", query,
                                         expected, paths, i, sem))
        report[scenario_name] = {**summarise(results, expected, paths),
                        "cache_mode": mode, "concurrency": 1,
                        "observed_owner_calls": observed_calls(start),
                        "profile_reads": sum(path.startswith("GET /doctors/")
                                             for _, path in OWNER_CALLS[start:]) if RECORDING_OWNER_CALLS else None}
    return report


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"), default="WARNING")
    parser.add_argument("--log-file", type=Path)
    args = parser.parse_args()
    if args.samples < 1 or args.concurrency < 1:
        parser.error("samples and concurrency must be positive")
    if args.log_level in {"DEBUG", "INFO"} and not args.log_file:
        parser.error("--log-level below WARNING requires --log-file")
    real_ops = os.environ.get("BENCH_OPS_BASE_URL")
    # With real operational hosts but no knowledge host yet, keep the in-process knowledge stub so knowledge
    # answer samples remain labelled fixtures. Scheduling never uses that stub.
    knowledge_stub_with_real_ops = bool(real_ops) and not os.environ.get("BENCH_KNOWLEDGE_BASE_URL")
    settings = Settings(
        env="development", log_level=args.log_level, provider_id="demo-hospital", domain_pack="healthcare",
        tenant_supported_languages="en,kn,hi",
        tenant_timezone="Asia/Kolkata", tenant_country_calling_code="91",
        ops_base_url=real_ops or "http://ops-stub.local/api/v1",
        ops_client_id=os.environ.get("BENCH_OPS_CLIENT_ID") or os.environ.get("OPS_E2E_CLIENT_ID", "mcp-dev"),
        ops_client_secret=(os.environ.get("BENCH_OPS_CLIENT_SECRET")
                           or os.environ.get("OPS_E2E_CLIENT_SECRET", "dev-secret")),
        knowledge_base_url=os.environ.get("BENCH_KNOWLEDGE_BASE_URL") or "http://knowledge-stub.local",
        knowledge_bearer_token=os.environ.get("BENCH_KNOWLEDGE_BEARER_TOKEN") or "dev-knowledge-secret",
        mcp_bearer_token="gateway",
        allow_budget_overrides=bool(real_ops),  # only distant real-host diagnostics exceed the in-call budget
        read_deadline_seconds=float(os.environ.get("BENCH_READ_DEADLINE", "2.0")) if real_ops else None,
        write_deadline_seconds=max(4.0, float(os.environ.get("BENCH_READ_DEADLINE", "2.0"))) if real_ops else None,
        summary_deadline_seconds=max(8.0, float(os.environ.get("BENCH_READ_DEADLINE", "2.0"))))
    if real_ops:
        knowledge = settings.knowledge_base_url
        if knowledge_stub_with_real_ops:
            knowledge = "in-process knowledge STUB (no real host yet)"
        boundary = f"laptop → MCP (local TCP) → {real_ops} (real network); knowledge: {knowledge}"
        ops_transport = None
        kb_state = knowledge_stub.KnowledgeStubState(bearer="dev-knowledge-secret")
        knowledge_transport = None
        if knowledge_stub_with_real_ops:
            knowledge_transport = httpx.ASGITransport(app=knowledge_stub.create_app(kb_state))
        clock = SystemClock()
    else:
        boundary = "laptop → MCP (local TCP) → in-process stubs (ASGI, no network): fixture timings only"
        clock = FixedClock(datetime(2026, 10, 1, 4, 30, tzinfo=UTC))
        scopes = {"appointments.write", "calls.write"}
        ops_state = ops_stub.OpsStubState(clock=clock, clients={"mcp-dev": ("dev-secret", scopes)})

        class Recording(httpx.AsyncBaseTransport):
            """Attributes each owner request to the MCP call that caused it (callId travels in request bodies for
            the knowledge service; operational requests are matched through the adapter's call-id contextvar)."""

            def __init__(self, app):
                self.inner = httpx.ASGITransport(app=app)

            async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
                from frontdesk_mcp.context import call_id_var

                prefix = httpx.URL(settings.ops_base_url).path.rstrip("/")
                OWNER_CALLS.append((call_id_var.get() or "",
                                    f"{request.method} {request.url.path.removeprefix(prefix)}"))
                return await self.inner.handle_async_request(request)

        global RECORDING_OWNER_CALLS
        RECORDING_OWNER_CALLS = True
        ops_transport = Recording(ops_stub.create_app(ops_state, prefix="/api/v1"))
        kb_state = knowledge_stub.KnowledgeStubState(bearer="dev-knowledge-secret")
        knowledge_transport = Recording(knowledge_stub.create_app(kb_state))
    scenarios = await selected_scenarios(settings, external=bool(real_ops))
    omitted = {name: "external writes disabled" for name in SCENARIOS if name not in scenarios}
    scenarios = {
        name: (tool, {**values, "visitDate": os.environ.get("BENCH_VISIT_DATE") or
                      clock.now().astimezone(settings.zone).date().isoformat()}, expected, paths)
        if values.get("visitDate") == "today" else (tool, values, expected, paths)
        for name, (tool, values, expected, paths) in scenarios.items()
    }
    app = create_app(settings, ops_transport=ops_transport, knowledge_transport=knowledge_transport, clock=clock)
    with contextlib.ExitStack() as log_files:
        if args.log_file:
            stream = log_files.enter_context(args.log_file.open("w", encoding="utf-8"))
            handlers = logging.getLogger().handlers
            assert len(handlers) == 1, "benchmark requires exactly one root log handler"
            handler = handlers[0]  # create_app owns the root JSON handler
            previous = handler.setStream(stream)
            log_files.callback(handler.setStream, previous)
        future_date = os.environ.get("BENCH_FUTURE_DATE") if real_ops else "2026-10-05"
        workload_scenarios = len(scenarios) + (2 if future_date else 0) + (0 if real_ops else 6)
        watchdog_limit = args.samples * workload_scenarios * max(
            settings.read_deadline_seconds, settings.write_deadline_seconds) + 30
        preparation = {}
        async with serving(app, watchdog_limit=watchdog_limit) as base:
            # warm: first call pays token + pool + schema
            async with Client(StreamableHttpTransport(
                    f"{base}/mcp/", headers={"Authorization": "Bearer gateway"})) as c:
                await c.list_tools()
            capabilities = await app.state.services.ops.get_capabilities(Deadline(settings.read_deadline_seconds))
            enabled = capabilities.slots.enabled
            mode = "enabled" if enabled else "disabled"
            if enabled:
                tool, values, _, paths = scenarios["availability_department"]
                scenarios["availability_department"] = (tool, values, {"DOCTORS_MATCHED", "CALLBACK_REQUIRED"}, paths)
                for name in ("availability_known_doctor", "availability_name_search"):
                    tool, values, _, paths = scenarios[name]
                    scenarios[name] = (tool, values, {"AVAILABILITY"}, paths, open_blocks)
            if "booking_create" in scenarios:
                selected, preparation[mode] = await prepare_booking(base, scenarios["booking_create"], mode)
                if selected is not None:
                    scenarios["booking_create"] = selected
                else:
                    del scenarios["booking_create"]
            report = await run(base, args.samples, args.concurrency, scenarios)
            if preparation.get(mode, {}).get("failure"):
                report["booking_create"] = preparation_failure(preparation[mode], ("POST /appointments",))
            if future_date:
                query = {"date": future_date, "departmentName": DEPARTMENT} if real_ops else {
                    "date": future_date, "departmentId": "dept_policy"}
                report.update(await department_cache_modes(app, base, args.samples, query=query,
                    name="availability_department_future",
                    expected={"DOCTORS_MATCHED"} if enabled else {"AVAILABILITY"}))
            for result in report.values():
                result["slots_observed"] = mode

            if not real_ops:
                ops_state.capabilities["slots"]["enabled"] = True
                for day in ("2026-10-01", "2026-10-05"):
                    ops_state.set_slots("doc_garima", day, slot_plan(date=day))
                oncall = slot_plan("doc_vikram_desai")
                oncall["sessions"] = [{**oncall["sessions"][1], "session": None}]
                ops_state.set_slots("doc_vikram_desai", "2026-10-01", oncall)
                # Explicit cold start for the new fixture mode; no service or global SSE flag is restarted/reset.
                app.state.services.cache.clear()
                enabled_scenarios = {
                    "slots_availability_future": ("get_doctor_availability", {
                        "doctorId": "doc_garima", "date": "2026-10-05"}, {"AVAILABILITY"},
                        ("GET /availability/doc_garima/slots",), open_blocks),
                    "slots_availability_today": ("get_doctor_availability", {
                        "doctorId": "doc_garima", "date": "today"}, {"AVAILABILITY"},
                        ("GET /availability", "GET /availability/doc_garima/slots"), open_blocks),
                    "slots_availability_oncall": ("get_doctor_availability", {
                        "doctorName": "vikram desai", "date": "today"}, {"AVAILABILITY"},
                        ("GET /doctors", "GET /availability", "GET /availability/doc_vikram_desai/slots"), open_blocks),
                }
                slot_report = await run(base, args.samples, args.concurrency, enabled_scenarios)
                create = ("manage_booking", {**SCENARIOS["booking_create"][1], "doctorId": "doc_garima",
                                            "visitDate": "2026-10-01"}, {"NOTED"},
                          ("GET /availability/doc_garima/slots", "POST /appointments"))
                selected, preparation["enabled"] = await prepare_booking(base, create, "enabled")
                if selected is None:
                    slot_report["slots_booking_create"] = preparation_failure(preparation["enabled"], create[3])
                else:
                    slot_report.update(await run(base, args.samples, args.concurrency, {
                        "slots_booking_create": (*selected, lambda b: bool(b.get("appointment", {}).get("slotTime")))}))
                slot_report.update(await department_cache_modes(app, base, args.samples,
                    query={"date": "today", "departmentName": "General Medicine"},
                    name="slots_department", expected={"DOCTORS_MATCHED"}))
                for result in slot_report.values():
                    result["slots_observed"] = "enabled"
                report.update(slot_report)
        print(json.dumps({"measured_at": datetime.now(UTC).isoformat(timespec="seconds"), "boundary": boundary,
                          "samples_per_scenario": args.samples, "concurrency": args.concurrency,
                          "read_deadline_seconds": settings.read_deadline_seconds,
                          "profile_batch_size": settings.profile_batch_size,
                          "min_batch_headroom_seconds": settings.min_batch_headroom_seconds,
                          "warm": "token warmed at start-up; one tools/list before sampling; "
                                  "a new MCP session per sample",
                          "owner_calls_verified": RECORDING_OWNER_CALLS,
                          "slots_observed": mode if real_ops else ["disabled", "enabled"],
                          "booking_preparation": preparation,
                          "workload_scenarios": workload_scenarios,
                          "watchdog_limit_seconds": watchdog_limit,
                          "fixture_mode_transition": None if real_ops else "same server; local directory cache cleared",
                          "omitted_scenarios": omitted,
                          "note": "timings cover tools/call after MCP session initialization, "
                                  "including client schema checking; "
                                  "a sample counts only when the intended outcome and owner call were observed",
                          "scenarios": report}, indent=2))
        return 1 if any(item.get("failure") for item in preparation.values()) else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
