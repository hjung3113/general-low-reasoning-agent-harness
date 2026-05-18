#!/usr/bin/env python3
"""Tests for _audit_tail_partial_write predicate (02d Group β fix β-2)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import phase_txn  # noqa: E402  (path injection above)

# Access the private helper via module attribute.
_audit_tail_partial_write = phase_txn._audit_tail_partial_write


class TestAuditTailPartialWrite(unittest.TestCase):

    def _write_audit(self, tmpdir: str, content: str) -> Path:
        p = Path(tmpdir) / "audit.log"
        p.write_text(content, encoding="utf-8")
        return p

    # --- well-formed full row → not partial -----------------------------------

    def test_full_well_formed_row_not_partial(self) -> None:
        entry = {
            "entry_hash": "abc123",
            "txn_id": "txn-001",
            "after_sha256": "deadbeef",
            "verb": "phase.set",
            "at": "2026-01-01T00:00:00Z",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            audit = self._write_audit(tmpdir, json.dumps(entry) + "\n")
            self.assertFalse(_audit_tail_partial_write(audit))

    # --- missing entry_hash → partial -----------------------------------------

    def test_missing_entry_hash_is_partial(self) -> None:
        entry = {
            "txn_id": "txn-002",
            "after_sha256": "deadbeef",
            "verb": "phase.set",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            audit = self._write_audit(tmpdir, json.dumps(entry) + "\n")
            self.assertTrue(_audit_tail_partial_write(audit))

    # --- missing txn_id → partial ---------------------------------------------

    def test_missing_txn_id_is_partial(self) -> None:
        entry = {
            "entry_hash": "abc123",
            "after_sha256": "deadbeef",
            "verb": "phase.set",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            audit = self._write_audit(tmpdir, json.dumps(entry) + "\n")
            self.assertTrue(_audit_tail_partial_write(audit))

    # --- missing after_sha256 → partial --------------------------------------

    def test_missing_after_sha256_is_partial(self) -> None:
        entry = {
            "entry_hash": "abc123",
            "txn_id": "txn-003",
            "verb": "phase.set",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            audit = self._write_audit(tmpdir, json.dumps(entry) + "\n")
            self.assertTrue(_audit_tail_partial_write(audit))

    # --- malformed JSON → partial (existing behaviour preserved) -------------

    def test_malformed_json_is_partial(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            audit = self._write_audit(tmpdir, '{"entry_hash": "abc", BROKEN\n')
            self.assertTrue(_audit_tail_partial_write(audit))

    # --- missing file → not partial ------------------------------------------

    def test_missing_audit_file_not_partial(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            audit = Path(tmpdir) / "no-such-audit.log"
            self.assertFalse(_audit_tail_partial_write(audit))

    # --- empty file → not partial --------------------------------------------

    def test_empty_audit_file_not_partial(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            audit = self._write_audit(tmpdir, "")
            self.assertFalse(_audit_tail_partial_write(audit))


if __name__ == "__main__":
    unittest.main()
