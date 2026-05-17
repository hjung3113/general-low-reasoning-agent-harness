"""S06-audit-chain: rotation seam verifier tests (design §2.5).

Tests verify:
- enumerate_rotated_files() returns files in correct order
- chain walker traverses rotated files correctly
- rotation seam hash is validated
- missing rotation file detected (AuditChainGapError)
- seq_global gap detected across rotation
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.audit_chain import (
    AuditChainGapError,
    AuditChainRotationSeamError,
    GENESIS_HASH,
    stamp_chain_fields,
    verify_chain,
    walk_chain,
)
from lib.audit_rotation import enumerate_rotated_files


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entry(verb: str = "phase.set", **extra) -> dict:
    base = {"verb": verb, "at": "2026-05-17T00:00:00Z", "schema_version": 2}
    base.update(extra)
    return base


def _write_entries_to_file(path: Path, entries: list[dict],
                           start_seq: int = 1, start_seq_global: int = 1,
                           first_prev_hash: str = GENESIS_HASH) -> str:
    """Write entries with chain fields. Returns the last entry_hash."""
    prev_hash = first_prev_hash
    seq = start_seq - 1
    seq_global = start_seq_global - 1
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for entry in entries:
            seq += 1
            seq_global += 1
            stamped = stamp_chain_fields(
                dict(entry),
                previous_entry_hash=prev_hash,
                seq=seq,
                seq_global=seq_global,
            )
            prev_hash = stamped["entry_hash"]
            f.write(json.dumps(stamped, separators=(",", ":"), sort_keys=True) + "\n")
    return prev_hash


def _setup_rotation(tmp_path: Path, *, n_old: int = 3, n_new: int = 2):
    """Create audit.log.1 (old) and audit.log (current tip) with valid seam.

    §2.5 / P1-3: the last entry in audit.log.1 MUST be verb=audit.rotated
    with next_file_seed_previous_entry_hash set to its own entry_hash.
    The first entry of audit.log uses that hash as previous_entry_hash.
    """
    old_log = tmp_path / "audit.log.1"
    cur_log = tmp_path / "audit.log"

    old_entries = [_make_entry(f"phase.set_{i}") for i in range(n_old)]
    last_old_hash = _write_entries_to_file(old_log, old_entries,
                                           start_seq=1, start_seq_global=1,
                                           first_prev_hash=GENESIS_HASH)

    # Append audit.rotated seam entry to old log
    seam_seq = n_old + 1
    seam_seq_global = n_old + 1
    seam_draft = {"verb": "audit.rotated", "at": "2026-05-17T00:00:00Z",
                  "index": n_old + 1, "schema_version": 2}
    seam_stamped = stamp_chain_fields(
        seam_draft,
        previous_entry_hash=last_old_hash,
        seq=seam_seq,
        seq_global=seam_seq_global,
    )
    # next_file_seed_previous_entry_hash = seam entry's own entry_hash
    seed_hash = seam_stamped["entry_hash"]
    seam_stamped["next_file_seed_previous_entry_hash"] = seed_hash
    with open(old_log, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(seam_stamped, separators=(",", ":"), sort_keys=True) + "\n")

    new_entries = [_make_entry(f"phase.approve_{i}") for i in range(n_new)]
    _write_entries_to_file(cur_log, new_entries,
                           start_seq=1, start_seq_global=n_old + 2,
                           first_prev_hash=seed_hash)
    return old_log, cur_log


# ---------------------------------------------------------------------------
# enumerate_rotated_files
# ---------------------------------------------------------------------------

class TestEnumerateRotatedFiles:
    def test_no_rotation_returns_just_log(self, tmp_path):
        log = tmp_path / "audit.log"
        log.write_text("", encoding="utf-8")
        files = enumerate_rotated_files(log)
        assert files == [log]

    def test_one_rotation(self, tmp_path):
        log = tmp_path / "audit.log"
        log1 = tmp_path / "audit.log.1"
        log.write_text("", encoding="utf-8")
        log1.write_text("", encoding="utf-8")
        files = enumerate_rotated_files(log)
        assert files == [log1, log]

    def test_multiple_rotations_ordered(self, tmp_path):
        log = tmp_path / "audit.log"
        log.write_text("", encoding="utf-8")
        for n in range(1, 4):
            (tmp_path / f"audit.log.{n}").write_text("", encoding="utf-8")
        files = enumerate_rotated_files(log)
        # Should be log.3, log.2, log.1, log (oldest first)
        assert files[0].name == "audit.log.3"
        assert files[-1].name == "audit.log"
        assert len(files) == 4


# ---------------------------------------------------------------------------
# Rotation seam chain walk — clean
# ---------------------------------------------------------------------------

class TestRotationSeamClean:
    def test_two_file_rotation_ok(self, tmp_path):
        _setup_rotation(tmp_path, n_old=3, n_new=2)
        result = verify_chain(tmp_path / "audit.log", rotation_dir=tmp_path)
        assert result.ok is True
        # 3 old + 1 seam (audit.rotated) + 2 new = 6
        assert result.entries_walked == 6
        assert result.rotation_files_traversed == 1

    def test_seq_global_monotonic(self, tmp_path):
        _setup_rotation(tmp_path, n_old=3, n_new=2)
        steps = list(walk_chain(tmp_path / "audit.log", rotation_dir=tmp_path))
        seq_globals = [s.entry["seq_global"] for s in steps if "seq_global" in s.entry]
        # 1,2,3 (old) + 4 (seam) + 5,6 (new)
        assert seq_globals == list(range(1, 7))


# ---------------------------------------------------------------------------
# Rotation seam — error cases
# ---------------------------------------------------------------------------

class TestRotationSeamErrors:
    def test_missing_rotation_file_raises_gap(self, tmp_path):
        """If audit.log.2 exists but audit.log.1 is missing, AuditChainGapError."""
        log = tmp_path / "audit.log"
        log2 = tmp_path / "audit.log.2"
        log.write_text("", encoding="utf-8")
        log2.write_text("", encoding="utf-8")  # present
        # audit.log.1 is absent — contiguity check should fail
        with pytest.raises(AuditChainGapError):
            list(walk_chain(log, rotation_dir=tmp_path))

    def test_seam_hash_mismatch_raises(self, tmp_path):
        """If first entry of audit.log has wrong previous_entry_hash (doesn't match last of audit.log.1)."""
        old_log = tmp_path / "audit.log.1"
        cur_log = tmp_path / "audit.log"

        # Write old log normally
        _write_entries_to_file(old_log, [_make_entry("phase.set_0")],
                               start_seq=1, start_seq_global=1, first_prev_hash=GENESIS_HASH)

        # Write new log with WRONG previous_entry_hash at seam
        entry = _make_entry("phase.approve_0")
        stamped = stamp_chain_fields(
            dict(entry),
            previous_entry_hash="dead" * 16,  # wrong
            seq=1,
            seq_global=2,
        )
        cur_log.write_text(
            json.dumps(stamped, separators=(",", ":"), sort_keys=True) + "\n",
            encoding="utf-8"
        )

        with pytest.raises(AuditChainRotationSeamError):
            list(walk_chain(cur_log, rotation_dir=tmp_path))


# ---------------------------------------------------------------------------
# Fixture-based tests
# ---------------------------------------------------------------------------

FIXTURE_AUDIT_DIR = Path(__file__).parent.parent / "fixtures" / "audit"


class TestFixtureRotationSeam:
    def test_missing_rotation_gap_fixture(self):
        path = FIXTURE_AUDIT_DIR / "missing_rotation_gap.jsonl"
        if not path.exists():
            pytest.skip("fixture missing: missing_rotation_gap.jsonl")
        result = verify_chain(path)
        assert result.ok is False

    def test_rotation_seam_mismatch_fixture(self):
        path = FIXTURE_AUDIT_DIR / "rotation_seam_mismatch.jsonl"
        if not path.exists():
            pytest.skip("fixture missing: rotation_seam_mismatch.jsonl")
        result = verify_chain(path)
        assert result.ok is False
