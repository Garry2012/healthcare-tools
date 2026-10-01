"""Stub of Manoj's operational API for development and tests.

It replays the pinned contract's shapes with scriptable state: a controllable clock (so "today" and
staleness are deterministic), client-credential tokens with scopes, per-session board entries,
an appointment register with Idempotency-Key replay, callId-deduplicated call summaries, and
failure scenarios (injected status, malformed body, commit-then-drop-the-response, latency).
It implements no scheduling rules beyond the contract's documented validation; it is not a backend.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from frontdesk_mcp.clock import Clock, SystemClock

DATA = Path(__file__).parent / "data/demo_hospital.json"
MOBILE = re.compile(r"^[0-9]{10}$")
APPROX_TIME = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
STALE_AFTER = timedelta(hours=4)  # the contract's default tenant threshold
INTENTS = {"AVAILABILITY", "BOOKING", "RESCHEDULE", "CANCEL", "GENERAL_INFO", "LAB", "INSURANCE", "EMERGENCY",
           "AMBULANCE", "SYMPTOM_ROUTING", "COMPLAINT", "ADMIN", "OTHER"}
OUTCOMES = {"RESOLVED_BY_AGENT", "APPOINTMENT_NOTED", "APPOINTMENT_CANCELLED", "APPOINTMENT_RESCHEDULED",
            "TRANSFERRED", "EMERGENCY_TRANSFERRED", "AMBULANCE_NUMBER_GIVEN", "CALLBACK_NOTED", "ABANDONED"}


def load_data() -> dict[str, Any]:
    return json.loads(DATA.read_text(encoding="utf-8"))


@dataclass
class OpsStubState:
    clock: Clock = field(default_factory=SystemClock)
    zone: str = "Asia/Kolkata"
    clients: dict[str, tuple[str, set[str]]] = field(
        default_factory=lambda: {"mcp-dev": ("dev-secret", {"appointments.write", "calls.write"})})
    data: dict[str, Any] = field(default_factory=load_data)
    appointments: dict[str, dict[str, Any]] = field(default_factory=dict)
    summaries: dict[str, dict[str, Any]] = field(default_factory=dict)
    idempotency: dict[str, tuple[str, int, dict[str, Any]]] = field(default_factory=dict)
    boards: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # ISO date → scripted entries
    # scenarios
    fail_next: list[tuple[str, int, dict[str, str]]] = field(default_factory=list)  # (path prefix, status, headers)
    malformed_next: list[str] = field(default_factory=list)  # path prefixes answering {"unexpected": true}
    commit_then: dict[str, int] = field(default_factory=dict)  # path prefix → status returned AFTER committing
    delay_seconds: float = 0.0
    counter: int = 0

    def today(self) -> date:
        return self.clock.now().astimezone(ZoneInfo(self.zone)).date()

    def set_board(self, iso_date: str, entries: list[dict[str, Any]]) -> None:
        self.boards[iso_date] = entries

    def next_id(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}_{self.counter:04d}"

    def token_for(self, client_id: str) -> str:
        return "stub-" + base64.urlsafe_b64encode(client_id.encode()).decode().rstrip("=")

    def client_of(self, token: str) -> str | None:
        if not token.startswith("stub-"):
            return None
        raw = token[len("stub-"):]
        try:
            client_id = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode()
        except ValueError:
            return None
        return client_id if client_id in self.clients else None

    def reset(self) -> None:
        self.appointments.clear(), self.summaries.clear(), self.idempotency.clear(), self.boards.clear()
        self.fail_next.clear(), self.malformed_next.clear(), self.commit_then.clear()
        self.delay_seconds = 0.0


def error(status: int, code: str, message: str, details: list[dict[str, str]] | None = None,
          headers: dict[str, str] | None = None) -> JSONResponse:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return JSONResponse(body, status_code=status, headers=headers)


def create_app(state: OpsStubState) -> Starlette:
    def authenticated(request: Request) -> tuple[str | None, Response | None]:
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer "):
            return None, error(401, "UNAUTHORIZED", "Invalid token")
        client = state.client_of(header.removeprefix("Bearer "))
        if client is None:
            return None, error(401, "UNAUTHORIZED", "Invalid token")
        return client, None

    def scoped(client: str, scope: str) -> Response | None:
        if scope not in state.clients[client][1]:
            return error(403, "FORBIDDEN", f"Scope {scope} is required")
        return None

    async def scenario(request: Request) -> Response | None:
        if state.delay_seconds:
            await asyncio.sleep(state.delay_seconds)
        for i, (prefix, status, headers) in enumerate(state.fail_next):
            if request.url.path.startswith(prefix):
                del state.fail_next[i]
                return error(status, "INTERNAL", "injected failure", headers=headers)
        return None

    def malformed(request: Request) -> Response | None:
        for i, prefix in enumerate(state.malformed_next):
            if request.url.path.startswith(prefix):
                del state.malformed_next[i]
                return JSONResponse({"unexpected": True})
        return None

    async def issue_token(request: Request) -> Response:
        form = await request.form()
        if form.get("grant_type") != "client_credentials":
            return error(400, "VALIDATION_FAILED", "grant_type must be client_credentials")
        client_id, secret = str(form.get("client_id", "")), str(form.get("client_secret", ""))
        basic = request.headers.get("authorization", "")
        if basic.startswith("Basic "):
            try:
                client_id, _, secret = base64.b64decode(basic[6:]).decode().partition(":")
            except ValueError:
                return error(401, "UNAUTHORIZED", "Invalid client")
        known = state.clients.get(client_id)
        if known is None or known[0] != secret:
            return error(401, "UNAUTHORIZED", "Invalid client")  # unknown id, wrong secret: same 401
        return JSONResponse({"access_token": state.token_for(client_id), "token_type": "Bearer", "expires_in": 3600})

    async def departments(request: Request) -> Response:
        _, denied = authenticated(request)
        if denied:
            return denied
        if blocked := await scenario(request) or malformed(request):
            return blocked
        return JSONResponse({"items": state.data["departments"]})

    def summary_of(doctor: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in doctor.items() if k not in ("usualSchedule", "patientsPerHour", "dataConfirmed")}

    async def search_doctors(request: Request) -> Response:
        _, denied = authenticated(request)
        if denied:
            return denied
        if blocked := await scenario(request) or malformed(request):
            return blocked
        q = request.query_params
        try:
            limit, offset = int(q.get("limit", 25)), int(q.get("offset", 0))
        except ValueError:
            return error(400, "VALIDATION_FAILED", "limit/offset must be integers")
        if not 1 <= limit <= 100 or offset < 0:
            return error(400, "VALIDATION_FAILED", "limit must be 1..100 and offset >= 0")
        if q.get("gender") not in (None, "FEMALE", "MALE"):
            return error(400, "VALIDATION_FAILED", "gender must be FEMALE or MALE")
        rows = [d for d in state.data["doctors"] if d["active"]]
        if query := q.get("query", "").strip().casefold():
            rows = [d for d in rows if query in d["name"].casefold()]
        if department := q.get("department"):
            rows = [d for d in rows if any(ref["id"] == department for ref in d["departments"])]
        if gender := q.get("gender"):
            rows = [d for d in rows if d.get("gender") == gender]
        return JSONResponse({"items": [summary_of(d) for d in rows[offset:offset + limit]], "total": len(rows)})

    async def get_doctor(request: Request) -> Response:
        _, denied = authenticated(request)
        if denied:
            return denied
        if blocked := await scenario(request) or malformed(request):
            return blocked
        doctor = next((d for d in state.data["doctors"] if d["id"] == request.path_params["doctor_id"]), None)
        if doctor is None:
            return error(404, "NOT_FOUND", "No such doctor")
        return JSONResponse(doctor)

    def entries_for(iso: str) -> list[dict[str, Any]]:
        if iso in state.boards:
            return state.boards[iso]
        return state.data["board_today"] if iso == state.today().isoformat() else []

    def board_entry(raw: dict[str, Any], iso: str, now: datetime) -> dict[str, Any]:
        doctor = next(d for d in state.data["doctors"] if d["id"] == raw["doctorId"])
        updated = now - timedelta(minutes=raw.get("updatedMinutesAgo", 0))
        stale = now - updated > STALE_AFTER
        entry: dict[str, Any] = {"doctorId": doctor["id"], "doctorName": doctor["name"], "date": iso,
                                 "status": "UNKNOWN" if stale else raw["status"], "isStale": stale,
                                 "lastUpdatedAt": updated.isoformat(timespec="seconds")}
        if raw.get("session"):
            entry["session"] = raw["session"]
        if not stale:
            for key in ("delayMinutes", "expectedTime", "expectedEndTime", "note"):
                if raw.get(key) is not None:
                    entry[key] = raw[key]
        for key in ("updatedBy", "source"):
            if raw.get(key):
                entry[key] = raw[key]
        return entry

    def unknown_entry(doctor: dict[str, Any], iso: str) -> dict[str, Any]:
        return {"doctorId": doctor["id"], "doctorName": doctor["name"], "date": iso, "status": "UNKNOWN",
                "isStale": True}

    async def availability(request: Request) -> Response:
        _, denied = authenticated(request)
        if denied:
            return denied
        if blocked := await scenario(request) or malformed(request):
            return blocked
        q = request.query_params
        doctor_id, department = q.get("doctorId"), q.get("department")
        if bool(doctor_id) == bool(department):
            return error(400, "VALIDATION_FAILED", "Exactly one of doctorId or department must be given")
        requested = q.get("date", "today")
        if requested == "today":
            iso = state.today().isoformat()
        else:
            try:
                iso = date.fromisoformat(requested).isoformat()
            except ValueError:
                return error(400, "VALIDATION_FAILED", "date must be ISO or 'today'",
                             [{"field": "date", "issue": "format"}])
        now = state.clock.now().astimezone(ZoneInfo(state.zone))
        if doctor_id:
            doctors = [d for d in state.data["doctors"] if d["id"] == doctor_id]
        else:
            doctors = [d for d in state.data["doctors"] if any(r["id"] == department for r in d["departments"])]
        items: list[dict[str, Any]] = []
        for doctor in doctors:
            rows = [r for r in entries_for(iso) if r["doctorId"] == doctor["id"]]
            items.extend(board_entry(r, iso, now) for r in rows) if rows else items.append(unknown_entry(doctor, iso))
        return JSONResponse({"date": iso, "items": items})

    def body_hash(body: Any) -> str:
        return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    async def write(request: Request, scope: str, handler) -> Response:
        """Common POST discipline: auth, scope, scenario, JSON body, Idempotency-Key replay, commit-then-fail."""
        client, denied = authenticated(request)
        if denied:
            return denied
        if forbidden := scoped(client, scope):
            return forbidden
        if blocked := await scenario(request):
            return blocked
        try:
            body = await request.json()
        except ValueError:
            return error(400, "VALIDATION_FAILED", "body must be JSON")
        key = request.headers.get("idempotency-key")
        if key and key in state.idempotency:
            stored_hash, status, stored = state.idempotency[key]
            if stored_hash != body_hash(body):
                return error(409, "IDEMPOTENCY_CONFLICT", "Same key, different body")
            return JSONResponse(stored, status_code=status)
        status, payload = handler(body)
        if status < 300 and key:
            state.idempotency[key] = (body_hash(body), status, payload)
        if status < 300:
            for prefix, failure in list(state.commit_then.items()):
                if request.url.path.startswith(prefix):
                    del state.commit_then[prefix]
                    return Response(status_code=failure)  # committed, response lost
        if malformed(request) and status < 300:
            return JSONResponse({"unexpected": True}, status_code=status)
        return JSONResponse(payload, status_code=status)

    def validate_create(body: dict[str, Any]) -> list[dict[str, str]]:
        issues = []
        for field_name in ("patientName", "mobile", "visitDate"):
            if not body.get(field_name):
                issues.append({"field": field_name, "issue": "required"})
        if "mobile" in body and not MOBILE.fullmatch(str(body["mobile"])):
            issues.append({"field": "mobile", "issue": "must be a 10-digit number"})
        if bool(body.get("doctorId")) == bool(body.get("department")):
            issues.append({"field": "doctorId", "issue": "exactly one of doctorId or department"})
        if body.get("expectedTime") and not APPROX_TIME.fullmatch(str(body["expectedTime"])):
            issues.append({"field": "expectedTime", "issue": "HH:MM"})
        try:
            date.fromisoformat(str(body.get("visitDate", "")))
        except ValueError:
            issues.append({"field": "visitDate", "issue": "ISO date"})
        if body.get("doctorId") and not any(d["id"] == body["doctorId"] for d in state.data["doctors"]):
            issues.append({"field": "doctorId", "issue": "unknown doctor"})
        if body.get("department") and not any(d["id"] == body["department"] for d in state.data["departments"]):
            issues.append({"field": "department", "issue": "unknown department"})
        return issues

    def create_appointment(body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if issues := validate_create(body):
            return 400, {"error": {"code": "VALIDATION_FAILED", "message": "invalid appointment", "details": issues}}
        now = state.clock.now().isoformat(timespec="seconds")
        appointment = {
            "id": state.next_id("appt"), "patientName": body["patientName"], "mobile": body["mobile"],
            "visitDate": body["visitDate"], "status": "NOTED", "createdAt": now, "updatedAt": now,
            "createdBy": {"type": "AGENT", "id": "mcp"},
        }
        for key in ("doctorId", "department", "expectedTime", "reasonVerbatim", "callId"):
            if body.get(key):
                appointment[key] = body[key]
        state.appointments[appointment["id"]] = appointment
        return 201, appointment

    def verified(appointment_id: str, body: dict[str, Any]) -> tuple[dict[str, Any] | None, tuple[int, dict] | None]:
        mobile = body.get("callerMobile")
        if not mobile or not MOBILE.fullmatch(str(mobile)):
            return None, (400, {"error": {"code": "VALIDATION_FAILED", "message": "callerMobile required",
                                          "details": [{"field": "callerMobile", "issue": "10 digits"}]}})
        appointment = state.appointments.get(appointment_id)
        if appointment is None or appointment["mobile"] != mobile:
            return None, (404, {"error": {"code": "NOT_FOUND", "message": "No matching appointment was found"}})
        return appointment, None

    def cancel(appointment_id: str):
        def handler(body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
            appointment, failure = verified(appointment_id, body)
            if failure:
                return failure
            if appointment["status"] == "CANCELLED":
                return 409, {"error": {"code": "CONFLICT", "message": "Request is already cancelled"}}
            appointment["status"] = "CANCELLED"
            appointment["updatedAt"] = state.clock.now().isoformat(timespec="seconds")
            return 200, appointment
        return handler

    def reschedule(appointment_id: str):
        def handler(body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
            appointment, failure = verified(appointment_id, body)
            if failure:
                return failure
            try:
                new_date = date.fromisoformat(str(body.get("newVisitDate", ""))).isoformat()
            except ValueError:
                return 400, {"error": {"code": "VALIDATION_FAILED", "message": "newVisitDate required",
                                       "details": [{"field": "newVisitDate", "issue": "ISO date"}]}}
            if body.get("newExpectedTime") and not APPROX_TIME.fullmatch(str(body["newExpectedTime"])):
                return 400, {"error": {"code": "VALIDATION_FAILED", "message": "newExpectedTime HH:MM"}}
            if appointment["status"] == "CANCELLED":
                return 409, {"error": {"code": "CONFLICT", "message": "Request is cancelled"}}
            appointment["visitDate"] = new_date
            if body.get("newExpectedTime"):
                appointment["expectedTime"] = body["newExpectedTime"]
            else:
                appointment.pop("expectedTime", None)
            appointment["status"] = "CHANGED"
            appointment["updatedAt"] = state.clock.now().isoformat(timespec="seconds")
            return 200, appointment
        return handler

    async def post_appointment(request: Request) -> Response:
        return await write(request, "appointments.write", create_appointment)

    async def post_cancel(request: Request) -> Response:
        return await write(request, "appointments.write", cancel(request.path_params["appointment_id"]))

    async def post_reschedule(request: Request) -> Response:
        return await write(request, "appointments.write", reschedule(request.path_params["appointment_id"]))

    async def find_appointments(request: Request) -> Response:
        _, denied = authenticated(request)
        if denied:
            return denied
        if blocked := await scenario(request) or malformed(request):
            return blocked
        q = request.query_params
        mobile = q.get("mobile", "")
        if not MOBILE.fullmatch(mobile):
            return error(400, "VALIDATION_FAILED", "mobile must be a 10-digit number",
                         [{"field": "mobile", "issue": "10 digits"}])
        start = q.get("from") or state.today().isoformat()
        end = q.get("to")
        status = q.get("status")
        rows = [a for a in state.appointments.values() if a["mobile"] == mobile and a["visitDate"] >= start
                and (not end or a["visitDate"] <= end) and (not status or a["status"] == status)]
        return JSONResponse({"items": rows})

    def create_summary(body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        required = ("callId", "startedAt", "intent", "outcome")
        issues = [{"field": f, "issue": "required"} for f in required if not body.get(f)]
        if body.get("intent") not in INTENTS:
            issues.append({"field": "intent", "issue": "enum"})
        if body.get("outcome") not in OUTCOMES:
            issues.append({"field": "outcome", "issue": "enum"})
        if len(str(body.get("summaryText", ""))) > 500:
            issues.append({"field": "summaryText", "issue": "maxLength 500"})
        if body.get("callerMobile") and not MOBILE.fullmatch(str(body["callerMobile"])):
            issues.append({"field": "callerMobile", "issue": "10 digits"})
        if body.get("language") not in (None, "EN", "KN", "HI"):
            issues.append({"field": "language", "issue": "enum"})
        if issues:
            return 400, {"error": {"code": "VALIDATION_FAILED", "message": "invalid summary", "details": issues}}
        if body["callId"] in state.summaries:
            return 200, state.summaries[body["callId"]]  # exists: returned unchanged
        stored = {**body, "id": state.next_id("cs"), "createdAt": state.clock.now().isoformat(timespec="seconds")}
        state.summaries[body["callId"]] = stored
        return 201, stored

    async def post_summary(request: Request) -> Response:
        return await write(request, "calls.write", create_summary)

    # --- scenario control over HTTP (for processes started by e2e tests and local demos) ---------
    async def stub_reset(_: Request) -> Response:
        state.reset()
        return JSONResponse({"ok": True})

    async def stub_scenario(request: Request) -> Response:
        body = await request.json()
        for item in body.get("failNext", []):
            state.fail_next.append((item["path"], int(item["status"]), dict(item.get("headers", {}))))
        state.malformed_next.extend(body.get("malformedNext", []))
        state.commit_then.update({k: int(v) for k, v in body.get("commitThen", {}).items()})
        if "delaySeconds" in body:
            state.delay_seconds = float(body["delaySeconds"])
        for iso, entries in body.get("boards", {}).items():
            state.set_board(iso, entries)
        return JSONResponse({"ok": True})

    async def stub_state(_: Request) -> Response:
        return JSONResponse({"appointments": list(state.appointments.values()),
                             "summaries": list(state.summaries.values()), "today": state.today().isoformat()})

    return Starlette(routes=[
        Route("/auth/token", issue_token, methods=["POST"]),
        Route("/departments", departments),
        Route("/doctors", search_doctors),
        Route("/doctors/{doctor_id}", get_doctor),
        Route("/availability", availability),
        Route("/appointments", post_appointment, methods=["POST"]),
        Route("/appointments", find_appointments, methods=["GET"]),
        Route("/appointments/{appointment_id}/cancel", post_cancel, methods=["POST"]),
        Route("/appointments/{appointment_id}/reschedule", post_reschedule, methods=["POST"]),
        Route("/call-summaries", post_summary, methods=["POST"]),
        Route("/__stub/reset", stub_reset, methods=["POST"]),
        Route("/__stub/scenario", stub_scenario, methods=["POST"]),
        Route("/__stub/state", stub_state),
    ])
