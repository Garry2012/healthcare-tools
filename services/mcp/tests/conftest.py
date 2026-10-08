from __future__ import annotations

import asyncio
import contextlib
import contextvars
import functools
import inspect
import os
import re
import socket
import sysconfig
from dataclasses import dataclass
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
        try:
            result = await original(*args, **kwargs)
        except asyncio.CancelledError:
            if state.failure is None:
                raise
        if state.failure is not None:
            state.task.uncancel()
            raise AssertionError(state.failure) from None
        return result

    request.node.obj = tracked
    try:
        yield
    finally:
        request.node.obj = original
        _HTTP_TEST_BODY.reset(token)


def _frame_location(frame):
    path = Path(frame.f_code.co_filename).resolve()
    if "site-packages" in path.parts:
        relative = Path(*path.parts[path.parts.index("site-packages") + 1:]).as_posix()
    else:
        roots = (Path(__file__).resolve().parents[3], Path(sysconfig.get_path("stdlib")).resolve())
        relative = next((path.relative_to(root).as_posix() for root in roots if path.is_relative_to(root)), path.name)
    primitive = relative.startswith(("asyncio/", "anyio/"))
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
    return location, None if primitive else category


def _task_evidence(task, limit):
    """Metadata only: no locals, arguments, arbitrary task names or object reprs."""
    coro = task.get_coro()
    awaited = coro
    chain = []
    seen = set()
    category = "other"
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
        awaited = next((getattr(awaited, attr, None) for attr in ("cr_await", "gi_yieldfrom", "ag_await")
                        if getattr(awaited, attr, None) is not None), None)
    if awaited is not None:
        chain.append("[await chain truncated]")
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
    pending = sorted(asyncio.all_tasks(), key=lambda task: (task is not body, id(task)))
    selected = pending[:40]
    header = f"pending={len(pending)} captured={len(selected)} (body first; cap 40)\n"
    # Reserve extra room for the body; preserve both ends of oversized chains.
    body_limit = 3000
    other_limit = (11800 - len(header) - body_limit) // max(1, len(selected) - 1) - 1
    return header + "\n".join(_task_evidence(task, body_limit if task is body else other_limit) for task in selected)

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
    port = free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, lifespan="on",
                            timeout_graceful_shutdown=2)
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    async with asyncio.timeout(10):
        while not server.started:
            await asyncio.sleep(0.02)
    owner = asyncio.current_task()
    test_body = _HTTP_TEST_BODY.get()
    failure = None

    async def watch_body():
        nonlocal failure
        await asyncio.sleep(watchdog_limit)
        body = owner if not owner.done() else test_body.task if test_body else None
        if body is None or body.done():
            return
        failure = f"HTTP test body exceeded {watchdog_limit:g}s\n" + _pending_task_dump(body)
        print(failure, flush=True)
        if body is not owner:
            test_body.failure = failure
        body.cancel()

    watchdog = asyncio.create_task(watch_body())
    try:
        try:
            yield f"http://127.0.0.1:{port}"
        except asyncio.CancelledError:
            if failure is None:
                raise
            owner.uncancel()
            raise AssertionError(failure) from None
        if failure is not None and owner is asyncio.current_task():
            owner.uncancel()
            raise AssertionError(failure)
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
                    f"test server shutdown exceeded {shutdown_limit:g}s; stopped after cancellation={bool(stopped)}")
