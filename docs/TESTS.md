# Test Inventory

75개 테스트 파일 (32 top-level + 43 subdirectory). 카테고리별 분류 + 제거 후보.

## Categories

- **WORKFLOW** — phase lifecycle, planning, status/next, transitions
- **INSTALL** — install/upgrade/manifest/atomic batch
- **INFRA** — atomic I/O, durable FS, safe_open, exitcodes
- **SECURITY** — audit, trust, hash, autopilot guard
- **SMOKE** — E2E lifecycle
- **LEGACY** — v0→v2 migration, deprecated fixtures

## Top-level tests/test_*.py (32 files)

| Test | Category | Status |
|---|---|---|
| `test_atomic_install.py` | INSTALL | ✅ |
| `test_atomic_install_batch_defer_cleanup.py` | INSTALL | ✅ |
| `test_check_import_smoke.py` | INFRA | ✅ |
| `test_check_planning_drift.py` | WORKFLOW | ✅ |
| `test_check_staging_detection.py` | WORKFLOW | ✅ |
| `test_error_code_consistency.py` | INFRA | ✅ |
| `test_exitcodes_symbols.py` | INFRA | ✅ |
| `test_hash_verification.py` | SECURITY | ✅ |
| `test_install_atomic_wire.py` | INSTALL | ✅ |
| `test_install_recovery_pending_manifest.py` | INSTALL | ✅ |
| `test_install_recovery.py` | INSTALL | ✅ |
| `test_install_upgrade_sync.py` | WORKFLOW | ✅ |
| `test_known_failures_drift.py` | INFRA | ✅ |
| `test_next_status_parity.py` | WORKFLOW | ✅ |
| `test_phase_reopen.py` | WORKFLOW | ✅ |
| `test_phase_set_done_idempotent.py` | WORKFLOW | ✅ |
| `test_planning_grammar.py` | INFRA | ✅ |
| `test_planning_grammar_real_files.py` | WORKFLOW | ✅ |
| `test_planning_status_regression.py` | WORKFLOW | ✅ |
| `test_progress_output.py` | WORKFLOW | ✅ |
| `test_roadmap_state_letter_suffix.py` | INFRA | ✅ |
| `test_skip_upgrade_guard.py` | WORKFLOW | ✅ |
| `test_state_repair_exit_codes.py` | WORKFLOW | ✅ |
| `test_state_staged_hash.py` | INFRA | ✅ |
| `test_upgrade_atomic_wire.py` | INSTALL | ✅ |
| `test_upgrade_dry_run.py` | WORKFLOW | ✅ |
| `test_wrong_tree_resolution.py` | INFRA | ✅ |

**Removed** (Phase 1): test_audit_verify_tail.py, test_audit_error_wording.py, test_phase_approve_no_nonce_strings.py, test_fixture_determinism.py, test_smoke_lifecycle.py.

## Test subdirectories (43 files)

| Dir | Files | Category | Purpose | Status |
|---|---|---|---|---|
| `audit/` | 5 | SECURITY | S06 chain-stamped audit writer, crash recovery matrix | ✅ |
| `crash/` | 1 | SECURITY | Crash recovery matrix (§3.8) | ✅ |
| `dep_guard/` | 1 | INFRA | Runtime-dep import guard contract | ✅ |
| `durable_fs/` | 1 | INFRA | Cross-platform durability primitives | ✅ |
| `fixtures/` | — | — | Test fixtures | ✅ |
| `install/` | 3 | INSTALL | Quarantine uuid4 suffix, upgrade summary | ✅ |
| `integration/` | 1 | SMOKE | E2E `phase approve` PTY [y/N] | ✅ |
| `phase_approve/` | 3 | WORKFLOW | ADR-003a human-only gate | ✅ |
| `phase_lock/` | 5 | WORKFLOW | classify() decision matrix (§3.7) | ✅ |
| `phase_preflight/` | 1 | WORKFLOW | preflight 추출 smoke (P2-3) | ✅ |
| `phase_reopen/` | 1 | WORKFLOW | Backward 전이 (§3.2) | ✅ |
| `phase_set_done/` | 1 | WORKFLOW | Stale-approval validator (execute→done) | ✅ |
| `phase_set_execute/` | 3 | WORKFLOW | Stale-approval validator (plan→execute) | ✅ |
| `phase_state/` | 6 | WORKFLOW | forward() round-trips on §9.1 fixtures | ✅ |
| `phase_txn/` | 3 | WORKFLOW | §9.1 fixtures dispatch | ✅ |
| `safe_open/` | 1 | INFRA | O_NOFOLLOW race-safe open | ✅ |

**Removed** (Phase 1): cli/ (5 files), autopilot/, phase_autopilot/, fsd_wrappers/, cycle1_fixC/, ci_provenance/, release_smoke/, slash/ (1 file), smoke/ (3 files) — ~20 test files total.
**Removed** (Phase 2 Item 7): halt_diary/ test dir — ~1200 LOC tests.

## Phase 1 Completion: Test File Removal

**Removed** (~20 files):
- cli/ (5 files) — cli_deprecated removed
- test_phase_approve_no_nonce_strings.py — secret_key removed
- test_audit_verify_tail.py, test_audit_error_wording.py — verify --audit removed
- test_fixture_determinism.py, build_v094_fixture dependency
- autopilot/, phase_autopilot/ — network guard removed
- fsd_wrappers/ — legacy slash command
- slash/ (1 file) — autopilot_guard manifest removed
- cycle1_fixC/ — legacy integration fixture
- ci_provenance/, release_smoke/ — pending release ops refactor
- smoke/ (3 files) — grep_gate tests for removed modules

## 단순화 후 핵심 테스트 셋

KEEP 필수 (워크플로우 무결성):
- phase_state/, phase_txn/, phase_lock/, phase_approve/, phase_reopen/, phase_preflight/
- phase_set_execute/, phase_set_done/
- crash/ (recovery matrix)
- audit/ (chain stamping — verify CLI 빼고)
- planning_grammar / planning_status regression tests
- roadmap_state letter suffix
- transition / status / next parity

KEEP (deployment 무결성):
- install/, atomic_install*, install_recovery*
- upgrade_atomic_wire, upgrade_dry_run
- durable_fs/, safe_open/, dep_guard/

KEEP (sanity):
- exitcodes_symbols, error_code_consistency
- check_import_smoke, check_planning_drift, check_staging_detection
- known_failures_drift, wrong_tree_resolution
- state_repair_exit_codes, state_staged_hash

## Test fixtures (`tests/fixtures/`, `scripts/fixtures/`)

대부분 phase-state / manifest / roadmap snapshots. legacy v0 fixture는 Phase 2에서 state_migrate 제거와 함께 정리 완료.
