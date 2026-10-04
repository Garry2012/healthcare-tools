"""`frontdesk-mcp serve` and `frontdesk-mcp schema` (the pinned tool surface, for the snapshot test and
gateway/voice-agent schema verification)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from . import prompt, tools
from .config import Settings, get_settings


def schema_document(settings: Settings) -> dict[str, Any]:
    from .server import build_mcp

    services = tools.Services.build(settings)
    mcp = build_mcp(services)

    async def collect() -> list[dict[str, Any]]:
        listed = await mcp.get_tools()
        items = []
        for name in tools.TOOL_NAMES:
            tool = listed[name]
            items.append({
                "name": name,
                "description": tool.description,
                "annotations": tool.annotations.model_dump(exclude_none=True) if tool.annotations else {},
                "inputSchema": tool.parameters,
                "outputSchema": tool.output_schema,
            })
        await services.aclose()
        return items

    return {"schemaVersion": prompt.SCHEMA_VERSION, "instructions": mcp.instructions,
            "tools": asyncio.run(collect())}


def main() -> None:
    parser = argparse.ArgumentParser(prog="frontdesk-mcp")
    parser.add_argument("command", choices=["serve", "schema"])
    args = parser.parse_args()
    settings = get_settings()
    if args.command == "schema":
        json.dump(schema_document(settings), sys.stdout, indent=2, ensure_ascii=False, sort_keys=True)
        sys.stdout.write("\n")
        return
    import uvicorn

    uvicorn.run("frontdesk_mcp.server:create_app", factory=True, host=settings.host, port=settings.port,
                log_config=None)


if __name__ == "__main__":
    main()
