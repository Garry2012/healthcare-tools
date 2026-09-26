# Testing: locally, and what to expect

For testing in Azure, see `AZURE.md` §8. For wiring a LiveKit agent, see `LIVEKIT.md`.

## Automated

| Command | What runs | Time | Needs |
|---|---|---|---|
| `make test-fast` | ruff, the architecture contracts (`lint-imports`), API unit and spec tests, MCP unit tests | ~10 s | uv |
| `make test` (= `./scripts/test.sh`) | everything: plus API integration on PostgreSQL 16, MCP end to end through a real `frontdesk-mcp serve`, schemathesis against the running API | ~2–3 min | uv, and Docker or a local PostgreSQL (`scripts/local-pg.sh`) |

Expect `== all suites passed`. CI runs `./scripts/test.sh` on every pull request and on `main`.

The integration suite runs at a fixed moment (Wednesday 23 September 2026, 10:00 IST), so a
result never depends on when you run it. To reproduce a time-of-day problem, rerun it at
another moment:

```bash
cd services/api && TEST_NOW=2026-09-27T21:30 uv run pytest tests/integration -q
```

## Run it locally

Needs Docker, uv 0.11+ and jq.

```bash
git checkout main && git pull
cp .env.example .env        # the change-me tokens are fine for a local run
make up                     # postgres + migrate + api (:8000) + mcp (:8100)
make seed-reset             # the synthetic hospital, dated from today
make demo                   # Kannada caller: search → book → list → reschedule → cancel
```

`make demo` should end with the booking `CANCELLED_BY_CUSTOMER`. "Tomorrow" is tomorrow in
India time, so late at night in India it can already be the day after.

## Try these by hand

```bash
AGENT=change-me-agent-token
ask()  { curl -s -X POST localhost:8000/api/v1/agent/availability-search -H "Authorization: Bearer $AGENT" \
           -H "X-Call-Id: try-$RANDOM" -H 'X-Caller-Number: +919000000101' -H 'Content-Type: application/json' -d "$1" | jq "$2"; }
know() { curl -s -X POST localhost:8000/api/v1/agent/knowledge-search -H "Authorization: Bearer $AGENT" \
           -H "X-Call-Id: try-$RANDOM" -H 'X-Caller-Number: +919000000101' -H 'Content-Type: application/json' -d "$1" | jq "$2"; }
```

| Try | Command | Expect |
|---|---|---|
| Emergency, Kannada | `ask '{"utterance":"ಎದೆ ನೋವು ಜಾಸ್ತಿ ಇದೆ","language":"kn"}' .routing` | `TRANSFER_EMERGENCY` |
| Emergency, mixed | `ask '{"utterance":"ಅಪ್ಪನಿಗೆ chest pain","language":"kn"}' .routing` | `TRANSFER_EMERGENCY` |
| Date as a word, Hindi | `ask '{"utterance":"पाँच तारीख डॉक्टर गरिमा","language":"hi","resourceName":"डॉक्टर गरिमा","when":{"expression":"पाँच तारीख"}}' .understood.dates` | the next 5th |
| Date as a word, Kannada | `ask '{"utterance":"ಐದು ತಾರೀಖು","language":"kn","resourceName":"Dr Garima","when":{"expression":"ಐದು ತಾರೀಖು"}}' .understood.dates` | the next 5th |
| Speech-to-speech English | `ask '{"utterance":"I need a children'"'"'s doctor","language":"kn","category":"children'"'"'s doctor"}' .understood.categories` | Paediatrics |
| Symptom, Hindi | `ask '{"utterance":"pet mein dard hai","language":"hi","needText":"pet mein dard"}' .understood.categories` | General Medicine |
| Which Dr Sharma | `ask '{"utterance":"Dr Sharma","language":"en","resourceName":"Dr Sharma"}' .clarification` | two options, each with days and hours |
| Unconfirmed fee | `ask '{"utterance":"bone doctor","language":"en","category":"bone doctor"}' '.results[].resource.price'` | `null` |
| Not understood | `ask '{"utterance":"I want to talk about my bill","language":"en"}' .routing` | `NO_SERVICE` to the desk, never "no one available" |
| Knowledge, Hindi | `know '{"question":"अस्पताल कहाँ है","language":"hi"}' .answer.text` | the approved Hindi answer |
| Knowledge, unclear | `know '{"question":"visiting hours for ICU","language":"en"}' .outcome` | `CLARIFICATION_NEEDED` |
| Spoken number, no name | `curl -s "localhost:8000/api/v1/agent/bookings?phone=9000000777" -H "Authorization: Bearer $AGENT" -H 'X-Call-Id: t' \| jq .outcome` | `NAME_REQUIRED` |

More scenarios with the seeded data: `SEED.md`. Every response carries `Server-Timing`
(database time and query count). A search should show 1–6 queries.

## What you can't test yet

- A live phone call: it needs a LiveKit agent and ContextForge (`LIVEKIT.md`, `CONTEXTFORGE.md`).
- A desk app: there isn't one. Staff actions (board, exceptions, notifications) are API calls
  with the staff token.
- Outbound SMS or WhatsApp: notifications are queued, not sent.
