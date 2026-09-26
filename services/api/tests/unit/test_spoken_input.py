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
    ("the fifth of October", date(2026, 10, 5)),
    ("October the fifth", date(2026, 10, 5)),
    ("October fifth", date(2026, 10, 5)),
    ("twenty first October", date(2026, 10, 21)),
    ("twenty-first of October", date(2026, 10, 21)),
    ("October thirty first", date(2026, 10, 31)),
    ("पाँच तारीख", date(2026, 10, 5)),
    ("paanch tareekh", date(2026, 10, 5)),
    ("पच्चीस तारीख", date(2026, 9, 25)),
    ("do tareekh", date(2026, 10, 2)),
    ("ಐದು ತಾರೀಖು", date(2026, 10, 5)),
    ("ಐದನೇ ತಾರೀಖು", date(2026, 10, 5)),
    ("aidu tareekh", date(2026, 10, 5)),
    ("ಇಪ್ಪತ್ತೈದು ತಾರೀಖು", date(2026, 9, 25)),
    ("ಅಕ್ಟೋಬರ್ ಐದನೇ", date(2026, 10, 5)),
    ("5 tareekh November", date(2026, 11, 5)),      # the month said with it, not the next 5th
    ("paanch tareekh november", date(2026, 11, 5)),
])
def test_dates_said_as_number_words(expression, expected, day_parts):
    r = resolve_when(today=WEDNESDAY, expression=expression, day_parts=day_parts)
    assert (r.resolved, r.date_from, r.date_to) == (True, expected, expected)


# Reviewers' cases: an ordinary sentence must never become an exact date the caller did not say.
@pytest.mark.parametrize(("utterance", "expected"), [
    ("book me one appointment tomorrow", date(2026, 9, 24)),
    ("tomorrow for me one slot", date(2026, 9, 24)),
    ("I am coming tomorrow, it's for me, one person", date(2026, 9, 24)),
    ("kal subah me ek slot chahiye", date(2026, 9, 24)),
    ("kal shaam me do baje aana hai", date(2026, 9, 24)),
    ("kal subah, mai ek report laaunga", date(2026, 9, 24)),
    ("aaj shaam mai ek baar aaunga", date(2026, 9, 23)),
    ("naale sanje me ondu appointment", date(2026, 9, 24)),
    ("can you see me first tomorrow", date(2026, 9, 24)),
    ("I want the second one. May I book it tomorrow", date(2026, 9, 24)),
    ("fever since the first. May I come tomorrow?", date(2026, 9, 24)),
    ("Dr Rao at ten? May I come tomorrow", date(2026, 9, 24)),
    ("I'll come at ten, may be tomorrow", date(2026, 9, 24)),
])
def test_ordinary_words_are_not_dates(utterance, expected, day_parts):
    r = resolve_when(today=WEDNESDAY, utterance=utterance, day_parts=day_parts)
    assert (r.date_from, r.date_to) == (expected, expected)


@pytest.mark.parametrize(("expression", "expected"), [
    # digits keep exactly their old meaning; a following time is not part of the day
    ("October 20 3 pm", date(2026, 10, 20)),
    ("May 20 5 pm", date(2027, 5, 20)),
    ("October 30, 2 pm", date(2026, 10, 30)),
    ("could you do May 5th", date(2027, 5, 5)),
    ("can we do October 12", date(2026, 10, 12)),
    ("give me a second, March 5", date(2027, 3, 5)),
    ("Sat, October 10", date(2026, 10, 10)),
])
def test_digits_next_to_a_month_mean_what_they_always_meant(expression, expected, day_parts):
    r = resolve_when(today=WEDNESDAY, expression=expression, day_parts=day_parts)
    assert (r.resolved, r.date_from) == (True, expected)


@pytest.mark.parametrize("expression", [
    "thirty second of October", "32 tareekh", "31 tarikh november",  # impossible
    "ek tareekh ko nahi, das tareekh",                 # two different days said
    "do teen tareekh",                                 # "the 2nd or 3rd"
    "October twenty, two pm", "October twenty one patient",  # a tens word without an ordinal
    "October first week", "ಅಕ್ಟೋಬರ್ ಒಂದು ವಾರ",          # a number that is not the day
    "give me two slots", "mai do din baad aaunga",
])
def test_an_unclear_day_is_asked_not_guessed(expression, day_parts):
    r = resolve_when(today=WEDNESDAY, expression=expression, day_parts=day_parts)
    assert r.resolved is False, (r.date_from, r.date_to)


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


# Voice-safety review: an everyday complaint route must never capture a danger sign.
@pytest.mark.parametrize("utterance", [
    "worst headache of my life", "sudden severe headache", "headache with neck stiffness",
    "headache and vomiting", "ತುಂಬಾ ತಲೆ ನೋವು ವಾಂತಿ", "headache after a fall", "head injury headache",
    "headache and blurred vision and my face is drooping", "headache, cannot speak properly",
    "stomach pain and vomiting blood", "stomach pain with blood in stool", "pet mein dard aur khoon ki ulti",
    "पेट में दर्द और खून की उल्टी", "ಹೊಟ್ಟೆ ನೋವು ರಕ್ತ ವಾಂತಿ", "cough with blood", "khansi mein khoon", "ಕೆಮ್ಮು ರಕ್ತ",
    "back pain cannot move legs", "back pain and numbness in legs", "cough and breathing problem",
    "child cough breathing fast", "cold and sweating chest pressure", "a cold sweat and fainting",
    "ತಲೆಗೆ ಪೆಟ್ಟು ಆಗಿದೆ",
])
def test_danger_signs_with_a_common_complaint_are_emergencies(directory, utterance):
    assert resolve(utterance=utterance, directory=directory, need_text=utterance).action == "TRANSFER_EMERGENCY"


@pytest.mark.parametrize("utterance", [
    "severe stomach pain", "severe headache", "bahut tez sir dard", "ತಲೆ ನೋವು ಜಾಸ್ತಿ", "ತುಂಬಾ ತಲೆ ನೋವು",
    "back pain after a fall", "back pain after an accident", "kamar dard gir gaya", "ಬಿದ್ದು ಬೆನ್ನು ನೋವು",
    # Hindi "sir" (head) is also the English filler "sir", so these are exact phrases to the desk
    "sir dard aur ulti", "sir mein chot lagi", "सिर में चोट",
])
def test_severity_or_a_fall_goes_to_a_person_not_a_slot(directory, utterance):
    r = resolve(utterance=utterance, directory=directory, need_text=utterance)
    assert (r.action, r.destination) in {("TRANSFER_DESK", "desk"), ("TRANSFER_EMERGENCY", None)}, r


@pytest.mark.parametrize("utterance", [
    "stomach pain, I am pregnant", "pet dard pregnant", "my child has stomach pain", "baby cough",
    "i feel cold and weak and confused",
])
def test_pregnancy_or_a_child_is_never_sent_straight_to_general_medicine(directory, utterance):
    r = resolve(utterance=utterance, directory=directory, need_text=utterance)
    assert not (r.action == "OFFER_SLOTS" and [c.category_id for c in r.categories] == ["cat_genmed"]), r


@pytest.mark.parametrize("utterance", [
    "when will my blood test report come", "blood report", "khoon ki jaanch", "I fell asleep in the waiting room",
    "cough and cold for three days", "I have a headache since morning",
])
def test_ordinary_requests_are_not_emergencies(directory, utterance):
    assert resolve(utterance=utterance, directory=directory).action != "TRANSFER_EMERGENCY"
