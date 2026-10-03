"""HTTP adapter for Shobhit's knowledge service under the PROVISIONAL knowledge_contract. It forwards
the caller's question argument and consumes his decision; it never decides locally. Any failure, missing
configuration or unknown response shape is an explicit unavailable result, never a negative answer."""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

import httpx
from pydantic import ValidationError

from . import knowledge_contract as kc
from .clock import Deadline, DeadlineExceeded
from .config import Settings
from .context import CallContext

logger = logging.getLogger(__name__)

KnowledgeFailure = Literal["NOT_CONFIGURED", "UNAVAILABLE", "MALFORMED"]


class KnowledgeUnavailable(Exception):
    def __init__(self, reason: KnowledgeFailure) -> None:
        super().__init__(reason)
        self.reason = reason


class KnowledgeClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        self.http = httpx.AsyncClient(
            base_url=settings.knowledge_base_url or "http://knowledge.unconfigured.invalid",
            transport=transport,
            headers={"Authorization": f"Bearer {settings.knowledge_bearer_token.get_secret_value()}"}
            if settings.knowledge_bearer_token.get_secret_value() else {},
            limits=httpx.Limits(max_connections=settings.knowledge_pool_max_connections,
                                max_keepalive_connections=settings.knowledge_pool_max_connections),
        )

    async def aclose(self) -> None:
        await self.http.aclose()

    async def _post(self, path: str, body: dict, deadline: Deadline) -> dict:
        if not self.settings.knowledge_base_url:
            raise KnowledgeUnavailable("NOT_CONFIGURED")
        try:
            timeout = deadline.timeout(self.settings.request_timeout_seconds)
            async with asyncio.timeout(timeout):  # wall-clock cap: httpx's timeout is per phase/chunk
                response = await self.http.post(path, json=body, timeout=timeout)
        except DeadlineExceeded as exc:
            raise KnowledgeUnavailable("UNAVAILABLE") from exc
        except (httpx.RequestError, TimeoutError) as exc:
            logger.warning("knowledge_unreachable", extra={"fields": {"path": path, "error": type(exc).__name__}})
            raise KnowledgeUnavailable("UNAVAILABLE") from exc
        if response.status_code in (401, 403):
            logger.error("knowledge_rejected_adapter_credentials", extra={"fields": {"status": response.status_code}})
            raise KnowledgeUnavailable("UNAVAILABLE")
        if response.status_code != 200:
            logger.warning("knowledge_error", extra={"fields": {"path": path, "status": response.status_code}})
            raise KnowledgeUnavailable("UNAVAILABLE")
        if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise KnowledgeUnavailable("MALFORMED")
        try:
            data = response.json()
        except ValueError as exc:
            raise KnowledgeUnavailable("MALFORMED") from exc
        if not isinstance(data, dict):
            raise KnowledgeUnavailable("MALFORMED")
        return data

    async def answer(self, question: str, language: str, ctx: CallContext, deadline: Deadline) -> kc.AnswerResponse:
        body: dict = {"question": question, "language": language}
        if ctx.call_id:
            body["callId"] = ctx.call_id
        data = await self._post(kc.ANSWER_PATH, body, deadline)
        try:
            return kc.AnswerResponse.model_validate(data)
        except ValidationError as exc:
            logger.error("knowledge_answer_malformed")
            raise KnowledgeUnavailable("MALFORMED") from exc
