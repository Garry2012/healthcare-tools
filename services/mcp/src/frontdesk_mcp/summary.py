"""record_call_summary: POST /call-summaries from the authenticated call-end lifecycle.

Call identity and timing are injected from trusted context (never from the invoker's arguments); the
callback number is caller-provided contact data and is never copied from caller ID. The payload is
built once, deterministically, and keyed by the call id, so a retry replays and a changed body
conflicts. The owner's callId deduplication makes the first accepted summary final.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from . import contract, identity, outcomes
from .clock import Deadline
from .config import Settings
from .context import CallContext
from .ops_client import Malformed, OpsClient, Rejected, Unavailable, UncertainWrite

logger = logging.getLogger(__name__)

SUMMARY_MAX = 500
_ID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
_TRANSFERS = {"TRANSFERRED", "EMERGENCY_TRANSFERRED"}


class SummaryRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    intent: contract.CallIntent
    outcome: contract.CallOutcome
    summaryText: str = Field(max_length=2000, description="One or two sentences for the admin UI; never a transcript.")  # noqa: N815
    callerName: str | None = Field(default=None, max_length=100)  # noqa: N815
    callerMobile: str | None = Field(default=None, max_length=20, description="Only when the caller gave it.")  # noqa: N815
    language: str | None = Field(default=None, max_length=16)
    doctorId: str | None = Field(default=None, max_length=64)  # noqa: N815
    appointmentId: str | None = Field(default=None, max_length=64)  # noqa: N815
    transferredTo: str | None = Field(default=None, max_length=64, description="Free text, ≤64 characters.")  # noqa: N815
    requestedDate: str | None = Field(  # noqa: N815
        default=None, max_length=10, description="YYYY-MM-DD the caller asked about (kept whole in the summary text).")


def summary_key(provider: str, call_id: str) -> str:
    return hashlib.sha256(f"{provider}|summary|{call_id}".encode()).hexdigest()


def contract_language(tag: str | None) -> str | None:
    if not tag:
        return None
    primary = tag.split("-")[0].lower()
    return {"en": "EN", "kn": "KN", "hi": "HI"}.get(primary)


def compose_text(caller_name: str | None, callback: bool, free_text: str, requested_date: str | None = None,
                 doctor_id: str | None = None) -> str:
    """Name, the callback marker and the requested date/doctor are essential and kept whole; only the free
    text is shortened. The number travels in the structured callerMobile field."""
    prefix = ""
    if caller_name:
        prefix += f"Caller: {caller_name.strip()}. "
    if callback:
        prefix += "Callback requested. "
        if requested_date or doctor_id:
            what = " with ".join(part for part in (requested_date, doctor_id) if part)
            prefix += f"Requested: {what}. "
    free = " ".join(free_text.split())
    room = SUMMARY_MAX - len(prefix)
    if len(free) > room:
        free = free[: max(room - 1, 0)].rstrip() + "…"
    return (prefix + free)[:SUMMARY_MAX]


class SummaryService:
    def __init__(self, ops: OpsClient, settings: Settings) -> None:
        self.ops = ops
        self.settings = settings

    def _validate(self, request: SummaryRequest) -> list[str]:
        fields: list[str] = []
        callback = request.outcome == "CALLBACK_NOTED"
        if request.callerMobile is not None and not identity.is_contract_mobile(request.callerMobile):
            fields.append("callerMobile")
        if callback:
            if not request.callerMobile:
                fields.append("callerMobile")
            if not (request.callerName or "").strip():
                fields.append("callerName")
            if request.appointmentId:
                fields.append("appointmentId")
            if request.transferredTo:
                fields.append("transferredTo")
        if request.transferredTo and request.outcome not in _TRANSFERS:
            fields.append("transferredTo")
        for name in ("doctorId", "appointmentId"):
            value = getattr(request, name)
            if value and not _ID.fullmatch(value):
                fields.append(name)
        if request.transferredTo is not None and not 1 <= len(request.transferredTo.strip()) <= 64:
            fields.append("transferredTo")
        if request.requestedDate and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", request.requestedDate):
            fields.append("requestedDate")
        if not request.summaryText.strip():
            fields.append("summaryText")
        return sorted(set(fields))

    def build_body(self, ctx: CallContext, request: SummaryRequest) -> dict[str, Any]:
        body: dict[str, Any] = {"callId": ctx.call_id, "startedAt": ctx.call_started_at.isoformat()}
        if ctx.call_duration_seconds is not None:
            body["durationSeconds"] = ctx.call_duration_seconds
        if language := contract_language(request.language):
            body["language"] = language
        if request.callerMobile:
            body["callerMobile"] = request.callerMobile
        body["intent"] = request.intent
        body["outcome"] = request.outcome
        if request.transferredTo:
            body["transferredTo"] = request.transferredTo
        if request.doctorId:
            body["doctorId"] = request.doctorId
        if request.appointmentId:
            body["appointmentId"] = request.appointmentId
        body["summaryText"] = compose_text(request.callerName, request.outcome == "CALLBACK_NOTED", request.summaryText,
                                           request.requestedDate, request.doctorId)
        return body

    async def record(self, ctx: CallContext, request: SummaryRequest) -> outcomes.SummaryResult:
        if not ctx.call_id or ctx.call_started_at is None:
            logger.warning("summary_without_lifecycle_context")
            return outcomes.SummaryResult(outcome="LIFECYCLE_CONTEXT_MISSING", nextStep="FIX_PLATFORM_INPUT",
                                          detail="CALL_ID_MISSING" if not ctx.call_id else "STARTED_AT_MISSING")
        if fields := self._validate(request):
            return outcomes.SummaryResult(outcome="INVALID_REQUEST", nextStep="FIX_PLATFORM_INPUT", fields=fields)
        body = self.build_body(ctx, request)
        key = summary_key(self.settings.provider_id, ctx.call_id)
        # After the call: its own budget and per-exchange cap, never the in-call share.
        deadline = Deadline(self.settings.summary_deadline_seconds, cap=self.settings.summary_deadline_seconds)
        try:
            status, stored = await self.ops.create_call_summary(body, key, deadline)
        except Rejected as exc:
            if exc.code == "IDEMPOTENCY_CONFLICT":
                return outcomes.SummaryResult(outcome="CONFLICT", nextStep="FIX_PLATFORM_INPUT",
                                              detail="IDEMPOTENCY_CONFLICT")
            return outcomes.SummaryResult(outcome="REJECTED", nextStep="FIX_PLATFORM_INPUT", fields=list(exc.fields),
                                          detail=exc.code or "REJECTED")
        except UncertainWrite:
            return outcomes.SummaryResult(outcome="UNCERTAIN", nextStep="RETRY_SAME_PAYLOAD",
                                          detail="NO_VERIFIED_RESPONSE")
        except Malformed:
            return outcomes.SummaryResult(outcome="UNCERTAIN", nextStep="RETRY_SAME_PAYLOAD",
                                          detail="MALFORMED_SUCCESS")
        except Unavailable as exc:
            # Transient: the platform keeps the frozen payload and retries later; only a credential problem is final.
            step = "RECORD_FAILED" if exc.reason == "AUTH" else "RETRY_SAME_PAYLOAD"
            return outcomes.SummaryResult(outcome="COULD_NOT_RECORD", nextStep=step, detail=exc.reason,
                                          retryAfterSeconds=exc.retry_after)
        if status == 201:
            return outcomes.SummaryResult(outcome="STORED", nextStep="DONE", summaryId=stored.id)
        # 200: the owner returned the summary that already exists under this callId, unchanged. Only when it is
        # ours (same intent and outcome, same callback number when we sent one) is it a replay of our write.
        extra = stored.model_extra or {}
        mine = (stored.intent == request.intent and stored.outcome == request.outcome
                and (not request.callerMobile or extra.get("callerMobile") == request.callerMobile))
        if not mine:
            logger.warning("summary_call_id_already_used", extra={"fields": {"stored_outcome": stored.outcome}})
            return outcomes.SummaryResult(outcome="CONFLICT", nextStep="FIX_PLATFORM_INPUT",
                                          detail="CALL_ID_ALREADY_USED")
        return outcomes.SummaryResult(outcome="REPLAYED", nextStep="DONE", summaryId=stored.id)
