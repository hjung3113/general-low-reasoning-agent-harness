# Changelog

All notable changes to this harness.

본 문서는 `develop` branch 기준 누적. 정식 릴리스 태그는 `main` branch + `vMAJOR.MINOR.PATCH`로 표시.

## Unreleased (develop)

### Breaking

- **L1 — `phase=done` no longer requires a specific `approved` value.** The
  schema's `done` branch drops the `approved` constant (ADR-001 option 3).
  Existing direct readers of `done.approved` MUST treat the field as
  unconstrained. `harness phase approve` exits 6 in `done` (T0-3). Migration:
  `python3 scripts/harness.py migrate state --forward` is idempotent at the
  `json.loads` level; the live `.scratch/phase-state.json` is rewritten to
  the v2 shape in this slice.
- **L2 — `state_schema_version=2` is now REQUIRED at the top level of
  `.scratch/phase-state.json`.** Pre-slice records (no `state_schema_version`
  field) are treated as version `0` and rejected by `scripts/harness.py check`
  with a remediation pointing at
  `python3 scripts/harness.py migrate state --forward`. ADR-001 Decision §
  resolves the spec's "1→2" wording by introducing the field directly at
  value `2`; no v1 wire format is ever written.
- **L3 — `fnmatch` glob activation in `allowed_paths` / `blocked_paths`
  (ADR-002 option 2, grammar G2-E).** `scripts/lib/worktree.py:matches_any`
  now applies `fnmatch.fnmatchcase` semantics per segment in addition to the
  pre-slice literal / trailing-slash-prefix branches. Supported
  metacharacters: `*` (any chars except `/`), `?` (single char except `/`),
  `[abc]` / `[!abc]` (POSIX-style character classes; `!` is the ONLY negation
  marker — `^` is a literal class member). `**` is NOT a recursive-descent
  operator and is treated as `*` (cannot cross `/`). `/` is the separator;
  matching is case-sensitive on every platform. Pre-slice entries that
  contain none of `* ? [ ! ]` continue to match exactly as before (literal
  exact or trailing-slash prefix). Pre-slice entries that DID happen to
  contain glob metacharacters (silent zero-match under the old prefix-only
  rule) now (a) start matching per the new grammar AND (b) emit a one-time
  G3-B loader warning to stderr when a literal file/dir collision exists at
  the unglobbed path. Malformed patterns (e.g., unterminated `[`) now fail
  loudly via `SystemExit` rather than silently zero-matching. No migration
  of existing live state entries is performed; today's literal entries
  round-trip identically.
- **L4 — `blocked_paths` overrides `allowed_paths` (ADR-002 precedence
  (a)).** When a changed path matches BOTH an `allowed_paths` entry AND a
  `blocked_paths` entry, the path is denied. Pre-slice behavior was already
  blocked-first in `scripts/lib/worktree.py:path_allowed`, but the rule is
  now contractually pinned: blocked always wins, including when the blocked
  entry is a glob and the allowed entry is a literal (or vice versa).
- **L12 — Migrator `--resume` verb (crash recovery, ADR G1-E).**
  `scripts/migrate_state.py` ships with `--forward`, `--reverse`, and
  `--resume` sub-verbs. `--forward` and `--reverse` refuse to overwrite an
  existing `.bak` (`O_EXCL`); `--resume` reads the sidecar
  `.harness/backups/<basename>.pre-repair.<...>.bak.resume.json` and either
  re-runs the partial migration or declares it complete by hash.
- **L5 — Verification 7-verb allowlist (ADR-004 / G4-A).** The
  `.scratch/phase-state.json` `verification` array now accepts ONLY entries
  beginning with one of seven verb prefixes: `python3 `, `git `, `jq `,
  `npx `, `pytest `, `harness `, `make `. The previous soft-prefixes
  (`Confirm `, `Review `, `Inspect `, `Validate `, bare `Roo`,
  `core-only `, `OpenCode-only `) AND `bash ` (D-G4) are no longer accepted.
  A new top-level `review: array<object>` field carries human-evidence
  entries (`{actor, at, evidence_path, summary}`); pre-slice soft-prefix
  entries are relocated by the migrator. Migration:
  `scripts/lib/state_migrate_t04.py` relocates non-conforming entries to
  `review` losslessly; existing `python3 ` entries are preserved.
- **L19 — Verification execution trust boundary (ADR-004 / G4-B).**
  `harness check` (and any other core CLI verb) NEVER executes a
  `verification[*]` string — the field is a developer-trusted manifest of
  commands to be run BY the developer / smoke runner, not by the harness.
  `scripts/release_smoke_test.py` carries a header docstring documenting
  that it is the sole in-tree consumer that intentionally crosses this
  boundary. A regression test mocks `subprocess.*` and `os.system` and
  asserts none are invoked by any code path reachable from
  `scripts.harness.main(["check"])`.
- **L6 — Drift-warning template (high-severity stderr) (T0-3).**
  `harness check` now compares the live `.scratch/phase-state.json`
  sha256 against the last audit entry's `after_sha256` in
  `.harness/audit.log`. When they diverge, a high-severity warning is
  emitted to stderr explaining drift and pointing at the canonical
  remediation (`harness phase set <current_phase>` or
  `harness phase approve`). The warning never fails the check.
  First-write / empty-log cases are suppressed. The template MUST NOT
  reference any future verbs.
- **L7 — Phase transition CLI verbs `set` and `approve` (T0-3).**
  `harness phase set <phase>` and `harness phase approve` land per
  ADR-003a Artifact 1. Each verb writes `.scratch/phase-state.json`
  through `atomic_write_text`, validates against the ADR-001 transition
  table, and appends a JSON-line audit entry. Exit codes
  `0/1/2/3/5/6/8` are reachable per Artifact 1.
- **L8 — Session lockfile (O_EXCL + atexit/signal release) (T0-3).**
  `.harness/session.lock` is created with `O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC`
  + `flock(LOCK_EX|LOCK_NB)`. Lifecycle: lockfile is released on clean
  Python exit (`atexit`) and on SIGINT/SIGTERM. Operational verb
  `harness session unlock` recovers stale lockfiles via
  `os.kill(pid, 0)` + Linux `boot_id` comparison, refusing live PIDs
  unless `--force`. Payload is JSON
  `{pid, hostname, started_at_utc, harness_version, boot_id}`.
- **L9 — Audit log path + atomic-append + rotation (T0-3).**
  `.harness/audit.log` carries one JSON-line entry per lifecycle write.
  Lines are ≤512 bytes (PIPE_BUF-safe); oversize `args` payloads are
  truncated to `{"truncated": true}` with the full record archived
  under `.harness/audit.overflow/<index>.json`. Rotation triggers at
  10 MiB or 10 000 entries (whichever first), keeping
  `audit.log.1..audit.log.5`.
- **L14 — Nanosecond-precision timestamps (T0-3).**
  `approved_at`, `updated_at`, and audit-entry `at` fields are written
  in ISO-8601 with full nanosecond precision
  (`YYYY-MM-DDTHH:MM:SS.nnnnnnnnnZ`). Helper lives in
  `scripts/lib/timestamps.py`.
- **L15 — `--at` 24h-window validation (T0-3).**
  `harness phase approve --at <ts>` refuses values whose absolute delta
  from current UTC exceeds 86 400 seconds. Exit code `8`
  (`EXIT_TIMESTAMP_OUT_OF_RANGE`).
- **L17 — Uninstall flag split (T0-3).**
  `scripts/uninstall_harness.py` gains
  `--remove-state` / `--remove-operational` / `--remove-install-state` /
  `--remove-all` flags that consume the `STATE_FILE_PATHS`,
  `OPERATIONAL_PATHS`, and `INSTALL_PATHS` tuples from
  `scripts/lib/operational_paths.py`. `--remove-all` is the union of
  the other three.
- **L11 — Unparseable JSON aborts (was: silent swallow) (T1-M).**
  `scripts/lib/state_diagnostics.py` introduces `load_state_json(path)` as
  the sole sanctioned reader for managed harness state (`.scratch/phase-state.json`,
  `.harness/installed-manifest.json`). Malformed input now raises
  `SystemExit(EXIT_UNPARSEABLE_JSON)` (exit code 5) with a single-line
  `error:` diagnostic naming the file, line:column from
  `JSONDecodeError`, and a remediation hint that surfaces
  `harness migrate state --resume` (when a sidecar at
  `.harness/backups/<basename>.pre-repair.*.bak.resume.json` exists) or the
  newest `.harness/backups/<basename>.pre-repair.*.bak` filename when only
  backups are present. Per ADR-005 / ADR-003a Artifact 1. Companion helper
  `parse_state_markdown(path)` wraps `managed_block.parse_blocks` and
  `roadmap_state.parse_frontmatter` so duplicate managed-block slugs,
  unbalanced markers, invalid slugs, and unclosed frontmatter delimiters
  abort with the same exit code instead of surfacing tracebacks or
  silently returning partial data. Pre-slice behavior at
  `check.check_phase_state_paths`, `worktree.check_changed_paths`,
  `worktree.check_worktree_paths`, `state.read_install_state`,
  `roadmap_state.roadmap_state_sync_applicable`,
  `roadmap_state.find_roadmap_state_sync_findings`, and
  `state_repair.repair` was an uncaught `JSONDecodeError` traceback (or, in
  `state_repair`, a silent swallow that proceeded with an empty dict); all
  now route through `load_state_json` and exit 5 with structured
  diagnostics. The `state_repair.py:197` swallow→raise rewrite proper is
  owned by T0-5 per CONTRACT-PIN §5.1; T1-M only replaces the bare
  `json.loads` call with `load_state_json` so the helper's exit propagates.
- **L16 — Exit code 4 = `SCOPE_VIOLATION` (reservation lifted) (T1-1).**
  ADR-003a originally reserved exit code 4 for "schema-version refusal."
  That reservation is LIFTED by the ADR amendment commit
  `docs(adr): assign exit code 4 to SCOPE_VIOLATION` and assigned to T1-1.
  `scripts/lib/worktree.py:check_changed_paths` and
  `check_worktree_paths` now `raise SystemExit(EXIT_SCOPE_VIOLATION)`
  (imported from `scripts/lib/exitcodes.py`) on scope violation; pre-slice
  behavior surfaced as exit 1 via a bare `SystemExit("…")`. A pre-commit
  hook installable via `harness install --pre-commit` (uninstallable via
  `harness uninstall --pre-commit`) invokes
  `python3 scripts/harness.py check --worktree` from the repo root and
  blocks commits that touch files outside `allowed_paths`. The failure
  message names every violating file and cites
  `docs/protocol-spec.md#scope-enforcement`. Schema-version refusal will
  use a code in the 9..15 range when implemented in `02c-hardening`.
- **L18 (T0-3 rows) — `.gitignore` audit + lockfile entries (T0-3).**
  The skeleton `.gitignore` (already excluding `.harness/`) is
  documented to cover `.harness/audit.log`, `.harness/audit.log.*`,
  `.harness/audit.overflow/`, and `.harness/session.lock`. The
  `.harness/backups/` row is owned by T0-5.
- **L20 — SKILL surface CLI alignment (T1-S).** Adapter command files
  (`.roo/commands/phase-*.md`, `.roo/commands/done.md`,
  `.opencode/commands/{discuss,plan,execute,done}.md`) and the 10
  `.roo/skills/workflow-*/SKILL.md` files now instruct the agent to
  advance the lifecycle via `python3 scripts/harness.py phase set <X>`
  and `python3 scripts/harness.py phase approve` (ADR-003a Verbs 1+2)
  instead of direct-editing `.scratch/phase-state.json`.
  `.roo/commands/done.md` is added per CONTRACT-PIN §5.2 (adapter
  parity gap closed). The G3-A canonical `phase=done` few-shot is
  anchored in `.roo/skills/workflow-phase-gate/SKILL.md`; other
  SKILLs reference it by path rather than duplicating the JSON.
  No code or schema changes; surface-touch only.

Note: this slice preserves the `## Unreleased (develop)` heading verbatim;
normalization to `## [Unreleased]` (Keep-a-Changelog) is deferred to T3.

### Added

- `python3 scripts/harness.py state show` — phase-state projection 출력 (text 또는 `--format json`).
- `python3 scripts/harness.py state repair` — `.planning/ROADMAP.md` / `.planning/STATE.md`의 machine-owned 영역을 canonical로 재렌더. Idempotent.
- HTML-comment managed marker block:
  ```
  <!-- HARNESS:BEGIN managed:<slug> v1 -->
  ...machine-owned content...
  <!-- HARNESS:END managed:<slug> -->
  ```
  - ROADMAP `## Phases` 체크리스트 → `managed:roadmap-phases` block
  - STATE `## Current Position` + `## Active Checkpoint` → `managed:state-current` block
- `scripts/lib/managed_block.py`, `scripts/lib/state_repair.py`, `scripts/lib/state_cli.py` — 신규 모듈. `harness/manifest.json`에 등록되어 target install에도 전파.
- `harness.py check`가 managed block 누락 시 warning (실패 아님) 출력. 메시지에 정확한 fix 명령 포함.
- `AGENTS.md` skeleton에 managed-block 가이드 + repair 한계 (in-block edit 후 자동 복원 불가, git revert 사용) 명시.

### Why

저추론 에이전트(Haiku 수준)가 strict regex 파서를 침묵으로 깨뜨리는 문제 해결. CLI verb 폭증 없이 parser drift만 막는 MVP. `phase-add` / `phase-done` / `transition` 같은 verb는 의도적 미포함 — agent 인지부하 최소화 위함.

### Fixed

- Orphan phase line (managed block 밖에 phase 줄 추가) 시 `repair`가 silently 흡수해 중복 생산하던 bug. 이제 block 밖 phase 줄 발견하면 `RepairReport.warnings`로 보고하고 흡수하지 않음.

## v0.6.1

### Profile 통합 + profile별 augment rules

Installer preset과 manifest profile이 단일 개념으로 합쳐졌습니다. Installer는 profile 하나를 받고, `generic`이 아닐 때만 database 축을 묻습니다.

- Profile 4종: `generic`, `dotnet-etl`, `python-etl`, `react-web`.
- `--db {mssql|postgresql|none}`이 대응하는 `tech-*`와 `workflow-db-context` pack을 자동 추가.
- `react-web` profile은 Roo adapter 설치 시 `ui-engineer` 모드를 추가합니다(브라우저 우선 UI 작업용).
- Profile-scoped augment rule은 `.roo/rules-<mode>/`(Roo)와 `.opencode/profile-rules/`(OpenCode)에 선택한 adapter 기준으로만 설치됩니다.

폐기:

- Installer preset `full`.
- Manifest profile `dotnet-etl-mssql` (legacy 설치는 `upgrade` 시 `dotnet-etl` + `tech-mssql` + `workflow-db-context`로 자동 마이그레이션).

OpenCode core 명령(`discuss`, `plan`, `execute`, `done`)은 시작 시 `.opencode/profile-rules/` 아래 모든 파일을 알파벳 순으로 읽습니다.

### `scripts/harness.py` 리팩토링

`scripts/harness.py`가 2561 lines → ~500 lines로 줄었습니다. 모든 비-CLI 로직은 `scripts/lib/`로 분할:

- `lib/version.py`, `lib/profiles.py`, `lib/manifest.py`, `lib/append_block.py`
- `lib/state.py`, `lib/roadmap_state.py`, `lib/worktree.py`
- `lib/adoption.py`, `lib/check.py`, `lib/doctor.py`
- `lib/install.py`, `lib/upgrade.py`

Public surface 보존: 이전에 `scripts.harness.X`로 import 가능했던 모든 심볼은 그대로 유지됩니다. `harness.py`의 `__all__` 블록이 계약을 명시합니다.

### 진단 강화

- `harness.py check`: `.roomodes`가 owning profile이 설치되지 않은 profile-contributed mode를 포함하면 실패합니다.
- `harness.py doctor`: OpenCode command 파일에서 `.opencode/profile-rules/` 읽기 지시가 빠지면 경고합니다.

### Upgrade 마이그레이션

이전 버전에서 `profile=dotnet-etl-mssql`로 설치된 target은 `upgrade` 실행 시 자동 마이그레이션됩니다. `--dry-run`과 실제 실행 모두 마이그레이션 결과를 다음과 같이 출력합니다:

```
MIGRATION:
  profiles: ['dotnet-etl-mssql'] -> ['dotnet-etl']
  packs added: tech-mssql, workflow-db-context
```
