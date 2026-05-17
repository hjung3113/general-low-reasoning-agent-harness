# Hardening Bundle ADR — 2026-05-16

## Status

Accepted (bundled session). This document locks ADR-001, ADR-002, ADR-003a, ADR-003b, ADR-004, ADR-005 and the six mandated artifacts in a single PR. Partial landing of any subset is forbidden per spec §6 ("ADR session protocol").

- Spec: `docs/superpowers/specs/2026-05-16-hardening-slice-design.md` (commit `7622aba`, 740 lines).
- Decided in session order (per spec §6 directive): 001, 002, 004, 003a, 003b, 005.
- Bound to `02b-hardening` phase (per spec §5).
- No code change is authorized by this document. Implementation begins on row T0-A first, then ADR-bound rows after the §10 verification protocol is scoped into the implementation plan.

**Revision note (2026-05-16, post-review):** This bundle was revised in-place after three adversarial reviews (Protocol Architect, Low-Reasoning Realist, Ops & Supply-Chain Hawk) and three locked user decisions (D-G1 full operational-safety fix; D-G2/G3 contract-precision + weak-model patches; D-G4 remove `bash ` from allowlist). The revision touches all six ADRs and all six artifacts.

## Context

The current `main` ships three internal inconsistencies (spec §3): the `done` predicate in `scripts/lib/check.py:431` (`approved is not False`) inverts schema intent; `scripts/lib/worktree.py` imports `fnmatch` but performs only prefix/exact matching, silently zero-matching globs; the verification allowlist accepts `"Room is great"` because of the bare `"Roo"` prefix; the live state self-attests by listing `.scratch/phase-state.json` inside `allowed_paths`; `scripts/lib/state_repair.py:197` swallows `JSONDecodeError`. The hardening slice (§7) cannot begin code until six ADRs lock these contracts in one bundled session. The CLI contract artifact (§10.1) is what breaks the smoke-vs-CLI circular dependency; it is therefore produced here, not in T0-3 implementation.

## Decision Summary Table

| ADR | One-line decision |
|---|---|
| ADR-001 | Adopt option **3** (drop `approved` from the `done` branch); bump `state_schema_version` from `1` to `2`; pick sub-decision **3a** (`--reverse` writes `approved=false`) to round-trip the existing live fixture semantically. |
| ADR-002 | Adopt option **2** (full `fnmatch` glob, activating the dead import); precedence rule **(a)** — `blocked_paths` always overrides `allowed_paths`. Grammar fully specified in ADR-002 Decision below. |
| ADR-003a | Adopt option **2** (CLI + warn): two lifecycle verbs (`harness phase set`, `harness phase approve`) plus one operational verb (`harness session unlock`); zero required flags on lifecycle path; direct edits warn but do not fail; state file stays at `.scratch/phase-state.json`; session lockfile `.harness/session.lock`. Optional-flag cap of 3 per verb. |
| ADR-003b | Field ownership matrix: lifecycle fields CLI-preferred; `done.approved` is user-only post-transition; narrative fields user-editable. |
| ADR-004 | Adopt option **1** (two fields): `verification` (machine, **7**-verb allowlist after D-G4 removed `bash `) and `review` (human, array of `{actor, at, evidence_path, summary}`); rejection diagnostic enumerates verbs inline and cites `docs/protocol-spec.md#verification-allowlist`. `verification` strings are NEVER executed by core CLI. |
| ADR-005 | Adopt option **3** (preserve verbatim + write `.bak`): non-managed content outside `## Phases` is preserved byte-for-byte; a timestamped `.bak` is written before rewrite into `.harness/backups/`; paused phases are first-class; unparseable `phase-state.json` aborts with diagnostic exit. `.bak` retention capped at 10 per original. |

---

## ADR-001: `phase=done` Contract

### Context

The schema (`.scratch/phase-state.schema.json:347-399`) declares `done` requires `approved=true`. The checker (`scripts/lib/check.py:431`) reads `if state.get("approved") is not False:` and uses that to REJECT the record — the inverse of the schema. The only currently-shippable live state is the schema-invalid `approved=false` at `.scratch/phase-state.json:3`. Spec §6 ADR-001 offers three options and (if option 3 chosen) sub-decisions 3a/3b/3c for the `--reverse` migrator.

### Options Considered

- **Option 1** (`done` requires `approved=true`; fix checker). Rejected: `approved` semantically gates `execute` entry, not terminal closure; conflating them keeps the per-transition flag bleeding into terminal state. Also: under this option, the existing live record (`approved=false`) round-trips as schema-invalid and forces a non-trivial migration interpretation ("was this approved?" — we cannot answer truthfully from the existing record).
- **Option 2** (`done` requires `approved=false`; fix schema, keep checker). Rejected: contradicts the only natural English reading of `approved=true`/`done`; spec §3 explicitly calls the checker's predicate "inverted relative to the schema's intent".
- **Option 3** (drop `approved` from `done` branch). **SELECTED.** `approved` is per-transition state and `done` is terminal; the conflation is the root defect. Aligns with `state_schema_version` introduction in T0-1. Weak-model muscle memory fits: "approval is something I do once on the way in".

### Decision

Adopt option **3**. Drop the `approved` constraint from the `done` branch of `.scratch/phase-state.schema.json`. The field remains in the top-level `properties` (still required at top level, since other phases use it), but the `if/then` block for `done` has no `approved` constant.

Bump `state_schema_version` from `1` (the value T0-1 introduces) to `2` for the new `done` shape. Pre-T0-1 records (which have no `state_schema_version` field) are treated as version `0`.

### Transition state machine

| from \ to | discuss | plan | execute | done |
|---|---|---|---|---|
| (none) | ✓ | — | — | — |
| discuss | ✓ (reset) | ✓ | — | — |
| plan | ✓ (reset, --reset-approval) | ✓ | approved-✓ | — |
| execute | ✓ (reset, --reset-approval) | ✓ (reset, --reset-approval) | ✓ | approved-✓ |
| done | ✓ (new cycle, --reset-approval) | ✓ (reset, --reset-approval) | ✓ (reset, --reset-approval) | ✓ (re-stamp) |

Rules:
- "approved-✓" means the transition requires `approved=true` from a prior `harness phase approve` call. Only `plan→execute` and `execute→done` require this.
- "(reset)" means the transition clears `approved`/`approved_by`/`approved_at` to null. Backwards (any to earlier phase) and lateral (e.g., `execute→plan`) transitions require explicit `--reset-approval` flag. Without the flag, exit 2 with diagnostic.
- "(new cycle)" from `done`: `done→discuss` is the canonical "start the next round" transition; `--reset-approval` is also required there as a safety prompt.
- Unmarked cells (—): invalid, exit 2 with diagnostic.
- `done→done` re-stamps `updated_at`/`updated_by` (no-op WRT phase value).

Artifact 1 verb 1 references this table for exit code 2 (invalid-transition).

### Sub-decisions

- **3a SELECTED**: `--reverse` migrator (v2 → v0) writes `approved=false` for `done` records. Rationale: semantically preserves the existing live fixture (`.scratch/phase-state.json:3` is `approved=false`); the round-trip property `loads(forward(x)) == loads(reverse(forward(x)))` holds for the only pre-slice fixture that exists. The reverse-migrated record is schema-invalid under the OLD schema's stated intent (which required `approved=true` for `done`) — but it is identical to what shipped, and the old schema was never honored in practice (the inverted checker accepted it). Reviewers must read this carefully: we are choosing fidelity-to-shipped-reality over fidelity-to-old-schema-intent because no v0 record with `approved=true` and `phase=done` has ever existed.
- Rejected **3b** (`approved=true` on reverse): would write a value that has never existed in any pre-slice record; breaks the existence-preservation property; offers no benefit because the old `done` branch was never the safely-shippable case.
- Rejected **3c** (refuse downgrade): forces operators to hand-edit; defeats the "at least one prior version" reversibility requirement (spec hard constraint).

### Consequences

- **Breaking**: `done` records that previously included `approved=true` or `approved=false` will be ACCEPTED by the v2 checker regardless of value (the constraint is dropped on the `done` branch only). Records that previously failed the inverted checker (i.e., `approved=true done`) now pass.
- **Migration**: T0-1 migrator adds `state_schema_version: 2`. The migrator does NOT delete `approved` from `done` records (the field still exists at top level); it only ensures the record is consistent with v2 rules.
- **`--reverse`**: writes `state_schema_version: 0` (i.e., removes the field), and writes `approved=false` if missing.
- **Weak-model fit**: the rejection diagnostic for any phase ≠ `done` mentioning `approved` is unchanged. The `done` case becomes "anything goes for `approved`", which a Haiku-class agent learns as "I don't have to remember the value for done".
- **Test churn**: the test in `scripts/test_harness.py` asserting `done requires approved=false` is deleted; replacement asserts the new shape (per spec §9.4).

---

## ADR-002: Scope Matching Syntax

### Context

`scripts/lib/worktree.py:4` imports `fnmatch` but never calls it; `matches_any` at lines 76-84 performs prefix/exact match only. Any pattern containing `*`, `?`, `[`, `]` silently matches zero paths. Spec §3 calls this a correctness defect. Spec §6 ADR-002 offers four options plus a precedence sub-decision.

### Options Considered

- **Option 1** (prefix + exact only; reject globs at load time). Rejected: the dead `fnmatch` import is a clear "intent was glob" signal; reverting to literal-only after promising globs is a UX regression for anyone who has written `**/*.md`-style entries in their planning notes.
- **Option 2** (full `fnmatch`). **SELECTED.** Activates the dead import. `fnmatch` is stdlib (no new dep).
- **Option 3** (`pathspec` gitignore). Rejected: adds a new dependency; spec hard constraint forbids new deps.
- **Option 4** (two-field split). Rejected: doubles the schema surface for a single field that low-reasoning agents already confuse with `blocked_paths`; spec §9.1 prioritizes weak-model success.

### Decision

Adopt option **2**: `allowed_paths` and `blocked_paths` accept glob patterns. Patterns with no glob metacharacters retain prefix/exact semantics (with trailing-slash → directory prefix).

**Glob grammar (the contract; `fnmatch` is the reference implementation, not the contract):**

- Metacharacters:
  - `*` — matches any run of characters except `/`.
  - `?` — matches exactly one character, which MUST NOT be `/`.
  - `[abc]` — character class; matches one character from the set.
  - `[!abc]` — negated character class; matches one character not in the set. `!` is the only negation operator. `^` is NOT supported as a negation operator (treated as a literal `^` inside the class).
  - `**` — NOT a separate operator. Treated as `*` (i.e., does not cross `/`). Authors who want recursive descent MUST write multiple entries (e.g., `dir/*.md` and `dir/*/*.md`) or accept that `**/*.md` matches only one level.
- Separator: `/` only. Backslash is treated as a literal character. Windows paths are out of scope (spec non-goal).
- Case-sensitive comparison on all platforms.
- Trailing-slash normalization: a literal pattern ending in `/` (e.g., `dir/`) is normalized to `dir/*` before matching, preserving prior directory-prefix semantics.

**Reference implementation:** Python `fnmatch.fnmatchcase`. Non-Python adapters MUST implement equivalent semantics under the grammar above; they MUST NOT rely on `fnmatch` quirks that diverge from the grammar (notably: stdlib `fnmatch.fnmatchcase` does NOT treat `/` as a separator — adapters and the reference implementation are responsible for the separator semantics described above, layered on top of `fnmatchcase` if needed).

`matches_any` calls the grammar-conformant matcher AND the existing prefix/exact branch; either match returns true.

### Sub-decisions

- **(a) SELECTED**: entry-level precedence. `blocked_paths` always overrides `allowed_paths` when both match the same path. Rationale: spec §6 ADR-002 explicitly states "Spec preference is (a) for low-reasoning agent legibility". The rule is one sentence ("block beats allow") and an agent can verify it from the field name alone.
- Rejected **(b)** (longest-match): "more specific" requires the agent to count characters; no muscle memory.
- Rejected **(c)** (order-of-declaration): JSON object/array order is fragile under reformatting; round-trip through `json.dumps(..., sort_keys=True)` (used in `scripts/lib/state.py:69`) would change behavior.

### Consequences

- **Breaking**: any consumer who relied on a pattern containing `*` matching zero paths (the dead-import silent behavior) will see those patterns START matching. T0-2 release notes MUST call this out.
- **Migration**: none required at the file level. Each `allowed_paths` entry whose meaning changes will be detected by `harness check --worktree`; if the new behavior is undesired for a specific entry, the user MUST escape it (e.g., add the literal string to `blocked_paths`).
- **Weak-model trap mitigation (G3-B):** at `harness check` load, the loader scans `allowed_paths` and `blocked_paths` for entries containing any of `*`, `?`, `[`, `!`, `]`. For each such entry: the loader checks whether a literal file or directory exists at the unglobbed path (i.e., treating the pattern string as a literal path). If so, it emits a one-time warning:
  ```
  warning: {field}[{index}] = {pattern!r} contains glob metacharacters, but a literal file/directory exists at the same path. The entry will be interpreted as a glob, not a literal. To match the literal path, escape the metacharacter (e.g., wrap in '[' and ']') or remove the metacharacter.
  ```
  Exit 0. The warning is rate-limited to one per pattern per `check` invocation.
- **Rejection path**: there is no "reject unsupported syntax" path under option 2; everything the grammar describes is supported. Option 2 collapses the v2 backlog "fail loudly on unsupported syntax" requirement into "the grammar IS the support surface".

---

## ADR-003a: Phase Transition Primitive

### Context

Spec §6 ADR-003a hard constraints: ≤2 CLI verbs total on the lifecycle path, zero required flags on the lifecycle path, no signing. Three options on the ballot: CLI-only (option 1), CLI + warn (option 2), thin wrapper + direct-edit-with-confirmation (option 3). Spec §3 names self-attestation as a release blocker. Spec D2 locks `.harness/session.lock` as the session lockfile convention.

**Revision note (G1-B):** the constraint "≤2 lifecycle verbs" is preserved exactly. A third operational verb (`harness session unlock`) is added for stale-lockfile recovery. The lifecycle-vs-operational distinction is explicit: `set` and `approve` advance state; `session unlock` is a recovery utility that does not write `.scratch/phase-state.json`.

### Options Considered

- **Option 1** (CLI-only, hard-fail on direct edit). Rejected: every existing `.roo/commands/*.md` and `.opencode/commands/*.md` instructs the agent to read/verify `.scratch/phase-state.json` and (in some cases) edit it. Hard-fail on direct edit forces a same-PR rewrite of all adapter commands AND all SKILL files. Spec §9.1 requires N=50 trials at ≥80% pass on a Haiku-class agent; cold-flipping the trust model fails this with high probability.
- **Option 2** (CLI + warn). **SELECTED.** CLI is the sanctioned path. Direct edits still pass the checker but produce a high-severity warning naming the missing audit-sidecar entry. Preserves muscle memory while making the CLI the obviously-easier path. Spec §2.1 explicitly lists "warn-not-fail" as an on-ballot variant to preserve weak-model muscle memory.
- **Option 3** (CLI + interactive confirmation prompt). Rejected: interactive prompts break headless CI; the spec's §10.2 smoke harness runs scripted, and the prompt either auto-answers (defeats the purpose) or blocks the smoke (defeats CI).

### Decision

Adopt option **2**.

**Verb shape (2 lifecycle + 1 operational):**

1. `harness phase set <phase>` — lifecycle. Sets the current phase. Optional flags capped at 3 (G3-C): `--plan-id`, `--summary`, `--reset-approval`. No required flags. Verb is positional; the phase name (`discuss`/`plan`/`execute`/`done`) is read from `argv[1]` of the subcommand. Additional fields previously settable as flags (`--next-action`, `--checkpoint`, `--checkpoint-path`, `--state-path`, `--plan-path`) are now settable only via stdin JSON: `echo '{"next_action":"..."}' | harness phase set plan --stdin-json`. The `--stdin-json` flag itself counts as a fourth flag; we accept this exception because it is a single "advanced path" flag that does not multiply with content.
2. `harness phase approve` — lifecycle. Flips `approved=true` and stamps `approved_by` (from `git config user.email` or `$USER`) and `approved_at` (`now_utc()` to nanosecond precision). No required flags. Optional flags capped at 3: `--by`, `--at`, `--stdin-json`.
3. `harness session unlock` — operational (G1-B). Reads `.harness/session.lock`, validates whether the recorded `pid` is still alive (`os.kill(pid, 0)`), checks `boot_id` if recorded (Linux: `/proc/sys/kernel/random/boot_id`; macOS: skipped, treated as None), and removes the lockfile if confirmed stale. Optional flags: `--force` (skip validation), `--print` (print lockfile contents, do nothing else). Exit 0 on successful unlock; exit 3 if process appears live; exit 7 if staleness cannot be determined (e.g., boot_id absent, PID lookup ambiguous).

Both lifecycle verbs touch the T0-A atomic-write primitive only. Both write a single-line entry to `.harness/audit.log` (newline-delimited JSON) via the atomic-append protocol described in G1-A below.

**Transition validation:** `phase set` consults the state machine in ADR-001. Invalid transitions exit 2 with diagnostic naming the current phase, target phase, and remediation (e.g., "run `harness phase approve` first" or "pass `--reset-approval`").

**Direct-edit policy:** `check` continues to accept `.scratch/phase-state.json` after a direct edit. If the audit log's most recent before-hash for the file does NOT match the current on-disk hash, `check` emits the drift-warning template (see Artifact 1) and exits 0. The warning is high-severity (printed to stderr, prefixed `warning:`).

**First-write / empty-log case (G1-A, G2-D):** drift detection is suppressed when `audit.log` has zero entries (file absent or zero-byte). In that case `check` exits 0 silently without warning. The first lifecycle verb invocation creates the file with `index=1` and records the post-write hash.

**State file location:** stays at `.scratch/phase-state.json`. No relocation. Rationale: relocating would force a parallel migration of every adapter command file and SKILL file in the same PR; spec §7 T1-S is scoped as surface-touch only.

**Uninstall — revised per G4-C:** three independent flags, plus an aggregate:
- `--remove-state` (new): removes `STATE_FILE_PATHS` (the live gate JSON).
- `--remove-operational` (new): removes `OPERATIONAL_PATHS` (`.harness/audit.log`, `.harness/session.lock`, and `.harness/backups/`).
- `--remove-install-state` (existing): removes `INSTALL_PATHS` (`.harness/installed-manifest.json`).
- `--remove-all`: removes all three tuples.

Each flag is independent; calling more than one is supported. Default (no flag) preserves all state.

**Session lockfile:** `.harness/session.lock`. See G1-B below for the full lifecycle contract.

### Sub-decisions

- **`STATE_FILE_PATHS` artifact**: see Artifact 2.
- **`OPERATIONAL_PATHS` artifact**: see Artifact 2 (new tuple per G1-C).
- **Audit log path**: `.harness/audit.log` (newline-delimited JSON). Operational state, in `OPERATIONAL_PATHS`.
- **Session lockfile path**: `.harness/session.lock`. Operational state, in `OPERATIONAL_PATHS`.
- **Backups path**: `.harness/backups/`. Operational state, in `OPERATIONAL_PATHS` (G1-D).

### G1-A: `audit.log` atomicity and rotation

**Atomic-append protocol (selected):** use `fcntl.flock(fd, LOCK_EX)` around append with single-byte-bounded line writes. Rationale for picking the flock variant over write-tmp-and-rename:
- Append is the dominant operation (every CLI invocation appends one line). Tmp-and-rename would force re-reading the entire log on every append, which is O(n) per write.
- Each audit line is bounded by 4 KiB (verb name, two SHA-256 hex strings, ISO-8601 timestamp, email, ≤256-byte args object). On Linux PIPE_BUF is 4096, on macOS 512. To stay safely under macOS PIPE_BUF we constrain audit lines to ≤512 bytes; if a serialization exceeds this, the writer truncates `args` to `{"truncated": true}` and the full payload is recorded as a separate side-record file (`.harness/audit.overflow/<index>.json`). This guarantees the actual `write(2)` is atomic at the kernel level even without flock; the flock is belt-and-suspenders for cross-process serialization.
- Protocol:
  1. Open `.harness/audit.log` with `O_WRONLY | O_APPEND | O_CREAT`, mode `0o644`.
  2. `fcntl.flock(fd, LOCK_EX)`.
  3. Compute next `index` by reading the last line of the file (seek to end, scan backward for last `\n`).
  4. Build the line (single JSON object, no embedded newlines, terminated by `\n`).
  5. Assert `len(line) <= 512`; on overflow, write the overflow side-record and replace `args` with the truncation marker.
  6. `os.write(fd, line)` — single syscall, atomic under PIPE_BUF.
  7. `os.fsync(fd)`.
  8. `fcntl.flock(fd, LOCK_UN)`, `os.close(fd)`.

**Rotation:** rotate when `os.stat(path).st_size >= 10 * 1024 * 1024` (10 MiB) OR when `index >= 10000`, whichever comes first. Rotation procedure: under the same exclusive flock, `os.rename(path, f"{path}.1")`, shift `audit.log.1 → audit.log.2`, …, `audit.log.4 → audit.log.5`, deleting any pre-existing `audit.log.5`. Keep the last 5 rotated files. After rotation, the next write to the fresh `audit.log` starts at `index=1` but records `previous_rotation_last_index` in the first entry to maintain cross-rotation traceability.

**Deletion recovery:** if the operator deletes `audit.log` while the harness is idle, the next CLI write recreates the file with `index=1`. `check` skips drift detection on the next invocation with a one-time stderr warning:
```
warning: .harness/audit.log was missing and has been recreated; drift detection for .scratch/phase-state.json is suppressed for this invocation. The next CLI write will re-establish the baseline.
```

**Empty-log case:** as described above, when the log has zero entries, drift warnings are suppressed entirely.

**Allowed writers for `audit.log`** (documented for the T0-A grep gate, G1-C):
- `scripts/lib/audit.py` (new): the `audit_append(entry)` helper. Only call site for production writes.
- `scripts/test_harness.py`: tests may write via the same helper.

### G1-B: `session.lock` lifecycle

**Lockfile payload (JSON, single line, terminated by `\n`):**
```json
{"pid": 12345, "hostname": "host.local", "started_at_utc": "2026-05-16T19:30:45.123456789Z", "harness_version": "0.2.0", "boot_id": "abc-...-def"}
```
`boot_id` is `null` on macOS (no portable equivalent in scope); otherwise read from `/proc/sys/kernel/random/boot_id` on Linux.

**Acquisition:**
1. Open `.harness/session.lock` with `os.open(path, O_WRONLY | O_CREAT | O_EXCL, 0o644)`. If the call raises `FileExistsError`, exit 3 with the lockfile-exists template (Artifact 1).
2. On successful create, `fcntl.flock(fd, LOCK_EX | LOCK_NB)`. If the flock fails (race with another process that created the file via `O_EXCL` race-loser path — should not happen but defensive), close fd, unlink the file we just created, exit 3.
3. Write the JSON payload, `fsync`, close. The file remains in place with the lock released at close — the file's presence (not the OS-level lock) is the gate.

**Release:** on clean exit, the CLI explicitly unlinks `.harness/session.lock`. Cleanup is registered via:
- `atexit.register(cleanup_lockfile)` for normal termination.
- `signal.signal(SIGINT, ...)` and `signal.signal(SIGTERM, ...)` handlers that call `cleanup_lockfile()` then re-raise.
- `try/finally` around the main verb body for synchronous failure paths.

**Staleness recovery:** the `harness session unlock` verb (defined above).

**Exit codes:** lockfile-exists = 3, stale-detection-uncertain = 7. Both documented in Artifact 1.

### G1-D: `.bak` retention (operational paths home)

**Filename grammar (revised):** `<original_basename>.pre-repair.<ISO-8601-nanos>.<pid>.bak`
- Example: `STATE.md.pre-repair.20260516T193045.123456789Z.12345.bak`
- ISO-8601 with nanosecond precision, no separators in the time part, `Z` for UTC.
- PID disambiguates concurrent repairs from different harness instances against the same file.

**Location (revised — moved out of `.planning/`):** `.harness/backups/<original_basename>.pre-repair.<...>.bak`. Rationale: `.planning/` is under user-edit territory and frequently `git add .`-ed. Backups in `.harness/` are scoped operational state, captured by `OPERATIONAL_PATHS` and the project `.gitignore` template.

**Retention cap:** on each `state repair` write, after the new `.bak` is written, the helper enumerates `.harness/backups/<original_basename>.pre-repair.*.bak`, sorts by the embedded timestamp (lexically sortable due to the fixed-width ISO format), and unlinks all but the most recent 10. Pruning happens after a successful new backup write so a failed repair never reduces the retention count.

**.gitignore (mandatory, not SHOULD):** T0-5 sub-requirement adds these entries to the installed project's `.gitignore`:
```
.harness/audit.log
.harness/audit.log.*
.harness/audit.overflow/
.harness/backups/
.harness/session.lock
```
Installer adds them at install time and on `harness upgrade` if missing.

### G1-E: Migrator crash race

**Refuse to overwrite existing `.bak`:** both `--forward` and `--reverse` migrators open the backup with `os.open(bak_path, O_WRONLY | O_CREAT | O_EXCL, 0o644)`. On `FileExistsError`, the migrator exits 1 with:
```
error: backup file already exists at {bak_path}; this typically indicates a previous migration crashed. Inspect the backup and either:
  (a) restore it manually (cp {bak_path} {target}) and re-run, or
  (b) run 'harness migrate state --resume' to continue from the backup, or
  (c) remove {bak_path} after confirming target is correct.
```

**`--resume` sub-verb:** `harness migrate state --resume` reads the most recent backup for the target, verifies its SHA-256 matches a "pre-migration" hash recorded in a sidecar `.harness/backups/<basename>.pre-repair.<...>.bak.resume.json`, and either:
- If the target's current hash matches the backup hash: re-run the migration from scratch (the migration never started writing the target).
- If the target's current hash matches the EXPECTED post-migration hash recorded in the sidecar: declare migration complete and remove the lock state.
- Otherwise: refuse and direct the operator to manual inspection.

The sidecar `.resume.json` is written BEFORE the target is touched, alongside the backup, under the same `O_EXCL` discipline. It records `{pre_hash, expected_post_hash, target_path, migrator_version, started_at}`.

### Consequences

- **Breaking**: agents that wrote `.scratch/phase-state.json` directly will see a stderr warning. CI that greps stderr for `warning:` will need an exemption or a CLI-path migration.
- **Adapter mirror**: `.roo/commands/phase-execute.md` and `.opencode/commands/execute.md` MUST replace the "verify `.scratch/phase-state.json` directly" instruction with `harness phase set execute && harness phase approve` invocations (T1-S sub-task; no additive ambiguity).
- **Weak-model fit**: two lifecycle verbs, four lifecycle phases, no required flags, ≤3 optional flags per verb. The Haiku menu is six items total (`set discuss`, `set plan`, `set execute`, `set done`, `approve`, plus the direct-edit-with-warning fallback) plus the rarely-used `session unlock`. Within spec §9.1 ergonomic budget.

---

## ADR-003b: Field Ownership Matrix

### Context

ADR-003a chose option 2 (CLI + warn). This means direct edits remain LEGAL but discouraged. ADR-003b's option space is therefore constrained: every field has at minimum a `user` writer (because direct edits are not blocked); the question is which fields are CLI-PREFERRED (i.e., the CLI verb sets them and the audit log records the change) vs CLI-EXCLUSIVE-IN-PRACTICE (the CLI verb is the only path that knows the correct value).

### Options Considered

- **Option A** (every field user-editable, no CLI ownership). Rejected: defeats the warn-on-drift mechanism; no field has a canonical CLI writer for the audit log to reference.
- **Option B** (lifecycle fields CLI-preferred, narrative fields user-editable). **SELECTED.** Splits cleanly along the line "fields that have a single canonical right answer the CLI can compute" vs "fields with content the user authors".
- **Option C** (all fields CLI-only). Rejected: would force CLI surface for `summary`, `acceptance_criteria`, etc., which are paragraph-level content; the CLI verb would devolve into "read multi-line input from stdin" and lose the zero-required-flags property.

### Decision

Adopt option **B**. See Artifact 3 below for the full table.

**CLI-preferred fields** (CLI is the canonical writer; direct edit emits drift warning):
- `phase` — written by `harness phase set <phase>`.
- `approved`, `approved_by`, `approved_at` — written by `harness phase approve` EXCEPT when `phase=done` (see G2-C below).
- `state_schema_version` — written by `harness migrate state` (T0-1 row's migrator); never user-edited.
- `updated_at`, `updated_by` — re-stamped by both lifecycle verbs on every write.

**User-editable fields** (CLI does not write these; direct edit is the canonical path):
- `plan_id`, `summary`, `plan_path`, `state_path`, `checkpoint_path`, `current_checkpoint`, `next_action`
- `allowed_paths`, `blocked_paths`
- `acceptance_criteria`, `verification`, `review`, `notes`
- `automation_mode`, `auto_selected`

**Optional CLI flag writes:** `harness phase set plan --plan-id X --summary "..."` writes `plan_id` and `summary` as a convenience; this is opt-in, not the canonical path. Other narrative fields are reachable via `--stdin-json` (see ADR-003a).

### G2-C: `done.approved` ownership clarification

After ADR-001 dropped the `approved` constraint on the `done` branch, the field is unconstrained in that phase. The question raised in review: does `harness phase set done` write `approved`, and if so, to what value?

**Resolution:** `harness phase approve` becomes a NO-OP when the current phase is `done`. The CLI does not write to `approved`, `approved_by`, or `approved_at` in the `done` phase. Rationale:
- The schema permits any value, so there is no "right" value to write.
- Writing `true` would imply the CLI is asserting approval the user did not request via CLI; writing `false` would clobber a legitimate prior approval stamped during `plan→execute`.
- Adding a `--approved` flag to `phase set done` would push the optional-flag count past the cap of 3 and add a decision point with no good default for low-reasoning agents.

**Behavior:** `harness phase approve` called when `phase=done` exits 2 with:
```
error: cannot approve phase=done; the done phase carries no approval semantics. Use 'harness phase set discuss --reset-approval' to start a new cycle.
```

The fields `approved`/`approved_by`/`approved_at` in a `done` record are therefore READ-ONLY-POST-TRANSITION from the CLI's perspective: whatever value was set during the `execute → done` transition is preserved verbatim. Direct edits to these fields in a `done` record do NOT emit drift warnings (the CLI has no canonical hash to compare against because it does not write them in this phase).

Artifact 3 reflects this with the cell value `user` for `approved`/`approved_by`/`approved_at` in the `done` column (changed from `cli (any; see ADR-001)`).

### Consequences

- **Breaking**: none in this row alone; the matrix is descriptive, not enforced via schema constraint. Enforcement is via the audit-log warning mechanism (ADR-003a).
- **Documentation**: `docs/protocol-spec.md#field-ownership` MUST contain the table verbatim from Artifact 3.

---

## ADR-004: Verification Field Shape

### Context

`scripts/lib/check.py:99-111` declares `VERIFICATION_PREFIXES` mixing 4 machine verbs with 6 review/free-text verbs. The bare `"Roo"` prefix means `"Room is great"` passes machine verification (spec §3). Spec §6 ADR-004 offers four options and three hard sub-constraints: (i) rejection diagnostic enumerates verbs inline, (ii) ≤8 verbs, (iii) error cites verbs source path.

**D-G4 decision:** `bash ` is REMOVED from the allowlist (8 → 7 verbs). Rationale per the Ops Hawk review: a bare `bash ` prefix is a very low trust ceiling — any shell script invocation passes machine verification regardless of content. The remaining 7 verbs are either argument-bounded (e.g., `pytest <path>`) or structured (e.g., `jq <expr> <file>`). Verification entries that previously used `bash scripts/foo.sh` migrate to `make foo` (preferred) or `python3 scripts/foo.py` (if direct).

### Options Considered

- **Option 1** (two fields: `verification` machine + `review` human). **SELECTED.** Clean split. `verification` is `array<string>` (each string must start with a registered command verb); `review` is `array<object>` with typed evidence. Two separate validators; two separate error messages.
- **Option 2** (discriminated union). Rejected: discriminated unions are a known weak-model trap.
- **Option 3** (tighten allowlist + parallel `review_evidence`). Rejected: structurally identical to option 1 but with a less-clear field name.
- **Option 4** (config-file allowlist). Rejected: spec sub-constraint (iii) requires the error to cite the allowlist location, and a config file would itself need a schema, recursing the problem.

### Decision

Adopt option **1**. Schema gains:

- `verification`: existing `array<string>`, items MUST start with one of the **7** allowlist verbs (see Artifact 4).
- `review`: new `array<object>`, items have `{actor: string, at: ISO-8601-UTC, evidence_path: string, summary: string}`. All four required.

The allowlist is hard-coded in `scripts/lib/check.py` (constant `VERIFICATION_PREFIXES`) and DOCUMENTED in `docs/protocol-spec.md#verification-allowlist`.

**Rejection diagnostic (revised, 7 verbs):**

```
error: {path} verification[{index}] = {value!r} does not start with an allowed verb.
Allowed verbs (7): python3, git, jq, npx, pytest, harness, make.
See docs/protocol-spec.md#verification-allowlist (source: scripts/lib/check.py VERIFICATION_PREFIXES).
```

### G4-B: Verification execution trust boundary

`verification` strings are READ by `harness check` for prefix validation ONLY. They are NOT executed by the core CLI. The core CLI's contract is:
- Parse each `verification[*]` string.
- Assert it begins with one of the 7 allowlist verb prefixes.
- Report violations; never invoke the string.

**Smoke-test adapters MAY execute** `verification` strings as part of release readiness checks. When they do, the smoke runner SHALL document its trust boundary explicitly in the runner's documentation. Recommended boilerplate:

> The smoke runner executes `verification[*]` strings as shell input on behalf of the developer who authored them. Verification entries should therefore be treated as DEVELOPER-TRUSTED shell input. Do not run the smoke against a `phase-state.json` authored by an untrusted party without prior review.

`scripts/release_smoke_test.py` is the in-tree reference smoke runner; it gains a header comment to this effect in T0-3.

### Sub-decisions

- Constraint **(i) inline-enumerated verbs**: satisfied by the template above; the verbs are printed verbatim.
- Constraint **(ii) ≤8 verbs**: 7 verbs (well within cap).
- Constraint **(iii) error cites source path**: the line `See docs/protocol-spec.md#verification-allowlist (source: scripts/lib/check.py VERIFICATION_PREFIXES)` satisfies this.

### Consequences

- **Breaking**: every existing record whose `verification` entry started with `Validate `, `Review `, `Inspect `, `Confirm `, `Roo`, `core-only `, `OpenCode-only `, or `bash ` will be REJECTED by the v2 checker. The current live fixture `.scratch/phase-state.json:34-39` is safe — all four entries start with `python3 `.
- **Migration**: the T0-1 migrator MUST scan `verification` entries and either (a) leave them if they match the new allowlist, or (b) move them to `review` with a synthesized `{actor: <verb-token>, at: <updated_at>, evidence_path: "", summary: <full text>}`. The synthesized `evidence_path: ""` is the empty-string sentinel — `review` items with empty `evidence_path` are accepted but flagged by `doctor` as needing manual completion. `bash`-prefixed entries are migrated under this same rule with `actor: "bash"`.
- **Doctor**: a new `doctor` finding "review entry has empty evidence_path" is added (T0-4 acceptance).
- **`scripts/release_smoke_test.py`** and `scripts/test_harness.py`: their `verification` entries are all-`python3 ` already; no churn.

---

## ADR-005: `state_repair` Preservation Policy

### Context

`scripts/lib/state_repair.py` rewrites `.planning/STATE.md` and `.planning/ROADMAP.md`. Today it preserves outside-managed-block content via `_wrap_section_in_block` (lines 79-120). Spec §3 cites `scripts/lib/state_repair.py:197` swallowing `JSONDecodeError`. Spec §5 requires paused phases (e.g., `02-skill-pack-expansion`) be first-class. Spec §6 ADR-005 offers four options.

### Options Considered

- **Option 1** (preserve verbatim, no backup). Rejected on its own: no safety net.
- **Option 2** (refuse on non-managed content). Rejected: users author non-managed content (the spec EXPECTS narrative outside `## Phases`).
- **Option 3** (preserve verbatim + write `.bak` with timestamp). **SELECTED.** Combines the safety of option 1 with a one-time recovery artifact, now with the G1-D revisions (location, retention, filename grammar).
- **Option 4** (interactive `state repair --interactive`). Rejected: same headless-CI problem as ADR-003a option 3.

### Decision

Adopt option **3** with G1-D revisions.

**Behavior:**
1. Before any rewrite of `.planning/STATE.md` or `.planning/ROADMAP.md`, `state_repair` writes `.harness/backups/<basename>.pre-repair.<ISO-8601-nanos>.<pid>.bak` via the T0-A atomic primitive AND `O_EXCL` (G1-E). After successful write, the retention pruner caps backups per-original at the 10 most recent.
2. Content outside the managed `## Phases` block (and outside any other managed marker block) is preserved BYTE-FOR-BYTE — no whitespace normalization, no trailing-newline addition outside the managed payload.
3. Paused phases (per spec §5) are represented as first-class state in `.planning/STATE.md`. The managed `state-current` block payload gains a `### Paused Phases` subsection listing phases with status `paused`. `state_repair` reads paused status from `.planning/STATE.md`'s pre-rewrite `### Paused Phases` subsection inside the managed block, or from the canonical pause-marker file (spec §5 leaves this to T0-5 implementation; the ADR mandates only "first-class, not deleted as orphan content").
4. If `phase-state.json` is unparseable (`JSONDecodeError`), `state_repair` aborts with exit code 5 (per the revised exit-code split: 5=unparseable-json) and the diagnostic: `error: .scratch/phase-state.json is unparseable ({exc}); fix the JSON or restore from a backup before running 'harness state repair'`. No rewrite of `.planning/STATE.md` or `.planning/ROADMAP.md` occurs. This replaces the current swallow at `scripts/lib/state_repair.py:197`.

### Sub-decisions

- **`.bak` retention**: 10 most recent per original; auto-pruned on each `state repair` write (G1-D).
- **`.bak` location**: `.harness/backups/` (G1-D). Mandatory `.gitignore` entry.

### Consequences

- **Breaking**: none for content; additive. `.bak` files accumulate in `.harness/backups/` (capped at 10); `.gitignore` includes the directory by default.
- **Atomic primitive**: `.bak` write goes through T0-A AND `O_EXCL`. The original is then written via T0-A. Order: write `.bak` first; if that fails or the file already exists, abort before touching the original (G1-E).
- **Paused-phase representation**: T0-5 implementation must edit `.planning/STATE.md` BEFORE T0-5 lands to define the `### Paused Phases` subsection structure. Spec §5 mandates this ordering.

---

## Artifact 1 — CLI Contract

### Verb 1: `harness phase set <phase>` (lifecycle)

**Synopsis:**
```
harness phase set discuss|plan|execute|done
                  [--plan-id PLAN_ID]
                  [--summary SUMMARY]
                  [--reset-approval]
                  [--stdin-json]
```

**Required positional arg:** `<phase>` ∈ `{discuss, plan, execute, done}`. No required flags.

**Optional flag cap (G3-C):** 3 user-facing flags (`--plan-id`, `--summary`, `--reset-approval`) plus `--stdin-json` as the escape hatch for less-common fields. Fields not exposed as flags (`next_action`, `current_checkpoint`, `checkpoint_path`, `state_path`, `plan_path`) are settable via:
```
echo '{"next_action":"...", "current_checkpoint":"CP-01-04"}' | harness phase set plan --stdin-json
```

**Transition validation:** consults ADR-001 state machine. Invalid transitions exit 2 with diagnostic.

**Input (JSON shape, internal representation after argparse):**
```json
{
  "verb": "phase.set",
  "phase": "discuss|plan|execute|done",
  "plan_id": "string|null",
  "summary": "string|null",
  "reset_approval": false,
  "stdin_json": {"next_action": "string|null", "current_checkpoint": "string|null", "checkpoint_path": "string|null", "state_path": "string|null", "plan_path": "string|null"}
}
```

**Output (stdout, JSON):**
```json
{
  "ok": true,
  "verb": "phase.set",
  "previous_phase": "string",
  "phase": "string",
  "state_path": ".scratch/phase-state.json",
  "audit_entry_index": 42,
  "updated_at": "2026-05-16T19:30:45.123456789Z",
  "updated_by": "hjung3113@gmail.com"
}
```

**Exit codes (revised split):**
- `0` — ok.
- `1` — generic error (write failure, IO).
- `2` — invalid transition (per ADR-001 state machine).
- `3` — session lockfile present (`.harness/session.lock` exists; another session active).
- `4` — `SCOPE_VIOLATION` — assigned to T1-1 (scope enforcement: write outside `allowed_paths` or matching `blocked_paths`). Reservation for "schema-version refusal" is lifted; that signal will use a code in the 9..15 range when `02c-hardening` ships. See ledger entry L16 and `.planning/phases/02b-hardening/CONTRACT-PIN.md` §4.
- `5` — unparseable JSON (state file or stdin).
- `6` — wrong phase for verb (e.g., `harness phase approve` when current phase is `done`).
- `7` — stale-detection-uncertain (used by `harness session unlock`; not normally raised by `phase set`).
- `8` — timestamp out of range (`--at` arg not within 24h of `datetime.now(UTC)`).

**Error templates** (printed to stderr):
- Lockfile: `error: active session detected at .harness/session.lock; finish the session ('harness phase set done' or 'harness phase approve'), or run 'harness session unlock' after confirming no other harness process is running` → exit 3.
- Invalid transition: `error: cannot set phase={target} from phase={current} (see ADR-001 transition table). {remediation}` → exit 2. Remediation is one of: "Run 'harness phase approve' first." | "Pass --reset-approval to clear prior approval and proceed." | "Transition is undefined; choose discuss/plan/execute/done as the next step."
- Unparseable state: `error: .scratch/phase-state.json is unparseable ({exc}); fix the JSON or restore from a backup before retrying.` → exit 5.
- Timestamp out of range: `error: --at value {value!r} is not within 24h of current UTC time ({now}); refusing to write a far-future or far-past timestamp.` → exit 8.

**Idempotency:** `harness phase set X` when current phase already equals X is safe; re-running re-stamps `updated_at`/`updated_by` and appends a new audit-log entry of type `phase.set.noop`. Expect a new audit-log entry each time `phase set` or `phase approve` is invoked.

### Verb 2: `harness phase approve` (lifecycle)

**Synopsis:**
```
harness phase approve [--by EMAIL] [--at ISO-8601-UTC-NANOS] [--stdin-json]
```

**Required positional arg:** none. No required flags. (`--by` and `--at` are reserved for replay/testing; default to `git config user.email`/`$USER` and `now_utc()` to nanosecond precision.)

**Optional flag cap (G3-C):** 3 flags total (`--by`, `--at`, `--stdin-json`).

**`--at` validation:** must parse as ISO-8601 UTC and must be within 24h of `datetime.now(timezone.utc)`. Out-of-range values exit 8.

**`approved_at` precision:** nanoseconds. Format: `2026-05-16T19:30:45.123456789Z`. Generated via `time.time_ns()` on supported platforms.

**Input (JSON shape):**
```json
{
  "verb": "phase.approve",
  "by": "string|null",
  "at": "string|null"
}
```

**Output (stdout, JSON):**
```json
{
  "ok": true,
  "verb": "phase.approve",
  "phase": "string",
  "approved": true,
  "approved_by": "hjung3113@gmail.com",
  "approved_at": "2026-05-16T19:30:45.123456789Z",
  "state_path": ".scratch/phase-state.json",
  "audit_entry_index": 43,
  "updated_at": "2026-05-16T19:30:45.123456789Z",
  "updated_by": "hjung3113@gmail.com"
}
```

**Exit codes:** 0/1/2/3/5/6/8 with same semantics as `phase set`.

**Error templates:**
- Wrong phase: `error: cannot approve phase={current}; approval is only valid in phase=plan (transitions to execute) or phase=execute (re-approval after change). For done, use 'harness phase set discuss --reset-approval' to start a new cycle.` → exit 6.
- Lockfile: same as `phase set`.
- Timestamp out of range: same as `phase set`.

**Idempotency:** `harness phase approve` in `phase=plan` or `phase=execute` when `approved=true` is already set re-stamps `approved_by`/`approved_at` and writes a new audit entry. In `phase=done`, exits 6 (G2-C).

### Verb 3: `harness session unlock` (operational, new per G1-B)

**Synopsis:**
```
harness session unlock [--force] [--print]
```

**Required positional arg:** none. No required flags.

**Behavior:**
1. Read `.harness/session.lock`. If absent, exit 0 silently.
2. Parse the JSON payload. If unparseable, exit 5.
3. If `--print`, print the payload to stdout and exit 0.
4. Validate staleness: `os.kill(pid, 0)` to check liveness; compare `boot_id` to current boot_id if available.
5. If process appears live and `--force` not given, exit 3 with diagnostic.
6. If staleness cannot be determined (e.g., `boot_id` was null and PID lookup is ambiguous) and `--force` not given, exit 7.
7. Unlink the file. Exit 0.

**Exit codes:** 0 ok; 3 process appears live; 5 unparseable lockfile; 7 staleness uncertain.

### Audit log format (`.harness/audit.log`)

Newline-delimited JSON, append-only, via the G1-A atomic-append protocol:
```json
{"index": 42, "verb": "phase.set", "args": {"phase": "execute"}, "before_sha256": "abc...", "after_sha256": "def...", "at": "2026-05-16T19:30:45.123456789Z", "by": "hjung3113@gmail.com"}
```

**Constraints:** each line ≤512 bytes (macOS PIPE_BUF). Overflow recorded in `.harness/audit.overflow/<index>.json`.

**Rotation:** at 10 MiB or 10000 entries, whichever first. Keep last 5 rotated files (`audit.log.1` .. `audit.log.5`).

**Path:** `.harness/audit.log`. Operational state, in `OPERATIONAL_PATHS`. Allowed writers documented in G1-A: only `scripts/lib/audit.py` `audit_append()`.

### Drift-warning template (printed by `harness check` to stderr, exit 0)

```
warning: .scratch/phase-state.json sha256 ({current}) does not match the last audit entry's after_sha256 ({expected}) at index {index}. Drift detected. To restore audit baseline, re-run the last CLI verb that should have produced this state (typically 'harness phase set {current_phase}' or 'harness phase approve'). Manual edits will not be tracked until 'harness phase audit' ships in 02c-hardening.
```

**Suppression cases (G2-D + G1-A):**
- Audit log has zero entries (or file absent): warning suppressed entirely.
- The on-disk state matches the audit log: no warning.
- In all other cases the warning is printed and `check` exits 0.

### G3-A: Canonical `phase=done` few-shot example

A complete, valid `phase-state.json` for `phase=done` after this slice ships. Annotations name the actor that set each field.

```json
{
  "state_schema_version": 2,
  "phase": "done",
  "approved": true,
  "approved_by": "hjung3113@gmail.com",
  "approved_at": "2026-05-16T19:30:45.123456789Z",
  "plan_id": "hardening-slice-01",
  "automation_mode": "manual",
  "auto_selected": [],
  "summary": "Hardening slice 02b complete: ADRs locked, atomic primitive landed, smoke green.",
  "state_path": ".planning/STATE.md",
  "plan_path": ".planning/phases/02-hardening/02b-PLAN.md",
  "checkpoint_path": ".planning/phases/02-hardening/02b-CHECKPOINTS.md",
  "current_checkpoint": "CP-02b-09",
  "next_action": "Start discuss for 02c-hardening.",
  "allowed_paths": ["scripts/", "docs/adr/", ".planning/"],
  "blocked_paths": [".harness/audit.log", ".harness/session.lock"],
  "acceptance_criteria": [
    "All six ADRs locked in a single PR.",
    "T0-A atomic primitive lands first."
  ],
  "verification": [
    "python3 scripts/harness.py check",
    "pytest scripts/tests/ -v",
    "harness check --worktree"
  ],
  "review": [
    {
      "actor": "hjung3113@gmail.com",
      "at": "2026-05-16T19:00:00.000000000Z",
      "evidence_path": "docs/reviews/02b-architect.md",
      "summary": "Architect review of bundle; G2 items addressed."
    }
  ],
  "notes": [
    "approved fields preserved from execute->done transition; not re-stamped by CLI in done phase (G2-C)."
  ],
  "updated_at": "2026-05-16T19:30:45.123456789Z",
  "updated_by": "hjung3113@gmail.com"
}
```

**Field-by-field actor annotation:**
- `state_schema_version` — set by `harness migrate state --forward` (system).
- `phase` — set by `harness phase set done` (CLI).
- `approved`, `approved_by`, `approved_at` — set by `harness phase approve` during the prior `plan→execute` or `execute→done` transition; NOT re-written in `done` (G2-C). From the CLI's perspective in `done`, these are user-only fields.
- `plan_id`, `summary`, `state_path`, `plan_path`, `checkpoint_path`, `current_checkpoint`, `next_action`, `allowed_paths`, `blocked_paths`, `acceptance_criteria`, `verification`, `review`, `notes`, `automation_mode`, `auto_selected` — user (direct edit).
- `updated_at`, `updated_by` — re-stamped by CLI on the last `phase set done` call.

---

## Artifact 2 — Path Tuples

The post-decision authoritative tuples of paths the harness manages. Single source of truth for the §10.2 grep gate, T1-S SKILL surface allowlist, and the uninstall flow.

```python
# Live gate state — the source of truth for phase semantics.
STATE_FILE_PATHS = (
    ".scratch/phase-state.json",
)

# Ephemeral operational state — audit, locks, backups.
OPERATIONAL_PATHS = (
    ".harness/audit.log",
    ".harness/session.lock",
    ".harness/backups/",
)

# Install manifest — what was placed on the system at install time.
INSTALL_PATHS = (
    ".harness/installed-manifest.json",
)
```

**Allowed writers for `STATE_FILE_PATHS`** (T0-A grep gate):
- `scripts/lib/state.py` (existing): the `write_state(state)` helper.
- `scripts/lib/migrate.py` (T0-1): the `--forward`/`--reverse` migrator.

**Allowed writers for `OPERATIONAL_PATHS`** (G1-C):
- `.harness/audit.log` and rotated siblings: only `scripts/lib/audit.py` `audit_append()` (and its rotation helper). See G1-A.
- `.harness/session.lock`: only `scripts/lib/session.py` `acquire_lock()` / `release_lock()` and `harness session unlock`. See G1-B.
- `.harness/backups/`: only `scripts/lib/state_repair.py` backup helper and `scripts/lib/migrate.py` backup helper. See G1-D, G1-E.

**Allowed writers for `INSTALL_PATHS`:**
- `scripts/install_harness.py` (existing) and `scripts/uninstall_harness.py` (existing).

**T0-A grep gate iterates BOTH `STATE_FILE_PATHS` and `OPERATIONAL_PATHS`** (G1-C). For each path in either tuple, the gate greps the entire `scripts/` tree (excluding the documented allowed writers) for write calls (`open(..., "w"...)`, `open(..., "a"...)`, `os.replace`, etc.) referencing the literal path string. Violations fail T0-A.

**Not in any tuple** (intentionally excluded; these are user content, not harness-managed):
- `.planning/STATE.md` (markdown durable memory, written via `state_repair`, but content is user-owned).
- `.planning/ROADMAP.md` (markdown durable memory).
- `.scratch/phase-state.schema.json` (schema, shipped artifact, not runtime state).
- `.scratch/phase-state.example.json` (example, not live state).

**Uninstall consumers (G4-C):**
- `--remove-state` consumes `STATE_FILE_PATHS`.
- `--remove-operational` consumes `OPERATIONAL_PATHS`.
- `--remove-install-state` consumes `INSTALL_PATHS`.
- `--remove-all` consumes all three.

---

## Artifact 3 — Field Ownership Matrix

Rows = field names. Columns = phases. Cells: `user` (direct edit canonical), `cli` (CLI verb canonical, direct edit warns), `system` (CLI/migrator writes only), `none` (field MUST be absent or null in this phase).

| Field | discuss | plan | execute | done |
|---|---|---|---|---|
| `phase` | cli | cli | cli | cli |
| `approved` | cli (=false) | cli (=false) | cli (=true) | **user** (G2-C) |
| `approved_by` | none | none | cli | **user** (G2-C) |
| `approved_at` | none | none | cli | **user** (G2-C) |
| `plan_id` | none | user | user | user |
| `summary` | user | user | user | user |
| `plan_path` | user | user | user | user |
| `state_path` | user | user | user | user |
| `checkpoint_path` | user | user | user | user |
| `current_checkpoint` | user | user | user | user |
| `next_action` | user | user | user | user |
| `allowed_paths` | user | user | user | user |
| `blocked_paths` | user | user | user | user |
| `acceptance_criteria` | user | user | user | user |
| `verification` | user | user | user | user |
| `review` (new, ADR-004) | user | user | user | user |
| `notes` | user | user | user | user |
| `automation_mode` | user | user | user | user |
| `auto_selected` | user | user | user | user |
| `state_schema_version` | system | system | system | system |
| `updated_at` | cli | cli | cli | cli |
| `updated_by` | cli | cli | cli | cli |

**Notes:**
- `cli` cells: direct edit is not blocked but emits the drift warning (Artifact 1, drift-warning template). The audit log records the canonical CLI write.
- `system` cells: only the migrator (`harness migrate state`) writes `state_schema_version`. Lifecycle CLI verbs do NOT write it.
- `none` cells: `harness phase set discuss` clears `approved_by`/`approved_at` to `null` if previously set. Schema allows `null` for these fields.
- `user` cells: SET via direct file edit. Optional CLI flags (`--plan-id`, `--summary`) are convenience writes that ALSO go through the audit log.
- `done.approved*` cells (G2-C): user-owned read-only-post-transition. `harness phase approve` exits 6 in `done`.

---

## Artifact 4 — Allowed Verification Verbs

**Allowlist (7 verbs, in canonical order — `bash ` removed per D-G4):**

```python
VERIFICATION_PREFIXES = (
    "python3 ",
    "git ",
    "jq ",
    "npx ",
    "pytest ",
    "harness ",
    "make ",
)
```

**Canonical source file:** `scripts/lib/check.py` constant `VERIFICATION_PREFIXES`.

**Documentation mirror:** `docs/protocol-spec.md#verification-allowlist` (created by T0-3). T0-3 acceptance includes a regression test asserting the doc and the constant match.

**Trust boundary (G4-B):** the core CLI READS these strings for prefix validation only. It NEVER executes them. Smoke runners that execute these strings document the trust boundary in their own README/header.

**Example values (one per verb):**

| Verb prefix | Example |
|---|---|
| `python3 ` | `python3 -m unittest scripts/test_harness.py` |
| `git ` | `git diff --name-only main...HEAD` |
| `jq ` | `jq -e '.phase == "done"' .scratch/phase-state.json` |
| `npx ` | `npx playwright test --reporter=line` |
| `pytest ` | `pytest scripts/tests/test_atomic.py -v` |
| `harness ` | `harness check --worktree` |
| `make ` | `make verify` |

**Removed from previous allowlist** (now belong in the new `review` field as `actor` or `summary`, or migrate to a different verb):
- `Validate `, `Review `, `Inspect `, `Confirm ` — review prose; move to `review[*].summary`.
- bare `Roo` — the false-positive root cause; removed.
- `core-only `, `OpenCode-only ` — bespoke per-adapter prefixes; their use cases are now scripted under `make core-only-checks` (preferred) or invoked as `harness check --adapter opencode`.
- `bash ` (D-G4) — too-broad shell escape; migrate to `make <target>` (preferred) or `python3 <script>` (direct).

**Adding an 8th verb:** spec §6 ADR-004 sub-constraint (ii) (≤8) leaves room; adding one still requires a separate ADR per the spec's amendment protocol. The current floor is 7; the cap is 8. The protocol-spec section documents this.

---

## Artifact 5 — Migration Spec

### Pre-slice → post-slice state shape diff

**Removed constraints:**
- Schema `allOf[3].then.properties.approved.const = true` (the `done` branch's `approved=true` constraint). DROPPED per ADR-001 option 3.

**Added fields:**
- `state_schema_version: integer` at the top level. T0-1 introduces with value `1`; this ADR bumps to `2` for new shape. Required as a presence-check; value enforcement is deferred (R-2, spec §2.8).
- `review: array<object>` at the top level. Items: `{actor: string, at: ISO-8601-UTC, evidence_path: string, summary: string}`. minItems: 0.

**Modified constraints:**
- `verification[*]` allowlist tightened to **7** verbs (Artifact 4, D-G4). Pre-slice entries failing the new allowlist are rewritten into `review[*]` by the migrator (see below). `bash`-prefixed entries are included in this rewrite.
- `approved_at` precision tightened to nanoseconds: format `YYYY-MM-DDThh:mm:ss.nnnnnnnnnZ`. Pre-slice records with second-precision timestamps are re-formatted by the migrator by appending `.000000000` before the `Z`.

### `--forward` transformation (G2-A: semantically equivalent, not byte-exact)

**Semantic guarantee:** `json.loads(forward(x))` equals the post-migration target state structurally. Serialization uses `json.dumps(state, sort_keys=True, indent=2, separators=(',', ': '))` with a trailing newline. The byte representation is determined by this canonical serializer; two records that `json.loads`-equal will `forward`-produce byte-identical output.

**Round-trip property test (T0-1 acceptance):**
- For any fixture `x` that is a valid v0 record:
  `json.loads(forward(x)) == json.loads(reverse(forward(x)))`
- Test fixtures live in `scripts/tests/fixtures/migrate/`.

**Input** (current live state, `.scratch/phase-state.json`):

```json
{
  "phase": "done",
  "approved": false,
  "approved_by": "user",
  "approved_at": "2026-05-14T15:00:00Z",
  "plan_id": "generalized-harness-release-01",
  "automation_mode": "manual",
  "auto_selected": [],
  "summary": "Generalized harness release work is approved in a separate repository copy.",
  "state_path": ".planning/STATE.md",
  "plan_path": ".planning/phases/01-generalized-harness-release/01-01-PLAN.md",
  "checkpoint_path": ".planning/phases/01-generalized-harness-release/01-CHECKPOINTS.md",
  "current_checkpoint": "CP-01-03",
  "next_action": "Phase 1 release complete. Start a new discuss pass for any further scope.",
  "allowed_paths": [
    "README.md",
    "CHANGELOG.md",
    "AGENTS.md",
    ".planning/",
    ".scratch/phase-state.json",
    ".opencode/",
    ".roo/",
    ".github/",
    "docs/",
    "harness/",
    "scripts/"
  ],
  "blocked_paths": [],
  "acceptance_criteria": [
    "Reviewer P1 findings for adapter alias, gate enforcement, release evidence, and core neutrality are addressed.",
    "README documents post-install commands and ready-to-use prompts.",
    "Release verification evidence records source checks, target matrix smoke, adversarial review, commit, and push."
  ],
  "verification": [
    "python3 -m unittest scripts/test_harness.py",
    "python3 scripts/harness.py check",
    "python3 scripts/harness.py check --worktree",
    "python3 scripts/release_smoke_test.py"
  ],
  "notes": [
    "This is a new repository copy created from the previous harness project.",
    "Core must remain stack-neutral and client-neutral.",
    "Skill packs are generic composable plugins."
  ],
  "updated_at": "2026-05-15T00:00:00Z",
  "updated_by": "codex"
}
```

**Output** (post-`--forward`, written via T0-A atomic primitive after creating the backup under `.harness/backups/phase-state.json.pre-repair.<ISO-nanos>.<pid>.bak` via `O_EXCL`):

The post-migration JSON contains all original fields with these additions:
- `"state_schema_version": 2` at top level.
- `"review": []` at top level.
- `"approved_at"` re-formatted to `"2026-05-14T15:00:00.000000000Z"`.

Canonical serialization is `sort_keys=True, indent=2, separators=(',', ': ')`, trailing newline. The post-migration on-disk bytes are determined solely by `json.loads(post) → json.dumps(canonical)`.

**Diff (semantic, not byte-exact in source insertion order):**
- Added: `state_schema_version=2`.
- Added: `review=[]`.
- Modified: `approved_at` from second precision to nanosecond precision (lexically distinct string; same Instant).
- All other field values: `json.loads`-equal to input.

### `--reverse` transformation (v2 → v0)

**Output produced by:**
1. Remove `state_schema_version` key.
2. Remove `review` key (and any non-empty content; if `review` was populated by the migrator's verification-rewrite, the data is LOST in the round-trip — this is acceptable because v0 had no `review` field).
3. Re-format `approved_at` back to second precision by truncating the fractional part (`.123456789` dropped). LOSSY for sub-second precision; acceptable because v0 records lacked sub-second precision.
4. Keep `approved=false` for `done` records (sub-decision 3a).
5. Re-emit via canonical serializer.

**Round-trip property:** `json.loads(forward(x)) == json.loads(reverse(forward(x)))` holds for the current live fixture and for any v0 fixture whose timestamps are at second precision and whose `verification` entries pass the new allowlist. For fixtures that fail the second precondition (verification entries rewritten into `review`), the round-trip is lossy by construction; T0-1 acceptance documents this and excludes those fixtures from the round-trip suite.

### Migrator acceptance tests (T0-1)

1. `--forward` on the current live fixture produces the canonical Output above, and `.harness/backups/phase-state.json.pre-repair.<...>.bak` is byte-identical to the Input (the backup helper uses `O_EXCL` per G1-E and a literal byte-copy, no canonicalization).
2. `--reverse` on the Output produces a file `json.loads`-equal to the Input.
3. `--forward` is idempotent at the `json.loads` level: applying it twice produces results that `json.loads`-equal.
4. The migrator uses the T0-A atomic primitive for ALL writes (the `.bak` AND the target file) AND `O_EXCL` for the backup (G1-E).
5. A `verification` entry not in the new allowlist (e.g., a pre-slice record with `"Validate that the docs look right"` or `"bash scripts/foo.sh"`) is moved to `review` with `{actor: <first-token>, at: <updated_at>, evidence_path: "", summary: <full text>}` and removed from `verification`.
6. The migrator REFUSES to overwrite an existing `.bak` file (`O_EXCL`); exit 1 with the G1-E error template. Recovery via `--resume`.
7. `--resume` happy path: pre-existing `.bak` with sidecar `.resume.json`; current target hash equals `pre_hash`; migrator re-runs cleanly.

---

## Artifact 6 — Breaking Change Ledger

Ready to copy under `CHANGELOG.md` → `## [Unreleased]` → `### Breaking`.

1. **`phase=done` no longer requires a specific `approved` value.** Schema's `done` branch drops the `approved` constant. The CLI does not write `approved` in the `done` phase (G2-C); `harness phase approve` exits 6 in `done`. Migration: `harness migrate state --forward` is idempotent; live state requires no manual edit.
2. **`state_schema_version` field introduced** at top level. Value `2`. Pre-slice records treated as version `0`.
3. **`verification` allowlist tightened to 7 verbs**: `python3`, `git`, `jq`, `npx`, `pytest`, `harness`, `make`. Removed: `Validate`, `Review`, `Inspect`, `Confirm`, `Roo`, `core-only`, `OpenCode-only`, **and `bash`** (D-G4). Migrator relocates removed entries into the new `review` field.
4. **`review` field introduced** (new, ADR-004): `array<object>` of `{actor, at, evidence_path, summary}`. Required at top level; minItems 0.
5. **`allowed_paths` / `blocked_paths` glob grammar fully specified** in ADR-002. Patterns matching the grammar that previously matched zero paths (dead `fnmatch` import) now match. Precedence: `blocked_paths` always overrides `allowed_paths`. Glob-vs-literal collision warning (G3-B) emits at check load.
6. **Direct edits to `.scratch/phase-state.json` emit a high-severity stderr warning** when on-disk hash drifts from the audit log's last `after_sha256`. Warning suppressed when `audit.log` is empty or absent (G1-A).
7. **New CLI verbs**: `harness phase set <phase>`, `harness phase approve` (lifecycle); `harness session unlock` (operational, G1-B). Two lifecycle verbs; zero required flags; ≤3 optional flags per verb plus `--stdin-json` escape hatch.
8. **Session lockfile**: `.harness/session.lock` is created with `O_EXCL` payload `{pid, hostname, started_at_utc, harness_version, boot_id}`, released on clean exit via atexit + signal handlers, recoverable via `harness session unlock`. `harness upgrade` refuses (exit 3) when the lockfile is present with a live PID.
9. **`audit.log` atomic-append protocol**: `fcntl.flock(LOCK_EX)` + ≤512-byte single-line writes via `os.write` (PIPE_BUF-safe on macOS). Overflow recorded in `.harness/audit.overflow/`. Rotation at 10 MiB or 10000 entries; keep last 5.
10. **`state_repair` writes `.bak` before rewriting** `.planning/STATE.md` and `.planning/ROADMAP.md`. Backups are `.harness/backups/<basename>.pre-repair.<ISO-nanos>.<pid>.bak`. Retention capped at 10 most recent per original; auto-pruned. `O_EXCL` on backup write (G1-E).
11. **`state_repair` aborts (exit 5) on unparseable `phase-state.json`** instead of swallowing `JSONDecodeError`.
12. **Migrator crash recovery (G1-E)**: `--forward` and `--reverse` refuse to overwrite existing `.bak`; `harness migrate state --resume` resumes from a sidecar `.resume.json`.
13. **Paused phases (e.g., `02-skill-pack-expansion`) are first-class** in `.planning/STATE.md`'s managed `state-current` block under a `### Paused Phases` subsection.
14. **`approved_at` and `updated_at` precision is nanoseconds.** Format: `YYYY-MM-DDThh:mm:ss.nnnnnnnnnZ`. Migrator pads second-precision values with `.000000000`.
15. **`--at` argument validation:** values not within 24h of `datetime.now(UTC)` are rejected with exit 8.
16. **Exit code split:** 2=invalid-transition, 3=lockfile-active, **4=scope-violation (reservation lifted; assigned to T1-1)**, 5=unparseable-json, 6=wrong-phase-for-verb, 7=stale-detection-uncertain, 8=timestamp-out-of-range. Code 4 was previously reserved for "schema-version refusal"; that signal is deferred to `02c-hardening` and will use a code in the 9..15 range.
17. **Uninstall flags split (G4-C):** `--remove-state` (live JSON), `--remove-operational` (audit/lock/backups), `--remove-install-state` (manifest), `--remove-all`.
18. **`.gitignore` mandatory entries** added by installer: `.harness/audit.log`, `.harness/audit.log.*`, `.harness/audit.overflow/`, `.harness/backups/`, `.harness/session.lock`.
19. **Verification trust boundary (G4-B):** core CLI never executes `verification[*]` strings; smoke runners document developer-trusted-input boundary.
20. **Adapter command files updated (T1-S, row size now M):** `.roo/commands/phase-execute.md`, `.opencode/commands/execute.md`, and 10+ SKILL files replace direct-edit instructions with `harness phase set X && harness phase approve` invocations.

---

## Cross-ADR Consistency Check

Self-audit: each ADR's dependencies on other ADRs are satisfied, in this bundle, by the locked decision indicated.

| ADR | Depends on | Dependency satisfied by |
|---|---|---|
| ADR-001 | T0-A atomic primitive (migrator writes); ADR-003a (state machine); ADR-003b (G2-C `done.approved` ownership) | T0-A is dependency-zero. ADR-003a embeds the state-machine reference. ADR-003b matrix marks `done.approved*` user. |
| ADR-002 | none (orthogonal to live-gate semantics); G3-B warning is loader-local | N/A. |
| ADR-003a | ADR-001 (transition table); ADR-004 (CLI knows verification shape); G1-A/B/C/D/E (operational primitives); G4-C (uninstall flags) | All in-bundle. CLI does not write `verification` or `review` (Artifact 3). Operational primitives detailed inline. |
| ADR-003b | ADR-003a (option 2 keeps direct-edit legal); ADR-001 (G2-C `done.approved` ownership) | Matrix reflects option 2 and G2-C. |
| ADR-004 | ADR-001 (allowlist applies to all phases including `done`); ADR-003a (CLI's `phase approve` does not write verification); G4-A (7-verb floor); G4-B (no execution) | Current live fixture's verification entries all pass the 7-verb allowlist (all `python3 `). Trust boundary documented inline. |
| ADR-005 | T0-A (atomic primitive for `.bak` + canonical rewrite); G1-D (location, retention, filename grammar); G1-E (crash race); ADR-001 (paused phases survive schema versions) | T0-A used for both `.bak` and target. G1-D/E inlined in ADR-005 Decision. Paused-phase representation is Markdown, schema-version orthogonal. |

**Critical artifact dependency**: the CLI contract (Artifact 1) is produced by ADR-003a + ADR-003b; the §10.2 smoke harness's golden file is derived from this artifact, not from running the implementation. Smoke can be authored in T0-3 in parallel with implementation.

**Path-tuple dependency** (G1-C + G4-C): T0-A's grep gate iterates BOTH `STATE_FILE_PATHS` and `OPERATIONAL_PATHS`. Artifact 2 locks both tuples and the writer-allowlist. Uninstall flags split per G4-C.

**Trust-boundary compliance** (G4-B): no ADR in this bundle authorizes the core CLI to execute `verification[*]` strings; smoke runners that do so document the boundary.

**Spec non-goal compliance**: no MCP server, no signing, no Windows support, no LICENSE introduced. No new dependencies (`fnmatch`, `argparse`, `tempfile`, `hashlib`, `fcntl`, `signal`, `atexit` all stdlib).

**Backward-compat compliance**: the current live fixture (`phase=done`, `approved=false`) is migratable via `--forward` and downgradable via `--reverse` with `json.loads` equality (Artifact 5).

**Weak-model fit compliance**: ≤2 lifecycle verbs (ADR-003a); 7-verb verification allowlist (ADR-004); one precedence rule (ADR-002 (a)); one preservation rule (ADR-005); one transition table (ADR-001); ≤3 optional flags per verb (G3-C); canonical `done` example provided (G3-A); glob-vs-literal warning (G3-B). All memorizable by a Haiku-class agent.

**End of bundle.**
