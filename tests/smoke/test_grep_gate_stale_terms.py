"""Tests for scripts/smoke/grep_gate_stale_terms.py (S14 consolidated gate).

Tests:
- Gate runs clean on current working tree in both --full (default) and
  --launcher-only modes (exit 0).
- Parametrized regression: injecting each forbidden term into a temp
  adapter-command file asserts the gate detects it (exit 1).
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_SCRIPT = REPO_ROOT / "scripts" / "smoke" / "grep_gate_stale_terms.py"


def run_gate(
    *extra_args: str,
    cwd: Path | None = None,
    extra_env: dict | None = None,
) -> subprocess.CompletedProcess:
    import os
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(GATE_SCRIPT), *extra_args],
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else str(REPO_ROOT),
        env=env,
    )


# ---------------------------------------------------------------------------
# Clean-tree smoke tests
# ---------------------------------------------------------------------------

class TestGatePassesClean:
    """Gate must exit 0 on the current working tree."""

    def test_full_mode_exits_zero(self):
        result = run_gate("--full")
        assert result.returncode == 0, (
            f"grep_gate_stale_terms.py --full exited {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_default_mode_exits_zero(self):
        """No-arg invocation (default --full) must also exit 0."""
        result = run_gate()
        assert result.returncode == 0, (
            f"grep_gate_stale_terms.py (default) exited {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_launcher_only_exits_zero(self):
        result = run_gate("--launcher-only")
        assert result.returncode == 0, (
            f"grep_gate_stale_terms.py --launcher-only exited {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_full_prints_ok_summary(self):
        result = run_gate("--full")
        assert "OK grep-gate (full)" in result.stdout, (
            f"Expected OK summary in stdout, got: {result.stdout!r}"
        )
        assert "0 forbidden terms" in result.stdout

    def test_launcher_only_prints_ok_summary(self):
        result = run_gate("--launcher-only")
        assert "OK grep-gate (launcher-only)" in result.stdout
        assert "0 forbidden terms" in result.stdout


# ---------------------------------------------------------------------------
# Regression tests — inject each forbidden term into a temp adapter file
# ---------------------------------------------------------------------------

# Each param: (snippet, rel_path_inside_tmp_roo_cmds, term_label)
# The temp file is created at REPO_ROOT / rel_path so the gate's globs pick
# it up.  We use .roo/commands/ as the scope common to all categories.

_ADAPTER_CMD_PATH = ".roo/commands/fake-s14-test.md"

FORBIDDEN_SNIPPETS = [
    # --- Category: alternative launchers in slash-command Markdown ---
    pytest.param(
        "python3 scripts/harness.py phase set plan",
        _ADAPTER_CMD_PATH,
        id="launcher-python3-scripts-harness",
    ),
    pytest.param(
        "python scripts/harness.py phase set plan",
        _ADAPTER_CMD_PATH,
        id="launcher-python-scripts-harness",
    ),
    pytest.param(
        "py scripts/harness.py phase set plan",
        _ADAPTER_CMD_PATH,
        id="launcher-py-scripts-harness",
    ),
    pytest.param(
        "scripts/show_phase_status.py",
        _ADAPTER_CMD_PATH,
        id="launcher-show-phase-status",
    ),
    # --- Category: deprecated fields in adapter files ---
    pytest.param(
        "automation_mode: manual",
        _ADAPTER_CMD_PATH,
        id="deprecated-field-automation-mode",
    ),
    pytest.param(
        "containment_layer: strict",
        _ADAPTER_CMD_PATH,
        id="deprecated-field-containment",
    ),
    pytest.param(
        "last_good_commit_sha: abc123",
        _ADAPTER_CMD_PATH,
        id="deprecated-field-last-good-commit-sha",
    ),
    pytest.param(
        "autopilot_budgets_remaining: 5",
        _ADAPTER_CMD_PATH,
        id="deprecated-field-autopilot-budgets-remaining",
    ),
    # --- Category: deprecated verbs ---
    pytest.param(
        "harness chain --resume",
        _ADAPTER_CMD_PATH,
        id="deprecated-verb-chain-resume",
    ),
    pytest.param(
        "harness chain --abort",
        _ADAPTER_CMD_PATH,
        id="deprecated-verb-chain-abort",
    ),
    # --- Category: deprecated env var ---
    pytest.param(
        "HARNESS_HUMAN=agent@example.com",
        _ADAPTER_CMD_PATH,
        id="deprecated-env-harness-human",
    ),
]


@pytest.mark.parametrize("snippet,rel_path", FORBIDDEN_SNIPPETS)
class TestGateDetectsRegressions:
    """Gate must exit 1 when a forbidden term is introduced in an adapter file."""

    def test_detects_forbidden_term(
        self,
        tmp_path: Path,
        snippet: str,
        rel_path: str,
    ) -> None:
        # Mirror enough repo structure so REPO_ROOT-relative globs resolve.
        # We create the forbidden file INSIDE the real repo tree using a
        # clearly-named test file so the gate's glob picks it up.
        target = REPO_ROOT / rel_path
        assert not target.exists(), (
            f"Test file {target} already exists — choose a different name."
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            textwrap.dedent(f"""\
            # Fake adapter command (S14 regression test — DO NOT COMMIT)
            {snippet}
            """),
            encoding="utf-8",
        )
        try:
            result = run_gate("--full")
            assert result.returncode == 1, (
                f"Gate should have exited 1 for snippet {snippet!r} in {rel_path}.\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )
            # Offending path should appear in stderr output.
            assert rel_path in result.stderr or target.name in result.stderr, (
                f"Expected {rel_path!r} in stderr.\nstderr: {result.stderr}"
            )
        finally:
            target.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Regression: word-boundary matching avoids false positives
# ---------------------------------------------------------------------------

class TestWordBoundaryMatching:
    """Word-boundary patterns must NOT trigger on legitimate sub-strings."""

    def test_windows_containment_degraded_not_flagged(self) -> None:
        """'windows_containment_degraded' must NOT match the containment_ check."""
        target = REPO_ROOT / ".roo/commands/fake-s14-wbtest.md"
        assert not target.exists()
        target.write_text(
            "sub_reason: windows_containment_degraded\n",
            encoding="utf-8",
        )
        try:
            result = run_gate("--full")
            assert result.returncode == 0, (
                f"'windows_containment_degraded' falsely triggered the containment_ gate.\n"
                f"stderr: {result.stderr}"
            )
        finally:
            target.unlink(missing_ok=True)

    def test_autopilot_guards_not_flagged_as_auto(self) -> None:
        """'--autopilot-guards' must NOT trigger the --auto check."""
        # --autopilot-guards is a valid harness CLI flag; should not match --auto
        # (this would only be an issue if --auto check is ever widened to scripts/lib)
        # Regression: injecting into a slash-cmd file confirms the regex boundary.
        target = REPO_ROOT / ".roo/commands/fake-s14-autoguard.md"
        assert not target.exists()
        target.write_text(
            "harness install --autopilot-guards\n",
            encoding="utf-8",
        )
        try:
            result = run_gate("--full")
            assert result.returncode == 0, (
                f"'--autopilot-guards' falsely triggered the --auto gate.\n"
                f"stderr: {result.stderr}"
            )
        finally:
            target.unlink(missing_ok=True)
