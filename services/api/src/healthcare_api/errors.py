"""Domain errors and their mapping onto the spec's `Error` envelope."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

_STATUS = {
    "VALIDATION_FAILED": 400,
    "UNAUTHORIZED": 401,
    "FORBIDDEN": 403,
    "NOT_FOUND": 404,
    "CONFLICT": 409,
    "IDEMPOTENCY_CONFLICT": 409,
    "SLOT_UNAVAILABLE": 409,
    "RATE_LIMITED": 429,
    "INTERNAL": 500,
    "SERVICE_UNAVAILABLE": 503,
    "UPSTREAM_TIMEOUT": 504,
}

# Deliberately identical for "no such appointment" and "not yours" (openapi NotFound).
NOT_FOUND_MESSAGE = "No matching appointment was found."


class ApiError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: list[dict[str, str]] | None = None,
        current_slots: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        self.current_slots = current_slots
        self.headers = headers or {}

    @property
    def status(self) -> int:
        return _STATUS[self.code]

    def body(self) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            error["details"] = self.details
        if self.current_slots is not None:
            error["currentSlots"] = self.current_slots
        return {"error": error}


def not_found(message: str = NOT_FOUND_MESSAGE) -> ApiError:
    return ApiError("NOT_FOUND", message)


def validation(message: str, field: str | None = None) -> ApiError:
    details = [{"field": field, "issue": message}] if field else None
    return ApiError("VALIDATION_FAILED", message, details=details)


def _json(error: ApiError) -> JSONResponse:
    return JSONResponse(error.body(), status_code=error.status, headers=error.headers)


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _json(exc)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"field": ".".join(str(p) for p in err.get("loc", ()) if p != "body"),
             "issue": str(err.get("msg", "invalid"))}
            for err in exc.errors()[:10]
        ]
        return _json(ApiError("VALIDATION_FAILED", "The request is not valid.", details=details))

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "VALIDATION_FAILED"}
        mapped = code.get(exc.status_code, "INTERNAL" if exc.status_code >= 500 else "VALIDATION_FAILED")
        error = ApiError(mapped, str(exc.detail) if exc.detail else mapped.replace("_", " ").lower())
        # Keep Starlette's headers: a 405 must say which methods are allowed.
        return JSONResponse(error.body(), status_code=exc.status_code, headers=getattr(exc, "headers", None))
