from __future__ import annotations

import pytest

from frontdesk_api import seed_data
from frontdesk_api.domain.resolver import CategoryEntry, Directory, LexiconTerm, ResourceEntry


@pytest.fixture(scope="session")
def directory() -> Directory:
    """The seed's synthetic directory, as the resolver sees it."""
    return Directory(
        resources=tuple(
            ResourceEntry(
                resource_id=d.id, name=d.name, category_ids=d.categories, name_variants=d.variants,
                localized_names=tuple(x for x in (d.kn, d.hi) if x), booking_policy=d.policy,
            )
            for d in seed_data.RESOURCES
        ),
        categories=tuple(
            CategoryEntry(category_id=d.id, name=d.name, code=d.code, localized_names=(d.kn, d.hi))
            for d in seed_data.CATEGORIES
        ),
        lexicon=tuple(LexiconTerm(*row) for row in seed_data.LEXICON),
    )


@pytest.fixture(scope="session")
def day_parts(directory):
    from frontdesk_api.domain.text import normalise

    return [(normalise(t.term), t.concept_id) for t in directory.terms("DAY_PART")]
