"""Golden cases for knowledge retrieval (TARGET.md A4) over the healthcare pack's answers."""

from __future__ import annotations

import pytest

from frontdesk_api import packs
from frontdesk_api.domain.knowledge import Entry, Hit, LexicalIndex, Thresholds, decide, pick_answer


@pytest.fixture(scope="module")
def index() -> LexicalIndex:
    pack = packs.load("healthcare")
    return LexicalIndex.build(Entry(k.id, k.topic, k.questions, k.answers, k.action, k.destination)
                              for k in pack.knowledge)


def ask(index: LexicalIndex, question: str):
    return decide(index.search(question), Thresholds())


@pytest.mark.parametrize(("question", "entry_id"), [
    ("what are the visiting hours", "kb_visiting_hours"),
    ("is there parking near the hospital", "kb_parking"),
    ("ಪಾರ್ಕಿಂಗ್ ಇದೆಯಾ", "kb_parking"),                       # Kannada script
    ("पार्किंग है क्या", "kb_parking"),                        # Devanagari
    ("hospital kab khulta hai", "kb_opd_hours"),             # romanised Hindi
    ("ಆಸ್ಪತ್ರೆ ಎಲ್ಲಿದೆ", "kb_location"),
    ("मरीज़ से मिलने का समय क्या है", "kb_visiting_hours"),
    ("when will my blood report come", "kb_lab_reports"),
    ("is the medical shop open at night", "kb_pharmacy_hours"),
    ("how much is the consultation fee", "kb_consultation_fee"),
    ("फीस कितनी है", "kb_consultation_fee"),
])
def test_answers_across_languages_and_scripts(index, question, entry_id):
    decision = ask(index, question)
    assert decision.outcome == "ANSWERED"
    assert decision.hit.entry.entry_id == entry_id


def test_vague_question_is_clarified_not_guessed(index):
    decision = ask(index, "what time")
    assert decision.outcome == "CLARIFICATION_NEEDED"
    assert {h.entry.entry_id for h in decision.options} >= {"kb_visiting_hours", "kb_opd_hours"}


@pytest.mark.parametrize("question", ["I want to book an appointment", "tell me a joke", ""])
def test_unrelated_question_has_no_answer(index, question):
    assert ask(index, question).outcome == "NO_ANSWER"


def test_transfer_entry_keeps_its_destination(index):
    decision = ask(index, "do you accept cashless insurance")
    assert decision.hit.entry.action == "TRANSFER_DESK" and decision.hit.entry.destination == "insurance"


def test_close_runner_up_blocks_an_answer():
    a, b = Entry("a", "t", ("q",), {"en": "A"}), Entry("b", "t", ("q",), {"en": "B"})
    assert decide([Hit(a, 0.8, "q"), Hit(b, 0.75, "q")], Thresholds()).outcome == "CLARIFICATION_NEEDED"
    assert decide([Hit(a, 0.8, "q"), Hit(b, 0.5, "q")], Thresholds()).outcome == "ANSWERED"


def test_answer_language_falls_back_to_english_never_translates():
    entry = Entry("x", "t", ("q",), {"en": "English", "kn": "ಕನ್ನಡ"})
    assert pick_answer(entry, "kn") == ("kn", "ಕನ್ನಡ")
    assert pick_answer(entry, "kn-IN") == ("kn", "ಕನ್ನಡ")
    assert pick_answer(entry, "ta") == ("en", "English")
    assert pick_answer(Entry("y", "t", ("q",), {"hi": "हिंदी"}), "ta") == ("hi", "हिंदी")


def test_empty_index_never_raises():
    assert LexicalIndex.build([]).search("anything") == []


@pytest.mark.parametrize(("question", "not_this"), [
    ("is there a cancellation fee for surgery", "kb_cancel_policy"),
    ("send the report to my email address", "kb_location"),
    ("what is the blood bank address", "kb_location"),
    ("visiting hours for ICU", "kb_visiting_hours"),
])
def test_a_specific_word_the_answers_do_not_cover_is_confirmed_not_answered(index, question, not_this):
    """A stored phrase inside a longer question is not proof: 'visiting hours for ICU' may not be
    the ward's hours. Confirm instead of speaking an approved answer to a different question."""
    decision = ask(index, question)
    assert decision.outcome != "ANSWERED" or decision.hit.entry.entry_id != not_this


@pytest.mark.parametrize(("question", "entry_id"), [
    ("is there parking near the hospital", "kb_parking"),
    ("please tell me the visiting hours", "kb_visiting_hours"),
])
def test_ordinary_filler_words_still_get_the_answer(index, question, entry_id):
    decision = ask(index, question)
    assert decision.outcome == "ANSWERED" and decision.hit.entry.entry_id == entry_id


def test_clarification_label_is_the_entrys_question_in_the_callers_script():
    """PO review 13: a clarifying option read 'gaadi kahan park karein' to an English caller."""
    from frontdesk_api.domain.knowledge import option_label

    parking = Entry("kb_parking", "parking",
                    ("parking", "gaadi kahan park karein", "ಪಾರ್ಕಿಂಗ್ ಇದೆಯಾ", "पार्किंग है क्या"), {"en": "x"})
    assert option_label(parking, "en") == "parking"
    assert option_label(parking, "kn") == "ಪಾರ್ಕಿಂಗ್ ಇದೆಯಾ"
    assert option_label(parking, "hi") == "पार्किंग है क्या"
    only_latin = Entry("kb_x", "x", ("visiting hours", "patient se milne ka time"), {"en": "x"})
    assert option_label(only_latin, "kn") == "visiting hours"
