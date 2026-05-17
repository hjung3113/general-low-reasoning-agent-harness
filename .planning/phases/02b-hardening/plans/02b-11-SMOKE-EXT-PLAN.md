# Plan — 02b-11 release_smoke_test.py 3-Stage Adapter-Neutral Extension

Phase: `02b-hardening` (slice 02b-11, release-gate harness; lands AFTER T0-1/T0-3/T0-4/T1-S/T1-M; per `CONTRACT-PIN.md` §8.2 this plan is the sole owner of §10.2 acceptance evidence)
Spec: `docs/superpowers/specs/2026-05-16-hardening-slice-design.md` §10 (adapter-neutral verification), §10.2 (three-stage smoke + static grep gate), §13.4 (release acceptance — the §10 smoke harness change is scoped into the implementation plan as a known cost)
ADR: `docs/adr/2026-05-16-hardening-bundle.md` — Artifact 1 (CLI Contract; the source of truth from which the golden file is DERIVED per spec §10.1, not generated from running the implementation)
Contract pin: `.planning/phases/02b-hardening/CONTRACT-PIN.md` §8.2 (this plan's ownership), §4 (exit codes consumed in fixtures), §1 (`scripts/lib/` module paths consumed)

## Goal (one sentence)
Extend `scripts/release_smoke_test.py` with three new sequential stages — **core-only**, **Roo lifecycle (4 commands)**, and **OpenCode lifecycle (4 commands)** — each driving the same scripted `discuss → plan → execute → done` flow against a fixture repo under `tmp/` and asserting byte-equality (modulo timestamp/pid redaction) against a single hand-authored golden file `scripts/smoke/golden/cli-contract-lifecycle.json` derived from ADR Artifact 1, plus a static grep gate that fails the smoke if any of the nine quarantined non-lifecycle Roo command files reintroduces a `.scratch/phase-state.json` write reference.

## Acceptance (copied verbatim from spec §10.2 and §13.4)
- Spec §10.2 stage 1: "Core-only stage: invoke the new CLI directly with no adapter context. Run a scripted `discuss -> plan -> execute -> done` flow against a fixture repository under `tmp/`. Pass criteria: every transition succeeds, every check passes, and the resulting state matches the golden file derived from the CLI contract."
- Spec §10.2 stage 2: "Roo stage: invoke the same scripted flow through ONLY the 4 lifecycle commands in `.roo/commands/` (`discuss`, `plan`, `execute`, `done`). The other 9 Roo commands (`adr`, `bugfix`, `feature`, etc.) are NOT exercised; they are quarantined. Each lifecycle Roo command MUST resolve to the same core CLI verb the core-only stage used. Pass criteria: same as core-only."
- Spec §10.2 stage 3: "OpenCode stage: invoke the same flow through `.opencode/commands/*.md` (4 commands: `discuss`, `plan`, `execute`, `done`). Pass criteria: same as core-only."
- Spec §10.2 static grep gate: "no non-lifecycle adapter command file may reference `.scratch/phase-state.json` (or the post-ADR-003a state file path, if moved) on any write path. The grep is conservative: it greps for the file path appearing in the same file as a `>`, `write`, `replace`, or similar write verb. The grep gate's allowlist is exactly the files touched by T1-S; an entry outside that allowlist fails CI. This prevents the quarantined commands from regressing the live-gate write paths while the slice is in flight."
- Spec §10.2 failure rule: "Any of the three smoke stages failing fails the slice acceptance."
- Spec §13.4: "The §10 smoke harness change (three stages + static grep gate) is scoped into the implementation plan as a known cost."

## Out of scope
- Re-implementing the core CLI verbs (`phase set`, `phase approve`, `session unlock`) — owned by T0-3 (`02b-04-T0-3-PLAN.md`); this plan only invokes them via subprocess.
- The 50-trial low-reasoning trial harness — owned by `02b-10-PHASE-E-HARNESS-PLAN.md` (CONTRACT-PIN §8.1). This plan does NOT exercise model behavior; it is a deterministic CLI smoke.
- Creating `.roo/commands/done.md` — owned by `02b-08-T1-S-PLAN.md` per CONTRACT-PIN §5.2. This plan EXPECTS that file to exist and CONSUMES it. If T1-S has not landed, every stage-2 step that calls `done.md` exits non-zero with a clear "T1-S not landed" diagnostic; the plan's first task verifies T1-S landed before any stage runs.
- Wiring new exit codes. CONTRACT-PIN §8.2 explicitly states: "Plans 10 and 11 MUST NOT define new exit codes; if a needed signal is missing, file a follow-up plan in `02c-hardening`." Fixtures exercise the existing CONTRACT-PIN §4 table only.
- Modifying ADR Artifact 1 to match implementation. If implementation diverges from Artifact 1, the implementation is wrong (per spec §10.3 "the contract precedes the implementation and the test"); this plan does NOT regenerate the golden file from runtime output.
- Adapter command count parity (spec §10.4 explicitly NOT a release criterion). Stage 2 exercises exactly 4 Roo lifecycle commands and ignores the other 9.
- Replacing the existing 11 `CASES` matrix in `release_smoke_test.py`. The three new stages run BEFORE the existing matrix loop and gate on its success.
- Windows-specific path handling (spec §4 declares OOS).

## Test list (write tests FIRST, in this order)
Each test = one numbered task. Tests live in a new `scripts/test_release_smoke_ext.py` (flat-test-file convention per CONTRACT-PIN §3). Fixtures live under `scripts/fixtures/smoke/`. Goldens live under `scripts/smoke/golden/`. The new driver code is added inline to `scripts/release_smoke_test.py` plus a new helper module `scripts/lib/smoke_lifecycle.py` (canonicalization + adapter dispatch).

### Group A — normalization primitives (CONTRACT-PIN §1: new helper module)

1. `test_canonicalize_redacts_iso_nanos_timestamps` — feed `{"approved_at":"2026-05-16T19:30:45.123456789Z"}` to `canonicalize_capture(payload)`; assert output `{"approved_at":"<TIMESTAMP>"}`. Covers ADR Artifact 1's nanosecond-precision `approved_at`/`updated_at`/`at` fields.
2. `test_canonicalize_redacts_pid_in_session_lock_payload` — feed `{"pid": 84321, "boot_id": "abc"}`; assert `{"pid":"<PID>","boot_id":"abc"}`. PID is non-deterministic per process.
3. `test_canonicalize_redacts_sha256_in_audit_drift_template` — feed an audit entry `{"before_sha256":"deadbeef..."*8, "after_sha256":"cafebabe..."*8}`; assert both fields become `"<SHA256>"`. SHAs are content-derived; goldens cite shape not content.
4. `test_canonicalize_sort_keys_true` — feed `{"b":1,"a":2}`; assert serialized form is `{"a":2,"b":1}` via `json.dumps(..., sort_keys=True, separators=(",", ":"))`.
5. `test_canonicalize_preserves_phase_enum_and_exit_code_literals` — feed `{"phase":"execute","exit_code":4}`; assert NOT redacted (these are part of the contract surface).
6. `test_canonicalize_redacts_audit_entry_index_to_monotonic_only` — feed `{"index": 42}`; assert `{"index":"<MONOTONIC>"}` (the exact value depends on whether other tests ran first; only monotonicity matters per ADR Artifact 1 line 500 "Expect a new audit-log entry each time").
7. `test_canonicalize_redacts_path_prefix_of_tmp_fixture` — replace `Path(tempfile.mkdtemp())` prefix with `<TMP>`. Fixtures live under randomized tmp dirs; golden must not encode the random path.
8. `test_canonicalize_redacts_email_to_canonical_actor` — feed `{"by":"hjung3113@gmail.com"}`; assert `{"by":"<ACTOR>"}` (the value is git-config-dependent; goldens assert shape).

### Group B — golden file structure (derived from ADR Artifact 1)

9. `test_golden_file_exists_and_parses_as_json` — assert `scripts/smoke/golden/cli-contract-lifecycle.json` is present and parses; this guards against accidental deletion or BOM corruption.
10. `test_golden_contains_four_lifecycle_audit_entries` — load golden; assert it has an `audit_entries` array of length 6 (one `phase.set discuss`, one `phase.set plan`, one `phase.approve` for plan→execute, one `phase.set execute`, one `phase.approve` for execute→done, one `phase.set done`) with `verb` values matching ADR Artifact 1 verb names exactly. **Deviation note:** the original plan body said "5 entries" (one approve). The implementation emits **6** entries because the lifecycle requires two `phase.approve` calls — one to unlock the `plan → execute` transition and a second to unlock the `execute → done` transition. The 6-entry shape is the contract; see CHANGELOG for the slice's deviation entry.
11. `test_golden_final_state_matches_artifact1_g3a_few_shot` — load golden; assert the `final_state` field matches the ADR Artifact 1 §G3-A canonical `phase=done` few-shot example (ADR lines 599-635), with timestamp/email/sha/path fields redacted per Group A.
12. `test_golden_exit_codes_in_table` — assert every `exit_code` in golden ∈ {0,1,2,3,4,5,6,7,8} per CONTRACT-PIN §4 (no exit codes outside the pinned table).
13. `test_golden_is_static_not_generated` — assert golden file's first line contains the marker comment `// DERIVED FROM ADR Artifact 1 — DO NOT REGENERATE FROM RUNTIME` (json5-style header stripped before parse). This is the spec §10.3 invariant made executable.

### Group C — core-only stage (CLI direct)

14. `test_stage1_core_only_full_lifecycle_produces_expected_golden` — spin up tmp fixture; run scripted flow (`harness phase set discuss`, `harness phase set plan`, `harness phase approve`, `harness phase set execute`, `harness phase set done`); capture (a) the contents of `.harness/audit.log` parsed as NDJSON, (b) the final `.scratch/phase-state.json` payload, (c) every stdout/stderr from each verb invocation; canonicalize via Group A primitives; assert deep-equality with golden.
15. `test_stage1_each_transition_returns_exit_0` — every CLI invocation in the happy-path flow exits 0. Run via `subprocess.run(..., check=False)` so an early non-zero exits with the failing verb name and stderr for the operator to read.
16. `test_stage1_audit_log_monotonic_indices` — assert audit entry `index` values are `[1,2,3,4,5]` strictly (pre-canonicalization sanity, before Group A test 6 redaction is applied).
17. `test_stage1_state_file_sha256_matches_last_audit_after_sha` — for every transition, compute `sha256(state_file_bytes)` after the verb returns, assert it equals the just-appended audit entry's `after_sha256` (per ADR Artifact 1 line 587 drift template invariant). Failure of this assertion is a contract violation in T0-3, not in this plan.
18. `test_stage1_session_lock_absent_after_done` — after the flow completes, `.harness/session.lock` MUST NOT exist (per ADR Artifact 1 line 559 unlock-on-clean-exit; `done` is a terminal lifecycle state).
19. `test_stage1_fixture_repo_isolated_from_repo_root` — assert the smoke runs in `tempfile.mkdtemp(prefix="harness-smoke-stage1.")` and that no file under repo root is modified during the stage (compare `git status --porcelain` before and after).

### Group D — Roo lifecycle stage (4 commands)

20. `test_stage2_roo_lifecycle_full_flow_produces_same_golden_as_stage1` — invoke the scripted flow through `.roo/commands/phase-discuss.md`, `.roo/commands/phase-plan.md`, `.roo/commands/phase-execute.md`, `.roo/commands/done.md` (lifecycle 4 only; per CONTRACT-PIN §5.2 `.roo/commands/done.md` is created by T1-S). Each command-file is dispatched via the new helper `dispatch_roo_command(name, args)` which parses the markdown's `mode` / `description` frontmatter, extracts the embedded CLI invocation, and runs it. Capture + canonicalize + assert deep-equality with the SAME golden file from stage 1.
21. `test_stage2_lifecycle_resolves_to_same_core_verb_as_stage1` — for each of the 4 Roo lifecycle commands, assert the dispatched core CLI invocation byte-equals the corresponding stage-1 invocation (modulo working directory). This is the spec §10.4 "semantic symmetry over lexical symmetry" rule: same CLI verb, same flags, same JSON payload.
22. `test_stage2_quarantined_commands_not_invoked` — assert that during the stage, NONE of `.roo/commands/{adr,bugfix,feature,doctor,issues,ops,fsd-phase,review,simple}.md` are read or executed. Implemented via a `pathlib.Path` mock that fails any open of those files inside the dispatcher. This codifies the spec §10.2 "9 commands quarantined" rule.
23. `test_stage2_t1s_landing_precondition` — assert `.roo/commands/done.md` exists before stage 2 runs. If missing, abort the stage with a clear `error: T1-S has not landed yet; cannot run stage 2 (Roo lifecycle smoke). See CONTRACT-PIN.md §5.2.` (exit 1) rather than emitting a confusing dispatcher failure.

### Group E — OpenCode lifecycle stage (4 commands)

24. `test_stage3_opencode_lifecycle_full_flow_produces_same_golden_as_stage1` — invoke the scripted flow through `.opencode/command/discuss.md`, `.opencode/command/plan.md`, `.opencode/command/execute.md`, `.opencode/command/done.md`. Dispatch via `dispatch_opencode_command(name, args)`. Capture + canonicalize + assert deep-equality with the same golden file. Note the directory name discrepancy: spec §10.2 line 517 writes `.opencode/commands/*.md` but the on-disk path is `.opencode/command/` (singular). The dispatcher accepts both for forward-compat; tests assert the singular form is the one actually present.
25. `test_stage3_lifecycle_resolves_to_same_core_verb_as_stage1` — same assertion as test 21, for OpenCode.
26. `test_stage3_opencode_no_paths_outside_command_dir` — assert dispatch never reads outside `.opencode/command/`. Adapter parity: OpenCode currently has only 4 commands (no quarantine list needed) but the test enforces the discipline going forward.

### Group F — static grep gate (spec §10.2 mandatory)

27. `test_grep_gate_passes_when_quarantined_commands_clean` — run the gate against the current `.roo/commands/{adr,bugfix,feature,doctor,issues,ops,fsd-phase,review,simple}.md` files; assert ZERO violations. The gate command is: `grep -l -E "(write|>|replace).*\.scratch/phase-state\.json|\.scratch/phase-state\.json.*(write|>|replace)" .roo/commands/{adr,bugfix,feature,doctor,issues,ops,fsd-phase,review,simple}.md` → expected empty output. This is the spec §10.2 line 519 "conservative" form: file path co-located with a write verb on any line.
28. `test_grep_gate_fails_when_synthetic_violation_planted` — synthesize a temp copy of `.roo/commands/adr.md` with a planted line `> .scratch/phase-state.json` and run the gate against the temp copy; assert the gate reports a violation and exits non-zero with the offending filename. This guards the guard.
29. `test_grep_gate_allowlist_matches_t1s_touched_files` — the gate allowlist (files PERMITTED to reference `.scratch/phase-state.json` write paths) is exactly: `.roo/commands/{phase-discuss,phase-plan,phase-execute,done}.md` and `.opencode/command/{discuss,plan,execute,done}.md`. Any non-allowlisted file flagged by the gate fails. Assert the allowlist constant in `scripts/lib/smoke_lifecycle.py` matches CONTRACT-PIN §5.2 + spec §10.2.
30. `test_grep_gate_pattern_does_not_false_positive_on_comments` — synthesize a Roo command file with `<!-- documentation: never write .scratch/phase-state.json -->` (no write verb in same line context); assert the gate does NOT flag it. The conservative form errs on the side of flagging; this test pins the false-positive boundary so the gate does not become un-runnable.

### Group G — orchestration + regression

31. `test_three_stages_run_in_order` — invoke `run_lifecycle_smoke(matrix_root)`; assert stage 1 completes before stage 2 starts before stage 3 starts (each stage prints a `STAGE n PASS` line; assert their stdout order).
32. `test_stage_failure_aborts_remaining_stages` — inject a forced failure into stage 1 (e.g., by pre-populating the fixture with an unparseable phase-state.json so the first `phase set discuss` exits 5); assert stage 2 and stage 3 are SKIPPED, the outer script exits non-zero, and the diagnostic names the failing stage.
33. `test_existing_release_smoke_test_cases_still_pass` — run `python3 scripts/release_smoke_test.py --keep-temp` against a known-good `develop` checkout; assert the 11 existing `CASES` entries (lines 16-79 of current file) all print `PASS`. The new stages are PREPENDED, not interleaved; they do not alter the existing matrix loop's contract.
34. `test_release_smoke_test_exits_0_on_full_success` — full run (3 new stages + 11 existing cases) on a clean tree exits 0 and prints `TMP <path>` last.
35. `test_keep_temp_flag_preserved` — `--keep-temp` continues to work; assert temp dir is not deleted when flag is set, IS deleted when flag is absent.
36. `test_release_flag_still_requires_expected_version` — assert `--release` without `--expected-version` still raises `SystemExit("--release requires --expected-version vMAJOR.MINOR.PATCH")` per current line 95.

## Implementation tasks (in order)
Each task is one RED→GREEN cycle. Tasks 1-8 build canonicalization primitives + golden. Tasks 9-14 wire stage 1. Tasks 15-19 wire stage 2 (Roo). Tasks 20-23 wire stage 3 (OpenCode). Tasks 24-27 wire the grep gate. Tasks 28-29 wire orchestration + regression.

1. Add `scripts/lib/smoke_lifecycle.py` skeleton exporting: `canonicalize_capture(obj) -> dict`, `LIFECYCLE_GOLDEN_PATH`, `STAGE1_INVOCATIONS` (list of dicts), `dispatch_roo_command(name, args, *, fixture_root)`, `dispatch_opencode_command(name, args, *, fixture_root)`, `QUARANTINED_ROO_COMMANDS` (frozenset), `LIFECYCLE_GREP_GATE_ALLOWLIST` (frozenset), `run_grep_gate() -> list[Violation]`, `run_lifecycle_smoke(matrix_root) -> None` (RED for all tests in Group A).
2. Implement `canonicalize_capture`: recursive walk; redact via regex `r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{9}Z$"` → `"<TIMESTAMP>"`; redact `r"^[0-9a-f]{64}$"` → `"<SHA256>"`; key-based redaction for `pid`, `index`, `by`, `updated_by`, `approved_by`; path-prefix replacement for `tempfile.gettempdir()` + the active matrix root; emit via `json.dumps(..., sort_keys=True, separators=(",", ":"))` for byte-stable form (GREEN for tests 1-8).
3. Create `scripts/smoke/golden/cli-contract-lifecycle.json` BY HAND from ADR Artifact 1 — copy the verb-1, verb-2, audit-log, and G3-A few-shot blocks verbatim, redacted via the Group A primitives, into a single JSON file with two top-level keys: `audit_entries` (length 5) and `final_state` (the G3-A canonical example). Prepend a `// DERIVED FROM ADR Artifact 1 — DO NOT REGENERATE FROM RUNTIME` header comment that is stripped before parse. (GREEN for tests 9-13.)
4. Add `scripts/fixtures/smoke/lifecycle-base/` containing the minimal repo skeleton needed to run a lifecycle smoke: `.harness/` (empty dir), `.scratch/` (empty dir), `.planning/STATE.md` (managed-block skeleton from `scripts/check_harness.py`'s expected layout). Add a `copy_fixture(dest)` helper in `scripts/lib/smoke_lifecycle.py`.
5. Implement `STAGE1_INVOCATIONS` as a literal list of dicts: `[{"argv":["phase","set","discuss"]}, {"argv":["phase","set","plan"]}, {"argv":["phase","approve"]}, {"argv":["phase","set","execute"]}, {"argv":["phase","set","done"]}]`. This list is the SHARED contract that stages 2 and 3 dispatch against, per spec §10.4 semantic-symmetry.
6. Implement stage 1 driver `_run_stage1_core(fixture_root) -> dict`: copy fixture, iterate `STAGE1_INVOCATIONS`, for each call `subprocess.run([sys.executable, "scripts/harness.py", *inv["argv"]], cwd=fixture_root, check=False, capture_output=True, text=True)`, accumulate {audit_log, final_state, stdouts, stderrs}, return canonicalized capture (GREEN for tests 14-15).
7. Implement audit-log SHA verification (test 17): after each verb, read `.harness/audit.log` last NDJSON line, compute `hashlib.sha256(state_file.read_bytes()).hexdigest()`, assert it equals the `after_sha256` field. This is verifying T0-3's contract, not adding behavior.
8. Implement session-lock + isolation assertions (tests 18-19) using `subprocess.run(["git","status","--porcelain"], cwd=repo_root)` snapshots before/after.
9. Add Roo command-file dispatcher `_dispatch_roo_command(path: Path, fixture_root: Path) -> CompletedProcess`: read the markdown file; parse the frontmatter (`---...---` block) for `mode` and `description`; locate the embedded slash-command and/or `harness ...` invocation in the body via regex `r"`(harness [a-z][a-z\- ]+)`"`; substitute the matched CLI invocation as argv; run via `subprocess.run`. This is a simulated Roo dispatcher (the real Roo runtime is a model orchestrator; we extract the deterministic CLI part).
10. Wire `STAGE1_INVOCATIONS[i]` ↔ `.roo/commands/{phase-discuss,phase-plan,phase-execute,done}.md` mapping: the dispatcher pulls the verb from the markdown body and asserts it matches `STAGE1_INVOCATIONS[i]["argv"][0]` (`phase`). If mismatch, fail with a diagnostic naming both sides so T1-S can be re-verified.
11. Implement stage 2 driver `_run_stage2_roo(fixture_root) -> dict`: iterate `STAGE1_INVOCATIONS` in order, for each look up the corresponding Roo command file, dispatch, accumulate capture, return canonicalized capture (GREEN for tests 20-21).
12. Implement quarantine enforcement (test 22): wrap `open()` with a no-op tracker during stage 2; after the stage, assert the tracker's set intersected with `QUARANTINED_ROO_COMMANDS` (the 9 file paths) is empty.
13. Implement T1-S precondition check (test 23): at the top of `_run_stage2_roo`, `assert (Path.cwd()/".roo/commands/done.md").exists(), "T1-S has not landed yet; cannot run stage 2 (Roo lifecycle smoke). See CONTRACT-PIN.md §5.2."` — exit 1 with the message, NOT a stack trace.
14. Add OpenCode command-file dispatcher `_dispatch_opencode_command(path: Path, fixture_root: Path)`: mirror the Roo dispatcher; accept either `.opencode/command/*.md` (current on-disk singular form) or `.opencode/commands/*.md` (spec text plural form) — prefer singular if both present.
15. Implement stage 3 driver `_run_stage3_opencode(fixture_root) -> dict`: mirror stage 2 against the OpenCode commands (GREEN for tests 24-25).
16. Implement directory-isolation assertion for stage 3 (test 26): instrument `_dispatch_opencode_command` to record every `Path.open()` and assert all reads stay under `.opencode/command/`.
17. Implement `run_grep_gate()`: shell out to `grep -l -E "..."` with the conservative pattern (write verb co-located with state path); accumulate violations; the allowlist (`LIFECYCLE_GREP_GATE_ALLOWLIST`) is excluded BEFORE the grep runs (the grep is invoked against `.roo/commands/{adr,bugfix,...}.md` only, never against allowlisted files). Return list of `Violation(file, line_number, line_text)`. (GREEN for tests 27-30.)
18. Wire grep gate into `run_lifecycle_smoke`: call `violations = run_grep_gate()`; if non-empty, raise `SystemExit(f"grep gate violations: {violations!r}")` BEFORE stage 1 runs (the gate is the cheapest test; fail fast).
19. Implement `run_lifecycle_smoke(matrix_root)`: invoke grep gate → stage 1 → stage 2 → stage 3 in order; on any stage failure, print `STAGE n FAILED: <reason>` and re-raise. Each successful stage prints `STAGE n PASS`. (GREEN for tests 31-32.)
20. Modify `scripts/release_smoke_test.py` `main()`: BEFORE the existing `for name, options in CASES` loop, call `run_lifecycle_smoke(matrix_root)`. The new flow is: optional `release-check` → `run_lifecycle_smoke` → existing `CASES` loop. Add `--skip-lifecycle-smoke` flag for debugging (not for CI) (GREEN for tests 33-36).
21. Update `scripts/release_smoke_test.py` module docstring to name the three new stages and cite spec §10.2 + this plan.
22. Add `scripts/smoke/golden/README.md` with one line: "Golden files in this directory are DERIVED FROM ADR Artifact 1 (`docs/adr/2026-05-16-hardening-bundle.md`). Do NOT regenerate them from runtime output. See spec §10.3."
23. Run the full new test file: `python3 -m unittest scripts.test_release_smoke_ext -v` — expect all 36 tests green.
24. Run the full smoke end-to-end: `python3 scripts/release_smoke_test.py` — expect `STAGE 1 PASS`, `STAGE 2 PASS`, `STAGE 3 PASS`, then 11 existing `PASS <name>` lines, then `TMP <path>`, exit 0.
25. Append CHANGELOG entry under `## Unreleased (develop)` → `### Tooling`: "Smoke harness extended with three adapter-neutral lifecycle stages (core, Roo, OpenCode) and static grep gate against quarantined adapter commands. Per spec §10.2." This plan does NOT own a Breaking Ledger row (per CONTRACT-PIN §7 mapping table; this plan is L-less because it adds capability without breaking existing contracts).

## Dependency on other slices
- **Hard blocks (must land first):**
  - `02b-04-T0-3-PLAN.md` — provides `harness phase set`, `harness phase approve`, `harness session unlock`, audit log writer. Stage 1 cannot run without these verbs.
  - `02b-02-T0-1-PLAN.md` — provides `state_schema_version=2` and migrator; the golden file's `final_state` block asserts `state_schema_version == 2` per ADR G3-A.
  - `02b-05-T0-4-PLAN.md` — provides 7-verb verification allowlist; the golden's `verification` field contents must match T0-4's grammar.
  - `02b-08-T1-S-PLAN.md` — provides `.roo/commands/done.md` (CONTRACT-PIN §5.2) and updated lifecycle command bodies to reference new CLI verbs (CONTRACT-PIN §7 row L20). Stage 2 fails fast if T1-S is missing (test 23).
  - `02b-09-T1-M-PLAN.md` — provides `state_diagnostics.py` so fixture validation produces structured diagnostics in failure-mode tests (test 32).
- **Soft (recommended but not blocking):**
  - `02b-01-T0-A-PLAN.md` — `exitcodes.py` constants. This plan uses CONTRACT-PIN §4 exit codes only via subprocess return values; tests do not import `EXIT_*` symbols directly, so T0-A is not a hard block.
  - `02b-10-PHASE-E-HARNESS-PLAN.md` — runs in parallel; both plans gate on T1-M but do not gate on each other.
- **Provides (consumed by §13 release acceptance):**
  - The three `STAGE n PASS` lines + a final `TMP <path>` line, with exit 0. Release-gate `make release` (or equivalent) consumes this output as adapter-neutral evidence per spec §13.
  - The static grep gate result, archived under `.harness/audit.log` as evidence that quarantined commands are clean as of the release commit.

## Verification commands
Run from repo root:
- `python3 -m unittest scripts.test_release_smoke_ext` — the new 36-test module (Groups A-G).
- `python3 scripts/release_smoke_test.py` — full end-to-end smoke; expect `STAGE 1 PASS` / `STAGE 2 PASS` / `STAGE 3 PASS` / 11× `PASS <name>` / `TMP <path>`, exit 0.
- `python3 scripts/release_smoke_test.py --skip-lifecycle-smoke` — regression-only path; expect just the 11× `PASS <name>` lines (parity with pre-slice behavior).
- `grep -l -E "(write|>|replace).*\.scratch/phase-state\.json|\.scratch/phase-state\.json.*(write|>|replace)" .roo/commands/{adr,bugfix,feature,doctor,issues,ops,fsd-phase,review,simple}.md` — MUST return empty (the spec §10.2 gate command, runnable independently).
- Golden-file diff sanity: `python3 -c "import json; print(json.load(open('scripts/smoke/golden/cli-contract-lifecycle.json')).keys())"` — expect `dict_keys(['audit_entries', 'final_state'])`.
- ADR cross-check: `diff <(jq -r .audit_entries[0].verb scripts/smoke/golden/cli-contract-lifecycle.json) <(echo "phase.set")` — every golden entry's `verb` matches ADR Artifact 1 verb names.

## Commits (atomic, in order)
One commit per RED→GREEN cycle. Tagged with the slice number `02b-11` for searchability.

1. `test(02b-11): RED for canonicalize_capture redaction primitives` (Group A tests 1-8)
2. `feat(02b-11): smoke_lifecycle.canonicalize_capture with sort_keys + timestamp/pid/sha/path redaction` (impl tasks 1-2)
3. `feat(02b-11): cli-contract-lifecycle.json golden derived from ADR Artifact 1` (impl task 3; GREEN for Group B tests 9-13)
4. `test(02b-11): RED for stage 1 core-only lifecycle smoke` (Group C tests 14-19)
5. `feat(02b-11): smoke_lifecycle.run_stage1_core driver + STAGE1_INVOCATIONS contract` (impl tasks 4-8)
6. `test(02b-11): RED for stage 2 Roo lifecycle dispatch + quarantine` (Group D tests 20-23)
7. `feat(02b-11): smoke_lifecycle.dispatch_roo_command + run_stage2_roo + quarantine guard + T1-S precondition` (impl tasks 9-13)
8. `test(02b-11): RED for stage 3 OpenCode lifecycle dispatch` (Group E tests 24-26)
9. `feat(02b-11): smoke_lifecycle.dispatch_opencode_command + run_stage3_opencode + directory-isolation` (impl tasks 14-16)
10. `test(02b-11): RED for static grep gate against quarantined commands` (Group F tests 27-30)
11. `feat(02b-11): smoke_lifecycle.run_grep_gate with conservative co-location pattern + allowlist` (impl tasks 17-18)
12. `test(02b-11): RED for orchestration ordering + failure fast-abort` (Group G tests 31-32)
13. `feat(02b-11): smoke_lifecycle.run_lifecycle_smoke orchestrator + stage failure abort` (impl task 19)
14. `test(02b-11): RED for release_smoke_test.py regression preservation` (Group G tests 33-36)
15. `feat(02b-11): wire run_lifecycle_smoke into release_smoke_test.py main + --skip-lifecycle-smoke flag` (impl tasks 20-22)
16. `docs(02b-11): CHANGELOG entry + golden README header invariant` (impl task 25)

## Risk + reversibility
- Risk: **M (medium)** — the plan adds tests + a driver but its correctness depends on three upstream rows (T0-3, T0-4, T1-S) shipping a CLI surface and adapter command bodies that match ADR Artifact 1. If upstream diverges from the contract, this plan's tests fail loudly (which is the POINT: spec §10.3 "the smoke validates that the implementation matches the contract"). The risk of THIS plan emitting a false PASS is bounded by the golden file being hand-authored from the ADR (test 13 invariant prevents accidental regeneration).
- Reversibility: **yes** — every artifact is additive: `scripts/lib/smoke_lifecycle.py` (new), `scripts/test_release_smoke_ext.py` (new), `scripts/smoke/golden/cli-contract-lifecycle.json` (new), `scripts/fixtures/smoke/lifecycle-base/` (new), `scripts/release_smoke_test.py` (extended in a backward-compat way via `--skip-lifecycle-smoke`). Deleting the new files restores pre-slice behavior identically.
- Migration: **none required**. No on-disk state format change. No CLI surface change. The 11 existing `CASES` entries (lines 16-79) run unchanged.
- Sequencing safety: this plan lands LAST in the 02b slice per CONTRACT-PIN §8.2 "Plans 10 and 11 BLOCK on the completion of plan 09 (T1-M)". If any upstream row reverts, this plan's first failing stage names the reverted row in its diagnostic, allowing the release-gate operator to bisect cleanly.
- Failure-mode behavior: any of the three new stages failing aborts the smoke with non-zero exit, blocking the release per spec §10.2 "Any of the three smoke stages failing fails the slice acceptance." There is no partial-success path; the smoke is binary.
