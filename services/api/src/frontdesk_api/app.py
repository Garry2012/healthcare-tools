"""FastAPI application assembly."""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import InterfaceError, OperationalError

from . import errors, locales
from .auth import StaticTokenVerifier, TokenVerifier
from .config import Settings, get_settings
from .db.session import DbStats, db_stats_var, make_engine, make_sessionmaker
from .logging import call_id_var, configure_logging, log_event
from .migrations import code_head
from .routers import (
    agent,
    availability,
    bookings,
    calls,
    directory,
    health,
    knowledge,
    notifications,
    scheduling,
)
from .services import directory as directory_service
from .services import knowledge as knowledge_service

logger = logging.getLogger(__name__)
API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None, verifier: TokenVerifier | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.provider_id)
    locales.select(settings.languages)  # one deployment serves one rollout's languages
    engine = make_engine(settings)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        log_event(logger, logging.INFO, "service_started", env=settings.env)
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(
        title="Front-Desk Operations API",
        version="1.0.0-draft",
        description="Domain API for a front-desk voice agent and the front-desk web application (any domain pack).",
        servers=[{"url": API_PREFIX}],
        lifespan=lifespan,
        separate_input_output_schemas=False,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.token_verifier = verifier or StaticTokenVerifier(settings.auth_tokens_json.get_secret_value())
    app.state.alembic_head = code_head()
    app.state.knowledge_cache = knowledge_service.new_cache()
    app.state.directory_cache = directory_service.new_cache()

    errors.install(app)

    @app.exception_handler(OperationalError)
    @app.exception_handler(InterfaceError)
    async def _database_down(_: Request, exc: Exception) -> JSONResponse:
        log_event(logger, logging.ERROR, "database_unavailable", error=type(exc).__name__)
        error = errors.ApiError("SERVICE_UNAVAILABLE", "The service is temporarily unavailable.",
                                headers={"Retry-After": "2"})
        return JSONResponse(error.body(), status_code=503, headers=error.headers)

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error", extra={"fields": {"error": type(exc).__name__}})
        return JSONResponse(errors.ApiError("INTERNAL", "Unexpected error.").body(), status_code=500)

    @app.middleware("http")
    async def _correlate(request: Request, call_next):
        raw = request.scope.get("raw_path", b"") + b"?" + request.scope.get("query_string", b"")
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > settings.max_request_bytes:
            error = errors.ApiError("VALIDATION_FAILED", f"Request body exceeds {settings.max_request_bytes} bytes.")
            return JSONResponse(error.body(), status_code=413)
        if b"%00" in raw or b"\x00" in raw:
            error = errors.ApiError("VALIDATION_FAILED", "Parameters must not contain NUL characters.")
            return JSONResponse(error.body(), status_code=400)
        token = call_id_var.set(request.headers.get("x-call-id"))
        stats_token = db_stats_var.set(stats := DbStats())
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            call_id_var.reset(token)
            db_stats_var.reset(stats_token)
        total_ms = (time.perf_counter() - started) * 1000
        db_ms = stats.seconds * 1000
        # Voice latency is the product: every response says where its time went.
        response.headers["Server-Timing"] = (
            f'db;dur={db_ms:.1f};desc="{stats.queries} queries", app;dur={total_ms - db_ms:.1f}, '
            f'total;dur={total_ms:.1f}'
        )
        log_event(logger, logging.INFO, "request", method=request.method, path=request.url.path,
                  status=response.status_code, ms=round(total_ms, 1), db_ms=round(db_ms, 1), queries=stats.queries)
        return response

    for router in (agent, directory, scheduling, availability, bookings, notifications, knowledge, calls):
        app.include_router(router.router, prefix=API_PREFIX)
    app.include_router(health.router)
    _describe_errors_as_400(app)
    app.add_middleware(BodyLimit, limit=settings.max_request_bytes)
    return app


class BodyLimit:
    """Reads the request body (at most MAX_REQUEST_BYTES) before the app sees it, so a chunked
    upload without Content-Length cannot get past the limit either; then replays it."""

    def __init__(self, app, limit: int) -> None:
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "DELETE", "OPTIONS"):
            await self.app(scope, receive, send)
            return
        messages, size = [], 0
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] != "http.request":
                break
            size += len(message.get("body", b""))
            if size > self.limit:
                error = errors.ApiError("VALIDATION_FAILED", f"Request body exceeds {self.limit} bytes.")
                await JSONResponse(error.body(), status_code=413)(scope, receive, send)
                return
            if not message.get("more_body", False):
                break
        pending = iter(messages)

        async def replay():
            return next(pending, None) or await receive()

        await self.app(scope, replay, send)


def _describe_errors_as_400(app: FastAPI) -> None:
    """Validation failures are returned as 400 `Error` (the spec), never FastAPI's 422."""
    original = app.openapi

    def openapi() -> dict:
        if app.openapi_schema is None:
            schema = original()
            for item in schema.get("paths", {}).values():
                for operation in item.values():
                    operation.get("responses", {}).pop("422", None)
            for name in ("HTTPValidationError", "ValidationError"):
                schema.get("components", {}).get("schemas", {}).pop(name, None)
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]
