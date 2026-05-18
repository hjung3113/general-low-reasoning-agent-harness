# 하네스 사용자 설명서 (v0.7.0)

## 목차

1. [개요](#1-개요)
2. [설치 및 업그레이드](#2-설치--업그레이드)
3. [CLI 명령 레퍼런스](#3-cli-명령-레퍼런스)
4. [Phase Gate 워크플로](#4-phase-gate-워크플로)
5. [보안 모델](#5-보안-모델)
6. [Release Trust](#6-release-trust)
7. [Windows 지원](#7-windows-지원)
8. [감사 로그](#8-감사-로그)
9. [Exit Codes](#9-exit-codes)
10. [환경 변수 레퍼런스](#10-환경-변수-레퍼런스)
11. [트러블슈팅](#11-트러블슈팅)
12. [v0.9.0 Carryover](#12-v09-carryover)
13. [참고 자료](#13-참고-자료)

---

## 1. 개요

이 설명서는 이미 하네스를 설치한 팀원들이 실제 작업에 사용하기 위한 상세 참고서입니다. [README.md](../README.md)는 설치 가이드이고, 이 문서는 각 명령, 워크플로, 보안 옵션의 심화 레퍼런스입니다. 하네스가 code review, approval gate, audit trail을 강제하는 작동 방식을 이해하는 데 도움이 됩니다.

---

## 2. 설치 & 업그레이드

### 2.1 초기 설치

```bash
python3 scripts/harness.py init --target /path/to/project
```

대화형 설치 시 adapter (Roo, OpenCode, 둘 다, 또는 없음), profile (generic, dotnet-etl, python-etl, react-web), database 축 (선택 시)을 묻습니다. 선택된 skill pack이 설치되며, 설치 메타데이터는 `.harness/installed-manifest.json`에 저장됩니다.

### 2.2 harness check와 doctor

설치 직후 target 안에서:

```bash
python3 scripts/harness.py check
python3 scripts/harness.py doctor
python3 scripts/harness.py state show
```

- `check`: 구조 오류, missing verification, managed block 누락, 단계 경로 drift를 감지합니다.
- `doctor`: workflow 품질 신호(누락된 required reads, 설치 manifest 불일치)를 warning으로 보고합니다.
- `state show`: 현재 phase 상태와 active checkpoint를 projection으로 표시합니다.

### 2.3 harness upgrade

새 버전으로 업그레이드하려면 새 harness checkout에서:

```bash
python3 /path/to/newer-harness/scripts/harness.py upgrade \
  --target /path/to/project \
  --dry-run
python3 /path/to/newer-harness/scripts/harness.py upgrade \
  --target /path/to/project
```

Target 안에서 bootstrapper 사용:

```bash
python3 scripts/upgrade_harness.py --version v0.7.0 --dry-run
python3 scripts/upgrade_harness.py --version v0.7.0
```

### 2.4 업그레이드 플래그: --allow-unsigned-dev

Dev 환경에서 서명되지 않은 tag로부터 설치할 때 사용:

```bash
HARNESS_ALLOW_UNSIGNED_DEV=1 python3 scripts/harness.py upgrade --target /path/to/project
```

또는:

```bash
python3 scripts/harness.py upgrade --target /path/to/project --allow-unsigned-dev
```

**주의**: 한 번 `trust_origin: signed_tag`로 설치되면, 이 플래그로 다시 unsigned로 downgrade할 수 없습니다. 반드시 properly signed release tag로 업그레이드하거나 재설치해야 합니다.

---

## 3. CLI 명령 레퍼런스

### 3.1 Phase Lifecycle

| 명령 | 설명 | 핵심 옵션 |
|---|---|---|
| `phase set <phase>` | 새 phase로 전환 | `--by <email>` identity override |
| `phase approve` | 현재 phase 승인 (execute → done 진행) | `--by <email>`, `--at <iso>` |
| `phase reopen --to discuss\|plan --reason <text>` | Phase 회귀, approval 리셋 | `--by <email>` |
| `phase autopilot start --phase <slug>` | Autopilot 시작 (phase 또는 chain) | `--allow-network`, `--mode phase\|chain` |
| `phase autopilot stop` | Autopilot 중단, manual로 복귀 | (TTY-only) |

**사용 예시**:
```bash
python3 scripts/harness.py phase set discuss
python3 scripts/harness.py phase set plan --by alice@company.com
python3 scripts/harness.py phase approve
python3 scripts/harness.py phase reopen --to plan --reason "scope 추가"
```

### 3.2 Approve-Nonce (새로움 v0.7.0)

```bash
python3 scripts/harness.py approve-nonce mint --audience phase.approve [--ttl 120]
```

`phase approve` 전에 다른 터미널에서 nonce를 minting합니다. 이는 human presence proof를 제공하고 agent가 approval을 가장할 수 없도록 합니다. TTY-only 명령입니다.

**Flow**:
1. 터미널 A (agent): 작업 수행, `phase approve` 전 대기
2. 터미널 B (human): `harness approve-nonce mint --audience phase.approve` 실행, 8자 code 받음 (120초 유효)
3. 터미널 A (human 또는 agent): `harness phase approve` 실행 — nonce 자동 소비, 승인 완료

### 3.3 상태 및 조회

| 명령 | 설명 |
|---|---|
| `state show` | 현재 phase, execution mode, active checkpoint 표시 |
| `state show --format json` | JSON 형식 출력 |
| `state repair` | 깨진 managed block 또는 누락된 marker 복구 |
| `status` | Autopilot halt diary 및 suggested next command 표시 |
| `next` | Current position에서 승인된 다음 step 제안 |
| `verify --audit` | Audit log chain integrity 검증 |

### 3.4 Session Lock

| 명령 | 설명 |
|---|---|
| `session unlock` | 잠긴 session 해제 (recovery) |
| `lock recover --force` | Stale lock 정리 (ambiguous 상황에서만) |

### 3.5 릴리스 및 진단

| 명령 | 설명 |
|---|---|
| `check` | 설치된 harness 구조 검증 |
| `check --worktree` | Staged/unstaged/untracked changes가 approved paths 내인지 확인 |
| `doctor` | Workflow 품질 신호 진단 |
| `release-check --expected-version v0.7.0` | Release tag 버전 검증 |

### 3.6 FSD (Fast Slash-command Dispatch)

Adapter Markdown command wrapper로서, 주로 adapter 내에서 호출됩니다.

```bash
python3 scripts/harness.py fsd phase --slug discuss
python3 scripts/harness.py fsd all
```

사용자는 일반적으로 `.roo/commands/` 또는 `.opencode/commands/`를 통해 간접 호출합니다.

---

## 4. Phase Gate 워크플로

### 4.1 기본 흐름: discuss → plan → execute → done

**discuss** (read-only): repository evidence 읽기, phase 후보 제안, 문제점 파악. 구현하지 않음.

**plan** (planning 문서 작성):
- `allowed_paths`: 이 phase에서 수정 가능한 경로
- `blocked_paths`: 금지된 경로
- `verification`: 다음 단계에서 실행할 concrete 검증 명령
- `acceptance_criteria`: done 판정 기준
- Adversarial review: spec 위반, regression, edge case

**execute** (사람이 명시적 `phase approve`한 후):
- Code 수정, 변경 범위는 `allowed_paths`로 제한됨
- `harness.py check --worktree`로 diff가 approved path 밖으로 나가지 않는지 확인

**done** (audit):
- 계획된 검증 명령 실행, 결과 기록
- Risk 및 rollback 경로 문서화
- Push 준비 확인

### 4.2 Execution Mode와 Autopilot

`.scratch/phase-state.json`의 `execution_mode`는:
- `manual` (기본): human `harness phase set` 명령 필요
- `phase_autopilot`: agent가 phase 범위 내에서 단계별 진행 (human approval 여전히 필요)
- `chain_autopilot`: agent가 phase sequence 전체 진행

`phase autopilot start`는 CI 환경에서 OIDC 또는 환경 변수로 증명된 bot identity를 요구합니다. TTY 환경에서는 human presence proof (nonce 또는 OS credential)로 충분합니다.

### 4.3 Halt와 Human-Presence Proof

Autopilot이 중단되면 (budget exhausted, fence deny, halt 명령):
- `harness status`로 상태 확인
- `harness next`로 suggested next command 확인
- `last_halt.suggested_next_command_requires_human` 확인 — TTY-only command면 human이 직접 실행해야 함

Approval nonce (§3.2)는 agent가 human approval을 가장할 수 없도록 합니다. Nonce는:
- `~/.harness/approval-nonces/` (POSIX) 또는 `%LOCALAPPDATA%\Harness\approval-nonces\` (Windows)에 저장
- 120초(기본) 유효
- Single-use (소비 후 삭제)
- Minter TTY ≠ consumer TTY (동일 PTY 내 agent 자동 실행 방지)

---

## 5. 보안 모델

### 5.1 Trust Boundaries

- `~/.harness/` (project 밖, agent 접근 불가): approval nonce, secret key, release trust root
- `<target>/.harness/` (project 내): installed manifest, audit log, phase state
- `.planning/**`, `.roo/**`, `.opencode/**` (project-scoped agent 작업 공간)

### 5.2 Project-Scoped Agent 방어

Project agent가 우회할 수 없는 항목:
- `phase approve` (TTY-only + human presence proof)
- `phase autopilot start` (CI 환경에서 OIDC/signed token 필수, TTY 환경에서 human proof 필수)
- `phase reopen` (TTY-only)
- Nonce file (project scope 밖의 `~/.harness/approval-nonces/`)
- Release tag signature verification (signed tag만 production upgrade 허용)

우회 가능한 항목 (honest defense-in-depth):
- `.planning/**`, `.scratch/**` 직접 편집 (audit chain 강제하지 않음, 다음 harness command가 state-audit consistency 검증)
- Git commit 직접 작성 (harness verify --audit가 forensic 기록)
- Network access (phase autopilot --allow-network flag로 명시적 opt-in, audit 기록)

### 5.3 HMAC Nonce Signing

Approval nonce는 HMAC으로 서명됩니다:
- Key: `~/.harness/secret.key` (0600 perms, 한 번만 생성)
- Signature: `minter_tty + consumer_tty + expires_at`로 계산
- Corruption 감지 시 자동 rotation (새 secret.key 생성, audit `verb=audit.secret_key.rotated`)

### 5.4 Signed Release Tags

Release tag는 maintainer의 SSH key로 서명됩니다 (§6). `harness upgrade`는 자동 검증. Dev 환경은 `--allow-unsigned-dev`로 bypass 가능하지만, 한 번 signed로 설치되면 downgrade 불가.

### 5.5 Audit Log Tamper Detection

Audit log는 두 가지 chain을 유지합니다:
- **State-content chain**: `before_sha256` / `after_sha256`로 state file 전환 증명
- **Entry chain**: 각 entry의 `entry_hash`와 `previous_entry_hash`로 log 무결성 확인

`harness verify --audit`는 전체 history (rotated files 포함)를 walk하여 chain integrity 검증. Partial edit, truncation, 또는 single-field rewrite를 감지합니다.

**한계**: Repo-local attacker가 모든 `audit.log*` + `.scratch/phase-state.json`을 rewrite하고 모든 `entry_hash`를 recompute할 수 있으면 우회 가능합니다. Signed external anchor (v0.9.0 feature)가 이를 해결합니다.

---

## 6. Release Trust

### 6.1 allowed-signers 파일

`docs/trust/allowed-signers`는 OpenSSH format 허용 목록:

```
release@harness namespaces="git" ssh-ed25519 AAAA... maintainer@example.com
```

각 line은 release engineer의 SSH public key를 authorize합니다.

### 6.2 New Signer 추가

1. Maintainer의 SSH public key 얻기: `cat ~/.ssh/id_ed25519.pub`
2. Fingerprint out-of-band 검증: `ssh-keygen -lf <pubkey-file>`
3. `docs/trust/allowed-signers`에 line 추가
4. Main으로 commit & push

### 6.3 Release Tag 서명 (Maintainer)

```bash
git config user.signingKey ~/.ssh/id_ed25519
git config gpg.format ssh
git tag -s v0.7.0 -m "Release v0.7.0"
git push origin v0.7.0
```

Git ≥ 2.34 필요 (Windows: Git for Windows 포함).

### 6.4 Tag 검증 (Consumer)

`harness upgrade`는 자동 검증. 수동 검증:

```bash
git -c gpg.ssh.allowedSignersFile=docs/trust/allowed-signers verify-tag v0.7.0
```

### 6.5 Trust-Downgrade Refusal

한 번 signed tag로 설치되면, `--allow-unsigned-dev`로도 unsigned로 downgrade 불가능합니다. 대신:
- Properly signed release tag로 업그레이드, 또는
- Target 재설치

---

## 7. Windows 지원

### 7.1 요구사항

- **Git for Windows ≥ 2.34**: SSH-signed-tag 검증을 위해 필요
- **Python 3**: `py -3`, `python`, 또는 Python Launcher
- **PowerShell 5.1+** 또는 **pwsh 7+**: autopilot deny-shim 실행

### 7.2 safe_open (Production Write)

Production write는 Windows CreateFileW를 사용합니다:
- Handle-bound reparse-point refusal: 열린 handle을 통해 junction/symlink 확인 및 거절
- ADS (Alternate Data Stream) 거절: `:`, `::$DATA` 같은 component 금지
- Case-fold containment: path normalization으로 case mismatch로 인한 escape 방지

Exit code 4 (`path_reparse_refused`) 또는 11 (`windows_containment_degraded`)이 emit됩니다.

### 7.3 PowerShell Deny-Shim

`autopilot_guard.ps1`은 network deny, file fence를 PowerShell에서 강제합니다. `$PROFILE`에 wire:

```powershell
$HarnessProjectRoot = "C:\path\to\project"
& "$HarnessProjectRoot\.harness\autopilot_guard.ps1"
```

`HARNESS_PROJECT_ROOT` env로 audit path 지정. 단, PowerShell 외 Bash/shell 명령은 이 shim을 우회할 수 있습니다. Phase gate는 여전히 적용됩니다.

### 7.4 LOCALAPPDATA 체크

Windows에서 `LOCALAPPDATA` unset 시 approval-nonces 저장 경로 부재로 warning 또는 error 발생합니다. 일반적으로 Windows login session에서는 자동 설정되지만, minimal CI환경이면 수동 설정 필요:

```powershell
$env:LOCALAPPDATA = "$env:UserProfile\AppData\Local"
```

---

## 8. 감사 로그

### 8.1 위치 및 형식

`.harness/audit.log` (JSON Lines). 각 entry:

```json
{
  "verb": "phase.approve",
  "at": "2026-05-17T14:30:15Z",
  "by_email": "alice@company.com",
  "by_source": "gitconfig_auto",
  "confirmation_kind": "human_cli",
  "approved_at": "2026-05-17T14:30:15Z",
  "schema_version": 2,
  "seq": 1,
  "seq_global": 10,
  "previous_entry_hash": "000...",
  "entry_hash": "abc..."
}
```

### 8.2 주요 Verb 레지스트리

**Phase Lifecycle**:
- `phase.set` — phase 전환
- `phase.approve` — execute 승인
- `phase.reopen` — 회귀 및 approval reset

**Autopilot**:
- `phase.autopilot.start` — autopilot 시작
- `phase.autopilot.stop` — autopilot 중단
- `phase.autopilot.halt` — halt (budget, fence, 기타)

**Audit Infrastructure**:
- `audit.rotated` — log 회전
- `audit.repair` — 복구 action
- `audit.secret_key.rotated` — secret key 손상 및 rotation

**Approval**:
- `approve_nonce.mint` — human presence proof 생성

**Network/Fence**:
- `autopilot.fence.deny` — 파일 제한으로 인한 거절
- `autopilot.network.deny` — network deny로 인한 거절

**Release**:
- `release.trust.verified` — signed tag 검증 성공
- `release.trust.bypassed` — `HARNESS_ALLOW_UNSIGNED_DEV=1` bypass 사용
- `release.trust.refused` — downgrade 또는 서명 오류로 거절

**CI/OIDC**:
- `ci.oidc.jti.consumed` — OIDC JTI token 소비
- `ci.oidc.jti.replay` — JTI replay 감지
- `ci.oidc.jti.store_rotated` — corrupted JTI store 회전

**Session**:
- `session.unlock` — session lock 해제
- `lock.recovered` — stale lock 복구
- `cli.deprecated_flag` — deprecated flag 사용

**Migration**:
- `migrate.state_v2` — v0.6 automation_mode → v0.7 execution_mode 마이그레이션

### 8.3 Strict Verb Registry Mode

```bash
HARNESS_STRICT_VERB_REGISTRY=1 python3 scripts/harness.py ...
```

Mode를 1로 설정하면, 등록되지 않은 verb는 exit 10으로 거절됩니다. 기본값(permissive)은 unknown verb를 warning으로만 보고하고 진행합니다.

### 8.4 Chain Integrity 검증

```bash
python3 scripts/harness.py verify --audit
```

모든 rotated files을 walk하여:
- `seq_global` 중복/gap 감지
- `previous_entry_hash` rotation seam에서 일치 확인
- 마지막 entry의 `entry_hash`가 journal recorded tip과 일치 확인

Failure → exit 10 (audit chain failure).

---

## 9. Exit Codes

`scripts/lib/exitcodes.py` 기준. `sub_reason` 필드는 exit code의 정확한 원인 식별.

| Code | 이름 | 의미 |
|---|---|---|
| 0 | `EXIT_OK` | 성공 |
| 1 | `EXIT_OPERATIONAL` | 일반 실패 (e.g. file not found) |
| 2 | `EXIT_INVALID_TRANSITION` | Bad CLI argument |
| 3 | `EXIT_SESSION_LOCKED` | State lock 경합 또는 recovery 필요 |
| 4 | `EXIT_SCOPE_VIOLATION` | Approved path 밖 change 또는 path reparse refusal (Windows) |
| 5 | `EXIT_UNPARSEABLE_JSON` | BOM 포함 또는 CRLF violation JSON |
| 6 | `EXIT_WRONG_PHASE_FOR_VERB` | Phase-verb mismatch 또는 nonce signature invalid |
| 7 | `EXIT_STALE_UNCERTAIN` | State timestamp 불확실성 (recovery 필요) |
| 8 | `EXIT_TIMESTAMP_OUT_OF_RANGE` | Approval timestamp 범위 초과 |
| 10 | (audit chain) | Audit log chain integrity failure |
| 11 | `EXIT_WINDOWS_CONTAINMENT_DEGRADED` | Windows ADS/reserved-char containment error |
| 14 | `EXIT_AUDIT_PARTIAL_WRITE` | Crash recovery undecidable (manual action required) |
| 15 | `EXIT_RELEASE_TRUST_INVALID` | Signed tag verification 실패 또는 trust downgrade refused |

**중요**: `sub_reason` 필드를 검토하여 정확한 원인 파악. 같은 exit code가 여러 상황에서 사용됩니다.

---

## 10. 환경 변수 레퍼런스

| 변수 | 값 | 의미 | 보안 노트 |
|---|---|---|---|
| `HARNESS_ALLOW_UNSIGNED_DEV` | `1` | Dev 환경에서 unsigned tag bypass | Production install은 downgrade 불가. 권장하지 않음 |
| `HARNESS_AUTOPILOT_NETWORK` | `1` | Autopilot에서 network 허용 | `phase autopilot --allow-network` flag와 동일; audit 기록 |
| `HARNESS_BY_TRUST` | email | CI 환경에서 bot identity 지정 | OIDC/signed token과 함께 필수; human approver와 겹치지 않아야 함 |
| `HARNESS_AUTOMATION` | `phase` \| `chain` | CI autopilot mode | OIDC 또는 환경 검증 필수; TTY 없음 |
| `HARNESS_NONCE_DIR` | path | Approval nonce 저장 위치 override | Test-only; production은 권장하지 않음 |
| `HARNESS_JTI_DIR` | path | OIDC JTI store override | 위치 override 시 audit warning `ci.oidc.jti.dir_override` 기록 |
| `HARNESS_STRICT_VERB_REGISTRY` | `1` | Unknown verb에 exit 10 enforce | 기본(permissive)은 warning만 |
| `HARNESS_PROJECT_ROOT` | path | PS audit path 지정 | PowerShell deny-shim용; Windows에서 audit path 명확화 |
| `HARNESS_BYPASS_TTY_CONFIRM` | `1` | TTY gate 무시 (test-only) | 테스트 fixture용; production 금지 |
| `HARNESS_FIXED_NOW_ISO` | timestamp | 고정 시간 (test-only) | 예: `2026-05-17T14:30:00Z` |

---

## 11. 트러블슈팅

### 11.1 "approve-nonce mint requires interactive TTY"

**원인**: Non-TTY 환경 (redirected stdin, agent subprocess)에서 nonce mint 시도.

**해결**: 실제 터미널에서 실행:
```bash
# 터미널 A (agent 작업)
# ... agent task ...

# 터미널 B (human)
python3 scripts/harness.py approve-nonce mint --audience phase.approve
# 8자 code → TTY로 출력
```

### 11.2 "tag_signature_invalid" / "trust_downgrade_refused"

**원인**: 
- Unsigned release tag로 업그레이드 시도 (production install이 이미 signed로 설치됨)
- `allowed-signers`의 signer public key가 outdated/missing

**해결**:
1. `docs/trust/allowed-signers` 확인 (signer key 최신인지)
2. Properly signed release tag로 upgrade:
   ```bash
   git verify-tag v0.7.0  # 로컬 verify
   python3 scripts/harness.py upgrade --target /path/to/project
   ```
3. Dev 환경이면 `--allow-unsigned-dev` 사용 (처음 설치만)

### 11.3 "nonce_signature_invalid"

**원인**: 
- Secret key 손상
- Nonce 만료 (기본 120초)
- Minter TTY = consumer TTY (agent가 same PTY에서 approval 시도)

**해결**:
- Secret key 손상 시 자동 rotation (audit `audit.secret_key.rotated`)
- Nonce 다시 mint (TTL 재시작)
- 다른 TTY에서 approval 명령 실행

### 11.4 "audit_partial_write" (exit 14)

**원인**: Power loss 또는 crash 사이 crash recovery 불확실성. State + audit transaction이 diverged.

**해결**: `harness lock recover --force` 실행 후 상태 재점검.

### 11.5 "non_tty_authorization_unverified"

**원인**: Non-TTY에서 `phase autopilot start` 시도, CI 환경 증명 없음.

**해결**:
- GitHub Actions: `GITHUB_ACTIONS=true`, `ACTIONS_ID_TOKEN_REQUEST_URL`, OIDC token 설정
- GitLab CI: `GITLAB_CI=true`, `CI_JOB_JWT_V2` token 설정
- Buildkite: `BUILDKITE=true`, Buildkite OIDC token 설정
- 없으면 TTY 환경에서 human presence proof 사용

### 11.6 "scope_violation" / "path_reparse_refused" (exit 4)

**원인**: 
- Approved `allowed_paths` 밖 file 수정
- Windows: reparse point (symlink, junction) 또는 reserved chars (`:`, `|`)

**해결**:
- `harness.py check --worktree` 실행, 위반 경로 확인
- Phase plan으로 돌아가 `allowed_paths` 수정
- Windows: `$Profile` 내 `.harness\autopilot_guard.ps1` wire 확인

### 11.7 "managed block missing" (warning)

**원인**: `.planning/ROADMAP.md` 또는 `.planning/STATE.md`에 managed marker block 누락.

**해결**: 메시지의 command 실행:
```bash
python3 scripts/harness.py state repair
```

### 11.8 "cli_bot_identity_overlaps_human_approver"

**원인**: `HARNESS_BY_TRUST` (bot identity)이 `.harness/install-record.json`의 approvers[] entry와 동일.

**해결**: CI bot identity 변경 또는 install-record approvers 재확인:
```bash
cat .harness/installed-manifest.json | grep approvers
```

---

## 12. v0.9.0 Carryover

다음 메이저 버전에 deferred된 항목:

1. **Explicit revoked_keys file**: v0.7 제약 (propagation 지연). v0.9에서 revoked_keys 병렬 consulted, immediate revocation.
2. **Signed external audit anchor**: Repo-local attacker 대항 (v0.7 honest defense-in-depth 한계).
3. **Advisory raw-tool budget enforcement**: v0.7은 `cli_budgets_remaining` hard-stop (harness subprocesses만), raw tools(Bash, Edit) advisory-only. v0.9에서 hook enforcement.
4. **Cross-machine collaboration**: v0.7은 single-user, single-machine. Multi-user lock contention, distributed state sync 미지원.

---

## 13. 참고 자료

- [README.md](../README.md) — quickstart, 설치 시나리오
- [docs/trust/README.md](../docs/trust/README.md) — release tag signing, allowed-signers 설정
- [docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md](../docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md) — §3 (phase commands), §6 (release trust), §12 (exit codes, audit verbs)
- [scripts/lib/exitcodes.py](../scripts/lib/exitcodes.py) — canonical exit-code constants
- [scripts/lib/audit.py](../scripts/lib/audit.py) — KNOWN_VERBS registry (lines 275–318)
- [docs/phase-gate-harness.md](../docs/phase-gate-harness.md) — phase gate concept & ROADMAP/STATE structure
- [docs/protocol-spec.md](../docs/protocol-spec.md) — core protocol reference
