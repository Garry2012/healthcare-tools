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
    "anyone free on 10/5",
    "koi doctor 5 tareekh ko milega",
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


def _without(directory, resource_id):
    from dataclasses import replace

    return replace(directory, resources=tuple(
        replace(d, active=False) if d.resource_id == resource_id else d for d in directory.resources))


@pytest.mark.parametrize("name", ["Kiran Hegde", "Dr Kiran Hegde", "ಡಾ. ಕಿರಣ್ ಹೆಗ್ಡೆ"])
def test_a_departed_doctor_leads_to_their_department_not_a_guess(directory, name):
    """PO review 3: after Dr Kiran Hegde (urology) left, his name was 'corrected' to Obstetrics."""
    gone = _without(directory, "res_kiran_hegde")
    res = resolve(utterance=f"I want to see {name}", resource_name=name, directory=gone)
    assert res.action == "OFFER_SLOTS" and res.resources == []
    assert res.departed == "res_kiran_hegde"
    assert [c.category_id for c in res.categories] == ["cat_uro"]
    assert res.categories[0].matched_on == "FORMER_RESOURCE"


def test_a_departed_doctor_is_never_matched_by_sound_alone(directory):
    gone = _without(directory, "res_kiran_hegde")
    res = resolve(utterance="Dr Keeran Hedge", resource_name="Dr Keeran Hedge", directory=gone)
    assert res.departed is None


def test_a_persons_name_is_not_spell_corrected_into_a_department(directory):
    res = resolve(utterance="I want to see Dr Hegdey Kiranov", resource_name="Dr Hegdey Kiranov",
                  directory=_without(directory, "res_kiran_hegde"))
    assert res.action == "NO_SERVICE" and res.clarification_options == []


@pytest.mark.parametrize(("name", "category"), [
    ("dermatalogy", "cat_derm"), ("cardiolgy", "cat_cardio"),
])
def test_a_misspelt_department_in_the_name_field_is_still_suggested(directory, name, category):
    """Tech-lead review: the model sometimes puts a department word in resourceName. Only a name
    said as a person's ("Dr …") is kept out of the spelling suggestions."""
    res = resolve(utterance=f"{name} doctor", resource_name=name, directory=directory)
    assert res.action == "CLARIFY" and ("category", category) in res.clarification_options


def test_a_departed_doctor_named_only_in_the_sentence_is_recognised(directory):
    gone = _without(directory, "res_kiran_hegde")
    res = resolve(utterance="I want to see Dr Kiran Hegde", directory=gone)
    assert res.departed == "res_kiran_hegde" and [c.category_id for c in res.categories] == ["cat_uro"]


def test_a_departed_doctor_whose_department_closed_still_says_so(directory):
    from dataclasses import replace

    gone = _without(directory, "res_kiran_hegde")
    gone = replace(gone, categories=tuple(replace(c, active=False) if c.category_id == "cat_uro" else c
                                          for c in gone.categories))
    res = resolve(utterance="Dr Kiran Hegde", resource_name="Dr Kiran Hegde", directory=gone)
    assert res.departed == "res_kiran_hegde" and res.categories == [] and res.action == "OFFER_SLOTS"


def test_two_departed_namesakes_are_still_reported(directory):
    from dataclasses import replace

    twin = replace(next(d for d in directory.resources if d.resource_id == "res_kiran_hegde"),
                   resource_id="res_kiran_hegde_2", active=False)
    gone = _without(directory, "res_kiran_hegde")
    gone = replace(gone, resources=(*gone.resources, twin))
    res = resolve(utterance="Kiran Hegde", resource_name="Kiran Hegde", directory=gone)
    assert res.departed in {"res_kiran_hegde", "res_kiran_hegde_2"}
    assert [c.category_id for c in res.categories] == ["cat_uro"]
