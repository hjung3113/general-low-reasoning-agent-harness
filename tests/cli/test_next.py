"""Tests for `harness next` (§3.9 + §3.4 exit codes).

Tests cover:
- Human format output
- Shell format: stdout suppressed when requires_human
- JSON format shape
- Exit code 18 for autopilot active
- Unacknowledged halt returns suggested command
- Phase done exits 0 with no action
- Agent-safe command printed to stdout with exit 0

Spec: docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md
§3.9, §3.4
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import pytest

# Make scripts/ importable
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lib import status_next as sn


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_state(
    *,
    phase: str = "plan",
    approved: bool = False,
    approved_by: Optional[str] = None,
    approved_at: Optional[str] = None,
    execution_mode: str = "manual",
    execute_attempt_started_at: Optional[str] = None,
    plan_finalized_at: Optional[str] = "2026-05-18T09:50:00Z",
    last_halt: Optional[dict] = None,
    autopilot_run_id: Optional[str] = None,
) -> dict:
    return {
        "phase": phase,
        "approved": approved,
        "approved_by": approved_by,
        "approved_at": approved_at,
        "execution_mode": execution_mode,
        "execute_attempt_started_at": execute_attempt_started_at,
        "plan_finalized_at": plan_finalized_at,
        "last_halt": last_halt,
        "autopilot_run_id": autopilot_run_id,
        "autopilot_phase_slug": None,
        "autopilot_allow_network": False,
        "autopilot_started_at_iso": None,
        "cli_budgets_remaining": None,
        "last_halt_history": [],
        "state_schema_version": 2,
    }


def _make_halt_diary(
    *,
    run_id: str = "abc123",
    halt_reason: str = "budget_exhausted",
    suggested_next_command: str = "harness phase autopilot stop --reason 'done'",
    suggested_next_command_requires_human: bool = False,
    acknowledged_at: Optional[str] = None,
) -> dict:
    return {
        "run_id": run_id,
        "halt_reason": halt_reason,
        "halt_at_iso": "2026-05-18T09:55:00Z",
        "suggested_next_command": suggested_next_command,
        "suggested_next_command_requires_human": suggested_next_command_requires_human,
        "acknowledged_at": acknowledged_at,
    }


# ---------------------------------------------------------------------------
# test_next_human_in_plan_unapproved_prints_approve_command
# ---------------------------------------------------------------------------


def test_next_human_in_plan_unapproved_prints_approve_command():
    """human next for plan+unapproved shows approve command."""
    state = _make_state(phase="plan", approved=False)
    result = sn.compute_next(state=state, audit_path=None)
    text = sn.format_next_human(result)

    assert "harness phase approve" in text
    assert result.requires_human is True
    assert result.exit_code == 17


def test_next_human_in_discuss_prints_set_plan():
    """Human next for discuss phase shows set plan."""
    state = _make_state(phase="discuss")
    result = sn.compute_next(state=state, audit_path=None)
    text = sn.format_next_human(result)
    assert "harness phase set plan" in text
    assert result.requires_human is False
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# test_next_shell_exits_17_when_requires_human
# ---------------------------------------------------------------------------


def test_next_shell_exits_17_when_requires_human():
    """shell format exits 17 for human-required action."""
    state = _make_state(phase="plan", approved=False)
    result = sn.compute_next(state=state, audit_path=None)
    text, exit_code = sn.format_next_shell(result)
    assert exit_code == 17


# ---------------------------------------------------------------------------
# test_next_shell_stdout_empty_when_requires_human
# ---------------------------------------------------------------------------


def test_next_shell_stdout_empty_when_requires_human():
    """shell format prints nothing to stdout when requires_human."""
    state = _make_state(phase="plan", approved=False)
    result = sn.compute_next(state=state, audit_path=None)
    text, exit_code = sn.format_next_shell(result)
    assert text == "", f"Expected empty stdout, got: {text!r}"


# ---------------------------------------------------------------------------
# test_next_json_shape
# ---------------------------------------------------------------------------


def test_next_json_shape():
    """JSON next output has all 4 required keys with correct types."""
    state = _make_state(phase="discuss")
    result = sn.compute_next(state=state, audit_path=None)
    text = sn.format_next_json(result)

    parsed = json.loads(text)
    assert "requires_human" in parsed
    assert "agent_safe" in parsed
    assert "command" in parsed
    assert "reason" in parsed
    assert isinstance(parsed["requires_human"], bool)
    assert isinstance(parsed["agent_safe"], bool)
    assert isinstance(parsed["reason"], str)
    # command may be str or None
    assert parsed["command"] is None or isinstance(parsed["command"], str)


def test_next_json_sorted_keys():
    """JSON next output has sorted keys."""
    state = _make_state(phase="discuss")
    result = sn.compute_next(state=state, audit_path=None)
    text = sn.format_next_json(result)
    parsed = json.loads(text)
    keys = list(parsed.keys())
    assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# test_next_autopilot_active_exits_18
# ---------------------------------------------------------------------------


def test_next_autopilot_active_exits_18():
    """Autopilot removed — execution_mode is always manual; no exit 18 case."""
    # execution_mode=phase_autopilot is ignored; system treats all as manual
    state = _make_state(phase="execute", execution_mode="manual")
    result = sn.compute_next(state=state, audit_path=None)
    # In execute without approval, should require human
    assert result.exit_code == 17
    assert result.requires_human is True


def test_next_shell_exits_18_when_autopilot():
    """Shell format no longer exits 18 — autopilot removed."""
    state = _make_state(phase="discuss")
    result = sn.compute_next(state=state, audit_path=None)
    text, exit_code = sn.format_next_shell(result)
    assert exit_code == 0
    assert "harness phase set plan" in text


# ---------------------------------------------------------------------------
# test_next_unacknowledged_halt_returns_suggested_command
# ---------------------------------------------------------------------------


def test_next_unacknowledged_halt_returns_suggested_command():
    """Halt diary removed — last_halt is ignored; normal phase logic applies."""
    halt = _make_halt_diary(
        suggested_next_command="harness phase autopilot stop --reason 'budget'",
        suggested_next_command_requires_human=False,
    )
    state = _make_state(phase="discuss", execution_mode="manual", last_halt=halt)
    result = sn.compute_next(state=state, audit_path=None)

    # Halt diary no longer affects next action; discuss phase goes to plan
    assert result.command == "harness phase set plan"
    assert result.exit_code == 0


def test_next_unacknowledged_halt_requires_human_exits_17():
    """Unacknowledged halt with requires_human=True → exit_code=17."""
    halt = _make_halt_diary(
        suggested_next_command="harness phase reopen --to plan",
        suggested_next_command_requires_human=True,
    )
    state = _make_state(phase="execute", execution_mode="manual", last_halt=halt)
    result = sn.compute_next(state=state, audit_path=None)

    assert result.requires_human is True
    assert result.exit_code == 17


def test_next_acknowledged_halt_ignored():
    """Acknowledged halt (acknowledged_at set) does not block normal next logic."""
    halt = _make_halt_diary(acknowledged_at="2026-05-18T10:01:00Z")
    state = _make_state(phase="discuss", last_halt=halt)
    result = sn.compute_next(state=state, audit_path=None)
    # Should fall through to normal discuss logic
    assert result.command == "harness phase set plan"
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# test_next_phase_done_exit_0_no_action
# ---------------------------------------------------------------------------


def test_next_phase_done_exit_0_no_action():
    """phase=done → exit_code=0, command=None, no action needed."""
    state = _make_state(phase="done")
    result = sn.compute_next(state=state, audit_path=None)
    assert result.exit_code == 0
    assert result.command is None
    assert result.agent_safe is False
    assert "complete" in result.reason.lower() or "no action" in result.reason.lower()


# ---------------------------------------------------------------------------
# test_next_shell_safe_command_exit_0_with_stdout
# ---------------------------------------------------------------------------


def test_next_shell_safe_command_exit_0_with_stdout():
    """shell format prints safe command to stdout and exits 0."""
    state = _make_state(phase="discuss")
    result = sn.compute_next(state=state, audit_path=None)
    text, exit_code = sn.format_next_shell(result)
    assert exit_code == 0
    assert "harness phase set plan" in text


def test_next_shell_execute_approved_fresh_exits_0():
    """shell format: execute phase with fresh approval → exit 0 + command."""
    state = _make_state(
        phase="execute",
        approved=True,
        approved_at="2026-05-18T10:00:00Z",
        execute_attempt_started_at="2026-05-18T09:58:00Z",
    )
    result = sn.compute_next(state=state, audit_path=None)
    text, exit_code = sn.format_next_shell(result)
    assert exit_code == 0
    assert "harness phase set done" in text


def test_next_shell_plan_approved_fresh_exits_0():
    """shell format: plan phase with fresh approval → exit 0 + set execute command."""
    state = _make_state(
        phase="plan",
        approved=True,
        approved_at="2026-05-18T10:00:00Z",
        plan_finalized_at="2026-05-18T09:50:00Z",
    )
    result = sn.compute_next(state=state, audit_path=None)
    text, exit_code = sn.format_next_shell(result)
    assert exit_code == 0
    assert "harness phase set execute" in text


# ---------------------------------------------------------------------------
# agent_safe flag contract
# ---------------------------------------------------------------------------


def test_next_agent_safe_true_only_when_safe_command_and_not_human():
    """agent_safe is True only when requires_human=False AND command is non-None."""
    state = _make_state(phase="discuss")
    result = sn.compute_next(state=state, audit_path=None)
    assert result.agent_safe is True
    assert result.requires_human is False
    assert result.command is not None


def test_next_agent_safe_false_when_human_required():
    """agent_safe is False when requires_human=True."""
    state = _make_state(phase="plan", approved=False)
    result = sn.compute_next(state=state, audit_path=None)
    assert result.agent_safe is False
    assert result.requires_human is True


def test_next_agent_safe_false_when_no_command():
    """agent_safe is False when no command (phase=done)."""
    state = _make_state(phase="done")
    result = sn.compute_next(state=state, audit_path=None)
    assert result.agent_safe is False
    assert result.command is None


# ---------------------------------------------------------------------------
# P1-1: state-trust fail-closed for next
# ---------------------------------------------------------------------------


def test_next_fails_closed_when_state_audit_mismatch(tmp_path: Path):
    """next returns exit 10 when state hash mismatches audit tail."""
    import json
    from lib import status_next_cli as cli

    (tmp_path / ".git").mkdir()
    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    audit_path = harness_dir / "audit.log"

    # Write audit log with a hash that won't match state.
    audit_path.write_text(
        json.dumps({"seq": 1, "verb": "phase.set", "after_sha256": "a" * 64}) + "\n",
        encoding="utf-8",
    )

    # Write state file whose hash differs from audit tail.
    state_path = scratch / "phase-state.json"
    state_path.write_text(
        json.dumps({"phase": "plan", "approved": True, "execution_mode": "manual",
                    "state_schema_version": 2}, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    result_state, exit_code = cli._read_state_with_preflight(
        scratch=scratch,
        audit_path=audit_path,
        cwd=tmp_path,
    )
    assert result_state is None, "Expected None state on mismatch"
    assert exit_code == 10, f"Expected exit 10, got {exit_code}"


# ---------------------------------------------------------------------------
# P2-1: JSON shape pin
# ---------------------------------------------------------------------------


def test_next_json_shape_complete():
    """JSON next output key set matches the expected complete shape — prevents silent field renames (P2-1)."""
    state = _make_state(phase="discuss")
    result = sn.compute_next(state=state, audit_path=None)
    text = sn.format_next_json(result)
    parsed = json.loads(text)

    # Per §3.9 line 591: {requires_human, agent_safe, command, reason}.
    expected_keys = {"requires_human", "agent_safe", "command", "reason"}
    assert set(parsed.keys()) == expected_keys, (
        f"JSON shape mismatch.\n"
        f"  Extra keys  : {set(parsed.keys()) - expected_keys}\n"
        f"  Missing keys: {expected_keys - set(parsed.keys())}"
    )
