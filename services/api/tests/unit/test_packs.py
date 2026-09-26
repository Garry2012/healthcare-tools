"""Every domain pack is valid data, and the same core resolves each domain's words."""

from __future__ import annotations

import pytest

from frontdesk_api import packs
from frontdesk_api.domain.resolver import CategoryEntry, Directory, LexiconTerm, ResourceEntry, resolve

PACKS = ("healthcare", "hospitality")


def directory_of(pack: packs.Pack) -> Directory:
    return Directory(
        resources=tuple(ResourceEntry(resource_id=r.id, name=r.name, category_ids=r.categories,
                                      name_variants=r.variants, localized_names=tuple(r.localized.values()),
                                      booking_policy=r.policy) for r in pack.resources),
        categories=tuple(CategoryEntry(category_id=c.id, name=c.name, code=c.code,
                                       localized_names=tuple(c.localized.values()),
                                       offers_bookings=c.offers_bookings) for c in pack.categories),
        lexicon=tuple(LexiconTerm(*row) for row in pack.lexicon),
    )


@pytest.mark.parametrize("name", PACKS)
def test_pack_is_valid(name):
    assert packs.validate(packs.load(name)) == []


def test_unknown_pack_is_refused():
    with pytest.raises(ValueError, match="Unknown DOMAIN_PACK"):
        packs.load("nonexistent")
    with pytest.raises(ValueError, match="not a valid pack name"):
        packs.load("../etc")


def test_validate_reports_dangling_references():
    bad = packs.Pack("bad", "nowhere", {"desk": "Desk"}, (), (packs.ResourceSeed("res_x", "X", ("cat_missing",)),),
                     (("CATEGORY", "cat_missing", "x", "en"),))
    problems = packs.validate(bad)
    assert any("escalation" in p for p in problems)
    assert any("unknown category" in p for p in problems)
    assert any("lexicon" in p for p in problems)


@pytest.mark.parametrize(("utterance", "fields", "action", "category"), [
    ("I want a massage tomorrow", {"category": "massage"}, "OFFER_SLOTS", "cat_spa"),
    ("table for dinner tonight", {"category": "table for dinner"}, "OFFER_SLOTS", "cat_dining"),
    ("my back pain is bad", {"need_text": "back pain"}, "OFFER_SLOTS", "cat_spa"),
    ("there is smoke in the room", {}, "TRANSFER_EMERGENCY", None),
    ("I need more towels", {}, "TRANSFER_DESK", None),
])
def test_hospitality_words_resolve_with_the_same_core(utterance, fields, action, category):
    res = resolve(utterance=utterance, directory=directory_of(packs.load("hospitality")), **fields)
    assert res.action == action
    if category:
        assert [d.category_id for d in res.categories] == [category]
