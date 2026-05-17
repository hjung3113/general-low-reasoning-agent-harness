"""Tests for scripts/smoke/verify_fix_lines.py (S16 Fix: enforcer).

Tests:
- The enforcer script itself runs clean (exit 0) on the current codebase.
- Each non-Windows exit case trigger produces the correct exit code.
- Each trigger's stderr contains "Fix:".
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ENFORCER = REPO_ROOT / "scripts" / "smoke" / "verify_fix_lines.py"


def run_enforcer(*extra_args: str) -> subprocess.CompletedProcess:
    import os

    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT) + (":" + env["PYTHONPATH"] if "PYTHONPATH" in env else "")
    return subprocess.run(
        [sys.executable, str(ENFORCER), *extra_args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=180,
    )


def test_enforcer_exits_zero() -> None:
    """Enforcer reports 0 failures on the current codebase (§3.9 S16)."""
    result = run_enforcer()
    assert result.returncode == 0, (
        f"verify_fix_lines.py exited {result.returncode}.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "0 failed" in result.stdout


def test_enforcer_summary_line() -> None:
    """Enforcer prints the pass/skip summary on stdout."""
    result = run_enforcer()
    assert "passed" in result.stdout
    assert "skipped" in result.stdout


@pytest.mark.parametrize(
    "exit_code,name",
    [
        (2, "invalid_transition"),
        (3, "session_locked"),
        (4, "scope_violation"),
        (5, "unparseable_state"),
        (6, "non_tty_approval_blocked"),
        (7, "stale_uncertain"),
        (8, "approve_during_autopilot"),
        (9, "budget_exhausted"),
        (10, "audit_chain_mismatch"),
        # 11 skipped: Windows-only
        (12, "git_repo_required"),
        (13, "deprecated_flag"),
        (14, "crash_recovery_undecidable"),
        (16, "chain_start_dirty_tree"),
        (17, "human_action_required"),
        (18, "no_action_during_autopilot"),
    ],
)
def test_each_exit_case_passes(exit_code: int, name: str) -> None:
    """Each individual exit case trigger produces the right code + Fix: in stderr."""
    import os
    import sys as _sys

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        from scripts.smoke.verify_fix_lines import EXIT_CASES  # type: ignore[import]
    finally:
        if str(REPO_ROOT / "scripts") in sys.path:
            sys.path.remove(str(REPO_ROOT / "scripts"))

    # Also add REPO_ROOT so scripts package resolves correctly
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from scripts.smoke.verify_fix_lines import EXIT_CASES  # noqa: F811
    except ImportError:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from scripts.smoke import verify_fix_lines as _m  # type: ignore[import]
        EXIT_CASES = _m.EXIT_CASES

    case = next((c for c in EXIT_CASES if c.code == exit_code and c.name == name), None)
    assert case is not None, f"No ExitCase registered for code={exit_code} name={name}"

    if case.skip_reason:
        pytest.skip(case.skip_reason)

    ok, msg = case.verify(verbose=False)
    assert ok, msg
