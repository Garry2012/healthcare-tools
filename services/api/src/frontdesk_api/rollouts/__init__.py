"""Rollouts: the third layer of core -> domain -> rollout (docs/architecture/TARGET.md A10).

A rollout is one provider's instance of one domain, written down as files and nothing else
(`model`): the settings it changes, its data, and the calls it must handle. `compose` joins it
with its domain pack; `check` validates it offline; `services.rollout_apply` writes it.
"""

from __future__ import annotations

from .check import Report, validate
from .compose import BASELINE, ROLLOUT, Composed, compose
from .model import Category, Dialogue, Knowledge, Resource, Rollout, RolloutError, Session, load, read_env

__all__ = [
    "BASELINE", "ROLLOUT", "Category", "Composed", "Dialogue", "Knowledge", "Report", "Resource", "Rollout",
    "RolloutError", "Session", "compose", "load", "read_env", "validate",
]
