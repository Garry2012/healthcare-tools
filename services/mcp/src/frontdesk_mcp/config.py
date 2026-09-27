"""Adapter settings, from the environment: the rollout's rollout.env (which provider, which
domain, which languages) plus secrets. Nothing provider-specific is written in code."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from . import packs


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", frozen=True)

    env: Literal["development", "test", "staging", "production"] = "development"
    log_level: str = "INFO"
    host: str = "127.0.0.1"
    port: int = Field(default=8100, ge=1, le=65535)

    # The rollout (rollouts/<id>/rollout.env, shared with the API): no defaults.
    provider_id: str = Field(min_length=1)
    # Which words the LLM reads (packs/<name>.json); the same DOMAIN_PACK as the API's.
    domain_pack: str
    # The languages the rollout serves; the LLM is told to set `language` to one of them.
    tenant_supported_languages: str
    # Optional: the provider's name as the agent may say it ("Front-desk tools for ... at <name>").
    tenant_display_name: str = ""

    api_base_url: str = "http://127.0.0.1:8000/api/v1"
    api_bearer_token: SecretStr = SecretStr("")
    # Bearer the gateway (ContextForge) must present. Empty is allowed only in development.
    mcp_bearer_token: SecretStr = SecretStr("")
    # Dev only: used when the gateway forwards no X-Caller-Number.
    mcp_dev_caller_number: str = ""

    read_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    write_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    default_retry_after_seconds: int = Field(default=2, ge=0, le=300)

    @field_validator("tenant_supported_languages")
    @classmethod
    def _languages(cls, value: str) -> str:
        codes = [c.strip() for c in value.split(",") if c.strip()]
        if not codes or not all(c.isalpha() and c.islower() and 2 <= len(c) <= 3 for c in codes):
            raise ValueError("TENANT_SUPPORTED_LANGUAGES must list language codes, e.g. en,kn,hi")
        return ",".join(codes)

    @property
    def languages(self) -> tuple[str, ...]:
        return tuple(self.tenant_supported_languages.split(","))

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        packs.load(self.domain_pack)
        if self.env == "production":
            if not self.api_base_url.startswith("https://"):
                # Caller numbers and names cross this hop: never in clear text in production.
                raise ValueError("API_BASE_URL must use https:// when ENV=production")
            if self.mcp_dev_caller_number:
                raise ValueError("MCP_DEV_CALLER_NUMBER must not be set when ENV=production")
            if not self.mcp_bearer_token.get_secret_value():
                raise ValueError("MCP_BEARER_TOKEN is required when ENV=production")
        if self.env != "development" and not self.api_bearer_token.get_secret_value():
            raise ValueError("API_BEARER_TOKEN is required outside development")
        return self

    @property
    def api_root(self) -> str:
        base = self.api_base_url.rstrip("/")
        return base[: -len("/api/v1")] if base.endswith("/api/v1") else base


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
