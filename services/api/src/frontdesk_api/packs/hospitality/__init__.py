"""Hospitality domain pack: a synthetic hotel's spa, restaurant and concierge (en/hi).

Proves the core carries a second domain with data only: therapists and restaurant tables
are resources, spa/dining are categories, guests are customers. Timed services and queued
walk-ins fit; multi-night room inventory does not (docs/architecture/TARGET.md).
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from .. import ALL_DAYS, CategorySeed, CustomerSeed, KnowledgeSeed, Pack, ResourceSeed, SessionSeed

if TYPE_CHECKING:
    from ...seed import Seeder

LANGUAGES = ("en", "hi")

CATEGORIES = (
    CategorySeed("cat_spa", "SPA", "Spa", {"hi": "स्पा"}),
    CategorySeed("cat_dining", "DINE", "Rooftop Restaurant", {"hi": "रूफ़टॉप रेस्टोरेंट"}),
    CategorySeed("cat_concierge", "CONC", "Concierge", {"hi": "कंसीयर्ज"}, offers_bookings=False),
)

RESOURCES = (
    # Hour-long treatments: a TIMED session, one slot per hour.
    ResourceSeed("res_asha", "Asha", ("cat_spa",), {"hi": "आशा"}, "FEMALE",
                 {"speciality": "Ayurvedic massage"}, 3500, languages=LANGUAGES,
                 sessions=(SessionSeed("day", "Spa day", ALL_DAYS, "10:00", "18:00", mode="FIXED", value=8,
                                       model="TIMED", slot_minutes=60, reserve=0),)),
    ResourceSeed("res_vikram", "Vikram", ("cat_spa",), {"hi": "विक्रम"}, "MALE",
                 {"speciality": "Deep tissue massage"}, 3500, languages=LANGUAGES,
                 sessions=(SessionSeed("day", "Spa day", ("TUE", "WED", "THU", "FRI", "SAT", "SUN"), "12:00", "20:00",
                                       mode="FIXED", value=8, model="TIMED", slot_minutes=60, reserve=0),)),
    # Table reservations: 30-minute seatings, a quarter held back for walk-in diners.
    ResourceSeed("res_rooftop", "Rooftop tables", ("cat_dining",), {"hi": "रूफ़टॉप टेबल"},
                 attributes={"cuisine": "North Indian grill"}, languages=LANGUAGES,
                 sessions=(SessionSeed("dinner", "Dinner", ALL_DAYS, "19:00", "23:00", mode="FIXED", value=16,
                                       model="TIMED", slot_minutes=30, reserve=25),)),
    # Handled by a person: shown, never booked by the agent.
    ResourceSeed("res_concierge", "Concierge desk", ("cat_concierge",), policy="DESK_ONLY", languages=LANGUAGES),
)

LEXICON: tuple[tuple[str, str, str, str], ...] = (
    ("CATEGORY", "cat_spa", "massage", "en"),
    ("CATEGORY", "cat_spa", "spa treatment", "en"),
    ("CATEGORY", "cat_spa", "मसाज", "hi"),
    ("CATEGORY", "cat_spa", "maalish", "hi"),
    ("CATEGORY", "cat_dining", "dinner", "en"),
    ("CATEGORY", "cat_dining", "table for dinner", "en"),
    ("CATEGORY", "cat_dining", "restaurant", "en"),
    ("CATEGORY", "cat_dining", "खाने की टेबल", "hi"),
    ("NEED_ROUTE", "cat_spa", "back pain", "en"),
    ("NEED_ROUTE", "cat_spa", "relax", "en"),
    ("NEED_ROUTE", "cat_dining", "anniversary dinner", "en"),
    ("RED_FLAG", "fire", "fire", "en"),
    ("RED_FLAG", "fire", "smoke in the room", "en"),
    ("RED_FLAG", "fire", "आग", "hi"),
    ("RED_FLAG", "medical", "someone collapsed", "en"),
    ("RED_FLAG", "medical", "not breathing", "en"),
    ("RED_FLAG", "security", "someone is in my room", "en"),
    ("DAY_PART", "MORNING", "सुबह", "hi"),
    ("DAY_PART", "EVENING", "शाम", "hi"),
    ("DAY_PART", "EVENING", "tonight", "en"),
    ("SERVICE_TRANSFER", "housekeeping", "housekeeping", "en"),
    ("SERVICE_TRANSFER", "housekeeping", "towels", "en"),
    ("SERVICE_TRANSFER", "room_service", "room service", "en"),
    ("SERVICE_TRANSFER", "front_desk", "checkout", "en"),
    ("SERVICE_TRANSFER", "front_desk", "bill", "en"),
    ("RESOURCE", "res_asha", "asha ji", "en"),
)

KNOWLEDGE: tuple[KnowledgeSeed, ...] = (
    KnowledgeSeed("kb_checkout", "stay", ("checkout time", "when is checkout", "check out kab hai", "चेकआउट कब है"),
                  {"en": "Check-out is at 11 AM. Late check-out until 1 PM can be requested at the front desk.",
                   "hi": "चेकआउट सुबह 11 बजे है। दोपहर 1 बजे तक लेट चेकआउट फ्रंट डेस्क पर माँगा जा सकता है।"}),
    KnowledgeSeed("kb_breakfast", "dining", ("breakfast timings", "when is breakfast", "nashta kab hai", "नाश्ता कब है"),
                  {"en": "Breakfast is served from 7 to 10:30 AM in the lobby café.",
                   "hi": "नाश्ता सुबह 7 से 10:30 बजे तक लॉबी कैफ़े में मिलता है।"}),
    KnowledgeSeed("kb_wifi", "stay", ("wifi password", "is there wifi", "internet", "वाईफाई"),
                  {"en": "Free Wi-Fi is available everywhere. The network name and password are on your "
                         "key card sleeve.",
                   "hi": "पूरे होटल में मुफ़्त वाई-फ़ाई है। नेटवर्क का नाम और पासवर्ड आपके की-कार्ड कवर पर है।"}),
    KnowledgeSeed("kb_pool", "facilities", ("pool timings", "is the pool open", "swimming pool", "स्विमिंग पूल"),
                  {"en": "The pool is open from 6 AM to 9 PM. Towels are at the pool desk.",
                   "hi": "पूल सुबह 6 से रात 9 बजे तक खुला रहता है। तौलिए पूल डेस्क पर मिलते हैं।"}),
    KnowledgeSeed("kb_airport", "transport", ("airport transfer", "airport pickup", "cab to airport", "एयरपोर्ट"),
                  {"en": "Airport transfers can be arranged by the concierge. I will connect you."},
                  action="TRANSFER_DESK", destination="concierge"),
)

GUESTS = tuple(
    CustomerSeed(name, f"90000{n:05d}", f"+9190000{n:05d}", language=lang)
    for n, (name, lang) in enumerate(
        [("Meera Shah", "en"), ("Rohit Kapoor", "hi"), ("Ananya Rao", "en"), ("Karan Malhotra", "hi")], start=700)
)


async def scenario(seed: Seeder) -> dict[str, int]:
    tomorrow = seed.today + timedelta(days=1)
    booked = 0
    guests = iter(GUESTS)
    for resource in ("res_asha", "res_rooftop"):
        for slot in (await seed.first_free(resource, tomorrow))[:2]:
            booked += await seed.book(slot, next(guests))
    # The therapist is away next Monday: bookings there would be moved and the guests notified.
    monday = seed.next_weekday(0)
    await seed.exception(resource_id="res_asha", date_from=monday, date_to=monday, scope="WHOLE_DAY",
                         effect="UNAVAILABLE", reason_category="LEAVE")
    return {"bookings": booked, "exceptions": 1, "board": 0}


PACK = Pack(
    name="hospitality",
    escalation_destination="security",
    transfer_destinations={"security": "Security / duty manager", "front_desk": "Front desk",
                           "concierge": "Concierge", "housekeeping": "Housekeeping",
                           "room_service": "Room service", "desk": "Front desk"},
    categories=CATEGORIES,
    resources=RESOURCES,
    lexicon=LEXICON,
    knowledge=KNOWLEDGE,
    scenario=scenario,
)
