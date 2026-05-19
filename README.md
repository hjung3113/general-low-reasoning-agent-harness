# 범용 저추론 에이전트 하네스 (harness source)

저추론 코딩 에이전트(Roo, OpenCode, Haiku 수준 모델)가 실제 저장소에서 안전하게 일하도록 만드는 재사용 가능한 하네스.
Target repository에 planning state, phase gate, adapter command, workflow skill, verification contract를 설치합니다.

**대상**: harness를 설치하거나 하네스 자체를 개발/유지하는 사람.
이미 설치된 하네스를 사용하는 팀원은 → [docs/USER_MANUAL.md](docs/USER_MANUAL.md)

최근 변경 사항은 [CHANGELOG.md](CHANGELOG.md)를 참고하세요.

---

## 1. 이 저장소

이 repo는 harness source이며, 직접 사용하는 제품이 아닙니다.
`scripts/harness.py init`으로 **target repository**에 설치하면 그 target에서 일상 작업이 이루어집니다.

v0.8.2의 일상 CLI 표면은 네 개입니다:

```bash
harness
harness next
harness run
harness check
```

`harness`는 짧은 가이드를 보여줍니다. `harness next`는 다음 안전 행동을 설명하고, `harness run`은 자동으로 해도 안전한 workflow 단계만 진행하다가 사람 승인이 필요하면 멈춥니다. `harness check`는 현재 하네스/계획 상태를 검증합니다.

`phase`, nonce, audit anchor, state repair, autopilot 같은 저수준 명령은 advanced/debug/CI 표면입니다. 보통 사용자와 어댑터는 이를 직접 실행하지 않습니다.

유즈케이스별 한글 안내는 [docs/use-cases/README.md](docs/use-cases/README.md)에서 시작하세요. UML 흐름은 [docs/minimal-workflow-sequence.md](docs/minimal-workflow-sequence.md), 상태 머신은 [docs/minimal-workflow-state-machine.md](docs/minimal-workflow-state-machine.md)에 있습니다.

핵심 가치:
- 저추론 에이전트가 합의 없이 바로 코딩하는 문제를 `discuss → plan → execute → done` phase gate로 차단
- Planning state(`.planning/**`)를 canonical memory로 유지
- 승인된 경로 밖 수정을 worktree check로 차단
- 필요한 workflow skill만 선택 설치

---

## 2. 빠른 설치

> **표기 컨벤션 (이 문서 전반)**
> - `/path/to/project` — target repository의 absolute path (사용자가 치환)
> - `$tmp` — `mktemp -d`로 만든 임시 디렉터리 (harness source clone 위치)
> - `v0.7.x` — 현재 release tag placeholder (실제 명령에서는 구체 버전으로 치환)
> - `python3` — Windows에서는 `py -3` 또는 `python`으로 대체

원격 source를 직접 열지 않고 한 번에 설치:

```bash
tmp="$(mktemp -d)"
git clone --depth 1 --branch v0.8.2 https://github.com/hjung3113/general-low-reasoning-agent-harness.git "$tmp"
python3 "$tmp/scripts/install_harness.py" --interactive
```

Interactive installer는:
1. Absolute path를 가진 existing target directory를 받습니다.
2. Adapter(`roo`/`opencode`/`both`/`none`)와 profile(`generic`/`dotnet-etl`/`python-etl`/`react-web`)을 묻습니다.
3. Profile이 `generic`이 아니면 database 축(`mssql`/`postgresql`/`none`)을 추가로 묻습니다.
4. 기본 포함 skill pack을 보여주고 추가 pack을 선택하게 합니다.

설치 후 target 안에서 첫 점검:

```bash
python3 scripts/harness.py
python3 scripts/harness.py next
python3 scripts/harness.py check
```

Windows 사용자는 `python3` 대신 `py -3` 또는 `python`을 사용하세요.

**설치 후 일상 사용법** → [docs/USER_MANUAL.md](docs/USER_MANUAL.md)

---

## 3. 사용 시나리오 빠른 선택 (설치 패턴)

| 목적 | 추천 설치 | 명령 |
| --- | --- | --- |
| 새 프로젝트에 기본 가드레일만 넣기 | 기본 Roo | `python3 scripts/harness.py init --target /path/to/project` |
| core-only 하네스 | adapter 없음 | `python3 scripts/harness.py init --target /path/to/project --adapters none` |
| OpenCode만 쓰기 | OpenCode adapter | `python3 scripts/harness.py init --target /path/to/project --adapters opencode` |
| Roo + OpenCode 동시 지원 | both adapters | `python3 scripts/harness.py init --target /path/to/project --adapters both` |
| .NET ETL | `dotnet-etl` profile | `python3 scripts/install_harness.py --interactive` |
| Python ETL | `python-etl` profile | `python3 scripts/install_harness.py --interactive` |
| React/TS/Tailwind web app | `react-web` profile | `python3 scripts/install_harness.py --interactive` |
| ETL with SQL Server | `dotnet-etl` + `--db mssql` | `python3 scripts/harness.py init --target ... --profiles dotnet-etl --db mssql` |
| 버그 진단 | debugging + TDD | `--packs workflow-core,workflow-debugging,workflow-tdd` |
| 보안/권한/secret 변경 | security review | `--packs workflow-core,workflow-security-review,workflow-code-review` |
| 하네스 업그레이드 | remembered init scope | `python3 scripts/upgrade_harness.py --version v0.8.2 --dry-run` |
| 하네스 일부 제거 | uninstall scopes | `python3 scripts/uninstall_harness.py --interactive` |

사내/외부 repo 헷갈리지 않는 설치 예시:

```bash
tmp="$(mktemp -d)"
git clone --depth 1 --branch v0.8.2 https://github.com/hjung3113/general-low-reasoning-agent-harness.git "$tmp"
python3 "$tmp/scripts/harness.py" init --target /path/to/project --adapters both
```

---

## 4. 저장소 구조

```
scripts/                   harness CLI와 설치 도구
  harness.py               thin CLI dispatcher (normal: harness/next/run/check; advanced: init, upgrade, phase, state, …)
  install_harness.py       human-facing interactive installer
  upgrade_harness.py       target-local upgrade bootstrapper
  uninstall_harness.py     target-local uninstall helper
  check_harness.py         target-local self-check
  doctor_harness.py        target-local diagnostics
  release_smoke_test.py    release matrix smoke test
  release.py               develop → main → tag → push → GitHub release 자동화
  test_harness.py          단위 테스트 (unittest)
  lib/                     role-split 모듈
    version.py, profiles.py, manifest.py, append_block.py
    state.py, roadmap_state.py, worktree.py
    adoption.py, check.py, doctor.py
    install.py, upgrade.py
    roomodes_writer.py, planning_status.py, workflow_static_checks.py
    managed_block.py, state_repair.py, state_cli.py
    audit.py, exitcodes.py, phase_lock.py, safe_open.py

harness/                   설치 대상 파일
  manifest.json            adapter/profile/pack 기준 설치 파일 목록
  skeleton/clean/**        target project 기본 골격
  profiles/**              optional project profiles (dotnet-etl, python-etl, react-web)
  skill-packs/**           source skill packs (설치 시 .agents/skills/**로 복사)
    workflow-core, workflow-tdd, workflow-debugging
    workflow-code-review, workflow-security-review, workflow-skill-authoring
    workflow-etl, workflow-db-context, workflow-web-development
    workflow-data-analysis, workflow-data-processing
    tech-python, tech-csharp, tech-typescript, tech-react, tech-tailwind
    tech-mssql, tech-postgresql

.roo/                      Roo adapter source (.roo/commands/, .roomodes)
.opencode/                 OpenCode adapter source (.opencode/commands/)

docs/                      문서
  USER_MANUAL.md           설치된 하네스 end-user 설명서
  trust/                   release tag signing (allowed-signers, README)
  superpowers/specs/       설계 사양 문서
  phase-gate-harness.md    phase gate 개념 + ROADMAP/STATE 구조
  protocol-spec.md         core protocol 레퍼런스
  adr/                     Architecture Decision Records

.planning/                 하네스 자체 planning state (dogfooding)
.scratch/                  하네스 자체 live gate
tests/                     추가 테스트 스위트
```

**중요한 ownership 규칙**: source repository에는 `.agents/skills/**`가 없어도 정상입니다.
`harness/skill-packs/**`가 source이며, install 시 선택한 pack만 target의 `.agents/skills/**`로 복사됩니다.

---

## 5. 개발자 가이드

### 테스트

```bash
# 단위 테스트
python3 -m unittest scripts/test_harness.py

# 전체 pytest
python3 -m pytest tests/ -q

# Release smoke test
python3 scripts/release_smoke_test.py
```

| Platform | 단위 테스트 | Source check | Smoke |
| --- | --- | --- | --- |
| Linux/macOS | `python3 -m unittest scripts/test_harness.py` | `python3 scripts/harness.py check` | `python3 scripts/release_smoke_test.py` |
| Windows PowerShell | `py -3 -m unittest scripts/test_harness.py` | `py -3 scripts/harness.py check` | `py -3 scripts/release_smoke_test.py` |

### Check

Source repo 자체에도 harness check를 적용할 수 있습니다 (dogfooding):

```bash
python3 scripts/harness.py check
python3 scripts/harness.py check --worktree
```

### 릴리스 절차 (요약)

```bash
# 1. Release gate 검증
python3 -m unittest scripts/test_harness.py
python3 scripts/harness.py check
python3 scripts/harness.py check --worktree
python3 scripts/release_smoke_test.py
python3 scripts/harness.py release-check --expected-version v0.8.2

# 2. Tag 서명 (SSH key)
git config user.signingKey ~/.ssh/id_ed25519
git config gpg.format ssh
git tag -s v0.8.2 -m "Release v0.8.2"
git push origin v0.8.2
```

상세 tag signing/trust root 절차는 [docs/trust/README.md](docs/trust/README.md) 참고.

### 기여 가이드

- PR 흐름: feature branch → PR → review → squash merge
- 커밋 컨벤션: `feat(scope): ...`, `fix(scope): ...`, `docs(scope): ...`
- Phase gate 자체 적용: 이 저장소도 `.planning/**` + `.scratch/phase-state.json`을 사용해 harness를 dogfooding합니다. 현재 phase를 확인하고 phase gate를 준수하세요.

---

## 6. 업그레이드 / 제거

상세 절차는 [docs/USER_MANUAL.md §C3 업그레이드](docs/USER_MANUAL.md#c3-업그레이드), [§7 제거](docs/USER_MANUAL.md#7-제거) 참고.

빠른 포인터:

```bash
# 업그레이드 (dry-run 먼저)
python3 scripts/upgrade_harness.py --version v0.8.2 --dry-run
python3 scripts/upgrade_harness.py --version v0.8.2

# 제거
python3 scripts/uninstall_harness.py --interactive
```

---

## 7. 변경 이력

→ [CHANGELOG.md](CHANGELOG.md)

**v0.8.2 Workflow UX Hardening** — `show_phase_status.py`의 `next_steps`, 어댑터 상태 템플릿, 승인 경계 문서를 보강했습니다.

**한글 유즈케이스 문서 Hotfix** — 유즈케이스별 한글 문서를 `docs/use-cases/`로 분리하고, 최소 워크플로 UML 문서 2개를 한글로 정리했습니다.

**Known Limitations** — to be fully addressed in the next minor release:
- The current release tag is **not** SSH-signed; `docs/trust/allowed-signers` ships as a placeholder. Treat the trust root as scaffold-only until a maintainer key is published and tags are signed. Do not rely on `git verify-tag` until the next minor release.
- Audit-chain `previous_entry_hash` GENESIS fallback (`audit_chain.compute_entry_hash`) permits suffix-rewrite by a local writer with code execution as the user. The out-of-repo anchor mitigates but is keyed in the same user's home — defense-in-depth only. Full integrity hardening lands in the next minor release.
- Approval-nonce TTY-isolation accepts `--consumer-tty` from argv rather than server-verifying `os.ttyname(0)` + `st_rdev`. A same-TTY agent can pass a fake distinct value. Server-side TTY binding lands in the next minor release.
- Audit-rotation path (`audit.py`) uses `os.rename` which is non-atomic over existing target on Windows; rotation correctness on native Windows is unverified at this release.

If you need a hardened trust root or strict TTY isolation today, treat this release as **internal-share-stable on POSIX, beta on Windows**, and wait for the next minor release.

---

## 8. 라이선스 / 기여 / 문의

Issue, PR, 또는 내부 채널로 문의하세요. Public/private repo 모두 `git clone` 인증 설정(SSH key, credential helper, SSO, PAT)을 그대로 따릅니다.
