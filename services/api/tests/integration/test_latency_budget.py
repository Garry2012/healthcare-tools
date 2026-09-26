"""Voice latency budget (docs/architecture/TARGET.md). Query counts are the deterministic gate:
on a networked database every sequential round trip costs milliseconds of caller silence.
Wall-clock limits are generous (shared CI runners) and catch only gross regressions."""

from __future__ import annotations

import time

import pytest

from .conftest import STAFF, call

SEARCHES = {
    "named": ({"utterance": "ನಾಳೆ ಸಂಜೆ ಡಾಕ್ಟರ್ ಗರಿಮಾ ಇರ್ತಾರಾ", "language": "kn", "resourceName": "Dr Garima",
               "when": {"expression": "tomorrow evening"}}, 5),
    "category": ({"utterance": "I need a skin doctor", "language": "en", "category": "skin doctor"}, 6),
    "anyone": ({"utterance": "is any doctor available right now", "language": "en"}, 6),
    "red_flag": ({"utterance": "my father has chest pain", "language": "en"}, 1),
}


def queries(response) -> int:
    return int(response.headers["server-timing"].split('desc="')[1].split(" ")[0])


async def timed(client, *args, **kwargs):
    started = time.perf_counter()
    response = await client.request(*args, **kwargs)
    return response, (time.perf_counter() - started) * 1000


@pytest.mark.parametrize("name", SEARCHES)
async def test_availability_search_round_trips_and_time(client, name):
    body, max_queries = SEARCHES[name]
    await client.post("/agent/availability-search", headers=call(), json=body)  # warm the directory cache
    elapsed = []
    for _ in range(10):
        r, ms = await timed(client, "POST", "/agent/availability-search", headers=call(), json=body)
        assert r.status_code == 200
        assert queries(r) <= max_queries, f"{name}: {queries(r)} round trips (budget {max_queries})"
        elapsed.append(ms)
    assert sorted(elapsed)[8] < 250, f"{name}: p90 {sorted(elapsed)[8]:.0f} ms"


async def test_knowledge_search_is_one_round_trip(client):
    body = {"question": "ಪಾರ್ಕಿಂಗ್ ಇದೆಯಾ", "language": "kn"}
    await client.post("/agent/knowledge-search", headers=call(), json=body)
    for _ in range(10):
        r, ms = await timed(client, "POST", "/agent/knowledge-search", headers=call(), json=body)
        assert r.status_code == 200 and queries(r) == 1 and ms < 50


async def test_directory_cache_builds_once_and_rebuilds_after_a_directory_write(client, app):
    cache = app.state.directory_cache
    body = SEARCHES["category"][0]
    for _ in range(3):
        await client.post("/agent/availability-search", headers=call(), json=body)
    assert cache.builds == 1
    term = {"conceptType": "CATEGORY", "conceptId": "cat_derm", "term": "rash doctor", "language": "en",
            "approved": True}
    assert (await client.post("/lexicon", headers=STAFF, json=term)).status_code == 201
    found = await client.post("/agent/availability-search", headers=call(),
                              json={"utterance": "rash doctor please", "language": "en", "category": "rash doctor"})
    assert cache.builds == 2
    assert [c["id"] for c in found.json()["understood"]["categories"]] == ["cat_derm"]
