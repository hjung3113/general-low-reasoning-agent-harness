# Workflow Enforcement

이 문서는 **유지해야 할 핵심 기능**. 저성능 AI에게 `discuss → plan → execute → done` 워크플로우를 강제하는 메커니즘 전부.

## 1. Phase state machine

### Phase values

```
discuss → plan → execute → done
```

`scripts/lib/phase_state.py:24-28` 정의. `transition.py:37-53` 전이 표:

| From | To | requires_approved | requires_reset_approval |
|---|---|---|---|
| None | discuss | False | False |
| discuss | plan | False | False |
| plan | execute | **True** | False |
| execute | done | **True** | False |
| plan | discuss | False | **True** |
| execute | plan/discuss | False | **True** |
| done | discuss/plan/execute | False | **True** |
| done | done | False | False (idempotent) |

**규칙**: forward edge → approval 필요. backward edge → `--reset-approval` 필요.

### Execution modes (v2 schema)

```python
EXECUTION_MODES = {"manual", "phase_autopilot", "chain_autopilot"}
```

Legacy `automation_mode` (v0.6.1) 자동 마이그레이션: chain→phase_autopilot, auto→chain_autopilot.

### State file: `.scratch/phase-state.json`

v2 필드 (`phase_state.py:42-61`):
```
execution_mode, autopilot_run_id, autopilot_mode, autopilot_phase_slug,
autopilot_start_entry_hash, autopilot_allow_network, autopilot_started_at_iso,
cli_budgets_remaining, last_halt, last_halt_history, execute_attempt_started_at,
plan_finalized_at, draft_verification, draft_allowed_paths
```

### Stale-approval check (§3.6)

`stamp_transition_timestamps()` (`phase_state.py:147-186`):
- plan 진입 → `plan_finalized_at = now`
- execute 진입 → `execute_attempt_started_at = now`

Approval은 둘 모두보다 나중이어야 유효. 옛 approval로 새 plan 통과 못 함.

## 2. Phase CLI commands

`scripts/lib/phase_cli.py` + `phase_approve.py` + `phase_reopen.py`.

| Verb | Behavior | Exit codes |
|---|---|---|
| `harness phase set <target>` | 전이 검증 → lock → state-trust preflight → commit_transaction | 0/2/4/10/14 |
| `harness phase approve` | **TTY-only** [y/N] prompt → `approved=true` stamp. 허용 phase: plan/execute. 식별: gitconfig email or `--by`. approver membership 검증 (`.harness/install-record.json`) | 0/17/idempotent |
| `harness phase reopen --to <p> --reason <t>` | **TTY-only**. plan/discuss로 backward. approval/verification/allowed_paths 클리어. autopilot 중이면 halt diary 회전 | 0/6 |
| `harness phase next-pending` | 다음 미완 phase slug 출력 (read-only) | 0 |
| `harness session unlock [--force]` | stale lock 해제 (psutil로 dead-PID 확인) | 0/3 |

### Lock acquisition flow (모든 mutating verb)

1. Acquire `.harness/session.lock` (timeout 10s)
2. state-trust preflight (audit oracle 검증)
3. Load phase-state.json
4. `transition.validate_transition_with_state()`
5. `phase_txn.commit_transaction()` — atomic state+audit write
6. Release lock

## 3. Approval gate (`phase_approve.py`)

Speed-bump 디자인 (2026-05-19 ADR). 순서:

1. TTY gate: stdin not tty → exit 17
2. Phase guard: plan/execute만 (discuss 차단)
3. Identity: `--by <email>` 또는 `git config user.email`
4. Approver membership 검증
5. Anchor preflight (state hash)
6. `execution_mode != manual` → exit 8 (autopilot 중 approve 금지)
7. Idempotency: 이미 approved면 exit 0 no-op
8. TTY [y/N] prompt
9. commit_transaction with `proof_class=soft_tty`

Fix-line 메시지 표 (ADR-003a Artifact 1):
- `_FIX_TTY`, `_FIX_GITCONFIG`, `_FIX_APPROVER_MEMBERSHIP`, `_FIX_AUTOPILOT`, `_FIX_STATE_TRUST`

## 4. Planning grammar

`scripts/lib/planning_grammar.py`. Document layout:

```
.planning/
├── STATE.md                       # 현재 phase + checkpoint
├── ROADMAP.md                     # phase 체크리스트
├── codebase/**                    # 인벤토리
└── phases/<NN[a-z]>-<slug>/...    # phase 폴더
```

### Managed marker blocks (machine-owned)

```html
<!-- HARNESS:BEGIN managed:<slug> v1 -->
...
<!-- HARNESS:END managed:<slug> -->
```

필수 slugs:
- `roadmap-phases` in ROADMAP.md
- `state-current` in STATE.md

마커 외부 (Notes, Session Continuity) = agent-editable. 내부 = harness가 `state repair`로 재생성.

### Regex patterns (planning_grammar.py:73-87)

- STATE phase line: `- **Phase**: <N> - <title>.`
- STATE checkpoint: `- **Checkpoint**: <id> - <title>.`
- ROADMAP bullet: `- [x] **Phase <N>: <title>** - <summary>`

Letter suffix 지원 (`1a`, `2b` 등).

## 5. Roadmap state sync (`roadmap_state.py`)

`check_roadmap_state_sync()` 5-point invariant:

1. ROADMAP phase count == STATE.progress.total_phases
2. completed count == STATE.progress.completed_phases
3. percent matches (completed/total*100)
4. active_phase == first incomplete
5. `.scratch/phase-state.json` 의 state_path/checkpoint_path/current_checkpoint == STATE.md 값

실패 → SystemExit + drift report.

## 6. Status & next-action (`status_next.py`, `status_next_cli.py`)

**Read-only projection** — lock 없이 짧게 잡고 state-trust preflight만. audit row 안 씀.

### StatusResult 필드 (status_next.py:50-65)

```
phase, phase_entered_at_iso, approved, approved_by, approved_at_iso, approved_source,
execution_mode, autopilot_run_id, autopilot_phase_slug, last_halt, last_halt_age_seconds,
projected_execute_gate_valid, can_enter_execute, next_action
```

Boolean gates:
- `projected_execute_gate_valid` = phase==execute AND approved AND approved_at >= execute_attempt_started_at
- `can_enter_execute` = phase==plan AND approved AND approved_at >= plan_finalized_at

### `harness next` exit codes

- 0 = agent_safe (concrete command 추천)
- 17 = human_action_required
- 18 = no_action_during_autopilot

## 7. Check command (`check.py`, 1110 LOC)

19개 검사 종목:

| # | Check | Purpose |
|---|---|---|
| 1 | import smoke | AST로 `from lib.X` import 검증 (T8a, BUG-2) |
| 2 | hash drift | per-policy SHA256 매트릭스 — harness-owned/managed/managed-append (T8b) |
| 3 | state sha drift | phase-state.json hash vs 마지막 audit after_sha256 |
| 4 | planning drift | project_dashboard.core 호출 |
| 5 | clean skeleton presence | harness/skeleton/clean/ 존재 |
| 6 | JSON structure | .roomodes, phase-state.json/.schema/.example 파싱 |
| 7 | phase-state semantics | schema_version=2, phase∈{discuss,plan,execute,done}, ISO-Z timestamps, 순서 |
| 8 | command-mode sync | .roomodes slugs vs .roo/commands/*.md |
| 9 | phase reference drift | 옛 템플릿 문구 검출 |
| 10 | phase-state paths | state_path/checkpoint_path/plan_path 파일 존재 |
| 11 | roadmap/state sync | 5-point invariant |
| 12 | manifest validation | load_manifest 일관성 |
| 13 | scope validation | adapter/profile/pack 이름 |
| 14 | installed target validation | 스코프 호환, managed-append 중복, hash drift opt-in |
| 15 | worktree paths | 스테이지/언스테이지 변경 |
| 16 | managed-block integrity | 마커 블록 누락/오염 |
| 17 | verification prefixes (ADR-004) | 허용: `python3`/`git`/`jq`/`npx`/`pytest`/`harness`/`make`. `bash ` 금지 |
| 18 | required AGENTS.md 문구 | Karpathy guideline / phase=execute gate / discuss pass |
| 19 | contamination | PR #N, "DB context snapshot", "implemented/완료", "under PR review" |

## 8. Halt diary (`halt_diary.py`)

Autopilot 정지 기록.

State 필드:
```python
last_halt = {
  "run_id": "...",
  "halt_reason": "...",
  "halted_at_iso": "...",
  "acknowledged_at": "<iso or None>"
}
last_halt_history = [...]  # cap=5
```

**Halt blocking** (`transition.py:338-350`, §12.12):
- `execute → done` 차단 if `last_halt && !acknowledged_at`
- 해결: `harness halt-diary clear` 또는 `phase reopen`

### `halt-diary clear` 흐름

1. TTY gate → exit 6
2. `last_halt is None` → exit 0 no-op
3. `acknowledged_at = now`, 이전 diary → history, `last_halt = None`
4. commit_transaction (verb=halt_diary.clear)

## 9. Pre-commit hook (`hooks.py`)

`.git/hooks/pre-commit`에 설치. 마커:
```bash
# HARNESS:scope-check-begin
python3 scripts/harness.py check --worktree
# HARNESS:scope-check-end
```

차단 조건:
- 변경이 `allowed_paths` 밖
- scope-controlled 폴더에 untracked 파일
- managed/harness-owned hash 불일치

**Exit 4 = `EXIT_SCOPE_VIOLATION`** (CONTRACT-PIN §4).

Install: 없으면 skeleton 전체 작성; 있으면 마커 블록만 in-place 교체. Uninstall: harness-only면 파일 삭제, user content 있으면 envelope만 surgical 제거.

Security: owner-execute bit만, umask 존중.

## 10. Profile/skill-pack selection (`profiles.py`)

```python
KNOWN_PROFILES = {"generic", "dotnet-etl", "python-etl", "react-web"}

_PROFILE_DEFAULT_PACKS = {
  "generic": ("workflow-core",),
  "dotnet-etl": ("workflow-core", "workflow-etl", "tech-csharp"),
  "python-etl": ("workflow-core", "workflow-etl", "tech-python"),
  "react-web": ("workflow-core", "workflow-web-development",
                "tech-react", "tech-typescript", "tech-tailwind"),
}

_DB_PACKS = {
  "mssql": ("tech-mssql", "workflow-db-context"),
  "postgresql": ("tech-postgresql", "workflow-db-context"),
  "none": (),
}
```

Default = generic. Repo evidence + user input 으로 specific profile 선택. Legacy alias: `dotnet-etl-mssql → dotnet-etl` (deprecation warning).

## 11. AGENTS.md skeleton rules

`harness/skeleton/clean/AGENTS.md` 강제 규칙:

1. `.scratch/phase-state.json != phase=execute+approved=true` → application code 수정 금지
2. Managed marker blocks = machine-owned, 손대지 말 것
3. 매 phase는 `discuss` pass로 시작
4. ADR/phase 확정 전 `grill-me` 정렬 + 적대적 리뷰 (expert 2 × lens 3)
5. `--auto` = low-risk default만, `--chain` = 단일 phase discuss→plan→execute (verified)
6. Skill plugin 디시플린 (generic 기본, repo evidence 우선)
7. Karpathy guidelines (think before coding, simplicity first, surgical changes, goal-driven)

## 12. Phase reopen (`phase_reopen.py`)

Backward transition.

검증:
1. TTY gate
2. `--reason` mandatory
3. `--to` ∈ {plan, discuss}
4. Identity + approver membership
5. state-trust preflight
6. Source 제약: `--to plan`은 execute/done에서만, `--to discuss`는 어디서나

Mutation:
- phase → target
- approved/approved_at/approved_by → null
- verification → draft_verification (보존), allowed_paths → draft_allowed_paths
- execute_attempt_started_at = None
- autopilot 중이면: last_halt 기록 + history 회전 + autopilot 필드 클리어 + execution_mode=manual

Audit: `phase.reopen` + (autopilot active면) `phase.autopilot.halt` — 같은 atomic txn.

## 13. State trust preflight (`state_trust.py`, `phase_preflight.py`)

`.scratch/phase-state.json` 변조 검출. 모든 phase-mutating verb 시작에서 호출.

1. Canonical SHA256(state file) 계산
2. Audit log (rotation 포함) 역추적 → 가장 최근 TXN verb 의 `after_sha256`
3. Mismatch → exit 10 `state_audit_mismatch`
4. Baseline state (fresh install, approved=false, phase=discuss, no plan_id) 는 audit 증거 없어도 OK
5. `autopilot_start_entry_hash` PENDING (crash marker) → exit 14, recover() 필요
6. BOM/CRLF/malformed JSON 거부

## 14. Crash-safe transaction (`phase_txn.py`)

5-step protocol (lock held throughout):

1. Write `.journal` (in-flight txn marker)
2. Compute new state + audit entry
3. Atomic rename `.tmp → phase-state.json` (durable fs)
4. Append audit entry with `entry_hash`, `txn_id`, `after_sha256`
5. Cleanup journal/tmp

Recovery matrix (`recover()`, 12 rows) — 크래시 후 다음 CLI 시작 시 partial state 해결.

Exit: 0 / 3 (locked) / 14 (undecidable).

**Phase 1 note**: No change to core protocol; all crash-safety mechanisms retained.

## 15. Exit codes (`exitcodes.py`)

| Code | Symbol | Meaning |
|---|---|---|
| 0 | EXIT_OK | success |
| 2 | EXIT_INVALID_TRANSITION | bad phase transition |
| 3 | EXIT_SESSION_LOCKED | .harness/session.lock held |
| 4 | EXIT_SCOPE_VIOLATION | pre-commit scope check failed |
| 5 | EXIT_UNPARSEABLE_JSON | malformed JSON |
| 6 | EXIT_WRONG_PHASE_FOR_VERB | phase guard rejected |
| 10 | EXIT_STATE_AUDIT_MISMATCH | state trust failed |
| 14 | EXIT_CRASH_RECOVERY_UNDECIDABLE | manual intervention |
| 17 | EXIT_NON_TTY | TTY-only verb hit non-TTY |
| 18 | EXIT_NO_ACTION_DURING_AUTOPILOT | autopilot active |

## Workflow invariants (요약) — Phase 1 complete

1. 11개 허용 전이만 (transition.py 표)
2. Forward edge → approval 필수
3. Stale-approval check (post-date plan/execute timestamps)
4. Halt diary unacknowledged → execute→done 차단
5. Managed marker blocks = machine-owned
6. Roadmap/state 5-point sync
7. Hash drift detection (harness-owned/managed/managed-append)
8. Pre-commit scope gate (exit 4)
9. TTY-only speed bumps (approve, reopen, halt-diary clear)
10. Crash-safe state+audit transactions

**Phase 1 removals**: No workflow enforcement changes. All security removal was dormant code (autopilot_guard, fs_fence, secret_key, cli_deprecated, audit_verify_cli, release_trust SSH dead code). Audit chain + state_trust + crash-safety fully retained.
**Phase 2 removals**: state_migrate, state_migrate_t04, migrate_state (v0→v2 migration — all state is now v2; `harness migrate state` subcommand removed).
