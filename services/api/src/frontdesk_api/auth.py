"""Bearer-token authentication with scopes.

Routers depend only on `Principal` and `require_scopes`. `StaticTokenVerifier` reads
`AUTH_TOKENS_JSON` for this phase; an OAuth2 client-credentials introspection verifier
implements the same `TokenVerifier` protocol and is swapped in `app.py` without touching
any router.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends, Request

from .errors import ApiError

# Scopes that make a caller "staff" for field-level redaction (openapi: "Staff scope only").
STAFF_SCOPES = frozenset({"appointments.staff", "schedule.write", "board.write", "directory.write"})


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    scopes: frozenset[str]

    @property
    def is_staff(self) -> bool:
        return bool(self.scopes & STAFF_SCOPES)


class TokenVerifier(Protocol):
    async def verify(self, token: str) -> Principal | None: ...


class StaticTokenVerifier:
    def __init__(self, tokens_json: str) -> None:
        raw = json.loads(tokens_json or "{}")
        if not isinstance(raw, dict):
            raise ValueError("AUTH_TOKENS_JSON must be an object of token -> [scopes]")
        # Keyed by digest so the table never holds a token as a dict key in plain form.
        self._tokens = {
            hashlib.sha256(token.encode()).hexdigest(): frozenset(scopes)
            for token, scopes in raw.items()
        }

    async def verify(self, token: str) -> Principal | None:
        digest = hashlib.sha256(token.encode()).hexdigest()
        for known, scopes in self._tokens.items():
            if hmac.compare_digest(known, digest):
                return Principal(subject=f"token:{digest[:8]}", scopes=scopes)
        return None


async def authenticate(request: Request) -> Principal:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ApiError("UNAUTHORIZED", "A bearer token is required.",
                       headers={"WWW-Authenticate": "Bearer"})
    verifier: TokenVerifier = request.app.state.token_verifier
    principal = await verifier.verify(token.strip())
    if principal is None:
        raise ApiError("UNAUTHORIZED", "The bearer token is not valid.",
                       headers={"WWW-Authenticate": "Bearer"})
    request.state.principal = principal
    return principal


def require_scopes(*scopes: str):
    """Dependency enforcing a spec `security` block; no scopes = any valid token."""

    async def dependency(principal: Annotated[Principal, Depends(authenticate)]) -> Principal:
        missing = [s for s in scopes if s not in principal.scopes]
        if missing:
            raise ApiError("FORBIDDEN", f"Missing scope: {', '.join(missing)}.")
        return principal

    return dependency
