from __future__ import annotations

from datetime import date

from frontdesk_api.domain import ids
from frontdesk_api.domain.text import contains_phrase, normalise, transliterate


def test_session_and_slot_ids_round_trip():
    sid = ids.session_id("res_garima", date(2026, 9, 26), 2)
    assert sid == "ses_res_garima_2026-09-26_2"
    ref = ids.parse_session_id(sid)
    assert (ref.resource_id, ref.date, ref.n) == ("res_garima", date(2026, 9, 26), "2")
    slot = ids.parse_slot_id(ids.position_slot_id(sid, 4))
    assert slot.slot_id == "slot_ses_res_garima_2026-09-26_2_04"
    assert slot.session.session_id == sid and slot.suffix == "04"
    timed = ids.parse_slot_id(ids.timed_slot_id("ses_res_x_2026-09-26_e12", "15:30"))
    assert (timed.session.n, timed.suffix) == ("e12", "1530")


def test_malformed_ids_are_rejected():
    for bad in ["", "slot_", "slot_ses_x_2026-13-01_1_01", "ses_x_notadate_1", "slot_ses_res_2026-09-26_1_ab"]:
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


def test_periods_overlap_only_when_they_share_time():
    from datetime import time

    from frontdesk_api.domain.intervals import overlaps, weekly_clash

    assert overlaps(time(9), time(12), time(11), time(13))
    assert not overlaps(time(9), time(12), time(12), time(15))  # touching ends is not a clash
    assert overlaps("09:00", "12:00", "10:00", "11:00")  # HH:MM strings order the same way
    assert weekly_clash(["MON", "TUE"], "09:00", "12:00", ["TUE"], "11:00", "13:00")
    assert not weekly_clash(["MON"], "09:00", "12:00", ["TUE"], "09:00", "12:00")


def test_chandrabindu_is_a_nasal_not_a_word_break():
    """'पाँच' (five) split into 'pa ch'; every Hindi word with ँ did (कहाँ, हाँ, माँ)."""
    from frontdesk_api.domain.text import normalise

    assert normalise("पाँच") == normalise("पांच") == "panch"
    assert normalise("अस्पताल कहाँ है") == "aspatal kahan hai"  # meets the romanised 'kahan'
    assert len(normalise("हाँ जी").split()) == 2


def test_an_english_possessive_is_the_word_itself():
    """Speech-to-speech models say "a children's doctor"; the lexicon has "children doctor"."""
    from frontdesk_api.domain.text import native_form, normalise

    assert normalise("children's doctor") == normalise("children’s doctor") == "children doctor"
    assert native_form("Garima's") == "garima"
    assert normalise("D'Souza") == "d souza"  # not a possessive
