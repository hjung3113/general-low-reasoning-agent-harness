# Plan — T0-A Atomic Write Primitive

Phase: `02b-hardening` (slice T0-A, dependency-zero, lands FIRST)
Spec: `docs/superpowers/specs/2026-05-16-hardening-slice-design.md` §7 (T0-A row) + §11 (worked example)
ADR: `docs/adr/2026-05-16-hardening-bundle.md` — Artifact 2 (`STATE_FILE_PATHS`, `OPERATIONAL_PATHS`), G1-A (audit.log atomicity), G1-D (`.bak` relocation)
Contract: `.planning/phases/02b-hardening/CONTRACT-PIN.md` §1 (module names), §2 (path-tuple ownership in `scripts/lib/operational_paths.py`), §3 (flat `scripts/test_<module>.py`), §7 (CHANGELOG seeding in FIRST commit).

## Goal (one sentence)
Introduce a single atomic-write helper module (`scripts/lib/atomic_io.py`) that performs `tempfile.NamedTemporaryFile + fsync + os.replace` for managed JSON/text state and `flock + os.write` for the audit-log append, and migrate every existing `path.write_text` call site that targets a path in `STATE_FILE_PATHS ∪ OPERATIONAL_PATHS` so that no partial-write window can corrupt managed state.

## Acceptance (copied verbatim from spec §7 T0-A row and §11 worked example)
- Scope: replace all `path.write_text(...)` calls that target managed JSON state with `NamedTemporaryFile(dir=parent) + fsync + os.replace`. Parent-dir same-filesystem requirement enforced by the helper.
- Acceptance: a single helper exists; every site that previously called `path.write_text` for managed JSON is migrated; a regression test injects a crash between write and replace and asserts the legacy file is intact.
- Acceptance (grep gate cross-reference): the §11 T0-A worked example's grep gate iterates over BOTH the `STATE_FILE_PATHS` list AND the `OPERATIONAL_PATHS` tuple defined by ADR-003a. T0-A MAY land before ADR-003a locks by using the pre-decision defaults `STATE_FILE_PATHS = (".scratch/phase-state.json",)` and `OPERATIONAL_PATHS = ()`; once ADR-003a locks, the grep gate, T1-S, and the uninstall flow MUST be updated in lockstep.
- Required behavior (§11): `write_json_atomic(path, data)` writes to a temp file in `path.parent`, calls `fsync`, then `os.replace(temp, path)`. Helper raises if `path.parent` does not exist or is on a different filesystem (detected via `os.stat().st_dev`). No other site in the repo calls `path.write_text` for a managed JSON state file.
- Audit-log append (ADR G1-A / Artifact 2 §9): `fcntl.flock(LOCK_EX | LOCK_NB)` + single `os.write` of a ≤512-byte line (PIPE_BUF-safe).
- §10 acceptance: at least 1 test injecting a crash between temp-write and `os.replace` and asserting the original file is intact; 1 test asserting the same-filesystem invariant; 1 test asserting the helper rejects non-managed paths (deferred — see Out of scope, the rejection list ships with ADR-003a in T0-3); 1 test for concurrent append non-tearing; 1 grep-gate test.

## Out of scope
- Audit-log rotation at 10 MiB / 10000 entries (G1-A) — ships with T0-3/T1-1, not T0-A. The append helper exposes a hook but does not implement rotation.
- `.bak` `O_EXCL` retention pruning (G1-D / G1-E) — backup-write helper lives with T0-5; T0-A only provides the atomic-write primitive that T0-5 will call.
- Migration of `path.write_text` call sites NOT in `STATE_FILE_PATHS ∪ OPERATIONAL_PATHS` (e.g., installer file copies in `install.py:write_text_file` for managed-append SKILL files). Those are user-facing content writes, not operational/state writes.
- Updating `STATE_FILE_PATHS` / `OPERATIONAL_PATHS` to the ADR-003a-locked shape. T0-A ships with the pre-ADR defaults (`STATE_FILE_PATHS = (".scratch/phase-state.json",)`, `OPERATIONAL_PATHS = ()`) and the grep gate is re-run after ADR-003a in a follow-up commit under T0-3.
- The "rejects non-managed paths" check (§10) — that policy lives with the ADR-003a allowed-writers allowlist (T0-3). T0-A does not gate by caller; it only guarantees atomicity for paths it is invoked against.
- Windows support (§4 declares OOS).
- CLI surface, audit-log schema, `.harness/audit.overflow/` directory creation — ADR-bundle artifacts owned by downstream rows.

## Test list (write tests FIRST, in this order)
Each test = one numbered task. Tests live in `scripts/test_atomic_io.py` (mirroring existing `scripts/test_*.py` convention).

1. `test_atomic_write_text_creates_file_with_content` — happy path: helper creates the target with the exact bytes and the documented mode (default `0o644`).
2. `test_atomic_write_text_replaces_existing_atomically` — pre-populate target with sentinel bytes, run helper, assert target contains new bytes AND no leftover tempfile remains in `path.parent`.
3. `test_atomic_write_text_crash_between_temp_and_replace_preserves_original` — monkeypatch `os.replace` to raise `OSError` after the tempfile has been written and fsync'd; assert the original file is byte-identical to the pre-call state AND the orphan tempfile is cleaned up (or, if cleanup-on-error is descoped, documented). This is the spec §10 mandated crash-injection test.
4. `test_atomic_write_text_rejects_missing_parent_directory` — call helper with `path` whose `path.parent` does not exist; assert it raises with a clear message naming the missing directory.
5. `test_atomic_write_text_rejects_cross_filesystem_parent` — monkeypatch `os.stat` so the tempfile's `st_dev` differs from `path.parent.st_dev`; assert helper raises with a message naming both `st_dev` values. (Spec §11 Required Behavior.)
6. `test_atomic_write_text_handles_disk_full_oserror` — monkeypatch tempfile writes to raise `OSError(ENOSPC)`; assert helper propagates the error AND the original target (if it existed) is unchanged.
7. `test_atomic_write_text_default_mode_is_0o644` — assert `path.stat().st_mode & 0o777 == 0o644` after a fresh write; also assert an explicit `mode=0o600` override is honored.
8. `test_atomic_append_log_creates_file_if_missing` — happy path: appending one line to a non-existent log creates the file with `0o644` and the line plus a trailing newline.
9. `test_atomic_append_log_appends_without_truncating` — write line A, then line B; assert file contains "A\nB\n" exactly.
10. `test_atomic_append_log_refuses_oversized_line` — pass a line whose encoded length (including the trailing newline) exceeds `max_bytes_per_line` (default 512); assert helper raises with a message naming the byte budget and the actual length, AND the log file is unchanged.
11. `test_atomic_append_log_concurrent_writes_dont_tear` — spawn N ≥ 8 worker threads (or multiprocesses) each writing a uniquely-tagged ≤512-byte line K ≥ 50 times; after join, assert (a) total line count equals N×K and (b) every line is structurally intact (no interleaved bytes). Justifies PIPE_BUF + `flock` claim.
12. `test_atomic_append_log_releases_lock_on_exception` — monkeypatch `os.write` to raise mid-call; assert the flock is released (a follow-up append succeeds) and the file is not partially extended beyond what `os.write` reported.
13. `test_grep_gate_fails_when_write_text_added_against_state_path` — synthesize a temp `scripts/` tree containing a planted file with `Path(".scratch/phase-state.json").write_text("x")`, run the grep gate function exported by the test module, assert it reports a violation. Then run the gate against the real `scripts/` tree post-migration and assert zero violations.

## Implementation tasks (in order)
Each task is one RED→GREEN cycle. Tasks 1–12 implement the helper; tasks 13–17 migrate call sites; task 18 wires the grep gate; task 19 is full-suite regression.

1. Add `scripts/lib/atomic_io.py` module skeleton with empty `atomic_write_text(path, content, *, mode=0o644)` and `atomic_append_log(path, line, *, max_bytes_per_line=512)` signatures (RED for tests 1–12).
2. Implement `atomic_write_text` happy-path body using `tempfile.NamedTemporaryFile(dir=parent, delete=False, mode="w", encoding="utf-8")` + `f.flush()` + `os.fsync(f.fileno())` + `os.replace(tmp.name, path)` + `os.chmod(path, mode)` (GREEN for test 1).
3. Add atomic replace + tempfile cleanup-on-success (GREEN for test 2).
4. Add error path: wrap `os.replace` so that a raised `OSError` triggers `os.unlink(tmp.name)` and re-raises (GREEN for test 3).
5. Add `path.parent.exists()` precondition check (GREEN for test 4).
6. Add same-filesystem invariant: compare `os.stat(path.parent).st_dev` to `os.stat(tmp.name).st_dev`; raise `RuntimeError` naming both devices (GREEN for test 5).
7. Add disk-full propagation path: ensure tempfile is unlinked when the inner `write` raises (GREEN for test 6).
8. Plumb the `mode` parameter through to `os.chmod` (GREEN for test 7).
9. Implement `atomic_append_log` open path: `os.open(path, O_WRONLY | O_APPEND | O_CREAT, 0o644)` (GREEN for test 8).
10. Add the no-truncation guarantee + trailing-newline normalization (GREEN for test 9).
11. Add the `max_bytes_per_line` precondition check BEFORE acquiring the lock (GREEN for test 10).
12. Add `fcntl.flock(fd, LOCK_EX | LOCK_NB)` + single `os.write(fd, line.encode("utf-8"))` + `try/finally` releasing the lock and closing the fd (GREEN for tests 11–12).
13. Migrate `scripts/lib/state.py` `write_json` (line 67–69) — replace `path.write_text(...)` with `atomic_write_text(path, json.dumps(...) + "\n")`. This is the single in-scope core call site; it is the writer for `.harness/installed-manifest.json` (operational install state). NOTE: `INSTALL_STATE` (`.harness/installed-manifest.json`) is NOT currently in `OPERATIONAL_PATHS` per the pre-ADR defaults; T0-A still migrates this site because the helper is functionally a drop-in upgrade and the spec §3 motivation (partial-write corruption) applies. Update the grep gate's tracked path tuple when ADR-003a locks (out-of-scope follow-up).
14. Migrate `scripts/lib/state_repair.py:240` (`roadmap_path.write_text(new_roadmap, encoding="utf-8")`) — replace with `atomic_write_text(roadmap_path, new_roadmap)`.
15. Migrate `scripts/lib/state_repair.py:248` (`state_path.write_text(new_state, encoding="utf-8")`) — replace with `atomic_write_text(state_path, new_state)`.
16. Audit `scripts/lib/install.py:132–141` (`write_text_file` / `write_text_conflict`). These are SKILL-pack content writers, NOT state/operational paths; per the Out-of-scope list, leave unchanged BUT add a comment referencing this plan + grep gate to document the deliberate exclusion. (No behavior change.)
17. Audit `scripts/lib/upgrade.py:184` and `:235` (`write_text_file(destination, result.updated_text)`). These re-enter `install.write_text_file`, so the audit in task 16 covers them; no edit required. Document the call chain in a comment near `upgrade.py:20` import block.
18. Add the grep-gate function in `scripts/test_atomic_io.py` (or a sibling helper). The gate: read `STATE_FILE_PATHS`, `OPERATIONAL_PATHS`, and `INSTALL_PATHS` from `scripts/lib/operational_paths.py` (sole declaration site per CONTRACT-PIN §2; T0-A creates the file with the post-ADR pinned values from CONTRACT-PIN §2); recursively scan `scripts/` for lines matching `r"\.write_text\("` AND containing any literal path string from any tuple; emit a violation per match. The test asserts zero violations against the live tree and one violation against the synthesized fixture (test 13). Do NOT duplicate tuple literals anywhere else.
19. Run full test suite + harness self-check, fix any regressions exposed by the in-place rewrite (e.g., tests that mocked `Path.write_text` need to mock `atomic_io.atomic_write_text` instead).

## Dependency on other slices
- Provides: `atomic_write_text` interface, consumed by T0-1 (migrator state writes), T0-3 (CLI transition writes), T0-5 (`state_repair` rewrites + `.bak` writes), and the audit-log append protocol used by T1-1 (`check --worktree`). Also provides `STATE_FILE_PATHS` / `OPERATIONAL_PATHS` tuples in their pre-ADR shape; T0-3 owns the post-ADR update.
- Depends on: none. T0-A is dependency-zero per spec §7.
- Coordination: when ADR-003a locks, a follow-up one-line PR (NOT part of T0-A) updates the tuples in `scripts/lib/atomic_io.py` to the ADR-003a-published shape and re-runs the grep gate.

## Verification commands
Run from repo root:
- `python3 -m unittest scripts.test_atomic_io` — the new test module (tests 1–13).
- `python3 -m unittest discover scripts/ -t .` — full self-test suite; expect zero regressions (existing `test_state_repair.py`, `test_harness.py`, etc.).
- `python3 scripts/harness.py check` — harness self-check still green.
- `python3 scripts/harness.py doctor` — verifies installed-manifest read/write round-trips through the new helper.
- Manual grep cross-check: `rg -n 'write_text\(' scripts/lib/state.py scripts/lib/state_repair.py` should show zero hits against the migrated paths.

## Commits (atomic, in order)
One commit per RED→GREEN cycle; squash only if a test required a follow-up correction.

Per `CONTRACT-PIN.md` §1 the helper module is `scripts/lib/atomic_io.py` with exports `atomic_write_text(path, content, *, mode=0o644)` and `atomic_append_log(path, line, *, max_bytes_per_line=512)`. Path tuples `STATE_FILE_PATHS`, `OPERATIONAL_PATHS`, and `INSTALL_PATHS` live ONLY in `scripts/lib/operational_paths.py` (§2). Tests are flat at `scripts/test_*.py` (§3). Note: the verbatim test snippet inside Task 1 importing `from scripts.tests.test_operational_paths` is illustrative ONLY; the actual files live at `scripts/test_operational_paths.py` per CONTRACT-PIN §3.

0. `docs(changelog): seed ## Unreleased (develop) → ### Breaking skeleton for T0-A` — CHANGELOG seeding commit per CONTRACT-PIN §7. T0-A owns no ledger entries itself, but lands the `### Breaking` heading skeleton so downstream slices can append their L# rows from their FIRST commits without merge races. This commit happens FIRST, before any test/code commit below.
1. `test(atomic_io): RED for atomic_write_text basic happy path` (test 1)
2. `feat(atomic_io): atomic_write_text via tempfile+fsync+replace` (impl tasks 2–3, GREEN tests 1–2)
3. `test(atomic_io): RED for crash-between-temp-and-replace preserves original` (test 3)
4. `feat(atomic_io): unlink tempfile on os.replace failure` (impl task 4)
5. `test(atomic_io): RED for missing-parent + cross-fs + disk-full` (tests 4–6)
6. `feat(atomic_io): preconditions (parent exists, same-fs, ENOSPC propagation)` (impl tasks 5–7)
7. `test(atomic_io): RED for mode parameter honored` (test 7)
8. `feat(atomic_io): plumb mode through to os.chmod` (impl task 8)
9. `test(atomic_io): RED for atomic_append_log create + append + no-tear` (tests 8–9)
10. `feat(atomic_io): atomic_append_log via O_APPEND + flock + os.write` (impl tasks 9–10)
11. `test(atomic_io): RED for oversized line refusal + lock release on error` (tests 10, 12)
12. `test(atomic_io): RED for concurrent append non-tearing (threading + subprocess SIGKILL)` (test 11 — RED MUST land before impl)
13. `feat(atomic_io): enforce max_bytes_per_line, release flock on exception, and finalize concurrent-safe append semantics (flock+os.write)` (impl tasks 11–12; GREEN for tests 10–12). Reorder rationale: per user adversarial review, the threading RED for non-tear must precede the flock+os.write GREEN; previous draft swapped these so the impl shipped first.
14. `test(atomic_io): RED for subprocess+SIGKILL crash injection (out-of-process integration)` — adds an out-of-process integration test that spawns a child writing via `atomic_append_log`, sends `SIGKILL` mid-batch, then asserts every persisted line parses. Marked as out-of-process integration test (skipped on platforms without `fork()`).
15. `refactor(state): route write_json through atomic_write_text` (impl task 13)
16. `refactor(state_repair): atomic writes for STATE.md and ROADMAP.md rewrites` (impl tasks 14–15)
17. `docs(install,upgrade): annotate deliberate non-migration of SKILL content writers` (impl tasks 16–17, comments only)
18. `test(atomic_io): grep gate for write_text against STATE/OPERATIONAL paths` (impl task 18, test 13). The grep gate imports `STATE_FILE_PATHS` / `OPERATIONAL_PATHS` / `INSTALL_PATHS` from `scripts/lib/operational_paths.py` (NOT from `atomic_io.py`); the tuples are declared in `operational_paths.py` per CONTRACT-PIN §2.
19. `chore(atomic_io): regression sweep — full suite + harness check pass` (impl task 19; only if existing tests need helper-mock updates)

## Risk + reversibility
- Risk: **L (low)** — isolated helper module, no protocol/schema change, no on-disk format change, no CLI surface change. Helper is additive; migrated call sites are functionally equivalent under the no-crash case.
- Reversibility: **yes** — every call-site migration is a one-line revert; the helper module can be deleted. No on-disk artifact records that atomic-write was used, so a downgrade leaves no migration debt.
- Migration: **none required**. Pre-existing `.scratch/phase-state.json` and `.harness/installed-manifest.json` files are read with the same `json.loads` path and rewritten through the new helper on the next state-mutating operation; no schema bump, no `.bak`, no version bump.
- Sequencing safety: T0-A lands first per spec §8 critical path; no other in-flight slice can introduce a new `write_text` call site against a state path because the grep gate (task 18) will fail CI for that PR.
