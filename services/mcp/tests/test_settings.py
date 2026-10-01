"""Configuration: two independent owner services, tenant identity, and production guards that
refuse development stubs, clear-text transport and missing credentials."""

from __future__ import annotations

import pytest

from frontdesk_mcp.config import Settings

PROD = {"env": "production", "ops_base_url": "https://ops.example/api/v1", "knowledge_base_url": "https://kb.example"}


def test_rollout_identity_is_required():
    from .conftest import ENDPOINTS, ROLLOUT
    for missing in ("tenant_timezone", "tenant_country_calling_code", "tenant_supported_languages", "provider_id"):
        with pytest.raises(ValueError, match=missing):
            Settings(**{k: v for k, v in ROLLOUT.items() if k != missing}, **ENDPOINTS, env="test")


def test_timezone_and_calling_code_are_validated(make_settings):
    with pytest.raises(ValueError, match="IANA"):
        make_settings(tenant_timezone="Mars/Olympus")
    with pytest.raises(ValueError, match="calling code"):
        make_settings(tenant_country_calling_code="+91")
    assert make_settings().tenant_timezone == "Asia/Kolkata"
    assert make_settings().zone.key == "Asia/Kolkata"


def test_language_list_is_validated(make_settings):
    with pytest.raises(ValueError, match="language codes"):
        make_settings(tenant_supported_languages="English")
    assert make_settings(tenant_supported_languages=" en, kn ").languages == ("en", "kn")


def test_the_legacy_single_api_setting_is_gone():
    assert "api_base_url" not in Settings.model_fields and "api_bearer_token" not in Settings.model_fields


def test_token_url_respects_the_full_configured_base_path(make_settings):
    backend = make_settings(ops_base_url="https://ops.example/api/v1/")
    mock = make_settings(ops_base_url="https://healthcare-contract-mock.example")
    assert backend.ops_token_url == "https://ops.example/api/v1/auth/token"
    assert mock.ops_token_url == "https://healthcare-contract-mock.example/auth/token"
    assert backend.ops_base_url == "https://ops.example/api/v1"  # trailing slash normalised


def test_production_requires_https_for_both_services(make_settings):
    with pytest.raises(ValueError, match="OPS_BASE_URL"):
        make_settings(**{**PROD, "ops_base_url": "http://ops.internal/api/v1"})
    with pytest.raises(ValueError, match="KNOWLEDGE_BASE_URL"):
        make_settings(**{**PROD, "knowledge_base_url": "http://kb.internal"})


@pytest.mark.parametrize("url", [
    "https://healthcare-contract-mock.icytree-6543aaa9.centralindia.azurecontainerapps.io",
    "https://localhost:4010", "https://127.0.0.1:8443/api/v1", "https://ops-stub.internal/api/v1",
])
def test_production_refuses_known_stub_and_mock_endpoints(make_settings, url):
    with pytest.raises(ValueError, match="stub|mock"):
        make_settings(**{**PROD, "ops_base_url": url})
    with pytest.raises(ValueError, match="stub|mock"):
        make_settings(**{**PROD, "knowledge_base_url": url})


def test_production_requires_credentials_and_distinct_lifecycle_token(make_settings):
    with pytest.raises(ValueError, match="OPS_CLIENT"):
        make_settings(**PROD, ops_client_secret="")
    with pytest.raises(ValueError, match="MCP_BEARER_TOKEN"):
        make_settings(**PROD, mcp_bearer_token="")
    with pytest.raises(ValueError, match="MCP_LIFECYCLE_BEARER_TOKEN"):
        make_settings(**PROD, mcp_lifecycle_bearer_token="")
    with pytest.raises(ValueError, match="MCP_LIFECYCLE_BEARER_TOKEN"):
        make_settings(**PROD, mcp_bearer_token="same", mcp_lifecycle_bearer_token="same")
    with pytest.raises(ValueError, match="MCP_DEV_CALLER_NUMBER"):
        make_settings(**PROD, mcp_dev_caller_number="+919000000101")
    assert make_settings(**PROD).env == "production"


def test_knowledge_service_is_required_outside_development(make_settings):
    with pytest.raises(ValueError, match="KNOWLEDGE_BASE_URL"):
        make_settings(knowledge_base_url="")
    assert make_settings(env="development", knowledge_base_url="").knowledge_base_url == ""


def test_credentials_are_required_outside_development(make_settings):
    with pytest.raises(ValueError, match="OPS_CLIENT"):
        make_settings(ops_client_id="")
    assert make_settings(env="development", ops_client_id="", ops_client_secret="").env == "development"


def test_deadlines_are_bounded_and_separate(make_settings):
    s = make_settings()
    assert 0 < s.read_deadline_seconds <= s.write_deadline_seconds <= s.summary_deadline_seconds
    with pytest.raises(ValueError):
        make_settings(read_deadline_seconds=0)
    with pytest.raises(ValueError):
        make_settings(read_deadline_seconds=31)


def test_accepted_caller_verification_is_a_set(make_settings):
    assert make_settings().accepted_verification == frozenset({"SIP_CALLER_ID"})
    assert make_settings(accepted_caller_verification="OTP, SIP_CALLER_ID").accepted_verification == frozenset(
        {"OTP", "SIP_CALLER_ID"})
    with pytest.raises(ValueError, match="ACCEPTED_CALLER_VERIFICATION"):
        make_settings(accepted_caller_verification="")


def test_unknown_pack_is_refused(make_settings):
    with pytest.raises(ValueError, match="Unknown DOMAIN_PACK"):
        make_settings(domain_pack="nonexistent")


def test_default_deadlines_fit_inside_a_one_second_turn_budget(make_settings):
    s = make_settings()
    assert s.read_deadline_seconds <= 1.2 and s.write_deadline_seconds <= 2.5 and s.request_timeout_seconds <= 0.8


# ------------------------------------------------------------------ architect review AR-06


def test_tool_deadlines_derive_from_the_voice_budget(make_settings):
    s = make_settings()
    assert s.voice_response_budget_seconds == 1.0 and s.reserved_stage_seconds == 0.65
    assert s.read_deadline_seconds == pytest.approx(0.35)  # 1.0 - 0.65: the tool's share of the caller's second
    assert s.request_timeout_seconds <= s.read_deadline_seconds
    assert s.write_deadline_seconds <= 0.6  # a confirmed write may use one more exchange than a read
    tighter = make_settings(voice_response_budget_seconds=0.8)
    assert tighter.read_deadline_seconds == pytest.approx(0.15)
    explicit = make_settings(read_deadline_seconds=2.0, write_deadline_seconds=2.0, request_timeout_seconds=1.5)
    assert explicit.read_deadline_seconds == 2.0  # diagnostic override stays explicit
    with pytest.raises(ValueError, match="reserved"):
        make_settings(voice_response_budget_seconds=0.6)
