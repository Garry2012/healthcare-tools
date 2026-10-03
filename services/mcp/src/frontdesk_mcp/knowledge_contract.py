"""PROVISIONAL consumer proposal for Shobhit's knowledge API, not an agreed owner contract.

One question returns either approved text or an actionable decision. The voice platform's every-turn
emergency classifier is a separate owner integration, outside this MCP adapter. No local interpretation.
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    ValidatorFunctionWrapHandler,
    field_validator,
    model_validator,
)

logger = logging.getLogger(__name__)

ANSWER_PATH = "/v1/answer"  # PROVISIONAL: replace only after the owner publishes the contract.
RoutingDecision = Literal["ROUTE_DEPARTMENT", "DESK_TRANSFER", "EMERGENCY_TRANSFER"]
AnswerOutcome = Literal["ANSWERED", "NO_ANSWER", "CLARIFY", "DESK_TRANSFER", "EMERGENCY_TRANSFER", "ROUTE_DEPARTMENT"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)


class Speech(_Model):
    text: str = Field(min_length=1, max_length=1000)
    language: str = Field(min_length=1, max_length=16)

    @field_validator("text", "language")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("speech fields must not be blank")
        return value  # preserve owner wording exactly


class DepartmentHint(_Model):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("department name must not be blank")
        return value


class AnswerResponse(_Model):
    outcome: AnswerOutcome
    answer: Speech | None = None
    department: DepartmentHint | None = None
    sourceId: str | None = Field(default=None, max_length=64)  # noqa: N815
    destination: str | None = Field(default=None, max_length=64)

    @field_validator("answer", "department", "sourceId", "destination", mode="wrap")
    @classmethod
    def preserve_transfer(cls, value: Any, handler: ValidatorFunctionWrapHandler,
                          info: ValidationInfo) -> Any:
        # outcome is declared first, so its validated value is available before optional fields.
        try:
            return handler(value)
        except ValidationError:
            if info.data.get("outcome") not in ("EMERGENCY_TRANSFER", "DESK_TRANSFER"):
                raise
            logger.warning("knowledge_optional_field_dropped", extra={"fields": {"field": info.field_name}})
            return None

    @model_validator(mode="after")
    def actionable(self) -> AnswerResponse:
        if self.outcome in ("ANSWERED", "CLARIFY") and self.answer is None:
            raise ValueError("this outcome needs approved speech")
        if self.outcome == "ROUTE_DEPARTMENT" and self.department is None:
            raise ValueError("department routing needs a department")
        return self
