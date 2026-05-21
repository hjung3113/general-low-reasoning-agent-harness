# Low-Reasoning Realist (LRR) Final Diff Review — v0.9.7

Verdict: BLOCK

Lens: stressed Korean-first operator at 2am. CLI exit codes, error message clarity, doc-to-code consistency.

## CRIT (block tag)

### C-1: `harness state repair` returns rc=0 even when files are quarantined — operator gets a green light on partial failure
`scripts/lib/state_cli.py:99-140` `run_repair` always returns 0. `docs/USER_MANUAL.md:1101-1107` Exit codes table promises:
| 0 | clean / no-op |
| 1 | partial — `.harness/conflicts/` 격리된 파일 있음 |
| 2 | catastrophic |

The docs LIE. A 2am operator who reads the manual, runs `state repair`, sees rc=0, and goes back to sleep will MISS `.harness/conflicts/` accumulating. The whole point of the bilingual error messages and exit code contract is to give the stressed operator a single signal — and that signal is broken.

The `USER_MANUAL.md:1117-1123` "실패 출력 예시 (orphan-pending, rc=1)" example shows `exit code 1` — but the code path that would produce that exit code does not exist anywhere in the diff. Search: `grep -n "return 1" scripts/lib/state_cli.py` returns only the unrelated `run_show` lock-contention path at line 61.

This is a direct repeat of v0.9.5 NEW-3 (exit code 0 on all errors). The IMPL-PLAN REV-2 line 41 explicitly invokes "v0.9.5 NEW-3 repeat" as the motivation for pinning these codes. The motivation made it into the plan; the implementation did not honor it.

Fix: 5-line change in `state_cli.run_repair`. Test: add CLI assertion in `tests/test_install_recovery_pending_manifest.py` that pipes through `state_run_repair` and asserts rc.

### C-2: T12 evidence file scenarios 2/3/5 are NOT real CLI output — they are reformatted unit-test results pretending to be smoke
`smoke-2026-05-21.md:25-38, 44-51, 75-83`: scenarios 2, 3, 5 contain pseudocode/test-result excerpts, not real CLI sessions. Scenario 2 quotes `Repair 1: RecoveryResult(action=<RecoveryAction.QUARANTINE: ...>` — this is Python repr output from a unit test, not what a user typing `python3 scripts/harness.py state repair` would see.

A real 2am operator running `state repair` after a crash will see whatever `state_cli.run_repair` writes — which (per current code, `state_cli.py:122-139`) writes "updated:\n", "markers_added:\n", "canonicalized:\n", "warnings:\n", "nothing to repair (already canonical)\n". The smoke evidence does NOT show ANY of these strings for scenarios 2/3/5.

This means: nobody has actually verified what a real recovery output looks like to a user. The "성공 출력 예시" in USER_MANUAL:1111-1115 shows `recovered: finalized pending manifest (runid=..., version=0.9.7)` — but searching the codebase for that exact string returns NO HITS. The manual documents output that no code produces.

Action: run the CLI for each smoke scenario, paste the actual stdout/stderr into the evidence file AND into USER_MANUAL, OR adjust the docs to match what the code currently emits.

## MAJOR (must fix before tag)

### M-1: Bilingual error messages have Korean punctuation issues in terminal display
`install.py:351-357` `CrossFilesystemError`:
> "타겟 파일시스템이 atomic rename 을 지원하지 않습니다. 복구 명령: python3 scripts/harness.py state repair (또는 HARNESS_ALLOW_NONATOMIC_INSTALL=1 로 비-atomic 강제 — 권장하지 않음) [Target filesystem does not support atomic rename. ...]"

Single very long line with em-dash, mixed parentheses, no line break before the English bracket. In a 80-column terminal this wraps mid-word and the operator must scroll. Compare with `upgrade.py:121-126` UpgradeRefused which is also one long line.

Action: use explicit `\n` line breaks for human readability. Korean line first, blank line, English line. The `repair: python3 scripts/harness.py state repair` action MUST be on its own line so a copy-paste works.

### M-2: `harness check` warning is noisy but actionable — good text, missing rate limit
`check.py:778-785` emits one warning line per stale staging dir:
> "warning: 중단된 설치 감지 (runid=99999-..., age=1200s). 복구: python3 scripts/harness.py state repair [Aborted install detected; recover with state repair]"

Good: bilingual, has runid, has age, has recovery command. Bad: if a CI loop or a developer leaves many `.staging-*` dirs around (which the deferred-cleanup design EXPECTS during normal operation, until `state repair` runs), `harness check` will print N warnings every run. No rate limit, no "1 of N" summary. A 2am operator who sees 5 warnings will not know if it's 5 separate problems or one repeated.

Action: collapse to "warning: N aborted install(s) detected (oldest runid=..., age=...). 복구: ..." when N > 1. Test 5 of `tests/test_check_staging_detection.py` ("Multiple stale dirs → one warning per dir") is the wrong test — it should be "one summary warning with N count".

### M-3: USER_MANUAL examples reference output strings that do not exist in code
- `USER_MANUAL.md:1113`: `recovered: finalized pending manifest (...)` — `grep -rn "recovered: finalized" scripts/` returns nothing.
- `USER_MANUAL.md:1121-1122`: `warning: quarantined orphan pending manifest to .harness/conflicts/...` — `grep -rn "quarantined orphan pending" scripts/` returns nothing.

The audit verbs (`install.recovery.pending_orphaned`, `install.recovery.finished`) are written to `.harness/audit.log`, NOT to stdout for the operator. The operator running `state repair` sees the state_cli output (warnings list), which is verbose Python-style not human-friendly.

Action: either add the documented output lines to `state_cli.run_repair` (and `install_recovery._emit_audit` for stdout mirroring), or remove the misleading examples from the manual.

### M-4: KNOWN_FAILING_TESTS.md env mismatch with IMPL-PLAN
`KNOWN_FAILING_TESTS.md:5`: "Environment: Python 3.9.6 (system)".
`IMPL-PLAN.md:380`: "Environment: Python 3.14 (homebrew), pinned dev requirements".

A teammate running drift-gate under Python 3.14 will see a different failing set. Drift gate will RED. The 2am operator chasing a CI failure will hit this and waste an hour.

Action: either reseed under Python 3.14 OR amend IMPL-PLAN to admit 3.9.6 is the actual baseline. Document in CHANGELOG.

## MINOR

- `install.py:418` success message: `installed harness v0.0.0-dev+unknown → ... (168 planned writes). Next: cd ... && python3 scripts/harness.py check` — good, but `0.0.0-dev+unknown` looks broken to a non-developer. Worth a "(dev build)" suffix.
- `upgrade.py:122-126` skip-upgrade error is bilingual but the override hint `HARNESS_ALLOW_SKIP_UPGRADE=1` appears in BOTH Korean and English sections — redundant. Trim to once.
- `CHANGELOG.md` v0.9.7 entry should mention "Exit code 1 returned on quarantine partial recovery" as a user-visible behavior change, IF C-1 is fixed.
- `T8-triage.md:36`: "These 35 extra files are correctly quarantined (not a bug)" — but the operator inheriting a v0.9.4 install with the v0.9.4 STALE-1 bug will see 35 surprise quarantines. Recommend a one-time-only `harness migrate v094-cleanup` helper, or a CHANGELOG note explicitly stating "Existing v0.9.4 installs with extra lib files may see N file quarantines on first upgrade — this is expected behavior."

## Confirmations (correctly implemented)

- Bilingual error message bodies present at all key paths (`install.py:351-357, 368-369, 383-385`; `upgrade.py:113-126, 1025-1027, 1051-1053`).
- Each error message includes the actionable next command (`python3 scripts/harness.py state repair`).
- USER_MANUAL B2.3a section exists (`USER_MANUAL.md:1093-1136`) and is in Korean-first format.
- `harness check` stale-staging warning includes runid + age (smoke evidence scenario 8).
- Skip-upgrade error message contains both Korean and English with override hint.

## Recommended next step

BLOCK the tag until C-1 (exit code wiring) is fixed AND smoke evidence is regenerated against the fixed code with real CLI output (closes C-2). Both are mechanical. After that the manual examples in M-3 must be verified against actual stdout.
