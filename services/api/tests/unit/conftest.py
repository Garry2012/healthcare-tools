from __future__ import annotations

import pytest

from frontdesk_api import packs
from frontdesk_api.domain.resolver import CategoryEntry, Directory, LexiconTerm, ResourceEntry


@pytest.fixture(scope="session")
def directory() -> Directory:
    """The healthcare pack's synthetic directory, as the resolver sees it."""
    pack = packs.load("healthcare")
    return Directory(
        resources=tuple(
            ResourceEntry(
                resource_id=d.id, name=d.name, category_ids=d.categories, name_variants=d.variants,
                localized_names=tuple(d.localized.values()), booking_policy=d.policy,
            )
            for d in pack.resources
        ),
        categories=tuple(
            CategoryEntry(category_id=d.id, name=d.name, code=d.code, localized_names=tuple(d.localized.values()))
            for d in pack.categories
        ),
        lexicon=tuple(LexiconTerm(*row) for row in pack.lexicon),
    )


@pytest.fixture(scope="session")
def day_parts(directory):
    from frontdesk_api.domain.text import normalise

    return [(normalise(t.term), t.concept_id) for t in directory.terms("DAY_PART")]
