"""Transport to Manoj's operational API: machine OAuth with a warm, single-flight token cache; one
deadline across auth and calls; honest error classes (unavailable, rejected, malformed, uncertain)
and at most one same-key retry of a write when the contract's replay makes it safe."""

from __future__ import annotations

import asyncio
import json
import logging
from base64 import b64decode

import httpx
import pytest

from frontdesk_mcp import ops_client
from frontdesk_mcp.clock import Deadline

TOKEN = {"access_token": "tok-1", "token_type": "Bearer", "expires_in": 3600}
DOCTOR = {"id": "doc_1", "name": "Dr Garima", "departments": [{"id": "dept_gen", "name": "General Medicine"}],
          "attendanceType": "REGULAR", "active": True, "usualSchedule": [], "dataConfirmed": True}
APPT = {"id": "appt_1", "patientName": "Lakshmi Rao", "mobile": "9000000101", "doctorId": "doc_1",
        "visitDate": "2026-10-03", "status": "NOTED", "createdAt": "2026-10-01T10:00:00+05:30",
        "createdBy": {"type": "AGENT"}}


class Upstream:
    """Scriptable owner service at the transport boundary; records every request."""

    def __init__(self, token_responses=None, responses=None):
        self.requests: list[httpx.Request] = []
        self.token_responses = list(token_responses or [TOKEN])
        self.responses = list(responses or [])

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/auth/token"):
            nxt = self.token_responses.pop(0) if len(self.token_responses) > 1 else self.token_responses[0]
            return httpx.Response(200, json=nxt) if isinstance(nxt, dict) else nxt
        nxt = self.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    def api_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if not r.url.path.endswith("/auth/token")]


def client_for(settings, upstream: Upstream, monotonic=None) -> ops_client.OpsClient:
    extra = {"monotonic": monotonic} if monotonic else {}
    return ops_client.OpsClient(settings, transport=httpx.MockTransport(upstream.handler), **extra)


def dl(seconds=2.0, monotonic=None) -> Deadline:
    return Deadline(seconds, monotonic=monotonic) if monotonic else Deadline(seconds)


async def test_machine_token_is_fetched_once_with_basic_auth_and_reused(make_settings):
    up = Upstream(responses=[httpx.Response(200, json=DOCTOR), httpx.Response(200, json=DOCTOR)])
    async with client_for(make_settings(), up) as client:
        await client.get_doctor("doc_1", dl())
        await client.get_doctor("doc_1", dl())
    token_requests = [r for r in up.requests if r.url.path.endswith("/auth/token")]
    assert len(token_requests) == 1
    t = token_requests[0]
    assert t.method == "POST" and t.url == "http://ops-stub.test/api/v1/auth/token"
    assert t.headers["content-type"].startswith("application/x-www-form-urlencoded")
    assert t.content == b"grant_type=client_credentials"
    assert b64decode(t.headers["authorization"].split()[1]).decode() == "mcp-test:ops-secret"
    assert [r.headers["authorization"] for r in up.api_requests()] == ["Bearer tok-1", "Bearer tok-1"]
    assert up.api_requests()[0].url == "http://ops-stub.test/api/v1/doctors/doc_1"


async def test_token_url_follows_the_configured_base_without_a_prefix(make_settings):
    up = Upstream(responses=[httpx.Response(200, json={"items": []})])
    async with client_for(make_settings(ops_base_url="http://mock.test"), up) as client:
        await client.list_departments(dl())
    assert str(up.requests[0].url) == "http://mock.test/auth/token"
    assert str(up.requests[1].url) == "http://mock.test/departments"


async def test_concurrent_cold_requests_share_a_single_token_fetch(make_settings):
    up = Upstream(responses=[httpx.Response(200, json={"items": []}) for _ in range(10)])
    async with client_for(make_settings(), up) as client:
        await asyncio.gather(*(client.list_departments(dl()) for _ in range(10)))
    assert len([r for r in up.requests if r.url.path.endswith("/auth/token")]) == 1
    assert len(up.api_requests()) == 10


async def test_token_is_refreshed_before_it_expires(make_settings):
    now = [1000.0]
    up = Upstream(token_responses=[{**TOKEN, "expires_in": 120}, {**TOKEN, "access_token": "tok-2"}],
                  responses=[httpx.Response(200, json={"items": []})] * 2)
    async with client_for(make_settings(token_refresh_margin_seconds=60), up, monotonic=lambda: now[0]) as client:
        await client.list_departments(dl(monotonic=lambda: now[0]))
        now[0] += 70  # 50 s left < 60 s margin
        await client.list_departments(dl(monotonic=lambda: now[0]))
    assert [r.headers["authorization"] for r in up.api_requests()] == ["Bearer tok-1", "Bearer tok-2"]


async def test_a_401_refreshes_once_and_retries_the_same_read(make_settings):
    up = Upstream(token_responses=[TOKEN, {**TOKEN, "access_token": "tok-2"}],
                  responses=[httpx.Response(401, json={"error": {"code": "UNAUTHORIZED", "message": "x"}}),
                             httpx.Response(200, json=DOCTOR)])
    async with client_for(make_settings(), up) as client:
        doctor = await client.get_doctor("doc_1", dl())
    assert doctor.name == "Dr Garima"
    assert [r.headers["authorization"] for r in up.api_requests()] == ["Bearer tok-1", "Bearer tok-2"]


async def test_persistent_401_or_403_is_an_operator_problem_never_a_caller_answer(make_settings, caplog):
    up = Upstream(responses=[httpx.Response(401, json={"error": {"code": "UNAUTHORIZED", "message": "bad"}})] * 2)
    async with client_for(make_settings(), up) as client:
        with pytest.raises(ops_client.Unavailable) as exc, caplog.at_level(logging.ERROR):
            await client.get_doctor("doc_1", dl())
    assert exc.value.reason == "AUTH"
    assert any(r.msg == "ops_rejected_adapter_credentials" for r in caplog.records)
    up = Upstream(responses=[httpx.Response(403, json={"error": {"code": "FORBIDDEN", "message": "scope"}})])
    async with client_for(make_settings(), up) as client:
        with pytest.raises(ops_client.Unavailable):
            await client.get_doctor("doc_1", dl())
    assert len(up.api_requests()) == 1  # a scope problem is not retried


async def test_token_endpoint_failure_is_unavailable_and_never_logs_the_secret(make_settings, caplog):
    up = Upstream(token_responses=[httpx.Response(500, text="boom ops-secret")])
    async with client_for(make_settings(), up) as client:
        with pytest.raises(ops_client.Unavailable), caplog.at_level(logging.DEBUG):
            await client.list_departments(dl())
    assert "ops-secret" not in caplog.text and "tok-1" not in caplog.text


async def test_one_deadline_covers_auth_and_the_call(make_settings):
    now = [0.0]
    seen: list[float] = []

    def slow_handler(request: httpx.Request) -> httpx.Response:
        read_timeout = request.extensions["timeout"]["read"]
        seen.append(read_timeout)
        now[0] += 1.5  # each exchange takes 1.5 s of a 2 s budget
        if read_timeout < 1.5:
            raise httpx.ReadTimeout("slow", request=request)
        if request.url.path.endswith("/auth/token"):
            return httpx.Response(200, json=TOKEN)
        return httpx.Response(200, json={"items": []})

    client = ops_client.OpsClient(make_settings(allow_budget_overrides=True, request_timeout_seconds=1.5),
                                  transport=httpx.MockTransport(slow_handler), monotonic=lambda: now[0])
    async with client:
        with pytest.raises(ops_client.Unavailable) as exc:
            await client.list_departments(Deadline(2.0, monotonic=lambda: now[0]))
    assert exc.value.reason == "TIMEOUT"
    assert seen == [pytest.approx(1.5), pytest.approx(0.5)]  # the call got only what the token left


async def test_an_expired_deadline_sends_nothing(make_settings):
    up = Upstream()
    async with client_for(make_settings(), up) as client:
        with pytest.raises(ops_client.Unavailable):
            await client.list_departments(Deadline(-1))
    assert up.requests == []


@pytest.mark.parametrize("response,reason,retry_after", [
    (httpx.ConnectError("refused"), "TRANSPORT", None),
    (httpx.ReadTimeout("slow"), "TIMEOUT", None),
    (httpx.Response(503, headers={"Retry-After": "7"}, json={"error": {"code": "INTERNAL", "message": "x"}}),
     "UPSTREAM", 7),
    (httpx.Response(429, json={"error": {"code": "RATE_LIMITED", "message": "x"}}), "UPSTREAM", None),
    (httpx.Response(500, text="<html>"), "UPSTREAM", None),
])
async def test_read_failures_are_unavailable_not_answers(make_settings, response, reason, retry_after):
    up = Upstream(responses=[response])
    async with client_for(make_settings(), up) as client:
        with pytest.raises(ops_client.Unavailable) as exc:
            await client.list_departments(dl())
    assert exc.value.reason == reason and exc.value.retry_after == retry_after
    assert len(up.api_requests()) == 1  # reads are never retried


async def test_contract_errors_are_typed_rejections_without_raw_prose(make_settings):
    body = {"error": {"code": "NOT_FOUND", "message": "Patient Lakshmi Rao has no appointment"}}
    up = Upstream(responses=[httpx.Response(404, json=body)])
    async with client_for(make_settings(), up) as client:
        with pytest.raises(ops_client.Rejected) as exc:
            await client.get_doctor("doc_9", dl())
    assert exc.value.code == "NOT_FOUND" and exc.value.status == 404
    assert "Lakshmi" not in str(exc.value)


async def test_a_4xx_without_a_contract_body_is_still_a_rejection(make_settings):
    up = Upstream(responses=[httpx.Response(400, text="Bad Request")])
    async with client_for(make_settings(), up) as client:
        with pytest.raises(ops_client.Rejected) as exc:
            await client.get_doctor("doc_9", dl())
    assert exc.value.code is None and exc.value.status == 400


async def test_a_2xx_that_does_not_match_the_contract_is_malformed(make_settings):
    up = Upstream(responses=[httpx.Response(200, json={"id": "doc_1"})])
    async with client_for(make_settings(), up) as client:
        with pytest.raises(ops_client.Malformed):
            await client.get_doctor("doc_1", dl())


async def test_path_ids_from_the_model_cannot_choose_another_endpoint(make_settings):
    up = Upstream()
    async with client_for(make_settings(), up) as client:
        for evil in ("../departments", "doc_1?x=1", "doc 1", "", "a" * 65):
            with pytest.raises(ops_client.InvalidIdentifier):
                await client.get_doctor(evil, dl())
    assert up.requests == []


async def test_write_timeout_retries_once_with_the_same_key_and_body(make_settings):
    up = Upstream(responses=[httpx.ReadTimeout("slow"), httpx.Response(201, json=APPT)])
    body = {"patientName": "Lakshmi Rao", "mobile": "9000000101", "doctorId": "doc_1", "visitDate": "2026-10-03"}
    async with client_for(make_settings(), up) as client:
        status, appt = await client.create_appointment(body, "key-abc", dl(4.0))
    assert status == 201 and appt.id == "appt_1"
    sent = up.api_requests()
    assert len(sent) == 2 and {r.headers["idempotency-key"] for r in sent} == {"key-abc"}
    assert sent[0].content == sent[1].content and json.loads(sent[0].content) == body


async def test_write_timeout_twice_is_uncertain_never_definite(make_settings):
    up = Upstream(responses=[httpx.ReadTimeout("slow"), httpx.ReadTimeout("slow")])
    async with client_for(make_settings(), up) as client:
        with pytest.raises(ops_client.UncertainWrite):
            await client.create_appointment({"x": 1}, "key", dl(4.0))
    assert len(up.api_requests()) == 2


async def test_write_not_sent_is_unavailable_not_uncertain(make_settings):
    up = Upstream(responses=[httpx.ConnectError("refused"), httpx.ConnectError("refused")])
    async with client_for(make_settings(), up) as client:
        with pytest.raises(ops_client.Unavailable):
            await client.create_appointment({"x": 1}, "key", dl(4.0))
    assert len(up.api_requests()) == 2


async def test_no_retry_when_the_budget_is_spent(make_settings):
    now = [0.0]

    def handler(request: httpx.Request) -> httpx.Response:
        up.requests.append(request)
        if request.url.path.endswith("/auth/token"):
            return httpx.Response(200, json=TOKEN)
        now[0] += 3.9  # the first attempt consumed almost all of the 4 s budget
        raise httpx.ReadTimeout("slow", request=request)

    up = Upstream()
    client = ops_client.OpsClient(make_settings(), transport=httpx.MockTransport(handler), monotonic=lambda: now[0])
    async with client:
        with pytest.raises(ops_client.UncertainWrite):
            await client.create_appointment({"x": 1}, "key", Deadline(4.0, monotonic=lambda: now[0]))
    assert len(up.api_requests()) == 1


@pytest.mark.parametrize("status,expected", [(502, ops_client.UncertainWrite), (504, ops_client.UncertainWrite),
                                             (500, ops_client.UncertainWrite), (503, ops_client.UncertainWrite)])
async def test_server_errors_after_a_write_was_sent_are_uncertain(make_settings, status, expected):
    up = Upstream(responses=[httpx.Response(status, text="x")] * 2)
    async with client_for(make_settings(), up) as client:
        with pytest.raises(expected):
            await client.create_appointment({"x": 1}, "key", dl(4.0))


async def test_idempotency_conflict_and_state_conflict_are_distinct_rejections(make_settings):
    up = Upstream(responses=[
        httpx.Response(409, json={"error": {"code": "IDEMPOTENCY_CONFLICT", "message": "x"}}),
        httpx.Response(409, json={"error": {"code": "CONFLICT", "message": "already cancelled"}}),
    ])
    async with client_for(make_settings(), up) as client:
        with pytest.raises(ops_client.Rejected) as first:
            await client.create_appointment({"x": 1}, "key", dl(4.0))
        with pytest.raises(ops_client.Rejected) as second:
            await client.cancel_appointment("appt_1", {"callerMobile": "9000000101"}, "key2", dl(4.0))
    assert first.value.code == "IDEMPOTENCY_CONFLICT" and second.value.code == "CONFLICT"
    assert str(up.api_requests()[1].url).endswith("/appointments/appt_1/cancel")


async def test_call_summary_distinguishes_stored_from_replayed(make_settings):
    stored = {"id": "cs_1", "callId": "call-1", "startedAt": "2026-10-01T10:00:00+05:30", "intent": "AVAILABILITY",
              "outcome": "CALLBACK_NOTED", "createdAt": "2026-10-01T10:03:00+05:30"}
    up = Upstream(responses=[httpx.Response(201, json=stored), httpx.Response(200, json=stored)])
    body = {"callId": "call-1", "startedAt": "2026-10-01T10:00:00+05:30", "intent": "AVAILABILITY",
            "outcome": "CALLBACK_NOTED"}
    async with client_for(make_settings(), up) as client:
        first = await client.create_call_summary(body, "k", dl(8.0))
        second = await client.create_call_summary(body, "k", dl(8.0))
    assert first[0] == 201 and second[0] == 200 and second[1].id == "cs_1"


async def test_query_parameters_are_the_contracts(make_settings):
    up = Upstream(responses=[httpx.Response(200, json={"items": [], "total": 0}),
                             httpx.Response(200, json={"date": "2026-10-03", "items": []}),
                             httpx.Response(200, json={"items": []})])
    async with client_for(make_settings(), up) as client:
        await client.search_doctors(dl(), query="garima", department="dept_gen", gender="FEMALE")
        await client.get_availability(dl(), date="today", doctor_id="doc_1")
        await client.find_appointments(dl(), mobile="9000000101", from_date="2026-10-01", status="NOTED")
    urls = [str(r.url) for r in up.api_requests()]
    assert urls[0].endswith("/doctors?query=garima&department=dept_gen&gender=FEMALE&limit=25&offset=0")
    assert urls[1].endswith("/availability?date=today&doctorId=doc_1")
    assert urls[2].endswith("/appointments?mobile=9000000101&from=2026-10-01&status=NOTED")


async def test_availability_requires_exactly_one_target(make_settings):
    async with client_for(make_settings(), Upstream()) as client:
        with pytest.raises(ValueError):
            await client.get_availability(dl(), date="today")
        with pytest.raises(ValueError):
            await client.get_availability(dl(), date="today", doctor_id="d", department="x")


# ------------------------------------------------------------------ review fixes (1 Oct 2026)


@pytest.mark.parametrize("second", [
    httpx.ConnectError("refused"),
    httpx.Response(503, json={"error": {"code": "INTERNAL", "message": "x"}}),
    httpx.Response(429, json={"error": {"code": "RATE_LIMITED", "message": "x"}}),
    httpx.Response(500, text="boom"),
    httpx.Response(401, json={"error": {"code": "UNAUTHORIZED", "message": "x"}}),
    httpx.Response(409, json={"error": {"code": "CONFLICT", "message": "already cancelled"}}),
    httpx.Response(404, json={"error": {"code": "NOT_FOUND", "message": "x"}}),
])
async def test_any_failure_after_a_sent_write_is_uncertain_not_definite(make_settings, second):
    """Attempt 1 reached the server and got no answer; whatever attempt 2 says, the first may have committed."""
    up = Upstream(token_responses=[TOKEN, TOKEN], responses=[httpx.ReadTimeout("slow"), second, second])
    async with client_for(make_settings(), up) as client:
        with pytest.raises(ops_client.UncertainWrite):
            await client.create_appointment({"x": 1}, "key", dl(4.0))


async def test_a_decoding_error_after_send_is_uncertain_and_on_a_read_unavailable(make_settings):
    up = Upstream(responses=[httpx.DecodingError("bad gzip"), httpx.DecodingError("bad gzip")])
    async with client_for(make_settings(), up) as client:
        with pytest.raises(ops_client.UncertainWrite):
            await client.create_appointment({"x": 1}, "key", dl(4.0))
    up = Upstream(responses=[httpx.DecodingError("bad gzip")])
    async with client_for(make_settings(), up) as client:
        with pytest.raises(ops_client.Unavailable):
            await client.list_departments(dl())


async def test_the_deadline_is_a_wall_clock_total_even_against_a_dribbling_server(make_settings):
    """A server that keeps sending one byte at a time never trips httpx's per-read timeout; the invocation
    deadline must cut it off anyway."""
    import asyncio
    import time

    async def dribble(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 400\r\n\r\n")
        await writer.drain()
        try:
            for _ in range(400):
                writer.write(b" ")
                await writer.drain()
                await asyncio.sleep(0.2)
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(dribble, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    settings = make_settings(ops_base_url=f"http://127.0.0.1:{port}/api/v1", allow_budget_overrides=True,
                             read_deadline_seconds=1.0, write_deadline_seconds=1.0, summary_deadline_seconds=1.0,
                             request_timeout_seconds=1.0)
    client = ops_client.OpsClient(settings)
    client.tokens._token, client.tokens._expires_at = "warm", time.monotonic() + 3600
    try:
        started = time.monotonic()
        with pytest.raises(ops_client.Unavailable) as exc:
            await client.list_departments(Deadline(1.0))
        assert time.monotonic() - started < 2.0 and exc.value.reason in ("DEADLINE", "TIMEOUT")
        started = time.monotonic()
        with pytest.raises(ops_client.UncertainWrite):
            await client.create_appointment({"x": 1}, "k", Deadline(1.0))
        assert time.monotonic() - started < 2.5
    finally:
        await client.aclose()
        server.close()
        await server.wait_closed()


async def test_token_is_warmed_at_startup_and_refreshed_in_the_background(make_settings):
    import asyncio

    now = [1000.0]
    up = Upstream(token_responses=[{**TOKEN, "expires_in": 100}, {**TOKEN, "access_token": "tok-2"}],
                  responses=[httpx.Response(200, json={"items": []})])
    client = client_for(make_settings(token_refresh_margin_seconds=60), up, monotonic=lambda: now[0])
    await client.start()
    assert len([r for r in up.requests if r.url.path.endswith("/auth/token")]) == 1  # warmed before any call
    now[0] += 45  # 55 s left: inside the margin → the refresher should fetch a new token without a caller
    await client.refresh_if_due()
    assert client.tokens._token == "tok-2"
    await client.list_departments(dl(monotonic=lambda: now[0]))
    assert up.api_requests()[0].headers["authorization"] == "Bearer tok-2"
    await client.aclose()
    assert isinstance(client.start, type(client.aclose)) or asyncio.iscoroutinefunction(client.start)


async def test_startup_warm_failure_does_not_prevent_serving(make_settings):
    up = Upstream(token_responses=[httpx.Response(503, text="down"), TOKEN],
                  responses=[httpx.Response(200, json={"items": []})])
    client = client_for(make_settings(), up)
    await client.start()  # logs and carries on
    assert (await client.list_departments(dl())).items == []
    await client.aclose()


async def test_waiting_for_the_token_lock_is_bounded_by_the_callers_deadline(make_settings):
    import asyncio

    up = Upstream(responses=[httpx.Response(200, json={"items": []})])
    client = client_for(make_settings(), up)
    await client.tokens._lock.acquire()  # someone else is refreshing and never finishes
    try:
        with pytest.raises(ops_client.Unavailable) as exc:
            await asyncio.wait_for(client.list_departments(Deadline(0.3)), timeout=2)
        assert exc.value.reason == "DEADLINE"
    finally:
        client.tokens._lock.release()
        await client.aclose()


# ------------------------------------------------------------------ re-review (clients)


async def test_summary_writes_use_their_own_cap_not_the_in_call_share(make_settings):
    """A slow-but-healthy owner (400 ms) must not make every call summary UNCERTAIN: the summary path runs
    after the call with its own 8 s budget and per-exchange cap."""
    import asyncio

    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.4)
        if request.url.path.endswith("/auth/token"):
            return httpx.Response(200, json=TOKEN)
        return httpx.Response(201, json={"id": "cs_1", "callId": "c", "startedAt": "2026-10-01T10:00:00+05:30",
                                         "intent": "OTHER", "outcome": "ABANDONED",
                                         "createdAt": "2026-10-01T10:03:00+05:30"})

    class SlowTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            return await slow(request)

    settings = make_settings()
    assert settings.request_timeout_seconds == pytest.approx(0.30)
    async with ops_client.OpsClient(settings, transport=SlowTransport()) as client:
        deadline = Deadline(settings.summary_deadline_seconds, cap=settings.summary_deadline_seconds)
        status, stored = await client.create_call_summary({"x": 1}, "k", deadline)
    assert status == 201 and stored.id == "cs_1"


async def test_background_token_refresh_has_its_own_timeout(make_settings):
    import asyncio

    class SlowToken(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            await asyncio.sleep(0.4)
            return httpx.Response(200, json=TOKEN)

    settings = make_settings()
    assert settings.token_refresh_timeout_seconds >= 2.0
    client = ops_client.OpsClient(settings, transport=SlowToken())
    await client.start()  # warm-up must tolerate a 400 ms token endpoint even though the in-call cap is 0.30 s
    assert client.tokens.usable
    await client.aclose()


async def test_a_usable_token_is_returned_without_waiting_for_a_refresh_in_progress(make_settings):
    import asyncio
    import time

    up = Upstream(responses=[httpx.Response(200, json={"items": []})])
    client = client_for(make_settings(), up)
    client.tokens._token, client.tokens._expires_at = "still-valid", time.monotonic() + 30  # inside the margin
    await client.tokens._lock.acquire()  # a refresh is running elsewhere
    try:
        result = await asyncio.wait_for(client.list_departments(Deadline(0.3)), timeout=1)
        assert result.items == [] and up.api_requests()[0].headers["authorization"] == "Bearer still-valid"
    finally:
        client.tokens._lock.release()
        await client.aclose()


async def test_same_key_retry_happens_when_the_first_attempt_failed_instantly(make_settings):
    """A stale keep-alive connection fails in a millisecond; with 0.30 s left the same-key retry must run."""
    up = Upstream(responses=[httpx.RemoteProtocolError("stale connection"), httpx.Response(201, json=APPT)])
    async with client_for(make_settings(), up) as client:
        status, appt = await client.create_appointment({"x": 1}, "key", Deadline(0.30))
    assert status == 201 and len(up.api_requests()) == 2
    assert {r.headers["idempotency-key"] for r in up.api_requests()} == {"key"}


@pytest.mark.parametrize("status", [500, 503])
async def test_a_5xx_on_a_sent_write_is_uncertain_even_on_the_first_attempt(make_settings, status):
    """The owner may have committed before failing; nothing in the contract says a 5xx means 'not stored'."""
    up = Upstream(responses=[httpx.Response(status, json={"error": {"code": "INTERNAL", "message": "x"}})] * 2)
    async with client_for(make_settings(), up) as client:
        with pytest.raises(ops_client.UncertainWrite):
            await client.create_appointment({"x": 1}, "key", dl(4.0))


async def test_a_429_before_processing_stays_a_definite_unavailable(make_settings):
    up = Upstream(responses=[httpx.Response(429, json={"error": {"code": "RATE_LIMITED", "message": "x"}})] * 2)
    async with client_for(make_settings(), up) as client:
        with pytest.raises(ops_client.Unavailable):
            await client.create_appointment({"x": 1}, "key", dl(4.0))
