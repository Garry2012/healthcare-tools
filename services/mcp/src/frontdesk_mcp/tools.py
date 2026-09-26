"""The two tools. Each one is a wrapper over an `Agent` REST operation and adds only:
call-context headers, a derived Idempotency-Key, and a failure envelope. No domain rules.

The model never sees or supplies X-Call-Id, X-Caller-Number or Idempotency-Key; they come
from the incoming MCP HTTP request (forwarded by the gateway from the voice platform).
"""

from __future__ import annotations

import hashlib
import json
import logging
import unicodedata
from datetime import date
from importlib import resources
from typing import Annotated, Any, Literal

import httpx
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from .config import Settings

logger = logging.getLogger(__name__)
DESCRIPTIONS: dict[str, str] = json.loads(
    resources.files("frontdesk_mcp").joinpath("descriptions.json").read_text(encoding="utf-8")
)

Action = Literal["BOOK", "LIST", "CANCEL", "RESCHEDULE"]
DayPart = Literal["MORNING", "AFTERNOON", "EVENING", "ANY"]
Gender = Literal["FEMALE", "MALE"]
Relation = Literal["SELF", "CHILD", "PARENT", "SPOUSE", "OTHER"]


class When(BaseModel):
    """Either an expression ("tomorrow evening", "ನಾಳೆ", "kal shaam") or explicit dates."""

    expression: Annotated[str | None, Field(max_length=100, description="As the caller said it.")] = None
    dateFrom: date | None = None  # noqa: N815 - wire name
    dateTo: date | None = None  # noqa: N815
    dayPart: DayPart | None = None  # noqa: N815


class Preferences(BaseModel):
    gender: Gender | None = None
    language: Annotated[str | None, Field(description="Preferred consultation language (BCP-47).")] = None


class Customer(BaseModel):
    name: Annotated[str, Field(max_length=100, description="As spoken and spelled back.")]
    phone: Annotated[str, Field(pattern=r"^[0-9]{6,15}$", description="Dictated and read back. Never the caller ID.")]
    relationToCaller: Relation | None = None  # noqa: N815


# Model-visible parameters, described from the Agent request schemas in openapi.yaml.
Utterance = Annotated[str, Field(max_length=500, description="The caller's request verbatim, as STT delivered it.")]
LanguageTag = Annotated[str, Field(description="Language tag reported by STT: en, kn, hi, ta, te, ...")]
ResourceName = Annotated[str | None, Field(max_length=100, description="If the caller named a resource. As heard.")]
CategoryText = Annotated[
    str | None, Field(max_length=100, description="If the caller named a speciality or category. As heard.")
]
NeedText = Annotated[str | None, Field(max_length=300, description="If the caller described a problem. As heard.")]
WhenArg = Annotated[When | None, Field(description="When they want to come. Never compute dates yourself.")]
ActionArg = Annotated[Action, Field(description="BOOK a slot, LIST the caller's bookings, CANCEL or RESCHEDULE.")]
SlotIdArg = Annotated[str | None, Field(description="BOOK: a slotId returned by find_availability.")]
CustomerArg = Annotated[Customer | None, Field(description="BOOK: the customer. One customer per call.")]
ReasonArg = Annotated[str | None, Field(max_length=500, description="BOOK/CANCEL: the caller's own words.")]
BookLanguage = Annotated[str | None, Field(description="BOOK: the caller's language tag.")]
TimingArg = Annotated[bool, Field(description="BOOK: the caller wants the desk to confirm an unconfirmed timing.")]
CustomerNameArg = Annotated[
    str | None, Field(max_length=100, description="LIST (optional), CANCEL, RESCHEDULE: the customer's name.")
]
SpokenPhoneArg = Annotated[
    str | None,
    Field(pattern=r"^[0-9]{6,15}$", description="LIST only: a spoken number when caller ID is missing or differs."),
]
FromArg = Annotated[date | None, Field(description="LIST: earliest booking date.")]
ToArg = Annotated[date | None, Field(description="LIST: latest booking date.")]
BookingIdArg = Annotated[str | None, Field(description="CANCEL/RESCHEDULE: an bookingId from LIST or BOOK.")]
NewSlotIdArg = Annotated[str | None, Field(description="RESCHEDULE: a slotId returned by find_availability.")]


# ---------------------------------------------------------------- transport


def call_context(settings: Settings) -> dict[str, str]:
    """Trusted identity comes from the MCP request headers only; absent means absent."""
    incoming = get_http_headers()
    headers: dict[str, str] = {}
    if call_id := incoming.get("x-call-id"):
        headers["X-Call-Id"] = call_id
    caller = incoming.get("x-caller-number")
    if not caller and settings.env != "production" and settings.mcp_dev_caller_number:
        caller = settings.mcp_dev_caller_number
    if caller:
        headers["X-Caller-Number"] = caller
    return headers


def normalise_name(name: str | None) -> str:
    return " ".join(unicodedata.normalize("NFC", name or "").casefold().split())


def idempotency_key(call_id: str, action: str, customer_name: str | None, target: str) -> str:
    """IMPLEMENTATION.md §2.5: sha256(callId | action | customer name | slotId or bookingId)."""
    material = "|".join((call_id, action, normalise_name(customer_name), target))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _failure(write: bool, retry_after: int) -> dict[str, Any]:
    return {"outcome": "COULD_NOT_RECORD" if write else "COULD_NOT_CHECK", "retryAfterSeconds": retry_after}


def _retry_after(response: httpx.Response, default: int) -> int:
    try:
        return max(0, int(response.headers.get("retry-after", default)))
    except ValueError:
        return default


def _invalid(field: str, message: str) -> dict[str, Any]:
    return {"error": {"code": "VALIDATION_FAILED", "message": message, "details": [{"field": field, "issue": message}]}}


class ApiClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        token = settings.api_bearer_token.get_secret_value()
        self.http = httpx.AsyncClient(
            base_url=settings.api_base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"} if token else {},
            transport=transport,
        )

    async def aclose(self) -> None:
        await self.http.aclose()

    async def send(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        write: bool,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """REST body unchanged on 2xx/4xx; a failure envelope on transport errors, 429, 5xx."""
        timeout = self.settings.write_timeout_seconds if write else self.settings.read_timeout_seconds
        default_wait = self.settings.default_retry_after_seconds
        attempts = 2 if write else 1  # one same-key retry on a write timeout, never a new key
        for attempt in range(attempts):
            last = attempt == attempts - 1
            try:
                response = await self.http.request(
                    method, path, headers=headers, json=json_body, params=params, timeout=timeout
                )
            except httpx.TimeoutException:
                logger.warning("api_timeout", extra={"fields": {"path": path, "attempt": attempt + 1}})
                if not last:
                    continue
                return _failure(write, default_wait)
            except httpx.TransportError as exc:
                logger.warning("api_unreachable", extra={"fields": {"path": path, "error": type(exc).__name__}})
                return _failure(write, default_wait)
            if response.status_code == 504 and not last:
                continue  # UPSTREAM_TIMEOUT: the API asks for exactly this retry
            if response.status_code == 429 or response.status_code >= 500:
                return _failure(write, _retry_after(response, default_wait))
            try:
                return response.json()
            except ValueError:
                return _failure(write, default_wait)
        return _failure(write, default_wait)


# ---------------------------------------------------------------- tools


def register(mcp: FastMCP, client: ApiClient) -> None:
    settings = client.settings

    @mcp.tool(
        name="find_availability",
        description=DESCRIPTIONS["find_availability"],
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    )
    async def find_availability(
        utterance: Utterance,
        language: LanguageTag,
        resourceName: ResourceName = None,  # noqa: N803 - parameter names mirror the REST schema
        category: CategoryText = None,
        needText: NeedText = None,  # noqa: N803
        when: WhenArg = None,
        preferences: Preferences | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"utterance": utterance, "language": language}
        for key, value in (("resourceName", resourceName), ("category", category), ("needText", needText)):
            if value:
                body[key] = value
        if when is not None:
            body["when"] = when.model_dump(mode="json", exclude_none=True)
        if preferences is not None:
            body["preferences"] = preferences.model_dump(mode="json", exclude_none=True)
        return await client.send("POST", "/agent/availability-search", headers=call_context(settings),
                                 json_body=body, write=False)

    @mcp.tool(
        name="manage_booking",
        description=DESCRIPTIONS["manage_booking"],
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True,
                                    openWorldHint=False),
    )
    async def manage_booking(  # noqa: N803 - parameter names mirror the REST schemas
        action: ActionArg,
        slotId: SlotIdArg = None,
        customer: CustomerArg = None,
        reasonVerbatim: ReasonArg = None,
        language: BookLanguage = None,
        requestTimingConfirmation: TimingArg = False,
        customerName: CustomerNameArg = None,
        phone: SpokenPhoneArg = None,
        fromDate: FromArg = None,
        toDate: ToArg = None,
        bookingId: BookingIdArg = None,
        newSlotId: NewSlotIdArg = None,
    ) -> dict[str, Any]:
        context = call_context(settings)
        call_id = context.get("X-Call-Id", "")

        if action == "LIST":
            params = {k: v for k, v in (("customerName", customerName), ("phone", phone),
                                        ("from", fromDate), ("to", toDate)) if v}
            return await client.send("GET", "/agent/bookings", headers=context,
                                     params={k: str(v) for k, v in params.items()}, write=False)

        if action == "BOOK":
            if not slotId:
                return _invalid("slotId", "BOOK needs a slotId from find_availability.")
            if customer is None:
                return _invalid("customer", "BOOK needs the customer's name and phone.")
            if not language:
                return _invalid("language", "BOOK needs the caller's language.")
            body: dict[str, Any] = {
                "slotId": slotId,
                "customer": customer.model_dump(mode="json", exclude_none=True),
                "language": language,
                "requestTimingConfirmation": requestTimingConfirmation,
            }
            if reasonVerbatim:
                body["reasonVerbatim"] = reasonVerbatim
            headers = _keyed(context, call_id, "BOOK", customer.name, slotId)
            return await client.send("POST", "/agent/bookings", headers=headers, json_body=body, write=True)

        if not bookingId:
            return _invalid("bookingId", f"{action} needs an bookingId from LIST or BOOK.")
        if not customerName:
            return _invalid("customerName", f"{action} needs the customer's name.")
        if action == "CANCEL":
            body = {"customerName": customerName}
            if reasonVerbatim:
                body["reasonVerbatim"] = reasonVerbatim
            headers = _keyed(context, call_id, "CANCEL", customerName, bookingId)
            return await client.send("POST", f"/agent/bookings/{bookingId}/cancel", headers=headers,
                                     json_body=body, write=True)

        if not newSlotId:
            return _invalid("newSlotId", "RESCHEDULE needs a newSlotId from find_availability.")
        headers = _keyed(context, call_id, "RESCHEDULE", customerName, f"{bookingId}|{newSlotId}")
        return await client.send("POST", f"/agent/bookings/{bookingId}/reschedule", headers=headers,
                                 json_body={"customerName": customerName, "newSlotId": newSlotId}, write=True)


def _keyed(context: dict[str, str], call_id: str, action: str, name: str | None, target: str) -> dict[str, str]:
    """Without a call id there is no safe key; the API then refuses the write (400)."""
    if not call_id:
        return dict(context)
    return {**context, "Idempotency-Key": idempotency_key(call_id, action, name, target)}
