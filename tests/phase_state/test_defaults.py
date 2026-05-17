"""S01-A.1: default population for the new schema fields (design §1.1).

Pure-function tests for `apply_v2_defaults`. Filesystem writes are S01-A.2.
"""

from __future__ import annotations

import pytest

from lib.phase_state import (
    EXECUTION_MODES,
    NEW_V2_FIELDS,
    apply_v2_defaults,
    coerce_legacy_execution_mode,
)


def test_execution_modes_enum_pin():
    """Pin the enum so the validator can rely on this set."""
    assert EXECUTION_MODES == {"manual", "phase_autopilot", "chain_autopilot"}


def test_apply_v2_defaults_populates_every_new_field():
    state = {"execution_mode": "manual", "phase": "discuss"}
    out = apply_v2_defaults(state)
    for key in NEW_V2_FIELDS:
        assert key in out, f"default not populated: {key}"


def test_apply_v2_defaults_does_not_overwrite_existing_values():
    state = {
        "execution_mode": "phase_autopilot",
        "autopilot_run_id": "11111111-1111-1111-1111-111111111111",
        "autopilot_allow_network": True,
        "plan_finalized_at": "2026-05-17T00:00:00Z",
    }
    out = apply_v2_defaults(state)
    assert out["autopilot_run_id"] == "11111111-1111-1111-1111-111111111111"
    assert out["autopilot_allow_network"] is True
    assert out["plan_finalized_at"] == "2026-05-17T00:00:00Z"


def test_default_execution_mode_when_field_missing():
    out = apply_v2_defaults({"phase": "discuss"})
    assert out["execution_mode"] == "manual"


def test_default_autopilot_identity_fields_are_null():
    out = apply_v2_defaults({"execution_mode": "manual"})
    assert out["autopilot_run_id"] is None
    assert out["autopilot_mode"] is None
    assert out["autopilot_phase_slug"] is None
    assert out["autopilot_start_entry_hash"] is None


def test_default_autopilot_allow_network_is_false_bool():
    out = apply_v2_defaults({"execution_mode": "manual"})
    assert out["autopilot_allow_network"] is False


def test_default_cli_budgets_remaining_is_null():
    """`null` until `phase autopilot start --budget` populates it (S07-prep)."""
    out = apply_v2_defaults({"execution_mode": "manual"})
    assert out["cli_budgets_remaining"] is None


def test_default_last_halt_is_null_and_history_is_empty_list():
    out = apply_v2_defaults({"execution_mode": "manual"})
    assert out["last_halt"] is None
    assert out["last_halt_history"] == []


def test_default_timestamps_and_drafts_are_null():
    out = apply_v2_defaults({"execution_mode": "manual"})
    assert out["execute_attempt_started_at"] is None
    assert out["plan_finalized_at"] is None
    assert out["draft_verification"] is None
    assert out["draft_allowed_paths"] is None


def test_apply_v2_defaults_returns_new_dict():
    state = {"execution_mode": "manual"}
    out = apply_v2_defaults(state)
    assert out is not state
    assert "last_halt_history" not in state


def test_apply_v2_defaults_is_idempotent():
    state = coerce_legacy_execution_mode({"automation_mode": "chain"})
    once = apply_v2_defaults(state)
    twice = apply_v2_defaults(once)
    assert twice == once


def test_last_halt_history_cap_at_five_entries_documented():
    """The cap is enforced by writers (not the default helper) — but the
    schema contract is that the field is an array, capped at 5 elements.

    This test pins the contract that `last_halt_history` defaults to an
    *empty* list; growth + capping is the writer's responsibility (S11).
    """
    out = apply_v2_defaults({"execution_mode": "manual"})
    assert isinstance(out["last_halt_history"], list)
    assert out["last_halt_history"] == []
