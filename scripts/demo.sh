#!/usr/bin/env bash
# Demo against the dev stack (`make up && make seed`): a Kannada-speaking caller asks for
# "Dr Garima tomorrow evening", books, looks the booking up, moves it, and cancels it.
# Uses the agent token from AUTH_TOKENS_JSON. Needs curl and jq.
set -euo pipefail
# Against a deployed API (e.g. Azure): API_URL=https://<api-host>/api/v1 AGENT_TOKEN=<agent token> ./scripts/demo.sh
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -z "${API_URL:-}" || -z "${AGENT_TOKEN:-}" ]]; then
  set -a; . "$ROOT/.env"; set +a
fi
API="${API_URL:-http://127.0.0.1:${API_HOST_PORT:-8000}/api/v1}"
AGENT="${AGENT_TOKEN:-$(jq -r 'to_entries | map(select(.value | index("agent"))) | .[0].key' <<<"$AUTH_TOKENS_JSON")}"
CALL="demo-$(date +%s)"
CALLER="+919000000777"
CUSTOMER='{"name":"Demo Customer","phone":"9000000777","relationToCaller":"SELF"}'
H=(-sS -H "Authorization: Bearer $AGENT" -H "X-Call-Id: $CALL" -H "X-Caller-Number: $CALLER"
   -H "Content-Type: application/json")

step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
first_slot() { jq -r '[.results[].sessions[].slots[]? | select(.available) | .slotId] | .[0] // empty'; }

step "1. find_availability — 'ನಾಳೆ ಸಂಜೆ ಡಾಕ್ಟರ್ ಗರಿಮಾ ಇರ್ತಾರಾ' (is Dr Garima in tomorrow evening?)"
SEARCH=$(curl "${H[@]}" -X POST "$API/agent/availability-search" -d '{
  "utterance": "ನಾಳೆ ಸಂಜೆ ಡಾಕ್ಟರ್ ಗರಿಮಾ ಇರ್ತಾರಾ", "language": "kn",
  "resourceName": "ಡಾ. ಗರಿಮಾ", "when": {"expression": "ನಾಳೆ ಸಂಜೆ"}}')
jq . <<<"$SEARCH"
SLOT=$(first_slot <<<"$SEARCH")

if [[ -z "$SLOT" ]]; then
  NEXT=$(jq -r '[.results[].unavailable[]?.nextBookable.date // empty] | .[0] // empty' <<<"$SEARCH")
  [[ -n "$NEXT" ]] || { echo "no bookable session in the horizon; run 'make seed-reset'"; exit 1; }
  step "1b. Not tomorrow evening — the server offered the next bookable date ($NEXT); search it"
  SEARCH=$(curl "${H[@]}" -X POST "$API/agent/availability-search" -d "{
    \"utterance\": \"ಡಾಕ್ಟರ್ ಗರಿಮಾ\", \"language\": \"kn\", \"resourceName\": \"ಡಾ. ಗರಿಮಾ\",
    \"when\": {\"dateFrom\": \"$NEXT\"}}")
  jq . <<<"$SEARCH"
  SLOT=$(first_slot <<<"$SEARCH")
fi
NEW_SLOT=$(jq -r --arg s "$SLOT" '[.results[].sessions[].slots[]? | select(.available and .slotId != $s) | .slotId] | .[0]' <<<"$SEARCH")

step "2. manage_booking BOOK $SLOT"
BOOKED=$(curl "${H[@]}" -H "Idempotency-Key: $CALL-book" -X POST "$API/agent/bookings" \
  -d "{\"slotId\": \"$SLOT\", \"customer\": $CUSTOMER, \"language\": \"kn\", \"reasonVerbatim\": \"ಜ್ವರ ಮೂರು ದಿನದಿಂದ\"}")
jq . <<<"$BOOKED"
APPT=$(jq -r .bookingId <<<"$BOOKED")

step "3. manage_booking LIST (caller number from X-Caller-Number)"
curl "${H[@]}" "$API/agent/bookings?customerName=Demo%20Customer" | jq .

step "4. manage_booking RESCHEDULE $APPT → $NEW_SLOT"
curl "${H[@]}" -H "Idempotency-Key: $CALL-move" -X POST "$API/agent/bookings/$APPT/reschedule" \
  -d "{\"customerName\": \"Demo Customer\", \"newSlotId\": \"$NEW_SLOT\"}" | jq .

step "5. manage_booking CANCEL $APPT"
curl "${H[@]}" -H "Idempotency-Key: $CALL-cancel" -X POST "$API/agent/bookings/$APPT/cancel" \
  -d '{"customerName": "Demo Customer", "reasonVerbatim": "ಬೇರೆ ದಿನ ಬರುತ್ತೇನೆ"}' | jq .
