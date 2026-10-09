from __future__ import annotations

import asyncio
import contextlib
import contextvars
import functools
import inspect
import json
import logging
import os
import re
import socket
import sys
import sysconfig
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import uvicorn

from frontdesk_mcp.config import Settings

SERVER_SHUTDOWN_LIMIT = 10
HTTP_TEST_BODY_LIMIT = 20


@dataclass
class _HTTPTestBody:
    task: asyncio.Task | None = None
    failure: str | None = None
    recorders: list = field(default_factory=list)


_HTTP_TEST_BODY = contextvars.ContextVar("http_test_body", default=None)


@pytest.fixture(autouse=True)
def http_test_body(request):
    """Fixture setup and test calls use different tasks in pytest-asyncio."""
    original = request.node.obj
    if not inspect.iscoroutinefunction(original):
        yield
        return
    state = _HTTPTestBody()
    token = _HTTP_TEST_BODY.set(state)

    @functools.wraps(original)
    async def tracked(*args, **kwargs):
        state.task = asyncio.current_task()
        with _http_failure_boundary(state.recorders, lambda: state.failure):
            return await original(*args, **kwargs)

    request.node.obj = tracked
    try:
        yield
    finally:
        request.node.obj = original
        _HTTP_TEST_BODY.reset(token)


def _pending_incident_failure(recorders):
    reports = [report for recorder in recorders if (report := recorder.failure()) is not None]
    return "\n".join(reports) or None


@contextlib.contextmanager
def _http_failure_boundary(recorders, watchdog_failure):
    """Only our watchdog may consume cancellation; incident failures retain their cause."""
    try:
        yield
    except BaseException as exc:
        incident = _pending_incident_failure(recorders)
        watchdog = watchdog_failure()
        if isinstance(exc, asyncio.CancelledError) and watchdog is not None:
            asyncio.current_task().uncancel()
            raise AssertionError(incident or watchdog) from exc
        if incident is not None:
            if isinstance(exc, Exception):
                raise AssertionError(incident) from exc
            exc.add_note(incident)
        raise
    else:
        incident = _pending_incident_failure(recorders)
        watchdog = watchdog_failure()
        if watchdog is not None:
            asyncio.current_task().uncancel()
        if incident is not None or watchdog is not None:
            raise AssertionError(incident or watchdog)


def _frame_location(frame):
    path = Path(frame.f_code.co_filename).resolve()
    if "site-packages" in path.parts:
        relative = Path(*path.parts[path.parts.index("site-packages") + 1:]).as_posix()
    else:
        roots = (Path(__file__).resolve().parents[3], Path(sysconfig.get_path("stdlib")).resolve())
        relative = next((path.relative_to(root).as_posix() for root in roots if path.is_relative_to(root)), path.name)
    primitive = relative.startswith(("asyncio/", "anyio/")) or relative == "contextlib.py"
    category = "other"
    for label, prefixes in (
        ("client", ("fastmcp/client/", "mcp/client/", "httpx/", "httpcore/")),
        ("server", ("uvicorn/", "starlette/", "mcp/server/", "fastmcp/server/", "frontdesk_mcp/",
                    "services/mcp/src/frontdesk_mcp/")),
        ("harness", ("tests/", "services/mcp/tests/", "pytest_asyncio/", "_pytest/")),
    ):
        if relative.startswith(prefixes):
            category = label
            break
    location = f"{relative[:180]}:{frame.f_lineno} in {frame.f_code.co_qualname[:120]}"
    return location, None if primitive or category == "other" else category


def _task_chain(task):
    """Metadata only: no locals, arguments, arbitrary task names or object reprs."""
    coro = task.get_coro()
    awaited = coro
    chain = []
    seen = set()
    category = "other"
    transport = False
    terminal = "unknown"
    while awaited is not None and id(awaited) not in seen and len(seen) < 96:
        seen.add(id(awaited))
        terminal = type(awaited).__name__[:80]
        frame = next((getattr(awaited, attr, None) for attr in ("cr_frame", "gi_frame", "ag_frame")
                      if getattr(awaited, attr, None) is not None), None)
        if frame is not None:
            location, frame_category = _frame_location(frame)
            chain.append(location)
            if frame_category is not None:
                category = frame_category
                transport |= frame_category in ("server", "client")
        awaited = next((getattr(awaited, attr, None) for attr in ("cr_await", "gi_yieldfrom", "ag_await")
                        if getattr(awaited, attr, None) is not None), None)
    if awaited is not None:
        chain.append("[await chain truncated]")
    return chain, category, terminal, transport


def _task_evidence(task, limit, chain_info):
    chain, category, terminal, _ = chain_info
    coro = task.get_coro()
    name = task.get_name()
    if not re.fullmatch(r"Task-[0-9]+", name):
        name = "<custom>"
    qualname = getattr(coro, "__qualname__", type(coro).__name__)[:64]
    header = f"task name={name[:24]} coro={qualname} class={category} awaited={terminal[:32]}\n  "
    evidence = "\n  -> ".join(chain)
    remaining = limit - len(header)
    if len(evidence) > remaining:
        marker = "\n  ... [truncated] ...\n"
        head = (remaining - len(marker)) // 2
        evidence = evidence[:head] + marker + evidence[-(remaining - len(marker) - head):]
    return header + evidence


def _pending_task_dump(body):
    chains = {task: _task_chain(task) for task in asyncio.all_tasks()}
    pending = sorted(chains, key=lambda task: (task is not body, not chains[task][3], id(task)))
    selected = pending[:40]
    header = f"pending={len(pending)} captured={len(selected)} (body first; cap 40)\n"
    # Reserve extra room for the body; preserve both ends of oversized chains.
    body_limit = 3000
    other_limit = (11800 - len(header) - body_limit) // max(1, len(selected) - 1) - 1
    return header + "\n".join(_task_evidence(task, body_limit if task is body else other_limit, chains[task])
                              for task in selected)

_HTTP_RECORDER = contextvars.ContextVar("http_recorder", default=None)
_INCOMPLETE_RESPONSE = "ASGI callable returned without completing response."
_SAFE_LIBRARY_MESSAGES = frozenset({"No response message received before stream closed"})


class _HTTPRecorder(logging.Handler):
    """Test-only metadata recorder. Never formats log arguments or captures payloads."""

    def __init__(self, app, body):
        super().__init__(logging.WARNING)
        self.app = app
        self.body = body
        self.started = asyncio.get_running_loop().time()
        self.requests = []
        self.incidents = []
        self._reported = 0
        self.confirmations = []
        self.warnings = []
        self._request = contextvars.ContextVar("recorded_request", default=None)

    def elapsed(self):
        return round(asyncio.get_running_loop().time() - self.started, 6)

    @staticmethod
    def content_type(headers):
        for name, value in headers:
            if name.lower() == b"content-type":
                media = value.split(b";", 1)[0].strip().lower()
                if media in (b"application/json", b"text/event-stream", b"text/plain"):
                    return media.decode("ascii")
                return "<other>"
        return None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        names = {name.lower() for name, _ in scope.get("headers", [])}
        path = scope.get("path", "").split("?", 1)[0]
        method = scope.get("method", "")
        record = {"sequence": len(self.requests) + 1, "start": self.elapsed(),
                  "method": method if method in ("GET", "POST", "DELETE", "PUT", "PATCH", "HEAD", "OPTIONS")
                  else "<other>",
                  "path": path if path in ("/", "/mcp", "/mcp/", "/health", "/ready", "/dependencies")
                  else "<other-path>",
                  "session_id": b"mcp-session-id" in names, "authorization": b"authorization" in names,
                  "request_content_type": self.content_type(scope.get("headers", [])),
                  "status": None, "response_content_type": None, "started": False, "complete": False,
                  "returned": False, "raised": None, "duration": None, "disconnected": False}
        self.requests.append(record)
        # Deliberately retained for uvicorn's subsequent log in this same request task.
        self._request.set(record["sequence"])

        async def recorded_receive():
            message = await receive()
            if message["type"] == "http.disconnect":
                record["disconnected"] = True
            return message

        async def recorded_send(message):
            await send(message)
            if message["type"] == "http.response.start":
                record["started"] = True
                record["status"] = message["status"]
                record["response_content_type"] = self.content_type(message.get("headers", []))
            elif message["type"] == "http.response.body" and not message.get("more_body", False):
                record["complete"] = True

        try:
            await self.app(scope, recorded_receive, recorded_send)
        except BaseException as exc:
            record["raised"] = type(exc).__name__[:80]
            raise
        else:
            record["returned"] = True
        finally:
            record["duration"] = round(self.elapsed() - record["start"], 6)
            if record["returned"] and record["started"] and not record["complete"] and not record["disconnected"]:
                self.capture(record)

    def capture(self, request):
        module = sys.modules.get("sse_starlette.sse")
        flag = getattr(getattr(module, "AppStatus", None), "should_exit", None)
        metadata = {"confirmed": False, "flags_disagree": False, "sse_should_exit": flag}
        try:
            self.incidents.append({**metadata, "time": self.elapsed(), "request": dict(request) if request else None,
                                   "candidates": [dict(r) for r in self.requests
                                                  if not r["complete"]]
                                   if request is None else [],
                                   "requests": [dict(r) for r in self.requests[-20:]],
                                   "tasks": _pending_task_dump(self.body())})
        except Exception as exc:  # noqa: BLE001 — recorder must not alter ASGI semantics
            # Diagnostics must not change the ASGI return/raise semantics.
            self.incidents.append({**metadata, "request": dict(request) if request else None,
                                   "capture_error": type(exc).__name__[:80]})

    def emit(self, record):
        if _HTTP_RECORDER.get() is not self:
            return
        try:
            if record.name == "uvicorn.error":
                if record.msg != _INCOMPLETE_RESPONSE:
                    return
                sequence = self._request.get()
                match = next((i for i in self.incidents if i["request"] and
                              i["request"]["sequence"] == sequence), None)
                if match is None:
                    request = next((r for r in self.requests if r["sequence"] == sequence), None)
                    self.capture(request)
                    match = self.incidents[-1]
                    match["flags_disagree"] = request is not None
                match["confirmed"] = True
                self.confirmations.append({"time": self.elapsed(), "incident": sequence})
            else:
                # Fixed messages only. Arbitrary record.msg may already contain private values.
                root = record.name.split(".", 1)[0]
                name = record.name if record.name in {
                    "mcp", "fastmcp", "starlette", "docket", "mcp.server.streamable_http",
                    "mcp.server.streamable_http_manager", "fastmcp.server.http",
                } else root[:40] + ".<other>"
                self.warnings.append({"logger": name, "level": record.levelname[:16],
                                      "exception": record.exc_info[0].__name__[:80] if record.exc_info else None,
                                      "message": record.msg if isinstance(record.msg, str)
                                      and record.msg in _SAFE_LIBRARY_MESSAGES
                                      else "<message omitted>"})
        except Exception:  # noqa: BLE001 — a logging observer must never raise
            # Logging must never raise into the server or inspect arbitrary values to diagnose itself.
            return

    def report(self, incidents=None):
        return json.dumps({"incidents": self.incidents if incidents is None else incidents,
                           "confirmations": self.confirmations,
                           "warnings": self.warnings, "last_requests": self.requests[-20:]}, indent=2)

    def failure(self):
        incidents = self.incidents[self._reported:]
        if not incidents:
            return None
        labels = []
        for incident in incidents:
            request = incident["request"]
            label = (f"{request['method']} {request['path']} #{request['sequence']}" if request
                     else "exact request not established (see candidates)")
            labels.append(f"{label} confirmed={str(incident['confirmed']).lower()}")
        report = "Incomplete HTTP response: " + ", ".join(labels) + "\n" + self.report(incidents)
        self._reported = len(self.incidents)
        return report


for _field in Settings.model_fields:
    os.environ.pop(_field.upper(), None)

# The demo hospital rollout's values the adapter reads (rollouts/demo-hospital/rollout.env).
ROLLOUT = {
    "provider_id": "demo-hospital", "domain_pack": "healthcare", "tenant_supported_languages": "en,kn,hi",
    "tenant_timezone": "Asia/Kolkata", "tenant_country_calling_code": "91",
}
# Dev/test endpoints: the in-process stubs (tests) or the compose stub services.
ENDPOINTS = {
    "ops_base_url": "http://ops-stub.test/api/v1", "ops_client_id": "mcp-test", "ops_client_secret": "ops-secret",
    "knowledge_base_url": "http://knowledge-stub.test", "knowledge_bearer_token": "knowledge-secret",
    "mcp_bearer_token": "mcp-token",
}


@pytest.fixture
def make_settings():
    def factory(**overrides) -> Settings:
        return Settings(**{**ROLLOUT, **ENDPOINTS, "env": "test", **overrides})

    return factory


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextlib.asynccontextmanager
async def serving(app, *, shutdown_limit=SERVER_SHUTDOWN_LIMIT, watchdog_limit=HTTP_TEST_BODY_LIMIT):
    """Run an ASGI app on a real local port for the duration of the block."""
    # sse-starlette keeps one process-wide drain flag; a previous test server's shutdown can
    # leave it set and cut off later event streams (T-4). Production has one server per process,
    # so each test server starts with that same fresh-process flag state.
    module = sys.modules.get("sse_starlette.sse")
    if module is not None:
        module.AppStatus.should_exit = False
    owner = asyncio.current_task()
    test_body = _HTTP_TEST_BODY.get()

    def body_task():
        return owner if not owner.done() else test_body.task if test_body else None

    recorder = _HTTPRecorder(app, body_task)
    token = _HTTP_RECORDER.set(recorder)
    if test_body:
        test_body.recorders.append(recorder)
    loggers = [logging.getLogger(name) for name in ("uvicorn.error", "mcp", "fastmcp", "starlette", "docket")]
    for logger in loggers:
        logger.addHandler(recorder)
    port = free_port()
    config = uvicorn.Config(recorder, host="127.0.0.1", port=port, log_config=None, lifespan="on",
                            timeout_graceful_shutdown=2)
    server = uvicorn.Server(config)
    try:
        task = asyncio.create_task(server.serve())
        async with asyncio.timeout(10):
            while not server.started:
                await asyncio.sleep(0.02)
        failure = None

        async def watch_body():
            nonlocal failure
            await asyncio.sleep(watchdog_limit)
            body = body_task()
            if body is None or body.done():
                return
            failure = f"HTTP test body exceeded {watchdog_limit:g}s\n" + _pending_task_dump(body)
            if recorder.requests or recorder.incidents or recorder.warnings:
                failure += "\n" + recorder.report()
            print(failure, flush=True)
            if body is not owner:
                test_body.failure = failure
            body.cancel()

        watchdog = asyncio.create_task(watch_body())
        try:
            with _http_failure_boundary([recorder], lambda: failure if owner is asyncio.current_task() else None):
                yield f"http://127.0.0.1:{port}"
        finally:
            watchdog.cancel()
            try:
                with contextlib.suppress(asyncio.CancelledError):
                    await watchdog
            finally:
                server.should_exit = True
                done, _ = await asyncio.wait({task}, timeout=shutdown_limit)
                if done:
                    await task  # Preserve ordinary server exceptions.
                else:
                    task.cancel()
                    stopped, _ = await asyncio.wait({task}, timeout=0.5)
                    if stopped and not task.cancelled():
                        task.exception()  # Retrieve a cleanup exception; the timeout still fails the test.
                    raise AssertionError(
                        f"test server shutdown exceeded {shutdown_limit:g}s; "
                        f"stopped after cancellation={bool(stopped)}")
    finally:
        try:
            incident = _pending_incident_failure([recorder])
            if incident is not None:
                if (exc := sys.exception()) is not None:
                    exc.add_note(incident)
                else:
                    raise AssertionError(incident)
        finally:
            for logger in loggers:
                logger.removeHandler(recorder)
            recorder.close()
            if test_body:
                test_body.recorders.remove(recorder)
            _HTTP_RECORDER.reset(token)
