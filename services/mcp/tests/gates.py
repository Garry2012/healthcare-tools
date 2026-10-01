"""Acceptance-gate predicates shared by the external tests. Kept separate so hermetic tests can prove that an
unavailable or refused downstream can never satisfy them (a passing gate means the operation really worked)."""

from __future__ import annotations

from frontdesk_mcp import outcomes

LIST_SUCCESS = {"FOUND", "NOT_FOUND"}


class GateFailure(AssertionError):
    pass


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
