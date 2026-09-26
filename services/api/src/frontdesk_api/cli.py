"""`frontdesk-api serve | migrate | seed | maintenance`."""

from __future__ import annotations

import argparse
import asyncio

from .config import get_settings


def _serve() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run("frontdesk_api.app:create_app", factory=True, host=settings.host, port=settings.port,
                log_config=None, proxy_headers=False)


def _migrate(revision: str) -> None:
    from alembic import command

    from .migrations import config

    command.upgrade(config(get_settings().async_database_url), revision)


def _seed(reset: bool) -> None:
    from .seed import run

    asyncio.run(run(get_settings(), reset=reset))


def _maintenance() -> None:
    from .db.session import make_engine, make_sessionmaker
    from .services import idempotency, schedule, scheduling

    async def work() -> None:
        settings = get_settings()
        engine = make_engine(settings)
        async with make_sessionmaker(engine)() as session:
            keys = await idempotency.purge_expired(session)
            board = await scheduling.purge_board_before(session, schedule.now_in(settings).date())
        await engine.dispose()
        print(f"purged {keys} idempotency keys, {board} expired board entries")

    asyncio.run(work())


def check_config() -> int:
    """Validate a provider's settings (and its pack) without touching the database."""
    import json
    import sys

    from pydantic import ValidationError

    from . import packs
    from .config import Settings

    try:
        settings = Settings()
        problems = list(packs.validate(settings.pack))
        parts = settings.day_parts
        if not {"MORNING", "AFTERNOON", "EVENING"} <= set(parts):
            problems.append("TENANT_DAY_PARTS_JSON must define MORNING, AFTERNOON and EVENING")
        destinations = settings.transfer_destinations
        escalation = settings.pack.escalation_destination
        if escalation not in destinations:
            problems.append(f"transfer destinations lack the pack's escalation {escalation!r}")
        if settings.tenant_knowledge_clarify_threshold > settings.tenant_knowledge_answer_threshold:
            problems.append("TENANT_KNOWLEDGE_CLARIFY_THRESHOLD must not exceed the answer threshold")
    except (ValidationError, ValueError) as exc:
        print(f"invalid configuration: {exc}", file=sys.stderr)
        return 1
    effective = {k: v for k, v in settings.model_dump(mode="json").items()
                 if k == "domain_pack" or k.startswith("tenant_")}
    print(json.dumps({"effective": effective, "transferDestinations": destinations,
                      "escalation": settings.pack.escalation_destination, "problems": problems},
                     indent=2, ensure_ascii=False))
    return 1 if problems else 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="frontdesk-api")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve")
    migrate = sub.add_parser("migrate", help="alembic upgrade (owner role only)")
    migrate.add_argument("revision", nargs="?", default="head")
    seed = sub.add_parser("seed", help="load synthetic demo data (idempotent)")
    seed.add_argument("--reset", action="store_true", help="DESTRUCTIVE: empty every table, then reload")
    sub.add_parser("maintenance", help="purge expired idempotency keys and board entries")
    sub.add_parser("check-config", help="validate provider settings and the domain pack (no database)")
    args = parser.parse_args()
    if args.command == "serve":
        _serve()
    elif args.command == "migrate":
        _migrate(args.revision)
    elif args.command == "seed":
        _seed(args.reset)
    elif args.command == "check-config":
        raise SystemExit(check_config())
    else:
        _maintenance()


if __name__ == "__main__":
    main()
