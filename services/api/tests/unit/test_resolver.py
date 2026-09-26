"""Resolver golden cases (IMPLEMENTATION.md §2.3)."""

from __future__ import annotations

import pytest

from frontdesk_api.domain.resolver import resolve


def ask(directory, utterance, **kw):
    return resolve(utterance=utterance, directory=directory, **kw)


def test_named_doctor_exact(directory):
    res = ask(directory, "is Dr Garima in today", doctor_name="Dr Garima")
    assert res.action == "OFFER_SLOTS"
    assert [(m.doctor_id, m.matched_on, m.confidence) for m in res.doctors] == [("doc_garima", "NAME_EXACT", 1.0)]


def test_lower_case_name_without_title_resolves(directory):
    res = ask(directory, "garima", doctor_name="garima")
    assert [m.doctor_id for m in res.doctors] == ["doc_garima"]


@pytest.mark.parametrize("heard", ["gareema", "Garimaa", "Dr. Gaarima"])
def test_misspelt_name_resolves_phonetically(directory, heard):
    res = ask(directory, heard, doctor_name=heard)
    assert res.action == "OFFER_SLOTS"
    assert [m.doctor_id for m in res.doctors] == ["doc_garima"]
    assert res.doctors[0].matched_on in {"NAME_PHONETIC", "NAME_VARIANT"}


def test_phonetic_match_is_below_exact(directory):
    res = ask(directory, "Garimaa", doctor_name="Garimaa")
    assert res.doctors[0].matched_on == "NAME_PHONETIC"
    assert res.doctors[0].confidence < 1.0


@pytest.mark.parametrize("heard", ["ಡಾ. ಗರಿಮಾ", "ಗರಿಮಾ", "डॉ. गरिमा"])
def test_indic_script_name_resolves_to_the_same_doctor(directory, heard):
    res = ask(directory, f"{heard} ನಾಳೆ ಇದ್ದಾರಾ", doctor_name=heard)
    assert [m.doctor_id for m in res.doctors] == ["doc_garima"]


def test_name_found_in_kannada_utterance_without_doctor_name(directory):
    res = ask(directory, "ನಾಳೆ ಸಂಜೆ ಡಾಕ್ಟರ್ ಗರಿಮಾ ಇರ್ತಾರಾ")
    assert [m.doctor_id for m in res.doctors] == ["doc_garima"]


def test_lexicon_doctor_alias(directory):
    res = ask(directory, "garima madam", doctor_name="garima madam")
    assert [m.doctor_id for m in res.doctors] == ["doc_garima"]


def test_asr_damaged_department_asks_to_confirm_urology(directory):
    res = ask(directory, "I need a zoologist appointment", department="zoologist")
    assert res.action == "CLARIFY"
    assert res.clarification_type == "CONFIRM_INTERPRETATION"
    assert res.departments == []  # no direct match was accepted
    assert res.clarification_options[0] == ("department", "dept_uro")


def test_shared_surname_is_clarified(directory):
    res = ask(directory, "Dr Sharma please", doctor_name="Dr Sharma")
    assert res.action == "CLARIFY"
    assert res.clarification_type == "WHICH_DOCTOR"
    assert sorted(cid for _, cid in res.clarification_options) == ["doc_anil_sharma", "doc_ravi_sharma"]


def test_shared_surname_is_clarified_regardless_of_availability(directory):
    """Resolution runs over the whole directory before any date filter: Ravi Sharma has no
    session on Mondays, but the question is still WHICH_DOCTOR."""
    res = ask(directory, "Dr Sharma on Monday", doctor_name="Sharma")
    assert res.clarification_type == "WHICH_DOCTOR"
    assert len(res.clarification_options) == 2


def test_full_name_disambiguates(directory):
    res = ask(directory, "Dr Ravi Sharma", doctor_name="Ravi Sharma")
    assert [m.doctor_id for m in res.doctors] == ["doc_ravi_sharma"]


def test_symptom_route_thyroid_goes_to_general_medicine(directory):
    res = ask(directory, "I need a thyroid doctor", symptom_text="thyroid doctor")
    assert res.action == "OFFER_SLOTS"
    assert [(d.department_id, d.matched_on) for d in res.departments] == [("dept_genmed", "SYMPTOM_ROUTE")]


def test_department_phrase_inside_request(directory):
    res = ask(directory, "lady doctor for thyroid", department="lady doctor for thyroid")
    assert [d.department_id for d in res.departments] == ["dept_genmed"]


@pytest.mark.parametrize(("text", "dept"), [
    ("skin doctor", "dept_derm"),
    ("ಚರ್ಮ ವೈದ್ಯ", "dept_derm"),
    ("charm ka doctor", "dept_derm"),
    ("Dermatology", "dept_derm"),
    ("ಮಕ್ಕಳ ಡಾಕ್ಟರ್", "dept_paed"),
    ("दिल का डॉक्टर", "dept_cardio"),
])
def test_multilingual_department_terms(directory, text, dept):
    res = ask(directory, text, department=text)
    assert [d.department_id for d in res.departments] == [dept]


@pytest.mark.parametrize("utterance", [
    "my father has chest pain, I want to book Dr Garima",
    "ಅಪ್ಪನಿಗೆ ಎದೆ ನೋವು",
    "पापा को सीने में दर्द है",
    "she is having fits since morning",
    "labour pains started",
])
def test_red_flag_transfers_before_anything_else(directory, utterance):
    res = ask(directory, utterance, doctor_name="Dr Garima")
    assert res.action == "TRANSFER_EMERGENCY"
    assert res.doctors == [] and res.departments == []


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


def test_doctor_outside_stated_department_is_confirmed(directory):
    res = ask(directory, "Dr Garima skin doctor", doctor_name="Dr Garima", department="skin doctor")
    assert res.action == "CLARIFY" and res.clarification_type == "CONFIRM_INTERPRETATION"


def test_unknown_department_is_no_service(directory):
    res = ask(directory, "I need a veterinarian", department="veterinarian")
    assert res.action == "NO_SERVICE"


def test_anyone_available_has_no_filter(directory):
    res = ask(directory, "anyone available right now?")
    assert res.action == "OFFER_SLOTS" and res.doctors == [] and res.departments == []


def test_unapproved_terms_are_ignored(directory):
    from dataclasses import replace

    from frontdesk_api.domain.resolver import LexiconTerm

    unapproved = replace(directory, lexicon=(LexiconTerm("RED_FLAG", "x", "hiccups", "en", approved=False),))
    assert resolve(utterance="I have hiccups", directory=unapproved).action != "TRANSFER_EMERGENCY"
