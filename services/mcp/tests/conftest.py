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
