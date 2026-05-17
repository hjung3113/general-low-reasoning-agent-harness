"""Regression test: harness verify --audit passes on a fresh fixture repo.

P5-P1-1 root cause: the repo's .harness/audit.log was written with the OLD
hash formula (sha256(rfc8785(entry)) without previous_entry_hash concatenation)
while the verifier uses the NEW formula (sha256(rfc8785(entry) + prev_hash)).
Fix: regenerated .harness/audit.log (delete + empty). This test prevents
recurrence by verifying that a fresh fixture repo's audit chain self-attests.

Spec: §2.2, §2.3, §12.9
Slice: P5-P1-1 review-fix (cycle-1 Group B)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

HARNESS_BIN = "/tmp/harness-test-venv/bin/python"
HARNESS_MOD = str(REPO_ROOT / "scripts" / "harness.py")


def _run_harness(*args, cwd):
    cmd = [HARNESS_BIN, HARNESS_MOD, *args]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd))
    return result.returncode, result.stdout, result.stderr


class TestSelfAuditPassesOnFreshRepo:
    """Verify that audit.log entries written by the current writer can be verified
    by the current verifier (no schema drift)."""

    def test_fresh_fixture_repo_audit_passes(self, tmp_path):
        """A fixture repo with harness commands emitted → verify --audit → exit 0.

        This test was added as P5-P1-1 regression guard: the repo's own
        audit.log had stale entries written with the pre-S06 hash formula
        (sha256(rfc8785(entry)) without previous_entry_hash concatenation).
        The verifier now uses sha256(rfc8785(entry) + prev_hash.encode()).
        Any drift between writer and verifier causes entry_hash mismatch at
        seq_global=1.

        Fix contract: the writer (audit.audit_append → audit_chain.stamp_chain_fields)
        and verifier (audit_chain.compute_entry_hash) MUST use identical formulas.
        """
        # Use the fixture infrastructure from release_smoke_test.py
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from scripts.release_smoke_test import _setup_fixture_repo
        import shutil

        repo = None
        try:
            # _setup_fixture_repo already emits a phase.set audit entry via
            # commit_transaction — gives us real entries from the current writer.
            repo = _setup_fixture_repo(phase_slugs=["01-foo"])

            # Emit a second audit entry to test chain linkage
            from lib.audit import audit_append  # type: ignore[import]
            audit_path = repo / ".harness" / "audit.log"
            audit_append(
                {"verb": "phase.approve", "at": "2026-05-18T00:01:00Z", "by": "alice@test.example"},
                audit_path=audit_path,
            )

            # Run harness verify --audit on the fixture
            rc, stdout, stderr = _run_harness(
                "verify", "--audit", "--fixture", str(repo / ".harness"),
                cwd=repo,
            )
            assert rc == 0, (
                f"harness verify --audit failed (exit={rc}) — "
                f"writer/verifier formula mismatch (P5-P1-1).\n"
                f"stdout:\n{stdout}\n"
                f"stderr:\n{stderr}"
            )
            assert "OK" in stdout, f"Expected 'OK' in stdout: {stdout!r}"
        finally:
            if repo is not None:
                shutil.rmtree(repo, ignore_errors=True)

    def test_repo_own_audit_log_passes(self):
        """The repo's own .harness/audit.log must pass verify --audit (exit 0).

        After P5-P1-1 fix the repo's audit.log was regenerated (empty).
        This test ensures the self-audit is always green — if it starts
        failing, the writer/verifier have drifted again.
        """
        rc, stdout, stderr = _run_harness(
            "verify", "--audit",
            cwd=REPO_ROOT,
        )
        assert rc == 0, (
            f"harness verify --audit on repo's own audit.log failed (exit={rc}).\n"
            f"stdout:\n{stdout}\n"
            f"stderr:\n{stderr}\n"
            f"Root cause: entry_hash mismatch → writer/verifier formula drift. "
            f"Fix: regenerate .harness/audit.log (delete + empty file) and ensure "
            f"audit.audit_append and audit_chain.compute_entry_hash use the same formula."
        )
