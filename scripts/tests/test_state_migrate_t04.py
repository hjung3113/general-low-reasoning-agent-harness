#!/usr/bin/env python3
"""Tests for T0-4 verification -> review migrator (pure function).

Owning plan: .planning/phases/02b-hardening/plans/02b-05-T0-4-PLAN.md
Test list source: plan §"Test List" rows 31-38.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.state_migrate_t04 import migrate_verification_to_review

UTC_TIMESTAMP_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$"


class MigratorTests(unittest.TestCase):
    def test_migrator_preserves_python3_entry(self) -> None:
        state = {"verification": ["python3 ok"], "updated_at": "2026-05-15T00:00:00Z"}
        out = migrate_verification_to_review(state, migration_time="2026-05-16T00:00:00Z")
        self.assertEqual(out["verification"], ["python3 ok"])
        self.assertEqual(out["review"], [])

    def test_migrator_moves_confirm_to_review_with_actor_token(self) -> None:
        state = {
            "verification": ["Confirm work is good"],
            "updated_at": "2026-05-16T00:00:00Z",
        }
        out = migrate_verification_to_review(state, migration_time="2026-05-16T01:00:00Z")
        self.assertEqual(out["verification"], [])
        self.assertEqual(len(out["review"]), 1)
        entry = out["review"][0]
        self.assertEqual(entry["actor"], "Confirm")
        self.assertEqual(entry["at"], "2026-05-16T00:00:00Z")
        self.assertEqual(entry["evidence_path"], "")
        self.assertEqual(entry["summary"], "Confirm work is good")

    def test_migrator_moves_bash_to_review(self) -> None:
        state = {"verification": ["bash scripts/foo.sh"], "updated_at": "2026-05-16T00:00:00Z"}
        out = migrate_verification_to_review(state, migration_time="2026-05-16T01:00:00Z")
        self.assertEqual(out["verification"], [])
        self.assertEqual(out["review"][0]["actor"], "bash")
        self.assertEqual(out["review"][0]["summary"], "bash scripts/foo.sh")

    def test_migrator_moves_roo_to_review(self) -> None:
        state = {"verification": ["Roomba"], "updated_at": "2026-05-16T00:00:00Z"}
        out = migrate_verification_to_review(state, migration_time="2026-05-16T01:00:00Z")
        self.assertEqual(out["verification"], [])
        self.assertEqual(out["review"][0]["actor"], "Roomba")

    def test_migrator_mixed_entries_split_correctly(self) -> None:
        state = {
            "verification": [
                "python3 keeper1",
                "Confirm one",
                "bash two",
                "harness keeper2",
                "Validate three",
            ],
            "updated_at": "2026-05-16T00:00:00Z",
        }
        out = migrate_verification_to_review(state, migration_time="2026-05-16T01:00:00Z")
        self.assertEqual(out["verification"], ["python3 keeper1", "harness keeper2"])
        self.assertEqual(len(out["review"]), 3)
        actors = [r["actor"] for r in out["review"]]
        self.assertEqual(actors, ["Confirm", "bash", "Validate"])

    def test_migrator_idempotent_on_already_migrated_state(self) -> None:
        state = {
            "verification": ["python3 ok"],
            "review": [
                {
                    "actor": "user",
                    "at": "2026-05-16T00:00:00Z",
                    "evidence_path": "docs/x.md",
                    "summary": "ok",
                }
            ],
            "updated_at": "2026-05-16T00:00:00Z",
        }
        out1 = migrate_verification_to_review(state, migration_time="2026-05-16T01:00:00Z")
        out2 = migrate_verification_to_review(out1, migration_time="2026-05-16T02:00:00Z")
        self.assertEqual(out1, out2)

    def test_migrator_handles_missing_updated_at(self) -> None:
        import re

        state = {"verification": ["Confirm x"]}
        out = migrate_verification_to_review(state, migration_time="2026-05-16T01:02:03Z")
        self.assertEqual(out["review"][0]["at"], "2026-05-16T01:02:03Z")
        self.assertRegex(out["review"][0]["at"], UTC_TIMESTAMP_PATTERN)

    def test_migrate_uses_fallback_when_updated_at_malformed(self) -> None:
        # SecM5: migrator must validate state['updated_at'] against the
        # check.py UTC regex before adopting it for the moved review entry's
        # `at`. Otherwise an external author could smuggle an arbitrary
        # string through the migrator and downstream evidence consumers
        # would inherit a non-conformant timestamp.
        state = {
            "verification": ["Confirm x"],
            "updated_at": "not-a-timestamp",
        }
        out = migrate_verification_to_review(state, migration_time="2026-05-16T01:02:03Z")
        self.assertEqual(out["review"][0]["at"], "2026-05-16T01:02:03Z")
        self.assertRegex(out["review"][0]["at"], UTC_TIMESTAMP_PATTERN)

    def test_migrator_does_not_mutate_input(self) -> None:
        state = {"verification": ["Confirm x"], "updated_at": "2026-05-15T00:00:00Z"}
        migrate_verification_to_review(state, migration_time="2026-05-16T01:00:00Z")
        self.assertEqual(state["verification"], ["Confirm x"])
        self.assertNotIn("review", state)


if __name__ == "__main__":
    unittest.main()
