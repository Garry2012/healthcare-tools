"""Demo scenario for rollouts/demo-hotel. Test and demo data only."""

from __future__ import annotations

from datetime import timedelta

from . import Customer, ScenarioBuilder

GUESTS = tuple(
    Customer(name, f"90000{n:05d}", f"+9190000{n:05d}", language=lang)
    for n, (name, lang) in enumerate(
        [("Meera Shah", "en"), ("Rohit Kapoor", "hi"), ("Ananya Rao", "en"), ("Karan Malhotra", "hi")], start=700)
)


async def scenario(seed: ScenarioBuilder) -> dict[str, int]:
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
