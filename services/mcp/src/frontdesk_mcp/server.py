"""Starlette + FastMCP assembly: /mcp/ (streamable HTTP, stateless), /health, /ready."""

from __future__ import annotations

import contextlib
import hmac
import json
import logging
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from . import tools
from .config import Settings, get_settings

logger = logging.getLogger(__name__)

INSTRUCTIONS = (
    "Front-desk tools for a hospital voice agent. Call find_availability once per caller question "
    "with the caller's own words; branch on `outcome` and `routing.action`. Book with "
    "manage_booking(action=BOOK) using a slotId from that result, one customer per call. "
    "Never invent ids, dates or prices; never say 'confirmed' unless timingCertainty is CONFIRMED."
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            entry.update(fields)
        return json.dumps(entry, default=str)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.getLogger().handlers[:] = [handler]
    logging.getLogger().setLevel(level.upper())


class BearerAuth:
    """Only the gateway may call /mcp/. /health and /ready stay open for the orchestrator."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.expected = f"Bearer {token}".encode() if token else b""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and self.expected and scope["path"].startswith("/mcp"):
            supplied = dict(scope.get("headers", [])).get(b"authorization", b"")
            if not hmac.compare_digest(supplied, self.expected):
                response = JSONResponse({"error": "unauthorized"}, status_code=401,
                                        headers={"WWW-Authenticate": "Bearer"})
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def build_mcp(client: tools.ApiClient) -> FastMCP:
    mcp = FastMCP(name="healthcare-frontdesk", instructions=INSTRUCTIONS)
    tools.register(mcp, client)
    return mcp


def create_app(settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None) -> Starlette:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    client = tools.ApiClient(settings, transport=transport)
    mcp = build_mcp(client)
    # Stateless: no per-session server state, so any replica can serve any request.
    mcp_app = mcp.http_app(path="/mcp/", transport="http", stateless_http=True)

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    async def ready(_: Request) -> JSONResponse:
        try:
            async with httpx.AsyncClient(timeout=settings.read_timeout_seconds) as http:
                upstream = await http.get(f"{settings.api_root}/ready")
        except httpx.HTTPError:
            return JSONResponse({"status": "unavailable", "api": "unreachable"}, status_code=503)
        if upstream.status_code != 200:
            return JSONResponse({"status": "unavailable", "api": upstream.status_code}, status_code=503)
        return JSONResponse({"status": "ready"})

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        logger.info("service_started", extra={"fields": {"env": settings.env, "tools": 2}})
        try:
            async with mcp_app.lifespan(app):
                yield
        finally:
            await client.aclose()

    app = Starlette(
        routes=[Route("/health", health), Route("/ready", ready), Mount("/", app=mcp_app)],
        lifespan=lifespan,
    )
    app.add_middleware(BearerAuth, token=settings.mcp_bearer_token.get_secret_value())
    app.state.mcp = mcp
    return app
