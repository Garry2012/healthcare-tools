"""A rollout's rows checked with the staff API's own input rules, so a file can never hold what the
API would refuse (a time written 9:00, a lowercase policy, a single question where a list goes),
and a rollout that validates also applies. One definition of each rule: `schemas`."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ValidationError

from .. import schemas as s

if TYPE_CHECKING:
    from .model import Rollout


def _check(model: type[BaseModel], values: dict[str, Any], where: str) -> Iterator[str]:
    try:
        model.model_validate(values)
    except ValidationError as exc:
        for error in exc.errors():
            field = ".".join(str(part) for part in error["loc"])
            yield f"{where}{'.' + field if field else ''}: {error['msg']}"


def _sessions(resource_id: str, sessions) -> Iterator[str]:
    where = f"resource {resource_id}"
    parsed: list[s.TemplateSession] = []
    for i, x in enumerate(sessions):
        values = {"template_session_id": f"tpl_{resource_id}_{x.key}", "label": x.label, "days_of_week": x.days,
                  "start": x.start, "end": x.end, "capacity_model": x.model, "slot_minutes": x.slot_minutes,
                  "capacity": {"mode": x.mode, "value": x.value}, "walk_in_reserve_percent": x.reserve}
        found = list(_check(s.TemplateSession, values, f"{where} sessions[{i}] ({x.key})"))
        yield from found
        if not found:
            parsed.append(s.TemplateSession.model_validate(values))
    if len(parsed) == len(sessions):
        yield from (f"{where} {at}: {what}" for at, what in s.session_problems(parsed))


def problems(rollout: Rollout) -> list[str]:
    found: list[str] = []
    for c in rollout.categories:
        found += _check(s.CategoryInput, {"code": c.code, "name": c.name, "localized_names": c.names,
                                          "offers_bookings": c.bookable}, f"category {c.id}")
    for r in rollout.resources:
        values = {"name": r.name, "localized_names": r.names, "name_variants": r.variants, "gender": r.gender,
                  "category_ids": r.categories, "attributes": r.attributes, "languages_spoken": r.languages,
                  "attendance_type": r.attendance, "booking_policy": r.policy, "data_confirmed": r.data_confirmed}
        found += _check(s.ResourceInput, values, f"resource {r.id}")
        if r.price is not None:
            found += _check(s.Money, {"amount": r.price, "currency": "XXX", "confirmed": r.price_confirmed},
                            f"resource {r.id} price")
        found += _sessions(r.id, r.sessions)
    for k in rollout.knowledge:
        found += _check(s.KnowledgeEntryInput, {"topic": k.topic, "questions": k.questions, "answers": k.answers,
                                                "action": k.action, "destination": k.destination},
                        f"knowledge {k.id}")
    for kind, target, term, language in rollout.terms:
        found += _check(s.LexiconEntryInput, {"concept_type": kind, "concept_id": target, "term": term,
                                              "language": language}, f"term {term!r}")
    return found
