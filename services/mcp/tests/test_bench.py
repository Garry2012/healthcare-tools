"""External latency measurement cannot quietly write into an arbitrary tenant."""
from __future__ import annotations

import runpy
from pathlib import Path

import pytest

BENCH = runpy.run_path(str(Path(__file__).resolve().parents[1] / "dev" / "bench.py"))
SELECT = BENCH["selected_scenarios"]


async def test_external_benchmark_defaults_to_reads_without_authenticating(monkeypatch, make_settings):
    monkeypatch.delenv("BENCH_ALLOW_WRITES", raising=False)

    def forbidden(*_):
        pytest.fail("read-only scenario selection must not authenticate or write")

    monkeypatch.setitem(SELECT.__globals__, "OpsClient", forbidden)
    scenarios = await SELECT(make_settings(), external=True)
    assert "booking_create" not in scenarios
    assert "booking_list" in scenarios and "knowledge_answer" in scenarios
    assert "booking_create" in await SELECT(make_settings(), external=False)


async def test_write_benchmark_requires_live_profile(monkeypatch, make_settings):
    monkeypatch.setenv("BENCH_ALLOW_WRITES", "1")
    monkeypatch.setenv("OPS_E2E_MODE", "mock")
    with pytest.raises(BENCH["GateFailure"], match="requires OPS_E2E_MODE=live"):
        await SELECT(make_settings(), external=True)


@pytest.mark.parametrize("permitted", [False, True])
async def test_write_benchmark_checks_tenant_before_selecting_writes(monkeypatch, make_settings, permitted):
    monkeypatch.setenv("BENCH_ALLOW_WRITES", "1")
    monkeypatch.setenv("OPS_E2E_MODE", "live")
    monkeypatch.setenv("BENCH_WRITE_TENANT", "synthetic")
    events = []

    class Client:
        def __init__(self, settings):
            pass

        async def aclose(self):
            events.append("closed")

    async def guard(client, expected):
        assert expected == "synthetic"
        events.append("checked")
        if not permitted:
            raise BENCH["GateFailure"]("tenant mismatch")

    monkeypatch.setitem(SELECT.__globals__, "OpsClient", Client)
    monkeypatch.setitem(SELECT.__globals__, "assert_authenticated_write_tenant", guard)
    if permitted:
        assert "booking_create" in await SELECT(make_settings(), external=True)
    else:
        with pytest.raises(BENCH["GateFailure"], match="tenant mismatch"):
            await SELECT(make_settings(), external=True)
    assert events == ["checked", "closed"]
