"""Healthcare domain pack: a synthetic multi-speciality hospital (en/kn/hi).

Every name and number here is invented; none comes from a real hospital. Schedules are
weekly templates; everything date-specific (bookings, exceptions, the board) is created by
`scenario` relative to the run date.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from .. import ALL_DAYS, CategorySeed, CustomerSeed, Pack, ResourceSeed, SessionSeed
from .knowledge import KNOWLEDGE

if TYPE_CHECKING:
    from ...seed import Seeder

LANGUAGES = ("en", "kn", "hi")


def _category(id: str, code: str, name: str, kn: str, hi: str) -> CategorySeed:
    return CategorySeed(id, code, name, {"kn": kn, "hi": hi})


def _resource(id: str, name: str, categories: tuple[str, ...], kn: str | None = None,
              hi: str | None = None, gender: str | None = None, qualification: str | None = None,
              price: int | None = None, **extra) -> ResourceSeed:
    localized = {k: v for k, v in (("kn", kn), ("hi", hi)) if v}
    attributes = {"qualification": qualification} if qualification else {}
    return ResourceSeed(id, name, categories, localized, gender, attributes, price, languages=LANGUAGES, **extra)


CATEGORIES = (
    _category("cat_genmed", "GM", "General Medicine", "ಸಾಮಾನ್ಯ ವೈದ್ಯಕೀಯ", "सामान्य चिकित्सा"),
    _category("cat_paed", "PAED", "Paediatrics", "ಮಕ್ಕಳ ವಿಭಾಗ", "बाल रोग विभाग"),
    _category("cat_obg", "OBG", "Obstetrics & Gynaecology", "ಪ್ರಸೂತಿ ಮತ್ತು ಸ್ತ್ರೀರೋಗ ವಿಭಾಗ", "प्रसूति एवं स्त्री रोग विभाग"),
    _category("cat_ortho", "ORTHO", "Orthopaedics", "ಮೂಳೆ ಚಿಕಿತ್ಸಾ ವಿಭಾಗ", "हड्डी रोग विभाग"),
    _category("cat_derm", "DERM", "Dermatology", "ಚರ್ಮರೋಗ ವಿಭಾಗ", "त्वचा रोग विभाग"),
    _category("cat_neuro", "NEURO", "Neurology", "ನರರೋಗ ವಿಭಾಗ", "तंत्रिका रोग विभाग"),
    _category("cat_cardio", "CARDIO", "Cardiology", "ಹೃದ್ರೋಗ ವಿಭಾಗ", "हृदय रोग विभाग"),
    _category("cat_uro", "URO", "Urology", "ಮೂತ್ರರೋಗ ವಿಭಾಗ", "मूत्र रोग विभाग"),
)


RESOURCES = (
    # The worked example: two sessions a day, three days a week, 25 % kept for walk-ins.
    _resource("res_garima", "Dr. Garima", ("cat_genmed",), "ಡಾ. ಗರಿಮಾ", "डॉ. गरिमा", "FEMALE",
        "MBBS, MD (General Medicine)", 600, variants=("Gareema",),
        sessions=(SessionSeed("am", "Morning", ("MON", "THU", "FRI"), "09:00", "12:00"),
                  SessionSeed("pm", "Afternoon", ("MON", "THU", "FRI"), "15:00", "17:00"))),
    # Duty physician, every day: carries today's time change and the ARRIVING board entry.
    _resource("res_arjun_menon", "Dr. Arjun Menon", ("cat_genmed",), "ಡಾ. ಅರ್ಜುನ್ ಮೆನನ್", "डॉ. अर्जुन मेनन", "MALE",
        "MBBS, DNB (Family Medicine)", 500,
        sessions=(SessionSeed("am", "Morning", ALL_DAYS, "10:00", "13:00", value=6, reserve=20),
                  SessionSeed("eve", "Evening", ALL_DAYS, "17:00", "20:00", value=6, reserve=20))),
    _resource("res_meera_kulkarni", "Dr. Meera Kulkarni", ("cat_paed",), "ಡಾ. ಮೀರಾ ಕುಲಕರ್ಣಿ", "डॉ. मीरा कुलकर्णी",
        "FEMALE", "MBBS, MD (Paediatrics)", 700,
        sessions=(SessionSeed("am", "Morning", ALL_DAYS, "09:00", "13:00", mode="FIXED", value=16),
                  SessionSeed("pm", "Evening", ALL_DAYS, "16:00", "19:00", mode="FIXED", value=12))),
    # Price not yet approved by the hospital: the agent must not quote it.
    _resource("res_rohan_shetty", "Dr. Rohan Shetty", ("cat_ortho",), "ಡಾ. ರೋಹನ್ ಶೆಟ್ಟಿ", "डॉ. रोहन शेट्टी", "MALE",
        "MBBS, MS (Orthopaedics)", 800, price_confirmed=False,
        sessions=(SessionSeed("am", "Late morning", ALL_DAYS, "11:00", "14:00"),)),
    # Two Sharmas in one category: "Dr Sharma" must be clarified, never guessed.
    _resource("res_anil_sharma", "Dr. Anil Sharma", ("cat_cardio",), "ಡಾ. ಅನಿಲ್ ಶರ್ಮಾ", "डॉ. अनिल शर्मा", "MALE",
        "MBBS, DM (Cardiology)", 1000,
        sessions=(SessionSeed("am", "Morning", ("MON", "WED", "FRI"), "10:00", "13:00", mode="FIXED", value=10,
                          reserve=20),)),
    _resource("res_ravi_sharma", "Dr. Ravi Sharma", ("cat_cardio",), "ಡಾ. ರವಿ ಶರ್ಮಾ", "डॉ. रवि शर्मा", None,
        "MBBS, DM (Cardiology)", 1000,
        sessions=(SessionSeed("pm", "Evening", ("TUE", "THU", "SAT"), "16:00", "19:00", mode="FIXED", value=10,
                          reserve=20),)),
    # Visiting consultant with no agreed capacity yet: capacitySource=DEFAULT.
    _resource("res_priya_nair", "Dr. Priya Nair", ("cat_derm",), "ಡಾ. ಪ್ರಿಯಾ ನಾಯರ್", "डॉ. प्रिया नायर", "FEMALE",
        "MBBS, MD (Dermatology)", 900, attendance="VISITING",
        sessions=(SessionSeed("pm", "Afternoon", ("TUE", "FRI"), "14:00", "17:00", mode="DEFAULT", value=None,
                          reserve=0),)),
    # On call and booked by the desk only: never bookable by the agent.
    _resource("res_vikram_desai", "Dr. Vikram Desai", ("cat_neuro",), "ಡಾ. ವಿಕ್ರಮ್ ದೇಸಾಯಿ", "डॉ. विक्रम देसाई", "MALE",
        "MBBS, DM (Neurology)", None, attendance="ON_CALL", policy="DESK_ONLY"),
    # Timed clinic: a slot is a 15-minute booking, not a queue position.
    _resource("res_sunita_patil", "Dr. Sunita Patil", ("cat_obg",), "ಡಾ. ಸುನೀತಾ ಪಾಟೀಲ್", "डॉ. सुनीता पाटिल", "FEMALE",
        "MBBS, MS (OBG)", 800,
        sessions=(SessionSeed("am", "Morning clinic", ("MON", "TUE", "WED", "THU", "FRI", "SAT"), "10:00", "13:00",
                          mode="FIXED", value=12, model="TIMED", slot_minutes=15, reserve=0),)),
    # Row not yet signed off by the hospital: certainty is capped at EXPECTED.
    _resource("res_kiran_hegde", "Dr. Kiran Hegde", ("cat_uro",), "ಡಾ. ಕಿರಣ್ ಹೆಗ್ಡೆ", "डॉ. किरण हेगड़े", "MALE",
        "MBBS, MCh (Urology)", 700, data_confirmed=False,
        sessions=(SessionSeed("eve", "Evening", ("MON", "WED", "SAT"), "17:00", "19:00", value=5, reserve=20),)),
)


# (concept_type, concept_id, term, language). All approved in the seed.
LEXICON: tuple[tuple[str, str, str, str], ...] = (
    # departments, as callers name them
    ("CATEGORY", "cat_genmed", "general physician", "en"),
    ("CATEGORY", "cat_genmed", "general doctor", "en"),
    ("CATEGORY", "cat_genmed", "physician", "en"),
    ("CATEGORY", "cat_genmed", "ಜನರಲ್ ಡಾಕ್ಟರ್", "kn"),
    ("CATEGORY", "cat_genmed", "सामान्य डॉक्टर", "hi"),
    ("CATEGORY", "cat_paed", "child specialist", "en"),
    ("CATEGORY", "cat_paed", "paediatrician", "en"),
    ("CATEGORY", "cat_paed", "pediatrician", "en"),
    ("CATEGORY", "cat_paed", "children doctor", "en"),
    ("CATEGORY", "cat_paed", "ಮಕ್ಕಳ ಡಾಕ್ಟರ್", "kn"),
    ("CATEGORY", "cat_paed", "makkala doctor", "kn"),
    ("CATEGORY", "cat_paed", "बच्चों का डॉक्टर", "hi"),
    ("CATEGORY", "cat_paed", "bacchon ka doctor", "hi"),
    ("CATEGORY", "cat_obg", "gynaecologist", "en"),
    ("CATEGORY", "cat_obg", "gynecologist", "en"),
    ("CATEGORY", "cat_obg", "pregnancy doctor", "en"),
    ("CATEGORY", "cat_obg", "ಹೆರಿಗೆ ಡಾಕ್ಟರ್", "kn"),
    ("CATEGORY", "cat_obg", "स्त्री रोग विशेषज्ञ", "hi"),
    ("CATEGORY", "cat_ortho", "bone doctor", "en"),
    ("CATEGORY", "cat_ortho", "orthopaedic", "en"),
    ("CATEGORY", "cat_ortho", "orthopedic", "en"),
    ("CATEGORY", "cat_ortho", "ಮೂಳೆ ಡಾಕ್ಟರ್", "kn"),
    ("CATEGORY", "cat_ortho", "हड्डी का डॉक्टर", "hi"),
    ("CATEGORY", "cat_ortho", "haddi ka doctor", "hi"),
    ("CATEGORY", "cat_derm", "skin doctor", "en"),
    ("CATEGORY", "cat_derm", "dermatologist", "en"),
    ("CATEGORY", "cat_derm", "skin specialist", "en"),
    ("CATEGORY", "cat_derm", "ಚರ್ಮ ವೈದ್ಯ", "kn"),
    ("CATEGORY", "cat_derm", "charma vaidya", "kn"),
    ("CATEGORY", "cat_derm", "त्वचा विशेषज्ञ", "hi"),
    ("CATEGORY", "cat_derm", "charm ka doctor", "hi"),
    ("CATEGORY", "cat_neuro", "neurologist", "en"),
    ("CATEGORY", "cat_neuro", "nerve doctor", "en"),
    ("CATEGORY", "cat_neuro", "ನರ ವೈದ್ಯ", "kn"),
    ("CATEGORY", "cat_neuro", "न्यूरोलॉजिस्ट", "hi"),
    ("CATEGORY", "cat_cardio", "heart doctor", "en"),
    ("CATEGORY", "cat_cardio", "cardiologist", "en"),
    ("CATEGORY", "cat_cardio", "ಹೃದಯ ಡಾಕ್ಟರ್", "kn"),
    ("CATEGORY", "cat_cardio", "दिल का डॉक्टर", "hi"),
    ("CATEGORY", "cat_cardio", "dil ka doctor", "hi"),
    ("CATEGORY", "cat_uro", "urologist", "en"),
    ("CATEGORY", "cat_uro", "ಮೂತ್ರ ವೈದ್ಯ", "kn"),
    ("CATEGORY", "cat_uro", "मूत्र रोग विशेषज्ञ", "hi"),
    # the hospital's approved symptom routes (e.g. thyroid → General Medicine, not endocrinology)
    ("NEED_ROUTE", "cat_genmed", "thyroid doctor", "en"),
    ("NEED_ROUTE", "cat_genmed", "thyroid", "en"),
    ("NEED_ROUTE", "cat_genmed", "sugar problem", "en"),
    ("NEED_ROUTE", "cat_genmed", "fever", "en"),
    ("NEED_ROUTE", "cat_genmed", "ಥೈರಾಯ್ಡ್", "kn"),
    ("NEED_ROUTE", "cat_genmed", "ಜ್ವರ", "kn"),
    ("NEED_ROUTE", "cat_genmed", "थायराइड", "hi"),
    ("NEED_ROUTE", "cat_genmed", "बुखार", "hi"),
    ("NEED_ROUTE", "cat_ortho", "knee pain", "en"),
    ("NEED_ROUTE", "cat_ortho", "ಮೊಣಕಾಲು ನೋವು", "kn"),
    ("NEED_ROUTE", "cat_ortho", "घुटने का दर्द", "hi"),
    ("NEED_ROUTE", "cat_derm", "skin rash", "en"),
    # red flags: checked before anything else, in three languages
    ("RED_FLAG", "chest_pain", "chest pain", "en"),
    ("RED_FLAG", "chest_pain", "ಎದೆ ನೋವು", "kn"),
    ("RED_FLAG", "chest_pain", "सीने में दर्द", "hi"),
    ("RED_FLAG", "chest_pain", "seene mein dard", "hi"),
    ("RED_FLAG", "breathlessness", "breathlessness", "en"),
    ("RED_FLAG", "breathlessness", "difficulty breathing", "en"),
    ("RED_FLAG", "breathlessness", "cannot breathe", "en"),
    ("RED_FLAG", "breathlessness", "ಉಸಿರಾಡಲು ಕಷ್ಟ", "kn"),
    ("RED_FLAG", "breathlessness", "सांस लेने में तकलीफ", "hi"),
    ("RED_FLAG", "unconscious", "unconscious", "en"),
    ("RED_FLAG", "unconscious", "fainted", "en"),
    ("RED_FLAG", "unconscious", "ಪ್ರಜ್ಞೆ ತಪ್ಪಿದೆ", "kn"),
    ("RED_FLAG", "unconscious", "बेहोश", "hi"),
    ("RED_FLAG", "heavy_bleeding", "heavy bleeding", "en"),
    ("RED_FLAG", "heavy_bleeding", "ತುಂಬಾ ರಕ್ತಸ್ರಾವ", "kn"),
    ("RED_FLAG", "heavy_bleeding", "बहुत खून बह रहा", "hi"),
    ("RED_FLAG", "fits", "having fits", "en"),
    ("RED_FLAG", "fits", "seizure", "en"),
    ("RED_FLAG", "fits", "ಫಿಟ್ಸ್", "kn"),
    ("RED_FLAG", "fits", "मिर्गी का दौरा", "hi"),
    ("RED_FLAG", "labour_pain", "labour pains", "en"),
    ("RED_FLAG", "labour_pain", "labor pain", "en"),
    ("RED_FLAG", "labour_pain", "ಹೆರಿಗೆ ನೋವು", "kn"),
    ("RED_FLAG", "labour_pain", "प्रसव पीड़ा", "hi"),
    # day parts
    ("DAY_PART", "MORNING", "morning", "en"),
    ("DAY_PART", "AFTERNOON", "afternoon", "en"),
    ("DAY_PART", "EVENING", "evening", "en"),
    ("DAY_PART", "EVENING", "night", "en"),
    ("DAY_PART", "MORNING", "ಬೆಳಿಗ್ಗೆ", "kn"),
    ("DAY_PART", "MORNING", "beligge", "kn"),
    ("DAY_PART", "AFTERNOON", "ಮಧ್ಯಾಹ್ನ", "kn"),
    ("DAY_PART", "EVENING", "ಸಂಜೆ", "kn"),
    ("DAY_PART", "EVENING", "sanje", "kn"),
    ("DAY_PART", "MORNING", "सुबह", "hi"),
    ("DAY_PART", "MORNING", "subah", "hi"),
    ("DAY_PART", "AFTERNOON", "दोपहर", "hi"),
    ("DAY_PART", "AFTERNOON", "dopahar", "hi"),
    ("DAY_PART", "EVENING", "शाम", "hi"),
    ("DAY_PART", "EVENING", "shaam", "hi"),
    # not a consultation: hand to the right desk
    ("SERVICE_TRANSFER", "lab", "blood report", "en"),
    ("SERVICE_TRANSFER", "lab", "lab report", "en"),
    ("SERVICE_TRANSFER", "lab", "blood test", "en"),
    ("SERVICE_TRANSFER", "lab", "ರಕ್ತ ಪರೀಕ್ಷೆ", "kn"),
    ("SERVICE_TRANSFER", "lab", "खून की जांच", "hi"),
    ("SERVICE_TRANSFER", "pharmacy", "pharmacy", "en"),
    ("SERVICE_TRANSFER", "pharmacy", "medical shop", "en"),
    ("SERVICE_TRANSFER", "pharmacy", "ಔಷಧಿ ಅಂಗಡಿ", "kn"),
    ("SERVICE_TRANSFER", "pharmacy", "दवाई की दुकान", "hi"),
    ("SERVICE_TRANSFER", "insurance", "insurance", "en"),
    ("SERVICE_TRANSFER", "insurance", "cashless", "en"),
    ("SERVICE_TRANSFER", "insurance", "ವಿಮೆ", "kn"),
    ("SERVICE_TRANSFER", "insurance", "बीमा", "hi"),
    ("SERVICE_TRANSFER", "desk", "ultrasound", "en"),
    ("SERVICE_TRANSFER", "desk", "vaccination", "en"),
    # ways callers say a doctor's name that phonetics would not catch
    ("RESOURCE", "res_garima", "garima madam", "en"),
    ("RESOURCE", "res_garima", "ಗರಿಮಾ ಮೇಡಂ", "kn"),
)


# Synthetic numbers in a clearly fake 90000 00xxx range.
LAKSHMI = CustomerSeed("Lakshmi Rao", "9000000101", "+919000000101", language="kn", reason="ಮೊಣಕಾಲು ನೋವು")
AARAV = CustomerSeed("Aarav Rao", "9000000101", "+919000000101", relation="CHILD", language="kn", reason="fever")
RAMESH = CustomerSeed("Ramesh Iyer", "9000000202", "+919000000303", relation="PARENT", reason="BP check")
POOL = tuple(
    CustomerSeed(name, f"90000{n:05d}", f"+9190000{n:05d}", language=lang)
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


async def scenario(seed: Seeder) -> dict[str, int]:
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


PACK = Pack(
    name="healthcare",
    escalation_destination="emergency",
    transfer_destinations={"emergency": "Emergency", "desk": "Front desk", "lab": "Laboratory",
                           "pharmacy": "Pharmacy", "insurance": "Insurance desk"},
    categories=CATEGORIES,
    resources=RESOURCES,
    lexicon=LEXICON,
    knowledge=KNOWLEDGE,
    scenario=scenario,
)
