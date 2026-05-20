# Harness Exit-Code Map

Canonical reference for every documented `(exit N)` hint in the codebase.
Generated from v0.9.5 audit — sources: `scripts/lib/*.py` + `scripts/harness.py`.

**Single source of truth for numeric values:** `scripts/lib/exitcodes.py`

---

## Table

| Code | Symbol | Verb / Sub-reason | Trigger condition | Source file:line |
|------|--------|------------------|-------------------|-----------------|
| 0 | `EXIT_OK` | any | Success / all phases done | `lib/exitcodes.py:14` |
| 1 | `EXIT_OPERATIONAL` | phase.set / session.unlock / state.show | General operational failure (bad args, file not found, etc.) | `lib/exitcodes.py:15` |
| 2 | `EXIT_INVALID_TRANSITION` | phase.set / phase.autopilot.start | Invalid phase transition; stale approval; invalid phase slug | `lib/exitcodes.py:16` |
| 2 | `EXIT_INVALID_TRANSITION` | fsd-run-phase / fsd-run-all | `multi_token_argument` or `slug_regex_mismatch` | `lib/fsd_wrappers.py:89,105` |
| 3 | `EXIT_SESSION_LOCKED` | phase.set / session.unlock / phase.autopilot.start | Another process holds the phase lock | `lib/exitcodes.py:17` |
| 4 | `EXIT_SCOPE_VIOLATION` | check (scope gate) | Files outside `allowed_paths` | `lib/exitcodes.py:18` |
| 4 | `EXIT_PATH_REPARSE_REFUSED` | safe_open (Windows) | Reparse point encountered on Windows path | `lib/exitcodes.py:32` |
| 4 | `EXIT_SCOPE_VIOLATION` | autopilot_guard shim | `autopilot_network_deny` — network command refused in autopilot mode | `lib/autopilot_guard.py:327` |
| 5 | `EXIT_UNPARSEABLE_JSON` | verify --audit | `AuditBomError` — BOM prefix in audit log | `lib/audit_verify_cli.py:119` |
| 5 | `EXIT_UNPARSEABLE_JSON` | verify --audit / manifest read | BOM or JSON parse error in installed-manifest | `lib/manifest_v2.py:89` |
| 5 | `EXIT_UNPARSEABLE_JSON` | state repair | `RepairRefusedError` — duplicate managed-block slug | `lib/state_repair.py:226` |
| 6 | `EXIT_WRONG_PHASE_FOR_VERB` | phase.autopilot.start (TTY) | `approver_not_in_install_record` — `by_email` not in install record | `lib/phase_autopilot.py:569` |
| 6 | `EXIT_WRONG_PHASE_FOR_VERB` | phase.autopilot.start (TTY) | `install_record_missing` — approvers list empty or record absent | `lib/phase_autopilot.py:581` |
| 6 | `EXIT_WRONG_PHASE_FOR_VERB` | phase.autopilot.start (TTY) | `human_proof_missing` — consumer_tty/nonce_audience/nonce_dir absent | `lib/phase_autopilot.py:605` |
| 6 | `EXIT_NONCE_SIGNATURE_INVALID` | phase.autopilot.start (TTY) | `signature_invalid` — nonce tampered or wrong secret.key | `lib/phase_autopilot.py:630` |
| 6 | `EXIT_WRONG_PHASE_FOR_VERB` | phase.autopilot.start (TTY) | nonce consume failed (various outcomes) | `lib/phase_autopilot.py:641` |
| 6 | `EXIT_WRONG_PHASE_FOR_VERB` | phase.autopilot.start (CI) | `ci_oidc_jti_replay` — OIDC token jti already consumed | `lib/phase_autopilot.py:704` |
| 6 | `EXIT_WRONG_PHASE_FOR_VERB` | phase.autopilot.start | `state_missing` — no state file present | `lib/phase_autopilot.py:849` |
| 6 | `EXIT_WRONG_PHASE_FOR_VERB` | phase.approve | `gitconfig_email_unset` or `install_record_missing` | `lib/phase_approve.py:321,443` |
| 6 | `EXIT_WRONG_PHASE_FOR_VERB` | autopilot_guard shim | `audit_write_failed` — both primary and fallback audit writes failed | `lib/autopilot_guard.py:273` |
| 7 | `EXIT_STALE_UNCERTAIN` | session.unlock | Lock pid absent or non-integer; staleness cannot be determined | `lib/exitcodes.py:22` |
| 8 | `EXIT_TIMESTAMP_OUT_OF_RANGE` | phase.set | `updated_at` timestamp outside ±60 s window | `lib/exitcodes.py:23` |
| 8 | `EXIT_TIMESTAMP_OUT_OF_RANGE` | phase.approve | `approve_during_autopilot` — approve attempted while autopilot active | `lib/phase_approve.py:553` |
| 9 | _(no symbol)_ | phase.autopilot / cli budgets | `budget_exhausted:<capability>` — operation budget exceeded | `lib/cli_budgets.py:475` |
| 10 | _(no symbol)_ | verify --audit | `AuditChainGapError` / `AuditChainDuplicateError` / `AuditChainTamperedError` / `AuditChainRotationSeamError` / `AuditChainTruncationError` — chain integrity failure | `lib/audit_verify_cli.py:57,66,103,126,137` |
| 11 | `EXIT_WINDOWS_CONTAINMENT_DEGRADED` | phase.autopilot.start | `windows_containment_degraded` — chain mode + Windows without network isolation | `lib/exitcodes.py:34` |
| 11 | `EXIT_WINDOWS_CONTAINMENT_DEGRADED` | safe_open (Windows) | ADS / Win32 reserved-char path components | `lib/safe_open.py:267,379,444,510` |
| 12 | `EXIT_PLANNING_DRIFT` | dashboard --check / phase.autopilot.start | `git_repo_required` — chain mode requires a git repository | `lib/exitcodes.py:24` |
| 13 | `EXIT_DEPRECATED_FLAG` | CLI entry point | `deprecated_flag` — `--chain` or `--auto` flag used | `lib/cli_deprecated.py:20` |
| 14 | _(no symbol)_ | verify --audit | `state_empty_crash_artefact` — 0-byte phase-state.json | `lib/audit_verify_cli.py:82` |
| 14 | _(no symbol)_ | phase.autopilot / phase_txn recovery | `audit_partial_write` / `malformed_journal` / `undecidable_state_hash_mismatch_audit` / `corruption` | `lib/phase_txn.py:541,549,578,628,659` |
| 14 | _(no symbol)_ | phase.approve / phase_preflight | state-related corruption artefact | `lib/phase_approve.py:493` |
| 15 | `EXIT_RELEASE_TRUST_INVALID` | install / upgrade | `tag_signature_invalid` / `trust_downgrade_refused` — SSH-signed tag verification failure | `lib/exitcodes.py:39` |
| 15 | `EXIT_RELEASE_TRUST_INVALID` | phase.autopilot.start | `autopilot_already_active` — autopilot run already running | `lib/phase_autopilot.py:865` |
| 16 | _(no symbol)_ | phase.autopilot.start | `chain_start_dirty_tree` — chain mode requires clean working tree | `lib/phase_autopilot.py:830` |
| 17 | `EXIT_HUMAN_CONFIRMATION_REQUIRED` | phase.approve | `non_tty_approval_blocked` — approval requires TTY | `lib/exitcodes.py:43` |
| 17 | `EXIT_HUMAN_CONFIRMATION_REQUIRED` | harness next / status | `requires_human` — autopilot halt, human action required | `lib/status_next.py:321,338` |

---

## Notes

1. **Exit 6 multi-meaning:** `EXIT_WRONG_PHASE_FOR_VERB` and `EXIT_NONCE_SIGNATURE_INVALID` share code 6 per design §12.6.
   `sub_reason` disambiguates: `signature_invalid` is nonce-specific; all others are wrong-phase-for-verb.

2. **Exit 4 dual meaning:** `EXIT_SCOPE_VIOLATION` and `EXIT_PATH_REPARSE_REFUSED` both map to 4 per spec §12.2.

3. **Exit 8 dual meaning:** `EXIT_TIMESTAMP_OUT_OF_RANGE` (timestamp gate) and `approve_during_autopilot`
   (phase.approve conflict) both return 8. `sub_reason` disambiguates.

4. **Exit 12 dual meaning:** `EXIT_PLANNING_DRIFT` (dashboard drift) and `git_repo_required`
   (autopilot chain mode) both return 12.

5. **Exit 15 dual meaning:** `EXIT_RELEASE_TRUST_INVALID` (trust verification) and
   `autopilot_already_active` both return 15. `sub_reason` disambiguates.

6. **Exit 9, 10, 14, 16** have no `exitcodes.py` symbol — they use numeric literals.
   These are stable operational codes (not subject to rename); adding symbols is a
   future-improvement item.

7. **HARNESS_DEBUG=1:** Setting this env var causes uncaught Python exceptions to print
   a full traceback instead of the default single-line summary. This does not affect
   intentional `SystemExit` paths (those are correct by design).

---

## Mismatch audit result

Audit performed 2026-05-21 against v0.9.5 HEAD.

**Total `(exit N)` hint sites found:** 21 (across `scripts/lib/*.py`)
**Mismatches (documented hint ≠ actual returned code):** 0

All `(exit N)` strings in the codebase match the actual exit code returned at that site.
