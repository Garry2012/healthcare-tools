"""The seed never duplicates the directory of a database seeded before migration 0002."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from frontdesk_api.seed import LegacyDemoData, load_directory


async def test_seed_refuses_pre_0002_demo_ids(app, app_settings):
    async with app.state.sessionmaker() as session:
        await session.execute(text("INSERT INTO resources (id, name) VALUES ('doc_garima', 'Dr. Garima')"))
        await session.commit()
        with pytest.raises(LegacyDemoData, match="seed --reset"):
            await load_directory(session, app_settings)
