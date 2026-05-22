#!/usr/bin/env python3
"""Unit tests for Phase E Tier-2 multi-step scenario driver.

Drives the scenario loop with scripted responses (no real subagent) to
confirm:
- ENV_CONTEXTS templates are well-formed and present for all 3 envs
- A clean response sequence advances discuss → plan → execute → done
- An out-of-order response leaves the harness state machine intact
  (harness rejects the bad verb; subsequent good verbs still work)
- needs-info responses do not corrupt state
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from smoke.multi_step_scenario import (
    ENV_CONTEXTS, Scenario, init_target, step,
)


class EnvContextsTests(unittest.TestCase):
    def test_three_envs_present(self) -> None:
        self.assertEqual(
            set(ENV_CONTEXTS),
            {"claude-code", "opencode-emulated", "roo-emulated"},
        )

    def test_env_contexts_are_non_trivial(self) -> None:
        for label, text in ENV_CONTEXTS.items():
            self.assertGreater(len(text), 40, f"{label} context too short")


class DriverLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="tier2-test."))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _scenario(self, env_label: str = "claude-code",
                  adapters: str = "none") -> Scenario:
        sc = Scenario(
            name="t", env_label=env_label, adapters=adapters,
            target_dir=self.tmp / "target",
            goal="Drive discuss -> done. Use plan_id 't-plan'. Approve as t@e.",
        )
        init_target(sc)
        return sc

    def test_clean_sequence_reaches_done(self) -> None:
        sc = self._scenario()
        steps = [
            "python3 scripts/harness.py phase set plan --plan-id t-plan\n"
            "python3 scripts/harness.py phase approve --by t@e",
            "python3 scripts/harness.py phase set execute",
            "python3 scripts/harness.py phase approve --by t@e\n"
            "python3 scripts/harness.py phase set done",
        ]
        for resp in steps:
            step(sc, resp)
        final = sc.read_state()
        self.assertEqual(final["phase"], "done")
        self.assertEqual(final["plan_id"], "t-plan")
        self.assertTrue(sc.is_done())

    def test_out_of_order_approve_in_discuss_rejected(self) -> None:
        sc = self._scenario(env_label="opencode-emulated", adapters="opencode")
        # First: model wrongly issues approve before set plan. Harness must
        # reject the approve verb (ADR-001 forbids approve in discuss/done),
        # then set plan succeeds and advances state.
        result = step(
            sc,
            "python3 scripts/harness.py phase approve --by t@e\n"
            "python3 scripts/harness.py phase set plan --plan-id t-plan",
        )
        self.assertEqual(len(result.executed_commands), 2)
        approve_rc = result.command_outputs[0]["returncode"]
        set_plan_rc = result.command_outputs[1]["returncode"]
        self.assertNotEqual(approve_rc, 0,
                            "approve in discuss must error (non-zero exit)")
        self.assertEqual(set_plan_rc, 0,
                         "set plan after rejected approve must still succeed")
        state = sc.read_state()
        self.assertEqual(state["phase"], "plan")
        self.assertEqual(state["plan_id"], "t-plan")
        self.assertFalse(state["approved"])

    def test_needs_info_response_does_not_corrupt_state(self) -> None:
        sc = self._scenario()
        before = sc.read_state()
        result = step(
            sc,
            "needs-info: Please clarify whether to hydrate planning first.",
        )
        self.assertIsNotNone(result.error)
        self.assertEqual(result.executed_commands, [])
        after = sc.read_state()
        # Phase, plan_id, approved unchanged; only timestamps may differ
        # (they shouldn't here since no commands executed).
        self.assertEqual(after["phase"], before["phase"])
        self.assertEqual(after["plan_id"], before["plan_id"])
        self.assertEqual(after["approved"], before["approved"])

    def test_three_envs_all_reach_done_with_clean_responses(self) -> None:
        # Use scripted responses tailored per env framing but identical
        # workflow semantics. Verifies driver is env-agnostic for the
        # state machine itself.
        for env_label, adapters in (
            ("claude-code", "none"),
            ("opencode-emulated", "opencode"),
            ("roo-emulated", "roo"),
        ):
            with self.subTest(env=env_label):
                sc = Scenario(
                    name=f"t-{env_label}", env_label=env_label,
                    adapters=adapters, target_dir=self.tmp / env_label,
                    goal="Drive discuss to done.",
                )
                init_target(sc)
                step(sc, "python3 scripts/harness.py phase set plan --plan-id p\n"
                         "python3 scripts/harness.py phase approve --by t@e")
                step(sc, "python3 scripts/harness.py phase set execute")
                step(sc, "python3 scripts/harness.py phase approve --by t@e\n"
                         "python3 scripts/harness.py phase set done")
                self.assertTrue(sc.is_done(), f"{env_label} did not reach done")


if __name__ == "__main__":
    import sys
    # Make scripts/smoke importable when run directly.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    unittest.main()
