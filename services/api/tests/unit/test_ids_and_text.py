from __future__ import annotations

from datetime import date

from healthcare_api.domain import ids
from healthcare_api.domain.text import contains_phrase, normalise, transliterate


def test_session_and_slot_ids_round_trip():
    sid = ids.session_id("doc_garima", date(2026, 9, 26), 2)
    assert sid == "ses_doc_garima_2026-09-26_2"
    ref = ids.parse_session_id(sid)
    assert (ref.doctor_id, ref.date, ref.n) == ("doc_garima", date(2026, 9, 26), "2")
    slot = ids.parse_slot_id(ids.position_slot_id(sid, 4))
    assert slot.slot_id == "slot_ses_doc_garima_2026-09-26_2_04"
    assert slot.session.session_id == sid and slot.suffix == "04"
    timed = ids.parse_slot_id(ids.timed_slot_id("ses_doc_x_2026-09-26_e12", "15:30"))
    assert (timed.session.n, timed.suffix) == ("e12", "1530")


def test_malformed_ids_are_rejected():
    for bad in ["", "slot_", "slot_ses_x_2026-13-01_1_01", "ses_x_notadate_1", "slot_ses_doc_2026-09-26_1_ab"]:
        assert ids.parse_slot_id(bad) is None and ids.parse_session_id(bad) is None


def test_transliteration_and_normalisation():
    assert normalise("ಡಾ. ಗರಿಮಾ", strip_honorifics=True) == "garima"
    assert normalise("डॉ. गरिमा", strip_honorifics=True) == "garima"
    assert normalise("ನಾಳೆ ಸಂಜೆ") == "nale sanje"
    assert normalise("शाम") == "sham"
    assert transliterate("Dr Garima") == "Dr Garima"


def test_phrase_containment_is_whole_word():
    assert contains_phrase("i have chest pain", "chest pain")
    assert not contains_phrase("benefits", "fits")
