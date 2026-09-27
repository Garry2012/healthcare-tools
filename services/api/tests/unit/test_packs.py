"""The domain layer: every pack is valid domain data, and settings resolve core -> domain -> rollout."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from frontdesk_api import packs
from frontdesk_api.config import IDENTITY, Settings

PACKS = ("healthcare", "hospitality")


@pytest.mark.parametrize("name", PACKS)
def test_pack_is_valid(name):
    assert packs.validate(packs.load(name)) == []


@pytest.mark.parametrize("name", PACKS)
def test_a_pack_holds_no_tenant(name):
    """Resources, schedules and approved answers are a rollout's: a pack has nowhere to put them."""
    pack = packs.load(name)
    assert not {"resources", "knowledge", "scenario"} & set(vars(pack))
    assert not [row for row in pack.baseline if row[0] == "RESOURCE"]


def test_unknown_pack_is_refused():
    with pytest.raises(ValueError, match="Unknown DOMAIN_PACK"):
        packs.load("nonexistent")
    with pytest.raises(ValueError, match="not a valid pack name"):
        packs.load("../etc")


def test_validate_reports_what_a_baseline_may_not_hold():
    bad = packs.Pack(
        "bad", "1", "nowhere", {"desk": "Desk"}, {"GM": "General"},
        baseline=(
            ("CATEGORY", "cat_gm", "general doctor", "en"),  # a category id, not a code
            ("SERVICE_TRANSFER", "lab", "blood report", "en"),  # no such destination
            ("RESOURCE", "res_x", "dr x", "en"),  # a tenant's row
            ("RED_FLAG", "chest", "chest pain", "xx"),  # no language module
            ("RED_FLAG", "chest", "Chest Pain", "xx"),  # the same words twice
        ),
        settings={"timezone": "UTC"},
    )
    problems = "\n".join(packs.validate(bad))
    for expected in ("escalation 'nowhere'", "unknown category code 'cat_gm'", "unknown destination 'lab'",
                     "cannot carry RESOURCE", "no language module for 'xx'", "appears twice",
                     "'timezone' is not a tenant setting"):
        assert expected in problems


def test_the_domain_default_sits_between_core_and_rollout(make_settings):
    hotel = {"domain_pack": "hospitality", "provider_id": "demo-hotel"}
    assert make_settings().tenant_default_slot_minutes == 15  # core
    assert make_settings(**hotel).tenant_default_slot_minutes == 30  # domain
    assert make_settings(**hotel, tenant_default_slot_minutes=20).tenant_default_slot_minutes == 20  # rollout


def test_a_domain_cannot_default_identity(make_settings, monkeypatch):
    real = packs.load("healthcare")
    fake = packs.Pack(**{**vars(real), "settings": {"tenant_timezone": "Asia/Kolkata"}})
    monkeypatch.setattr(packs, "load", lambda name: fake)
    with pytest.raises(ValidationError, match="cannot default 'tenant_timezone'"):
        make_settings()


@pytest.mark.parametrize("field", sorted(IDENTITY))
def test_identity_has_no_default(make_settings, field):
    """A rollout that forgets who it is fails to start instead of inheriting another provider's values."""
    values = make_settings().model_dump()
    del values[field]
    with pytest.raises(ValidationError, match=field):
        Settings(**values)


def test_languages_must_have_a_module(make_settings):
    assert make_settings(tenant_supported_languages="en, hi").languages == ("en", "hi")
    with pytest.raises(ValidationError, match="no language module for ta"):
        make_settings(tenant_supported_languages="en,ta")


def test_unknown_timezone_is_a_validation_error_not_a_crash(make_settings):
    with pytest.raises(ValidationError, match="unknown IANA timezone"):
        make_settings(tenant_timezone="Mars/Base")
