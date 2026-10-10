"""Starlette + FastMCP assembly: /mcp/ (streamable HTTP, stateless), /health, /ready, /dependencies.

The gateway bearer authenticates all four tools; trusted call identity comes from headers."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import re
import sys
import time
import traceback
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import get_args

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from pydantic import BaseModel, ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from . import (
    availability,
    context,
    contract,
    knowledge_contract,
    outcomes,
    packs,
    prompt,
    schedule_reader,
    summary,
    tools,
)
from .clock import Clock, Deadline
from .config import Settings, get_settings
from .ops_client import UnavailableReason, UpstreamError

logger = logging.getLogger(__name__)
DEPENDENCY_CHECK_SECONDS = 1.0
DEPENDENCY_CACHE_SECONDS = 15.0
DEPENDENCY_REFRESH_MIN_INTERVAL = 5.0  # ?refresh=1 is unauthenticated: never more than one upstream check per 5 s


# Values are derived once from their producers. Unknown values fail closed without guessing.
def _known(values):
    accepted = frozenset(values)
    return lambda value: type(value) is str and value in accepted


def _integer_between(low: int, high: int):
    return lambda value: type(value) is int and low <= value <= high


_REQUEST_ERRORS = {httpx.RequestError}
_pending_errors = [httpx.RequestError]
while _pending_errors:
    for _error in _pending_errors.pop().__subclasses__():
        if _error not in _REQUEST_ERRORS:
            _REQUEST_ERRORS.add(_error)
            _pending_errors.append(_error)

# IDs are matched but discarded; query strings and unknown routes never enter the log.
ROUTE_TEMPLATES = {
    re.compile(re.escape(route).replace(r"\{id\}", r"[^/?#]+")): route
    for route in ("/auth/token", "/departments", "/doctors", "/doctors/{id}", "/availability",
                  "/availability/{id}/slots", "/capabilities", "/appointments", "/appointments/{id}/cancel",
                  "/appointments/{id}/reschedule", "/call-summaries", knowledge_contract.ANSWER_PATH)
}


def _route_template(value):
    if type(value) is str:
        return next((route for pattern, route in ROUTE_TEMPLATES.items() if pattern.fullmatch(value)), None)
    return None


SAFE_LOG_FIELDS = {
    "tool": _known(tools.TOOL_NAMES),
    "outcome": _known(value for kind in (outcomes.AvailabilityOutcome, outcomes.BookingOutcome,
                                        outcomes.KnowledgeOutcome, outcomes.SummaryOutcome)
                      for value in get_args(kind)),
    "nextStep": _known(value for kind in (outcomes.NextStep, outcomes.BookingNextStep, outcomes.KnowledgeNextStep)
                       for value in get_args(kind)),
    "detail": _known((*schedule_reader.READ_FAILURE_DETAILS.values(), availability.DIRECTORY_FAILURE_DETAIL)),
    "reason": _known((*get_args(summary.SummaryFailureReason), *get_args(UnavailableReason))),
    "error": _known(c.__name__ for c in (*schedule_reader.READ_ERRORS, *_REQUEST_ERRORS, TimeoutError)),
    "model": _known(c.__name__ for c in vars(contract).values()
                    if isinstance(c, type) and issubclass(c, BaseModel) and c.__module__ == contract.__name__),
    "field": _known(knowledge_contract.AnswerResponse.model_fields),
    "header": _known(context.FIELD_OF_HEADER),
    "path": _route_template,
    "callId": lambda value: type(value) is str and context._ID.fullmatch(value) is not None,
    "summaryId": lambda value: type(value) is str and summary._LOG_ID.fullmatch(value) is not None,
    "status": _integer_between(100, 599),
    "httpStatus": _integer_between(100, 599),
    "attempt": _integer_between(1, 10),
    "retryAfterSeconds": _integer_between(0, 86_400),
    "env": _known(get_args(Settings.model_fields["env"].annotation)),
    "pack": _known(p.name.removesuffix(".json") for p in resources.files("frontdesk_mcp").joinpath("packs").iterdir()
                   if p.is_file() and p.name.endswith(".json")),
    "schemaVersion": _known((prompt.SCHEMA_VERSION,)),
}

# Verified against installed uvicorn/server.py, lifespan/on.py, protocols/http/* and
# mcp/server/streamable_http.py. FastMCP's already-filled tool-error f-string is deliberately absent.
SAFE_LIBRARY_MESSAGES = frozenset({
    "Started server process [%d]", "Waiting for application startup.", "Application startup complete.",
    "Application startup failed. Exiting.", "Uvicorn running on %s://%s:%d (Press CTRL+C to quit)",
    "Shutting down", "Waiting for application shutdown.", "Application shutdown complete.",
    "Finished server process [%d]", "Exception in ASGI application\n",
    "ASGI callable returned without completing response.", "No response message received before stream closed",
})
_REPO_ROOT = Path(__file__).resolve().parents[4]


def _error_frames(tb) -> list[str]:
    frames = []
    for frame in traceback.extract_tb(tb, limit=-10):
        path = Path(frame.filename)
        if "site-packages" in path.parts:
            relative = Path(*path.parts[path.parts.index("site-packages") + 1:]).as_posix()
        elif path.is_relative_to(_REPO_ROOT):
            relative = path.relative_to(_REPO_ROOT).as_posix()
        else:
            relative = path.name
        frames.append(f"{relative}:{frame.lineno} in {frame.name}")
    return frames


class JsonFormatter(logging.Formatter):
    """One safe JSON boundary: unfilled templates, exact internal facts, no free-text errors."""

    def __init__(self, provider: str = "") -> None:
        super().__init__()
        self.provider = provider

    def format(self, record: logging.LogRecord) -> str:
        adapter = record.name == "frontdesk_mcp" or record.name.startswith("frontdesk_mcp.")
        message = record.msg if type(record.msg) is str and (adapter or record.msg in SAFE_LIBRARY_MESSAGES) else (
            "library_message_omitted")
        entry = {"ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
                 "level": record.levelname, "logger": record.name, "msg": message}
        if self.provider:
            entry["provider"] = self.provider
        call_id = context.call_id_var.get()
        if call_id is not None and SAFE_LOG_FIELDS["callId"](call_id):
            entry["callId"] = call_id
        fields = getattr(record, "fields", None)
        if adapter and isinstance(fields, dict):
            omitted = []
            for name, value in fields.items():
                check = SAFE_LOG_FIELDS.get(name)
                if check is None:
                    omitted.append(name)
                    continue
                checked = check(value) if value is not None else True
                if checked:
                    entry[name] = checked if name == "path" and value is not None else value
                else:
                    omitted.append(name)
            if omitted:
                entry["omittedFields"] = omitted
        if record.exc_info and record.levelno >= logging.ERROR:
            entry["exception"] = record.exc_info[0].__name__
            entry["frames"] = _error_frames(record.exc_info[2])
        return json.dumps(entry)


# Libraries that log request URLs (which carry ?mobile=... to the owner API) or per-request chatter.
QUIET_LOGGERS = ("httpx", "httpcore", "uvicorn.access", "mcp", "docket")


def configure_logging(level: str, provider: str = "") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(provider))
    logging.getLogger().handlers[:] = [handler]
    logging.getLogger().setLevel(level.upper())
    fastmcp_logger = logging.getLogger("fastmcp")
    fastmcp_logger.handlers.clear()
    fastmcp_logger.propagate = True
    fastmcp_logger.setLevel(logging.NOTSET)
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


class BearerAuth:
    """Authenticates /mcp/; /health, /ready and /dependencies stay open."""

    def __init__(self, app: ASGIApp, gateway_token: str, development: bool) -> None:
        self.app = app
        self.gateway = f"Bearer {gateway_token}".encode() if gateway_token else b""
        self.development = development

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/mcp"):
            await self.app(scope, receive, send)
            return
        supplied = dict(scope.get("headers", [])).get(b"authorization", b"")
        authenticated = (hmac.compare_digest(supplied, self.gateway) if self.gateway else self.development)
        if not authenticated:
            response = JSONResponse({"error": "unauthorized"}, status_code=401,
                                    headers={"WWW-Authenticate": "Bearer"})
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


class SummaryErrorRedaction(Middleware):
    """Format framework validation failures without echoing private arguments; no validation of our own."""

    async def on_call_tool(self, context: MiddlewareContext, call_next: CallNext):
        try:
            return await call_next(context)
        except ValidationError:
            if context.message.name != "record_call_summary":
                raise
            # Error values, locations (unexpected argument names) and context can all contain caller data.
            raise ToolError("Invalid call summary arguments. Check required fields, types and limits.") from None


def build_mcp(services: tools.Services) -> FastMCP:
    settings = services.settings
    pack = packs.load(settings.domain_pack)
    mcp = FastMCP(
        name=f"frontdesk-{pack.name}",
        instructions=prompt.instructions(pack, settings.languages, settings.tenant_display_name),
        version=prompt.SCHEMA_VERSION,
        middleware=[SummaryErrorRedaction()],
        mask_error_details=True,
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
                       development=settings.env == "development")
    app.state.mcp = mcp
    app.state.services = services
    return app
