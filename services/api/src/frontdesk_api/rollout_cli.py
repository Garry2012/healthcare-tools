"""`frontdesk-api check-config`, `rollout validate` and `rollout apply`.

check-config      the deployment's settings (from the environment) and its domain pack
rollout validate  a rollout directory offline: settings, data, and its acceptance dialogues
rollout apply     write the deployment's rollout (domain baseline + its data) to the database
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Mapping

from pydantic import ValidationError

from . import locales, packs, rollouts
from .config import DEPLOYMENT, IDENTITY, SECRETS, Settings, get_settings


def settings_problems(settings: Settings) -> list[str]:
    """What the running system needs from a rollout's settings, beyond field validation."""
    problems = list(packs.validate(settings.pack))
    if not {"MORNING", "AFTERNOON", "EVENING"} <= set(settings.day_parts):
        problems.append("TENANT_DAY_PARTS_JSON must define MORNING, AFTERNOON and EVENING")
    missing = sorted(settings.pack.required_destinations() - set(settings.transfer_destinations))
    problems += [f"transfer destinations lack {d!r}" for d in missing]
    if settings.tenant_knowledge_clarify_threshold > settings.tenant_knowledge_answer_threshold:
        problems.append("TENANT_KNOWLEDGE_CLARIFY_THRESHOLD must not exceed the answer threshold")
    return problems


def effective(settings: Settings, written: Mapping[str, str]) -> dict[str, str]:
    """Every rollout-level setting: "value  [layer]", the layer it came from (rollout, domain, core)."""
    written = {k.lower() for k in written}
    out: dict[str, str] = {}
    for name, value in settings.model_dump(mode="json").items():
        if name in IDENTITY or name.startswith("tenant_"):
            layer = "rollout" if name in written else "domain" if name in settings.pack.settings else "core"
            out[name] = f"{value}  [{layer}]"
    return out


def _print(payload: dict) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def check_config() -> int:
    """The deployment's settings, from its environment (no database, no data)."""
    try:
        settings = Settings()
    except (ValidationError, ValueError) as exc:
        print(f"invalid configuration: {exc}", file=sys.stderr)
        return 1
    problems = settings_problems(settings)
    _print({"effective": effective(settings, os.environ), "transferDestinations": settings.transfer_destinations,
            "problems": problems})
    return 1 if problems else 0


def file_problems(written: Mapping[str, str]) -> list[str]:
    """A rollout file holds known, non-secret rollout settings only: a typo would silently fall
    back to a default, and a secret would be committed or baked into an image."""
    problems = []
    for key in written:
        name = key.lower()
        if name in SECRETS:
            problems.append(f"{key} is a secret: keep it in the secret store, never in rollout.env")
        elif name in DEPLOYMENT:
            problems.append(f"{key} is set by the deployment (compose, deploy.sh), not by a rollout")
        elif name not in Settings.model_fields:
            problems.append(f"{key} is not a setting (a typo?)")
    return problems


def validate(directory: str) -> int:
    """A rollout directory, offline: the settings it writes, its data and its dialogues."""
    try:
        rollout = rollouts.load(directory)
        written = {k.lower(): v for k, v in rollout.settings.items() if k.lower() in Settings.model_fields}
        settings = Settings(**written)
    except (rollouts.RolloutError, ValidationError, ValueError) as exc:
        print(f"invalid rollout: {exc}", file=sys.stderr)
        return 1
    composed = rollouts.compose(settings.pack, rollout)
    report = rollouts.validate(composed, settings.transfer_destinations, settings.thresholds,
                               settings.knowledge_thresholds)
    problems = file_problems(rollout.settings) + settings_problems(settings) + list(report.problems)
    _print({"rollout": rollout.id, "domain": f"{settings.pack.name} v{settings.pack.version}",
            "languages": list(rollout.languages), "effective": effective(settings, rollout.settings),
            "counts": {"categories": len(rollout.categories), "resources": len(rollout.resources),
                       "terms": len(composed.lexicon), "knowledge": len(rollout.knowledge),
                       "dialogues": len(rollout.dialogues)},
            "notes": list(report.notes), "problems": problems})
    return 1 if problems else 0


def apply(directory: str | None) -> int:
    """Write the deployment's rollout. Allowed in production: this is how a provider's data loads."""
    from .db.session import make_engine, make_sessionmaker
    from .services import rollout_apply

    settings = get_settings()
    locales.select(settings.languages)

    async def work() -> dict[str, int]:
        composed = rollout_apply.load(settings, directory)
        engine = make_engine(settings)
        try:
            async with make_sessionmaker(engine)() as session:
                summary = await rollout_apply.apply(session, settings, composed)
                await session.commit()
                return summary
        finally:
            await engine.dispose()

    try:
        summary = asyncio.run(work())
    except (rollouts.RolloutError, ValueError) as exc:
        print(f"not applied: {exc}", file=sys.stderr)
        return 1
    _print({"applied": settings.provider_id, **summary})
    return 0
