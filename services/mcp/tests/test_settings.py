"""Configuration: one operational owner service, tenant identity, and production guards that
refuse development stubs, clear-text transport and missing credentials."""

from __future__ import annotations

import pytest

from frontdesk_mcp.config import Settings

PROD = {"env": "production", "ops_base_url": "https://ops.example/api/v1"}


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


def test_production_requires_https_for_operational_service(make_settings):
    with pytest.raises(ValueError, match="OPS_BASE_URL"):
        make_settings(**{**PROD, "ops_base_url": "http://ops.internal/api/v1"})


@pytest.mark.parametrize("url", [
    "https://healthcare-contract-mock.icytree-6543aaa9.centralindia.azurecontainerapps.io",
    "https://localhost:4010", "https://127.0.0.1:8443/api/v1", "https://ops-stub.internal/api/v1",
])
def test_production_refuses_known_stub_and_mock_endpoints(make_settings, url):
    with pytest.raises(ValueError, match="stub|mock"):
        make_settings(**{**PROD, "ops_base_url": url})


def test_production_requires_owner_credentials_and_gateway_bearer(make_settings):
    with pytest.raises(ValueError, match="OPS_CLIENT"):
        make_settings(**PROD, ops_client_secret="")
    with pytest.raises(ValueError, match="MCP_BEARER_TOKEN"):
        make_settings(**PROD, mcp_bearer_token="")
    with pytest.raises(ValueError, match="MCP_DEV_CALLER_NUMBER"):
        make_settings(**PROD, mcp_dev_caller_number="+919000000101")
    assert make_settings(**PROD).env == "production"




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


def test_budget_defaults_keep_reads_fast_and_writes_independent(make_settings):
    settings = make_settings()
    assert (settings.read_budget.total, settings.read_budget.exchange) == (0.3, 0.3)
    assert (settings.write_budget.total, settings.write_budget.exchange) == (3.0, 1.0)
    assert (settings.summary_budget.total, settings.summary_budget.exchange) == (8.0, 8.0)
    assert make_settings(voice_response_budget_seconds=0.8).read_budget.total == 0.1
    with pytest.raises(ValueError, match="reserved"):
        make_settings(voice_response_budget_seconds=0.6)


def test_read_share_has_no_bypass_and_write_may_exceed_voice_share(make_settings):
    with pytest.raises(ValueError, match="budget"):
        make_settings(read_deadline_seconds=0.4)
    try:
        settings = make_settings(write_deadline_seconds=4, write_exchange_timeout_seconds=2)
    except ValueError:
        pytest.fail("independent write budget was refused", pytrace=False)
    assert settings.write_budget.total == 4 and settings.read_budget.total == 0.3


def test_only_per_budget_exchange_fields_and_voice_budget_remain():
    assert {key for key in Settings.model_fields if "budget" in key} == {"voice_response_budget_seconds"}
    assert {key for key in Settings.model_fields if key.endswith("timeout_seconds")} == {
        "read_exchange_timeout_seconds", "write_exchange_timeout_seconds",
        "summary_exchange_timeout_seconds", "token_refresh_timeout_seconds"}


@pytest.mark.parametrize("name,value,want", [
    ("READ_DEADLINE_SECONDS", "0.2", ((0.2, 0.2), (3.0, 1.0), (8.0, 8.0))),
    ("READ_EXCHANGE_TIMEOUT_SECONDS", "0.1", ((0.3, 0.1), (3.0, 1.0), (8.0, 8.0))),
    ("WRITE_DEADLINE_SECONDS", "4", ((0.3, 0.3), (4.0, 1.0), (8.0, 8.0))),
    ("WRITE_EXCHANGE_TIMEOUT_SECONDS", "2", ((0.3, 0.3), (3.0, 2.0), (8.0, 8.0))),
    ("SUMMARY_DEADLINE_SECONDS", "9", ((0.3, 0.3), (3.0, 1.0), (9.0, 9.0))),
    ("SUMMARY_EXCHANGE_TIMEOUT_SECONDS", "4", ((0.3, 0.3), (3.0, 1.0), (8.0, 4.0))),
])
def test_each_budget_environment_value_changes_only_its_owner(monkeypatch, name, value, want):
    from .conftest import ENDPOINTS, ROLLOUT

    monkeypatch.setenv(name, value)
    try:
        settings = Settings(**ROLLOUT, **ENDPOINTS, env="test")
    except ValueError:
        pytest.fail("independent budget environment setting was refused", pytrace=False)
    assert tuple((budget.total, budget.exchange) for budget in (
        settings.read_budget, settings.write_budget, settings.summary_budget)) == want


@pytest.mark.parametrize("values,match", [
    ({"read_deadline_seconds": 2, "write_deadline_seconds": 1, "voice_response_budget_seconds": 3},
     "read <= write <= summary"),
    ({"write_deadline_seconds": 9}, "read <= write <= summary"),
    ({"summary_deadline_seconds": 0}, "greater than 0"),
    ({"write_deadline_seconds": 31}, "less than or equal to 30"),
    ({"summary_deadline_seconds": 61}, "less than or equal to 60"),
    ({"read_exchange_timeout_seconds": 0}, "greater than 0"),
    ({"write_exchange_timeout_seconds": 0}, "greater than 0"),
    ({"summary_exchange_timeout_seconds": 0}, "greater than 0"),
])
def test_invalid_budget_totals_and_nesting_are_refused(make_settings, values, match):
    with pytest.raises(ValueError, match=match):
        make_settings(**values)


async def test_production_serves_scheduling(make_settings):
    import httpx

    from frontdesk_mcp.availability import AvailabilityRequest
    from frontdesk_mcp.context import CallContext
    from frontdesk_mcp.tools import Services
    from frontdesk_stubs import ops as ops_stub

    from . import harness

    settings = make_settings(**PROD)
    h = harness.build(settings)

    services = Services.build(settings, clock=h.clock,
                              ops_transport=httpx.ASGITransport(app=ops_stub.create_app(h.ops_state, prefix="/api/v1")))
    try:
        result = await services.availability.get(
            CallContext(), AvailabilityRequest(date="today", doctorId="doc_garima"))
        assert result.outcome == "AVAILABILITY" and result.doctors[0].board[0].status == "IN"
    finally:
        await services.aclose()
        await h.aclose()


@pytest.mark.parametrize("url,token", [("http://retired-stub.invalid", "unused"), ("", "leftover-token")])
def test_production_ignores_retired_knowledge_environment(monkeypatch, url, token):
    from .conftest import ROLLOUT

    monkeypatch.setenv("KNOWLEDGE_BASE_URL", url)
    monkeypatch.setenv("KNOWLEDGE_BEARER_TOKEN", token)
    settings = Settings(**ROLLOUT, env="production", ops_base_url="https://ops.example/api/v1",
                        ops_client_id="client", ops_client_secret="secret", mcp_bearer_token="gateway")
    assert settings.ops_token_url == "https://ops.example/api/v1/auth/token"
    assert not any(name.startswith("knowledge_") for name in settings.model_dump())


@pytest.mark.parametrize("kind", ["read", "write", "summary"])
def test_budget_pairs_own_total_and_exchange_cap(make_settings, kind):
    settings = make_settings(**{f"{kind}_exchange_timeout_seconds": None})
    budget = getattr(settings, f"{kind}_budget")
    assert budget.total == getattr(settings, f"{kind}_deadline_seconds")
    assert budget.exchange == budget.total


@pytest.mark.parametrize("kind", ["read", "write", "summary"])
def test_exchange_cap_cannot_exceed_own_total(make_settings, kind):
    with pytest.raises(ValueError, match="exchange"):
        make_settings(**{f"{kind}_exchange_timeout_seconds": 9.0})
