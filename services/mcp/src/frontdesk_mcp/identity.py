"""Caller identity for appointment lookups/changes. Authority comes from the platform's trusted,
verified caller number under the configured country rule; a dictated patient mobile is contact data
and never authorises anything. No arbitrary prefix stripping, never "the last ten digits"."""

from __future__ import annotations

import re

from .config import Settings
from .context import CallContext
from .contract import APPROX_TIME_PATTERN, MOBILE_PATTERN

_MOBILE = re.compile(MOBILE_PATTERN)
_TIME = re.compile(APPROX_TIME_PATTERN)


def is_contract_mobile(value: str) -> bool:
    return bool(_MOBILE.fullmatch(value))


def is_approx_time(value: str) -> bool:
    return bool(_TIME.fullmatch(value))


def contract_mobile(e164: str, calling_code: str) -> str | None:
    """`+<calling code><10 digits>` → the contract's 10-digit Mobile; anything else is unsupported."""
    prefix = f"+{calling_code}"
    if not e164.startswith(prefix):
        return None
    national = e164[len(prefix):]
    return national if is_contract_mobile(national) else None


def authorised_mobile(ctx: CallContext, settings: Settings) -> str | None:
    """The mobile the authenticated platform context vouches for, or None (identity unavailable)."""
    if not ctx.caller_number or ctx.caller_verification not in settings.accepted_verification:
        return None
    return contract_mobile(ctx.caller_number, settings.tenant_country_calling_code)
