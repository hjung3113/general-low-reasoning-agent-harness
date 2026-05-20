"""T5: init → upgrade --dry-run planned_writes desync (STALE-1).

After a fresh `init`, `upgrade --dry-run` must report `planned_writes=0`
for the same --adapters/--profiles flags.  Before the fix, upgrade reported
102 because it unconditionally counted all harness-owned entries as planned
writes even when the source sha256 was unchanged since install.

Fix A (install.py): align counter — skip project-owned and managed-append
  with no content change (STALE-1 sync comment).
Fix B (upgrade.py): sha256 short-circuit — if installed source_sha256 ==
  current source file_hash, skip write and counter increment.

Plan ref: /tmp/v095-PLAN.md REV-2 §3.1 STALE-1
Impl ref: /tmp/v095-IMPL.md REV-4 T5
Trace:    .planning/phases/02e-v0.9.5-hotfix/evidence/stale1-trace.md
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Repo-root / scripts path
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

HARNESS_PY = str(SCRIPTS_DIR / "harness.py")
_PYTHON = sys.executable

_DEV_ENV = {
    **os.environ,
    "HARNESS_ALLOW_UNSIGNED_DEV": "1",
    "HARNESS_BYPASS_TTY_CONFIRM": "1",
}


def _run(*args: str, cwd: str | None = None, env: dict | None = None):
    """Run harness.py with given args; return (rc, stdout, stderr)."""
    cmd = [_PYTHON, HARNESS_PY, *args]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd or str(REPO_ROOT),
        env=env or _DEV_ENV,
    )
    return result.returncode, result.stdout, result.stderr


def _parse_planned_writes(stdout: str) -> int:
    """Extract planned_writes=N from upgrade --dry-run stdout."""
    for line in stdout.splitlines():
        if line.startswith("planned_writes="):
            return int(line.split("=", 1)[1].strip())
    raise ValueError(f"planned_writes not found in output:\n{stdout}")


# ===========================================================================
# T5-1: Fresh init → upgrade --dry-run must report planned_writes=0
# ===========================================================================

class TestInstallUpgradeSync:
    """STALE-1: upgrade --dry-run immediately after init must report planned_writes=0."""

    def test_upgrade_dry_run_after_fresh_init_is_zero(self, tmp_path: Path) -> None:
        """Core T5 done-criterion: init + upgrade --dry-run → planned_writes=0."""
        # Step 1: initialise a fresh git repo in tmp_path so init accepts it
        subprocess.run(
            ["git", "init", "-q"],
            cwd=str(tmp_path),
            check=True,
        )
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init-for-test", "-q"],
            cwd=str(tmp_path),
            check=True,
            env={**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t",
                 "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t"},
        )

        # Step 2: fresh init
        rc_init, stdout_init, stderr_init = _run(
            "init",
            "--target", str(tmp_path),
            "--adapters", "none",
        )
        assert rc_init == 0, (
            f"init must exit 0.\nstdout={stdout_init}\nstderr={stderr_init}"
        )

        # Step 3: upgrade --dry-run with same scope (no --adapters flag = default)
        rc, stdout, stderr = _run(
            "upgrade",
            "--target", str(tmp_path),
            "--dry-run",
        )

        assert rc == 0, (
            f"upgrade --dry-run after fresh init must exit 0.\n"
            f"stdout={stdout}\nstderr={stderr}"
        )

        planned_writes = _parse_planned_writes(stdout)
        assert planned_writes == 0, (
            f"STALE-1: upgrade --dry-run immediately after init must report "
            f"planned_writes=0, got {planned_writes}.\n"
            f"stdout=\n{stdout}\nstderr=\n{stderr}"
        )


# ===========================================================================
# T5-2: Changed harness-owned file still counts as planned write
# ===========================================================================

class TestInstallUpgradeSyncChangedFile:
    """Regression guard: when a harness-owned file is modified in the target,
    upgrade --dry-run must still report planned_writes >= 1."""

    def test_modified_harness_file_is_counted(self, tmp_path: Path) -> None:
        # Step 1: fresh git repo + init
        subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "i", "-q"],
            cwd=str(tmp_path),
            check=True,
            env={**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t",
                 "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t"},
        )
        rc_init, stdout_init, stderr_init = _run(
            "init",
            "--target", str(tmp_path),
            "--adapters", "none",
        )
        assert rc_init == 0, (
            f"init must exit 0.\nstdout={stdout_init}\nstderr={stderr_init}"
        )

        # Step 2: modify a harness-owned file in the target to make it differ
        # from the source.  We pick the installed-manifest itself to avoid
        # dealing with the conflict-detection path — instead we overwrite a
        # scripts/ file that is harness-owned and unlikely to conflict-protect.
        # Find any harness-owned file in the target's scripts/ tree.
        scripts_dir = tmp_path / "scripts" / "lib"
        harness_owned = next(scripts_dir.rglob("*.py"), None)
        assert harness_owned is not None, (
            f"Expected at least one *.py under {scripts_dir}"
        )
        original = harness_owned.read_bytes()
        harness_owned.write_bytes(original + b"\n# T5-test-marker\n")

        # Step 3: upgrade --dry-run — the modified file must appear as conflict
        rc, stdout, stderr = _run(
            "upgrade",
            "--target", str(tmp_path),
            "--dry-run",
        )

        # rc may be 0 or 1 depending on whether conflicts are fatal in dry-run;
        # either way, the file must NOT be silently skipped.
        # The key property: the sha256 short-circuit ONLY fires when
        # installed source_sha256 == current source hash AND on-disk == old_hash.
        # A user-modified file has current_hash != old_hash → conflict path.
        conflicts_val = 0
        pw_val = 0
        for line in stdout.splitlines():
            if line.startswith("conflicts="):
                conflicts_val = int(line.split("=", 1)[1].strip())
            if line.startswith("planned_writes="):
                pw_val = int(line.split("=", 1)[1].strip())

        assert conflicts_val >= 1 or pw_val >= 1, (
            f"A modified harness-owned file must appear as a conflict or "
            f"planned write, not silently skipped.\n"
            f"stdout=\n{stdout}\nstderr=\n{stderr}"
        )
