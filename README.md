# 범용 저추론 에이전트 하네스 (harness source)

저추론 코딩 에이전트(Roo, OpenCode, Haiku 수준 모델)가 실제 저장소에서 안전하게 일하도록 만드는 재사용 가능한 하네스.
Target repository에 planning state, phase gate, adapter command, workflow skill, verification contract를 설치합니다.

**대상**: harness를 설치하거나 하네스 자체를 개발/유지하는 사람.
이미 설치된 하네스를 사용하는 팀원은 → [docs/USER_MANUAL.md](docs/USER_MANUAL.md)

최근 변경 사항은 [CHANGELOG.md](CHANGELOG.md)를 참고하세요.

---

## 용어 / Glossary

| 용어 | 뜻 |
|------|---|
| **Speed bump (방지턱)** | `phase approve` 시 `[y/N]`로 묻는 단계. 보안 검사 아님. 취소 가능. |
| **Autopilot** | 묻지 않고 여러 phase를 진행하는 모드. Speed bump와 별개. 기본 OFF. |
| **Phase** | 워크플로우 단계 (`design`, `discuss`, `plan`, `execute`, `done`). `phase approve`로 stamp, `phase set`로 전환. |
| **Phase gate** | 특정 verb가 특정 phase에서만 동작하는 규칙. |
| **Halt** | 하네스가 멈추고 사용자 행동을 요청. 에러 아님. 예: non-TTY halt = "터미널에서 다시 실행하세요". |
| **Audit log** | `.harness/audit.log`에 append-only로 기록되는 phase 변화/승인 로그. Chain-verified. |
| **Release confirmation** | `harness release`가 요구하는 타이핑 토큰. `phase approve`와 다름. (내부는 HMAC nonce — 사용자가 보는 용어는 "release confirmation".) |
| **Approve-nonce** | Legacy 용어. `phase approve`는 더 이상 사용 안 함. CLI verb `approve-nonce mint`는 deprecated, v1.0에서 제거. |
| **BY_TRUST** | CI 전용 하네스 flag (release 자동화에서만 사용). 일반 사용자는 설정하지 않음. |
| **Trust root** | 설치/업그레이드 시 검증되는 서명된 git tag. Release-path 전용. |
| **하네스 설정 flag (harness flag)** | 하네스 내부 설정값 (`HARNESS_*` 환경 변수로 전달). 일반 사용자는 만질 일 없음. `docs/advanced/harness-flags.md` 참고. |

자세한 내용: `docs/USER_MANUAL.md` §0.2.

---

## 1. 이 저장소

이 repo는 harness source이며, 직접 사용하는 제품이 아닙니다.
`scripts/harness.py init`으로 **target repository**에 설치하면 그 target에서 일상 작업이 이루어집니다.

v0.9.6의 일상 CLI 표면은 네 개입니다:

```bash
harness
harness next
harness run
harness check
```

`harness`는 짧은 가이드를 보여줍니다. `harness next`는 다음 안전 행동을 설명하고, `harness run`은 자동으로 해도 안전한 workflow 단계만 진행하다가 사람 승인이 필요하면 멈춥니다. `harness check`는 현재 하네스/계획 상태를 검증합니다.

`phase`, nonce, state repair, autopilot 같은 저수준 명령은 advanced/debug/CI 표면입니다. 보통 사용자와 어댑터는 이를 직접 실행하지 않습니다.

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
git clone --depth 1 --branch v0.9.6 https://github.com/hjung3113/general-low-reasoning-agent-harness.git "$tmp"
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

설치된 target repository에서 대시보드를 열려면:

```bash
python3 scripts/project_dashboard.py --serve
```

브라우저에서 `http://127.0.0.1:8765/overview`를 엽니다. 심어진 대시보드는 overview/progress/actions 세 페이지로 구성되며, actions 페이지의 버튼은 allowlist된 `scripts/harness.py` 명령만 실행합니다. 임의 shell 입력은 받지 않고, workflow를 움직일 수 있는 버튼은 브라우저 확인을 요구합니다.

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
| 하네스 업그레이드 | remembered init scope | `python3 scripts/upgrade_harness.py --version v0.9.6 --dry-run` |
| 하네스 일부 제거 | uninstall scopes | `python3 scripts/uninstall_harness.py --interactive` |

사내/외부 repo 헷갈리지 않는 설치 예시:

```bash
tmp="$(mktemp -d)"
git clone --depth 1 --branch v0.9.6 https://github.com/hjung3113/general-low-reasoning-agent-harness.git "$tmp"
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
  project_dashboard.py     target-local static/interactive dashboard
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
python3 scripts/harness.py release-check --expected-version v0.9.6

# 2. Tag 서명 (SSH key)
git config user.signingKey ~/.ssh/id_ed25519
git config gpg.format ssh
git tag -s v0.9.6 -m "Release v0.9.6"
git push origin v0.9.6
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
python3 scripts/upgrade_harness.py --version v0.9.6 --dry-run
python3 scripts/upgrade_harness.py --version v0.9.6

# 제거
python3 scripts/uninstall_harness.py --interactive
```

---

## 7. 변경 이력

→ [CHANGELOG.md](CHANGELOG.md)

**phase.approve Speed Bump** — `harness phase approve`가 interactive `[y/N]` 방지턱이 됨. `approve-nonce mint --audience phase.approve`는 deprecated. Release path 무변경. 자세한 내용은 `CHANGELOG.md` 또는 ADR `docs/adr/2026-05-19-phase-approve-speed-bump.md` 참고.

**한글 유즈케이스 문서 Hotfix** — 유즈케이스별 한글 문서를 `docs/use-cases/`로 분리하고, 최소 워크플로 UML 문서 2개를 한글로 정리했습니다.

**Known Limitations** — to be fully addressed in the next minor release:
- The current release tag is **not** SSH-signed; `docs/trust/allowed-signers` ships as a placeholder. Treat the trust root as scaffold-only until a maintainer key is published and tags are signed. Do not rely on `git verify-tag` until the next minor release.
- Audit-chain `previous_entry_hash` GENESIS fallback (`audit_chain.compute_entry_hash`) permits suffix-rewrite by a local writer with code execution as the user. Repo-local attacker (audit log forgery/replay) is intentionally out of threat model for this internal-only tool (out-of-repo audit-tip anchor removed in v0.9.5; see ADR `docs/adr/2026-05-20-remove-audit-tip-anchor.md`).
- Release-path approval-nonce TTY-isolation still accepts `--consumer-tty` from argv rather than server-verifying `os.ttyname(0)` + `st_rdev` (phase.approve no longer uses this path). A same-TTY agent can pass a fake distinct value.
- Audit-rotation path (`audit.py`) uses `os.rename` which is non-atomic over existing target on Windows; rotation correctness on native Windows is unverified at this release.

If you need a hardened trust root or strict TTY isolation today, treat this release as **internal-share-stable on POSIX, beta on Windows**, and wait for the next minor release.

---

## 8. 라이선스 / 기여 / 문의

Issue, PR, 또는 내부 채널로 문의하세요. Public/private repo 모두 `git clone` 인증 설정(SSH key, credential helper, SSO, PAT)을 그대로 따릅니다.
