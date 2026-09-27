"""Hermetic defaults: every Settings field is stripped from the environment before the
application is imported, so a developer's shell can never change what a test sees."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from frontdesk_api import locales
from frontdesk_api.config import Settings
from frontdesk_api.rollouts import read_env

for _field in Settings.model_fields:
    os.environ.pop(_field.upper(), None)

AGENT_TOKEN = "agent-token-for-tests-only"
STAFF_TOKEN = "staff-token-for-tests-only"
STAFF_SCOPES = ["bookings.staff", "schedule.write", "board.write", "directory.write", "knowledge.write", "calls.write",
                "calls.read"]
TOKENS = json.dumps({AGENT_TOKEN: ["agent"], STAFF_TOKEN: STAFF_SCOPES})

ROLLOUTS = Path(__file__).resolve().parents[3] / "rollouts"
DEMO_HOSPITAL = ROLLOUTS / "demo-hospital"
# The demo hospital's own settings file: tests run as that rollout unless they say otherwise.
DEMO_SETTINGS = {k.lower(): v for k, v in read_env(DEMO_HOSPITAL / "rollout.env").items()}


@pytest.fixture(scope="session")
def make_settings():
    def factory(**overrides) -> Settings:
        base = {
            **DEMO_SETTINGS,
            "rollout_dir": str(DEMO_HOSPITAL),
            "env": "test",
            "database_url": os.environ.get("TEST_DATABASE_URL", "postgresql://nobody:x@127.0.0.1:1/none"),
            "auth_tokens_json": TOKENS,
        }
        return Settings(**{**base, **overrides})

    return factory


@pytest.fixture(scope="session")
def settings(make_settings) -> Settings:
    return make_settings()


@pytest.fixture(autouse=True)
def _all_languages_after_each_test():
    """A test that switches languages (an app for another rollout) never leaks into the next."""
    yield
    locales.select(locales.AVAILABLE)
