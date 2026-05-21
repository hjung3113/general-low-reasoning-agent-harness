# 하네스 사용자 설명서 (v0.9.7)

이미 하네스가 설치된 target repository에서 일하는 사람을 위한 설명서입니다.
어떻게 시작하고, 무엇을 prompt하고, 어떤 명령을 언제 쓰는지 처음부터 끝까지 다룹니다.

하네스 설치 자체나 소스 기여는 → [README.md](../README.md)

---

> **TL;DR — 어디서 읽을지 안내**
>
> - **일상 사용자** (개발팀원): **Part 1 (§1–§7)** 만 읽으세요. 명령 4개(`harness`, `harness next`, `harness run`, `harness check`)와 워크플로 모델, 프롬프트 레시피, 제거 절차가 전부입니다.
> - **Adapter 작성자 / Doctor 사용자**: **Part 2 (§8–§9)** 추가로 읽으세요.
> - **Maintainer / Security 담당**: **부록 A** — 보안 모델, Release Trust, 감사 로그, Release Confirmation 상세.
> - **Troubleshooting / Advanced CLI**: **부록 B** — 오류 해결 레시피, 전체 CLI 레퍼런스, Exit Codes.
> - **CI / 자동화 엔지니어**: **부록 C** — 환경 변수, Phase Gate 상세(autopilot), 업그레이드, Windows 지원.
> - **기타**: **부록 D** — Carryover, 참고 자료.

---

## 목차

### §0 — 개념 안내

- [0.1 Speed bump vs Autopilot](#01-speed-bump-방지턱-vs-autopilot)
- [0.2 Glossary / 용어](#02-glossary--용어)

### Part 1 — 일상 사용자

1. [개요](#1-개요)
2. [첫 세션 시작하기](#2-첫-세션-시작하기)
3. [워크플로 모델 — discuss → plan → execute → done](#3-워크플로-모델--discuss--plan--execute--done)
4. [Planning State 문서](#4-planning-state-문서)
5. [Skill Packs — 언제 무엇을 쓰는가](#5-skill-packs--언제-무엇을-쓰는가)
6. [프롬프트 레시피](#6-프롬프트-레시피)
7. [제거](#7-제거)

### Part 2 — Adapter 작성자

8. [Adapters — Roo vs OpenCode vs Core-only](#8-adapters--roo-vs-opencode-vs-core-only)
9. [점검 / Doctor / 검증](#9-점검--doctor--검증)

### 부록 A — Maintainer / Release Trust

- [A1. 보안 모델](#a1-보안-모델)
- [A2. Release Trust](#a2-release-trust)
- [A3. 감사 로그](#a3-감사-로그)
- [A4. Release Confirmation](#a4-release-confirmation)

### 부록 B — Troubleshooting & Advanced CLI

- [B1. 트러블슈팅](#b1-트러블슈팅)
- [B2. CLI 명령 레퍼런스 (Advanced)](#b2-cli-명령-레퍼런스-advanced)
- [B3. Exit Codes](#b3-exit-codes)

### 부록 C — CI / 자동화

- [C1. 고급 설정 flag](#c1-고급-설정-flag)
- [C2. Phase Gate 상세 (Autopilot)](#c2-phase-gate-상세-autopilot)
- [C3. 업그레이드](#c3-업그레이드)
- [C4. Windows 지원](#c4-windows-지원)

### 부록 D — 기타

- [D1. Carryover](#d1-carryover)
- [D2. 참고 자료](#d2-참고-자료)

---

## What's new in v0.9.5

> **v0.9.5** — 2026-05-21 hotfix release. 이전 버전(v0.9.4)의 설치 불능(P0) + 8개 주요 버그를 수정합니다.

### 주요 수정 내역

- **Manifest gap 해소 (T3 + T14b)**: `harness/manifest.json`에 누락된 `scripts/lib/*.py` 모듈 35개 추가. v0.9.4 fresh install에서 발생하던 `ModuleNotFoundError` 완전 해소.
- **Install-record 자동 생성 (T7)**: `harness init`이 `.harness/installed-manifest.json`을 즉시 생성합니다. v0.9.4에서 `approve` / `verify`가 "install-record not found"로 crash하던 문제 수정.
- **State show 루트 탐색 수정 (T9)**: `state show` 명령이 CWD에서 `.git` / `.harness`를 위로 탐색합니다. 서브디렉토리에서 실행해도 올바른 프로젝트 루트를 찾습니다.
- **Daily-four 워크플로 정상화 (BLOCK-2)**: `harness next`가 정상 모드에서 `harness run`을 안내합니다. `init → next → run → check` 네 명령 사이클이 `phase set` 없이도 동작합니다.
- **에러 코드 통일 (T10)**: 모든 에러에서 non-zero exit code를 반환합니다. v0.9.4에서 발생하던 CI 우회 가능성(rc=0) 수정.
- **Dry-run 가짜 격리 수정 (STALE-2)**: `upgrade --dry-run`이 sha256이 일치하는 workaround 파일을 잘못 quarantine하지 않습니다.
- **Done→done 멱등 noop (T13)**: `harness phase set done` 반복 실행 시 rc=0으로 noop 처리. 회귀 시에는 `EXIT_OPERATIONAL` 반환.
- **Atomic install helper (T14a)**: `scripts/lib/atomic_io.py` 추가. install.py / upgrade.py wire-in은 v0.9.6으로 이연.
- **Hash 검증 매트릭스 활성화 (STALE-3)**: `check --verify-hashes`가 per-policy sha256 4개 필드를 실제로 검증합니다.
- **Upgrade 호환 테스트 (T15)**: v0.9.4 → v0.9.5 in-place upgrade를 검증하는 테스트 3종 추가.

---

## §0 — 개념 안내

### 0.1 Speed bump (방지턱) vs Autopilot

이 하네스에는 사용자가 자주 만나는 두 개의 개념이 있습니다. 자주 혼동되니 한 번 짚고 갑니다.

- **Speed bump (방지턱)** — `harness phase approve`가 매번 `[y/N]`로 묻는 단계입니다. 사용자가 `y`를 입력해야 현재 phase가 stamp되고, 그 다음에 `phase set`으로 다음 phase로 이동합니다. **이건 보안 검사가 아닙니다.** 워크플로우 중간에 사람이 한 번 더 확인하라는 의도된 마찰입니다. 답이 `y`가 아니거나, 터미널이 아닌 환경 (agent subprocess, CI 등)에서 실행하면 halt 합니다.
- **Autopilot** — `harness autopilot start`로 시작합니다. 묻지 않고 여러 phase를 자동 진행합니다. 시간/턴 budget이 정해지면 그 안에서만 동작합니다. 기본 OFF.

둘은 독립적인 기능입니다. autopilot이 활성화돼도 speed bump가 모든 phase 전환을 가로채는 것은 아닙니다 (autopilot 자체의 정책에 따릅니다).

### 0.2 Glossary / 용어

| 용어 | 뜻 | 참고 |
|------|----|---|
| **Speed bump (방지턱)** | `phase approve` 시 `[y/N]`로 묻는 단계. 보안 검사 아님. 취소 가능. | §0.1, §1 |
| **Autopilot** | 묻지 않고 여러 phase를 진행하는 모드. Speed bump와 별개. 기본 OFF. | §0.1, §B3 |
| **Phase** | 워크플로우 단계. `phase approve`로 stamp, `phase set`로 전환. | §1 |
| **Phase gate** | 특정 verb가 특정 phase에서만 동작하는 규칙. | 프로토콜 스펙 |
| **Halt** | 하네스가 멈추고 사용자 행동을 요청. 에러 아님. 예: non-TTY halt = "터미널에서 다시 실행하세요". | §B |
| **Audit log** | `.harness/audit.log` — chain-verified append-only. | §A |
| **Release confirmation** | `harness release`가 요구하는 타이핑 토큰. `phase approve`와 다름. (내부 메커니즘은 HMAC nonce이지만 사용자가 보는 용어는 "release confirmation"입니다.) | §A4 |
| **Approve-nonce** | Legacy 용어. `phase approve`에서는 더 이상 사용하지 않습니다. CLI `approve-nonce mint` verb는 v0.9.0에서 deprecated, v1.0에서 제거. | §migration |
| **BY_TRUST** | CI 전용 하네스 flag (release 자동화에서만 사용). 일반 사용자는 설정하지 않음. | §A1, release docs |
| **Trust root** | 설치/업그레이드 시 검증되는 서명된 git tag. Release-path 전용. | §A1 |
| **하네스 설정 flag (harness flag)** | 하네스 내부 설정값 (`HARNESS_*` env vars로 전달). 일반 사용자는 만질 일 없음. | `docs/advanced/harness-flags.md` |

---

## Part 1 — 일상 사용자

## 1. 개요

이 설명서는 하네스가 이미 설치된 target repository에서 실제 작업을 수행하는 팀원을 위한 상세 참고서입니다.

하네스는 target project에 작은 protocol을 설치해서 에이전트가 다음을 지키게 합니다:

- 작업 전에 durable planning state를 읽는다
- 논의, 계획, 실행, 완료 감사를 분리한다
- 명시적 execute 승인 전에는 application code를 수정하지 않는다
- 하나의 거대한 prompt 대신 task에 맞는 workflow skill을 조합한다
- target repository에 실제로 존재하는 명령으로 검증한다

Core protocol은 client-neutral, stack-neutral입니다. Roo와 OpenCode는 adapter이지 source of truth가 아닙니다.

---

## 2. 첫 세션 시작하기

### 2.0 매일 쓰는 명령 4개

설치된 target repository에서 보통 사용자는 아래 네 개만 알면 됩니다:

```bash
harness
harness next
harness run
harness check
```

- `harness`: 짧은 사용 가이드를 보여줍니다.
- `harness next`: 지금 해도 되는 다음 행동을 보여줍니다.
- `harness run`: 안전한 workflow 전환만 실행합니다. 사람 승인이 필요하면 승인 안내를 출력하고 멈춥니다.
- `harness check`: 하네스 구조와 현재 workflow gate를 검증합니다.

저수준 `phase`, nonce, audit, state repair, autopilot 명령은 advanced/debug/CI용입니다. 일반 prompt와 adapter prompt는 이를 정상 경로로 요구하지 않습니다.

터미널 명령을 한 화면에서 보고 실행하고 싶으면 target repository에서 로컬 대시보드를 열 수 있습니다:

```bash
python3 scripts/project_dashboard.py --serve
```

브라우저에서 `http://127.0.0.1:8765/overview`를 엽니다.

- `/overview`: 전체 프로젝트 개요, 마일스톤 진행률, 현재 checkpoint, 다음 행동.
- `/progress`: phase gate 상세, acceptance criteria, verification, allowed/blocked paths, phase 문서.
- `/actions`: `check`, `next`, `run`, `doctor`, snapshot 생성 버튼.

대시보드는 localhost 전용 Python 서버입니다. 버튼은 하네스가 미리 정한 allowlist 명령만 실행하며, 임의 shell 입력은 받지 않습니다. `run`처럼 workflow state를 움직일 수 있는 버튼은 브라우저 확인을 요구하고, 실제 판단은 계속 `scripts/harness.py`의 기존 phase gate가 수행합니다. Speed bump가 나오면 대시보드가 대신 승인하지 않습니다.

유즈케이스별 빠른 안내:

- [처음 설치하고 시작하기](use-cases/first-install.md)
- [매일 쓰는 기본 작업 흐름](use-cases/daily-workflow.md)
- [Roo/OpenCode 어댑터로 작업하기](use-cases/adapter-agent-workflow.md)
- [계획 승인 후 구현하기](use-cases/approval-and-execute.md)
- [문제가 생겼을 때 점검하기](use-cases/troubleshooting.md)

### 2.1 설치 옵션 요약

설치 시 선택한 profile과 database 축이 어떤 skill pack과 adapter가 설치될지 결정합니다:
- `--db mssql` 또는 `--db postgresql` — DB 축 선택 시 해당 tech pack 자동 설치
- Profile: `generic` / `dotnet-etl` / `python-etl` / `react-web`
- Adapter: `roo` / `opencode` / `both` / `none`

### 2.2 설치 직후 확인

target repository 안에서:

```bash
python3 scripts/harness.py check
python3 scripts/harness.py next
```

- `check`: 구조 오류, missing verification, managed block 누락, 단계 경로 drift를 감지합니다.
- `next`: 현재 phase 상태를 바탕으로 다음 안전 행동을 알려줍니다.

### 2.3 Planning State 탐색

일상 작업에서는 먼저 고수준 명령만 사용합니다:

```bash
harness check
harness next
```

`harness check`가 출력 없이 0으로 끝나면 통과입니다. 더 깊은 디버깅이 필요할 때만 `state show`나 직접 파일 읽기를 사용합니다.

고급 탐색이 필요하면:

```bash
ls .planning/
cat .planning/ROADMAP.md
cat .planning/STATE.md
```

`state show` 또는 `show_phase_status.py`가 warning을 보고하면, 그 파일들을 최소한의 필수 읽기 목록으로 삼습니다. 둘 다 없거나 실패하면, 아래 legacy 읽기 순서를 따릅니다:

1. `.scratch/phase-state.json`
2. `.planning/STATE.md`
3. `.planning/ROADMAP.md`
4. `.planning/phases/<phase>/*-PLAN.md`
5. `.planning/phases/<phase>/*-CHECKPOINTS.md`
6. `.planning/phases/<phase>/*-VERIFICATION.md`

### 2.4 처음 에이전트에 할 prompt

Planning hydration만 하고 아직 구현하지 않을 때:

```text
Do not implement yet.
Use repository-evidence-research first.
Hydrate .planning/codebase/** from actual repository evidence.
List confirmed facts, inferred facts, rejected assumptions, and open questions.
Stop before changing application code.
```

Roo를 설치했다면 `/phase-discuss planning-hydration --pass 0`으로 시작.
OpenCode만 설치했다면 `.opencode/commands/discuss.md`를 사용.

일상 구현 작업을 맡길 때:

```text
Run harness check first.
Then run HARNESS_MACHINE=1 harness next and read the JSON.
Only edit files when may_edit is true.
If requires_user_approval is true, show next_user_prompt to the user and stop.
Do not self-approve or run low-level approval, nonce, repair, or phase commands.
After edits, run the verification commands named by the current phase and report results.
```

---

## 3. 워크플로 모델 — discuss → plan → execute → done

### 3.1 각 단계 개요

```
discuss -> plan -> execute -> done
```

(또는 유니코드: discuss → plan → execute → done)

| 단계 | 목적 | 에이전트 행동 | 금지 |
| --- | --- | --- | --- |
| discuss | 요청 이해, evidence 수집 | repository 읽기, phase 후보 제안, 문제 파악 | 구현 금지 |
| plan | 작업 범위 문서화 | allowed_paths, blocked_paths, verification, acceptance criteria 작성 | application code 수정 금지 |
| execute | 실제 구현 | approved paths만 수정, worktree check | plan 밖 파일 수정 금지 |
| done | 감사 및 push 준비 | test, diff, residual risk, push readiness 기록 | 미검증 push 금지 |

모든 roadmap phase는 자신의 `discuss` pass를 먼저 거치고 `plan` 또는 `execute`로 진행합니다.

active phase docs는 다음 순서로 해석합니다:

1. `.scratch/phase-state.json`
2. `.planning/STATE.md`
3. `.planning/ROADMAP.md`
4. `.planning/phases/<phase>/*-PLAN.md`
5. `.planning/phases/<phase>/*-CHECKPOINTS.md`
6. `.planning/phases/<phase>/*-VERIFICATION.md`

### 3.2 단계 전환

일상 흐름은 `harness next`로 확인하고 `harness run`으로 진행합니다. 계획이 준비되면 `harness run`은 스스로 승인하지 않고 사람 승인 안내를 출력한 뒤 멈춥니다.

Advanced/debug/CI에서만 저수준 lifecycle 명령을 직접 씁니다:

```bash
python3 scripts/harness.py phase set discuss
python3 scripts/harness.py phase set plan
python3 scripts/harness.py phase approve        # 현재 phase에 approved=true 스탬프 (다음 phase는 phase set으로 이동)
python3 scripts/harness.py phase reopen --to plan --reason "scope 추가"
```

### 3.3 단계별 권장 prompt

**discuss**:
```text
Use .opencode/commands/discuss.md (또는 Roo /phase-discuss).
Read repository evidence first.
Do not propose code changes — only list confirmed facts, inferred facts, open questions, and phase candidates.
Stop after discuss and summarize.
```

**plan**:
```text
Write the plan to .planning/phases/<phase>/<phase>-PLAN.md.
Include: allowed_paths, blocked_paths, verification commands, acceptance_criteria.
Run adversarial review before submitting the plan.
Do not enter execute until I explicitly approve.
```

**execute**:
```text
Enter execute only after I explicitly approve the plan and `harness check` reports the execute gate is valid.
Modify only the files listed in allowed_paths.
Run `harness check` before finishing.
```

**done**:
```text
Run all verification commands from the plan.
Record results in .planning/phases/<phase>/<phase>-VERIFICATION.md.
Summarize residual risk and rollback path.
Confirm push readiness.
```

### 3.4 Adversarial review 위치

Plan과 execute 사이에 adversarial review를 돌립니다. 권장 review 관점 3가지:
- Protocol/product fit (spec 위반, regression)
- Implementation (edge case, missing test)
- Release/low-reasoning usability (검증 가능성, 이해 용이성)

---

## 4. Planning State 문서

`.planning/**`은 canonical memory입니다. 구조/stack/convention/roadmap/phase plan/검증 evidence/decision 기록을 담습니다.
`.scratch/phase-state.json`은 현재 작업을 열거나 막는 live gate일 뿐입니다. 직접 편집하지 마세요.

### 4.1 문서 역할 요약

| 파일/경로 | 역할 | 편집 주체 |
| --- | --- | --- |
| `.planning/ROADMAP.md` | phase 목록 (managed block 포함) | script (block 내) / human (block 밖) |
| `.planning/STATE.md` | 현재 position + active checkpoint (managed block 포함) | script (block 내) / human (block 밖) |
| `.planning/phases/<phase>/*-PLAN.md` | phase 계획 (자유 양식) | agent + human |
| `.planning/phases/<phase>/*-CHECKPOINTS.md` | 진행 체크리스트 | agent + human |
| `.planning/phases/<phase>/*-VERIFICATION.md` | 검증 evidence | agent + human |
| `.scratch/phase-state.json` | live gate (READ-ONLY for humans/agents) | script only |

### 4.2 Managed Marker Blocks

ROADMAP.md / STATE.md 안에서 machine-owned 영역은 HTML 주석 marker block으로 감쌉니다:

```
<!-- HARNESS:BEGIN managed:roadmap-phases v1 -->
- [ ] **Phase 0: Planning Hydration**
<!-- HARNESS:END managed:roadmap-phases -->
```

- Block 안: 스크립트 소유. 에이전트 직접 편집 금지.
- Block 밖: 자유. Notes / Session Continuity / 자유 prose.

### 4.3 State 관리 명령

| 목적 | 명령 |
| --- | --- |
| projection 보기 (read-only) | `python3 scripts/harness.py state show` |
| projection JSON으로 보기 | `python3 scripts/harness.py state show --format json` |
| 깨진 양식 또는 marker 없는 파일 복구 | `python3 scripts/harness.py state repair` |

`state repair`는 idempotent합니다. 마커 없는 파일이면 marker를 추가하고, 이미 있으면 canonical 형태로 재렌더합니다. Block 밖에 phase 줄이 있으면 `RepairReport.warnings`로 보고하며 흡수하지 않습니다.

**한계**: `state repair`는 별도 canonical hash를 저장하지 않습니다. Block 안을 잘못 편집하면 그 내용을 source-of-truth로 삼아 다시 써넣습니다. 복구는 `git revert`로.

`harness.py check`는 marker가 없는 ROADMAP/STATE에 대해 warning(실패 아님)을 출력합니다. 메시지에 정확한 fix 명령이 포함됩니다.

---

## 5. Skill Packs — 언제 무엇을 쓰는가

skill pack은 플러그인입니다. 필요한 pack만 설치하세요. 생략하면 `workflow-core`가 설치됩니다.

설치된 `.agents/skills/` 아래 pack이 실제 workflow를 구동합니다. Adapter command(`/feature`, `/bugfix` 등)가 적절한 skill을 자동 invoke하거나, 직접 prompt에 명시할 수 있습니다.

### 5.1 Always 포함: workflow-core

모든 install의 기본. 다음 sub-skill을 포함합니다:

| Sub-skill | 역할 |
| --- | --- |
| `repository-evidence-research` | repository evidence 먼저 읽기, confirmed/inferred/rejected 분리 |
| `skill-plugin-composition` | 작업에 필요한 최소 skill 조합 선택 |
| `verification-contract` | target repository에 실제 존재하는 verification command 선택 |
| `risk-review` | rollback, upgrade safety, edge case, operational risk 점검 |
| `multi-agent-review` | product/protocol, implementation, release 관점 리뷰 분리 |
| `release-readiness-audit` | release requirement를 artifact/test/git evidence/push state와 매핑 |
| `data-workflow` | ingestion, transformation, validation, generated dataset |
| `integration-boundary` | 외부 시스템 contract와 boundary |

### 5.2 Quality Workflows

| Pack | 역할 | 언제 쓰는가 |
| --- | --- | --- |
| `workflow-tdd` | test-first red-green-refactor | 새 기능 / 회귀 위험이 있는 변경 |
| `workflow-debugging` | 증상 재현 → 최소화 → 가설 → 계측 → 수정 → 회귀 테스트 | 원인 불명 버그 |
| `workflow-code-review` | diff 적대적 리뷰 (bug, regression, missing test) | PR 전 검토 |
| `workflow-security-review` | auth, secret, permission boundary, dependency risk | 보안 민감 변경 |
| `workflow-skill-authoring` | project-local skill 설계와 검증 | 새 skill 작성 시 |

### 5.3 Tech Packs (stack별)

| Pack | 대상 |
| --- | --- |
| `tech-python` | Python project convention과 verification |
| `tech-csharp` | C#/.NET build, test, nullable, public contract |
| `tech-typescript` | TypeScript typecheck/build expectation |
| `tech-react` | React UI 구현과 browser verification |
| `tech-tailwind` | Tailwind styling constraint와 maintainability |
| `tech-mssql` | SQL Server-backed persistence verification |
| `tech-postgresql` | PostgreSQL-backed persistence verification |

### 5.4 Domain Workflows

| Pack | 역할 |
| --- | --- |
| `workflow-etl` | source, extract, transform, validate, stage, load, observe, restart, idempotency, backfill |
| `workflow-db-context` | DB context snapshot freshness, scope, substitute documentation |
| `workflow-web-development` | frontend 구현, responsive behavior, user-facing verification |
| `workflow-data-analysis` | reproducible analysis, assumptions, outputs, checks |
| `workflow-data-processing` | parsing, transformation, generated artifacts, validation |

### 5.5 Skill 호출 방법

**Adapter 통해 자동 invoke** (권장):
- Roo `/feature` → `workflow-tdd`, `workflow-code-review` 자동 적용
- Roo `/bugfix` → `workflow-debugging`, `workflow-tdd` 자동 적용

**직접 prompt**:
```text
Use workflow-tdd to add X feature.
Use workflow-debugging and workflow-tdd for this bug.
Use workflow-security-review and workflow-code-review. Treat auth changes as high-risk.
```

---

## 6. 프롬프트 레시피

### Planning Hydration

```text
Do not implement yet.
Use repository-evidence-research first.
Hydrate .planning/codebase/** from actual repository evidence.
List confirmed facts, inferred facts, rejected assumptions, and open questions.
Stop before changing application code.
```

### Feature Implementation

```text
Run discuss → plan → execute.
In plan, include allowed_paths, blocked_paths, verification, acceptance criteria, and adversarial review.
Do not enter execute until I explicitly approve.
```

### Bug Diagnosis

```text
Use workflow-debugging, workflow-tdd.
Reproduce the symptom first, minimize it, state hypotheses, instrument only what is needed, then write a regression test before fixing.
```

### Security-Sensitive Work

```text
Use workflow-security-review and workflow-code-review.
Treat auth, permission checks, secrets, logs, config, and dependency changes as high-risk.
Show rollback and verification evidence before done.
```

### Push Readiness

```text
완료 전 python3 scripts/harness.py check, python3 scripts/harness.py check --worktree, 계획에 적힌 검증 명령을 모두 실행하고 결과를 .planning/*VERIFICATION.md에 기록해.
push 전에 서브에이전트 적대적 리뷰를 해줘.
리뷰어는 protocol/product fit, installer/adapter compatibility, release verification/low-reasoning usability 관점으로 나눠.
```

### TDD로 Refactor

```text
Use workflow-tdd.
Write characterization tests for the current behavior before refactoring.
Red-green-refactor cycle. Do not change behavior — only structure.
After refactor, run tests and record coverage delta.
```

### Adversarial Review

```text
Run adversarial review with 3 personas:
1. Protocol/product fit: spec violation, regression, scope creep.
2. Implementation: edge case, missing test, maintainability issue.
3. Release/low-reasoning usability: is this verifiable? understandable by a junior dev?
Record findings in .planning/phases/<phase>/<phase>-PLAN.md under "Adversarial Review".
```

### DB-Sensitive Work (ETL / SQL)

```text
Use workflow-etl and workflow-db-context (또는 workflow-debugging for DB bugs).
Include restart/idempotency proof in the plan.
For schema changes, include rollback DDL and migration test.
```

### Windows 사용자에게 적용

```text
Windows 사용자에게 적용할 명령은 PowerShell 기준으로 써줘.
.sh 스크립트는 Linux/macOS 전용으로 보고, 하네스 핵심 검증은 scripts/harness.py check와 scripts/test_harness.py로 해.
경로는 Windows 절대경로를 그대로 쓰되, manifest나 planning 문서에는 repo-relative POSIX 스타일 경로를 기록해.
```

### 코드 리뷰 요청

```text
Use workflow-code-review.
Review the diff for: bugs, regression risk, missing tests, maintainability.
Output as a structured list: [CRITICAL], [MAJOR], [MINOR], [SUGGESTION].
```

---

## 7. 제거

Target-local uninstall은 전용 script를 씁니다.

```bash
python3 scripts/uninstall_harness.py --interactive
```

Source checkout에서 target을 지정:

```bash
python3 /path/to/harness/scripts/uninstall_harness.py --target /path/to/project --select 1,2 --dry-run
python3 /path/to/harness/scripts/uninstall_harness.py --target /path/to/project --select 1,2
```

**제거 범위**:

| 번호 | 제거 범위 |
| --- | --- |
| 1 | Roo 환경만 제거: `.roo/**`, `.roomodes`, `.rooignore` |
| 2 | OpenCode 환경만 제거: `.opencode/**` |
| 3 | Runtime harness만 제거: `.agents/skills/**`, harness scripts 등. Adapter와 core protocol은 보존 |
| 4 | Core protocol만 제거: `AGENTS.md`/`.gitignore` managed block, `.scratch/**` 등. Adapter/runtime/docs는 보존 |
| 5 | Planning/docs만 제거: `.planning/**`, harness docs/profiles 등. 권장하지 않음. 프로젝트 계획 기록이 사라집니다 |

전체 범위 `1,2,3,4,5`를 삭제해도 기본적으로 `.harness/installed-manifest.json`은 보존됩니다. 설치 상태까지 지우려면:

```bash
python3 /path/to/harness/scripts/uninstall_harness.py --target /path/to/project --select 1,2,3,4,5 --remove-install-state
```

`--dry-run`으로 먼저 확인. Conflict가 있으면 실제 삭제는 중단됩니다.

---

## Part 2 — Adapter 작성자

## 8. Adapters — Roo vs OpenCode vs Core-only

설치 시 선택한 adapter에 따라 사용하는 명령 표면이 달라집니다. 모든 adapter는 동일한 `.planning/**`과 `.scratch/phase-state.json` live gate를 사용합니다.

### 8.1 Roo Adapter

`.roo/commands/`에 설치되는 슬래시 명령:

| 명령 | 용도 | 주요 사용 시점 |
| --- | --- | --- |
| `/phase-discuss` | Phase discovery + planning hydration | 모든 phase 시작 |
| `/phase-plan` | 계획 문서 작성 | discuss 완료 후 |
| `/phase-execute` | 승인된 범위 구현 | phase approve 후 |
| `/adr` | ADR(Architecture Decision Record) 문서화 | 중요 설계 결정 |
| `/bugfix` | 버그 진단 + 수정 워크플로 | 버그 발생 시 |
| `/doctor` | 환경/구조 진단 | 이상 감지 시 |
| `/done` | 완료 감사 | execute 완료 후 |
| `/feature` | 기능 추가 워크플로 | 새 기능 구현 |
| `/issues` | issue 트래커 연동 | 이슈 관리 |
| `/ops` | 운영 작업 (deploy, monitor) | 운영 필요 시 |
| `/review` | 코드 리뷰 | PR 전 적대적 검토 |
| `/simple` | 작은/저위험 변경용 lightweight workflow | 단순 질문, 작은 edit, cleanup |
| `/fsd-run-all` | 전체 FSD dispatch (chain autopilot) | 자동화 실행 |
| `/fsd-run-phase` | 단일 phase FSD dispatch (phase autopilot) | phase 단위 자동화 |
| `/fsd-status` | FSD 현재 상태 확인 | 진행 확인 |

**Roo modes** (기본 8개):

| Mode | 역할 |
| --- | --- |
| `orchestrator` | 전체 조율, phase 진행 관리 |
| `architect` | 설계 결정, ADR 작성 |
| `tdd-code` | TDD 구현 (test-first) |
| `diagnose` | 버그 진단, 환경 점검 |
| `review` | 코드/spec 적대적 리뷰 |
| `docs-issues` | 문서화, issue 트래커 |
| `ops-observability` | 운영, 모니터링 |
| `harness-maintainer` | 하네스 자체 유지보수 |

Profile-contributed mode 추가:
- `ui-engineer` (`react-web` profile + Roo adapter): browser-first UI 구현. Profile 제거 시 자동 drop.

**권장 시작 prompt**:
```text
/phase-discuss planning-hydration --pass 0
```

### 8.2 OpenCode Adapter

`.opencode/commands/`에 설치되는 슬래시 명령:

| 명령 | 용도 |
| --- | --- |
| `/discuss` | 요구사항 논의, phase 후보 제안 |
| `/plan` | 계획 문서 작성 |
| `/execute` | 승인된 범위 구현 (live gate가 execution approved일 때만) |
| `/done` | 완료 감사 |
| `/fsd-run-all` | 전체 chain autopilot dispatch |
| `/fsd-run-phase` | 단일 phase autopilot dispatch |
| `/fsd-status` | FSD 현재 상태 확인 |

OpenCode adapter는 의도적으로 phase primitive만 제공합니다. 세부 workflow(debugging, TDD, security review)는 설치된 `.agents/skills/**` pack에서 가져옵니다.

`.opencode/commands/execute.md`는 live gate가 execution approved 상태일 때만 사용합니다.

**OpenCode에서 버그 수정**:
```text
Use /discuss first.
Then use installed skills workflow-debugging,workflow-tdd.
Do not edit application code until the plan names allowed_paths and I approve execute.
```

### 8.3 Core-only (Adapter 없음)

Roo/OpenCode adapter 없이 `harness.py` CLI와 `AGENTS.md` 직접 사용.

### 클라이언트별 커맨드 모델

| 클라이언트 | Discuss | Plan | Execute | Done / audit |
| --- | --- | --- | --- | --- |
| Roo | `/phase-discuss` | `/phase-plan` | `/phase-execute` | `/done` |
| OpenCode | `/discuss` | `/plan` | `/execute` | `/done` |
| Generic agent | `AGENTS.md` 읽기 | plan docs 작성 | live gate 준수 | verification evidence 요약 |

Core-only에서 agent에게 직접 prompt:
```text
Read AGENTS.md first.
Then read .planning/STATE.md and .planning/ROADMAP.md.
Do not modify application code until we are in execute phase and I approve.
```

---

## 9. 점검 / Doctor / 검증

### 9.1 Check 명령

```bash
python3 scripts/harness.py check
```

감지 항목:
- 구조 오류, missing verification
- Managed block 누락
- 단계 경로 drift

```bash
python3 scripts/harness.py check --worktree
```

Staged/unstaged/untracked change가 `allowed_paths` 밖으로 나갔는지 확인. Exit 4로 차단.

### 9.2 Doctor 명령

```bash
python3 scripts/harness.py doctor
```

Warning으로 보고:
- 누락된 required reads
- 설치 manifest 불일치
- Workflow 품질 신호

### 9.3 Verify 명령

```bash
python3 scripts/harness.py verify --audit
```

Audit log chain integrity 전체 검증. §A3.4 참고.

### 9.4 Target-local 스크립트

설치된 target 안에서도 별도 스크립트로 점검 가능:

```bash
python3 scripts/check_harness.py
python3 scripts/doctor_harness.py
```

---

## 부록 A — Maintainer / Release Trust

## A1. 보안 모델

### A1.1 Trust Boundaries

| 경계 | 위치 | 내용 | 접근 |
| --- | --- | --- | --- |
| Out-of-project | `~/.harness/` | approval nonce, secret key, release trust root | harness CLI만 |
| Project-scoped install | `<target>/.harness/` | installed manifest, audit log, phase state | harness CLI + human |
| Agent workspace | `.planning/**`, `.roo/**`, `.opencode/**` | planning docs, adapter commands | agent + human |

### A1.2 Project-Scoped Agent 방어

**우회 불가** (project agent가 직접 우회할 수 없는 항목):
- `phase approve` (TTY-only + human presence proof)
- `phase autopilot start` (CI: OIDC/signed token 필수, TTY: human proof 필수)
- `phase reopen` (TTY-only)
- Nonce file (`~/.harness/approval-nonces/` — project scope 밖)
- Release tag signature verification (signed tag만 production upgrade 허용)

**우회 가능** (honest defense-in-depth 한계):
- `.planning/**`, `.scratch/**` 직접 편집 (다음 harness command가 state-audit consistency 검증)
- Git commit 직접 작성 (`harness verify --audit`가 forensic 기록)
- Network access (`phase autopilot --allow-network` flag로 명시적 opt-in, audit 기록)

### A1.3 Release-path HMAC Signing

> Release path 전용입니다. 일반 `phase approve`는 v0.9.0부터 HMAC을 사용하지 않습니다 (§0.1 참고).

Approval nonce는 HMAC으로 서명됩니다:
- Key: `~/.harness/secret.key` (0600 perms, 한 번만 생성)
- Signature: `minter_tty + consumer_tty + expires_at`로 계산
- Corruption 감지 시 자동 rotation (새 secret.key 생성, audit `verb=audit.secret_key.rotated`)

### A1.4 Signed Release Tags

Release tag는 maintainer의 SSH key로 서명됩니다 (§A2 참고). `harness upgrade`는 자동 검증. Dev 환경은 `--allow-unsigned-dev`로 bypass 가능하지만, 한 번 signed로 설치되면 downgrade 불가.

### A1.5 Audit Log Tamper Detection

Audit log는 두 가지 chain을 유지합니다:
- **State-content chain**: `before_sha256` / `after_sha256`로 state file 전환 증명
- **Entry chain**: 각 entry의 `entry_hash`와 `previous_entry_hash`로 log 무결성 확인

`harness verify --audit`는 전체 history(rotated files 포함)를 walk하여 chain integrity 검증. Partial edit, truncation, 또는 single-field rewrite를 감지합니다.

**한계**: Repo-local attacker가 모든 `audit.log*` + `.scratch/phase-state.json`을 rewrite하고 모든 `entry_hash`를 recompute할 수 있으면 우회 가능합니다. 이 threat class는 이 internal-only 도구의 threat model에서 명시적으로 제외됩니다 — out-of-repo audit-tip anchor는 v0.9.3에서 제거되었습니다 (ADR `2026-05-20-remove-audit-tip-anchor.md` 참고).

---

## A2. Release Trust

### A2.1 allowed-signers 파일

`docs/trust/allowed-signers`는 OpenSSH format 허용 목록:

```
release@harness namespaces="git" ssh-ed25519 AAAA... maintainer@example.com
```

각 line은 release engineer의 SSH public key를 authorize합니다.

### A2.2 New Signer 추가

1. Maintainer의 SSH public key 얻기: `cat ~/.ssh/id_ed25519.pub`
2. Fingerprint out-of-band 검증: `ssh-keygen -lf <pubkey-file>`
3. `docs/trust/allowed-signers`에 line 추가
4. Main으로 commit & push

### A2.3 Release Tag 서명 (Maintainer)

```bash
git config user.signingKey ~/.ssh/id_ed25519
git config gpg.format ssh
git tag -s v0.9.7 -m "Release v0.9.7"
git push origin v0.9.7
```

Git ≥ 2.34 필요 (Windows: Git for Windows 포함).

### A2.4 Tag 검증 (Consumer)

`harness upgrade`는 자동 검증. 수동 검증:

```bash
git -c gpg.ssh.allowedSignersFile=docs/trust/allowed-signers verify-tag v0.9.7
```

### A2.5 Trust-Downgrade Refusal

한 번 signed tag로 설치되면, `--allow-unsigned-dev`로도 unsigned로 downgrade 불가능합니다. 대신:
- Properly signed release tag로 업그레이드, 또는
- Target 재설치

---

## A3. 감사 로그

### A3.1 위치 및 형식

`.harness/audit.log` (JSON Lines). 각 entry:

```json
{
  "verb": "phase.approve",
  "at": "2026-05-17T14:30:15Z",
  "by_email": "alice@company.com",
  "by_source": "gitconfig_auto",
  "confirmation_kind": "human_cli",
  "approved_at": "2026-05-17T14:30:15Z",
  "schema_version": 2,
  "seq": 1,
  "seq_global": 10,
  "previous_entry_hash": "000...",
  "entry_hash": "abc..."
}
```

### A3.2 주요 Verb 레지스트리

**Phase Lifecycle**:
- `phase.set` — phase 전환
- `phase.approve` — execute 승인
- `phase.reopen` — 회귀 및 approval reset

**Autopilot**:
- `phase.autopilot.start` — autopilot 시작
- `phase.autopilot.stop` — autopilot 중단
- `phase.autopilot.halt` — halt (budget, fence, 기타)

**Audit Infrastructure**:
- `audit.rotated` — log 회전
- `audit.repair` — 복구 action
- `audit.secret_key.rotated` — secret key 손상 및 rotation

**Approval**:
- `approve_nonce.mint` — release-path confirmation token mint (phase.approve audience는 v0.9.0부터 no-op)

**Network/Fence**:
- `autopilot.fence.deny` — 파일 제한으로 인한 거절
- `autopilot.network.deny` — network deny로 인한 거절

**Release**:
- `release.trust.verified` — signed tag 검증 성공
- `release.trust.bypassed` — `HARNESS_ALLOW_UNSIGNED_DEV=1` bypass 사용
- `release.trust.refused` — downgrade 또는 서명 오류로 거절

**CI/OIDC**:
- `ci.oidc.jti.consumed` — OIDC JTI token 소비
- `ci.oidc.jti.replay` — JTI replay 감지
- `ci.oidc.jti.store_rotated` — corrupted JTI store 회전

**Session**:
- `session.unlock` — session lock 해제
- `lock.recovered` — stale lock 복구
- `cli.deprecated_flag` — deprecated flag 사용

**Migration**:
- `migrate.state_v2` — v0.6 automation_mode → v0.7 execution_mode 마이그레이션

### A3.3 Strict Verb Registry Mode

```bash
HARNESS_STRICT_VERB_REGISTRY=1 python3 scripts/harness.py ...
```

`1`로 설정하면, 등록되지 않은 verb는 exit 10으로 거절됩니다. 기본값(permissive)은 unknown verb를 warning으로만 보고하고 진행합니다.

### A3.4 Chain Integrity 검증

```bash
python3 scripts/harness.py verify --audit
```

모든 rotated files를 walk하여:
- `seq_global` 중복/gap 감지
- `previous_entry_hash` rotation seam에서 일치 확인
- 마지막 entry의 `entry_hash`가 journal recorded tip과 일치 확인

Failure → exit 10 (audit chain failure).

---

## A4. Release Confirmation

`harness release`를 실행할 때, 하네스는 사용자가 직접 타이핑한 토큰으로 확인을 받습니다. 일반 `phase approve`의 `[y/N]` 방지턱(§0.1)보다 한 단계 엄격한 단계입니다.

### A4.1 사용 흐름

1. 터미널에서 `python3 scripts/harness.py release v0.9.7` 실행
2. 하네스가 묻습니다: `Type 'release v0.9.7' to confirm:`
3. 정확히 `release v0.9.7`를 타이핑하고 Enter

다른 답 (`y`, Ctrl+C, 다른 문자열)은 cancel로 처리되고 release는 진행되지 않습니다.

### A4.2 왜 이 단계가 있는가

`release`는 git tag 생성, push, GitHub release 등 외부에 영향을 주는 작업입니다. 근육 기억으로 `y`를 누르는 사고를 막기 위해 토큰 타이핑을 요구합니다. 내부적으로는 HMAC mechanism(`approval nonce`)이 동작하지만, 사용자가 보는 용어는 "release confirmation"입니다.

### A4.3 비-TTY 환경

CI 환경에서는 별도의 trust path (`HARNESS_BY_TRUST` + OIDC)를 사용합니다. 자세한 내용은 §C2.2 참고.

---

## 부록 B — Troubleshooting & Advanced CLI

## B1. 트러블슈팅

### B1.1 "tag_signature_invalid" / "trust_downgrade_refused"

**원인**:
- Unsigned release tag로 업그레이드 시도 (production install이 이미 signed로 설치됨)
- `allowed-signers`의 signer public key가 outdated/missing

**해결**:
1. `docs/trust/allowed-signers` 확인 (signer key 최신인지)
2. Properly signed release tag로 upgrade:
   ```bash
   git verify-tag v0.9.7
   python3 scripts/harness.py upgrade --target /path/to/project
   ```
3. Dev 환경이면 `--allow-unsigned-dev` 사용 (처음 설치만)

### B1.2 "audit_partial_write" (exit 14)

**원인**: Power loss 또는 crash 사이 crash recovery 불확실성. State + audit transaction이 diverged.

**해결**: `harness session unlock --force` 실행 후 상태 재점검.

### B1.3 "release confirmation expired"

**원인**: `harness release` 실행 시 토큰을 너무 늦게 타이핑함 (내부 expiry 초과).

**해결**: `harness release <version>` 다시 실행. 토큰을 바로 타이핑.

### B1.4 "phase approve requires a terminal"

**원인**: `phase approve`를 agent subprocess, redirected stdin, 또는 CI 환경 등 TTY가 아닌 곳에서 실행함.

**해결**: 본인 터미널에서 `python3 scripts/harness.py phase approve` 직접 실행. `[y/N]` 프롬프트에 `y` 응답.

### B1.5 "non_tty_authorization_unverified"

**원인**: Non-TTY에서 `phase autopilot start` 시도, CI 환경 증명 없음.

**해결**:
- GitHub Actions: `GITHUB_ACTIONS=true`, `ACTIONS_ID_TOKEN_REQUEST_URL`, OIDC token 설정
- GitLab CI: `GITLAB_CI=true`, `CI_JOB_JWT_V2` token 설정
- Buildkite: `BUILDKITE=true`, Buildkite OIDC token 설정
- CI가 아닌 경우 TTY에서 `phase approve` 직접 실행 (`[y/N]` 응답으로 워크플로우 체크포인트 통과)

### B1.6 "scope_violation" / "path_reparse_refused" (exit 4)

**원인**:
- Approved `allowed_paths` 밖 file 수정
- Windows: reparse point(symlink, junction) 또는 reserved chars(`:`, `|`)

**해결**:
- `harness.py check --worktree` 실행, 위반 경로 확인
- Phase plan으로 돌아가 `allowed_paths` 수정
- Windows: `$Profile` 내 `.harness\autopilot_guard.ps1` wire 확인

### B1.7 "managed block missing" (warning)

**원인**: `.planning/ROADMAP.md` 또는 `.planning/STATE.md`에 managed marker block 누락.

**해결**: 메시지의 command 실행:
```bash
python3 scripts/harness.py state repair
```

### B1.8 "cli_bot_identity_overlaps_human_approver"

**원인**: `HARNESS_BY_TRUST` (bot identity)이 `.harness/install-record.json`의 approvers[] entry와 동일.

**해결**: CI bot identity 변경 또는 install-record approvers 재확인:
```bash
cat .harness/installed-manifest.json | grep approvers
```

### B1.9 State projection 불일치

**원인**: `state show`와 실제 파일 내용이 다를 때.

**해결**:
```bash
python3 scripts/harness.py state repair
python3 scripts/harness.py state show
```

`state repair`가 해결하지 못하면, git log로 파일 변경 이력 확인 후 `git revert`를 검토하세요.

### B1.10 Python 명령 미발견 (Windows)

**원인**: Python Launcher 미설치 또는 PATH 미설정.

**해결**:
- `py -3 --version` 확인
- `python3`이 없으면 `python` 또는 `py -3` 사용
- `scripts/codex-cloud-setup.sh`는 Linux/macOS 전용 — Windows에서는 `harness.py` 직접 사용

### B1.11 자주 혼동하는 케이스 (Common Confusions)

**Q. Approval 했는데 왜 execute로 못 들어가나요?**
**A.** `harness phase approve`만으로 충분합니다. 터미널에서 실행하면 `[y/N]` 프롬프트가 뜨고 `y` 입력 후 현재 phase가 approve로 stamp되고, `phase set <next>`로 다음 phase로 이동할 수 있습니다. 별도의 `approve-nonce mint` 명령은 v0.9.0부터 필요 없습니다 (release는 별개, §A4 참고).

**Q. Skill pack을 설치 후에 추가하려면?**
A. `harness state show`로 현재 installed packs 확인 후, 원하는 전체 packs를 `--packs`로 명시해 upgrade:
```bash
python3 scripts/upgrade_harness.py --target <target> --packs workflow-core,workflow-debugging,workflow-tdd
```
`--packs`는 "추가"가 아닌 "전체 교체"이므로 기존 packs를 포함시켜야 합니다. (§5, §B2.5)

**Q. Phase를 한 단계 뒤로 돌릴 수 있나요?**
A. `harness phase reopen --to plan`. 현재 phase에서 plan으로 되돌리며 approval 초기화. audit log에 기록되니 실수가 아니면 새 plan을 다시 세우는 편이 안전합니다. (§C2.4)

**Q. `requires_human` (exit 17)이 뜨는데 무엇을 해야 하나요?**
A. autopilot 중 human approval이 필요한 시점에 도달했다는 신호. TTY에서 `python3 scripts/harness.py phase approve` 직접 실행 후 `[y/N]` 프롬프트에 `y` 응답. autopilot 재시작. (§B3, §A4)

**Q. Source repo와 installed target을 헷갈립니다.**
A. `harness/skill-packs/**`가 source — clone한 곳에 존재. `.agents/skills/**`는 install이 만들어낸 target artifact. Source repo에 `.agents/skills/`가 없는 것이 정상. (§4 ownership 규칙)

**Q. Roo와 OpenCode adapter를 동시에 깔면 둘 중 무엇이 우선인가요?**
A. Adapter는 entry-point에 불과하며 phase gate state는 공유. 두 adapter 모두 같은 `.scratch/phase-state.json`을 본다. 충돌 시 마지막 mutation이 audit log에 기록됨. (§8)

**Q. Autopilot이 시작 안 됩니다 — "no human presence proof"?**
A. CI: `HARNESS_BY_TRUST` + OIDC 토큰 필요. TTY: `python3 scripts/harness.py phase approve` 실행 후 `[y/N]` 프롬프트에 `y` 응답 후 시작. Dev에서 임시로 우회하려면 `HARNESS_ALLOW_UNSIGNED_DEV=1` (production 금지). (§C2.2, §C1)

---

## B2. CLI 명령 레퍼런스 (Advanced)

> ⚠️ 이하 명령은 advanced/debug/CI용입니다. 일상 사용은 §2.0의 4개 명령으로 충분합니다. `HARNESS_ADVANCED=1`을 설정해야 도움말에 표시됩니다.

### B2.1 Phase Lifecycle

| 명령 | 설명 | 핵심 옵션 |
| --- | --- | --- |
| `phase set <phase>` | 새 phase로 전환 | `--by <email>` identity override |
| `phase approve` | 현재 phase에 `approved=true` 스탬프 (실제 phase 이동은 `phase set`이 수행) | `--by <email>`, `--at <iso>` |
| `phase reopen --to discuss\|plan --reason <text>` | Phase 회귀, approval 리셋 | `--by <email>` |
| `phase autopilot start --phase <slug>` | Autopilot 시작 (phase 또는 chain) | `--allow-network`, `--mode phase\|chain` |
| `phase autopilot stop` | Autopilot 중단, manual로 복귀 | (TTY-only) |
| `phase next-pending` | 다음 non-done roadmap phase slug 출력 | (pure read) |

**사용 예시**:
```bash
python3 scripts/harness.py phase set discuss
python3 scripts/harness.py phase set plan --by alice@company.com
python3 scripts/harness.py phase approve
python3 scripts/harness.py phase reopen --to plan --reason "scope 추가"
```

### B2.2 Approve-Nonce (Deprecated)

> **v0.9.0에서 deprecated**. `--audience phase.approve`는 no-op + stderr warning. v1.0에서 제거.
> phase.approve는 이제 interactive `[y/N]` (§0.1 참고). Release path 내부에서는 여전히 사용되지만 사용자가 직접 호출할 일은 없음.

내부 release-path 디버깅 용도로 남아 있는 verb (감사 로그 분석 시 참고):

```bash
python3 scripts/harness.py approve-nonce mint --audience release.publish [--ttl 120]
```

### B2.3 상태 및 조회

| 명령 | 설명 |
| --- | --- |
| `state show` | 현재 phase, execution mode, active checkpoint 표시 |
| `state show --format json` | JSON 형식 출력 |
| `state repair` | 깨진 managed block 또는 누락된 marker 복구 |
| `status` | Autopilot halt diary 및 suggested next command 표시 |
| `next` | Current position에서 승인된 다음 step 제안 |
| `verify --audit` | Audit log chain integrity 검증 |

### B2.3a 중단된 설치 복구 (v0.9.7+)

`harness init` 또는 `harness upgrade` 도중 프로세스가 비정상 종료된 경우(SIGTERM, 전원 끊김, Ctrl-C 등), 재실행 전에 복구 명령을 실행하세요.

```bash
python3 scripts/harness.py state repair
```

**Exit codes:**

| Exit code | 의미 |
| --- | --- |
| `0` | 정상 완료 또는 복구 불필요 (no-op) |
| `1` | 부분 복구 — `.harness/conflicts/` 에 격리된 파일 있음; 수동 확인 필요 |
| `2` | 치명적 오류 — 복구 자체가 실패 |

**성공 출력 예시 (sentinel-finalize):**

```
harness state repair
recovered: finalized pending manifest (runid=12345-20260521T100000Z-abc123, version=0.9.7)
exit code 0
```

**실패 출력 예시 (orphan-pending, rc=1):**

```
harness state repair
warning: quarantined orphan pending manifest to .harness/conflicts/installed-manifest.json.pending-99999-...
[Orphaned pending manifest quarantined; check .harness/conflicts/ for manual review]
exit code 1
```

rc=1 일 때 `.harness/conflicts/` 안을 확인하고 필요시 파일을 수동으로 복구하세요.

**stale 설치 감지:**

`harness check` 명령이 `.harness/` 안에서 600초(10분) 이상 방치된 staging 디렉토리를 감지하면 경고를 출력합니다:

```
warning: 중단된 설치 감지 (runid=99999-20260521T100000Z-abcdef, age=1200s). 복구: python3 scripts/harness.py state repair [Aborted install detected; recover with state repair]
```

이 경우 `state repair` 를 실행하세요.

### B2.4 Session Lock

| 명령 | 설명 |
| --- | --- |
| `session unlock` | 잠긴 session 해제 (recovery; live owner는 보호됨) |
| `session unlock --force` | Stale/ambiguous lock 강제 정리 (수동 검토 후에만) |

### B2.5 릴리스 및 진단

| 명령 | 설명 |
| --- | --- |
| `check` | 설치된 harness 구조 검증 |
| `check --worktree` | Staged/unstaged/untracked changes가 approved paths 내인지 확인 |
| `doctor` | Workflow 품질 신호 진단 |
| `release-check --expected-version v0.9.7` | Release tag 버전 검증 |

### B2.6 FSD (Fast Slash-command Dispatch)

Adapter Markdown command wrapper로서, 주로 adapter 내에서 호출됩니다.

```bash
python3 scripts/harness.py fsd-run-phase --slug discuss
python3 scripts/harness.py fsd-run-all
```

사용자는 일반적으로 `.roo/commands/` 또는 `.opencode/commands/`를 통해 간접 호출합니다.

### B2.7 Anchor (removed in v0.9.3)

`harness anchor` 서브커맨드는 v0.9.3에서 제거되었습니다. Out-of-repo audit-tip anchor 기능 전체가 삭제되었으며, 기존 `~/.harness/audit-tip/<id>.json` 파일은 무시됩니다(자동 삭제 없음; 원하는 경우 수동 삭제 가능). 자세한 내용은 ADR `docs/adr/2026-05-20-remove-audit-tip-anchor.md` 참고.

### B2.8 Halt Diary Admin

```bash
python3 scripts/harness.py halt-diary clear   # 현재 halt 기록을 acknowledged 처리
```

Halt 상세 내용 확인은 `python3 scripts/harness.py state show`의 `last_halt` 섹션을 참고하세요. (`halt-diary show` 서브명령은 v0.7.0에 없습니다 — v0.8.0 검토.)

### B2.9 Migration

```bash
python3 scripts/harness.py migrate state --forward    # v0.6 → v0.7 schema 전진 이행
python3 scripts/harness.py migrate state --reverse    # v0.7 → v0.6 (필요 시)
python3 scripts/harness.py migrate state --resume     # 중단된 migration 재개
```

v0.6 `automation_mode` → v0.7 `execution_mode` 마이그레이션은 phase command 진입 시 자동 실행되며, 수동 trigger가 필요한 경우 위 명령을 사용합니다. (이전 문서의 `migrate --target` 시그니처는 잘못된 표기였으며 실제 CLI에는 존재하지 않습니다.)

---

## B3. Exit Codes

`scripts/lib/exitcodes.py` 기준. `sub_reason` 필드는 exit code의 정확한 원인 식별.

| Code | 이름 | 의미 |
| --- | --- | --- |
| 0 | `EXIT_OK` | 성공 |
| 1 | `EXIT_OPERATIONAL` | 일반 실패 (e.g. file not found) |
| 2 | `EXIT_INVALID_TRANSITION` | Bad CLI argument |
| 3 | `EXIT_SESSION_LOCKED` | State lock 경합 또는 recovery 필요 |
| 4 | `EXIT_SCOPE_VIOLATION` | Approved path 밖 change 또는 path reparse refusal (Windows) |
| 5 | `EXIT_UNPARSEABLE_JSON` | BOM 포함 또는 CRLF violation JSON |
| 6 | `EXIT_WRONG_PHASE_FOR_VERB` | Phase-verb mismatch 또는 nonce signature invalid |
| 7 | `EXIT_STALE_UNCERTAIN` | State timestamp 불확실성 (recovery 필요) |
| 8 | `EXIT_TIMESTAMP_OUT_OF_RANGE` | Approval timestamp 범위 초과 |
| 9 | `EXIT_AUTOPILOT_BUDGET_EXHAUSTED` | Autopilot budget (대화 turn/시간) 소진 |
| 10 | (audit chain) | Audit log chain integrity failure |
| 11 | `EXIT_WINDOWS_CONTAINMENT_DEGRADED` | Windows ADS/reserved-char containment error |
| 14 | `EXIT_AUDIT_PARTIAL_WRITE` | Crash recovery undecidable (manual action required) |
| 15 | `EXIT_RELEASE_TRUST_INVALID` | Signed tag verification 실패 또는 trust downgrade refused |
| 17 | (`next --shell`, `phase approve`) | `requires_human` (autopilot 진입 차단) 또는 `non_tty_approval_blocked` (phase approve 비-TTY halt). `sub_reason`으로 구분. |
| 18 | (`next --shell`) | autopilot active — 재진입 금지 (§C2.2) |

**중요**: `sub_reason` 필드를 검토하여 정확한 원인 파악. 같은 exit code가 여러 상황에서 사용됩니다.

---

---

## 부록 C — CI / 자동화

## C1. 고급 설정 flag

하네스 내부 설정 flag(`HARNESS_*`)는 [`docs/advanced/harness-flags.md`](../advanced/harness-flags.md)를 참고하세요. 일반 사용자는 건드릴 일 없습니다.

---

## C2. Phase Gate 상세 (Autopilot)

### C2.1 Live Gate: .scratch/phase-state.json

`.scratch/phase-state.json`은 현재 작업을 열거나 막는 live gate입니다. 직접 편집하지 마세요. harness CLI만 이 파일을 수정합니다.

주요 필드:
- `current_phase`: 현재 phase slug
- `execution_mode`: `manual` / `phase_autopilot` / `chain_autopilot`
- `approved`: boolean (execute 진입 허용 여부)

### C2.2 Execution Mode와 Autopilot

| Mode | 의미 | 사용 조건 |
| --- | --- | --- |
| `manual` (기본) | human이 `harness phase set` 명령 직접 실행 | 일반 작업 |
| `phase_autopilot` | agent가 phase 범위 내에서 단계별 진행 | human approval 여전히 필요 |
| `chain_autopilot` | agent가 phase sequence 전체 진행 | CI + OIDC 또는 TTY human proof |

```bash
python3 scripts/harness.py phase autopilot start --phase <slug>
python3 scripts/harness.py phase autopilot start --phase <slug> --mode chain
python3 scripts/harness.py phase autopilot stop
```

`phase autopilot start`는:
- CI 환경: OIDC 또는 환경 변수로 증명된 bot identity 요구
- TTY 환경: `phase approve`의 `[y/N]` 프롬프트에 응답하면 됩니다 (speed-bump 체크포인트). 강한 human-proof는 v0.9.0에서 release path 전용입니다.

**위험과 사용 기준**: Autopilot은 승인된 scope 내에서만 동작하지만, 연속 실행 중 예상치 못한 변경이 발생할 수 있습니다. 중요한 변경 전에는 `manual` 모드를 유지하세요.

### C2.3 Halt Diary

Autopilot이 중단되면(budget exhausted, fence deny, halt 명령):

```bash
python3 scripts/harness.py status          # halt diary + suggested next command 확인
python3 scripts/harness.py next            # 승인된 다음 step 제안
python3 scripts/harness.py halt-diary clear   # diary 초기화
```

`last_halt.suggested_next_command_requires_human`이 true이면 human이 직접 실행해야 합니다.

### C2.4 Worktree Check

Phase execute 중 approved paths 밖으로 change가 나갔는지 확인:

```bash
python3 scripts/harness.py check --worktree
```

Staged/unstaged/untracked change가 `allowed_paths` 밖으로 나갔으면 exit 4로 차단합니다.

---

## C3. 업그레이드

### C3.1 새 source checkout에서 target upgrade

```bash
python3 /path/to/newer-harness/scripts/harness.py upgrade --target /path/to/project --dry-run
python3 /path/to/newer-harness/scripts/harness.py upgrade --target /path/to/project
python3 /path/to/project/scripts/harness.py check
```

새 버전으로 upgrade하면 공용 workflow 정적 검사 helper인 `scripts/lib/workflow_static_checks.py`도 target에 설치됩니다.

### C3.2 Installed target bootstrapper로 upgrade

```bash
python3 scripts/upgrade_harness.py --version v0.9.7 --dry-run
python3 scripts/upgrade_harness.py --version v0.9.7
python3 scripts/check_harness.py
python3 scripts/doctor_harness.py
```

Install state에 git source provenance가 있으면 bootstrapper는 그 repo를 기본값으로 씁니다. 사내 mirror에서 설치한 target은 별도 지정 없이도 같은 mirror에서 upgrade됩니다.

### C3.3 사내/외부 repo 명시 override

```bash
python3 scripts/upgrade_harness.py \
  --repo https://github.com/hjung3113/general-low-reasoning-agent-harness.git \
  --version v0.9.7 \
  --dry-run
```

### C3.4 Remote access 막힌 경우 local source fallback

```bash
python3 scripts/upgrade_harness.py --source /path/to/newer-harness --version v0.9.7 --dry-run
```

### C3.5 오래된 수동 설치 adopt

Target에 harness file은 있지만 `.harness/installed-manifest.json`이 없으면 adopt 후 upgrade:

```bash
python3 /path/to/newer-harness/scripts/harness.py upgrade \
  --target "/path/to/manual project" \
  --adopt-existing \
  --adapters roo \
  --profiles generic \
  --packs workflow-core
```

Conflict는 `.harness/conflicts/` 아래에 기록됩니다. 검토 전에는 `--force`를 쓰지 않습니다.

### C3.6 --allow-unsigned-dev 플래그

Dev 환경에서 서명되지 않은 tag로부터 설치할 때:

```bash
HARNESS_ALLOW_UNSIGNED_DEV=1 python3 scripts/harness.py upgrade --target /path/to/project
# 또는
python3 scripts/harness.py upgrade --target /path/to/project --allow-unsigned-dev
```

**주의**: 한 번 `trust_origin: signed_tag`로 설치되면, 이 플래그로 다시 unsigned로 downgrade할 수 없습니다. 반드시 properly signed release tag로 업그레이드하거나 재설치해야 합니다.

---

## C4. Windows 지원

### C4.1 요구사항

- **Git for Windows ≥ 2.34**: SSH-signed-tag 검증을 위해 필요
- **Python 3**: `py -3`, `python`, 또는 Python Launcher
- **PowerShell 5.1+** 또는 **pwsh 7+**: autopilot deny-shim 실행

### C4.2 safe_open (Production Write)

Production write는 Windows CreateFileW를 사용합니다:
- Handle-bound reparse-point refusal: 열린 handle을 통해 junction/symlink 확인 및 거절
- ADS (Alternate Data Stream) 거절: `:`, `::$DATA` 같은 component 금지
- Case-fold containment: path normalization으로 case mismatch로 인한 escape 방지

Exit code 4 (`path_reparse_refused`) 또는 11 (`windows_containment_degraded`)이 emit됩니다.

### C4.3 PowerShell Deny-Shim

`autopilot_guard.ps1`은 network deny, file fence를 PowerShell에서 강제합니다. `$PROFILE`에 wire:

```powershell
$HarnessProjectRoot = "C:\path\to\project"
& "$HarnessProjectRoot\.harness\autopilot_guard.ps1"
```

`HARNESS_PROJECT_ROOT` env로 audit path 지정. 단, PowerShell 외 Bash/shell 명령은 이 shim을 우회할 수 있습니다. Phase gate는 여전히 적용됩니다.

### C4.4 LOCALAPPDATA 체크

Windows에서 `LOCALAPPDATA` unset 시 **release-path** approval-nonces 저장 경로 부재로 warning 또는 error 발생합니다. 일반적으로 Windows login session에서는 자동 설정되지만, minimal CI환경이면 수동 설정 필요:

```powershell
$env:LOCALAPPDATA = "$env:UserProfile\AppData\Local"
```

### C4.5 지원 환경과 명령 표기

`scripts/codex-cloud-setup.sh`는 Linux/macOS shell용입니다. Windows에서는 `harness.py` 명령(init, check, doctor)을 직접 사용하세요.

| 작업 | Linux/macOS | Windows PowerShell |
| --- | --- | --- |
| harness check | `python3 scripts/harness.py check` | `py -3 scripts/harness.py check` |
| 단위 테스트 | `python3 -m unittest scripts/test_harness.py` | `py -3 -m unittest scripts/test_harness.py` |
| smoke | `python3 scripts/release_smoke_test.py` | `py -3 scripts/release_smoke_test.py` |

PowerShell temp install 예시:

```powershell
$tmp = New-Item -ItemType Directory -Path ([System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), [System.Guid]::NewGuid()))
git clone --depth 1 --branch v0.9.7 https://github.com/hjung3113/general-low-reasoning-agent-harness.git $tmp.FullName
py -3 "$($tmp.FullName)\scripts\install_harness.py" --interactive
```

---

---

## 부록 D — 기타

## D1. Carryover

다음 메이저 버전에 deferred된 항목:

1. **Explicit revoked_keys file**: v0.7 제약(propagation 지연). v0.9에서 revoked_keys 병렬 consulted, immediate revocation.
2. **Signed external audit anchor**: Repo-local attacker 대항 (v0.7 honest defense-in-depth 한계). — **v0.9.3에서 제거됨**: threat class가 internal-only 도구의 scope 밖으로 재분류됨. ADR `2026-05-20-remove-audit-tip-anchor.md` 참고.
3. **Advisory raw-tool budget enforcement**: v0.7은 `cli_budgets_remaining` hard-stop(harness subprocesses만), raw tools(Bash, Edit) advisory-only. v0.9에서 hook enforcement.
4. **Cross-machine collaboration**: v0.7은 single-user, single-machine. Multi-user lock contention, distributed state sync 미지원.

---

## D2. 참고 자료

- [README.md](../README.md) — harness source, 설치 패턴, 개발자 가이드
- [CHANGELOG.md](../CHANGELOG.md) — 릴리스 노트
- [docs/trust/README.md](../docs/trust/README.md) — release tag signing, allowed-signers 설정
- [docs/phase-gate-harness.md](../docs/phase-gate-harness.md) — phase gate 개념 + ROADMAP/STATE 구조
- [docs/protocol-spec.md](../docs/protocol-spec.md) — core protocol 레퍼런스
- [docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md](../docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md) — §3(phase commands), §6(release trust), §12(exit codes, audit verbs)
- [scripts/lib/exitcodes.py](../scripts/lib/exitcodes.py) — canonical exit-code constants
- [scripts/lib/audit.py](../scripts/lib/audit.py) — KNOWN_VERBS registry
