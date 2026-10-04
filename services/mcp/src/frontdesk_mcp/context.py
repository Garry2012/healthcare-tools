"""Trusted call context: what the voice platform forwards (through the gateway) as HTTP headers on
each MCP request. The model never sees or supplies these; a malformed value is treated as absent,
never guessed. Authentication is checked by the server before tools run."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime

from .config import Settings

logger = logging.getLogger(__name__)

# The current request's call id, for log correlation.
call_id_var: ContextVar[str | None] = ContextVar("mcp_call_id", default=None)

_ID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
FIELD_OF_HEADER = {
    "x-call-id": "call_id",
    "x-caller-number": "caller_number",
    "x-caller-verification": "caller_verification",
    "x-operation-id": "operation_id",
    "x-call-started-at": "call_started_at",
}
# Headers the gateway must pass through from the platform (deploy/contextforge/register.py).
PASSTHROUGH_HEADERS = ("X-Call-Id", "X-Caller-Number", "X-Caller-Verification",
                       "X-Operation-Id", "X-Call-Started-At")


@dataclass(frozen=True)
class CallContext:
    call_id: str | None = None
    caller_number: str | None = None
    caller_verification: str | None = None
    operation_id: str | None = None
    call_started_at: datetime | None = None


def _ident(value: str | None, header: str) -> str | None:
    if value is None:
        return None
    if not _ID.fullmatch(value):
        logger.warning("trusted_header_malformed", extra={"fields": {"header": header}})
        return None
    return value


def _started_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        logger.warning("trusted_header_malformed", extra={"fields": {"header": "x-call-started-at"}})
        return None
    if parsed.tzinfo is None:
        logger.warning("trusted_header_malformed", extra={"fields": {"header": "x-call-started-at"}})
        return None
    return parsed


def from_headers(headers: Mapping[str, str], settings: Settings) -> CallContext:
    lower = {k.lower(): v for k, v in headers.items()}
    call_id = _ident(lower.get("x-call-id"), "x-call-id")
    call_id_var.set(call_id)
    caller = lower.get("x-caller-number") or None
    # The platform must say what it verified; a bare number authorises nothing (absent means unverified).
    verification = lower.get("x-caller-verification") or None
    if not caller and settings.env == "development" and settings.mcp_dev_caller_number:
        caller, verification = settings.mcp_dev_caller_number, "SIP_CALLER_ID"  # development convenience only
    return CallContext(
        call_id=call_id,
        caller_number=caller,
        caller_verification=verification if caller else None,
        operation_id=_ident(lower.get("x-operation-id"), "x-operation-id"),
        call_started_at=_started_at(lower.get("x-call-started-at")),
    )
