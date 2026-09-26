"""What the resolver does when it cannot name a doctor or department: it must not guess a
doctor for words it did not understand, and must not let a person's name hide the department
the caller asked for (PO review, tech-lead N5)."""

from __future__ import annotations

import pytest

from frontdesk_api.domain.resolver import resolve


@pytest.mark.parametrize("utterance", [
    "is any doctor available right now",
    "koi doctor abhi hai kya",
    "anyone free tomorrow evening",
    "ಈಗ ಯಾರಾದರೂ ಡಾಕ್ಟರ್ ಇದ್ದಾರಾ",
])
def test_anyone_available_is_offered(directory, utterance):
    assert resolve(utterance=utterance, directory=directory).action == "OFFER_SLOTS"


@pytest.mark.parametrize("utterance", [
    "ರಿಪೋರ್ಟ್ ಬೇಕು",                 # "I need my report"
    "I want to talk about my bill",
    "mujhe apna x-ray chahiye",
])
def test_words_not_understood_are_never_answered_with_a_doctor(directory, utterance):
    res = resolve(utterance=utterance, directory=directory)
    assert res.action in {"NO_SERVICE", "TRANSFER_DESK", "CLARIFY"}
    assert res.resources == []


def test_pharmacy_in_romanised_hindi_goes_to_the_pharmacy(directory):
    res = resolve(utterance="dawai ki dukan khuli hai kya", directory=directory)
    assert (res.action, res.destination) == ("TRANSFER_DESK", "pharmacy")


@pytest.mark.parametrize("utterance", [
    "this is Kiran Hegde's father, need a heart doctor",
    "Hi, I am Garima, need a skin doctor for my son",
])
def test_a_name_in_the_sentence_does_not_override_the_department_asked_for(directory, utterance):
    res = resolve(utterance=utterance, directory=directory)
    assert res.action == "CLARIFY" and res.clarification_type == "CONFIRM_INTERPRETATION"


def test_a_named_doctor_with_reports_to_show_is_still_that_doctor(directory):
    res = resolve(utterance="Dr Garima, I have my reports to show", directory=directory, resource_name="Dr Garima")
    assert res.action == "OFFER_SLOTS" and [m.resource_id for m in res.resources] == ["res_garima"]
