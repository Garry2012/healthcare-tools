"""Demo scenario for rollouts/demo-hospital: dated bookings, exceptions and board entries.

Everything date-specific is created relative to the run date, through the same services the API
uses. Test and demo data only: `frontdesk-api seed` refuses ENV=production.
"""

from __future__ import annotations

from datetime import timedelta

from . import Customer, ScenarioBuilder

# Synthetic numbers in a clearly fake 90000 00xxx range.
LAKSHMI = Customer("Lakshmi Rao", "9000000101", "+919000000101", language="kn", reason="ಮೊಣಕಾಲು ನೋವು")
AARAV = Customer("Aarav Rao", "9000000101", "+919000000101", relation="CHILD", language="kn", reason="fever")
RAMESH = Customer("Ramesh Iyer", "9000000202", "+919000000303", relation="PARENT", reason="BP check")
POOL = tuple(
    Customer(name, f"90000{n:05d}", f"+9190000{n:05d}", language=lang)
    for n, (name, lang) in enumerate(
        [
            ("Anita Gowda", "kn"), ("Suresh Kumar", "en"), ("Farah Khan", "hi"), ("Deepak Joshi", "hi"),
            ("Kavya Shenoy", "kn"), ("Imran Ali", "hi"), ("Nisha Pillai", "en"), ("Manjunath B", "kn"),
            ("Pooja Verma", "hi"), ("Harish Reddy", "en"), ("Shalini Das", "en"), ("Vinay Kamath", "kn"),
            ("Rekha Nayak", "kn"), ("Arvind Bhat", "en"), ("Sneha Kulkarni", "kn"), ("Tarun Mehta", "hi"),
            ("Geeta Hegde", "kn"), ("Naveen Rao", "en"), ("Ritu Saxena", "hi"), ("Sanjay Patil", "en"),
            ("Bhavana M", "kn"), ("Yusuf Sheikh", "hi"), ("Lata Menon", "en"), ("Prakash Gowda", "kn"),
            ("Divya Iyer", "en"), ("Kishore N", "kn"), ("Zoya Mirza", "hi"), ("Ganesh Shetty", "kn"),
        ],
        start=400,
    )
)


async def scenario(seed: ScenarioBuilder) -> dict[str, int]:
    """Dated demo data: every case in docs/handover/SEED.md, relative to the run date."""
    today = seed.today
    tomorrow = today + timedelta(days=1)
    next_thursday = seed.next_weekday(3)
    next_sunday = seed.next_weekday(6)
    pool = iter(POOL)
    booked = 0

    # 1. Three patients in Dr. Garima's afternoon on the coming Thursday; the surgery
    #    exception below removes that session, so these become the impacted patients.
    for slot in (await seed.first_free("res_garima", next_thursday, "2"))[:3]:
        booked += await seed.book(slot, next(pool))

    # 2. Two patients on one phone (mother and child), and a booking made from a
    #    different number than the patient's own.
    for customer, resource in ((LAKSHMI, "res_arjun_menon"), (AARAV, "res_meera_kulkarni")):
        slots = await seed.first_free(resource, tomorrow)
        if slots:
            booked += await seed.book(slots[0], customer)
    slots = await seed.first_free("res_anil_sharma", seed.next_weekday(0))
    if slots:
        booked += await seed.book(slots[0], RAMESH)

    # 3. Spread the rest over the next seven days, a couple per doctor-day.
    spread = ("res_garima", "res_arjun_menon", "res_meera_kulkarni", "res_rohan_shetty", "res_sunita_patil",
              "res_kiran_hegde", "res_ravi_sharma", "res_priya_nair")
    for offset in range(7):
        day = today + timedelta(days=offset)
        for i, resource in enumerate(spread):
            if booked >= 30 or (offset + i) % 3:
                continue
            for slot in (await seed.first_free(resource, day, skip=1))[:2]:
                customer = next(pool, None)
                if customer is None:
                    break
                booked += await seed.book(slot, customer)

    # 4. Reality differs from the template.
    await seed.exception(resource_id="res_garima", date_from=next_thursday, date_to=next_thursday,
                         scope="SESSION", template_session_id="tpl_res_garima_pm", effect="UNAVAILABLE",
                         reason_category="OTHER_DUTY", note="Two surgeries (synthetic)")
    await seed.exception(resource_id="res_arjun_menon", date_from=today, date_to=today, scope="SESSION",
                         template_session_id="tpl_res_arjun_menon_eve", effect="TIME_CHANGE",
                         new_start="18:00", new_end="20:00", reason_category="OTHER")
    await seed.exception(resource_id="res_garima", date_from=next_sunday, date_to=next_sunday,
                         scope="TIME_RANGE", effect="EXTRA_SESSION", new_start="10:00", new_end="12:00",
                         new_capacity=8, reason_category="OTHER")
    await seed.exception(resource_id="res_meera_kulkarni", date_from=tomorrow, date_to=tomorrow,
                         scope="SESSION", template_session_id="tpl_res_meera_kulkarni_pm",
                         effect="TIMING_PENDING", reason_category="OTHER")

    # 5. What the desk has marked on today's board.
    await seed.board("res_arjun_menon", "1", presence="ARRIVING", delay_minutes=20, expected_start="10:20")
    await seed.board("res_meera_kulkarni", "1", presence="PRESENT", tokens_issued=7)
    await seed.board("res_rohan_shetty", "1", presence="LEFT")
    return {"bookings": booked, "exceptions": 4, "board": 3}
