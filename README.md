# 범용 저추론 에이전트 하네스

저추론 에이전트가 여러 종류의 프로젝트에서 같은 절차로 안전하게 일하도록 만드는 범용 하네스입니다.

핵심 목표는 특정 스택을 기본값으로 박아두는 것이 아닙니다. 기본 하네스는 중립적으로 유지하고, 프로젝트가 요구하는 기술과 작업 유형을 **pack 조합**으로 붙여서 같은 워크플로우를 재사용합니다.

```text
discuss -> plan -> execute -> done
```

## 핵심 개념

- `.planning/**`은 canonical memory입니다.
- `.scratch/phase-state.json`은 현재 작업을 열거나 막는 live gate일 뿐입니다.
- Roo, OpenCode는 adapter입니다. 프로젝트의 진실은 adapter 파일이 아니라 `.planning/**`에 있습니다.
- skill pack은 플러그인입니다. Python, C#, MSSQL, React 같은 기술 pack과 ETL, 웹 개발, 데이터 분석 같은 workflow pack을 필요에 맞게 조합합니다.
- 기본 설치는 stack-neutral입니다. Python, .NET, MSSQL, PostgreSQL, React 등을 자동으로 가정하지 않습니다.

## 설치 예시

### 1. 기본 Roo 하네스

```bash
python3 scripts/harness.py init --target /path/to/project
```

설치되는 것:

- core planning skeleton
- Roo adapter
- generic profile
- `workflow-core` skill pack

### 2. core-only 하네스

```bash
python3 scripts/harness.py init --target /path/to/project --adapters none
```

Roo나 OpenCode 없이 `.planning/**`, phase gate, 검증 스크립트만 설치합니다. 새 adapter를 붙이기 전 baseline 검증에 사용합니다.

설치되는 것:

- `AGENTS.md`
- `README.md`
- `.planning/**`
- `.scratch/phase-state.json`
- `.scratch/phase-state.schema.json`
- `docs/agents/**`
- `scripts/harness.py`

설치되지 않는 것:

- `.roo/**`
- `.roomodes`
- `.opencode/**`

### 3. Roo 전용 하네스

```bash
python3 scripts/harness.py init --target /path/to/project --adapters roo
```

설치되는 Roo 파일:

- `.roo/**`
- `.roomodes`

설치되지 않는 것:

- `.opencode/**`

### 4. OpenCode 전용 하네스

```bash
python3 scripts/harness.py init --target /path/to/project --adapters opencode
```

설치되는 OpenCode command:

- `.opencode/commands/discuss.md`
- `.opencode/commands/plan.md`
- `.opencode/commands/execute.md`
- `.opencode/commands/done.md`

Roo 파일이 없어도 유효한 타겟이어야 합니다.

### 5. Roo + OpenCode 동시 지원

```bash
python3 scripts/harness.py init --target /path/to/project --adapters roo,opencode
```

두 client가 같은 `.planning/**`과 `.scratch/phase-state.json`을 공유합니다. Roo와 OpenCode가 각자 별도 memory를 만들면 안 됩니다.

## Pack 조합 예시

### C#/.NET + MSSQL + ETL 프로젝트

예전 특화 하네스가 C#/.NET, MSSQL, ETL을 기본값으로 들고 있었다면, 이제는 다음처럼 pack으로 조합합니다. 예를 들어 타겟이 `.NET 10`을 명시하면 `tech-csharp`가 그 버전을 확인된 사실로 기록하지만, 하네스 core는 특정 .NET 버전을 기본값으로 만들지 않습니다.

```bash
python3 scripts/harness.py init \
  --target /path/to/dotnet-etl-project \
  --adapters roo,opencode \
  --profiles generic,dotnet-etl-mssql \
  --packs workflow-core,tech-csharp,tech-mssql,workflow-etl,workflow-db-context
```

이 조합이 제공하는 guardrail:

- `tech-csharp`: `.sln`, `.csproj`, `global.json`, 실제 .NET 버전, build/test command 확인
- `tech-mssql`: SQL Server 연결, migration, transaction, idempotency, rollback, 검증 방식 확인
- `workflow-etl`: source, transform, load target, restart, deduplication, backfill, schema drift 확인
- `workflow-db-context`: DB schema/context가 없으면 `needs-db-context`로 멈추고 추측 금지
- `verification-contract`: execute 전에 검증 명령과 증거를 live gate에 기록
- `risk-review`: 중요한 phase commitment 전 적대적 리뷰

중요한 점: 이 조합은 C# + MSSQL + ETL 프로젝트에만 활성화됩니다. 다른 프로젝트에 전역 기본값으로 새지 않습니다.

### Python 데이터 분석 프로젝트

```bash
python3 scripts/harness.py init \
  --target /path/to/python-analysis \
  --adapters opencode \
  --packs workflow-core,tech-python,workflow-data-analysis
```

이 조합은 Python을 “가정”하지 않습니다. `pyproject.toml`, `requirements.txt`, `uv.lock`, notebook, Python test file 같은 evidence가 있거나 사용자가 명시했을 때만 Python pack을 씁니다.

주요 skill:

- `repository-evidence-research`
- `tech-python`
- `workflow-data-analysis`
- `verification-contract`

이 조합이 확인하는 것:

- `pyproject.toml`, `requirements.txt`, `uv.lock`, notebook 존재 여부
- 데이터 입력 파일, schema, row count, null/중복 기준
- 분석 산출물의 재현 명령
- 민감정보와 샘플 데이터 경계
- notebook만 있는 경우 script/export 검증 가능 여부

### 데이터 처리 파이프라인

```bash
python3 scripts/harness.py init \
  --target /path/to/data-pipeline \
  --packs workflow-core,workflow-data-processing,workflow-etl,tech-postgresql
```

PostgreSQL이 확인된 데이터 처리/적재 프로젝트 예시입니다. MSSQL이면 `tech-mssql`, 언어나 런타임이 확인되면 `tech-python` 또는 `tech-csharp` 등을 추가합니다.

### React + TypeScript + Tailwind 웹 개발

```bash
python3 scripts/harness.py init \
  --target /path/to/web-app \
  --adapters roo,opencode \
  --packs workflow-core,tech-react,tech-typescript,tech-tailwind,workflow-web-development
```

이 조합이 확인하는 것:

- React가 실제로 쓰이는지
- TypeScript 설정과 typecheck command가 무엇인지
- Tailwind 버전, config, design token, responsive convention
- route/screen, loading/empty/error/success state
- build/test/browser smoke 검증

## 제공되는 Tech Pack

- `tech-python`
- `tech-react`
- `tech-typescript`
- `tech-tailwind`
- `tech-csharp`
- `tech-mssql`
- `tech-postgresql`

## 제공되는 Workflow Pack

- `workflow-core`
- `workflow-data-analysis`
- `workflow-data-processing`
- `workflow-etl`
- `workflow-web-development`

## workflow-core 기본 skill

`workflow-core`는 기본 설치되는 stack-neutral plugin 묶음입니다.

- `repository-evidence-research`: repo evidence를 먼저 읽고 확인된 사실/추론/거절된 가정을 분리
- `skill-plugin-composition`: 현재 phase에 필요한 skill만 최소 조합
- `verification-contract`: execute 전에 검증 명령, 증거, 실패 신호를 명시
- `risk-review`: phase gate, adapter, pack, 구현 계획을 적대적으로 리뷰
- `data-workflow`: 데이터 이동/형태/검증/민감정보를 스택 중립적으로 확인
- `integration-boundary`: API, DB, queue, filesystem, auth, 배포 경계 확인

## Skill Pack 조합 규칙

- `workflow-core`는 거의 항상 포함합니다.
- `tech-*` pack은 저장소 증거 또는 사용자 명시가 있을 때만 추가합니다.
- `workflow-*` pack은 작업 유형이 명확할 때 추가합니다.
- 여러 기술이 함께 쓰이면 필요한 만큼 조합합니다.
- 예: C# ETL이면 `tech-csharp` + `tech-mssql` + `workflow-etl`
- DB-backed ETL이면 `workflow-db-context`도 함께 포함합니다.
- 예: React UI이면 `tech-react` + `tech-typescript` + `tech-tailwind` + `workflow-web-development`
- 예: Python 분석이면 `tech-python` + `workflow-data-analysis`
- 알 수 없는 스택이면 `workflow-core`만 설치하고 Phase 0 hydration에서 evidence를 모읍니다.

## 검증 명령

소스 레포 검증:

```bash
python3 -m unittest scripts/test_harness.py
python3 scripts/harness.py check
```

타겟 검증:

```bash
python3 scripts/harness.py check --target /path/to/project
python3 scripts/harness.py check --target /path/to/project --adapter opencode
```

## 릴리스 전 확인 매트릭스

릴리스 전에 최소한 아래 설치 조합을 검증합니다.

```bash
python3 scripts/harness.py init --target /tmp/core --adapters none
python3 scripts/harness.py init --target /tmp/opencode --adapters opencode
python3 scripts/harness.py init --target /tmp/roo --adapters roo
python3 scripts/harness.py init --target /tmp/both --adapters roo,opencode
python3 scripts/harness.py init --target /tmp/python-analysis --adapters opencode --packs workflow-core,tech-python,workflow-data-analysis
python3 scripts/harness.py init --target /tmp/dotnet-etl --adapters roo,opencode --profiles generic,dotnet-etl-mssql --packs workflow-core,tech-csharp,tech-mssql,workflow-etl,workflow-db-context
python3 scripts/harness.py init --target /tmp/web --packs workflow-core,tech-react,tech-typescript,tech-tailwind,workflow-web-development
```

각 타겟에서 `python3 scripts/harness.py check`가 통과해야 합니다.

## 구조

```text
harness/
  manifest.json
  skeleton/clean/
  profiles/
  skill-packs/
.roo/          # Roo adapter
.opencode/    # OpenCode adapter
scripts/
docs/
```

## 설계 문서

자세한 protocol spec은 `docs/protocol-spec.md`에 있습니다.
