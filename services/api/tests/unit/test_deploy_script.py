"""deploy/azure/deploy.sh in --dry-run: what it would ask Azure to do, for any rollout directory.

It cannot reach a subscription here; this pins the parts that must hold for every rollout: the
rollout validates before anything is created, its data rides in its own API image, its settings
(and nothing else) become the containers' settings, and no secret is ever printed.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
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
    assert "--value" not in hospital.stderr  # secrets go to Key Vault from a private file
    assert not re.search(r"(PGPASSWORD=|--admin-password )(?!\*\*\*)\S", hospital.stderr)
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


FAKE_AZ = """#!/usr/bin/env bash
# Stands in for the Azure CLI: nothing exists yet, queries answer, and Key Vault refuses writes
# (as it does for a minute or two after the role that allows them was assigned).
echo "$*" >> "$AZ_LOG"
case "$*" in
  *"keyvault secret set"*) exit 1 ;;
  *"--query"*) echo fake; exit 0 ;;
  *" show"*) exit 3 ;;
esac
exit 0
"""


def test_a_secret_key_vault_refuses_stops_the_deployment_before_the_database(tmp_path):
    """A password that was generated but never stored would be lost: the next run makes another,
    and the database created with the first one could no longer be reached."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "az").write_text(FAKE_AZ)
    (bin_dir / "az").chmod(0o755)
    (bin_dir / "psql").write_text("#!/bin/bash\nexit 0\n")
    (bin_dir / "psql").chmod(0o755)
    log = tmp_path / "az.log"
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
           "AZ_LOG": str(log), "KV_RETRY_SECONDS": "0"}
    result = subprocess.run([str(SCRIPT), str(DEMO_HOSPITAL)], capture_output=True, text=True, env=env, timeout=300)
    assert result.returncode != 0
    assert "could not store secret db-owner-password" in result.stderr
    called = log.read_text()
    assert called.count("keyvault secret set") == 6  # retried, then stopped
    assert "postgres flexible-server create" not in called and "containerapp create" not in called


def test_missing_psql_is_caught_before_azure_is_called(tmp_path):
    # An isolated PATH makes the test independent of whether the developer installed psql.
    for command in ("bash", "uv", "git", "openssl", "az", "curl", "dirname"):
        target = shutil.which(command)
        if target:
            (tmp_path / command).symlink_to(target)
        else:
            (tmp_path / command).write_text("#!/bin/bash\nexit 99\n")
            (tmp_path / command).chmod(0o755)
    result = subprocess.run([str(SCRIPT), str(DEMO_HOSPITAL)], capture_output=True, text=True,
                            env={**os.environ, "PATH": str(tmp_path)}, timeout=30)
    assert result.returncode != 0
    assert "missing prerequisite: psql" in result.stderr
    assert "== infrastructure" not in result.stderr


@pytest.fixture
def fake_cloud(tmp_path):
    """Exercise the real shell control flow without touching a subscription or database."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "commands.log"
    az = f"#!{sys.executable}\n" + '''
import json, os, sys
args = sys.argv[1:]
text = " ".join(args)
with open(os.environ["AZ_LOG"], "a") as log:
    log.write(text + "\\n")
if args[:3] == ["postgres", "flexible-server", "db"] and "show" in args:
    sys.exit(0 if os.environ.get("DATABASE_EXISTS") else 3)
if args[:3] == ["containerapp", "job", "show"]:
    sys.exit(3)
if args[:3] == ["postgres", "flexible-server", "firewall-rule"] and "delete" in args:
    sys.exit(int(os.environ.get("CLEANUP_FAIL", "0")))
if args[:2] == ["containerapp", "show"] and "yaml" in args:
    print(json.dumps({"properties": {"template": {"containers": [{}]}}}))
elif "--query" in args:
    query = args[args.index("--query") + 1]
    values = {"properties.healthState": "Unhealthy" if os.environ.get("UNHEALTHY") else "Healthy",
              "properties.latestRevisionName": "revision-new",
              "properties.latestReadyRevisionName": "revision-old" if os.environ.get("OLD_READY") else "revision-new",
              "properties.status": "Succeeded", "value": "stored-test-secret"}
    print(values.get(query, "fake"))
'''
    scripts = {
        "az": az,
        "curl": "#!/bin/bash\necho 203.0.113.10\n",
        "sleep": "#!/bin/bash\nexit 0\n",
        "psql": '''#!/bin/bash
echo "PSQL $*" >> "$AZ_LOG"
if [[ "$*" == *"-c SELECT 1"* ]]; then
  [[ -z "${PG_UNREACHABLE:-}" ]] || exit 1
  if [[ -n "${PG_TRANSIENT:-}" && ! -f "$AZ_LOG.connected" ]]; then
    touch "$AZ_LOG.connected"; exit 1
  fi
  exit 0
fi
cat >> "$AZ_LOG"
exit "${SQL_FAIL:-0}"
''',
        "uv": f'''#!/bin/bash
if [[ "$*" == *"deploy/azure/smoke.py"* ]]; then
  echo SMOKE >> "$AZ_LOG"
  exit "${{SMOKE_FAIL:-0}}"
fi
exec {shlex.quote(shutil.which("uv"))} "$@"
''',
    }
    for name, script in scripts.items():
        path = bin_dir / name
        path.write_text(script)
        path.chmod(0o755)

    def run(**overrides):
        env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "AZ_LOG": str(log), **overrides}
        result = subprocess.run([str(SCRIPT), str(DEMO_HOSPITAL)], capture_output=True, text=True,
                                env=env, timeout=60)
        return result, log.read_text()

    return run


@pytest.mark.parametrize("database_exists", ["", "1"])
def test_resume_repairs_roles_even_when_server_or_database_already_exists(fake_cloud, database_exists):
    result, log = fake_cloud(DATABASE_EXISTS=database_exists)
    assert result.returncode == 0, result.stderr
    assert "postgres flexible-server create" not in log
    assert ("postgres flexible-server db create" in log) == (not database_exists)
    assert "WHERE NOT EXISTS (SELECT 1 FROM pg_roles" in log
    assert "ON ALL TABLES IN SCHEMA public" in log
    assert log.index("COMMIT;") < log.index("firewall-rule delete") < log.index("job-migrate-")
    assert log.index("properties.healthState") < log.index("SMOKE")
    assert "== done:" in result.stderr
    assert "stored-test-secret" not in result.stdout + result.stderr


def test_failed_role_setup_removes_firewall_and_stops_before_migrations(fake_cloud):
    result, log = fake_cloud(SQL_FAIL="1")
    assert result.returncode != 0
    assert "firewall-rule delete" in log
    assert "job-migrate-" not in log and "== done:" not in result.stderr


@pytest.mark.parametrize("state", ["UNHEALTHY", "OLD_READY"])
def test_an_unready_new_revision_cannot_report_success(fake_cloud, state):
    result, log = fake_cloud(**{state: "1"})
    assert result.returncode != 0
    assert "did not become ready" in result.stderr
    assert "SMOKE" not in log and "== done:" not in result.stderr


def test_failed_functional_smoke_cannot_report_success(fake_cloud):
    result, log = fake_cloud(SMOKE_FAIL="1")
    assert result.returncode != 0
    assert "SMOKE" in log and "== done:" not in result.stderr


def test_transient_database_connectivity_is_retried(fake_cloud):
    result, log = fake_cloud(PG_TRANSIENT="1")
    assert result.returncode == 0, result.stderr
    assert log.count("-c SELECT 1") == 2


def test_unreachable_database_cleans_up_and_stops(fake_cloud):
    result, log = fake_cloud(PG_UNREACHABLE="1")
    assert result.returncode != 0
    assert "database did not become reachable" in result.stderr
    assert "firewall-rule delete" in log and "job-migrate-" not in log


def test_firewall_cleanup_failure_is_reported(fake_cloud):
    result, log = fake_cloud(CLEANUP_FAIL="1")
    assert result.returncode != 0
    assert "could not remove PostgreSQL firewall rule 'setup'" in result.stderr
    assert "job-migrate-" not in log and "== done:" not in result.stderr
