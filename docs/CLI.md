# CLI Reference

`scripts/harness.py` 가 모든 subcommand의 dispatcher. `harness_cli.py`가 console-script entry.

## Main subcommands

| Subcommand | Lib function | Purpose | Removal candidate? |
|---|---|---|---|
| `install` | `lib.hooks.install_pre_commit_hook()` | Pre-commit scope hook 설치 (T1-1) | KEEP |
| `init` | `lib.install.install()` | Clean skeleton + scopes 설치 | KEEP |
| `upgrade` | `lib.upgrade.upgrade()` | Harness-owned 파일 갱신 | KEEP |
| `check` | `lib.check.check()` | 19종 invariant 검증 | KEEP |
| `doctor` | `lib.doctor.doctor()` | Planning/adapter drift 진단 (read-only) | KEEP, simplify |
| `uninstall` | `uninstall_harness.py` | Scope 별 제거 | KEEP |
| `release-check` | `lib.version.release_check()` | 릴리즈 version/tag/worktree 게이트 | KEEP (release 시) |
| `state show` | `lib.state_cli.run_show()` | Phase-state projection 출력 | KEEP |
| `state repair` | `lib.state_cli.run_repair()` | Managed marker block 재생성 | KEEP |
| `phase set <target>` | `lib.phase_cli.cmd_phase_set()` | Phase 전이 | KEEP |
| `phase approve` | `lib.phase_cli.cmd_phase_approve()` | TTY-only [y/N] approval | KEEP |
| `phase reopen --to <p>` | `lib.phase_cli.cmd_phase_reopen()` | Backward 전이 + diary 회전 | KEEP |
| `phase next-pending` | `lib.phase_cli.cmd_phase_next_pending()` | 다음 미완 phase slug | KEEP |
| `session unlock` | `lib.phase_cli.cmd_session_unlock()` | Stale lock 해제 | KEEP |
| `status` | `lib.status_next_cli.cmd_status()` | Phase + halt + next action | KEEP |
| `next` | `lib.status_next_cli.cmd_next()` | Recommended next action | KEEP |
| `run` | `lib.status_next_cli.cmd_run()` | Safe step 실행, human 멈춤 | KEEP |

## 공용 flags

| Flag | Scope | Meaning |
|---|---|---|
| `--version v<X.Y.Z>` | global | Release version 오버라이드 |
| `--target <dir>` | most | 타겟 프로젝트 디렉토리 |
| `--dry-run` | init/upgrade/uninstall | Plan만 출력, 디스크 변경 없음 |
| `--force` | init/upgrade | Locally modified harness-owned 덮어쓰기 |
| `--adopt-existing` | upgrade | 기존 매뉴얼 설치 흡수 |
| `--adapters <list>` | init/upgrade | roo, opencode, both, none |
| `--profiles <list>` | init/upgrade | generic, dotnet-etl, python-etl, react-web |
| `--packs <list>` | init/upgrade | 명시 안 하면 profile에서 derive |
| `--db <db>` | init | mssql, postgresql, none |
| `--adapter <name>` | check | 추가 adapter 검증 |
| `--base <ref>` | check | Git base ref |
| `--worktree` | check | Staged/unstaged 변경 enforce |
| `--verify-hashes` | check | Per-policy hash 검증 (opt-in) |
| `--format <fmt>` | doctor/state show | markdown / json |
| `--quiet` | init/upgrade | Progress 억제 |
<!-- --approver-email removed in M5 #13 (ADR-0002: no allowlist enforcement; installer identity auto-derived) -->

## Top-level scripts (`scripts/*.py`)

| Script | Purpose | Removal? |
|---|---|---|
| `harness.py` | Main dispatcher (916 LOC) | KEEP |
| `harness_cli.py` (project root) | Console-script entry | KEEP |
| `check_harness.py` | `check` wrapper (45 LOC) | KEEP |
| `doctor_harness.py` | `doctor` wrapper (30 LOC) | KEEP, optional |
| `install_harness.py` | Interactive installer (259 LOC) | KEEP |
| `upgrade_harness.py` | Target-local upgrade bootstrapper (189 LOC) | KEEP |
| `uninstall_harness.py` | Uninstall flow (376 LOC) | KEEP |
| `release.py` | Develop→main merge, tag, push (217 LOC) | KEEP (release ops) |
| `release_harness.py` | release-check wrapper (27 LOC) | KEEP |
| `show_phase_status.py` | Phase status JSON (29 LOC) | KEEP |
| `project_dashboard.py` | HTML dashboard stub (10 LOC) | DROP or expand |
| `build_v094_fixture.py` | v0.9.4 fixture builder (423 LOC) | KEEP (active test dep) |
| `target_smoke_test.py` | Template: smoke tests for initialized targets (95 LOC). Distributed as `scripts/test_harness.py` during `harness init`. | KEEP |

## Smoke scripts (`scripts/smoke/`)

Live-trial harness removed Milestone 2. Remaining modules are diagnostics gates only.

| Module | Purpose |
|---|---|
| `grep_gate_stale_terms.py` | Stale term sweep (S14 full + launcher-only modes) |
| `grep_gate_slash_rename.py` | Slash-command rename regex gate |
| `grep_gate_release_terms.py` | Release-term adapter-only sweep |

## Git hooks (`.githooks/`)

| Hook | Behavior |
|---|---|
| `pre-commit` | main 브랜치는 README.md 변경만 허용, non-merge commit 차단. Merge source = develop/hotfix/* 만 |
| `commit-msg` | Main merge commit source 검증 |
| `pre-merge-commit` | Non-develop/non-hotfix merge 차단 |
| `pre-push` | Main push는 develop/hotfix merge commit만 허용 |

이 hook들은 **harness repo 자체의 git policy**용. 타겟에 심는 hook (scripts/lib/hooks.py)와 별개.

## 단순화 후 최소 CLI

```
harness init --target <dir> [--profiles ... --packs ... --adapters ...]
harness upgrade --target <dir> [--source <dir> | --repo <url> --ref <git-ref>]
                               [--dry-run --force --adopt-existing]
                               [--adapters ... --profiles ... --packs ...]
harness uninstall --target <dir>
harness check [--target <dir> --worktree --verify-hashes]
harness doctor [--target <dir>]
harness state show
harness state repair
harness phase set <discuss|plan|execute|done>
harness phase approve
harness phase reopen --to <plan|discuss> --reason <text>
harness phase next-pending
harness session unlock [--force]
harness status [--json]
harness next [--shell|--json]
harness run
```

**Removed**: `verify --audit` (Milestone 1), `migrate state` (Milestone 2 Item 1), `halt-diary clear` (Milestone 2 Item 7).

**Pending**: `release-check` (release ops 별도 도구로).
