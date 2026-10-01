"""Trusted call context: what the voice platform forwards (through the gateway) as HTTP headers on
each MCP request. The model never sees or supplies these; a malformed value is treated as absent,
never guessed. `principal` is set by the server's bearer check, not by any header."""

from __future__ import annotations

import base64
import binascii
import json
import logging
import re
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from .config import Settings

logger = logging.getLogger(__name__)

Principal = Literal["conversation", "lifecycle"]
# Set by the server for the current request: which bearer authenticated it.
principal_var: ContextVar[Principal | None] = ContextVar("mcp_principal", default=None)
# The current request's call id, for log correlation.
call_id_var: ContextVar[str | None] = ContextVar("mcp_call_id", default=None)

_ID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
# Agreed size limit for one turn's words. Never truncated: an oversized context is refused (no clearance),
# because the decisive words may be at the end. Header transport comfortably carries 4,000 characters.
UTTERANCE_MAX = 4000
TurnFailure = Literal["TURN_CONTEXT_MISSING", "TURN_CONTEXT_MALFORMED", "TURN_CONTEXT_OVERSIZED"]

FIELD_OF_HEADER = {
    "x-call-id": "call_id",
    "x-caller-number": "caller_number",
    "x-caller-verification": "caller_verification",
    "x-turn-context": "turn",
    "x-operation-id": "operation_id",
    "x-call-started-at": "call_started_at",
    "x-call-duration-seconds": "call_duration_seconds",
}
# Headers the gateway must pass through from the platform (deploy/contextforge/register.py).
PASSTHROUGH_HEADERS = ("X-Call-Id", "X-Caller-Number", "X-Caller-Verification", "X-Turn-Context",
                       "X-Operation-Id", "X-Call-Started-At", "X-Call-Duration-Seconds")


@dataclass(frozen=True)
class TurnContext:
    """The caller's original words for this turn, as the platform heard them (not as the model retold them)."""

    utterance: str
    language: str
    turn_id: str | None = None


@dataclass(frozen=True)
class CallContext:
    call_id: str | None = None
    caller_number: str | None = None
    caller_verification: str | None = None
    turn: TurnContext | None = None
    turn_failure: TurnFailure | None = None  # why `turn` is None; never clearance
    operation_id: str | None = None
    call_started_at: datetime | None = None
    call_duration_seconds: int | None = None


def _ident(value: str | None, header: str) -> str | None:
    if value is None:
        return None
    if not _ID.fullmatch(value):
        logger.warning("trusted_header_malformed", extra={"fields": {"header": header}})
        return None
    return value


def _turn(value: str | None) -> tuple[TurnContext | None, TurnFailure | None]:
    if not value:
        return None, "TURN_CONTEXT_MISSING"
    try:
        padded = value + "=" * (-len(value) % 4)
        raw = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        utterance, language = raw["utterance"], raw["language"]
        if not isinstance(utterance, str) or not isinstance(language, str) or not utterance.strip():
            raise ValueError("utterance/language must be non-empty strings")
        turn_id = raw.get("turnId")
        if turn_id is not None and not isinstance(turn_id, str):
            raise ValueError("turnId must be a string")
    except (binascii.Error, UnicodeDecodeError, ValueError, KeyError, TypeError, AttributeError):
        logger.warning("trusted_header_malformed", extra={"fields": {"header": "x-turn-context"}})
        return None, "TURN_CONTEXT_MALFORMED"
    if len(utterance) > UTTERANCE_MAX or len(language) > 16:
        logger.warning("trusted_turn_oversized", extra={"fields": {"length": len(utterance), "max": UTTERANCE_MAX}})
        return None, "TURN_CONTEXT_OVERSIZED"
    return TurnContext(utterance=utterance, language=language, turn_id=turn_id), None


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


def _duration(value: str | None) -> int | None:
    if value is None:
        return None
    if not value.isdigit():
        logger.warning("trusted_header_malformed", extra={"fields": {"header": "x-call-duration-seconds"}})
        return None
    return int(value)


def from_headers(headers: Mapping[str, str], settings: Settings) -> CallContext:
    lower = {k.lower(): v for k, v in headers.items()}
    call_id = _ident(lower.get("x-call-id"), "x-call-id")
    call_id_var.set(call_id)
    caller = lower.get("x-caller-number") or None
    # The platform must say what it verified; a bare number authorises nothing (absent means unverified).
    verification = lower.get("x-caller-verification") or None
    if not caller and settings.env == "development" and settings.mcp_dev_caller_number:
        caller, verification = settings.mcp_dev_caller_number, "SIP_CALLER_ID"  # development convenience only
    turn, turn_failure = _turn(lower.get("x-turn-context"))
    return CallContext(
        call_id=call_id,
        caller_number=caller,
        caller_verification=verification if caller else None,
        turn=turn,
        turn_failure=turn_failure,
        operation_id=_ident(lower.get("x-operation-id"), "x-operation-id"),
        call_started_at=_started_at(lower.get("x-call-started-at")),
        call_duration_seconds=_duration(lower.get("x-call-duration-seconds")),
    )
