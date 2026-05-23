"""T13 NEW-5 — `phase set done` from `done` idempotent-noop vs divergent state.

Spec (v095-PLAN.md §3.8, v095-IMPL.md T13):
  - done → done with byte-identical valid done shape:
      rc=0, advisory printed, audit verb == "phase.set.idempotent-noop",
      state file UNCHANGED (no timestamp mutation).
  - done → done where on-disk state is divergent (missing required done fields):
      rc != 0 (refuse).

These tests call `cmd_phase_set` directly (no subprocess) using a
synthesised args namespace and a tmp_path fixture root.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_DONE_STATE = {
    "phase": "done",
    "state_schema_version": 2,
    "automation_mode": "manual",
    "execution_mode": "manual",
    "approved": False,
    "updated_at": "2026-05-21T00:00:00Z",
    "updated_by": "test-agent",
    "plan_id": "test-plan-001",
    "state_path": ".planning/STATE.md",
    "plan_path": ".planning/milestones/01/01-PLAN.md",
    "checkpoint_path": ".planning/milestones/01/01-CHECKPOINTS.md",
    "current_checkpoint": "final",
    "next_action": "harness phase reopen --to discuss",
    "auto_selected": [],
    "verification": ["pytest -q"],
}


def _write_state(state_path: Path, state: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _make_args(**kwargs) -> types.SimpleNamespace:
    defaults = {
        "phase": "done",
        "plan_id": None,
        "summary": None,
        "stdin_json": False,
        "reset_approval": False,
    }
    defaults.update(kwargs)
    return types.SimpleNamespace(**defaults)


def _read_audit_entries(audit_path: Path) -> list[dict]:
    if not audit_path.exists():
        return []
    entries = []
    for line in audit_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries


# ---------------------------------------------------------------------------
# Test: byte-identical valid done → rc=0, advisory, idempotent-noop verb
# ---------------------------------------------------------------------------


def test_done_idempotent_noop_rc_zero(tmp_path, monkeypatch, capsys):
    """phase set done from a valid done state → rc=0 + advisory message."""
    monkeypatch.chdir(tmp_path)

    # Setup harness dirs
    (tmp_path / ".harness").mkdir()
    state_path = tmp_path / ".scratch" / "phase-state.json"
    _write_state(state_path, _VALID_DONE_STATE)

    # Patch HARNESS_USER so identity doesn't require git
    monkeypatch.setenv("HARNESS_USER", "test-agent")

    from lib.phase_cli import cmd_phase_set  # type: ignore[import]

    args = _make_args(phase="done")
    rc = cmd_phase_set(args)
    assert rc == 0, f"Expected rc=0 for done→done idempotent noop; got {rc}"


def test_done_idempotent_noop_advisory_printed(tmp_path, monkeypatch, capsys):
    """phase set done from valid done → prints '(already done; no change)' advisory."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".harness").mkdir()
    state_path = tmp_path / ".scratch" / "phase-state.json"
    _write_state(state_path, _VALID_DONE_STATE)
    monkeypatch.setenv("HARNESS_USER", "test-agent")

    from lib.phase_cli import cmd_phase_set  # type: ignore[import]

    args = _make_args(phase="done")
    cmd_phase_set(args)

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "already done" in combined or "no change" in combined, (
        f"Expected advisory text in output; got:\nstdout={captured.out}\nstderr={captured.err}"
    )


def test_done_idempotent_noop_audit_verb(tmp_path, monkeypatch):
    """phase set done from valid done → audit log contains phase.set.idempotent-noop."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".harness").mkdir()
    state_path = tmp_path / ".scratch" / "phase-state.json"
    _write_state(state_path, _VALID_DONE_STATE)
    monkeypatch.setenv("HARNESS_USER", "test-agent")

    from lib.phase_cli import cmd_phase_set  # type: ignore[import]

    args = _make_args(phase="done")
    cmd_phase_set(args)

    audit_path = tmp_path / ".harness" / "audit.log"
    entries = _read_audit_entries(audit_path)
    verbs = [e.get("verb") for e in entries]
    assert "phase.set.idempotent-noop" in verbs, (
        f"Expected 'phase.set.idempotent-noop' verb in audit log; got verbs={verbs}"
    )


def test_done_idempotent_noop_state_unchanged(tmp_path, monkeypatch):
    """phase set done from valid done → state file MUST NOT be mutated (no timestamp update)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".harness").mkdir()
    state_path = tmp_path / ".scratch" / "phase-state.json"
    _write_state(state_path, _VALID_DONE_STATE)

    before_bytes = state_path.read_bytes()
    monkeypatch.setenv("HARNESS_USER", "test-agent")

    from lib.phase_cli import cmd_phase_set  # type: ignore[import]

    args = _make_args(phase="done")
    cmd_phase_set(args)

    after_bytes = state_path.read_bytes()
    assert before_bytes == after_bytes, (
        "State file must not be mutated on done→done idempotent noop; "
        f"bytes changed from {len(before_bytes)} to {len(after_bytes)}"
    )


# ---------------------------------------------------------------------------
# Test: divergent done state → rc != 0
# ---------------------------------------------------------------------------


def test_done_divergent_state_rc_nonzero(tmp_path, monkeypatch):
    """phase set done from divergent done state (missing required field) → rc != 0."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".harness").mkdir()

    # Divergent: phase=done but plan_id missing (required done field)
    divergent_state = dict(_VALID_DONE_STATE)
    del divergent_state["plan_id"]  # remove required field

    state_path = tmp_path / ".scratch" / "phase-state.json"
    _write_state(state_path, divergent_state)
    monkeypatch.setenv("HARNESS_USER", "test-agent")

    from lib.phase_cli import cmd_phase_set  # type: ignore[import]

    args = _make_args(phase="done")
    rc = cmd_phase_set(args)
    assert rc != 0, (
        f"Expected non-zero rc for done→done with divergent state; got rc={rc}"
    )


def test_done_divergent_state_error_message(tmp_path, monkeypatch, capsys):
    """phase set done from divergent state → error message names the divergence."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".harness").mkdir()

    divergent_state = dict(_VALID_DONE_STATE)
    del divergent_state["plan_id"]

    state_path = tmp_path / ".scratch" / "phase-state.json"
    _write_state(state_path, divergent_state)
    monkeypatch.setenv("HARNESS_USER", "test-agent")

    from lib.phase_cli import cmd_phase_set  # type: ignore[import]

    args = _make_args(phase="done")
    cmd_phase_set(args)

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    # Should mention "divergent" or "inconsistent" or "done" in an error context
    assert "divergent" in combined.lower() or "inconsistent" in combined.lower() or "error" in combined.lower(), (
        f"Expected error message for divergent done state; got:\n{combined}"
    )
