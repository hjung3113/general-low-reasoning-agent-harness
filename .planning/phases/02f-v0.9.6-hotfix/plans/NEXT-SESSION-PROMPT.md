# 다음 세션 작업 지시 (v0.9.7 release까지)

세션 시작 시 이 문서를 먼저 읽으세요.

## 현재 상태
- 브랜치: `develop` (HEAD `492d239`, 26 commits ahead of main)
- v0.9.7 임플 + FIX-1~FIX-9 끝. codex 최종 PASS.
- 태그/푸시 보류 — 이번 세션에서 UX 개선 + 문서 정리 후 릴리스.

## 작업 순서

### 1단계: init/upgrade 진행 표시 (NEW, 가장 중요)

**문제**: 현재 `harness init`/`upgrade` 돌리면 한참 동안 아무 출력 없다가 "installed harness ..." 한 줄 뜸. 168 파일 설치하는데 침묵하면 멈춘 건지 동작 중인지 모름.

**목표**: 가벼운 진행 표시 추가. 화려한 progress bar 말고 단순하게.

**옵션** (둘 다 박아도 됨, 또는 단순한 거 하나):
- **옵션 A (권장)**: phase별 한 줄 로그
  ```
  staging files... [42/168]
  staging files... [84/168]
  staging files... [126/168]
  staging files... [168/168] done
  writing pending sidecar... done
  applying atomic batch... [168/168] done
  syncing roomodes... done
  finalizing... done
  installed harness v0.9.7 → /target (168 planned writes). Next: ...
  ```
  - stderr로 출력 (stdout은 기존 final summary 유지)
  - 너무 자주 출력하면 노이즈 → 25%/50%/75%/100% 또는 매 50 파일마다 한 번
  - `--quiet` flag로 끌 수 있게

- **옵션 B**: 단순 dot progress
  ```
  staging .................. (168)
  batch    .................. (168)
  ```

**구현 위치**:
- `scripts/lib/install.py` Phase 1 (staging loop), Phase 4 (batch — atomic_install_batch 내부 callback 필요할 수 있음)
- `scripts/lib/upgrade.py` Pass A loop, Pass B batch
- `scripts/lib/atomic_io.py` `atomic_install_batch`에 optional `progress: Callable | None = None` 콜백 파라미터 추가

**테스트**:
- 새 테스트 `tests/test_progress_output.py`: subprocess로 init 돌려서 stderr에 progress 라인 N개 이상 나오는지 확인
- 기존 init/upgrade 테스트는 stderr를 무시하거나 progress 라인을 expected에 추가

**범위 주의**: progress는 stderr로만. stdout 포맷 변경 금지 (기존 파서/CI 깨짐).

### 2단계: 에러 메시지 줄바꿈 (FIX-A)

**대상 파일**:
- `scripts/lib/install.py` (CrossFilesystemError, InstallFailed 두 군데)
- `scripts/lib/upgrade.py` (UpgradeRefused, finalize 검증)

**패턴**:
```
"한국어 한 문장.
한국어 두 번째 문장 (필요 시).

복구:
    python3 scripts/harness.py state repair

[English equivalent line 1.
English equivalent line 2 (if needed).

Recover:
    python3 scripts/harness.py state repair]"
```

- `python3 scripts/harness.py state repair` 명령은 자기 줄에 단독 (copy-paste 친화)
- 한국어 블록, 빈 줄, 영어 블록 분리

**테스트 어서트 수정**: 기존 메시지에 정확한 줄 검색하던 grep은 키워드 검색으로 완화 (`"state repair" in stderr` 등).

### 3단계: `harness check` 경고 요약 (FIX-B)

**대상**: `scripts/lib/check.py` stale staging 감지 (T5 코드)

**동작**:
- N == 1: 기존 그대로 (`warning: 중단된 설치 감지 (runid=..., age=...s). 복구: ...`)
- N >= 2: 한 줄 요약 (`warning: {N}개 중단된 설치 감지 (oldest runid=..., age=...s). 복구: ...`)

**테스트**: `tests/test_check_staging_detection.py:test_multiple_stale_dirs` 어서트를 "N개" 패턴으로 변경.

### 4단계: atomic write 함수 통합 (FIX-C)

**비교**:
- `scripts/lib/install.py:_atomic_write_json_fsync`
- `scripts/lib/atomic_io.py:atomic_write_text`

**작업**:
- atomic_io.py 쪽을 카논으로 채택
- install.py의 `_atomic_write_json_fsync`는 thin wrapper로 변경하거나 직접 import로 대체
- pytest 풀로 회귀 확인 (특히 install/upgrade 테스트)

### 5단계: 문서 sweep (README / manual.html / 기타)

**목표**:
- v0.9.6 → v0.9.7 잔존 ref 정리
- v0.9.4 → v0.9.7 격리 경고 신설
- 진행 표시 추가된 거 매뉴얼에 한 줄 언급

**대상 파일** (반드시 확인):
- `README.md`
- `docs/USER_MANUAL.md`
- `docs/site/manual.html` (USER_MANUAL.md 재생성)
- `docs/site/index.html`
- `docs/site/use-cases.html`
- `docs/use-cases/README.md`
- `CHANGELOG.md` (v0.9.7 entry 보강)

**확인 사항**:
1. `git grep -nE 'v?0\.9\.6' -- ':!CHANGELOG.md' ':!.planning'` → 의도된 히스토리만 남기고 모두 0.9.7
2. **v0.9.4 → v0.9.7 격리 경고 신설**: USER_MANUAL에 "v0.9.4에서 업그레이드 시 주의사항" 섹션 추가
   - "기존 v0.9.4 설치에는 매니페스트에 없는 lib 파일이 있을 수 있음 (v0.9.4 STALE-1 버그). 업그레이드 시 이 파일들이 `.harness/conflicts/`로 격리됨. 확인 후 안전하면 삭제 가능."
   - 한국어 + 영어
3. CHANGELOG에도 같은 경고 한 줄 추가
4. **진행 표시 한 줄 언급**: USER_MANUAL과 CHANGELOG에 "init/upgrade 진행 상태 stderr 출력 (`--quiet`로 비활성화)" 추가
5. `state repair` 출력 예시가 실제 코드 emit string과 일치하는지 grep 재확인
6. manual.html 재생성 (기존 generator script 사용)

### 6단계: 최종 검증

```bash
PYTHONPATH=scripts python3 -m pytest tests/ -q --junitxml=.harness-test-cache/junit.xml
# 35 failed (all in KNOWN_FAILING_TESTS.md), pass count up
PYTHONPATH=scripts python3 -m pytest tests/test_known_failures_drift.py -q
# green

# Smoke
python3 scripts/project_dashboard.py --check  # ok
git grep -nE 'v?0\.9\.6' -- ':!CHANGELOG.md' ':!.planning'  # only historical

# 직접 init 한 번 돌려서 progress 잘 나오는지 눈으로 확인
rm -rf /tmp/v097-final-smoke && mkdir -p /tmp/v097-final-smoke
PYTHONPATH=scripts python3 scripts/harness.py init --target /tmp/v097-final-smoke --profile generic --adapter roo
# stderr에 staging/batch progress 라인 나오는지 확인
```

### 7단계: 어드버서리얼 최종 1라운드

- codex CLI에 diff (main..develop) 적대적 리뷰 요청
- PASS 받으면 다음 단계
- 시간 여유 있으면 Opus 3-panel 한 번 더 (선택)

### 8단계: 릴리스

```bash
# 메모리 workflow_orchestration 참고
git tag -s v0.9.7 -m "v0.9.7: atomic install staging + crash recovery + progress UX"
git push origin develop
git checkout main && git merge --ff-only develop && git push origin main
git push origin v0.9.7
# GitHub release create (CHANGELOG에서 발췌)
```

### 9단계: 메모리 업데이트

- `project_v097_released.md` 신규 (v0.9.5/v0.9.6 패턴 참고)
- `MEMORY.md` 인덱스에 한 줄 추가
- `project_v097_pre_release.md` 메모리는 SUPERSEDED 표시
- `project_v094_install_broken.md`, `project_v095_hotfix_scope.md`는 해결됨 표시

---

## Deferred (이번 세션 안 함)

- **SIGTERM E2E test-seam**: 당장은 큰 문제 아님. v0.9.8 이후.
- **`.complete.tmp` 청소 audit row**: 너무 예외적. drop.
- **Pre-existing 35 failure**: v0.9.8 백로그 유지.

---

## 컨텍스트 파일 (세션 시작 시 빠르게 훑기)

- `.planning/phases/02f-v0.9.6-hotfix/plans/PLAN.md` (REV-5 — 디자인 계약)
- `.planning/phases/02f-v0.9.6-hotfix/plans/IMPL-PLAN.md` (REV-2)
- `.planning/phases/02f-v0.9.6-hotfix/evidence/impl-summary.md`
- `.planning/phases/02f-v0.9.6-hotfix/evidence/impl-deviations.md`
- `.planning/phases/02f-v0.9.6-hotfix/reviews/DIFF-review-codex-final.md` (PASS)
- 메모리: `workflow_orchestration`, `feedback_plan_location`, `feedback_internal_only_threat_model`, `feedback_unittest_verification`

## 작업 원칙

- 1단계 (진행 표시)가 사용자 체감 가장 큼 → 우선.
- 각 FIX/feature는 atomic commit.
- pytest baseline 유지: 35 failed (all KNOWN). 새 fail 나오면 즉시 잡기.
- progress 출력은 stderr 전용. stdout 포맷 변경 금지 (기존 파서 호환).
- 절대로 `--no-verify` 같은 거 안 씀.
- 태그/푸시는 6단계 검증 + 7단계 codex PASS 후에만.

## 예상 소요

- 1단계 진행 표시: 1.5시간 (callback 박고 phase별 출력 + 테스트)
- 2-4단계 UX fix A-C: 1시간
- 5단계 문서 sweep + 격리 경고 신설: 1시간
- 6-8단계 검증 + codex + 릴리스: 30분
- **총 4시간 예상**
