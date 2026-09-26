"""Schemathesis smoke run against a *running* service (set CONTRACT_API_URL and
CONTRACT_API_TOKEN, a token holding every scope). `make test` starts one.

Checks run: no 5xx, responses match the spec's schemas, content types and headers, and
unsupported methods answer 405 with Allow. Not run, because the spec itself is the cause
(see docs/handover/OPEN-QUESTIONS.md): status_code_conformance (the spec omits 400/404 on
several operations), positive_data_acceptance (domain rules are stricter than the schema:
tenant phone format, slot existence, board-is-today), negative_data_rejection (unknown
query parameters are ignored, as HTTP APIs conventionally do).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SPEC = Path(__file__).resolve().parents[4] / "docs/frontdesk-api/openapi.yaml"
URL = os.environ.get("CONTRACT_API_URL")
TOKEN = os.environ.get("CONTRACT_API_TOKEN")
CHECKS = "not_a_server_error,response_schema_conformance,content_type_conformance," \
         "response_headers_conformance,unsupported_method"


@pytest.mark.skipif(not (URL and TOKEN), reason="CONTRACT_API_URL / CONTRACT_API_TOKEN not set")
def test_schemathesis_smoke():
    result = subprocess.run(
        [
            sys.executable, "-m", "schemathesis.cli", "run", str(SPEC),
            "--url", URL,
            "-H", f"Authorization: Bearer {TOKEN}",
            "-H", "X-Acting-User: schemathesis",
            "--checks", CHECKS,
            "--phases", "examples,coverage,fuzzing",
            "--max-examples", os.environ.get("CONTRACT_MAX_EXAMPLES", "15"),
            "--seed", "20260925",
            "-w", "4",
        ],
        capture_output=True, text=True, timeout=900,
    )
    # Keep the failure details (request, response, curl reproduction), not just the tally.
    failures = result.stdout[result.stdout.find("FAILURES"):] if "FAILURES" in result.stdout else result.stdout
    assert result.returncode == 0, failures[-8000:]
