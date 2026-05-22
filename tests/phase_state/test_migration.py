"""S01-A.1: read-time migration of legacy `automation_mode` → `execution_mode`.

Autopilot modes removed; coerce_legacy_execution_mode now always returns manual.
"""

from __future__ import annotations

from lib.phase_state import coerce_legacy_execution_mode


def test_any_input_yields_manual():
    state = {"phase": "discuss"}
    out = coerce_legacy_execution_mode(state)
    assert out["execution_mode"] == "manual"


def test_coerce_returns_new_dict_not_mutation():
    """Pure function: input dict is not mutated."""
    state = {"automation_mode": "chain"}
    out = coerce_legacy_execution_mode(state)
    assert "execution_mode" not in state
    assert out is not state


def test_coerce_is_idempotent_after_first_pass():
    state = {"automation_mode": "chain"}
    once = coerce_legacy_execution_mode(state)
    twice = coerce_legacy_execution_mode(once)
    assert twice["execution_mode"] == "manual"
