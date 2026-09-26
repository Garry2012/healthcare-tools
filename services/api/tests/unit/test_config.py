"""Settings derived from the environment."""

from __future__ import annotations

import pytest


@pytest.mark.parametrize(("given", "expected"), [
    # Azure Database for PostgreSQL and Supabase hand out libpq URLs with sslmode; asyncpg calls it ssl.
    ("postgresql://u:p@db.example.com:5432/frontdesk?sslmode=require",
     "postgresql+asyncpg://u:p@db.example.com:5432/frontdesk?ssl=require"),
    ("postgres://u:p@h/db?sslmode=verify-full&application_name=x",
     "postgresql+asyncpg://u:p@h/db?ssl=verify-full&application_name=x"),
    ("postgresql://u:p@h/db?ssl=require", "postgresql+asyncpg://u:p@h/db?ssl=require"),
    ("postgresql://u:p@h/db", "postgresql+asyncpg://u:p@h/db"),
])
def test_libpq_sslmode_becomes_asyncpg_ssl(make_settings, given, expected):
    assert make_settings(database_url=given).async_database_url == expected
