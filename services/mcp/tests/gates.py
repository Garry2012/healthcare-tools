"""Acceptance-gate predicates shared by the external tests. Kept separate so hermetic tests can prove that an
unavailable or refused downstream can never satisfy them (a passing gate means the operation really worked)."""

from __future__ import annotations

import base64
import binascii
import json

from frontdesk_mcp import outcomes
from frontdesk_mcp.clock import Deadline
from frontdesk_mcp.ops_client import OpsClient, Unavailable

LIST_SUCCESS = {"FOUND", "NOT_FOUND"}


class GateFailure(AssertionError):
    pass


async def assert_authenticated_write_tenant(ops: OpsClient, expected: str) -> None:
    """Read identity ONLY from the token fetched by our client from the configured HTTPS owner endpoint.

    This is not JWT authentication of caller-supplied input: TokenCache obtains the token over verified TLS
    using the owner's machine credentials. We inspect that trusted auth response before any test write.
    Manoj currently issues JWTs with `tenant`; opaque/malformed/unknown identities fail closed until an
    authoritative identity endpoint is agreed. The owner must separately designate `expected` as synthetic.
    """
    if not expected.strip() or not ops.settings.ops_base_url.startswith("https://"):
        raise GateFailure("BLOCKED: write tests require an expected tenant and an HTTPS owner endpoint")
    try:
        token = await ops.tokens.get(Deadline(5.0, cap=5.0))
    except Unavailable as exc:
        raise GateFailure("BLOCKED: could not authenticate the write-test tenant") from exc
    try:
        segments = token.split(".")
        if len(segments) != 3:
            raise ValueError("not a JWT")
        claims = json.loads(base64.b64decode(segments[1] + "=" * (-len(segments[1]) % 4),
                                           altchars=b"-_", validate=True))
        tenant = claims.get("tenant") if isinstance(claims, dict) else None
    except (ValueError, binascii.Error, UnicodeDecodeError):
        tenant = None
    if not isinstance(tenant, str) or not tenant:
        raise GateFailure("BLOCKED: auth response has no authoritative tenant identity; no test writes allowed")
    if tenant != expected:
        raise GateFailure("BLOCKED: authenticated tenant does not match OPS_E2E_WRITE_TENANT; no writes allowed")


def assert_list_succeeded(result: outcomes.BookingResult) -> list[outcomes.AppointmentOut]:
    """A LIST counts only when the owner answered: FOUND or an honest NOT_FOUND. Refusals and failures never pass."""
    if result.outcome not in LIST_SUCCESS:
        raise GateFailure(f"LIST did not succeed: {result.outcome} ({result.detail})")
    return list(result.appointments)


def assert_no_new_appointment(before: list[outcomes.AppointmentOut], after: list[outcomes.AppointmentOut],
                              doctor_id: str, visit_date: str) -> None:
    """Negative case: compared with a successful baseline, nothing for that doctor/date appeared."""
    before_ids = {a.appointmentId for a in before}
    created = [a for a in after if a.appointmentId not in before_ids and a.doctorId == doctor_id
               and a.visitDate == visit_date]
    if created:
        ids = [a.appointmentId for a in created]
        raise GateFailure(f"an appointment was created for {doctor_id} on {visit_date}: {ids}")


def assert_identity_forwarded(with_identity: dict, without_identity: dict) -> None:
    """Transport check only: the verified caller is not refused and the bare call is. Says nothing about the owner."""
    if with_identity.get("outcome") == "IDENTITY_UNAVAILABLE":
        raise GateFailure("trusted identity headers did not reach the adapter")
    if without_identity.get("outcome") != "IDENTITY_UNAVAILABLE":
        raise GateFailure("a request without identity was not refused")


def assert_backend_lookup_succeeded(result: dict) -> None:
    """Backend verification: the owner answered the lookup. COULD_NOT_CHECK/UNAVAILABLE/refusals never pass."""
    if result.get("outcome") not in LIST_SUCCESS:
        raise GateFailure(f"backend lookup did not succeed through the adapter: {result.get('outcome')} "
                          f"({result.get('detail')})")
