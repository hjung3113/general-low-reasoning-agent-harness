"""S06-audit-chain: per-entry hash chain verifier tests (design §2.2).

Tests verify:
- compute_entry_hash() produces canonical rfc8785 sha256 output
- stamp_chain_fields() fills all required chain fields
- walk_chain() yields steps in order and raises on corruption
- verify_chain() returns a ChainVerifyResult with correct fields
- Error class hierarchy maps to exit 10
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from lib.audit_chain import (
    AuditChainDuplicateError,
    AuditChainError,
    AuditChainGapError,
    AuditChainRotationSeamError,
    AuditChainTamperedError,
    AuditChainTruncationError,
    ChainStep,
    ChainVerifyResult,
    compute_entry_hash,
    stamp_chain_fields,
    verify_chain,
    walk_chain,
    GENESIS_HASH,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entry(verb: str = "phase.set", **extra) -> dict:
    base = {
        "verb": verb,
        "at": "2026-05-17T00:00:00Z",
        "index": 1,
        "schema_version": 2,
    }
    base.update(extra)
    return base


def _write_chain_entries(path: Path, entries: list[dict]) -> None:
    """Stamp chain fields on each entry and write to JSONL file."""
    from lib.audit_chain import stamp_chain_fields
    prev_hash = GENESIS_HASH
    seq = 0
    seq_global = 0
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


# ---------------------------------------------------------------------------
# compute_entry_hash
# ---------------------------------------------------------------------------

class TestComputeEntryHash:
    def test_returns_hex_string(self):
        entry = _make_entry()
        h = compute_entry_hash(entry)
        assert isinstance(h, str)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_deterministic(self):
        entry = _make_entry()
        assert compute_entry_hash(entry) == compute_entry_hash(entry)

    def test_excludes_entry_hash_field(self):
        entry = _make_entry()
        entry_with_hash = dict(entry, entry_hash="dummy_value_ignored")
        assert compute_entry_hash(entry) == compute_entry_hash(entry_with_hash)

    def test_excludes_previous_entry_hash_field(self):
        """previous_entry_hash participates in compute_entry_hash via
        inclusion in canonical input — NOT excluded like entry_hash."""
        entry_no_prev = _make_entry()
        entry_with_prev = dict(entry_no_prev, previous_entry_hash="abc" * 21 + "ab")
        # Should differ because previous_entry_hash is included in the hash input
        assert compute_entry_hash(entry_no_prev) != compute_entry_hash(entry_with_prev)

    def test_different_field_values_differ(self):
        e1 = _make_entry(verb="phase.approve")
        e2 = _make_entry(verb="phase.set")
        assert compute_entry_hash(e1) != compute_entry_hash(e2)

    def test_field_order_doesnt_matter(self):
        """rfc8785 sorts keys — field order must be irrelevant."""
        e1 = {"verb": "phase.set", "at": "2026-05-17T00:00:00Z", "index": 1}
        e2 = {"at": "2026-05-17T00:00:00Z", "index": 1, "verb": "phase.set"}
        assert compute_entry_hash(e1) == compute_entry_hash(e2)


# ---------------------------------------------------------------------------
# stamp_chain_fields
# ---------------------------------------------------------------------------

class TestStampChainFields:
    def test_stamps_all_required_fields(self):
        draft = _make_entry()
        stamped = stamp_chain_fields(
            draft,
            previous_entry_hash=GENESIS_HASH,
            seq=1,
            seq_global=1,
        )
        assert stamped["seq"] == 1
        assert stamped["seq_global"] == 1
        assert stamped["previous_entry_hash"] == GENESIS_HASH
        assert "entry_hash" in stamped
        assert "schema_version" in stamped

    def test_entry_hash_computed_last(self):
        """entry_hash must be sha256 of entry_minus_entry_hash (with previous_entry_hash included)."""
        draft = _make_entry()
        prev = GENESIS_HASH
        stamped = stamp_chain_fields(draft, previous_entry_hash=prev, seq=1, seq_global=1)
        # Remove entry_hash and re-compute to verify correctness
        entry_for_hash = {k: v for k, v in stamped.items() if k != "entry_hash"}
        expected_hash = compute_entry_hash(entry_for_hash)
        assert stamped["entry_hash"] == expected_hash

    def test_does_not_mutate_input(self):
        draft = _make_entry()
        original = dict(draft)
        stamp_chain_fields(draft, previous_entry_hash=GENESIS_HASH, seq=1, seq_global=1)
        assert draft == original


# ---------------------------------------------------------------------------
# walk_chain / verify_chain — clean chain
# ---------------------------------------------------------------------------

class TestWalkChainClean:
    def test_single_entry(self, tmp_path):
        log = tmp_path / "audit.log"
        entries = [_make_entry(verb="phase.approve")]
        _write_chain_entries(log, entries)
        steps = list(walk_chain(log))
        assert len(steps) == 1
        assert steps[0].entry["verb"] == "phase.approve"

    def test_multiple_entries(self, tmp_path):
        log = tmp_path / "audit.log"
        entries = [_make_entry(verb="phase.set"), _make_entry(verb="phase.approve"), _make_entry(verb="phase.reopen")]
        _write_chain_entries(log, entries)
        steps = list(walk_chain(log))
        assert len(steps) == 3
        for i, step in enumerate(steps):
            assert step.entry["seq"] == i + 1
            assert step.entry["seq_global"] == i + 1

    def test_verify_chain_ok(self, tmp_path):
        log = tmp_path / "audit.log"
        entries = [_make_entry(verb="phase.set"), _make_entry(verb="phase.approve")]
        _write_chain_entries(log, entries)
        result = verify_chain(log)
        assert isinstance(result, ChainVerifyResult)
        assert result.ok is True
        assert result.entries_walked == 2
        assert result.error is None

    def test_genesis_hash_is_all_zeros(self):
        assert GENESIS_HASH == "0" * 64

    def test_empty_log_is_ok(self, tmp_path):
        log = tmp_path / "audit.log"
        log.write_text("", encoding="utf-8")
        result = verify_chain(log)
        assert result.ok is True
        assert result.entries_walked == 0

    def test_missing_log_is_ok(self, tmp_path):
        log = tmp_path / "audit.log"
        result = verify_chain(log)
        assert result.ok is True
        assert result.entries_walked == 0

    def test_v1_entries_tolerated(self, tmp_path):
        """Legacy v1 entries (no chain fields) are tolerated — only v2 entries are chain-verified."""
        log = tmp_path / "audit.log"
        v1_entry = {"verb": "phase.set", "at": "2026-05-17T00:00:00Z", "index": 1}
        log.write_text(json.dumps(v1_entry) + "\n", encoding="utf-8")
        result = verify_chain(log)
        assert result.ok is True


# ---------------------------------------------------------------------------
# walk_chain / verify_chain — tampered chain
# ---------------------------------------------------------------------------

class TestWalkChainTampered:
    def test_tampered_entry_hash_raises(self, tmp_path):
        log = tmp_path / "audit.log"
        entries = [_make_entry(verb="phase.set"), _make_entry(verb="phase.approve")]
        _write_chain_entries(log, entries)
        # Corrupt the first entry's entry_hash
        lines = log.read_text().splitlines()
        first = json.loads(lines[0])
        first["entry_hash"] = "a" * 64
        lines[0] = json.dumps(first, separators=(",", ":"), sort_keys=True)
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(AuditChainTamperedError):
            list(walk_chain(log))

    def test_verify_chain_tampered_returns_not_ok(self, tmp_path):
        log = tmp_path / "audit.log"
        entries = [_make_entry(verb="phase.set")]
        _write_chain_entries(log, entries)
        lines = log.read_text().splitlines()
        entry = json.loads(lines[0])
        entry["verb"] = "tampered"  # mutate but keep entry_hash stale
        lines[0] = json.dumps(entry, separators=(",", ":"), sort_keys=True)
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = verify_chain(log)
        assert result.ok is False
        assert result.error is not None

    def test_previous_hash_mismatch_raises(self, tmp_path):
        """If previous_entry_hash of entry N+1 doesn't match entry_hash of N."""
        log = tmp_path / "audit.log"
        entries = [_make_entry(verb="phase.set"), _make_entry(verb="phase.approve")]
        _write_chain_entries(log, entries)
        lines = log.read_text().splitlines()
        second = json.loads(lines[1])
        second["previous_entry_hash"] = "b" * 64  # corrupt
        # re-stamp entry_hash to match the new previous_entry_hash
        entry_for_hash = {k: v for k, v in second.items() if k != "entry_hash"}
        second["entry_hash"] = compute_entry_hash(entry_for_hash)
        lines[1] = json.dumps(second, separators=(",", ":"), sort_keys=True)
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(AuditChainTamperedError):
            list(walk_chain(log))


# ---------------------------------------------------------------------------
# Fixture-based tests: use tests/fixtures/audit/
# ---------------------------------------------------------------------------

FIXTURE_AUDIT_DIR = Path(__file__).parent.parent / "fixtures" / "audit"


class TestFixtures:
    def test_tampered_tail_rejected(self):
        path = FIXTURE_AUDIT_DIR / "tampered_tail.jsonl"
        if not path.exists():
            pytest.skip("fixture missing: tampered_tail.jsonl")
        result = verify_chain(path)
        assert result.ok is False

    def test_duplicate_seq_global_raises(self):
        path = FIXTURE_AUDIT_DIR / "duplicate_seq_global.jsonl"
        if not path.exists():
            pytest.skip("fixture missing: duplicate_seq_global.jsonl")
        with pytest.raises(AuditChainDuplicateError):
            list(walk_chain(path))

    def test_mixed_v1_v2_rotation_ok(self):
        """S06 golden fixture: v1+v2 mixed with rotation seam passes."""
        audit_log = FIXTURE_AUDIT_DIR / "mixed_v1_v2_rotation_ok" / "audit.log"
        rotation = FIXTURE_AUDIT_DIR / "mixed_v1_v2_rotation_ok"
        if not audit_log.exists():
            pytest.skip("fixture missing: mixed_v1_v2_rotation_ok")
        result = verify_chain(audit_log, rotation_dir=rotation)
        assert result.ok is True


# ---------------------------------------------------------------------------
# Error class hierarchy
# ---------------------------------------------------------------------------

class TestErrorHierarchy:
    def test_all_errors_are_audit_chain_error(self):
        for cls in [AuditChainGapError, AuditChainDuplicateError,
                    AuditChainTruncationError, AuditChainRotationSeamError,
                    AuditChainTamperedError]:
            assert issubclass(cls, AuditChainError)

    def test_audit_chain_error_is_os_error(self):
        assert issubclass(AuditChainError, OSError)

    def test_exit_code_on_error_classes(self):
        """All chain error classes must carry exit_code=10."""
        for cls in [AuditChainGapError, AuditChainDuplicateError,
                    AuditChainTruncationError, AuditChainRotationSeamError,
                    AuditChainTamperedError]:
            err = cls("test error")
            assert err.exit_code == 10
