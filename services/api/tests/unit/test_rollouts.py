"""The rollout layer: core + domain pack + one provider's files. A second provider of the same
domain is its own files, nothing else; the domain pack and the core never change for it."""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest

from frontdesk_api import locales, packs, rollouts
from frontdesk_api.config import IDENTITY, Settings
from frontdesk_api.domain.dates import resolve_when
from frontdesk_api.domain.resolver import resolve
from frontdesk_api.domain.text import normalise
from tests.conftest import DEMO_HOSPITAL, ROLLOUTS

COMMITTED = sorted(p.name for p in ROLLOUTS.iterdir() if (p / "rollout.env").is_file())


def check(directory: Path) -> rollouts.Report:
    rollout = rollouts.load(directory)
    settings = Settings(**{k.lower(): v for k, v in rollout.settings.items()})
    composed = rollouts.compose(settings.pack, rollout)
    return rollouts.validate(composed, settings.transfer_destinations, settings.thresholds,
                             settings.knowledge_thresholds)


def copy_demo(tmp_path: Path, **env: str) -> Path:
    """The demo hospital's data under another provider's settings (Hospital B)."""
    target = tmp_path / "hospital-b"
    shutil.copytree(DEMO_HOSPITAL, target)
    (target / "dialogues.yaml").unlink()
    lines = [f"{k}={v}" for k, v in {**rollouts.read_env(DEMO_HOSPITAL / "rollout.env"), **env}.items()]
    (target / "rollout.env").write_text("\n".join(lines) + "\n")
    return target


@pytest.mark.parametrize("name", COMMITTED)
def test_committed_rollouts_are_valid_and_pass_their_dialogues(name):
    report = check(ROLLOUTS / name)
    assert report.problems == ()
    assert rollouts.load(ROLLOUTS / name).dialogues, "a committed rollout carries acceptance dialogues"


@pytest.mark.parametrize("name", COMMITTED)
def test_rollout_files_write_only_differences(name):
    """Anything a rollout writes that equals the domain or core default is copy-and-modify residue."""
    written = {k.lower(): v for k, v in rollouts.read_env(ROLLOUTS / name / "rollout.env").items()}
    settings = Settings(**written)
    for key, value in written.items():
        if key in IDENTITY:
            continue
        without = Settings(**{k: v for k, v in written.items() if k != key})
        assert getattr(without, key) != getattr(settings, key), f"{name}: {key}={value} is already the default"


def test_a_second_hospital_is_its_own_files_only(tmp_path):
    """Hospital B: English and Hindi, no Kannada. Same domain pack, no code or pack change."""
    b = copy_demo(tmp_path, PROVIDER_ID="hospital-b", TENANT_SUPPORTED_LANGUAGES="en,hi")
    data = (b / "data.yaml").read_text()
    (b / "data.yaml").write_text("\n".join(line for line in data.splitlines() if "language: kn}" not in line))
    rollout = rollouts.load(b)
    composed = rollouts.compose(packs.load("healthcare"), rollout)
    assert {row[3] for row, _ in composed.lexicon if row[0] != "RED_FLAG"} == {"en", "hi"}
    assert check(b).problems == ()

    locales.select(rollout.languages)
    directory = composed.directory()
    assert resolve(utterance="सीने में दर्द", directory=directory).action == "TRANSFER_EMERGENCY"
    assert resolve(utterance="ಹೊಟ್ಟೆ ನೋವು", directory=directory).action == "NO_SERVICE"  # Kannada is off
    today = date(2026, 9, 23)
    assert resolve_when(today=today, expression="paanch tareekh").date_from == date(2026, 10, 5)
    assert resolve_when(today=today, expression="ಐದು ತಾರೀಖು").resolved is False


def test_the_languages_a_rollout_selects_are_the_ones_understood():
    today = date(2026, 9, 23)
    locales.select(("en", "kn"))
    assert resolve_when(today=today, expression="aidu tareekh").date_from == date(2026, 10, 5)
    assert resolve_when(today=today, expression="ನಾಳೆ ಸಂಜೆ").day_part == "EVENING"
    locales.select(("en",))
    assert resolve_when(today=today, expression="aidu tareekh").resolved is False
    assert resolve_when(today=today, expression="tomorrow evening").day_part == "EVENING"


def test_a_rollout_term_re_points_a_baseline_route_but_never_a_danger_sign(tmp_path):
    b = copy_demo(tmp_path)
    data = (b / "data.yaml").read_text()
    data = data.replace("categories:\n", "categories:\n  - {id: cat_endo, code: ENDO, name: Endocrinology}\n", 1)
    data = data.replace("terms:\n", "terms:\n  - {type: NEED_ROUTE, target: cat_endo, term: thyroid, language: en}\n"
                                    "  - {type: NEED_ROUTE, target: cat_genmed, term: chest pain, language: en}\n", 1)
    (b / "data.yaml").write_text(data)
    composed = rollouts.compose(packs.load("healthcare"), rollouts.load(b))
    rows = {(kind, target, normalise(term)) for (kind, target, term, language), _ in composed.lexicon}
    assert ("NEED_ROUTE", "cat_endo", "thyroid") in rows
    assert ("NEED_ROUTE", "cat_genmed", "thyroid") not in rows
    assert any(kind == "RED_FLAG" and term == "chest pain" for kind, _, term in rows)
    assert resolve(utterance="chest pain", directory=composed.directory()).action == "TRANSFER_EMERGENCY"


def test_a_domain_code_with_no_department_is_a_note_not_an_error(tmp_path):
    b = copy_demo(tmp_path)
    data = (b / "data.yaml").read_text().replace("    code: URO\n", "    code: KIDNEY\n")
    (b / "data.yaml").write_text(data)
    report = check(b)
    assert report.problems == ()
    assert any("'URO'" in note for note in report.notes)


def test_problems_name_what_is_wrong(tmp_path):
    b = copy_demo(tmp_path, TENANT_SUPPORTED_LANGUAGES="en,hi")
    data = (b / "data.yaml").read_text()
    data = data.replace("categories: [cat_uro]", "categories: [cat_nephro]")
    data = data.replace("destination: insurance", "destination: radiology")
    (b / "data.yaml").write_text(data)
    (b / "dialogues.yaml").write_text('- {say: "chest pain", expect: OFFER_SLOTS}\n')
    problems = "\n".join(check(b).problems)
    assert "unknown category 'cat_nephro'" in problems
    assert "unknown destination 'radiology'" in problems
    assert "'ಗರಿಮಾ ಮೇಡಂ' is in 'kn', which this rollout does not switch on" in problems


def test_a_failing_dialogue_fails_the_rollout(tmp_path):
    b = copy_demo(tmp_path)
    (b / "dialogues.yaml").write_text('- {say: "chest pain", expect: OFFER_SLOTS}\n')
    assert check(b).problems == ("say 'chest pain': expected OFFER_SLOTS , got TRANSFER_EMERGENCY ",)


@pytest.mark.parametrize(("edit", "message"), [
    (("resources:\n", "resources:\n  - {id: res_x, name: X, categories: [cat_genmed], colour: blue}\n"),
     "unknown field(s) colour"),
    (("start: '10:00'", "start: 10:00"), "write start and end in quotes"),  # YAML reads 10:00 as 600
    (("knowledge:\n", "wards:\n"), "unknown section(s) wards"),
])
def test_files_are_read_strictly(tmp_path, edit, message):
    b = copy_demo(tmp_path)
    (b / "data.yaml").write_text((b / "data.yaml").read_text().replace(*edit, 1))
    with pytest.raises(rollouts.RolloutError, match=message.replace("(", r"\(").replace(")", r"\)")):
        rollouts.load(b)


def test_a_rollout_file_holds_only_known_non_secret_settings():
    from frontdesk_api.rollout_cli import file_problems

    assert file_problems({"PROVIDER_ID": "x", "TENANT_DISPLAY_NAME": "Demo Hospital"}) == []
    problems = file_problems({"TENANT_TIMEZOEN": "UTC", "DATABASE_URL": "postgresql://…", "PORT": "8000"})
    assert problems == ["TENANT_TIMEZOEN is not a setting (a typo?)",
                        "DATABASE_URL is a secret: keep it in the secret store, never in rollout.env",
                        "PORT is set by the deployment (compose, deploy.sh), not by a rollout"]


@pytest.mark.parametrize("languages", [("kn", "hi"), ("hi",), ("en",)])
def test_danger_signs_are_on_in_every_language_whatever_the_rollout_serves(languages):
    """Callers code-switch: "my father has chest pain" from a Kannada caller, "ಎದೆ ನೋವು" at an
    English-only desk. Switching a language off never switches its emergencies off."""
    from dataclasses import replace

    pack = packs.load("healthcare")
    rollout = replace(rollouts.load(DEMO_HOSPITAL), languages=languages, terms=())
    composed = rollouts.compose(pack, rollout)
    flags = {row for row, _ in composed.lexicon if row[0] == "RED_FLAG"}
    assert flags == {row for row in pack.baseline if row[0] == "RED_FLAG"}
    locales.select(languages)
    directory = composed.directory()
    for utterance in ("my father has chest pain", "he collapsed, not breathing", "ಎದೆ ನೋವು", "सीने में दर्द"):
        assert resolve(utterance=utterance, directory=directory).action == "TRANSFER_EMERGENCY", utterance


def test_a_rollout_may_add_a_danger_sign_in_any_language(tmp_path):
    b = copy_demo(tmp_path, TENANT_SUPPORTED_LANGUAGES="en,hi")
    data = (b / "data.yaml").read_text().replace("language: kn}", "language: hi}")
    data = data.replace("terms:\n", "terms:\n  - {type: RED_FLAG, target: chest, term: ನೆಂಜು ನೋವು, language: kn}\n", 1)
    (b / "data.yaml").write_text(data)
    assert check(b).problems == ()
