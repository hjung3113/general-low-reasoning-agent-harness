# Changelog

All notable changes to this harness.

본 문서는 `develop` branch 기준 누적. 정식 릴리스 태그는 `main` branch + `vMAJOR.MINOR.PATCH`로 표시.

## Unreleased (develop)

### Breaking
- Prior ledger entries: `phase=done` contract (state machine terminal guard),
  `state_schema_version` bump from v0.8 → v0.9, and `migrate state --resume`
  verb are recorded in the **v0.9.0** section below.

_No further unreleased breaking changes._

## v0.9.8 (2026-05-22) — upgrade UX hotfix

Driven by Windows/PowerShell smoke: v0.9.7 upgrade looked like a hang on
small upgrades because stdout was empty after `finalizing...` and the
staging-files progress line never crossed its quartile throttle. Plus
`git verify-tag` had no timeout so a stalled ssh-keygen could freeze
the upgrade indefinitely.

### UX
- `harness upgrade` now prints a final stdout summary on success:
  `upgraded harness → vX.Y.Z at <target> (N writes, R removals, C conflicts).
  Next: cd <target> && python3 scripts/harness.py check`. Empty stdout
  was being read as "hang" on Windows.
- Pass A staging surfaces an explicit terminal note —
  `staging files... staged N file(s)` (or `... no harness-owned files
  needed restaging`) — so small upgrades that short-circuit on
  source_sha256 match still show progress.

### Hardening
- `lib/release_trust._run`: 15 s default timeout. `git verify-tag` spawns
  `ssh-keygen -Y verify`, which on Windows can hang on a stalled ssh-agent
  or allowed-signers parse. Timeout converts the hang into a deterministic
  non-zero CompletedProcess so callers raise UpgradeTrustError with a
  readable `[timeout after 15.0s]` instead of freezing.

### Notes
- v0.9.7 → v0.9.8 is a wire-level no-op upgrade (only UX + timeout).
  Trust-downgrade refusal (signed → dev) still applies; for dev source
  HEAD set `HARNESS_VERSION` to a release version or run from a clean tag.

## v0.9.7 (2026-05-21)

### Hardening
- harness init/upgrade harness-owned file replacement now uses resumable per-file
  atomic staging with a pending-manifest sidecar, completion sentinel, and runid
  collision-resistant naming (`scripts/lib/atomic_io.py` + `install_recovery.py`).
  Crashes mid-install (SIGTERM, power loss, manual abort) are recoverable via
  `harness state repair`. Managed-append and composed write_text_file updates
  remain in-place and are deferred to a later release.
- Skip-upgrade guard refuses v0.9.4 → v0.9.7 with an actionable bilingual message
  (override: `HARNESS_ALLOW_SKIP_UPGRADE=1`).
- `harness state repair` exit codes: 0 (clean / no-op), 1 (quarantined partial),
  2 (catastrophic).
- `harness check` now warns when a stale aborted-install staging directory is
  detected (age ≥ 600s OR `.aborted` marker).
- Test fixture: v0.9.4 tarball includes deterministic `.harness/` state; upgrade
  tests now exercise real upgrade paths (synthetic seeders removed).
- `tests/KNOWN_FAILING_TESTS.md` enumerates pre-existing failing node-ids; CI
  gate via `tests/test_known_failures_drift.py`. Baseline seeded under Python 3.9.6
  (system); failing set may differ under Python 3.14+ (reseed with
  `scripts/refresh_known_failures.sh` in the target env).

### UX
- `harness init` / `harness upgrade` emit phase-by-phase progress lines on
  stderr (`staging files... [N/M]`, `applying atomic batch... [N/M]`,
  `writing pending sidecar...`, `syncing roomodes...`, `finalizing...`). Disable
  with `--quiet`. stdout summary is unchanged.
- Bilingual install/upgrade failure messages reformatted: separate Korean and
  English blocks with the `state repair` recovery command on its own copy-pasteable line.
- `harness check` collapses multiple stale-staging warnings into a single
  `{N}개 중단된 설치 감지 (oldest runid=…)` summary when N >= 2.

### Refactor
- `lib/install._atomic_write_json_fsync` unified onto `lib/atomic_io.atomic_write_text`
  (single canonical fsync + dir-fsync + Windows retry-replace path).

### Docs
- USER_MANUAL: new "중단된 설치 복구" subsection with success/failure example output.
- USER_MANUAL: new "v0.9.4 → v0.9.7 업그레이드 시 주의사항 (격리 경고)" section
  documenting `.harness/conflicts/` leftovers from the v0.9.4 manifest-gap bug.

### Deferred to v0.9.8
- Managed-append + `write_text_file` content-mutating atomic staging
- Pre-existing test failure triage (76 tests)
- BUG-4 release-check rc=0
- Symlink-aware staging; Windows support

## v0.9.6 — 2026-05-21

### Documentation hotfix

Pure-docs release. No code changes. Brings the user-facing docs surface back
in sync with the actual shipped behavior post-v0.9.5.

- **USER_MANUAL.md**: bump version header to v0.9.6; preserve What's new in
  v0.9.5 section as historical context.
- **README.md**: bump installation/upgrade examples and `release-check`
  expected-version to v0.9.6.
- **docs/site/*.html**: regenerate `index.html`, `manual.html`,
  `advanced.html`, `use-cases.html` against the new version header.
- **docs/use-cases/README.md**: bump intro version reference.

### Deferred to next release

Substantive work for the v0.9.5 known limitations (T14a `atomic_install_batch`
wire-in into `install.py` / `upgrade.py`, fixture `.harness/` inclusion in
`build_v094_fixture.py`, KNOWN_FAILING_TESTS.md) was scoped under
`.planning/phases/02f-v0.9.6-hotfix/` (DRAFT plan + 3-panel Opus review) but
DEFERRED. v0.9.6 ships docs only; the deferred items roll forward to the next
session's work.

## v0.9.5 — 2026-05-21

### Fixed (P0 / P1 hotfixes from v0.9.4 install-broken report)

- **Manifest gap (T3 + T14b)**: 35 missing `scripts/lib/*.py` modules added to
  `harness/manifest.json`; fresh `harness init` now ships all required files.
  `scripts/lib/install_recovery.py` (added in T14b) also registered.
- **Import-smoke broadened (T8a)**: `check.py _collect_lib_imports_from_file`
  now also catches `from lib import X` forms (previously skipped), preventing
  this manifest-gap class from recurring silently.
- **Install-record bootstrap (T7)**: fresh `harness init` now writes
  `.harness/installed-manifest.json` immediately; `approve` / `verify` no
  longer fail with "install-record not found" on the very first run.
- **Wrong-tree root resolution (T9)**: `state_cli.resolve_root` walks up from
  CWD to the nearest `.git` / `.harness` ancestor; fixes 5× `__file__.parents`
  wrong-tree crashes.
- **Error code map (T10)**: unified exit-code table; harness now exits non-zero
  on all errors (fixes CI-bypass via `rc=0` on errors, NEW-3).
- **Dry-run quarantine false-positive (T6 / STALE-2)**: upgrade `--dry-run`
  no longer quarantines workaround files whose sha256 matches the v0.9.5
  source.
- **Done→done idempotent noop (T13)**: `harness phase set done` when already
  done returns `rc=0`; divergent done-state returns `EXIT_OPERATIONAL`.
- **Reopen smoke bypass (T12)**: dual-env gate
  (`HARNESS_SMOKE_TEST=1 + HARNESS_SMOKE_BYPASS_SPEED_BUMP=1`) allows CI smoke
  to reopen phases; bypass recorded as `proof_class=smoke_bypass`.
- **Audit-verify tail check (f7d1081)**: `audit_verify_cli` now compares
  `final_after_sha256` (correct field) instead of `final_tip_hash` against
  `phase-state.json` sha256.
- **Chain re-anchor audit (T16)**: upgrade re-hashes `installed_files_chain_hash`
  after manifest expansion and writes a `release.trust.rechained` audit row.
- **Daily-four UX (BLOCK-2)**: `harness next` in normal mode now emits
  `harness run` instead of `harness phase set plan`; the daily-four workflow
  (`init → next → run → check`) no longer requires explicit `phase set`.
- **Release smoke cases (FIX-5)**: fsd-status-roo/opencode now parse
  env-prefixed backtick spans; oidc-jti-replay marker check uses correct
  sha256-based filename.  All 18 smoke cases pass.

### Added
- **`scripts/lib/install_recovery.py`** (T14b): state-repair module detects
  and cleans up orphaned `.staging-<pid>/` directories left by interrupted
  installs; delegated from `harness state repair`.
- **`scripts/lib/atomic_io.py`** (T14a helper): `atomic_install_batch`
  stage-then-rename helper landed.  Wire-in to `install.py` / `upgrade.py`
  write paths deferred to v0.9.6 (see below).
- **T15 upgrade-compat tests**: `tests/test_smoke_lifecycle.py`,
  `tests/test_upgrade_from_v094_clean.py`,
  `tests/test_upgrade_from_v094_with_workaround.py` (5 + 5 + 7 tests).

### Known limitations / deferred to v0.9.6
- **`atomic_install_batch` not wired**: the `atomic_io.py` helper is
  implemented and tested but `install.py` / `upgrade.py` still write files
  in-place.  An interrupted upgrade leaves a partial install; `state repair`
  will detect orphaned staging dirs once the wire-in lands.
- **Fixture `.harness/` not captured**: `tests/fixtures/v094-*.tar.gz` do not
  include `.harness/installed-manifest.json` / `audit.log`; upgrade tests
  synthesise the v0.9.4 state rather than replaying a real capture.
- **Dev-unsigned (`HARNESS_ALLOW_UNSIGNED_DEV=1`) upgrades do not rechain**:
  the T16 `record_rechain` path is only exercised by signed-tag installs.
  This is a dev-mode limitation; real signed-tag installs rechain correctly.

## v0.9.4 — 2026-05-20

### Added
- **Planning-parser unification.** Single `scripts/lib/planning_grammar.py` module owns all planning-doc parsing (frontmatter, STATE phase/checkpoint, ROADMAP bullet, phase-folder, heading matcher, schema-version). Both `scripts/lib/planning_status.py` and `scripts/lib/project_dashboard/core.py` consume the shared grammar; the legacy duplicate parsers were collapsed.
- **`planning_doc_schema_version: 1`** frontmatter field on `.planning/STATE.md`. Distinct namespace from `.scratch/phase-state.json`'s `state_schema_version` (the latter unchanged at 2; see ADR-001).
- **Letter-suffix phase IDs** (`02b`, `1c`, etc.) are now first-class across ROADMAP bullets, STATE phase line, STATE checkpoint line, phase-folder names, and the planning_status / roadmap_state / dashboard parsers.
- **`DashboardWarning(code, severity, message, paths)`** structured warning type replaces free-text strings throughout the dashboard. JSON output of `scripts/show_phase_status.py` and dashboard `--check` both carry stable codes.
- **`EXIT_PLANNING_DRIFT = 12`** in `scripts/lib/exitcodes.py`. New `python3 scripts/project_dashboard.py --check` exits with this code on blocking drift; `harness check` consumes it too.
- **Nested `plans/*-PLAN.md`** inventoried by the dashboard for phases that organise plan files under a `plans/` subdir (matches 02b-hardening layout).
- **`docs/planning-grammar.md`** documents the dialect formally with positive + negative examples.

### Fixed
- Malformed `.scratch/phase-state.json` now emits a single `phase_state_malformed_json` blocking warning instead of silently cascading missing-path-ref + checkpoint-drift warnings.
- ROADMAP bullets without trailing `- summary` are no longer silently merged (regex newline-consumption bug in `ROADMAP_BULLET_RE`).
- `roadmap_state.parse_roadmap_phases` and `roadmap_state.parse_state_snapshot` accept letter-suffix phase numbers consistently with the dashboard parser.
- Phase folders that don't match the `NN[a-z]?-slug` grammar emit a `phase_folder_grammar_invalid` blocking warning instead of silent skip.

### Deferred (tracked separately)
- ROADMAP/STATE.md reconciliation for v0.9.x shipped phases. The new `phase_folder_not_in_roadmap` warning flags `02b-hardening` as actionable rather than silencing it; the planning-doc content edit is its own plan.

## v0.9.3 — 2026-05-20

### Removed
- **Audit-tip anchor (BREAKING)**: The out-of-repo audit-tip anchor (`~/.harness/audit-tip/<id>.json`) and the `harness anchor` subcommand have been removed. Internal-only threat model retires the repo-local attacker class the anchor defended against.

### Fixed
- Fresh-install regression: `harness next` no longer errors with "audit-tip anchor not found" on first use.
- Operational integrity: `state_trust.preflight` now refuses to trust state when audit log is empty/missing but state file has been advanced past the install baseline (sub_reason: `state_advanced_without_audit_evidence`).
- Torn-write detection: TXN-verb audit entries missing `after_sha256` now raise (`txn_entry_missing_after_sha256`) instead of being silently walked past.

### Compatibility
- Existing v0.9.x installs upgrade in place. Vestigial `~/.harness/audit-tip/<id>.json` files are ignored (left intact; user may delete manually).
- New smoke case `upgrade-from-v091-with-vestigial-anchor` covers this path.

### Note
Internal tool. Repo-local attacker (audit log forgery/replay) is intentionally out of threat model.

## v0.9.2 — 2026-05-20 (installed dashboard)

### Added
- Installed target repositories now include an interactive local dashboard via
  `python3 scripts/project_dashboard.py --serve`.
- Dashboard pages:
  - `/overview` for project overview, milestones, checkpoint, and next action.
  - `/progress` for phase-gate details, acceptance criteria, verification,
    allowed paths, and phase documents.
  - `/actions` for allowlisted local CLI buttons (`check`, `next`, `run`,
    `doctor`, and static snapshot generation).
- Dashboard server stays localhost-only, token-protected, and delegates actions
  to existing `scripts/harness.py` commands instead of reimplementing workflow
  semantics.

### Docs
- README, target skeleton README, and USER_MANUAL document the installed
  dashboard launch command and safety model.

## v0.9.1 — 2026-05-20 (docs hotfix)

### Fixed
- Restore correct location for HTML site files:
  - Presentation deck (~80KB) moved to `docs/site/presentation.html`.
  - Landing page (~5KB) restored at `docs/site/index.html`.
  - `docs/index.html` removed (was a mis-named copy of the deck in v0.9.0).
- README and USER_MANUAL install/upgrade examples bumped to `v0.9.1`.

No code or test changes.

## v0.9.0 — 2026-05-19 (phase.approve speed bump)

### Breaking
- `harness phase approve` no longer consumes an HMAC nonce. Replaced with interactive `[y/N]` prompt on a TTY.
- Non-TTY callers now exit `EXIT_HUMAN_CONFIRMATION_REQUIRED=17` with `sub_reason=non_tty_approval_blocked` (previously exit 6 with varied sub_reasons like `human_proof_missing`, `human_proof_nonce_expired`).
- `harness approve-nonce mint --audience phase.approve` is now a deprecation no-op that emits a stderr warning and exits 0 without writing a nonce. Removal scheduled for v1.0. Other audiences (release.*) unchanged.
- `phase approve` while in `done` phase refused with `EXIT_WRONG_PHASE_FOR_VERB=6` + `sub_reason=approve_in_done`.

### Changed
- Audit row for phase.approve now records `proof_class=soft_tty`, `tty`, `response`. Chain stamping (schema_version, seq, previous_entry_hash, entry_hash) preserved unchanged via `audit_append`.
- `confirmation_kind` field value `human_nonce` → `soft_tty` for phase.approve rows.
- `_do_phase_approve` legacy shim retired; `run_approve` is the direct dispatch.

### Added
- New ADR `docs/adr/2026-05-19-phase-approve-speed-bump.md` records the threat-model downgrade scoped to phase.approve.
- USER_MANUAL §0.1 (Speed-bump vs autopilot boundary), §0.2 (Glossary).
- README "용어 / Glossary" section.
- `docs/advanced/harness-flags.md` lists all `HARNESS_*` flags; USER_MANUAL no longer carries the env-var table.
- New exit code symbol `EXIT_HUMAN_CONFIRMATION_REQUIRED=17` (numeric value already reserved by protocol-spec §3.4 "human action required" slot).
- New test-only parameter `skip_state_trust_preflight` on `run_approve` (decoupled from `skip_anchor_preflight`).

### Docs
- USER_MANUAL §A4 renamed "Approve-Nonce" → "Release Confirmation".
- USER_MANUAL §B1.1/B1.2 (approve-nonce troubleshooting) removed. New §B1.4 "phase approve requires a terminal".
- USER_MANUAL §C2.2 FAQ rewritten: `phase approve` alone is sufficient.
- Adapter prompt templates updated: `[y/N]` prompts must not be answered by adapter agents.

### Out of scope (intentionally unchanged)
- `harness release`, signed tags, OIDC, release_trust, `.github/workflows/release.yml`, `docs/trust/`.

See ADR 2026-05-19-phase-approve-speed-bump for rationale.

## v0.8.3 — 2026-05-19 (hotfix — signed tag + manual restructure + error message)

### Trust

- **Signed release tag 복구**: v0.8.0/8.1/8.2가 unsigned tag로 발행되어 install/upgrade가 `tag_signature_invalid`로 거부되는 문제 수정. v0.8.3은 SSH ed25519로 properly signed. `docs/trust/allowed-signers`에 maintainer pubkey 등록 (release@harness hjung3113@gmail.com).
- v0.8.0~v0.8.2 unsigned tag는 history 보존을 위해 그대로 둡니다. 해당 버전을 install/upgrade할 때만 `HARNESS_ALLOW_UNSIGNED_DEV=1` 필요.

### Fixed

- `harness status/next` anchor-missing 에러 메시지 수정 (3-persona 적대적 리뷰 적용):
  - 잘못된 경로(`.harness/audit.tip-anchor.json` in-repo) → 정확한 경로 (`~/.harness/audit-tip/<repo-id>.json` out-of-repo)
  - 잘못된 fix 명령(`harness init`) → `harness anchor repair`
  - `({exc})` 보간으로 peer callsites(`halt_diary_cli.py`, `phase_autopilot_cli.py`)와 일치

### Docs

- `docs/USER_MANUAL.md` 재구조 (1288 → 1339 lines, 콘텐츠 0 손실):
  - **Part 1 (§1–§7)**: 일상 사용자가 읽어야 할 전부 — 개요, 첫 세션, 워크플로, Planning State, Skill Packs, 프롬프트 레시피, 제거.
  - **Part 2 (§8–§9)**: Adapter 작성자.
  - **부록 A**: Maintainer/Security — 보안 모델, Release Trust, 감사 로그, Approve-Nonce.
  - **부록 B**: Troubleshooting + Advanced CLI (`HARNESS_ADVANCED=1`) + Exit Codes.
  - **부록 C**: CI/자동화 — 환경 변수, Autopilot, 업그레이드, Windows.
  - **부록 D**: v0.9.0 Carryover, 참고 자료.
  - TL;DR 안내 블록 추가 (어디서 읽을지).
  - §B2 CLI 레퍼런스에 `HARNESS_ADVANCED=1` 경고 banner.
- `README.md` USER_MANUAL anchor 수정 (§16/§17 → §C3/§7).
- 모든 v0.8.2 → v0.8.3 release token 갱신.

## v0.8.2 — 2026-05-19 (workflow UX hardening)

- Added compact `next_steps` guidance to `show_phase_status.py` JSON so low-reasoning agents can read trust, next read, edit permission, and verification obligations without inferring them from the full projection.
- Updated adapter status and phase-run prompts to use the current `HARNESS_MACHINE=1 harness next` contract fields: `may_edit`, `requires_user_approval`, `next_command`, and `next_user_prompt`.
- Clarified approval-boundary docs: humans approve after `harness run` surfaces the prompt; adapters must never self-approve.
- Updated README/manual release examples from v0.8.1 to v0.8.2.

## v0.8.1 — 2026-05-19 (한글 유즈케이스 문서 hotfix)

- `docs/use-cases/` 아래에 한글 유즈케이스 문서를 추가했습니다:
  첫 설치, 매일 쓰는 기본 흐름, Roo/OpenCode 어댑터 흐름, 승인 후 구현, 문제 해결.
- v0.8 UML 워크플로 문서 2개를 한글로 바꿨습니다:
  `docs/minimal-workflow-sequence.md` and `docs/minimal-workflow-state-machine.md`.
- README와 사용자 설명서에 유즈케이스 문서 링크를 추가했습니다.

## v0.8.0 — 2026-05-19 (minimal workflow)

- Reduced the normal user CLI surface to `harness`, `harness next`, `harness run`, and `harness check`.
- Added `HARNESS_MACHINE=1` JSON output for adapter-facing `next`, `run`, and `check`.
- Changed normal `harness next` output to avoid low-level phase/approval commands.
- Added `harness run` as the safe workflow stepper; it can enter planning but stops for human approval before implementation.
- Updated README, user manual, Roo/OpenCode prompts, and added UML workflow diagrams.

## v0.7.2 — 2026-05-19 (UX sweep)

부작용 0 UX 개선 9 group. JSON output shape, schema, exit code, security
boundary, install semantics 불변. 9 commit, 매 group 별도 Opus 적대적 리뷰
수행 후 진행.

### UX improvements (per group)

- **A — phantom verb / internal-name sweep** — Fix-line이 추천하던 미등록
  verb `harness phase status` → `harness status` 통일. 내부 슬라이스 명칭
  `(lands Sxx)` 메시지에서 제거. `...` 리터럴 placeholder → `<phase>`.
- **B — `check.py` Fix-line 보강 (21곳)** — 모든 missing-field /
  install-drift / scope-gate 거부 메시지에 actionable Fix 안내 추가. 모든
  추천 verb는 argparse 실재 등록분만 (`phase set --stdin-json`,
  `--reset-approval`, `upgrade --target` 등). v0.7.1 P0 재발 차단을 위해
  적대적 리뷰가 5개 미존재 flag (`--updated-at` 등) 사전 차단.
  `worktree.py` scope-violation 블록 dedup — 중복된 `Remediation:` +
  trailing `Fix:` 라인 단일 `Fix (pick one):`로 통합.
- **C — reopen reason placeholder** — Fleet-wide 캔드 reason
  `"fix and re-approve"` → `<describe why you are reopening>`. 단일 상수
  `REOPEN_REASON_PLACEHOLDER`를 `transition.py`에 정의, `status_next.py`가
  import. 4 사이트 모두 적용 (transition.py:172/346, status_next.py:180/321).
- **D — install 첫 경험** — `init` 성공 시 출력 0줄이던 것을 1줄 추가
  ("installed harness vX.Y.Z → <target> (N planned writes). Next: ..."),
  "Refusing to overwrite" 메시지 멀티라인 정리 + 안내. profile prompt에
  `(generic is recommended for first install)` 힌트. 적대적 리뷰가
  `--adopt-existing` 추천 (2차 SystemExit 유발 위험) 사전 차단.
- **E — docs** — README §4 tree `ADR/` → `adr/` (실제 디렉터리 케이스),
  README §2에 표기 컨벤션 박스 추가, USER_MANUAL §913 dead anchor
  `§3.5.2` → `§7.2`, USER_MANUAL §19.11 "자주 혼동하는 케이스" 7 Q&A 신설.
  적대적 리뷰가 잘못된 verb 추천 (`upgrade --add-packs` 미존재 → `--packs`
  + replace semantics 명시; `state repair --to <phase>` 미존재 →
  `phase reopen --to plan`) 사전 catch.
- **F — adapter prompt** — `.roo/commands/`, `.opencode/commands/` 6
  파일에서 "when available" 모호 표현을 exit-code 기반 결정적 wording으로
  교체. Roo phase-discuss/phase-plan에 OpenCode와 동일한 preflight
  checklist 추가 (verbatim). done.md 양쪽 `check --worktree` ordering
  명확화 (phase=execute 단계에서 실행). fsd-run-phase.md 양쪽에
  `requires_human` 가드 추가 (fsd-run-all과 symmetric). `.roo/commands/README.md`
  table에 `/fsd-run-all` / `/fsd-status` 행 추가. fsd-status.md는
  byte-exact pin test 있어 v0.8.0로 이전.
- **G — argparse "did you mean"** — typo 시 `difflib.get_close_matches`로
  근접 verb 1-2개 stderr hint emit. top-level verb + subverb + flag-choice
  자동 상속 (argparse parent class 기본값). 기존 메시지 텍스트/exit code
  2 100% 보존. 적대적 리뷰가 원안의 9 nested subparser `parser_class=`
  명시 추가 모두 redundant임을 catch (자동 상속).
- **H — human-only output** — `format_status_human`에서 `Next action`
  라인 항상 emit (None일 때 `(none — <reason>)` 표시). halt age 4-tier
  단위 변환 (s/m/h/d). `next --json` help wording 통일. JSON output
  shape 모든 항목 불변 (필드 추가/제거 X). H4 `state_cli` 힌트는
  PlanningProjection vs raw state dict mismatch로 v0.8.0 이전.
- **I — target-local wrapper help** — `check_harness.py`,
  `doctor_harness.py` argparse description + epilog 보강 (1-2줄 설명 +
  예시 + 관련 verb cross-ref).

### Not changed

- JSON output shape (필드 추가/제거/이름변경 X)
- schema, state_schema_version
- 모든 exit code 의미 (`Fix:` 라인 텍스트만 추가)
- approval/security boundary (TTY gate, nonce, audit chain)
- manifest hash 메커니즘 (Group F adapter 파일 변경은 manifest entry에
  sha256 없음 — release.py에 manifest 재baseline 단계 없으므로 안전)
- v0.7.0/v0.7.1 "Carried over" 모두 v0.8.0 scope 유지

## v0.7.1 — 2026-05-18 (hotfix)

Pre-release adversarial-review remediation. Two findings from
`.scratch/reports/pr-2-adversarial-review.md` (independent reviewer round
that produced the PR-2 review, distinct from the 3-Opus persona round
folded into v0.7.0) were left unaddressed at v0.7.0 tag. This hotfix
closes both with no surface or schema changes — drop-in replacement.

### Fixed

- **P0 — Source-checkout fails with bare `ModuleNotFoundError: psutil`.**
  README §빠른 설치 documents direct `python3 scripts/harness.py ...`
  execution, but `scripts/lib/phase_lock.py` (reached on the very first
  phase command) imports `psutil` unconditionally and crashes with a raw
  Python traceback when the user has not yet run `pip install -e .`.
  Same hazard for `rfc8785` via `scripts/lib/audit_chain.py`.
  Both imports are now wrapped in `try/except ImportError → SystemExit`
  with an actionable message naming the exact install command.
  The runtime dependency declaration in `pyproject.toml` is unchanged;
  callers that already `pip install -e .` see no behavior change.
- **P1 — `release-gate-summary` job can stay green when release-smoke
  fails.** `.github/workflows/release.yml` summary previously had
  `if: always()` and only inspected `powershell-deny-fuzz.result`, so a
  release-smoke `failure`/`cancelled`/`skipped` would leave the summary
  green. With the summary used as the single release branch-protection
  gate, that was a real release leak. Added an explicit step that fails
  the summary on `needs.release-smoke.result != 'success'`. The
  matrix-row `continue-on-error` for `nice-to-have` and
  `release-gate-degraded-tolerant` rows is unchanged, so degraded rows
  still do not block.

### Not changed

- v0.7.0 "Carried over" deferrals remain v0.8.0 scope:
  audit-chain GENESIS fallback, `consumer_tty` server-binding,
  audit-rotation Windows atomicity, native Windows pre-commit-scope hook,
  SSH-signed release tags (`allowed-signers` is still a placeholder; the
  PR-2 review flagged this third item as P1 but it was already an
  intentional v0.7.0 deferral per the v0.7.0 "Carried over" section —
  not re-litigated in this hotfix).

## v0.7.0 — 2026-05-18

First "internal-share-stable" release. Summary:

- **Phase-gate hardening rounds 02b / 02c / 02d** — 17 slices + 5-perspective
  Opus adversarial-review panel; full audit-chain hash chain (S06), state
  schema v2 (L1/L2), fnmatch path grammar (L3), forward-only migration (L12),
  approval-nonce HMAC (B-series), out-of-repo audit-tip anchor (S03),
  release-trust scaffold (R-series), Windows containment (W-series).
- **HMAC-signed approval nonces** — `harness approve-nonce mint` /
  `approve-nonce consume`, sidecar fcntl/msvcrt lock for create/rotate.
- **Release-trust scaffold** — `release-check`, `docs/trust/allowed-signers`
  stub, `--allow-unsigned-dev` flag. *Not yet activated on v0.7.0 tag itself —
  see README §7 Known Limitations.*
- **Windows safe_open** — CreateFileW + reparse-point refusal.
- **Audit-verb registry expansion** — CI/OIDC, migration, session verbs.
- **Exit-code spec alignment** — 0–15 (full table in `docs/USER_MANUAL.md`
  §14, including codes 9/17/18 added in this release).

Detailed breaking changes, additions, and infrastructure work are listed in
the sections below.

### Adversarial-review remediations folded in immediately before tag

Three Opus adversarial reviewers (cross-platform / workflow / UX) ran against
the release candidate. The following CRITICAL findings were fixed in-place
before tagging v0.7.0; remaining deeper-architecture findings are listed
under "Carried over" and tracked for v0.8.0.

1. **Windows import-portability fix** — `scripts/lib/atomic_io.py`,
   `scripts/lib/audit.py` now gate `fcntl` behind `os.name == "posix"` and
   use `msvcrt.locking` on Windows. Previously every state-write path was
   unimportable on native Windows.
2. **`atomic_write_text` durability + byte-identity** — uses
   `durable_fs.replace_with_retry` (Windows AV-aware) and passes
   `newline=""` to `NamedTemporaryFile` so embedded `\n` is never translated
   to `\r\n` (would break audit/state hash chains on Windows).
3. **`phase_lock.current_owner_record` ambiguity sentinel** — on
   transient psutil failure, `process_start_time` is recorded as `None`
   (was `0.0`). `classify()` now treats `None` as `"ambiguous"` instead
   of falsely classifying a live holder as `"stale"`, preventing a
   `try_recover` race that could unlink the lock under an active owner.
4. **Doc / CLI alignment** — `phase_lock` error messages and
   `docs/USER_MANUAL.md` no longer point to nonexistent verbs
   (`harness lock recover --force` → `harness session unlock --force`;
   `halt-diary show` removed; `migrate --target` corrected to
   `migrate state --forward|--reverse|--resume`). Install snippets in
   README + USER_MANUAL no longer ship the literal `{Repo git}`
   placeholder. README §7 lists Known Limitations honestly.

### Carried over (deferred to v0.8.0)

- Audit-chain GENESIS fallback (`audit_chain.compute_entry_hash`) — full
  on-disk-chain integrity requires removing the absent-prev fallback +
  validating first-entry seeds. Out-of-repo anchor still mitigates today.
- Approval-nonce `consumer_tty` server-binding via `os.ttyname(0)` +
  `st_rdev` — same-TTY agent currently bypasses isolation if it supplies a
  fake distinct value via `--consumer-tty`.
- Audit-rotation Windows atomicity (`audit.py` `os.rename` → `os.replace`).
- Native Windows pre-commit-scope hook (POSIX-`sh` body today).
- SSH-signed release tags (`allowed-signers` is a placeholder; first signed
  tag pending).

---

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
- **L10 — `.bak` relocated to `.harness/backups/` + retention=10 (T0-5).**
  `state repair` no longer writes `.bak` files alongside the source under
  `.planning/`. All pre-rewrite snapshots are now written under
  `<root>/.harness/backups/<basename>.pre-repair.<UTC-compact-nanos>.<pid>.bak`
  (CONTRACT-PIN §6.1 filename grammar) via the shared
  `scripts/lib/backups.py` helper with `O_EXCL` + `O_NOFOLLOW`, a `0o700`
  backups directory, and a retention cap of 10 per basename (oldest pruned
  best-effort). `.bak` writes precede the atomic rewrite of the original
  file; on backup collision (`SystemExit(1)`) the original is never
  touched. The previous behavior (no `.bak` at all for `state_repair`) is
  replaced with a durable per-target snapshot.
- **L13 — Paused phases first-class in `STATE.md` `managed:state-current`
  block (T0-5).** When `.scratch/phase-state.json` carries a non-empty
  `paused_phases: [{"slug": "...", "paused_since": "YYYY-MM-DD"}, ...]`
  list, `state repair` now renders a `### Paused Phases` H3 subsection
  INSIDE the `managed:state-current` payload (between
  `<!-- HARNESS:BEGIN -->` and `<!-- HARNESS:END -->`), AFTER
  `## Active Checkpoint`. Each paused phase becomes a line
  `- <slug> (paused since <date>)`. Missing/absent key → no subsection
  (forward-compatible with pre-slice state files). The subsection
  round-trips through `replace_block` without drift on a second
  `state repair` invocation.
- **L18 (T0-5 row) — `.harness/backups/` `.gitignore` entry (T0-5).**
  The skeleton `.gitignore` at `harness/skeleton/clean/.gitignore` now
  contains a `.harness/backups/` line so the per-target `.bak` snapshots
  written by `state repair` and the state migrator are not tracked in
  target repositories. Per CONTRACT-PIN §5.4 row-ownership table.
- **L11 (T0-5 wrap) — `state_repair` refuses to rewrite on malformed
  `phase-state.json` (T0-5).** T1-M routed the parse through
  `load_state_json` (which exits 5); T0-5 now wraps that boundary in
  `RepairRefusedError` so callers can catch the refusal programmatically,
  and the CLI verb `harness state repair` translates it to exit code 5
  (`EXIT_UNPARSEABLE_JSON`, CONTRACT-PIN §4) with the diagnostic
  `state repair: refusing to rewrite — phase-state.json invalid …; fix
  the JSON or restore from .harness/backups/`. No data is written;
  pre-existing `ROADMAP.md` and `STATE.md` bytes are preserved
  byte-identical. Duplicate `managed:state-current` blocks similarly
  surface as `RepairRefusedError` ("duplicate managed block 'state-current'")
  with exit 5 instead of a `ValueError` traceback.
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

### Tooling

- **02b-10**: Phase E low-reasoning scenario harness (N=50 Haiku-4.5 trials
  per flow, ≥80% pass threshold, evidence-based release gate per spec §9.1).
  Ships `scripts/smoke/low_reasoning_scenario.py` plus four deterministic
  fixtures (`discuss→plan`, `plan→approve`, `execute→done`, full lifecycle),
  programmatic judge (no LLM-as-judge; routes through
  `scripts.lib.state_diagnostics.load_state_json` + `VERIFICATION_PREFIXES`),
  budget caps (60s wall / 20k input / 4k output tokens — hard fail, no
  retry), max-2 flake-retry with noisy-trial tracking, per-trial JSON
  evidence under `.planning/phases/02b-hardening/evidence/<timestamp>/per-flow/`,
  and aggregator that writes `SUMMARY.json` + `SUMMARY.md` with a
  RELEASE-GATE verdict. Escape clause: if `ANTHROPIC_API_KEY` is absent the
  runner writes `SKIPPED.md` and exits 0 with a `SLICE BLOCKED` banner
  (spec §9.1 — never silent unmeasured claim). 32 self-tests run without
  the key via `FakeClient`; one optional live smoke gates on
  `HARNESS_E2E_LIVE=1`.
- **02b-11**: Smoke harness extended with three adapter-neutral lifecycle stages
  (core, Roo, OpenCode) and static grep gate against quarantined adapter
  commands. Each stage drives the same scripted `discuss → plan → approve →
  execute → approve → done` flow through `scripts/lib/smoke_lifecycle.py` and
  asserts shape parity against `scripts/smoke/golden/cli-contract-lifecycle.json`
  (hand-derived from ADR Artifact 1; never regenerated from runtime). Per spec
  §10.2 and `.planning/phases/02b-hardening/plans/02b-11-SMOKE-EXT-PLAN.md`.
  **Deviation from plan body:** the plan body (Goal + Test 10) originally said
  "5 audit entries / 1 approve"; the actual lifecycle requires **6 entries / 2
  approve calls** (one for `plan → execute`, one for `execute → done`). The
  golden, the canonical `STAGE1_INVOCATIONS` list, and Test 10 are reconciled
  to 6 entries; the plan body has been updated in place to match.
- **T0-3 follow-up — `state_schema_version=2` is now stamped on every
  state write** (`harness phase set` and `harness phase approve`). Closes
  the L2 contract gap surfaced by 02b-11 review (commit `bab5c5d` had
  used an `<ANY>` sentinel in `cli-contract-lifecycle.json` as a
  temporary workaround). The runtime helper `_ensure_state_schema_version`
  in `scripts/lib/phase_cli.py` now (a) stamps `2` when the field is
  absent, (b) no-ops when already `2`, and (c) exits 5 with
  `state_schema_version={N} expected 2; run 'harness migrate state
  --forward' first` on any other value. The smoke golden now pins the
  literal `2` and `_compare_to_golden` enforces strict equality on the
  field (the `<ANY>` sentinel for `approved`/`approved_at`/`approved_by`
  is retained per ADR-001).

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
