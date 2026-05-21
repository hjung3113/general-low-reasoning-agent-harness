# 다음 세션 작업 지시 (v0.9.7 release까지)

세션 시작 시 이 문서를 먼저 읽으세요.

## 현재 상태
- 브랜치: `develop` (HEAD `96c0429`, 25 commits ahead of main)
- v0.9.7 임플 + FIX-1~FIX-9 끝. codex 최종 PASS.
- 태그/푸시 보류 — 이번 세션에서 cleanup 후 릴리스.

## 작업 순서

### 1단계: 4번 (SIGTERM 진짜 테스트) 처리

**목표**: 단위 테스트만으로 검증된 crash recovery를 실제 subprocess + signal로 한 번이라도 통과시키기.

**작업**:
1. `scripts/lib/install.py`에 test-seam 환경변수 훅 추가:
   ```python
   _abort_phase = os.environ.get("HARNESS_TEST_ABORT_AFTER_PHASE")
   if _abort_phase == "1":  # after Phase 1 staging
       os._exit(137)
   # ... phase 2/3/4 동일
   ```
   - Phase 1 (staging done), Phase 3 (pending sidecar written), Phase 4 (batch done, sentinel written), Phase 5 (after os.replace) — 총 4 지점
2. `scripts/lib/upgrade.py`에도 동등 훅 (B2/B3/B4/B5)
3. 새 테스트 파일 `tests/test_sigterm_e2e.py`:
   - 각 phase 별로 subprocess.run(env={...HARNESS_TEST_ABORT_AFTER_PHASE=N}) → 종료 코드 137 확인
   - `state repair` subprocess 돌려서 rc=0 (or rc=1 for orphan) 어서트
   - 재실행해서 init이 깨끗이 완료되는지 확인
4. 4개 phase × init/upgrade = 8 시나리오. 단순 변형이라 fixture 공유.

**범위 주의**: test-seam은 환경변수 없으면 no-op. 프로덕션 코드 흐름 절대 영향 없음.

### 2단계: UX 폴리시 fix들 (안 고쳐도 무방하지만 같이 박기)

**FIX-A: 에러 메시지 줄바꿈**
- 대상 파일:
  - `scripts/lib/install.py` (CrossFilesystemError, InstallFailed 두 군데)
  - `scripts/lib/upgrade.py` (UpgradeRefused, finalize 검증)
- 패턴: `"한국어. ... [English ...]"` → `"한국어 줄 1\n한국어 줄 2\n\n[English line 1\nEnglish line 2]"`
- 핵심: `python3 scripts/harness.py state repair` 명령은 반드시 자기 줄에 단독 배치 (copy-paste 친화)
- 어서트 변경 필요한 테스트: 메시지에 정확한 줄 박혀있는지 보던 grep 어서트만 살짝 손대면 됨

**FIX-B: `harness check` 경고 요약**
- `scripts/lib/check.py` stale staging 감지 부분 (T5 코드)
- N >= 2면: 한 줄 요약 `"warning: {N}개 중단된 설치 감지 (oldest runid=..., age=...s). 복구: ..."`
- N == 1면: 기존 그대로 (runid + age 한 줄)
- 테스트 `tests/test_check_staging_detection.py:test_multiple_stale_dirs` 어서트 수정

**FIX-C: atomic write 함수 통합**
- 비교 대상: `scripts/lib/install.py:_atomic_write_json_fsync` vs `scripts/lib/atomic_io.py:atomic_write_text`
- atomic_io.py 쪽을 카논으로 채택. install.py의 로컬 함수는 호출만 위임하거나 import로 대체.
- 이미 동작하는 코드라 회귀 위험 낮음. pytest 풀로 회귀 확인.

**FIX-D: `.complete.tmp` 청소 audit row**
- `scripts/lib/install_recovery.py:_cleanup_sentinel_tmp_orphans`
- 청소 카운트 > 0이면 `install.recovery.tmp_orphans_cleaned` audit verb 발행
- 테스트 `tests/test_install_recovery_pending_manifest.py`에 어서트 한 줄 추가

**FIX-E: pre-existing 35 failure는 손대지 않음** — v0.9.8 백로그 유지.

### 3단계: 문서 sweep (README / manual.html / 기타)

**목표**: 매뉴얼 한 번 정리 + v0.9.4 → v0.9.7 업그레이드 시 35개 lib 격리 경고 명시 (앞서 3번 항목).

**대상 파일** (반드시 확인):
- `README.md`
- `docs/USER_MANUAL.md`
- `docs/site/manual.html` (USER_MANUAL.md 재생성)
- `docs/site/index.html`
- `docs/site/use-cases.html`
- `docs/use-cases/README.md`
- `CHANGELOG.md` (v0.9.7 entry 보강)

**확인 사항**:
1. v0.9.6 잔존 ref 없는지 `git grep -nE 'v?0\.9\.6' -- ':!CHANGELOG.md' ':!.planning'` 실행 → 의도된 히스토리 ref만 남기고 모두 0.9.7
2. **v0.9.4 → v0.9.7 격리 경고 신설**: USER_MANUAL에 "Upgrading from v0.9.4" 섹션 추가
   - "기존 v0.9.4 설치에는 매니페스트에 없는 lib 파일이 있을 수 있음 (v0.9.4 STALE-1 버그). 업그레이드 시 이 파일들이 `.harness/conflicts/`로 격리됨. 확인 후 안전하면 삭제 가능."
   - 한국어 + 영어
3. CHANGELOG에도 같은 경고 한 줄 추가
4. `state repair` 출력 예시가 실제 코드 emit string과 여전히 일치하는지 grep 재확인
5. manual.html 재생성 (기존 generator script 사용)

### 4단계: 최종 검증

```bash
PYTHONPATH=scripts python3 -m pytest tests/ -q --junitxml=.harness-test-cache/junit.xml
# 36 (or fewer) failed (all in KNOWN_FAILING_TESTS.md), pass count up
PYTHONPATH=scripts python3 -m pytest tests/test_known_failures_drift.py -q
# green

# Smoke
python3 scripts/project_dashboard.py --check  # ok
git grep -nE 'v?0\.9\.6' -- ':!CHANGELOG.md' ':!.planning'  # only historical
```

### 5단계: 어드버서리얼 최종 1라운드

- codex CLI에 diff (main..develop) 적대적 리뷰 요청
- PASS 받으면 다음 단계
- 시간 여유 있으면 Opus 3-panel 한 번 더 (선택)

### 6단계: 릴리스

```bash
# 메모리 workflow_orchestration 참고
git tag -s v0.9.7 -m "v0.9.7: atomic install staging + crash recovery"
git push origin develop
git checkout main && git merge --ff-only develop && git push origin main
git push origin v0.9.7
# GitHub release create (CHANGELOG에서 발췌)
```

### 7단계: 메모리 업데이트

- `project_v097_released.md` 신규 (v0.9.5/v0.9.6 패턴 참고)
- `MEMORY.md` 인덱스에 한 줄 추가
- `project_v094_install_broken.md`, `project_v095_hotfix_scope.md`는 사후 정리 (해결됨 표시)

---

## 컨텍스트 파일 (세션 시작 시 빠르게 훑기)

- `.planning/phases/02f-v0.9.6-hotfix/plans/PLAN.md` (REV-5 — 디자인 계약)
- `.planning/phases/02f-v0.9.6-hotfix/plans/IMPL-PLAN.md` (REV-2)
- `.planning/phases/02f-v0.9.6-hotfix/evidence/impl-summary.md`
- `.planning/phases/02f-v0.9.6-hotfix/evidence/impl-deviations.md`
- `.planning/phases/02f-v0.9.6-hotfix/reviews/DIFF-review-codex-final.md` (PASS)
- 메모리: `workflow_orchestration`, `feedback_plan_location`, `feedback_internal_only_threat_model`, `feedback_unittest_verification`

## 작업 원칙

- 1단계 (SIGTERM E2E)가 최우선. UX/문서 fix는 그 뒤.
- 각 FIX는 atomic commit.
- pytest baseline 유지: 35 failed (all KNOWN). 새 fail 나오면 즉시 잡기.
- 절대로 `--no-verify` 같은 거 안 씀.
- 태그/푸시는 4단계 검증 + 5단계 codex PASS 후에만.

## 예상 소요

- 1단계 SIGTERM E2E: 1-1.5시간 (test-seam 박고 8 시나리오)
- 2단계 UX fix A-D: 1시간
- 3단계 문서 sweep: 1시간 (격리 경고 신설 포함)
- 4-6단계 검증 + 릴리스: 30분
- **총 3.5-4시간 예상**
