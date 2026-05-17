"""Tests for scripts/smoke/grep_gate_slash_rename.py.

Tests:
- Gate runs clean on current working tree (exit 0).
- Parametrized regression: temp file with forbidden ref is detected (exit 1).
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_SCRIPT = REPO_ROOT / "scripts" / "smoke" / "grep_gate_slash_rename.py"

# Forbidden patterns the gate must detect (old slash command names).
FORBIDDEN_SNIPPETS = [
    pytest.param(
        "/fsd-phase",
        ".roo/commands/fake-test-cmd.md",
        id="fsd-phase-in-roo-command",
    ),
    pytest.param(
        "/fsd-chain-phase",
        ".roo/commands/fake-chain-cmd.md",
        id="fsd-chain-phase-in-roo-command",
    ),
    pytest.param(
        "use `/fsd-phase` to run a phase",
        "docs/fake-doc.md",
        id="fsd-phase-in-docs",
    ),
    pytest.param(
        "use `/fsd-chain-phase` for chaining",
        "docs/fake-chain-doc.md",
        id="fsd-chain-phase-in-docs",
    ),
]


def run_gate(cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GATE_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else str(REPO_ROOT),
    )


class TestGatePassesClean:
    """Gate must exit 0 on the current working tree."""

    def test_exits_zero_on_current_tree(self):
        result = run_gate()
        assert result.returncode == 0, (
            f"grep_gate_slash_rename.py exited {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_prints_success_summary(self):
        result = run_gate()
        assert "slash-rename grep gate" in result.stdout, (
            f"Expected success summary in stdout, got: {result.stdout!r}"
        )
        assert "0 forbidden references found" in result.stdout


@pytest.mark.parametrize("snippet,rel_path", FORBIDDEN_SNIPPETS)
class TestGateDetectsRegressions:
    """Gate must exit 1 when a forbidden reference is introduced."""

    def test_detects_forbidden_ref(self, tmp_path, snippet, rel_path):
        # Create a minimal repo-like tree with a forbidden file.
        target = tmp_path / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            textwrap.dedent(f"""\
            # Fake file
            {snippet}
            """),
            encoding="utf-8",
        )
        # Run gate with tmp_path as repo root via env override.
        result = subprocess.run(
            [sys.executable, str(GATE_SCRIPT), "--repo-root", str(tmp_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1, (
            f"Gate should have exited 1 for snippet {snippet!r} in {rel_path}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        # Offending file path should appear in stderr.
        assert rel_path in result.stderr or rel_path.split("/")[-1] in result.stderr, (
            f"Expected offending path in stderr.\nstderr: {result.stderr}"
        )
