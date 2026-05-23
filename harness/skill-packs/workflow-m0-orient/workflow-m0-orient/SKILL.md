---
name: workflow-m0-orient
description: Mandatory first-milestone (M0) orientation. Auto-detects existing-code vs greenfield, fills .planning/codebase/ and seeds future milestone skeletons. Run before any feature work.
writes:
  - codebase.summary.*
  - codebase.conventions.*
  - codebase.concerns.*
  - codebase.architecture.*
  - codebase.stack.*
  - codebase.structure.*
  - codebase.testing.*
  - codebase.integrations.*
reads:
  - codebase.stack.*
  - codebase.structure.*
  - codebase.testing.*
  - codebase.integrations.*
---

# Workflow M0 Orient

## ⛔ STOP — DO NOT WRITE SOURCE CODE

This skill runs during **Milestone 0** orientation. ONLY allowed outputs: `.planning/codebase/*.md`, `.planning/ROADMAP.md`, `.planning/milestones/00-orientation/*`, `.planning/STATE.md` (via `harness state repair`).

**FORBIDDEN**: `index.html`, `*.css`, `*.js`, `*.py`, `package.json`, `src/**`. If user asks for code now, REFUSE and say: "M0 (orientation) 끝나야 code 시작 가능. 먼저 .planning/codebase/ 채우고 M1 (Implementation) 으로 advance." **User instruction does NOT override M0 gate.**

Mandatory entry skill for Milestone 0. M0 closes only when codebase orientation is complete (ADR-0009). `harness check` refuses M1+ work until M0 done criteria pass.

## Path detection

Detect signals via Bash before deciding path:

```bash
ls package.json pyproject.toml Cargo.toml go.mod Gemfile pom.xml 2>/dev/null
ls *.csproj 2>/dev/null
find src lib app -maxdepth 2 -type f 2>/dev/null | head -1
```

If ANY signal present → **Existing Code Path**.
If NO signal → **Greenfield Path**.

## Existing Code Path

1. **Run `harness recon`**.

   ```bash
   harness recon --target .
   ```

   Fills `STACK.md`, `STRUCTURE.md`, `TESTING.md` (frameworks + commands), and `INTEGRATIONS.md` (if external integrations detected). If the command fails or is missing, STOP and report the exact error.

2. **Fill `CONVENTIONS.md`** — read lint configs (`.eslintrc`, `pyproject.toml`, `prettier`), grep for common patterns, check 3–5 source files. Anchors:
   - `codebase.conventions.formatting` / `.naming` / `.imports` / `.errors` / `.logging` / `.git` / `.review`

3. **Fill `CONCERNS.md`** — grep TODO/FIXME, scan flaky-test markers, identify security-sensitive paths. Anchors:
   - `codebase.concerns.high_risk` / `.tech_debt` / `.flaky_tests` / `.security` / `.performance` / `.open_questions`

4. **Fill agent-owned `TESTING.md` anchors** — `codebase.testing.scopes`, `.fixtures`, `.repro`, `.known_failures`.

5. **Optionally fill `ARCHITECTURE.md`** — skip if codebase too small. ASCII diagram + components table.

6. **Fill `SUMMARY.md`** — synthesize from the above:
   - `codebase.summary.identity` (2-3 sentences)
   - `codebase.summary.quickstart` (install + run cmd)
   - `codebase.summary.test` (primary test cmd, copy from TESTING)
   - `codebase.summary.map` (3-5 key edit paths)
   - `codebase.summary.concerns` (top 3 from CONCERNS)
   - `codebase.summary.links`

7. **Update frontmatter** on edited files: `status: current`, `updated_at: <today>`, `source: human` or `mixed`, `ownership: agent` (or `hybrid` for TESTING).

8. **Close M0** — see "Close M0" below.

## Greenfield Path

No code yet. Interview the user grill-style to crystallize intent. Same 8 files, same anchors, but `source: human` and content is forward-looking.

1. **Project identity** (`codebase.summary.identity`):
   - 한 줄로 이 프로젝트가 무엇인가?
   - 주요 사용자는 누구인가?

2. **Tech intent** (`codebase.stack.*`):
   - 어떤 언어/런타임? → `runtime`, `languages`
   - 패키지 매니저? → `package_managers`
   - 테스트 프레임워크 결정했나? → `test`
   - CI 시스템? → `ci`

3. **Structure intent** (`codebase.structure.*`):
   - 디렉토리 layout 계획? — describe planned tree
   - 어떤 경로를 가장 자주 편집할 것 같나? → `key_paths`

4. **Testing strategy** (`codebase.testing.*`):
   - 테스트 전략? (unit/integration/e2e) → `scopes`
   - 정해진 테스트 실행 명령? → `commands`

5. **Conventions** (`codebase.conventions.*`):
   - 네이밍 규칙? (camelCase/snake_case/kebab-case)
   - 포맷터/린터?
   - Git branching model?

6. **Concerns** (`codebase.concerns.*`):
   - 예상되는 high-risk 영역?
   - 사전에 알고있는 제약?
   - 모든 unknown은 `codebase.concerns.open_questions`에 TODO 로

7. **Integrations** (only if non-trivial — `codebase.integrations.*`):
   - DB 쓸 예정? 어떤 거?
   - 외부 API?
   - Auth 방식?

8. **Architecture** (optional — skip if too early):
   - 전체 system 모양 한 paragraph

9. **Roadmap** — ask for planned milestones:
   - 총 몇 개 milestone 으로 나눌 예정?
   - 각각: 짧은 title + 1-line summary
   - `.planning/ROADMAP.md` 에 `- [ ] **Milestone N: Title** - summary` bullets 추가

10. **Update frontmatter**: `status: current`, `source: human`, `ownership: agent`, `updated_at: <today>`.

11. **Close M0** — see below.

## Close M0

After both paths reach this point:

1. **Verify done criteria** (also enforced by `harness check`):
   - All 6 core `.planning/codebase/*.md` have `status: current`
   - `.planning/ROADMAP.md` has at least 1 future milestone bullet
   - `.planning/STATE.md` ready to advance to Milestone 1

2. **Generate skeleton folders** for each planned milestone in ROADMAP.md:

   For each `- [ ] **Milestone N: <Title>** - <summary>` bullet in ROADMAP.md, create:
   - `.planning/milestones/NN-slug/NN-CONTEXT.md` — 2-3 sentences from ROADMAP summary + `<!-- discuss phase will expand -->`
   - `.planning/milestones/NN-slug/NN-CHECKPOINTS.md` — `- [ ] CP-NN-01 — <first concrete step>` placeholder

3. **Advance STATE**:
   - Update `.planning/STATE.md` Current Position to Milestone 1
   - Run `harness state repair` to refresh managed blocks
   - Run `harness phase set discuss` to enter M1 discuss phase

## Stop Conditions

- `harness` CLI missing or wrong version (existing path)
- User refuses interview (greenfield path)
- Cannot resolve project identity (both paths)
- Mixed signal (partly-existing-partly-empty) — STOP and ask user which path

## Worked Examples

**Existing Python repo**: lockfile detected → `harness recon` fills STACK (Python, pytest, GH Actions) + STRUCTURE (depth-2 tree) + TESTING.commands (`pytest`) → agent reads `pyproject.toml [tool.ruff]` and fills CONVENTIONS.formatting → agent greps `TODO\|FIXME` and fills CONCERNS.tech_debt → SUMMARY synthesized → close M0, write `01-feature-x/01-CONTEXT.md` skeleton.

**Greenfield idea**: no files. Interview yields `runtime: Node.js`, `package_managers: pnpm (planned)`, `test: vitest (planned)`, `naming: kebab-case files / camelCase functions`, ROADMAP has 3 planned milestones → write codebase files with `source: human`, skeleton folders `01-*`, `02-*`, `03-*`, STATE advances to M1.
