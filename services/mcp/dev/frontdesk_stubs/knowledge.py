"""Stub of Shobhit's knowledge service following the PROVISIONAL knowledge_contract.

A scripted exact-match table: utterance → routing decision, question → approved answer. It does not
classify, normalise or interpret anything; an unlisted utterance is CONTINUE and an unlisted question
is NO_ANSWER. Development/test only.
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


@dataclass(frozen=True)
class Decision:
    utterances: tuple[str, ...]
    decision: str
    department: str | None = None
    speak: dict[str, str] | None = None


def load_decisions() -> list[Decision]:
    raw = json.loads(DATA.read_text(encoding="utf-8"))["routing"]["decisions"]
    return [Decision(tuple(r["utterances"]), r["decision"], (r.get("department") or {}).get("name"), r.get("speak"))
            for r in raw]


def load_answers() -> list[dict[str, Any]]:
    return json.loads(DATA.read_text(encoding="utf-8"))["answers"]


@dataclass
class KnowledgeStubState:
    bearer: str = "dev-knowledge-secret"
    decisions: list[Decision] = field(default_factory=load_decisions)
    answers: list[dict[str, Any]] = field(default_factory=load_answers)
    fail_next: list[int] = field(default_factory=list)
    malformed_next: list[bool] = field(default_factory=list)
    delay_seconds: float = 0.0
    routed: list[dict[str, Any]] = field(default_factory=list)  # every routing request received, for tests


def create_app(state: KnowledgeStubState) -> Starlette:
    def denied(request: Request) -> Response | None:
        if request.headers.get("authorization") != f"Bearer {state.bearer}":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return None

    async def scenario() -> Response | None:
        if state.delay_seconds:
            await asyncio.sleep(state.delay_seconds)
        if state.fail_next:
            return JSONResponse({"error": "injected"}, status_code=state.fail_next.pop(0))
        if state.malformed_next:
            state.malformed_next.pop(0)
            return JSONResponse({"unexpected": True})
        return None

    async def route(request: Request) -> Response:
        if refused := denied(request):
            return refused
        if blocked := await scenario():
            return blocked
        body = await request.json()
        state.routed.append(body)
        utterance = str(body.get("utterance", "")).strip()
        texts = [utterance, *(str(t).strip() for t in (body.get("additionalText") or []))]
        for item in state.decisions:
            if any(t in item.utterances for t in texts):
                payload: dict[str, Any] = {"decision": item.decision, "provenance": "stub-fixture"}
                if item.department:
                    payload["department"] = {"name": item.department}
                if item.speak:
                    payload["speak"] = item.speak
                return JSONResponse(payload)
        return JSONResponse({"decision": "CONTINUE", "provenance": "stub-default"})

    async def answer(request: Request) -> Response:
        if refused := denied(request):
            return refused
        if blocked := await scenario():
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
                if entry.get("destination"):
                    payload["destination"] = entry["destination"]
                return JSONResponse(payload)
        return JSONResponse({"outcome": "NO_ANSWER"})

    return Starlette(routes=[Route(kc.ROUTE_PATH, route, methods=["POST"]),
                             Route(kc.ANSWER_PATH, answer, methods=["POST"])])
