from __future__ import annotations

import pytest

from healthcare_api import seed_data
from healthcare_api.domain.resolver import DepartmentEntry, Directory, DoctorEntry, LexiconTerm


@pytest.fixture(scope="session")
def directory() -> Directory:
    """The seed's synthetic directory, as the resolver sees it."""
    return Directory(
        doctors=tuple(
            DoctorEntry(
                doctor_id=d.id, name=d.name, department_ids=d.departments, name_variants=d.variants,
                localized_names=tuple(x for x in (d.kn, d.hi) if x), booking_policy=d.policy,
            )
            for d in seed_data.DOCTORS
        ),
        departments=tuple(
            DepartmentEntry(department_id=d.id, name=d.name, code=d.code, localized_names=(d.kn, d.hi))
            for d in seed_data.DEPARTMENTS
        ),
        lexicon=tuple(LexiconTerm(*row) for row in seed_data.LEXICON),
    )


@pytest.fixture(scope="session")
def day_parts(directory):
    from healthcare_api.domain.text import normalise

    return [(normalise(t.term), t.concept_id) for t in directory.terms("DAY_PART")]
