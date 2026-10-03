"""Static checks for the reviewer-identified contract wording errors; not runtime tests."""
from pathlib import Path

text = Path('docs/handover/VOICE-TEAM.md').read_text()
checks = {
    "callback summary exclusions": "CALLBACK_NOTED rejects appointmentId and transferredTo",
    'availability ambiguity is directory-only': 'get_doctor_availability.outcome.CLARIFICATION_NEEDED` | Multiple directory matches',
    'knowledge clarification is owner text': 'search_knowledge.outcome.CLARIFICATION_NEEDED` | Knowledge-service clarification text',
    'availability not-found is directory-only': 'get_doctor_availability.outcome.NOT_FOUND` | No matching doctor or department',
    'booking not-found is verified caller scope': 'manage_booking.outcome.NOT_FOUND` | No matching verified-caller appointment',
    'staleness is owner supplied': 'Owner-supplied board staleness flag',
    'expiry is today-only with status exclusions': 'Today-only end-time expiry; false for CANCELLED/UNKNOWN',
}
for name, fragment in checks.items():
    print(('PASS' if fragment in text else 'FAIL') + ': ' + name)
raise SystemExit(0 if all(fragment in text for fragment in checks.values()) else 1)
