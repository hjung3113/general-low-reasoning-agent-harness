"""T11 — NEW-4: `harness next` and `harness status` share a single projection.

For any given state dict, ``compute_next_action(state)`` is the canonical
source of truth.  Both ``compute_status(...).next_action`` and
``compute_next(...).command`` MUST equal it byte-for-byte.

Previously ``compute_next`` had its own inline phase/approval logic that
could diverge from ``compute_status`` when state changed between the two
reads (stale-snapshot bug, NEW-4).  After the T11 refactor both functions
call ``compute_next_action`` so the contract is enforced structurally.

Parametrized states cover every combination called out in the plan:
  - discuss / unapproved
  - plan / unapproved
  - plan / fresh-approved  (the NEW-4 lag site: post-approve, next lagged)
  - plan / stale-approved  (approved_at < plan_finalized_at)
  - plan / approved_by set
  - execute / fresh-approved
  - execute / stale (no fresh approval)
  - done
  - autopilot active (execution_mode != "manual")
  - unacknowledged halt with suggested command
  - unacknowledged halt without suggested command (requires diary clear)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import pytest

# Ensure scripts/ is importable when pytest is run from repo root.
_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from lib.status_next import compute_next, compute_next_action, compute_status


# ---------------------------------------------------------------------------
# State factory helpers
# ---------------------------------------------------------------------------

_BASE_TIMESTAMPS = {
    "plan_finalized_at": "2026-05-21T10:00:00Z",
    "execute_attempt_started_at": "2026-05-21T11:00:00Z",
}

_APPROVED_FRESH = "2026-05-21T10:30:00Z"   # between plan_finalized and execute_attempt
_APPROVED_STALE = "2026-05-21T09:00:00Z"   # before plan_finalized_at


def _state(
    *,
    phase: str = "discuss",
    approved: bool = False,
    approved_at: Optional[str] = None,
    approved_by: Optional[str] = None,
    execution_mode: str = "manual",
    last_halt: Optional[dict] = None,
) -> dict:
    """Return a minimal state dict with v2-compatible fields."""
    s: dict = {
        "phase": phase,
        "approved": approved,
        "execution_mode": execution_mode,
    }
    if approved_at is not None:
        s["approved_at"] = approved_at
    if approved_by is not None:
        s["approved_by"] = approved_by
    s.update(_BASE_TIMESTAMPS)
    if last_halt is not None:
        s["last_halt"] = last_halt
    return s


# ---------------------------------------------------------------------------
# Parametrize: (state_id, state_dict)
# ---------------------------------------------------------------------------

PARAMETRIZE_STATES = [
    pytest.param(
        "discuss/unapproved",
        _state(phase="discuss"),
        id="discuss-unapproved",
    ),
    pytest.param(
        "plan/unapproved",
        _state(phase="plan"),
        id="plan-unapproved",
    ),
    pytest.param(
        "plan/unapproved-with-approver",
        _state(phase="plan", approved_by="alice@example.com"),
        id="plan-unapproved-with-approver",
    ),
    pytest.param(
        "plan/stale-approved",
        _state(phase="plan", approved=True, approved_at=_APPROVED_STALE),
        id="plan-stale-approved",
    ),
    pytest.param(
        # NEW-4 lag site: just after `phase approve`, both verbs must agree.
        "plan/fresh-approved",
        _state(phase="plan", approved=True, approved_at=_APPROVED_FRESH),
        id="plan-fresh-approved",
    ),
    pytest.param(
        "execute/fresh-approved",
        _state(
            phase="execute",
            approved=True,
            approved_at="2026-05-21T11:30:00Z",  # after execute_attempt_started_at
        ),
        id="execute-fresh-approved",
    ),
    pytest.param(
        "execute/stale-approval",
        _state(
            phase="execute",
            approved=True,
            approved_at=_APPROVED_STALE,  # before execute_attempt_started_at
        ),
        id="execute-stale-approval",
    ),
    pytest.param(
        "execute/unapproved",
        _state(phase="execute"),
        id="execute-unapproved",
    ),
    pytest.param(
        "done",
        _state(phase="done"),
        id="done",
    ),
    pytest.param(
        "autopilot-active",
        _state(phase="plan", execution_mode="phase_autopilot"),
        id="autopilot-active",
    ),
    pytest.param(
        "halt-with-suggested-command",
        _state(
            phase="execute",
            last_halt={
                "halt_reason": "dependency failed",
                "suggested_next_command": "harness halt-diary ack --run-id abc123",
                "suggested_next_command_requires_human": False,
                "acknowledged_at": None,
            },
        ),
        id="halt-with-suggested-command",
    ),
    pytest.param(
        "halt-without-suggested-command",
        _state(
            phase="execute",
            last_halt={
                "halt_reason": "unknown error",
                "suggested_next_command": None,
                "acknowledged_at": None,
            },
        ),
        id="halt-without-suggested-command",
    ),
    pytest.param(
        "halt-acknowledged",
        _state(
            phase="plan",
            last_halt={
                "halt_reason": "manual stop",
                "suggested_next_command": "harness phase set execute",
                "acknowledged_at": "2026-05-21T12:00:00Z",
            },
        ),
        id="halt-acknowledged",
    ),
]


# ---------------------------------------------------------------------------
# Core parity tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("state_id,state", PARAMETRIZE_STATES)
def test_status_next_action_equals_compute_next_action(
    state_id: str, state: dict, tmp_path: Path
) -> None:
    """compute_status(...).next_action == compute_next_action(state)."""
    audit_path = tmp_path / "audit.log"

    canonical = compute_next_action(state)
    status_result = compute_status(state=state, audit_path=audit_path)

    assert status_result.next_action == canonical, (
        f"[{state_id}] compute_status.next_action={status_result.next_action!r} "
        f"!= compute_next_action={canonical!r}"
    )


@pytest.mark.parametrize("state_id,state", PARAMETRIZE_STATES)
def test_compute_next_command_equals_compute_next_action(
    state_id: str, state: dict, tmp_path: Path
) -> None:
    """compute_next(...).command == compute_next_action(state).

    Exception: when phase=="done" or autopilot active, compute_next returns
    command=None and compute_next_action also returns None — both agree.
    """
    audit_path = tmp_path / "audit.log"

    canonical = compute_next_action(state)
    next_result = compute_next(state=state, audit_path=audit_path)

    assert next_result.command == canonical, (
        f"[{state_id}] compute_next.command={next_result.command!r} "
        f"!= compute_next_action={canonical!r}"
    )


@pytest.mark.parametrize("state_id,state", PARAMETRIZE_STATES)
def test_three_way_parity(state_id: str, state: dict, tmp_path: Path) -> None:
    """All three surfaces agree: compute_next_action == status.next_action == next.command."""
    audit_path = tmp_path / "audit.log"

    canonical = compute_next_action(state)
    status_result = compute_status(state=state, audit_path=audit_path)
    next_result = compute_next(state=state, audit_path=audit_path)

    assert status_result.next_action == canonical, (
        f"[{state_id}] status.next_action mismatch"
    )
    assert next_result.command == canonical, (
        f"[{state_id}] next.command mismatch"
    )


# ---------------------------------------------------------------------------
# Spot-check expected values for key states
# ---------------------------------------------------------------------------


def test_discuss_next_action() -> None:
    """discuss phase → harness phase set plan."""
    state = _state(phase="discuss")
    assert compute_next_action(state) == "harness phase set plan"


def test_plan_unapproved_next_action() -> None:
    """plan / unapproved → harness phase approve."""
    state = _state(phase="plan")
    assert compute_next_action(state) == "harness phase approve"


def test_plan_fresh_approved_next_action() -> None:
    """NEW-4 lag site: plan / fresh approved → harness phase set execute."""
    state = _state(phase="plan", approved=True, approved_at=_APPROVED_FRESH)
    assert compute_next_action(state) == "harness phase set execute"


def test_execute_fresh_approved_next_action() -> None:
    """execute / fresh approved → harness phase set done."""
    state = _state(
        phase="execute",
        approved=True,
        approved_at="2026-05-21T11:30:00Z",
    )
    assert compute_next_action(state) == "harness phase set done"


def test_done_next_action_is_none() -> None:
    """done phase → None (no action)."""
    state = _state(phase="done")
    assert compute_next_action(state) is None


def test_autopilot_next_action_is_none() -> None:
    """Autopilot removed — plan phase unapproved → suggest approve."""
    state = _state(phase="plan", execution_mode="manual")
    assert compute_next_action(state) == "harness phase approve"


def test_format_status_human_next_action_line_matches_next_command(
    tmp_path: Path,
) -> None:
    """Regression: format_status_human's 'Next action:' line shows the canonical command.

    This test reproduces the exact NEW-4 scenario: after plan approval the
    status output 'Next action     : harness phase set execute' must match
    what harness next would output.
    """
    from lib.status_next import format_status_human

    state = _state(phase="plan", approved=True, approved_at=_APPROVED_FRESH)
    audit_path = tmp_path / "audit.log"

    status_result = compute_status(state=state, audit_path=audit_path)
    next_result = compute_next(state=state, audit_path=audit_path)

    # Extract "Next action     : <value>" from human-formatted status
    human_output = format_status_human(status_result)
    next_action_line = next(
        (ln for ln in human_output.splitlines() if ln.startswith("Next action")),
        None,
    )
    assert next_action_line is not None, "format_status_human did not emit a Next action line"

    # The value after the colon+space
    _, _, status_next_value = next_action_line.partition(": ")
    assert status_next_value.strip() == (next_result.command or "").strip(), (
        f"status 'Next action' value {status_next_value!r} != "
        f"next.command {next_result.command!r}"
    )
