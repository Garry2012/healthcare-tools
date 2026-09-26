"""Alembic plumbing shared by the CLI (`migrate`) and readiness (`/ready`)."""

from __future__ import annotations

import os
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def alembic_ini() -> Path:
    """ALEMBIC_INI, else ./alembic.ini (the container's /app), else the source checkout."""
    candidates = [
        Path(os.environ["ALEMBIC_INI"]) if os.environ.get("ALEMBIC_INI") else None,
        Path.cwd() / "alembic.ini",
        Path(__file__).resolve().parents[2] / "alembic.ini",
    ]
    for path in candidates:
        if path is not None and path.is_file():
            return path
    raise FileNotFoundError("alembic.ini not found; set ALEMBIC_INI")


def config(database_url: str | None = None) -> Config:
    cfg = Config(str(alembic_ini()))
    cfg.attributes["configure_logger"] = False
    if database_url:
        cfg.attributes["database_url"] = database_url
    return cfg


def code_head() -> str:
    head = ScriptDirectory.from_config(config()).get_current_head()
    if head is None:
        raise RuntimeError("no Alembic revisions found")
    return head
