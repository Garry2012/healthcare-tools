# Seed data

`make seed` (or `frontdesk-api seed`) loads **synthetic** data. Every name and number is
invented; nothing comes from the archived hospital documents. Dates are computed from the run
date, so the demo works on any day.

| Command | Effect |
|---|---|
| `make seed` | Upserts directory rows (departments, doctors, templates, lexicon) every run. Bookings, exceptions and the board are created once; later runs leave them alone. |
| `make seed-reset` | **Destructive.** Empties every table, then reloads. Use it to re-date the demo or clean up after exploratory testing. |

## What is loaded

- **8 departments** with `kn` and `hi` names: General Medicine, Paediatrics, Obstetrics &
  Gynaecology, Orthopaedics, Dermatology, Neurology, Cardiology, Urology.
- **10 doctors**, each covering a case the spec cares about:

| Doctor | Case |
|---|---|
| Dr. Garima (General Medicine) | Mon/Thu/Fri 09:00–12:00 and 15:00–17:00, SEQUENCE, 4 per hour, 25 % walk-in reserve |
| Dr. Arjun Menon (General Medicine) | Every day; carries today's TIME_CHANGE and the ARRIVING board entry |
| Dr. Meera Kulkarni (Paediatrics) | Every day; PRESENT on today's board with tokens issued; TIMING_PENDING tomorrow evening |
| Dr. Rohan Shetty (Orthopaedics) | Fee **not confirmed**; LEFT on today's board |
| Dr. Anil Sharma / Dr. Ravi Sharma (Cardiology) | Shared surname in one department → `CLARIFY WHICH_DOCTOR`; Ravi has `gender = null` |
| Dr. Priya Nair (Dermatology) | VISITING, Tue/Fri, no agreed capacity → `capacitySource: DEFAULT` |
| Dr. Vikram Desai (Neurology) | ON_CALL and DESK_ONLY: no template; never bookable by the agent |
| Dr. Sunita Patil (OBG) | TIMED clinic, 15-minute slots |
| Dr. Kiran Hegde (Urology) | `dataConfirmed = false` → certainty capped at EXPECTED |

- **Exceptions:** surgery (UNAVAILABLE) on Dr. Garima's afternoon next Thursday; a same-day
  TIME_CHANGE (Dr. Arjun Menon's evening now 18:00–20:00); an EXTRA_SESSION on the coming Sunday
  (Dr. Garima 10:00–12:00, capacity 8); TIMING_PENDING on tomorrow evening (Dr. Meera Kulkarni).
- **Board today:** Dr. Arjun Menon ARRIVING (20 min late), Dr. Meera Kulkarni PRESENT
  (7 tokens), Dr. Rohan Shetty LEFT.
- **About 30 appointments** over the next seven days, made through the same booking service
  the API uses. They include three in the Thursday afternoon the surgery removes (so they are
  `NEEDS_RESCHEDULE` with three pending notifications), two patients on one phone (Lakshmi Rao
  and her son Aarav, 9000000101), and a booking made from a different number than the
  patient's own (Ramesh Iyer, phone 9000000202, booked from +919000000303).
- **Lexicon (111 approved terms, en/kn/hi):** department names callers use ("skin doctor",
  "ಚರ್ಮ ವೈದ್ಯ", "charm ka doctor"), doctor aliases, symptom routes ("thyroid doctor" → General
  Medicine), red flags (chest pain, breathlessness, unconscious, heavy bleeding, fits, labour
  pains), day parts ("ಸಂಜೆ", "shaam"), and service transfers (lab, pharmacy, insurance, desk).

Source: `services/api/src/frontdesk_api/seed_data.py` (data) and `seed.py` (dates and loading).
