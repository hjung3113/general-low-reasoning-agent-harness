"""Review-fix P1-2 regression tests — `plan_finalized_at` and
`execute_attempt_started_at` MUST be produced by the live phase-set
path, not just consumed by the validator.

Design refs:
  - §1.1 (schema fields)
  - §3.6 (stale-approval validator floor)

The reviewer flagged that pre-fix, `validate_transition_with_state`
rejected with `plan_finalized_at_missing` /
`execute_attempt_started_at_missing` on any real-world state because
nothing in `scripts/lib/` ever wrote them. These tests pair the
producer (`phase_state.stamp_transition_timestamps` +
`phase_cli._do_phase_set` wiring) with the consumer
(`transition.validate_transition_with_state`) end-to-end.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from lib import phase_state, transition


# ---------------------------------------------------------------------------
# 1. Pure-helper unit tests (no FS).
# ---------------------------------------------------------------------------


def test_stamp_plan_sets_plan_finalized_at():
    out = phase_state.stamp_transition_timestamps(
        {"phase": "discuss"}, to_phase="plan", now_iso="2026-05-17T12:00:00Z"
    )
    assert out["plan_finalized_at"] == "2026-05-17T12:00:00Z"
    # execute_attempt_started_at is NOT stamped on plan entry.
    assert "execute_attempt_started_at" not in out


def test_stamp_execute_sets_execute_attempt_started_at():
    out = phase_state.stamp_transition_timestamps(
        {"phase": "plan"}, to_phase="execute", now_iso="2026-05-17T13:00:00Z"
    )
    assert out["execute_attempt_started_at"] == "2026-05-17T13:00:00Z"


def test_stamp_other_phases_noop():
    base = {"phase": "execute"}
    for target in ("discuss", "done"):
        out = phase_state.stamp_transition_timestamps(
            base, to_phase=target, now_iso="2026-05-17T14:00:00Z"
        )
        assert "plan_finalized_at" not in out
        assert "execute_attempt_started_at" not in out


def test_stamp_does_not_mutate_input():
    base = {"phase": "discuss"}
    phase_state.stamp_transition_timestamps(
        base, to_phase="plan", now_iso="2026-05-17T12:00:00Z"
    )
    assert "plan_finalized_at" not in base


# ---------------------------------------------------------------------------
# 2. Producer + consumer paired contract — validator accepts post-stamp.
# ---------------------------------------------------------------------------


def test_stamped_state_passes_plan_to_execute_validator():
    """Drive `discuss → plan → execute` through the producer and check
    `validate_transition_with_state` accepts at every step."""
    state = {
        "phase": None,
        "approved": False,
        "verification": ["pytest -q"],
        "allowed_paths": ["src/"],
    }
    # discuss
    state["phase"] = "discuss"
    transition.validate_transition_with_state(
        state, "plan", reset_approval=False
    )

    # → plan
    state = phase_state.stamp_transition_timestamps(
        state, to_phase="plan", now_iso="2026-05-17T11:00:00Z"
    )
    state["phase"] = "plan"
    # Simulate approve: stamp approved_at AFTER plan_finalized_at.
    state["approved"] = True
    state["approved_at"] = "2026-05-17T11:30:00Z"

    # → execute (validator expects plan_finalized_at present + approved_at
    # >= it).
    transition.validate_transition_with_state(
        state, "execute", reset_approval=False
    )

    # Stamp execute_attempt_started_at on entry.
    state = phase_state.stamp_transition_timestamps(
        state, to_phase="execute", now_iso="2026-05-17T12:00:00Z"
    )
    state["phase"] = "execute"

    # Re-approve after execute_attempt_started_at for (execute → done).
    state["approved_at"] = "2026-05-17T12:30:00Z"
    transition.validate_transition_with_state(
        state, "done", reset_approval=False
    )


# ---------------------------------------------------------------------------
# 3. Black-box test: drive cmd_phase_set and observe the live state file.
#
# We chdir into a tmp_path-rooted fake repo, mint the bare scaffolding
# expected by `phase_cli._do_phase_set`, and call the handler directly.
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    """Minimal repo layout where `cmd_phase_set` can write."""
    (tmp_path / ".scratch").mkdir()
    (tmp_path / ".harness").mkdir()
    monkeypatch.chdir(tmp_path)

    # Seed a state file in `discuss` so subsequent transitions are valid.
    seed = {
        "phase": "discuss",
        "approved": False,
        "approved_at": None,
        "approved_by": None,
        "state_schema_version": 2,
        "verification": ["pytest -q"],
        "allowed_paths": ["src/"],
    }
    (tmp_path / ".scratch" / "phase-state.json").write_text(
        json.dumps(seed, indent=2, sort_keys=True) + "\n"
    )
    return tmp_path


def test_live_phase_set_stamps_plan_finalized_at(fake_repo):
    from lib import phase_cli

    class Ns:
        pass

    ns = Ns()
    ns.phase = "plan"
    ns.plan_id = None
    ns.summary = None
    ns.reset_approval = False
    ns.stdin_json = False

    rc = phase_cli._do_phase_set(ns)
    assert rc == 0

    state = json.loads(
        (fake_repo / ".scratch" / "phase-state.json").read_text()
    )
    assert state["phase"] == "plan"
    assert state.get("plan_finalized_at") is not None
    # ISO-Z canonical shape.
    assert state["plan_finalized_at"].endswith("Z")


def test_live_phase_set_stamps_execute_attempt_started_at(fake_repo):
    """Drive discuss → plan → (approve) → execute and assert stamping."""
    from lib import phase_cli

    class Ns:
        pass

    # → plan
    ns = Ns()
    ns.phase = "plan"
    ns.plan_id = None
    ns.summary = None
    ns.reset_approval = False
    ns.stdin_json = False
    assert phase_cli._do_phase_set(ns) == 0

    # Mark approved (use legacy _do_phase_approve so the in-tree handler
    # populates approved_at correctly).
    napp = Ns()
    napp.by = "alice@example.com"
    napp.at = None
    assert phase_cli._do_phase_approve(napp) == 0

    # → execute
    nx = Ns()
    nx.phase = "execute"
    nx.plan_id = None
    nx.summary = None
    nx.reset_approval = False
    nx.stdin_json = False
    assert phase_cli._do_phase_set(nx) == 0

    state = json.loads(
        (fake_repo / ".scratch" / "phase-state.json").read_text()
    )
    assert state["phase"] == "execute"
    assert state.get("execute_attempt_started_at") is not None
    assert state["execute_attempt_started_at"].endswith("Z")


# ---------------------------------------------------------------------------
# 4. xfail-strict integration pin — review-fix P2-1 (cmd_phase_set
# routing through `validate_transition_with_state`).
# Today `cmd_phase_set` still uses the legacy `validate_transition`
# (4-arg signature) — wiring the §3.6 extended validator into the live
# path is S07-prep scope. The xfail-strict pin will fail-as-pass today
# and surface a real failure the moment the wiring lands.
# ---------------------------------------------------------------------------


def test_live_cli_set_routes_through_validate_transition_with_state():
    import inspect

    from lib import phase_cli

    src = inspect.getsource(phase_cli._do_phase_set)
    # Looking for an actual call site, not a code comment. The legacy
    # 4-arg `validate_transition(...)` call must be replaced (or
    # supplemented) by `validate_transition_with_state(...)`.
    assert (
        "validate_transition_with_state(" in src
    ), "expected _do_phase_set to call validate_transition_with_state(...)"
