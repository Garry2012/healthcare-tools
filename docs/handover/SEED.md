# Seed data

The seed is a demo rollout (`rollouts/demo-hospital`, or `rollouts/demo-hotel`) applied exactly as
`frontdesk-api rollout apply` would, plus that demo's dated scenario (`frontdesk_api/demo/`).
It refuses `ENV=production`: a real provider's data is its own rollout, never the demo.

`make seed` (or `frontdesk-api seed`) loads **synthetic** data. Every name and number is
invented; nothing comes from the archived hospital documents. Dates are computed from the run
date, so the demo works on any day.

| Command | Effect |
|---|---|
| `make seed` | Upserts directory rows (categories, resources, templates, lexicon) every run. Bookings, exceptions and the board are created once; later runs leave them alone. |
| `make seed-reset` | **Destructive.** Empties every table, then reloads. Use it to re-date the demo or clean up after exploratory testing. |

## What is loaded

- **8 categories** with `kn` and `hi` names: General Medicine, Paediatrics, Obstetrics &
  Gynaecology, Orthopaedics, Dermatology, Neurology, Cardiology, Urology.
- **10 resources**, each covering a case the spec cares about:

| Resource | Case |
|---|---|
| Dr. Garima (General Medicine) | Mon/Thu/Fri 09:00–12:00 and 15:00–17:00, SEQUENCE, 4 per hour, 25 % walk-in reserve |
| Dr. Arjun Menon (General Medicine) | Every day; carries today's TIME_CHANGE and the ARRIVING board entry |
| Dr. Meera Kulkarni (Paediatrics) | Every day; PRESENT on today's board with tokens issued; TIMING_PENDING tomorrow evening |
| Dr. Rohan Shetty (Orthopaedics) | Price **not confirmed**; LEFT on today's board |
| Dr. Anil Sharma / Dr. Ravi Sharma (Cardiology) | Shared surname in one category → `CLARIFY WHICH_RESOURCE`; Ravi has `gender = null` |
| Dr. Priya Nair (Dermatology) | VISITING, Tue/Fri, no agreed capacity → `capacitySource: DEFAULT` |
| Dr. Vikram Desai (Neurology) | ON_CALL and DESK_ONLY: no template; never bookable by the agent |
| Dr. Sunita Patil (OBG) | TIMED clinic, 15-minute slots |
| Dr. Kiran Hegde (Urology) | `dataConfirmed = false` → certainty capped at EXPECTED |

- **Exceptions:** surgery (UNAVAILABLE) on Dr. Garima's afternoon next Thursday; a same-day
  TIME_CHANGE (Dr. Arjun Menon's evening now 18:00–20:00); an EXTRA_SESSION on the coming Sunday
  (Dr. Garima 10:00–12:00, capacity 8); TIMING_PENDING on tomorrow evening (Dr. Meera Kulkarni).
- **Board today:** Dr. Arjun Menon ARRIVING (20 min late), Dr. Meera Kulkarni PRESENT
  (7 tokens), Dr. Rohan Shetty LEFT.
- **About 30 bookings** over the next seven days, made through the same booking service
  the API uses. They include three in the Thursday afternoon the surgery removes (so they are
  `NEEDS_RESCHEDULE` with three pending notifications), two customers on one phone (Lakshmi Rao
  and her son Aarav, 9000000101), and a booking made from a different number than the
  customer's own (Ramesh Iyer, phone 9000000202, booked from +919000000303).
- **Lexicon (196 approved terms, en/kn/hi):** from the healthcare domain's baseline, 194 terms:
  department names callers use ("skin doctor", "ಚರ್ಮ ವೈದ್ಯ", "charm ka doctor"), symptom routes
  ("thyroid doctor" → General Medicine), red flags (chest pain, breathlessness, unconscious,
  heavy bleeding, fits, labour pains) and service transfers (lab, pharmacy, insurance, desk).
  From the demo hospital's own `terms`, 2 doctor aliases. Day-part words ("ಸಂಜೆ", "shaam") come
  from the language modules, not the lexicon.

Source: `rollouts/demo-hospital/` (directory, schedules, aliases, knowledge base), the domain
pack `services/api/src/frontdesk_api/packs/healthcare/` (baseline words), and
`services/api/src/frontdesk_api/demo/hospital.py` (the dated scenario).

## Other packs

`PROVIDER_ID=demo-hotel` (the `rollouts/demo-hotel` rollout of the hospitality domain) seeds a synthetic hotel instead: two spa therapists (60-minute timed
treatments), rooftop restaurant tables (30-minute seatings, 25 % held for walk-ins), a desk-only
concierge, an en/hi lexicon (red flags escalate to `security`) and hotel FAQs. The API, the
MCP tools and the database are identical; only the domain pack and the rollout differ.
