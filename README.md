# General Low-Reasoning Agent Harness

A reusable harness for making low-reasoning coding agents work inside real repositories with explicit planning state, phase gates, adapter commands, workflow skills, and verification contracts.

This project is inspired structurally by the clear “quickstart -> why -> reference” style of [mattpocock/skills](https://github.com/mattpocock/skills/blob/main/README.md), but this repo is a harness distribution: it installs project-local rules, commands, scripts, planning docs, and skill packs into target repositories.

## Table of Contents

- [Quickstart](#quickstart)
- [What This Harness Is](#what-this-harness-is)
- [Why It Exists](#why-it-exists)
- [Core Model](#core-model)
- [Use Cases](#use-cases)
- [Install Patterns](#install-patterns)
- [After Install](#after-install)
- [Workflow Model](#workflow-model)
- [Client Commands](#client-commands)
- [Skill Packs](#skill-packs)
- [Prompt Recipes](#prompt-recipes)
- [Check, Doctor, And Verification](#check-doctor-and-verification)
- [Upgrade](#upgrade)
- [Platform Notes](#platform-notes)
- [Reference](#reference)

## Quickstart

### Remote install without manually opening the source repo

Use this when the harness source lives in GitHub, GitHub Enterprise, GitLab, Bitbucket, or another internal git host. `{Repo git}` is the harness repository URL for your environment.

```bash
tmp="$(mktemp -d)"
git clone --depth 1 --branch v0.5.0 {Repo git} "$tmp"
python3 "$tmp/scripts/install_harness.py" --interactive
```

The interactive installer asks for target path, adapters, profiles, skill packs, and whether to dry-run first. The same checkout records its git source provenance into the target install state, so future upgrades can use the same internal or external repo by default.

### Direct init from a checked-out source

```bash
python3 scripts/harness.py init --target /path/to/project
```

Default install:

- core planning skeleton
- Roo adapter
- generic profile
- `workflow-core` skill pack

### Fast validation

```bash
python3 scripts/harness.py check
python3 scripts/harness.py doctor
```

## What This Harness Is

This repository is the generalized low-reasoning agent harness source. It installs a small protocol into a target project so agents can:

- read durable planning state before acting
- separate discussion, planning, execution, and done audit
- avoid editing implementation code before explicit execute approval
- compose workflow skills by task instead of baking every behavior into one prompt
- verify changes with commands the target repository actually supports

The core protocol is client-neutral and stack-neutral. Roo and OpenCode are adapters, not sources of truth.

## Why It Exists

### Problem 1: The agent starts coding before the work is aligned

Agents often jump from a vague request to source edits. This harness forces `discuss -> plan -> execute -> done`, with planning docs and live gate state separating alignment from mutation.

### Problem 2: The agent forgets what matters

`.planning/**`은 canonical memory입니다. It records project structure, stack, conventions, active roadmap, phase plans, verification evidence, and decisions. The agent does not have to infer everything from scratch every turn.

### Problem 3: The agent edits outside the approved scope

`.scratch/phase-state.json`은 현재 작업을 열거나 막는 live gate일 뿐입니다. It says whether the active phase is approved for execution and which paths are allowed. `python3 scripts/harness.py check --worktree` catches staged, unstaged, and untracked changes outside the approved paths.

### Problem 4: One workflow does not fit every task

Skill pack은 플러그인입니다. Core stays small, while workflows like debugging, TDD, code review, security review, ETL, React, TypeScript, and MSSQL are selected only when useful.

## Core Model

The harness has four layers:

- **Core protocol**: `.planning/**`, `.scratch/phase-state.json`, checks, doctor, dashboard, AGENTS guidance.
- **Adapters**: `.roo/**`, `.opencode/**`, and client-specific command surfaces.
- **Profiles**: confirmed project environments such as `generic` or `dotnet-etl-mssql`.
- **Skill packs**: composable workflow and tech skills installed under `.agents/skills/**`.

Important ownership rule: source repository에는 `.agents/skills/**`가 없어도 정상입니다. Skills live in `harness/skill-packs/**` in the source and are installed into target repositories as selected plugins.

## Use Cases

### 사용 시나리오 빠른 선택

| Goal | Recommended install | Command | Starter prompt |
| --- | --- | --- | --- |
| 새 프로젝트에 기본 가드레일만 넣기 | default Roo or `--adapters roo` | `python3 scripts/harness.py init --target /path/to/project` | "아직 구현하지 말고 planning hydration만 해줘." |
| core-only 하네스 | no client adapter | `python3 scripts/harness.py init --target /path/to/project --adapters none` | "core planning docs만 만들고 adapter command는 설치하지 마." |
| OpenCode만 쓰기 | OpenCode adapter | `python3 scripts/harness.py init --target /path/to/project --adapters opencode` | "OpenCode discuss command 순서대로 읽고 phase 후보만 제안해." |
| Roo + OpenCode 동시 지원 | both adapters | `python3 scripts/harness.py init --target /path/to/project --adapters both` | "Roo/OpenCode 모두 같은 `.planning/**`과 live gate를 쓰는지 확인해." |
| .NET ETL/MSSQL | profile + tech packs | `python3 scripts/harness.py init --target /path/to/project --adapters both --profiles generic,dotnet-etl-mssql --packs workflow-core,tech-csharp,tech-mssql,workflow-etl,workflow-db-context` | "SQL Server persistence와 ETL restart/idempotency를 검증 계획에 넣어줘." |
| React/TypeScript web app | web tech packs | `python3 scripts/harness.py init --target /path/to/project --packs workflow-core,tech-react,tech-typescript,tech-tailwind,workflow-web-development` | "UI 변경은 browser verification까지 포함해서 plan을 세워줘." |
| 버그 진단 | debugging + TDD | `--packs workflow-core,workflow-debugging,workflow-tdd` | "증상 재현부터 최소화, 가설, 계측, 회귀 테스트 순서로 진행해." |
| 보안/권한/secret 변경 | security review | `--packs workflow-core,workflow-security-review,workflow-code-review` | "권한, secret exposure, rollback 관점으로 적대적 리뷰해." |
| 하네스 업그레이드 | remembered init scope | `python3 scripts/upgrade_harness.py --version v0.5.0 --dry-run` | "dry-run 결과와 conflict를 먼저 설명하고, force는 쓰지 마." |

## Install Patterns

### 기본 Roo 하네스

```bash
python3 scripts/harness.py init --target /path/to/project
```

### core-only 하네스

```bash
python3 scripts/harness.py init --target /path/to/project --adapters none
```

Installs the planning skeleton, `AGENTS.md`, target README, scripts, and selected `.agents/skills/**`, but no Roo or OpenCode adapter files.

### OpenCode 전용 하네스

```bash
python3 scripts/harness.py init --target /path/to/project --adapters opencode
```

OpenCode adapter는 의도적으로 phase primitive만 제공합니다. Detailed work such as debugging, TDD, review, or security comes from installed `.agents/skills/**` packs, not from many separate OpenCode commands.

### Roo + OpenCode 동시 지원

```bash
python3 scripts/harness.py init --target /path/to/project --adapters both
```

Equivalent alias:

```bash
python3 scripts/harness.py init --target /path/to/project --adapters roo,opencode
```

### Internal and external repo clarity

Use `{Repo git}` in shared docs and onboarding snippets. Examples:

```bash
tmp="$(mktemp -d)"
git clone --depth 1 --branch v0.5.0 {Repo git} "$tmp"
python3 "$tmp/scripts/install_harness.py" --interactive
```

For an internal mirror:

```bash
tmp="$(mktemp -d)"
git clone --depth 1 --branch v0.5.0 {Repo git} "$tmp"
python3 "$tmp/scripts/harness.py" init --target /path/to/project --adapters both
```

The value of `{Repo git}` can be public or private. Authentication is handled by `git clone` through SSH keys, SSO, credential helpers, or your company-approved mechanism.

## After Install

Run these from the target repository:

```bash
python3 scripts/check_harness.py
python3 scripts/doctor_harness.py
python3 scripts/show_phase_status.py
```

Then start with planning hydration. Roo를 설치했다면 `/phase-discuss planning-hydration --pass 0`로 시작합니다. OpenCode만 설치했다면 `.opencode/commands/discuss.md`를 사용하되 이 preflight를 먼저 적용합니다. Start with `python3 scripts/show_phase_status.py` when available. If it reports warnings, treat named files as minimum required reads before trusting the projection. If it is missing, fails, emits malformed output, or reports an unsupported contract version, use the legacy durable planning read order.

Fresh target first prompt:

```text
I want to apply this Roo/Codex harness to this existing repository.
Do not implement application changes yet.
Hydrate .planning/codebase/** and active phase documents from the real repository.
Ask only for product intent or phase-boundary decisions the repo cannot answer.
Stop after the discuss pass and summarize confirmed facts, inferred facts, open questions, and recommended next phase.
```

## Workflow Model

The intended loop is:

```text
discuss -> plan -> execute -> done
```

- **discuss**: understand the request, inspect repository evidence, identify phase candidates, and stop before implementation.
- **plan**: write allowed paths, blocked paths, verification commands, acceptance criteria, and adversarial review.
- **execute**: modify only approved paths after explicit approval.
- **done**: audit evidence, tests, diff, risks, and readiness before merge or push.

Every roadmap phase starts with its own `discuss` pass before `plan` or `execute`. Before finalizing phase commitments, run adversarial review and include the mandatory lens of whether the workflow is concrete enough for low-reasoning models.

active phase docs는 다음 순서로 해석합니다:

1. `.scratch/phase-state.json`
2. `.planning/STATE.md`
3. `.planning/ROADMAP.md`
4. `.planning/phases/<phase>/*-PLAN.md`
5. `.planning/phases/<phase>/*-CHECKPOINTS.md`
6. `.planning/phases/<phase>/*-VERIFICATION.md`

## Client Commands

### 클라이언트별 커맨드 모델

| Client | Discuss | Plan | Execute | Done / audit |
| --- | --- | --- | --- | --- |
| Roo | `/phase-discuss` | `/phase-plan` | `/phase-execute` | `/phase-execute` then done prompt |
| OpenCode | `.opencode/commands/discuss.md` | `.opencode/commands/plan.md` | `.opencode/commands/execute.md` | `.opencode/commands/done.md` |
| Generic agent | read `AGENTS.md` | write plan docs | obey live gate | run verification and summarize evidence |

Use `/phase-discuss` for phase discovery and planning hydration. Use `.opencode/commands/execute.md` only after the live gate says execution is approved.

OpenCode에서 버그 수정:

```text
Use `.opencode/commands/discuss.md` first.
Then use installed skills workflow-debugging,workflow-tdd.
Do not edit application code until the plan names allowed_paths and I approve execute.
```

## Skill Packs

skill pack은 플러그인입니다. Install only the packs the target project needs. If omitted, `workflow-core` is installed.

### Workflow core

- `repository-evidence-research`: read repo evidence first and separate confirmed facts, inferred facts, and rejected assumptions.
- `skill-plugin-composition`: select the smallest useful set of installed workflow skills for a task.
- `verification-contract`: choose concrete verification commands that exist in the target repository.
- `risk-review`: review rollback, upgrade safety, edge cases, and operational risk.
- `multi-agent-review`: split review across product/protocol, implementation, and release perspectives.
- `release-readiness-audit`: map release requirements to artifacts, tests, git evidence, and push state.
- `data-workflow`: reason about ingestion, transformation, validation, and generated datasets.
- `integration-boundary`: make external system contracts explicit.

### Workflow quality

- `workflow-tdd`: test-first red-green-refactor for features and fixes.
- `workflow-debugging`: reproduce, minimize, hypothesize, instrument, fix, and regression-test.
- `workflow-code-review`: review changes for bugs, regressions, missing tests, and maintainability.
- `workflow-skill-authoring`: design and validate new project-local skills.
- `workflow-security-review`: review auth, secrets, permission boundaries, dependency risk, and deployment exposure.

### Tech packs

- `tech-csharp`: C#/.NET build, test, nullable, and public-contract guidance.
- `tech-mssql`: SQL Server-backed persistence verification.
- `tech-postgresql`: PostgreSQL-backed persistence verification.
- `tech-python`: Python project conventions and verification.
- `tech-react`: React UI implementation and browser verification expectations.
- `tech-typescript`: TypeScript typecheck/build expectations.
- `tech-tailwind`: Tailwind styling constraints and maintainability.

### Domain workflows

- `workflow-etl`: source, extract, transform, validate, stage, load, observe, restart, idempotency, and backfill.
- `workflow-db-context`: DB context snapshot freshness, scope, and substitute documentation.
- `workflow-web-development`: frontend implementation, responsive behavior, and user-facing verification.
- `workflow-data-analysis`: reproducible analysis, assumptions, outputs, and checks.
- `workflow-data-processing`: parsing, transformation, generated artifacts, and validation.

## Prompt Recipes

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

### Windows 사용자에게 적용

```text
Windows 사용자에게 적용할 명령은 PowerShell 기준으로 써줘.
.sh 스크립트는 Linux/macOS 전용으로 보고, 하네스 핵심 검증은 scripts/harness.py check와 scripts/test_harness.py로 해.
경로는 Windows 절대경로를 그대로 쓰되, manifest나 planning 문서에는 repo-relative POSIX 스타일 경로를 기록해.
```

## Check, Doctor, And Verification

### 지원 환경과 명령 표기

| Platform | Unit tests | Source check | Smoke |
| --- | --- | --- | --- |
| Linux/macOS | `python3 -m unittest scripts/test_harness.py` | `python3 scripts/harness.py check` | `python3 scripts/release_smoke_test.py` |
| Windows PowerShell | `py -3 -m unittest scripts/test_harness.py` | `py -3 scripts/harness.py check` | `py -3 scripts/release_smoke_test.py` |
| Windows without launcher | `python -m unittest scripts/test_harness.py` | `python scripts/harness.py check` | `python scripts/release_smoke_test.py` |

`scripts/codex-cloud-setup.sh`는 Linux/macOS shell용입니다. Windows에서는 같은 효과를 내는 setup 명령을 PowerShell로 옮겨 실행하거나, core 명령인 `scripts/harness.py init/check/doctor`만 사용합니다.

### Source repository checks

Run before committing harness source changes:

```bash
python3 -m unittest scripts/test_harness.py
python3 scripts/harness.py check
python3 scripts/harness.py check --worktree
python3 scripts/release_smoke_test.py
```

### Target repository checks

Run from the harness source against a target:

```bash
python3 scripts/harness.py check --target /path/to/project
python3 scripts/harness.py check --target /path/to/project --adapter opencode
```

Run from an installed target:

```bash
python3 scripts/check_harness.py
python3 scripts/doctor_harness.py
```

### Worktree scope check

Implementation changes should pass:

```bash
python3 scripts/harness.py check --worktree
```

If this fails, the current diff has escaped the approved `allowed_paths`. Stop and return to planning.

## Upgrade

### Upgrade from a newer source checkout

```bash
python3 /path/to/newer-harness/scripts/harness.py upgrade --target /path/to/project --dry-run
python3 /path/to/newer-harness/scripts/harness.py upgrade --target /path/to/project
python3 /path/to/project/scripts/harness.py check
```

### Upgrade from the installed target bootstrapper

```bash
python3 scripts/upgrade_harness.py --version v0.5.0 --dry-run
python3 scripts/upgrade_harness.py --version v0.5.0
python3 scripts/check_harness.py
python3 scripts/doctor_harness.py
```

If install state has git source provenance, the bootstrapper uses that repo as the default. That means an internal mirror install upgrades from the same internal mirror unless overridden.

### Override repo for internal or external use

```bash
python3 scripts/upgrade_harness.py \
  --repo {Repo git} \
  --version v0.5.0 \
  --dry-run
```

### Local fallback when remote access is blocked

```bash
python3 scripts/upgrade_harness.py --source /path/to/newer-harness --version v0.5.0 --dry-run
```

### Adopt an older manual install

If a target has harness files but no `.harness/installed-manifest.json`, explicitly adopt before upgrade:

```bash
python3 /path/to/newer-harness/scripts/harness.py upgrade \
  --target "/path/to/manual project" \
  --adopt-existing \
  --adapters roo \
  --profiles generic \
  --packs workflow-core
```

Conflicts are written under `.harness/conflicts/`. Inspect them before using `--force`.

## Platform Notes

### Linux/macOS

Use `python3`. Shell examples assume bash-compatible syntax.

### Windows PowerShell

Use `py -3` when the Python launcher is installed:

```powershell
py -3 scripts/harness.py check
```

For clone/install, translate shell temp-dir syntax to PowerShell:

```powershell
$tmp = New-Item -ItemType Directory -Path ([System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), [System.Guid]::NewGuid()))
git clone --depth 1 --branch v0.5.0 {Repo git} $tmp.FullName
py -3 "$($tmp.FullName)\scripts\install_harness.py" --interactive
```

### Git authentication

The harness does not own git credentials. Public and private repo access both go through your normal `git clone` setup: SSH keys, credential helper, SSO, PAT, or internal tooling.

## Reference

### Repository structure

- `AGENTS.md`: source-repo agent instructions.
- `README.md`: source-repo user guide.
- `harness/manifest.json`: installable file manifest.
- `harness/skeleton/clean/**`: target project skeleton.
- `harness/profiles/**`: optional project profiles.
- `harness/skill-packs/**`: source skill packs installed into target `.agents/skills/**`.
- `.roo/**`: Roo adapter source.
- `.opencode/**`: OpenCode adapter source.
- `scripts/harness.py`: init, upgrade, check, doctor, release-check.
- `scripts/install_harness.py`: human-facing interactive installer.
- `scripts/upgrade_harness.py`: target-local upgrade bootstrapper.
- `scripts/check_harness.py`: target-local self-check.
- `scripts/doctor_harness.py`: target-local diagnostics.
- `scripts/show_phase_status.py`: live phase gate status.
- `scripts/release_smoke_test.py`: release matrix smoke test.

### Manifest and install state

`harness/manifest.json` selects files by adapter, profile, and pack. `init` records selected scope in `.harness/installed-manifest.json` as `init_options`. Later `upgrade` reuses that remembered scope unless you pass new `--adapters`, `--profiles`, or `--packs`.

### Managed files

Project-owned planning docs are not blindly overwritten. Harness-owned files update from the source manifest. Managed append files such as `.gitignore` and `AGENTS.md` use marker blocks where supported.

### Release checklist

Before a source release:

```bash
python3 -m unittest scripts/test_harness.py
python3 scripts/harness.py check
python3 scripts/harness.py check --worktree
python3 scripts/release_smoke_test.py
python3 scripts/harness.py release-check --expected-version v0.5.0
```

Record the evidence in the phase verification document before tagging or pushing.
