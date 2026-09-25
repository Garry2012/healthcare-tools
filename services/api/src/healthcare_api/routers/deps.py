"""Shared request dependencies and the response helper."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Annotated, Any

from fastapi import Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..db.session import get_session
from ..errors import ApiError, validation
from ..schemas import Error

CALLER_PATTERN = r"^\+[1-9][0-9]{6,14}$"

Session = Annotated[AsyncSession, Depends(get_session)]
CallId = Annotated[str, Header(alias="X-Call-Id", max_length=64)]
CallerNumber = Annotated[str | None, Header(alias="X-Caller-Number", pattern=CALLER_PATTERN)]
IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key", max_length=64)]
ActingUser = Annotated[str, Header(alias="X-Acting-User", max_length=64)]


def settings_of(request: Request) -> Settings:
    return request.app.state.settings


SettingsDep = Annotated[Settings, Depends(settings_of)]


def respond(
    model: BaseModel | dict[str, Any], status: int = 200, headers: dict[str, str] | None = None
) -> JSONResponse:
    body = model if isinstance(model, dict) else model.model_dump(mode="json", by_alias=True, exclude_none=True)
    return JSONResponse(body, status_code=status, headers=headers)


def require_key(key: str | None) -> str:
    if not key:
        raise validation("Idempotency-Key is required on agent writes.", "Idempotency-Key")
    return key


async def within[T](seconds: float, work: Awaitable[T]) -> T:
    """Writes complete or roll back within the budget (IMPLEMENTATION.md §2.5)."""
    try:
        async with asyncio.timeout(seconds):
            return await work
    except TimeoutError:
        raise ApiError(
            "UPSTREAM_TIMEOUT",
            "The write did not complete in time. Retry once with the same Idempotency-Key.",
        ) from None


ERRORS = {
    400: {"description": "Invalid request."},
    401: {"description": "Missing or invalid credentials."},
    403: {"description": "Missing scope."},
    404: {"description": "Not found."},
    409: {"description": "Conflict."},
    429: {"description": "Too many requests."},
    500: {"description": "Unexpected error."},
    503: {"description": "Temporarily unavailable."},
    504: {"description": "Write did not complete within 5 s."},
}


def errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: {**ERRORS[code], "model": Error} for code in codes}
