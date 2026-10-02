"""Starlette + FastMCP assembly: /mcp/ (streamable HTTP, stateless), /health, /ready, /dependencies.

Two bearers may reach /mcp/: the gateway's (conversational principal, three in-call tools) and the
call-end finalizer's (lifecycle principal, record_call_summary only). The principal is decided here,
on the server, and enforced by access.LifecycleGate; no header can claim it."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import sys
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from . import context, packs, prompt, tools
from .access import LifecycleGate
from .clock import Clock, Deadline
from .config import Settings, get_settings
from .ops_client import UpstreamError

logger = logging.getLogger(__name__)
DEPENDENCY_CHECK_SECONDS = 1.0
DEPENDENCY_CACHE_SECONDS = 15.0
DEPENDENCY_REFRESH_MIN_INTERVAL = 5.0  # ?refresh=1 is unauthenticated: never more than one upstream check per 5 s


class JsonFormatter(logging.Formatter):
    """One JSON object per line; provider and callId correlate across services. Never caller data."""

    def __init__(self, provider: str = "") -> None:
        super().__init__()
        self.provider = provider

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if self.provider:
            entry["provider"] = self.provider
        if call_id := context.call_id_var.get():
            entry["callId"] = call_id
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            entry.update(fields)
        return json.dumps(entry, default=str)


# Libraries that log request URLs (which carry ?mobile=... to the owner API) or per-request chatter.
QUIET_LOGGERS = ("httpx", "httpcore", "uvicorn.access", "mcp", "docket")


def configure_logging(level: str, provider: str = "") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(provider))
    logging.getLogger().handlers[:] = [handler]
    logging.getLogger().setLevel(level.upper())
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


class BearerAuth:
    """Decides the principal for /mcp/ from the presented bearer. /health, /ready, /dependencies stay open."""

    def __init__(self, app: ASGIApp, gateway_token: str, lifecycle_token: str, development: bool) -> None:
        self.app = app
        self.gateway = f"Bearer {gateway_token}".encode() if gateway_token else b""
        self.lifecycle = f"Bearer {lifecycle_token}".encode() if lifecycle_token else b""
        self.development = development

    def principal(self, supplied: bytes) -> context.Principal | None:
        if self.lifecycle and hmac.compare_digest(supplied, self.lifecycle):
            return "lifecycle"
        if self.gateway and hmac.compare_digest(supplied, self.gateway):
            return "conversation"
        if not self.gateway and self.development:
            return "conversation"  # development without a configured gateway token
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/mcp"):
            await self.app(scope, receive, send)
            return
        supplied = dict(scope.get("headers", [])).get(b"authorization", b"")
        principal = self.principal(supplied)
        if principal is None:
            response = JSONResponse({"error": "unauthorized"}, status_code=401,
                                    headers={"WWW-Authenticate": "Bearer"})
            await response(scope, receive, send)
            return
        token = context.principal_var.set(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            context.principal_var.reset(token)


def build_mcp(services: tools.Services) -> FastMCP:
    settings = services.settings
    pack = packs.load(settings.domain_pack)
    mcp = FastMCP(
        name=f"frontdesk-{pack.name}",
        instructions=prompt.instructions(pack, settings.languages, settings.tenant_display_name),
        version=prompt.SCHEMA_VERSION,
        middleware=[LifecycleGate()],
    )
    tools.register(mcp, services, pack)
    return mcp


class DependencyStatus:
    """Bounded, cached checks of the two owner services; distinct from local readiness."""

    def __init__(self, services: tools.Services) -> None:
        self.services = services
        self._cached: tuple[float, dict, int] | None = None
        self._lock = asyncio.Lock()  # single flight: concurrent probes share one upstream check

    async def check(self, *, refresh: bool = False) -> tuple[dict, int]:
        async with self._lock:
            now = time.monotonic()
            if self._cached:
                age = now - self._cached[0]
                if age < (DEPENDENCY_REFRESH_MIN_INTERVAL if refresh else DEPENDENCY_CACHE_SECONDS):
                    return self._cached[1], self._cached[2]
            return await self._probe(now)

    async def _probe(self, now: float) -> tuple[dict, int]:
        status = 200
        try:
            await self.services.ops.list_departments(Deadline(DEPENDENCY_CHECK_SECONDS))
            operational = {"status": "ok", "check": "listDepartments"}
        except UpstreamError as exc:
            operational = {"status": "unavailable", "reason": getattr(exc, "reason", type(exc).__name__)}
            status = 503
        knowledge = {"status": "configured" if self.services.settings.knowledge_base_url else "not_configured",
                     "check": "none agreed (contract pending)"}
        body = {"operational": operational, "knowledge": knowledge}
        self._cached = (now, body, status)
        return body, status


def create_app(settings: Settings | None = None, *, ops_transport: httpx.AsyncBaseTransport | None = None,
               knowledge_transport: httpx.AsyncBaseTransport | None = None, clock: Clock | None = None) -> Starlette:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.provider_id)
    services = tools.Services.build(settings, ops_transport=ops_transport, knowledge_transport=knowledge_transport,
                                    clock=clock)
    mcp = build_mcp(services)
    # Stateless: no per-session server state, so any replica can serve any request.
    mcp_app = mcp.http_app(path="/mcp/", transport="http", stateless_http=True)
    dependencies = DependencyStatus(services)

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    async def ready(_: Request) -> JSONResponse:
        # Local readiness: configuration validated, clients and tools built. No fresh token, no upstream probe.
        return JSONResponse({"status": "ready", "schemaVersion": prompt.SCHEMA_VERSION, "tools": len(tools.TOOL_NAMES)})

    async def dependency_status(request: Request) -> JSONResponse:
        body, status = await dependencies.check(refresh=request.query_params.get("refresh") == "1")
        return JSONResponse(body, status_code=status)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        logger.info("service_started", extra={"fields": {"env": settings.env, "pack": settings.domain_pack,
                                                         "schemaVersion": prompt.SCHEMA_VERSION}})
        await services.ops.start()  # warm machine token now, keep it warm in the background
        try:
            async with mcp_app.lifespan(app):
                yield
        finally:
            await services.aclose()

    app = Starlette(
        routes=[Route("/health", health), Route("/ready", ready), Route("/dependencies", dependency_status),
                Mount("/", app=mcp_app)],
        lifespan=lifespan,
    )
    app.add_middleware(BearerAuth, gateway_token=settings.mcp_bearer_token.get_secret_value(),
                       lifecycle_token=settings.mcp_lifecycle_bearer_token.get_secret_value(),
                       development=settings.env == "development")
    app.state.mcp = mcp
    app.state.services = services
    return app
