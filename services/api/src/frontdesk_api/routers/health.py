"""Liveness and readiness. Readiness = database reachable AND schema at the code's Alembic head."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ..logging import log_event

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Health"], include_in_schema=False)


@router.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    expected: str = request.app.state.alembic_head
    try:
        async with request.app.state.sessionmaker() as session:
            current = await session.scalar(text("SELECT version_num FROM alembic_version"))
    except (SQLAlchemyError, OSError) as exc:
        log_event(logger, logging.WARNING, "readiness_failed", error=type(exc).__name__)
        return JSONResponse({"status": "unavailable", "reason": type(exc).__name__}, status_code=503)
    if current != expected:
        return JSONResponse(
            {"status": "unavailable", "schema": current, "expected": expected}, status_code=503
        )
    return JSONResponse({"status": "ready", "schema": current})
