"""Integration test for `scripts/release_smoke_test.py --release` flag (S13 step 3).

Subprocess-invokes the smoke runner with --release --evidence-dir <tmp> and
asserts:
  - exit code 0
  - evidence dir contains per-case subdirs each with result.json
  - summary line "N passed, M failed, K skipped" present in stdout

Spec: docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md §7.1 + §12.10
Slice: S13-smoke step 3
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_SMOKE_SCRIPT = REPO_ROOT / "scripts" / "release_smoke_test.py"


@pytest.fixture
def evidence_dir(tmp_path):
    """Provide a temporary evidence directory for the smoke run."""
    ev = tmp_path / "release-evidence"
    ev.mkdir()
    return ev


def test_release_flag_exits_zero(evidence_dir):
    """--release --evidence-dir exits 0 when all cases pass."""
    result = subprocess.run(
        [sys.executable, str(RELEASE_SMOKE_SCRIPT), "--release", "--evidence-dir", str(evidence_dir)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Expected exit 0, got {result.returncode}.\n"
        f"stdout: {result.stdout[-2000:]!r}\n"
        f"stderr: {result.stderr[-2000:]!r}"
    )


def test_release_flag_writes_evidence_dirs(evidence_dir):
    """--release writes per-case subdirs in the evidence dir."""
    subprocess.run(
        [sys.executable, str(RELEASE_SMOKE_SCRIPT), "--release", "--evidence-dir", str(evidence_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    # At least one case dir must exist
    case_dirs = [d for d in evidence_dir.iterdir() if d.is_dir()]
    assert len(case_dirs) > 0, "Expected per-case subdirs in evidence dir, found none"


def test_release_flag_each_case_has_result_json(evidence_dir):
    """Each per-case subdir must contain result.json."""
    subprocess.run(
        [sys.executable, str(RELEASE_SMOKE_SCRIPT), "--release", "--evidence-dir", str(evidence_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    case_dirs = [d for d in evidence_dir.iterdir() if d.is_dir()]
    assert len(case_dirs) > 0, "No case evidence dirs found"
    for case_dir in case_dirs:
        result_json = case_dir / "result.json"
        assert result_json.exists(), f"Missing result.json in {case_dir}"
        data = json.loads(result_json.read_text(encoding="utf-8"))
        assert "case_name" in data, f"result.json missing case_name in {case_dir}"
        assert "passed" in data, f"result.json missing passed field in {case_dir}"
        assert "exit_code" in data, f"result.json missing exit_code in {case_dir}"


def test_release_flag_summary_line_in_stdout(evidence_dir):
    """--release prints a summary line 'N passed, M failed, K skipped'."""
    result = subprocess.run(
        [sys.executable, str(RELEASE_SMOKE_SCRIPT), "--release", "--evidence-dir", str(evidence_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "passed" in result.stdout and "failed" in result.stdout and "skipped" in result.stdout, (
        f"Expected summary line in stdout, got:\n{result.stdout[-1000:]!r}"
    )
    # Summary line format: "N passed, M failed, K skipped"
    assert any(
        "passed" in line and "failed" in line and "skipped" in line
        for line in result.stdout.splitlines()
    ), f"No summary line found in stdout:\n{result.stdout!r}"


def test_release_flag_result_json_fields_valid(evidence_dir):
    """Each result.json must have valid structure (case_name, passed, assertions list)."""
    subprocess.run(
        [sys.executable, str(RELEASE_SMOKE_SCRIPT), "--release", "--evidence-dir", str(evidence_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    case_dirs = [d for d in evidence_dir.iterdir() if d.is_dir()]
    for case_dir in case_dirs:
        result_json = case_dir / "result.json"
        if not result_json.exists():
            continue
        data = json.loads(result_json.read_text(encoding="utf-8"))
        assert isinstance(data.get("assertions"), list), (
            f"assertions must be a list in {case_dir}/result.json"
        )
        assert isinstance(data.get("passed"), bool), (
            f"passed must be bool in {case_dir}/result.json"
        )


def test_release_flag_known_cases_have_evidence(evidence_dir):
    """Core cases from §12.10 must have evidence dirs when they run on this platform."""
    subprocess.run(
        [sys.executable, str(RELEASE_SMOKE_SCRIPT), "--release", "--evidence-dir", str(evidence_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    # These cases run on all platforms (no platform restriction)
    always_run_cases = [
        "run-phase",
        "run-phase-empty-arg",
        "run-phase-multi-arg-fail",
        "run-all",
        "run-all-empty-roadmap",
        "halt-handoff-flow",
        "env-only-spoof-rejected",
        "phase-autopilot-stop",
        "manifest-init-idempotency",
    ]
    present_dirs = {d.name for d in evidence_dir.iterdir() if d.is_dir()}
    for case_name in always_run_cases:
        assert case_name in present_dirs, (
            f"Expected evidence dir for {case_name!r}, found: {sorted(present_dirs)}"
        )
