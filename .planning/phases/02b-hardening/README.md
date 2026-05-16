# Phase 02b — Hardening

Production-internal hardening of the harness lifecycle, state machine, scope enforcement, audit trail, and adapter surface. This phase corresponds to `docs/superpowers/specs/2026-05-16-hardening-slice-design.md` §2.7 (production-internal posture: this is an internal-only release; no external operator semantics are stabilised here) and explicitly accepts the §2.8 residual risks **R-1** (per-platform `fcntl`/lockfile differences), **R-2** (`state_schema_version` enforcement guard deferred to 02c), and **R-3** (non-lifecycle adapter commands remain quarantined). The cross-plan contract authority is `CONTRACT-PIN.md` — when a plan in this directory disagrees with the pin, the pin wins.

## Plan inventory

| File | Slice | One-line description |
|---|---|---|
| `plans/02b-01-T0-A-PLAN.md` | T0-A | Atomic-write primitives (`atomic_write_text`, `atomic_append_log`) + canonical `STATE_FILE_PATHS` / `OPERATIONAL_PATHS` / `INSTALL_PATHS` / `exitcodes.py` stub + grep gate. Dependency-zero; lands FIRST. |
| `plans/02b-02-T0-1-PLAN.md` | T0-1 | `phase=done` contract alignment, `state_schema_version=2`, forward/reverse/resume migrator, transition state-machine table (`scripts/lib/transition.py` singular). |
| `plans/02b-03-T0-2-PLAN.md` | T0-2 | Scope-matching `fnmatch` activation, ADR-002 G2-E grammar, `blocked_paths` precedence over `allowed_paths`, G3-B literal-collision loader warning. |
| `plans/02b-04-T0-3-PLAN.md` | T0-3 | Phase transition CLI verbs (`phase set`, `phase approve`, `session unlock`), `.harness/session.lock` lifecycle, `.harness/audit.log` atomic-append + rotation, drift template, uninstall flag split, `.gitignore` audit/lock rows, `docs/protocol-spec.md` skeleton. |
| `plans/02b-05-T0-4-PLAN.md` | T0-4 | Verification 7-verb allowlist (`python3`, `git`, `jq`, `npx`, `pytest`, `harness`, `make`); split `verification`/`review`; trust boundary (core never executes verification strings). |
| `plans/02b-06-T0-5-PLAN.md` | T0-5 | `state_repair` preservation + paused-phase first-class + `.bak` relocation to `.harness/backups/` (O_EXCL, retention=10) + `RepairRefusedError` exit 5 wrapping `UnparseableStateError` from T1-M. |
| `plans/02b-07-T1-1-PLAN.md` | T1-1 | `check --worktree` wired at the workflow boundary via pre-commit hook + adapter `execute`-command mirroring; consumes `EXIT_SCOPE_VIOLATION = 4`. |
| `plans/02b-08-T1-S-PLAN.md` | T1-S | SKILL surface + adapter command alignment to new CLI verbs; creates `.roo/commands/done.md`; advisory Haiku-4.5 V8–V11 smoke. |
| `plans/02b-09-T1-M-PLAN.md` | T1-M | Malformed-state diagnostic helper `scripts/lib/state_diagnostics.py` (sole owner of `state_repair.py:197` rewrite); fuzz coverage; grep gate for bare `json.loads`. |

Two follow-up plans are owed but live OUTSIDE this directory's 9-plan set (CONTRACT-PIN §8): `02b-10-PHASE-E-HARNESS-PLAN.md` (N=50 Haiku trial harness per spec §9.1) and `02b-11-SMOKE-EXT-PLAN.md` (three-stage extension of `release_smoke_test.py` per spec §10.2). Plans 01..09 MUST NOT pull their acceptance criteria into scope.

## Contract authority

`CONTRACT-PIN.md` in this directory is the single source of truth for: module names + canonical paths (§1), path-tuple literal values (§2), test directory convention (§3), exit codes (§4 — including the post-amendment assignment of code 4 to SCOPE_VIOLATION via ADR commit `880334f`), ownership of disputed source lines (§5 — notably `state_repair.py:197`, `.roo/commands/done.md`, uninstall flag split, `.gitignore` rows, `check.py` merge order, drift-warning template), filename grammar (§6 — `.bak` UTC-compact-nanos format, audit log rotation, migrator sidecar), and the CHANGELOG Breaking-Ledger distribution (§7 — each plan lands its assigned L# rows in its FIRST commit, not last, to prevent merge-eve scrambles). Every plan in this directory cites CONTRACT-PIN at least once and amendments to that file require re-grepping every plan in the next session (§9).

## Execution order graph

```
T0-A  (dependency-zero, lands FIRST)
  │
  ├─→ T0-1 (state migration + transition.py + state_schema_version=2)
  │     │
  │     └─→ T0-3 (CLI verbs + session.lock + audit.log + uninstall split)
  │           │
  │           ├─→ T0-4 (verification 7-verb allowlist; rebases on T0-3 check.py)
  │           │     │
  │           │     └─→ T1-1 (check --worktree wiring; rebases on T0-4 check.py)
  │           │
  │           └─→ T1-S (SKILL + adapter alignment; sequences after T0-3 contract)
  │
  ├─→ T0-2 (scope-matching fnmatch; parallel with T0-1; check.py merge first in T0-2→T0-4→T1-1 chain)
  │
  └─→ T1-M (state_diagnostics.py; lands BEFORE T0-5 per §5.1)
        │
        └─→ T0-5 (state_repair preservation + .bak relocation; imports load_state_json from T1-M)
```

T0-A blocks every other slice. T0-1 and T0-2 may run in parallel after T0-A. T0-3 sequences after T0-1. T0-4 sequences after T0-3 (check.py merge order). T1-1 sequences after T0-4 (check.py merge order). T1-M lands before T0-5 (sole `state_repair.py:197` ownership). T1-S sequences after T0-3 contract artifact lock (not after T0-3 implementation merge).

Plans 02b-10 and 02b-11 (when authored) BLOCK on plan 09 (T1-M) per CONTRACT-PIN §8 dependency posture — the smoke harness needs `state_diagnostics.py` for fixture validation.

## Post-merge ledger

| ID | Slice | Gap | Resolution |
|---|---|---|---|
| L-T1S-001 | T1-S | `.roo/commands/done.md` was authored under T1-S but never registered in `harness/manifest.json`, so `harness init` skipped it in installed targets. | Caught in 02b-hardening close-out review; fixed in commit `8a4b0f6 chore(manifest): register .roo/commands/done.md (T1-S parity gap)`. Future slice T1-S work MUST add a manifest-registration check to its plan acceptance list. |
