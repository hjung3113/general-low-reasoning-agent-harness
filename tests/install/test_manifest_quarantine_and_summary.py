"""P2-1 + P2-3 tests: quarantine path uuid4 suffix + loud upgrade quarantine summary.

P2-1: Two reconcile_file calls in the same UTC second must produce different
quarantine filenames (uuid4 suffix prevents collision).

P2-3: _stamp_installed_manifest_v2 must print a loud summary block to stderr
when any files were quarantined during upgrade.

Spec: §6 (quarantine paths, upgrade warnings).
Slice: S14 review-fix.
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from lib.manifest_reconciler import (  # type: ignore[import]
    ReconcileDecision,
    reconcile_file,
)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ===========================================================================
# P2-1: quarantine uuid4 suffix prevents collision
# ===========================================================================

class TestQuarantineCollisionAvoided:
    def _make_diverged_file(self, path: Path, content: str) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))
        return sha256_text(content)

    def test_quarantine_collision_avoided_same_second(self, tmp_path: Path) -> None:
        """Two reconcile_file calls with same timestamp → different quarantine paths.

        Previously the quarantine filename was <rel>.<ts> only, so two diverged
        files in the same UTC second could collide.  The uuid4 suffix fix ensures
        uniqueness.
        """
        q_dir = tmp_path / ".harness" / "conflicts"
        file_a = tmp_path / "project" / "a.txt"
        file_b = tmp_path / "project" / "b.txt"

        self._make_diverged_file(file_a, "user-modified content A\n")
        self._make_diverged_file(file_b, "user-modified content B\n")

        release_sha_a = sha256_text("original release A\n")
        release_sha_b = sha256_text("original release B\n")
        # Same timestamp for both calls (simulating same-second collision scenario)
        same_ts = "2026-01-01T00:00:00Z"

        result_a = reconcile_file(
            file_a,
            release_installed_sha256=release_sha_a,
            prior_current_sha256=None,
            repo_root=tmp_path,
            quarantine_dir=q_dir,
            now_iso=same_ts,
        )
        result_b = reconcile_file(
            file_b,
            release_installed_sha256=release_sha_b,
            prior_current_sha256=None,
            repo_root=tmp_path,
            quarantine_dir=q_dir,
            now_iso=same_ts,
        )

        assert result_a.decision == ReconcileDecision.USER_MODIFIED_QUARANTINE
        assert result_b.decision == ReconcileDecision.USER_MODIFIED_QUARANTINE

        # Both quarantine paths must exist and be DIFFERENT
        q_path_a = Path(result_a.quarantine_path)
        q_path_b = Path(result_b.quarantine_path)
        assert q_path_a.exists(), f"Quarantine file A must exist: {q_path_a}"
        assert q_path_b.exists(), f"Quarantine file B must exist: {q_path_b}"
        assert q_path_a != q_path_b, (
            f"Quarantine paths must be unique even within the same second.\n"
            f"  A: {q_path_a}\n"
            f"  B: {q_path_b}"
        )

    def test_quarantine_filename_contains_uuid_suffix(self, tmp_path: Path) -> None:
        """Quarantine filename must end with a hex suffix (uuid4[:8])."""
        q_dir = tmp_path / ".harness" / "conflicts"
        file_c = tmp_path / "c.txt"
        file_c.write_bytes(b"diverged\n")

        result = reconcile_file(
            file_c,
            release_installed_sha256=sha256_text("original\n"),
            prior_current_sha256=None,
            repo_root=tmp_path,
            quarantine_dir=q_dir,
            now_iso="2026-01-01T12:00:00Z",
        )
        q_path = Path(result.quarantine_path)
        # The last segment should end with .<8 hex chars>
        name = q_path.name
        parts = name.split(".")
        last = parts[-1]
        assert len(last) == 8 and all(c in "0123456789abcdef" for c in last), (
            f"Quarantine filename {name!r} must end with an 8-char hex uuid4 suffix. "
            f"Last part was: {last!r}"
        )


# ===========================================================================
# P2-3: Loud quarantine summary to stderr
# ===========================================================================

class TestUpgradeLoudQuarantineSummary:
    def _make_release_and_prior(
        self,
        path_str: str,
        release_sha: str,
        installed_sha: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        release = {
            "schema_version": 2,
            "harness_version": "v0.7.0",
            "files": {
                path_str: {"installed_sha256": release_sha, "current_sha256": release_sha},
            },
        }
        installed = {
            "schema_version": 2,
            "harness_version": "v0.6.0",
            "files": {
                path_str: {"installed_sha256": installed_sha, "current_sha256": installed_sha},
            },
        }
        return release, installed

    def test_loud_summary_printed_to_stderr_when_quarantined(
        self, tmp_path: Path, capsys
    ) -> None:
        """_stamp_installed_manifest_v2 prints a ==== WARNING block when files quarantined."""
        from lib.manifest_reconciler import ReconcileResult, ReconcileDecision  # type: ignore[import]
        from lib.upgrade import _stamp_installed_manifest_v2  # type: ignore[import]

        release, installed = self._make_release_and_prior(
            "some/file.txt",
            sha256_text("release content\n"),
            sha256_text("user content\n"),
        )

        # Simulate a reconcile result for a quarantined file
        quarantine_path = str(tmp_path / ".harness" / "conflicts" / "some_file.txt.2026-01-01T00-00-00Z.abcd1234")
        reconcile_results = [
            ReconcileResult(
                path="some/file.txt",
                decision=ReconcileDecision.USER_MODIFIED_QUARANTINE,
                quarantine_path=quarantine_path,
            )
        ]

        _stamp_installed_manifest_v2(
            installed,
            release_manifest=release,
            harness_version="v0.7.0",
            reconcile_results=reconcile_results,
        )

        captured = capsys.readouterr()
        assert "WARNING" in captured.err and "quarantined" in captured.err.lower(), (
            "Expected a loud WARNING block in stderr when files are quarantined. "
            f"Actual stderr:\n{captured.err}"
        )
        assert "====" in captured.err, "Expected === border markers in quarantine summary block."

    def test_no_summary_when_nothing_quarantined(self, tmp_path: Path, capsys) -> None:
        """No quarantine summary printed when no files were quarantined."""
        from lib.manifest_reconciler import ReconcileResult, ReconcileDecision  # type: ignore[import]
        from lib.upgrade import _stamp_installed_manifest_v2  # type: ignore[import]

        sha = sha256_text("content\n")
        release = {
            "schema_version": 2,
            "harness_version": "v0.7.0",
            "files": {
                "ok.txt": {"installed_sha256": sha, "current_sha256": sha},
            },
        }
        installed = {
            "schema_version": 2,
            "harness_version": "v0.6.0",
            "files": {
                "ok.txt": {"installed_sha256": sha, "current_sha256": sha},
            },
        }
        reconcile_results = [
            ReconcileResult(
                path="ok.txt",
                decision=ReconcileDecision.UNCHANGED_SAFE_REPLACE,
                quarantine_path=None,
            )
        ]

        _stamp_installed_manifest_v2(
            installed,
            release_manifest=release,
            harness_version="v0.7.0",
            reconcile_results=reconcile_results,
        )

        captured = capsys.readouterr()
        assert "quarantined" not in captured.err.lower(), (
            f"Should not print quarantine summary when nothing was quarantined. "
            f"Actual stderr:\n{captured.err}"
        )
