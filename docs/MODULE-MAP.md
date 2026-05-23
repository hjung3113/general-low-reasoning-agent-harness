# Module Map — `scripts/lib/*.py`

54개 파일 (50 modules + project_dashboard 4-file subpackage), 17,960 LOC. 카테고리 + 역할 + LOC + KEEP/DROP 판단.

## Legend

- ✅ KEEP — workflow/install/infra 필수
- 🔄 SIMPLIFY — 유지하되 단순화
- ❌ DROP — slim 빌드에서 제거

## WORKFLOW_CORE (12 modules, 4,542 LOC)

| Module | LOC | Purpose | Verdict |
|---|---|---|---|
| `phase_state.py` | 198 | v2 schema, legacy migration, timestamp stamping | ✅ |
| `phase_preflight.py` | 180 | TTY-only verb helpers, preflight 진입점 | ✅ |
| `phase_lock.py` | 529 | O_EXCL primary lock + dead-process recovery | ✅ |
| `phase_txn.py` | 836 | 5-step crash-safe state+audit txn + recovery matrix | ✅ |
| `phase_approve.py` | 705 | TTY [y/N] gate, identity, approver membership | ✅ |
| `phase_reopen.py` | 553 | Backward 전이, draft 보존 | ✅ |
| `planning_grammar.py` | 176 | STATE.md/ROADMAP.md regex + parsing | ✅ |
| `planning_status.py` | 689 | Read-only status projection, task inventory | ✅ |
| `roadmap_state.py` | 272 | 5-point invariant check | ✅ |
| `status_next.py` | 517 | StatusResult/NextResult dataclass, gate logic | ✅ |
| `session.py` | 222 | Session lock lifecycle (ADR-003a G1-B) | ✅ |
| `transition.py` | 380 | 전이 표, validate_transition_with_state | ✅ |

## INSTALL (13 modules, 4,193 LOC)

| Module | LOC | Purpose | Verdict |
|---|---|---|---|
| `install.py` | 753 | Init/install flow orchestrator | ✅ |
| `upgrade.py` | 890 | Upgrade flow (heaviest aggregator) | 🔄 (trust_origin 로직 정리) |
| `adoption.py` | 227 | Manual install adoption (`--adopt-existing`) | ✅ |
| `manifest.py` | 252 | Manifest model, load, select_entries | ✅ |
| `manifest_v2.py` | 113 | v2 schema R/W (BOM/CRLF reject) | 🔄 (trust_origin 빼고 keep) |
| `manifest_reconciler.py` | 463 | 3-way reconciler (install/current/source) | ✅ |
| `append_block.py` | 227 | HTML-comment 마커 블록 parse/render/merge | ✅ |
| `managed_block.py` | 109 | Managed marker block helpers | ✅ |
| `state.py` | 452 | Install state model + sha256 + scope resolution | ✅ |
| `profiles.py` | 66 | KNOWN_PROFILES, _PROFILE_DEFAULT_PACKS, _DB_PACKS | ✅ |
| `hooks.py` | 238 | Pre-commit scope hook install/uninstall | ✅ |
| `install_recovery.py` | 537 | `.staging-*` 회수 (T14b) | ✅ |
| `roomodes_writer.py` | 63 | `.roomodes` R/W (logical base/profile split) | ✅ |

## INFRA (10 modules, 2,272 LOC) — Milestone 1 complete

| Module | LOC | Purpose | Verdict |
|---|---|---|---|
| `atomic_io.py` | 586 | atomic_write_text/json, rename_atomic, atomic_install_batch | ✅ |
| `durable_fs.py` | 296 | fsync_parent_dir, replace_with_retry, F_FULLFSYNC | ✅ |
| `safe_open.py` | 752 | O_NOFOLLOW path walk, symlink avoidance | ✅ |
| `backups.py` | 237 | `.bak` snapshots, retention | ✅ |
| `timestamps.py` | 67 | ISO-8601 UTC nano timestamp | ✅ |
| `exitcodes.py` | 63 | EXIT_* 상수 | ✅ |
| `version.py` | 171 | Version, git provenance, release_check | ✅ |
| `operational_paths.py` | 34 | 정규 path tuples | ✅ |
| `progress.py` | 66 | stderr progress | ✅ |
| `roo_modes.py` | 18 | Roo mode 상수 | ✅ |

**Removed**: fs_fence.py (390 LOC)

## SECURITY (4 modules, 1,081 LOC) — Milestone 2 complete

| Module | LOC | Purpose | Verdict |
|---|---|---|---|
| `audit.py` | 535 | audit.log writer, rotation orchestration | ✅ |
| `audit_chain.py` | 126 | per-entry SHA256 chain stamping only; verify/walk path removed Milestone 2 Item 5 | ✅ |
| `audit_rotation.py` | 60 | Rotated file enumeration | ✅ |
| `state_trust.py` | 360 | Audit oracle preflight (after_sha256 비교) | ✅ |

**Removed in Milestone 1**: secret_key (208), cli_deprecated (148), fs_fence (390), autopilot_guard (389 + assets), audit_verify_cli (235), release_trust (283, sec-7b) — ~1,653 LOC modules.

## CLI_DISPATCH (3 modules, 1,448 LOC)

| Module | LOC | Purpose | Verdict |
|---|---|---|---|
| `phase_cli.py` | 801 | phase set/approve/reopen/next-pending, session unlock | ✅ |
| `status_next_cli.py` | 490 | status/next/run CLI handlers | ✅ |
| `state_cli.py` | 157 | state show/repair CLI | ✅ |

## DIAGNOSTICS (5 modules, 2,547 LOC)

| Module | LOC | Purpose | Verdict |
|---|---|---|---|
| `check.py` | 1106 | 19종 invariant 검증 | ✅ (단순화 가능) |
| `doctor.py` | 544 | Drift findings + render (markdown/json) | 🔄 |
| `state_diagnostics.py` | 409 | Malformed-state diagnostic, schema 검증 | ✅ |
| `state_repair.py` | 370 | Managed marker block 재생성 | ✅ |
| `workflow_static_checks.py` | 118 | 설치된 하네스의 static check | ✅ |

## DEAD_LEGACY — Milestone 2 제거 완료

`state_migrate.py`, `state_migrate_t04.py`, `migrate_state.py` (v0→v2 마이그레이션) — Milestone 2에서 제거됨. 모든 state는 이제 v2.

---

## 의존 그래프 핵심

```
Tier 1: atomic_io, durable_fs, safe_open, backups, timestamps, exitcodes,
        audit, audit_chain, phase_state, phase_lock, phase_txn,
        transition, planning_grammar, roadmap_state, managed_block, profiles

Tier 2: manifest, append_block, state, install_recovery,
        phase_approve, phase_reopen, planning_status, status_next,
        session, state_diagnostics, state_repair, state_trust

Tier 3: install, adoption, check, doctor,
        phase_cli, status_next_cli, state_cli

**Removed (Milestone 2 Item 7)**: halt_diary_cli, cli_budgets, halt_diary

Tier 4: upgrade (모두 의존)
```

순환 의존 **없음**.

---

## Milestone 1 Completion: LOC & Module Reduction

| Commit | Item | LOC | Status |
|---|---|---|---|
| sec-1 | secret_key.py | 208 | ✅ |
| sec-2 | cli_deprecated.py + dispatcher hook | 148 | ✅ |
| sec-3 | fs_fence.py + phase_txn fence block | 390 | ✅ |
| sec-4 | autopilot_guard.py + .ps1 + 3 wrappers | 389 + assets | ✅ |
| sec-5 | audit_verify_cli.py + `verify --audit` subparser | 235 | ✅ |
| sec-6 | release_trust SSH dead code | ~46 | ✅ |
| sec-7 | trust_origin decision logic | ~160 net | ✅ |
| sec-7b | release_trust.py orphan + EXIT constant | 283 | ✅ |
| **Milestone 1 Total** | (modules + tests + manifest + audit verbs) | **~3,930** | **✅** |

**Module reduction**: 60 → 54 files (50 modules + project_dashboard subpackage). **SECURITY** 9→4 (audit + audit_chain + audit_rotation + state_trust), **INFRA** 12→10 (fs_fence + worktree 제거). **DEAD_LEGACY** fully cleared (Milestone 2).

**Milestone 2 Item 7 completion**: halt-diary + cli_budgets + autopilot scaffolding removed — ~816 LOC modules + ~1200 LOC tests. `halt_diary.py` (196 LOC), `halt_diary_cli.py` (128 LOC), `cli_budgets.py` (495 LOC) deleted. Schema fields `autopilot_started_at_iso`, `cli_budgets_remaining`, `last_halt`, `last_halt_history`, `autopilot_run_id`, `autopilot_mode`, `autopilot_phase_slug`, `autopilot_start_entry_hash`, `autopilot_allow_network` removed. Audit verbs `phase.autopilot.*`, `halt_diary.clear` removed.

**Remaining phases**:
- doctor.py simplification — ~200 LOC potential
- **Release ops redesign** (deferred): `scripts/release_smoke_test.py` is referenced
  by `scripts/release.py:170`, `scripts/tests/test_release.py`, and
  `.github/workflows/release.yml:62` but the file does not exist in the tree.
  Release flow is broken at HEAD. Needs ground-up rebuild or full removal of
  release-ops surface (release.py, release_harness.py, release-check CLI).
- **Test directory consolidation** (deferred): `scripts/tests/` (30 flat
  unittest files) and `tests/` (75+ pytest files) live side by side.
  `scripts/release.py:170` invokes specific files by path via `python3 -m
  unittest`, so consolidation requires release-ops rebuild first.

---

## Top-level scripts (`scripts/*.py`)

| Script | LOC | Verdict |
|---|---|---|
| `harness.py` | 916 | ✅ KEEP |
| `install_harness.py` | 238 | ✅ |
| `upgrade_harness.py` | 193 | ✅ |
| `uninstall_harness.py` | 358 | ✅ |
| `check_harness.py` | 45 | ✅ |
| `doctor_harness.py` | 30 | ✅ |
| `release.py` | 217 | ✅ (release ops) |
| `release_harness.py` | 27 | ✅ |
| `show_phase_status.py` | 29 | ✅ |
| `project_dashboard.py` | 10 | 🔄 (stub) |
| `build_v094_fixture.py` | 423 | ✅ (active test dep) |
| `target_smoke_test.py` | 95 | ✅ |
