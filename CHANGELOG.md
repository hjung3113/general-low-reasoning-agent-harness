# Changelog

All notable changes to this harness.

본 문서는 `develop` branch 기준 누적. 정식 릴리스 태그는 `main` branch + `vMAJOR.MINOR.PATCH`로 표시.

## Unreleased (develop)

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
- **L12 — Migrator `--resume` verb (crash recovery, ADR G1-E).**
  `scripts/migrate_state.py` ships with `--forward`, `--reverse`, and
  `--resume` sub-verbs. `--forward` and `--reverse` refuse to overwrite an
  existing `.bak` (`O_EXCL`); `--resume` reads the sidecar
  `.harness/backups/<basename>.pre-repair.<...>.bak.resume.json` and either
  re-runs the partial migration or declares it complete by hash.

Note: this slice preserves the `## Unreleased (develop)` heading verbatim;
normalization to `## [Unreleased]` (Keep-a-Changelog) is deferred to T3.

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
