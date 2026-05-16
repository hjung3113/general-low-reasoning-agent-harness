# 범용 저추론 에이전트 하네스

저추론 코딩 에이전트가 실제 저장소에서 안전하게 일하도록 만드는 재사용 가능한 하네스입니다. 명시적인 planning state, phase gate, adapter command, workflow skill, verification contract를 target repository에 설치합니다.

이 README는 [mattpocock/skills README](https://github.com/mattpocock/skills/blob/main/README.md)의 “빠른 시작 -> 왜 필요한가 -> 상세 레퍼런스” 흐름을 참고했습니다. 다만 이 저장소는 단순 skill 모음이 아니라, target repository에 규칙/명령/스크립트/계획 문서/skill pack을 배포하는 harness source입니다.

## 목차

- [빠른 시작](#빠른-시작)
- [이 하네스가 하는 일](#이-하네스가-하는-일)
- [왜 필요한가](#왜-필요한가)
- [핵심 모델](#핵심-모델)
- [사용 시나리오 빠른 선택](#사용-시나리오-빠른-선택)
- [설치 패턴](#설치-패턴)
- [설치 후 첫 작업](#설치-후-첫-작업)
- [워크플로우 모델](#워크플로우-모델)
- [클라이언트별 커맨드 모델](#클라이언트별-커맨드-모델)
- [스킬 팩](#스킬-팩)
- [프롬프트 레시피](#프롬프트-레시피)
- [점검, Doctor, 검증](#점검-doctor-검증)
- [업그레이드](#업그레이드)
- [플랫폼별 참고사항](#플랫폼별-참고사항)
- [레퍼런스](#레퍼런스)

## 빠른 시작

### source repo를 직접 열지 않고 원격에서 설치

하네스 source가 GitHub, GitHub Enterprise, GitLab, Bitbucket, 사내 git host 어디에 있든 같은 방식으로 설치합니다. `{Repo git}`은 각 환경의 harness repository git URL입니다. public repo와 사내 mirror를 혼동하지 않도록 문서에는 구체 repo명을 쓰지 않습니다.

```bash
tmp="$(mktemp -d)"
git clone --depth 1 --branch v0.6.0 {Repo git} "$tmp"
python3 "$tmp/scripts/install_harness.py" --interactive
```

또는 Python 실행명이 `python`인 환경에서는:

```bash
tmp="$(mktemp -d)"
git clone --depth 1 --branch v0.6.0 {Repo git} "$tmp"
python "$tmp/scripts/install_harness.py" --interactive
```

interactive installer는 absolute path인 existing target directory를 받은 뒤 adapter와 installer-only profile preset을 번호/이름으로 선택하게 합니다. relative path나 존재하지 않는 path를 입력하면 경고하고 다시 묻습니다. preset을 고르면 기본 포함 skill pack을 먼저 보여주고, 이미 포함된 pack을 제외한 추가 skill pack만 더 선택하게 합니다. 이 checkout의 git source provenance가 target의 `.harness/installed-manifest.json`에 기록되므로, 이후 upgrade는 같은 public repo 또는 사내 mirror를 기본값으로 사용합니다.

### 이미 checkout한 source에서 바로 설치

```bash
python3 scripts/harness.py init --target /path/to/project
```

또는:

```bash
python scripts/harness.py init --target /path/to/project
```

기본 설치 내용:

- core planning skeleton
- Roo adapter
- generic profile
- `workflow-core` skill pack

Interactive profile presets are installer-only UX presets. They map to existing manifest profiles and skill packs; they are not valid values for `scripts/harness.py init --profiles`.

- `minimal`: stack-neutral planning guardrails plus `workflow-core`.
- `dotnet-etl`: .NET/C# ETL packs without assuming a database engine.
- `python-etl`: Python ETL/data pipeline packs.
- `react-tailwind-typescript-web`: React, TypeScript, Tailwind, and web workflow packs.
- `full`: all shipped skill packs; adapters are still selected separately.

### 빠른 검증

```bash
python3 scripts/harness.py check
python3 scripts/harness.py doctor
```

또는:

```bash
python scripts/harness.py check
python scripts/harness.py doctor
```

## 이 하네스가 하는 일

이 저장소는 generalized low-reasoning agent harness source입니다. Target project에 작은 protocol을 설치해서 에이전트가 다음을 지키게 합니다.

- 작업 전에 durable planning state를 읽습니다.
- 논의, 계획, 실행, 완료 감사를 분리합니다.
- 명시적 execute 승인 전에는 application code를 수정하지 않습니다.
- 하나의 거대한 prompt 대신 task에 맞는 workflow skill을 조합합니다.
- target repository에 실제로 존재하는 명령으로 검증합니다.

Core protocol은 client-neutral, stack-neutral입니다. Roo와 OpenCode는 adapter이지 source of truth가 아닙니다.

## 왜 필요한가

### 문제 1: 에이전트가 합의 전에 바로 코딩한다

에이전트는 모호한 요청을 받으면 바로 source edit로 뛰어들기 쉽습니다. 이 하네스는 `discuss -> plan -> execute -> done` 흐름을 강제해 alignment와 mutation을 분리합니다.

### 문제 2: 에이전트가 중요한 맥락을 잊는다

`.planning/**`은 canonical memory입니다. 프로젝트 구조, stack, convention, roadmap, phase plan, verification evidence, decision을 기록합니다. 매번 처음부터 추론하지 않아도 됩니다.

### 문제 3: 승인된 범위 밖을 수정한다

`.scratch/phase-state.json`은 현재 작업을 열거나 막는 live gate일 뿐입니다. 현재 phase가 execute 가능한지, 어떤 path가 allowed인지 확인합니다. `python3 scripts/harness.py check --worktree`는 staged, unstaged, untracked change가 approved path 밖으로 나갔는지 잡습니다.

### 문제 4: 모든 작업을 하나의 workflow로 처리하려 한다

skill pack은 플러그인입니다. Core는 작게 유지하고, debugging, TDD, code review, security review, ETL, React, TypeScript, MSSQL 같은 skill은 필요한 target에만 설치합니다.

## 핵심 모델

하네스는 네 계층으로 나뉩니다.

- **Core protocol**: `.planning/**`, `.scratch/phase-state.json`, checks, doctor, dashboard, AGENTS guidance.
- **Adapters**: `.roo/**`, `.opencode/**`, client-specific command surfaces.
- **Profiles**: `generic`, `dotnet-etl-mssql` 같은 확인된 project environment.
- **Skill packs**: `.agents/skills/**` 아래에 설치되는 composable workflow/tech skills.

중요한 ownership rule: source repository에는 `.agents/skills/**`가 없어도 정상입니다. Source에는 `harness/skill-packs/**`가 있고, target install 시 선택한 pack만 `.agents/skills/**`로 복사됩니다.

## 사용 시나리오 빠른 선택

| 목적 | 추천 설치 | 명령 | 시작 프롬프트 |
| --- | --- | --- | --- |
| 새 프로젝트에 기본 가드레일만 넣기 | 기본 Roo 또는 `--adapters roo` | `python3 scripts/harness.py init --target /path/to/project` | "아직 구현하지 말고 planning hydration만 해줘." |
| core-only 하네스 | adapter 없음 | `python3 scripts/harness.py init --target /path/to/project --adapters none` | "core planning docs만 만들고 adapter command는 설치하지 마." |
| OpenCode만 쓰기 | OpenCode adapter | `python3 scripts/harness.py init --target /path/to/project --adapters opencode` | "OpenCode discuss command 순서대로 읽고 phase 후보만 제안해." |
| Roo + OpenCode 동시 지원 | both adapters | `python3 scripts/harness.py init --target /path/to/project --adapters both` | "Roo/OpenCode 모두 같은 `.planning/**`과 live gate를 쓰는지 확인해." |
| .NET ETL | installer preset `dotnet-etl` | `python3 scripts/install_harness.py --interactive` | ".NET ETL restart/idempotency와 TDD 검증 계획을 세워줘." |
| Python ETL | installer preset `python-etl` | `python3 scripts/install_harness.py --interactive` | "Python 데이터 파이프라인의 입력/변환/재시작 검증 계획을 세워줘." |
| React/Tailwind/TypeScript web app | installer preset `react-tailwind-typescript-web` | `python3 scripts/install_harness.py --interactive` | "UI 변경은 browser verification까지 포함해서 plan을 세워줘." |
| DB가 중요한 ETL | ETL profile + 추가 DB pack | interactive에서 `tech-mssql` 또는 `tech-postgresql`, 필요 시 `workflow-db-context` 추가 | "DB별 transaction/idempotency 검증도 포함해줘." |
| 버그 진단 | debugging + TDD | `--packs workflow-core,workflow-debugging,workflow-tdd` | "증상 재현부터 최소화, 가설, 계측, 회귀 테스트 순서로 진행해." |
| 보안/권한/secret 변경 | security review | `--packs workflow-core,workflow-security-review,workflow-code-review` | "권한, secret exposure, rollback 관점으로 적대적 리뷰해." |
| 하네스 업그레이드 | remembered init scope | `python3 scripts/upgrade_harness.py --version v0.6.0 --dry-run` | "dry-run 결과와 conflict를 먼저 설명하고, force는 쓰지 마." |
| 하네스 일부 제거 | uninstall scopes | `python3 scripts/uninstall_harness.py --interactive` | "먼저 dry-run으로 뭐가 지워지는지 보여줘." |

Python 실행명이 `python`인 환경에서는 위 명령의 `python3`만 `python`으로 바꾸면 됩니다.

## 설치 패턴

### 기본 Roo 하네스

```bash
python3 scripts/harness.py init --target /path/to/project
```

또는:

```bash
python scripts/harness.py init --target /path/to/project
```

### core-only 하네스

```bash
python3 scripts/harness.py init --target /path/to/project --adapters none
```

Roo/OpenCode adapter 없이 planning skeleton, `AGENTS.md`, target README, scripts, 선택한 `.agents/skills/**`만 설치합니다.

### OpenCode 전용 하네스

```bash
python3 scripts/harness.py init --target /path/to/project --adapters opencode
```

OpenCode adapter는 의도적으로 phase primitive만 제공합니다. Debugging, TDD, review, security 같은 세부 workflow는 OpenCode command를 많이 늘리는 대신 설치된 `.agents/skills/**` pack에서 가져옵니다.

### Roo + OpenCode 동시 지원

```bash
python3 scripts/harness.py init --target /path/to/project --adapters both
```

동일한 alias:

```bash
python3 scripts/harness.py init --target /path/to/project --adapters roo,opencode
```

### 사내/외부 repo를 헷갈리지 않는 설치 예시

공유 문서에는 구체 repo URL 대신 `{Repo git}`을 사용합니다.

```bash
tmp="$(mktemp -d)"
git clone --depth 1 --branch v0.6.0 {Repo git} "$tmp"
python3 "$tmp/scripts/install_harness.py" --interactive
```

또는:

```bash
tmp="$(mktemp -d)"
git clone --depth 1 --branch v0.6.0 {Repo git} "$tmp"
python "$tmp/scripts/install_harness.py" --interactive
```

사내 mirror에서 바로 init하려면:

```bash
tmp="$(mktemp -d)"
git clone --depth 1 --branch v0.6.0 {Repo git} "$tmp"
python3 "$tmp/scripts/harness.py" init --target /path/to/project --adapters both
```

`{Repo git}` 값은 public URL이어도 되고 private/internal URL이어도 됩니다. 인증은 `git clone`이 SSH key, SSO, credential helper, PAT, 사내 표준 도구를 통해 처리합니다.

## 설치 후 첫 작업

Target repository에서 먼저 실행합니다.

```bash
python3 scripts/check_harness.py
python3 scripts/doctor_harness.py
python3 scripts/show_phase_status.py
```

또는:

```bash
python scripts/check_harness.py
python scripts/doctor_harness.py
python scripts/show_phase_status.py
```

그 다음 planning hydration부터 시작합니다. Roo를 설치했다면 `/phase-discuss planning-hydration --pass 0`로 시작합니다. OpenCode만 설치했다면 `.opencode/commands/discuss.md`를 사용하되 이 preflight를 먼저 적용합니다. Start with `python3 scripts/show_phase_status.py` when available. If it reports warnings, treat named files as minimum required reads before trusting the projection. If it is missing, fails, emits malformed output, or reports an unsupported contract version, use the legacy durable planning read order.

처음 사용하는 target prompt:

```text
I want to apply this Roo/Codex harness to this existing repository.
Do not implement application changes yet.
Hydrate .planning/codebase/** and active phase documents from the real repository.
Ask only for product intent or phase-boundary decisions the repo cannot answer.
Stop after the discuss pass and summarize confirmed facts, inferred facts, open questions, and recommended next phase.
```

## 워크플로우 모델

기본 흐름:

```text
discuss -> plan -> execute -> done
```

- **discuss**: 요청을 이해하고 repository evidence를 읽고 phase 후보를 제안합니다. 구현은 하지 않습니다.
- **plan**: allowed paths, blocked paths, verification commands, acceptance criteria, adversarial review를 작성합니다.
- **execute**: 명시적 승인 후 approved paths만 수정합니다.
- **done**: test, diff, residual risk, push readiness를 감사합니다.

Every roadmap phase starts with its own `discuss` pass before `plan` or `execute`. Before finalizing phase commitments, run adversarial review and include the mandatory lens of whether the workflow is concrete enough for low-reasoning models.

active phase docs는 다음 순서로 해석합니다:

1. `.scratch/phase-state.json`
2. `.planning/STATE.md`
3. `.planning/ROADMAP.md`
4. `.planning/phases/<phase>/*-PLAN.md`
5. `.planning/phases/<phase>/*-CHECKPOINTS.md`
6. `.planning/phases/<phase>/*-VERIFICATION.md`

## 클라이언트별 커맨드 모델

| Client | Discuss | Plan | Execute | Done / audit |
| --- | --- | --- | --- | --- |
| Roo | `/phase-discuss` | `/phase-plan` | `/phase-execute` | `/phase-execute` 후 done prompt |
| OpenCode | `.opencode/commands/discuss.md` | `.opencode/commands/plan.md` | `.opencode/commands/execute.md` | `.opencode/commands/done.md` |
| Generic agent | `AGENTS.md` 읽기 | plan docs 작성 | live gate 준수 | verification evidence 요약 |

`/phase-discuss`는 phase discovery와 planning hydration에 사용합니다. `.opencode/commands/execute.md`는 live gate가 execution approved 상태일 때만 사용합니다.

OpenCode에서 버그 수정:

```text
Use `.opencode/commands/discuss.md` first.
Then use installed skills workflow-debugging,workflow-tdd.
Do not edit application code until the plan names allowed_paths and I approve execute.
```

## 스킬 팩

skill pack은 플러그인입니다. 필요한 pack만 설치합니다. 생략하면 `workflow-core`가 설치됩니다.

### Workflow core

- `repository-evidence-research`: repository evidence를 먼저 읽고 confirmed facts, inferred facts, rejected assumptions를 분리합니다.
- `skill-plugin-composition`: 작업에 필요한 최소 skill 조합을 고릅니다.
- `verification-contract`: target repository에 실제로 존재하는 verification command를 선택합니다.
- `risk-review`: rollback, upgrade safety, edge case, operational risk를 점검합니다.
- `multi-agent-review`: product/protocol, implementation, release 관점으로 리뷰를 나눕니다.
- `release-readiness-audit`: release requirement를 artifact, test, git evidence, push state와 매핑합니다.
- `data-workflow`: ingestion, transformation, validation, generated dataset을 다룹니다.
- `integration-boundary`: 외부 시스템 contract와 boundary를 명확히 합니다.

### Workflow quality

- `workflow-tdd`: feature/fix를 test-first red-green-refactor로 진행합니다.
- `workflow-debugging`: reproduce, minimize, hypothesize, instrument, fix, regression-test 순서로 진단합니다.
- `workflow-code-review`: bug, regression, missing test, maintainability를 리뷰합니다.
- `workflow-skill-authoring`: project-local skill을 설계하고 검증합니다.
- `workflow-security-review`: auth, secret, permission boundary, dependency risk, deployment exposure를 점검합니다.

### Tech packs

- `tech-csharp`: C#/.NET build, test, nullable, public contract guidance.
- `tech-mssql`: SQL Server-backed persistence verification.
- `tech-postgresql`: PostgreSQL-backed persistence verification.
- `tech-python`: Python project convention과 verification.
- `tech-react`: React UI 구현과 browser verification.
- `tech-typescript`: TypeScript typecheck/build expectation.
- `tech-tailwind`: Tailwind styling constraint와 maintainability.

### Domain workflows

- `workflow-etl`: source, extract, transform, validate, stage, load, observe, restart, idempotency, backfill.
- `workflow-db-context`: DB context snapshot freshness, scope, substitute documentation.
- `workflow-web-development`: frontend implementation, responsive behavior, user-facing verification.
- `workflow-data-analysis`: reproducible analysis, assumptions, outputs, checks.
- `workflow-data-processing`: parsing, transformation, generated artifacts, validation.

## 프롬프트 레시피

### Planning hydration

```text
Do not implement yet.
Use repository-evidence-research first.
Hydrate .planning/codebase/** from actual repository evidence.
List confirmed facts, inferred facts, rejected assumptions, and open questions.
Stop before changing application code.
```

### Feature implementation

```text
Run discuss -> plan -> execute.
In plan, include allowed_paths, blocked_paths, verification, acceptance criteria, and adversarial review.
Do not enter execute until I explicitly approve.
```

### Bug diagnosis

```text
Use workflow-debugging,workflow-tdd.
Reproduce the symptom first, minimize it, state hypotheses, instrument only what is needed, then write a regression test before fixing.
```

### Security-sensitive work

```text
Use workflow-security-review and workflow-code-review.
Treat auth, permission checks, secrets, logs, config, and dependency changes as high-risk.
Show rollback and verification evidence before done.
```

### Push readiness

```text
완료 전 python3 scripts/harness.py check, python3 scripts/harness.py check --worktree, 계획에 적힌 검증 명령을 모두 실행하고 결과를 .planning/*VERIFICATION.md에 기록해.
push 전에 서브에이전트 적대적 리뷰를 해줘.
리뷰어는 protocol/product fit, installer/adapter compatibility, release verification/low-reasoning usability 관점으로 나눠.
```

Python 실행명이 `python`인 환경에서는 위 prompt의 `python3`를 `python`으로 바꿔도 됩니다.

### Windows 사용자에게 적용

```text
Windows 사용자에게 적용할 명령은 PowerShell 기준으로 써줘.
.sh 스크립트는 Linux/macOS 전용으로 보고, 하네스 핵심 검증은 scripts/harness.py check와 scripts/test_harness.py로 해.
경로는 Windows 절대경로를 그대로 쓰되, manifest나 planning 문서에는 repo-relative POSIX 스타일 경로를 기록해.
```

## 점검, Doctor, 검증

### 지원 환경과 명령 표기

하네스 Python 스크립트는 Python 3로 실행해야 합니다. Windows에서는 `python3` 대신 `py -3` 또는 `python`이 일반적입니다. `python scripts/foo.py`처럼 명시적으로 interpreter를 붙여 실행하면 script 내부 shebang은 문제되지 않습니다.

| Platform | Unit tests | Source check | Smoke |
| --- | --- | --- | --- |
| Linux/macOS | `python3 -m unittest scripts/test_harness.py` | `python3 scripts/harness.py check` | `python3 scripts/release_smoke_test.py` |
| Windows PowerShell | `py -3 -m unittest scripts/test_harness.py` | `py -3 scripts/harness.py check` | `py -3 scripts/release_smoke_test.py` |
| Windows without launcher | `python -m unittest scripts/test_harness.py` | `python scripts/harness.py check` | `python scripts/release_smoke_test.py` |

`scripts/codex-cloud-setup.sh`는 Linux/macOS shell용입니다. Windows에서는 같은 효과를 내는 setup 명령을 PowerShell로 옮겨 실행하거나, core 명령인 `scripts/harness.py init/check/doctor`만 사용합니다.

### Source repository checks

Harness source를 수정한 뒤 commit 전 실행합니다.

```bash
python3 -m unittest scripts/test_harness.py
python3 scripts/harness.py check
python3 scripts/harness.py check --worktree
python3 scripts/release_smoke_test.py
```

또는:

```bash
python -m unittest scripts/test_harness.py
python scripts/harness.py check
python scripts/harness.py check --worktree
python scripts/release_smoke_test.py
```

### Target repository checks

Harness source에서 target을 점검합니다.

```bash
python3 scripts/harness.py check --target /path/to/project
python3 scripts/harness.py check --target /path/to/project --adapter opencode
```

또는:

```bash
python scripts/harness.py check --target /path/to/project
python scripts/harness.py check --target /path/to/project --adapter opencode
```

Installed target 안에서는:

```bash
python3 scripts/check_harness.py
python3 scripts/doctor_harness.py
```

또는:

```bash
python scripts/check_harness.py
python scripts/doctor_harness.py
```

`check`는 live phase gate의 구조 오류를 실패로 처리합니다. 특히 `verification`이 비어 있거나 `TODO:`, `TBD`, `placeholder`, `manual test`처럼 실행 가능한 검증이 아닌 placeholder이면 실패합니다. 일반 도메인 문구(`todo-list`, `manual test plan`, `placeholder replacement`)는 막지 않습니다.

`doctor`는 실패시키기보다 workflow 품질 신호를 보고합니다. 예를 들어 phase-status projection의 `required_reads` 누락, optional verification/summary pointer 누락, 설치 manifest의 adapter/profile/pack metadata 불일치를 warning으로 보여줍니다.

### Worktree scope check

구현 변경은 다음을 통과해야 합니다.

```bash
python3 scripts/harness.py check --worktree
```

또는:

```bash
python scripts/harness.py check --worktree
```

실패하면 현재 diff가 approved `allowed_paths` 밖으로 나간 것입니다. 구현을 멈추고 plan으로 돌아갑니다.

## 업그레이드

### 새 source checkout에서 target upgrade

```bash
python3 /path/to/newer-harness/scripts/harness.py upgrade --target /path/to/project --dry-run
python3 /path/to/newer-harness/scripts/harness.py upgrade --target /path/to/project
python3 /path/to/project/scripts/harness.py check
```

또는:

```bash
python /path/to/newer-harness/scripts/harness.py upgrade --target /path/to/project --dry-run
python /path/to/newer-harness/scripts/harness.py upgrade --target /path/to/project
python /path/to/project/scripts/harness.py check
```

새 버전으로 upgrade하면 공용 workflow 정적 검사 helper인 `scripts/lib/workflow_static_checks.py`도 target에 설치됩니다.

### Installed target bootstrapper로 upgrade

```bash
python3 scripts/upgrade_harness.py --version v0.6.0 --dry-run
python3 scripts/upgrade_harness.py --version v0.6.0
python3 scripts/check_harness.py
python3 scripts/doctor_harness.py
```

또는:

```bash
python scripts/upgrade_harness.py --version v0.6.0 --dry-run
python scripts/upgrade_harness.py --version v0.6.0
python scripts/check_harness.py
python scripts/doctor_harness.py
```

Install state에 git source provenance가 있으면 bootstrapper는 그 repo를 기본값으로 씁니다. 사내 mirror에서 설치한 target은 별도 지정이 없으면 같은 사내 mirror에서 upgrade합니다.

### 사내/외부 repo 명시 override

```bash
python3 scripts/upgrade_harness.py \
  --repo {Repo git} \
  --version v0.6.0 \
  --dry-run
```

또는:

```bash
python scripts/upgrade_harness.py \
  --repo {Repo git} \
  --version v0.6.0 \
  --dry-run
```

### Remote access가 막힌 경우 local source fallback

```bash
python3 scripts/upgrade_harness.py --source /path/to/newer-harness --version v0.6.0 --dry-run
```

또는:

```bash
python scripts/upgrade_harness.py --source /path/to/newer-harness --version v0.6.0 --dry-run
```

### 오래된 수동 설치 adopt

Target에 harness file은 있지만 `.harness/installed-manifest.json`이 없다면 adopt 후 upgrade합니다.

```bash
python3 /path/to/newer-harness/scripts/harness.py upgrade \
  --target "/path/to/manual project" \
  --adopt-existing \
  --adapters roo \
  --profiles generic \
  --packs workflow-core
```

Conflict는 `.harness/conflicts/` 아래에 기록됩니다. 검토 전에는 `--force`를 쓰지 않습니다.

## 제거

Target-local uninstall은 전용 script를 씁니다.

```bash
python3 scripts/uninstall_harness.py --interactive
```

또는 source checkout에서 target을 지정합니다.

```bash
python3 /path/to/harness/scripts/uninstall_harness.py --target /path/to/project --select 1,2 --dry-run
python3 /path/to/harness/scripts/uninstall_harness.py --target /path/to/project --select 1,2
```

전체 범위 `1,2,3,4,5`를 삭제해도 기본적으로 `.harness/installed-manifest.json`은 보존됩니다. Interactive 모드에서는 전체 범위 선택 시 설치 상태 manifest까지 삭제할지 추가로 확인합니다. 비대화형 모드에서 설치 상태까지 지우려면 명시적으로 `--remove-install-state`를 붙입니다.

```bash
python3 /path/to/harness/scripts/uninstall_harness.py --target /path/to/project --select 1,2,3,4,5 --remove-install-state
```

`scripts/harness.py uninstall`도 같은 script로 위임합니다.

```bash
python3 scripts/harness.py uninstall --target /path/to/project --select 4 --dry-run
```

Interactive 선택지는 독립 범위입니다. 숫자를 여러 개 콤마로 입력할 수 있고, 앞 번호가 뒤 번호를 포함하지 않습니다.

| 번호 | 제거 범위 |
| --- | --- |
| 1 | Roo 환경만 제거: `.roo/**`, `.roomodes`, `.rooignore` |
| 2 | OpenCode 환경만 제거: `.opencode/**` |
| 3 | Runtime harness만 제거: `.agents/skills/**`, harness scripts 등. Adapter와 core protocol은 보존 |
| 4 | Core protocol만 제거: `AGENTS.md`/`.gitignore` managed block, `.scratch/**` 등. Adapter/runtime/docs는 보존 |
| 5 | Planning/docs만 제거: `.planning/**`, harness docs/profiles 등. 권장하지 않음. 프로젝트 계획 기록이 사라집니다 |

삭제 대상은 `.harness/installed-manifest.json`에 기록된 파일과 managed marker block 기준입니다. 설치 상태 manifest 자체는 `--remove-install-state`를 명시하거나 interactive 추가 확인에 동의한 경우에만 삭제됩니다. `--dry-run`으로 먼저 확인하고, conflict가 있으면 실제 삭제는 중단됩니다.

## 플랫폼별 참고사항

### Linux/macOS

보통 `python3`를 사용합니다. Shell 예시는 bash-compatible syntax 기준입니다.

### Windows PowerShell

Python Launcher가 있으면 `py -3`를 권장합니다.

```powershell
py -3 scripts/harness.py check
```

Python Launcher가 없거나 `python`이 Python 3를 가리키는 환경이면 다음처럼 실행합니다.

```powershell
python scripts/harness.py check
```

Clone/install 예시는 PowerShell temp directory 문법으로 바꿔 실행합니다.

```powershell
$tmp = New-Item -ItemType Directory -Path ([System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), [System.Guid]::NewGuid()))
git clone --depth 1 --branch v0.6.0 {Repo git} $tmp.FullName
py -3 "$($tmp.FullName)\scripts\install_harness.py" --interactive
```

또는:

```powershell
$tmp = New-Item -ItemType Directory -Path ([System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), [System.Guid]::NewGuid()))
git clone --depth 1 --branch v0.6.0 {Repo git} $tmp.FullName
python "$($tmp.FullName)\scripts\install_harness.py" --interactive
```

### Git authentication

하네스는 git credential을 직접 관리하지 않습니다. Public/private repo 접근은 모두 일반 `git clone` 설정을 따릅니다. SSH key, credential helper, SSO, PAT, 사내 표준 tooling을 사용하세요.

## 레퍼런스

### Repository structure

- `AGENTS.md`: source-repo agent instructions.
- `README.md`: source-repo user guide.
- `harness/manifest.json`: installable file manifest.
- `harness/skeleton/clean/**`: target project skeleton.
- `harness/profiles/**`: optional project profiles.
- `harness/skill-packs/**`: source skill packs installed into target `.agents/skills/**`.
- `.roo/**`: Roo adapter source.
- `.opencode/**`: OpenCode adapter source.
- `scripts/harness.py`: init, upgrade, check, doctor, uninstall, release-check.
- `scripts/install_harness.py`: human-facing interactive installer.
- `scripts/upgrade_harness.py`: target-local upgrade bootstrapper.
- `scripts/uninstall_harness.py`: target-local uninstall helper.
- `scripts/check_harness.py`: target-local self-check.
- `scripts/doctor_harness.py`: target-local diagnostics.
- `scripts/show_phase_status.py`: live phase gate status.
- `scripts/release_smoke_test.py`: release matrix smoke test.

### Manifest and install state

`harness/manifest.json`는 adapter, profile, pack 기준으로 설치 파일을 고릅니다. `init`은 선택 scope를 `.harness/installed-manifest.json`의 `init_options`에 기록합니다. 이후 `upgrade`는 새 `--adapters`, `--profiles`, `--packs`를 넘기지 않으면 remembered scope를 재사용합니다.

### Managed files

Project-owned planning docs는 무조건 덮어쓰지 않습니다. Harness-owned files는 source manifest 기준으로 갱신합니다. `.gitignore`, `AGENTS.md`처럼 marker block을 지원하는 파일은 managed append semantics를 사용합니다.

### Release checklist

Source release 전:

```bash
python3 -m unittest scripts/test_harness.py
python3 scripts/harness.py check
python3 scripts/harness.py check --worktree
python3 scripts/release_smoke_test.py
python3 scripts/harness.py release-check --expected-version v0.6.0
```

또는:

```bash
python -m unittest scripts/test_harness.py
python scripts/harness.py check
python scripts/harness.py check --worktree
python scripts/release_smoke_test.py
python scripts/harness.py release-check --expected-version v0.6.0
```

검증 evidence는 tag/push 전에 phase verification document에 기록합니다.
