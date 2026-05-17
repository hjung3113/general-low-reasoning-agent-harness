"""`cli_budgets` — budget decrement helpers, exhaustion check, and halt-diary
builder per design §1.1 (line 66), §3.5, and §5.3.

Budget shape (§1.1 line 66):
    state.cli_budgets_remaining = {
        "shell_invocations": N,   # hard-stop for harness-mediated subprocesses
        "file_mutation_ops": N,   # hard-stop for phase set / phase autopilot *
        "wall_seconds": N,        # elapsed-time budget (checked, not decremented)
    }

Design decisions on under-specified points:
  • stamp_autopilot_started_at implements REPLACE (not idempotent): each new
    autopilot start resets the wall-clock anchor.  The caller (phase autopilot
    start, wired in step 2) is responsible for invoking once per start.  Clearance
    happens on stop/halt (clear_autopilot_started_at).
  • budget_check for wall_seconds with no autopilot_started_at_iso anchor
    returns exhausted=False (skip-check semantics: no anchor → no measurement).
  • decrement clamps at 0 (non-negative invariant); budget_check uses ≤ 0.
  • Exit code for budget exhaustion: exit 9 with sub_reason "budget_exhausted"
    (closest existing fault family per §3.4; documented here; wiring deferred
    to step 2 when commit_transaction / CLI entry-point integration lands).

Out of scope (DEFER step 2):
  • Wiring into commit_transaction (file_mutation_ops decrement)
  • Wiring into phase_autopilot.run_start (stamp autopilot_started_at_iso)
  • Wiring into phase_autopilot.run_stop (clear autopilot_started_at_iso)
  • Subprocess wrapper for shell_invocations decrement
  • CLI entry-point wall-clock check
  • phase_state.py schema field formalization for autopilot_started_at_iso

Spec: docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Optional

# Import _rotate_last_halt_history from phase_reopen (import, not copy,
# to avoid a refactor; TODO: consolidate to a shared utilities module).
from .phase_reopen import _rotate_last_halt_history

# Import now_iso_z from phase_preflight for ISO timestamp generation.
from .phase_preflight import now_iso_z as _now_iso_z


# ---------------------------------------------------------------------------
# Public constants / types
# ---------------------------------------------------------------------------

CAPABILITIES = ("shell_invocations", "file_mutation_ops", "wall_seconds")
Capability = Literal["shell_invocations", "file_mutation_ops", "wall_seconds"]


@dataclass
class BudgetCheckResult:
    """Returned by budget_check. exhausted=True means caller MUST halt."""

    exhausted: bool
    capability: Optional[Capability]  # which capability exhausted, if any
    remaining: int                    # remaining count for that capability (0 if exhausted)
    message: str                      # human-readable reason


@dataclass
class BudgetDiaryEntry:
    """Halt-diary entry per §5.3 for budget-exhaustion halt.

    Note: NO 'verb' field (S04 review-fix lesson — last_halt must not contain
    a verb; that belongs only in audit rows).
    """

    at: str                                # ISO-Z when halt was decided
    reason: str                            # "budget_exhausted:<capability>"
    capability: Capability
    remaining_at_halt: int
    autopilot_run_id: Optional[str]
    autopilot_phase_slug: Optional[str]
    suggested_next_command: str            # "harness phase autopilot stop --reason 'budget exhausted'"
    suggested_next_command_requires_human: bool   # False (non-TTY command)
    acknowledged_at: Optional[str]         # null on creation


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_iso_z(ts: str) -> datetime:
    """Parse an ISO-Z timestamp into an aware datetime (UTC)."""
    # Handle both "+00:00" suffix and "Z" suffix
    if ts.endswith("Z"):
        ts_normalized = ts[:-1] + "+00:00"
    else:
        ts_normalized = ts
    return datetime.fromisoformat(ts_normalized)


def _now_utc(now_iso: Optional[str]) -> datetime:
    """Return current UTC datetime, from now_iso if given else datetime.now."""
    if now_iso is not None:
        return _parse_iso_z(now_iso)
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# budget_check
# ---------------------------------------------------------------------------


def budget_check(
    state: dict,
    *,
    capability: Capability,
    now_iso: Optional[str] = None,
) -> BudgetCheckResult:
    """Inspect state.cli_budgets_remaining for the given capability.

    Returns BudgetCheckResult(exhausted=True, ...) if the counter has reached
    0 (or below). For wall_seconds, compares elapsed since
    state.autopilot_started_at_iso against state.cli_budgets_remaining.wall_seconds.

    If state.cli_budgets_remaining is None: returns exhausted=False (no budgets
    set ⇒ no check).
    If state.execution_mode == "manual": returns exhausted=False (no autopilot
    ⇒ no enforcement).
    """
    # No enforcement in manual mode
    if state.get("execution_mode") == "manual":
        return BudgetCheckResult(
            exhausted=False,
            capability=None,
            remaining=0,
            message="manual mode: budget checks not enforced",
        )

    budgets = state.get("cli_budgets_remaining")
    if budgets is None:
        return BudgetCheckResult(
            exhausted=False,
            capability=None,
            remaining=0,
            message="no budgets configured",
        )

    if capability == "wall_seconds":
        return _check_wall_seconds(state, budgets, now_iso=now_iso)

    # count-based capabilities: shell_invocations, file_mutation_ops
    remaining = budgets.get(capability)
    if remaining is None:
        # Capability not in budget dict → no check
        return BudgetCheckResult(
            exhausted=False,
            capability=None,
            remaining=0,
            message=f"{capability} not in budget dict",
        )

    if remaining <= 0:
        return BudgetCheckResult(
            exhausted=True,
            capability=capability,
            remaining=0,
            message=f"{capability} budget exhausted (remaining={remaining})",
        )

    return BudgetCheckResult(
        exhausted=False,
        capability=None,
        remaining=remaining,
        message=f"{capability} budget OK: {remaining} remaining",
    )


def _check_wall_seconds(
    state: dict,
    budgets: dict,
    *,
    now_iso: Optional[str],
) -> BudgetCheckResult:
    """Internal: check wall_seconds budget via elapsed-time comparison."""
    wall_budget = budgets.get("wall_seconds")
    if wall_budget is None:
        return BudgetCheckResult(
            exhausted=False,
            capability=None,
            remaining=0,
            message="wall_seconds not in budget dict",
        )

    started_at_iso = state.get("autopilot_started_at_iso")
    if not started_at_iso:
        # No anchor → cannot compute elapsed → skip check
        return BudgetCheckResult(
            exhausted=False,
            capability=None,
            remaining=0,
            message="wall_seconds: no autopilot_started_at_iso anchor — skipping check",
        )

    now_dt = _now_utc(now_iso)
    started_dt = _parse_iso_z(started_at_iso)
    # P2-3 fix: clamp elapsed to ≥0 to defend against backward clock skew.
    # Without the clamp, a future anchor (e.g. NTP correction) would yield
    # negative elapsed, making remaining > budget and extending the budget
    # beyond what the user configured. We halt conservatively: when clock
    # goes backward the measurement is uncertain so we treat it as 0 elapsed
    # (remaining = full budget) rather than extending. Spec deviation note:
    # §1.1 specifies wall-clock via ISO anchor (not POSIX monotonic); this
    # clamp is the correct conservative behaviour for a non-monotonic clock.
    elapsed_seconds = max(0.0, (now_dt - started_dt).total_seconds())
    remaining_seconds = int(wall_budget - elapsed_seconds)

    if elapsed_seconds >= wall_budget:
        return BudgetCheckResult(
            exhausted=True,
            capability="wall_seconds",
            remaining=0,
            message=(
                f"wall_seconds budget exhausted: {elapsed_seconds:.0f}s elapsed, "
                f"budget={wall_budget}s"
            ),
        )

    return BudgetCheckResult(
        exhausted=False,
        capability=None,
        remaining=max(0, remaining_seconds),
        message=(
            f"wall_seconds budget OK: {remaining_seconds}s remaining "
            f"(elapsed={elapsed_seconds:.0f}s, budget={wall_budget}s)"
        ),
    )


# ---------------------------------------------------------------------------
# decrement
# ---------------------------------------------------------------------------


def decrement(
    state: dict,
    *,
    capability: Capability,
    by: int = 1,
    now_iso: Optional[str] = None,  # accepted but unused (future: for logging)
) -> dict:
    """Pure: returns new state dict with the capability counter decremented by `by`.

    For wall_seconds, this is a no-op (wall_seconds is checked via elapsed-time,
    not decremented).
    No-op when cli_budgets_remaining is None or capability not in the dict.
    Caller is responsible for persisting via commit_transaction.
    """
    budgets = state.get("cli_budgets_remaining")
    if budgets is None:
        return state  # no mutation needed

    if capability == "wall_seconds":
        return state  # wall_seconds is checked, not decremented

    if capability not in budgets:
        return state  # capability not tracked → no-op

    new_state = copy.deepcopy(state)
    current = new_state["cli_budgets_remaining"][capability]
    new_state["cli_budgets_remaining"][capability] = max(0, current - by)
    return new_state


# ---------------------------------------------------------------------------
# stamp_autopilot_started_at / clear_autopilot_started_at
# ---------------------------------------------------------------------------


def stamp_autopilot_started_at(state: dict, *, now_iso: str) -> dict:
    """Pure: returns new state with state.autopilot_started_at_iso = now_iso.

    Design choice: REPLACE on every start (not idempotent).  Each autopilot
    start resets the wall-clock anchor so wall_seconds is always measured from
    the most recent run_start.  The caller (phase autopilot start) invokes this
    once; run_stop/halt invokes clear_autopilot_started_at.
    """
    new_state = copy.deepcopy(state)
    new_state["autopilot_started_at_iso"] = now_iso
    return new_state


def clear_autopilot_started_at(state: dict) -> dict:
    """Pure: returns new state with autopilot_started_at_iso = None.

    Called on phase.autopilot.stop or any halt.
    """
    new_state = copy.deepcopy(state)
    new_state["autopilot_started_at_iso"] = None
    return new_state


# ---------------------------------------------------------------------------
# build_budget_halt_diary
# ---------------------------------------------------------------------------


def build_budget_halt_diary(
    *,
    result: BudgetCheckResult,
    state: dict,
    now_iso: str,
) -> BudgetDiaryEntry:
    """Construct the §5.3 last_halt entry for budget-exhaustion halt.

    Note: does NOT include a 'verb' key (S04 review-fix lesson: verb belongs
    only in audit rows, not in last_halt diary).
    """
    capability = result.capability  # the exhausted capability
    # P2-6 fix: capability must not be None for a budget-exhausted diary entry.
    assert capability is not None, (
        "build_budget_halt_diary requires result.capability to be set "
        "(must be called with an exhausted BudgetCheckResult)"
    )
    return BudgetDiaryEntry(
        at=now_iso,
        reason=f"budget_exhausted:{capability}",
        capability=capability,
        remaining_at_halt=result.remaining,
        autopilot_run_id=state.get("autopilot_run_id"),
        autopilot_phase_slug=state.get("autopilot_phase_slug"),
        suggested_next_command="harness phase autopilot stop --reason 'budget exhausted'",
        suggested_next_command_requires_human=False,
        acknowledged_at=None,
    )


# ---------------------------------------------------------------------------
# apply_budget_halt
# ---------------------------------------------------------------------------


def apply_budget_halt(state: dict, *, diary: BudgetDiaryEntry) -> dict:
    """Pure: returns new state with budget-exhaustion halt applied.

    Mutations (per §5.3 + §1.1 + S04 review-fix):
      - execution_mode = "manual"
      - autopilot_run_id / autopilot_mode / autopilot_phase_slug /
        autopilot_start_entry_hash / autopilot_allow_network /
        autopilot_started_at_iso = None (all cleared)
      - cli_budgets_remaining = None (cleared)
      - last_halt = diary.__dict__ (no 'verb' key per S04 review-fix;
        suggested_next_command_requires_human included per §5.3)
      - last_halt_history rotated (cap=5; uses _rotate_last_halt_history
        imported from phase_reopen — TODO: consolidate to shared utilities)
    """
    new_state = copy.deepcopy(state)

    # Rotate prior last_halt to history (cap-5).
    # Stamp acknowledged_at on the rotated entry if not already set — the new
    # budget-halt event IS the implicit acknowledgement of the prior halt
    # (consistent with run_start ack semantics per §1.1 line 67: "the new run
    # IS the implicit acknowledgement"). Without this stamp, cli_budgets and
    # run_start diverge in ack semantics, causing cross-batch halt-diary drift.
    prior_last_halt = new_state.get("last_halt")
    if prior_last_halt is not None and prior_last_halt.get("acknowledged_at") is None:
        _ack_now = _now_iso_z()
        prior_last_halt = dict(prior_last_halt)
        prior_last_halt["acknowledged_at"] = _ack_now
    new_state["last_halt_history"] = _rotate_last_halt_history(
        state, prior_last_halt, cap=5
    )

    # Set execution mode to manual
    new_state["execution_mode"] = "manual"

    # Clear all autopilot identity fields
    new_state["autopilot_run_id"] = None
    new_state["autopilot_mode"] = None
    new_state["autopilot_phase_slug"] = None
    new_state["autopilot_start_entry_hash"] = None
    new_state["autopilot_allow_network"] = None
    new_state["autopilot_started_at_iso"] = None

    # Clear budgets
    new_state["cli_budgets_remaining"] = None

    # Populate last_halt with diary (as dict, no 'verb' key per S04 lesson)
    new_state["last_halt"] = diary.__dict__

    return new_state


# ---------------------------------------------------------------------------
# wall_seconds_check_and_maybe_halt — shared budget guard (P1-2 fix)
# ---------------------------------------------------------------------------


def wall_seconds_check_and_maybe_halt(
    *,
    before_state: dict,
    scratch_root,
    audit_path,
    lock_handle,
    now_iso: "Optional[str]" = None,
) -> "Optional[int]":
    """If autopilot active and wall_seconds budget exhausted, apply halt +
    commit the halted state and return exit code 9. Otherwise return None.

    Relocated from phase_autopilot_cli._wall_seconds_check_and_maybe_halt
    (P1-2 fix) so phase_cli.py and phase_autopilot_cli.py can both import
    without circularity.

    Position contract: call AFTER state-trust preflight (state is trusted),
    BEFORE any state-mutating logic. Caller MUST hold the lock.
    """
    import sys
    from pathlib import Path

    # Lazy import to avoid circular at module load time.
    from . import phase_txn as _phase_txn
    from . import phase_preflight as _phase_preflight

    exec_mode = before_state.get("execution_mode", "manual")
    if exec_mode == "manual":
        return None

    _now = now_iso or _phase_preflight.now_iso_z()
    check = budget_check(before_state, capability="wall_seconds", now_iso=_now)
    if not check.exhausted:
        return None

    # Budget exhausted: build diary, apply halt, commit.
    diary = build_budget_halt_diary(result=check, state=before_state, now_iso=_now)
    halted_state = apply_budget_halt(before_state, diary=diary)

    scratch = Path(scratch_root)
    audit_path_p = Path(audit_path)

    # P2-2 fix: emit structured stderr so operators can disambiguate exit 9.
    cap = diary.capability
    print(
        f"ERROR: budget exhausted (capability={cap}, remaining={diary.remaining_at_halt}). "
        f"Exit 9 sub_reason=budget_exhausted:{cap}.\n"
        "Fix: inspect 'harness phase status' for last_halt diary; "
        "then 'harness phase autopilot stop --reason \"<text>\"' to return to manual.",
        file=sys.stderr,
    )

    try:
        _phase_txn.commit_transaction(
            scratch,
            lock=lock_handle,
            request=_phase_txn.TxnRequest(
                action="phase.autopilot.halt.budget",
                before_state=before_state,
                after_state=halted_state,
                audit_entry_draft={
                    "verb": "phase.autopilot.halt",
                    "args": {
                        "reason": diary.reason,
                        "capability": diary.capability,
                        "remaining_at_halt": diary.remaining_at_halt,
                        "halted_at": _now,
                    },
                },
            ),
            audit_path=audit_path_p,
        )
    except (FileNotFoundError, PermissionError):
        pass  # repo state absent — caller's exit-9 message is still meaningful
    except Exception as e:
        print(f"WARNING: budget-halt commit failed: {e}", file=sys.stderr)
        raise  # re-raise so caller sees the real fault, not a silent 9

    return 9


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

__all__ = [
    "CAPABILITIES",
    "Capability",
    "BudgetCheckResult",
    "BudgetDiaryEntry",
    "budget_check",
    "decrement",
    "stamp_autopilot_started_at",
    "clear_autopilot_started_at",
    "build_budget_halt_diary",
    "apply_budget_halt",
    "wall_seconds_check_and_maybe_halt",
]
