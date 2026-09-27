"""Domain packs for the words the LLM reads (docs/architecture/TARGET.md A3, A10).

The tool surface (names, parameters, behaviour) is the same in every domain; a pack gives only
its own words: who the agent is (`role`), the instructions that are the domain's alone, and the
tool and parameter descriptions. The core rules and the rollout's languages are added by
`prompt.instructions`. A pack must describe every tool, and may only describe parameters that exist.
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
    role: str  # "a hospital voice agent"
    instructions: str  # the domain's own rules; never a core rule
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
