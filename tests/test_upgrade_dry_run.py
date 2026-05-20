"""T6: upgrade --dry-run must not emit a false quarantine warning on a fresh install.

STALE-2 regression: immediately after `init`, `upgrade --dry-run` used to emit
"WARNING: harness upgrade quarantined N user-modified file(s)" because
_stamp_installed_manifest_v2 appended (path, "") entries for files classified
as USER_MODIFIED_QUARANTINE with classify_only=True — even though no files were
actually moved.  The warning should only fire when a real quarantine move occurs
(non-dry-run with actual conflicts).

Plan: /tmp/v095-PLAN.md REV-2 §3.1 STALE-2
Impl: /tmp/v095-IMPL.md REV-4 T6
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
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

# Env to bypass SSH tag verification and TTY confirm in subprocess calls
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


# ===========================================================================
# T6-1: Fresh init → upgrade --dry-run must not emit a quarantine warning
# ===========================================================================

class TestUpgradeDryRunNoFalseQuarantine:
    """STALE-2: after a fresh init, upgrade --dry-run must report conflicts=0
    and must NOT print any 'quarantined' text to stdout or stderr."""

    def test_no_quarantine_warning_on_fresh_install(self, tmp_path: Path) -> None:
        # Step 1: fresh init
        rc_init, stdout_init, stderr_init = _run(
            "init",
            "--target", str(tmp_path),
            "--profile", "generic",
            "--adapter", "roo",
        )
        assert rc_init == 0, (
            f"init must exit 0.\nstdout={stdout_init}\nstderr={stderr_init}"
        )

        # Step 2: upgrade --dry-run
        rc, stdout, stderr = _run(
            "upgrade",
            "--target", str(tmp_path),
            "--dry-run",
        )

        # rc must be 0 (no real conflicts)
        assert rc == 0, (
            f"upgrade --dry-run on a fresh install must exit 0 (no conflicts).\n"
            f"stdout={stdout}\nstderr={stderr}"
        )

        # stdout must contain conflicts=0
        assert "conflicts=0" in stdout, (
            f"upgrade --dry-run must report conflicts=0.\nstdout={stdout}"
        )

        # Neither stdout nor stderr may contain "quarantined"
        combined = stdout + stderr
        assert "quarantined" not in combined.lower(), (
            "upgrade --dry-run on a fresh install must NOT print any quarantine "
            "warning.  STALE-2: _stamp_installed_manifest_v2 was appending "
            "(path, '') entries for classify_only=True reconcile results.\n"
            f"stdout=\n{stdout}\nstderr=\n{stderr}"
        )


# ===========================================================================
# T6-2: Real conflict (user-modified harness-owned file) must still warn
# ===========================================================================

class TestUpgradeRealConflictStillWarns:
    """Regression guard: when a user actually modifies a harness-owned file and
    then a non-dry-run upgrade runs, the quarantine warning must still appear."""

    def _sha256(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def test_real_quarantine_warning_on_user_modified_file(
        self, tmp_path: Path, capsys
    ) -> None:
        """_stamp_installed_manifest_v2 prints WARNING when quarantine_path is set."""
        from lib.manifest_reconciler import ReconcileDecision, ReconcileResult  # type: ignore[import]
        from lib.upgrade import _stamp_installed_manifest_v2  # type: ignore[import]

        release_sha = self._sha256("release content\n")
        installed_sha = self._sha256("user-modified content\n")

        release: dict = {
            "schema_version": 2,
            "harness_version": "v0.9.5",
            "files": {
                "some/tool.md": {
                    "installed_sha256": release_sha,
                    "current_sha256": release_sha,
                },
            },
        }
        installed: dict = {
            "schema_version": 2,
            "harness_version": "v0.9.4",
            "files": {
                "some/tool.md": {
                    "installed_sha256": installed_sha,
                    "current_sha256": installed_sha,
                },
            },
        }

        # A real quarantine result has a non-None quarantine_path (not classify_only)
        q_path = str(
            tmp_path / ".harness" / "conflicts"
            / "some_tool.md.2026-01-01T00-00-00Z.abcd1234"
        )
        reconcile_results = [
            ReconcileResult(
                path="some/tool.md",
                decision=ReconcileDecision.USER_MODIFIED_QUARANTINE,
                quarantine_path=q_path,
            )
        ]

        _stamp_installed_manifest_v2(
            installed,
            release_manifest=release,
            harness_version="v0.9.5",
            reconcile_results=reconcile_results,
        )

        captured = capsys.readouterr()
        assert "quarantined" in captured.err.lower(), (
            "Expected quarantine WARNING in stderr for a real user-modified file.\n"
            f"stderr=\n{captured.err}"
        )
        assert "WARNING" in captured.err, (
            "Expected 'WARNING' in quarantine summary block.\n"
            f"stderr=\n{captured.err}"
        )
        assert "====" in captured.err, (
            "Expected ==== border markers in quarantine summary block.\n"
            f"stderr=\n{captured.err}"
        )

    def test_classify_only_quarantine_does_not_warn(
        self, tmp_path: Path, capsys
    ) -> None:
        """_stamp_installed_manifest_v2 must NOT warn when quarantine_path is None
        (classify_only=True path — used by dry-run and upgrade's own conflict logic)."""
        from lib.manifest_reconciler import ReconcileDecision, ReconcileResult  # type: ignore[import]
        from lib.upgrade import _stamp_installed_manifest_v2  # type: ignore[import]

        release_sha = self._sha256("release content\n")
        installed_sha = self._sha256("user-modified content\n")

        release: dict = {
            "schema_version": 2,
            "harness_version": "v0.9.5",
            "files": {
                "some/tool.md": {
                    "installed_sha256": release_sha,
                    "current_sha256": release_sha,
                },
            },
        }
        installed: dict = {
            "schema_version": 2,
            "harness_version": "v0.9.4",
            "files": {
                "some/tool.md": {
                    "installed_sha256": installed_sha,
                    "current_sha256": installed_sha,
                },
            },
        }

        # classify_only=True path → quarantine_path is None (no file move)
        reconcile_results = [
            ReconcileResult(
                path="some/tool.md",
                decision=ReconcileDecision.USER_MODIFIED_QUARANTINE,
                quarantine_path=None,  # <-- classify_only=True: no actual move
            )
        ]

        _stamp_installed_manifest_v2(
            installed,
            release_manifest=release,
            harness_version="v0.9.5",
            reconcile_results=reconcile_results,
        )

        captured = capsys.readouterr()
        assert "quarantined" not in captured.err.lower(), (
            "Must NOT emit quarantine WARNING when quarantine_path is None "
            "(classify_only mode — no files were actually moved).\n"
            f"stderr=\n{captured.err}"
        )
