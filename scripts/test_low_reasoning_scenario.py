"""Unit tests for the 02b-10 low-reasoning scenario harness.

Plan: .planning/phases/02b-hardening/plans/02b-10-PHASE-E-HARNESS-PLAN.md §5.
Contract pin: .planning/phases/02b-hardening/CONTRACT-PIN.md §3 (flat tests).

All tests run without an API key (FakeClient mocks the model). One opt-in
live smoke test runs only when `ANTHROPIC_API_KEY` is exported AND
`HARNESS_E2E_LIVE=1` is set.
"""
from __future__ import annotations

import filecmp
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.smoke.fake_client import FakeClient, ModelResponse
from scripts.smoke import judge as judge_mod
from scripts.smoke.judge import (
    JudgeResult,
    judge_fixture_01,
    judge_fixture_02,
    judge_fixture_03,
    judge_fixture_04,
)
from scripts.smoke.prepare_scratch import (
    prepare_scratch_dir,
    load_fixture,
    load_all_fixtures,
)
from scripts.smoke import runner as runner_mod
from scripts.smoke.runner import (
    run_trial,
    TrialRecord,
    WALL_CLOCK_CAP_SECONDS,
    INPUT_TOKEN_CAP,
    OUTPUT_TOKEN_CAP,
    PINNED_MODEL,
)
from scripts.smoke.aggregator import (
    aggregate_evidence,
    write_summary,
    Summary,
    FlowSummary,
    PASS_THRESHOLD,
)

FIXTURES_DIR = _REPO_ROOT / "scripts" / "smoke" / "fixtures"


def _write_state(dest: Path, payload: dict) -> None:
    (dest / ".scratch").mkdir(parents=True, exist_ok=True)
    (dest / ".harness").mkdir(parents=True, exist_ok=True)
    (dest / ".scratch" / "phase-state.json").write_text(
        json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8"
    )


def _write_audit(dest: Path, entries: list[dict]) -> None:
    (dest / ".harness").mkdir(parents=True, exist_ok=True)
    log = dest / ".harness" / "audit.log"
    log.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


def _load(name: str) -> dict:
    return load_fixture(FIXTURES_DIR / name)


FX01 = "fixture-01-discuss-then-plan.json"
FX02 = "fixture-02-plan-then-approve.json"
FX03 = "fixture-03-execute-then-done.json"
FX04 = "fixture-04-full-lifecycle.json"


class JudgeFixture01Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = _load(FX01)
        self.tmp = Path(tempfile.mkdtemp(prefix="judge01."))

    def test_passes_when_phase_advanced_to_plan(self) -> None:
        _write_state(self.tmp, {"phase": "plan", "state_schema_version": 2})
        result = judge_fixture_01(self.tmp, self.fixture, response_text="ok")
        self.assertTrue(result.passed, result.reason)

    def test_fails_when_phase_unchanged(self) -> None:
        _write_state(self.tmp, {"phase": "discuss", "state_schema_version": 2})
        result = judge_fixture_01(self.tmp, self.fixture, response_text="ok")
        self.assertFalse(result.passed)
        self.assertIn("phase set plan", result.reason)

    def test_fails_when_phase_overshoots_to_execute(self) -> None:
        _write_state(self.tmp, {"phase": "execute", "state_schema_version": 2})
        result = judge_fixture_01(self.tmp, self.fixture, response_text="ok")
        self.assertFalse(result.passed)
        self.assertIn("overshot", result.reason)

    def test_passes_on_needs_info_response(self) -> None:
        # No state file needed; grounded needs-info short-circuits to pass.
        result = judge_fixture_01(
            self.tmp,
            self.fixture,
            response_text="needs-info: please clarify which approach in the discuss phase",
        )
        self.assertTrue(result.passed, result.reason)

    def test_fails_on_ungrounded_needs_info(self) -> None:
        result = judge_fixture_01(
            self.tmp,
            self.fixture,
            response_text="needs-info: what is the weather today",
        )
        self.assertFalse(result.passed)
        self.assertIn("grounded", result.reason)


class JudgeFixture02Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = _load(FX02)
        self.tmp = Path(tempfile.mkdtemp(prefix="judge02."))

    def test_passes_when_plan_populated_and_approved(self) -> None:
        _write_state(
            self.tmp,
            {
                "phase": "plan",
                "approved": True,
                "approved_by": "agent@example.com",
                "plan_id": "plan-007",
                "summary": "ok",
                "state_schema_version": 2,
            },
        )
        result = judge_fixture_02(self.tmp, self.fixture, response_text="")
        self.assertTrue(result.passed, result.reason)

    def test_fails_when_approved_without_plan_population(self) -> None:
        _write_state(
            self.tmp,
            {
                "phase": "plan",
                "approved": True,
                "approved_by": "agent",
                "plan_id": None,
                "state_schema_version": 2,
            },
        )
        result = judge_fixture_02(self.tmp, self.fixture, response_text="")
        self.assertFalse(result.passed)
        self.assertIn("fabricated approval", result.reason)


class JudgeFixture03Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = _load(FX03)
        self.tmp = Path(tempfile.mkdtemp(prefix="judge03."))

    def test_passes_when_verification_entries_use_allowlist(self) -> None:
        _write_state(
            self.tmp,
            {
                "phase": "done",
                "verification": ["pytest scripts/", "harness check"],
                "state_schema_version": 2,
            },
        )
        _write_audit(
            self.tmp,
            [{"verb": "phase.set", "args": {"phase": "done"}}],
        )
        result = judge_fixture_03(self.tmp, self.fixture, response_text="")
        self.assertTrue(result.passed, result.reason)

    def test_fails_when_verification_uses_bash(self) -> None:
        _write_state(
            self.tmp,
            {
                "phase": "done",
                "verification": ["bash scripts/foo.sh"],
                "state_schema_version": 2,
            },
        )
        _write_audit(self.tmp, [{"verb": "phase.set", "args": {"phase": "done"}}])
        result = judge_fixture_03(self.tmp, self.fixture, response_text="")
        self.assertFalse(result.passed)
        self.assertIn("bash", result.reason)

    def test_fails_when_phase_done_without_verification(self) -> None:
        _write_state(
            self.tmp,
            {"phase": "done", "verification": [], "state_schema_version": 2},
        )
        _write_audit(self.tmp, [{"verb": "phase.set", "args": {"phase": "done"}}])
        result = judge_fixture_03(self.tmp, self.fixture, response_text="")
        self.assertFalse(result.passed)
        self.assertIn("empty verification", result.reason)


class JudgeFixture04Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = _load(FX04)
        self.tmp = Path(tempfile.mkdtemp(prefix="judge04."))

    def test_passes_on_full_lifecycle_trace(self) -> None:
        _write_state(
            self.tmp,
            {
                "phase": "done",
                "verification": ["pytest scripts/", "harness check"],
                "state_schema_version": 2,
            },
        )
        _write_audit(
            self.tmp,
            [
                {"verb": "phase.set", "args": {"phase": "plan"}},
                {"verb": "phase.approve", "args": {"by": "agent"}},
                {"verb": "phase.set", "args": {"phase": "execute"}},
                {"verb": "phase.approve", "args": {"by": "agent"}},
                {"verb": "phase.set", "args": {"phase": "done"}},
            ],
        )
        result = judge_fixture_04(self.tmp, self.fixture, response_text="")
        self.assertTrue(result.passed, result.reason)

    def test_fails_when_lifecycle_skips_approval(self) -> None:
        _write_state(
            self.tmp,
            {"phase": "done", "state_schema_version": 2},
        )
        _write_audit(
            self.tmp,
            [
                {"verb": "phase.set", "args": {"phase": "plan"}},
                {"verb": "phase.set", "args": {"phase": "execute"}},
                {"verb": "phase.set", "args": {"phase": "done"}},
            ],
        )
        result = judge_fixture_04(self.tmp, self.fixture, response_text="")
        self.assertFalse(result.passed)
        # Either the missing phase.approve entry or the gated-transition
        # check fires; both indicate the approval gate was skipped.
        self.assertTrue(
            "approval" in result.reason.lower() or "approve" in result.reason.lower(),
            result.reason,
        )

    def test_fails_when_orphan_lockfile_remains(self) -> None:
        _write_state(
            self.tmp,
            {
                "phase": "done",
                "verification": ["pytest scripts/", "harness check"],
                "state_schema_version": 2,
            },
        )
        _write_audit(
            self.tmp,
            [
                {"verb": "phase.set", "args": {"phase": "plan"}},
                {"verb": "phase.approve", "args": {"by": "agent"}},
                {"verb": "phase.set", "args": {"phase": "execute"}},
                {"verb": "phase.approve", "args": {"by": "agent"}},
                {"verb": "phase.set", "args": {"phase": "done"}},
            ],
        )
        # plant orphan lockfile
        (self.tmp / ".harness" / "session.lock").write_text("stale\n")
        result = judge_fixture_04(self.tmp, self.fixture, response_text="")
        self.assertFalse(result.passed)
        self.assertIn("orphan", result.reason)


class JudgeMetaTests(unittest.TestCase):
    """Meta-tests per plan §5.1 tests 14-15."""

    def test_judge_imports_constants_not_literals(self) -> None:
        src = Path(judge_mod.__file__).read_text(encoding="utf-8")
        # No `sys.exit(<digit>)` or bare `return <digit>` style literal exit codes.
        import re

        offenders = re.findall(r"sys\.exit\(\s*[0-9]+\s*\)", src)
        self.assertEqual(offenders, [], f"judge.py uses raw exit literals: {offenders}")

    def test_judge_uses_state_diagnostics_for_parsing(self) -> None:
        src = Path(judge_mod.__file__).read_text(encoding="utf-8")
        # No direct json.loads on phase-state.json paths.
        self.assertNotIn(
            "json.loads(open",
            src,
            "judge.py must route state reads through load_state_json, not raw json.loads",
        )
        # Confirm load_state_json is the chosen reader.
        self.assertIn("load_state_json", src)


# ---------------------------------------------------------------------------
# Runner tests
# ---------------------------------------------------------------------------


class RunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = _load(FX01)
        self.tmp = Path(tempfile.mkdtemp(prefix="runner."))
        self.scratch = self.tmp / "scratch"
        self.evidence = self.tmp / "evidence"

    def _client(self, responses: list[str], **kwargs) -> FakeClient:
        return FakeClient(scripted_responses=responses, **kwargs)

    def test_runner_records_per_trial_evidence_json(self) -> None:
        # Phase-set command that should drive judge to pass.
        client = self._client(["harness phase set plan"])
        record = run_trial(self.fixture, 1, client, self.scratch, self.evidence)
        path = self.evidence / "discuss-to-plan" / "trial-001.json"
        self.assertTrue(path.exists())
        data = json.loads(path.read_text())
        for key in (
            "fixture_id",
            "trial_index",
            "model",
            "prompt",
            "response",
            "judgment",
            "retry_count",
            "wall_clock_seconds",
            "input_tokens",
            "output_tokens",
            "budget_caps_hit",
            "noisy",
            "commands_executed",
            "passed",
        ):
            self.assertIn(key, data, f"missing key {key}")
        self.assertEqual(data["model"], PINNED_MODEL)

    def test_runner_enforces_wall_clock_cap(self) -> None:
        client = self._client(
            ["harness phase set plan"],
            scripted_wall_seconds=[WALL_CLOCK_CAP_SECONDS + 5.0],
        )
        record = run_trial(self.fixture, 2, client, self.scratch, self.evidence)
        self.assertFalse(record.passed)
        self.assertIn("wall_clock", record.budget_caps_hit)
        self.assertEqual(record.retry_count, 0)

    def test_runner_enforces_input_token_cap(self) -> None:
        client = self._client(
            ["harness phase set plan"],
            scripted_token_counts=[(INPUT_TOKEN_CAP + 1, 100)],
        )
        record = run_trial(self.fixture, 3, client, self.scratch, self.evidence)
        self.assertFalse(record.passed)
        self.assertIn("input_tokens", record.budget_caps_hit)

    def test_runner_enforces_output_token_cap(self) -> None:
        client = self._client(
            ["harness phase set plan"],
            scripted_token_counts=[(100, OUTPUT_TOKEN_CAP + 1)],
        )
        record = run_trial(self.fixture, 4, client, self.scratch, self.evidence)
        self.assertFalse(record.passed)
        self.assertIn("output_tokens", record.budget_caps_hit)

    def test_runner_retries_up_to_2_on_judge_fail(self) -> None:
        # First two responses are no-ops (phase stays discuss); third moves to plan.
        client = self._client(
            [
                "# nothing",
                "# still nothing",
                "harness phase set plan",
            ]
        )
        record = run_trial(self.fixture, 5, client, self.scratch, self.evidence)
        self.assertTrue(record.passed)
        self.assertEqual(record.retry_count, 2)
        self.assertTrue(record.noisy)

    def test_runner_does_not_retry_after_2_failures(self) -> None:
        client = self._client(["# nope", "# nope", "# nope"])
        record = run_trial(self.fixture, 6, client, self.scratch, self.evidence)
        self.assertFalse(record.passed)
        self.assertEqual(record.retry_count, 2)
        self.assertTrue(record.noisy)
        # client was called 3 times (orig + 2 retries)
        self.assertEqual(len(client.calls), 3)

    def test_runner_does_not_retry_on_budget_cap_failure(self) -> None:
        client = self._client(
            ["harness phase set plan"],
            scripted_token_counts=[(100, OUTPUT_TOKEN_CAP + 1)],
        )
        record = run_trial(self.fixture, 7, client, self.scratch, self.evidence)
        self.assertEqual(record.retry_count, 0)

    def test_runner_uses_temperature_zero(self) -> None:
        client = self._client(["harness phase set plan"])
        run_trial(self.fixture, 8, client, self.scratch, self.evidence)
        self.assertEqual(client.last_call["temperature"], 0.0)
        for call in client.calls:
            self.assertEqual(call["temperature"], 0.0)

    def test_runner_uses_pinned_model_id(self) -> None:
        client = self._client(["harness phase set plan"])
        run_trial(self.fixture, 9, client, self.scratch, self.evidence)
        self.assertEqual(client.last_call["model"], PINNED_MODEL)

    def test_runner_deterministic_fixtures_byte_identical_per_trial(self) -> None:
        a = self.tmp / "scratch-a" / "trial-A"
        b = self.tmp / "scratch-b" / "trial-B"
        prepare_scratch_dir(self.fixture, a)
        prepare_scratch_dir(self.fixture, b)
        sa = (a / ".scratch" / "phase-state.json").read_bytes()
        sb = (b / ".scratch" / "phase-state.json").read_bytes()
        self.assertEqual(hashlib.sha256(sa).hexdigest(), hashlib.sha256(sb).hexdigest())
        cmp = filecmp.dircmp(a, b)
        self.assertEqual(cmp.left_only, [])
        self.assertEqual(cmp.right_only, [])
        self.assertEqual(cmp.diff_files, [])


class AggregatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="agg."))

    def _write_trials(self, flow: str, results: list[tuple[bool, bool]]) -> None:
        """results: list of (passed, noisy)."""
        flow_dir = self.tmp / flow
        flow_dir.mkdir(parents=True, exist_ok=True)
        for i, (passed, noisy) in enumerate(results, start=1):
            (flow_dir / f"trial-{i:03d}.json").write_text(
                json.dumps(
                    {
                        "fixture_id": "fx",
                        "trial_index": i,
                        "passed": passed,
                        "noisy": noisy,
                        "judgment": {"passed": passed, "reason": "x"},
                    }
                )
            )

    def test_aggregator_computes_per_flow_pass_rate(self) -> None:
        self._write_trials("discuss-to-plan", [(True, False)] * 42 + [(False, False)] * 8)
        summary = aggregate_evidence(self.tmp)
        flow = summary.flows[0]
        self.assertEqual(flow.passed, 42)
        self.assertEqual(flow.total, 50)
        self.assertAlmostEqual(flow.pass_rate, 0.84, places=2)
        self.assertTrue(flow.gate_passed)

    def test_aggregator_marks_flow_failed_below_threshold(self) -> None:
        self._write_trials("discuss-to-plan", [(True, False)] * 39 + [(False, False)] * 11)
        summary = aggregate_evidence(self.tmp)
        self.assertFalse(summary.flows[0].gate_passed)
        self.assertEqual(summary.release_gate, "BLOCKED")

    def test_aggregator_records_noisy_trial_count(self) -> None:
        self._write_trials(
            "discuss-to-plan",
            [(True, True)] * 7 + [(True, False)] * 35 + [(False, False)] * 8,
        )
        summary = aggregate_evidence(self.tmp)
        self.assertEqual(summary.flows[0].noisy_count, 7)

    def test_aggregator_writes_summary_json_and_markdown(self) -> None:
        self._write_trials("discuss-to-plan", [(True, False)] * 50)
        summary = aggregate_evidence(self.tmp)
        json_path, md_path = write_summary(summary, self.tmp)
        self.assertTrue(json_path.exists())
        self.assertTrue(md_path.exists())
        md = md_path.read_text()
        self.assertIn("RELEASE GATE", md)

    def test_release_gate_passes_only_when_all_four_flows_pass(self) -> None:
        self._write_trials("discuss-to-plan", [(True, False)] * 50)
        self._write_trials("plan-to-approve", [(True, False)] * 50)
        self._write_trials("execute-to-done", [(True, False)] * 50)
        self._write_trials(
            "full-lifecycle", [(True, False)] * 30 + [(False, False)] * 20
        )
        summary = aggregate_evidence(self.tmp)
        self.assertEqual(summary.release_gate, "BLOCKED")
        self.assertIn("full-lifecycle", summary.blocking_flows)


class FixtureValidationTests(unittest.TestCase):
    def test_all_four_fixtures_load_and_have_required_keys(self) -> None:
        fixtures = load_all_fixtures(FIXTURES_DIR)
        self.assertEqual(len(fixtures), 4)
        ids = {f["fixture_id"] for f in fixtures}
        self.assertEqual(
            ids,
            {
                "fixture-01-discuss-then-plan",
                "fixture-02-plan-then-approve",
                "fixture-03-execute-then-done",
                "fixture-04-full-lifecycle",
            },
        )
        for fx in fixtures:
            for key in (
                "fixture_id",
                "flow",
                "initial_state",
                "prompt_template",
                "expected_target_phase",
                "diagnostic_keywords",
                "allowed_verbs",
            ):
                self.assertIn(key, fx)
            # initial_state must round-trip through json.dumps for prompt rendering.
            json.dumps(fx["initial_state"], sort_keys=True, indent=2)


# ---------------------------------------------------------------------------
# Optional live smoke (skipped unless both env vars set)
# ---------------------------------------------------------------------------


@unittest.skipUnless(
    os.environ.get("HARNESS_E2E_LIVE") == "1" and os.environ.get("ANTHROPIC_API_KEY"),
    "live smoke gated on HARNESS_E2E_LIVE=1 and ANTHROPIC_API_KEY",
)
class LiveSmokeTests(unittest.TestCase):
    def test_live_single_trial_smoke(self) -> None:
        from scripts.smoke.model_client import HaikuClient

        fixture = _load(FX01)
        client = HaikuClient()
        tmp = Path(tempfile.mkdtemp(prefix="live."))
        record = run_trial(fixture, 1, client, tmp / "scratch", tmp / "evidence")
        # Don't assert pass/fail; just that the pipeline produced a record.
        path = tmp / "evidence" / "discuss-to-plan" / "trial-001.json"
        self.assertTrue(path.exists())
        data = json.loads(path.read_text())
        self.assertEqual(data["model"], PINNED_MODEL)


if __name__ == "__main__":
    unittest.main()
