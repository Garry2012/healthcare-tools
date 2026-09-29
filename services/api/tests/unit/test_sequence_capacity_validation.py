"""Reject capacities that cannot produce positive HH:MM queue windows."""

import pytest

from frontdesk_api.schemas import TemplateSession, session_problems


@pytest.mark.parametrize(("mode", "value", "valid"), [
    ("PER_HOUR", 8, True), ("PER_HOUR", 9, True), ("PER_HOUR", 60, True),
    ("PER_HOUR", 61, False), ("FIXED", 180, True), ("FIXED", 181, False),
])
def test_sequence_capacity_must_fit_minute_precision(mode, value, valid):
    session = TemplateSession.model_validate({
        "templateSessionId": "morning", "daysOfWeek": ["MON"], "start": "09:00", "end": "12:00",
        "capacityModel": "SEQUENCE", "capacity": {"mode": mode, "value": value},
    })
    problems = session_problems([session])
    if valid:
        assert problems == []
    else:
        assert problems == [("sessions[0].capacity.value",
                             "SEQUENCE capacity must allow at least one minute per position.")]
