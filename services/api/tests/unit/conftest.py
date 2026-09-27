from __future__ import annotations

import pytest

from frontdesk_api import packs, rollouts
from frontdesk_api.domain.resolver import Directory
from tests.conftest import DEMO_HOSPITAL


@pytest.fixture(scope="session")
def demo_hospital() -> rollouts.Composed:
    """The healthcare domain composed with the demo hospital rollout, as `rollout apply` writes it."""
    rollout = rollouts.load(DEMO_HOSPITAL)
    return rollouts.compose(packs.load(rollout.domain), rollout)


@pytest.fixture(scope="session")
def directory(demo_hospital) -> Directory:
    """The demo hospital's directory, as the resolver sees it."""
    return demo_hospital.directory()


@pytest.fixture(scope="session")
def day_parts(directory):
    from frontdesk_api.domain.text import normalise

    return [(normalise(t.term), t.concept_id) for t in directory.terms("DAY_PART")]
