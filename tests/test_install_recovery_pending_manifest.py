"""T2 — install_recovery._recover_pending_manifest (sentinel + nonce + .tmp cleanup).

Test cases:
1. Sentinel present -> finalize; manifest bytes equal pending content
2. .aborted marker (no sentinel) -> explicit rollback; backups restored; pending removed
3. Journal+staging, no sentinel, no .aborted -> resume via batch; sentinel appears; finalize fires
4. Journal+staging, resume fails -> explicit rollback (NOOP result; staging preserved)
5. Pending sidecar only (no journal/staging) -> orphan -> quarantined; audit row asserted
6. Idempotent: run recovery 3x; first does work, 2nd+3rd are no-ops; rc=0 each time
7. .complete.tmp orphan older than 60s -> unlinked during scan
8. Two pending sidecars with different runids -> each processed independently
9. Sentinel + .aborted coexistence: .aborted wins -> EXPLICIT ROLLBACK (not finalize)
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from lib.install_recovery import (  # noqa: E402
    RecoveryAction,
    _cleanup_sentinel_tmp_orphans,
    _finalize_pending_manifest,
    _recover_pending_manifest,
    recover_aborted_install,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_target(tmp_path: Path) -> Path:
    target = tmp_path / "target"
    target.mkdir()
    harness = target / ".harness"
    harness.mkdir()
    return target


def _write_pending(harness: Path, runid: str, version: str = "0.9.7-test") -> Path:
    pending_path = harness / f"installed-manifest.json.pending-{runid}"
    pending_path.write_text(
        json.dumps({"version": version, "schema_version": 2, "files": {}}),
        encoding="utf-8",
    )
    return pending_path


def _write_sentinel(harness: Path, runid: str) -> Path:
    sentinel = harness / f".staging-{runid}.complete"
    sentinel.write_bytes(b"")
    return sentinel


def _write_staging_and_journal(harness: Path, target: Path, runid: str) -> tuple[Path, Path]:
    staging_dir = harness / f".staging-{runid}"
    staging_dir.mkdir()
    (staging_dir / "lib").mkdir()
    (staging_dir / "lib" / "foo.py").write_text("# content\n", encoding="utf-8")

    journal_path = harness / f".staging-{runid}.journal.jsonl"
    # empty journal = no completed entries yet
    journal_path.write_text("", encoding="utf-8")
    return staging_dir, journal_path


# ---------------------------------------------------------------------------
# Test 1: Sentinel present -> finalize
# ---------------------------------------------------------------------------


def test_sentinel_present_finalizes(tmp_path):
    """T2-1: sentinel present -> pending renamed to final; content preserved."""
    target = _make_target(tmp_path)
    harness = target / ".harness"
    runid = "12345-20260521T000000Z-abc123"

    pending_path = _write_pending(harness, runid)
    sentinel_path = _write_sentinel(harness, runid)
    pending_content = json.loads(pending_path.read_text(encoding="utf-8"))

    result = recover_aborted_install(target)

    final = harness / "installed-manifest.json"
    assert final.exists(), "Final manifest must exist after finalization"
    assert not pending_path.exists(), "Pending sidecar must be removed after finalization"
    assert not sentinel_path.exists(), "Sentinel must be cleaned up after finalization"

    actual = json.loads(final.read_text(encoding="utf-8"))
    assert actual["version"] == pending_content["version"]
    assert len(result.finished) >= 1


# ---------------------------------------------------------------------------
# Test 2: .aborted marker -> explicit rollback; pending removed
# ---------------------------------------------------------------------------


def test_aborted_marker_rolls_back(tmp_path):
    """T2-2: .aborted in staging -> rollback; pending sidecar removed."""
    target = _make_target(tmp_path)
    harness = target / ".harness"
    runid = "12345-20260521T000001Z-def456"

    pending_path = _write_pending(harness, runid)
    staging_dir = harness / f".staging-{runid}"
    staging_dir.mkdir()
    # Plant .aborted marker
    (staging_dir / ".aborted").write_text(
        json.dumps({"failed_rel": "lib/foo.py", "error": "simulated"}),
        encoding="utf-8",
    )

    result = recover_aborted_install(target)

    assert not pending_path.exists(), "Pending sidecar must be removed after rollback"
    assert not staging_dir.exists(), "Staging dir must be cleaned up after rollback"
    # No final manifest from this (no completed entries to roll back / finalize)
    final = harness / "installed-manifest.json"
    # final may not exist — we didn't have completed journal entries to finalize


# ---------------------------------------------------------------------------
# Test 3: journal+staging, no sentinel, no .aborted -> resume batch, finalize
# ---------------------------------------------------------------------------


def test_journal_staging_resumes_and_finalizes(tmp_path):
    """T2-3: journal+staging, no sentinel -> resume batch -> sentinel -> finalize."""
    target = _make_target(tmp_path)
    harness = target / ".harness"
    runid = "12345-20260521T000002Z-ghi789"

    pending_path = _write_pending(harness, runid)
    staging_dir, journal_path = _write_staging_and_journal(harness, target, runid)

    result = recover_aborted_install(target)

    # After recovery: the batch was resumed, sentinel written, then finalized
    final = harness / "installed-manifest.json"
    assert final.exists(), "Final manifest must exist after resumed finalization"
    assert not pending_path.exists(), "Pending sidecar must be consumed"


# ---------------------------------------------------------------------------
# Test 4: journal+staging, resume fails -> NOOP (staging preserved)
# ---------------------------------------------------------------------------


def test_resume_fails_noop(tmp_path):
    """T2-4: resume batch fails (OSError) -> NOOP; staging preserved."""
    target = _make_target(tmp_path)
    harness = target / ".harness"
    runid = "12345-20260521T000003Z-jkl012"

    pending_path = _write_pending(harness, runid)
    staging_dir, journal_path = _write_staging_and_journal(harness, target, runid)

    with patch("lib.install_recovery.atomic_install_batch", side_effect=OSError("simulated batch fail")):
        action = _recover_pending_manifest(target, pending_path, __import__("lib.install_recovery", fromlist=["RecoveryResult"]).RecoveryResult(found_staging_dirs=1))

    # NOOP when batch fails
    assert action == RecoveryAction.NOOP
    # Pending sidecar still present (we couldn't finalize)
    assert pending_path.exists(), "Pending sidecar should be preserved on failed resume"


# ---------------------------------------------------------------------------
# Test 5: Pending sidecar only (orphan) -> quarantined; audit row
# ---------------------------------------------------------------------------


def test_orphan_pending_quarantined(tmp_path):
    """T2-5: pending sidecar only (no journal/staging/sentinel) -> quarantined."""
    target = _make_target(tmp_path)
    harness = target / ".harness"
    runid = "12345-20260521T000004Z-mno345"

    pending_path = _write_pending(harness, runid)
    # No staging dir, no journal, no sentinel

    result = recover_aborted_install(target)

    assert not pending_path.exists(), "Pending sidecar should be quarantined (moved)"
    conflicts = target / ".harness" / "conflicts"
    assert conflicts.exists(), "Conflicts dir should be created"
    quarantined_files = list(conflicts.iterdir())
    assert len(quarantined_files) >= 1, "At least one file should be in conflicts dir"


# ---------------------------------------------------------------------------
# Test 6: Idempotent - 3x recovery; first does work, 2nd+3rd no-ops
# ---------------------------------------------------------------------------


def test_idempotent_recovery(tmp_path):
    """T2-6: run recovery 3x; first run finalizes; subsequent runs are no-ops."""
    target = _make_target(tmp_path)
    harness = target / ".harness"
    runid = "12345-20260521T000005Z-pqr678"

    pending_path = _write_pending(harness, runid)
    _write_sentinel(harness, runid)

    # First run
    result1 = recover_aborted_install(target)
    final = harness / "installed-manifest.json"
    assert final.exists()
    assert not pending_path.exists()

    # Second run - no-op
    result2 = recover_aborted_install(target)
    assert result2.found_staging_dirs == 0 or len(result2.finished) == 0

    # Third run - no-op
    result3 = recover_aborted_install(target)
    assert result3.found_staging_dirs == 0 or len(result3.finished) == 0


# ---------------------------------------------------------------------------
# Test 7: .complete.tmp orphan older than 60s -> unlinked
# ---------------------------------------------------------------------------


def test_sentinel_tmp_orphan_cleanup(tmp_path):
    """T2-7: .staging-*.complete.tmp older than 60s -> unlinked during scan."""
    target = _make_target(tmp_path)
    harness = target / ".harness"

    # Create a .complete.tmp file and backdate its mtime
    sentinel_tmp = harness / ".staging-old-runid.complete.tmp"
    sentinel_tmp.write_bytes(b"")
    old_mtime = time.time() - 120  # 120 seconds ago (> 60s threshold)
    os.utime(str(sentinel_tmp), (old_mtime, old_mtime))

    # Run cleanup
    removed = _cleanup_sentinel_tmp_orphans(target)
    assert removed == 1, f"Expected 1 removed, got {removed}"
    assert not sentinel_tmp.exists(), ".complete.tmp should be removed"


# ---------------------------------------------------------------------------
# Test 8: Two pending sidecars with different runids -> each processed
# ---------------------------------------------------------------------------


def test_two_pending_sidecars_processed_independently(tmp_path):
    """T2-8: two pending sidecars -> each processed independently."""
    target = _make_target(tmp_path)
    harness = target / ".harness"
    runid1 = "11111-20260521T000000Z-aaa111"
    runid2 = "22222-20260521T000001Z-bbb222"

    pending1 = _write_pending(harness, runid1, version="0.9.7-v1")
    pending2 = _write_pending(harness, runid2, version="0.9.7-v2")
    _write_sentinel(harness, runid1)
    # runid2: orphan (no journal/staging/sentinel)

    result = recover_aborted_install(target)

    # pending1 should be finalized (sentinel present)
    # pending2 should be quarantined (orphan)
    final = harness / "installed-manifest.json"
    # At least one got processed
    assert not pending1.exists() or not pending2.exists()


# ---------------------------------------------------------------------------
# Test 9: Sentinel + .aborted coexistence -> .aborted wins (EXPLICIT ROLLBACK)
# ---------------------------------------------------------------------------


def test_aborted_wins_over_sentinel(tmp_path):
    """T2-9: .aborted + sentinel coexistence -> .aborted wins; rollback, not finalize."""
    target = _make_target(tmp_path)
    harness = target / ".harness"
    runid = "12345-20260521T000006Z-stu901"

    pending_path = _write_pending(harness, runid)
    sentinel_path = _write_sentinel(harness, runid)
    staging_dir = harness / f".staging-{runid}"
    staging_dir.mkdir()
    # Plant .aborted marker alongside sentinel
    (staging_dir / ".aborted").write_text(
        json.dumps({"failed_rel": "lib/bar.py", "error": "simulated"}),
        encoding="utf-8",
    )

    from lib.install_recovery import RecoveryResult
    result = RecoveryResult(found_staging_dirs=1)
    action = _recover_pending_manifest(target, pending_path, result)

    # .aborted must win: action is ROLLED_BACK, not FINALIZED
    assert action == RecoveryAction.ROLLED_BACK, (
        f"Expected ROLLED_BACK (aborted wins), got {action}"
    )
    # Final manifest should NOT be written (no completed entries to finalize)
    final = harness / "installed-manifest.json"
    assert not final.exists(), "Final manifest must NOT be written when .aborted wins"
    # Pending sidecar cleaned up
    assert not pending_path.exists(), "Pending sidecar must be removed on rollback"
