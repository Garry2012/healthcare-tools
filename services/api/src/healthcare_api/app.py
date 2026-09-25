"""FastAPI application assembly."""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import InterfaceError, OperationalError

from . import errors
from .auth import StaticTokenVerifier, TokenVerifier
from .config import Settings, get_settings
from .db.session import make_engine, make_sessionmaker
from .logging import call_id_var, configure_logging, log_event
from .migrations import code_head
from .routers import (
    agent,
    appointments,
    availability,
    calls,
    directory,
    health,
    notifications,
    scheduling,
)

logger = logging.getLogger(__name__)
API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None, verifier: TokenVerifier | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    engine = make_engine(settings)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        log_event(logger, logging.INFO, "service_started", env=settings.env)
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(
        title="Healthcare Front-Desk Operations API",
        version="1.0.0-draft",
        description="Domain API for a hospital front-desk voice agent and the front-desk web application.",
        servers=[{"url": API_PREFIX}],
        lifespan=lifespan,
        separate_input_output_schemas=False,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.token_verifier = verifier or StaticTokenVerifier(settings.auth_tokens_json.get_secret_value())
    app.state.alembic_head = code_head()

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
        token = call_id_var.set(request.headers.get("x-call-id"))
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            call_id_var.reset(token)
        log_event(logger, logging.INFO, "request", method=request.method, path=request.url.path,
                  status=response.status_code, ms=round((time.perf_counter() - started) * 1000, 1))
        return response

    for router in (agent, directory, scheduling, availability, appointments, notifications, calls):
        app.include_router(router.router, prefix=API_PREFIX)
    app.include_router(health.router)
    _describe_errors_as_400(app)
    return app


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
