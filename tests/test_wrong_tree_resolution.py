"""Tests for T9 — state show resolves root from cwd, not __file__.

Done-criterion: state show from any cwd inside a project hits THAT
project's state, not the harness source tree's state.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Ensure scripts/ is importable when pytest is run from repo root.
_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from tests._helpers.planning_repo import make_minimal_planning_repo


# ---------------------------------------------------------------------------
# Helper: make a minimal project with a known phase
# ---------------------------------------------------------------------------

def _make_project(project_path: Path, *, phase: str = "plan", phase_id: str = "03") -> Path:
    """Build a minimal harness project dir with a specific phase in phase-state."""
    project_path.mkdir(parents=True, exist_ok=True)
    root = make_minimal_planning_repo(
        project_path,
        phase_id=phase_id,
        phase_folder=f"{phase_id}-test",
        roadmap_title="Test",
        checkpoint_id=f"CP-{phase_id}-01",
        phase_state_overrides={"phase": phase},
    )
    return root


# ---------------------------------------------------------------------------
# resolve_root() unit tests (no subprocess needed)
# ---------------------------------------------------------------------------

class TestResolveRootUnit:
    """Unit tests for state_cli.resolve_root()."""

    def test_cli_root_arg_takes_priority(self, tmp_path, monkeypatch):
        """--root <path> is returned as-is (resolved)."""
        from lib.state_cli import resolve_root

        monkeypatch.delenv("HARNESS_STATE_ROOT", raising=False)
        result = resolve_root(tmp_path)
        assert result == tmp_path.resolve()

    def test_env_var_takes_priority_over_cwd(self, tmp_path, monkeypatch):
        """HARNESS_STATE_ROOT overrides cwd walk-up."""
        from lib.state_cli import resolve_root

        monkeypatch.setenv("HARNESS_STATE_ROOT", str(tmp_path))
        monkeypatch.delenv("HARNESS_STATE_ROOT", raising=False)
        # With env explicitly set
        monkeypatch.setenv("HARNESS_STATE_ROOT", str(tmp_path))
        result = resolve_root(None)
        assert result == tmp_path.resolve()

    def test_cwd_walk_finds_scratch_dir(self, tmp_path, monkeypatch):
        """Walk-up stops at the directory containing .scratch/phase-state.json."""
        from lib.state_cli import resolve_root

        monkeypatch.delenv("HARNESS_STATE_ROOT", raising=False)
        project = _make_project(tmp_path / "myproject")
        subdir = project / "deep" / "nested"
        subdir.mkdir(parents=True)
        monkeypatch.chdir(subdir)

        result = resolve_root(None)
        assert result == project.resolve()

    def test_cwd_walk_finds_harness_dir(self, tmp_path, monkeypatch):
        """Walk-up also stops at a directory containing .harness/."""
        from lib.state_cli import resolve_root

        monkeypatch.delenv("HARNESS_STATE_ROOT", raising=False)
        # Create a project that only has .harness (not .scratch/phase-state.json)
        project = tmp_path / "harnessonly"
        project.mkdir()
        (project / ".harness").mkdir()
        subdir = project / "sub"
        subdir.mkdir()
        monkeypatch.chdir(subdir)

        result = resolve_root(None)
        assert result == project.resolve()

    def test_no_project_raises_system_exit(self, tmp_path, monkeypatch):
        """When no harness project is found in ancestry, SystemExit is raised."""
        from lib.state_cli import resolve_root

        monkeypatch.delenv("HARNESS_STATE_ROOT", raising=False)
        # Use a tmp dir with no .scratch or .harness markers
        empty = tmp_path / "empty_project"
        empty.mkdir()
        monkeypatch.chdir(empty)

        with pytest.raises(SystemExit) as exc_info:
            resolve_root(None)
        assert "no harness project found" in str(exc_info.value)

    def test_error_message_mentions_overrides(self, tmp_path, monkeypatch):
        """Error message hints at --root and HARNESS_STATE_ROOT."""
        from lib.state_cli import resolve_root

        monkeypatch.delenv("HARNESS_STATE_ROOT", raising=False)
        empty = tmp_path / "bare"
        empty.mkdir()
        monkeypatch.chdir(empty)

        with pytest.raises(SystemExit) as exc_info:
            resolve_root(None)
        msg = str(exc_info.value)
        assert "--root" in msg or "HARNESS_STATE_ROOT" in msg


# ---------------------------------------------------------------------------
# Integration: run_show resolves the correct project's phase
# ---------------------------------------------------------------------------

class TestRunShowCwdResolution:
    """run_show picks up the correct project based on cwd walk-up."""

    def test_show_from_project_cwd_reflects_project_phase(self, tmp_path, monkeypatch):
        """state show from within a project returns THAT project's phase."""
        import io
        from lib.state_cli import run_show, resolve_root

        monkeypatch.delenv("HARNESS_STATE_ROOT", raising=False)
        project = _make_project(tmp_path / "proj", phase="plan")
        monkeypatch.chdir(project)

        root = resolve_root(None)
        buf = io.StringIO()
        rc = run_show(root=root, stream=buf)
        assert rc == 0
        assert "plan" in buf.getvalue()

    def test_show_different_phase_values(self, tmp_path, monkeypatch):
        """run_show reports the exact phase written into phase-state.json."""
        import io
        from lib.state_cli import run_show, resolve_root

        monkeypatch.delenv("HARNESS_STATE_ROOT", raising=False)
        for phase in ("discuss", "plan", "execute", "done"):
            project = _make_project(tmp_path / f"proj_{phase}", phase=phase)
            monkeypatch.chdir(project)
            root = resolve_root(None)
            buf = io.StringIO()
            rc = run_show(root=root, stream=buf)
            assert rc == 0, f"rc should be 0 for phase={phase}"
            assert phase in buf.getvalue(), (
                f"Expected phase={phase!r} in output, got: {buf.getvalue()!r}"
            )

    def test_show_from_subdirectory_walks_up(self, tmp_path, monkeypatch):
        """run_show from a subdir inside the project still finds the project root."""
        import io
        from lib.state_cli import run_show, resolve_root

        monkeypatch.delenv("HARNESS_STATE_ROOT", raising=False)
        project = _make_project(tmp_path / "proj", phase="execute")
        nested = project / "a" / "b" / "c"
        nested.mkdir(parents=True)
        monkeypatch.chdir(nested)

        root = resolve_root(None)
        assert root == project.resolve()

        buf = io.StringIO()
        rc = run_show(root=root, stream=buf)
        assert rc == 0
        assert "execute" in buf.getvalue()

    def test_root_override_ignores_cwd(self, tmp_path, monkeypatch):
        """--root <path> makes run_show use that project, not cwd's project."""
        import io
        from lib.state_cli import run_show, resolve_root

        monkeypatch.delenv("HARNESS_STATE_ROOT", raising=False)
        project_a = _make_project(tmp_path / "proj_a", phase="plan")
        project_b = _make_project(tmp_path / "proj_b", phase="execute")

        # cd into project_a but point --root at project_b
        monkeypatch.chdir(project_a)

        root = resolve_root(project_b)
        buf = io.StringIO()
        rc = run_show(root=root, stream=buf)
        assert rc == 0
        assert "execute" in buf.getvalue()
        assert "plan" not in buf.getvalue().split("\n")[0]  # first line has phase

    def test_env_override_ignores_cwd(self, tmp_path, monkeypatch):
        """HARNESS_STATE_ROOT makes run_show use that project, not cwd's project."""
        import io
        from lib.state_cli import run_show, resolve_root

        project_a = _make_project(tmp_path / "proj_a", phase="plan")
        project_b = _make_project(tmp_path / "proj_b", phase="done")

        monkeypatch.chdir(project_a)
        monkeypatch.setenv("HARNESS_STATE_ROOT", str(project_b))

        root = resolve_root(None)
        assert root == project_b.resolve()

        buf = io.StringIO()
        rc = run_show(root=root, stream=buf)
        assert rc == 0
        assert "done" in buf.getvalue()


# ---------------------------------------------------------------------------
# Integration: state show does NOT use source-tree root when cwd is a project
# ---------------------------------------------------------------------------

class TestNotSourceTree:
    """Ensure state show uses cwd project, not the harness source tree."""

    def test_source_tree_not_used_when_cwd_is_project(self, tmp_path, monkeypatch):
        """The phase returned reflects the target project, not source repo state."""
        import io
        from lib.state_cli import run_show, resolve_root
        from lib import version as _version

        monkeypatch.delenv("HARNESS_STATE_ROOT", raising=False)

        # Build a target project with phase=done
        project = _make_project(tmp_path / "target", phase="done")
        monkeypatch.chdir(project)

        root = resolve_root(None)
        # Confirm we are NOT pointing at the harness source repo
        source_root = _version.repo_root()
        assert root != source_root, (
            "resolve_root() returned the harness source tree instead of the target project"
        )

        buf = io.StringIO()
        rc = run_show(root=root, stream=buf)
        assert rc == 0
        assert "done" in buf.getvalue()
