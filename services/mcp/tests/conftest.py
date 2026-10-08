from __future__ import annotations

import asyncio
import contextlib
import os
import re
import socket

import pytest
import uvicorn

from frontdesk_mcp.config import Settings

SERVER_SHUTDOWN_LIMIT = 10

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
async def serving(app, *, shutdown_limit=SERVER_SHUTDOWN_LIMIT):
    """Run an ASGI app on a real local port for the duration of the block."""
    port = free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, lifespan="on",
                            timeout_graceful_shutdown=2)
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    async with asyncio.timeout(10):
        while not server.started:
            await asyncio.sleep(0.02)
    # Uvicorn 0.53 creates this separately from serve(), without retaining its handle.
    # Identify only this server's lifespan task, never unrelated tasks on the loop.
    lifespan_tasks = {
        candidate for candidate in asyncio.all_tasks()
        if (frame := getattr(candidate.get_coro(), "cr_frame", None)) is not None
        and frame.f_code.co_name == "main" and frame.f_locals.get("self") is server.lifespan
    }
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        done, _ = await asyncio.wait({task}, timeout=shutdown_limit)
        if done:
            await task  # Preserve ordinary server exceptions.
        else:
            owned = {task, *lifespan_tasks, *server.server_state.tasks}
            # Inspect before force/cancel destroys the evidence. Never dump locals,
            # coroutine arguments or arbitrary task names (which can contain caller data).
            shutdown_started = False
            awaited = task.get_coro()
            while awaited is not None:
                frame = getattr(awaited, "cr_frame", None)
                if frame is not None and frame.f_code.co_name == "shutdown":
                    shutdown_started |= frame.f_locals.get("self") is server.lifespan
                awaited = getattr(awaited, "cr_await", None)
            finished = server.lifespan.shutdown_event.is_set()
            diagnostic = [
                f"connections={len(server.server_state.connections)} "
                f"server_tasks={sum(not t.done() for t in server.server_state.tasks)} "
                f"lifespan_shutdown_started={shutdown_started or finished} "
                f"lifespan_shutdown_finished={finished}",
            ]
            pending = sorted(asyncio.all_tasks() - {asyncio.current_task()},
                             key=lambda candidate: (candidate not in owned, id(candidate)))
            diagnostic.append(f"pending_tasks={len(pending)} (showing at most 8)")
            for candidate in pending[:8]:
                name = candidate.get_name()
                if not re.fullmatch(r"Task-[0-9]+", name):
                    name = "<custom>"
                coro = candidate.get_coro()
                stack = candidate.get_stack(limit=1)
                location = "unknown"
                if stack:
                    frame = stack[0]
                    location = f"{os.path.basename(frame.f_code.co_filename)[:120]}:{frame.f_lineno}"
                diagnostic.append(f"name={name[:80]} coro={coro.__qualname__[:120]} frame={location}")
            message = f"test server shutdown exceeded {shutdown_limit:g}s\n" + "\n".join(diagnostic)
            server.force_exit = True
            await asyncio.wait({task}, timeout=0.5)
            owned.update(server.server_state.tasks)
            for candidate in owned:
                if not candidate.done():
                    candidate.cancel()
            await asyncio.gather(*owned, return_exceptions=True)
            for listener in server.servers:
                listener.close()
                await listener.wait_closed()
            raise AssertionError(message)
