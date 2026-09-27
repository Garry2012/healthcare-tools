"""deploy/azure/deploy.sh in --dry-run: what it would ask Azure to do, for any rollout directory.

It cannot reach a subscription here; this pins the parts that must hold for every rollout: the
rollout validates before anything is created, its data rides in its own API image, its settings
(and nothing else) become the containers' settings, and no secret is ever printed.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.conftest import DEMO_HOSPITAL, ROLLOUTS

SCRIPT = ROLLOUTS.parent / "deploy/azure/deploy.sh"
pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def dry_run(rollout: Path, *flags: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(SCRIPT), str(rollout), "--dry-run", *flags], capture_output=True, text=True,
                          timeout=300)


def calls(result: subprocess.CompletedProcess[str]) -> list[str]:
    return [line[2:] for line in result.stderr.splitlines() if line.startswith("+ ")]


@pytest.fixture(scope="module")
def hospital() -> subprocess.CompletedProcess[str]:
    return dry_run(DEMO_HOSPITAL, "--seed-demo")


def test_a_valid_rollout_is_deployed_as_its_own_image_and_settings(hospital):
    assert hospital.returncode == 0, hospital.stderr
    lines = calls(hospital)
    assert hospital.stderr.index("== validate") < hospital.stderr.index("+ az")
    assert any(re.search(r"acr build .* -t frontdesk-api-demo-hospital:\w+ ", c) for c in lines)
    apply = next(c for c in lines if "job create" in c and "job-apply-" in c)
    assert apply.endswith("--command frontdesk-api --args rollout apply -o none")
    assert "frontdesk-api-demo-hospital:" in apply and "ROLLOUT_DIR=/app/rollout" in apply
    assert "TENANT_SUPPORTED_LANGUAGES=en,kn,hi" in apply and "ENV=production" in apply
    api = next(c for c in lines if c.startswith("az containerapp create") and "-n api-" in c)
    mcp = next(c for c in lines if c.startswith("az containerapp create") and "-n mcp-" in c)
    assert "--ingress internal" in api and "frontdesk-api-demo-hospital:" in api
    assert "--ingress external" in mcp and "DOMAIN_PACK=healthcare" in mcp and "PROVIDER_ID=demo-hospital" in mcp
    order = [next(i for i, c in enumerate(lines) if key in c) for key in ("job-migrate-", "job-apply-", "-n api-")]
    assert order == sorted(order)  # schema first, then data, then the service that reads both


def test_no_secret_is_printed(hospital):
    assert not re.search(r"\b[0-9a-f]{48}\b", hospital.stderr)  # tokens
    assert not re.search(r"(--value|PGPASSWORD=|--admin-password) (?!\*\*\*)\S", hospital.stderr)
    assert "PASSWORD '" not in hospital.stderr


def test_a_rollout_that_fails_its_checks_creates_nothing(tmp_path):
    broken = tmp_path / "hospital-b"
    shutil.copytree(DEMO_HOSPITAL, broken)
    (broken / "dialogues.yaml").write_text('- {say: "chest pain", expect: OFFER_SLOTS}\n')
    result = dry_run(broken)
    assert result.returncode == 1
    assert calls(result) == []
    assert "expected OFFER_SLOTS" in result.stderr


def test_the_demo_scenario_is_refused_for_a_real_provider(tmp_path):
    real = tmp_path / "hospital-b"
    shutil.copytree(DEMO_HOSPITAL, real)
    env = (real / "rollout.env").read_text().replace("PROVIDER_ID=demo-hospital", "PROVIDER_ID=hospital-b")
    (real / "rollout.env").write_text(env)
    result = dry_run(real, "--seed-demo")
    assert result.returncode == 2 and "demo rollouts only" in result.stderr
    assert not [c for c in calls(result) if "job-seed" in c]
