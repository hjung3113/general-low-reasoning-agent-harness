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

from datetime import datetime
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


__all__ = [
    "TRANSITION_TABLE",
    "InvalidTransition",
    "StaleApprovalError",
    "validate_transition",
    "validate_transition_with_state",
]


# Remediation taxonomy per ADR-003a Artifact 1 verb 1 error template.
REMEDIATION_NEEDS_APPROVAL = "needs_approval"
REMEDIATION_NEEDS_RESET = "needs_reset"
REMEDIATION_UNDEFINED = "undefined"

_REMEDIATION_TEXT: dict[str, str] = {
    REMEDIATION_NEEDS_APPROVAL: (
        "Fix: run 'harness phase approve' first, then retry 'harness phase set <target>'."
    ),
    REMEDIATION_NEEDS_RESET: (
        "Fix: pass --reset-approval to clear prior approval and proceed, "
        "e.g. 'harness phase set <target> --reset-approval'."
    ),
    REMEDIATION_UNDEFINED: (
        "Fix: run 'harness phase set discuss|plan|execute|done' "
        "(see ADR-001 transition table for valid moves)."
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


# ---------------------------------------------------------------------------
# S03 — design §3.6 ADR-001 transition validator extension
# ---------------------------------------------------------------------------


class StaleApprovalError(SystemExit):
    """§3.6 fault class — approval is stale relative to the phase
    timeline, or required §3.6 fields are missing.

    Subclasses `SystemExit` with `.code == 2` so it slots into the same
    ADR-001 transition-rejection exit family. Carries a `sub_reason`
    bucket for smoke / forensic taxonomy:

      * approval_predates_plan_finalized_at
      * approval_predates_execute_attempt
      * plan_finalized_at_missing
      * execute_attempt_started_at_missing
      * verification_missing
      * allowed_paths_missing

    `format_message()` returns the user-visible string with a `Fix:`
    remediation line per §3.9.
    """

    _FIX_BY_SUB = {
        "approval_predates_plan_finalized_at": (
            "Fix: run 'harness phase approve' after the latest plan "
            "edit (approval must post-date plan_finalized_at)"
        ),
        "approval_predates_execute_attempt": (
            "Fix: run 'harness phase approve' to re-approve before "
            "marking done (approval_at must post-date "
            "execute_attempt_started_at)"
        ),
        "plan_finalized_at_missing": (
            "Fix: re-enter plan via 'harness phase set plan' so "
            "plan_finalized_at gets stamped on exit"
        ),
        "execute_attempt_started_at_missing": (
            "Fix: re-enter execute via 'harness phase set execute' "
            "(this stamps execute_attempt_started_at) after a fresh "
            "'harness phase approve'"
        ),
        "verification_missing": (
            "Fix: populate state.verification (non-empty list of "
            "verification commands) before entering execute"
        ),
        "allowed_paths_missing": (
            "Fix: populate state.allowed_paths (non-empty list of "
            "path globs) before entering execute"
        ),
        "last_halt_unacknowledged": (
            "Fix: run 'harness halt-diary clear' to acknowledge and clear the "
            "halt diary, or 'harness phase reopen --to plan --reason \"...\"' "
            "to rewind the phase (design §12.12)"
        ),
    }

    def __init__(
        self,
        target: str,
        current: Optional[str],
        sub_reason: str,
        *,
        detail: str = "",
    ) -> None:
        super().__init__(2)
        self.target = target
        self.current = current
        self.sub_reason = sub_reason
        self.detail = detail
        self.fix = self._FIX_BY_SUB.get(
            sub_reason,
            "Fix: see design §3.6 / ADR-001 transition table",
        )

    def format_message(self) -> str:
        base = (
            f"error: cannot set phase={self.target} from "
            f"phase={self.current} (see ADR-001 §3.6 stale-approval "
            f"check): {self.sub_reason}"
        )
        if self.detail:
            base = f"{base} ({self.detail})"
        return f"{base}. {self.fix}"

    def __str__(self) -> str:  # noqa: D401
        return self.format_message()


def _iso_lt(a: Optional[str], b: Optional[str]) -> bool:
    """Return True iff `a < b` chronologically.

    Review-fix P2-2: prior implementation compared the raw strings
    lexicographically. That ASSUMED uniform precision — but our
    producers mix seconds-precision and fractional-precision ISO-Z
    timestamps. Counter-example: `"2026-05-17T12:00:00.999Z"`
    lexically sorts AFTER `"2026-05-17T12:00:01Z"` because `.` (0x2E)
    sorts before `Z` (0x5A), but the `9`s after the `.` flip the order
    in the lex string compared to the chronological order — concretely,
    `'2026-05-17T12:00:00.999Z' > '2026-05-17T12:00:01Z'` is False
    lexically yet chronologically the fractional one is EARLIER, which
    happens to round-trip correctly here, but `2026-05-17T12:00:01.000Z`
    vs `2026-05-17T12:00:01Z` DOES misorder lexically. To eliminate the
    foot-gun entirely we parse both sides via `datetime.fromisoformat`
    and compare as `datetime`.

    Inputs MUST be UTC-`Z` strings; we reject anything else with a
    `ValueError` so future producer drift (e.g. an unstamped `+00:00`)
    surfaces immediately rather than silently mis-comparing.

    Returns False if either side is None — callers handle missing-field
    cases explicitly before calling this.
    """
    if a is None or b is None:
        return False
    return _parse_iso_z(a) < _parse_iso_z(b)


def _parse_iso_z(s: str) -> datetime:
    """Parse a canonical UTC-Z ISO-8601 string. Raises ValueError on
    anything that does not end in `Z` so producer drift fails loudly.

    Python 3.9 ``datetime.fromisoformat`` accepts at most 6 fractional
    decimal digits (microsecond precision). Our internal timestamp
    producer ``timestamps.now_iso_nanos`` emits 9-digit nanosecond
    strings. We truncate any fractional-second component to 6 digits
    before parsing so both producers are accepted. The truncation is
    correct for chronological comparison because the nanosecond bits
    never change the microsecond-level ordering of the two timestamps
    being compared (the comparison precision is coarser).
    """
    if not isinstance(s, str) or not s.endswith("Z"):
        raise ValueError(
            f"timestamp {s!r} is not a canonical UTC-Z ISO-8601 string "
            f"(must end with 'Z'); see design §1.1 timestamps producer "
            f"contract"
        )
    # Truncate fractional seconds to at most 6 digits for Python 3.9
    # compatibility (fromisoformat on 3.9 rejects 9-digit nanos).
    body = s[:-1]  # strip trailing Z
    if "." in body:
        integer_part, frac = body.split(".", 1)
        body = integer_part + "." + frac[:6]
    return datetime.fromisoformat(body + "+00:00")


def validate_transition_with_state(
    state: dict,
    to_phase: str,
    *,
    reset_approval: bool,
) -> None:
    """Extended §3.6 validator. Same exit code (2) and same `Fix:`
    contract as `validate_transition`, but takes the full state dict
    so it can check stale-approval invariants:

      - (plan → execute): approved=True AND approved_at >=
        plan_finalized_at AND verification non-empty AND allowed_paths
        non-empty.
      - (execute → done): approved=True AND approved_at >=
        execute_attempt_started_at.

    Backward / lateral transitions still flow through the legacy table.
    Non-manual modes get the same floor here; the autopilot-context
    checks (§3.6 first bullet) land in S07 and layer on top.
    """
    from_phase = state.get("phase")
    approved = bool(state.get("approved"))

    # First run the legacy table — catches undefined pairs and the
    # `approved=False` reject for forward transitions. The legacy
    # checks are a strict subset of §3.6's requirements.
    validate_transition(
        from_phase, to_phase, approved=approved, reset_approval=reset_approval
    )

    # §3.6 extensions for the two forward edges that gate code work.
    if (from_phase, to_phase) == ("plan", "execute"):
        verification = state.get("verification") or []
        allowed_paths = state.get("allowed_paths") or []
        if not verification:
            raise StaleApprovalError(to_phase, from_phase, "verification_missing")
        if not allowed_paths:
            raise StaleApprovalError(to_phase, from_phase, "allowed_paths_missing")
        plan_finalized_at = state.get("plan_finalized_at")
        if plan_finalized_at is None:
            raise StaleApprovalError(
                to_phase, from_phase, "plan_finalized_at_missing"
            )
        approved_at = state.get("approved_at")
        if approved_at is None or _iso_lt(approved_at, plan_finalized_at):
            raise StaleApprovalError(
                to_phase,
                from_phase,
                "approval_predates_plan_finalized_at",
                detail=f"approved_at={approved_at!r} < plan_finalized_at={plan_finalized_at!r}",
            )
        return

    if (from_phase, to_phase) == ("execute", "done"):
        execute_attempt_started_at = state.get("execute_attempt_started_at")
        if execute_attempt_started_at is None:
            raise StaleApprovalError(
                to_phase, from_phase, "execute_attempt_started_at_missing"
            )
        approved_at = state.get("approved_at")
        if approved_at is None or _iso_lt(approved_at, execute_attempt_started_at):
            raise StaleApprovalError(
                to_phase,
                from_phase,
                "approval_predates_execute_attempt",
                detail=(
                    f"approved_at={approved_at!r} < "
                    f"execute_attempt_started_at={execute_attempt_started_at!r}"
                ),
            )
        # §12.12: refuse if last_halt is non-null with acknowledged_at=None.
        last_halt = state.get("last_halt")
        if last_halt is not None and last_halt.get("acknowledged_at") is None:
            raise StaleApprovalError(
                to_phase,
                from_phase,
                "last_halt_unacknowledged",
                detail=(
                    "last_halt diary is present but has not been acknowledged. "
                    "Fix: run 'harness halt-diary clear' to acknowledge and clear, "
                    "or 'harness phase reopen --to plan --reason \"...\"' to rewind."
                ),
            )
        return


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
