"""The synthetic hospital must never land in a real provider's database."""

from __future__ import annotations

import pytest

from frontdesk_api.seed import SeedRefused, run


@pytest.mark.parametrize("reset", [False, True])
async def test_seed_refuses_to_run_in_production(make_settings, reset):
    # an unreachable database: the refusal must come before any connection is attempted
    settings = make_settings(env="production", database_url="postgresql://u:p@127.0.0.1:9/nowhere")
    with pytest.raises(SeedRefused, match="production"):
        await run(settings, reset=reset)
