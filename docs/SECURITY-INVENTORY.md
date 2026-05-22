# Security / Trust / Integrity Inventory

## Phase 1 (Security removal) — COMPLETE

**Commits**: strip(sec-1) through strip(sec-7b). **3,930 LOC deleted**, 7 modules + dead code removed. All items below marked **DONE**.

### REMOVED IN PHASE 1

1. **secret_key.py** (HMAC nonce, 208 LOC) ✅ sec-1
2. **cli_deprecated.py** (`--chain`/`--auto` halt gate, 148 LOC) ✅ sec-2
3. **fs_fence.py** (write-path enforcement, 390 LOC) ✅ sec-3
4. **autopilot_guard.py** + `.ps1` + 3 wrappers (389 LOC + assets) ✅ sec-4
5. **audit_verify_cli.py** (`harness verify --audit` CLI, 235 LOC) ✅ sec-5
6. **release_trust SSH verify dead code** (~46 LOC) ✅ sec-6
7. **trust_origin decision logic** (~160 LOC net in upgrade/install/audit/exitcodes) ✅ sec-7
8. **release_trust.py** orphan + tests + EXIT_RELEASE_TRUST_INVALID ✅ sec-7b

**Total phase 1**: ~3,930 LOC across 8 commits (modules + tests + manifest + audit verbs).

### KEEP — SURVIVING MODULES

- **audit.py** (558 LOC) — chain SHA256 stamping (state_trust oracle)
- **audit_chain.py** (126 LOC) — per-entry chain stamp only; walk/verify removed Phase 2 Item 5
- **audit_rotation.py** (61 LOC) — rotated file enumeration
- **state_trust.py** (388 LOC) — audit oracle preflight (after_sha256 compare)

### LOAD-BEARING — DO NOT REMOVE

12. **phase_lock.py** — mutual exclusion + crash recovery (모든 mutating verb 의존)
13. **phase_txn.py** — 5-step crash-safe state+audit 프로토콜
14. **atomic_io.py + durable_fs.py + safe_open.py** — 크래시 안전, symlink 방어
15. **backups.py** — install_recovery 의존
16. **install_recovery.py** — aborted install 회수

---

---

## KEPT MODULES (post-phase 1)

### 1. Audit chain (`audit.py` 558 + `audit_chain.py` 126 + `audit_rotation.py` 61)

Per-entry SHA256 chain (ADR D-3). `entry_hash = sha256(rfc8785(entry) + previous_hash)`. 10 MiB / 10k entries rotate with seam entry `audit.rotated`.

**KEEP**: Core to state_trust oracle. Rotation orchestration essential (unbounded log prevention).

### 2. State trust (`state_trust.py` 388)

Phase-state SHA256 vs audit oracle (`after_sha256`). Detects hand-edit. BOM/CRLF reject, canonical JSON re-emit.

**KEEP**: Workflow enforcement (§2.6).

### 3. Release trust — REMOVED (sec-7b)

After trust_origin simplification (sec-7), `release_trust.py` had zero non-test importers. Whole module + tests + `EXIT_RELEASE_TRUST_INVALID` deleted in sec-7b.

### 4. Atomic I/O & Durability (`atomic_io.py` 586 + `durable_fs.py` 296 + `safe_open.py` 752)

atomic_write_text/json, atomic_append_log, rename_atomic, fsync_parent_dir, F_FULLFSYNC, O_NOFOLLOW symlink defense.

**KEEP**: Crash-safe state/audit writes (workflow backbone).

### 5. Backups (`backups.py` 237)

`.harness/backups/` snapshots (retention 10).

**KEEP**: install_recovery dependency.

### 6. Install recovery (`install_recovery.py` 537)

Detects/recovers `.harness/.staging-*` after crash (600s timeout, .aborted sentinel).

**KEEP**: install/upgrade crash recovery.

### 7. Phase lock (`phase_lock.py` 529)

`.scratch/.lock.primary` O_EXCL mutual exclusion + dead-process recovery (psutil, cross-platform boot_id).

**KEEP**: Workflow lock + crash recovery.

### 8. Phase txn (`phase_txn.py` 836)

5-step crash-safe state+audit protocol + 12-row recovery matrix.

**KEEP**: State+audit consistency (workflow integrity foundation).

---

## Phase 1 Impact Summary

**Removed LOC breakdown** (modules only — tests + manifest + audit-log additional):
- secret_key.py: 208
- cli_deprecated.py: 148
- fs_fence.py: 390
- autopilot_guard.py + .ps1 + 3 wrappers: 389 + assets
- audit_verify_cli.py: 235
- release_trust.py (full module after sec-7b): 283
- trust_origin scattered logic: ~160 net
- SSH dead code (sec-6, already counted in release_trust): subset

**Workflow enforcement impact**: **ZERO**. All removed are dormant/ceremony code.

**KNOWN_VERBS removed**: `autopilot.network.deny`, `autopilot.fence.deny`, `audit.secret_key.rotated`, `cli.deprecated_flag`, `release.trust.verified`, `release.trust.bypassed`, `release.trust.refused`, `release.trust.rechained`.

---

## Design criteria (internal/single-user tool)

Per v0.9.13 commit: low-perf AI agent, **no multi-user threat model**.

**Must keep**:
1. Phase state integrity (hand-edit detection) — audit chain + state_trust
2. Crash safety (state+audit consistency) — phase_lock + phase_txn + atomic_io
3. Install idempotency + recovery — install_recovery + backups

**Removed** (unnecessary):
- Network isolation (autopilot_guard)
- Write-path sandbox (fs_fence)
- HMAC nonce signing (secret_key)
- SSH tag verification + release_trust module entirely (sec-6 dead code + sec-7b orphan)
- Forensic audit CLI (audit_verify_cli)
- Legacy flag deprecation (cli_deprecated)
- trust_origin decision tree (always dev_unsigned now)

**Removed in Phase 2**:
- state_migrate.py + state_migrate_t04.py + migrate_state.py (v0→v2 migration — all state is now v2)

**Deferred to future phase** (still present, not workflow-critical):
- audit_verify (chain library `verify_chain`/`walk_chain` test-only callers)
