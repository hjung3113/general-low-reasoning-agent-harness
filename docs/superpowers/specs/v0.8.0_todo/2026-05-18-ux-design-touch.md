# v0.8.0 UX Design Touch — 명령 surface / JSON shape / structural

**Date:** 2026-05-18
**Parent:** [../2026-05-18-ux-improvements-discovery.md](../2026-05-18-ux-improvements-discovery.md)
**Sibling:** [../v0.7.2_todo/2026-05-18-ux-quick-wins.md](../v0.7.2_todo/2026-05-18-ux-quick-wins.md) (먼저 처리)
**Related:** [../2026-05-18-friendly-workflow-cli-minimization-design.md](../2026-05-18-friendly-workflow-cli-minimization-design.md) — 통합 검토 대상

## 0.8.0 분기 사유

v0.7.2 patch는 문자열·문서·prompt 변경만 다룸. 아래 항목은 모두 다음 중 하나 이상 건드림:
- 명령 계약 (새 verb / alias)
- JSON output shape (필드 추가/변경)
- install semantics (성공/실패 조건)
- security/approval boundary
- manifest hash (skeleton/adapter 파일 추가)

따라서 spec/ADR 작업 + 적대적 리뷰 panel + 2-cycle 보강 필요.

---

## Section 1 — CLI surface 재설계

### 1.1 `harness phase status` alias 등록
- v0.7.2 sweep으로 문구 수정. 이후 진짜 alias를 `phase` subparser에 등록하면 양쪽 다 동작
- 단순 alias라 위험 낮지만 새 verb 등록 = 명령 계약 변경

### 1.2 `halt-diary` 등 kebab vs nesting 통일
- `harness halt-diary clear` (canonical) + `harness halt diary clear` (hidden alias)
- 같은 패턴: `release-check`, `approve-nonce`, `fsd-run-phase`

### 1.3 `check` / `doctor` / `verify` 헬프 + epilog 재설계
- 3 verb 의미 분리 명시:
  - `check` = 구조/정책 검증, 빠름, pre-commit-grade
  - `doctor` = drift 진단, 느림, fix-list 출력
  - `verify` = audit-chain 암호 검증, tamper 알람 후
- 각 subparser에 `epilog`로 cross-link

### 1.4 `init` / 각 verb의 `epilog=` 예시 추가
- argparse `epilog="Examples:\n  ..."`
- high-traffic verb 우선: `init`, `phase set/approve`, `autopilot start`, `status`, `next`, `verify`

### 1.5 `--version` 의미 정리
- 현재 `--version` = stamp override (`--release-version`스러운 동작)
- `--version`만 = print version (관용)으로 변경, override는 `--release-version`로 신설
- deprecated alias 한 사이클 유지

### 1.6 누락 `help=` 채우기
- `harness uninstall --select`, `phase set/approve` flags, `fsd-run-phase` flags
- v0.7.2에 일부 가능하지만 enum 토큰 명시 + `--select` 의미 확장은 design 결정 필요 → 0.8.0

---

## Section 2 — JSON shape 확장 (additive)

### 2.1 `harness next --json`에 `fix` 필드 추가
- 현재 Fix 힌트는 stderr only (`status_next_cli.py:268-296`)
- JSON 호출자 (agent)는 받지 못함
- additive 변경이지만 contract test 필요 + adapter prompt 갱신 동반

### 2.2 `format_status_json`에 `last_halt_age_human` 추가 (옵션)
- 현재 raw seconds만 — agent가 단위 변환 필요
- additive 필드, optional

---

## Section 3 — `check.py` 구조화 출력

### 3.1 누적 finding 보고
- 현재 fail-fast — 첫 실패에서 abort, 사용자 3-cycle 반복
- 누적 후 한 번에 출력 + exit non-zero
- **위험:** 기존 fail-fast 동작에 의존하는 caller 영향 (pre-commit hook 등)

### 3.2 doctor-style severity 분류
- `cause` / `fix` 구조화된 finding 도입
- text format은 호환 보존, `--format json` 신설

---

## Section 4 — Install 흐름 개선

### 4.1 없는 target dir 생성 prompt
- `install_harness.py:41-55` 단순 거부 → `Create [y/N]?` 후 mkdir
- install semantics 변경 (현재는 명시적으로 dir 존재 요구)

### 4.2 dry-run 후 real install 이어가기
- `install_harness.py:195-196` → post-dry-run `Proceed with real install? [y/N]`
- 같은 flow 안에서 두 단계, 답변 보존
- 동일 패턴 `uninstall_harness.py`

### 4.3 wrong-choice loop
- `prompt_choice` / `parse_pack_selection`에서 SystemExit 대신 re-prompt
- interactive flow 답변 손실 차단
- 의미상 install semantics 영향 없지만 reviewer가 boundary 검토 권고

### 4.4 progress 표시
- `lib/install.py:119-128` 다수 파일 복사에 단순 dot/percent
- `lib/check.py` 다수 검사에도 단계 표시

---

## Section 5 — Adapter 구조 정리

### 5.1 skeleton에 `.roo/` + `.opencode/` 포함
- 현재 `harness/skeleton/clean/`에 adapter 없음
- fresh target에 slash command 없는 상태 → install 단계가 adapter dir materialize
- **manifest hash 직격** — install record + verify 둘 다 영향

### 5.2 `.opencode/PREAMBLE.md` 추출
- `.opencode/commands/{discuss,plan,execute,done}.md:5` 4중 verbatim → 단일 파일 reference
- manifest entry 추가 + 각 command가 PREAMBLE 참조
- **manifest hash 영향**

### 5.3 `.roo/commands/` boilerplate hoist
- "harness check when available..." 8× 중복 → `workflow-core` skill-pack로 이전
- skill-pack 의존성 변경 → install scope 영향

### 5.4 `.claude/commands/` 의도적 부재 명문화
- README 또는 ADR에 "Claude Code 전용 adapter는 만들지 않음" 1줄 + 이유 (이 repo가 Claude Code 자체임)
- 0.7.2에 docs/README 줄 추가는 가능하지만 ADR 작성은 0.8.0

### 5.5 Roo ↔ OpenCode argv 처리 비대칭 (F3)
- Roo: `$ARGUMENTS` 지원, OpenCode: 미지원
- 0.7.2에 prompt 문구로 명시 가능. 실제 OpenCode side에 substitution 우회 메커니즘은 0.8.0

---

## Section 6 — friendly-workflow-cli-minimization-design 통합

기존 `2026-05-18-friendly-workflow-cli-minimization-design.md`가 제안한 reshuffle (5 user-facing cmd + guide/enforce mode + `--for-agent --json` machine contract)와 **본 spec의 sections 1-5** 사이 중복/충돌 점검:

- friendly design 의 `harness next --for-agent --json` machine contract = 본 spec 2.1과 중첩 → friendly design 우선
- friendly design 의 `harness mode guide|enforce|show` = 본 spec 1.x 범위 밖, 큰 추가
- friendly design 의 `harness check` warning-first → 본 spec 3.1 (누적 보고)와 호환

**결정 필요:** v0.8.0이 friendly design 전체를 채택할지, 부분 채택할지. 본 spec sections 1-5는 friendly design 채택 시 일부 dead code 가능.

---

## 진행 순서 권고

1. **v0.7.2 quick-wins 먼저 출시** (1주 내) — fleet trust 회복
2. **friendly-workflow-cli-minimization-design 채택 범위 결정** (ADR) — 본 spec sections 1-5 중 어디까지 묶을지 명시
3. **v0.8.0 design freeze** — sections 1-5 + friendly design 채택분
4. **2-cycle adversarial review** (v0.7.0 패턴) — 3 Opus 페르소나 (CLI / install / adapter)
5. **v0.8.0 tag** — schema migration 동반 가능

---

## Out of scope (v0.9.0+)

- security boundary 변경 (e.g., approval-nonce TTY 서버 바인딩) — `[[project-02d-post-v080-deferred]]` 참조
- audit-chain GENESIS fallback 제거 — v0.7.0 carryover
- Windows native pre-commit-scope hook — v0.7.0 carryover
