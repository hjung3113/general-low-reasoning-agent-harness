# 하네스 설정 Flag (Harness Flags)

> 이 문서는 하네스 내부 설정 flag(`HARNESS_*`) 목록입니다. **평소에는 건드리지 않습니다.** 테스트, CI, 디버깅, 명시적 override가 필요한 경우에만 사용합니다.
>
> 이름이 `HARNESS_*`인 OS 환경 변수로 전달되지만, 일반적인 시스템 환경 변수와 다릅니다 — 하네스에만 영향을 주며, shell rc에 추가할 필요 없습니다.

## Flag 목록

| 변수 | 값 | 의미 | 보안 노트 |
| --- | --- | --- | --- |
| `HARNESS_ALLOW_UNSIGNED_DEV` | `1` | Dev 환경에서 unsigned tag bypass | Production install은 downgrade 불가. 권장하지 않음 |
| `HARNESS_ALLOW_UNSIGNED_DEV_SOURCE` | `cli_flag` \| `path_source` | upgrade 시 unsigned source 허용 출처 표시 | harness 내부 전달용; 직접 설정 금지 |
| `HARNESS_ALLOW_NETWORK` | `1` | Autopilot에서 network 허용 의도를 표명 (input metadata) | `HARNESS_AUTOPILOT_NETWORK`와 다름 — 단독으로는 network를 승인하지 않음; 적절한 authorization과 함께 사용 |
| `HARNESS_AUTOPILOT_NETWORK` | `1` | Autopilot에서 network 허용 (승인 경로) | `phase autopilot --allow-network` flag와 동일; audit 기록 |
| `HARNESS_AUTOMATION` | `phase` \| `chain` | CI autopilot mode | OIDC 또는 환경 검증 필수; TTY 없음 |
| `HARNESS_BY_TRUST` | email | CI 환경에서 bot identity 지정 | OIDC/signed token과 함께 필수; human approver와 겹치지 않아야 함 |
| `HARNESS_BYPASS_TTY_CONFIRM` | `1` | TTY gate 무시 (test-only) | 테스트 fixture용; production 금지 |
| `HARNESS_DEV_BUILD` | `1` | Dev build flag (test fixture) | Production에서 동작 변경 없음; test context에서만 사용 |
| `HARNESS_DELEGATED_SOURCE_KIND` | string | upgrade 위임 소스 종류 | `upgrade_harness.py`가 내부적으로 전달; 직접 설정 금지 |
| `HARNESS_DELEGATED_SOURCE_REF` | ref | upgrade 위임 소스 git ref | 위와 동일 |
| `HARNESS_DELEGATED_SOURCE_REPO` | repo | upgrade 위임 소스 repo URL | 위와 동일 |
| `HARNESS_DELEGATED_SOURCE_VERSION` | version | upgrade 위임 소스 버전 | 위와 동일 |
| `HARNESS_FIXED_NOW_ISO` | timestamp | 고정 시간 (test-only) | 예: `2026-05-17T14:30:00Z` |
| `HARNESS_HOOK_ALLOW_SKIP` | `1` | hook skip 레거시 동작 허용 (test-only) | 테스트 검증 목적; production 금지 |
| `HARNESS_JTI_DIR` | path | OIDC JTI store override | 위치 override 시 audit warning `ci.oidc.jti.dir_override` 기록 |
| `HARNESS_NONCE_DIR` | path | Approval nonce 저장 위치 override (release path) | Windows LOCALAPPDATA 불가 시 또는 테스트 격리에 사용 |
| `HARNESS_OIDC_TEST_MODE` | `1` | OIDC stub 활성화 (test-only) | CI predicate 테스트 경로용; production 절대 금지 |
| `HARNESS_PROJECT_ROOT` | path | PS audit path 지정 | PowerShell deny-shim용; Windows에서 audit path 명확화 |
| `HARNESS_RELEASE_RUN` | `1` | release smoke test에서 release 모드 활성화 | `--release` flag와 동일; release_smoke_test.py 전용 |
| `HARNESS_SMOKE_PLATFORM_OVERRIDE` | `win32` 등 | smoke test 내 플랫폼 override | Windows 경로 검증을 non-Windows 환경에서 실행할 때 사용 |
| `HARNESS_STRICT_VERB_REGISTRY` | `1` | Unknown verb에 exit 10 enforce | 기본(permissive)은 warning만 |
| `HARNESS_TEST_FORCE_TTY` | `1` | **제거됨 (Cycle-2 이후 production 코드에서 삭제)** | 더 이상 TTY gate를 bypass하지 않음; 테스트는 `sys.stdin.isatty` mock 사용 |
| `HARNESS_TEST_OIDC_CLAIMS_` | prefix | OIDC claim 주입 (test stub) | `HARNESS_OIDC_TEST_MODE=1` 필수; test fixture용 |
| `HARNESS_TEST_OIDC_CLAIMS_GITHUB_ACTIONS` | JSON | GitHub Actions OIDC claim 주입 (test stub) | `HARNESS_OIDC_TEST_MODE=1` 필수; test fixture용 |
| `HARNESS_TEST_OIDC_TOKEN_` | prefix | OIDC token 주입 (test stub) | 위와 동일 |
| `HARNESS_TEST_OIDC_TOKEN_GITHUB_ACTIONS` | JWT | GitHub Actions OIDC token 주입 (test stub) | `HARNESS_OIDC_TEST_MODE=1` 필수; test fixture용 |
| `HARNESS_VERSION_OVERRIDE` | semver | anchor CLI에서 harness version override | 테스트 또는 디버깅 목적; production에서 권장하지 않음 |

### 내부 전용 (직접 설정 불가)

아래 flag는 하네스 프로세스가 내부적으로 설정하며, 사용자가 직접 설정해서는 안 됩니다.

| 변수 | 용도 |
| --- | --- |
| `HARNESS_ADVANCED` | 내부 advanced 모드 플래그 |
| `HARNESS_BIN` | 하네스 바이너리 경로 |
| `HARNESS_CLI` | CLI 실행 경로 |
| `HARNESS_CMD` | 현재 실행 중인 명령 |
| `HARNESS_DIR` | 하네스 디렉터리 경로 |
| `HARNESS_E` | 내부 exit code 전달 |
| `HARNESS_HUMAN` | human identity (내부 전달) |
| `HARNESS_INVOCATION_RE` | 호출 패턴 regexp (내부) |
| `HARNESS_MACHINE` | machine identity (내부) |
| `HARNESS_MOD` | 모듈 경로 (내부) |
| `HARNESS_REPO` | 현재 repo 경로 |
| `HARNESS_USER` | 현재 user identity |
| `HARNESS_VERSION` | 실행 중인 harness 버전 |
