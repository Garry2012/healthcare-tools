"""The booking lifecycle: every status set a rule depends on, defined once.

The partial unique index on `bookings.slot_id` uses HOLDS_SLOT as its predicate (migration
0001, renamed by 0002); `tests/integration/test_booking_status.py` fails if they drift.
"""

from __future__ import annotations

ALL = (
    "BOOKED", "CONFIRMED_BY_DESK", "RESCHEDULED", "NEEDS_RESCHEDULE", "ARRIVED", "COMPLETED",
    "NO_SHOW", "CANCELLED_BY_CUSTOMER", "CANCELLED_BY_PROVIDER",
)

# Live, visit still ahead: what a schedule change can impact.
BEFORE_VISIT = ("BOOKED", "CONFIRMED_BY_DESK", "RESCHEDULED")
# Owns its slot: nobody else may book it.
HOLDS_SLOT = (*BEFORE_VISIT, "ARRIVED")
# The customer may still cancel or move it.
CHANGEABLE = (*BEFORE_VISIT, "NEEDS_RESCHEDULE")
# What a caller hears about on lookup.
LISTED = (*CHANGEABLE, "ARRIVED")
CANCELLED = ("CANCELLED_BY_CUSTOMER", "CANCELLED_BY_PROVIDER")

# Staff status changes: target -> statuses it may come from.
STAFF_TRANSITIONS = {
    "ARRIVED": BEFORE_VISIT,
    "COMPLETED": HOLDS_SLOT,
    "NO_SHOW": BEFORE_VISIT,
    "CANCELLED_BY_PROVIDER": CHANGEABLE,
}
