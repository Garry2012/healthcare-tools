"""Domain-specific tool descriptions and neutral contract facts.

The tool surface is common across packs; each pack supplies its domain label, factual summary
and parameter descriptions. Rollout languages and display name are supplied by prompt.instructions.
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
    role: str  # domain label
    instructions: str  # neutral domain facts
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
    return Pack(name=name, role=raw["role"], instructions=" ".join(raw["instructions"].split()), tools=tools)
