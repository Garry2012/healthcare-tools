"""Hermetic defaults: every Settings field is stripped from the environment before the
application is imported, so a developer's shell can never change what a test sees."""

from __future__ import annotations

import json
import os

import pytest

from healthcare_api.config import Settings

for _field in Settings.model_fields:
    os.environ.pop(_field.upper(), None)

AGENT_TOKEN = "agent-token-for-tests-only"
STAFF_TOKEN = "staff-token-for-tests-only"
STAFF_SCOPES = ["appointments.staff", "schedule.write", "board.write", "directory.write", "calls.write", "calls.read"]
TOKENS = json.dumps({AGENT_TOKEN: ["agent"], STAFF_TOKEN: STAFF_SCOPES})


@pytest.fixture(scope="session")
def make_settings():
    def factory(**overrides) -> Settings:
        base = {
            "env": "test",
            "database_url": os.environ.get("TEST_DATABASE_URL", "postgresql://nobody:x@127.0.0.1:1/none"),
            "auth_tokens_json": TOKENS,
        }
        return Settings(**{**base, **overrides})

    return factory


@pytest.fixture(scope="session")
def settings(make_settings) -> Settings:
    return make_settings()
