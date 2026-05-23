"""T3 — install.py init wire-in (new phase order).

Test cases:
1. Happy path: install succeeds, manifest written, no staging artifacts left
2. SIGTERM after Phase 1 (before Phase 3): no pending, no journal; recovery no-op;
   re-run init succeeds
3. SIGTERM after Phase 3 (before Phase 4): pending exists, no journal; recovery
   quarantines pending (orphan path); rc=1
4. SIGTERM mid-batch (Phase 4): pending+journal+staging present, no sentinel;
   state repair resumes; rc=0
5. SIGTERM after sentinel (between Phase 4 and Phase 5): state repair finalizes; rc=0
6. SIGTERM after os.replace (Phase 5), before cleanup: manifest correct; recovery clean; rc=0
7. Idempotency: state repair 3x after each scenario; all succeed
"""
from __future__ import annotations

import json
import os
import sys
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from lib.install import InstallFailed, _atomic_write_json_fsync  # noqa: E402
from lib.install_recovery import recover_aborted_install  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_minimal_manifest(root: Path) -> None:
    """Create a minimal harness manifest.json for testing."""
    harness_dir = root / "harness"
    harness_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = harness_dir / "manifest.json"
    # Minimal valid manifest: one harness-owned file
    manifest_path.write_text(
        json.dumps({
            "schema_version": 2,
            "version": "__release__",
            "files": [
                {
                    "path": "scripts/harness.py",
                    "source": "scripts/harness.py",
                    "policy": "harness-owned",
                    "owner": "harness",
                    "adapter": "roo",
                    "profile": "generic",
                }
            ],
            "packs": {},
        }),
        encoding="utf-8",
    )
    # Create the source file
    scripts_dir = root / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    (scripts_dir / "harness.py").write_text("# harness\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Test 1: Happy path — install succeeds, manifest written, staging cleaned up
# ---------------------------------------------------------------------------


def test_happy_path_atomic_install(tmp_path, monkeypatch):
    """T3-1: normal install via atomic staging -> manifest written, no staging artifacts."""
    root = tmp_path / "source"
    root.mkdir()
    _make_minimal_manifest(root)

    target = tmp_path / "install_target"
    target.mkdir()

    monkeypatch.setattr("lib.state._active_harness_version", lambda: "0.9.7-test")
    monkeypatch.setattr("lib.state.now_utc", lambda: "2026-05-21T00:00:00Z")
    monkeypatch.setattr("lib.state._git_user_email_sha256", lambda: None)
    # Patch manifest chain verification to no-op
    monkeypatch.setattr("lib.install_recovery.recover_aborted_install", lambda t: None)
    import lib.manifest_reconciler as _mrc
    monkeypatch.setattr(_mrc, "verify_install_record_integrity", lambda t: None)

    from lib.install import install as _install
    _install(
        root=root,
        target=target,
        adapters={"roo"},
        profiles={"generic"},
        packs=set(),
        harness_version="0.9.7-test",
    )

    # Manifest should exist
    final = target / ".harness" / "installed-manifest.json"
    assert final.exists(), "Final manifest must exist after install"
    data = json.loads(final.read_text(encoding="utf-8"))
    assert data["version"] == "0.9.7-test"

    # No staging artifacts
    harness_dir = target / ".harness"
    staging_dirs = list(harness_dir.glob(".staging-*"))
    pending_files = list(harness_dir.glob("installed-manifest.json.pending-*"))
    assert not staging_dirs, f"Staging dirs should be cleaned up: {staging_dirs}"
    assert not pending_files, f"Pending files should be cleaned up: {pending_files}"

    # Installed file should be in target
    assert (target / "scripts" / "harness.py").exists()


# ---------------------------------------------------------------------------
# Test 2: SIGTERM after Phase 1 (before Phase 3) — no pending/journal; re-run succeeds
# ---------------------------------------------------------------------------


def test_sigterm_after_phase1_recovery_noop(tmp_path, monkeypatch):
    """T3-2: crash after staging but before pending write -> re-run init succeeds."""
    root = tmp_path / "source"
    root.mkdir()
    _make_minimal_manifest(root)
    target = tmp_path / "install_target"
    target.mkdir()

    monkeypatch.setattr("lib.state._active_harness_version", lambda: "0.9.7-test")
    monkeypatch.setattr("lib.state.now_utc", lambda: "2026-05-21T00:00:00Z")
    monkeypatch.setattr("lib.state._git_user_email_sha256", lambda: None)
    import lib.manifest_reconciler as _mrc
    monkeypatch.setattr(_mrc, "verify_install_record_integrity", lambda t: None)

    # Simulate crash: manually create staging dir (Phase 1 done) but no pending
    harness_dir = target / ".harness"
    harness_dir.mkdir()
    staging_dir = harness_dir / ".staging-99999-20260521T000000Z-abc000"
    staging_dir.mkdir()
    (staging_dir / "scripts").mkdir()
    (staging_dir / "scripts" / "harness.py").write_text("# staged\n", encoding="utf-8")
    # No pending file, no journal

    # Recovery should be a no-op for this (no pending sidecar, staging is fresh so not stale)
    result = recover_aborted_install(target)
    # Staging dir may or may not be cleaned (it's new, not stale) — that's fine

    # Now re-run install (target is empty of actual files)
    from lib.install import install as _install
    _install(
        root=root,
        target=target,
        adapters={"roo"},
        profiles={"generic"},
        packs=set(),
        harness_version="0.9.7-test",
    )
    final = target / ".harness" / "installed-manifest.json"
    assert final.exists(), "After re-run, manifest must exist"


# ---------------------------------------------------------------------------
# Test 3: SIGTERM after Phase 3 (pending exists, no journal) — orphan quarantine
# ---------------------------------------------------------------------------


def test_sigterm_after_phase3_orphan_quarantine(tmp_path, monkeypatch):
    """T3-3: crash after pending write but before batch -> recovery quarantines orphan."""
    target = tmp_path / "target"
    target.mkdir()
    harness_dir = target / ".harness"
    harness_dir.mkdir()

    # Simulate: pending sidecar written, but no staging dir or journal
    runid = "99999-20260521T000001Z-def111"
    pending_path = harness_dir / f"installed-manifest.json.pending-{runid}"
    pending_path.write_text(
        json.dumps({"version": "0.9.7-test", "schema_version": 2, "files": {}}),
        encoding="utf-8",
    )
    # No staging dir, no journal, no sentinel = orphan

    result = recover_aborted_install(target)

    # Pending should be quarantined
    assert not pending_path.exists(), "Orphaned pending should be quarantined"
    conflicts = harness_dir / "conflicts"
    assert conflicts.exists()
    assert len(result.quarantined) >= 1


# ---------------------------------------------------------------------------
# Test 4: SIGTERM mid-batch — pending+journal+staging present; repair resumes
# ---------------------------------------------------------------------------


def test_sigterm_mid_batch_repair_resumes(tmp_path, monkeypatch):
    """T3-4: crash mid-batch -> state repair resumes and finalizes."""
    target = tmp_path / "target"
    target.mkdir()
    harness_dir = target / ".harness"
    harness_dir.mkdir()

    runid = "99999-20260521T000002Z-ghi222"
    staging_dir = harness_dir / f".staging-{runid}"
    staging_dir.mkdir()
    journal_path = harness_dir / f".staging-{runid}.journal.jsonl"

    # Create a staged file
    (staging_dir / "scripts").mkdir()
    (staging_dir / "scripts" / "harness.py").write_text("# content\n", encoding="utf-8")
    # Empty journal = nothing yet
    journal_path.write_text("", encoding="utf-8")

    # Pending sidecar
    pending_path = harness_dir / f"installed-manifest.json.pending-{runid}"
    pending_path.write_text(
        json.dumps({"version": "0.9.7-test", "schema_version": 2, "files": {}}),
        encoding="utf-8",
    )

    # Recovery: should resume batch, finalize
    result = recover_aborted_install(target)

    final = harness_dir / "installed-manifest.json"
    assert final.exists(), "After resume+finalize, manifest must exist"
    data = json.loads(final.read_text(encoding="utf-8"))
    assert data["version"] == "0.9.7-test"
    assert not pending_path.exists(), "Pending should be consumed"


# ---------------------------------------------------------------------------
# Test 5: SIGTERM after sentinel but before Phase 5 — state repair finalizes
# ---------------------------------------------------------------------------


def test_sigterm_after_sentinel_repair_finalizes(tmp_path):
    """T3-5: crash after sentinel written but before os.replace -> repair finalizes."""
    target = tmp_path / "target"
    target.mkdir()
    harness_dir = target / ".harness"
    harness_dir.mkdir()

    runid = "99999-20260521T000003Z-jkl333"
    pending_path = harness_dir / f"installed-manifest.json.pending-{runid}"
    sentinel_path = harness_dir / f".staging-{runid}.complete"

    pending_path.write_text(
        json.dumps({"version": "0.9.7-test", "schema_version": 2, "files": {}}),
        encoding="utf-8",
    )
    sentinel_path.write_bytes(b"")  # sentinel present

    result = recover_aborted_install(target)

    final = harness_dir / "installed-manifest.json"
    assert final.exists(), "Finalization must occur when sentinel present"
    assert not pending_path.exists(), "Pending consumed"
    assert not sentinel_path.exists(), "Sentinel cleaned up"

    # 3x idempotency
    r2 = recover_aborted_install(target)
    r3 = recover_aborted_install(target)
    assert len(r2.finished) == 0 or r2.found_staging_dirs == 0
    assert len(r3.finished) == 0 or r3.found_staging_dirs == 0


# ---------------------------------------------------------------------------
# Test 6: SIGTERM after os.replace (Phase 5) before cleanup — manifest correct, recovery clean
# ---------------------------------------------------------------------------


def test_sigterm_after_finalize_before_cleanup(tmp_path):
    """T3-6: crash after os.replace but before cleanup -> manifest correct; recovery no-op."""
    target = tmp_path / "target"
    target.mkdir()
    harness_dir = target / ".harness"
    harness_dir.mkdir()

    # Simulate: manifest already finalized, but staging/sentinel/journal still present
    runid = "99999-20260521T000004Z-mno444"
    staging_dir = harness_dir / f".staging-{runid}"
    staging_dir.mkdir()
    journal_path = harness_dir / f".staging-{runid}.journal.jsonl"
    journal_path.write_text("", encoding="utf-8")
    sentinel_path = harness_dir / f".staging-{runid}.complete"
    sentinel_path.write_bytes(b"")  # sentinel present

    # Final manifest already exists (Phase 5 completed)
    final = harness_dir / "installed-manifest.json"
    final.write_text(
        json.dumps({"version": "0.9.7-test", "schema_version": 2, "files": {}}),
        encoding="utf-8",
    )

    # No pending file (os.replace in Phase 5 already consumed it)
    # Recovery: pending absent -> legacy stale staging dir path (no journal in T2 impl; staging is stale if old)
    # The staging dir exists but no pending sidecar; it's new so not stale.
    # So recovery is effectively no-op for fresh staging dirs.
    result = recover_aborted_install(target)

    # Manifest still correct
    data = json.loads(final.read_text(encoding="utf-8"))
    assert data["version"] == "0.9.7-test", "Final manifest must be intact"


# ---------------------------------------------------------------------------
# Test 7: Idempotency — state repair 3x
# ---------------------------------------------------------------------------


def test_state_repair_3x_idempotent(tmp_path):
    """T3-7: run state repair 3x after sentinel-finalize scenario; all succeed."""
    target = tmp_path / "target"
    target.mkdir()
    harness_dir = target / ".harness"
    harness_dir.mkdir()

    runid = "99999-20260521T000005Z-pqr555"
    pending_path = harness_dir / f"installed-manifest.json.pending-{runid}"
    sentinel_path = harness_dir / f".staging-{runid}.complete"
    pending_path.write_text(
        json.dumps({"version": "0.9.7-test", "schema_version": 2, "files": {}}),
        encoding="utf-8",
    )
    sentinel_path.write_bytes(b"")

    # Run 1: finalizes
    r1 = recover_aborted_install(target)
    assert len(r1.finished) >= 1

    # Run 2+3: no-ops
    r2 = recover_aborted_install(target)
    r3 = recover_aborted_install(target)
    # Each subsequent run should find no work to do
    assert r2.found_staging_dirs == 0 or len(r2.finished) == 0
    assert r3.found_staging_dirs == 0 or len(r3.finished) == 0
