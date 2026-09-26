"""Service settings and tenant configuration (IMPLEMENTATION.md §2.9).

Every value comes from the process environment; the service never reads a `.env` file
itself (compose and the Makefile load it). Nothing provider- or domain-specific lives in code.
"""

from __future__ import annotations

import json
import re
from datetime import time
from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from . import packs
from .domain.availability import EngineConfig
from .domain.resolver import ResolverThresholds

DAY_PART_DEFAULT = '{"MORNING":["06:00","12:00"],"AFTERNOON":["12:00","16:00"],"EVENING":["16:00","23:00"]}'


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", frozen=True)

    # --- service ---------------------------------------------------------
    env: Literal["development", "test", "staging", "production"] = "development"
    log_level: str = "INFO"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    database_url: SecretStr = SecretStr("")
    database_pool_size: int = Field(default=5, ge=1, le=50)
    # Supabase's transaction pooler (pgbouncer) cannot use prepared statements.
    database_disable_prepared_statements: bool = False
    auth_tokens_json: SecretStr = SecretStr("{}")
    write_timeout_seconds: float = Field(default=5.0, ge=0.5, le=30.0)

    # --- domain pack (packs/<name>): vocabulary data, escalation, demo seed ---
    domain_pack: str = "healthcare"

    # --- tenant: this deployment's provider (one deployment per provider) ---
    tenant_timezone: str = "Asia/Kolkata"
    tenant_country_calling_code: str = "91"
    tenant_phone_pattern: str = r"^[0-9]{10}$"
    tenant_currency: str = "INR"
    tenant_day_parts_json: str = DAY_PART_DEFAULT
    tenant_default_capacity: int = Field(default=12, ge=1)
    tenant_last_arrival_offset_minutes: int = Field(default=15, ge=0)
    tenant_walk_in_reserve_percent: int = Field(default=0, ge=0, le=100)
    tenant_sequence_window_minutes: int = Field(default=20, ge=1)
    tenant_default_slot_minutes: int = Field(default=15, ge=1)
    tenant_search_default_days: int = Field(default=7, ge=1, le=31)
    tenant_next_bookable_horizon_days: int = Field(default=14, ge=1, le=60)
    tenant_resolver_resource_threshold: float = Field(default=0.8, ge=0, le=1)
    tenant_resolver_category_threshold: float = Field(default=0.8, ge=0, le=1)
    tenant_resolver_suggestion_cutoff: float = Field(default=0.7, ge=0, le=1)
    tenant_knowledge_answer_threshold: float = Field(default=0.6, ge=0, le=1)
    tenant_knowledge_clarify_threshold: float = Field(default=0.35, ge=0, le=1)
    tenant_disclosure_policy: Literal["NAME_REQUIRED"] = "NAME_REQUIRED"
    tenant_cancel_on_spoken_number: bool = False
    tenant_desk_follow_up_list_enabled: bool = True
    # Empty = the domain pack's defaults.
    tenant_transfer_destinations_json: str = ""
    tenant_supported_languages: str = "en,kn,hi"

    @field_validator("domain_pack")
    @classmethod
    def _pack(cls, value: str) -> str:
        packs.load(value)
        return value

    @field_validator("tenant_timezone")
    @classmethod
    def _tz(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown IANA timezone {value!r}") from exc
        return value

    @field_validator("tenant_phone_pattern")
    @classmethod
    def _pattern(cls, value: str) -> str:
        re.compile(value)
        return value

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.tenant_timezone)

    @property
    def day_parts(self) -> dict[str, tuple[time, time]]:
        raw = json.loads(self.tenant_day_parts_json)
        return {k: (time.fromisoformat(v[0]), time.fromisoformat(v[1])) for k, v in raw.items()}

    @property
    def pack(self) -> packs.Pack:
        return packs.load(self.domain_pack)

    @property
    def transfer_destinations(self) -> dict[str, str]:
        if not self.tenant_transfer_destinations_json:
            return dict(self.pack.transfer_destinations)
        return dict(json.loads(self.tenant_transfer_destinations_json))

    @property
    def engine(self) -> EngineConfig:
        return EngineConfig(
            default_capacity=self.tenant_default_capacity,
            default_walk_in_reserve_percent=self.tenant_walk_in_reserve_percent,
            default_last_arrival_offset_minutes=self.tenant_last_arrival_offset_minutes,
            sequence_window_minutes=self.tenant_sequence_window_minutes,
            default_slot_minutes=self.tenant_default_slot_minutes,
        )

    @property
    def thresholds(self) -> ResolverThresholds:
        return ResolverThresholds(
            resource=self.tenant_resolver_resource_threshold,
            category=self.tenant_resolver_category_threshold,
            suggestion=self.tenant_resolver_suggestion_cutoff,
        )

    @property
    def async_database_url(self) -> str:
        url = self.database_url.get_secret_value()
        for prefix in ("postgresql+asyncpg://", "postgresql://", "postgres://"):
            if url.startswith(prefix):
                return "postgresql+asyncpg://" + url[len(prefix):]
        return url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
