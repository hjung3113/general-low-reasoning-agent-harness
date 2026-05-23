# 하네스 사용 매뉴얼

설치된 하네스를 타겟 프로젝트에서 일상적으로 사용하는 법.

대상: 타겟 프로젝트에서 `discuss → plan → execute → done` 워크플로우를 진행하는 개발자 (또는 감독 에이전트).

설치 절차는 [`README.ko.md`](README.ko.md). 용어 정의는 [`CONTEXT.md`](CONTEXT.md). 전체 CLI 표면은 [`docs/CLI.md`](docs/CLI.md).

English version: [`MANUAL.md`](MANUAL.md).

## 워크플로우

모든 프로젝트 작업 단위는 4 phase 순차 진행:

```
discuss → plan → execute → done
```

하네스가 순서 강제. Forward edge (`discuss → plan`, `plan → execute`, `execute → done`) 는 명시적 approval 필요. Backward edge (예: `execute → plan`) 는 `--reset-approval` 필요. 건너뛰기 불가.

| Phase | 할 일 | 다음 |
|---|---|---|
| `discuss` | `.planning/phases/NN-*/NN-CONTEXT.md` 에 문제 정의. 코드 변경 ❌. | `plan` |
| `plan` | `NN-NN-PLAN.md` 작성: 구체적 단계 + 수용 기준. | `execute` (approval 필요) |
| `execute` | 코드 변경. `draft_allowed_paths` 범위 안에서만. | `done` (approval 필요) |
| `done` | `NN-VERIFICATION.md`, `NN-NN-SUMMARY.md` 작성. 추가 변경 ❌. | 다음 마일스톤 또는 `discuss` |

## 자주 쓰는 명령

### 현재 위치 확인

```bash
harness status        # phase + checkpoint + 다음 권장 action
harness next          # 다음 action 만
```

### 전진

```bash
harness phase set discuss      # discuss 진입 (approval 불필요)
harness phase set plan         # discuss → plan (approval 불필요)
harness phase approve          # TTY [y/N] gate
harness phase set execute      # plan → execute (approval 필요)
harness phase approve          # execute → done 위해 한 번 더
harness phase set done
```

`phase approve` 는 TTY 전용 — stdin/stdout 이 tty 가 아니면 거부 (exit 17). Identity 는 기본 `git config user.email`; `--by user@example.com` 으로 오버라이드. **Self-approval 정상** (2-person control 아님 — [`docs/adr/0002-internal-tool-threat-model.md`](docs/adr/0002-internal-tool-threat-model.md) 참조).

### 후진 (드물게)

```bash
harness phase reopen --to plan --reset-approval
```

Backward 전이는 직전 approval 무효화. execute 시작 후 plan 수정 필요할 때.

### 헬퍼

```bash
harness phase next-pending     # 다음 미완 phase slug
harness session unlock         # crash 후 stale session lock 해제
harness state show             # parsed phase-state.json 출력
harness state repair           # managed AGENTS.md block 재생성
harness run                    # 다음 안전한 step 실행 + human gate 에서 정지
harness recon                  # .planning/codebase/{STACK,STRUCTURE,TESTING,INTEGRATIONS}.md 자동 채움
```

### 코드베이스 오리엔테이션 (`.planning/codebase/`)

`harness recon` 은 8개 파일 (6 core + 2 conditional) 의 구조화된 디렉토리를 채움. 모든 workflow skill-pack 이 읽는 코드베이스 계약 역할을 함:

- **CLI 자동 채움** (직접 편집 X): `STACK.md`, `STRUCTURE.md`, `TESTING.md` (프레임워크 + 명령), `INTEGRATIONS.md` (외부 통합 감지 시에만).
- **에이전트 소유** (`workflow-codebase-recon` skill-pack 이 채움): `SUMMARY.md`, `CONVENTIONS.md`, `CONCERNS.md`, `ARCHITECTURE.md`.

각 섹션은 `## [codebase.stack.runtime] Runtime` 같은 앵커 ID 사용. 하위 skill-pack (`workflow-tdd`, `workflow-debugging`, `workflow-code-review`, `repository-evidence-research`) 이 전체 파일을 다시 읽지 않고 특정 사실만 grep 가능. 스키마 + 앵커 목록 + frontmatter 모양: [`docs/CODEBASE-SCHEMA.md`](docs/CODEBASE-SCHEMA.md). 의사결정 근거: [`docs/adr/0008-multi-file-codebase-recon.md`](docs/adr/0008-multi-file-codebase-recon.md).

`harness recon` 재실행 안전: 자동 파일은 덮어쓰지만 agent 소유 파일의 본문은 보존됨 (frontmatter 의 `updated_at` 만 다시 찍힘).

## 사용자가 관리하는 planning 문서

마일스톤별로 `.planning/phases/NN-<slug>/` 디렉토리. 하네스가 이걸 읽어서 검증. 사용자가 직접 작성.

```
.planning/
├── ROADMAP.md                  # 마일스톤 목록 (Milestone N: Title)
├── STATE.md                    # 현재 마일스톤 + 체크포인트 포인터
└── phases/
    └── 03-some-milestone/
        ├── 03-CONTEXT.md       # discuss phase
        ├── 03-CHECKPOINTS.md   # plan phase
        ├── 03-01-PLAN.md       # plan phase
        ├── 03-VERIFICATION.md  # done phase
        ├── 03-REVIEW.md        # 선택
        └── 03-01-SUMMARY.md    # done phase
```

문법 규칙 (`planning_grammar.py` 강제):
- `ROADMAP.md` bullet: `- [ ] **Milestone N: Title** - summary` (레거시 `**Phase N:**` 도 허용)
- `STATE.md` state 라인: `- **Milestone**: N - Title`
- Phase 폴더: `NN-slug`, `NN` 은 zero-pad

잘못된 라인은 grammar 가 거부 — 편집 후 `harness check` 권장.

## Approval — identity 기록 방식

`harness phase approve` 실행 시:

1. Identity 결정:
   - `--by user@example.com` 가 주어지면 그것
   - 아니면 `git config user.email`
2. TTY `[y/N]` 프롬프트. `n` 누르면 아무것도 기록 안 함.
3. `y` 누르면: state 에 `approved_by` + `approved_at` 찍힘. `.harness/audit.jsonl` 에 audit row 1줄 append.

환경 변수 (`HARNESS_BY_TRUST` 등) 는 identity 에 **영향 없음**. Override-identity 탈출구 없음.

### 에이전트 주도 워크플로우 (Agent-driven workflows)

하네스는 에이전트 주도 실행 + 휴먼 감시를 위해 설계됨. 에이전트 (또는 스크립트) 는 `discuss`, `plan`, `execute` phase 를 무인으로 진행할 수 있음. **그러나 approval (phase 전이) 는 반드시 휴먼이 실제 터미널에서 해야 함**. 이것이 에이전트가 전체 사이클을 독립적으로 도는 것을 방지하는 checkpoint.

의도된 패턴:
1. 에이전트가 `discuss`, `plan`, `execute` phase 자동 진행.
2. 감시 휴먼이 자신의 터미널에서 `harness phase approve` 대화형 실행.
3. 휴먼이 prompt `[y/N]` 검토 후 전이 명시적 동의.
4. Approval 감시: audit log 에 누가, 언제 승인했는지 기록됨.

TTY 요구 (터미널 아니면 exit 17) 는 제약이 아님 — 설계임. **휴먼으로 handoff 하는 것이 핵심**. 에이전트가 프로그래매틱으로 approval 할 수 있으면, 하네스는 비감시 자동화로 타락하고 존재 이유가 사라짐. [`docs/adr/0007-tty-approval-is-human-checkpoint.md`](docs/adr/0007-tty-approval-is-human-checkpoint.md) 참조.

## Audit log

`.harness/audit.jsonl` 은 plain JSONL. State-mutating verb 당 1줄. 해시 체인/canonicalization 없음 — forensic 아니라 diagnostic ([`docs/adr/0005-audit-log-is-plain-jsonl.md`](docs/adr/0005-audit-log-is-plain-jsonl.md)).

로그처럼 tail:

```bash
tail -f .harness/audit.jsonl | python3 -m json.tool
```

각 row: `at` (ISO timestamp), `verb`, `phase`, `actor`, `target_path`, `outcome`, `txn_id`, `before_sha256`, `after_sha256`.

## 문제 발생 시

| 증상 | 해결 |
|---|---|
| `phase approve` 가 exit 17 "not a TTY" | Interactive shell 에서 실행, CI 에서는 ❌ |
| `state file present but empty` | `git checkout -- .scratch/phase-state.json` 후 재시도 |
| `session locked: process N alive` | 기다리거나, 죽은 게 확실하면 `harness session unlock` |
| `Refusing to write malformed managed-append destination` | 에러 메시지에 unified diff 같이 출력됨 — `AGENTS.md` 에 수동 적용 후 재시도 |
| `unknown pack: workflow-XYZ` | 이전 마일스톤에서 제거된 pack; 현재 살아있는 set 에서 선택 (`harness check` 로 확인) |
| `harness check` drift 보고 | `harness state repair` (managed block 재생성) 또는 `harness doctor` (read-only 진단) |
| 신규 설치 직후 `harness check` 가 `00-planning-hydration` 관련 경고 | 정상 — skeleton 시드한 템플릿 phase, 첫 마일스톤을 `.planning/ROADMAP.md` + `STATE.md` 에 선언하면 사라짐. 버그 아님. |

Exit code 매핑: [`docs/error-code-map.md`](docs/error-code-map.md).

## Crash 회복

하네스는 phase state 를 primary lock 아래 atomic write — crash 후 항상 old state 또는 new state 중 하나, **half-written 파일 절대 없음**. Journal replay/recovery oracle 없음.

Crash 로 orphan session lock 남으면:

```bash
harness session unlock
```

수동 회복은 이게 유일. State 파일 손상 (드뭄) 은 `git checkout -- .scratch/phase-state.json`.

## 커스터마이징 — AGENTS.md managed block

`AGENTS.md` 는 2 영역으로 분할:

```md
<!-- HARNESS:BEGIN managed:agents-rules v1 -->
... 하네스 관리 영역 (upgrade 시 재생성) ...
<!-- HARNESS:END managed:agents-rules -->

## 프로젝트 메모는 이 줄 아래.
```

Managed block 은 `harness upgrade` 시 재생성. 마커 **안** 의 수정은 다음 upgrade 시 충돌 (덮어쓰기 거부 + diff 출력). 마커 **밖** 수정은 영구 보존.

## 하네스가 **하지 않는** 것

- Plan 이 *옳은지* 판단 ❌ — 사용자 몫
- 코드 품질 / 커밋 메시지 스타일 / 테스트 커버리지 강제 ❌
- 워크플로우 우회 차단 ❌ (예: git history rewrite 로 우회 가능)
- 보안 경계 아님 — 사용자와 머신이 신뢰된다고 가정

70% / 30% 규칙 ([`CONTEXT.md`](CONTEXT.md#scope--non-goals)) 이 설계 계약.

## Uninstall

```bash
harness uninstall --scope all
```

Planning 문서 유지하고 하네스만 제거:

```bash
harness uninstall --scope harness,scratch,agents,adapters
# .planning/ 는 그대로
```
