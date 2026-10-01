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

SCENARIOS = {
    "availability_known_doctor": ("get_doctor_availability", {"doctorId": "doc_garima", "date": "today"}),
    "availability_name_search": ("get_doctor_availability", {"doctorName": "garima", "date": "today"}),
    "availability_ambiguous": ("get_doctor_availability", {"doctorName": "sharma", "date": "today"}),
    "availability_department": ("get_doctor_availability", {"departmentName": "cardiology", "date": "today"}),
    "knowledge_answer": ("search_knowledge", {"question": "parking", "language": "en"}),
    "booking_list": ("manage_booking", {"action": "LIST"}),
}


def turn(utterance: str) -> str:
    payload = json.dumps({"utterance": utterance, "language": "en"}).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))]


async def measure(base: str, name: str, tool: str, args: dict, i: int, sem: asyncio.Semaphore) -> float | None:
    """One tool round trip in ms, or None when the result is an error/failure envelope."""
    headers = {"Authorization": "Bearer gateway", "X-Call-Id": f"bench-{name}-{i}",
               "X-Caller-Number": "+919000000101", "X-Turn-Context": turn("availability please")}
    async with sem, Client(StreamableHttpTransport(f"{base}/mcp/", headers=headers)) as c:
        started = time.perf_counter()
        result = await c.call_tool(tool, args, raise_on_error=False)
        elapsed = (time.perf_counter() - started) * 1000
    body = result.structured_content or {}
    if result.is_error or body.get("outcome") in ("COULD_NOT_CHECK", "ROUTING_UNAVAILABLE"):
        return None
    return elapsed


async def run(base: str, samples: int, concurrency: int) -> dict:
    report: dict = {}
    for name, (tool, args) in SCENARIOS.items():
        sem = asyncio.Semaphore(concurrency)
        results = await asyncio.gather(*(measure(base, name, tool, args, i, sem) for i in range(samples)))
        timings = [r for r in results if r is not None]
        failures = len(results) - len(timings)
        report[name] = {"samples": samples, "ok": len(timings), "failures": failures,
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
    settings = Settings(
        env="development", log_level="WARNING", provider_id="demo-hospital", domain_pack="healthcare",
        tenant_supported_languages="en,kn,hi",
        tenant_timezone="Asia/Kolkata", tenant_country_calling_code="91",
        ops_base_url=real_ops or "http://ops-stub.local/api/v1",
        ops_client_id=os.environ.get("BENCH_OPS_CLIENT_ID", "mcp-dev"),
        ops_client_secret=os.environ.get("BENCH_OPS_CLIENT_SECRET", "dev-secret"),
        knowledge_base_url=os.environ.get("BENCH_KNOWLEDGE_BASE_URL",
                                          "" if real_ops else "http://knowledge-stub.local"),
        knowledge_bearer_token=os.environ.get("BENCH_KNOWLEDGE_BEARER_TOKEN", "dev-knowledge-secret"),
        mcp_bearer_token="gateway", mcp_lifecycle_bearer_token="lifecycle",
        read_deadline_seconds=float(os.environ.get("BENCH_READ_DEADLINE", "2.0")))
    if real_ops:
        knowledge = settings.knowledge_base_url or "not configured"
        boundary = f"laptop → MCP (local TCP) → {real_ops} (real network); knowledge: {knowledge}"
        ops_transport = knowledge_transport = None
        clock = SystemClock()
    else:
        boundary = "laptop → MCP (local TCP) → in-process stubs (ASGI, no network): fixture timings only"
        clock = FixedClock(datetime(2026, 10, 1, 4, 30, tzinfo=UTC))
        scopes = {"appointments.write", "calls.write"}
        ops_state = ops_stub.OpsStubState(clock=clock, clients={"mcp-dev": ("dev-secret", scopes)})
        ops_transport = httpx.ASGITransport(app=ops_stub.create_app(ops_state, prefix="/api/v1"))
        kb_state = knowledge_stub.KnowledgeStubState(bearer="dev-knowledge-secret")
        knowledge_transport = httpx.ASGITransport(app=knowledge_stub.create_app(kb_state))
    app = create_app(settings, ops_transport=ops_transport, knowledge_transport=knowledge_transport, clock=clock)
    async with serving(app) as base:
        # warm: first call pays token + pool + schema
        async with Client(StreamableHttpTransport(f"{base}/mcp/", headers={"Authorization": "Bearer gateway"})) as c:
            await c.list_tools()
        report = await run(base, args.samples, args.concurrency)
    print(json.dumps({"measured_at": datetime.now(UTC).isoformat(timespec="seconds"), "boundary": boundary,
                      "samples_per_scenario": args.samples, "concurrency": args.concurrency, "warm": True,
                      "scenarios": report}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
