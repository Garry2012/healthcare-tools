"""A rollout as it is written down: `rollouts/<id>/` (or a private repository's copy).

    rollout.env     settings that differ from the domain and core defaults (non-secret)
    data.yaml       this provider's categories, resources, schedules, local terms, approved answers
    dialogues.yaml  acceptance lines: what a caller says and what must happen (optional)

Nothing here is code; `load` only reads and type-checks the files.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml

from ..packs import LexiconRow


class RolloutError(ValueError):
    """A rollout's files cannot be read as a rollout."""


@dataclass(frozen=True)
class Category:
    id: str
    code: str  # the domain's category code (its words reach this category), or the rollout's own
    name: str
    names: dict[str, str] = field(default_factory=dict)  # language -> approved spoken name
    bookable: bool = True


@dataclass(frozen=True)
class Session:
    key: str  # suffix of the templateSessionId
    label: str
    days: tuple[str, ...]
    start: str
    end: str
    mode: str = "PER_HOUR"
    value: int | None = 4
    model: str = "SEQUENCE"
    slot_minutes: int | None = None
    reserve: int = 25


@dataclass(frozen=True)
class Resource:
    id: str
    name: str
    categories: tuple[str, ...]
    names: dict[str, str] = field(default_factory=dict)
    gender: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    price: int | None = None
    price_confirmed: bool = True
    attendance: str = "REGULAR"
    policy: str = "BOOKABLE"
    data_confirmed: bool = True
    variants: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    sessions: tuple[Session, ...] = ()


@dataclass(frozen=True)
class Knowledge:
    """One approved answer. `questions` are ways callers ask, in any language or script."""

    id: str
    topic: str
    questions: tuple[str, ...]
    answers: dict[str, str]  # language -> approved spoken answer
    action: str = "ANSWER"  # ANSWER | TRANSFER_DESK
    destination: str | None = None


@dataclass(frozen=True)
class Dialogue:
    """An acceptance line, checked offline by `frontdesk-api rollout validate`."""

    expect: str  # a routing action (OFFER_SLOTS, CLARIFY, TRANSFER_EMERGENCY, ...) or a knowledge outcome
    say: str | None = None  # what the caller says, as find_availability receives it
    ask: str | None = None  # a general question, as search_knowledge receives it
    language: str = "en"
    resource_name: str | None = None
    category: str | None = None
    need_text: str | None = None
    expect_category: str | None = None
    expect_resource: str | None = None
    expect_answer: str | None = None  # knowledge entry id


@dataclass(frozen=True)
class Rollout:
    id: str
    domain: str
    languages: tuple[str, ...]
    settings: dict[str, str]  # rollout.env, as written (KEY -> value)
    categories: tuple[Category, ...] = ()
    resources: tuple[Resource, ...] = ()
    terms: tuple[LexiconRow, ...] = ()  # (concept_type, target, term, language): target is an id
    knowledge: tuple[Knowledge, ...] = ()
    dialogues: tuple[Dialogue, ...] = ()


def read_env(path: Path) -> dict[str, str]:
    """KEY=value lines, as docker --env-file reads them (no quoting, no expansion)."""
    values: dict[str, str] = {}
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not key.strip():
            raise RolloutError(f"{path.name}:{n}: expected KEY=value")
        values[key.strip()] = value
    return values


def _build(cls: type, raw: Any, where: str) -> Any:
    if not isinstance(raw, dict):
        raise RolloutError(f"{where}: expected a mapping")
    known = {f.name for f in fields(cls)}
    if unknown := sorted(set(raw) - known):
        raise RolloutError(f"{where}: unknown field(s) {', '.join(unknown)}")
    values = {k: tuple(v) if isinstance(v, list) else v for k, v in raw.items()}
    try:
        return cls(**values)
    except TypeError as exc:
        raise RolloutError(f"{where}: {exc}") from None


def _session(raw: Any, where: str) -> Session:
    session = _build(Session, raw, where)
    if not (isinstance(session.start, str) and isinstance(session.end, str)):
        raise RolloutError(f"{where}: write start and end in quotes ('09:00'), or YAML reads them as numbers")
    return session


def _resource(raw: Any, where: str) -> Resource:
    resource = _build(Resource, raw, where)
    sessions = tuple(_session(s, f"{where}.sessions[{i}]") for i, s in enumerate(resource.sessions))
    return Resource(**{**{f.name: getattr(resource, f.name) for f in fields(Resource)}, "sessions": sessions})


def _yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise RolloutError(f"{path.name}: {exc}") from None


def load(directory: str | Path) -> Rollout:
    root = Path(directory)
    env_file, data_file, dialogues_file = root / "rollout.env", root / "data.yaml", root / "dialogues.yaml"
    for required in (env_file, data_file):
        if not required.is_file():
            raise RolloutError(f"{root}: missing {required.name}")
    settings = read_env(env_file)
    missing = [k for k in ("PROVIDER_ID", "DOMAIN_PACK", "TENANT_SUPPORTED_LANGUAGES") if not settings.get(k)]
    if missing:
        raise RolloutError(f"rollout.env: {', '.join(missing)} must be set")

    data = _yaml(data_file) or {}
    if not isinstance(data, dict):
        raise RolloutError("data.yaml: expected a mapping")
    if unknown := sorted(set(data) - {"categories", "resources", "terms", "knowledge"}):
        raise RolloutError(f"data.yaml: unknown section(s) {', '.join(unknown)}")
    terms = []
    for i, row in enumerate(data.get("terms") or ()):
        if not isinstance(row, dict) or set(row) != {"type", "target", "term", "language"}:
            raise RolloutError(f"data.yaml terms[{i}]: needs exactly type, target, term and language")
        terms.append((row["type"], row["target"], row["term"], row["language"]))
    dialogues = _yaml(dialogues_file) if dialogues_file.is_file() else None
    return Rollout(
        id=settings["PROVIDER_ID"],
        domain=settings["DOMAIN_PACK"],
        languages=tuple(code.strip() for code in settings["TENANT_SUPPORTED_LANGUAGES"].split(",") if code.strip()),
        settings=settings,
        categories=tuple(_build(Category, c, f"data.yaml categories[{i}]")
                         for i, c in enumerate(data.get("categories") or ())),
        resources=tuple(_resource(r, f"data.yaml resources[{i}]") for i, r in enumerate(data.get("resources") or ())),
        terms=tuple(terms),
        knowledge=tuple(_build(Knowledge, k, f"data.yaml knowledge[{i}]")
                        for i, k in enumerate(data.get("knowledge") or ())),
        dialogues=tuple(_build(Dialogue, d, f"dialogues.yaml [{i}]") for i, d in enumerate(dialogues or ())),
    )
