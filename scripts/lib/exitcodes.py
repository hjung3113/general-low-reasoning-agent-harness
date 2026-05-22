"""Exit-code constants per ADR-003a Artifact 1 (post-amendment).

Owning plan: .planning/phases/02b-hardening/plans/02b-04-T0-3-PLAN.md
Contract pin: .planning/phases/02b-hardening/CONTRACT-PIN.md §4.

Single source of truth — no other module may define a numeric exit-code
literal. Per CONTRACT-PIN: "Tests assert exitcodes.EXIT_SCOPE_VIOLATION == 4".

Code 4 is defined here; the consumer is T1-1's check.py scope enforcement.
"""

from __future__ import annotations

EXIT_OK = 0
EXIT_OPERATIONAL = 1
EXIT_INVALID_TRANSITION = 2
EXIT_SESSION_LOCKED = 3
EXIT_SCOPE_VIOLATION = 4  # Defined here; consumed by T1-1's check.py scope enforcement.
EXIT_UNPARSEABLE_JSON = 5
EXIT_WRONG_PHASE_FOR_VERB = 6
# Exit 6 multi-meaning per §12.6 — sub_reason disambiguates
EXIT_STALE_UNCERTAIN = 7
EXIT_TIMESTAMP_OUT_OF_RANGE = 8
EXIT_PLANNING_DRIFT = 12  # dashboard --check detected drift between planning docs and live gate
# §12.6 line 1322: nonce HMAC consumers reject invalid/missing signatures with
# exit 6 `nonce_signature_invalid`.  sub_reason distinguishes from
# EXIT_WRONG_PHASE_FOR_VERB.  Budget-exhausted uses 9 operationally
# (phase_txn.BudgetExhausted) — that keeps exit 9.
EXIT_NONCE_SIGNATURE_INVALID = 6
# §12.2: reparse-point refusal uses the same exit code as scope_violation (4)
# per spec §12.2 line 1254.  FenceWindowsUnsupported stays at 11.
EXIT_PATH_REPARSE_REFUSED = 4  # path_reparse_refused — reparse point on Windows path
# §12.2: ADS / Win32 reserved-char components — containment error, not reparse
EXIT_WINDOWS_CONTAINMENT_DEGRADED = 11  # windows_containment_degraded
# §3.4 "human action required" slot — also used by `harness next` autopilot
# halt with sub_reason=requires_human. Phase.approve non-TTY halts use the
# same numeric value with sub_reason=non_tty_approval_blocked.
EXIT_HUMAN_CONFIRMATION_REQUIRED = 17


__all__ = [
    "EXIT_OK",
    "EXIT_OPERATIONAL",
    "EXIT_INVALID_TRANSITION",
    "EXIT_SESSION_LOCKED",
    "EXIT_SCOPE_VIOLATION",
    "EXIT_UNPARSEABLE_JSON",
    "EXIT_WRONG_PHASE_FOR_VERB",
    "EXIT_STALE_UNCERTAIN",
    "EXIT_TIMESTAMP_OUT_OF_RANGE",
    "EXIT_PLANNING_DRIFT",
    "EXIT_NONCE_SIGNATURE_INVALID",
    "EXIT_PATH_REPARSE_REFUSED",
    "EXIT_WINDOWS_CONTAINMENT_DEGRADED",
    "EXIT_HUMAN_CONFIRMATION_REQUIRED",
]
