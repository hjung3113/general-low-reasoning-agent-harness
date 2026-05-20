"""T14a — atomic_install_batch tests.

Done-criteria
-------------
(a) test_clean_batch_renames_all:
    Stage 5 files; call helper; assert all 5 in target, staging dir removed,
    journal removed (clean run leaves no staging/journal).

(b) test_idempotent_resume:
    Stage 5 files, manually pre-move 2 into target, then call helper; assert
    remaining 3 moved, journal records all 5 total.

(c) test_simulated_failure:
    Monkey-patch os.replace to raise on the 3rd entry; assert 2 in target,
    3rd+ still in staging, journal records 2 successes + 1 failure, .aborted
    sentinel present.

(d) test_cross_fs_refuses:
    Pass staging_dir and target on different st_dev mounts → CrossFilesystemError.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure scripts/ is on sys.path.
_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from lib.atomic_io import (  # noqa: E402
    AtomicInstallResult,
    CrossFilesystemError,
    atomic_install_batch,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_staging(staging_dir: Path, file_map: dict[str, str]) -> None:
    """Populate staging_dir with files described by {rel_path: content}."""
    for rel, content in file_map.items():
        dest = staging_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")


def _read_journal(journal_path: Path) -> list[dict]:
    """Parse a journal file into a list of dicts (one per line)."""
    records = []
    with open(str(journal_path), encoding="utf-8") as jf:
        for line in jf:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


# ---------------------------------------------------------------------------
# test_clean_batch_renames_all
# ---------------------------------------------------------------------------


def test_clean_batch_renames_all(tmp_path):
    """(a) Clean run: all 5 files renamed; staging dir and journal absent after."""
    staging = tmp_path / ".staging-test"
    staging.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    journal = tmp_path / "journal.jsonl"

    files = {
        "scripts/lib/alpha.py": "# alpha\n",
        "scripts/lib/beta.py": "# beta\n",
        "scripts/lib/gamma.py": "# gamma\n",
        "AGENTS.md": "# agents\n",
        "docs/README.md": "# readme\n",
    }
    _make_staging(staging, files)

    result = atomic_install_batch(staging, target, journal)

    # All 5 reported as completed.
    assert sorted(result.completed) == sorted(files.keys()), (
        f"Expected {sorted(files.keys())}, got {sorted(result.completed)}"
    )
    assert result.failed_entry is None
    assert result.aborted is False

    # All 5 files present in target.
    for rel in files:
        assert (target / rel).exists(), f"Missing in target: {rel}"

    # Clean run: staging dir and journal removed.
    assert not staging.exists(), "staging dir should be removed on clean run"
    assert not journal.exists(), "journal should be removed on clean run"


# ---------------------------------------------------------------------------
# test_idempotent_resume
# ---------------------------------------------------------------------------


def test_idempotent_resume(tmp_path):
    """(b) Pre-move 2 files; helper moves remaining 3; total completed = 5."""
    staging = tmp_path / ".staging-test"
    staging.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    journal = tmp_path / "journal.jsonl"

    all_files = {
        "scripts/lib/alpha.py": "# alpha\n",
        "scripts/lib/beta.py": "# beta\n",
        "scripts/lib/gamma.py": "# gamma\n",
        "AGENTS.md": "# agents\n",
        "docs/README.md": "# readme\n",
    }
    _make_staging(staging, all_files)

    # Manually pre-move the first 2 (sorted order: AGENTS.md, docs/README.md).
    pre_moved = ["AGENTS.md", "docs/README.md"]
    for rel in pre_moved:
        src = staging / rel
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(str(src), str(dst))
        # Simulate a partially-written journal from a prior run.
        import datetime
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with open(str(journal), "a", encoding="utf-8") as jf:
            jf.write(json.dumps({"src_rel": rel, "dst_rel": rel, "rename_at_iso": ts}) + "\n")

    # Now call helper — should pick up remaining 3 from staging.
    result = atomic_install_batch(staging, target, journal)

    assert result.failed_entry is None
    assert result.aborted is False
    assert sorted(result.completed) == sorted(all_files.keys()), (
        f"completed={sorted(result.completed)}, expected={sorted(all_files.keys())}"
    )

    # All 5 in target.
    for rel in all_files:
        assert (target / rel).exists(), f"Missing in target: {rel}"


# ---------------------------------------------------------------------------
# test_simulated_failure
# ---------------------------------------------------------------------------


def test_simulated_failure(tmp_path):
    """(c) Inject failure on the 3rd rename; assert partial results + sentinel."""
    staging = tmp_path / ".staging-fail"
    staging.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    journal = tmp_path / "journal.jsonl"

    # 5 files, sorted alphabetically: a, b, c, d, e → fail on 'c'
    files = {
        "a.txt": "aaa\n",
        "b.txt": "bbb\n",
        "c.txt": "ccc\n",  # failure injected here
        "d.txt": "ddd\n",
        "e.txt": "eee\n",
    }
    _make_staging(staging, files)

    # Sorted order: a.txt, b.txt, c.txt, d.txt, e.txt
    sorted_rels = sorted(files.keys())
    fail_target_rel = sorted_rels[2]  # "c.txt"

    _original_replace = os.replace
    call_counter = {"n": 0}

    def _patched_replace(src: str, dst: str) -> None:
        call_counter["n"] += 1
        if call_counter["n"] == 3:
            raise OSError(5, "Simulated IO error")
        _original_replace(src, dst)

    with patch("os.replace", side_effect=_patched_replace):
        result = atomic_install_batch(staging, target, journal)

    # First 2 succeeded.
    assert sorted(result.completed) == sorted(sorted_rels[:2]), (
        f"completed={sorted(result.completed)}"
    )
    assert result.failed_entry == fail_target_rel
    assert result.aborted is True

    # First 2 in target.
    for rel in sorted_rels[:2]:
        assert (target / rel).exists(), f"Missing in target: {rel}"

    # 3rd–5th still in staging (or at least staging dir still present).
    assert staging.exists(), "staging dir must NOT be cleaned up on failure"

    # .aborted sentinel present in staging dir.
    sentinel = staging / ".aborted"
    assert sentinel.exists(), ".aborted sentinel missing"
    sentinel_data = json.loads(sentinel.read_text(encoding="utf-8"))
    assert sentinel_data["failed_rel"] == fail_target_rel

    # Journal records 2 successes + 1 failure line.
    assert journal.exists(), "journal must be present after failure"
    records = _read_journal(journal)
    success_recs = [r for r in records if "error" not in r]
    failure_recs = [r for r in records if "error" in r]
    assert len(success_recs) == 2, f"Expected 2 success entries, got {success_recs}"
    assert len(failure_recs) == 1, f"Expected 1 failure entry, got {failure_recs}"
    assert failure_recs[0]["src_rel"] == fail_target_rel


# ---------------------------------------------------------------------------
# test_cross_fs_refuses
# ---------------------------------------------------------------------------


def test_cross_fs_refuses(tmp_path):
    """(d) Cross-filesystem staging dir raises CrossFilesystemError.

    We mock os.stat to return different st_dev values for staging vs target,
    avoiding reliance on actual filesystem topology (which varies per machine).
    """
    staging = tmp_path / ".staging-xfs"
    staging.mkdir()
    target = tmp_path / "target-xfs"
    target.mkdir()
    journal = tmp_path / "journal.jsonl"

    _original_stat = os.stat

    def _patched_stat(path, **kwargs):
        result = _original_stat(path, **kwargs)
        # Return a fake stat with a different device number for staging.
        if str(path) == str(staging):
            # Build a mock with st_dev overridden.
            class _FakeStat:
                st_dev = result.st_dev + 9999
                # Forward all other attributes.
                def __getattr__(self, name):
                    return getattr(result, name)
            return _FakeStat()
        return result

    with patch("os.stat", side_effect=_patched_stat):
        with pytest.raises(CrossFilesystemError):
            atomic_install_batch(staging, target, journal)
