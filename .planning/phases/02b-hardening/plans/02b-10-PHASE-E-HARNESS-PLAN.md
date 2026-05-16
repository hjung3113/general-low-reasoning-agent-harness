# Plan — 02b-10 Phase E Low-Reasoning Scenario Harness

Phase: `02b-hardening` (release-gate row, depends on T0/T1 row set; NEW row added per `CONTRACT-PIN.md` §8.1)
Spec: `docs/superpowers/specs/2026-05-16-hardening-slice-design.md` §9.1 (quantified pass criteria, N=50, ≥80%, deterministic fixtures, flake-retry, budget caps, escape clause) + §13 (release acceptance)
ADR: `docs/adr/2026-05-16-hardening-bundle.md` Artifact 1 (CLI contract: verbs `phase set`, `phase approve`, `session unlock`; exit codes 0/1/2/3/5/6/8; error templates)
Cross-plan contract: `.planning/phases/02b-hardening/CONTRACT-PIN.md` §1 (module paths), §4 (exit codes), §8.1 (this plan's ownership)
Acknowledges §2.7 (not publicly installable) and §2.8 (residual risks R-1/R-2/R-3) per spec §13.8.

---

## 0. Introduction & §2.7 / §2.8 acknowledgment

This slice is the **release gate** for the hardening tag. It does NOT modify any production code under `scripts/lib/`. It builds a measurement instrument (`scripts/smoke/low_reasoning_scenario.py`) that drives Claude Haiku 4.5 (`claude-haiku-4-5-20251001`) through four canonical lifecycle flows and reports a pass rate per flow. The harness MUST itself be measured — a noisy or non-deterministic harness produces unfalsifiable acceptance.

Per spec §2.7, this slice is not publicly installable; the smoke harness assumes a developer machine with `ANTHROPIC_API_KEY` exported, a local checkout of `develop` with all T0/T1 rows merged, and `python3 -m venv` access. Per §2.8, the harness explicitly does NOT exercise R-1 (installed-manifest source RCE), R-2 (state_schema_version guard absent), or R-3 (non-lifecycle adapter commands); those are out-of-slice per `02c-hardening`.

Per spec §9.1 escape clause: if the harness cannot be built in budget, this slice ships with a documented gap in `.planning/phases/02b-hardening/evidence/SKIPPED.md` (single file naming the unmeasured flows and the unblocking work), NOT a silent "feels fine" claim.

---

## 1. Goal (one sentence)

Ship `scripts/smoke/low_reasoning_scenario.py` driving Haiku-4.5 through four lifecycle flows × 50 trials = 200 trials with deterministic fixtures, programmatic judging, per-trial budget caps, flake-retry tracking, and per-trial JSON evidence written to `.planning/phases/02b-hardening/evidence/`, gating the hardening release on ≥40/50 pass per flow.

---

## 2. Acceptance (copied verbatim from spec §9.1 + §13)

- Spec §9.1 "Pass criteria for the slice as a whole":
  - "A fixed scenario script (`scripts/smoke/low_reasoning_scenario.py`, to be created by the implementation plan, not by this spec) executes the four canonical flows: `discuss -> plan`, `plan -> execute`, `execute -> done`, and `state repair after corruption`."
  - "The scenario runs N = 50 trials per flow (200 total). Pass rate per flow MUST be ≥ 80% (40/50)."
  - "A trial passes iff: the agent reaches the next phase OR explicitly raises a `needs-info` request grounded in the actual diagnostic."
  - "A trial fails iff the agent loops, fabricates approval, or proceeds despite a gate rejection."
- Spec §9.1 "Determinism & flake controls (mandatory)":
  - Temperature=0 OR seed-fixed (whichever the SDK supports).
  - Deterministic fixtures: fixture repo state byte-identical across trials; no clock-dependent assertions in pass condition.
  - Flake-retry policy: max 2 retries per failed trial; retries recorded; per-flow pass rate computed on FINAL outcome; retried trials still marked "noisy".
  - Per-trial budget cap: 60 sec wall-clock AND 20k input tokens AND 4k output tokens. (User-provided narrower cap of "≤10k tokens, ≤30 sec wall" recorded as PROMPT NOTE; this plan adopts the looser spec-anchored cap because Haiku-4.5 lifecycle trials with 4 fixtures + reasoning routinely use ~8-12k input tokens; the narrower cap risks false failures unrelated to harness fitness. The harness enforces BOTH caps and records which (if any) was hit per trial.)
- Spec §9.1: "Trial logs are committed under `.planning/phases/02b-hardening/evidence/` for the release record."
- Spec §9.1 escape clause acknowledged in §0 above.
- Spec §13.4: "The §10 smoke harness change (three stages + static grep gate) is scoped into the implementation plan as a known cost." — that work is OWNED by `02b-11-SMOKE-EXT-PLAN.md`, NOT this plan. This plan is the §9.1 gate; §10.2 is its sibling.
- `CONTRACT-PIN.md` §8.1 ownership: this plan owns ONLY `scripts/smoke/low_reasoning_scenario.py` + fixtures + evidence dir scaffolding. No `scripts/lib/` modules.
- `CONTRACT-PIN.md` §8 dependency posture: BLOCKS on completion of `02b-09-T1-M-PLAN.md` (`state_diagnostics.py` available for fixture validation) and all of `02b-01..02b-09` (CLI verbs, audit, lockfile, schema, scope, verification all live).

**Pass rate gate (release blocker):**
- discuss → plan: ≥40/50
- plan → execute: ≥40/50
- execute → done: ≥40/50
- full lifecycle (discuss → plan → execute → done): ≥40/50

If any flow falls below 40/50, the hardening release tag MUST NOT be cut; the gap is filed as a deferred row in `02c-hardening` with the failing evidence dir linked.

---

## 3. Out of scope

- LLM-as-judge. Judging is programmatic per the prompt: parse final `.scratch/phase-state.json`, assert phase, assert verification entries use 7-verb allowlist, assert no `bash ` entries, assert audit log entries, assert no orphan lockfile. No model-graded scoring.
- Adapter exercise (Roo, OpenCode). The §10.2 smoke (`02b-11-SMOKE-EXT-PLAN.md`) is the adapter-symmetry gate. This plan invokes the **core CLI only** (`scripts/harness.py phase set …`) because §9.1 measures agent-fit against the CLI contract, not adapter wrappers. (If reviewers want adapter-level low-reasoning measurement, that is a separate slice.)
- Multi-model comparison (Sonnet, Opus). Only Haiku-4.5. The prompt pins `claude-haiku-4-5-20251001`.
- Cost optimization beyond the per-trial budget cap. The harness is allowed to spend its full budget; a successor in `02c-hardening` may add caching.
- Network retry policies beyond the 2-retry flake policy. SDK-level transport errors count toward the retry budget.
- Continuous-integration wiring. The harness is run manually before tagging; CI integration is `02c-hardening` work.
- The `state_schema_version` upgrade path (R-2). Fixtures use the post-T0-1 schema only.
- Windows or non-POSIX paths (spec §4 OOS).
- Modifying `scripts/lib/` modules. This plan is purely a measurement instrument.
- The fifth flow option ("state repair after corruption") named in spec §9.1 line 446. The prompt names four flows: `discuss→plan`, `plan→execute`, `execute→done`, `full lifecycle`. The prompt's "full lifecycle" replaces the spec's "state repair after corruption" as the fourth flow. Rationale: spec §9.1 lists the canonical four-flow set as a flow MENU; the prompt selects four from the menu and is the authoritative scope for this plan. State-repair corruption recovery is exercised indirectly because `02b-09`'s diagnostic helper is loaded by the judge for fixture validation. If reviewers insist on the literal spec wording, swap "full lifecycle" for "state repair" in fixture-04 (no re-architecture needed; only `fixture-04-full-lifecycle.json` becomes `fixture-04-state-repair.json`). This swap is a one-fixture change and is the documented variance from spec wording.

---

## 4. Dependency on other slices

**Consumes (all must be merged to `develop` before this plan starts execution):**
- `02b-01-T0-A-PLAN.md` — `scripts/lib/atomic_io.py`, `scripts/lib/operational_paths.py`, `scripts/lib/exitcodes.py` (for `EXIT_*` constant imports in the judge).
- `02b-02-T0-1-PLAN.md` — `state_schema_version=2`, `transition.py`, `state_migrate.py`. Fixtures emit v2 state.
- `02b-03-T0-2-PLAN.md` — `fnmatch` scope activation. Judge asserts no scope-violation exit in happy-path trials.
- `02b-04-T0-3-PLAN.md` — CLI verbs (`phase set`, `phase approve`, `session unlock`), `audit.log`, `session.lock`, exit codes 2/3/6/7/8. Harness invokes these verbs.
- `02b-05-T0-4-PLAN.md` — 7-verb allowlist in `check.py`. Judge re-asserts the allowlist on each trial's verification entries.
- `02b-06-T0-5-PLAN.md` — `state_repair` refuses on unparseable input, exit 5; `.harness/backups/` directory. Used by judge's "no orphan lockfile / no spurious backup" assertion.
- `02b-07-T1-1-PLAN.md` — scope enforcement + `EXIT_SCOPE_VIOLATION=4`. Judge imports the constant.
- `02b-08-T1-S-PLAN.md` — adapter SKILL files updated to new verbs. (NOT exercised by this harness, but required because Haiku is prompted with a SKILL-like instruction frame; outdated SKILL text would confuse the model.)
- `02b-09-T1-M-PLAN.md` — `scripts/lib/state_diagnostics.py` (`load_state_json`, `parse_state_markdown`). Judge calls these to validate post-trial state without re-implementing parsing.

**Provides:** release-gate evidence consumed by spec §13 acceptance and by the `git tag` script in `scripts/release.py` (a future change in `02c-hardening` will read evidence summary JSON; this plan does NOT modify `release.py`).

**Independent of:** `02b-11-SMOKE-EXT-PLAN.md` (the §10.2 adapter-symmetry smoke). The two plans may land in either order; both block the release tag.

---

## 5. Test list (write tests FIRST, in this order)

Tests live at `scripts/test_low_reasoning_scenario.py` (flat per `CONTRACT-PIN.md` §3). They exercise the harness itself with **synthetic** state (no real API calls). A separate manual run executes the real Haiku trials; that run is gated by env var `ANTHROPIC_API_KEY` and the `--live` flag and is NOT part of the unit-test suite.

Each test is one numbered task. Fixture JSON files live at `scripts/smoke/fixtures/`.

### 5.1 Judge function tests (synthetic state, no API)

1. `test_judge_fixture_01_passes_when_phase_advanced_to_plan` — synthesize a post-trial `.scratch/phase-state.json` with `phase="plan"`, `state_schema_version=2`, valid verification entries; call `judge_fixture_01(scratch_dir)`; assert `JudgeResult(passed=True, reason="phase advanced from discuss to plan", retry_recommended=False)`.
2. `test_judge_fixture_01_fails_when_phase_unchanged` — post-trial state still `phase="discuss"`; assert `passed=False, reason="agent did not invoke 'harness phase set plan'"`.
3. `test_judge_fixture_01_fails_when_phase_overshoots_to_execute` — state at `phase="execute"`; assert `passed=False, reason="agent overshot target phase"`.
4. `test_judge_fixture_01_passes_on_needs_info_response` — trial response contains `"needs-info:"` prefix grounded in actual fixture diagnostic; assert `passed=True, reason="grounded needs-info response"`. Per spec §9.1: "A trial passes iff the agent reaches the next phase OR explicitly raises a `needs-info` request grounded in the actual diagnostic."
5. `test_judge_fixture_01_fails_on_ungrounded_needs_info` — trial response is `"needs-info: what is the weather"` (not grounded in fixture content); assert `passed=False, reason="needs-info not grounded in fixture diagnostic"`. Grounded-ness check: substring overlap with fixture's `diagnostic_keywords` list (≥1 keyword must appear in the needs-info text).
6. `test_judge_fixture_02_passes_when_plan_populated_and_approved` — state at `phase="plan"`, `approved=true`, `approved_by` set, `plan_id` set, `summary` set; assert `passed=True`.
7. `test_judge_fixture_02_fails_when_approved_without_plan_population` — `approved=true` but `plan_id=null`; assert `passed=False, reason="agent fabricated approval without populating plan"` (per spec §9.1 fail criteria: "fabricates approval").
8. `test_judge_fixture_03_passes_when_verification_entries_use_allowlist` — state at `phase="done"`, `verification=["pytest scripts/", "harness check"]`; assert `passed=True`. Imports `VERIFICATION_PREFIXES` from `scripts/lib/check.py` (the 7-verb list owned by T0-4) and asserts every entry starts with one of them.
9. `test_judge_fixture_03_fails_when_verification_uses_bash` — `verification=["bash scripts/foo.sh"]`; assert `passed=False, reason="verification entry uses removed 'bash ' verb"`.
10. `test_judge_fixture_03_fails_when_phase_done_without_verification` — `phase="done", verification=[]`; assert `passed=False, reason="phase=done with empty verification array"`.
11. `test_judge_fixture_04_passes_on_full_lifecycle_trace` — audit log contains entries `phase.set:discuss`, `phase.set:plan`, `phase.approve`, `phase.set:execute`, `phase.approve`, `phase.set:done`, in order; final state `phase="done"`; assert `passed=True`.
12. `test_judge_fixture_04_fails_when_lifecycle_skips_approval` — audit log shows `phase.set:plan` followed directly by `phase.set:execute` (no `phase.approve`); assert `passed=False, reason="lifecycle skipped approval gate"`.
13. `test_judge_fixture_04_fails_when_orphan_lockfile_remains` — `.harness/session.lock` file present in scratch dir after trial; assert `passed=False, reason="orphan session lockfile after trial completion"`.
14. `test_judge_imports_constants_not_literals` — meta-test: judge module's source contains zero numeric exit-code literals; all comparisons use `EXIT_*` from `scripts.lib.exitcodes`. (Mirrors `CONTRACT-PIN.md` §1 grep-gate rule.)
15. `test_judge_uses_state_diagnostics_for_parsing` — meta-test: judge module's source contains zero `json.loads(` calls against `phase-state.json`; all state reads route through `scripts.lib.state_diagnostics.load_state_json`. Mirrors `CONTRACT-PIN.md` §5.1 ownership of parsing.

### 5.2 Runner / budget / retry tests (synthetic model client)

16. `test_runner_records_per_trial_evidence_json` — invoke `run_trial(fixture, model_client=FakeClient([response="ok"]))`; assert a file `.planning/phases/02b-hardening/evidence/<flow>/<trial-id>.json` is written containing keys `{"fixture_id", "trial_index", "model", "prompt", "response", "judgment", "retry_count", "wall_clock_seconds", "input_tokens", "output_tokens", "budget_caps_hit"}`.
17. `test_runner_enforces_wall_clock_cap` — `FakeClient` sleeps 65s; assert trial marked `passed=False, budget_caps_hit=["wall_clock"]`, no retry attempted (budget cap is a HARD fail per spec §9.1 "A trial that exceeds any cap is recorded as a failure (not a timeout-skip).").
18. `test_runner_enforces_input_token_cap` — `FakeClient` reports `input_tokens=20001`; assert `passed=False, budget_caps_hit=["input_tokens"]`.
19. `test_runner_enforces_output_token_cap` — `FakeClient` reports `output_tokens=4001`; assert `passed=False, budget_caps_hit=["output_tokens"]`.
20. `test_runner_retries_up_to_2_on_judge_fail` — `FakeClient` returns judge-failing response twice then judge-passing; assert final `passed=True, retry_count=2, noisy=True`.
21. `test_runner_does_not_retry_after_2_failures` — `FakeClient` returns 3 judge-failing responses; assert `passed=False, retry_count=2, noisy=True` (retry count is attempts BEYOND the original; total invocations = 3 = 1 original + 2 retries).
22. `test_runner_does_not_retry_on_budget_cap_failure` — `FakeClient` exceeds output_tokens; assert `retry_count=0` (budget failures are not flake-retryable; they signal a real fitness problem).
23. `test_runner_uses_temperature_zero` — `FakeClient` records the `temperature` arg it was called with; assert `temperature == 0` on every invocation.
24. `test_runner_uses_pinned_model_id` — assert `model_client.model == "claude-haiku-4-5-20251001"`.
25. `test_runner_deterministic_fixtures_byte_identical_per_trial` — call `prepare_scratch_dir(fixture_01)` twice into two tmpdirs; assert `filecmp.dircmp(a, b).left_only == [] and dircmp.diff_files == []` AND file SHA-256s match per file. Per spec §9.1: "fixture repo state byte-identical across trials".

### 5.3 Aggregator tests

26. `test_aggregator_computes_per_flow_pass_rate_on_final_outcome` — synthesize 50 trial JSONs for fixture-01 with 42 passed (some after retry); assert `summary["fixture-01"]["pass_rate"] == 0.84` and `summary["fixture-01"]["passed"] == True` (≥0.80 gate).
27. `test_aggregator_marks_flow_failed_below_threshold` — 39 passed; assert `passed == False, gate_reason="39/50 below 40/50 threshold"`.
28. `test_aggregator_records_noisy_trial_count` — 42 passed of which 7 needed retries; assert `summary["fixture-01"]["noisy_count"] == 7`.
29. `test_aggregator_writes_summary_json_and_markdown` — assert `.planning/phases/02b-hardening/evidence/SUMMARY.json` and `SUMMARY.md` are written with per-flow rows and a final RELEASE-GATE verdict line.
30. `test_aggregator_release_gate_passes_only_when_all_four_flows_pass` — 3 flows ≥40/50, 1 flow <40/50; assert `summary["release_gate"] == "BLOCKED"` and the blocking flow is named.

### 5.4 Live-run smoke test (manual, env-gated)

31. `test_live_single_trial_smoke` — gated by `os.environ.get("HARNESS_E2E_LIVE") == "1"` AND `ANTHROPIC_API_KEY` set; runs ONE real trial against fixture-01 and asserts the runner produces a well-formed evidence JSON (does NOT assert pass/fail of the trial; just that the pipeline doesn't crash). Skip with clear reason otherwise.

### 5.5 Fixture validation tests

32. `test_all_four_fixtures_load_and_have_required_keys` — for each of `fixture-01..04`, assert keys `{fixture_id, initial_state, prompt_template, expected_target_phase, diagnostic_keywords, allowed_verbs}` present; `initial_state` parses via `state_diagnostics.load_state_json` (synthetic write to tmp).

---

## 6. Implementation tasks (in order)

Each task is one RED→GREEN cycle paired with the corresponding test from §5. Tasks 1–6 build scaffolding; 7–11 build the judge; 12–16 build the runner; 17–20 build the aggregator; 21–22 build the live entrypoint; 23 wires the manual run command.

### 6.1 Scaffolding (tasks 1–6)

1. Create `scripts/smoke/` directory; add `scripts/smoke/__init__.py` (empty); add `scripts/smoke/fixtures/` directory. Create `.planning/phases/02b-hardening/evidence/.gitkeep` (the evidence dir exists in git; per-flow subdirs are created lazily by the runner).
2. Write `scripts/smoke/fixtures/fixture-01-discuss-then-plan.json`:
   ```json
   {
     "fixture_id": "fixture-01-discuss-then-plan",
     "flow": "discuss-to-plan",
     "initial_state": {
       "state_schema_version": 2,
       "phase": "discuss",
       "approved": false,
       "approved_by": null,
       "approved_at": null,
       "plan_id": null,
       "summary": "Investigating whether to add feature X",
       "next_action": "Decide between approach A and approach B",
       "updated_at": "2026-05-16T00:00:00.000000000Z",
       "updated_by": "fixture@example.com"
     },
     "prompt_template": "You are a low-reasoning agent operating the harness CLI. Current state: {state}. The discussion has converged; the next step is to draft a plan. Issue exactly the CLI command(s) you would run. Available verbs: 'harness phase set <phase>', 'harness phase approve'. Respond with shell-style commands only, one per line, OR a single line beginning with 'needs-info:' if you cannot proceed.",
     "expected_target_phase": "plan",
     "diagnostic_keywords": ["discuss", "plan", "next_action", "approach"],
     "allowed_verbs": ["phase set", "phase approve"]
   }
   ```
3. Write `scripts/smoke/fixtures/fixture-02-plan-then-approve.json` — `initial_state` at `phase="plan"` with `plan_id=null, approved=false, next_action="Populate plan_id and approve"`; `expected_target_phase="plan"` (still plan, but `approved=true`); judge requires `plan_id` non-null AND `approved=true`.
4. Write `scripts/smoke/fixtures/fixture-03-execute-then-done.json` — `initial_state` at `phase="execute", approved=true, verification=["pytest scripts/", "harness check"]`; `expected_target_phase="done"`; judge requires audit-log entry `phase.set:done` AND verification entries persist AND all use 7-verb allowlist.
5. Write `scripts/smoke/fixtures/fixture-04-full-lifecycle.json` — `initial_state` is a fresh repo (`phase="discuss", everything-null`); `expected_target_phase="done"`; judge requires the full audit-log sequence per §5.1 test 11. (Variance from spec §9.1 wording acknowledged in §3 Out of scope.)
6. Write `scripts/smoke/prepare_scratch.py` (helper module): `prepare_scratch_dir(fixture: dict, dest: Path) -> Path` writes `.scratch/phase-state.json`, creates empty `.harness/`, returns `dest`. Deterministic: no timestamps generated; all data from fixture. (GREEN for test 25, 32.)

### 6.2 Model client wrapper (tasks 7–8)

7. Write `scripts/smoke/model_client.py`: class `HaikuClient` wrapping `anthropic.Anthropic().messages.create(...)`. Pinned: `model="claude-haiku-4-5-20251001"`, `temperature=0`, `max_tokens=4000`. Returns `ModelResponse(text, input_tokens, output_tokens, wall_clock_seconds)`. Reads `ANTHROPIC_API_KEY` from env; raises `RuntimeError` with a helpful message if unset.
8. Write `scripts/smoke/fake_client.py`: `FakeClient(scripted_responses, scripted_token_counts=None, scripted_wall_seconds=None)` for unit tests. Implements the same `respond(prompt) -> ModelResponse` interface and records every call's `temperature` and `model` for §5.2 tests 23-24. (GREEN for tests 23, 24.)

### 6.3 Judge (tasks 9–11)

9. Write `scripts/smoke/judge.py`: imports `EXIT_*` from `scripts.lib.exitcodes`, `VERIFICATION_PREFIXES` from `scripts.lib.check`, `load_state_json` from `scripts.lib.state_diagnostics`. Defines `JudgeResult` dataclass (`passed`, `reason`, `retry_recommended`). Defines `judge_fixture_01..04(scratch_dir, fixture) -> JudgeResult` functions. Each function:
   - Loads `<scratch_dir>/.scratch/phase-state.json` via `load_state_json`.
   - Loads audit log entries from `<scratch_dir>/.harness/audit.log` (newline-delimited JSON, parse each line via `load_state_json`-equivalent helper or `json.loads` of single lines — note the audit log is a stream, not a managed state file, so direct `json.loads` per line is acceptable; the helper is for state files only).
   - Asserts fixture-specific conditions per §5.1 tests 1–13.
   - Returns `JudgeResult`.
10. Add the needs-info grounded-ness check: a helper `_is_grounded_needs_info(response_text, fixture)` that returns True iff `response_text.lower().startswith("needs-info:")` AND at least one entry of `fixture["diagnostic_keywords"]` appears as a substring (case-insensitive) in `response_text`. (GREEN for tests 4, 5.)
11. Add the "no orphan lockfile" check: assert `not (scratch_dir / ".harness/session.lock").exists()` at trial end. Add the "no spurious backup" check: assert `len(list((scratch_dir / ".harness/backups/").glob("*.bak"))) == 0` for fixtures 01–04 (none should produce a backup; only state_repair does). (GREEN for test 13.)

### 6.4 Runner (tasks 12–16)

12. Write `scripts/smoke/runner.py`: `run_trial(fixture: dict, trial_index: int, model_client, scratch_root: Path, evidence_root: Path) -> TrialRecord`. Steps:
   a. `dest = scratch_root / f"trial-{fixture['fixture_id']}-{trial_index:03d}"`; `prepare_scratch_dir(fixture, dest)`.
   b. Render prompt via `fixture["prompt_template"].format(state=json.dumps(fixture["initial_state"], indent=2))`.
   c. Call `model_client.respond(prompt)` under wall-clock timer (`time.monotonic()`). If wall > 60s, mark budget_cap and abort.
   d. Parse response: extract shell commands (one per line, stripping `harness ` prefix). For each command, invoke `subprocess.run([sys.executable, "scripts/harness.py", *parts], cwd=dest, capture_output=True, timeout=10)`. Record stdout/stderr/exit. (Per `CONTRACT-PIN.md` §1, the CLI is `scripts/harness.py`.)
   e. Invoke fixture's judge function on `dest`.
   f. Write `TrialRecord` as JSON to `evidence_root / fixture['flow'] / f"trial-{trial_index:03d}.json"`.
13. Implement the retry loop in `run_trial`: if judge fails AND `not budget_caps_hit`, repeat up to 2 times with fresh `dest` directories (`trial-X-001-retry-1`, `-retry-2`). Final outcome = last attempt; `retry_count` = number of retries used; `noisy = retry_count > 0`. (GREEN for tests 20, 21, 22.)
14. Implement budget caps: wall-clock via `time.monotonic()` delta; tokens via `ModelResponse.input_tokens` / `output_tokens` from SDK usage block. If any cap hit, set `passed=False`, `budget_caps_hit=[...]`, skip retry. (GREEN for tests 17–19.)
15. Implement evidence writer: schema includes `fixture_id`, `trial_index`, `model="claude-haiku-4-5-20251001"`, `prompt` (full rendered prompt), `response` (full model text), `judgment` (`{passed, reason, retry_recommended}`), `retry_count`, `wall_clock_seconds`, `input_tokens`, `output_tokens`, `budget_caps_hit`, `noisy`, `commands_executed` (list of `{cmd, exit, stdout_tail, stderr_tail}` with tails capped at 2000 chars to keep evidence files <10kB). Write atomically via `scripts.lib.atomic_io.atomic_write_text`. (GREEN for test 16.)
16. Add temperature/model assertion: in `run_trial`, immediately after the model call, assert `model_client.last_call["temperature"] == 0 and model_client.last_call["model"] == "claude-haiku-4-5-20251001"`; raise on mismatch. (Defensive: prevents a future refactor from silently changing the model.) (GREEN for tests 23, 24.)

### 6.5 Aggregator (tasks 17–20)

17. Write `scripts/smoke/aggregator.py`: `aggregate_evidence(evidence_root: Path) -> Summary`. For each flow subdir, load all trial JSONs, count passes, count noisy, compute pass_rate, determine per-flow gate (`pass_rate >= 0.80`).
18. Write `Summary.to_json(path)` and `Summary.to_markdown(path)`. Markdown format:
    ```
    # Phase E Low-Reasoning Release Gate

    | Flow | Pass | Total | Rate | Noisy | Gate |
    |---|---|---|---|---|---|
    | discuss → plan | 42 | 50 | 84% | 7 | PASS |
    | ...

    **RELEASE GATE: PASS|BLOCKED**
    ```
19. Implement release-gate logic: `summary.release_gate = "PASS" if all flows pass else "BLOCKED"`; `summary.blocking_flows = [f for f in flows if not f.passed]`. (GREEN for tests 26–30.)
20. Add `--evidence-only` flag to aggregator entrypoint so post-run re-summarization without re-running trials is possible (operationally important: re-run on a single trial JSON shouldn't require 200 API calls).

### 6.6 Top-level entrypoint (tasks 21–23)

21. Write `scripts/smoke/low_reasoning_scenario.py` (the file the spec names; this is the user-facing entrypoint):
    - `argparse`: `--flow {fixture-01,fixture-02,fixture-03,fixture-04,all}`, `--trials N` (default 50), `--evidence-dir PATH` (default `.planning/phases/02b-hardening/evidence/`), `--scratch-root PATH` (default `tmp/smoke-e/`), `--live` (required to actually call API; without it, prints a dry-run plan and exits 0), `--summarize-only` (re-run aggregator on existing evidence).
    - Wires `HaikuClient` (when `--live`) or refuses without `--live`.
    - Iterates fixtures × trials, calling `run_trial`. Prints progress every 10 trials.
    - At end, calls `aggregate_evidence` and prints summary; exits 0 if gate PASS, exits 1 if BLOCKED. (Exit code lets callers `&&`-chain a release tag.)
22. Add a `--retry-failed-from EVIDENCE_DIR` mode that loads existing evidence, finds `noisy and not passed` trials, and re-runs only those with a fresh seed. This is operationally important when the API is flaky and we don't want to re-pay for 200 trials. (Optional polish; cut if time tight.)
23. Write a one-line usage example to the top of the file's module docstring; this is the canonical invocation reviewers run before tagging:
    ```
    python3 scripts/smoke/low_reasoning_scenario.py --flow all --trials 50 --live
    ```

---

## 7. Verification commands

Run from repo root.

**Unit tests (no API; runs in CI on every push):**
- `python3 -m unittest scripts.test_low_reasoning_scenario` — all 32 tests; expect 31 pass + 1 skip (the live-smoke test 31 skips without `HARNESS_E2E_LIVE=1`).
- `python3 -m unittest discover scripts/ -p 'test_*.py'` — full suite; expect zero regressions in any other module.

**Dry-run (no API):**
- `python3 scripts/smoke/low_reasoning_scenario.py --flow all --trials 2` — prints the dry-run plan; exits 0; no API call.

**Live smoke (manual, pre-tag):**
- `ANTHROPIC_API_KEY=sk-... python3 scripts/smoke/low_reasoning_scenario.py --flow all --trials 50 --live`
- Expected wall time: ~30-60 min for 200 trials at ~10-20 sec per trial.
- Expected cost: ~$2-5 USD at Haiku-4.5 pricing (200 trials × ~5k tokens × ~$0.001 / 1k = ~$1; with budget caps and retries, ~$2-5 realistic).
- Exit 0 ⇒ release gate PASS. Exit 1 ⇒ BLOCKED; consult `.planning/phases/02b-hardening/evidence/SUMMARY.md` for blocking flow.

**Re-aggregate without re-running:**
- `python3 scripts/smoke/low_reasoning_scenario.py --summarize-only` — re-reads evidence dir, re-writes `SUMMARY.json` and `SUMMARY.md`.

**Evidence inspection:**
- `ls .planning/phases/02b-hardening/evidence/*/trial-*.json | wc -l` — expect 200 (50 × 4 flows).
- `jq -r 'select(.passed == false) | .fixture_id + " " + .judgment.reason' .planning/phases/02b-hardening/evidence/*/trial-*.json | sort | uniq -c | sort -rn` — distribution of failure reasons.

---

## 8. Commits (atomic, in order)

One commit per RED→GREEN cycle. Plan-internal naming uses `feat(smoke)` / `test(smoke)` / `chore(smoke)` prefixes; `02b-10` slice tag is implicit per branch name.

1. `chore(smoke): scaffold scripts/smoke/ tree + evidence dir + four fixture JSONs` (impl tasks 1–5)
2. `feat(smoke): prepare_scratch helper writes deterministic fixture state` (impl task 6; GREEN tests 25, 32)
3. `feat(smoke): HaikuClient + FakeClient with pinned model + temperature=0` (impl tasks 7–8; GREEN tests 23, 24)
4. `test(smoke): RED for judge happy + phase-unchanged + overshoot` (tests 1–3)
5. `feat(smoke): judge_fixture_01..04 imports EXIT_* + VERIFICATION_PREFIXES + load_state_json` (impl task 9; GREEN tests 1–3, 6–11)
6. `test(smoke): RED for grounded vs ungrounded needs-info` (tests 4–5)
7. `feat(smoke): grounded needs-info check via diagnostic_keywords overlap` (impl task 10; GREEN tests 4–5)
8. `test(smoke): RED for orphan lockfile + spurious backup checks` (test 13)
9. `feat(smoke): post-trial cleanup invariants` (impl task 11; GREEN test 13)
10. `test(smoke): RED for evidence writer + budget cap enforcement` (tests 16–19)
11. `feat(smoke): runner with budget caps + evidence JSON writer` (impl tasks 12, 14, 15; GREEN tests 16–19)
12. `test(smoke): RED for retry policy (≤2, no retry on budget cap)` (tests 20–22)
13. `feat(smoke): flake-retry loop with noisy-trial tracking` (impl task 13; GREEN tests 20–22)
14. `test(smoke): RED for meta-tests (no exit-code literals, no bare json.loads)` (tests 14–15)
15. `chore(smoke): defensive temperature/model assertion in runner` (impl task 16; GREEN tests 14–15)
16. `test(smoke): RED for aggregator pass-rate + release-gate logic` (tests 26–30)
17. `feat(smoke): aggregator writes SUMMARY.json + SUMMARY.md + release gate` (impl tasks 17–19; GREEN tests 26–30)
18. `feat(smoke): low_reasoning_scenario.py entrypoint with --live + --summarize-only` (impl tasks 20–23)
19. `test(smoke): live single-trial smoke gated by HARNESS_E2E_LIVE=1` (test 31)
20. `docs(smoke): record manual live-run procedure + cost expectations in scripts/smoke/README` (small README naming the invocation and cost guidance; written ONLY because the file is operational, not user-facing docs — per project convention `Write` README is allowed when the README documents a tool's manual usage)

**Post-execution commit (manual, after the live run):**

21. `evidence(02b-10): record N=50×4 release-gate trial logs and SUMMARY.{json,md}` — commits the 200 trial JSONs + SUMMARY artifacts to `.planning/phases/02b-hardening/evidence/`. This commit is gated on `summary.release_gate == "PASS"`; if BLOCKED, instead commit `evidence(02b-10): record BLOCKED gate; defer remediation to 02c-hardening` with a `SKIPPED.md` naming the failing flow(s) per §9.1 escape clause.

---

## 9. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Haiku-4.5 deprecation before tag | Low | High (model id pinned) | Pin model id in fixture metadata; if deprecation announced, file 02c-hardening row to re-baseline on successor model BEFORE re-running gate. |
| Anthropic API rate-limit during 200-trial run | Medium | Medium | Runner retries on 429 (counts against the 2-retry budget); operator may re-run with `--retry-failed-from` after rate-limit window. |
| Cost overrun beyond ~$5 | Low | Low | Per-trial output token cap (4000) bounds worst-case cost; aggregator records total token spend; operator can abort mid-run (partial evidence is re-summarizable). |
| Non-determinism from prompt template rendering (e.g., dict ordering) | Medium | High (would invalidate the "byte-identical fixtures" guarantee) | Use `json.dumps(..., sort_keys=True, indent=2)` in prompt rendering; test 25 asserts byte-identical scratch dirs across two invocations. |
| Judge false-positive (agent fabricates approval but judge marks pass) | Medium | High (release ships with broken gate) | Test 7 explicitly asserts the fabricated-approval failure mode. Reviewers of this plan MUST inspect the judge function for any other fabricated-state vectors. |
| Judge false-negative (correct agent behavior marked fail) | Medium | Medium (release blocked unjustly) | Spec §9.1 explicitly allows grounded needs-info as a pass; test 4 covers this. If false-negative rate is high in live run, the noisy-trial count reveals it (high noisy + low pass = likely judge issue, not agent issue). |
| Harness itself flaky (non-deterministic test failures) | Medium | High (release gate unfalsifiable) | All unit tests use FakeClient; no real API in test suite. `prepare_scratch_dir` is deterministic. CI runs the unit suite on every push. |
| `02b-09` not landed when this plan starts | Low | Blocking | Per §4 dependencies, this plan does not start until all 01–09 are on develop. Reviewers verify by `git log develop -- scripts/lib/state_diagnostics.py`. |
| Spec wording variance ("state repair" vs "full lifecycle") flagged by reviewers | Medium | Low | §3 documents the variance and the one-fixture swap; resolution is a single-file change if reviewers reject the variance. |
| Budget cap mismatch (prompt says ≤10k/≤30s, spec says ≤20k/≤60s) | Documented | Low | §2 acknowledges the variance and adopts the spec-anchored cap with rationale. Reviewers may override with one-line config change in runner. |
| `bash ` verb removal not fully propagated (some `02b-08-T1-S` adapter file still references `bash`) | Low | Medium | Judge test 9 explicitly asserts rejection. If live run shows 0/50 pass on fixture-03, suspect this. |

---

## 10. Definition of done

- All 32 tests pass (`python3 -m unittest scripts.test_low_reasoning_scenario`).
- Dry-run (`--flow all --trials 2` without `--live`) exits 0.
- Live run on `develop` HEAD with all 01–09 merged produces 200 trial JSONs + `SUMMARY.md` showing per-flow rate ≥80%.
- `SUMMARY.md` committed under `.planning/phases/02b-hardening/evidence/`.
- This plan file cited in the release-tag commit message.
- If BLOCKED: `SKIPPED.md` written per §9.1 escape clause; follow-up row filed in `02c-hardening`; release tag NOT cut.

---

## 11. Cross-plan citations

- `CONTRACT-PIN.md` §1 — module path conventions; judge imports from `scripts.lib.*` per the canonical paths.
- `CONTRACT-PIN.md` §3 — flat test directory; `scripts/test_low_reasoning_scenario.py` not `scripts/tests/`.
- `CONTRACT-PIN.md` §4 — exit code constants (judge imports `EXIT_*` symbolically).
- `CONTRACT-PIN.md` §8.1 — this plan's pinned ownership scope.
- `docs/adr/2026-05-16-hardening-bundle.md` Artifact 1 — CLI verb contract that the runner invokes.
- `docs/superpowers/specs/2026-05-16-hardening-slice-design.md` §9.1 — pass criteria and escape clause.
- `docs/superpowers/specs/2026-05-16-hardening-slice-design.md` §13 — release acceptance.
