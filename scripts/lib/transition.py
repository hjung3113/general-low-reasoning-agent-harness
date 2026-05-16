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


__all__ = ["TRANSITION_TABLE", "validate_transition"]


class _CodedSystemExit(SystemExit):
    """SystemExit subclass carrying both an int exit code and a message.

    ``SystemExit(int)`` sets ``.code`` to the int but prints nothing. We need
    both ``ctx.exception.code == 2`` (for tests/CLI semantics per CONTRACT-PIN
    §4) and a human-readable ``str(exc)``. Subclassing lets us pin both.
    """

    def __init__(self, code: int, message: str) -> None:
        super().__init__(code)
        self._message = message

    def __str__(self) -> str:  # noqa: D401
        return self._message


def _exit2(message: str) -> None:
    raise _CodedSystemExit(2, message)


def validate_transition(
    from_phase: Optional[str],
    to_phase: str,
    *,
    approved: bool,
    reset_approval: bool,
) -> None:
    """Validate that ``(from_phase, to_phase)`` is permitted.

    Raises ``_CodedSystemExit`` (a ``SystemExit`` subclass with ``.code == 2``)
    on:
    - undefined pair (no row in ``TRANSITION_TABLE``),
    - approval-required pair invoked with ``approved=False``,
    - backward/lateral pair invoked without ``reset_approval=True``.
    """
    key = (from_phase, to_phase)
    row = TRANSITION_TABLE.get(key)
    if row is None:
        _exit2(
            f"invalid phase transition {from_phase!r} -> {to_phase!r}: not "
            f"listed in ADR-001 transition table. See "
            f"docs/adr/2026-05-16-hardening-bundle.md ADR-001."
        )
        return  # unreachable; satisfies type checker
    if row["requires_approved"] and not approved:
        _exit2(
            f"phase transition {from_phase!r} -> {to_phase!r} requires "
            f"approved=true. Run: harness phase approve"
        )
        return
    if row["requires_reset_approval"] and not reset_approval:
        _exit2(
            f"phase transition {from_phase!r} -> {to_phase!r} requires "
            f"--reset-approval (backward/lateral move clears prior approval). "
            f"Re-run with --reset-approval."
        )
        return
