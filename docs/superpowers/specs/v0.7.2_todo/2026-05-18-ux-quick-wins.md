# v0.7.2 UX Quick Wins — 부작용 0 문구/문서/prompt 패치

**Date:** 2026-05-18
**Parent:** [2026-05-18-ux-improvements-discovery.md](../2026-05-18-ux-improvements-discovery.md)
**Reviewer consensus:** Archimedes + Hubble + safety/product 관점 합치
**Constraint (절대 위반 금지):**
- schema 변경 X
- exit code 의미 변경 X
- approval-security boundary 우회 X
- install semantics 변경 X
- JSON output shape 변경 X (필드 추가/제거/이름변경 X)
- 새 CLI verb / alias 등록 X
- structured output 도입 X (단순 문자열 보강만)

목표: 저추론 agent가 복붙해도 깨지는 문구/dead link/silent stall 제거. 패치는 **문자열·문서·prompt only**.

---

## Group A — 유령 verb / 내부 명칭 누출 sweep

**A1. `harness phase status` → `harness status` sweep**
- `scripts/lib/cli_budgets.py:441-447` 외 7+ 곳
- Fix-line, 에러 메시지, 문서 grep-replace
- Verb 자체는 미등록 (실제는 `harness status`) — alias 등록은 0.8.0
- **검증:** `grep -rn "phase status" scripts/ docs/ .roo/ .opencode/ | grep -v "^scripts/.*\.py.*#"` 결과 0

**A2. `(lands Sxx)` 내부 슬라이스 명칭 제거**
- `scripts/lib/anchor_cli.py:180` 외 grep
- 사용자에게 의미 없는 maintainer-only 명칭
- **검증:** `grep -rn "lands S[0-9]" scripts/` 결과 0

**A3. 리터럴 `...` placeholder 제거**
- `scripts/lib/check.py:104,113-117` — `harness phase set ...` 리터럴
- 실제 phase 값으로 채우거나 `<phase>` 같이 의도 명시
- **검증:** check.py에 `phase set ...` 리터럴 0

---

## Group B — `check.py` `Fix:` 라인 보강 (문자열 only)

**B1. `check_phase_state_semantics` missing-field 오류 13곳**
- `scripts/lib/check.py:469/471/474/491/493/506/509/511/513/516/527/689/701`
- 각 `SystemExit(msg)`에 `Fix: <concrete next verb>` append
- **금지:** 메시지 누적/구조화 (그건 0.8.0)
- **검증:** 위 13 라인 모두 `"Fix:"` substring 포함

**B2. install drift 오류에 `Fix: harness upgrade`**
- `scripts/lib/check.py:251/322/341/357/365/374/386`
- Manifest sources missing / Installed target missing files / Retired files remain → `Fix: harness upgrade --target <target>` append

**B3. `--worktree` 거부 메시지 (`check.py:283` via `worktree.py:264`)**
- "requires phase=execute…" → `Fix: this check is only meaningful during execute/done. Skip --worktree, or run after `harness phase set execute`.`

**B4. skeleton contamination 메시지 (`check.py:443-450`)**
- 개발자 전용이지만 Fix 안내 추가: `Fix: git checkout HEAD -- <path>, or update CONTAMINATION_PATTERNS allowlist if intentional.`

**B5. scope-violation Fix 라인 중복 (`worktree.py:32-50`)**
- 3-bullet Remediation + tail `Fix:` 라인 충돌 → 단일 canonical Fix 라인으로 통합
- 메시지 내용은 보존, 중복 라인만 제거

---

## Group C — `phase reopen --reason` placeholder

**C1. 리터럴 `"fix and re-approve"` → `"<describe what you fixed>"`**
- `scripts/lib/status_next.py:178/319`
- Fleet 전체가 같은 의미 없는 reason으로 audit-trail 오염되는 거 차단
- 상수 `_REOPEN_PLACEHOLDER_CMD` 도입 (모듈 내부만)
- **검증:** `grep "fix and re-approve" scripts/lib/` 결과 0

---

## Group D — install 첫 경험 침묵 제거 (문자열 only)

**D1. `init` 성공 메시지 1줄**
- `scripts/lib/install.py:118-138` non-dry-run 분기 끝에 `print(f"installed harness v{ver} → {target} ({n} files). Next: cd {target} && python3 scripts/harness.py check")`
- **금지:** install 로직/옵션/flag 변경 (0.8.0)
- **검증:** `lib/install.py` 변경 후 dry-run/real-run 출력 차이 줄 +1

**D2. "Refusing to overwrite" 메시지 보강 (`install.py:103-104`)**
- 파일 목록 newline-joined + 끝에 안내: `Hint: use 'harness upgrade --adopt-existing' to take ownership, or pick an empty directory.`
- **금지:** `--force` flag 신설 (0.8.0)

**D3. `install_harness.py:106` profile prompt 디폴트 힌트**
- `generic` 옵션 라벨에 `(recommended for first install)` 부착
- prompt 텍스트만 변경, 로직 X

---

## Group E — Documentation fixes

**E1. README §4 tree 케이싱**
- `README.md:125` `ADR/` → `adr/` (실제 디렉터리 일치)

**E2. USER_MANUAL dead anchor**
- `docs/USER_MANUAL.md:913` `§3.5.2` → 존재하는 살아있는 anchor로 교체 (`§7.2` 후보, 실제 anchor 확인 후 결정)

**E3. README "source vs installed" 선택 안내 (Hubble 추가 발굴)**
- README 상단 §1 또는 §2 진입부에 한 줄:
  `> source contributor (이 repo에서 작업) → 이 README. installed user (target 안에서 작업) → docs/USER_MANUAL.md`

**E4. placeholder convention 박스 (D6)**
- README §2 상단에 한 줄: `이 문서에서 \`/path/to/project\`는 your target absolute path.`

**E5. `docs/trust/README.md` v0.7.0 예시 (E12)**
- `docs/trust/README.md:35/44` — release-check 스코프 외부 확인 후 v0.7.1로 교체
- **확인 필요:** trust README가 `README_RELEASE_VERSION` regex 검사 대상인지

**E6. USER_MANUAL §19 끝에 "Common Confusions" 5-7개 (D10)**
- "approval 했는데 왜 execute 못 들어가?" 등 FAQ 추가
- 새 anchor만 추가, 본문 구조 변경 X

---

## Group F — Adapter prompt-only 정리 (문구만)

**F1. "when available" 모호 표현 명확화**
- `.roo/commands/done.md:13` 외 6 파일
- `Run \`harness check\`. If it exits non-zero with \`command not found\`, use legacy durable planning read order; on any other failure stop.`
- **금지:** 파일 신설, manifest hash 영향 가는 구조 변경 (0.8.0)

**F2. `phase-execute.md` exit-code 가이드 추가 (Roo)**
- `.roo/commands/phase-execute.md:13`
- OpenCode와 symmetric하게 `exits 0 with phase=execute, approved=true` 명시

**F3. Roo discuss/plan preflight checklist 추가**
- `.roo/commands/phase-discuss.md`, `phase-plan.md`
- OpenCode 9-13 라인 같은 preflight 추가 (문구만)

**F4. `done.md` 양쪽 `check --worktree` 순서 명시**
- Roo + OpenCode `done.md`
- `Step N (before \`harness phase set done\`): run \`harness check --worktree\`.`

**F5. `fsd-run-phase` `requires_human` 가드**
- `.roo/commands/fsd-run-phase.md`
- `fsd-run-all`과 symmetric — step 5 후 `harness next --json` 호출 + `requires_human` 체크 문구

**F6. `fsd-status.md` `.command` 실행 footgun 좁히기**
- `.roo/commands/fsd-status.md:15`, `.opencode/commands/fsd-status.md:11`
- `if agent_safe == true AND command begins with "harness "` 조건 추가 (prompt 문구만)

**F7. `.roo/commands/README.md` entry table 누락 보완 (Hubble 추가 발굴)**
- `/fsd-run-all`, `/fsd-status` 행 추가

**F8. `.opencode/README.md` 신설 (Hubble 추가 발굴)**
- 짧은 한 페이지: "OpenCode는 positional substitution 미지원. Roo/OpenCode는 adapter일 뿐 source of truth 아님."
- manifest 영향 확인 후 추가 — **manifest hash 영향 있으면 0.8.0로 이전**

---

## Group G — argparse 오타 제안 (에러 문구만, alias 등록 없음)

**G1. unknown verb 시 `Did you mean` 힌트**
- `scripts/harness.py` argparse 래핑
- `difflib.get_close_matches`로 가까운 verb 1-2개 stderr에 출력
- **금지:** alias 등록 (실제 verb 추가 — 0.8.0)
- **검증:** `harness phse approve` → stderr에 `Did you mean 'phase'?`, exit 2 유지

---

## Group H — Human-only 출력 보강 (JSON shape 불변)

**H1. `Next action: none — <reason>` 항상 표시**
- `scripts/lib/status_next.py:346-419` `format_status_human`
- next_action None일 때 줄 자체 생략하지 말고 `Next action: (none — <reason>)` 항상 출력
- **JSON shape 불변** — `format_status_json`은 손대지 않음
- **검증:** human path에서 phase=done이거나 autopilot active일 때 "Next action" 라인 항상 보임

**H2. halt age `>= 3600` 단위 변환**
- `scripts/lib/status_next.py:393-411`
- `Ns` / `Nm` 외에 `>=3600` → `Nh`, `>=86400` → `Nd`
- 가독성만 — 데이터 X

**H3. `--json` / `--format json` help에 "machine-readable" 단어 (Hubble 추가 발굴)**
- `harness.py` 관련 subparser들
- help 텍스트 한 단어 추가 — agent discovery 도움

**H4. `state show` human 출력에 `Next:` 힌트 (W13)**
- `scripts/lib/state_cli.py:14-54` `run_show` text format
- `compute_next` 호출해 `Next: <verb>` 한 줄 추가
- **JSON output 불변**

---

## Group I — Target-local wrapper help (Hubble 추가 발굴)

**I1. `scripts/check_harness.py`, `scripts/doctor_harness.py` help 보강**
- 두 wrapper의 `--help` 출력이 부실 — installed target user가 가장 자주 보는 cmd
- 1-2줄 설명 + 1개 예시 추가

---

## 전체 검증

각 group commit 후:
```bash
python3 -m unittest scripts/test_harness.py    # 228 baseline 유지
python3 -m pytest tests/                        # 1266 baseline (13 known fail 유지)
python3 scripts/harness.py release-check --expected-version v0.7.2  # README check 통과
```

**Adapter manifest hash 영향 체크 (Group F):**
```bash
# install_harness가 .roo/, .opencode/ 내용을 hash 검증하는지 manifest 코드 확인
grep -n "hash\|sha256" scripts/lib/manifest.py
```
manifest hash 영향 있으면 해당 항목만 0.8.0로 이전 (특히 F8 .opencode/README.md 신설).

---

## 예상 작업량

| Group | 항목 수 | 추정 시간 |
|---|---|---|
| A — sweep | 3 | 30분 |
| B — Fix-line | 5 | 1시간 |
| C — reopen placeholder | 1 | 10분 |
| D — install 침묵 | 3 | 30분 |
| E — docs | 6 | 45분 |
| F — adapter prompt | 8 | 1시간 |
| G — argparse hint | 1 | 30분 |
| H — human output | 4 | 45분 |
| I — wrapper help | 1 | 15분 |
| **합계** | **32** | **~5h** |

Adversarial review 1 cycle (Opus subagent) + 검증 포함 시 6-7시간.

---

## 비 v0.7.2 항목 (0.8.0로 이전)

본 spec에 포함 X. 0.8.0 spec 별도.

- `phase status` alias 등록, halt diary hidden alias
- `check`/`doctor`/`verify` help/epilog 전체 재설계
- `check.py` structured output, cumulative reporting
- `harness next --json` `fix` 필드 추가 (JSON shape 확장)
- skeleton에 `.roo`/`.opencode` 포함 + materialization 변경
- `.opencode/PREAMBLE.md` 추출, workflow-core hoist
- 없는 target dir 생성 prompt, dry-run 후 real install 이어가기
- friendly workflow CLI minimization design 통합

이유: 모두 **명령 계약 / JSON shape / install semantics / security boundary**에 닿음.
