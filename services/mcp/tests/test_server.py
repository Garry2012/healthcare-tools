"""The assembled server over real streamable HTTP (uvicorn): exactly four tools under gateway authentication,
trusted identity from headers only, concurrent-call isolation,
local readiness distinct from dependency status, and a pinned tool-schema snapshot."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import socket
from pathlib import Path

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from frontdesk_mcp import cli, packs, prompt
from frontdesk_mcp.server import JsonFormatter, create_app

from . import conftest, harness
from .conftest import serving

SNAPSHOT = Path(__file__).parent / "contracts/mcp-tools.snapshot.json"
FORBIDDEN = {"x-call-id", "xcallid", "callid", "x-caller-number", "xcallernumber", "callernumber", "callernumbers",
             "idempotency-key", "idempotencykey", "operationid", "x-operation-id",
             "turncontext", "x-turn-context", "utterance", "tenant", "tenantid", "principal",
             "startedat", "durationseconds"}
TOOLS = ["get_doctor_availability", "manage_booking", "record_call_summary", "search_knowledge"]


class _LifespanApp:
    def __init__(self, shutdown_gate):
        self.shutdown_gate = shutdown_gate
        self.shutdown_started = asyncio.Event()
        self.finished = asyncio.Event()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})
            return
        assert scope["type"] == "lifespan"
        try:
            assert (await receive())["type"] == "lifespan.startup"
            await send({"type": "lifespan.startup.complete"})
            assert (await receive())["type"] == "lifespan.shutdown"
            self.shutdown_started.set()
            await self.shutdown()
            await send({"type": "lifespan.shutdown.complete"})
        finally:
            self.finished.set()

    async def shutdown(self):
        await self.shutdown_gate.wait()


class _CancellationIgnoringLifespanApp(_LifespanApp):
    async def shutdown(self):
        while not self.shutdown_gate.is_set():
            try:
                await self.shutdown_gate.wait()
            except asyncio.CancelledError:
                continue


@pytest.mark.parametrize("app_type", [_LifespanApp, _CancellationIgnoringLifespanApp])
async def test_serving_bounds_stuck_shutdown_and_cleans_up(monkeypatch, app_type):
    app = app_type(asyncio.Event())
    unrelated = asyncio.create_task(asyncio.Event().wait(), name="PRIVATE42-caller-secret")
    before = asyncio.all_tasks()
    loop = asyncio.get_running_loop()
    owned = set()
    # The old gather can absorb the outer timeout; release its blocked child as a final RED safeguard.
    emergency_release = loop.call_later(2.5, app.shutdown_gate.set)
    try:
        async with asyncio.timeout(2):
            with pytest.raises(AssertionError, match=r"shutdown exceeded 0\.5s") as failure:
                async with serving(app, shutdown_limit=0.5) as base:
                    owned = asyncio.all_tasks() - before
                    assert any(t.get_coro().__qualname__ == "Server.serve" for t in owned)
                    port = int(base.rsplit(":", 1)[1])
                    started = loop.time()
        elapsed = loop.time() - started
        assert 0.5 <= elapsed < 2
        assert app.shutdown_started.is_set()
        assert all(t.done() for t in owned if t.get_coro().__qualname__ == "Server.serve")
        # The fixture owns its blocked ASGI lifespan. serving only cancels the public serve() task.
        app.shutdown_gate.set()
        _, pending = await asyncio.wait(owned, timeout=1)
        assert not pending and app.finished.is_set()
        assert asyncio.all_tasks() <= before
        assert not unrelated.done()
        message = str(failure.value)
        assert "stopped after cancellation=True" in message
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", port))
        # Reusing the exact released port proves the next server can start and stop.
        monkeypatch.setattr(conftest, "free_port", lambda: port)
        gate = asyncio.Event()
        gate.set()
        recovered = _LifespanApp(gate)
        async with asyncio.timeout(2):
            async with serving(recovered) as restarted:
                assert restarted == base
        assert recovered.finished.is_set()
        assert asyncio.all_tasks() <= before
    finally:
        emergency_release.cancel()
        app.shutdown_gate.set()
        unrelated.cancel()
        _, pending = await asyncio.wait({unrelated, *owned}, timeout=1)
        assert not pending


async def test_serving_normal_shutdown_stays_fast_and_quiet(capsys, caplog):
    gate = asyncio.Event()
    gate.set()
    app = _LifespanApp(gate)
    before = asyncio.all_tasks()
    async with asyncio.timeout(2):
        async with serving(app):
            started = asyncio.get_running_loop().time()
    assert asyncio.get_running_loop().time() - started < 1
    assert app.shutdown_started.is_set() and app.finished.is_set()
    assert asyncio.all_tasks() <= before
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    assert not [record for record in caplog.records if record.levelno >= logging.WARNING]


async def test_serving_reports_a_server_task_that_ignores_cancellation(monkeypatch):
    blocker = _CancellationIgnoringLifespanApp(asyncio.Event())
    original_shutdown = conftest.uvicorn.Server.shutdown

    async def stuck_shutdown(server, sockets=None):
        await original_shutdown(server, sockets)
        await blocker.shutdown()

    monkeypatch.setattr(conftest.uvicorn.Server, "shutdown", stuck_shutdown)
    gate = asyncio.Event()
    gate.set()
    before = asyncio.all_tasks()
    owned = set()
    loop = asyncio.get_running_loop()
    emergency_release = loop.call_later(2.5, blocker.shutdown_gate.set)
    try:
        async with asyncio.timeout(2):
            with pytest.raises(AssertionError, match="stopped after cancellation=False"):
                async with serving(_LifespanApp(gate), shutdown_limit=0.5):
                    owned = asyncio.all_tasks() - before
                    started = loop.time()
        assert 0.5 <= loop.time() - started < 2
    finally:
        emergency_release.cancel()
        blocker.shutdown_gate.set()
        if owned:
            _, pending = await asyncio.wait(owned, timeout=1)
            assert not pending


async def test_serving_watchdog_captures_body_without_private_values(capsys):
    gate = asyncio.Event()
    gate.set()
    app = _LifespanApp(gate)
    release = asyncio.Event()

    async def hold_argument(value):
        assert value
        await release.wait()

    before = asyncio.all_tasks()
    private = [asyncio.create_task(hold_argument("ARGUMENT-SECRET-9000000123"),
                                  name=f"NAME-SECRET-{i}") for i in range(45)]
    owned = set(private)
    try:
        async with asyncio.timeout(3):
            with pytest.raises(AssertionError, match=r"^HTTP test body exceeded 0\.5s") as failure:
                async with serving(app, watchdog_limit=0.5):
                    owned.update(asyncio.all_tasks() - before)
                    started = asyncio.get_running_loop().time()
                    await asyncio.Event().wait()
        assert 0.5 <= asyncio.get_running_loop().time() - started < 2
        message = str(failure.value)
        assert len(message) <= 12000
        assert "ARGUMENT-SECRET" not in message and "NAME-SECRET" not in message
        assert "9000000123" not in message and "name=<custom>" in message
        assert re.search(r"services/mcp/tests/test_server.py:\d+ in", message)
        assert all(" class=" in record and " awaited=" in record for record in message.split("\ntask ")[1:])
        body = message.split("\ntask ")[1]
        assert "class=harness" in body and "Event.wait" in body
        assert "awaited=" in body and len(message.split("\ntask ")) == 41
        assert message in capsys.readouterr().out
        assert app.finished.is_set()
        assert all(t.done() for t in owned - set(private))
    finally:
        release.set()
        if owned:
            _, pending = await asyncio.wait(owned, timeout=1)
            assert not pending
    assert asyncio.all_tasks() <= before


async def test_serving_watchdog_normal_http_round_trip_is_quiet(capsys, caplog):
    gate = asyncio.Event()
    gate.set()
    before = asyncio.all_tasks()
    async with asyncio.timeout(3):
        async with serving(_LifespanApp(gate), watchdog_limit=0.5) as base:
            async with httpx.AsyncClient() as http:
                response = await http.get(base)
                assert response.status_code == 200 and response.text == "ok"
    assert asyncio.all_tasks() <= before
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    assert not [record for record in caplog.records if record.levelno >= logging.WARNING]


def test_serving_watchdog_fails_the_fixture_backed_test_call(tmp_path):
    import subprocess
    import sys
    import textwrap

    probe = tmp_path / "test_watchdog_probe.py"
    probe.write_text(textwrap.dedent('''\
        import asyncio
        import pytest
        from tests.conftest import serving
        from tests.test_server import _LifespanApp

        @pytest.fixture
        async def http_server():
            gate = asyncio.Event()
            gate.set()
            async with serving(_LifespanApp(gate), watchdog_limit=0.5):
                yield

        async def test_frozen_body(http_server):
            async with asyncio.timeout(2):
                await asyncio.Event().wait()
        '''))
    result = subprocess.run([sys.executable, "-m", "pytest", str(probe), "-q", "-p", "tests.conftest",
                             "-c", "pyproject.toml", "-p", "no:cacheprovider"],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=10)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "AssertionError: HTTP test body exceeded 0.5s" in result.stdout
    assert "FAILED" in result.stdout and "test_frozen_body" in result.stdout
    assert "1 failed" in result.stdout and "ERROR at setup" not in result.stdout


def test_serving_resets_previous_server_sse_drain_flag(tmp_path):
    import subprocess
    import sys
    import textwrap

    probe = tmp_path / "test_sse_drain_probe.py"
    probe.write_text(textwrap.dedent('''\
        import asyncio
        import sys
        from fastmcp import Client
        from fastmcp.client.transports import StreamableHttpTransport
        from frontdesk_mcp.config import Settings
        from frontdesk_mcp.server import create_app
        from tests import conftest, harness

        async def test_fresh_server_completes_session_after_previous_drain():
            h = harness.build(Settings(**conftest.ROLLOUT, **conftest.ENDPOINTS, env="test"))
            try:
                app = create_app(h.settings, ops_transport=h.ops.http._transport,
                                 knowledge_transport=h.knowledge.http._transport, clock=h.clock)
                module = sys.modules["sse_starlette.sse"]
                module.AppStatus.should_exit = True
                async with conftest.serving(app) as base:
                    flag_at_start = module.AppStatus.should_exit
                    recorder = conftest._HTTP_RECORDER.get()
                    async with asyncio.timeout(10):
                        async with Client(StreamableHttpTransport(base + "/mcp/", headers={
                                "Authorization": "Bearer mcp-token"})) as client:
                            result = await client.call_tool("get_doctor_availability", {
                                "doctorId": "doc_garima", "date": "2099-01-05"})
                    assert result.structured_content["outcome"] == "AVAILABILITY"
                    assert recorder.incidents == []
                    assert flag_at_start is False
                print("SSE_DRAIN_RESET_OK")
            finally:
                await h.aclose()
        '''))
    result = subprocess.run([sys.executable, "-m", "pytest", str(probe), "-q", "-s", "--tb=short",
                             "-p", "tests.conftest", "-c", "pyproject.toml", "-p", "no:cacheprovider"],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SSE_DRAIN_RESET_OK" in result.stdout


class _IncompleteResponseApp(_LifespanApp):
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await super().__call__(scope, receive, send)
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"text/event-stream")]})
        await send({"type": "http.response.body", "body": b"PRIVATE-BODY", "more_body": True})


async def test_serving_recorder_identifies_incomplete_request_and_confirmation(capsys):
    gate = asyncio.Event()
    gate.set()
    async with asyncio.timeout(3):
        with pytest.raises(AssertionError, match="Incomplete HTTP response") as failure:
            async with serving(_IncompleteResponseApp(gate)) as base:
                recorder = conftest._HTTP_RECORDER.get()
                async with httpx.AsyncClient() as http:
                    with pytest.raises(httpx.RemoteProtocolError):
                        await http.post(base + "/mcp/?secret=PRIVATE-QUERY", content=b"PRIVATE-REQUEST",
                                        headers={"Authorization": "Bearer PRIVATE-TOKEN",
                                                 "mcp-session-id": "PRIVATE-SESSION",
                                                 "content-type": "application/json; secret=PRIVATE-PARAM"})
    incident = recorder.incidents[0]
    request = incident["request"]
    assert request["method"] == "POST" and request["path"] == "/mcp/"
    assert request["authorization"] is True and request["session_id"] is True
    assert request["request_content_type"] == "application/json"
    assert request["response_content_type"] == "text/event-stream" and request["status"] == 200
    assert request["started"] and not request["complete"] and not request["disconnected"]
    assert request["returned"] and request["raised"] is None
    assert 0 <= request["start"] <= request["start"] + request["duration"]
    assert "pending=" in incident["tasks"] and len(incident["tasks"]) <= 12000
    assert recorder.confirmations[0]["incident"] == request["sequence"]
    assert "PRIVATE" not in str(failure.value)
    assert "last_requests" in str(failure.value) and "warnings" in str(failure.value)
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("style", ["direct", "fixture", "direct-error", "fixture-error"])
def test_serving_recorder_fails_only_owning_test_call(tmp_path, style):
    import subprocess
    import sys
    import textwrap

    fixture = '''
@pytest.fixture
async def served():
    gate = asyncio.Event()
    gate.set()
    async with serving(_IncompleteResponseApp(gate)) as base:
        yield base
'''
    call = '''
async def request(base):
    async with httpx.AsyncClient() as http:
        with pytest.raises(httpx.RemoteProtocolError):
            await http.get(base + "/mcp/")
'''
    body = '''
async def test_incident(served):
    async with asyncio.timeout(3):
        await request(served)
''' if style.startswith("fixture") else '''
async def test_incident():
    gate = asyncio.Event()
    gate.set()
    async with asyncio.timeout(3):
        async with serving(_IncompleteResponseApp(gate)) as base:
            await request(base)
'''
    if style.endswith("error"):
        call = call.replace("with pytest.raises(httpx.RemoteProtocolError):", "if True:")
    probe = tmp_path / "test_incident_probe.py"
    probe.write_text(textwrap.dedent('''\
import asyncio
import httpx
import pytest
from tests.conftest import serving
from tests.test_server import _IncompleteResponseApp

async def test_unrelated():
    assert True
''') + fixture + call + body)
    result = subprocess.run([sys.executable, "-m", "pytest", str(probe), "-q", "-p", "tests.conftest",
                             "-c", "pyproject.toml", "-p", "no:cacheprovider"],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=10)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "AssertionError: Incomplete HTTP response" in result.stdout
    assert "FAILED" in result.stdout and "::test_incident" in result.stdout
    assert "1 failed, 1 passed" in result.stdout
    assert "ERROR at setup" not in result.stdout and "ERROR at teardown" not in result.stdout


async def test_serving_recorder_library_log_privacy():
    gate = asyncio.Event()
    gate.set()
    secrets = ["abcdef0123456789abcdef0123456789", "9000000123", "BearerSecretAlphaToken"]
    async with asyncio.timeout(3):
        with pytest.raises(AssertionError, match="Incomplete HTTP response") as failure:
            async with serving(_IncompleteResponseApp(gate)) as base:
                recorder = conftest._HTTP_RECORDER.get()
                logging.getLogger("mcp").warning(
                    "session=" + secrets[0] + " phone=" + secrets[1] + " bearer=" + secrets[2])
                logging.getLogger("fastmcp").warning("payload %s", {"patient": "PRIVATE-PATIENT"})
                async with httpx.AsyncClient() as http:
                    with pytest.raises(httpx.RemoteProtocolError):
                        await http.get(base + "/mcp/")
    assert len(recorder.warnings) == 2
    assert {r["logger"] for r in recorder.warnings} == {"mcp", "fastmcp"}
    assert all(r["level"] == "WARNING" for r in recorder.warnings)
    for secret in [*secrets, "PRIVATE-PATIENT"]:
        assert secret not in json.dumps(recorder.warnings) and secret not in str(failure.value)


async def test_serving_recorder_distinguishes_raise_complete_and_disconnect(capsys):
    class Probe(_LifespanApp):
        async def __call__(self, scope, receive, send):
            if scope["type"] == "http" and scope["method"] == "POST":
                await send({"type": "http.response.start", "status": 200, "headers": []})
                raise ValueError("PRIVATE-EXCEPTION")
            return await super().__call__(scope, receive, send)

    gate = asyncio.Event()
    gate.set()
    loggers = [logging.getLogger(name) for name in ("uvicorn.error", "mcp", "fastmcp", "starlette", "docket")]
    handlers = [list(logger.handlers) for logger in loggers]
    async with asyncio.timeout(3):
        async with serving(Probe(gate)) as base:
            recorder = conftest._HTTP_RECORDER.get()
            async with httpx.AsyncClient() as http:
                assert (await http.get(base + "/health")).status_code == 200
                with pytest.raises(httpx.RemoteProtocolError):
                    await http.post(base + "/mcp/")
    assert not recorder.incidents
    assert recorder.requests[0]["complete"] and recorder.requests[0]["returned"]
    assert recorder.requests[1]["raised"] == "ValueError" and not recorder.requests[1]["returned"]
    assert "PRIVATE-EXCEPTION" not in recorder.report()
    assert [logger.handlers for logger in loggers] == handlers
    assert capsys.readouterr().out == ""

    async def disconnect_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200})
        assert (await receive())["type"] == "http.disconnect"

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        pass

    recorder = conftest._HTTPRecorder(disconnect_app, asyncio.current_task)
    async with asyncio.timeout(1):
        await recorder({"type": "http", "method": "GET", "path": "/mcp/", "headers": []}, receive, send)
    assert recorder.requests[0]["disconnected"] and not recorder.incidents


async def test_serving_recorder_preserves_ordinary_cancellation():
    gate = asyncio.Event()
    gate.set()
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.1):
            async with serving(_LifespanApp(gate)):
                await asyncio.Event().wait()


async def test_serving_recorder_prioritizes_classified_chains():
    import contextlib

    @contextlib.asynccontextmanager
    async def blocked_context():
        await asyncio.Event().wait()
        yield

    # A real wait chain with the library's filename exercises classification through contextlib.
    async def connection_wait():
        async with blocked_context():
            pass

    import inspect

    connection_wait.__code__ = connection_wait.__code__.replace(co_filename=inspect.getfile(Client))
    ordinary = [asyncio.create_task(asyncio.Event().wait()) for _ in range(45)]
    connection = asyncio.create_task(connection_wait())
    try:
        async with asyncio.timeout(1):
            await asyncio.sleep(0)
            dump = conftest._pending_task_dump(asyncio.current_task())
        assert "class=client" in dump.split("\ntask ")[2]
        assert f"name={connection.get_name()} " in dump.split("\ntask ")[2]
        assert len(dump) <= 12000
    finally:
        for task in [*ordinary, connection]:
            task.cancel()
        await asyncio.gather(*ordinary, connection, return_exceptions=True)


async def test_serving_recorder_keeps_concurrent_servers_separate():
    gate = asyncio.Event()
    gate.set()
    async with asyncio.timeout(3):
        with pytest.raises(AssertionError, match="Incomplete HTTP response"):
            async with serving(_IncompleteResponseApp(gate)) as broken:
                first = conftest._HTTP_RECORDER.get()
                async with serving(_LifespanApp(gate)) as healthy:
                    second = conftest._HTTP_RECORDER.get()
                    async with httpx.AsyncClient() as http:
                        assert (await http.get(healthy + "/health")).status_code == 200
                        with pytest.raises(httpx.RemoteProtocolError):
                            await http.get(broken + "/mcp/")
    assert len(first.incidents) == len(first.confirmations) == 1
    assert not second.incidents and not second.confirmations


async def test_serving_recorder_preserves_safe_library_message_and_logger():
    gate = asyncio.Event()
    gate.set()
    async with asyncio.timeout(3):
        async with serving(_LifespanApp(gate)):
            recorder = conftest._HTTP_RECORDER.get()
            logging.getLogger("mcp.server.streamable_http").error("No response message received before stream closed")
    assert recorder.warnings[0]["logger"] == "mcp.server.streamable_http"
    assert recorder.warnings[0]["message"] == "No response message received before stream closed"


class _ShutdownResponseApp(_LifespanApp):
    def __init__(self):
        gate = asyncio.Event()
        gate.set()
        super().__init__(gate)
        self.request_started = asyncio.Event()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await super().__call__(scope, receive, send)
        import signal

        server = signal.getsignal(signal.SIGTERM).__self__
        await send({"type": "http.response.start", "status": 200, "headers": []})
        self.request_started.set()
        if scope["method"] == "POST":
            return
        while not server.should_exit:
            await asyncio.sleep(0.01)
        await send({"type": "http.response.body", "body": b"probe", "more_body": True})


@pytest.mark.parametrize("body_error", [None, "body failure"])
async def test_recorder_t4_reports_shutdown_incident_once(body_error):
    app = _ShutdownResponseApp()
    async with asyncio.timeout(3):
        async with httpx.AsyncClient() as http:
            request = None
            try:
                with pytest.raises(AssertionError) as failure:
                    async with serving(app) as base:
                        request = asyncio.create_task(http.get(base + "/mcp/"))
                        await app.request_started.wait()
                        if body_error:
                            raise AssertionError(body_error)
                if body_error:
                    assert str(failure.value) == body_error
                    report = "\n".join(failure.value.__notes__)
                else:
                    report = str(failure.value)
                assert report.count("Incomplete HTTP response:") == 1
                assert "POST" not in report and "GET /mcp/ #1" in report
            finally:
                if request:
                    with pytest.raises(httpx.RemoteProtocolError):
                        await request


@pytest.mark.parametrize("style", ["direct", "fixture"])
@pytest.mark.parametrize("behavior", ["cancel", "own_failure", "interrupt", "late"])
def test_recorder_t4_exception_and_teardown_ownership(tmp_path, style, behavior):
    import subprocess
    import sys

    source = '''
import asyncio
import contextlib
import httpx
import pytest
from tests.conftest import serving
from tests.test_server import _IncompleteResponseApp, _ShutdownResponseApp

@contextlib.asynccontextmanager
async def host():
    gate = asyncio.Event()
    gate.set()
    app = APP
    async with httpx.AsyncClient() as http:
        try:
            async with serving(app) as base:
                yield app, http, base
        finally:
            if hasattr(app, "request_task"):
                with pytest.raises(httpx.RemoteProtocolError):
                    await app.request_task

@pytest.fixture
async def server():
    async with host() as values:
        yield values

async def exercise(app, http, base):
    ACTION
'''
    if behavior == "late":
        action = '''app.request_task = asyncio.create_task(http.get(base + "/mcp/"))
    await app.request_started.wait()'''
    else:
        action = '''with pytest.raises(httpx.RemoteProtocolError):
        await http.get(base + "/mcp/")
    ''' + {
            "cancel": "asyncio.current_task().cancel()\n    await asyncio.Event().wait()",
            "own_failure": 'raise AssertionError("ORIGINAL_BODY_FAILURE")',
            "interrupt": 'raise KeyboardInterrupt("PROBE_INTERRUPT")',
        }[behavior]
    source = source.replace("APP", "_ShutdownResponseApp()" if behavior == "late" else "_IncompleteResponseApp(gate)")
    source = source.replace("ACTION", action)
    source += '''
async def test_owner(server):
    async with asyncio.timeout(3):
        await exercise(*server)
''' if style == "fixture" else '''
async def test_owner():
    async with asyncio.timeout(3):
        async with host() as values:
            await exercise(*values)
'''
    probe = tmp_path / "test_t4_owner.py"
    probe.write_text(source)
    result = subprocess.run([sys.executable, "-m", "pytest", str(probe), "-q", "-p", "tests.conftest",
                             "-c", "pyproject.toml", "-p", "no:cacheprovider"],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=10)
    output = result.stdout + result.stderr
    assert "Incomplete HTTP response:" in output, output
    if behavior == "interrupt":
        assert result.returncode == 2 and "KeyboardInterrupt: PROBE_INTERRUPT" in output, output
        assert "1 failed" not in output
    elif behavior == "late" and style == "fixture":
        assert result.returncode == 1 and "ERROR at teardown of test_owner" in output, output
        assert "1 passed" in output and "1 error" in output and "FAILED" not in output
    elif behavior == "cancel":
        assert result.returncode == 1 and " - asyncio.exceptions.CancelledError" in output, output
    else:
        assert result.returncode == 1 and "FAILED" in output, output
        if behavior == "own_failure":
            assert "ORIGINAL_BODY_FAILURE" in output and "direct cause" in output


async def test_recorder_t4_outer_timeout_keeps_cancellation():
    gate = asyncio.Event()
    gate.set()
    with pytest.raises(TimeoutError) as failure:
        async with asyncio.timeout(0.15):
            async with serving(_IncompleteResponseApp(gate)) as base:
                async with httpx.AsyncClient() as http:
                    with pytest.raises(httpx.RemoteProtocolError):
                        await http.get(base + "/mcp/")
                await asyncio.Event().wait()
    assert isinstance(failure.value.__cause__, asyncio.CancelledError)
    assert "Incomplete HTTP response:" in "\n".join(failure.value.__cause__.__notes__)


async def test_recorder_t4_reports_body_and_shutdown_incidents_separately():
    app = _ShutdownResponseApp()
    async with asyncio.timeout(3):
        async with httpx.AsyncClient() as http:
            request = None
            try:
                with pytest.raises(AssertionError) as failure:
                    async with serving(app) as base:
                        with pytest.raises(httpx.RemoteProtocolError):
                            await http.post(base + "/mcp/")
                        app.request_started.clear()
                        request = asyncio.create_task(http.get(base + "/mcp/"))
                        await app.request_started.wait()
                assert str(failure.value).splitlines()[0].startswith("Incomplete HTTP response: POST /mcp/ #1")
                assert len(failure.value.__notes__) == 1
                assert failure.value.__notes__[0].splitlines()[0].startswith("Incomplete HTTP response: GET /mcp/ #2")
                assert len(json.loads(str(failure.value).split("\n", 1)[1])["incidents"]) == 1
                assert len(json.loads(failure.value.__notes__[0].split("\n", 1)[1])["incidents"]) == 1
            finally:
                if request:
                    with pytest.raises(httpx.RemoteProtocolError):
                        await request


async def test_recorder_t4_late_incident_does_not_replace_shutdown_limit():
    app = _ShutdownResponseApp()
    app.shutdown_gate.clear()
    before = asyncio.all_tasks()
    async with asyncio.timeout(3):
        async with httpx.AsyncClient() as http:
            request = None
            try:
                with pytest.raises(AssertionError, match="test server shutdown exceeded") as failure:
                    async with serving(app, shutdown_limit=0.3) as base:
                        request = asyncio.create_task(http.get(base + "/mcp/"))
                        await app.request_started.wait()
                assert len(failure.value.__notes__) == 1
                assert "Incomplete HTTP response: GET /mcp/ #1" in failure.value.__notes__[0]
            finally:
                app.shutdown_gate.set()
                if request:
                    with pytest.raises(httpx.RemoteProtocolError):
                        await request
                remaining = asyncio.all_tasks() - before
                if remaining:
                    _, pending = await asyncio.wait(remaining, timeout=1)
                    assert not pending


async def test_recorder_t4_reverse_correlation_uses_real_uvicorn():
    class InvalidHeader(_LifespanApp):
        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                return await super().__call__(scope, receive, send)
            try:
                await send({"type": "http.response.start", "status": 200,
                            "headers": [(b"x-probe", b"invalid\nheader")]})
            except RuntimeError:
                return

    gate = asyncio.Event()
    gate.set()
    async with asyncio.timeout(3):
        with pytest.raises(AssertionError) as failure:
            async with serving(InvalidHeader(gate)) as base:
                recorder = conftest._HTTP_RECORDER.get()
                async with httpx.AsyncClient() as http:
                    with pytest.raises(httpx.RemoteProtocolError):
                        await http.post(base + "/mcp/")
    assert len(recorder.incidents) == 1
    incident = recorder.incidents[0]
    assert incident["request"]["sequence"] == 1 and incident["request"]["method"] == "POST"
    assert incident["request"]["path"] == "/mcp/" and incident["flags_disagree"] is True
    assert incident["confirmed"] is True and "confirmed=true" in str(failure.value)
    assert recorder.confirmations[0]["incident"] == 1


async def test_recorder_t4_unconfirmed_candidates_and_flag(monkeypatch):
    import sys
    import types

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200})

    async def receive():
        return {"type": "http.request"}

    async def send(message):
        pass

    scope = {"type": "http", "method": "POST", "path": "/mcp/", "headers": []}
    async with asyncio.timeout(1):
        for flag in (None, False, True):
            if flag is None:
                monkeypatch.delitem(sys.modules, "sse_starlette.sse", raising=False)
            else:
                monkeypatch.setitem(sys.modules, "sse_starlette.sse",
                                    types.SimpleNamespace(AppStatus=types.SimpleNamespace(should_exit=flag)))
            recorder = conftest._HTTPRecorder(app, asyncio.current_task)
            await recorder(scope, receive, send)
            assert "confirmed=false" in recorder.failure()
            assert recorder.incidents[0]["sse_should_exit"] is flag
            token = conftest._HTTP_RECORDER.set(recorder)
            request_token = recorder._request.set(None)
            try:
                recorder.emit(logging.LogRecord("uvicorn.error", logging.ERROR, "", 0,
                                                "ASGI callable returned without completing response.", (), None))
            finally:
                recorder._request.reset(request_token)
                conftest._HTTP_RECORDER.reset(token)
            assert recorder.incidents[-1]["request"] is None
            assert [r["sequence"] for r in recorder.incidents[-1]["candidates"]] == [1]


def _names(schema) -> set[str]:
    found: set[str] = set()
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key == "properties" and isinstance(value, dict):
                found |= {k.lower().replace("_", "") for k in value}
            found |= _names(value)
    elif isinstance(schema, list):
        for item in schema:
            found |= _names(item)
    return found


@pytest.fixture
async def served(make_settings):
    h = harness.build(make_settings())
    app = create_app(h.settings, ops_transport=h.ops.http._transport, knowledge_transport=h.knowledge.http._transport,
                     clock=h.clock)
    async with serving(app) as base:
        yield base, h
    await h.aclose()


def client(base: str, token: str = "mcp-token", **kwargs) -> Client:
    return Client(StreamableHttpTransport(f"{base}/mcp/", headers={"Authorization": f"Bearer {token}",
                                                                    **harness.headers(**kwargs)}))


async def test_gateway_gets_all_four_tools_without_trusted_fields(served):
    base, _ = served
    async with client(base) as c:
        tools = await c.list_tools()
        instructions = c.initialize_result.instructions
    assert sorted(t.name for t in tools) == TOOLS
    for tool in tools:
        leaked = (_names(tool.inputSchema) | _names(tool.outputSchema or {})) & FORBIDDEN
        assert leaked == set(), f"{tool.name} exposes {leaked}"
        assert tool.outputSchema, f"{tool.name} has no output schema"
    booking = next(t for t in tools if t.name == "manage_booking")
    assert booking.annotations.readOnlyHint is False and booking.annotations.destructiveHint is True
    availability = next(t for t in tools if t.name == "get_doctor_availability")
    assert availability.annotations.readOnlyHint is True
    assert "NOTED" in instructions and prompt.SCHEMA_VERSION in instructions


async def test_working_hours_and_missing_date_are_exposed_through_mcp(served):
    base, h = served
    async with client(base) as c:
        tool = next(t for t in await c.list_tools() if t.name == "get_doctor_availability")
        hours = await c.call_tool("get_doctor_availability", {
            "doctorId": "doc_garima", "purpose": "WORKING_HOURS"}, raise_on_error=False)
        missing = await c.call_tool("get_doctor_availability", {"doctorId": "doc_garima"}, raise_on_error=False)
    assert not hours.is_error and hours.structured_content["outcome"] == "WORKING_HOURS"
    assert not missing.is_error and missing.structured_content["detail"] == "DATE_REQUIRED"
    assert "date" not in tool.inputSchema.get("required", []) and "/availability" not in h.ops_paths()
    assert tool.outputSchema["$defs"]["BoardSessionOut"]["properties"]["status"]["enum"] == [
        "IN", "LATE", "CANCELLED", "NOT_CONFIRMED", "UNKNOWN"]


def test_availability_description_distinguishes_counts_and_sources(make_settings):
    doc = cli.schema_document(make_settings())
    text = next(t["description"] for t in doc["tools"] if t["name"] == "get_doctor_availability")
    for fact in ("totalMatches", "bookableFound", "complete", "WORKING_HOURS", "decision", "status",
                 "NOT_AVAILABLE", "HANDOFF_REQUIRED", "SESSION_ENDED", "attendance not confirmed"):
        assert fact in text


async def test_department_booking_is_absent_from_schema_and_refused_without_writes(served):
    base, h = served
    async with client(base, operation_id="no-department") as c:
        tool = next(t for t in await c.list_tools() if t.name == "manage_booking")
        assert "departmentId" not in tool.inputSchema["properties"]
        result = await c.call_tool("manage_booking", {"action": "CREATE", "departmentId": "dept_genmed",
            "patientName": "Synthetic", "patientMobile": "9000000101", "visitDate": "2026-10-05",
            "callerConfirmed": True}, raise_on_error=False)
    assert result.is_error and not h.ops_state.appointments


async def test_gateway_can_save_a_summary_with_trusted_call_identity(served):
    base, h = served
    async with client(base, started_at="2026-10-01T09:58:00+05:30") as c:
        result = await c.call_tool("record_call_summary", {
            "intent": "GENERAL_INFO", "outcome": "RESOLVED_BY_AGENT", "summaryText": "Explained visiting hours."},
            raise_on_error=False)
        tool = next(t for t in await c.list_tools() if t.name == "record_call_summary")
    assert result.structured_content == {"outcome": "SAVED"}
    assert h.ops_state.summaries["call-1"]["summaryText"] == "Explained visiting hours."
    assert tool.annotations.readOnlyHint is False and tool.annotations.idempotentHint is True


async def test_gateway_must_authenticate_and_health_stays_open(served):
    base, _ = served
    async with httpx.AsyncClient() as http:
        assert (await http.post(f"{base}/mcp/", json={})).status_code == 401
        assert (await http.post(f"{base}/mcp/", json={}, headers={"Authorization": "Bearer nope"})).status_code == 401
        assert (await http.post(f"{base}/mcp/", json={},
                                headers={"Authorization": "Bearer lifecycle-token"})).status_code == 401
        assert (await http.get(f"{base}/health")).json() == {"status": "ok"}
        ready = await http.get(f"{base}/ready")
        assert ready.status_code == 200 and ready.json()["status"] == "ready"


def test_tool_schemas_match_the_pinned_snapshot(make_settings):
    assert SNAPSHOT.is_file(), "the tool schema snapshot must stay tracked (regenerate: frontdesk-mcp schema)"
    document = cli.schema_document(make_settings())
    assert document == json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert document["schemaVersion"] == prompt.SCHEMA_VERSION
    assert sorted(t["name"] for t in document["tools"]) == TOOLS


async def test_the_whole_journey_over_http(served):
    base, h = served
    async with client(base, operation_id="op-1") as c:
        found = await c.call_tool("get_doctor_availability", {"doctorName": "garima", "date": "2026-10-02"})
        assert found.structured_content["outcome"] == "AVAILABILITY"  # future uses the usual schedule
        today = (await c.call_tool("get_doctor_availability", {"doctorName": "garima", "date": "today"})
                 ).structured_content
        assert today["outcome"] == "AVAILABILITY" and len(today["doctors"][0]["board"]) == 2
        unknown_day = (await c.call_tool("manage_booking", {
            "action": "CREATE", "patientName": "Lakshmi Rao", "patientMobile": "9000000101",
            "doctorId": "doc_vikram_desai",
            "visitDate": "2026-10-02", "preferredTime": "09:30", "reasonVerbatim": "fever", "callerConfirmed": True,
        })).structured_content
        assert unknown_day["outcome"] == "HANDOFF_REQUIRED"  # no confirmed on-call entry for this date
        noted = (await c.call_tool("manage_booking", {
            "action": "CREATE", "patientName": "Lakshmi Rao", "patientMobile": "9000000101", "doctorId": "doc_garima",
            "visitDate": "2026-10-01", "preferredTime": "10:45", "reasonVerbatim": "fever", "callerConfirmed": True,
        })).structured_content
        assert noted["outcome"] == "NOTED"
        appointment_id = noted["appointment"]["appointmentId"]
        listed = (await c.call_tool("manage_booking", {"action": "LIST"})).structured_content
        assert [a["appointmentId"] for a in listed["appointments"]] == [appointment_id]
        answer = (await c.call_tool("search_knowledge", {"question": "parking", "language": "en"})).structured_content
        assert answer["outcome"] == "ANSWERED"
    async with client(base, operation_id="op-2") as c:
        unknown_move = (await c.call_tool("manage_booking", {"action": "RESCHEDULE", "appointmentId": appointment_id,
                                                             "newVisitDate": "2026-10-03", "callerConfirmed": True})
                        ).structured_content
        assert unknown_move["outcome"] == "NOT_AVAILABLE"  # Saturday is not a usual day
        moved = (await c.call_tool("manage_booking", {"action": "RESCHEDULE", "appointmentId": appointment_id,
                                                      "newVisitDate": "2026-10-05", "callerConfirmed": True})
                 ).structured_content
        assert moved["outcome"] == "NOTED"
    async with client(base, operation_id="op-3") as c:
        cancelled = (await c.call_tool("manage_booking", {"action": "CANCEL", "appointmentId": appointment_id,
                                                          "callerConfirmed": True})).structured_content
        assert cancelled["outcome"] == "CANCELLED"
    async with client(base, started_at="2026-10-01T09:58:00+05:30") as c:
        stored = (await c.call_tool("record_call_summary", {
            "intent": "BOOKING", "outcome": "APPOINTMENT_CANCELLED", "appointmentId": appointment_id,
            "summaryText": "Requested, moved and cancelled an appointment with Dr. Garima."})).structured_content
        assert stored == {"outcome": "SAVED"}
    assert "durationSeconds" not in h.ops_state.summaries["call-1"]


async def test_the_model_cannot_supply_booking_identity_fields(served):
    base, h = served
    async with client(base) as c:
        for extra in ({"callId": "other"}, {"callerNumber": "+919000000999"}, {"operationId": "x"},
                      {"X-Caller-Number": "+919000000999"}, {"patientMobile": "9000000999"}):
            result = await c.call_tool("manage_booking", {"action": "LIST", **extra}, raise_on_error=False)
            assert result.is_error or result.structured_content["outcome"] in ("NOT_FOUND", "FOUND"), extra
        assert (await c.call_tool("manage_booking", {"action": "LIST"})).structured_content["outcome"] == "NOT_FOUND"
    queries = [r for r in h.requests if r.url.path.endswith("/appointments") and r.method == "GET"]
    assert queries and all(r.url.params["mobile"] == "9000000101" for r in queries)


async def test_summary_arguments_cannot_override_trusted_headers(served):
    base, h = served
    async with client(base, started_at="2026-10-01T09:58:00+05:30") as c:
        result = await c.call_tool("record_call_summary", {
            "intent": "OTHER", "outcome": "ABANDONED", "summaryText": "Caller left.",
            "callId": "forged-call", "startedAt": "2020-01-01T00:00:00Z"}, raise_on_error=False)
        assert result.is_error or result.structured_content == {"outcome": "SAVED"}
        await c.call_tool("record_call_summary", {
            "intent": "OTHER", "outcome": "ABANDONED", "summaryText": "Caller left."})
    assert set(h.ops_state.summaries) == {"call-1"}
    assert h.ops_state.summaries["call-1"]["startedAt"] == "2026-10-01T09:58:00+05:30"


async def test_concurrent_summaries_keep_their_own_call_and_start_time(served):
    base, h = served

    async def one(i):
        async with client(base, call_id=f"call-{i}", started_at=f"2026-10-01T09:0{i}:00+05:30") as c:
            return (await c.call_tool("record_call_summary", {
                "intent": "OTHER", "outcome": "ABANDONED", "summaryText": f"Conversation {i}."},
                raise_on_error=False)).structured_content

    assert await asyncio.gather(*(one(i) for i in range(1, 6))) == [{"outcome": "SAVED"}] * 5
    for i in range(1, 6):
        stored = h.ops_state.summaries[f"call-{i}"]
        assert stored["startedAt"] == f"2026-10-01T09:0{i}:00+05:30"
        assert stored["summaryText"] == f"Conversation {i}."


async def test_concurrent_calls_keep_their_own_identity(served):
    base, h = served

    async def one(call_id: str, caller: str):
        async with client(base, call_id=call_id, caller=caller, operation_id=f"op-{call_id}") as c:
            await c.call_tool("manage_booking", {
                "action": "CREATE", "patientName": f"Patient {call_id}", "patientMobile": caller[3:],
                "doctorId": "doc_garima", "visitDate": "2026-10-01", "session": "Morning", "callerConfirmed": True})
            return (await c.call_tool("manage_booking", {"action": "LIST"})).structured_content

    results = await asyncio.gather(*(one(f"call-{i}", f"+91900000010{i}") for i in range(1, 6)))
    for i, listed in enumerate(results, start=1):
        assert [a["patientName"] for a in listed["appointments"]] == [f"Patient call-{i}"]
    assert len(h.ops_state.appointments) == 5
    assert {a["callId"] for a in h.ops_state.appointments.values()} == {f"call-{i}" for i in range(1, 6)}


async def test_dependency_status_is_separate_from_local_readiness(served, monkeypatch):
    from frontdesk_mcp import server as server_module

    monkeypatch.setattr(server_module, "DEPENDENCY_REFRESH_MIN_INTERVAL", 0.0)  # the throttle has its own test
    base, h = served
    async with httpx.AsyncClient() as http:
        healthy = (await http.get(f"{base}/dependencies")).json()
        assert healthy["operational"]["status"] == "ok" and healthy["knowledge"]["status"] == "configured"
        h.ops_state.fail_next.append(("/departments", 503, {}))
        h.ops_state.fail_next.append(("/departments", 503, {}))
        degraded = await http.get(f"{base}/dependencies", params={"refresh": "1"})
        assert degraded.status_code == 503 and degraded.json()["operational"]["status"] == "unavailable"
        assert (await http.get(f"{base}/ready")).status_code == 200  # local readiness is unaffected


async def test_log_lines_carry_the_call_id_not_the_caller(served):
    base, _ = served
    lines: list[dict] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(json.loads(JsonFormatter("demo-hospital").format(record)))

    package = logging.getLogger("frontdesk_mcp")
    handler = Capture()
    package.addHandler(handler)
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        async with client(base, call_id="call-log-1") as c:
            await c.call_tool("get_doctor_availability", {"doctorName": "garima", "date": "today"})
            await c.call_tool("manage_booking", {"action": "LIST"})  # upstream query carries ?mobile=
    finally:
        package.removeHandler(handler)
        root.removeHandler(handler)
    results = [line for line in lines if line["msg"] == "tool_result"]
    assert results and results[0]["callId"] == "call-log-1" and results[0]["outcome"] == "AVAILABILITY"
    assert all(line["provider"] == "demo-hospital" for line in lines)
    assert "9000000101" not in json.dumps(lines), "a caller number reached the logs (httpx request lines?)"
    assert "garima" not in json.dumps(lines).lower()


def test_pack_describes_exactly_the_four_tools():
    assert set(packs.load("healthcare").tools) == set(TOOLS)


def test_published_tool_text_contains_facts_not_behaviour_scripts(make_settings):
    from frontdesk_mcp.cli import schema_document

    document = schema_document(make_settings())
    text = [document["instructions"]]

    def descriptions(value):
        if isinstance(value, dict):
            text.extend(v for k, v in value.items() if k == "description")
            for child in value.values():
                descriptions(child)
        elif isinstance(value, list):
            for child in value:
                descriptions(child)

    descriptions(document["tools"])
    forbidden = ("say ", "never say", "ask ", "transfer immediately", "speak ", "pass ",
                 "read back", "read-back", "do not", "never ", "collect ", "use ")
    for entry in text:
        for phrase in forbidden:
            assert re.search(r"\b" + re.escape(phrase), entry.casefold()) is None, (phrase, entry)


def test_server_instructions_are_short_contract_facts():
    text = prompt.instructions(packs.load("healthcare"), ("en", "kn", "hi"), "Demo Hospital")
    assert len(text) < 1000
    for fact in ("Demo Hospital", "en, kn, hi", "YYYY-MM-DD", "relative dates are not accepted",
                 "NOTED", "CALLBACK_REQUIRED", "UNCERTAIN", prompt.SCHEMA_VERSION):
        assert fact in text


# ------------------------------------------------------------------ review fixes (1 Oct 2026)


async def test_dependency_refresh_is_single_flight_and_throttled(served):
    """Review fix: an unauthenticated ?refresh=1 must not be able to drive owner traffic per hit."""
    base, h = served
    before = len([r for r in h.requests if r.url.path.endswith("/departments")])
    async with httpx.AsyncClient() as http:
        await asyncio.gather(*(http.get(f"{base}/dependencies", params={"refresh": "1"}) for _ in range(8)))
        await http.get(f"{base}/dependencies", params={"refresh": "1"})
    after = len([r for r in h.requests if r.url.path.endswith("/departments")])
    assert after - before <= 1  # one upstream check for nine refresh requests inside the minimum interval


async def test_results_carry_an_output_schema_and_structured_content_without_sdk_revalidation(served):
    """Review fix: the SDK re-validated every result against a 6 KB schema (~16 ms CPU per call). Results
    are returned as CallToolResult (via ToolResult.meta) so the SDK trusts the pydantic-validated content;
    the schema is still advertised for clients."""
    base, _ = served
    async with client(base) as c:
        tools = {t.name: t for t in await c.list_tools()}
        assert tools["get_doctor_availability"].outputSchema["properties"]["outcome"]
        result = await c.call_tool("get_doctor_availability", {"doctorName": "garima", "date": "today"})
    assert result.structured_content["outcome"] == "AVAILABILITY"
    assert result.meta == {"schemaVersion": prompt.SCHEMA_VERSION}


def test_an_external_suite_exists_for_owner_designated_services():
    """scripts/test.sh runs `pytest -m external` when OPS_E2E_BASE_URL is set; the marker must select tests."""
    import subprocess
    import sys

    out = subprocess.run([sys.executable, "-m", "pytest", "tests", "-m", "external", "--collect-only", "-q",
                          "-p", "no:cacheprovider"], capture_output=True, text=True, check=False)
    import re

    assert "test_external.py" in out.stdout
    collected = re.search(r"(\d+)(?:/\d+)? tests? collected", out.stdout)
    assert collected and int(collected.group(1)) >= 3, out.stdout[-300:]


async def test_smoke_distinguishes_unconfigured_knowledge_from_scheduling_failure(make_settings, capsys):
    import runpy

    smoke = runpy.run_path(str(Path(__file__).resolve().parents[3] / "deploy/azure/smoke.py"))
    settings = make_settings(knowledge_base_url="", knowledge_bearer_token="")
    h = harness.build(settings)
    app = create_app(settings, ops_transport=h.ops.http._transport, clock=h.clock)
    try:
        async with serving(app) as base:
            await smoke["smoke"](f"{base}/mcp/", "mcp-token", "en", "General Medicine", "absent")
        assert "knowledge: NOT_CONFIGURED" in capsys.readouterr().out
        assert h.ops_state.summaries == {} and h.ops_state.appointments == {}
        assert not [r for r in h.requests if r.method == "POST" and r.url.path != "/api/v1/auth/token"]
    finally:
        await h.aclose()


def test_cli_exposes_only_server_and_schema_commands():
    import subprocess

    result = subprocess.run(["frontdesk-mcp", "--help"], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert "{serve,schema}" in result.stdout



def test_routing_object_cannot_claim_a_clarification_decision():
    from pydantic import ValidationError

    from frontdesk_mcp.outcomes import Routing

    with pytest.raises(ValidationError):
        Routing(decision="CLARIFY")


def _interface_rows():
    text = (Path(__file__).resolve().parents[3] / "docs/handover/VOICE-TEAM.md").read_text()
    rows = {}
    for line in text.splitlines():
        if line.startswith("| `"):
            cells = [c.strip().strip("`") for c in line.strip("|").split(" | ")]
            assert cells[0] not in rows, f"duplicate interface row: {cells[0]}"
            rows[cells[0]] = cells[1:]
    return text, rows


def test_interface_parameter_and_output_tables_match_pinned_schema():
    snapshot = json.loads((Path(__file__).parent / "contracts/mcp-tools.snapshot.json").read_text())
    text, rows = _interface_rows()
    assert f"Schema version: `{snapshot['schemaVersion']}`" in text
    expected = {}

    def wire_shape(value):
        # Descriptions are separate prose; output defaults include callback metadata,
        # which is intentionally not reproduced as a spoken script in the interface document.
        if isinstance(value, dict):
            return {k: wire_shape(v) for k, v in value.items() if k not in ("title", "description", "default")}
        if isinstance(value, list):
            return [wire_shape(v) for v in value]
        return value

    for tool in snapshot["tools"]:
        for kind, schema in (("input", tool["inputSchema"]), ("output", tool["outputSchema"])):
            objects = [("", schema), *[(f"$defs.{name}.", definition)
                                      for name, definition in schema.get("$defs", {}).items()]]
            for prefix, obj in objects:
                for field, shape in obj.get("properties", {}).items():
                    key = f"{tool['name']}.{kind}.{prefix}{field}"
                    expected[key] = (wire_shape(shape), "required" if field in obj.get("required", []) else "optional")
                    assert key in rows, f"missing interface field: {key}"
                    cells = rows[key]
                    assert len(cells) == 3 and cells[2], f"missing field meaning: {key}"
                    assert (json.loads(cells[0]), cells[1]) == expected[key], key
                    if kind == "input":
                        assert cells[2] == shape["description"], key
    actual = {key for key in rows if ".input." in key or ".output." in key}
    assert actual == set(expected)


def test_interface_describes_every_outcome_and_next_step():
    from typing import get_args

    from frontdesk_mcp import outcomes

    _, rows = _interface_rows()
    models = {"get_doctor_availability": outcomes.AvailabilityResult, "manage_booking": outcomes.BookingResult,
              "search_knowledge": outcomes.KnowledgeResult, "record_call_summary": outcomes.SummaryResult}
    expected = set()
    for name, model in models.items():
        for field in ("outcome", "nextStep") if name != "record_call_summary" else ("outcome",):
            for value in get_args(model.model_fields[field].annotation):
                key = f"{name}.{field}.{value}"
                expected.add(key)
                assert key in rows and len(rows[key]) == 1 and rows[key][0], f"undocumented meaning: {key}"
    actual = {key for key in rows if ".outcome." in key or ".nextStep." in key}
    assert actual == expected


@pytest.mark.parametrize("length", [501, 2000])
async def test_summary_length_is_an_in_band_invalid_request(served, length):
    base, h = served
    async with client(base, started_at="2026-10-01T09:58:00+05:30") as c:
        result = await c.call_tool("record_call_summary", {
            "intent": "GENERAL_INFO", "outcome": "RESOLVED_BY_AGENT", "summaryText": "x" * length},
            raise_on_error=False)
        tool = next(t for t in await c.list_tools() if t.name == "record_call_summary")
    assert not result.is_error
    assert result.structured_content == {"outcome": "INVALID_REQUEST", "fields": ["summaryText"]}
    assert tool.inputSchema["properties"]["summaryText"]["maxLength"] == 500
    assert not h.ops_state.summaries


@pytest.mark.parametrize("invalid", [
    {"summaryText": {"private": "NAME42 9000000123 SYMPTOM42"}},
    {"summaryText": ["NAME42", "9000000123", "SYMPTOM42"]},
    {"summaryText": 9000000123},
    {"summaryText": "NAME42 9000000123 SYMPTOM42" + "x" * 1974},
    {"intent": "NAME42 9000000123 SYMPTOM42"},
    {"callerMobile": {"private": "NAME42 9000000123 SYMPTOM42"}},
    {"NAME42 9000000123 SYMPTOM42": "unexpected argument"},
], ids=["object", "list", "number", "outer-cap", "enum", "contact-type", "unexpected-key"])
async def test_invalid_summary_does_not_echo_private_input_in_protocol_or_logs(served, invalid, caplog, capsys):
    base, h = served
    async with client(base, started_at="2026-10-01T09:58:00+05:30") as c:
        result = await c.call_tool("record_call_summary", {
            "intent": "GENERAL_INFO", "outcome": "RESOLVED_BY_AGENT", "summaryText": "Whole call.", **invalid},
            raise_on_error=False)
    captured = capsys.readouterr()
    response = json.dumps({"content": [block.model_dump(mode="json") for block in result.content],
                           "structuredContent": result.structured_content, "meta": result.meta})
    for marker in ("NAME42", "9000000123", "SYMPTOM42"):
        assert marker not in response + caplog.text + captured.out + captured.err
    assert result.is_error and result.structured_content is None
    assert "argument" in response.lower()  # still an explicit argument error, not a success envelope
    assert not [r for r in h.requests if r.url.path.endswith("/call-summaries")]
    assert not h.ops_state.summaries


@pytest.mark.parametrize("arguments,expected", [
    ({}, "protocol"), ({"summaryText": None}, "protocol"),
    ({"summaryText": "  \n  "}, "invalid"),
    ({"summaryText": "NAME42 9000000123 SYMPTOM42" + "x" * 473}, "saved"),
    ({"summaryText": "  Lakshmi 9000000123 — ಜ್ವರ; बुखार.\nCallback promised.  "}, "saved"),
    ({"summaryText": "NAME42 9000000123 SYMPTOM42" + "x" * 1974}, "protocol"),
], ids=["missing", "null", "blank", "500", "multilingual-exact", "2001"])
async def test_summary_http_boundaries_preserve_text_and_log_privacy(served, arguments, expected, caplog, capsys):
    base, h = served
    async with client(base, started_at="2026-10-01T09:58:00+05:30") as c:
        result = await c.call_tool("record_call_summary", {
            "intent": "GENERAL_INFO", "outcome": "RESOLVED_BY_AGENT", **arguments}, raise_on_error=False)
    captured = capsys.readouterr()
    logs = caplog.text + captured.out + captured.err
    assert all(marker not in logs for marker in ("NAME42", "9000000123", "SYMPTOM42", "Lakshmi", "ಜ್ವರ", "बुखार"))
    writes = [r for r in h.requests if r.url.path.endswith("/call-summaries")]
    if expected == "protocol":
        assert result.is_error and writes == []
    elif expected == "invalid":
        assert result.structured_content == {"outcome": "INVALID_REQUEST", "fields": ["summaryText"]}
        assert writes == []
    else:
        assert result.structured_content == {"outcome": "SAVED"}
        assert len(writes) == 1 and json.loads(writes[0].content)["summaryText"] == arguments["summaryText"]


@pytest.mark.parametrize("day", ["today", "2026-10-05"])
@pytest.mark.parametrize("session", ["   ", " " * 40])
async def test_mcp_blank_sessions_are_unselected_for_both_tools(served, day, session):
    from .test_booking import CREATE

    base, h = served
    async with client(base, operation_id="blank") as c:
        normal = (await c.call_tool("get_doctor_availability", {
            "doctorId": "doc_garima", "date": day})).structured_content
        blank = (await c.call_tool("get_doctor_availability", {
            "doctorId": "doc_garima", "date": day, "session": session})).structured_content
        assert blank == normal
        booking = (await c.call_tool("manage_booking", {
            **CREATE, "visitDate": day, "session": session})).structured_content
    assert booking["outcome"] == "NOTED"
    assert len([r for r in h.requests if r.method == "POST" and r.url.path.endswith("/appointments")]) == 1


@pytest.mark.parametrize("session", [" " * 41, "x" * 41, 12])
async def test_mcp_session_invalid_values_never_reach_owner_reads(served, session):
    from .test_booking import CREATE

    base, h = served
    async with client(base, operation_id="invalid") as c:
        for tool, args in [("get_doctor_availability", {"doctorId": "doc_garima", "date": "today"}),
                           ("manage_booking", CREATE)]:
            result = await c.call_tool(tool, {**args, "session": session}, raise_on_error=False)
            assert result.is_error
    assert h.ops_paths() == []


async def test_mcp_slots_require_time_then_publish_owner_block(served):
    from .test_booking import CREATE

    base, h = served
    h.ops_state.set_slots("doc_garima", "2026-10-01", harness.slot_plan())
    h.ops_state.write_outcomes["/appointments"] = [{"slotTime": "10:30"}]
    async with client(base, operation_id="slots") as c:
        missing = (await c.call_tool("manage_booking", {**CREATE, "preferredTime": None,
                                                       "session": "Morning"})).structured_content
        assert (missing["outcome"], missing["nextStep"], missing["fields"]) == (
            "INVALID_REQUEST", "ASK_WHICH_TIME", ["preferredTime"])
        assert missing["sessions"][0]["openSlots"][0]["start"] == "10:30"
        assert not any(r.method == "POST" and r.url.path.endswith("/appointments") for r in h.requests)
        noted = (await c.call_tool("manage_booking", {**CREATE, "session": "Morning"})).structured_content
    assert (noted["outcome"], noted["appointment"]["slotTime"], noted["appointment"]["slotMoved"]) == (
        "NOTED", "10:30", False)


# LOG-1 tests exercise formatted output, rather than the implementation's allowlist tables.
LOG1_PRIVATE = ("Zelda Fakename", "9876501234", "+919876501234", "SECRETREASONPAIN",
                "SECRETTOKENXYZ", "BearerSecretAlphaToken")


def _log1_record(name="frontdesk_mcp.tools", msg="tool_result", args=(), fields=None, exc_info=None):
    record = logging.LogRecord(name, logging.ERROR if exc_info else logging.INFO, __file__, 1, msg, args, exc_info)
    if fields is not None:
        record.fields = fields
    return record


@pytest.mark.parametrize("name,msg,args,want", [
    ("some.library", "Zelda Fakename 9876501234 SECRETTOKENXYZ", (), "library_message_omitted"),
    ("mcp.shared.session", "Invalid request %s", ({"secret": "SECRETTOKENXYZ"},), "library_message_omitted"),
    ("root", "SECRETREASONPAIN", (), "library_message_omitted"),
    ("fastmcp.tools.tool_manager", "Error calling tool 'record_call_summary'", (), "library_message_omitted"),
    ("uvicorn.error", "Started server process [%d]", (9876501234,), "Started server process [%d]"),
    ("uvicorn.error", "Uvicorn running on %s://%s:%d (Press CTRL+C to quit)",
     ("https", "SECRETTOKENXYZ", 9876501234), "Uvicorn running on %s://%s:%d (Press CTRL+C to quit)"),
    ("some.library", {"secret": "SECRETTOKENXYZ"}, (), "library_message_omitted"),
    ("frontdesk_mcp.tools", "tool_result", ("SECRETTOKENXYZ",), "tool_result"),
])
def test_log1_never_interpolates_values(name, msg, args, want):
    line = JsonFormatter().format(_log1_record(name, msg, args))
    assert json.loads(line)["msg"] == want
    assert all(value not in line for value in LOG1_PRIVATE)


def test_log1_libraries_cannot_inject_adapter_fields():
    line = JsonFormatter().format(_log1_record("root", "Shutting down", fields={
        "tool": "manage_booking", "token": "SECRETTOKENXYZ"}))
    assert "tool" not in json.loads(line) and "token" not in json.loads(line)
    assert "SECRETTOKENXYZ" not in line


def test_log1_only_bounded_error_frames_are_kept():
    import sys

    def nested(depth):
        if depth:
            return nested(depth - 1)
        raise RuntimeError(" ".join(LOG1_PRIVATE))

    try:
        nested(14)
    except RuntimeError:
        record = _log1_record("fastmcp.tools.tool_manager", "failure", exc_info=sys.exc_info())
    line = JsonFormatter().format(record)
    body = json.loads(line)
    assert body["exception"] == "RuntimeError"
    assert len(body["frames"]) == 10
    assert all(re.fullmatch(r"services/mcp/tests/test_server.py:\d+ in nested", f) for f in body["frames"])
    assert all(value not in line for value in LOG1_PRIVATE)
    assert "frames" not in json.loads(JsonFormatter().format(_log1_record()))


def test_log1_adapter_fields_keep_safe_facts_and_drop_unknown_values():
    fields = {"tool": "manage_booking", "outcome": "NOTED", "nextStep": "SAY_REQUEST_NOTED"}
    before = json.loads(JsonFormatter().format(_log1_record(fields=fields)))
    assert all(before[k] == v for k, v in fields.items())
    assert "omittedFields" not in before
    private = {"patientName": LOG1_PRIVATE[0], "callerNumber": LOG1_PRIVATE[1],
               "arguments": {"summaryText": LOG1_PRIVATE[3]}, "token": LOG1_PRIVATE[4]}
    line = JsonFormatter().format(_log1_record(fields={**fields, **private}))
    body = json.loads(line)
    assert all(body[k] == v for k, v in fields.items())
    assert set(body["omittedFields"]) == set(private)
    assert not set(private) & body.keys()
    assert all(value not in line for value in LOG1_PRIVATE)


@pytest.mark.parametrize("field,value", [
    ("reason", "SECRETTOKENXYZ"), ("detail", "JOHN_SMITH"), ("outcome", "ZELDA_FAKENAME"),
    ("nextStep", "CALL_9876501234"), ("error", "BearerSecretAlphaToken"), ("model", "ZeldaFakename"),
    ("field", "zelda_fakename"), ("pack", "zelda-fakename"), ("header", "x-zelda-fakename"),
    ("tool", "lookup_patient"), ("env", "zelda"), ("schemaVersion", "2026-10-10.9"),
])
def test_log1_secret_shaped_values_are_not_safe_codes(field, value):
    line = JsonFormatter().format(_log1_record(fields={field: value}))
    body = json.loads(line)
    assert field not in body and body["omittedFields"] == [field]
    assert value not in line


@pytest.mark.parametrize("path,want", [
    ("/doctors/doc_zelda_9876501234", "/doctors/{id}"),
    ("/appointments/SECRETTOKENXYZ/cancel", "/appointments/{id}/cancel"),
    ("/availability/SECRETTOKENXYZ/slots", "/availability/{id}/slots"),
    ("/appointments/SECRETTOKENXYZ/reschedule", "/appointments/{id}/reschedule"),
    ("/zelda/fakename", None), ("/appointments?mobile=9876501234", None),
])
def test_log1_owner_paths_discard_ids_and_refuse_unknown_routes(path, want):
    line = JsonFormatter().format(_log1_record(fields={"path": path}))
    body = json.loads(line)
    if want:
        assert body["path"] == want and "omittedFields" not in body
    else:
        assert "path" not in body and body["omittedFields"] == ["path"]
    assert path not in line
    assert all(value not in line for value in LOG1_PRIVATE)


@pytest.mark.parametrize("field", ["attempt", "callId", "detail", "env", "error", "field", "header",
    "httpStatus", "model", "nextStep", "outcome", "pack", "path", "reason", "retryAfterSeconds",
    "schemaVersion", "status", "summaryId", "tool"])
@pytest.mark.parametrize("value", [{"token": "SECRETTOKENXYZ"}, ["Zelda Fakename"]])
def test_log1_fields_reject_containers_and_allow_none(field, value):
    line = JsonFormatter().format(_log1_record(fields={field: value}))
    assert json.loads(line)["omittedFields"] == [field]
    assert field not in json.loads(line)
    assert all(v not in line for v in LOG1_PRIVATE)
    body = json.loads(JsonFormatter().format(_log1_record(fields={field: None})))
    assert body[field] is None and "omittedFields" not in body


@pytest.mark.parametrize("field,value", [
    ("status", True), ("status", "404"), ("status", 99), ("httpStatus", 600),
    ("attempt", True), ("attempt", 0), ("attempt", 11),
    ("retryAfterSeconds", -1), ("retryAfterSeconds", 86401),
    ("callId", "Zelda Fakename"), ("summaryId", "SECRETTOKENXYZ"),
])
def test_log1_invalid_primitives_are_omitted(field, value):
    body = json.loads(JsonFormatter().format(_log1_record(fields={field: value})))
    assert field not in body and body["omittedFields"] == [field]


def test_log1_context_call_id_uses_the_existing_syntax_check():
    from frontdesk_mcp.context import call_id_var

    for value, want in [("safe-call-1", "safe-call-1"), ("Zelda Fakename", None)]:
        token = call_id_var.set(value)
        try:
            line = JsonFormatter().format(_log1_record())
            assert json.loads(line).get("callId") == want
            assert "Zelda Fakename" not in line
        finally:
            call_id_var.reset(token)


def _log1_subprocess(tmp_path, source):
    import subprocess
    import sys

    child = tmp_path / "log1_child.py"
    child.write_text("import sys\nsys.path[:0] = ['.', 'dev']\n" + source)
    return subprocess.run([sys.executable, str(child)], cwd=Path(__file__).resolve().parents[1],
                          capture_output=True, text=True, timeout=30)


def _log1_import_warnings_only(stderr):
    allowed = ("It will be compatible before version 2.0.0.",
               "from authlib.jose import JsonWebKey, JsonWebToken", "from ._compat import httpx2")
    for line in stderr.splitlines():
        assert line.strip() in allowed or (
            "AuthlibDeprecationWarning:" in line and
            ("authlib.jose module is deprecated" in line or "httpx module is deprecated" in line)), line


def test_log1_all_six_logging_sources_have_one_json_owner(tmp_path):
    result = _log1_subprocess(tmp_path, '''
import asyncio, logging
from frontdesk_mcp.config import Settings
from frontdesk_mcp.server import create_app
from tests import conftest, harness
h = harness.build(Settings(**conftest.ROLLOUT, **conftest.ENDPOINTS, env="test", log_level="INFO"))
app = create_app(h.settings, ops_transport=h.ops.http._transport,
                 knowledge_transport=h.knowledge.http._transport, clock=h.clock)
private = 'Zelda Fakename 9876501234 +919876501234 SECRETREASONPAIN SECRETTOKENXYZ BearerSecretAlphaToken'
logging.warning(private)
try:
    raise RuntimeError(private)
except RuntimeError:
    logging.getLogger('fastmcp.tools.tool_manager').exception(private)
for name, level in [('mcp.shared.session', logging.WARNING), ('uvicorn.error', logging.ERROR),
                    ('docket.worker', logging.WARNING), ('some.thirdparty.module', logging.WARNING)]:
    logging.getLogger(name).log(level, private)
assert not logging.getLogger('fastmcp').handlers
assert logging.getLogger('fastmcp').propagate
assert logging.getLogger('fastmcp').level == logging.NOTSET
asyncio.run(app.state.services.aclose())
asyncio.run(h.aclose())
''')
    assert result.returncode == 0, result.stdout + result.stderr
    assert all(v not in result.stdout + result.stderr for v in LOG1_PRIVATE)
    _log1_import_warnings_only(result.stderr)
    records = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(records) == 6
    assert {r["logger"] for r in records} == {"root", "fastmcp.tools.tool_manager", "mcp.shared.session",
                                             "uvicorn.error", "docket.worker", "some.thirdparty.module"}
    assert all(r["msg"] == "library_message_omitted" for r in records)
    error = next(r for r in records if r["logger"] == "fastmcp.tools.tool_manager")
    assert error["exception"] == "RuntimeError" and 1 <= len(error["frames"]) <= 10


def test_log1_exc_info_without_an_active_exception_keeps_logs_private(tmp_path):
    result = _log1_subprocess(tmp_path, '''
import logging
from frontdesk_mcp.server import configure_logging
configure_logging("INFO")
private = 'Zelda Fakename 9876501234 +919876501234 SECRETREASONPAIN SECRETTOKENXYZ BearerSecretAlphaToken'
logging.getLogger('some.library').error('lookup failed for %s', private, exc_info=True)
logging.getLogger('frontdesk_mcp.tools').exception('tool_result')
''')
    assert result.returncode == 0, result.stdout + result.stderr
    assert all(v not in result.stdout + result.stderr for v in LOG1_PRIVATE), result.stdout + result.stderr
    _log1_import_warnings_only(result.stderr)
    records = [json.loads(line) for line in result.stdout.splitlines()]
    assert [(r["logger"], r["level"], r["msg"]) for r in records] == [
        ("some.library", "ERROR", "library_message_omitted"),
        ("frontdesk_mcp.tools", "ERROR", "tool_result"),
    ]
    assert all("exception" not in r and "frames" not in r for r in records)


def test_log1_private_data_stays_out_of_real_http_logs_and_unexpected_errors(tmp_path):
    result = _log1_subprocess(tmp_path, '''
import asyncio, json
import httpx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from frontdesk_mcp.config import Settings
from frontdesk_mcp.server import create_app
from tests import conftest, harness
private = ('Zelda Fakename', '9876501234', '+919876501234', 'SECRETREASONPAIN',
           'SECRETTOKENXYZ', 'BearerSecretAlphaToken')
async def main():
    h = harness.build(Settings(**conftest.ROLLOUT, **conftest.ENDPOINTS, env="test", log_level="INFO"))
    app = create_app(h.settings, ops_transport=h.ops.http._transport,
                     knowledge_transport=h.knowledge.http._transport, clock=h.clock)
    headers = {'Authorization': 'Bearer mcp-token', **harness.headers(
        call_id='log1-private', caller=private[2], operation_id='log1-create',
        started_at='2026-10-01T09:58:00+05:30')}
    async with conftest.serving(app) as base:
        async with asyncio.timeout(10):
            async with Client(StreamableHttpTransport(base+'/mcp/', headers=headers)) as c:
                created = await c.call_tool('manage_booking', {'action': 'CREATE', 'patientName': private[0],
                    'patientMobile': private[1], 'doctorId': 'doc_garima', 'visitDate': '2099-01-05',
                    'preferredTime': '09:30', 'reasonVerbatim': private[3], 'callerConfirmed': True})
                assert created.structured_content['outcome'] == 'NOTED'
                listed = await c.call_tool('manage_booking', {'action': 'LIST'})
                assert listed.structured_content['outcome'] == 'FOUND'
                saved = await c.call_tool('record_call_summary', {'intent': 'BOOKING',
                    'outcome': 'APPOINTMENT_NOTED', 'summaryText': ' '.join(private)})
                assert saved.structured_content['outcome'] == 'SAVED'
                invalid = await c.call_tool('record_call_summary', {'intent': 'BOOKING',
                    'outcome': 'APPOINTMENT_NOTED', 'summaryText': {'secret': private[4]}}, raise_on_error=False)
                assert invalid.is_error
                assert invalid.content[0].text == (
                    'Invalid call summary arguments. Check required fields, types and limits.')
                async def broken(ctx, request):
                    raise RuntimeError(' '.join(private))
                app.state.services.summary.record = broken
                failed = await c.call_tool('record_call_summary', {'intent': 'BOOKING',
                    'outcome': 'APPOINTMENT_NOTED', 'summaryText': ' '.join(private)}, raise_on_error=False)
                assert failed.is_error
                assert failed.content[0].text == "Error calling tool 'record_call_summary'"
                assert all(v not in json.dumps([b.model_dump() for b in failed.content]) for v in private)
            async with httpx.AsyncClient() as http:
                raw = {'jsonrpc': '2.0', 'id': 7, 'method': 'tools/call',
                       'params': {'name': 123, 'arguments': {'patientName': private[0], 'token': private[4]}}}
                await http.post(base+'/mcp/', json=raw,
                                headers={**headers, 'Accept': 'application/json, text/event-stream'})
    assert 'callerMobile' not in h.ops_state.summaries['log1-private']
    await h.aclose()
asyncio.run(main())
''')
    assert result.returncode == 0, result.stdout + result.stderr
    assert all(v not in result.stdout + result.stderr for v in LOG1_PRIVATE)
    _log1_import_warnings_only(result.stderr)
    records = [json.loads(line) for line in result.stdout.splitlines()]
    assert any(r["logger"] == "root" and r["msg"] == "library_message_omitted" for r in records)
    failure = next(r for r in records if r.get("exception") == "RuntimeError")
    assert failure["logger"] == "fastmcp.tools.tool_manager" and failure["frames"]
    assert failure["msg"] == "library_message_omitted"
    messages = {r["msg"] for r in records}
    assert {"Started server process [%d]", "Finished server process [%d]", "Application startup complete.",
            "Application shutdown complete.", "tool_result", "summary_saved"} <= messages


async def test_log1_all_observed_owner_routes_are_templated(served):
    base, h = served
    async with client(base, operation_id="log1-create", caller="+919876501234",
                      started_at="2026-10-01T09:58:00+05:30") as c:
        for arguments in ({"departmentName": "General Medicine", "date": "today"},
                          {"doctorName": "garima", "date": "2099-01-05"}):
            result = await c.call_tool("get_doctor_availability", arguments)
            assert result.structured_content["outcome"] == "AVAILABILITY"
        result = await c.call_tool("manage_booking", {"action": "CREATE", "patientName": "Zelda Fakename",
            "patientMobile": "9876501234", "doctorId": "doc_garima", "visitDate": "2099-01-05",
            "preferredTime": "09:30", "callerConfirmed": True})
        assert result.structured_content["outcome"] == "NOTED"
        appointment_id = result.structured_content["appointment"]["appointmentId"]
        assert (await c.call_tool("manage_booking", {"action": "LIST"})).structured_content["outcome"] == "FOUND"
        assert (await c.call_tool("search_knowledge", {"question": "parking", "language": "en"})
                ).structured_content["outcome"] == "ANSWERED"
        assert (await c.call_tool("record_call_summary", {"intent": "BOOKING", "outcome": "APPOINTMENT_NOTED",
                     "summaryText": "Synthetic test."})).structured_content["outcome"] == "SAVED"
    for action, op, more in [("RESCHEDULE", "log1-move", {"newVisitDate": "2099-01-12"}),
                             ("CANCEL", "log1-cancel", {})]:
        async with client(base, operation_id=op, caller="+919876501234") as c:
            result = await c.call_tool("manage_booking", {"action": action, "appointmentId": appointment_id,
                                                       "callerConfirmed": True, **more})
            assert result.structured_content["outcome"] == ("NOTED" if action == "RESCHEDULE" else "CANCELLED")
    templates = set()
    for request in h.requests:
        prefix = httpx.URL(h.settings.ops_base_url).path.rstrip("/") if request.url.host == "ops-stub.test" else ""
        path = request.url.path.removeprefix(prefix)
        body = json.loads(JsonFormatter().format(_log1_record(fields={"path": path})))
        assert "omittedFields" not in body, path
        templates.add(body["path"])
    assert templates == {"/auth/token", "/departments", "/doctors", "/doctors/{id}", "/availability",
                         "/availability/{id}/slots", "/capabilities", "/appointments",
                         "/appointments/{id}/cancel", "/appointments/{id}/reschedule", "/call-summaries", "/v1/answer"}


async def test_log1_real_adapter_events_keep_every_permitted_value(make_settings):
    from frontdesk_mcp import availability, context, contract, knowledge_contract, summary
    from frontdesk_mcp.clock import Deadline
    from frontdesk_mcp.ops_client import Malformed, Unavailable, UncertainWrite

    h = harness.build(make_settings(log_level="INFO"))
    app = create_app(h.settings, ops_transport=h.ops.http._transport,
                     knowledge_transport=h.knowledge.http._transport, clock=h.clock)
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    package = logging.getLogger("frontdesk_mcp")
    capture = Capture()
    package.addHandler(capture)
    try:
        async with serving(app):
            ops = app.state.services.ops
            ctx = h.ctx(started_at="2026-10-01T09:58:00+05:30")
            request = summary.SummaryRequest(intent="GENERAL_INFO", outcome="RESOLVED_BY_AGENT",
                                              summaryText="Synthetic test.")
            assert (await app.state.services.summary.record(ctx, request)).outcome == "SAVED"
            assert (await app.state.services.summary.record(context.CallContext(), request)).outcome == "NOT_SAVED"
            context.from_headers({"X-Call-Id": "Zelda Fakename"}, h.settings)
            knowledge_contract.AnswerResponse.model_validate({"outcome": "DESK_TRANSFER", "sourceId": {}})
            with pytest.raises(Malformed):
                ops._parse(contract.DepartmentList, {}, "/departments")
            h.ops_state.fail_next.append(("/departments", 500, {}))
            result = await app.state.services.availability.get(ctx,
                availability.AvailabilityRequest(departmentName="General Medicine", date="today"))
            assert result.outcome == "COULD_NOT_CHECK"
            h.ops_state.fail_next.append(("/appointments", 500, {}))
            with pytest.raises(UncertainWrite):
                await ops.create_appointment({}, "log1-test", Deadline(1))
            original = ops.http._transport

            async def unavailable(request):
                raise httpx.ConnectError("SECRETTOKENXYZ", request=request)

            ops.http._transport = httpx.MockTransport(unavailable)
            try:
                with pytest.raises(Unavailable):
                    await ops.list_departments(Deadline(1))
            finally:
                ops.http._transport = original
    finally:
        package.removeHandler(capture)
        await h.aclose()
    expected = {"ops_write_server_error", "ops_unreachable", "summary_write_unverified", "summary_saved",
                "trusted_header_malformed", "availability_could_not_check", "ops_malformed_success",
                "knowledge_optional_field_dropped", "service_started"}
    found = {record.msg for record in records}
    assert expected <= found
    for record in records:
        body = json.loads(JsonFormatter().format(record))
        assert "omittedFields" not in body, (record.msg, getattr(record, "fields", None))
        for key, value in getattr(record, "fields", {}).items():
            assert body[key] == value  # these nine events use static paths
