"""Identity and disclosure (IMPLEMENTATION.md §2.4)."""

from __future__ import annotations

from frontdesk_api.domain.identity import (
    BookingIdentity,
    customers_on,
    filter_by_name,
    name_matches,
    national_number,
    number_matches,
)
from frontdesk_api.errors import NOT_FOUND_MESSAGE, not_found

LAKSHMI = BookingIdentity("bkg_1", "Lakshmi Rao", "9000000101", "+919000000101")
AARAV = BookingIdentity("bkg_2", "Aarav Rao", "9000000101", "+919000000101")
RAMESH = BookingIdentity("bkg_3", "Ramesh Iyer", "9000000202", "+919000000303")


def match(booking, caller=None, spoken=None):
    return number_matches(booking, caller_number=caller, spoken_phone=spoken, country_code="91")


def test_national_number():
    assert national_number("+919876543210", "91") == "9876543210"
    assert national_number("+61412345678", "91") == "61412345678"


def test_caller_matches_the_booking_phone():
    assert match(LAKSHMI, "+919000000101")


def test_caller_matches_the_booked_from_number_when_phone_differs():
    assert match(RAMESH, "+919000000303")  # daughter booked for her father
    assert match(RAMESH, "+919000000202")  # the father himself calls


def test_other_callers_do_not_match():
    assert not match(RAMESH, "+919999999999")
    assert not match(RAMESH)  # withheld number


def test_spoken_number_only_when_given():
    assert match(RAMESH, spoken="9000000202")
    assert not match(RAMESH, spoken="9000000303")


def test_name_must_match_after_normalisation():
    assert name_matches(LAKSHMI, "lakshmi  rao")
    assert name_matches(LAKSHMI, "LAKSHMI RAO.")
    # Script is transliterated before comparing, but spelling differences are not forgiven:
    # "ರಾವ್" romanises to "rav", so a Kannada-script "Lakshmi Rao" does not match. Strict on purpose.
    assert name_matches(BookingIdentity("a", "Lakshmi", "9000000101", None), "ಲಕ್ಷ್ಮಿ")
    assert not name_matches(LAKSHMI, "ಲಕ್ಷ್ಮಿ ರಾವ್")
    assert not name_matches(LAKSHMI, "Lakshmi")
    assert not name_matches(LAKSHMI, "Aarav Rao")
    assert not name_matches(LAKSHMI, None)
    assert not name_matches(LAKSHMI, "")


def test_two_customers_on_one_number_are_counted_without_names():
    assert customers_on([LAKSHMI, AARAV]) == 2
    assert customers_on([LAKSHMI, LAKSHMI]) == 1
    assert filter_by_name([LAKSHMI, AARAV], "Aarav Rao") == [AARAV]


def test_not_found_is_one_body_for_every_failure():
    missing, not_yours, wrong_name = not_found(), not_found(), not_found()
    assert missing.body() == not_yours.body() == wrong_name.body()
    assert missing.body() == {"error": {"code": "NOT_FOUND", "message": NOT_FOUND_MESSAGE}}
    assert missing.status == 404
