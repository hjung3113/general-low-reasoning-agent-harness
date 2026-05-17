#!/usr/bin/env python3
"""Tests for scripts/lib/transition.py — ADR-001 G2-B state machine table.

Owning plan: .planning/phases/02b-hardening/plans/02b-02-T0-1-PLAN.md Block B.
Contract pin: .planning/phases/02b-hardening/CONTRACT-PIN.md §1 (module name
singular: `transition.py`) and §3 (flat test path `scripts/test_*.py`).

Tests T-22..T-26 from the plan.
"""

from __future__ import annotations

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import transition  # noqa: E402


class TransitionMachineTests(unittest.TestCase):
    # ---------------- T-22: legal pairs accept ----------------
    def test_transition_table_legal_pairs_accept(self) -> None:
        legal_cases = [
            # (from, to, approved, reset_approval)
            (None, "discuss", False, False),
            ("discuss", "plan", False, False),
            ("plan", "execute", True, False),
            ("execute", "done", True, False),
            ("done", "discuss", False, True),
        ]
        for from_phase, to_phase, approved, reset in legal_cases:
            with self.subTest(from_phase=from_phase, to_phase=to_phase):
                # MUST NOT raise.
                transition.validate_transition(
                    from_phase, to_phase, approved=approved, reset_approval=reset
                )

    # ---------------- T-23: undefined pairs reject exit 2 ----------------
    def test_transition_table_undefined_pairs_reject_with_exit_2(self) -> None:
        # Deviation from plan T-23 list: the plan's example list included
        # ("done", "execute") as "clearly-undefined", but ADR-001 Decision §
        # "Transition state machine" explicitly marks ``done -> execute`` as
        # legal with ``(reset, --reset-approval)``. ADR is authoritative;
        # remove that pair and keep the truly-undefined ones.
        undefined_cases = [
            ("discuss", "execute"),
            ("discuss", "done"),
            ("plan", "done"),
        ]
        for from_phase, to_phase in undefined_cases:
            with self.subTest(from_phase=from_phase, to_phase=to_phase):
                with self.assertRaises(SystemExit) as ctx:
                    transition.validate_transition(
                        from_phase, to_phase, approved=True, reset_approval=True
                    )
                self.assertEqual(ctx.exception.code, 2)

    # ---------------- T-24: approval required pairs ----------------
    def test_transition_table_approval_required_pairs_reject_without_approved(self) -> None:
        for from_phase, to_phase in [("plan", "execute"), ("execute", "done")]:
            with self.subTest(from_phase=from_phase, to_phase=to_phase):
                with self.assertRaises(SystemExit) as ctx:
                    transition.validate_transition(
                        from_phase, to_phase, approved=False, reset_approval=False
                    )
                self.assertEqual(ctx.exception.code, 2)
                msg = str(ctx.exception)
                self.assertIn("harness phase approve", msg)

    # ---------------- T-25: backward/lateral requires reset_approval ----------------
    def test_transition_table_backward_lateral_requires_reset_approval(self) -> None:
        backward_lateral = [
            ("execute", "plan"),
            ("execute", "discuss"),
            ("plan", "discuss"),
            ("done", "discuss"),
        ]
        for from_phase, to_phase in backward_lateral:
            with self.subTest(from_phase=from_phase, to_phase=to_phase, reset=False):
                with self.assertRaises(SystemExit) as ctx:
                    transition.validate_transition(
                        from_phase, to_phase, approved=False, reset_approval=False
                    )
                self.assertEqual(ctx.exception.code, 2)
                self.assertIn("--reset-approval", str(ctx.exception))
            with self.subTest(from_phase=from_phase, to_phase=to_phase, reset=True):
                # With reset_approval=True it should accept.
                transition.validate_transition(
                    from_phase, to_phase, approved=False, reset_approval=True
                )

    # ---------------- T-26: self-loops rejected (except done->done re-stamp) ----------------
    def test_transition_table_self_loops_rejected(self) -> None:
        # Per ADR-001 transition table, discuss/plan/execute self-loops are
        # invalid; done->done is a re-stamp no-op and we treat it as legal.
        rejected_self = [
            ("discuss", "discuss"),
            ("plan", "plan"),
            ("execute", "execute"),
        ]
        for from_phase, to_phase in rejected_self:
            with self.subTest(from_phase=from_phase, to_phase=to_phase):
                with self.assertRaises(SystemExit) as ctx:
                    transition.validate_transition(
                        from_phase, to_phase, approved=True, reset_approval=False
                    )
                self.assertEqual(ctx.exception.code, 2)

    # ---------------- Table presence ----------------
    def test_transition_table_constant_present(self) -> None:
        self.assertTrue(hasattr(transition, "TRANSITION_TABLE"))
        self.assertIsInstance(transition.TRANSITION_TABLE, dict)


if __name__ == "__main__":
    unittest.main()
