"""What LiveKit hands the tools, in both voice modes, for English, Hindi and Kannada.

Cascade (STT -> LLM -> TTS): the model forwards the transcript: native script, romanised
text, code-mixed sentences, numbers as digits or as words. Speech-to-speech (GPT realtime):
the model often renders the caller in English itself ("I need a children's doctor").
Either way the date must be the one the caller meant, or a question - never a wrong date.
"""

from __future__ import annotations

from datetime import date

import pytest

from frontdesk_api.domain.dates import resolve_when
from frontdesk_api.domain.resolver import resolve

WEDNESDAY = date(2026, 9, 23)


@pytest.mark.parametrize(("expression", "expected"), [
    ("5th October", date(2026, 10, 5)),
    ("fifth of October", date(2026, 10, 5)),
    ("October the fifth", date(2026, 10, 5)),
    ("twenty first October", date(2026, 10, 21)),
    ("twenty-first of October", date(2026, 10, 21)),
    ("October thirty first", date(2026, 10, 31)),
    ("पाँच तारीख", date(2026, 10, 5)),
    ("paanch tareekh", date(2026, 10, 5)),
    ("पच्चीस तारीख", date(2026, 9, 25)),
    ("ಐದು ತಾರೀಖು", date(2026, 10, 5)),
    ("ಐದನೇ ತಾರೀಖು", date(2026, 10, 5)),
    ("aidu tareekh", date(2026, 10, 5)),
    ("ಇಪ್ಪತ್ತೈದು ತಾರೀಖು", date(2026, 9, 25)),
    ("ಅಕ್ಟೋಬರ್ ಐದು", date(2026, 10, 5)),
])
def test_dates_said_as_number_words(expression, expected, day_parts):
    r = resolve_when(today=WEDNESDAY, expression=expression, day_parts=day_parts)
    assert (r.resolved, r.date_from, r.date_to) == (True, expected, expected)


@pytest.mark.parametrize("expression", ["thirty second of October", "32 tareekh", "बत्तीस अक्टूबर"])
def test_an_impossible_day_is_asked_not_guessed(expression, day_parts):
    r = resolve_when(today=WEDNESDAY, expression=expression, day_parts=day_parts)
    assert r.resolved is False


def test_a_number_word_away_from_a_month_is_not_a_date(day_parts):
    # "ek doctor" is "a doctor", not the 1st
    r = resolve_when(today=WEDNESDAY, utterance="mujhe ek doctor chahiye kal", day_parts=day_parts)
    assert r.date_from == date(2026, 9, 24)


@pytest.mark.parametrize(("utterance", "category", "need", "expected"), [
    ("I need a children's doctor", "children's doctor", None, "cat_paed"),
    ("my child's doctor", "child's doctor", None, None),
    ("I have stomach pain", None, "stomach pain", "cat_genmed"),
    ("pet mein dard hai", None, "pet mein dard", "cat_genmed"),
    ("पेट में दर्द है", None, "पेट में दर्द", "cat_genmed"),
    ("ಹೊಟ್ಟೆ ನೋವು", None, "ಹೊಟ್ಟೆ ನೋವು", "cat_genmed"),
    ("cough and cold for three days", None, "cough and cold", "cat_genmed"),
    ("ಕೆಮ್ಮು ನೆಗಡಿ", None, "ಕೆಮ್ಮು ನೆಗಡಿ", "cat_genmed"),
    ("khansi zukam", None, "khansi zukam", "cat_genmed"),
    ("back pain", None, "back pain", "cat_ortho"),
    ("ಬೆನ್ನು ನೋವು", None, "ಬೆನ್ನು ನೋವು", "cat_ortho"),
    ("kamar dard", None, "kamar dard", "cat_ortho"),
    ("sir dard ho raha hai", None, "sir dard", "cat_genmed"),
    ("ತಲೆ ನೋವು", None, "ತಲೆ ನೋವು", "cat_genmed"),
])
def test_what_callers_ask_for_reaches_a_department(directory, utterance, category, need, expected):
    r = resolve(utterance=utterance, directory=directory, category=category, need_text=need)
    if expected is None:
        assert r.action != "TRANSFER_EMERGENCY"
        return
    assert r.action == "OFFER_SLOTS" and [c.category_id for c in r.categories] == [expected]


@pytest.mark.parametrize("utterance", [
    "my father has severe chest pain", "ಅಪ್ಪನಿಗೆ chest pain", "seene mein dard ho raha hai",
    "ಎದೆ ನೋವು ಜಾಸ್ತಿ ಇದೆ", "सीने में दर्द", "he is not breathing properly",
])
def test_emergencies_in_every_language_and_mix(directory, utterance):
    assert resolve(utterance=utterance, directory=directory).action == "TRANSFER_EMERGENCY"
