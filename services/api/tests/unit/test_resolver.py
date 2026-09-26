"""Resolver golden cases (IMPLEMENTATION.md §2.3)."""

from __future__ import annotations

import pytest

from frontdesk_api.domain.resolver import resolve


def ask(directory, utterance, **kw):
    return resolve(utterance=utterance, directory=directory, **kw)


def test_named_resource_exact(directory):
    res = ask(directory, "is Dr Garima in today", resource_name="Dr Garima")
    assert res.action == "OFFER_SLOTS"
    assert [(m.resource_id, m.matched_on, m.confidence) for m in res.resources] == [("res_garima", "NAME_EXACT", 1.0)]


def test_lower_case_name_without_title_resolves(directory):
    res = ask(directory, "garima", resource_name="garima")
    assert [m.resource_id for m in res.resources] == ["res_garima"]


@pytest.mark.parametrize("heard", ["gareema", "Garimaa", "Dr. Gaarima"])
def test_misspelt_name_resolves_phonetically(directory, heard):
    res = ask(directory, heard, resource_name=heard)
    assert res.action == "OFFER_SLOTS"
    assert [m.resource_id for m in res.resources] == ["res_garima"]
    assert res.resources[0].matched_on in {"NAME_PHONETIC", "NAME_VARIANT"}


def test_phonetic_match_is_below_exact(directory):
    res = ask(directory, "Garimaa", resource_name="Garimaa")
    assert res.resources[0].matched_on == "NAME_PHONETIC"
    assert res.resources[0].confidence < 1.0


@pytest.mark.parametrize("heard", ["ಡಾ. ಗರಿಮಾ", "ಗರಿಮಾ", "डॉ. गरिमा"])
def test_indic_script_name_resolves_to_the_same_resource(directory, heard):
    res = ask(directory, f"{heard} ನಾಳೆ ಇದ್ದಾರಾ", resource_name=heard)
    assert [m.resource_id for m in res.resources] == ["res_garima"]


def test_name_found_in_kannada_utterance_without_resource_name(directory):
    res = ask(directory, "ನಾಳೆ ಸಂಜೆ ಡಾಕ್ಟರ್ ಗರಿಮಾ ಇರ್ತಾರಾ")
    assert [m.resource_id for m in res.resources] == ["res_garima"]


def test_lexicon_resource_alias(directory):
    res = ask(directory, "garima madam", resource_name="garima madam")
    assert [m.resource_id for m in res.resources] == ["res_garima"]


def test_asr_damaged_category_asks_to_confirm_urology(directory):
    res = ask(directory, "I need a zoologist appointment", category="zoologist")
    assert res.action == "CLARIFY"
    assert res.clarification_type == "CONFIRM_INTERPRETATION"
    assert res.categories == []  # no direct match was accepted
    assert res.clarification_options[0] == ("category", "cat_uro")


def test_shared_surname_is_clarified(directory):
    res = ask(directory, "Dr Sharma please", resource_name="Dr Sharma")
    assert res.action == "CLARIFY"
    assert res.clarification_type == "WHICH_RESOURCE"
    assert sorted(cid for _, cid in res.clarification_options) == ["res_anil_sharma", "res_ravi_sharma"]


def test_shared_surname_is_clarified_regardless_of_availability(directory):
    """Resolution runs over the whole directory before any date filter: Ravi Sharma has no
    session on Mondays, but the question is still WHICH_RESOURCE."""
    res = ask(directory, "Dr Sharma on Monday", resource_name="Sharma")
    assert res.clarification_type == "WHICH_RESOURCE"
    assert len(res.clarification_options) == 2


def test_full_name_disambiguates(directory):
    res = ask(directory, "Dr Ravi Sharma", resource_name="Ravi Sharma")
    assert [m.resource_id for m in res.resources] == ["res_ravi_sharma"]


def test_need_route_thyroid_goes_to_general_medicine(directory):
    res = ask(directory, "I need a thyroid doctor", need_text="thyroid doctor")
    assert res.action == "OFFER_SLOTS"
    assert [(d.category_id, d.matched_on) for d in res.categories] == [("cat_genmed", "NEED_ROUTE")]


def test_category_phrase_inside_request(directory):
    res = ask(directory, "lady doctor for thyroid", category="lady doctor for thyroid")
    assert [d.category_id for d in res.categories] == ["cat_genmed"]


@pytest.mark.parametrize(("text", "cat"), [
    ("skin doctor", "cat_derm"),
    ("ಚರ್ಮ ವೈದ್ಯ", "cat_derm"),
    ("charm ka doctor", "cat_derm"),
    ("Dermatology", "cat_derm"),
    ("ಮಕ್ಕಳ ಡಾಕ್ಟರ್", "cat_paed"),
    ("दिल का डॉक्टर", "cat_cardio"),
])
def test_multilingual_category_terms(directory, text, cat):
    res = ask(directory, text, category=text)
    assert [d.category_id for d in res.categories] == [cat]


@pytest.mark.parametrize("utterance", [
    "my father has chest pain, I want to book Dr Garima",
    "ಅಪ್ಪನಿಗೆ ಎದೆ ನೋವು",
    "पापा को सीने में दर्द है",
    "she is having fits since morning",
    "labour pains started",
])
def test_red_flag_transfers_before_anything_else(directory, utterance):
    res = ask(directory, utterance, resource_name="Dr Garima")
    assert res.action == "TRANSFER_EMERGENCY"
    assert res.resources == [] and res.categories == []


def test_red_flag_wins_over_service_transfer(directory):
    assert ask(directory, "blood report and chest pain").action == "TRANSFER_EMERGENCY"


@pytest.mark.parametrize(("utterance", "destination"), [
    ("I want my blood report", "lab"),
    ("is the pharmacy open", "pharmacy"),
    ("cashless insurance approval", "insurance"),
    ("ರಕ್ತ ಪರೀಕ್ಷೆ ರಿಪೋರ್ಟ್ ಬೇಕು", "lab"),
])
def test_service_requests_transfer_to_the_desk(directory, utterance, destination):
    res = ask(directory, utterance)
    assert (res.action, res.destination) == ("TRANSFER_DESK", destination)


def test_resource_outside_stated_category_is_confirmed(directory):
    res = ask(directory, "Dr Garima skin doctor", resource_name="Dr Garima", category="skin doctor")
    assert res.action == "CLARIFY" and res.clarification_type == "CONFIRM_INTERPRETATION"


def test_unknown_category_is_no_service(directory):
    res = ask(directory, "I need a veterinarian", category="veterinarian")
    assert res.action == "NO_SERVICE"


def test_anyone_available_has_no_filter(directory):
    res = ask(directory, "anyone available right now?")
    assert res.action == "OFFER_SLOTS" and res.resources == [] and res.categories == []


def test_unapproved_terms_are_ignored(directory):
    from dataclasses import replace

    from frontdesk_api.domain.resolver import LexiconTerm

    unapproved = replace(directory, lexicon=(LexiconTerm("RED_FLAG", "x", "hiccups", "en", approved=False),))
    assert resolve(utterance="I have hiccups", directory=unapproved).action != "TRANSFER_EMERGENCY"
