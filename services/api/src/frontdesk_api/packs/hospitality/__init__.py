"""Hospitality domain: what every hotel rollout shares.

Service codes (spa, dining, concierge), the words guests use for them, safety phrases (always a
transfer to the duty manager), and the desks a request goes to by default. A rollout brings its
own services, therapists, tables, schedules and approved answers. Timed services and walk-in
queues fit the core as data; multi-night room inventory does not yet (TARGET.md).
"""

from __future__ import annotations

from .. import LexiconRow, Pack

CATEGORIES = {"SPA": "Spa", "DINE": "Restaurant", "CONC": "Concierge"}

# (concept_type, target, term, language). CATEGORY and NEED_ROUTE rows point at a category code.
BASELINE: tuple[LexiconRow, ...] = (
    ("CATEGORY", "SPA", "massage", "en"),
    ("CATEGORY", "SPA", "spa treatment", "en"),
    ("CATEGORY", "SPA", "मसाज", "hi"),
    ("CATEGORY", "SPA", "maalish", "hi"),
    ("CATEGORY", "DINE", "dinner", "en"),
    ("CATEGORY", "DINE", "table for dinner", "en"),
    ("CATEGORY", "DINE", "restaurant", "en"),
    ("CATEGORY", "DINE", "खाने की टेबल", "hi"),
    ("NEED_ROUTE", "SPA", "back pain", "en"),
    ("NEED_ROUTE", "SPA", "relax", "en"),
    ("NEED_ROUTE", "DINE", "anniversary dinner", "en"),
    ("RED_FLAG", "fire", "fire", "en"),
    ("RED_FLAG", "fire", "smoke in the room", "en"),
    ("RED_FLAG", "fire", "आग", "hi"),
    ("RED_FLAG", "medical", "someone collapsed", "en"),
    ("RED_FLAG", "medical", "not breathing", "en"),
    ("RED_FLAG", "security", "someone is in my room", "en"),
    ("SERVICE_TRANSFER", "housekeeping", "housekeeping", "en"),
    ("SERVICE_TRANSFER", "housekeeping", "towels", "en"),
    ("SERVICE_TRANSFER", "room_service", "room service", "en"),
    ("SERVICE_TRANSFER", "front_desk", "checkout", "en"),
    ("SERVICE_TRANSFER", "front_desk", "bill", "en"),
)


PACK = Pack(
    name="hospitality",
    version="1",
    escalation_destination="security",
    desk_destination="desk",
    transfer_destinations={"security": "Security / duty manager", "front_desk": "Front desk",
                           "concierge": "Concierge", "housekeeping": "Housekeeping",
                           "room_service": "Room service", "desk": "Front desk"},
    categories=CATEGORIES,
    baseline=BASELINE,
    # Hotel services are booked in half hours unless a rollout says otherwise.
    settings={"tenant_default_slot_minutes": "30"},
)
