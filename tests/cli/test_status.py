"""Tests for `harness status` (§3.9 + §1.1 line 624).

Test suite exercises:
- Human-readable formatting (phase, approval, halt diary)
- JSON formatting with required keys
- projected_execute_gate_valid and can_enter_execute booleans (§1.1 line 624)
- State-trust preflight rejects tampered state
- Read-only contract: no audit row written

Spec: docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md
§3.9, §1.1 line 624
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
    phase: str = "execute",
    approved: bool = True,
    approved_by: str = "alice@example.com",
    approved_at: Optional[str] = "2026-05-18T10:00:00Z",
    execution_mode: str = "manual",
    execute_attempt_started_at: Optional[str] = "2026-05-18T10:00:00Z",
    plan_finalized_at: Optional[str] = "2026-05-18T09:50:00Z",
    last_halt: Optional[dict] = None,
    autopilot_run_id: Optional[str] = None,
    autopilot_phase_slug: Optional[str] = None,
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
        "autopilot_phase_slug": autopilot_phase_slug,
        "autopilot_allow_network": False,
        "autopilot_started_at_iso": None,
        "cli_budgets_remaining": None,
        "last_halt_history": [],
        "state_schema_version": 2,
    }


def _make_halt_diary(
    *,
    run_id: str = "abc123",
    halt_reason: str = "budget_exhausted:file_mutation_ops",
    halt_at_iso: str = "2026-05-18T09:55:00Z",
    suggested_next_command: str = "harness phase autopilot stop --reason 'done'",
    suggested_next_command_requires_human: bool = False,
    acknowledged_at: Optional[str] = None,
) -> dict:
    return {
        "run_id": run_id,
        "halt_reason": halt_reason,
        "halt_at_iso": halt_at_iso,
        "suggested_next_command": suggested_next_command,
        "suggested_next_command_requires_human": suggested_next_command_requires_human,
        "acknowledged_at": acknowledged_at,
    }


# ---------------------------------------------------------------------------
# test_status_human_format_phase_execute_approved
# ---------------------------------------------------------------------------


def test_status_human_format_phase_execute_approved():
    """Human format for execute+approved shows phase, approval, and next action."""
    state = _make_state(
        phase="execute",
        approved=True,
        approved_by="alice@example.com",
        approved_at="2026-05-18T10:00:00Z",
        execute_attempt_started_at="2026-05-18T09:58:00Z",
    )
    result = sn.compute_status(state=state, audit_path=None)
    text = sn.format_status_human(result)

    assert "Phase" in text
    assert "execute" in text
    assert "Approved" in text
    assert "yes" in text
    assert "alice@example.com" in text
    assert "Next action" in text
    assert "harness phase set done" in text


def test_status_human_format_halt_diary_none():
    """Human format shows '(none recent)' when no halt diary."""
    state = _make_state(phase="execute", last_halt=None)
    result = sn.compute_status(state=state, audit_path=None)
    text = sn.format_status_human(result)
    assert "(none recent)" in text


# ---------------------------------------------------------------------------
# test_status_human_format_with_recent_halt
# ---------------------------------------------------------------------------


def test_status_human_format_with_recent_halt():
    """Human format renders halt block when last_halt is present."""
    halt = _make_halt_diary(
        run_id="8f6c",
        halt_reason="verification_failed",
    )
    state = _make_state(phase="execute", last_halt=halt)
    result = sn.compute_status(state=state, audit_path=None)
    text = sn.format_status_human(result)

    assert "Halt diary" in text
    assert "8f6c" in text
    assert "verification_failed" in text


def test_status_human_halt_acknowledged_at_set_not_blocking():
    """Halt with acknowledged_at set is still shown but next_action reflects normal flow."""
    halt = _make_halt_diary(acknowledged_at="2026-05-18T10:01:00Z")
    state = _make_state(phase="plan", approved=True, approved_at="2026-05-18T10:00:00Z",
                        plan_finalized_at="2026-05-18T09:50:00Z", last_halt=halt)
    result = sn.compute_status(state=state, audit_path=None)
    text = sn.format_status_human(result)
    # Acknowledged halt doesn't block
    assert "harness phase set execute" in text


# ---------------------------------------------------------------------------
# test_status_json_format
# ---------------------------------------------------------------------------


def test_status_json_format():
    """JSON output parses cleanly and has required keys."""
    state = _make_state()
    result = sn.compute_status(state=state, audit_path=None)
    text = sn.format_status_json(result)

    parsed = json.loads(text)
    required_keys = {
        "phase",
        "approved",
        "approved_by",
        "approved_at_iso",
        "execution_mode",
        "projected_execute_gate_valid",
        "can_enter_execute",
        "last_halt",
        "next_action",
    }
    for key in required_keys:
        assert key in parsed, f"Missing key: {key!r}"


def test_status_json_is_sorted():
    """JSON output has sorted keys for deterministic diffs."""
    state = _make_state()
    result = sn.compute_status(state=state, audit_path=None)
    text = sn.format_status_json(result)
    parsed = json.loads(text)
    keys = list(parsed.keys())
    assert keys == sorted(keys), "JSON keys are not sorted"


# ---------------------------------------------------------------------------
# test_status_projected_execute_gate_valid
# ---------------------------------------------------------------------------


def test_status_projected_execute_gate_valid_when_phase_execute_approved_fresh():
    """projected_execute_gate_valid=True when in execute, approved, approved_at >= execute_attempt_started_at."""
    state = _make_state(
        phase="execute",
        approved=True,
        approved_at="2026-05-18T10:00:00Z",
        execute_attempt_started_at="2026-05-18T09:58:00Z",
    )
    result = sn.compute_status(state=state, audit_path=None)
    assert result.projected_execute_gate_valid is True


def test_status_projected_execute_gate_valid_false_when_not_execute():
    """projected_execute_gate_valid=False when phase != execute."""
    state = _make_state(phase="plan")
    result = sn.compute_status(state=state, audit_path=None)
    assert result.projected_execute_gate_valid is False


def test_status_projected_execute_gate_valid_false_when_not_approved():
    """projected_execute_gate_valid=False when not approved."""
    state = _make_state(phase="execute", approved=False, approved_at=None)
    result = sn.compute_status(state=state, audit_path=None)
    assert result.projected_execute_gate_valid is False


def test_status_projected_execute_gate_valid_false_when_approval_stale():
    """projected_execute_gate_valid=False when approved_at < execute_attempt_started_at."""
    state = _make_state(
        phase="execute",
        approved=True,
        approved_at="2026-05-18T09:55:00Z",   # before execute_attempt
        execute_attempt_started_at="2026-05-18T10:00:00Z",
    )
    result = sn.compute_status(state=state, audit_path=None)
    assert result.projected_execute_gate_valid is False


# ---------------------------------------------------------------------------
# test_status_can_enter_execute
# ---------------------------------------------------------------------------


def test_status_can_enter_execute_when_plan_approved_fresh():
    """can_enter_execute=True when in plan, approved, approved_at >= plan_finalized_at."""
    state = _make_state(
        phase="plan",
        approved=True,
        approved_at="2026-05-18T10:00:00Z",
        plan_finalized_at="2026-05-18T09:50:00Z",
        execute_attempt_started_at=None,
    )
    result = sn.compute_status(state=state, audit_path=None)
    assert result.can_enter_execute is True


def test_status_can_enter_execute_false_when_plan_unapproved():
    """can_enter_execute=False when not approved."""
    state = _make_state(
        phase="plan",
        approved=False,
        approved_at=None,
        plan_finalized_at="2026-05-18T09:50:00Z",
        execute_attempt_started_at=None,
    )
    result = sn.compute_status(state=state, audit_path=None)
    assert result.can_enter_execute is False


def test_status_can_enter_execute_false_when_not_plan():
    """can_enter_execute=False when phase != plan."""
    state = _make_state(phase="execute")
    result = sn.compute_status(state=state, audit_path=None)
    assert result.can_enter_execute is False


def test_status_can_enter_execute_false_when_approval_predates_plan_finalized():
    """can_enter_execute=False when approved_at < plan_finalized_at."""
    state = _make_state(
        phase="plan",
        approved=True,
        approved_at="2026-05-18T09:40:00Z",    # before plan_finalized_at
        plan_finalized_at="2026-05-18T09:50:00Z",
        execute_attempt_started_at=None,
    )
    result = sn.compute_status(state=state, audit_path=None)
    assert result.can_enter_execute is False


# ---------------------------------------------------------------------------
# test_status_preflight_rejects_tampered_state
# ---------------------------------------------------------------------------


def test_status_preflight_rejects_tampered_state(tmp_path: Path):
    """State-trust preflight rejects state with tampered approved=true (no audit match)."""
    from lib import state_trust as _state_trust, phase_lock as _phase_lock
    import json

    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    audit_path = harness_dir / "audit.log"

    # Write a tampered state with no corresponding audit entry
    state_path = scratch / "phase-state.json"
    tampered_state = {
        "phase": "discuss",
        "approved": True,
        "execution_mode": "manual",
        "state_schema_version": 2,
    }
    state_path.write_text(json.dumps(tampered_state, sort_keys=True) + "\n", encoding="utf-8")

    # Write audit with a different after_sha256 (mismatch)
    audit_path.write_text(
        json.dumps({
            "seq": 1,
            "verb": "phase.set",
            "after_sha256": "a" * 64,  # wrong hash
        }) + "\n",
        encoding="utf-8",
    )

    # Preflight should raise StateAuditMismatchError when lock is held
    lock = _phase_lock.acquire_primary(scratch, timeout_s=5.0, audit_path=audit_path)
    try:
        with pytest.raises(_state_trust.StateAuditMismatchError):
            _state_trust.preflight(
                scratch,
                audit_path=audit_path,
                lock=lock,
                anchor_verified=True,
            )
    finally:
        _phase_lock.release_primary(lock)


# ---------------------------------------------------------------------------
# test_status_read_only_no_audit_row
# ---------------------------------------------------------------------------


def test_status_read_only_no_audit_row(tmp_path: Path):
    """compute_status does NOT write to the audit log."""
    import json

    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    audit_path = harness_dir / "audit.log"

    state = _make_state()
    result = sn.compute_status(state=state, audit_path=audit_path)

    # Audit log must NOT be created or written by compute_status
    assert not audit_path.exists(), "compute_status wrote an audit row (forbidden)"


def test_status_compute_does_not_write_state(tmp_path: Path):
    """compute_status does NOT modify state files."""
    import json

    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    state_path = scratch / "phase-state.json"
    state_data = _make_state()
    original_bytes = json.dumps(state_data, sort_keys=True).encode()
    state_path.write_bytes(original_bytes)

    sn.compute_status(state=state_data, audit_path=tmp_path / ".harness" / "audit.log")

    assert state_path.read_bytes() == original_bytes, "compute_status mutated state file"


# ---------------------------------------------------------------------------
# Additional edge cases
# ---------------------------------------------------------------------------


def test_status_autopilot_active_shown():
    """Human format shows autopilot as active when autopilot_run_id is set."""
    state = _make_state(
        phase="execute",
        execution_mode="phase_autopilot",
        autopilot_run_id="run-xyz",
        autopilot_phase_slug="02c-hardening",
    )
    result = sn.compute_status(state=state, audit_path=None)
    text = sn.format_status_human(result)
    assert "active" in text
    assert "run-xyz" in text


def test_status_json_includes_projected_booleans():
    """JSON must include both projected gate booleans."""
    state = _make_state(
        phase="execute",
        approved=True,
        approved_at="2026-05-18T10:00:00Z",
        execute_attempt_started_at="2026-05-18T09:58:00Z",
    )
    result = sn.compute_status(state=state, audit_path=None)
    text = sn.format_status_json(result)
    parsed = json.loads(text)
    assert "projected_execute_gate_valid" in parsed
    assert "can_enter_execute" in parsed
    assert parsed["projected_execute_gate_valid"] is True
    assert parsed["can_enter_execute"] is False  # phase != plan


def test_status_phase_discuss_no_approval():
    """Discuss phase with no approval shows no, next=set plan."""
    state = _make_state(phase="discuss", approved=False, approved_at=None,
                        execute_attempt_started_at=None)
    result = sn.compute_status(state=state, audit_path=None)
    text = sn.format_status_human(result)
    assert "no" in text.lower()
    assert "harness phase set plan" in text
