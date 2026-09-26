"""Latency of the voice-path operations against a seeded database, in process (no network).

    DATABASE_URL=postgresql://app:…@host/db uv run python scripts/bench.py [-n 50]

Prints p50/p95/max per scenario and the budget from docs/architecture/TARGET.md. The
gateway, the adapter and the network are not included; this is the API's own share.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time

import httpx

from frontdesk_api.app import create_app
from frontdesk_api.config import Settings

TOKEN = "bench-token"  # noqa: S105 - local benchmark only
HEADERS = {"Authorization": f"Bearer {TOKEN}", "X-Call-Id": "bench", "X-Caller-Number": "+919000000101"}
SCENARIOS: dict[str, tuple[str, str, dict | None, float]] = {
    # name: (method, path, body, budget ms)
    "search: named resource, tomorrow evening (kn)": ("POST", "/agent/availability-search", {
        "utterance": "ನಾಳೆ ಸಂಜೆ ಡಾಕ್ಟರ್ ಗರಿಮಾ ಇರ್ತಾರಾ", "language": "kn", "resourceName": "Dr Garima",
        "when": {"expression": "tomorrow evening"}}, 250),
    "search: category, next 7 days": ("POST", "/agent/availability-search", {
        "utterance": "I need a skin doctor", "language": "en", "category": "skin doctor"}, 250),
    "search: anyone available now": ("POST", "/agent/availability-search", {
        "utterance": "is any doctor available right now", "language": "en"}, 250),
    "search: red flag": ("POST", "/agent/availability-search", {
        "utterance": "my father has chest pain", "language": "en"}, 250),
    "knowledge: parking (kn)": ("POST", "/agent/knowledge-search", {"question": "ಪಾರ್ಕಿಂಗ್ ಇದೆಯಾ", "language": "kn"}, 50),
    "bookings: list by caller": ("GET", "/agent/bookings", None, 250),
}


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


async def main(n: int) -> dict[str, dict[str, float]]:
    settings = Settings(auth_tokens_json=json.dumps({TOKEN: ["agent"]}), log_level="WARNING")
    app = create_app(settings)
    results: dict[str, dict[str, float]] = {}
    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://bench/api/v1"
    ) as client:
        for name, (method, path, body, budget) in SCENARIOS.items():
            timings, queries = [], 0
            for i in range(n + 3):
                started = time.perf_counter()
                r = await client.request(method, path, json=body, headers=HEADERS)
                elapsed = (time.perf_counter() - started) * 1000
                r.raise_for_status()
                queries = int(r.headers["server-timing"].split('desc="')[1].split(" ")[0])
                if i >= 3:  # warm-up: pool connections, first cache build
                    timings.append(elapsed)
            results[name] = {"p50": statistics.median(timings), "p95": pct(timings, 0.95), "max": max(timings),
                             "budget": budget, "queries": queries}
            print(f"{name:48} p50 {results[name]['p50']:7.1f}  p95 {results[name]['p95']:7.1f}  "
                  f"max {results[name]['max']:7.1f}  budget {budget:5.0f} ms  queries {queries}")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", type=int, default=50)
    asyncio.run(main(parser.parse_args().n))
