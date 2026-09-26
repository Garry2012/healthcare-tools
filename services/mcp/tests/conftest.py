from __future__ import annotations

import asyncio
import contextlib
import os
import socket

import pytest
import uvicorn

from frontdesk_mcp.config import Settings

for _field in Settings.model_fields:
    os.environ.pop(_field.upper(), None)


@pytest.fixture
def make_settings():
    def factory(**overrides) -> Settings:
        return Settings(**{"env": "test", "api_bearer_token": "api-token", "mcp_bearer_token": "mcp-token",
                           **overrides})

    return factory


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextlib.asynccontextmanager
async def serving(app):
    """Run an ASGI app on a real local port for the duration of the block."""
    port = free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, lifespan="on",
                            timeout_graceful_shutdown=2)
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    async with asyncio.timeout(10):
        while not server.started:
            await asyncio.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task
