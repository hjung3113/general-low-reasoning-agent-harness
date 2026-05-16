# 범용 저추론 에이전트 하네스

저추론 코딩 에이전트(Roo, OpenCode, Haiku 수준 모델)가 실제 저장소에서 안전하게 일하도록 만드는 재사용 가능한 하네스. Target repository에 planning state, phase gate, adapter command, workflow skill, verification contract를 설치합니다.

[mattpocock/skills README](https://github.com/mattpocock/skills/blob/main/README.md)의 "빠른 시작 → 왜 필요한가 → 상세 레퍼런스" 흐름 참고. 다만 본 저장소는 단순 skill 모음이 아니라, target repository에 규칙/명령/스크립트/계획 문서/skill pack을 배포하는 harness source.

최근 변경 사항은 [CHANGELOG.md](CHANGELOG.md)를 참고하세요.

## 빠른 시작

원격 source를 직접 열지 않고 한 번에 설치:

```bash
tmp="$(mktemp -d)"
git clone --depth 1 --branch v0.6.1 {Repo git} "$tmp"
python3 "$tmp/scripts/install_harness.py" --interactive
```

Interactive installer는:
1. Absolute path를 가진 existing target directory를 받습니다.
2. Adapter(`roo`/`opencode`/`both`/`none`)와 profile(`generic`/`dotnet-etl`/`python-etl`/`react-web`)을 묻습니다.
3. Profile이 `generic`이 아니면 database 축(`mssql`/`postgresql`/`none`)을 추가로 묻습니다.
4. 기본 포함 skill pack을 보여주고 추가 pack을 선택하게 합니다.

설치 후 target 안에서 첫 점검:

```bash
python3 scripts/harness.py check
python3 scripts/harness.py state show
```

Windows 사용자는 `python3` 대신 `py -3` 또는 `python`을 사용하세요. 자세한 platform 안내는 [플랫폼별 참고사항](#플랫폼별-참고사항)을 참조하세요.

## 이 하네스가 하는 일

Target project에 작은 protocol을 설치해서 에이전트가 다음을 지키게 합니다.

- 작업 전에 durable planning state를 읽는다.
- 논의, 계획, 실행, 완료 감사를 분리한다.
- 명시적 execute 승인 전에는 application code를 수정하지 않는다.
- 하나의 거대한 prompt 대신 task에 맞는 workflow skill을 조합한다.
- target repository에 실제로 존재하는 명령으로 검증한다.

Core protocol은 client-neutral, stack-neutral. Roo와 OpenCode는 adapter이지 source of truth가 아닙니다.

## 왜 필요한가

| 문제 | 하네스의 해결 |
| --- | --- |
| 에이전트가 합의 전에 바로 코딩한다 | `discuss -> plan -> execute -> done` 흐름을 강제해 alignment와 mutation을 분리 |
| 에이전트가 중요한 맥락을 잊는다 | `.planning/**`은 canonical memory입니다. 구조/stack/convention/roadmap/phase plan/검증 evidence/decision 기록 |
| 승인된 범위 밖을 수정한다 | `.scratch/phase-state.json`은 현재 작업을 열거나 막는 live gate일 뿐입니다. `harness.py check --worktree`가 staged/unstaged/untracked change가 approved path 밖으로 나갔는지 차단 |
| 모든 작업을 하나의 workflow로 처리하려 한다 | skill pack은 플러그인. Core는 작게, debugging/TDD/code review 같은 skill은 필요한 target에만 |
| 에이전트가 ROADMAP/STATE 양식을 깨뜨린다 | machine-owned 영역을 [managed marker block](#managed-marker-blocks)으로 감싸고 `state repair`로 canonical 복구 |

## 사용 시나리오 빠른 선택

| 목적 | 추천 설치 | 명령 | 시작 프롬프트 |
| --- | --- | --- | --- |
| 새 프로젝트에 기본 가드레일만 넣기 | 기본 Roo 또는 `--adapters roo` | `python3 scripts/harness.py init --target /path/to/project` | "아직 구현하지 말고 planning hydration만 해줘." |
| core-only 하네스 | adapter 없음 | `python3 scripts/harness.py init --target /path/to/project --adapters none` | "core planning docs만 만들고 adapter command는 설치하지 마." |
| OpenCode만 쓰기 | OpenCode adapter | `python3 scripts/harness.py init --target /path/to/project --adapters opencode` | "OpenCode discuss command 순서대로 읽고 phase 후보만 제안해." |
| Roo + OpenCode 동시 지원 | both adapters | `python3 scripts/harness.py init --target /path/to/project --adapters both` | "Roo/OpenCode 모두 같은 `.planning/**`과 live gate를 쓰는지 확인해." |
| .NET ETL | `dotnet-etl` profile | `python3 scripts/install_harness.py --interactive` | ".NET ETL restart/idempotency와 TDD 검증 계획을 세워줘." |
| Python ETL | `python-etl` profile | `python3 scripts/install_harness.py --interactive` | "Python 데이터 파이프라인의 입력/변환/재시작 검증 계획을 세워줘." |
| React/TS/Tailwind web app | `react-web` profile | `python3 scripts/install_harness.py --interactive` | "UI 변경은 browser verification까지 포함해서 plan을 세워줘." |
| ETL with SQL Server | `dotnet-etl` + `--db mssql` | interactive 또는 `python3 scripts/harness.py init --target ... --profiles dotnet-etl --db mssql` | "MSSQL transaction/idempotency 검증도 포함해줘." |
| DB가 중요한 ETL | ETL profile + `--db` flag | interactive에서 `--db mssql` 또는 `--db postgresql`, 필요 시 `workflow-db-context` 추가 | "DB별 transaction/idempotency 검증도 포함해줘." |
| 버그 진단 | debugging + TDD | `--packs workflow-core,workflow-debugging,workflow-tdd` | "증상 재현부터 최소화, 가설, 계측, 회귀 테스트 순서로 진행해." |
| 보안/권한/secret 변경 | security review | `--packs workflow-core,workflow-security-review,workflow-code-review` | "권한, secret exposure, rollback 관점으로 적대적 리뷰해." |
| 양식 깨진 ROADMAP/STATE 복구 | core | `python3 scripts/harness.py state repair` | (no prompt — CLI 호출만) |
| 하네스 업그레이드 | remembered init scope | `python3 scripts/upgrade_harness.py --version v0.6.1 --dry-run` | "dry-run 결과와 conflict를 먼저 설명하고, force는 쓰지 마." |
| 하네스 일부 제거 | uninstall scopes | `python3 scripts/uninstall_harness.py --interactive` | "먼저 dry-run으로 뭐가 지워지는지 보여줘." |

## 워크플로우 모델

기본 흐름:

```text
discuss -> plan -> execute -> done
```

- **discuss**: 요청 이해, repository evidence 읽기, phase 후보 제안. 구현 안 함.
- **plan**: allowed paths, blocked paths, verification commands, acceptance criteria, adversarial review 작성.
- **execute**: 명시적 승인 후 approved paths만 수정.
- **done**: test, diff, residual risk, push readiness 감사.

Every roadmap phase starts with its own `discuss` pass before `plan` or `execute`. 마무리 전에 adversarial review를 돌리고, low-reasoning model에게도 workflow가 구체적인지 lens로 검증합니다.

active phase docs는 다음 순서로 해석합니다:

1. `.scratch/phase-state.json`
2. `.planning/STATE.md`
3. `.planning/ROADMAP.md`
4. `.planning/phases/<phase>/*-PLAN.md`
5. `.planning/phases/<phase>/*-CHECKPOINTS.md`
6. `.planning/phases/<phase>/*-VERIFICATION.md`

권장: 매 세션 시작 시 `python3 scripts/harness.py state show`로 projection을 먼저 확인. 양식 drift가 의심되면 `python3 scripts/harness.py state repair`.

## Managed marker blocks

ROADMAP.md / STATE.md 안에서 machine-owned 영역은 HTML 주석 marker block으로 감쌉니다.

```
<!-- HARNESS:BEGIN managed:roadmap-phases v1 -->
- [ ] **Phase 0: Planning Hydration**
<!-- HARNESS:END managed:roadmap-phases -->
```

- Block 안: 스크립트 소유. 에이전트 직접 편집 금지.
- Block 밖: 자유. Notes / Session Continuity / 자유 prose.

운영 명령:

| 목적 | 명령 |
| --- | --- |
| projection 보기 (read-only) | `python3 scripts/harness.py state show` |
| projection JSON으로 보기 | `python3 scripts/harness.py state show --format json` |
| 깨진 양식 또는 marker 없는 파일 복구 | `python3 scripts/harness.py state repair` |

`state repair`는 idempotent. 마커 없는 파일이면 marker를 추가하고, 이미 있으면 canonical 형태로 재렌더. Block 밖에 phase 줄(`- [x] **Phase N: ...**`)이 있으면 `RepairReport.warnings`로 보고하며 흡수하지 않습니다.

한계:

- `state repair`는 별도 canonical hash를 저장하지 않습니다. Block 안을 잘못 편집하면 그 내용을 source-of-truth로 삼아 다시 써넣습니다. 복구는 git revert로.
- 현재 marker 적용 대상은 `.planning/ROADMAP.md`의 phase 체크리스트와 `.planning/STATE.md`의 Current Position + Active Checkpoint 영역뿐입니다. Phase plan/checkpoint 문서는 자유 양식 유지.

`harness.py check`는 marker가 없는 ROADMAP/STATE에 대해 **warning(실패 아님)**을 출력합니다. 메시지에 정확한 fix 명령이 포함됩니다.

## 핵심 모델

하네스는 네 계층으로 나뉩니다.

- **Core protocol**: `.planning/**`, `.scratch/phase-state.json`, checks, doctor, dashboard, AGENTS guidance.
- **Adapters**: `.roo/**`, `.opencode/**`, client-specific command surfaces.
- **Profiles**: `generic`, `dotnet-etl`, `python-etl`, `react-web` 같은 확인된 project environment.
- **Skill packs**: `.agents/skills/**` 아래에 설치되는 composable workflow/tech skill.

중요한 ownership rule: source repository에는 `.agents/skills/**`가 없어도 정상입니다. Source에는 `harness/skill-packs/**`가 있고, target install 시 선택한 pack만 `.agents/skills/**`로 복사됩니다.

## 설치 패턴

### 기본 Roo 하네스

```bash
python3 scripts/harness.py init --target /path/to/project
```

기본 설치 내용: core planning skeleton, Roo adapter, generic profile, `workflow-core` skill pack.

### core-only 하네스

```bash
python3 scripts/harness.py init --target /path/to/project --adapters none
```

Roo/OpenCode adapter 없이 planning skeleton, `AGENTS.md`, target README, scripts, 선택한 `.agents/skills/**`만 설치.

### OpenCode 전용 하네스

```bash
python3 scripts/harness.py init --target /path/to/project --adapters opencode
```

OpenCode adapter는 의도적으로 phase primitive만 제공합니다. Debugging, TDD, review, security 같은 세부 workflow는 설치된 `.agents/skills/**` pack에서 가져옵니다.

### Roo + OpenCode 동시 지원

```bash
python3 scripts/harness.py init --target /path/to/project --adapters both
```

동일 alias: `--adapters roo,opencode`.

### 사내/외부 repo 헷갈리지 않는 설치 예시

공유 문서에는 구체 repo URL 대신 `{Repo git}`을 사용합니다.

```bash
tmp="$(mktemp -d)"
git clone --depth 1 --branch v0.6.1 {Repo git} "$tmp"
python3 "$tmp/scripts/install_harness.py" --interactive
```

사내 mirror에서 바로 init하려면:

```bash
tmp="$(mktemp -d)"
git clone --depth 1 --branch v0.6.1 {Repo git} "$tmp"
python3 "$tmp/scripts/harness.py" init --target /path/to/project --adapters both
```

`{Repo git}`은 public/private/internal URL 모두 가능. 인증은 `git clone`이 SSH key/SSO/credential helper/PAT/사내 도구를 통해 처리합니다.

## 설치 후 첫 작업

Target repository 안에서:

```bash
python3 scripts/check_harness.py
python3 scripts/doctor_harness.py
python3 scripts/harness.py state show
```

그 다음 planning hydration. Roo를 설치했다면 `/phase-discuss planning-hydration --pass 0`로 시작. OpenCode만 설치했다면 `.opencode/commands/discuss.md`를 사용. Start with `python3 scripts/harness.py state show` when available. If it reports warnings, treat named files as minimum required reads before trusting the projection. If it is missing, fails, or emits malformed output, use the legacy durable planning read order.

처음 사용하는 target prompt:

```text
I want to apply this harness to this existing repository.
Do not implement application changes yet.
Hydrate .planning/codebase/** and active phase documents from the real repository.
Ask only for product intent or phase-boundary decisions the repo cannot answer.
Stop after the discuss pass and summarize confirmed facts, inferred facts, open questions, and recommended next phase.
```

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

## Roo modes

기본 8개 mode (`orchestrator`, `architect`, `tdd-code`, `diagnose`, `review`, `docs-issues`, `ops-observability`, `harness-maintainer`). Profile-contributed mode는 추가됩니다:

- `ui-engineer` (`react-web` profile + Roo adapter): browser-first UI 구현. Profile 제거 시 자동 drop.

## 스킬 팩

skill pack은 플러그인입니다. 필요한 pack만 설치. 생략하면 `workflow-core`가 설치됩니다.

### Workflow core

- `repository-evidence-research`: repository evidence를 먼저 읽고 confirmed/inferred/rejected를 분리.
- `skill-plugin-composition`: 작업에 필요한 최소 skill 조합 선택.
- `verification-contract`: target repository에 실제로 존재하는 verification command 선택.
- `risk-review`: rollback, upgrade safety, edge case, operational risk 점검.
- `multi-agent-review`: product/protocol, implementation, release 관점 리뷰 분리.
- `release-readiness-audit`: release requirement를 artifact/test/git evidence/push state와 매핑.
- `data-workflow`: ingestion, transformation, validation, generated dataset.
- `integration-boundary`: 외부 시스템 contract와 boundary.

### Workflow quality

- `workflow-tdd`: feature/fix를 test-first red-green-refactor로.
- `workflow-debugging`: reproduce → minimize → hypothesize → instrument → fix → regression-test.
- `workflow-code-review`: bug, regression, missing test, maintainability.
- `workflow-skill-authoring`: project-local skill 설계와 검증.
- `workflow-security-review`: auth, secret, permission boundary, dependency risk, deployment exposure.

### Tech packs

- `tech-csharp`: C#/.NET build, test, nullable, public contract.
- `tech-mssql`: SQL Server-backed persistence verification.
- `tech-postgresql`: PostgreSQL-backed persistence verification.
- `tech-python`: Python project convention과 verification.
- `tech-react`: React UI 구현과 browser verification.
- `tech-typescript`: TypeScript typecheck/build expectation.
- `tech-tailwind`: Tailwind styling constraint와 maintainability.

### Domain workflows

- `workflow-etl`: source, extract, transform, validate, stage, load, observe, restart, idempotency, backfill.
- `workflow-db-context`: DB context snapshot freshness, scope, substitute documentation.
- `workflow-web-development`: frontend 구현, responsive behavior, user-facing verification.
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
Run discuss → plan → execute.
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

### Windows 사용자에게 적용

```text
Windows 사용자에게 적용할 명령은 PowerShell 기준으로 써줘.
.sh 스크립트는 Linux/macOS 전용으로 보고, 하네스 핵심 검증은 scripts/harness.py check와 scripts/test_harness.py로 해.
경로는 Windows 절대경로를 그대로 쓰되, manifest나 planning 문서에는 repo-relative POSIX 스타일 경로를 기록해.
```

## 점검, Doctor, 검증

### 지원 환경과 명령 표기

하네스 Python 스크립트는 Python 3로 실행. Windows에서는 `python3` 대신 `py -3` 또는 `python`이 일반적입니다. `python scripts/foo.py`처럼 명시적으로 interpreter를 붙여 실행하면 script 내부 shebang은 문제되지 않습니다.

| Platform | Unit tests | Source check | Smoke |
| --- | --- | --- | --- |
| Linux/macOS | `python3 -m unittest scripts/test_harness.py` | `python3 scripts/harness.py check` | `python3 scripts/release_smoke_test.py` |
| Windows PowerShell | `py -3 -m unittest scripts/test_harness.py` | `py -3 scripts/harness.py check` | `py -3 scripts/release_smoke_test.py` |
| Windows without launcher | `python -m unittest scripts/test_harness.py` | `python scripts/harness.py check` | `python scripts/release_smoke_test.py` |

`scripts/codex-cloud-setup.sh`는 Linux/macOS shell용입니다. Windows에서는 core 명령(`scripts/harness.py init/check/doctor`)만 사용합니다.

### Source repository checks

Harness source 수정 후 commit 전:

```bash
python3 -m unittest scripts/test_harness.py
python3 scripts/harness.py check
python3 scripts/harness.py check --worktree
python3 scripts/release_smoke_test.py
```

### Target repository checks

Harness source에서 target을 점검:

```bash
python3 scripts/harness.py check --target /path/to/project
python3 scripts/harness.py check --target /path/to/project --adapter opencode
```

Installed target 안에서:

```bash
python3 scripts/check_harness.py
python3 scripts/doctor_harness.py
python3 scripts/harness.py state show
```

`check`는 live phase gate의 구조 오류를 실패로 처리합니다. `verification`이 비어 있거나 `TODO:`/`TBD`/`placeholder`/`manual test`처럼 실행 가능한 검증이 아닌 placeholder이면 실패. 일반 도메인 문구(`todo-list`, `manual test plan`, `placeholder replacement`)는 막지 않습니다.

Managed block이 없거나 깨진 경우는 **warning(실패 아님)**으로 표시되며, 메시지에 `python3 scripts/harness.py state repair` 명령이 포함됩니다.

`doctor`는 실패시키기보다 workflow 품질 신호를 보고합니다. phase-status projection의 `required_reads` 누락, optional verification/summary pointer 누락, 설치 manifest의 adapter/profile/pack metadata 불일치 등을 warning으로 보여줍니다.

### Worktree scope check

구현 변경은 다음을 통과해야 합니다:

```bash
python3 scripts/harness.py check --worktree
```

실패하면 현재 diff가 approved `allowed_paths` 밖으로 나간 것. 구현을 멈추고 plan으로 돌아갑니다.

## 업그레이드

### 새 source checkout에서 target upgrade

```bash
python3 /path/to/newer-harness/scripts/harness.py upgrade --target /path/to/project --dry-run
python3 /path/to/newer-harness/scripts/harness.py upgrade --target /path/to/project
python3 /path/to/project/scripts/harness.py check
```

새 버전으로 upgrade하면 공용 workflow 정적 검사 helper인 `scripts/lib/workflow_static_checks.py`도 target에 설치됩니다.

### Installed target bootstrapper로 upgrade

```bash
python3 scripts/upgrade_harness.py --version v0.6.1 --dry-run
python3 scripts/upgrade_harness.py --version v0.6.1
python3 scripts/check_harness.py
python3 scripts/doctor_harness.py
```

Install state에 git source provenance가 있으면 bootstrapper는 그 repo를 기본값으로 씁니다. 사내 mirror에서 설치한 target은 별도 지정 없이도 같은 mirror에서 upgrade.

### 사내/외부 repo 명시 override

```bash
python3 scripts/upgrade_harness.py \
  --repo {Repo git} \
  --version v0.6.1 \
  --dry-run
```

### Remote access 막힌 경우 local source fallback

```bash
python3 scripts/upgrade_harness.py --source /path/to/newer-harness --version v0.6.1 --dry-run
```

### 오래된 수동 설치 adopt

Target에 harness file은 있지만 `.harness/installed-manifest.json`이 없으면 adopt 후 upgrade:

```bash
python3 /path/to/newer-harness/scripts/harness.py upgrade \
  --target "/path/to/manual project" \
  --adopt-existing \
  --adapters roo \
  --profiles generic \
  --packs workflow-core
```

Conflict는 `.harness/conflicts/` 아래에 기록. 검토 전에는 `--force`를 쓰지 않습니다.

## 제거

Target-local uninstall은 전용 script를 씁니다.

```bash
python3 scripts/uninstall_harness.py --interactive
```

Source checkout에서 target을 지정:

```bash
python3 /path/to/harness/scripts/uninstall_harness.py --target /path/to/project --select 1,2 --dry-run
python3 /path/to/harness/scripts/uninstall_harness.py --target /path/to/project --select 1,2
```

전체 범위 `1,2,3,4,5`를 삭제해도 기본적으로 `.harness/installed-manifest.json`은 보존됩니다. Interactive에서는 전체 범위 선택 시 설치 상태 manifest까지 삭제할지 추가 확인. 비대화형에서 설치 상태까지 지우려면 `--remove-install-state`를 명시.

```bash
python3 /path/to/harness/scripts/uninstall_harness.py --target /path/to/project --select 1,2,3,4,5 --remove-install-state
```

| 번호 | 제거 범위 |
| --- | --- |
| 1 | Roo 환경만 제거: `.roo/**`, `.roomodes`, `.rooignore` |
| 2 | OpenCode 환경만 제거: `.opencode/**` |
| 3 | Runtime harness만 제거: `.agents/skills/**`, harness scripts 등. Adapter와 core protocol은 보존 |
| 4 | Core protocol만 제거: `AGENTS.md`/`.gitignore` managed block, `.scratch/**` 등. Adapter/runtime/docs는 보존 |
| 5 | Planning/docs만 제거: `.planning/**`, harness docs/profiles 등. 권장하지 않음. 프로젝트 계획 기록이 사라집니다 |

`--dry-run`으로 먼저 확인. Conflict가 있으면 실제 삭제는 중단됩니다.

## 플랫폼별 참고사항

### Linux/macOS

보통 `python3`를 사용. Shell 예시는 bash-compatible syntax 기준.

### Windows PowerShell

Python Launcher가 있으면 `py -3`를 권장:

```powershell
py -3 scripts/harness.py check
```

Python Launcher가 없거나 `python`이 Python 3를 가리키는 환경이면:

```powershell
python scripts/harness.py check
```

Clone/install 예시는 PowerShell temp directory 문법으로 바꿔 실행:

```powershell
$tmp = New-Item -ItemType Directory -Path ([System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), [System.Guid]::NewGuid()))
git clone --depth 1 --branch v0.6.1 {Repo git} $tmp.FullName
py -3 "$($tmp.FullName)\scripts\install_harness.py" --interactive
```

### Git authentication

하네스는 git credential을 직접 관리하지 않습니다. Public/private repo 접근은 모두 일반 `git clone` 설정을 따릅니다. SSH key, credential helper, SSO, PAT, 사내 표준 tooling 사용.

## 레퍼런스

### Repository structure

- `AGENTS.md`: source-repo agent instructions.
- `README.md`: source-repo user guide.
- `CHANGELOG.md`: release notes.
- `harness/manifest.json`: installable file manifest.
- `harness/skeleton/clean/**`: target project skeleton.
- `harness/profiles/**`: optional project profiles.
- `harness/skill-packs/**`: source skill packs installed into target `.agents/skills/**`.
- `.roo/**`: Roo adapter source.
- `.opencode/**`: OpenCode adapter source.
- `scripts/harness.py`: thin CLI dispatcher (init, upgrade, check, doctor, uninstall, release-check, state). Implementation lives in `scripts/lib/**`; the file re-exports every public symbol so existing `from scripts.harness import X` callers keep working.
- `scripts/lib/**`: role-split modules used by `scripts/harness.py`.
  - `version.py`, `profiles.py`, `manifest.py`, `append_block.py`
  - `state.py`, `roadmap_state.py`, `worktree.py`
  - `adoption.py`, `check.py`, `doctor.py`
  - `install.py`, `upgrade.py`
  - `roomodes_writer.py`, `planning_status.py`, `workflow_static_checks.py`
  - `managed_block.py`, `state_repair.py`, `state_cli.py`
- `scripts/install_harness.py`: human-facing interactive installer.
- `scripts/upgrade_harness.py`: target-local upgrade bootstrapper.
- `scripts/uninstall_harness.py`: target-local uninstall helper.
- `scripts/check_harness.py`: target-local self-check.
- `scripts/doctor_harness.py`: target-local diagnostics.
- `scripts/show_phase_status.py`: live phase gate status.
- `scripts/release_smoke_test.py`: release matrix smoke test.
- `scripts/release.py`: develop → main → tag → push → GitHub release automation.

### Manifest and install state

`harness/manifest.json`는 adapter, profile, pack 기준으로 설치 파일을 고릅니다. `init`은 선택 scope를 `.harness/installed-manifest.json`의 `init_options`에 기록. 이후 `upgrade`는 새 `--adapters`, `--profiles`, `--packs`를 넘기지 않으면 remembered scope를 재사용합니다.

### Managed files

Project-owned planning docs는 무조건 덮어쓰지 않습니다. Harness-owned files는 source manifest 기준으로 갱신. `.gitignore`, `AGENTS.md`처럼 marker block을 지원하는 파일은 managed append semantics를 사용합니다. ROADMAP/STATE 안의 `<!-- HARNESS:BEGIN managed:... -->` block은 `state repair`로 갱신.

### Release checklist

Source release 전:

```bash
python3 -m unittest scripts/test_harness.py
python3 scripts/harness.py check
python3 scripts/harness.py check --worktree
python3 scripts/release_smoke_test.py
python3 scripts/harness.py release-check --expected-version v0.6.1
```

검증 evidence는 tag/push 전에 phase verification document에 기록.
