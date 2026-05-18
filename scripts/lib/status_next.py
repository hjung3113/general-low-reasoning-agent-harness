"""Read-only status + next-action computation (design §3.9 + §1.1 line 624).

Exports two pure computation functions (`compute_status`, `compute_next`)
and four formatters (`format_status_human`, `format_status_json`,
`format_next_human`, `format_next_shell`, `format_next_json`).

Contract
--------
- NO lock acquired (read-only per §3.9 "no lock contention").
  State-trust preflight uses the brief lock-acquire-and-release option (a)
  from §3.9 line 554, executed by the CLI handler in status_next_cli.py.
- NO audit row written (§3.9 "auditless").
- Pure functions: state dict + audit_path in → result dataclass out.

Exit codes (§3.4)
-----------------
  0  — agent_safe: a concrete, machine-executable command is recommended.
  17 — human_action_required: next step requires a human in a TTY.
  18 — no_action_during_autopilot: autopilot active; no manual action expected.

Booleans (§1.1 line 624)
-------------------------
  projected_execute_gate_valid
      phase == "execute" AND approved == true
      AND approved_at >= execute_attempt_started_at
  can_enter_execute
      phase == "plan" AND approved == true
      AND approved_at >= plan_finalized_at

Spec: docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md
§3.9, §1.1, §3.4
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from lib.transition import REOPEN_REASON_PLACEHOLDER


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class StatusResult:
    phase: str                          # e.g. "execute"
    phase_entered_at_iso: Optional[str] # from state field depending on phase
    approved: bool
    approved_by: Optional[str]
    approved_at_iso: Optional[str]
    approved_source: Optional[str]      # "gitconfig_auto" / "override_identity" / "ci_..."
    execution_mode: str                 # "manual" / "phase_autopilot" / "chain_autopilot"
    autopilot_run_id: Optional[str]
    autopilot_phase_slug: Optional[str]
    last_halt: Optional[dict]           # raw diary or None
    last_halt_age_seconds: Optional[int]
    projected_execute_gate_valid: bool  # §1.1 line 624
    can_enter_execute: bool             # §1.1 line 624 (while in plan)
    next_action: Optional[str]          # the recommendation string


@dataclass
class NextResult:
    requires_human: bool
    agent_safe: bool                    # True iff requires_human=False AND a concrete safe command exists
    command: Optional[str]              # e.g. "harness phase set done", or None if no action
    reason: str
    exit_code: int                      # 0 if agent_safe, 17 if requires_human, 18 if no_action_during_autopilot


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _iso_lt(a: Optional[str], b: Optional[str]) -> bool:
    """Return True iff a < b chronologically. Returns False if either is None."""
    if a is None or b is None:
        return False
    from datetime import datetime

    def _parse(s: str) -> datetime:
        if not s.endswith("Z"):
            raise ValueError(f"Not a UTC-Z timestamp: {s!r}")
        body = s[:-1]
        if "." in body:
            integer_part, frac = body.split(".", 1)
            body = integer_part + "." + frac[:6]
        return datetime.fromisoformat(body + "+00:00")

    return _parse(a) < _parse(b)


def _approved_fresh(state: dict, phase: str) -> bool:
    """Return True iff the approval is fresh relative to the phase entry timestamp.

    For phase==execute: approved AND approved_at >= execute_attempt_started_at
    For phase==plan: approved AND approved_at >= plan_finalized_at
    """
    approved = bool(state.get("approved"))
    if not approved:
        return False
    approved_at = state.get("approved_at")
    if phase == "execute":
        baseline = state.get("execute_attempt_started_at")
    elif phase == "plan":
        baseline = state.get("plan_finalized_at")
    else:
        return approved
    if approved_at is None or baseline is None:
        return False
    # approved_at >= baseline ↔ NOT (approved_at < baseline)
    return not _iso_lt(approved_at, baseline)


def _compute_last_halt_age(last_halt: Optional[dict]) -> Optional[int]:
    """Compute age in seconds since halt_at_iso, or None."""
    if last_halt is None:
        return None
    halt_at = last_halt.get("halt_at_iso")
    if halt_at is None:
        return None
    try:
        from datetime import datetime, timezone
        body = halt_at[:-1] if halt_at.endswith("Z") else halt_at
        if "." in body:
            integer_part, frac = body.split(".", 1)
            body = integer_part + "." + frac[:6]
        dt = datetime.fromisoformat(body + "+00:00")
        now = datetime.now(timezone.utc)
        delta = now - dt
        return max(0, int(delta.total_seconds()))
    except Exception:
        return None


def _phase_entered_at(state: dict, phase: str) -> Optional[str]:
    """Return the ISO timestamp when this phase was entered, if available."""
    if phase == "execute":
        return state.get("execute_attempt_started_at")
    elif phase == "plan":
        return state.get("plan_finalized_at")
    return None


def _next_action_for_state(state: dict) -> Optional[str]:
    """Determine the recommended next action command string."""
    execution_mode = state.get("execution_mode", "manual")
    phase = state.get("phase", "discuss")
    last_halt = state.get("last_halt")

    # Autopilot active — no manual action
    if execution_mode != "manual":
        return None

    # Unacknowledged halt takes priority
    if last_halt is not None and last_halt.get("acknowledged_at") is None:
        suggested = last_halt.get("suggested_next_command")
        return suggested if suggested else "harness halt-diary clear"

    # Phase-based
    if phase == "discuss":
        return "harness phase set plan"
    elif phase == "plan":
        if _approved_fresh(state, "plan"):
            return "harness phase set execute"
        approved_by = state.get("approved_by")
        if approved_by:
            return f"harness phase approve --by {approved_by}"
        return "harness phase approve"
    elif phase == "execute":
        if _approved_fresh(state, "execute"):
            return "harness phase set done"
        return f'harness phase reopen --to plan --reason "{REOPEN_REASON_PLACEHOLDER}"'
    elif phase == "done":
        return None
    return None


# ---------------------------------------------------------------------------
# Projected gate booleans (§1.1 line 624)
# ---------------------------------------------------------------------------


def _compute_projected_execute_gate_valid(state: dict) -> bool:
    """True iff phase==execute AND approved==true AND approved_at >= execute_attempt_started_at."""
    if state.get("phase") != "execute":
        return False
    return _approved_fresh(state, "execute")


def _compute_can_enter_execute(state: dict) -> bool:
    """True iff phase==plan AND approved==true AND approved_at >= plan_finalized_at."""
    if state.get("phase") != "plan":
        return False
    return _approved_fresh(state, "plan")


# ---------------------------------------------------------------------------
# Pure compute functions
# ---------------------------------------------------------------------------


def compute_status(*, state: dict, audit_path) -> StatusResult:
    """Pure: read state dict, return StatusResult.
    Does NOT acquire lock (read-only consistent-snapshot per §3.9).
    """
    phase = state.get("phase", "discuss")
    execution_mode = state.get("execution_mode", "manual")
    approved = bool(state.get("approved"))
    last_halt = state.get("last_halt")

    # Gate booleans
    projected_execute_gate_valid = _compute_projected_execute_gate_valid(state)
    can_enter_execute = _compute_can_enter_execute(state)

    # Next action recommendation
    next_action = _next_action_for_state(state)

    return StatusResult(
        phase=phase,
        phase_entered_at_iso=_phase_entered_at(state, phase),
        approved=approved,
        approved_by=state.get("approved_by"),
        approved_at_iso=state.get("approved_at"),
        approved_source=state.get("approved_source"),
        execution_mode=execution_mode,
        autopilot_run_id=state.get("autopilot_run_id"),
        autopilot_phase_slug=state.get("autopilot_phase_slug"),
        last_halt=last_halt,
        last_halt_age_seconds=_compute_last_halt_age(last_halt),
        projected_execute_gate_valid=projected_execute_gate_valid,
        can_enter_execute=can_enter_execute,
        next_action=next_action,
    )


def compute_next(*, state: dict, audit_path) -> NextResult:
    """Pure: decide next action based on current state.
    Returns NextResult with exit_code per §3.4 (0/17/18).
    """
    execution_mode = state.get("execution_mode", "manual")
    phase = state.get("phase", "discuss")
    last_halt = state.get("last_halt")

    # Rule 1: Autopilot active → no manual action
    if execution_mode != "manual":
        return NextResult(
            requires_human=False,
            agent_safe=False,
            command=None,
            reason="autopilot active; no manual action expected",
            exit_code=18,
        )

    # Rule 2: Unacknowledged halt → consult diary
    if last_halt is not None and last_halt.get("acknowledged_at") is None:
        suggested = last_halt.get("suggested_next_command")
        requires_human = bool(last_halt.get("suggested_next_command_requires_human", True))
        halt_reason = last_halt.get("halt_reason", "unknown")
        command = suggested if suggested else "harness halt-diary clear"
        exit_code = 17 if requires_human else 0
        return NextResult(
            requires_human=requires_human,
            agent_safe=(not requires_human and command is not None),
            command=command,
            reason=f"unacknowledged halt: {halt_reason}",
            exit_code=exit_code,
        )

    # Rule 3: Phase-based decision
    if phase == "discuss":
        return NextResult(
            requires_human=False,
            agent_safe=True,
            command="harness phase set plan",
            reason="in discuss phase; ready to move to plan",
            exit_code=0,
        )
    elif phase == "plan":
        if _approved_fresh(state, "plan"):
            return NextResult(
                requires_human=False,
                agent_safe=True,
                command="harness phase set execute",
                reason="plan approved and fresh; ready to execute",
                exit_code=0,
            )
        else:
            approved_by = state.get("approved_by")
            if approved_by:
                command = f"harness phase approve --by {approved_by}"
            else:
                command = "harness phase approve"
            return NextResult(
                requires_human=True,
                agent_safe=False,
                command=command,
                reason="plan requires human approval before execute",
                exit_code=17,
            )
    elif phase == "execute":
        if _approved_fresh(state, "execute"):
            return NextResult(
                requires_human=False,
                agent_safe=True,
                command="harness phase set done",
                reason="execute approved and fresh; ready to mark done",
                exit_code=0,
            )
        else:
            return NextResult(
                requires_human=True,
                agent_safe=False,
                command=f'harness phase reopen --to plan --reason "{REOPEN_REASON_PLACEHOLDER}"',
                reason="execute requires fresh approval; reopen to plan first",
                exit_code=17,
            )
    elif phase == "done":
        return NextResult(
            requires_human=False,
            agent_safe=False,
            command=None,
            reason="phase complete; no action needed",
            exit_code=0,
        )
    else:
        return NextResult(
            requires_human=False,
            agent_safe=False,
            command=None,
            reason=f"unknown phase {phase!r}; no action determined",
            exit_code=0,
        )


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


def format_status_human(result: StatusResult) -> str:
    """Render StatusResult as the human-friendly text (§3.9 lines 555-573)."""
    lines: list[str] = []

    # Phase line
    phase_str = result.phase
    if result.phase_entered_at_iso:
        phase_str += f" (entered {result.phase_entered_at_iso})"
    lines.append(f"Phase           : {phase_str}")

    # Approved line
    if result.approved:
        approved_parts = "yes"
        if result.approved_by:
            approved_parts += f" ({result.approved_by}"
            if result.approved_at_iso:
                approved_parts += f" at {result.approved_at_iso}"
            if result.approved_source:
                approved_parts += f", source={result.approved_source}"
            approved_parts += ")"
        lines.append(f"Approved        : {approved_parts}")
    else:
        lines.append("Approved        : no")

    # Execution mode line — append [reverted from <mode>] annotation when
    # the mode is manual but last_halt records a non-null previous mode.
    em = result.execution_mode
    em_str = em
    if (
        em == "manual"
        and result.last_halt is not None
        and result.last_halt.get("mode") is not None
    ):
        em_str = f"{em} [reverted from {result.last_halt['mode']}]"
    lines.append(f"Execution mode  : {em_str}")

    # Autopilot line
    if result.autopilot_run_id:
        ap_str = f"active (run_id={result.autopilot_run_id}"
        if result.autopilot_phase_slug:
            ap_str += f", phase={result.autopilot_phase_slug}"
        ap_str += ")"
    else:
        ap_str = "inactive"
    lines.append(f"Autopilot       : {ap_str}")

    # Halt diary line
    if result.last_halt is not None:
        lh = result.last_halt
        halt_str = ""
        run_id = lh.get("run_id")
        if run_id:
            halt_str += f"run_id={run_id}"
        age = result.last_halt_age_seconds
        if age is not None:
            if age < 120:
                halt_str += f", halted {age}s ago"
            else:
                halt_str += f", halted {age // 60}m ago"
        lines.append(f"Halt diary      : {halt_str}")
        halt_reason = lh.get("halt_reason")
        if halt_reason:
            lines.append(f"                  reason={halt_reason}")
        last_transition = lh.get("last_successful_transition")
        if last_transition:
            lines.append(f"                  last successful: {last_transition}")
    else:
        lines.append("Halt diary      : (none recent)")

    # Next action line
    if result.next_action:
        lines.append(f"Next action     : {result.next_action}")

    return "\n".join(lines) + "\n"


def format_status_json(result: StatusResult) -> str:
    """Render StatusResult as JSON (asdict + json.dumps sorted_keys + LF)."""
    d = asdict(result)
    return json.dumps(d, sort_keys=True, indent=2) + "\n"


def format_next_human(result: NextResult) -> str:
    """Render NextResult for plain `harness next`."""
    if result.command is not None:
        if result.requires_human:
            return (
                f"Human action required:\n"
                f"  {result.command}\n"
                f"  ({result.reason})\n"
            )
        else:
            return result.command + "\n"
    else:
        return f"No action: {result.reason}\n"


def format_next_shell(result: NextResult) -> tuple[str, int]:
    """Render NextResult for `harness next --shell`.

    Returns (stdout_text, exit_code). Per §3.9 line 590: prints stdout ONLY
    for agent-safe commands; otherwise prints nothing + exits 17.
    Special: requires_human → ("", 17). no_action_during_autopilot → ("", 18).
    """
    if result.exit_code == 18:
        return ("", 18)
    if result.requires_human:
        return ("", 17)
    if result.agent_safe and result.command:
        return (result.command + "\n", 0)
    # agent_safe=False, requires_human=False, exit_code=0 (e.g. phase done)
    return ("", 0)


def format_next_json(result: NextResult) -> str:
    """Render NextResult as JSON per §3.9 line 591.

    Shape: {requires_human, agent_safe, command, reason}.
    """
    d = {
        "requires_human": result.requires_human,
        "agent_safe": result.agent_safe,
        "command": result.command,
        "reason": result.reason,
    }
    return json.dumps(d, sort_keys=True, indent=2) + "\n"


__all__ = [
    "StatusResult",
    "NextResult",
    "compute_status",
    "compute_next",
    "format_status_human",
    "format_status_json",
    "format_next_human",
    "format_next_shell",
    "format_next_json",
]
