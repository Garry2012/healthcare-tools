"""One whole-call summary, stored unchanged by Manoj under the trusted call ID.

The first accepted summary is final. Call identity/start time come from headers; the callback
number is caller-provided contact data, never caller-ID authorization. Retries use the same body.
"""

from __future__ import annotations

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
_LOG_ID = re.compile(r"^(?:cs_[A-Za-z0-9]{1,61}|[A-Fa-f0-9]{8}(?:-[A-Fa-f0-9]{4}){3}-[A-Fa-f0-9]{12})$")
_TRANSFERS = {"TRANSFERRED", "EMERGENCY_TRANSFERRED"}


class SummaryRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    intent: contract.CallIntent
    outcome: contract.CallOutcome
    # Outer argument cap; the service returns an in-band INVALID_REQUEST above SUMMARY_MAX.
    summaryText: str = Field(max_length=2000)  # noqa: N815
    callerMobile: str | None = Field(default=None, max_length=20)  # noqa: N815
    language: str | None = Field(default=None, max_length=16)
    doctorId: str | None = Field(default=None, max_length=64)  # noqa: N815
    appointmentId: str | None = Field(default=None, max_length=64)  # noqa: N815
    transferredTo: str | None = Field(default=None, max_length=64)  # noqa: N815


def contract_language(tag: str | None) -> str | None:
    if not tag:
        return None
    primary = tag.split("-")[0].lower()
    return {"en": "EN", "kn": "KN", "hi": "HI"}.get(primary)


class SummaryService:
    def __init__(self, ops: OpsClient, settings: Settings) -> None:
        self.ops = ops
        self.settings = settings

    def _validate(self, request: SummaryRequest) -> list[str]:
        fields: list[str] = []
        if request.callerMobile is not None and not identity.is_contract_mobile(request.callerMobile):
            fields.append("callerMobile")
        if request.outcome == "CALLBACK_NOTED":
            if not request.callerMobile:
                fields.append("callerMobile")
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
        if not request.summaryText.strip() or len(request.summaryText) > SUMMARY_MAX:
            fields.append("summaryText")
        return sorted(set(fields))

    def build_body(self, ctx: CallContext, request: SummaryRequest) -> dict[str, Any]:
        body: dict[str, Any] = {"callId": ctx.call_id, "startedAt": ctx.call_started_at.isoformat(),
                                "intent": request.intent, "outcome": request.outcome,
                                "summaryText": request.summaryText}
        if language := contract_language(request.language):
            body["language"] = language
        for name in ("callerMobile", "transferredTo", "doctorId", "appointmentId"):
            if value := getattr(request, name):
                body[name] = value
        return body

    @staticmethod
    def _failure(ctx: CallContext, outcome: outcomes.SummaryOutcome, reason: str,
                 retry_after: int | None = None) -> outcomes.SummaryResult:
        event = "summary_call_id_mismatch" if reason == "CALL_ID_MISMATCH" else "summary_write_unverified"
        logger.warning(event, extra={"fields": {"callId": ctx.call_id, "outcome": outcome,
                                                 "reason": reason, "retryAfterSeconds": retry_after}})
        return outcomes.SummaryResult(outcome=outcome)

    async def record(self, ctx: CallContext, request: SummaryRequest) -> outcomes.SummaryResult:
        if not ctx.call_id or ctx.call_started_at is None:
            return self._failure(ctx, "NOT_SAVED", "CALL_ID_MISSING" if not ctx.call_id else "STARTED_AT_MISSING")
        if fields := self._validate(request):
            return outcomes.SummaryResult(outcome="INVALID_REQUEST", fields=fields)
        body = self.build_body(ctx, request)
        # Separate summary budget and per-exchange cap, including auth and any same-request retry.
        deadline = Deadline(self.settings.summary_deadline_seconds, cap=self.settings.summary_deadline_seconds)
        try:
            status, stored = await self.ops.create_call_summary(body, deadline)
        except Rejected as exc:
            if exc.status == 400:
                allowed = set(SummaryRequest.model_fields) | {"callId", "startedAt"}
                return outcomes.SummaryResult(outcome="INVALID_REQUEST", fields=sorted(set(exc.fields) & allowed))
            return self._failure(ctx, "NOT_CONFIRMED", "UNEXPECTED_STATUS")
        except UncertainWrite:
            return self._failure(ctx, "NOT_CONFIRMED", "NO_VERIFIED_RESPONSE")
        except Malformed:
            return self._failure(ctx, "NOT_CONFIRMED", "MALFORMED_SUCCESS")
        except Unavailable as exc:
            outcome = "NOT_SAVED" if exc.reason == "AUTH" else "NOT_CONFIRMED"
            return self._failure(ctx, outcome, exc.reason, exc.retry_after)
        if status not in (200, 201):
            return self._failure(ctx, "NOT_CONFIRMED", "UNEXPECTED_STATUS")
        if stored.callId != ctx.call_id:
            return self._failure(ctx, "NOT_CONFIRMED", "CALL_ID_MISMATCH")
        if status == 201:
            # Owner IDs are untrusted strings. Unexpected formats are omitted from logs, not rejected.
            fields = {"callId": ctx.call_id}
            if _LOG_ID.fullmatch(stored.id):
                fields["summaryId"] = stored.id
            logger.info("summary_saved", extra={"fields": fields})
            return outcomes.SummaryResult(outcome="SAVED")
        return outcomes.SummaryResult(outcome="ALREADY_SAVED")
