"""Progress UX (v0.9.7): init/upgrade emit phase-by-phase lines on stderr.

Contract:
  - stdout summary line ("installed harness v… → …") is unchanged.
  - stderr carries "staging files... [N/M]", "writing pending sidecar...",
    "applying atomic batch... [N/M]", "syncing roomodes...", "finalizing..."
    when running without --quiet.
  - With --quiet, stderr is empty (no progress lines).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_PY = REPO_ROOT / "scripts" / "harness.py"


def _run_init(target: Path, *, quiet: bool) -> tuple[str, str, int]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "scripts")
    # Bootstrap-approver fallback path.
    env.setdefault("HARNESS_INSTALL_APPROVER", "test@example.com")
    cmd = [
        sys.executable,
        str(HARNESS_PY),
        "init",
        "--target", str(target),
        "--profile", "generic",
        "--adapter", "roo",
    ]
    if quiet:
        cmd.append("--quiet")
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, capture_output=True, text=True)
    return proc.stdout, proc.stderr, proc.returncode


def test_init_emits_progress_lines_on_stderr():
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "tgt"
        target.mkdir()
        stdout, stderr, rc = _run_init(target, quiet=False)
        assert rc == 0, f"init failed: rc={rc}\nstdout={stdout}\nstderr={stderr}"
        # stdout summary unchanged.
        assert "installed harness" in stdout
        # stderr carries phase markers.
        assert "staging files..." in stderr, stderr
        assert "applying atomic batch..." in stderr, stderr
        assert "writing pending sidecar..." in stderr, stderr
        assert "syncing roomodes..." in stderr, stderr
        assert "finalizing..." in stderr, stderr
        # At least 3 tick lines total (quartile throttling).
        tick_lines = [ln for ln in stderr.splitlines() if "[" in ln and "/" in ln]
        assert len(tick_lines) >= 3, f"expected >=3 tick lines, got {tick_lines!r}"


def test_init_quiet_suppresses_stderr_progress():
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "tgt"
        target.mkdir()
        stdout, stderr, rc = _run_init(target, quiet=True)
        assert rc == 0, f"init failed: rc={rc}\nstdout={stdout}\nstderr={stderr}"
        assert "installed harness" in stdout
        # Allow stderr only if it has no progress markers.
        assert "staging files..." not in stderr
        assert "applying atomic batch..." not in stderr
        assert "syncing roomodes..." not in stderr
        assert "finalizing..." not in stderr
