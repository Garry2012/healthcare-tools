"""HTTP adapter for Manoj's operational API (the pinned contract). Only transport concerns live here:
machine OAuth with a warm, single-flight token cache; one deadline per invocation that caps every
exchange; response validation against the contract types; and honest failure classes. No scheduling
rule, no local fallback, no persistence."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from collections.abc import Callable
from typing import Any, Literal

import httpx
from pydantic import ValidationError

from . import contract
from .clock import Deadline, DeadlineExceeded
from .config import Settings

logger = logging.getLogger(__name__)

_ID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
UnavailableReason = Literal["TRANSPORT", "TIMEOUT", "UPSTREAM", "AUTH", "DEADLINE"]


class UpstreamError(Exception):
    """Base class: never carries caller data or upstream prose into the model's view."""


class Unavailable(UpstreamError):
    """The service could not be used (down, slow, rate-limited, our credentials refused, budget spent)."""

    def __init__(self, reason: UnavailableReason, retry_after: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retry_after = retry_after


class Rejected(UpstreamError):
    """A definite 4xx from the owner. `code` is the contract error code when the body had one."""

    def __init__(self, status: int, code: contract.ErrorCode | None, fields: tuple[str, ...] = ()) -> None:
        super().__init__(f"{status} {code or 'NO_CONTRACT_BODY'}")
        self.status = status
        self.code = code
        self.fields = fields


class Malformed(UpstreamError):
    """A 2xx whose body does not satisfy the contract: not a success."""


class UncertainWrite(UpstreamError):
    """A mutation was sent but no verified response came back: neither success nor failure."""


class InvalidIdentifier(ValueError):
    """A path identifier that is not an id this API ever returned."""


def _path_id(value: str) -> str:
    if not _ID.fullmatch(value or ""):
        raise InvalidIdentifier("identifier must be one returned by the API")
    return value


def _retry_after(response: httpx.Response) -> int | None:
    try:
        return max(0, int(response.headers["retry-after"]))
    except (KeyError, ValueError):
        return None


def _rejection(response: httpx.Response) -> Rejected:
    try:
        error = contract.ErrorBody.model_validate(response.json()).error
    except (ValueError, ValidationError):
        return Rejected(response.status_code, None)
    return Rejected(response.status_code, error.code, tuple(d.field for d in error.details if d.field))


# A same-key retry runs only when the remaining budget can plausibly fit it: at least MIN_RETRY_FLOOR and at
# least RETRY_HEADROOM × the time the first attempt took (an instant failure such as a stale keep-alive gets its
# retry; a slow one does not burn the rest of the turn).
MIN_RETRY_FLOOR_SECONDS = 0.05
RETRY_HEADROOM = 1.5
# Timeouts/errors that happen before the request body could have reached the server.
_NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout, httpx.UnsupportedProtocol, httpx.ProxyError)


class TokenCache:
    """One machine token per (service, client); warmed at start-up, refreshed before expiry by a background
    refresher and, failing that, by the first caller that needs it; one refresh in flight at a time."""

    def __init__(self, settings: Settings, http: httpx.AsyncClient, monotonic: Callable[[], float]) -> None:
        self._settings = settings
        self._http = http
        self._monotonic = monotonic
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    def _fresh(self) -> bool:
        margin = self._settings.token_refresh_margin_seconds
        return self._token is not None and self._monotonic() < self._expires_at - margin

    @property
    def usable(self) -> bool:
        """A token that has not expired yet, even if inside the refresh margin."""
        return self._token is not None and self._monotonic() < self._expires_at

    def invalidate(self) -> None:
        self._token = None

    async def get(self, deadline: Deadline) -> str:
        if self._fresh():
            return self._token  # type: ignore[return-value]
        if self.usable and self._lock.locked():
            return self._token  # type: ignore[return-value]  # a refresh is in flight; the current token still works
        try:
            async with asyncio.timeout(deadline.timeout(self._settings.request_timeout_seconds)):
                await self._lock.acquire()  # single flight: concurrent cold callers wait for one exchange
        except TimeoutError as exc:
            raise Unavailable("DEADLINE") from exc
        except DeadlineExceeded as exc:
            raise Unavailable("DEADLINE") from exc
        try:
            if self._fresh():
                return self._token  # type: ignore[return-value]
            if self.usable and deadline.remaining() < self._settings.request_timeout_seconds:
                return self._token  # type: ignore[return-value]  # no time to refresh: the current token still works
            return await self._refresh(deadline)
        finally:
            self._lock.release()

    async def refresh_if_due(self) -> None:
        """Background cadence: renew inside the margin so no caller pays for the exchange. Failures are logged."""
        if self._fresh():
            return
        if self._lock.locked():
            return
        async with self._lock:
            if self._fresh():
                return
            try:
                budget = self._settings.token_refresh_timeout_seconds  # background work: not the in-call cap
                await self._refresh(Deadline(budget, self._monotonic, cap=budget))
            except Unavailable as exc:
                logger.warning("ops_token_refresh_deferred", extra={"fields": {"reason": exc.reason}})

    async def _refresh(self, deadline: Deadline) -> str:
        settings = self._settings
        try:
            budget = deadline.timeout(settings.request_timeout_seconds)
            async with asyncio.timeout(budget):
                response = await self._http.post(
                    settings.ops_token_url,
                    data={"grant_type": "client_credentials"},
                    auth=(settings.ops_client_id, settings.ops_client_secret.get_secret_value()),
                    timeout=budget,
                )
        except DeadlineExceeded as exc:
            raise Unavailable("DEADLINE") from exc
        except (httpx.TimeoutException, TimeoutError) as exc:
            logger.warning("ops_token_timeout")
            raise Unavailable("TIMEOUT") from exc
        except httpx.RequestError as exc:
            logger.warning("ops_token_unreachable", extra={"fields": {"error": type(exc).__name__}})
            raise Unavailable("TRANSPORT") from exc
        if response.status_code in (400, 401):
            logger.error("ops_rejected_adapter_credentials", extra={"fields": {"status": response.status_code}})
            raise Unavailable("AUTH")
        if response.status_code != 200:
            logger.warning("ops_token_failed", extra={"fields": {"status": response.status_code}})
            raise Unavailable("UPSTREAM", _retry_after(response))
        try:
            token = contract.TokenResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            logger.error("ops_token_malformed")
            raise Unavailable("UPSTREAM") from exc
        self._token = token.access_token
        self._expires_at = self._monotonic() + token.expires_in
        return self._token


class OpsClient:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self.http = httpx.AsyncClient(
            base_url=settings.ops_base_url,
            transport=transport,
            limits=httpx.Limits(max_connections=settings.ops_pool_max_connections,
                                max_keepalive_connections=settings.ops_pool_max_connections),
        )
        self.tokens = TokenCache(settings, self.http, monotonic)
        self._refresher: asyncio.Task[None] | None = None

    async def __aenter__(self) -> OpsClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def start(self) -> None:
        """Warm the token before the first caller and keep it warm; a failure here is logged, not fatal."""
        await self.tokens.refresh_if_due()
        if self._refresher is None:
            self._refresher = asyncio.create_task(self._keep_warm(), name="ops-token-refresher")

    async def refresh_if_due(self) -> None:
        await self.tokens.refresh_if_due()

    async def _keep_warm(self) -> None:
        while True:
            await asyncio.sleep(self.settings.token_refresh_check_seconds)
            await self.tokens.refresh_if_due()

    async def aclose(self) -> None:
        if self._refresher is not None:
            self._refresher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._refresher
            self._refresher = None
        await self.http.aclose()

    # ------------------------------------------------------------------ transport core

    async def _exchange(self, method: str, path: str, deadline: Deadline, *, params=None, json_body=None,
                        headers: dict[str, str] | None = None, token: str) -> httpx.Response:
        """One HTTP exchange under a wall-clock cap. httpx's timeout is per phase (and per read chunk), so a
        server that keeps dribbling bytes would never trip it; asyncio.timeout makes the cap total."""
        budget = deadline.timeout(self.settings.request_timeout_seconds)
        try:
            async with asyncio.timeout(budget):
                return await self.http.request(
                    method, path, params=params, json=json_body,
                    headers={**(headers or {}), "Authorization": f"Bearer {token}"},
                    timeout=budget,
                )
        except TimeoutError as exc:
            raise httpx.ReadTimeout("exchange exceeded the invocation deadline") from exc

    async def _read(self, path: str, deadline: Deadline, params: dict[str, Any] | None = None) -> Any:
        """GET; one refresh-and-retry on a 401; otherwise never retried (the caller's budget is the turn)."""
        try:
            token = await self.tokens.get(deadline)
            response = await self._exchange("GET", path, deadline, params=params, token=token)
            if response.status_code == 401:
                self.tokens.invalidate()
                token = await self.tokens.get(deadline)
                response = await self._exchange("GET", path, deadline, params=params, token=token)
        except DeadlineExceeded as exc:
            raise Unavailable("DEADLINE") from exc
        except httpx.TimeoutException as exc:
            logger.warning("ops_timeout", extra={"fields": {"path": path}})
            raise Unavailable("TIMEOUT") from exc
        except httpx.RequestError as exc:
            logger.warning("ops_unreachable", extra={"fields": {"path": path, "error": type(exc).__name__}})
            raise Unavailable("TRANSPORT") from exc
        return self._body(response, path)

    async def _write(self, path: str, body: dict[str, Any], key: str, deadline: Deadline) -> tuple[int, Any]:
        """POST with a frozen body and Idempotency-Key. At most one same-key retry: a request that never
        left (connect failure) may be resent; a request that may have been committed is resent only because
        the contract replays the same key, and if that also fails the result is uncertain, not a failure."""
        headers = {"Idempotency-Key": key}
        sent = False  # once an attempt may have reached the owner, no later failure is definite
        for attempt in (1, 2):
            started = deadline.remaining()
            try:
                token = await self.tokens.get(deadline)
                response = await self._exchange("POST", path, deadline, json_body=body, headers=headers, token=token)
                if response.status_code == 401 and attempt == 1 and not sent:
                    self.tokens.invalidate()
                    token = await self.tokens.get(deadline)
                    response = await self._exchange("POST", path, deadline, json_body=body, headers=headers,
                                                    token=token)
            except (DeadlineExceeded, Unavailable) as exc:  # budget spent, or the token could not be obtained
                if sent:
                    raise UncertainWrite from exc
                if isinstance(exc, Unavailable):
                    raise
                raise Unavailable("DEADLINE") from exc
            except _NOT_SENT as exc:
                logger.warning("ops_unreachable", extra={"fields": {"path": path, "attempt": attempt}})
                if sent:
                    raise UncertainWrite from exc
                if attempt == 2 or not self._can_retry(deadline, started):
                    raise Unavailable("TRANSPORT") from exc
                continue
            except httpx.RequestError as exc:  # timeouts, read/decoding errors: the request left
                sent = True
                logger.warning("ops_write_unanswered", extra={"fields": {"path": path, "attempt": attempt}})
                if attempt == 2 or not self._can_retry(deadline, started):
                    raise UncertainWrite from exc
                continue
            if response.status_code in (502, 504):
                raise UncertainWrite  # an intermediary answered; the owner may have committed
            if sent and response.status_code >= 400:
                # The retry was refused or failed, but attempt 1 may already have committed.
                logger.warning("ops_write_retry_inconclusive", extra={"fields": {"path": path,
                                                                                 "status": response.status_code}})
                raise UncertainWrite
            if response.status_code >= 500:
                # The owner answered with a server error after receiving the write: nothing in the contract says
                # it did not commit first. Uncertain, never a definite failure.
                logger.warning("ops_write_server_error",
                               extra={"fields": {"path": path, "status": response.status_code}})
                raise UncertainWrite
            return response.status_code, self._body(response, path)
        raise UncertainWrite  # unreachable: the loop always returns or raises

    @staticmethod
    def _can_retry(deadline: Deadline, remaining_at_start: float) -> bool:
        elapsed = max(0.0, remaining_at_start - deadline.remaining())
        return deadline.remaining() >= max(MIN_RETRY_FLOOR_SECONDS, RETRY_HEADROOM * elapsed)

    def _body(self, response: httpx.Response, path: str) -> Any:
        status = response.status_code
        if status in (401, 403):
            logger.error("ops_rejected_adapter_credentials", extra={"fields": {"path": path, "status": status}})
            raise Unavailable("AUTH")
        if status == 429 or status >= 500:
            logger.warning("ops_upstream_error", extra={"fields": {"path": path, "status": status}})
            raise Unavailable("UPSTREAM", _retry_after(response))
        if status >= 400:
            raise _rejection(response)
        try:
            return response.json()
        except ValueError as exc:
            logger.error("ops_malformed_success", extra={"fields": {"path": path}})
            raise Malformed from exc

    @staticmethod
    def _parse(model: type[contract._Model], data: Any, path: str) -> Any:
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            logger.error("ops_malformed_success", extra={"fields": {"path": path, "model": model.__name__}})
            raise Malformed from exc

    # ------------------------------------------------------------------ contract operations

    async def list_departments(self, deadline: Deadline) -> contract.DepartmentList:
        return self._parse(contract.DepartmentList, await self._read("/departments", deadline), "/departments")

    async def search_doctors(self, deadline: Deadline, *, query: str | None = None, department: str | None = None,
                             gender: str | None = None, limit: int = 25, offset: int = 0) -> contract.DoctorPage:
        params: dict[str, Any] = {}
        if query:
            params["query"] = query[:100]
        if department:
            params["department"] = department
        if gender:
            params["gender"] = gender
        params.update(limit=limit, offset=offset)
        return self._parse(contract.DoctorPage, await self._read("/doctors", deadline, params), "/doctors")

    async def get_doctor(self, doctor_id: str, deadline: Deadline) -> contract.DoctorDetail:
        path = f"/doctors/{_path_id(doctor_id)}"
        return self._parse(contract.DoctorDetail, await self._read(path, deadline), "/doctors/{id}")

    async def get_availability(self, deadline: Deadline, *, date: str, doctor_id: str | None = None,
                               department: str | None = None) -> contract.AvailabilityBoard:
        if bool(doctor_id) == bool(department):
            raise ValueError("exactly one of doctor_id or department")
        params: dict[str, Any] = {"date": date}
        if doctor_id:
            params["doctorId"] = doctor_id
        else:
            params["department"] = department
        return self._parse(contract.AvailabilityBoard, await self._read("/availability", deadline, params),
                           "/availability")

    async def find_appointments(self, deadline: Deadline, *, mobile: str, from_date: str | None = None,
                                to_date: str | None = None, status: str | None = None) -> contract.AppointmentList:
        params: dict[str, Any] = {"mobile": mobile}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        if status:
            params["status"] = status
        return self._parse(contract.AppointmentList, await self._read("/appointments", deadline, params),
                           "/appointments")

    async def create_appointment(self, body: dict[str, Any], key: str, deadline: Deadline
                                 ) -> tuple[int, contract.Appointment]:
        status, data = await self._write("/appointments", body, key, deadline)
        return status, self._parse(contract.Appointment, data, "/appointments")

    async def cancel_appointment(self, appointment_id: str, body: dict[str, Any], key: str, deadline: Deadline
                                 ) -> tuple[int, contract.Appointment]:
        path = f"/appointments/{_path_id(appointment_id)}/cancel"
        status, data = await self._write(path, body, key, deadline)
        return status, self._parse(contract.Appointment, data, "/appointments/{id}/cancel")

    async def reschedule_appointment(self, appointment_id: str, body: dict[str, Any], key: str, deadline: Deadline
                                     ) -> tuple[int, contract.Appointment]:
        path = f"/appointments/{_path_id(appointment_id)}/reschedule"
        status, data = await self._write(path, body, key, deadline)
        return status, self._parse(contract.Appointment, data, "/appointments/{id}/reschedule")

    async def create_call_summary(self, body: dict[str, Any], key: str, deadline: Deadline
                                  ) -> tuple[int, contract.CallSummary]:
        status, data = await self._write("/call-summaries", body, key, deadline)
        return status, self._parse(contract.CallSummary, data, "/call-summaries")
