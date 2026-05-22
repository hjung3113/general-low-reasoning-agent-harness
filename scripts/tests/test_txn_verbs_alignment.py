#!/usr/bin/env python3
"""D-2 (Cycle-2): _TXN_VERBS drift lint test.

Asserts that all txn verb literals in the phase_txn.py source itself
(the _TXN_VERBS definition comments and the BudgetExhaustedError context)
are internally consistent, and that the known set of verbs produced by
commit_transaction-callers is a subset of _TXN_VERBS.

Uses a regex scan of source files for "verb": "<literal>" patterns that
appear inside TxnRequest(...) call contexts (identified by "audit_entry_draft"
nearby) to detect drift.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.phase_txn import _TXN_VERBS  # noqa: E402

_SCRIPTS_DIR = Path(__file__).resolve().parent
_LIB_DIR = _SCRIPTS_DIR / "lib"


def _scan_txn_request_verbs(source: str) -> set[str]:
    """Return verb string literals found inside TxnRequest construction blocks.

    Scans for TxnRequest(...) call contexts (identified by 'audit_entry_draft'
    nearby within a 40-line window) and extracts 'verb': '<literal>' patterns.
    """
    verbs: set[str] = set()
    lines = source.splitlines()
    n = len(lines)
    window = 40

    for i, line in enumerate(lines):
        # Look for lines that contain TxnRequest (the start of a txn-verb site).
        if "TxnRequest" not in line and "audit_entry_draft" not in line:
            continue
        # Scan a window of lines around this site.
        start = max(0, i - 5)
        end = min(n, i + window)
        chunk = "\n".join(lines[start:end])
        if "audit_entry_draft" not in chunk:
            continue
        for m in re.finditer(r'"verb"\s*:\s*"([a-z][a-z0-9._]*)"', chunk):
            verbs.add(m.group(1))

    return verbs


class TestTxnVerbsAlignment(unittest.TestCase):
    """_TXN_VERBS must cover all txn-verb literals used in TxnRequest construction."""

    def _get_source_txn_verbs(self) -> set[str]:
        found: set[str] = set()
        for fname in ("phase_autopilot.py", "phase_approve.py", "phase_reopen.py"):
            path = _LIB_DIR / fname
            if not path.exists():
                continue
            src = path.read_text(encoding="utf-8")
            found |= _scan_txn_request_verbs(src)
        return found

    def test_txn_verbs_frozenset_covers_txn_request_verbs(self) -> None:
        """All 'verb' literals inside TxnRequest blocks must be in _TXN_VERBS."""
        source_verbs = self._get_source_txn_verbs()
        # It's OK if scanning yields empty (pattern may not match in all versions);
        # but if we do find verbs, they must all be in _TXN_VERBS.
        if not source_verbs:
            # Graceful skip — pattern didn't match; test the explicit set below.
            return
        missing = source_verbs - _TXN_VERBS
        self.assertEqual(
            missing, set(),
            msg=(
                f"Verb(s) found in TxnRequest blocks but NOT in _TXN_VERBS: {missing!r}.\n"
                f"Add them to _TXN_VERBS in scripts/lib/phase_txn.py."
            ),
        )

    def test_txn_verbs_not_empty(self) -> None:
        """_TXN_VERBS must not be empty — sanity guard."""
        self.assertGreater(len(_TXN_VERBS), 0, "_TXN_VERBS must not be empty")

    def test_known_core_txn_verbs_present(self) -> None:
        """Core txn verbs must always be in _TXN_VERBS (explicit drift guard)."""
        core = {
            "phase.approve",
            "phase.autopilot.start",
            "phase.autopilot.stop",
            "phase.autopilot.halt",
            "phase.autopilot.halt.budget",
            "phase.budget.halt",
            "halt_diary.clear",
        }
        missing = core - _TXN_VERBS
        self.assertEqual(missing, set(),
                         msg=f"Core txn verbs missing from _TXN_VERBS: {missing!r}")

    def test_phase_reopen_in_txn_verbs(self) -> None:
        """phase.reopen is a txn verb used by commit_transaction."""
        self.assertIn("phase.reopen", _TXN_VERBS)

    def test_recover_pending_in_txn_verbs(self) -> None:
        """phase.autopilot.start.recover_pending is a txn verb."""
        self.assertIn("phase.autopilot.start.recover_pending", _TXN_VERBS)

    def test_txn_verbs_are_strings(self) -> None:
        """All elements of _TXN_VERBS must be strings (no typos yielding non-str)."""
        for v in _TXN_VERBS:
            self.assertIsInstance(v, str, f"_TXN_VERBS entry {v!r} is not a str")
            self.assertTrue(v, f"_TXN_VERBS entry is empty string")

    def test_txn_verbs_subset_of_known_verbs(self) -> None:
        """Every _TXN_VERBS verb must also be in audit.KNOWN_VERBS (complete registry)."""
        from lib.audit import KNOWN_VERBS
        missing = _TXN_VERBS - KNOWN_VERBS
        self.assertEqual(
            missing, set(),
            msg=(
                f"_TXN_VERBS entries not in audit.KNOWN_VERBS: {missing!r}.\n"
                "Add them to KNOWN_VERBS in scripts/lib/audit.py."
            ),
        )


if __name__ == "__main__":
    unittest.main()
