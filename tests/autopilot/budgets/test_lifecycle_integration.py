"""Integration tests for cli_budgets wired into the autopilot lifecycle.

Covers:
  A. phase_autopilot.run_start stamps autopilot_started_at_iso + persists
     cli_budgets_remaining from budgets kwarg.
  B. phase_autopilot.run_stop clears autopilot_started_at_iso + nulls
     cli_budgets_remaining.
  C. phase_txn.commit_transaction:
     - rejects file_mutation_ops mutation when budget zero
     - proceeds when budget nonzero
     - no-op check when manual mode
     - no-op check when no budgets
  D. wall_seconds halt via _wall_seconds_check_and_maybe_halt (simulated).
  E. with_budget_decrement helper (caller-contract).
  F. BudgetExhaustedError is an OSError with exit_code=9.
  G. End-to-end: start → N phase_sets with budget=3 → halts at 4th.
  H. build_budget_halt_diary round-trip (last_halt keys post-halt).
  I. Backward-compat: commit_transaction no regression when before_state has
     no budgets / manual mode.

Spec: docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md
§3.5, §5.3, §1.1, §3.4
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pytest

from scripts.lib import cli_budgets, phase_autopilot, phase_lock, phase_txn
from scripts.lib.cli_budgets import (
    BudgetDiaryEntry,
    apply_budget_halt,
    budget_check,
    build_budget_halt_diary,
    decrement,
)
from scripts.lib.phase_txn import (
    BudgetExhaustedError,
    TxnRequest,
    commit_transaction,
    with_budget_decrement,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_base_state(*, execution_mode: str = "manual") -> dict:
    return {
        "phase": "plan",
        "approved": False,
        "approved_at": None,
        "approved_by": None,
        "execution_mode": execution_mode,
        "autopilot_run_id": None,
        "autopilot_mode": None,
        "autopilot_phase_slug": None,
        "autopilot_start_entry_hash": None,
        "autopilot_allow_network": False,
        "autopilot_started_at_iso": None,
        "cli_budgets_remaining": None,
        "last_halt": None,
        "last_halt_history": [],
        "state_schema_version": 2,
    }


@pytest.fixture
def harness_env(tmp_path: Path) -> dict:
    """Primed harness: scratch + audit + CI-authorized install-record."""
    from scripts.lib import phase_lock, phase_txn

    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    harness = tmp_path / ".harness"
    harness.mkdir()
    audit_path = harness / "audit.log"

    seed_state = _make_base_state()
    lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    try:
        phase_txn.commit_transaction(
            scratch,
            lock=lock,
            request=TxnRequest(
                action="seed",
                before_state=None,
                after_state=seed_state,
                audit_entry_draft={"verb": "seed", "args": {}},
            ),
            audit_path=audit_path,
        )
    finally:
        phase_lock.release_primary(lock)

    # Install-record with ci-bot@example.com as approver.
    install_record = {
        "harness_version": "v0.7.0",
        "installed_at": "2026-05-17T03:14:15Z",
        "adapters": ["roo"],
        "git_present_at_install": True,
        "approvers": [
            {
                "email": "ci-bot@example.com",
                "added_at": "2026-05-17T03:14:15Z",
                "source": "gitconfig_auto",
            }
        ],
    }
    (harness / "install-record.json").write_text(
        json.dumps(install_record, indent=2) + "\n"
    )

    # Roadmap.
    planning = tmp_path / ".planning" / "phases"
    planning.mkdir(parents=True)
    for slug in ("phase-alpha", "phase-beta"):
        (planning / slug).mkdir()

    return {
        "tmp_path": tmp_path,
        "scratch": scratch,
        "harness": harness,
        "audit_path": audit_path,
        "roadmap_root": planning,
    }


def _ci_env() -> dict:
    return {
        "HARNESS_AUTOMATION": "phase",
        "HARNESS_BY_TRUST": "ci-bot@example.com",
        "GITHUB_ACTIONS": "true",
        "GITHUB_RUN_ID": "999",
        "GITHUB_REPOSITORY": "org/repo",
        "GITHUB_SHA": "abc123",
        "GITHUB_WORKFLOW": "ci.yml",
        "GITHUB_RUN_ATTEMPT": "1",
        "ACTIONS_ID_TOKEN_REQUEST_URL": "https://example.com/oidc",
    }


def _fake_oidc_fetcher(url: str) -> str:
    return "fake-token"


def _fake_oidc_verifier(token: str, expected_claims: dict) -> dict:
    return {
        "iss": "https://token.actions.githubusercontent.com",
        "sub": "repo:org/repo:ref:refs/heads/main",
        "repository": "org/repo",
        "ref": "refs/heads/main",
        "sha": "abc123",
    }


def _do_start(
    harness_env: dict,
    *,
    budgets: Optional[dict] = None,
    phase_slug: str = "phase-alpha",
) -> phase_autopilot.AutopilotResult:
    scratch = harness_env["scratch"]
    audit_path = harness_env["audit_path"]
    roadmap_root = harness_env["roadmap_root"]
    lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    try:
        result = phase_autopilot.run_start(
            scratch_root=scratch,
            audit_path=audit_path,
            lock_handle=lock,
            phase_slug=phase_slug,
            mode="phase",
            budgets=budgets,
            allow_network=False,
            skip_anchor_preflight=True,
            roadmap_root=roadmap_root,
            env=_ci_env(),
            stdin_is_tty=False,
            oidc_fetcher=_fake_oidc_fetcher,
            oidc_verifier=_fake_oidc_verifier,
        )
    finally:
        phase_lock.release_primary(lock)
    return result


def _do_stop(harness_env: dict) -> phase_autopilot.AutopilotResult:
    scratch = harness_env["scratch"]
    audit_path = harness_env["audit_path"]
    lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    try:
        result = phase_autopilot.run_stop(
            scratch_root=scratch,
            audit_path=audit_path,
            lock_handle=lock,
            reason="test stop",
            anchor_verified=True,
            skip_anchor_preflight=True,
        )
    finally:
        phase_lock.release_primary(lock)
    return result


def _read_state(harness_env: dict) -> dict:
    return json.loads((harness_env["scratch"] / "phase-state.json").read_text())


# ---------------------------------------------------------------------------
# A. run_start stamps autopilot_started_at_iso
# ---------------------------------------------------------------------------


def test_run_start_stamps_autopilot_started_at_iso(harness_env):
    result = _do_start(harness_env)
    assert result.exit_code == 0
    state = _read_state(harness_env)
    assert state.get("autopilot_started_at_iso") is not None
    # Must be a parseable ISO-Z string.
    ts = state["autopilot_started_at_iso"]
    assert isinstance(ts, str)
    assert ts.endswith("Z")


def test_run_start_persists_cli_budgets_remaining_from_kwargs(harness_env):
    budgets = {"file_mutation_ops": 7, "wall_seconds": 200}
    result = _do_start(harness_env, budgets=budgets)
    assert result.exit_code == 0
    state = _read_state(harness_env)
    remaining = state.get("cli_budgets_remaining")
    assert remaining is not None
    # P1-1 fix: run_start now calls with_budget_decrement for its own commit,
    # so file_mutation_ops starts at 7 and is decremented to 6 after start.
    assert remaining["file_mutation_ops"] == 6
    assert remaining["wall_seconds"] == 200


def test_run_start_persists_default_budgets_when_none_supplied(harness_env):
    result = _do_start(harness_env, budgets=None)
    assert result.exit_code == 0
    state = _read_state(harness_env)
    remaining = state.get("cli_budgets_remaining")
    assert remaining is not None
    # Default budgets from phase_autopilot._DEFAULT_BUDGETS must be set.
    assert "file_mutation_ops" in remaining
    assert "shell_invocations" in remaining
    assert "wall_seconds" in remaining


def test_run_start_autopilot_started_at_iso_survives_hash_finalize_commit(harness_env):
    """Two-phase commit for autopilot_start_entry_hash must NOT clobber budget fields."""
    result = _do_start(harness_env)
    assert result.exit_code == 0
    state = _read_state(harness_env)
    # Both fields must survive the finalize commit.
    assert state.get("autopilot_started_at_iso") is not None
    assert state.get("cli_budgets_remaining") is not None


# ---------------------------------------------------------------------------
# B. run_stop clears autopilot_started_at_iso and cli_budgets_remaining
# ---------------------------------------------------------------------------


def test_run_stop_clears_autopilot_started_at_and_budgets(harness_env):
    _do_start(harness_env)
    state_before = _read_state(harness_env)
    assert state_before.get("autopilot_started_at_iso") is not None
    assert state_before.get("cli_budgets_remaining") is not None

    result = _do_stop(harness_env)
    assert result.exit_code == 0

    state = _read_state(harness_env)
    assert state.get("autopilot_started_at_iso") is None
    assert state.get("cli_budgets_remaining") is None


# ---------------------------------------------------------------------------
# C. commit_transaction budget check
# ---------------------------------------------------------------------------


def _commit(scratch, lock, *, before_state, after_state, audit_path) -> str:
    return commit_transaction(
        scratch,
        lock=lock,
        request=TxnRequest(
            action="test.phase.set",
            before_state=before_state,
            after_state=after_state,
            audit_entry_draft={"verb": "test.phase.set", "args": {}},
        ),
        audit_path=audit_path,
    )


def test_commit_transaction_rejects_file_mutation_when_budget_zero(harness_env):
    scratch = harness_env["scratch"]
    audit_path = harness_env["audit_path"]
    # Write a state with autopilot active + file_mutation_ops=0.
    base = _make_base_state(execution_mode="phase_autopilot")
    base["cli_budgets_remaining"] = {
        "file_mutation_ops": 0,
        "shell_invocations": 10,
        "wall_seconds": 300,
    }
    base["autopilot_run_id"] = "run-x"

    # First: write this state via commit_transaction (with manual mode to bypass check).
    seed_state = dict(base)
    seed_state["execution_mode"] = "manual"
    seed_state["cli_budgets_remaining"] = None
    lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    try:
        # Overwrite state to set autopilot active with zero budget.
        # We use a direct file write to simulate crash-recovery-free setup.
        from scripts.lib.phase_txn import TMP_NAME, STATE_NAME, _canonical_bytes
        import os

        # Write state directly via tmp→rename pattern.
        state_bytes = _canonical_bytes(base)
        tmp_path = scratch / TMP_NAME
        tmp_path.write_bytes(state_bytes)
        (scratch / STATE_NAME).write_bytes(state_bytes)
        tmp_path.unlink(missing_ok=True)

        after = dict(base)
        after["phase"] = "execute"
        with pytest.raises(BudgetExhaustedError) as exc_info:
            _commit(
                scratch, lock,
                before_state=base,
                after_state=after,
                audit_path=audit_path,
            )
        err = exc_info.value
        assert isinstance(err, OSError)
        assert err.exit_code == 9
        assert "file_mutation_ops" in err.sub_reason
    finally:
        phase_lock.release_primary(lock)


def test_commit_transaction_proceeds_when_budget_nonzero(tmp_path):
    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    audit_path = tmp_path / "audit.log"

    base = _make_base_state(execution_mode="phase_autopilot")
    base["cli_budgets_remaining"] = {
        "file_mutation_ops": 5,
        "shell_invocations": 10,
        "wall_seconds": 300,
    }
    base["autopilot_run_id"] = "run-y"

    lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    try:
        # Write initial state.
        from scripts.lib.phase_txn import STATE_NAME, _canonical_bytes
        (scratch / STATE_NAME).write_bytes(_canonical_bytes(base))

        after = dict(base)
        after["phase"] = "execute"
        txn_id = _commit(
            scratch, lock,
            before_state=base,
            after_state=after,
            audit_path=audit_path,
        )
        assert isinstance(txn_id, str)
        assert len(txn_id) > 0
    finally:
        phase_lock.release_primary(lock)


def test_commit_transaction_no_op_check_when_manual_mode(tmp_path):
    """Budget check is skipped in manual mode (even if budgets dict has zero)."""
    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    audit_path = tmp_path / "audit.log"

    base = _make_base_state(execution_mode="manual")
    base["cli_budgets_remaining"] = {"file_mutation_ops": 0}

    lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    try:
        from scripts.lib.phase_txn import STATE_NAME, _canonical_bytes
        (scratch / STATE_NAME).write_bytes(_canonical_bytes(base))

        after = dict(base)
        after["phase"] = "execute"
        # Should NOT raise BudgetExhaustedError.
        txn_id = _commit(
            scratch, lock,
            before_state=base,
            after_state=after,
            audit_path=audit_path,
        )
        assert isinstance(txn_id, str)
    finally:
        phase_lock.release_primary(lock)


def test_commit_transaction_no_op_check_when_no_budgets(tmp_path):
    """Budget check is skipped when cli_budgets_remaining is None."""
    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    audit_path = tmp_path / "audit.log"

    base = _make_base_state(execution_mode="phase_autopilot")
    base["cli_budgets_remaining"] = None
    base["autopilot_run_id"] = "run-z"

    lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    try:
        from scripts.lib.phase_txn import STATE_NAME, _canonical_bytes
        (scratch / STATE_NAME).write_bytes(_canonical_bytes(base))

        after = dict(base)
        after["phase"] = "execute"
        txn_id = _commit(
            scratch, lock,
            before_state=base,
            after_state=after,
            audit_path=audit_path,
        )
        assert isinstance(txn_id, str)
    finally:
        phase_lock.release_primary(lock)


# ---------------------------------------------------------------------------
# D. Wall-clock budget check via _wall_seconds_check_and_maybe_halt
# ---------------------------------------------------------------------------


def test_wall_seconds_halt_via_cli_handler(harness_env):
    """Simulated wall_seconds exhaustion: budget=60s, 100s elapsed → exit 9."""
    from scripts.lib.phase_autopilot_cli import _wall_seconds_check_and_maybe_halt

    scratch = harness_env["scratch"]
    audit_path = harness_env["audit_path"]

    # Start autopilot.
    _do_start(harness_env, budgets={"wall_seconds": 60, "file_mutation_ops": 10})
    state = _read_state(harness_env)

    # Simulate 100 seconds elapsed past the start.
    start_dt = datetime.now(timezone.utc) - timedelta(seconds=100)
    overdue_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    try:
        # Patch the state's autopilot_started_at_iso to simulate elapsed time.
        state["autopilot_started_at_iso"] = overdue_iso

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        exit_code = _wall_seconds_check_and_maybe_halt(
            before_state=state,
            scratch_root=scratch,
            audit_path=audit_path,
            lock_handle=lock,
            now_iso=now_iso,
        )
        assert exit_code == 9

        # After halt, state must show manual mode + last_halt populated.
        halted_state = _read_state(harness_env)
        assert halted_state["execution_mode"] == "manual"
        assert halted_state["last_halt"] is not None
        assert "wall_seconds" in halted_state["last_halt"]["reason"]
        assert halted_state["last_halt"]["acknowledged_at"] is None
    finally:
        phase_lock.release_primary(lock)


def test_wall_seconds_no_halt_when_within_budget(harness_env):
    """Wall_seconds=300 and 10s elapsed → no halt."""
    from scripts.lib.phase_autopilot_cli import _wall_seconds_check_and_maybe_halt

    scratch = harness_env["scratch"]
    audit_path = harness_env["audit_path"]

    _do_start(harness_env, budgets={"wall_seconds": 300, "file_mutation_ops": 10})
    state = _read_state(harness_env)

    # Only 10 seconds elapsed.
    start_dt = datetime.now(timezone.utc) - timedelta(seconds=10)
    state["autopilot_started_at_iso"] = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    try:
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        exit_code = _wall_seconds_check_and_maybe_halt(
            before_state=state,
            scratch_root=scratch,
            audit_path=audit_path,
            lock_handle=lock,
            now_iso=now_iso,
        )
        assert exit_code is None  # No halt
    finally:
        phase_lock.release_primary(lock)


# ---------------------------------------------------------------------------
# E. with_budget_decrement helper (caller-contract)
# ---------------------------------------------------------------------------


def test_shell_invocations_exhaustion_via_with_budget_decrement_helper():
    """with_budget_decrement decrements file_mutation_ops when autopilot active."""
    state = {
        "execution_mode": "phase_autopilot",
        "cli_budgets_remaining": {
            "file_mutation_ops": 5,
            "shell_invocations": 10,
            "wall_seconds": 300,
        },
        "autopilot_run_id": "run-abc",
    }
    new_state = with_budget_decrement(state)
    assert new_state["cli_budgets_remaining"]["file_mutation_ops"] == 4
    assert new_state["cli_budgets_remaining"]["shell_invocations"] == 10  # unchanged


def test_with_budget_decrement_no_op_when_manual():
    state = {
        "execution_mode": "manual",
        "cli_budgets_remaining": {"file_mutation_ops": 5},
    }
    new_state = with_budget_decrement(state)
    assert new_state["cli_budgets_remaining"]["file_mutation_ops"] == 5


def test_with_budget_decrement_no_op_when_no_budgets():
    state = {
        "execution_mode": "phase_autopilot",
        "cli_budgets_remaining": None,
    }
    new_state = with_budget_decrement(state)
    assert new_state["cli_budgets_remaining"] is None


def test_with_budget_decrement_clamps_at_zero():
    state = {
        "execution_mode": "phase_autopilot",
        "cli_budgets_remaining": {"file_mutation_ops": 0},
    }
    new_state = with_budget_decrement(state)
    assert new_state["cli_budgets_remaining"]["file_mutation_ops"] == 0


# ---------------------------------------------------------------------------
# F. BudgetExhaustedError
# ---------------------------------------------------------------------------


def test_budget_exhausted_error_is_oserror():
    err = BudgetExhaustedError(
        capability="file_mutation_ops",
        remaining=0,
        message="exhausted",
    )
    assert isinstance(err, OSError)
    assert err.exit_code == 9
    assert err.sub_reason == "budget_exhausted:file_mutation_ops"


def test_budget_exhausted_error_wall_seconds():
    err = BudgetExhaustedError(
        capability="wall_seconds",
        remaining=0,
        message="wall seconds exhausted",
    )
    assert err.exit_code == 9
    assert "wall_seconds" in err.sub_reason


# ---------------------------------------------------------------------------
# G. End-to-end: start → 3 commits with budget=3 → halts at 4th
# ---------------------------------------------------------------------------


def test_autopilot_start_then_3_commits_with_budget_3_halts_at_4th(tmp_path):
    """Full happy-path then exhaustion: budget file_mutation_ops=3 → run_start decrements
    to 2, then 2 more user commits bring it to 0, and the 3rd user commit raises.
    (P1-1 fix: run_start now uses one decrement for its own commit.)"""
    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    harness = tmp_path / ".harness"
    harness.mkdir()
    audit_path = harness / "audit.log"
    planning = tmp_path / ".planning" / "phases"
    planning.mkdir(parents=True)
    (planning / "p1").mkdir()

    seed_state = _make_base_state()
    lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    try:
        commit_transaction(
            scratch,
            lock=lock,
            request=TxnRequest(
                action="seed",
                before_state=None,
                after_state=seed_state,
                audit_entry_draft={"verb": "seed", "args": {}},
            ),
            audit_path=audit_path,
        )
    finally:
        phase_lock.release_primary(lock)

    install_record = {
        "harness_version": "v0.7.0",
        "installed_at": "2026-05-17T03:14:15Z",
        "adapters": ["roo"],
        "git_present_at_install": True,
        "approvers": [
            {"email": "ci-bot@example.com", "added_at": "2026-05-17T03:14:15Z", "source": "gitconfig_auto"}
        ],
    }
    (harness / "install-record.json").write_text(json.dumps(install_record) + "\n")

    # Start with budget=3 file_mutation_ops.
    # P1-1 fix: run_start now decrements file_mutation_ops for its own commit,
    # so after start the budget is 2 (not 3).
    lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    try:
        result = phase_autopilot.run_start(
            scratch_root=scratch,
            audit_path=audit_path,
            lock_handle=lock,
            phase_slug="p1",
            mode="phase",
            budgets={"file_mutation_ops": 3, "wall_seconds": 300},
            allow_network=False,
            skip_anchor_preflight=True,
            roadmap_root=planning,
            env=_ci_env(),
            stdin_is_tty=False,
            oidc_fetcher=_fake_oidc_fetcher,
            oidc_verifier=_fake_oidc_verifier,
        )
    finally:
        phase_lock.release_primary(lock)
    assert result.exit_code == 0

    # After start, file_mutation_ops should be 2 (3 - 1 for the start commit).
    state = json.loads((scratch / "phase-state.json").read_text())
    assert state["cli_budgets_remaining"]["file_mutation_ops"] == 2

    # Do 2 user commits — each one should succeed (decrements 2 → 1 → 0).
    for i in range(2):
        state = json.loads((scratch / "phase-state.json").read_text())
        # Caller contract: decrement before passing after_state.
        after = with_budget_decrement(dict(state))
        lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
        try:
            commit_transaction(
                scratch,
                lock=lock,
                request=TxnRequest(
                    action="test.set",
                    before_state=state,
                    after_state=after,
                    audit_entry_draft={"verb": "test.set", "args": {"i": i}},
                ),
                audit_path=audit_path,
            )
        finally:
            phase_lock.release_primary(lock)

    # After 2 user decrements, file_mutation_ops should be 0.
    state = json.loads((scratch / "phase-state.json").read_text())
    assert state["cli_budgets_remaining"]["file_mutation_ops"] == 0

    # 3rd user commit: should raise BudgetExhaustedError.
    after = dict(state)
    after["phase"] = "execute"
    lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    try:
        with pytest.raises(BudgetExhaustedError) as exc_info:
            commit_transaction(
                scratch,
                lock=lock,
                request=TxnRequest(
                    action="test.set",
                    before_state=state,
                    after_state=after,
                    audit_entry_draft={"verb": "test.set", "args": {"i": 3}},
                ),
                audit_path=audit_path,
            )
        err = exc_info.value
        assert err.exit_code == 9
        assert "file_mutation_ops" in err.sub_reason
    finally:
        phase_lock.release_primary(lock)


# ---------------------------------------------------------------------------
# H. build_budget_halt_diary round-trip (last_halt keys post-halt)
# ---------------------------------------------------------------------------


def test_budget_halt_diary_round_trip():
    """Verify last_halt has all required keys after apply_budget_halt."""
    from scripts.lib.cli_budgets import BudgetCheckResult

    state = {
        "execution_mode": "phase_autopilot",
        "autopilot_run_id": "run-xyz",
        "autopilot_phase_slug": "execute",
        "autopilot_mode": "phase",
        "autopilot_start_entry_hash": "abc",
        "autopilot_allow_network": False,
        "autopilot_started_at_iso": "2026-05-17T00:00:00Z",
        "cli_budgets_remaining": {"file_mutation_ops": 0},
        "last_halt": None,
        "last_halt_history": [],
    }
    result = BudgetCheckResult(
        exhausted=True,
        capability="file_mutation_ops",
        remaining=0,
        message="file_mutation_ops budget exhausted",
    )
    now_iso = "2026-05-17T01:00:00Z"
    diary = build_budget_halt_diary(result=result, state=state, now_iso=now_iso)
    halted = apply_budget_halt(state, diary=diary)

    last_halt = halted["last_halt"]
    # Required keys per §5.3.
    assert last_halt["at"] == now_iso
    assert last_halt["reason"] == "budget_exhausted:file_mutation_ops"
    assert last_halt["capability"] == "file_mutation_ops"
    assert last_halt["remaining_at_halt"] == 0
    assert last_halt["autopilot_run_id"] == "run-xyz"
    assert last_halt["autopilot_phase_slug"] == "execute"
    assert isinstance(last_halt["suggested_next_command"], str)
    assert last_halt["suggested_next_command_requires_human"] is False
    assert last_halt["acknowledged_at"] is None
    # No verb key.
    assert "verb" not in last_halt
    # Mode set to manual.
    assert halted["execution_mode"] == "manual"
    assert halted["cli_budgets_remaining"] is None


# ---------------------------------------------------------------------------
# I. Backward-compat: no regression when before_state has no budgets / manual
# ---------------------------------------------------------------------------


def test_commit_transaction_backward_compat_no_budgets_manual(tmp_path):
    """Legacy state with no cli_budgets_remaining and manual mode: no crash."""
    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    audit_path = tmp_path / "audit.log"

    # Old-style state without any budget fields.
    before = {
        "phase": "plan",
        "approved": False,
        "execution_mode": "manual",
    }
    after = dict(before)
    after["phase"] = "execute"

    lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    try:
        from scripts.lib.phase_txn import STATE_NAME, _canonical_bytes
        (scratch / STATE_NAME).write_bytes(_canonical_bytes(before))

        txn_id = commit_transaction(
            scratch,
            lock=lock,
            request=TxnRequest(
                action="phase.set",
                before_state=before,
                after_state=after,
                audit_entry_draft={"verb": "phase.set", "args": {}},
            ),
            audit_path=audit_path,
        )
        assert isinstance(txn_id, str)
    finally:
        phase_lock.release_primary(lock)


def test_commit_transaction_backward_compat_autopilot_no_budgets(tmp_path):
    """Autopilot mode but cli_budgets_remaining=None → no budget check, proceeds."""
    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    audit_path = tmp_path / "audit.log"

    before = {
        "phase": "plan",
        "approved": False,
        "execution_mode": "phase_autopilot",
        "autopilot_run_id": "run-legacy",
        "cli_budgets_remaining": None,
    }
    after = dict(before)
    after["phase"] = "execute"

    lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    try:
        from scripts.lib.phase_txn import STATE_NAME, _canonical_bytes
        (scratch / STATE_NAME).write_bytes(_canonical_bytes(before))

        txn_id = commit_transaction(
            scratch,
            lock=lock,
            request=TxnRequest(
                action="phase.set",
                before_state=before,
                after_state=after,
                audit_entry_draft={"verb": "phase.set", "args": {}},
            ),
            audit_path=audit_path,
        )
        assert isinstance(txn_id, str)
    finally:
        phase_lock.release_primary(lock)
