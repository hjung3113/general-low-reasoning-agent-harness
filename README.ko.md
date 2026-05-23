# general-low-reasoning-agent-harness

저성능 AI 코딩 에이전트가 `discuss → plan → execute → done` 워크플로우를 강제적으로 따르도록 만드는 **하네스(harness)** 를 타겟 프로젝트에 설치하는 Python CLI.

사내 도구. 신뢰된 개발자/머신 가정, 외부 공격자 없음 ([`docs/adr/0002-internal-tool-threat-model.md`](docs/adr/0002-internal-tool-threat-model.md)).

용어 ("harness", "skeleton", "skill-pack", "phase", "milestone" 등) 정의는 [`CONTEXT.md`](CONTEXT.md). 설치된 하네스를 일상적으로 사용하는 법은 [`MANUAL.ko.md`](MANUAL.ko.md).

English version: [`README.md`](README.md).

## 하네스를 설치하면 타겟에 생기는 것

| 경로 | 소유자 | 용도 |
|---|---|---|
| `.harness/` | 하네스 생성 | 런타임: install-record, audit log |
| `.scratch/` | 하네스 생성 | 런타임: phase state, locks, session files |
| `.planning/ROADMAP.md`, `.planning/STATE.md` | 타겟 소유 | 사용자가 직접 작성하는 로드맵 + 현재 상태 |
| `.planning/phases/NN-*/` | 타겟 소유 | 마일스톤별 planning 문서 |
| `AGENTS.md` | 혼합 (managed block + 프로젝트 영역) | 에이전트용 규칙 + 프로젝트 메모 |
| `README.md` | 최초 시드 후 타겟 소유 | 프로젝트 README 출발점 |
| `.roo/`, `.opencode/` (선택) | 어댑터 소유 | 에디터/에이전트 통합 어댑터 |

전체 파일 목록 (manifest 에서 생성됨): [`docs/ARTIFACTS.md`](docs/ARTIFACTS.md).

## 설치

### Clone 후 설치

```bash
git clone https://github.com/hjung3113/general-low-reasoning-agent-harness.git
cd general-low-reasoning-agent-harness
pip install -e .
```

`harness` 콘솔 스크립트가 설치됨.

### 타겟 프로젝트에 init

```bash
harness init --target /path/to/your/project \
  --profiles generic \
  --adapters none
```

`--profiles`, `--adapters` 는 선택. 기본값: `generic` 프로파일, 어댑터 없음. Profile/pack 합성 규칙:

```
profile (1개)        →  default skill-packs (N개)
db (선택)            →  db skill-packs (M개)
--packs flag         →  수동 추가 (K개)
최종 = 셋의 합집합 (additive — `--packs` 가 default 를 대체 ❌)
```

사용 가능한 profile: `generic`, `dotnet-etl`, `python-etl`, `react-web`.
사용 가능한 DB pack: `mssql`, `postgresql`, `none`.

### First-run TTY 확인

`harness init` 은 기본적으로 interactive. `[y/N]` 프롬프트로 *누가* 하네스를 초기화했는지 `.harness/install-record.json` 에 기록. **권한 부여가 아니라 attribution 만 기록** — approver allowlist 없음 ([`docs/adr/0002-internal-tool-threat-model.md`](docs/adr/0002-internal-tool-threat-model.md)).

CI/스크립트에서 비대화식으로 attribution 지정: `--approver-email user@example.com`.

### 설치 검증

```bash
cd /path/to/your/project
harness check
harness status
```

`check` = 구조/정책 검증. `status` = 현재 phase, 다음 action, halt 여부 표시.

## Upgrade

새 버전 하네스 출시 시:

```bash
cd /path/to/your/project
harness upgrade
```

같은 버전이면 no-op. 같은 버전에서 manifest 강제 재적용: `--force`. `manifest.removed_in_version` 의 `upgrade_action: delete` 파일은 삭제됨. `warn` 정책 파일은 stderr 경고 후 보존. **타겟 소유 파일은 절대 자동 삭제 안 됨** ([`docs/adr/0006-install-upgrade-adoption-flow-predicates.md`](docs/adr/0006-install-upgrade-adoption-flow-predicates.md)).

## Adoption (수동 설치 흡수)

이전에 skeleton 파일을 수동으로 두었거나 `.harness/install-record.json` 이 없는 경우:

```bash
harness upgrade --adopt-existing
```

기존 파일을 install 의 출발점으로 인정하고 install-record 작성. 모호한/부분 상태는 자동 라우팅 거부 — 명시적 opt-in 필요.

## Uninstall

```bash
harness uninstall --scope all
```

하네스 소유 파일 제거. `--scope` 로 부분 선택 가능: `harness`, `planning`, `scratch`, `adapters`, `agents`, `all`.

## CLI 빠른 참조

| 명령 | 용도 |
|---|---|
| `harness init` | 타겟에 새로 설치 |
| `harness upgrade` | 하네스 소유 파일 갱신 |
| `harness check` | 구조/정책 검증 |
| `harness status` | Phase + 다음 action |
| `harness next` | 다음 권장 action |
| `harness uninstall` | 하네스 scope 제거 |
| `harness doctor` | 읽기 전용 drift 진단 |

전체 CLI 참조: [`docs/CLI.md`](docs/CLI.md).

## 프로젝트 구조

```
.
├── harness_cli.py          # console-script entry
├── pyproject.toml          # 패키지 메타
├── scripts/                # 모든 Python 로직
│   ├── harness.py          # CLI dispatcher
│   └── lib/                # 50 modules
├── harness/
│   ├── skeleton/clean/     # 템플릿 파일 (AGENTS.md, README.md)
│   ├── profiles/           # generic, dotnet-etl, python-etl, react-web
│   ├── skill-packs/        # 14 packs: 4 tech-* + 10 workflow-*
│   └── manifest.json       # 설치/제거 파일의 source of truth
├── CONTEXT.md              # 용어집
├── docs/
│   ├── ARTIFACTS.md        # manifest 에서 생성됨
│   ├── ARCHITECTURE.md
│   ├── CLI.md
│   ├── WORKFLOW.md
│   ├── INSTALL-MODEL.md
│   └── adr/                # 6 ADRs (standing decisions)
└── tests/                  # 전체 테스트 스위트
```

## 기여

작업 마일스톤 = GitHub milestone + issue 로 관리 (`hjung3113/general-low-reasoning-agent-harness`). [`docs/agents/issue-tracker.md`](docs/agents/issue-tracker.md), [`docs/agents/triage-labels.md`](docs/agents/triage-labels.md) 참조. 마일스톤별 plan: [`.planning/phases/NN-*/`](.planning/phases/).

의사결정 이력: [`docs/adr/`](docs/adr/).
