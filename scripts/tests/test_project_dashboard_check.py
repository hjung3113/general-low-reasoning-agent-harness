"""Tests for project_dashboard.py --check mode.

Option-B reconciliation (test #2):
  `phase_folder_not_in_roadmap` has severity "warning" (non-blocking) per Task 3.2's spec.
  The plan's clarifying note states status=="ok" is allowed to coexist with non-blocking
  warning entries.  Therefore the second test asserts exit=0 and status="ok" but still
  verifies the warning code is present in the payload — rather than asserting EXIT_PLANNING_DRIFT.
"""

import json
import subprocess
import sys
from pathlib import Path

from tests._helpers.planning_repo import make_minimal_planning_repo

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(root):
    return subprocess.run(
        [sys.executable, "scripts/project_dashboard.py", "--check", "--root", str(root)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


def test_check_exit_zero_on_clean_fixture(tmp_path):
    root = make_minimal_planning_repo(tmp_path)
    result = _run(root)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert all(w["severity"] != "blocking" for w in payload["warnings"])


def test_check_exit_ok_on_extra_undeclared_phase(tmp_path):
    # Option-B reconciliation: phase_folder_not_in_roadmap is severity "warning" (non-blocking),
    # so --check exits 0 with status "ok" but includes the warning in the payload.
    root = make_minimal_planning_repo(tmp_path)
    (root / ".planning/milestones/02c-extra").mkdir()
    result = _run(root)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert any(w["code"] == "phase_folder_not_in_roadmap" for w in payload["warnings"])


def test_check_exit_drift_on_blocking_warning(tmp_path):
    from scripts.lib.exitcodes import EXIT_PLANNING_DRIFT

    root = make_minimal_planning_repo(tmp_path)
    (root / ".scratch/phase-state.json").write_text("{bad")
    result = _run(root)
    assert result.returncode == EXIT_PLANNING_DRIFT
    payload = json.loads(result.stdout)
    assert any(
        w["code"] == "phase_state_malformed_json" and w["severity"] == "blocking"
        for w in payload["warnings"]
    )
