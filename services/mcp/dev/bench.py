"""Tool round-trip latency: agent → MCP (streamable HTTP over TCP) → owner service(s) → result.

Default: the in-process development stubs (fixture timings, NOT production evidence). With
BENCH_OPS_BASE_URL (and optionally BENCH_KNOWLEDGE_BASE_URL + credentials) the adapter is pointed at
real hosts and the same scenarios are measured there. Reports p50/p95/p99, failures and the boundary.

    uv run python dev/bench.py [--samples 50] [--concurrency 1]
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from conftest import serving  # noqa: E402

from frontdesk_mcp.clock import FixedClock, SystemClock  # noqa: E402
from frontdesk_mcp.config import Settings  # noqa: E402
from frontdesk_mcp.server import create_app  # noqa: E402
from frontdesk_stubs import knowledge as knowledge_stub  # noqa: E402
from frontdesk_stubs import ops as ops_stub  # noqa: E402

# name → (tool, arguments, outcomes that count as the intended success, owner paths the call must have hit:
#          operational paths and the knowledge routing path; every in-call tool must route first)
ROUTE = "/v1/route"
# Directory values the scenarios need. Defaults are the development fixtures; a real host needs its own
# (BENCH_DOCTOR_ID: a doctor id; BENCH_DOCTOR_NAME: a name matching exactly one doctor; BENCH_AMBIGUOUS_NAME:
# a name matching several; BENCH_DEPARTMENT: a department name present in the tenant).
DOCTOR_ID = os.environ.get("BENCH_DOCTOR_ID", "doc_garima")
DOCTOR_NAME = os.environ.get("BENCH_DOCTOR_NAME", "garima")
AMBIGUOUS_NAME = os.environ.get("BENCH_AMBIGUOUS_NAME", "sharma")
DEPARTMENT = os.environ.get("BENCH_DEPARTMENT", "cardiology")
SCENARIOS = {
    "availability_known_doctor": ("get_doctor_availability", {"doctorId": DOCTOR_ID, "date": "today"},
                                  {"AVAILABILITY", "CALLBACK_REQUIRED"}, ("/availability", ROUTE)),
    "availability_name_search": ("get_doctor_availability", {"doctorName": DOCTOR_NAME, "date": "today"},
                                 {"AVAILABILITY", "CALLBACK_REQUIRED"}, ("/doctors", "/availability", ROUTE)),
    "availability_ambiguous": ("get_doctor_availability", {"doctorName": AMBIGUOUS_NAME, "date": "today"},
                               {"CLARIFICATION_NEEDED"}, ("/doctors", ROUTE)),
    # departments are cached across samples: the board is the per-call owner read that must be observed
    "availability_department": ("get_doctor_availability", {"departmentName": DEPARTMENT, "date": "today"},
                                {"AVAILABILITY", "CALLBACK_REQUIRED"}, ("/availability", ROUTE)),
    "knowledge_answer": ("search_knowledge", {"question": "parking", "language": "en"}, {"ANSWERED", "NO_ANSWER"},
                         ("/v1/answer", ROUTE)),
    "booking_list": ("manage_booking", {"action": "LIST"}, {"FOUND", "NOT_FOUND"}, ("/appointments",)),
    "booking_create": ("manage_booking", {"action": "CREATE", "patientName": "Bench Patient",
                                          "patientMobile": "9000000101", "doctorId": DOCTOR_ID, "visitDate": "today",
                                          "preferredTime": "09:30", "callerConfirmed": True},
                       {"NOTED", "CALLBACK_REQUIRED"}, ("/availability", ROUTE)),
}


def turn(utterance: str) -> str:
    payload = json.dumps({"utterance": utterance, "language": "en"}).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))]


OWNER_CALLS: list[tuple[str, str]] = []  # (call id, path) seen by the recording transports (stub mode only)
BUDGET_MS = 300.0  # the in-call tool share (config default): samples above it are reported separately


async def measure(base: str, name: str, tool: str, args: dict, expected: set[str], paths: tuple[str, ...],
                  i: int, sem: asyncio.Semaphore) -> float | str:
    """One tool round trip in ms when the outcome is the scenario's intended success AND the intended owner
    operation was observed (stub mode); otherwise the outcome/detail label, counted as a rejected sample."""
    call_id = f"bench-{name}-{i}"
    headers = {"Authorization": "Bearer gateway", "X-Call-Id": call_id, "X-Operation-Id": f"{call_id}-op",
               "X-Caller-Number": "+919000000101", "X-Caller-Verification": "SIP_CALLER_ID",
               "X-Turn-Context": turn("availability please")}
    if args.get("visitDate") == "today":
        args = {**args, "visitDate": datetime.now(UTC).astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat()}
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
    if RECORDING_OWNER_CALLS:
        seen = [path for cid, path in OWNER_CALLS if cid == call_id]  # attributed by call id, safe under concurrency
        for path in paths:
            if not any(path in p for p in seen):
                return f"{outcome}:owner call {path} not observed"
    return elapsed


RECORDING_OWNER_CALLS = False


async def run(base: str, samples: int, concurrency: int) -> dict:
    report: dict = {}
    for name, (tool, args, expected, paths) in SCENARIOS.items():
        sem = asyncio.Semaphore(concurrency)
        results = await asyncio.gather(*(measure(base, name, tool, args, expected, paths, i, sem)
                                         for i in range(samples)))
        timings = [r for r in results if isinstance(r, float)]
        failed = [r for r in results if isinstance(r, str)]
        failures = len(failed)
        outcomes = {}
        for r in results:
            label = r if isinstance(r, str) else "ok"
            outcomes[label] = outcomes.get(label, 0) + 1
        report[name] = {"samples": samples, "ok": len(timings), "rejected_or_failed": failures,
                        "over_budget_ms": BUDGET_MS, "over_budget": sum(1 for t in timings if t > BUDGET_MS),
                        "expected_outcomes": sorted(expected), "outcomes": outcomes,
                        "first_call_ms": round(results[0], 1) if isinstance(results[0], float) else results[0],
                        "p50_ms": round(percentile(timings, 50), 1) if timings else None,
                        "p95_ms": round(percentile(timings, 95), 1) if timings else None,
                        "p99_ms": round(percentile(timings, 99), 1) if timings else None,
                        "mean_ms": round(statistics.fmean(timings), 1) if timings else None}
    return report


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=1)
    args = parser.parse_args()
    real_ops = os.environ.get("BENCH_OPS_BASE_URL")
    # With real operational hosts but no knowledge host yet, keep the in-process knowledge stub so the routing
    # gate clears and the Manoj critical path is what gets measured. Reported in the boundary line.
    knowledge_stub_with_real_ops = bool(real_ops) and not os.environ.get("BENCH_KNOWLEDGE_BASE_URL")
    settings = Settings(
        env="development", log_level="WARNING", provider_id="demo-hospital", domain_pack="healthcare",
        tenant_supported_languages="en,kn,hi",
        tenant_timezone="Asia/Kolkata", tenant_country_calling_code="91",
        ops_base_url=real_ops or "http://ops-stub.local/api/v1",
        ops_client_id=os.environ.get("BENCH_OPS_CLIENT_ID") or os.environ.get("OPS_E2E_CLIENT_ID", "mcp-dev"),
        ops_client_secret=(os.environ.get("BENCH_OPS_CLIENT_SECRET")
                           or os.environ.get("OPS_E2E_CLIENT_SECRET", "dev-secret")),
        knowledge_base_url=os.environ.get("BENCH_KNOWLEDGE_BASE_URL", "http://knowledge-stub.local"),
        knowledge_bearer_token=os.environ.get("BENCH_KNOWLEDGE_BEARER_TOKEN", "dev-knowledge-secret"),
        mcp_bearer_token="gateway", mcp_lifecycle_bearer_token="lifecycle",
        allow_budget_overrides=True,  # diagnostic: the bench runs from wherever it is started, not from the MCP region
        read_deadline_seconds=float(os.environ.get("BENCH_READ_DEADLINE", "2.0")),
        write_deadline_seconds=max(4.0, float(os.environ.get("BENCH_READ_DEADLINE", "2.0"))),
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

                OWNER_CALLS.append((call_id_var.get() or "", request.url.path))
                return await self.inner.handle_async_request(request)

        global RECORDING_OWNER_CALLS
        RECORDING_OWNER_CALLS = True
        ops_transport = Recording(ops_stub.create_app(ops_state, prefix="/api/v1"))
        kb_state = knowledge_stub.KnowledgeStubState(bearer="dev-knowledge-secret")
        knowledge_transport = Recording(knowledge_stub.create_app(kb_state))
    app = create_app(settings, ops_transport=ops_transport, knowledge_transport=knowledge_transport, clock=clock)
    async with serving(app) as base:
        # warm: first call pays token + pool + schema
        async with Client(StreamableHttpTransport(f"{base}/mcp/", headers={"Authorization": "Bearer gateway"})) as c:
            await c.list_tools()
        report = await run(base, args.samples, args.concurrency)
    print(json.dumps({"measured_at": datetime.now(UTC).isoformat(timespec="seconds"), "boundary": boundary,
                      "samples_per_scenario": args.samples, "concurrency": args.concurrency,
                      "warm": "token warmed at start-up; one tools/list before sampling; a new MCP session per sample",
                      "owner_calls_verified": RECORDING_OWNER_CALLS,
                      "note": "timings include client-side schema checking and session initialize; "
                              "a sample counts only when the intended outcome and owner call were observed",
                      "scenarios": report}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
