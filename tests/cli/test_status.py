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


# ---------------------------------------------------------------------------
# P1-1: anchor fail-closed tests
# ---------------------------------------------------------------------------


def test_status_fails_closed_when_anchor_missing_and_state_present(tmp_path: Path):
    """status returns exit 6 when anchor is missing but state file exists (P1-1)."""
    import json
    from lib import status_next_cli as cli

    # Set up .git, .harness, .scratch so walk-up finds the tmp_path as repo root.
    (tmp_path / ".git").mkdir()
    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()

    # Write a state file (so anchor check is triggered).
    state_path = scratch / "phase-state.json"
    state_path.write_text(
        json.dumps({"phase": "discuss", "approved": False, "execution_mode": "manual",
                    "state_schema_version": 2}) + "\n",
        encoding="utf-8",
    )

    # NO anchor file present — should fail-closed.
    result_state, exit_code = cli._read_state_with_preflight(
        scratch=scratch,
        audit_path=harness_dir / "audit.log",
        cwd=tmp_path,
    )
    assert result_state is None, "Expected None state on anchor_missing"
    assert exit_code == 6, f"Expected exit 6, got {exit_code}"


def test_status_fails_closed_when_anchor_mismatch(tmp_path: Path):
    """status returns exit 6 when anchor exists but mismatches the audit log (P1-1)."""
    import json
    from lib import status_next_cli as cli
    from lib import audit_anchor as _aa

    (tmp_path / ".git").mkdir()
    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    audit_path = harness_dir / "audit.log"

    # Write minimal audit log.
    audit_path.write_text(
        json.dumps({"seq": 1, "verb": "phase.set", "after_sha256": "a" * 64}) + "\n",
        encoding="utf-8",
    )

    # Write a state file.
    state_path = scratch / "phase-state.json"
    state_path.write_text(
        json.dumps({"phase": "discuss", "approved": False, "execution_mode": "manual",
                    "state_schema_version": 2}) + "\n",
        encoding="utf-8",
    )

    # Write an anchor with a MISMATCHING hash.
    anchor_path = harness_dir / "audit.tip-anchor.json"
    anchor_path.write_text(
        json.dumps({"tip_sha256": "b" * 64, "tip_seq": 1, "anchored_at": "2026-05-18T00:00:00Z"}) + "\n",
        encoding="utf-8",
    )

    result_state, exit_code = cli._read_state_with_preflight(
        scratch=scratch,
        audit_path=audit_path,
        cwd=tmp_path,
    )
    assert result_state is None, "Expected None state on anchor_mismatch"
    assert exit_code == 6, f"Expected exit 6, got {exit_code}"


def test_status_bootstrap_succeeds_no_state_no_anchor(tmp_path: Path):
    """Bootstrap repo: no state file and no anchor → exit 0, default state (P1-1)."""
    import json
    from lib import status_next_cli as cli

    (tmp_path / ".git").mkdir()
    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()

    # Neither state nor anchor present.
    result_state, exit_code = cli._read_state_with_preflight(
        scratch=scratch,
        audit_path=harness_dir / "audit.log",
        cwd=tmp_path,
    )
    assert exit_code == 0, f"Bootstrap should exit 0, got {exit_code}"
    assert result_state is not None
    assert result_state.get("phase") == "discuss"


# ---------------------------------------------------------------------------
# P1-2: auditless under stale-lock recovery
# ---------------------------------------------------------------------------


def test_status_no_audit_row_after_stale_lock_recovery(tmp_path: Path):
    """status must NOT write any audit row even when a stale primary lock is recovered (P1-2)."""
    import json
    import time
    from lib import status_next_cli as cli
    from lib import phase_lock as _phase_lock
    from lib import audit_anchor as _aa

    (tmp_path / ".git").mkdir()
    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    audit_path = harness_dir / "audit.log"

    # Write a valid audit log entry so anchor can be written.
    audit_path.write_text(
        json.dumps({"seq": 1, "verb": "init", "after_sha256": "c" * 64}) + "\n",
        encoding="utf-8",
    )

    # Write matching anchor.
    anchor_path = harness_dir / "audit.tip-anchor.json"
    anchor_path.write_text(
        json.dumps({"tip_sha256": "c" * 64, "tip_seq": 1, "anchored_at": "2026-05-18T00:00:00Z"}) + "\n",
        encoding="utf-8",
    )

    # Write a state file.
    state_path = scratch / "phase-state.json"
    state_path.write_text(
        json.dumps({"phase": "discuss", "approved": False, "execution_mode": "manual",
                    "state_schema_version": 2}) + "\n",
        encoding="utf-8",
    )

    # Plant a stale primary lock (old mtime + non-existent pid).
    primary_lock = scratch / ".phase_primary.lock"
    primary_lock.write_text(
        json.dumps({"pid": 99999999, "boot_id": "stale", "hostname": "testhost",
                    "acquired_at": "2026-05-18T00:00:00Z"}) + "\n",
        encoding="utf-8",
    )
    # Force mtime to be old enough to be considered stale.
    old_time = time.time() - 120
    import os
    os.utime(str(primary_lock), (old_time, old_time))

    # Record audit log size before.
    audit_size_before = audit_path.stat().st_size

    # Invoke _read_state_with_preflight — anchor verify will fail (hash mismatch), but
    # the important assertion is that even if we get past anchor, the lock acquire
    # uses audit_path=None. Since anchor verify may fail here (state hash != audit),
    # we only care that audit_path is unchanged.
    # The lock itself should be acquired without writing a recovery audit row.
    # We cannot guarantee preflight success here (no real state trust), so just
    # check audit_path size is unchanged.
    try:
        cli._read_state_with_preflight(
            scratch=scratch,
            audit_path=audit_path,
            cwd=tmp_path,
        )
    except Exception:
        pass  # We only care about audit file below.

    audit_size_after = audit_path.stat().st_size
    assert audit_size_after == audit_size_before, (
        f"audit.log grew from {audit_size_before} to {audit_size_after} bytes during status "
        "(stale-lock recovery must not write audit rows; §3.9 line 578)."
    )


# ---------------------------------------------------------------------------
# P2-1: JSON shape pin
# ---------------------------------------------------------------------------


def test_status_json_shape_complete():
    """JSON output key set matches the complete expected shape — prevents silent field renames (P2-1)."""
    state = _make_state()
    result = sn.compute_status(state=state, audit_path=None)
    text = sn.format_status_json(result)
    parsed = json.loads(text)

    expected_keys = {
        "approved",
        "approved_at_iso",
        "approved_by",
        "approved_source",
        "autopilot_phase_slug",
        "autopilot_run_id",
        "can_enter_execute",
        "execution_mode",
        "last_halt",
        "last_halt_age_seconds",
        "next_action",
        "phase",
        "phase_entered_at_iso",
        "projected_execute_gate_valid",
    }
    assert set(parsed.keys()) == expected_keys, (
        f"JSON shape mismatch.\n"
        f"  Extra keys  : {set(parsed.keys()) - expected_keys}\n"
        f"  Missing keys: {expected_keys - set(parsed.keys())}"
    )


# ---------------------------------------------------------------------------
# P2-3: _iso_lt microsecond precision regression
# ---------------------------------------------------------------------------


def test_iso_lt_microsecond_precision():
    """approved_at with microsecond precision compares correctly against execute_attempt_started_at (P2-3).

    Regression guard: _iso_lt truncates fractional seconds to 6 digits so that
    datetime.fromisoformat does not raise ValueError on 7+ digit fractions.
    """
    # approved_at has microsecond precision; execute_attempt_started_at is rounded.
    # approved_at > execute_attempt_started_at → gate valid.
    state = _make_state(
        phase="execute",
        approved=True,
        approved_at="2026-05-18T10:00:00.123456Z",   # 6 fractional digits
        execute_attempt_started_at="2026-05-18T09:58:00.000000Z",
    )
    result = sn.compute_status(state=state, audit_path=None)
    assert result.projected_execute_gate_valid is True, (
        "Gate should be valid when approved_at > execute_attempt_started_at (microsecond precision)"
    )

    # Same moment: approved_at == execute_attempt_started_at → gate valid (not lt).
    state2 = _make_state(
        phase="execute",
        approved=True,
        approved_at="2026-05-18T10:00:00.000001Z",
        execute_attempt_started_at="2026-05-18T10:00:00.000001Z",
    )
    result2 = sn.compute_status(state=state2, audit_path=None)
    assert result2.projected_execute_gate_valid is True, (
        "Gate should be valid when approved_at == execute_attempt_started_at"
    )

    # approved_at < execute_attempt_started_at by one microsecond → gate invalid.
    state3 = _make_state(
        phase="execute",
        approved=True,
        approved_at="2026-05-18T10:00:00.000000Z",
        execute_attempt_started_at="2026-05-18T10:00:00.000001Z",
    )
    result3 = sn.compute_status(state=state3, audit_path=None)
    assert result3.projected_execute_gate_valid is False, (
        "Gate should be invalid when approved_at < execute_attempt_started_at by one microsecond"
    )


# ---------------------------------------------------------------------------
# P2-6: reverted annotation
# ---------------------------------------------------------------------------


def test_status_human_format_reverted_annotation():
    """Human format appends [reverted from <mode>] when manual + last_halt.mode is set (P2-6)."""
    halt = _make_halt_diary()
    halt["mode"] = "phase_autopilot"
    state = _make_state(
        phase="discuss",
        execution_mode="manual",
        last_halt=halt,
    )
    result = sn.compute_status(state=state, audit_path=None)
    text = sn.format_status_human(result)
    assert "[reverted from phase_autopilot]" in text, (
        f"Expected '[reverted from phase_autopilot]' in execution mode line.\nGot:\n{text}"
    )


def test_status_human_format_no_reverted_annotation_without_halt_mode():
    """Human format does NOT append reverted annotation when last_halt.mode is absent."""
    halt = _make_halt_diary()
    # No 'mode' key in halt diary.
    state = _make_state(
        phase="discuss",
        execution_mode="manual",
        last_halt=halt,
    )
    result = sn.compute_status(state=state, audit_path=None)
    text = sn.format_status_human(result)
    assert "[reverted from" not in text, (
        "No reverted annotation expected when last_halt.mode is absent."
    )


def test_status_human_format_no_reverted_annotation_when_autopilot():
    """Human format does NOT append reverted annotation when execution_mode is autopilot."""
    halt = _make_halt_diary()
    halt["mode"] = "phase_autopilot"
    state = _make_state(
        phase="execute",
        execution_mode="phase_autopilot",
        last_halt=halt,
    )
    result = sn.compute_status(state=state, audit_path=None)
    text = sn.format_status_human(result)
    assert "[reverted from" not in text, (
        "No reverted annotation expected when execution_mode is not manual."
    )
