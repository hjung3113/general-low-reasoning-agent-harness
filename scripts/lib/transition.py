"""ADR-001 G2-B phase transition state machine.

Owning plan: .planning/phases/02b-hardening/plans/02b-02-T0-1-PLAN.md Block B.
Contract pin: .planning/phases/02b-hardening/CONTRACT-PIN.md §1 (module name
SINGULAR: `transition.py`).

This module exposes:
- ``TRANSITION_TABLE`` — a frozen dict keyed by ``(from_phase, to_phase)``
  describing the legal transitions per ADR-001's state-machine table.
- ``validate_transition(from_phase, to_phase, *, approved, reset_approval)``
  — raises ``SystemExit(2)`` for invalid transitions with a remediation in
  the message string per Artifact 1 verb 1.

T0-1 lands the data table and the validator function. No runtime caller wires
this into a write site at T0-1; T0-3 (``harness phase set``) is the consumer.

Per ADR-001 transition table (see docs/adr/2026-05-16-hardening-bundle.md):
- ``plan->execute`` and ``execute->done`` REQUIRE ``approved=true``.
- Backward / lateral transitions REQUIRE ``--reset-approval``.
- Same-phase loops are rejected (except ``done->done`` re-stamp).
"""

from __future__ import annotations

from typing import Optional


# Each entry: {"requires_approved": bool, "requires_reset_approval": bool}.
# from_phase=None denotes initial bootstrap.
TRANSITION_TABLE: dict[tuple[Optional[str], str], dict[str, bool]] = {
    # Bootstrap.
    (None, "discuss"): {"requires_approved": False, "requires_reset_approval": False},
    # Forward path.
    ("discuss", "plan"): {"requires_approved": False, "requires_reset_approval": False},
    ("plan", "execute"): {"requires_approved": True, "requires_reset_approval": False},
    ("execute", "done"): {"requires_approved": True, "requires_reset_approval": False},
    # Backward / lateral (require --reset-approval).
    ("plan", "discuss"): {"requires_approved": False, "requires_reset_approval": True},
    ("execute", "plan"): {"requires_approved": False, "requires_reset_approval": True},
    ("execute", "discuss"): {"requires_approved": False, "requires_reset_approval": True},
    ("done", "discuss"): {"requires_approved": False, "requires_reset_approval": True},
    ("done", "plan"): {"requires_approved": False, "requires_reset_approval": True},
    ("done", "execute"): {"requires_approved": False, "requires_reset_approval": True},
    # done->done re-stamp (no-op WRT phase value).
    ("done", "done"): {"requires_approved": False, "requires_reset_approval": False},
}


__all__ = ["TRANSITION_TABLE", "InvalidTransition", "validate_transition"]


# Remediation taxonomy per ADR-003a Artifact 1 verb 1 error template.
REMEDIATION_NEEDS_APPROVAL = "needs_approval"
REMEDIATION_NEEDS_RESET = "needs_reset"
REMEDIATION_UNDEFINED = "undefined"

_REMEDIATION_TEXT: dict[str, str] = {
    REMEDIATION_NEEDS_APPROVAL: "Run 'harness phase approve' first.",
    REMEDIATION_NEEDS_RESET: (
        "Pass --reset-approval to clear prior approval and proceed."
    ),
    REMEDIATION_UNDEFINED: (
        "Transition is undefined; choose discuss/plan/execute/done as the next step."
    ),
}


class InvalidTransition(SystemExit):
    """Typed exception raised by ``validate_transition`` for illegal moves.

    Subclasses ``SystemExit`` with ``.code == 2`` so existing call sites that
    treat ``validate_transition`` as a process-exiting validator keep working
    (test_transition.py assertions on ``ctx.exception.code``). Carries the
    structured fields needed by phase_cli to format the ADR-003a Artifact 1
    error template byte-exactly:

        error: cannot set phase={target} from phase={current} (see ADR-001
        transition table). {remediation}
    """

    def __init__(
        self,
        target: str,
        current: Optional[str],
        remediation_kind: str,
    ) -> None:
        super().__init__(2)
        self.target = target
        self.current = current
        self.remediation_kind = remediation_kind
        self.remediation = _REMEDIATION_TEXT[remediation_kind]

    def format_message(self) -> str:
        return (
            f"error: cannot set phase={self.target} from "
            f"phase={self.current} (see ADR-001 transition table). "
            f"{self.remediation}"
        )

    def __str__(self) -> str:  # noqa: D401
        return self.format_message()


def validate_transition(
    from_phase: Optional[str],
    to_phase: str,
    *,
    approved: bool,
    reset_approval: bool,
) -> None:
    """Validate that ``(from_phase, to_phase)`` is permitted.

    Raises ``InvalidTransition`` (a ``SystemExit`` subclass with ``.code == 2``)
    on:
    - undefined pair (no row in ``TRANSITION_TABLE``),
    - approval-required pair invoked with ``approved=False``,
    - backward/lateral pair invoked without ``reset_approval=True``.

    The exception carries ``(target, current, remediation_kind)`` so the
    caller can format the Artifact 1 template.
    """
    key = (from_phase, to_phase)
    row = TRANSITION_TABLE.get(key)
    if row is None:
        raise InvalidTransition(to_phase, from_phase, REMEDIATION_UNDEFINED)
    if row["requires_approved"] and not approved:
        raise InvalidTransition(to_phase, from_phase, REMEDIATION_NEEDS_APPROVAL)
    if row["requires_reset_approval"] and not reset_approval:
        raise InvalidTransition(to_phase, from_phase, REMEDIATION_NEEDS_RESET)
