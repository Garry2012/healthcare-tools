"""Adapter settings, from the environment: the rollout's identity (rollouts/<id>/rollout.env), the
two owner services (Manoj's operational API, Shobhit's knowledge service) and the gateway/lifecycle
bearers. Nothing provider-specific is written in code, and production refuses development stubs."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from . import packs

# Hostname fragments that identify contract mocks and development stubs. Production never talks to them.
STUB_MARKERS = ("healthcare-contract-mock", "localhost", "127.0.0.1", ":4010", "stub", "prism", "mock")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", frozen=True)

    env: Literal["development", "test", "staging", "production"] = "development"
    log_level: str = "INFO"
    host: str = "127.0.0.1"
    port: int = Field(default=8100, ge=1, le=65535)

    # --- the rollout (rollout.env): no defaults -------------------------------------------------
    provider_id: str = Field(min_length=1)
    domain_pack: str
    tenant_supported_languages: str
    tenant_timezone: str
    tenant_country_calling_code: str
    tenant_display_name: str = ""

    # --- Manoj's operational API: full base URL (backend has /api/v1, the public mock does not) ---
    ops_base_url: str
    ops_client_id: str = ""
    ops_client_secret: SecretStr = SecretStr("")

    # --- Shobhit's knowledge service (contract pending: see knowledge_contract.py) ----------------
    knowledge_base_url: str = ""
    knowledge_bearer_token: SecretStr = SecretStr("")

    # --- who may call us ------------------------------------------------------------------------
    # Conversational path: the bearer the gateway presents for the three in-call tools.
    mcp_bearer_token: SecretStr = SecretStr("")
    # Call-end lifecycle: a different bearer that alone may invoke record_call_summary.
    mcp_lifecycle_bearer_token: SecretStr = SecretStr("")
    # Dev only: used when the gateway forwards no X-Caller-Number.
    mcp_dev_caller_number: str = ""
    # Which X-Caller-Verification assertions authorise appointment lookups/changes (agreed with Manoj).
    accepted_caller_verification: str = "SIP_CALLER_ID"

    # --- one total deadline per tool invocation (pool wait + auth + every call + any retry) -------
    # The caller's response budget (TARGET-STATE.md): end of speech → first useful audio. The other stages
    # (endpointing/STT, model tool choice, model answer, TTS start, headroom) are reserved; what remains is the
    # whole tool round trip including the gateway, so the adapter's own deadline is derived from it unless a
    # diagnostic override sets READ_DEADLINE_SECONDS explicitly. These are design allocations to validate on
    # the real path, not measured guarantees.
    voice_response_budget_seconds: float = Field(default=1.0, gt=0, le=10)
    reserved_stage_seconds: float = Field(default=0.65, ge=0, le=10)
    gateway_overhead_seconds: float = Field(default=0.05, ge=0, le=5)  # ContextForge hop, outside the adapter
    # Every tool called during the conversation (reads AND confirmed writes) gets the same share:
    # budget − reserved − gateway. Explicit values are diagnostic overrides; one that exceeds the share is refused
    # unless ALLOW_BUDGET_OVERRIDES=true is set deliberately (bench/external runs from a distant laptop).
    read_deadline_seconds: float | None = Field(default=None, gt=0, le=30)
    write_deadline_seconds: float | None = Field(default=None, gt=0, le=30)
    summary_deadline_seconds: float = Field(default=8.0, gt=0, le=60)  # after the call: outside the budget
    request_timeout_seconds: float | None = Field(default=None, gt=0, le=30)  # cap per exchange; default: read
    allow_budget_overrides: bool = False
    token_refresh_margin_seconds: int = Field(default=60, ge=0, le=3600)
    token_refresh_check_seconds: float = Field(default=15.0, gt=0, le=3600)  # background refresher cadence
    token_refresh_timeout_seconds: float = Field(default=5.0, gt=0, le=60)  # background/start-up refresh: not in-call
    directory_cache_seconds: int = Field(default=300, ge=0, le=86400)
    directory_page_size: int = Field(default=25, ge=1, le=100)  # bounded search/department fan-out
    directory_cache_max_entries: int = Field(default=512, ge=1, le=100_000)
    ops_pool_max_connections: int = Field(default=20, ge=1, le=1000)
    knowledge_pool_max_connections: int = Field(default=10, ge=1, le=1000)

    @field_validator("tenant_supported_languages")
    @classmethod
    def _languages(cls, value: str) -> str:
        codes = [c.strip() for c in value.split(",") if c.strip()]
        if not codes or not all(c.isalpha() and c.islower() and 2 <= len(c) <= 3 for c in codes):
            raise ValueError("TENANT_SUPPORTED_LANGUAGES must list language codes, e.g. en,kn,hi")
        return ",".join(codes)

    @field_validator("tenant_timezone")
    @classmethod
    def _timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"TENANT_TIMEZONE must be an IANA zone name, e.g. Asia/Kolkata: {value!r}") from exc
        return value

    @field_validator("tenant_country_calling_code")
    @classmethod
    def _calling_code(cls, value: str) -> str:
        if not value.isdigit() or not 1 <= len(value) <= 3:
            raise ValueError("TENANT_COUNTRY_CALLING_CODE must be the digits of the calling code, e.g. 91")
        return value

    @field_validator("ops_base_url", "knowledge_base_url")
    @classmethod
    def _strip_slash(cls, value: str) -> str:
        value = value.strip()
        if value and not value.rstrip("/"):
            raise ValueError("owner base URL must not contain only slashes")
        return value.rstrip("/")

    @field_validator("knowledge_bearer_token")
    @classmethod
    def _knowledge_token(cls, value: SecretStr) -> SecretStr:
        return SecretStr(value.get_secret_value().strip())

    @field_validator("accepted_caller_verification")
    @classmethod
    def _verification(cls, value: str) -> str:
        levels = [v.strip() for v in value.split(",") if v.strip()]
        if not levels:
            raise ValueError("ACCEPTED_CALLER_VERIFICATION must name at least one verification level")
        return ",".join(levels)

    @property
    def languages(self) -> tuple[str, ...]:
        return tuple(self.tenant_supported_languages.split(","))

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.tenant_timezone)

    @property
    def accepted_verification(self) -> frozenset[str]:
        return frozenset(self.accepted_caller_verification.split(","))

    @property
    def ops_token_url(self) -> str:
        return f"{self.ops_base_url}/auth/token"

    @model_validator(mode="before")
    @classmethod
    def _derive_deadlines(cls, data):
        if not isinstance(data, dict):
            return data
        budget = float(data.get("voice_response_budget_seconds", 1.0))
        reserved = float(data.get("reserved_stage_seconds", 0.65))
        gateway = float(data.get("gateway_overhead_seconds", 0.05))
        tool_share = round(budget - reserved - gateway, 3)
        if tool_share < 0.1:
            raise ValueError("voice budget minus reserved stages and gateway leaves no time for the tool "
                             "(reserved too large)")
        for name in ("read_deadline_seconds", "write_deadline_seconds"):
            if data.get(name) is None:
                data[name] = tool_share
        if data.get("request_timeout_seconds") is None:
            data["request_timeout_seconds"] = data["read_deadline_seconds"]
        return data

    @model_validator(mode="after")
    def _guard_budget_overrides(self) -> Settings:
        """After validation the flag is a real bool (an environment string "false" is false, not truthy)."""
        tool_share = round(self.voice_response_budget_seconds - self.reserved_stage_seconds
                           - self.gateway_overhead_seconds, 3)
        for name in ("read_deadline_seconds", "write_deadline_seconds"):
            value = getattr(self, name)
            if value > tool_share + 1e-9 and not self.allow_budget_overrides:
                raise ValueError(f"{name.upper()}={value} exceeds the in-call tool budget of {tool_share} s "
                                 "(set ALLOW_BUDGET_OVERRIDES=true only for diagnostics)")
        return self

    @model_validator(mode="after")
    def _deadlines_nest(self) -> Settings:
        if not self.read_deadline_seconds <= self.write_deadline_seconds <= self.summary_deadline_seconds:
            raise ValueError("deadlines must satisfy read <= write <= summary")
        return self

    @model_validator(mode="after")
    def _guards(self) -> Settings:
        packs.load(self.domain_pack)
        if self.env != "development":
            if bool(self.knowledge_base_url) != bool(self.knowledge_bearer_token.get_secret_value()):
                raise ValueError("KNOWLEDGE_BASE_URL and KNOWLEDGE_BEARER_TOKEN must both be set or both empty")
            if self.mcp_dev_caller_number:
                raise ValueError("MCP_DEV_CALLER_NUMBER is allowed only when ENV=development")
            gateway = self.mcp_bearer_token.get_secret_value()
            lifecycle = self.mcp_lifecycle_bearer_token.get_secret_value()
            if lifecycle and lifecycle == gateway:
                raise ValueError("MCP_LIFECYCLE_BEARER_TOKEN must differ from MCP_BEARER_TOKEN (the lifecycle split is "
                                 "decided by the bearer)")
            if not (self.ops_client_id and self.ops_client_secret.get_secret_value()):
                raise ValueError("OPS_CLIENT_ID and OPS_CLIENT_SECRET are required outside development")
        if self.env == "production":
            for name, url in (("OPS_BASE_URL", self.ops_base_url), ("KNOWLEDGE_BASE_URL", self.knowledge_base_url)):
                if name == "KNOWLEDGE_BASE_URL" and not url:
                    continue  # only the knowledge tool is unavailable; scheduling remains independent
                if not url.startswith("https://"):
                    # Caller numbers, names and symptoms cross these hops: never in clear text in production.
                    raise ValueError(f"{name} must use https:// when ENV=production")
                if any(marker in url.lower() for marker in STUB_MARKERS):
                    raise ValueError(f"{name} points at a stub/mock endpoint; production needs the owner's service")
            gateway = self.mcp_bearer_token.get_secret_value()
            lifecycle = self.mcp_lifecycle_bearer_token.get_secret_value()
            if not gateway:
                raise ValueError("MCP_BEARER_TOKEN is required when ENV=production")
            if not lifecycle or lifecycle == gateway:
                raise ValueError("MCP_LIFECYCLE_BEARER_TOKEN is required and must differ from MCP_BEARER_TOKEN")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
