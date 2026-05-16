# Plan — T1-M Malformed State Diagnostic + Crash Prevention

Phase: `02b-hardening` (slice T1-M, independent of T0-1/T0-2/T0-3/T0-4/T0-5, may land any time after the ADR session)
Spec: `docs/superpowers/specs/2026-05-16-hardening-slice-design.md` §7 (T1-M row) + per-row note §7 "T1-M (malformed state recovery)" + §9.4 ("at least 1 test per failure class") + the Realist Minor 3 follow-up explicitly putting STATE.md frontmatter parsing in T1-M's blast radius
ADR: `docs/adr/2026-05-16-hardening-bundle.md` — ADR-005 (state_repair refuses on unparseable input; quoted diagnostic copy) + ADR-003a Artifact 1 exit-code table (exit 5 = unparseable JSON; exit 1 = generic IO/parse for non-JSON; the canonical CLI error template lines 497, 420)

## Goal (one sentence)
Replace every bare `json.loads(...)` / `parse_blocks(...)` / `parse_frontmatter(...)` call against managed harness state (`.scratch/phase-state.json`, `.planning/STATE.md`, `.planning/ROADMAP.md`, `.harness/installed-manifest.json`) with a single diagnostic-emitting helper module so that any malformed input produces a structured `error:` line naming the file (plus line:column when available) and a one-line remediation hint, exits with the ADR-003a code 5, and NEVER raises an uncaught `JSONDecodeError`, `ValueError`, or `KeyError` that surfaces as a traceback to the operator.

## Acceptance (copied verbatim from spec §7 T1-M row + per-row note + ADR-005)
- Spec §7 T1-M row: "Malformed state recovery: `phase-state.json` parse failures, duplicate slugs, broken roadmap produce diagnostic exit not traceback; `state_repair` refuses on unparseable input".
- Per-row note: "No ADR dependency: 'do not crash on malformed input' is not a decision; only the diagnostic copy is, and diagnostic copy does not gate code. Acceptance: `state_repair` MUST refuse to rewrite when `phase-state.json` is unparseable (current code at `scripts/lib/state_repair.py:197` swallows `JSONDecodeError` and proceeds with empty dict — that is the defect). This acceptance is shared with T0-5."
- ADR-005 §4: "If `phase-state.json` is unparseable (`JSONDecodeError`), `state_repair` aborts with exit code 5 ... and the diagnostic: `error: .scratch/phase-state.json is unparseable ({exc}); fix the JSON or restore from a backup before running 'harness state repair'`."
- ADR-003a Artifact 1 error template: `error: .scratch/phase-state.json is unparseable ({exc}); fix the JSON or restore from a backup before retrying.` → exit 5.
- §9.4 coverage floor: "T1-M: at least 1 test per failure class (malformed JSON, duplicate managed-block slug, unparseable roadmap heading)."

## Out of scope
- Implementing the `harness migrate state --resume` verb itself — that ships with T0-1. T1-M only references the verb by name in the diagnostic when a sidecar at `.harness/backups/<basename>.pre-repair.*.bak.resume.json` is present on disk.
- Implementing the `.bak` writer or `.harness/backups/` retention pruner — ships with T0-5 (consumer of T0-A). T1-M only listens to the directory and surfaces "restore from `.harness/backups/<NAME>`" when a backup exists.
- The `state_repair` refuse-on-unparseable behavior at `state_repair.py:197` itself — that line is owned by T0-5 per the per-row note ("This acceptance is shared with T0-5."). T1-M does NOT re-implement it; T1-M routes T0-5's diagnostic through the shared helper introduced here so both rows emit byte-identical copy. Implementation order: T0-5 lands the raise; T1-M migrates the raise site to call the shared helper. If T1-M lands first, the helper is added but `state_repair.py:197` retains the current swallow until T0-5 lands. The TWO rows COORDINATE on the diagnostic string; they do not overlap on the swallow→raise rewrite.
- Schema validation (jsonschema, pydantic). T1-M asserts only "JSON parses" + "managed-block invariants hold" + "frontmatter delimiters match". Field-level validation lives with the consumer (e.g., `validate_installed_scope_names`).
- CLI argv parsing / argparse errors. Those already exit cleanly via argparse.
- Windows pathing (§4 declares OOS).
- Migration of `json.loads` sites in install/upgrade content readers (`install.py:66`, `manifest.py:164`) — these read SOURCE manifests, not managed state; their failures are user-content bugs, not state-corruption bugs. They get a deferred follow-up note, not a migration.

## Test list (write tests FIRST, in this order)
Each test = one numbered task. Tests live in a new `scripts/test_malformed_state.py` (mirroring existing `scripts/test_*.py` convention). Helper module: `scripts/lib/state_diagnostics.py`.

1. `test_load_state_json_returns_dict_on_valid_input` — happy path: helper reads a valid `phase-state.json`, returns the parsed dict, no diagnostic.
2. `test_load_state_json_truncated_raises_systemexit_5_with_file_line_col` — write `{"phase": "exec` (truncated mid-string), call helper, assert `SystemExit` with `code == 5` AND the rendered stderr line contains the absolute path, `:line:col` from `JSONDecodeError.lineno`/`colno`, AND the suggested-fix sentence.
3. `test_load_state_json_empty_file_raises_systemexit_5` — create a zero-byte `phase-state.json`, call helper, assert `SystemExit(5)` with diagnostic "empty file" (NOT a silently-returned empty dict). This guards against the historical foot-gun where empty JSON became `{}`.
4. `test_load_state_json_diagnostic_suggests_resume_when_sidecar_present` — create `.harness/backups/phase-state.json.pre-repair.2026-05-16T19:30:45.123456789Z.12345.bak.resume.json`, parse a broken state file, assert the diagnostic contains `harness migrate state --resume`. Per ADR-bundle line 265 the "(b) run 'harness migrate state --resume'" remediation is the canonical recovery when a sidecar exists.
5. `test_load_state_json_diagnostic_lists_backups_when_present_and_no_sidecar` — create three `.harness/backups/phase-state.json.pre-repair.*.bak` files (no sidecar), parse a broken state, assert the diagnostic lists the most-recent backup filename (sorted lexically per ADR-005 sub-decision; we only quote the newest to keep the message short).
6. `test_load_state_json_diagnostic_omits_resume_and_backups_when_neither_present` — no `.harness/backups/`, parse a broken state, assert the diagnostic contains the bare "fix the JSON or restore from a backup" template (ADR-005 line 420) and does NOT invent a nonexistent file path.
7. `test_parse_managed_blocks_duplicate_slug_raises_systemexit_5_with_two_line_refs` — synthesize STATE.md containing two `<!-- HARNESS:BEGIN managed:foo v1 -->` lines (the existing `managed_block.parse_blocks` already raises `ValueError("Duplicate managed-block slug: ...")`), call the new wrapper, assert `SystemExit(5)` AND the stderr cites BOTH line numbers of the duplicate BEGIN markers AND the slug name AND the file path.
8. `test_parse_managed_blocks_unbalanced_markers_raises_systemexit_5` — STATE.md with a BEGIN but no matching END (existing parser raises `ValueError("Unbalanced managed-block markers")`); assert `SystemExit(5)` AND the diagnostic names the file AND the offending BEGIN line number.
9. `test_parse_managed_blocks_invalid_slug_raises_systemexit_5` — STATE.md with `managed:Foo_BAD v1` (uppercase/underscore, rejected by `_SLUG_RE` in `managed_block.py:12`); assert `SystemExit(5)` naming file, line, and the offending slug literal.
10. `test_parse_state_frontmatter_unclosed_delimiter_raises_systemexit_5` — STATE.md with `---\nphase: 1\n` (no closing `---`); assert `SystemExit(5)` naming file + frontmatter start line + a suggestion to add a closing `---`. (Per Realist Minor 3: frontmatter parsing is in scope; current `parse_frontmatter` at `roadmap_state.py:82` silently returns partial data when the closing delimiter is missing.)
11. `test_parse_state_frontmatter_valid_then_invalid_body_partial_warning` — STATE.md with a VALID frontmatter block followed by a managed-block body that fails `parse_blocks`; assert `SystemExit(5)` with a diagnostic that (a) acknowledges the frontmatter parsed, (b) names the body-section failure with line number, (c) does NOT discard the frontmatter content from the error context (so the operator knows where to look). This is the "partial valid + warning" branch from the prompt's test list.
12. `test_check_phase_state_paths_does_not_crash_on_malformed_state` — call `check.check_phase_state_paths` (the `check.py:481` site) against a truncated state file; assert `SystemExit(5)` with the structured diagnostic, NOT an uncaught `JSONDecodeError` traceback. Same assertion for `worktree.check_changed_paths` (worktree.py:16) and `worktree.check_worktree_paths` (worktree.py:32).
13. `test_state_repair_when_phase_state_unparseable_emits_t1m_diagnostic` — coordination test with T0-5: feed `state_repair.run` an unparseable phase-state, assert it routes through the shared helper and exits 5 with the ADR-005 line-420 diagnostic copy verbatim. SKIP if T0-5 has not landed; the test asserts a clear skip reason naming the cross-row dependency.
14. `test_no_uncaught_exception_on_any_malformed_input_fuzz` — table-driven: feed the parse helper a sequence of malformed inputs (`""`, `"\x00"`, `"{"`, `"]"`, `"\xff\xfe"` invalid UTF-8, 1MiB of `"a"`, `"null"`, `"[]"`, `'{"phase":}'`); assert NO raise of any exception other than `SystemExit(5)`. This is the spec §7 "diagnostic exit not traceback" sweep.
15. `test_diagnostic_format_is_single_line_under_200_chars` — assert every diagnostic emitted in tests 2-13 fits on one stderr line ≤200 chars (low-reasoning agent fit: the operator should be able to read the whole message without scrolling). Multi-line diagnostics use `\n  hint: ...` continuation form with the second line ≤120 chars.
16. `test_grep_gate_no_bare_json_loads_on_state_paths_outside_helper` — synthesize a fixture file with `json.loads(Path(".scratch/phase-state.json").read_text(...))`; run the gate function; assert violation. Run the gate against the real `scripts/lib/` post-migration; assert zero violations EXCEPT inside `scripts/lib/state_diagnostics.py` itself (the one allowed call site).

## Implementation tasks (in order)
Each task is one RED→GREEN cycle. Tasks 1-8 build the helper module; tasks 9-15 migrate call sites; task 16 wires the grep gate; task 17 is the regression sweep.

1. Add `scripts/lib/state_diagnostics.py` module skeleton exporting `load_state_json(path: Path) -> dict`, `parse_state_markdown(path: Path) -> ParsedStateDoc`, `EXIT_UNPARSEABLE_JSON = 5`, and a private `_format_diagnostic(file, line, col, what, hint)` (RED for tests 1-11).
2. Implement `load_state_json` happy path: `text = path.read_text(encoding="utf-8")`; if `text == ""` raise `SystemExit(5)` with "empty file" diagnostic; else `return json.loads(text)` (GREEN for tests 1, 3).
3. Wrap `json.loads` in `try/except json.JSONDecodeError as exc`; render diagnostic `f"error: {path} is unparseable at line {exc.lineno}:col {exc.colno}: {exc.msg}; fix the JSON or restore from a backup before retrying."` (matches ADR-003a line 497 template, with the line:col extension), raise `SystemExit(5)` (GREEN for test 2).
4. Implement sidecar detection: scan `path.parent.parent / "backups"` (i.e., `.harness/backups/`) for `{path.name}.pre-repair.*.bak.resume.json`; if any match, append `\n  hint: run 'harness migrate state --resume' to continue from the most recent in-progress migration.` (GREEN for test 4).
5. Implement backup-listing fallback: if no sidecar but at least one `{path.name}.pre-repair.*.bak`, append `\n  hint: restore from .harness/backups/{newest_bak_name}` (lexicographic sort, take last) (GREEN for test 5).
6. Default branch when neither sidecar nor backups exist: use ADR-005 line-420 copy verbatim (GREEN for test 6).
7. Implement `parse_state_markdown(path)`: read text; wrap `parse_frontmatter` to detect unclosed `---` (count delimiter occurrences; if first line is `---` but no second `---` before EOF, raise `SystemExit(5)` naming the start line and suggesting "add a closing `---` line"); then wrap `managed_block.parse_blocks` in try/except `ValueError` and translate each known error message into a `SystemExit(5)` diagnostic that names the file and the offending line number(s). Use the existing `_BLOCK_RE` pattern to re-locate BEGIN markers for line-number reporting (GREEN for tests 7-11).
8. For duplicate-slug detection, the existing `parse_blocks` raises on first duplicate; the wrapper re-scans the text with `re.finditer(r"^<!-- HARNESS:BEGIN managed:(?P<slug>[a-z][a-z0-9-]*) v1 -->$", text, re.MULTILINE)` and collects ALL line numbers where the duplicated slug appears, so the diagnostic can cite both lines (GREEN for test 7's "two line refs" assertion).
9. Migrate `scripts/lib/check.py:481` (`check_phase_state_paths`): replace `state = json.loads(state_path.read_text(...))` with `state = load_state_json(state_path)` (GREEN for half of test 12).
10. Migrate `scripts/lib/worktree.py:16` (`check_changed_paths`) and `:32` (`check_worktree_paths`): same replacement; remove the now-unused `import json` from the function bodies, hoist to module scope if needed (GREEN for rest of test 12).
11. Migrate `scripts/lib/check.py:202` (`check_installed_target` reads `installed-manifest.json`): `installed = load_state_json(installed_path)`. (Companion migration; `installed-manifest.json` is managed state per `STATE_FILE_PATHS`.)
12. Migrate `scripts/lib/state.py:234` (`read_install_state`): same replacement.
13. Migrate `scripts/lib/roadmap_state.py:159` and `:189` (the two `phase_state = json.loads(...)` sites in the sync-applicable + diff helpers): same replacement.
14. T0-5 coordination point: edit `scripts/lib/state_repair.py:197` to call `load_state_json` instead of the bare `json.loads` + `except`/`warnings.append` swallow. If T0-5 has already landed the raise, change the raise to use the shared helper for diagnostic-copy parity. If T0-5 has NOT landed, this task is RED (test 13 SKIPped) and is completed by T0-5's PR — leave a `# TODO(T0-5):` comment naming this plan. (No overlap: T0-5 picks WHEN to raise; T1-M picks the WORDS.)
15. Migrate the managed-block parse sites in `state_repair.py` (`parse_blocks(roadmap_text)` line ~242, `parse_blocks(state_text)` line ~224) to route through `parse_state_markdown` for diagnostic shape consistency (GREEN for tests 7-11 when invoked through `state repair`). Frontmatter handling enters via `parse_state_snapshot` in `roadmap_state.py:126` — wrap that call in the helper as well so the Realist Minor 3 scope (frontmatter) is fully covered.
16. Add the grep-gate function in `scripts/test_malformed_state.py`: scan `scripts/lib/**/*.py` for `r"json\.loads\("` AND any literal from `("phase-state.json", "installed-manifest.json", "STATE.md", "ROADMAP.md")`; report violations EXCEPT for `scripts/lib/state_diagnostics.py` itself (the single sanctioned call site). Also gate `parse_blocks(` and `parse_frontmatter(` against the same file allowlist (GREEN for test 16).
17. Run full test suite + `python3 scripts/harness.py check` + `python3 scripts/harness.py doctor`; ensure no existing test that synthesized malformed state expecting an uncaught exception now fails — rewrite such tests to expect `SystemExit(5)`. Spot-check `scripts/test_state_repair.py`, `scripts/test_check.py`, `scripts/test_worktree.py`.

## Dependency on other slices
- Provides: `load_state_json`, `parse_state_markdown`, `EXIT_UNPARSEABLE_JSON` consumed by T0-5 (the swallow→raise rewrite at `state_repair.py:197` uses this helper for diagnostic-copy parity) and T0-3 (the CLI verbs' `--stdin-json` parser also exits 5 per Artifact 1; T0-3 SHOULD route through the same helper, but T1-M does not block on this).
- Depends on: none structurally. Touches existing parse sites only. Coordinates with T0-5 on `state_repair.py:197` (task 14) — neither row blocks the other; landing order determines which PR contains the final swallow→raise edit.
- Consumes T0-A indirectly: the helper does NOT write anything (read-only); the only files it inspects on the rewrite path are `.harness/backups/` for sidecar detection (read-only `os.listdir`).
- Cross-reference: §10.2 smoke harness golden file (produced by T0-3) MUST include the ADR-003a line-497 exit-5 diagnostic copy verbatim. T1-M's task 3 diagnostic string is the source of truth for that golden line.

## Verification commands
Run from repo root:
- `python3 -m unittest scripts.test_malformed_state` — the new test module (tests 1-16).
- `python3 -m unittest discover scripts/ -t .` — full self-test suite; expect zero regressions.
- `python3 scripts/harness.py check` — harness self-check still green against the live (well-formed) `.scratch/phase-state.json`.
- Manual malformed-input smoke: `cp .scratch/phase-state.json /tmp/good.json && echo '{' > .scratch/phase-state.json && python3 scripts/harness.py check; echo "exit=$?"; mv /tmp/good.json .scratch/phase-state.json` — expect single-line `error:` on stderr and `exit=5`, NOT a traceback.
- Grep cross-check: `rg -n 'json\.loads\(' scripts/lib/ | grep -v 'state_diagnostics.py' | grep -E '(phase-state|installed-manifest|STATE\.md|ROADMAP\.md)'` should print zero lines.

## Commits (atomic, in order)
One commit per RED→GREEN cycle; squash only if a test required a follow-up correction.

1. `test(state_diagnostics): RED for load_state_json happy + empty + truncated` (tests 1-3)
2. `feat(state_diagnostics): load_state_json with exit-5 diagnostic for parse failures` (impl tasks 1-3)
3. `test(state_diagnostics): RED for sidecar + backup-listing remediation hints` (tests 4-6)
4. `feat(state_diagnostics): sidecar detection and backup-listing in diagnostic` (impl tasks 4-6)
5. `test(state_diagnostics): RED for duplicate slug + unbalanced markers + invalid slug` (tests 7-9)
6. `feat(state_diagnostics): parse_state_markdown wraps managed_block with line-cited diagnostics` (impl tasks 7-8)
7. `test(state_diagnostics): RED for unclosed frontmatter + partial-valid body` (tests 10-11)
8. `feat(state_diagnostics): frontmatter delimiter validation with start-line citation` (impl task 7 frontmatter branch)
9. `refactor(check,worktree): route phase-state.json reads through load_state_json` (impl tasks 9-10, GREEN test 12)
10. `refactor(state,check): route installed-manifest.json reads through load_state_json` (impl tasks 11-12)
11. `refactor(roadmap_state): route sync-applicable + diff phase-state reads through helper` (impl task 13)
12. `refactor(state_repair): route phase-state read + managed-block parses through state_diagnostics` (impl tasks 14-15; coordinates with T0-5)
13. `test(state_diagnostics): RED for fuzz sweep + diagnostic single-line constraint` (tests 14-15)
14. `feat(state_diagnostics): finalize diagnostic format to satisfy fuzz + format constraints` (any fixes surfaced by tests 14-15)
15. `test(state_diagnostics): grep gate for bare json.loads on state paths` (impl task 16, test 16)
16. `chore(state_diagnostics): regression sweep — rewrite tests expecting raw exceptions to expect SystemExit(5)` (impl task 17; only if existing tests need updates)

## Risk + reversibility
- Risk: **L (low)** — read-only helper; every migration is a one-line drop-in (`json.loads(x)` → `load_state_json(x)`); no schema change; no on-disk format change; no CLI surface change. The only behavioral shift is exit codes for currently-uncaught exception paths, which are by definition not depended upon (a traceback is not a contract).
- Reversibility: **yes** — every call-site migration is a one-line revert; the helper module can be deleted. No on-disk artifact records the diagnostic format.
- Migration: **none required**. Existing well-formed state files round-trip through the helper identically to `json.loads`. The only observable change is for malformed files, where the previous behavior was a traceback or `{}`.
- Sequencing safety: T1-M can land in either order with T0-5. If T1-M lands first, `state_repair.py:197` keeps its current swallow until T0-5 lands (test 13 SKIPped, no regression). If T0-5 lands first, T1-M's task 14 reduces to a one-line edit to use the shared diagnostic. The grep gate (task 16) prevents any new PR from re-introducing a bare `json.loads` against a managed state path.
