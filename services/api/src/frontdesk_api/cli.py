"""`frontdesk-api serve | migrate | seed | maintenance | check-config | rollout validate|apply`."""

from __future__ import annotations

import argparse
import asyncio

from . import rollout_cli
from .config import get_settings


def _serve() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run("frontdesk_api.app:create_app", factory=True, host=settings.host, port=settings.port,
                log_config=None, proxy_headers=False)


def _migrate(revision: str) -> None:
    from alembic import command

    from .config import migration_database_url
    from .migrations import config

    command.upgrade(config(migration_database_url()), revision)


def _seed(reset: bool) -> None:
    from .seed import SeedRefused, run

    try:
        asyncio.run(run(get_settings(), reset=reset))
    except SeedRefused as exc:
        raise SystemExit(str(exc)) from None


def _maintenance() -> None:
    from .db.session import make_engine, make_sessionmaker
    from .services import board, idempotency, schedule

    async def work() -> None:
        settings = get_settings()
        engine = make_engine(settings)
        async with make_sessionmaker(engine)() as session:
            keys = await idempotency.purge_expired(session)
            entries = await board.purge_board_before(session, schedule.now_in(settings).date())
        await engine.dispose()
        print(f"purged {keys} idempotency keys, {entries} expired board entries")

    asyncio.run(work())


def main() -> None:
    parser = argparse.ArgumentParser(prog="frontdesk-api")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve")
    migrate = sub.add_parser("migrate", help="alembic upgrade (owner role only)")
    migrate.add_argument("revision", nargs="?", default="head")
    seed = sub.add_parser("seed", help="load synthetic demo data (idempotent)")
    seed.add_argument("--reset", action="store_true", help="DESTRUCTIVE: empty every table, then reload")
    sub.add_parser("maintenance", help="purge expired idempotency keys and board entries")
    sub.add_parser("check-config", help="validate this deployment's settings and its domain pack (no database)")
    rollout = sub.add_parser("rollout", help="a rollout: core + domain pack + one provider's settings and data")
    action = rollout.add_subparsers(dest="action", required=True)
    action.add_parser("validate", help="check a rollout directory offline, dialogues included").add_argument("dir")
    action.add_parser("apply", help="write this deployment's rollout to the database").add_argument(
        "dir", nargs="?", default=None, help="default: ROLLOUT_DIR")
    args = parser.parse_args()
    if args.command == "serve":
        _serve()
    elif args.command == "migrate":
        _migrate(args.revision)
    elif args.command == "seed":
        _seed(args.reset)
    elif args.command == "check-config":
        raise SystemExit(rollout_cli.check_config())
    elif args.command == "rollout":
        raise SystemExit(rollout_cli.validate(args.dir) if args.action == "validate" else rollout_cli.apply(args.dir))
    else:
        _maintenance()


if __name__ == "__main__":
    main()
