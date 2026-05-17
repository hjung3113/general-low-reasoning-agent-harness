"""§12.10 release smoke case catalogue — S13 step-2 additions.

Each parametrize ID corresponds to a named `release_smoke_test.py --case <name>`
invocation described verbatim in §12.10 of the phase-gate hardening design spec
(docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md).

S13 step-1 implemented 5 fundamental cases (rows 1/2/3/5/6).
S13 step-2 implements 7 more cases (rows 4/7/8/12 + phase-autopilot-stop +
deny-listed-verb-via-shim + manifest-init-idempotency + windows-exit-11).

Remaining 3 cases (rows 9/10/11) stay skipped pending S15 (harness status/next).

S13 implementer checklist:
  1. Build `release_smoke_test.py --case <case_id>` infrastructure. ← DONE (step 1)
  2. Implement remaining deferred cases. ← DONE (step 2, this file)
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
# S13 step-2: 7 new cases (rows 4/7/8/12 + stop/deny-shim/manifest/windows)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case_id",
    [
        # §12.10 row 4 (OpenCode positional-negative; trailing token ignored)
        "run-phase-missing-positional-negative",
        # §12.10 row 7 (S10c network shim — POSIX deny curl)
        "net-deny-curl-posix",
        # §12.10 row 8 (S11 halt diary — budget-exhaustion halt-handoff)
        "halt-handoff-flow",
        # §12.10 row 12 (env-only spoof rejection — mandatory per §7 line 1020)
        "env-only-spoof-rejected",
        # phase autopilot stop flow (§3.5)
        "phase-autopilot-stop",
        # deny-listed git-push verb via shim (POSIX-only, §5.2)
        "deny-listed-verb-via-shim",
        # manifest init idempotency (§6 line 970)
        "manifest-init-idempotency",
        # windows-exit-11 (Windows-only chain-mode containment; POSIX skipped)
        "windows-exit-11",
    ],
)
def test_release_smoke_case_step2(case_id):
    """Subprocess-invoke release_smoke_test.py --case <id>, assert exit 0.

    POSIX-only cases (net-deny-curl-posix, deny-listed-verb-via-shim) and
    Windows-only cases (windows-exit-11) return a skip-sentinel (passed=True)
    on the wrong platform, so this test always exits 0 on any OS.

    Spec: docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md §12.10
    Slice: S13-smoke step 2
    """
    env = {**os.environ, **_CI_ENV}
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "release_smoke_test.py"),
            "--case", case_id,
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
# Remaining deferred cases (S15 dependency — kept skipped)
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="S15 dependency: harness status / harness next not yet built")
@pytest.mark.parametrize(
    "case_id",
    [
        # §12.10 table — row 9 (S15 status-after-halt)
        "status-after-halt",
        # §12.10 table — row 10 (S15 /fsd-status Roo)
        "fsd-status-roo",
        # §12.10 table — row 11 (S15 /fsd-status OpenCode)
        "fsd-status-opencode",
    ],
)
def test_release_smoke_case_deferred_s15(case_id):
    """Placeholder pinned to §12.10 case catalogue. Flips to real test when S15 lands.

    Spec: docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md §12.10
    Slice: S15 (harness status / harness next — not yet built)
    """
    pytest.fail("S15 harness-status/harness-next not yet built")
