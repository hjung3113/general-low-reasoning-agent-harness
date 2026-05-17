"""S01-A.2: integration of phase_state v2 schema into the migrator + checker.

Wires `coerce_legacy_execution_mode` + `apply_v2_defaults` into the live
`state_migrate.forward` path so that any v0/v0.6.1/v0.7-legacy phase-state
file is brought to the full v2 shape on migration. Reverse strips the
v2-only fields so that the round-trip property `reverse(forward(s)) == s`
continues to hold.

Per design §1.1 + §1.2 + §12.15
(`docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md`).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import state_migrate
from lib.phase_state import (
    EXECUTION_MODES,
    NEW_V2_FIELDS,
    strip_v2_only_fields,
)


# ---------------------------------------------------------------------------
# Forward integration — every legacy shape lands at a full v2 record.
# ---------------------------------------------------------------------------


def _minimal_v0(**overrides: object) -> dict:
    """Minimal v0 phase-state shape sufficient for forward() to succeed.

    Includes an empty `verification` list because pre-existing T0-4 logic
    inside `forward()` unconditionally writes `verification` to the output,
    so the round-trip property requires the input to carry it too.
    """
    base = {
        "phase": "discuss",
        "approved": False,
        "auto_selected": [],
        "verification": [],
        "updated_at": "2026-05-15T00:00:00Z",
        "updated_by": "test",
    }
    base.update(overrides)
    return base


def test_forward_v061_both_absent_yields_execution_mode_manual():
    v0 = _minimal_v0()  # no automation_mode, no execution_mode
    v2 = state_migrate.forward(v0)
    assert v2["execution_mode"] == "manual"


def test_forward_legacy_automation_chain_maps_to_phase_autopilot():
    v0 = _minimal_v0(automation_mode="chain")
    v2 = state_migrate.forward(v0)
    assert v2["execution_mode"] == "phase_autopilot"
    # Legacy alias is preserved on the wire so older readers can still parse.
    assert v2["automation_mode"] == "chain"


def test_forward_legacy_automation_auto_maps_to_chain_autopilot():
    v0 = _minimal_v0(automation_mode="auto")
    v2 = state_migrate.forward(v0)
    assert v2["execution_mode"] == "chain_autopilot"


def test_forward_legacy_automation_manual_maps_to_manual():
    v0 = _minimal_v0(automation_mode="manual")
    v2 = state_migrate.forward(v0)
    assert v2["execution_mode"] == "manual"


def test_forward_populates_every_new_v2_default_field():
    v0 = _minimal_v0()
    v2 = state_migrate.forward(v0)
    for key, expected in NEW_V2_FIELDS.items():
        assert key in v2, f"forward dropped: {key}"
        if isinstance(expected, list):
            assert v2[key] == expected
        elif key != "execution_mode":  # execution_mode value depends on legacy
            assert v2[key] == expected


def test_forward_is_idempotent_with_new_fields():
    v0 = _minimal_v0(automation_mode="chain")
    once = state_migrate.forward(v0)
    twice = state_migrate.forward(once)
    assert once == twice


def test_forward_execution_mode_is_inside_enum():
    for legacy in ("manual", "chain", "auto"):
        v0 = _minimal_v0(automation_mode=legacy)
        v2 = state_migrate.forward(v0)
        assert v2["execution_mode"] in EXECUTION_MODES


# ---------------------------------------------------------------------------
# Reverse integration — v2-only fields are stripped on reverse.
# ---------------------------------------------------------------------------


def test_reverse_strips_every_new_v2_field():
    v0 = _minimal_v0(automation_mode="chain")
    v2 = state_migrate.forward(v0)
    rev = state_migrate.reverse(v2)
    for key in NEW_V2_FIELDS:
        assert key not in rev, f"reverse failed to strip: {key}"


def test_reverse_preserves_legacy_automation_mode():
    v0 = _minimal_v0(automation_mode="chain")
    v2 = state_migrate.forward(v0)
    rev = state_migrate.reverse(v2)
    assert rev["automation_mode"] == "chain"


def test_forward_then_reverse_round_trip_equal_to_input():
    v0 = _minimal_v0(automation_mode="auto")
    assert state_migrate.reverse(state_migrate.forward(v0)) == v0


def test_forward_then_reverse_round_trip_for_v061_input():
    """Both fields absent → forward adds execution_mode=manual → reverse must
    strip it so the round-trip equality holds bytewise."""
    v0 = _minimal_v0()
    rev = state_migrate.reverse(state_migrate.forward(v0))
    assert rev == v0
    assert "execution_mode" not in rev
    assert "automation_mode" not in rev


# ---------------------------------------------------------------------------
# strip_v2_only_fields — pure helper used by reverse().
# ---------------------------------------------------------------------------


def test_strip_v2_only_fields_removes_every_new_field():
    v2_shape = {key: NEW_V2_FIELDS[key] for key in NEW_V2_FIELDS}
    v2_shape["phase"] = "discuss"
    v2_shape["automation_mode"] = "manual"
    stripped = strip_v2_only_fields(v2_shape)
    for key in NEW_V2_FIELDS:
        assert key not in stripped
    # Legacy + non-v2 fields preserved.
    assert stripped["phase"] == "discuss"
    assert stripped["automation_mode"] == "manual"


def test_strip_v2_only_fields_returns_new_dict():
    state = {"execution_mode": "manual", "phase": "discuss"}
    out = strip_v2_only_fields(state)
    assert out is not state
    assert "execution_mode" in state  # input untouched


# ---------------------------------------------------------------------------
# Audit emission — `verb=migrate.state_v2` on content-changing forward.
# ---------------------------------------------------------------------------


def test_migrate_file_forward_emits_state_v2_audit_entry(tmp_path: Path):
    target = tmp_path / "phase-state.json"
    target.write_text(json.dumps(_minimal_v0(automation_mode="chain")) + "\n", encoding="utf-8")
    audit_path = tmp_path / ".harness" / "audit.log"

    state_migrate.migrate_file(
        target,
        direction="forward",
        backups_dir=tmp_path / ".harness" / "backups",
        audit_path=audit_path,
    )

    assert audit_path.exists(), "audit log not created"
    entries = [json.loads(ln) for ln in audit_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    migrate_entries = [e for e in entries if e.get("verb") == "migrate.state_v2"]
    assert len(migrate_entries) == 1, f"expected exactly 1 migrate.state_v2 entry, got {len(migrate_entries)}"
    entry = migrate_entries[0]
    # Per design §1.2: emit before_sha256/after_sha256 to track provenance.
    assert "before_sha256" in entry
    assert "after_sha256" in entry
    assert entry["before_sha256"] != entry["after_sha256"]
    assert len(entry["before_sha256"]) == 64
    assert len(entry["after_sha256"]) == 64


def test_migrate_file_forward_without_audit_path_is_silent(tmp_path: Path):
    """Back-compat: when audit_path is omitted, migrate_file does not crash
    and emits no audit log."""
    target = tmp_path / "phase-state.json"
    target.write_text(json.dumps(_minimal_v0(automation_mode="chain")) + "\n", encoding="utf-8")

    state_migrate.migrate_file(
        target,
        direction="forward",
        backups_dir=tmp_path / ".harness" / "backups",
    )
    # No audit dir created.
    assert not (tmp_path / ".harness" / "audit.log").exists()


def test_migrate_file_forward_noop_does_not_emit_audit_entry(tmp_path: Path):
    """If the on-disk content is already byte-identical to the v2 forward
    output, migrate_file is a no-op and MUST NOT spuriously emit a
    duplicate migrate.state_v2 audit entry."""
    target = tmp_path / "phase-state.json"
    v0 = _minimal_v0(automation_mode="chain")
    v2_bytes = state_migrate.serialize(state_migrate.forward(v0))
    target.write_bytes(v2_bytes)
    audit_path = tmp_path / ".harness" / "audit.log"

    state_migrate.migrate_file(
        target,
        direction="forward",
        backups_dir=tmp_path / ".harness" / "backups",
        audit_path=audit_path,
    )
    # No audit log written for a no-op migration.
    assert not audit_path.exists()


# ---------------------------------------------------------------------------
# Validator extension — check.check_phase_state_semantics accepts both
# execution_mode and the legacy automation_mode (transitional posture).
# ---------------------------------------------------------------------------


def _valid_discuss_state() -> dict:
    """Discuss-phase v2 record that should pass the validator."""
    return {
        "phase": "discuss",
        "approved": False,
        "auto_selected": [],
        "automation_mode": "manual",
        "execution_mode": "manual",
        "state_schema_version": 2,
        "updated_at": "2026-05-15T00:00:00.000000000Z",
        "updated_by": "test",
    }


def test_validator_accepts_execution_mode_manual(tmp_path: Path):
    from lib import check

    target = tmp_path / "state.json"
    target.write_text(json.dumps(_valid_discuss_state()) + "\n", encoding="utf-8")
    check.check_phase_state_semantics(target)  # must not raise


def _auto_selected_entry() -> dict:
    """Single auto_selected entry satisfying check.py's required schema —
    used when automation_mode != manual (legacy validator constraint)."""
    return {
        "choice": "noop",
        "selected_value": "noop",
        "reason": "test fixture",
        "evidence_path": "tests/phase_state/test_state_schema_integration.py",
        "risk_level": "low",
        "reversible": True,
        "inside_allowed_paths": True,
        "stop_conditions_checked": ["none"],
    }


def test_validator_accepts_execution_mode_phase_autopilot(tmp_path: Path):
    from lib import check

    state = _valid_discuss_state()
    state["automation_mode"] = "chain"
    state["auto_selected"] = [_auto_selected_entry()]
    state["execution_mode"] = "phase_autopilot"
    target = tmp_path / "state.json"
    target.write_text(json.dumps(state) + "\n", encoding="utf-8")
    check.check_phase_state_semantics(target)


def test_validator_accepts_execution_mode_chain_autopilot(tmp_path: Path):
    from lib import check

    state = _valid_discuss_state()
    state["automation_mode"] = "auto"
    state["auto_selected"] = [_auto_selected_entry()]
    state["execution_mode"] = "chain_autopilot"
    target = tmp_path / "state.json"
    target.write_text(json.dumps(state) + "\n", encoding="utf-8")
    check.check_phase_state_semantics(target)


def test_validator_rejects_unknown_execution_mode(tmp_path: Path):
    from lib import check

    state = _valid_discuss_state()
    state["execution_mode"] = "warp_speed"
    target = tmp_path / "state.json"
    target.write_text(json.dumps(state) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="execution_mode"):
        check.check_phase_state_semantics(target)


def test_validator_tolerates_legacy_only_state_without_execution_mode(tmp_path: Path):
    """A state file that was migrated to schema_v2 in a prior release but
    never had `execution_mode` written (legacy v0.7.0.dev0 row) must still
    pass the checker so the user can run `harness migrate state --forward`
    to upgrade it. Validator merely warns / accepts the absent field."""
    from lib import check

    state = _valid_discuss_state()
    state.pop("execution_mode")
    target = tmp_path / "state.json"
    target.write_text(json.dumps(state) + "\n", encoding="utf-8")
    # Must not raise — back-compat with pre-S01 schema_v2 rows.
    check.check_phase_state_semantics(target)
