"""Adapter settings. All from the environment; nothing provider-specific."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from . import packs


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", frozen=True)

    env: Literal["development", "test", "staging", "production"] = "development"
    log_level: str = "INFO"
    host: str = "127.0.0.1"
    port: int = Field(default=8100, ge=1, le=65535)

    # Which words the LLM reads (packs/<name>.json); must match the API's DOMAIN_PACK.
    domain_pack: str = "healthcare"

    api_base_url: str = "http://127.0.0.1:8000/api/v1"
    api_bearer_token: SecretStr = SecretStr("")
    # Bearer the gateway (ContextForge) must present. Empty is allowed only in development.
    mcp_bearer_token: SecretStr = SecretStr("")
    # Dev only: used when the gateway forwards no X-Caller-Number.
    mcp_dev_caller_number: str = ""

    read_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    write_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    default_retry_after_seconds: int = Field(default=2, ge=0, le=300)

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        packs.load(self.domain_pack)
        if self.env == "production":
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
