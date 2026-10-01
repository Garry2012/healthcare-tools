"""Run both stubs as real HTTP servers for local development and process-level e2e tests.

    python -m frontdesk_stubs --ops-port 8200 --knowledge-port 8300 --ops-prefix /api/v1

Development only. The clock is the system clock unless --now is given (ISO, aware)."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime

import uvicorn

from frontdesk_mcp.clock import FixedClock, SystemClock

from . import knowledge, ops


def main() -> None:
    parser = argparse.ArgumentParser(prog="frontdesk_stubs")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--ops-port", type=int, default=8200)
    parser.add_argument("--knowledge-port", type=int, default=8300)
    parser.add_argument("--ops-prefix", default="/api/v1", help="mount prefix; '' mirrors the public mock")
    parser.add_argument("--client-id", default="mcp-dev")
    parser.add_argument("--client-secret", default="dev-secret")
    parser.add_argument("--knowledge-bearer", default="dev-knowledge-secret")
    parser.add_argument("--zone", default="Asia/Kolkata")
    parser.add_argument("--now", default=None, help="fixed aware ISO datetime for a deterministic 'today'")
    args = parser.parse_args()

    clock = FixedClock(datetime.fromisoformat(args.now)) if args.now else SystemClock()
    ops_state = ops.OpsStubState(clock=clock, zone=args.zone,
                                 clients={args.client_id: (args.client_secret, {"appointments.write", "calls.write"})})
    kb_state = knowledge.KnowledgeStubState(bearer=args.knowledge_bearer)

    async def serve() -> None:
        servers = [
            uvicorn.Server(uvicorn.Config(ops.create_app(ops_state, prefix=args.ops_prefix), host=args.host,
                                          port=args.ops_port, log_level="warning")),
            uvicorn.Server(uvicorn.Config(knowledge.create_app(kb_state), host=args.host, port=args.knowledge_port,
                                          log_level="warning")),
        ]
        await asyncio.gather(*(s.serve() for s in servers))

    asyncio.run(serve())


if __name__ == "__main__":
    main()
