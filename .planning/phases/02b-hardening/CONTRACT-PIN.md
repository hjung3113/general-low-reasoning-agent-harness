# CONTRACT-PIN: 02b-hardening Cross-Plan Interface Contracts

**Status:** Pinned. Single source of truth for cross-plan interfaces in phase 02b.
**Created:** 2026-05-16
**Resolves:** G1 drift identified in plan review across `02b-01-T0-A-PLAN.md` through `02b-09-T1-M-PLAN.md`.
**Authority:** This file overrides any conflicting language in individual plan files. If a plan disagrees with this document, the plan is wrong and must be corrected before execution.
**Parent decisions:** `docs/adr/2026-05-16-hardening-bundle.md` (Artifact 1, Artifact 2, Artifact 6).

---

## 0. Purpose

The nine plan files in `.planning/phases/02b-hardening/plans/` were authored in parallel by different drafting passes and drifted on:

- module filenames (singular vs. plural, location under `scripts/lib/` vs `scripts/`)
- which path-tuple module owns the canonical literal values
- exit-code semantics (in particular code 4, which was reserved in early drafts then claimed by T1-1)
- test-directory layout (`scripts/tests/` vs flat `scripts/test_*.py`)
- ownership of disputed source lines (notably `state_repair.py:197`)
- which plan adds Breaking Ledger entries to `CHANGELOG.md`
- ownership of new files (`.roo/commands/done.md`, `.gitignore` entries, uninstall flag implementations)

This file pins the canonical answer for each. Cross-plan PRs MUST cite the section of this file they are honoring.

---

## 1. Module Names (Canonical Paths)

All modules live under `scripts/lib/` unless otherwise noted. Filenames are pinned; plans that name them differently are stale.

| Module | Path | Exports | Owning plan |
|---|---|---|---|
| Atomic I/O primitives | `scripts/lib/atomic_io.py` | `atomic_write_text(path, content, *, mode=0o644)`, `atomic_append_log(path, line, *, max_bytes_per_line=512)` | `02b-01-T0-A-PLAN.md` |
| Path tuples (source of truth) | `scripts/lib/operational_paths.py` | `STATE_FILE_PATHS`, `OPERATIONAL_PATHS`, `INSTALL_PATHS` | `02b-01-T0-A-PLAN.md` |
| Phase transition table | `scripts/lib/transition.py` (singular) | `validate_transition(from_phase, to_phase, approved)`, `TRANSITION_TABLE` | `02b-02-T0-1-PLAN.md` |
| Exit codes | `scripts/lib/exitcodes.py` | `EXIT_*` constants per ADR-003a Artifact 1 (post-amendment) | `02b-04-T0-3-PLAN.md` |
| Session lockfile lifecycle | `scripts/lib/session.py` | `acquire_lock()`, `release_lock()`, `read_lock()`, `is_lock_stale()` | `02b-04-T0-3-PLAN.md` |
| Audit log writer | `scripts/lib/audit.py` | `audit_append(verb, args, before_sha, after_sha, *, at=None, by=None)`, `rotate_if_needed()` | `02b-04-T0-3-PLAN.md` |
| Backup helper | `scripts/lib/backups.py` | `write_backup(src_path, *, label, retention=10)` (O_EXCL + prune); shared by T0-1 migrator and T0-5 state_repair | `02b-06-T0-5-PLAN.md` |
| Malformed-state diagnostics | `scripts/lib/state_diagnostics.py` | `load_state_json(path) -> dict`, raises `UnparseableStateError` | `02b-09-T1-M-PLAN.md` |
| Forward/reverse state migrator | `scripts/lib/state_migrate.py` | `forward(state) -> dict`, `reverse(state) -> dict`, `migrate(path, *, direction, resume=False)` | `02b-02-T0-1-PLAN.md` |
| Phase CLI verb dispatch | `scripts/lib/phase_cli.py` | `cmd_phase_set(argv)`, `cmd_phase_approve(argv)`, `cmd_session_unlock(argv)` | `02b-04-T0-3-PLAN.md` |

**Rule:** `operational_paths.py` is the sole declarer of the path-tuple literals. T0-A's grep gate (`scripts/check_path_writers.py` or equivalent) imports from this module. If `02b-01-T0-A-PLAN.md` chooses to re-export the names from another helper (`scripts/lib/paths.py`), the re-export must be a simple `from .operational_paths import *` — no duplication of literals.

**Rule:** `transition.py` is singular, not `transitions.py`. Plans that say "transitions" are wrong; correct on first commit touching the file.

**Rule:** the `EXIT_*` constants live ONLY in `scripts/lib/exitcodes.py`. No other module may define a numeric exit-code literal. This includes test files: tests MUST `from scripts.lib.exitcodes import EXIT_SCOPE_VIOLATION` rather than asserting `== 4`. The grep gate in `02b-01-T0-A-PLAN.md` greps `scripts/**/*.py` (excluding `scripts/lib/exitcodes.py` and `scripts/test_exitcodes.py`) for `sys.exit\([0-9]\)` and `return [0-9]$` patterns at function tails of CLI entry points — violations block T0-A.

**Per-plan citations (which plan creates which module first):**

- `02b-01-T0-A-PLAN.md` creates `atomic_io.py`, `operational_paths.py`, `exitcodes.py` (stub with all constants), and the grep-gate runner. T0-A is dependency-zero; every other plan imports from these.
- `02b-02-T0-1-PLAN.md` creates `transition.py`, `state_migrate.py`, depends on `atomic_io.py` from T0-A.
- `02b-03-T0-2-PLAN.md` modifies `scripts/lib/check.py` (existing) for `fnmatch` activation; no new module.
- `02b-04-T0-3-PLAN.md` creates `phase_cli.py`, `session.py`, `audit.py`; populates `exitcodes.py` semantics; consumes `transition.py` from T0-1.
- `02b-05-T0-4-PLAN.md` modifies `scripts/lib/check.py` for the 7-verb allowlist; no new module.
- `02b-06-T0-5-PLAN.md` creates `backups.py`; modifies existing `scripts/lib/state_repair.py`.
- `02b-07-T1-1-PLAN.md` modifies `scripts/lib/check.py` for scope enforcement; uses `EXIT_SCOPE_VIOLATION` from T0-A's stub `exitcodes.py`.
- `02b-08-T1-S-PLAN.md` modifies adapter command files; no new `scripts/lib/` module.
- `02b-09-T1-M-PLAN.md` creates `state_diagnostics.py`; T0-5 imports from it (see §5.1).

---

## 2. Path-Tuple Literal Values

These are the canonical values, owned by `scripts/lib/operational_paths.py`. They are an exact copy of ADR Artifact 2 with no additions. Any plan that introduces a fourth tuple, a new entry, or a renamed key is wrong.

```python
# scripts/lib/operational_paths.py

STATE_FILE_PATHS = (
    ".scratch/phase-state.json",
)

OPERATIONAL_PATHS = (
    ".harness/audit.log",
    ".harness/session.lock",
    ".harness/backups/",
)

INSTALL_PATHS = (
    ".harness/installed-manifest.json",
)
```

**Drift sites resolved:**
- `02b-01-T0-A-PLAN.md` — pins the writer (this file).
- `02b-04-T0-3-PLAN.md` — consumes `OPERATIONAL_PATHS` for `.gitignore` and uninstall flag implementation; MUST NOT re-declare.
- `02b-06-T0-5-PLAN.md` — consumes `.harness/backups/` from `OPERATIONAL_PATHS`; MUST NOT re-declare.
- `02b-07-T1-1-PLAN.md` (scope enforcement) — reads `STATE_FILE_PATHS` for scope checks but does not write them.

**Allowed writers** (T0-A grep gate enforces): identical to ADR Artifact 2. No additions in this phase.

---

## 3. Test Directory Convention

**All slice tests live FLAT at `scripts/test_<module>.py`. NOT under `scripts/tests/`.**

| Convention | Pinned value | Notes |
|---|---|---|
| Test files | `scripts/test_<module>.py` | e.g., `scripts/test_atomic_io.py`, `scripts/test_session.py`, `scripts/test_state_migrate.py` |
| Fixtures | `scripts/fixtures/` | Per-module subdirs allowed: `scripts/fixtures/migrate/`, `scripts/fixtures/state/`. |
| Test discovery | `python3 -m unittest discover -s scripts -p 'test_*.py'` | Single root, no nested `tests/` package. |
| Imports | Tests use absolute imports of `scripts.lib.*` modules. | Tests run from repo root. |

**Drift sites resolved:**
- ADR Artifact 4 example shows `pytest scripts/tests/test_atomic.py -v` — that example is illustrative of the `pytest ` allowlist prefix, NOT a directory directive. The path under this contract is `scripts/test_atomic_io.py`.
- ADR Artifact 5 round-trip property test references `scripts/tests/fixtures/migrate/`. Under this contract the location is `scripts/fixtures/migrate/`. Plans `02b-02-T0-1-PLAN.md` and `02b-09-T1-M-PLAN.md` MUST use the flat path.

---

## 4. Exit Codes (Post-Amendment Canonical Table)

This table supersedes any inline exit-code list in any plan. It tracks ADR-003a Artifact 1 with the post-amendment note for code 4 (see `docs/adr/2026-05-16-hardening-bundle.md` ledger L16).

| Code | Name | Meaning | Owning plan |
|---|---|---|---|
| 0 | `EXIT_OK` | success | all |
| 1 | `EXIT_OPERATIONAL` | operational error (I/O, permissions, generic write failure) | all |
| 2 | `EXIT_INVALID_TRANSITION` | invalid phase transition per ADR-001 state machine | `02b-04-T0-3-PLAN.md` |
| 3 | `EXIT_SESSION_LOCKED` | session lockfile held by another process | `02b-04-T0-3-PLAN.md` |
| 4 | `EXIT_SCOPE_VIOLATION` | scope violation (write outside `allowed_paths`, or matches `blocked_paths`) — **RESERVATION LIFTED; assigned to T1-1** | `02b-07-T1-1-PLAN.md` |
| 5 | `EXIT_UNPARSEABLE_JSON` | unparseable JSON (state file or stdin) | `02b-09-T1-M-PLAN.md` / `02b-06-T0-5-PLAN.md` |
| 6 | `EXIT_WRONG_PHASE_FOR_VERB` | verb invoked in a phase that does not accept it | `02b-04-T0-3-PLAN.md` |
| 7 | `EXIT_STALE_UNCERTAIN` | stale-detection uncertain (session unlock without `--force`) | `02b-04-T0-3-PLAN.md` |
| 8 | `EXIT_TIMESTAMP_OUT_OF_RANGE` | `--at` value not within 24h of current UTC | `02b-04-T0-3-PLAN.md` |
| 9..15 | reserved | reserved for `02c-hardening` (schema-version refusal, audit verb, …) | future |

**Pre-amendment note:** ADR-003a originally reserved code 4 for "schema-version refusal." That reservation is **lifted** by ledger entry L16 and the amendment in commit `docs(adr): assign exit code 4 to SCOPE_VIOLATION`. Schema-version refusal will use a code in the 9..15 range when implemented in `02c-hardening`.

**Pinning rule:** `scripts/lib/exitcodes.py` defines one `EXIT_*` constant per row above; no aliases, no integer literals scattered through the CLI. Tests assert `exitcodes.EXIT_SCOPE_VIOLATION == 4`.

**Drift sites resolved by this section:**

- `02b-04-T0-3-PLAN.md` previously enumerated codes `0/1/2/3/5/6/7/8` with code 4 listed as "reserved." Update to drop the "reserved" footnote when the file is next touched (replace with a one-line reference to this section).
- `02b-07-T1-1-PLAN.md` previously hand-rolled an exit code or referenced ambiguous "violation exit." Plan now consumes `EXIT_SCOPE_VIOLATION = 4` from `scripts/lib/exitcodes.py`.
- `02b-09-T1-M-PLAN.md` and `02b-06-T0-5-PLAN.md` both reference exit 5 for unparseable JSON. Both consume `EXIT_UNPARSEABLE_JSON` from the same module; T0-5 wraps T1-M's exception (see §5.1).
- ADR Artifact 1 verb-2 line "Exit codes: 0/1/2/3/5/6/8" omits 4 because `phase approve` cannot itself emit a scope violation. That omission is correct and not a drift.

**Verification:** the smoke harness's golden file (per §10.2, see §8.2 below) MUST exercise at least one path per non-zero exit code in the table above. Any plan whose verb can emit a code listed here owns a test asserting that code.

---

## 5. Ownership of Disputed Source Lines

The following decisions resolve "who lands this first" debates that surfaced during plan drafting.

### 5.1 `scripts/lib/state_repair.py:197` (JSONDecodeError handling)

**Pre-slice behavior:** silent swallow.
**Post-slice behavior:** abort with exit 5.

**Ownership split:**
1. `02b-09-T1-M-PLAN.md` ships **first**: creates `scripts/lib/state_diagnostics.py` exporting `load_state_json(path) -> dict`. This helper raises `UnparseableStateError` (with a structured `exc.path`, `exc.json_decode_error`) on failure.
2. `02b-06-T0-5-PLAN.md` ships **second**: imports `load_state_json` and wraps `UnparseableStateError` in a `RepairRefusedError`, prints the diagnostic from ADR-005 Decision item 4, exits 5.

**Rule:** T0-5 MUST NOT re-implement JSON parsing. The diagnostic string lives in `state_diagnostics.py`; T0-5 only adds the wrapping/exit behavior.

### 5.2 `.roo/commands/done.md` creation

Assigned to **`02b-08-T1-S-PLAN.md`** as a new sub-task (adapter parity gap: the `.opencode/commands/done.md` exists in the pre-slice tree but `.roo/commands/done.md` does not). The content of the file mirrors `.opencode/commands/done.md` with the documented `.roo` frontmatter conventions. This was not previously assigned to any plan and was identified as a drift gap.

### 5.3 Uninstall flag split (`--remove-state`, `--remove-operational`, `--remove-install-state`, `--remove-all`)

Assigned to **`02b-04-T0-3-PLAN.md`**. T0-3 owns `scripts/uninstall_harness.py` flag additions because the flag set consumes `STATE_FILE_PATHS`, `OPERATIONAL_PATHS`, and `INSTALL_PATHS` — all three of which T0-3 already wires through `scripts/lib/operational_paths.py`. Per ADR Artifact 2 "Uninstall consumers (G4-C)".

### 5.4 `.gitignore` mandatory entries

Split by file owner:

| Entry | Owning plan |
|---|---|
| `.harness/audit.log` | `02b-04-T0-3-PLAN.md` |
| `.harness/audit.log.*` | `02b-04-T0-3-PLAN.md` |
| `.harness/audit.overflow/` | `02b-04-T0-3-PLAN.md` |
| `.harness/session.lock` | `02b-04-T0-3-PLAN.md` |
| `.harness/backups/` | `02b-06-T0-5-PLAN.md` |

Rationale: each plan owns the file it creates; `.gitignore` is touched by whichever plan introduces the artifact whose presence requires ignoring.

### 5.5 `scripts/lib/check.py` modifications

Three plans touch `check.py`:
- `02b-03-T0-2-PLAN.md` — `fnmatch` activation + glob precedence + G3-B warning.
- `02b-05-T0-4-PLAN.md` — `VERIFICATION_PREFIXES` 7-verb allowlist + trust-boundary doc comment.
- `02b-07-T1-1-PLAN.md` — scope enforcement (uses `STATE_FILE_PATHS` from `operational_paths.py` and `EXIT_SCOPE_VIOLATION` from `exitcodes.py`).

**Merge order:** T0-2 → T0-4 → T1-1. Each plan rebases on the previous before merging to `develop`. T0-A's grep gate must pass after each merge.

### 5.6 ADR Artifact 1 drift-warning template ownership

The drift-warning template (ADR Artifact 1, "Drift-warning template" subsection) is implemented in `scripts/lib/check.py` by `02b-04-T0-3-PLAN.md` because T0-3 is the plan that introduces the audit log whose `after_sha256` the template compares against. T0-2/T0-4/T1-1's later modifications of `check.py` MUST NOT alter the template string.

---

## 6. Filename Grammar

### 6.1 `.bak` files (state_repair + migrator)

**Format:** `<basename>.pre-repair.<UTC-compact-nanos>.<pid>.bak`

- `<basename>`: the basename of the file being backed up (e.g., `STATE.md`).
- `<UTC-compact-nanos>`: compact UTC timestamp with nanosecond precision, **no colons** (sortable, filesystem-safe on all targets). Format: `YYYYMMDDTHHMMSSnnnnnnnnnZ` (e.g., `20260516T193045123456789Z`).
- `<pid>`: the writing process PID, decimal.
- `<.bak>`: literal suffix.

**Location:** `.harness/backups/` (NOT alongside the source file). Per ADR-005 + G1-D.

**Example:** `.harness/backups/STATE.md.pre-repair.20260516T193045123456789Z.84321.bak`

**Why no colons:** macOS HFS+ technically permits `:` but several tools and Finder display it as `/`. ADR Artifact 1's nanos timestamps (`2026-05-16T19:30:45.123456789Z`) are JSON-payload timestamps, not filenames; filenames use the compact form.

### 6.2 Audit log files

- Current: `.harness/audit.log`
- Rotated: `.harness/audit.log.1`, `.harness/audit.log.2`, …, `.harness/audit.log.5`
- Overflow records (>512 B single line): `.harness/audit.overflow/<index>.json` (per ADR Artifact 1).

No other audit-log filenames are introduced in this slice.

### 6.3 Migrator sidecar (resume)

- Sidecar: `.scratch/phase-state.json.resume.json` (alongside the live state, NOT in `.harness/backups/`).
- Lifecycle: created at start of `--forward`/`--reverse`, deleted on successful completion; `harness migrate state --resume` consumes if present.

---

## 7. CHANGELOG Breaking-Ledger Distribution

**Rule:** each plan MUST append its assigned Breaking Ledger entries to `CHANGELOG.md` under `## Unreleased (develop)` → `### Breaking` in its **FIRST** commit (not last). This prevents the "merge-eve scramble" failure mode where every plan's final commit races for the same CHANGELOG section.

**Mapping** (ledger numbers correspond to `docs/adr/2026-05-16-hardening-bundle.md` Artifact 6):

| Ledger # | Entry summary | Owning plan |
|---|---|---|
| L1 | `done.approved` schema constant dropped | `02b-02-T0-1-PLAN.md` |
| L2 | `state_schema_version=2` mandatory | `02b-02-T0-1-PLAN.md` |
| L3 | `fnmatch` glob activation (precedence + grammar) | `02b-03-T0-2-PLAN.md` |
| L4 | `blocked_paths` overrides `allowed_paths` (blocked wins) | `02b-03-T0-2-PLAN.md` |
| L5 | Verification 7-verb allowlist (bash removed) | `02b-05-T0-4-PLAN.md` |
| L6 | Drift-warning template (high-severity stderr) | `02b-04-T0-3-PLAN.md` |
| L7 | Phase transition CLI verbs (`set`, `approve`) | `02b-04-T0-3-PLAN.md` |
| L8 | Session lockfile (O_EXCL + atexit/signal release) | `02b-04-T0-3-PLAN.md` |
| L9 | Audit log path + atomic-append + rotation | `02b-04-T0-3-PLAN.md` |
| L10 | `.bak` relocated to `.harness/backups/` + retention=10 | `02b-06-T0-5-PLAN.md` |
| L11 | Unparseable JSON aborts (was: silent swallow) | `02b-09-T1-M-PLAN.md` |
| L12 | Migrator `--resume` verb (crash recovery) | `02b-02-T0-1-PLAN.md` |
| L13 | Paused phases first-class in `STATE.md` `state-current` block | `02b-06-T0-5-PLAN.md` |
| L14 | Nanosecond-precision timestamps (`approved_at`, `updated_at`) | `02b-04-T0-3-PLAN.md` |
| L15 | `--at` 24h-window validation (exit 8) | `02b-04-T0-3-PLAN.md` |
| L16 | Exit code 4 = SCOPE_VIOLATION (reservation lifted; was: reserved) | `02b-07-T1-1-PLAN.md` |
| L17 | Uninstall flag split (`--remove-state`/`--remove-operational`/`--remove-install-state`/`--remove-all`) | `02b-04-T0-3-PLAN.md` |
| L18 | `.gitignore` mandatory entries | `02b-04-T0-3-PLAN.md` + `02b-06-T0-5-PLAN.md` (each lands its own row of §5.4) |
| L19 | Verification execution trust boundary (core never executes) | `02b-05-T0-4-PLAN.md` |
| L20 | SKILL surface CLI alignment (adapter command files use new verbs) | `02b-08-T1-S-PLAN.md` |

**Conflict-resolution:** because the FIRST commit of each plan lands its rows, conflicts in `CHANGELOG.md` will manifest at the start of each plan's branch and can be resolved early — not as a release blocker.

---

## 8. New Plan Files (Phase E and Smoke Extension)

Two new plan files are owed for spec §9.1 and §10.2 coverage. They are NOT among the nine plans currently in `.planning/phases/02b-hardening/plans/`; they are pinned here so future drift cannot reassign them.

### 8.1 `02b-10-PHASE-E-HARNESS-PLAN.md`

**Owns:**
- `scripts/smoke/low_reasoning_scenario.py` — driver for the N=50 Haiku-4.5 trial harness per spec §9.1.
- The 50-trial fixture set and pass-rate gate documented in §9.1.

### 8.2 `02b-11-SMOKE-EXT-PLAN.md`

**Owns:**
- The three-stage extension of `scripts/release_smoke_test.py` per spec §10.2.
- The golden file derived from ADR Artifact 1 (NOT from running the implementation; per ADR cross-consistency note).

Until these plan files are written, their work is **out of scope** for plans 01..09. Plans 01..09 MUST NOT pull §9.1 or §10.2 acceptance criteria into their own scopes.

**Dependency posture:** plans 10 and 11 BLOCK on the completion of plan 09 (T1-M) because the smoke harness needs `state_diagnostics.py` for fixture validation. The §9.1 fixture set will exercise: invalid transition (exit 2), session lock contention (exit 3), scope violation (exit 4), unparseable JSON (exit 5), wrong phase for verb (exit 6), and timestamp out of range (exit 8). Plans 10 and 11 MUST NOT define new exit codes; if a needed signal is missing, file a follow-up plan in `02c-hardening`.

---

## 10. Acceptance Gate for This Document

Before phase 02b execution begins, the following MUST be true:

1. Every plan in `02b-hardening/plans/` cites this file by section (e.g., "Path tuples per `CONTRACT-PIN.md` §2") at least once.
2. The ADR amendment for code 4 (companion commit `docs(adr): assign exit code 4 to SCOPE_VIOLATION`) has landed on `develop`.
3. No plan reintroduces `scripts/tests/` (§3) or duplicates path-tuple literals (§2).
4. `02b-04-T0-3-PLAN.md` reflects the uninstall-flag-split assignment (§5.3) and `.gitignore` ownership (§5.4 rows for T0-3).
5. `02b-06-T0-5-PLAN.md` reflects the `.harness/backups/` `.gitignore` row (§5.4) and the `state_diagnostics` import (§5.1 step 2).
6. `02b-08-T1-S-PLAN.md` reflects the `.roo/commands/done.md` sub-task (§5.2).

Failure of any gate item blocks merging the affected plan to `develop`. Reviewers cite the failing gate item in their review.

---

---

## 9. Change Log for This File

| Date | Change | Author |
|---|---|---|
| 2026-05-16 | Initial pin (resolves G1 drift across plans 01..09 and ADR amendment for code 4) | hjung3113@gmail.com |

When this file is amended, every plan in `02b-hardening/plans/` MUST be re-grepped for the changed term in the next session.
