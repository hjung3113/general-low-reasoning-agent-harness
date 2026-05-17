"""S03-stale-approval — `(plan → execute)` validator extension (§3.6).

Per design §3.6:

  > For `(plan → execute)` under `manual`: require `approved=true`,
  > `approved_at >= plan_finalized_at`, and active `verification` /
  > `allowed_paths` values to be present. Only after these checks
  > pass may the CLI stamp `execute_attempt_started_at`.

Failure mode (line 617): "reject (exit 2)" — same family as ADR-001
transition rejection.

This module extends `scripts/lib/transition.py` with
`validate_transition_with_state(state, target, *, reset_approval)`
which knows about `execution_mode`, `approved_at`, `plan_finalized_at`,
and `execute_attempt_started_at`. The legacy
`validate_transition(from_phase, to_phase, *, approved, reset_approval)`
remains for callers that don't yet have the full state dict (the
existing 228 unittest harness relies on it).

Tests cover the §3.6 matrix:
  - manual mode + approved=false                         → reject (legacy)
  - manual mode + approved=true + no plan_finalized_at   → reject (stale)
  - manual mode + approved_at < plan_finalized_at        → reject (stale)
  - manual mode + approved_at >= plan_finalized_at       → accept
  - manual mode + missing verification/allowed_paths     → reject
  - non-manual mode: short-circuits to autopilot-context check;
    these tests pin the manual-mode contract specifically.
"""

from __future__ import annotations

import pytest

from lib import transition


def _state(
    *,
    phase="plan",
    approved=True,
    approved_at="2026-05-17T12:00:00Z",
    plan_finalized_at="2026-05-17T11:00:00Z",
    execute_attempt_started_at=None,
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
# Legacy regression — must still reject (plan→execute) with approved=False
# ---------------------------------------------------------------------------


def test_legacy_plan_to_execute_unapproved_rejected_exit_2():
    state = _state(approved=False, approved_at=None)
    with pytest.raises(SystemExit) as ctx:
        transition.validate_transition_with_state(
            state, "execute", reset_approval=False
        )
    assert ctx.value.code == 2


# ---------------------------------------------------------------------------
# §3.6 — fresh approval against plan_finalized_at
# ---------------------------------------------------------------------------


def test_approved_at_after_plan_finalized_at_accepted():
    state = _state(
        approved=True,
        approved_at="2026-05-17T12:00:00Z",
        plan_finalized_at="2026-05-17T11:00:00Z",
    )
    transition.validate_transition_with_state(
        state, "execute", reset_approval=False
    )


def test_approved_at_equal_plan_finalized_at_accepted():
    state = _state(
        approved=True,
        approved_at="2026-05-17T12:00:00Z",
        plan_finalized_at="2026-05-17T12:00:00Z",
    )
    transition.validate_transition_with_state(
        state, "execute", reset_approval=False
    )


def test_approved_at_before_plan_finalized_at_rejected():
    state = _state(
        approved=True,
        approved_at="2026-05-17T10:00:00Z",
        plan_finalized_at="2026-05-17T11:00:00Z",
    )
    with pytest.raises(SystemExit) as ctx:
        transition.validate_transition_with_state(
            state, "execute", reset_approval=False
        )
    assert ctx.value.code == 2
    assert isinstance(ctx.value, transition.StaleApprovalError)
    assert ctx.value.sub_reason == "approval_predates_plan_finalized_at"


def test_missing_plan_finalized_at_rejected():
    """§3.6 + §1.1 Round-7 Coherence E-33: plan_finalized_at MUST be
    populated on (discuss|execute) → plan exit. If absent at the
    plan→execute gate, the plan was never properly finalized; reject."""
    state = _state(
        approved=True,
        approved_at="2026-05-17T12:00:00Z",
        plan_finalized_at=None,
    )
    with pytest.raises(SystemExit) as ctx:
        transition.validate_transition_with_state(
            state, "execute", reset_approval=False
        )
    assert ctx.value.code == 2
    assert ctx.value.sub_reason == "plan_finalized_at_missing"


# ---------------------------------------------------------------------------
# §3.6 — verification / allowed_paths must be present
# ---------------------------------------------------------------------------


def test_missing_verification_rejected():
    state = _state(verification=[])
    with pytest.raises(SystemExit) as ctx:
        transition.validate_transition_with_state(
            state, "execute", reset_approval=False
        )
    assert ctx.value.code == 2
    assert ctx.value.sub_reason == "verification_missing"


def test_missing_allowed_paths_rejected():
    state = _state(allowed_paths=[])
    with pytest.raises(SystemExit) as ctx:
        transition.validate_transition_with_state(
            state, "execute", reset_approval=False
        )
    assert ctx.value.code == 2
    assert ctx.value.sub_reason == "allowed_paths_missing"


# ---------------------------------------------------------------------------
# Fix line on the rejection messages (§3.9)
# ---------------------------------------------------------------------------


def test_stale_rejection_message_includes_fix_line():
    state = _state(
        approved=True,
        approved_at="2026-05-17T10:00:00Z",
        plan_finalized_at="2026-05-17T11:00:00Z",
    )
    with pytest.raises(SystemExit) as ctx:
        transition.validate_transition_with_state(
            state, "execute", reset_approval=False
        )
    msg = ctx.value.format_message()
    assert "Fix:" in msg
    assert "harness phase approve" in msg


# ---------------------------------------------------------------------------
# Manual mode: legacy backward-compat retained
# ---------------------------------------------------------------------------


def test_legacy_validate_transition_unchanged():
    """Existing callers that haven't migrated to the state-aware path
    must keep working — the 228 unittest harness depends on it."""
    transition.validate_transition(
        "plan", "execute", approved=True, reset_approval=False
    )
    with pytest.raises(SystemExit) as ctx:
        transition.validate_transition(
            "plan", "execute", approved=False, reset_approval=False
        )
    assert ctx.value.code == 2


# ---------------------------------------------------------------------------
# Non-manual mode: this slice does NOT implement the §3.6 autopilot-
# context rules (they land alongside the autopilot-start verb in S07).
# We pin the current behavior: the state-aware validator MUST defer to
# the manual-mode checks even when execution_mode != manual, because
# the manual-mode gate is the strictly-stronger floor (approved=true
# + fresh + verification+allowed_paths still required).
# ---------------------------------------------------------------------------


def test_non_manual_mode_still_requires_fresh_approval():
    """Even under autopilot, the (plan→execute) gate fails on stale
    approval. The autopilot-context checks (autopilot_run_id etc.) are
    additive — they land in S07; this slice pins the floor."""
    state = _state(
        execution_mode="phase_autopilot",
        approved=True,
        approved_at="2026-05-17T10:00:00Z",
        plan_finalized_at="2026-05-17T11:00:00Z",
    )
    with pytest.raises(SystemExit) as ctx:
        transition.validate_transition_with_state(
            state, "execute", reset_approval=False
        )
    assert ctx.value.code == 2
