"""S03-stale-approval — `(execute → done)` validator extension (§3.6).

Per design §3.6:

  > For `(execute → done)` under `manual`: keep the existing
  > `approved=true` check, but also require
  > `approved_at >= execute_attempt_started_at` so a later
  > `reopen --to plan` invalidates stale approvals for completion.

Failure mode: exit 2 (ADR-001 transition rejection family).
"""

from __future__ import annotations

import pytest

from lib import transition


def _state(
    *,
    phase="execute",
    approved=True,
    approved_at="2026-05-17T13:00:00Z",
    plan_finalized_at="2026-05-17T11:00:00Z",
    execute_attempt_started_at="2026-05-17T12:00:00Z",
    execution_mode="manual",
    verification=None,
    allowed_paths=None,
):
    return {
        "phase": phase,
        "approved": approved,
        "approved_at": approved_at,
        "plan_finalized_at": plan_finalized_at,
        "execute_attempt_started_at": execute_attempt_started_at,
        "execution_mode": execution_mode,
        "verification": verification if verification is not None else ["pytest -q"],
        "allowed_paths": allowed_paths if allowed_paths is not None else ["src/"],
    }


# ---------------------------------------------------------------------------
# Legacy regression
# ---------------------------------------------------------------------------


def test_legacy_execute_to_done_unapproved_rejected_exit_2():
    state = _state(approved=False, approved_at=None)
    with pytest.raises(SystemExit) as ctx:
        transition.validate_transition_with_state(
            state, "done", reset_approval=False
        )
    assert ctx.value.code == 2


# ---------------------------------------------------------------------------
# §3.6 — approved_at >= execute_attempt_started_at
# ---------------------------------------------------------------------------


def test_approval_post_execute_start_accepted():
    state = _state(
        approved_at="2026-05-17T13:00:00Z",
        execute_attempt_started_at="2026-05-17T12:00:00Z",
    )
    transition.validate_transition_with_state(
        state, "done", reset_approval=False
    )


def test_approval_equals_execute_start_accepted():
    state = _state(
        approved_at="2026-05-17T12:00:00Z",
        execute_attempt_started_at="2026-05-17T12:00:00Z",
    )
    transition.validate_transition_with_state(
        state, "done", reset_approval=False
    )


def test_approval_pre_execute_start_rejected():
    state = _state(
        approved_at="2026-05-17T11:30:00Z",
        execute_attempt_started_at="2026-05-17T12:00:00Z",
    )
    with pytest.raises(SystemExit) as ctx:
        transition.validate_transition_with_state(
            state, "done", reset_approval=False
        )
    assert ctx.value.code == 2
    assert isinstance(ctx.value, transition.StaleApprovalError)
    assert ctx.value.sub_reason == "approval_predates_execute_attempt"


def test_missing_execute_attempt_started_at_rejected():
    """§3.6 invariant: `execute_attempt_started_at` is stamped ONLY
    after a successful, approval-validated plan→execute transition.
    If absent at the execute→done gate, that invariant was violated;
    reject with a descriptive Fix: line per §3.9."""
    state = _state(execute_attempt_started_at=None)
    with pytest.raises(SystemExit) as ctx:
        transition.validate_transition_with_state(
            state, "done", reset_approval=False
        )
    assert ctx.value.code == 2
    assert ctx.value.sub_reason == "execute_attempt_started_at_missing"
    assert "Fix:" in ctx.value.format_message()


# ---------------------------------------------------------------------------
# Approved=false path remains the primary gate
# ---------------------------------------------------------------------------


def test_unapproved_rejection_kept():
    state = _state(approved=False, approved_at=None)
    with pytest.raises(SystemExit) as ctx:
        transition.validate_transition_with_state(
            state, "done", reset_approval=False
        )
    assert ctx.value.code == 2


# ---------------------------------------------------------------------------
# Non-manual mode: legacy floor preserved (S07 lands autopilot context)
# ---------------------------------------------------------------------------


def test_non_manual_execute_to_done_still_stale_blocked():
    state = _state(
        execution_mode="phase_autopilot",
        approved_at="2026-05-17T11:30:00Z",
        execute_attempt_started_at="2026-05-17T12:00:00Z",
    )
    with pytest.raises(SystemExit) as ctx:
        transition.validate_transition_with_state(
            state, "done", reset_approval=False
        )
    assert ctx.value.code == 2


# ---------------------------------------------------------------------------
# Legacy validator backward-compat
# ---------------------------------------------------------------------------


def test_legacy_validator_unchanged_for_execute_to_done():
    transition.validate_transition(
        "execute", "done", approved=True, reset_approval=False
    )
    with pytest.raises(SystemExit) as ctx:
        transition.validate_transition(
            "execute", "done", approved=False, reset_approval=False
        )
    assert ctx.value.code == 2
