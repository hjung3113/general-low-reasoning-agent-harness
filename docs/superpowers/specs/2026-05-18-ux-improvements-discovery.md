# UX Discovery — 부작용 0 개선 발굴 (INDEX)

**Date:** 2026-05-18
**Scope:** v0.7.1 직후, v0.7.2 또는 v0.8.0 후보 발굴
**Method:** 5 도메인 병렬 Opus 서브에이전트 (CLI / Install / Docs / Adapter / Workflow) + Archimedes/Hubble 안전·product 리뷰
**Constraint:** schema/exit-code/security 영향 0. 순수 UX/메시지/문서/prompt 개선만.

## 분기 (2026-05-18 리뷰 후 확정)

- **v0.7.2 quick-wins** (즉시 처리, 부작용 0 문구·문서·prompt) → [v0.7.2_todo/2026-05-18-ux-quick-wins.md](v0.7.2_todo/2026-05-18-ux-quick-wins.md)
- **v0.8.0 design touch** (CLI surface / JSON shape / install semantics / manifest hash) → [v0.8.0_todo/2026-05-18-ux-design-touch.md](v0.8.0_todo/2026-05-18-ux-design-touch.md)

**분기 기준 (Archimedes + Hubble + product 합의):**
- 문자열·문서·prompt만 건드리면 즉시 (v0.7.2)
- 명령 계약 / JSON shape / install semantics / approval boundary / manifest hash 닿으면 v0.8.0
- W8 (`Next action: none — <reason>`)처럼 human 출력만 바꾸면 즉시, JSON shape 바꾸면 v0.8.0 — **"human-only" 조건** 명시 (v0.7.2 spec Group H 참조)

본 문서는 발굴 원본 (78 finding × 5 도메인). 실제 작업 분기는 위 두 spec 참고.

---

## Cross-Cutting Pattern (5 도메인 공통)

1. **`Fix:` 라인 불균일** — `phase_approve.py` / `phase_reopen.py` / `transition.py`는 100% 커버, `check.py`는 ~20%. Agent가 막히는 곳 일관성 부족.
2. **유령 verb `harness phase status`** — 8+ 파일 Fix-line이 이 verb 추천하지만 argparse 미등록. 실제는 `harness status`. Agent가 따라가다 `invalid choice`로 막힘.
3. **Roo ↔ OpenCode 비대칭** — 같은 phase에 다른 가드/preflight/exit 안내.
4. **Boilerplate 중복** — `.opencode/commands/`에 4개 파일이 같은 preamble 줄 반복.
5. **Dead link / 경로 케이싱** — `USER_MANUAL §3.5.2` 미존재, README §4 tree 표기 `ADR/` vs 실제 `adr/`.

---

## 도메인 1 — CLI Surface (verb / help / error message)

원본 에이전트 ID: `ae6be321a21283bc0`

| # | Sev | Pri | File:Line | Issue | Suggested |
|---|---|---|---|---|---|
| C1 | HIGH | 1 | `harness.py:454/460/752` | `check` vs `doctor` vs `verify` — 헬프가 언제 무엇 쓸지 안내 X | 각 헬프 재작성 + `epilog` cross-link |
| C2 | HIGH | 1 | `harness.py:859/870` + `cli_budgets.py:444` 외 | 유령 verb `phase status` — Fix-line 다수가 미등록 verb 추천 | `phase status` → `status` sweep, 또는 alias 등록 |
| C3 | HIGH | 1 | `anchor_cli.py:180` | `Fix:` 라인에 `(lands S06)` 내부 슬라이스 명칭 누출 | `(lands Sxx)` 모두 제거 |
| C4 | HIGH | 1 | `harness.py:476/774/797/672` vs `:521/484/735` | kebab vs nesting 일관성 없음 (`halt-diary clear` vs `halt diary clear` 헷갈림) | hidden alias 등록, kebab을 canonical로 문서화 |
| C5 | MED | 1 | `harness.py:521/633/672/752/797/824/859/870` | `--help`에 spec § 참조 누출 (`§3.9`, `ADR-003a` 등) | docstring으로 이동, help는 평이한 한 줄 |
| C6 | MED | 1 | `harness.py:464-469/534-536/541-544/689-706` | `--help=` 누락 다수 flag (uninstall, phase set/approve, fsd-run-phase) | `help=` 채우기, `--select` 토큰 enum 명시 |
| C7 | MED | 2 | `harness.py:879-881` | `exit 17/18` 헬프에서 raw 숫자 — `exitcodes.py:14-38`엔 0-15만 | symbol 부여 (`EXIT_REQUIRES_HUMAN=17`) 또는 헬프 wording 변경 |
| C8 | MED | 2 | `phase_approve.py:78` 외 4곳 | TTY 거부 메시지에 actionable 안내 부족 | "Fix: 새 터미널 열고 대화형 실행. agent라면 사람에게 인계." 한 줄 |
| C9 | MED | 2 | `phase_approve.py:96` | nonce TTL Fix 라인이 120s 하드코딩 — `--ttl` 가변인데 | "default 120s" 표기 |
| C10 | MED | 3 | `harness.py:662` | SUPPRESS된 deprecated `--consumer-tty` alias — typo 시 cryptic argparse 오류 | `cli_deprecated.print_and_exit` 패턴 적용 |
| C11 | LOW | 2 | argparse 전반 | `harness phse approve` 오타 → 표준 argparse 오류만 | `difflib.get_close_matches`로 "Did you mean 'phase'?" |
| C12 | LOW | 3 | `harness.py:412` | `--adapters` 헬프가 "or both" → 3택인데 binary 인상 | "comma-separated; valid: none/roo/opencode" |
| C13 | LOW | 3 | `harness.py:666-669` | `next-pending` vs `next` 의미 충돌 | 헬프에 "not the same as 'harness next'" 명시 |
| C14 | LOW | 3 | 전 subparser | `epilog=` 부재 → 예시 없음 | high-traffic verb에 1줄 예시 |
| C15 | LOW | 3 | `harness.py:391` | `--version`이 print이 아닌 stamp override 의미 | `--release-version` 신설, `--version` deprecated alias |

---

## 도메인 2 — Install / First-Run

원본 에이전트 ID: `affa8eaf98e98e422`

| # | Sev | Pri | File:Line | Issue | Suggested |
|---|---|---|---|---|---|
| I1 | HIGH | 1 | `lib/install.py:118-138` | `init` 성공 시 출력 0줄 — next-action 부재 | `print(f"installed harness v{ver} → {target} ({n} files). Next: cd {target} && harness check")` |
| I2 | HIGH | 1 | `install_harness.py:41-55` | 없는 target dir 거부 — 다음 단계가 `mkdir(parents=True, exist_ok=True)`인데 | `Create [y/N]?` offer |
| I3 | HIGH | 1 | `install_harness.py:87/101` | wrong-choice → `SystemExit`, 모든 답변 손실 | `prompt_choice`/`parse_pack_selection` 내부 loop |
| I4 | HIGH | 1 | `lib/install.py:103-104` | "Refusing to overwrite" — remediation X | newline 정리 + "`upgrade --adopt-existing` 또는 빈 디렉터리" 안내 |
| I5 | HIGH | 2 | `install_harness.py:195-196` | dry-run 후 "real install? [y/N]" 미제공 — 전체 flow 재실행 | post-dry-run prompt 추가 |
| I6 | MED | 1 | `lib/check.py` raise 50+개 | 비구조화 `SystemExit("<short>")` — severity/fix 없음 | top-10에 doctor 스타일 `cause/fix` 적용 |
| I7 | MED | 1 | `lib/check.py:300/318/322/341/357/365` | fail-fast — 독립 문제 3개면 3 cycle | 누적 후 한 번에 출력 |
| I8 | MED | 2 | `lib/doctor.py:486-499` | finding 별 `## P1` H2 헤더 N개 — 요약 X | `# Doctor — 3 P1, 5 P2, 4 P3` 상단 |
| I9 | MED | 2 | `lib/doctor.py` 전반 | TTY ANSI 색상 X | `sys.stdout.isatty()` 게이트 최소 색 |
| I10 | MED | 2 | `install_harness.py:233` | `Equivalent command:` 사전 인쇄만, 성공 후 "wrote N files in X.Ys" X | 사후 요약 |
| I11 | MED | 2 | `lib/install.py:119-128` | 다수 파일 복사에 progress X | `…copying N files…` + done |
| I12 | MED | 2 | `upgrade_harness.py:104` | `git clone` raw 출력 노출 | "cloning {repo}@{ref}…" preface |
| I13 | LOW | 2 | `install_harness.py:106` | `generic` 디폴트지만 "처음이면 이것" 힌트 X | `(recommended for first install)` 부착 |
| I14 | LOW | 3 | `install_harness.py:124/187` | `none` 키워드 + Enter 동일 동작 — 중복 | `Enter to skip` |
| I15 | LOW | 3 | `uninstall_harness.py:50-65` | 동일 dry-run-후-실행 미제공 | I5와 동일 |
| I16 | LOW | 3 | `lib/check.py:104` | `harness phase set ...` 리터럴 `...` | `harness phase set discuss` |
| I17 | LOW | 3 | `install_harness.py:230-231` | argv 비고 stdin TTY면 argparse error 대신 interactive 자동 | `args.interactive=True` 자동 |

---

## 도메인 3 — Documentation (README + USER_MANUAL)

원본 에이전트 ID: `a86030af2347c5799`

| # | Sev | Pri | File:Line | Issue | Suggested |
|---|---|---|---|---|---|
| D1 | HIGH | 1 | `README.md:1-9` | 5초 파악 실패 — 누구/무엇 한 줄 부재 | "한 줄 결과:" hero 박스 |
| D2 | HIGH | 1 | `README.md` 전체 | TOC 없음 (231줄, 8 섹션) | `## 목차` 추가 |
| D3 | HIGH | 1 | `README.md:125` | tree에 `ADR/`, 실제는 `adr/` — Linux/Windows 케이싱 혼란 | `adr/` |
| D4 | HIGH | 1 | `USER_MANUAL.md:913` | `§3.5.2` cross-ref 미존재 | `§7.2` 또는 적절한 살아있는 anchor |
| D5 | HIGH | 2 | `USER_MANUAL.md:429-449` | Approve-Nonce "왜 필요" 부재 — 위협 모델 한 줄 X | prologue 1줄 추가 |
| D6 | HIGH | 2 | `README.md:32/76` 외 | placeholder 컨벤션 박스 부재 (`tmp=...` vs `/path/to/project`) | §2 상단 "Conventions" 박스 |
| D7 | MED | 2 | `USER_MANUAL.md:99-108` | adapter 첫 prompt 모호 — "둘 중 하나 골라" | "확신 없으면 §5.1 비교표" 한 줄 |
| D8 | MED | 2 | `USER_MANUAL.md` 전체 1215줄 | 단일 파일 과대 — guide vs reference 섞임 | "Part A / Part B" H1 분리 표식 |
| D9 | MED | 2 | `USER_MANUAL.md:911-913` | exit code 10/17/18 상수명 빈 칸 | canonical name 채우거나 일관 dash |
| D10 | MED | 3 | `USER_MANUAL.md` | FAQ/흔한 실수 섹션 없음 | §19 끝에 "Common Confusions" 5-7개 |
| D11 | MED | 3 | `README.md:32-49` vs `USER_MANUAL.md:54-69` | 첫 점검 명령 순서 mismatch | 한 쪽 참조 또는 통일 |
| D12 | LOW | 3 | `docs/trust/README.md:35/44` | 예시가 `v0.7.0` — 다른 곳 v0.7.1 (단 release-check 스코프 확인 필요) | maintainer 확인 권고 |
| D13 | LOW | 3 | `USER_MANUAL.md:1208-1216` | §21 link text가 raw path | description-leading anchor text |
| D14 | LOW | 3 | `README.md:55-71` | 9 시나리오 중 interactive vs flag-driven 패턴 미설명 | 표 위에 한 줄 가이드 |
| D15 | LOW | 3 | `USER_MANUAL.md:319/309-311` | "Generic agent" core-only flow 2줄에 그침 | §5.3 확장 — 첫 prompt + AGENTS.md 위치 |

---

## 도메인 4 — Adapter (Roo + OpenCode)

원본 에이전트 ID: `ae84122b22e5f9ef7`
**Claude-Code adapter는 의도적 부재 (F1 무효 — 본 repo는 Claude Code 전용 adapter 안 만듦)**

| # | Sev | Pri | File:Line | Issue | Suggested |
|---|---|---|---|---|---|
| ~~F1~~ | — | — | — | ~~`.claude/commands/` 부재~~ | **무효** — 의도적, adapter target 아님 |
| F2 | HIGH | 1 | `harness/skeleton/clean/` | skeleton에 `.roo/`/`.opencode/` 미포함 — fresh target에 slash cmd 없음 | install 단계가 materialize 또는 skeleton에 포함 |
| F3 | HIGH | 1 | `.roo/commands/fsd-run-phase.md:11` vs `.opencode/.../fsd-run-phase.md:7` | argv 처리 비대칭 — OpenCode는 `$ARGUMENTS` 미지원, slug 무시됨 | "OpenCode는 slug 미지원, `phase set ...` 먼저" 명시 |
| F4 | HIGH | 1 | `.roo/commands/done.md:13` 외 6 | "when available" 모호 — agent skip 위험 | "exit non-zero with `command not found`이면 legacy, 다른 실패면 stop" |
| F5 | HIGH | 2 | `.roo/commands/phase-execute.md:13` | exit-code 가이드 없음 — OpenCode는 있음 | "exits 0 with phase=execute, approved=true" 추가 |
| F6 | MED | 2 | Roo vs OpenCode `done.md` | `check --worktree` 순서 모호 | "Step N (before `phase set done`):" 명시 |
| F7 | MED | 2 | `.opencode/commands/fsd-run-all.md:18` | "Manual handoff per §5.3" — anchor 없음 | Roo와 동일하게 inline 조건 |
| F8 | MED | 2 | `.roo/.../fsd-run-all.md:20` vs `fsd-run-phase.md` | `requires_human` 가드 비대칭 | fsd-run-phase에도 추가 |
| F9 | MED | 2 | `.roo/.../phase-discuss.md` vs `.opencode/.../discuss.md:9-13` | preflight checklist Roo에만 없음 | Roo discuss/plan에도 추가 |
| F10 | MED | 3 | `.opencode/commands/{discuss,done,execute,plan}.md:5` | "Before proceeding, read every file under `.opencode/profile-rules/`..." 4중 verbatim | `.opencode/PREAMBLE.md` 추출 + reference |
| F11 | MED | 2 | `.roo/.../fsd-status.md:15` vs `.opencode/.../fsd-status.md:11` | `.command` execute에 footgun — read-only intent인데 임의 execute | `agent_safe == true AND command begins with "harness "` |
| F12 | MED | 3 | `.roo/commands/` 다수 | "harness check when available..." 8× 중복 | workflow-core skill-pack로 hoist |
| F13 | LOW | 3 | `.roo/.../phase-execute.md:28` | "symmetric with `.opencode/...`" maintainer 메모가 agent 노이즈 | comment/README로 이동, heading은 간결 |
| F14 | LOW | 3 | `.opencode/.../execute.md:17-25` | preflight + check 가드 중복 — 같은 verb 두 번 | 단일 list |
| F15 | LOW | 3 | `.roo/.../fsd-run-phase.md` step 6 | Next action 빈 경우 분기 없음 — silent stall | "둘 다 비면 raw status surface 후 stop" |
| F16 | LOW | 3 | `harness/profiles/*/rules/` | `etl-tdd.md` 등 stack 간 동명 — 디렉터리만 구분 | prefix 또는 commands가 profile dir 동반 |

---

## 도메인 5 — Workflow Guidance (phase gate / next-action / 메시지)

원본 에이전트 ID: `a9fb28ab06f85317e`

| # | Sev | Pri | File:Line | Issue | Suggested |
|---|---|---|---|---|---|
| W1 | HIGH | 1 | `lib/worktree.py:32-50` | scope-violation Fix가 3-bullet Remediation + tail `Fix:` 라인 충돌 | 단일 canonical Fix |
| W2 | HIGH | 1 | `lib/check.py:540-544/558-562/577-582` | plan/execute/done missing-field 오류에 Fix 없음 | `Fix: harness phase set plan --stdin-json {...}` 추가 |
| W3 | HIGH | 1 | `lib/check.py:469/471/474/491-516/527/689/701` | ~13 `SystemExit`에 `Fix:` 없음 — `check.py` 일관성 깨짐 | 각각 `Fix: <verb>` 추가 |
| W4 | HIGH | 1 | `lib/check.py:251/322/341/357/365/374/386` | install drift 오류에 Fix X | `Fix: harness upgrade` 추가 |
| W5 | HIGH | 2 | `lib/status_next.py:178` | `phase reopen --reason "fix and re-approve"` 리터럴 — 함대 전체가 같은 reason | `<describe what you fixed>` placeholder |
| W6 | MED | 2 | `lib/status_next.py:319` | 같은 리터럴 reason | 상수 `_REOPEN_PLACEHOLDER_CMD` |
| W7 | MED | 2 | `lib/check.py:113-117` | `harness phase set ...` 리터럴 `...` | 실제 phase 읽어 채움 |
| W8 | MED | 2 | `lib/status_next.py:346-419` | next_action None일 때 라인 자체 생략 — silent absence | `Next action: (none — <reason>)` always |
| W9 | MED | 2 | `lib/cli_budgets.py:441-447` | `harness phase status` 추천 (유령 verb) | `harness status` |
| W10 | MED | 2 | `lib/halt_diary.py:135` | clear 시 state 없음 + cwd 힌트 X | cwd 표기 |
| W11 | MED | 3 | `lib/transition.py:166-170` | halt unack Fix가 `halt-diary clear` OR `phase reopen` — 선택 기준 X | "incidental이면 clear, 다시 plan/approve 필요면 reopen" |
| W12 | MED | 3 | `lib/phase_cli.py:63-68` | LOCKFILE 메시지에 instruction 3중 | 단일 Fix + bullets |
| W13 | LOW | 3 | `lib/state_cli.py:14-54` | text format이 `next_action`/`verification` 생략 | compute_next 호출해 `Next:` 한 줄 추가 |
| W14 | LOW | 3 | `lib/check.py:443-450` | skeleton contamination 메시지 Fix X | `git checkout HEAD -- <path>` 또는 allowlist 갱신 |
| W15 | LOW | 3 | `lib/status_next.py:393-411` | halt age `1500m ago` 같이 무한 분 단위 | `>=3600` → `Nh`, `>=86400` → `Nd` |
| W16 | LOW | 3 | `lib/check.py:283` | `--worktree` 거부 메시지가 "requires"만 — 무엇 할지 X | "Skip --worktree 또는 execute 전환 후 재실행" |

추가 cross-cutting:
- `lib/status_next_cli.py:263` — `harness next --json` 호출자(agent)는 Fix string 못 받음. `format_next_json` shape에 `fix` 필드 추가 (additive).
- `harness state show --json` flag 인간 path에 광고 X — agent discovery 어려움.

---

## v0.7.2 Patch 후보 (부작용 0, ~2-3시간)

1. **C2 + W9** — `phase status` → `status` sweep (8+ 파일, grep-replace)
2. **C3** — `(lands Sxx)` 내부 슬라이스 명칭 누출 제거
3. **I1** — `init` 성공 메시지 1줄
4. **W3 + W4** — `check.py` Fix-line ~20 자리 sweep
5. **D3 + D4** — README ADR 케이싱 + USER_MANUAL dead anchor
6. **W5/W6** — reopen `--reason` placeholder

## v0.8.0 후보 (design touch)

- F2 — skeleton에 adapter 포함
- F10/F12 — `.opencode/PREAMBLE.md` 추출, workflow-core hoist
- C1 — `check`/`doctor`/`verify` epilog cross-link + 헬프 재작성
- I6/I7 — `check.py` doctor-style structured output + 누적 보고
- 기존 `friendly-workflow-cli-minimization-design.md` 와 통합 검토

---

## 진행 추적

| Bucket | 항목 수 | 누적 작업 추정 |
|---|---|---|
| v0.7.2 후보 (즉시) | 6 group | 2-3h |
| v0.8.0 후보 (design) | 5 group | 1-2일 |
| LOW backlog | ~30 | 추후 |
