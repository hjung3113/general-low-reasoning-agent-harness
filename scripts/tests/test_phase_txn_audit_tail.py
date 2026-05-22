#!/usr/bin/env python3
"""Tests for _audit_tail_partial_write predicate (02d Group β fix β-2).

B2-Fix-1 (Cycle-1): predicate is now verb-gated — missing {entry_hash, txn_id,
after_sha256} is only a partial-write for TXN verbs (those emitted via
commit_transaction). Non-txn verbs (ci.oidc.jti.consumed, lock.recovered, etc.)
legitimately omit those fields.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import phase_txn  # noqa: E402  (path injection above)

# Access the private helper via module attribute.
_audit_tail_partial_write = phase_txn._audit_tail_partial_write


class TestAuditTailPartialWrite(unittest.TestCase):

    def _write_audit(self, tmpdir: str, content: str) -> Path:
        p = Path(tmpdir) / "audit.log"
        p.write_text(content, encoding="utf-8")
        return p

    # --- well-formed txn row → not partial -----------------------------------

    def test_full_well_formed_txn_row_not_partial(self) -> None:
        entry = {
            "entry_hash": "abc123",
            "txn_id": "txn-001",
            "after_sha256": "deadbeef",
            "verb": "phase.approve",
            "at": "2026-01-01T00:00:00Z",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            audit = self._write_audit(tmpdir, json.dumps(entry) + "\n")
            self.assertFalse(_audit_tail_partial_write(audit))

    # --- txn verb missing entry_hash → partial --------------------------------

    def test_txn_verb_missing_entry_hash_is_partial(self) -> None:
        entry = {
            "txn_id": "txn-002",
            "after_sha256": "deadbeef",
            "verb": "phase.approve",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            audit = self._write_audit(tmpdir, json.dumps(entry) + "\n")
            self.assertTrue(_audit_tail_partial_write(audit))

    # --- txn verb missing txn_id → partial ------------------------------------

    def test_txn_verb_missing_txn_id_is_partial(self) -> None:
        entry = {
            "entry_hash": "abc123",
            "after_sha256": "deadbeef",
            "verb": "phase.approve",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            audit = self._write_audit(tmpdir, json.dumps(entry) + "\n")
            self.assertTrue(_audit_tail_partial_write(audit))

    # --- txn verb missing after_sha256 → partial -----------------------------

    def test_txn_verb_missing_after_sha256_is_partial(self) -> None:
        entry = {
            "entry_hash": "abc123",
            "txn_id": "txn-003",
            "verb": "phase.approve",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            audit = self._write_audit(tmpdir, json.dumps(entry) + "\n")
            self.assertTrue(_audit_tail_partial_write(audit))

    # --- non-txn verb missing entry_hash → NOT partial (B2-Fix-1) -----------

    def test_non_txn_jti_consumed_not_partial(self) -> None:
        """ci.oidc.jti.consumed has no entry_hash — must NOT be flagged as partial."""
        entry = {
            "verb": "ci.oidc.jti.consumed",
            "jti": "some-jti-value",
            "at": "2026-01-01T00:00:00Z",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            audit = self._write_audit(tmpdir, json.dumps(entry) + "\n")
            self.assertFalse(_audit_tail_partial_write(audit))

    def test_non_txn_lock_recovered_not_partial(self) -> None:
        """lock.recovered has no entry_hash — must NOT be flagged as partial."""
        entry = {
            "verb": "lock.recovered",
            "at": "2026-01-01T00:00:00Z",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            audit = self._write_audit(tmpdir, json.dumps(entry) + "\n")
            self.assertFalse(_audit_tail_partial_write(audit))

    def test_non_txn_approve_nonce_mint_not_partial(self) -> None:
        """approve_nonce.mint has no entry_hash — must NOT be flagged as partial."""
        entry = {
            "verb": "approve_nonce.mint",
            "nonce_id": "abc",
            "at": "2026-01-01T00:00:00Z",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            audit = self._write_audit(tmpdir, json.dumps(entry) + "\n")
            self.assertFalse(_audit_tail_partial_write(audit))

    # --- txn verbs: all entries in _TXN_VERBS should be flagged when missing fields

    def test_autopilot_start_txn_verb_missing_fields_is_partial(self) -> None:
        """phase.autopilot.start is a txn verb — missing fields → partial."""
        entry = {
            "verb": "phase.autopilot.start",
            "at": "2026-01-01T00:00:00Z",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            audit = self._write_audit(tmpdir, json.dumps(entry) + "\n")
            self.assertTrue(_audit_tail_partial_write(audit))

    def test_phase_reopen_txn_verb_missing_fields_is_partial(self) -> None:
        """phase.reopen is a txn verb — missing fields → partial."""
        entry = {
            "verb": "phase.reopen",
            "at": "2026-01-01T00:00:00Z",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            audit = self._write_audit(tmpdir, json.dumps(entry) + "\n")
            self.assertTrue(_audit_tail_partial_write(audit))

    # --- C-5: backward scan finds txn row hidden behind non-txn rows ----------

    def test_partial_txn_followed_by_non_txn_is_partial(self) -> None:
        """C-5: tail is [partial_txn_row, jti_consumed_row] → predicate returns True."""
        partial_txn = {
            "verb": "phase.approve",
            "at": "2026-01-01T00:00:00Z",
            # Missing entry_hash, txn_id, after_sha256 → partial
        }
        non_txn = {
            "verb": "ci.oidc.jti.consumed",
            "jti": "some-jti",
            "at": "2026-01-01T00:00:01Z",
        }
        content = json.dumps(partial_txn) + "\n" + json.dumps(non_txn) + "\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            audit = self._write_audit(tmpdir, content)
            self.assertTrue(_audit_tail_partial_write(audit),
                            "Partial txn row hidden behind non-txn should be detected")

    def test_full_txn_followed_by_non_txn_not_partial(self) -> None:
        """C-5: tail is [full_txn_row, jti_consumed_row] → predicate returns False."""
        full_txn = {
            "verb": "phase.approve",
            "entry_hash": "abc123",
            "txn_id": "txn-001",
            "after_sha256": "deadbeef",
            "at": "2026-01-01T00:00:00Z",
        }
        non_txn = {
            "verb": "ci.oidc.jti.consumed",
            "jti": "some-jti",
            "at": "2026-01-01T00:00:01Z",
        }
        content = json.dumps(full_txn) + "\n" + json.dumps(non_txn) + "\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            audit = self._write_audit(tmpdir, content)
            self.assertFalse(_audit_tail_partial_write(audit),
                             "Full txn row hidden behind non-txn should not be flagged")

    def test_no_txn_rows_in_tail_not_partial(self) -> None:
        """C-5: only non-txn rows in tail → no partial write."""
        non_txn1 = {"verb": "ci.oidc.jti.consumed", "jti": "j1"}
        non_txn2 = {"verb": "lock.recovered", "at": "2026-01-01T00:00:00Z"}
        content = json.dumps(non_txn1) + "\n" + json.dumps(non_txn2) + "\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            audit = self._write_audit(tmpdir, content)
            self.assertFalse(_audit_tail_partial_write(audit))

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
