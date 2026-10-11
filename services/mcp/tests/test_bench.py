"""External latency measurement cannot quietly write into an arbitrary tenant."""
from __future__ import annotations

import asyncio
import runpy
import sys
from pathlib import Path

import pytest

BENCH = runpy.run_path(str(Path(__file__).resolve().parents[1] / "dev" / "bench.py"))
SELECT = BENCH["selected_scenarios"]


async def _run_python(*arguments, env=None, timeout=30):
    process = await asyncio.create_subprocess_exec(
        sys.executable, *arguments, cwd=Path(__file__).resolve().parents[1], env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise
    return process.returncode, stdout, stderr


async def test_external_benchmark_defaults_to_reads_without_authenticating(monkeypatch, make_settings):
    monkeypatch.delenv("BENCH_ALLOW_WRITES", raising=False)

    def forbidden(*_):
        pytest.fail("read-only scenario selection must not authenticate or write")

    monkeypatch.setitem(SELECT.__globals__, "OpsClient", forbidden)
    scenarios = await SELECT(make_settings(), external=True)
    assert "booking_create" not in scenarios
    assert "booking_list" in scenarios
    assert "knowledge_answer" not in scenarios
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


@pytest.mark.parametrize("doctor,ok", [("doc_garima", 1), ("doc_rohan_shetty", 0)])
async def test_stub_benchmark_measures_a_real_create_at_the_fixture_date(doctor, ok):
    import json
    import os

    env = {key: value for key, value in os.environ.items() if not key.startswith(("BENCH_", "OPS_E2E_"))}
    env["BENCH_DOCTOR_ID"] = doctor
    code, stdout, stderr = await _run_python(
        "dev/bench.py", "--samples", "1", "--concurrency", "1", env=env)
    assert code == 0, stderr.decode()[-2000:]
    report = json.loads(stdout)
    create = report["scenarios"]["booking_create"]
    assert create["expected_outcomes"] == ["NOTED"]
    assert create["ok"] == ok and create["rejected_or_failed"] == 1 - ok
    assert report["owner_calls_verified"] is True
    assert "POST /appointments" in create["required_owner_calls"]
    for mode in ("cold", "warm"):
        future = report["scenarios"][f"availability_department_future_{mode}"]
        assert future["ok"] == 1 and future["rejected_or_failed"] == 0
        assert future["cache_mode"] == mode
        assert "GET /availability" not in future["required_owner_calls"]
        assert future["profile_reads"] > 0 if mode == "cold" else future["profile_reads"] == 0


@pytest.mark.parametrize("samples", [1, 2])
async def test_benchmark_slot_modes_verify_paths_times_and_workload_bound(samples):
    import json
    import os

    env = {key: value for key, value in os.environ.items() if not key.startswith(("BENCH_", "OPS_E2E_"))}
    code, stdout, stderr = await _run_python(
        "dev/bench.py", "--samples", str(samples), "--concurrency", "1", env=env)
    assert code == 0, stderr.decode()[-2000:]
    report = json.loads(stdout)
    scenarios = report["scenarios"]
    expected = {
        "slots_availability_today": {"GET /availability", "GET /availability/doc_garima/slots"},
        "slots_availability_future": {"GET /doctors/doc_garima", "GET /availability/doc_garima/slots"},
        "slots_booking_create": {"GET /availability/doc_garima/slots", "POST /appointments"},
        "slots_availability_oncall": {"GET /doctors", "GET /availability",
                                      "GET /availability/doc_vikram_desai/slots"},
        "slots_department_cold": {"GET /doctors", "GET /availability", "GET /capabilities"},
        "slots_department_warm": {"GET /doctors", "GET /availability"},
    }
    for name, paths in expected.items():
        result = scenarios[name]
        assert result["ok"] == samples and result["rejected_or_failed"] == 0, result
        assert result["slots_observed"] == "enabled"
        assert paths <= set(result["observed_owner_calls"])
        if "department" in name:
            assert result["expected_outcomes"] == ["DOCTORS_MATCHED"]
            assert not any(p.endswith("/slots") for p in result["observed_owner_calls"])
        else:
            assert "GET /capabilities" not in result["observed_owner_calls"]
    assert "GET /availability" not in scenarios["slots_availability_future"]["observed_owner_calls"]
    assert "GET /capabilities" not in scenarios["slots_department_warm"]["observed_owner_calls"]
    assert scenarios["slots_department_cold"]["observed_owner_calls"]["GET /capabilities"] == samples
    assert scenarios["slots_booking_create"]["arguments"]["preferredTime"] == "10:30"
    assert report["booking_preparation"]["enabled"]["selected_time"] == "10:30"
    assert scenarios["booking_create"]["slots_observed"] == "disabled"
    assert "GET /availability/doc_garima/slots" in scenarios["availability_known_doctor"]["observed_owner_calls"]
    assert report["watchdog_limit_seconds"] == samples * report["workload_scenarios"] * .3 + 30
    assert report["workload_scenarios"] == len(scenarios)


async def test_demo_shows_slots_missing_time_and_selected_time():
    import json

    code, stdout, stderr = await _run_python("dev/demo.py")
    assert code == 0, stderr.decode()[-2000:]
    sections = {}
    for section in stdout.decode().split("\n== ")[1:]:
        title, body = section.split("\n", 1)
        sections[title] = json.loads(body)
    available = sections["slots: availability today"]
    assert available["doctors"][0]["board"][0]["openSlots"][0]["start"] == "10:30"
    refused = sections["slots: CREATE without a time"]
    assert (refused["outcome"], refused["nextStep"]) == ("INVALID_REQUEST", "ASK_WHICH_TIME")
    noted = sections["slots: CREATE with an offered time"]
    assert noted["outcome"] == "NOTED" and noted["appointment"]["slotTime"] == "10:30"
    assert noted["appointment"]["slotMoved"] is False


@pytest.mark.parametrize("offered", [[], [{"start": "10:50", "end": "11:00", "available": 2}]])
async def test_bench_requires_offered_blocks_and_prepares_the_returned_time(monkeypatch, offered):
    from fastmcp import FastMCP

    remote = FastMCP("offered-blocks")

    @remote.tool()
    def get_doctor_availability(doctorId: str, date: str) -> dict:  # noqa: N803
        return {"outcome": "AVAILABILITY", "doctors": [
            {"doctorId": doctorId, "board": [{"openSlots": offered}], "usualSessions": None}]}

    measure = BENCH["measure"]
    # Replace only the transport; real MCP dispatch and tool-result serialization remain in the test.
    monkeypatch.setitem(measure.__globals__, "StreamableHttpTransport", lambda *_args, **_kwargs: remote)
    monkeypatch.setitem(measure.__globals__, "RECORDING_OWNER_CALLS", False)
    result = await measure("http://unused", "offered", "get_doctor_availability", {
        "doctorId": "doc_garima", "date": "today"}, {"AVAILABILITY"}, (), 0, asyncio.Semaphore(1),
        check=lambda body: bool(body["doctors"][0]["board"][0]["openSlots"]))
    if offered:
        assert isinstance(result, float)
    else:
        assert result == "AVAILABILITY:result check failed"
    selected, evidence = await BENCH["prepare_booking"]("http://unused", (
        "manage_booking", {"doctorId": "doc_garima", "visitDate": "2026-10-01"}, {"NOTED"}, ()), "enabled")
    if offered:
        assert selected[1]["preferredTime"] == "10:50"
        assert evidence["selected_time"] == "10:50"
    else:
        assert selected is None and evidence["failure"] == "NO_OPEN_BLOCK"


async def test_subprocess_timeout_kills_and_reaps_child(monkeypatch):
    children = []
    launch = asyncio.create_subprocess_exec

    async def record_child(*args, **kwargs):
        child = await launch(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", record_child)
    try:
        with pytest.raises(TimeoutError):
            await _run_python("-c", "import time; time.sleep(60)", timeout=.1)
        assert children[0].returncode is not None, "timed-out child is still running"
        assert await children[0].wait() != 0
    finally:
        for child in children:
            if child.returncode is None:
                child.kill()
            await child.wait()


@pytest.mark.parametrize("initial_enabled", [False, True])
async def test_bench_failed_preparation_attempts_no_booking_and_exits_failure(initial_enabled):
    import json
    import os

    env = {key: value for key, value in os.environ.items() if not key.startswith(("BENCH_", "OPS_E2E_"))}
    # Change only owner fixtures in a child process: real HTTP MCP, preparation and report code execute.
    script = f"""
import atexit, json, runpy, sys
sys.path[:0] = ['dev', 'tests']
import harness
from frontdesk_stubs import ops
original_state = ops.OpsStubState
states = []
def state(**kwargs):
    capabilities = ops.default_capabilities()
    capabilities['slots']['enabled'] = {initial_enabled!r}
    instance = original_state(**kwargs, capabilities=capabilities)
    states.append(instance)
    return instance
ops.OpsStubState = state
original_plan = harness.slot_plan
def empty_plan(*args, **kwargs):
    plan = original_plan(*args, **kwargs)
    for session in plan['sessions']:
        session['slots'] = []
    return plan
harness.slot_plan = empty_plan
@atexit.register
def evidence():
    print('OWNER_WRITES=' + json.dumps([r for state in states for r in state.requests
        if r['method'] == 'POST' and r['path'] == '/appointments']), file=sys.stderr)
sys.argv = ['bench.py', '--samples', '2', '--concurrency', '1']
runpy.run_path('dev/bench.py', run_name='__main__')
"""
    code, stdout, stderr = await _run_python("-c", script, env=env)
    assert stdout, stderr.decode()
    report = json.loads(stdout)
    names = ["slots_booking_create"] + (["booking_create"] if initial_enabled else [])
    for name in names:
        result = report["scenarios"][name]
        assert result["samples"] == 0, result
        assert result["ok"] == 0 and result["rejected_or_failed"] == 0
        assert result["preparation_failure"] == "NO_OPEN_BLOCK"
        assert result["first_call_ms"] is None and result["p50_ms"] is None
        assert name not in report["omitted_scenarios"]
    writes = json.loads(stderr.decode().split("OWNER_WRITES=", 1)[1])
    # Only the two disabled-mode samples may write; every failed-preparation scenario writes nothing.
    assert len(writes) == (0 if initial_enabled else 2)
    assert code == 1, stderr.decode()
    if initial_enabled:
        for name in ("availability_known_doctor", "availability_name_search"):
            assert report["scenarios"][name]["expected_outcomes"] == ["AVAILABILITY"]


@pytest.mark.parametrize("level", [None, "INFO"])
async def test_benchmark_log_level_keeps_report_separate_from_logs(tmp_path, level):
    import json
    import os

    env = {k: v for k, v in os.environ.items() if not k.startswith(("BENCH_", "OPS_E2E_"))}
    log = tmp_path / "bench.log"
    arguments = ["dev/bench.py", "--samples", "1", "--concurrency", "1", "--log-file", str(log)]
    if level:
        arguments += ["--log-level", level]
    code, stdout, stderr = await _run_python(*arguments, env=env)
    assert code == 0, stderr.decode()
    report = json.loads(stdout)
    assert set(report) == {"measured_at", "boundary", "samples_per_scenario", "concurrency",
        "read_deadline_seconds", "profile_batch_size", "min_batch_headroom_seconds", "warm",
        "owner_calls_verified", "slots_observed", "booking_preparation", "workload_scenarios",
        "watchdog_limit_seconds", "fixture_mode_transition", "omitted_scenarios", "note", "scenarios"}
    assert all(item["ok"] == 1 for item in report["scenarios"].values())
    records = [json.loads(line) for line in log.read_text().splitlines()]
    if level == "INFO":
        assert any(r["msg"] == "tool_result" and r["level"] == "INFO" for r in records)
    else:
        assert all(r["level"] in {"WARNING", "ERROR", "CRITICAL"} for r in records)


@pytest.mark.parametrize("level", ["DEBUG", "INFO"])
async def test_benchmark_requires_file_before_verbose_measurement(level):
    import os

    env = {k: v for k, v in os.environ.items() if not k.startswith(("BENCH_", "OPS_E2E_"))}
    code, stdout, stderr = await _run_python(
        "dev/bench.py", "--samples", "1", "--log-level", level, env=env)
    assert code == 2, stderr.decode()
    assert "--log-level below WARNING requires --log-file" in stderr.decode()
    assert stdout == b"", "invalid CLI must not start the benchmark"


async def test_benchmark_refuses_ambiguous_log_ownership(tmp_path):
    script = '''
import logging, runpy, sys
sys.path.insert(0, "dev")
from frontdesk_mcp import server
original = server.create_app
def build(*args, **kwargs):
    app = original(*args, **kwargs)
    logging.getLogger().addHandler(logging.NullHandler())
    return app
server.create_app = build
sys.argv = ['bench.py', '--samples', '1', '--log-file', sys.argv[1]]
runpy.run_path('dev/bench.py', run_name='__main__')
'''
    code, stdout, stderr = await _run_python("-c", script, str(tmp_path / "bench.log"))
    assert code != 0
    assert "benchmark requires exactly one root log handler" in stderr.decode()
    assert stdout == b"", "ambiguous ownership must fail before measurement"
