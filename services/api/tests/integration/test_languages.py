"""English, Hindi and Kannada through the real agent endpoints, as LiveKit sends them.

Cascade mode forwards the speech-to-text transcript (native script, romanised, code-mixed,
numbers as words). Speech-to-speech mode (GPT realtime) often writes the arguments in
English itself. The clock is fixed at Wednesday 23 September 2026, 10:00 IST.
"""

from __future__ import annotations

import pytest

from .conftest import call


async def search(client, **body):
    r = await client.post("/agent/availability-search", headers=call(), json=body)
    assert r.status_code == 200, r.text
    return r.json()


def slot_dates(body):
    return {s["date"] for r in body["results"] for s in r["sessions"]}


@pytest.mark.parametrize(("language", "utterance", "name", "expression"), [
    ("kn", "ಐದು ತಾರೀಖು ಡಾಕ್ಟರ್ ಗರಿಮಾ ಸಿಗ್ತಾರಾ", "ಡಾಕ್ಟರ್ ಗರಿಮಾ", "ಐದು ತಾರೀಖು"),      # cascade, Kannada script
    ("kn", "aidu tareekh garima madam sigtara", "garima madam", "aidu tareekh"),       # cascade, romanised
    ("hi", "पाँच तारीख को डॉक्टर गरिमा मिलेंगी", "डॉक्टर गरिमा", "पाँच तारीख"),          # cascade, Devanagari
    ("en", "Is Dr Garima available on the fifth of October?", "Dr Garima", "fifth of October"),  # S2S English
])
async def test_a_date_said_in_words_finds_that_day(client, language, utterance, name, expression):
    body = await search(client, utterance=utterance, language=language, resourceName=name,
                        when={"expression": expression})
    assert body["outcome"] == "FOUND" and body["understood"]["dates"] == {"from": "2026-10-05", "to": "2026-10-05"}
    assert slot_dates(body) == {"2026-10-05"}


@pytest.mark.parametrize(("language", "utterance", "fields", "category"), [
    ("en", "I need a children's doctor tomorrow", {"category": "children's doctor"}, "cat_paed"),  # S2S
    ("kn", "ನಾಳೆ ಬೆಳಿಗ್ಗೆ ಮಕ್ಕಳ ಡಾಕ್ಟರ್", {"category": "ಮಕ್ಕಳ ಡಾಕ್ಟರ್"}, "cat_paed"),
    ("hi", "pet mein dard hai, kal dikhana hai", {"needText": "pet mein dard"}, "cat_genmed"),
    ("kn", "ಹೊಟ್ಟೆ ನೋವು, tomorrow morning", {"needText": "ಹೊಟ್ಟೆ ನೋವು"}, "cat_genmed"),  # code-mixed
])
async def test_what_the_caller_needs_reaches_a_department(client, language, utterance, fields, category):
    body = await search(client, utterance=utterance, language=language, **fields)
    assert body["routing"]["action"] == "OFFER_SLOTS", body
    assert [c["id"] for c in body["understood"]["categories"]] == [category]


@pytest.mark.parametrize(("language", "utterance"), [
    ("en", "my father has severe chest pain"), ("hi", "सीने में दर्द हो रहा है"),
    ("kn", "ಎದೆ ನೋವು ಜಾಸ್ತಿ ಇದೆ"), ("kn", "ಅಪ್ಪನಿಗೆ chest pain"),
])
async def test_emergencies_transfer_in_every_language(client, language, utterance):
    body = await search(client, utterance=utterance, language=language)
    assert body["routing"]["action"] == "TRANSFER_EMERGENCY"


@pytest.mark.parametrize(("language", "question", "entry"), [
    ("hi", "अस्पताल कहाँ है", "kb_location"),
    ("hi", "hospital kahan hai", "kb_location"),
    ("kn", "ಪಾರ್ಕಿಂಗ್ ಇದೆಯಾ", "kb_parking"),
    ("en", "Where is the hospital?", "kb_location"),
])
async def test_approved_answers_come_back_in_the_callers_language(client, language, question, entry):
    r = await client.post("/agent/knowledge-search", headers=call(), json={"question": question, "language": language})
    body = r.json()
    assert body["outcome"] == "ANSWERED" and body["answer"]["entryId"] == entry
    assert body["answer"]["language"] == language
