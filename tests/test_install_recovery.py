"""T14b — install_recovery tests.

Done-criteria
-------------
(a) test_no_staging_no_op:
    target with no .staging-* dirs → RecoveryResult(found=0, [], [], [], False)

(b) test_finish_complete_pending:
    staging dir with pending files + partial journal (3/5 complete) →
    recover finishes remaining 2 renames; staging dir removed.

(c) test_rollback_aborted_with_backups:
    staging dir with .aborted sentinel + 2 completed renames + backup files →
    recover restores from backups; rolled_back list populated.

(d) test_quarantine_no_backups:
    staging dir with .aborted sentinel + 2 completed renames, no backups →
    displaced files moved to .harness/conflicts/; quarantined list populated.

(e) test_audit_row_emitted:
    recover emits an audit row via lib.audit.audit_append.
"""
from __future__ import annotations

import datetime
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from lib.install_recovery import (  # noqa: E402
    RecoveryResult,
    STAGING_AGE_THRESHOLD_SECS,
    recover_aborted_install,
)
from lib.atomic_io import read_install_journal  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_target(tmp_path: Path) -> Path:
    """Create a minimal target directory with .harness/."""
    target = tmp_path / "target"
    (target / ".harness").mkdir(parents=True)
    return target


def _make_staging(target: Path, name: str, file_map: dict[str, str]) -> Path:
    """Create a staging dir under target/.harness/ with given files."""
    staging = target / ".harness" / name
    staging.mkdir(parents=True)
    for rel, content in file_map.items():
        dest = staging / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
    return staging


def _write_journal(target: Path, staging_name: str, records: list[dict]) -> Path:
    """Write a journal JSONL file alongside the staging dir."""
    journal = target / ".harness" / f"{staging_name}.journal.jsonl"
    with open(str(journal), "w", encoding="utf-8") as jf:
        for rec in records:
            jf.write(json.dumps(rec) + "\n")
    return journal


def _make_stale(staging_dir: Path) -> None:
    """Back-date staging_dir mtime to exceed STAGING_AGE_THRESHOLD_SECS."""
    old_time = time.time() - STAGING_AGE_THRESHOLD_SECS - 60
    os.utime(str(staging_dir), (old_time, old_time))


def _make_backup(target: Path, filename: str, content: bytes) -> Path:
    """Write a fake backup file under .harness/backups/."""
    backups = target / ".harness" / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    ts = "20260521T120000000000000Z"
    bak = backups / f"{filename}.pre-repair.{ts}.12345.bak"
    bak.write_bytes(content)
    return bak


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_no_staging_no_op(tmp_path):
    """No .staging-* dirs → RecoveryResult with all zeros and no actions."""
    target = _make_target(tmp_path)
    result = recover_aborted_install(target)
    assert result.found_staging_dirs == 0
    assert result.finished == []
    assert result.rolled_back == []
    assert result.quarantined == []
    assert result.sentinel_present is False


def test_fresh_staging_not_stale(tmp_path):
    """A staging dir created just now (not old, no sentinel) is ignored."""
    target = _make_target(tmp_path)
    staging = _make_staging(target, ".staging-fresh", {"lib/foo.py": "# foo"})
    # Do NOT back-date → age is < threshold
    result = recover_aborted_install(target)
    assert result.found_staging_dirs == 0
    # staging dir still present (not touched)
    assert staging.exists()


def test_finish_complete_pending(tmp_path):
    """Stale staging dir with pending files → atomic_install_batch resumes."""
    target = _make_target(tmp_path)
    files = {
        "lib/a.py": "# a",
        "lib/b.py": "# b",
        "lib/c.py": "# c",
        "lib/d.py": "# d",
        "lib/e.py": "# e",
    }
    staging = _make_staging(target, ".staging-partial", files)
    _make_stale(staging)

    # Pre-create 3 "already completed" journal entries (a, b, c were renamed)
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    already_done = [
        {"src_rel": "lib/a.py", "dst_rel": "lib/a.py", "rename_at_iso": ts},
        {"src_rel": "lib/b.py", "dst_rel": "lib/b.py", "rename_at_iso": ts},
        {"src_rel": "lib/c.py", "dst_rel": "lib/c.py", "rename_at_iso": ts},
    ]
    _write_journal(target, ".staging-partial", already_done)
    # Simulate that a, b, c are already in target (staged files still also exist
    # in staging — atomic_install_batch will skip missing src + treat dst as done)
    for rel in ("lib/a.py", "lib/b.py", "lib/c.py"):
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(files[rel], encoding="utf-8")
        # Remove from staging to mimic already-renamed
        (staging / rel).unlink()

    result = recover_aborted_install(target)

    assert result.found_staging_dirs == 1
    assert result.sentinel_present is False
    # d and e should now be in target
    assert (target / "lib" / "d.py").exists()
    assert (target / "lib" / "e.py").exists()
    # staging dir should be removed (atomic_install_batch cleaned it up)
    assert not staging.exists()
    # finished list non-empty
    assert len(result.finished) >= 2


def test_rollback_aborted_with_backups(tmp_path):
    """Aborted install + backups present → rolled_back populated."""
    target = _make_target(tmp_path)
    staging = _make_staging(target, ".staging-abort", {"lib/x.py": "# new-x"})
    _make_stale(staging)

    # Write .aborted sentinel
    (staging / ".aborted").write_text(
        json.dumps({"failed_rel": "lib/x.py", "error": "EIO"}), encoding="utf-8"
    )

    # Simulate 2 completed renames in journal (y.py, z.py were installed)
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    journal_records = [
        {"src_rel": "lib/y.py", "dst_rel": "lib/y.py", "rename_at_iso": ts},
        {"src_rel": "lib/z.py", "dst_rel": "lib/z.py", "rename_at_iso": ts},
    ]
    _write_journal(target, ".staging-abort", journal_records)

    # Create installed files (they were renamed into target)
    (target / "lib").mkdir(parents=True, exist_ok=True)
    (target / "lib" / "y.py").write_text("# new-y", encoding="utf-8")
    (target / "lib" / "z.py").write_text("# new-z", encoding="utf-8")

    # Create backups for both
    _make_backup(target, "y.py", b"# old-y")
    _make_backup(target, "z.py", b"# old-z")

    result = recover_aborted_install(target)

    assert result.found_staging_dirs == 1
    assert result.sentinel_present is True
    assert len(result.rolled_back) == 2
    assert result.quarantined == []
    # Installed files were replaced with backup content
    assert (target / "lib" / "y.py").read_bytes() == b"# old-y"
    assert (target / "lib" / "z.py").read_bytes() == b"# old-z"


def test_quarantine_no_backups(tmp_path):
    """Aborted install + no backups → quarantined list populated."""
    target = _make_target(tmp_path)
    staging = _make_staging(target, ".staging-abort-q", {"lib/w.py": "# new-w"})
    _make_stale(staging)

    (staging / ".aborted").write_text(
        json.dumps({"failed_rel": "lib/w.py", "error": "EIO"}), encoding="utf-8"
    )

    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _write_journal(
        target,
        ".staging-abort-q",
        [{"src_rel": "lib/w.py", "dst_rel": "lib/w.py", "rename_at_iso": ts}],
    )

    (target / "lib").mkdir(parents=True, exist_ok=True)
    (target / "lib" / "w.py").write_text("# new-w", encoding="utf-8")
    # No backups created

    result = recover_aborted_install(target)

    assert result.found_staging_dirs == 1
    assert result.sentinel_present is True
    assert result.rolled_back == []
    assert len(result.quarantined) == 1
    # Original installed path should no longer exist (moved to conflicts/)
    assert not (target / "lib" / "w.py").exists()
    # Conflicts dir should have the displaced file
    conflicts = target / ".harness" / "conflicts"
    assert conflicts.is_dir()
    conflict_files = list(conflicts.iterdir())
    assert len(conflict_files) == 1


def test_audit_row_emitted(tmp_path):
    """recover_aborted_install emits an audit row via audit_append."""
    target = _make_target(tmp_path)

    emitted: list[dict] = []

    def _fake_audit_append(entry: dict, *, audit_path):
        emitted.append(entry)

    with patch("lib.install_recovery.audit_append", side_effect=_fake_audit_append):
        # No staging dirs → noop row
        recover_aborted_install(target)

    assert len(emitted) >= 1
    verbs = {e.get("verb") for e in emitted}
    assert "install.recovery.noop" in verbs


def test_audit_row_finished_emitted(tmp_path):
    """Finishing pending renames emits install.recovery.finished audit row."""
    target = _make_target(tmp_path)
    staging = _make_staging(target, ".staging-fin", {"lib/p.py": "# p"})
    _make_stale(staging)

    emitted: list[dict] = []

    def _fake_audit_append(entry: dict, *, audit_path):
        emitted.append(entry)

    with patch("lib.install_recovery.audit_append", side_effect=_fake_audit_append):
        recover_aborted_install(target)

    verbs = {e.get("verb") for e in emitted}
    assert "install.recovery.finished" in verbs


def test_state_repair_delegates(tmp_path):
    """state_repair.repair() calls recover_aborted_install via delegation."""
    target = _make_target(tmp_path)

    # Create minimal ROADMAP.md + STATE.md so repair() does not bail early.
    planning = target / ".planning"
    planning.mkdir()
    (planning / "ROADMAP.md").write_text(
        "# Roadmap\n\n## Phases\n\n- [ ] **Phase 1: Init**\n",
        encoding="utf-8",
    )
    (planning / "STATE.md").write_text(
        "# State\n\n## Current Position\n\n- **Phase**: 1\n",
        encoding="utf-8",
    )

    called_with: list[Path] = []

    import lib.install_recovery as _ir
    original = _ir.recover_aborted_install

    def _spy(t: Path):
        called_with.append(t)
        return original(t)

    with patch.object(_ir, "recover_aborted_install", side_effect=_spy):
        import lib.state_repair as sr
        sr.repair(target)

    assert len(called_with) == 1
    assert called_with[0] == target
