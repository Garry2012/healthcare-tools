"""Domain packs for the words the LLM reads (docs/architecture/TARGET.md A3).

The tool surface (names, parameters, behaviour) is the same in every domain; only the
server instructions, tool descriptions and parameter descriptions change. A pack must
describe every tool, and may only describe parameters that exist.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib import resources


@dataclass(frozen=True)
class ToolText:
    description: str
    parameters: dict[str, str]


@dataclass(frozen=True)
class Pack:
    name: str
    instructions: str
    tools: dict[str, ToolText]


@cache
def load(name: str) -> Pack:
    if not name.isidentifier():
        raise ValueError(f"DOMAIN_PACK {name!r} is not a valid pack name")
    source = resources.files("frontdesk_mcp").joinpath("packs", f"{name}.json")
    if not source.is_file():
        raise ValueError(f"Unknown DOMAIN_PACK {name!r}")
    raw = json.loads(source.read_text(encoding="utf-8"))
    tools = {
        tool: ToolText(description=" ".join(text["description"].split()), parameters=dict(text.get("parameters", {})))
        for tool, text in raw["tools"].items()
    }
    return Pack(name=name, instructions=" ".join(raw["instructions"].split()), tools=tools)
