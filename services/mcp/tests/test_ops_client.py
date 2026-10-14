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
from frontdesk_mcp.clock import Budget, Deadline

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
    return Deadline(Budget(seconds, .3), monotonic=monotonic) if monotonic else Deadline(Budget(seconds, .3))


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


async def test_background_refresh_renews_before_token_expiry(make_settings):
    now = [1000.0]
    up = Upstream(token_responses=[{**TOKEN, "expires_in": 120}, {**TOKEN, "access_token": "tok-2"}],
                  responses=[httpx.Response(200, json={"items": []})] * 2)
    async with client_for(make_settings(token_refresh_margin_seconds=60), up, monotonic=lambda: now[0]) as client:
        await client.list_departments(dl(monotonic=lambda: now[0]))
        now[0] += 70  # 50 s left < 60 s margin
        await client.refresh_if_due()
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

    client = ops_client.OpsClient(make_settings(),
                                  transport=httpx.MockTransport(slow_handler), monotonic=lambda: now[0])
    async with client:
        with pytest.raises(ops_client.Unavailable) as exc:
            await client.list_departments(Deadline(Budget(2.0, 1.5), monotonic=lambda: now[0]))
    assert exc.value.reason == "TIMEOUT"
    assert seen == [pytest.approx(1.5), pytest.approx(0.5)]  # the call got only what the token left


async def test_an_expired_deadline_sends_nothing(make_settings):
    up = Upstream()
    async with client_for(make_settings(), up) as client:
        with pytest.raises(ops_client.Unavailable):
            await client.list_departments(Deadline(Budget(-1, .3)))
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
            await client.create_appointment({"x": 1}, "key", Deadline(Budget(4.0, .3), monotonic=lambda: now[0]))
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


async def test_call_summary_preserves_created_and_existing_http_statuses(make_settings):
    stored = {"id": "cs_1", "callId": "call-1", "startedAt": "2026-10-01T10:00:00+05:30", "intent": "AVAILABILITY",
              "outcome": "CALLBACK_NOTED", "createdAt": "2026-10-01T10:03:00+05:30"}
    up = Upstream(responses=[httpx.Response(201, json=stored), httpx.Response(200, json=stored)])
    body = {"callId": "call-1", "startedAt": "2026-10-01T10:00:00+05:30", "intent": "AVAILABILITY",
            "outcome": "CALLBACK_NOTED"}
    async with client_for(make_settings(), up) as client:
        first = await client.create_call_summary(body, dl(8.0))
        second = await client.create_call_summary(body, dl(8.0))
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
    settings = make_settings(ops_base_url=f"http://127.0.0.1:{port}/api/v1", voice_response_budget_seconds=1.7,
                             read_deadline_seconds=1.0, write_deadline_seconds=1.0, summary_deadline_seconds=1.0,
                             read_exchange_timeout_seconds=1.0, write_exchange_timeout_seconds=1.0)
    client = ops_client.OpsClient(settings)
    client.tokens._token, client.tokens._expires_at = "warm", time.monotonic() + 3600
    try:
        started = time.monotonic()
        with pytest.raises(ops_client.Unavailable) as exc:
            await client.list_departments(Deadline(Budget(1.0, 1.0)))
        assert time.monotonic() - started < 2.0 and exc.value.reason in ("DEADLINE", "TIMEOUT")
        started = time.monotonic()
        with pytest.raises(ops_client.UncertainWrite):
            await client.create_appointment({"x": 1}, "k", Deadline(Budget(1.0, 1.0)))
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
            await asyncio.wait_for(client.list_departments(Deadline(Budget(0.3, .3))), timeout=2)
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
    assert settings.read_exchange_timeout_seconds == pytest.approx(0.30)
    async with ops_client.OpsClient(settings, transport=SlowTransport()) as client:
        deadline = Deadline(settings.summary_budget)
        status, stored = await client.create_call_summary({"x": 1}, deadline)
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
        result = await asyncio.wait_for(client.list_departments(Deadline(Budget(0.3, .3))), timeout=1)
        assert result.items == [] and up.api_requests()[0].headers["authorization"] == "Bearer still-valid"
    finally:
        client.tokens._lock.release()
        await client.aclose()


async def test_same_key_retry_happens_when_the_first_attempt_failed_instantly(make_settings):
    """A stale keep-alive connection fails in a millisecond; with 0.30 s left the same-key retry must run."""
    up = Upstream(responses=[httpx.RemoteProtocolError("stale connection"), httpx.Response(201, json=APPT)])
    async with client_for(make_settings(), up) as client:
        status, appt = await client.create_appointment({"x": 1}, "key", Deadline(Budget(0.30, .3)))
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


async def test_summary_retries_same_body_without_a_header_key(make_settings):
    body = {"callId": "call-1", "startedAt": "2026-10-01T10:00:00+05:30",
            "intent": "GENERAL_INFO", "outcome": "RESOLVED_BY_AGENT", "summaryText": "Opening hours explained."}
    stored = {**body, "id": "cs_1", "createdAt": "2026-10-01T10:03:00+05:30"}
    up = Upstream(responses=[httpx.ReadError("connection lost"), httpx.Response(200, json=stored)])
    async with client_for(make_settings(), up) as client:
        status, result = await client.create_call_summary(body, dl())
    assert status == 200 and result.callId == "call-1"
    assert len(up.api_requests()) == 2
    assert all(json.loads(r.content) == body and "idempotency-key" not in r.headers for r in up.api_requests())


@pytest.mark.parametrize("date", ["today", "2026-10-07"])
async def test_slot_reads_use_validated_path_and_unchanged_date(make_settings, date):
    from frontdesk_mcp import contract

    from .test_contract import slot_example

    up = Upstream(responses=[httpx.Response(200, json=slot_example())])
    async with client_for(make_settings(), up) as client:
        result = await client.get_slots(dl(), doctor_id="doc_001", date=date)
    assert isinstance(result, contract.SlotPlan)
    assert result.sessions[0].slots[1].available == 2
    [request] = up.api_requests()
    assert request.method == "GET" and request.url.path == "/api/v1/availability/doc_001/slots"
    assert dict(request.url.params) == {"date": date} and request.headers["authorization"] == "Bearer tok-1"


async def test_capability_read_returns_typed_used_fields(make_settings):
    from frontdesk_mcp import contract

    from .test_contract import capability_example

    up = Upstream(responses=[httpx.Response(200, json=capability_example())])
    async with client_for(make_settings(), up) as client:
        result = await client.get_capabilities(dl())
    assert isinstance(result, contract.Capabilities)
    assert result.slots.enabled is True and result.slots.blockMinutes == 30
    [request] = up.api_requests()
    assert request.method == "GET" and str(request.url) == "http://ops-stub.test/api/v1/capabilities"


async def test_slot_read_rejects_malformed_identifier_before_auth_or_http(make_settings):
    up = Upstream()
    async with client_for(make_settings(), up) as client:
        for value in ("../departments", "doc_1?x=1", "doc 1", "", "a" * 65):
            with pytest.raises(ops_client.InvalidIdentifier):
                await client.get_slots(dl(), doctor_id=value, date="today")
    assert up.requests == []


@pytest.mark.parametrize("method,args", [("get_slots", {"doctor_id": "doc_001", "date": "today"}),
                                        ("get_capabilities", {})])
@pytest.mark.parametrize("status,code", [(400, "VALIDATION_FAILED"), (404, "NOT_FOUND")])
async def test_new_reads_keep_definite_owner_rejections(make_settings, method, args, status, code):
    up = Upstream(responses=[httpx.Response(status, json={"error": {"code": code, "message": "private owner text"}})])
    async with client_for(make_settings(), up) as client:
        with pytest.raises(ops_client.Rejected) as caught:
            await getattr(client, method)(dl(), **args)
    assert caught.value.status == status and caught.value.code == code
    assert "private owner text" not in str(caught.value) and len(up.api_requests()) == 1


@pytest.mark.parametrize("method,args", [("get_slots", {"doctor_id": "doc_001", "date": "today"}),
                                        ("get_capabilities", {})])
@pytest.mark.parametrize("response,reason", [(httpx.Response(503), "UPSTREAM"),
                                            (httpx.ReadTimeout("slow"), "TIMEOUT")])
async def test_new_reads_keep_unavailable_failures(make_settings, method, args, response, reason):
    up = Upstream(responses=[response])
    async with client_for(make_settings(), up) as client:
        with pytest.raises(ops_client.Unavailable) as caught:
            await getattr(client, method)(dl(), **args)
    assert caught.value.reason == reason and len(up.api_requests()) == 1


@pytest.mark.parametrize("method,args,body", [
    ("get_slots", {"doctor_id": "doc_001", "date": "today"}, {}),
    ("get_capabilities", {}, {}),
    ("get_capabilities", {}, {"slots": {"blockMinutes": 30}}),
])
async def test_new_reads_reject_missing_required_facts_as_malformed(make_settings, method, args, body):
    up = Upstream(responses=[httpx.Response(200, json=body)])
    async with client_for(make_settings(), up) as client:
        with pytest.raises(ops_client.Malformed):
            await getattr(client, method)(dl(), **args)
    assert len(up.api_requests()) == 1


@pytest.mark.parametrize("invalid", ["reversed", "negative", "excess", "unordered", "overlap"])
async def test_slot_invariant_violations_use_existing_malformed_failure(make_settings, invalid):
    from .test_contract import slot_example

    raw = slot_example()
    blocks = raw["sessions"][0]["slots"]
    if invalid == "reversed":
        blocks[0]["end"] = blocks[0]["start"]
    elif invalid == "negative":
        blocks[0]["booked"] = -1
    elif invalid == "excess":
        blocks[0]["available"] = 4
    elif invalid == "unordered":
        blocks.reverse()
    else:
        blocks[1]["start"] = "10:45"
    up = Upstream(responses=[httpx.Response(200, json=raw)])
    async with client_for(make_settings(), up) as client:
        with pytest.raises(ops_client.Malformed):
            await client.get_slots(dl(), doctor_id="doc_001", date="today")
    assert len(up.api_requests()) == 1


@pytest.mark.parametrize("total,cap", [(0.3, 0.3), (3.0, 1.0), (8.0, 8.0)])
async def test_valid_in_margin_token_never_refreshes_in_call(make_settings, total, cap):
    up = Upstream(responses=[httpx.Response(200, json={"items": []})])
    async with client_for(make_settings(), up, monotonic=lambda: 100.0) as client:
        client.tokens._token, client.tokens._expires_at = "still-valid", 130.0
        deadline = Deadline(Budget(total, cap), monotonic=lambda: 100.0)
        await client.list_departments(deadline)
    assert len([r for r in up.requests if r.url.path.endswith("/auth/token")]) == 0


@pytest.mark.parametrize("status,event", [(502, "ops_write_gateway_error"), (504, "ops_write_gateway_error"),
                                         (500, "ops_write_server_error"), (503, "ops_write_server_error")])
async def test_write_warning_records_elapsed_time(make_settings, caplog, status, event):
    tick = [0.0]

    def owner(request):
        tick[0] += 0.125
        return httpx.Response(status)

    async with ops_client.OpsClient(make_settings(), transport=httpx.MockTransport(owner),
                                   monotonic=lambda: tick[0]) as client:
        client.tokens._token, client.tokens._expires_at = "warm", 100.0
        with pytest.raises(ops_client.UncertainWrite):
            await client.create_appointment({}, "key", Deadline(Budget(3, 1), monotonic=lambda: tick[0]))
    records = [r for r in caplog.records if r.msg == event]
    assert len(records) == 1
    assert records[0].fields["elapsedMs"] == 125 and records[0].fields["status"] == status


async def test_unanswered_write_records_safe_timing_and_retry_decision(make_settings, caplog):
    tick = [0.0]

    def owner(request):
        tick[0] += 1.0
        raise httpx.ReadTimeout("unanswered")

    async with ops_client.OpsClient(make_settings(), transport=httpx.MockTransport(owner),
                                   monotonic=lambda: tick[0]) as client:
        client.tokens._token, client.tokens._expires_at = "warm", 100.0
        with pytest.raises(ops_client.UncertainWrite):
            await client.create_appointment({}, "key", Deadline(Budget(3, 1), monotonic=lambda: tick[0]))
    records = [r for r in caplog.records if r.msg == "ops_write_unanswered"]
    assert len(records) == 2
    assert [r.fields for r in records] == [
        {"path": "/appointments", "attempt": 1, "error": "ReadTimeout",
         "elapsedMs": 1000, "remainingMs": 2000, "retry": True},
        {"path": "/appointments", "attempt": 2, "error": "ReadTimeout",
         "elapsedMs": 1000, "remainingMs": 1000, "retry": False},
    ]


async def test_inconclusive_retry_records_its_elapsed_time(make_settings, caplog):
    tick = [0.0]
    up = Upstream(responses=[httpx.ReadError("lost"), httpx.Response(409)])

    def owner(request):
        tick[0] += 0.125
        return up.handler(request)

    async with ops_client.OpsClient(make_settings(), transport=httpx.MockTransport(owner),
                                   monotonic=lambda: tick[0]) as client:
        client.tokens._token, client.tokens._expires_at = "warm", 100.0
        with pytest.raises(ops_client.UncertainWrite):
            await client.create_appointment({}, "key", Deadline(Budget(3, 1), monotonic=lambda: tick[0]))
    [record] = [r for r in caplog.records if r.msg == "ops_write_retry_inconclusive"]
    assert record.fields.get("elapsedMs") == 125


@pytest.mark.parametrize("kind,total,cap", [("read", .3, .3), ("write", 3, 1), ("summary", 8, 8)])
@pytest.mark.parametrize("state", ["valid", "absent", "expired"])
async def test_each_budget_uses_valid_tokens_or_single_flight_refresh(make_settings, kind, total, cap, state):
    now = [100.0]
    response = (httpx.Response(200, json={"items": []}) if kind == "read" else
                httpx.Response(201, json=APPT) if kind == "write" else
                httpx.Response(201, json={"id": "cs_test", "callId": "call-test",
                    "startedAt": "2026-10-01T10:00:00+05:30", "intent": "OTHER", "outcome": "ABANDONED",
                    "createdAt": "2026-10-01T10:03:00+05:30"}))
    up = Upstream(responses=[response] * 3)
    async with client_for(make_settings(), up, monotonic=lambda: now[0]) as client:
        if state != "absent":
            client.tokens._token, client.tokens._expires_at = "cached", 130 if state == "valid" else 99

        async def invoke():
            deadline = Deadline(Budget(total, cap), monotonic=lambda: now[0])
            if kind == "read":
                return await client.list_departments(deadline)
            if kind == "write":
                return await client.create_appointment({}, "key", deadline)
            return await client.create_call_summary({}, deadline)

        await asyncio.gather(*(invoke() for _ in range(3)))
    tokens = [r for r in up.requests if r.url.path.endswith("/auth/token")]
    assert len(tokens) == (0 if state == "valid" else 1)
    assert len(up.api_requests()) == 3
    assert all(r.extensions["timeout"]["read"] == pytest.approx(cap) for r in up.requests)


async def test_write_401_refresh_keeps_frozen_body_and_key(make_settings):
    up = Upstream(responses=[httpx.Response(401), httpx.Response(201, json=APPT)])
    async with client_for(make_settings(), up) as client:
        import time

        client.tokens._token, client.tokens._expires_at = "warm", time.monotonic() + 30
        status, _ = await client.create_appointment({"x": 1}, "unchanged", Deadline(Budget(3, 1)))
    assert status == 201 and len(up.api_requests()) == 2
    first, second = up.api_requests()
    assert first.content == second.content
    assert first.headers["idempotency-key"] == second.headers["idempotency-key"]
    assert len([r for r in up.requests if r.url.path.endswith("/auth/token")]) == 1


@pytest.mark.parametrize("pre,auth,exchange,retries", [
    (.5, 0, 1, 1), (.501, 0, 1, 0),
    (.1875, .125, 1, 1), (.1885, .125, 1, 0),
    (2.949, 0, 0, 1), (2.951, 0, 0, 0),
    (.5, 1, 0, 1), (.501, 1, 0, 0),
])
async def test_retry_boundaries_include_auth_schedule_and_floor(make_settings, pre, auth, exchange, retries):
    tick = [0.0]
    requests = []

    def owner(request):
        requests.append(request)
        if request.url.path.endswith("/auth/token"):
            tick[0] += auth
            return httpx.Response(200, json=TOKEN)
        posts = [r for r in requests if not r.url.path.endswith("/auth/token")]
        if len(posts) == 1:
            tick[0] += exchange
            raise httpx.ReadTimeout("unanswered")
        return httpx.Response(201, json=APPT)

    async with ops_client.OpsClient(make_settings(), transport=httpx.MockTransport(owner),
                                   monotonic=lambda: tick[0]) as client:
        if not auth:
            client.tokens._token, client.tokens._expires_at = "warm", 100.0
        deadline = Deadline(Budget(3, 1), monotonic=lambda: tick[0])
        tick[0] += pre
        if retries:
            status, _ = await client.create_appointment({"x": 1}, "same", deadline)
            assert status == 201
        else:
            with pytest.raises(ops_client.UncertainWrite):
                await client.create_appointment({"x": 1}, "same", deadline)
    posts = [r for r in requests if not r.url.path.endswith("/auth/token")]
    assert len(posts) == 1 + retries
    assert all(r.content == posts[0].content and r.headers["idempotency-key"] == "same" for r in posts)
    assert all(r.extensions["timeout"]["read"] <= 1 for r in requests)


async def test_expired_read_does_not_consume_write_or_summary_budget(make_settings):
    settings = make_settings()
    now = [0.0]
    read = Deadline(settings.read_budget, monotonic=lambda: now[0])
    now[0] = 0.5
    up = Upstream(responses=[httpx.Response(201, json=APPT)])
    async with client_for(settings, up, monotonic=lambda: now[0]) as client:
        client.tokens._token, client.tokens._expires_at = "warm", 100.0
        with pytest.raises(ops_client.Unavailable):
            await client.list_departments(read)
        status, _ = await client.create_appointment({}, "key", Deadline(settings.write_budget,
                                                                      monotonic=lambda: now[0]))
    assert status == 201 and len(up.api_requests()) == 1
    assert up.api_requests()[0].extensions["timeout"]["read"] == 1.0
