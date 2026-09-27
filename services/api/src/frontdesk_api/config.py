"""Service settings, resolved in three layers: core default -> domain pack default -> rollout.

Every value comes from the process environment (a rollout's `rollout.env` plus secrets); the
service never reads a `.env` file itself (compose and the Makefile load it). A domain pack may
default any tenant setting (`Pack.settings`); what the rollout sets always wins. Identity
settings (who the provider is, its timezone, phone numbering, currency and languages) have no
default at any layer: a rollout that forgets one fails to start instead of inheriting another's.
"""

from __future__ import annotations

import json
import os
import re
from datetime import time
from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from . import locales, packs
from .domain.availability import EngineConfig
from .domain.knowledge import Thresholds as KnowledgeThresholds
from .domain.resolver import ResolverThresholds

DAY_PART_DEFAULT = '{"MORNING":["06:00","12:00"],"AFTERNOON":["12:00","16:00"],"EVENING":["16:00","23:00"]}'


_SSLMODE = re.compile(r"([?&])sslmode=")


# Never in a rollout's files: they are committed or baked into an image; these live in the secret store.
SECRETS = frozenset({"database_url", "auth_tokens_json", "api_bearer_token", "mcp_bearer_token"})
# Deployment wiring, set by compose or deploy.sh, not by a rollout.
DEPLOYMENT = frozenset({"env", "host", "port", "rollout_dir", "api_base_url", "mcp_dev_caller_number"})

# Settings a rollout must state itself: never defaulted by the core or a domain pack.
IDENTITY = frozenset({
    "provider_id", "domain_pack", "tenant_timezone", "tenant_country_calling_code", "tenant_phone_pattern",
    "tenant_currency", "tenant_supported_languages",
})


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
    # Voice reads answer COULD_NOT_CHECK rather than keep a caller waiting.
    read_timeout_seconds: float = Field(default=2.0, ge=0.1, le=30.0)
    # Waiting for a pooled connection counts against the same budget.
    database_pool_timeout_seconds: float = Field(default=2.0, ge=0.1, le=30.0)
    # Server-side cap per statement; not sent through a transaction pooler (pgbouncer rejects it).
    database_statement_timeout_ms: int = Field(default=5000, ge=100, le=60000)
    max_request_bytes: int = Field(default=65536, ge=1024, le=10_485_760)

    # --- rollout identity: required, no default anywhere (rollouts/<id>/rollout.env) ---
    # Which provider this deployment serves; on every log line.
    provider_id: str = Field(min_length=1)
    # The domain pack (packs/<name>) this rollout instantiates.
    domain_pack: str
    tenant_timezone: str
    tenant_country_calling_code: str = Field(pattern=r"^[0-9]{1,3}$")
    tenant_phone_pattern: str
    tenant_currency: str = Field(pattern=r"^[A-Z]{3}$")
    # The languages this rollout serves, comma-separated (locales/<code>.py must exist for each).
    tenant_supported_languages: str
    # Where the rollout's data files are inside the container (`rollout apply` and `seed` read them).
    rollout_dir: str = ""
    # Optional: the provider's name as the agent may say it. The MCP adapter puts it in the agent's
    # instructions; declared here too so `rollout validate` knows every key a rollout may write.
    tenant_display_name: str = ""

    # --- tenant behaviour: core defaults, which the domain pack or the rollout may override ---
    tenant_day_parts_json: str = DAY_PART_DEFAULT
    tenant_default_capacity: int = Field(default=12, ge=1)
    tenant_last_arrival_offset_minutes: int = Field(default=15, ge=0)
    tenant_walk_in_reserve_percent: int = Field(default=0, ge=0, le=100)
    tenant_sequence_window_minutes: int = Field(default=20, ge=1)
    # A shorter queue only moves someone to a position whose window ends at least this far ahead.
    tenant_move_lead_minutes: int = Field(default=15, ge=0, le=240)
    tenant_default_slot_minutes: int = Field(default=15, ge=1)
    tenant_search_default_days: int = Field(default=7, ge=1, le=31)
    # The agent never computes more than this many days in one search (voice latency, payload).
    tenant_search_max_days: int = Field(default=31, ge=1, le=62)
    # How far ahead a booking may be made.
    tenant_booking_horizon_days: int = Field(default=180, ge=1, le=730)
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

    @model_validator(mode="before")
    @classmethod
    def _domain_defaults(cls, data: object) -> object:
        """The middle layer: the domain pack's defaults, under whatever the rollout set."""
        if not isinstance(data, dict) or not isinstance(data.get("domain_pack"), str):
            return data  # the field validation reports the missing pack
        pack = packs.load(data["domain_pack"])
        for key in pack.settings:
            if key in IDENTITY or key not in cls.model_fields:
                raise ValueError(f"domain pack {pack.name!r} cannot default {key!r}")
        return {**pack.settings, **data}

    @field_validator("tenant_supported_languages")
    @classmethod
    def _languages(cls, value: str) -> str:
        codes = [c.strip() for c in value.split(",") if c.strip()]
        if not codes:
            raise ValueError("at least one language is required")
        if unknown := [c for c in codes if c not in locales.AVAILABLE]:
            raise ValueError(f"no language module for {', '.join(unknown)} (locales/)")
        return ",".join(codes)

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
    def languages(self) -> tuple[str, ...]:
        return tuple(self.tenant_supported_languages.split(","))

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
    def knowledge_thresholds(self) -> KnowledgeThresholds:
        return KnowledgeThresholds(answer=self.tenant_knowledge_answer_threshold,
                                   clarify=self.tenant_knowledge_clarify_threshold)

    @property
    def async_database_url(self) -> str:
        return async_url(self.database_url.get_secret_value())


def async_url(url: str) -> str:
    """The SQLAlchemy asyncpg form of a PostgreSQL URL."""
    # Managed PostgreSQL (Azure, Supabase) hands out libpq URLs with `sslmode=`; asyncpg
    # takes the same values as `ssl=` and fails on `sslmode`.
    url = _SSLMODE.sub(r"\1ssl=", url)
    for prefix in ("postgresql+asyncpg://", "postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix):]
    return url


def migration_database_url() -> str:
    """Migrations need only the owner's database URL, never a rollout's settings."""
    return async_url(os.environ.get("DATABASE_URL", ""))


class FileSettings(Settings):
    """Settings from given values only (a rollout's file), never the process environment: a
    setting the file forgets must fail validation, not be filled in by whoever runs it."""

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings,
                                   file_secret_settings):
        return (init_settings,)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
