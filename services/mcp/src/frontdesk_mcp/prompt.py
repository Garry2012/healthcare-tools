"""Neutral MCP contract metadata, domain facts and rollout identity."""

from __future__ import annotations

from .packs import Pack

SCHEMA_VERSION = "2026-10-11.2"


def instructions(pack: Pack, languages: tuple[str, ...], display_name: str = "") -> str:
    at = f" at {display_name}" if display_name else ""
    return " ".join((
        f"MCP tools for {pack.role}{at}.", pack.instructions,
        "Availability date: 'today' or YYYY-MM-DD; other relative dates are not accepted.",
        "NOTED records a request, not a reservation.",
        "CALLBACK_REQUIRED: ordinary unresolved schedule. On-call without a confirmed usable entry: "
        "HANDOFF_REQUIRED, not callback.",
        "Future dates: slots when enabled, usual hours otherwise; attendance not confirmed.",
        "Slots-enabled CREATE/RESCHEDULE require a time in openSlots; session is optional and validated.",
        "slotTime: owner slotTime, else expectedTime, else null. slotMoved marks a different block.",
        "UNCERTAIN: unverified write, desk handoff, not retry; a later same-operation invocation can fail a "
        "fresh schedule check.",
        "Gateway authentication covers all three tools.",
        f"Supported languages: {', '.join(languages)}. Tool schema {SCHEMA_VERSION}.",
    ))
