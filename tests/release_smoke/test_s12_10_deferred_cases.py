"""§12.10 release smoke case catalogue — S13 step-1 pins.

Each parametrize ID corresponds to a named `release_smoke_test.py --case <name>`
invocation described verbatim in §12.10 of the phase-gate hardening design spec
(docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md).

S13 step-1 has implemented 5 fundamental cases (rows 1/2/3/5/6).  The remaining
10 cases (rows 4/7-15) stay skipped pending steps 2-3 (S08b, S10c, S11, S15, …).

S13 implementer checklist:
  1. Build `release_smoke_test.py --case <case_id>` infrastructure. ← DONE (step 1)
  2. Implement remaining deferred cases.
  3. When list is empty, delete this file.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# S13 step-1: 5 implemented cases (rows 1/2/3/5/6 of §12.10)
# ---------------------------------------------------------------------------

#: TEST-OIDC env vars required for CI authorization predicate (§3.5.1)
_CI_ENV = {
    "HARNESS_OIDC_TEST_MODE": "1",
    "HARNESS_AUTOMATION": "phase",
    "HARNESS_BY_TRUST": "ci-bot@smoke.example.com",
    "GITHUB_ACTIONS": "true",
    "GITHUB_RUN_ID": "9999999999",
    "GITHUB_REPOSITORY": "smoke-org/smoke-repo",
    "GITHUB_SHA": "aabbccdd11223344556677889900aabb11223344",
    "GITHUB_WORKFLOW": "smoke-ci.yml",
    "GITHUB_RUN_ATTEMPT": "1",
    "ACTIONS_ID_TOKEN_REQUEST_URL": "https://smoke.example.com/oidc",
    "HARNESS_TEST_OIDC_TOKEN_GITHUB_ACTIONS": "smoke-stub-token",
    "HARNESS_TEST_OIDC_CLAIMS_GITHUB_ACTIONS": (
        '{"iss":"https://token.actions.githubusercontent.com",'
        '"sub":"repo:smoke-org/smoke-repo:ref:refs/heads/main",'
        '"repository":"smoke-org/smoke-repo",'
        '"ref":"refs/heads/main",'
        '"sha":"aabbccdd11223344556677889900aabb11223344"}'
    ),
}


@pytest.mark.parametrize(
    "case_id",
    [
        "run-phase",               # §12.10 row 1
        "run-phase-empty-arg",     # §12.10 row 2
        "run-phase-multi-arg-fail",# §12.10 row 3
        "run-all",                 # §12.10 row 5
        "run-all-empty-roadmap",   # §12.10 row 6
    ],
)
def test_release_smoke_case_implemented(case_id):
    """Subprocess-invoke release_smoke_test.py --case <id> --adapter roo, assert exit 0.

    Spec: docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md §12.10
    Slice: S13-smoke step 1
    """
    env = {**os.environ, **_CI_ENV}
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "release_smoke_test.py"),
            "--case", case_id,
            "--adapter", "roo",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"case {case_id!r} failed (exit={result.returncode}):\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# Remaining deferred cases (steps 2-3 scope — kept skipped)
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="Release smoke harness (S13 steps 2-3 scope) not yet implemented")
@pytest.mark.parametrize(
    "case_id",
    [
        # §12.10 table — row 4 (OpenCode positional-negative; S08b primary case)
        "run-phase-missing-positional-negative",
        # §12.10 table — row 7 (S10c network shim)
        "net-deny-curl-posix",
        # §12.10 table — row 8 (S11 halt diary)
        "halt-handoff-flow",
        # §12.10 table — row 9
        "status-after-halt",
        # §12.10 table — row 10 (S15 /fsd-status Roo)
        "fsd-status-roo",
        # §12.10 table — row 11 (S15 /fsd-status OpenCode)
        "fsd-status-opencode",
        # §12.10 table — row 12 (env-only spoof rejection)
        "env-only-spoof-rejected",
        # §12.10 table — row 13 (OIDC jti replay)
        "oidc-jti-replay",
        # §12.10 table — row 14 (anchor tampered)
        "anchor-tampered",
        # §12.10 table — row 15 (gitconfig rotated post-install)
        "gitconfig-rotated",
    ],
)
def test_release_smoke_case_deferred(case_id):
    """Placeholder pinned to §12.10 case catalogue. Flips to real test when S13 step 2/3 lands.

    Spec: docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md §12.10
    Slice: S13-smoke steps 2-3 (depends_on S08b/S10c/S11/S15/S16)
    """
    pytest.fail("S13 release_smoke_test.py step 2/3 cases not yet built")
