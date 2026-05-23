# Harness Exit-Code Map

Canonical reference for every documented `(exit N)` hint in the codebase.

**Single source of truth for numeric values:** `scripts/lib/exitcodes.py`

---

## Table

| Code | Symbol | Verb / Sub-reason | Trigger condition | Source file:line |
|------|--------|------------------|-------------------|-----------------|
| 0 | `EXIT_OK` | any | Success | `lib/exitcodes.py:14` |
| 1 | `EXIT_OPERATIONAL` | phase.set / session.unlock / state.show | General operational failure (bad args, file not found, etc.) | `lib/exitcodes.py:15` |
| 2 | `EXIT_INVALID_TRANSITION` | phase.set / phase.approve | Invalid phase transition; stale approval; invalid phase slug (exit 2) | `lib/phase_cli.py:193,198,238` |
| 3 | `EXIT_SESSION_LOCKED` | phase.set / phase.approve | Another process holds the phase lock | `lib/phase_cli.py:213,725` |
| 4 | `EXIT_SCOPE_VIOLATION` | check (scope gate) / worktree | Files outside `allowed_paths` (exit 4) | `lib/worktree.py:40` |
| 4 | `EXIT_PATH_REPARSE_REFUSED` | safe_open (Windows) | Reparse point encountered on Windows path | `lib/exitcodes.py:32` |
| 5 | `EXIT_UNPARSEABLE_JSON` | manifest read / state repair | BOM or JSON parse error (exit 5) | `lib/manifest_v2.py:89` |
| 6 | `EXIT_WRONG_PHASE_FOR_VERB` | phase.approve / phase.reopen | `gitconfig_email_unset` / `non_tty_approval_blocked` / `install_record_missing` | `lib/phase_approve.py:302,319,447` |
| 6 | `EXIT_NONCE_SIGNATURE_INVALID` | phase.approve | `nonce_signature_invalid` — nonce HMAC verification failed | `lib/exitcodes.py:28` |
| 7 | `EXIT_STALE_UNCERTAIN` | session.unlock | Lock pid absent or non-integer; staleness cannot be determined | `lib/phase_cli.py:693,703` |
| 8 | `EXIT_TIMESTAMP_OUT_OF_RANGE` | phase.set / phase.approve | `updated_at` timestamp outside ±60 s window | `lib/phase_cli.py:488,498` |
| 10 | _(no symbol)_ | state-trust preflight / phase.approve | `state_audit_mismatch` — canonical state sha does not match audit tail | `lib/phase_approve.py:469` |
| 11 | `EXIT_WINDOWS_CONTAINMENT_DEGRADED` | safe_open (Windows) | ADS / Win32 reserved-char path components | `lib/safe_open.py:130,150` |
| 12 | `EXIT_PLANNING_DRIFT` | dashboard --check | Blocking warning detected in planning docs | `lib/project_dashboard/core.py:765` |
| 14 | _(no symbol)_ | state-trust preflight / phase.approve / phase_txn recovery | `state_empty_crash_artefact` — 0-byte phase-state.json; corruption | `lib/state_trust.py:102` |
| 17 | `EXIT_HUMAN_CONFIRMATION_REQUIRED` | phase.approve (TTY gate) | `non_tty_approval_blocked` — approval requires TTY (exit 17) | `lib/phase_approve.py:302` |

---

## Notes

1. **Exit 6 multi-meaning:** `EXIT_WRONG_PHASE_FOR_VERB` and `EXIT_NONCE_SIGNATURE_INVALID` share code 6 per design §12.6.
   `sub_reason` disambiguates.

2. **Exit 4 dual meaning:** `EXIT_SCOPE_VIOLATION` and `EXIT_PATH_REPARSE_REFUSED` both map to 4 per spec §12.2.

3. **Exit 10, 14** have no `exitcodes.py` symbol — they use numeric literals.

4. **Codes 0 and 1** are universal (success / generic failure) and have no `(exit N)` hint sites by design.
