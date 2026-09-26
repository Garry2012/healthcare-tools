"""Who may see or change a booking (IMPLEMENTATION.md §2.4).

A booking is reachable from a call when the network caller number matches either the
booking's contact phone or the number the booking was made from, and — for any change —
the spoken patient name matches. Every failure looks exactly like "not found".
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .text import normalise_person_name


@dataclass(frozen=True, slots=True)
class BookingIdentity:
    appointment_id: str
    patient_name: str
    phone: str
    caller_number: str | None


def national_number(e164: str, country_code: str) -> str:
    """'+919876543210' → '9876543210' for country code '91'; other countries unchanged."""
    digits = e164.lstrip("+")
    if e164.startswith("+") and digits.startswith(country_code):
        return digits[len(country_code):]
    return digits


def number_matches(
    booking: BookingIdentity,
    *,
    caller_number: str | None,
    spoken_phone: str | None,
    country_code: str,
) -> bool:
    if caller_number:
        if booking.caller_number == caller_number:
            return True
        if booking.phone == national_number(caller_number, country_code):
            return True
    return bool(spoken_phone) and booking.phone == spoken_phone


def name_matches(booking: BookingIdentity, spoken_name: str | None) -> bool:
    if not spoken_name:
        return False
    spoken = normalise_person_name(spoken_name)
    return bool(spoken) and spoken == normalise_person_name(booking.patient_name)


def patients_on(bookings: Iterable[BookingIdentity]) -> int:
    return len({normalise_person_name(b.patient_name) for b in bookings})


def filter_by_name(bookings: Sequence[BookingIdentity], name: str) -> list[BookingIdentity]:
    return [b for b in bookings if name_matches(b, name)]
