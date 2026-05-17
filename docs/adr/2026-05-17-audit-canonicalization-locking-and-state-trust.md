# ADR: Audit Canonicalization, Locking, and State Trust — 2026-05-17

## Status

Accepted. Bound to **phase 02c-phase-gate-hardening**, design baseline `docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md` (Round-7).

Locks the byte-level contract for hashing, the cross-platform locking protocol, the two-file (state + audit) crash-atomic transaction protocol, the out-of-repo anchor that defeats audit replay, and the read-side state-trust preflight that catches direct file edits.

## Context

Rounds 2 through 7 surfaced a layered set of integrity problems that any one of them, left undefended, defeats every other defense:

- **Schema-bump hash break** (Round-1): adding optional audit fields invalidates the chain.
- **Concurrent-writer corruption** (Round-2): audit append and state mutation under separate locks let a power loss or a second writer interleave bytes.
- **Cross-platform line ending + path serialization drift** (Round-2): `core.autocrlf=true` and `os.path.normpath` produce divergent hashes on Linux vs Windows.
- **Audit not tamper-evident** (Round-3): per-entry chaining catches accidental edits but a repo-local attacker rewrites all entries.
- **`os.replace` not crash-atomic across two files** (Round-4): a crash between audit append and state replace leaves audit and state divergent; per-entry hashes then disagree with state-content hashes.
- **Stale-lock recovery races** (Round-3, Round-5): mtime + `pid_exists` is unsafe; PID reuse, container PID namespaces, and clock jumps all conspire.
- **APFS directory fsync is insufficient** (Round-7): `os.fsync(dir_fd)` on macOS does not flush the volume; `F_FULLFSYNC` is the documented primitive. NTFS needs `FlushFileBuffers` on the renamed file's handle.
- **Direct state edits bypass lock/journal** (Round-6): `Edit`/`Write` on `.scratch/phase-state.json` without taking the lock corrupts state for any reader that trusts the file.
- **Audit replay through stale-but-valid tail** (Round-7): rewriting `audit.log` to truncate back to a prior moment where `approved=true` was legitimately written defeats §2.6 preflight unless an out-of-repo anchor exists.

These problems are addressed below as one bound contract; partial adoption is not safe.

## Decision

### D-1. RFC 8785 JSON canonicalization

JSON canonicalization for hashing uses the `rfc8785` PyPI library (RFC 8785 — JSON Canonicalization Scheme): sorted keys, UTF-8 without BOM, no insignificant whitespace, normalized number serialization (NaN/Inf rejected at write boundary; ints > 2^53 stringified; surrogate pairs NFC-normalized).

**Library version pin**: `rfc8785 >= 0.1.4, < 0.2.0`. Bumping requires a new ADR.

**Golden vectors** (regression fixture at `tests/fixtures/canonicalization/`):

1. State file mid-transition (`state_mid_transition.json`).
2. Audit entry with `previous_entry_hash` set.
3. Entry spanning rotation boundary (carries `next_file_seed_previous_entry_hash`).
4. Entry with unicode + control-character `--reason` post-sanitization.

Tests in `tests/audit/test_canonicalization.py` must produce byte-identical output across Linux, macOS, and Windows for every vector.

### D-2. Line endings and path serialization

All harness-managed JSON files are written with `open(..., newline='\n')` and explicit `\n`. The paths are registered in `.gitattributes` with `text eol=lf working-tree-encoding=UTF-8` so `core.autocrlf=true` cannot mangle them on Windows checkouts. Readers MUST normalize CRLF → LF before canonicalization.

All path strings in audit / manifest / state entries are serialized as `pathlib.PurePosixPath` forward-slash form. Native Windows input is accepted in memory but rejected at the canonical-JSON serialization boundary; backslashes are not permitted in any persisted path field. Hashing operates on the canonicalized POSIX form so Linux and Windows produce byte-identical hashes for the same logical content.

UTF-8 BOM is forbidden in all harness-managed files (design doc §2.4). Readers detect the `0xEF 0xBB 0xBF` prefix and exit 5 with hint `run 'harness repair --strip-bom <path>'`.

### D-3. Two complementary hash chains

**(A) State-content chain**: each audit entry carries `before_sha256` / `after_sha256` of the state-file content surrounding the action. Survives audit-log rotation trivially.

**(B) Per-entry chain (NEW Round-3)**: each audit entry carries `entry_hash = sha256(canonical_json(entry_minus_entry_hash) || previous_entry_hash)`. Rotation boundary records `seed_previous_entry_hash` so the verifier walks across rotated files (design doc §2.5). Global monotonic `seq_global` field added in Round-4 detects gaps without recomputation.

**Tamper-detection claim is "integrity-checked, not signature-tamper-evident"** (Round-4 honest downgrade). The per-entry chain detects incomplete or accidental edits — partial deletion, single-field rewrite, truncation, rotation-seam corruption — but does NOT defeat a repo-local attacker who rewrites every entry and recomputes every `entry_hash`. The audit-tip anchor (D-7) is the defense against that class.

### D-4. Cross-platform lock protocol

Lockfile path: `.scratch/phase-state.json.lock`. Created via `os.open(path, O_CREAT | O_EXCL | O_WRONLY)` (atomic on both POSIX and Windows). Owner record (design doc §3.7): `{pid, hostname, process_start_time, boot_id, monotonic_acquired_at, acquired_iso, owner_token}`. `boot_id` source: Linux `/proc/sys/kernel/random/boot_id`; macOS `sysctl kern.boottime`; Windows `WMI Win32_OperatingSystem.LastBootUpTime`.

**Recovery decision matrix** (design doc §3.7):

- Different `hostname` → never force-stale.
- Same hostname + different `boot_id` → reboot happened, safe to recover.
- Same hostname + same `boot_id` + PID alive + `process_start_time` matches → genuinely held; exit 3.
- Same hostname + same `boot_id` + (PID dead or `process_start_time` mismatch) → stale, recover via STEP A protocol.
- Ambiguous (sandboxed `/proc`) → require `harness lock recover --force`.

**STEP A — recovery-mutex acquisition ordering**: every primary-lock acquire MUST first check for `.lock.recovery` and back off while it exists. The recovery mutex defends against a normal waiter grabbing the primary in the window between stale-detect and unlink (design doc §3.7). The `audit_emit("lock.recovered", ...)` call MUST happen BEFORE `os.unlink(PRIMARY)`, not after (Round-7 ordering fix).

**Substrate guard**: at every CLI start, `.scratch/` filesystem is detected. NFS, SMB, CIFS, FUSE → exit 3 `unsupported_substrate` unless `--accept-remote-substrate-best-effort` (logs `verb=harness.substrate.degraded`).

### D-5. Crash-safe state + audit transaction protocol

Five-step protocol under the state lock (design doc §3.8):

| # | Step | Durability |
|---|---|---|
| 1 | Write journal `{txn_id, action, before_sha256, after_sha256, audit_entry_draft, started_at_monotonic}` | `fsync(journal_fd)` + `fsync_parent_dir(scratch)` |
| 2 | Write `state.json.tmp.<txn_id>` | `fsync_file_durable(tmp_fd)` + `fsync_parent_dir(scratch)` |
| 3 | Append audit entry to `audit.log` | `fsync(audit_fd)` + `fsync_parent_dir(scratch)` (Round-7 addition) |
| 4 | `os.replace(state.json.tmp, state.json)` with up-to-5 retry on Windows `PermissionError` (AV/indexer) | `fsync_file_durable(state_fd_reopened)` + `fsync_parent_dir(scratch)` |
| 5 | `os.unlink(journal)` | `fsync_parent_dir(scratch)` |

**Tmp file is named per-`txn_id`** (Round-7 P1a fix) so two concurrent recoveries do not collide on the singular path.

**Recovery decision matrix** (12 rows including Round-7 audit-partial-write row 12; design doc §3.8). The verifier validates per-entry chain integrity AND JSON well-formedness of the audit tail before classifying `A`; bad-parse → exit 14 `audit_partial_write`.

### D-6. Cross-platform durability primitive

`scripts/lib/durable_fs.py` exports `fsync_parent_dir(path)` and `fsync_file_durable(fd)`:

- POSIX non-macOS file: `os.fsync(fd)`.
- macOS file: `fcntl.fcntl(fd, fcntl.F_FULLFSYNC)` with fall-through to `os.fsync(fd)` on `EINVAL` (Round-7 BLOCK B-10).
- POSIX dir: `fd = os.open(parent, O_RDONLY|O_DIRECTORY); os.fsync(fd); os.close(fd)`.
- Windows dir: `CreateFileW(parent, FILE_LIST_DIRECTORY, FILE_SHARE_R_W_D, OPEN_EXISTING, BACKUP_SEMANTICS)` + `FlushFileBuffers(h)` + `CloseHandle(h)`; return values checked and `WIN32_LAST_ERROR` raised as `DurableFsError` (Round-7 B-12).
- Windows file post-`os.replace`: re-open with `CreateFileW(GENERIC_WRITE, OPEN_EXISTING)` + `FlushFileBuffers(h)`.

### D-7. Out-of-repo audit-tip anchor

Path: POSIX `~/.harness/audit-tip/<repo-id>.json` (0600); Windows `%LOCALAPPDATA%\Harness\audit-tip\<repo-id>.json` (user ACL). `<repo-id> = sha256(canonical_absolute_path_of_repo_root)[:16]`.

Anchor body (design doc §12.1):

```json
{
  "anchor_schema_version": 1,
  "repo_root_canonical": "...",
  "harness_version": "v0.7.0",
  "install_id": "<uuid4>",
  "install_record_sha256": "<sha256>",
  "audit_tip_entry_hash": "<entry_hash>",
  "audit_tip_seq_global": 1234,
  "updated_at_iso": "...",
  "anchor_signature": "<HMAC-SHA256 keyed by ~/.harness/secret.key>"
}
```

**Update protocol**: every audit append MUST, after step 5 (journal removed), atomically rewrite the anchor via `tmp + fsync + os.replace + fsync_parent_dir`. Failure exits 14 `anchor_update_failed`.

**Verification (`harness verify --audit`, every CLI start)**:

1. Verify `anchor_signature` using `~/.harness/secret.key`.
2. Verify `audit_tip_entry_hash` matches live audit tail's `entry_hash`.
3. Verify `install_record_sha256` matches live `install-record.json`.

Any mismatch → exit 10 with sub-reason. `audit_tip_seq_global` is monotonic; an anchor with `seq_global` less than any previously seen value (cached in `~/.harness/audit-tip/.seen.json`) is rejected as rollback.

### D-8. State trust preflight

Every CLI command that reads or mutates `.scratch/phase-state.json` MUST run the §2.6 preflight before trusting any state field:

1. Read state bytes; reject BOM/CRLF violations; canonicalize.
2. Walk audit tail far enough to identify the latest valid entry with `after_sha256`.
3. Compare `sha256(canonical_state_bytes)` to that `after_sha256`.
4. Verify the audit tail's `entry_hash` matches the anchor's `audit_tip_entry_hash` (D-7).
5. Mismatch → exit 10 `state_audit_tip_mismatch` (or `anchor_signature_invalid` / `audit_tail_diverged_from_anchor`); no mutation, print `Fix: run harness verify --audit`.

**Read-only verbs (`harness status`, `harness next`)** use consistent-snapshot read instead of taking the lock (design doc §12.8): 3 retry attempts with 70/140/280 ms backoff to cover the `os.replace` rename window. Persistent mismatch surfaces as `state_audit_tip_mismatch=true` in `--json` output; the verb still exits 0 (status must be low-noise).

### D-9. Recovery and anchor ordering

`harness verify --audit` and every CLI start performs recovery in this order (Round-7 BLOCK A-6 fix):

1. Read anchor; verify signature.
2. Check anchor tip against live audit tail.
3. Run §3.8 crash-recovery matrix; roll-forward (row 7) is gated on the journal's `txn_id` being referenced by audit tail whose `entry_hash` equals or is a descendant of the anchor tip.
4. After recovery completes (or is a no-op), run state-trust preflight (D-8).

`anchor → recovery → preflight`, never `recovery → preflight → anchor`. This prevents a forged-tmp roll-forward from installing attacker state before preflight runs.

## Consequences

**Positive**:

- The chain is integrity-checked across schema evolution (every new optional field naturally enters the canonical hash).
- Rotation, BOM, CRLF, path separator drift are all closed at the byte level with cross-platform regression fixtures.
- Two-file crash atomicity is guaranteed by the journal + audit + tmp ordering; no power-loss configuration leaves state and audit divergent.
- APFS and NTFS rename durability is explicit (`F_FULLFSYNC` / `FlushFileBuffers` on the renamed file's handle).
- Direct `Edit`/`Write` of `.scratch/phase-state.json` no longer goes undetected — preflight + anchor catch both single-file edits AND coordinated state+audit replays.
- Status/next read verbs remain agent-safe and IDE-pollable without lock contention.

**Negative**:

- `~/.harness/secret.key` is a new credential under user home; loss requires `harness anchor repair` (admin verb, TTY-only). Adapters MUST deny the file in `permissions.deny` to claim `approval_proof=supported`.
- NFS/SMB/CIFS substrates are unsupported by default; users must opt in with a flag and accept degraded posture.
- An attacker with unrestricted user-account access (outside any adapter sandbox) defeats the anchor; this is documented out-of-scope and matches the broader OS-trust assumption.
- Verification cost is non-trivial: every CLI start runs anchor + chain walk + preflight. For repos with > 100k audit entries, this is mitigated by `seq_global` indexing and tail-bounded walks.
- The transaction protocol's 5 steps × `fsync` × `fsync_parent_dir` adds latency on slow disks; measured worst case on spinning disk is ~50 ms per mutation.

## Alternatives considered

- **Signed `audit.log.sig` tip pointer in repo** (rejected, Round-4): repo-local attacker rewrites both. Anchored tip outside the mutable repo (D-7) is the chosen alternative.
- **External timestamp authority** (deferred, Round-4): higher trust ceiling but requires network at every commit; out of scope for v0.7.
- **Hash chain over state-content only, no per-entry chain** (rejected, Round-3): does not detect single-field audit edits.
- **Soft lock (advisory)** (rejected, Round-2): O_EXCL is the only atomic primitive that works on both POSIX and Windows local filesystems.
- **Eager migration of legacy state on every read** (rejected, Round-7 B-8): write-back outside transaction protocol corrupts state on crash. Mutating verbs perform migration; read-only verbs defer.

## Cross-references

- Design doc: §1.2, §2.2, §2.3, §2.4, §2.5, §2.6, §3.7, §3.8, §3.8.1, §12.1, §12.2, §12.5, §12.8, §12.9.
- ADR-1 `2026-05-17-approver-provenance-and-execution-mode.md`: identity binding feeds audit `by_source`.
- ADR-3 `2026-05-17-autopilot-guards-and-manual-handoff.md`: budget decrements and halt-diary writes ride this transaction protocol.
- Slice S01 (schema + lock + transaction + durable_fs + preflight), S06 (audit chain verifier + rotation seam + crash recovery matrix), S00.7 (audit-tip anchor + secret.key minting).
