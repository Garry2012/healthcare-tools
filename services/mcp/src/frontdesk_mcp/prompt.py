"""Neutral MCP contract metadata, domain facts and rollout identity."""

from __future__ import annotations

from .packs import Pack

SCHEMA_VERSION = "2026-10-04.1"


def instructions(pack: Pack, languages: tuple[str, ...], display_name: str = "") -> str:
    at = f" at {display_name}" if display_name else ""
    return " ".join((
        f"MCP tools for {pack.role}{at}.", pack.instructions,
        "Availability date accepts only 'today' or YYYY-MM-DD; other relative dates are not accepted.",
        "NOTED is a recorded appointment request, not a confirmed or reserved time.",
        "CALLBACK_REQUIRED denotes UNKNOWN board availability; UNCERTAIN denotes an unverified write result.",
        "Call summaries require lifecycle authentication; the other three tools require gateway authentication.",
        f"Supported languages: {', '.join(languages)}. Tool schema {SCHEMA_VERSION}.",
    ))
