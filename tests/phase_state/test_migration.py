"""S01-A.1: read-time migration of legacy `automation_mode` → `execution_mode`.

Per design §1.1 + §1.2 (`docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md`):

    automation_mode=manual → execution_mode=manual
    automation_mode=chain  → execution_mode=phase_autopilot
    automation_mode=auto   → execution_mode=chain_autopilot

If both fields are absent (pristine v0.6.1 install) → execution_mode=manual.

These tests cover the pure in-memory coercion only. Filesystem write-back +
`verb=migrate.state_v2` audit emission are S01-A.2 scope.
"""

from __future__ import annotations

import pytest

from lib.phase_state import coerce_legacy_execution_mode


def test_v061_both_absent_defaults_to_manual():
    state = {"phase": "discuss"}
    out = coerce_legacy_execution_mode(state)
    assert out["execution_mode"] == "manual"


def test_legacy_automation_manual_maps_to_manual():
    state = {"automation_mode": "manual", "phase": "discuss"}
    out = coerce_legacy_execution_mode(state)
    assert out["execution_mode"] == "manual"


def test_legacy_automation_chain_maps_to_phase_autopilot():
    state = {"automation_mode": "chain", "phase": "execute"}
    out = coerce_legacy_execution_mode(state)
    assert out["execution_mode"] == "phase_autopilot"


def test_legacy_automation_auto_maps_to_chain_autopilot():
    state = {"automation_mode": "auto", "phase": "execute"}
    out = coerce_legacy_execution_mode(state)
    assert out["execution_mode"] == "chain_autopilot"


def test_explicit_execution_mode_wins_over_legacy_alias():
    """If both fields exist, execution_mode is authoritative (post-migration)."""
    state = {
        "execution_mode": "phase_autopilot",
        "automation_mode": "manual",  # stale alias, should be ignored
    }
    out = coerce_legacy_execution_mode(state)
    assert out["execution_mode"] == "phase_autopilot"


def test_unknown_legacy_automation_mode_rejected():
    """Defensive: an unrecognised legacy value MUST NOT silently default."""
    state = {"automation_mode": "lightspeed"}
    with pytest.raises(ValueError, match="automation_mode"):
        coerce_legacy_execution_mode(state)


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
    assert twice == once


def test_unknown_execution_mode_value_rejected():
    state = {"execution_mode": "warp_speed"}
    with pytest.raises(ValueError, match="execution_mode"):
        coerce_legacy_execution_mode(state)


# ---------------------------------------------------------------------------
# Review-fix (P1, 2026-05-17): explicit-null vs absent distinction.
#
# Per design §1.2: "If `execution_mode` is absent and `automation_mode` is
# present, coerce as ...". Only **absent** triggers the v0.6.1 default path;
# an explicit JSON `null` is an invalid explicit value and MUST fail closed.
# Prior implementation used `.get()` which conflated absence and null.
# ---------------------------------------------------------------------------


def test_explicit_null_execution_mode_rejected():
    """JSON `null` for execution_mode is an invalid explicit value, not absent."""
    state = {"execution_mode": None, "phase": "discuss"}
    with pytest.raises(ValueError, match="execution_mode"):
        coerce_legacy_execution_mode(state)


def test_explicit_null_execution_mode_rejected_even_with_valid_legacy_alias():
    """Explicit null on execution_mode must not be papered over by a legacy alias."""
    state = {"execution_mode": None, "automation_mode": "chain"}
    with pytest.raises(ValueError, match="execution_mode"):
        coerce_legacy_execution_mode(state)


def test_explicit_null_automation_mode_rejected():
    """JSON `null` for automation_mode is an invalid explicit legacy value,
    not the v0.6.1 'both absent' shape — fail closed."""
    state = {"automation_mode": None}
    with pytest.raises(ValueError, match="automation_mode"):
        coerce_legacy_execution_mode(state)
