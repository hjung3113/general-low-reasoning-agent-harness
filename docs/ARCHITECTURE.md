# Architecture

전체 구조 요약. Refactor 의사결정 기준 문서.

## 전체 그림

```
general-low-reasoning-agent-harness/
├── harness_cli.py              # Console-script entry — sys.path 보강 후 scripts/harness.py:run() 호출
├── pyproject.toml              # name=general-low-reasoning-agent-harness, version=0.9.4
│                               # deps: rfc8785, psutil. entrypoint: harness=harness_cli:main
├── scripts/                    # 모든 Python 로직 (lib/ + 14개 top-level)
│   ├── harness.py              # CLI dispatcher (1031 LOC, argparse subparsers)
│   ├── lib/                    # 60개 모듈, ~21.5K LOC
│   └── smoke/                  # grep gates only (live-trial harness removed Phase 2)
├── harness/                    # 타겟에 심을 자원들
│   ├── skeleton/clean/         # AGENTS.md + README.md 템플릿 (project-owned 복사)
│   ├── profiles/               # generic / dotnet-etl / python-etl / react-web
│   ├── skill-packs/            # workflow-* (11) + tech-* (7) = 18 packs
│   └── manifest.json           # ~1357 lines: packs section + files manifest + removed_in_version
├── .harness/                   # 런타임 상태 (audit.log + backups/)
├── .scratch/                   # 런타임 상태 (phase-state.json + journals + locks)
├── .planning/                  # 타겟에서 만드는 state/roadmap (이 repo엔 없음 — wipe됐음)
├── .githooks/                  # 4개 hook: main 브랜치 정책 강제
├── tests/                      # 75개 테스트 파일 (60+ workflow, audit/security/infra)
└── docs/                       # (이 폴더 — 새로 작성됨)
```

## 코드 카테고리 (53 lib 모듈, 17.5K LOC) — Phase 1 complete

| Category | Modules | LOC | Status |
|---|---|---|---|
| WORKFLOW_CORE | 12 | 5,045 | ✅ KEEP |
| INSTALL | 13 | 4,390 | ✅ KEEP |
| INFRA | 11 | 2,819 | ✅ KEEP (fs_fence removed) |
| DIAGNOSTICS | 8 | 3,606 | 🔄 TRIM (smoke pending) |
| SECURITY | 5 | 1,550 | ✅ KEEP (9→5 modules) |
| CLI_DISPATCH | 4 | 1,515 | 🔄 (halt_diary_cli pending) |

**Total**: 53 lib + 12 scripts/*.py = 65 Python files, ~19K LOC.

**Phase 1 reduction**: 60→53 modules, ~21.5K→17.5K LOC lib, ~980 test files removed.

## Tier dependency graph (no cycles) — Phase 1 updated

```
Tier 1 (no lib deps):
  atomic_io, durable_fs, safe_open, backups, timestamps, exitcodes, progress,
  operational_paths, audit, audit_chain, audit_rotation,
  phase_state, phase_lock, phase_txn, phase_preflight, planning_grammar,
  transition, roadmap_state, managed_block, profiles, hooks, version

Tier 2 (Tier 1만 의존):
  manifest, append_block, state, install_recovery, state_trust,
  phase_approve, phase_reopen, planning_status, status_next,
  session, state_diagnostics, workflow_static_checks, state_repair

Tier 3:
  install, adoption, check, doctor,
  phase_cli, status_next_cli, state_cli, halt_diary_cli, cli_budgets

Tier 4 (heaviest aggregator):
  upgrade (adoption + install + manifest_reconciler + manifest_v2 + ...)
```

**Removed in Phase 1**: secret_key, cli_deprecated, fs_fence, autopilot_guard, audit_verify_cli, release_trust (sec-7b orphan).
**Removed in Phase 2**: state_migrate, state_migrate_t04, migrate_state (v0→v2 migration — all state is now v2).

## Two-axis 분류: workflow vs deployment

- **Workflow enforcement axis** (이 프로젝트 존재 이유):
  phase state machine + planning grammar + roadmap sync + check + AGENTS.md skeleton.
  타겟 프로젝트에 심어진 후 저성능 모델이 따라야 하는 워크플로우 강제.
- **Deployment axis** (하네스 자체 배포):
  install/upgrade/uninstall + manifest + adapters (.roo/.opencode) + profiles + skill-packs.
  하네스를 다른 repo에 심고 갱신하는 메커니즘.

두 축은 강하게 분리되어 있으나 일부 모듈(예: `hooks.py`)이 양쪽 다 건드림.

## Entry point chain

```
pip install -e . → harness_cli:main (pyproject script)
       ↓
harness_cli.py:main() — sys.path.insert(scripts/) → import harness
       ↓
scripts/harness.py:run(argv) — argparse + subcommand dispatch
       ↓
lib.install / lib.upgrade / lib.phase_cli / lib.check / ...
```

`python3 scripts/harness.py` 직접 호출도 지원 (bare `from lib.X import` 패턴 때문에 sys.path 보강 필요).

## Adapter system

| Adapter | Output dir | Purpose |
|---|---|---|
| `roo` | `.roo/` | Roo Code adapter — commands/, rules/, skills/ |
| `opencode` | `.opencode/` | OpenCode adapter — commands/, profile-rules/ |

Manifest entry는 `adapter` 필드로 선택 필터링 (`select_entries()` in manifest.py).

## 참고 문서 (이 폴더)

- `WORKFLOW.md` — phase gate, planning, roadmap (KEEP 대상 상세)
- `SECURITY-INVENTORY.md` — 모든 보안/trust 기능 + 제거 후보 ranking
- `INSTALL-MODEL.md` — install/upgrade/manifest/adapter
- `CLI.md` — 모든 subcommand 표
- `MODULE-MAP.md` — 60 lib 모듈 카테고리 매핑
- `TESTS.md` — 75 테스트 파일 카테고리
