"""Structured JSON logs. X-Call-Id is the correlation id; phone numbers and patient
names are never logged at INFO (only ids and outcomes are)."""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

call_id_var: ContextVar[str | None] = ContextVar("call_id", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        call_id = call_id_var.get()
        if call_id:
            entry["callId"] = call_id
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            entry.update(fields)
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers[:] = []
        logging.getLogger(name).propagate = True
    # The access log would print query strings (which can carry a phone number).
    logging.getLogger("uvicorn.access").disabled = True


def log_event(logger: logging.Logger, level: int, msg: str, **fields: Any) -> None:
    logger.log(level, msg, extra={"fields": fields})
