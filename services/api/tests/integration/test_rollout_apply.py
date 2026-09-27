"""`rollout apply` writes core + domain + rollout: idempotent, the baseline owned by the pack, a
provider's own rows and choices kept, danger signs always on."""

from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import func, select

from frontdesk_api import packs, rollouts
from frontdesk_api.db import tables as t
from frontdesk_api.services import rollout_apply
from tests.conftest import DEMO_HOSPITAL

from .conftest import STAFF


def demo() -> rollouts.Composed:
    rollout = rollouts.load(DEMO_HOSPITAL)
    return rollouts.compose(packs.load(rollout.domain), rollout)


async def sources(session) -> dict[str, int]:
    rows = await session.execute(select(t.LexiconEntry.source, func.count()).group_by(t.LexiconEntry.source))
    return dict(rows.all())


async def test_apply_is_idempotent_and_tags_where_each_row_came_from(app, app_settings):
    async with app.state.sessionmaker() as session:
        first = await sources(session)
        await rollout_apply.apply(session, app_settings, demo())
        await session.commit()
        assert await sources(session) == first == {"DOMAIN_BASELINE": 194, "PROVIDER": 2}


async def test_a_baseline_row_the_pack_dropped_is_removed_and_the_providers_rows_stay(app, app_settings):
    composed = demo()
    dropped = next(row for row, source in composed.lexicon if source == rollouts.BASELINE)
    fewer = replace(composed, lexicon=tuple(item for item in composed.lexicon if item[0] != dropped))
    async with app.state.sessionmaker() as session:
        summary = await rollout_apply.apply(session, app_settings, fewer)
        await session.commit()
        assert summary["baselineRemoved"] == 1
        assert await sources(session) == {"DOMAIN_BASELINE": 193, "PROVIDER": 2}


async def test_a_switched_off_route_stays_off_but_a_danger_sign_comes_back(app, app_settings):
    async with app.state.sessionmaker() as session:
        route = await session.scalar(select(t.LexiconEntry).where(t.LexiconEntry.concept_type == "NEED_ROUTE"))
        flag = await session.scalar(select(t.LexiconEntry).where(t.LexiconEntry.concept_type == "RED_FLAG"))
        route.approved = flag.approved = False  # e.g. a direct database edit
        await session.commit()
        await rollout_apply.apply(session, app_settings, demo())
        await session.commit()
        await session.refresh(route)
        await session.refresh(flag)
        assert (route.approved, flag.approved) == (False, True)


async def test_staff_cannot_switch_off_a_domain_danger_sign(client, app):
    async with app.state.sessionmaker() as session:
        flag = await session.scalar(select(t.LexiconEntry).where(t.LexiconEntry.concept_type == "RED_FLAG"))
        route = await session.scalar(select(t.LexiconEntry).where(t.LexiconEntry.concept_type == "NEED_ROUTE"))
    body = {"conceptType": "RED_FLAG", "conceptId": flag.concept_id, "term": flag.term, "language": flag.language,
            "approved": False}
    refused = await client.post("/lexicon", json=body, headers=STAFF)
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "VALIDATION_FAILED", refused.text
    body = {"conceptType": "NEED_ROUTE", "conceptId": route.concept_id, "term": route.term,
            "language": route.language, "approved": False}
    allowed = await client.post("/lexicon", json=body, headers=STAFF)
    assert allowed.status_code == 201 and allowed.json()["source"] == "DOMAIN_BASELINE"


async def test_another_providers_rollout_is_refused(app, make_settings):
    other = make_settings(provider_id="hospital-b")
    async with app.state.sessionmaker() as session:
        with pytest.raises(ValueError, match="not this deployment's provider"):
            await rollout_apply.apply(session, other, demo())
