"""The generated OpenAPI must match docs/frontdesk-api/openapi.yaml on every path+method,
operationId, and every schema's `required` list and enum values (recursively, through
$ref, allOf, nullable anyOf, arrays and inline objects)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import yaml

from healthcare_api.app import API_PREFIX, create_app

SPEC = Path(os.environ.get("SPEC_PATH", Path(__file__).resolve().parents[4] / "docs/frontdesk-api/openapi.yaml"))
METHODS = {"get", "put", "post", "delete", "patch"}


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return yaml.safe_load(SPEC.read_text())


@pytest.fixture(scope="module")
def generated(settings) -> dict[str, Any]:
    return create_app(settings).openapi()


def _operations(doc: dict[str, Any], prefix: str = "") -> dict[tuple[str, str], dict[str, Any]]:
    ops = {}
    for path, item in doc["paths"].items():
        if prefix and not path.startswith(prefix):
            continue
        for method, op in item.items():
            if method in METHODS:
                ops[(path[len(prefix):], method)] = op
    return ops


class Resolver:
    def __init__(self, doc: dict[str, Any]) -> None:
        self.schemas = doc.get("components", {}).get("schemas", {})

    def resolve(self, node: dict[str, Any]) -> dict[str, Any]:
        """Follow $ref, merge allOf, and unwrap nullable anyOf/oneOf into one schema."""
        seen = 0
        while True:
            seen += 1
            assert seen < 50, "reference cycle"
            if "$ref" in node:
                node = {**self.schemas[node["$ref"].rsplit("/", 1)[-1]],
                        **{k: v for k, v in node.items() if k != "$ref"}}
                continue
            if "allOf" in node:
                merged: dict[str, Any] = {k: v for k, v in node.items() if k != "allOf"}
                for part in node["allOf"]:
                    part = self.resolve(part)
                    merged.setdefault("properties", {}).update(part.get("properties", {}))
                    merged["required"] = sorted(set(merged.get("required", [])) | set(part.get("required", [])))
                    for key in ("enum", "type", "items"):
                        if key in part and key not in merged:
                            merged[key] = part[key]
                if not merged.get("properties"):
                    merged.pop("properties", None)
                if not merged.get("required"):
                    merged.pop("required", None)
                node = merged
                continue
            for key in ("anyOf", "oneOf"):
                if key in node:
                    branches = [b for b in node[key] if b.get("type") != "null"]
                    if len(branches) == 1:
                        node = {**{k: v for k, v in node.items() if k != key}, **branches[0]}
                        break
            else:
                return node


def _compare(spec_node, gen_node, spec_r: Resolver, gen_r: Resolver, where: str, problems: list[str]) -> None:
    s = spec_r.resolve(spec_node)
    g = gen_r.resolve(gen_node)
    if "enum" in s:
        if set(s["enum"]) != set(g.get("enum", [])):
            problems.append(f"{where}: enum {sorted(s['enum'])} != {sorted(g.get('enum', []))}")
    if s.get("type") == "array" or "items" in s:
        if "items" in s:
            if "items" not in g:
                problems.append(f"{where}: generated schema is not an array")
            else:
                _compare(s["items"], g["items"], spec_r, gen_r, f"{where}[]", problems)
    if "required" in s or "properties" in s:
        if set(s.get("required", [])) != set(g.get("required", [])):
            problems.append(
                f"{where}: required {sorted(s.get('required', []))} != {sorted(g.get('required', []))}"
            )
        for name, prop in s.get("properties", {}).items():
            if name not in g.get("properties", {}):
                problems.append(f"{where}.{name}: missing from generated schema")
                continue
            _compare(prop, g["properties"][name], spec_r, gen_r, f"{where}.{name}", problems)
    if isinstance(s.get("additionalProperties"), dict) and isinstance(g.get("additionalProperties"), dict):
        _compare(s["additionalProperties"], g["additionalProperties"], spec_r, gen_r, f"{where}{{}}", problems)


def test_every_path_and_method_exists(spec, generated):
    wanted = set(_operations(spec))
    have = set(_operations(generated, API_PREFIX))
    assert sorted(wanted - have) == []
    assert sorted(have - wanted) == [], "generated API has operations the spec does not"


def test_operation_ids_match(spec, generated):
    have = _operations(generated, API_PREFIX)
    mismatched = {
        key: (op["operationId"], have[key].get("operationId"))
        for key, op in _operations(spec).items()
        if key in have and have[key].get("operationId") != op["operationId"]
    }
    assert mismatched == {}


def test_every_named_schema_matches(spec, generated):
    spec_r, gen_r = Resolver(spec), Resolver(generated)
    problems: list[str] = []
    for name, schema in spec["components"]["schemas"].items():
        resolved = spec_r.resolve(schema)
        structural = "enum" in resolved or "properties" in resolved or "required" in resolved
        if not structural:
            continue  # primitives (Language, Phone, ClockTime, LocalizedText) have no component
        if name not in gen_r.schemas:
            problems.append(f"{name}: no generated component")
            continue
        _compare(schema, gen_r.schemas[name], spec_r, gen_r, name, problems)
    assert problems == []


def test_request_and_response_bodies_match(spec, generated):
    """Inline bodies (cancel, reschedule, confirm, list wrappers) are compared structurally too."""
    spec_r, gen_r = Resolver(spec), Resolver(generated)
    have = _operations(generated, API_PREFIX)
    problems: list[str] = []
    for key, op in _operations(spec).items():
        gen_op = have.get(key)
        if gen_op is None:
            continue
        label = f"{key[1].upper()} {key[0]}"
        spec_body = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
        if spec_body:
            gen_body = gen_op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
            if gen_body is None:
                problems.append(f"{label}: request body missing")
            else:
                _compare(spec_body, gen_body, spec_r, gen_r, f"{label} request", problems)
        for status, response in op.get("responses", {}).items():
            spec_schema = response.get("content", {}).get("application/json", {}).get("schema") \
                if "content" in response else None
            if spec_schema is None or str(status) not in {"200", "201"}:
                continue
            gen_response = gen_op.get("responses", {}).get(str(status), {})
            gen_schema = gen_response.get("content", {}).get("application/json", {}).get("schema")
            if gen_schema is None:
                problems.append(f"{label} {status}: response schema missing")
            else:
                _compare(spec_schema, gen_schema, spec_r, gen_r, f"{label} {status}", problems)
    assert problems == []


def test_required_parameters_match(spec, generated):
    have = _operations(generated, API_PREFIX)
    problems: list[str] = []
    for key, op in _operations(spec).items():
        gen_op = have.get(key)
        if gen_op is None:
            continue
        gen_params = {(p["in"], p["name"]): p for p in gen_op.get("parameters", [])}
        for param in op.get("parameters", []):
            if "$ref" in param:
                param = spec["components"]["parameters"][param["$ref"].rsplit("/", 1)[-1]]
            ident = (param["in"], param["name"])
            if ident not in gen_params:
                problems.append(f"{key}: parameter {ident} missing")
            elif bool(param.get("required")) != bool(gen_params[ident].get("required")):
                problems.append(f"{key}: parameter {ident} required mismatch")
    assert problems == []
