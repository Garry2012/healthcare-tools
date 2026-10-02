"""Stub of Shobhit's knowledge service following the PROVISIONAL knowledge_contract.

A scripted question → owner response fixture table. It does not classify symptoms;
an unlisted question is NO_ANSWER. Development/test only.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from frontdesk_mcp import knowledge_contract as kc

DATA = Path(__file__).parent / "data/demo_hospital.json"






def load_answers() -> list[dict[str, Any]]:
    return json.loads(DATA.read_text(encoding="utf-8"))["answers"]


@dataclass
class KnowledgeStubState:
    bearer: str = "dev-knowledge-secret"
    answers: list[dict[str, Any]] = field(default_factory=load_answers)
    fail_next: list[int] = field(default_factory=list)
    fail_next_for: list[tuple[str, int]] = field(default_factory=list)  # (path, status): one failure for that path
    malformed_next: list[bool] = field(default_factory=list)
    malformed_next_for: list[str] = field(default_factory=list)  # paths answering {"unexpected": true} once
    delay_seconds: float = 0.0


def create_app(state: KnowledgeStubState) -> Starlette:
    def denied(request: Request) -> Response | None:
        if request.headers.get("authorization") != f"Bearer {state.bearer}":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return None

    async def scenario(path: str = "") -> Response | None:
        if state.delay_seconds:
            await asyncio.sleep(state.delay_seconds)
        for i, (prefix, status) in enumerate(state.fail_next_for):
            if path.startswith(prefix):
                del state.fail_next_for[i]
                return JSONResponse({"error": "injected"}, status_code=status)
        for i, prefix in enumerate(state.malformed_next_for):
            if path.startswith(prefix):
                del state.malformed_next_for[i]
                return JSONResponse({"unexpected": True})
        if state.fail_next:
            return JSONResponse({"error": "injected"}, status_code=state.fail_next.pop(0))
        if state.malformed_next:
            state.malformed_next.pop(0)
            return JSONResponse({"unexpected": True})
        return None

    async def answer(request: Request) -> Response:
        if refused := denied(request):
            return refused
        if blocked := await scenario(kc.ANSWER_PATH):
            return blocked
        body = await request.json()
        question = str(body.get("question", "")).strip().casefold()
        language = str(body.get("language", "en"))
        for entry in state.answers:
            if question in (q.casefold() for q in entry["questions"]):
                text = entry["answers"].get(language) or entry["answers"]["en"]
                spoken = language if language in entry["answers"] else "en"
                payload: dict[str, Any] = {"outcome": entry.get("outcome", "ANSWERED"), "sourceId": entry["id"],
                                           "answer": {"text": text, "language": spoken}}
                if entry.get("department"):
                    payload["department"] = entry["department"]
                if entry.get("destination"):
                    payload["destination"] = entry["destination"]
                return JSONResponse(payload)
        return JSONResponse({"outcome": "NO_ANSWER"})

    return Starlette(routes=[Route(kc.ANSWER_PATH, answer, methods=["POST"])])
