"""One selected profile supplies URLs and credential references to runtime, tests and benchmarks."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"


def profile(tmp_path, name, mode="live"):
    (tmp_path / f"{name}.env").write_text(
        f"PROFILE={name}\nOPS_BASE_URL=https://{name}.example/api/v1\nOPS_E2E_MODE={mode}\n"
        "AZ_SUBSCRIPTION_ID=subscription\nAZ_KEYVAULT=test-vault\n"
        "OPS_CLIENT_ID_SECRET_NAME=custom-id\nOPS_CLIENT_SECRET_SECRET_NAME=custom-secret\n")


def test_switching_profiles_replaces_operational_urls(tmp_path):
    profile(tmp_path, "live")
    profile(tmp_path, "mock", "mock")
    keys = ["OPS_BASE_URL", "OPS_E2E_BASE_URL", "BENCH_OPS_BASE_URL"]
    probe = tmp_path / "probe.py"
    probe.write_text(f"import os,json; print(json.dumps({{k:os.environ.get(k) for k in {keys!r}}}))")
    result = subprocess.run(["bash", "-c",
                             'eval "$(scripts/env.sh live)"; python3 "$1"; '
                             'eval "$(scripts/env.sh mock)"; python3 "$1"', "profiles", str(probe)],
                            cwd=ROOT, env={**os.environ, "DEPLOY_PROFILE_DIR": str(tmp_path)},
                            text=True, capture_output=True, check=True)
    live, mock = map(json.loads, result.stdout.splitlines())
    assert all(live[k] == "https://live.example/api/v1" for k in keys)
    assert all(mock[k] == "https://mock.example/api/v1" for k in keys)


def test_launcher_uses_selected_vault_references_and_does_not_print_secrets(tmp_path):
    profile(tmp_path, "live")
    az = tmp_path / "az"
    az.write_text("#!/usr/bin/env python3\nimport sys\n"
                  "assert sys.argv[1:4] == ['keyvault','secret','show']\n"
                  "name=sys.argv[sys.argv.index('--name')+1]\n"
                  "print({'custom-id':'test-id-value','custom-secret':'test-secret-value'}[name])\n")
    az.chmod(0o700)
    probe = """import os
for names,expected in [
 (['OPS_CLIENT_ID','OPS_E2E_CLIENT_ID','BENCH_OPS_CLIENT_ID'],'test-id-value'),
 (['OPS_CLIENT_SECRET','OPS_E2E_CLIENT_SECRET','BENCH_OPS_CLIENT_SECRET'],'test-secret-value')]:
 assert all(os.environ[n] == expected for n in names)
print('profile credentials matched')
"""
    result = subprocess.run([str(SCRIPTS / "run-profile.sh"), "live", "--", sys.executable, "-c", probe],
                            env={**os.environ, "DEPLOY_PROFILE_DIR": str(tmp_path),
                                 "PATH": f"{tmp_path}:{os.environ['PATH']}", "BENCH_OPS_CLIENT_SECRET": "stale"},
                            capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "profile credentials matched" and result.stderr == ""
    assert "test-secret-value" not in result.stdout


def test_mock_launcher_never_reads_or_forwards_real_credentials(tmp_path):
    profile(tmp_path, "mock", "mock")
    az = tmp_path / "az"
    az.write_text("#!/bin/sh\nexit 99\n")
    az.chmod(0o700)
    probe = """import os
assert os.environ['OPS_CLIENT_SECRET'] == os.environ['OPS_E2E_CLIENT_SECRET'] == 'contract-example'
print('mock isolated')
"""
    result = subprocess.run([str(SCRIPTS / "run-profile.sh"), "mock", "--", sys.executable, "-c", probe],
                            env={**os.environ, "DEPLOY_PROFILE_DIR": str(tmp_path),
                                 "PATH": f"{tmp_path}:{os.environ['PATH']}", "OPS_CLIENT_SECRET": "real-value"},
                            capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "mock isolated" and result.stderr == ""
