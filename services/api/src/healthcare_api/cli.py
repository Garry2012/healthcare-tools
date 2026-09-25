"""`healthcare-api serve | migrate | seed | maintenance`."""

from __future__ import annotations

import argparse
import asyncio

from .config import get_settings


def _serve() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run("healthcare_api.app:create_app", factory=True, host=settings.host, port=settings.port,
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


def main() -> None:
    parser = argparse.ArgumentParser(prog="healthcare-api")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve")
    migrate = sub.add_parser("migrate", help="alembic upgrade (owner role only)")
    migrate.add_argument("revision", nargs="?", default="head")
    seed = sub.add_parser("seed", help="load synthetic demo data (idempotent)")
    seed.add_argument("--reset", action="store_true", help="delete bookings/exceptions/board first")
    sub.add_parser("maintenance", help="purge expired idempotency keys and board entries")
    args = parser.parse_args()
    if args.command == "serve":
        _serve()
    elif args.command == "migrate":
        _migrate(args.revision)
    elif args.command == "seed":
        _seed(args.reset)
    else:
        _maintenance()


if __name__ == "__main__":
    main()
