"""S07-prep-autopilot-cli — `phase autopilot start|stop|next-pending` verb tests.

Design refs:
  - §3.5  — `phase autopilot start | stop | next-pending` surface
  - §3.5.2 — Active-autopilot re-entry (exit 15)
  - §3.4  — Exit codes: 11 windows_containment_degraded, 12 git_repo_required,
             15 autopilot_already_active, 2 invalid (phase_slug_not_in_roadmap)
  - §1.1  — State fields: execution_mode, autopilot_run_id, autopilot_mode,
             autopilot_phase_slug, autopilot_start_entry_hash,
             cli_budgets_remaining, autopilot_allow_network

Fault classes asserted:
  - anchor_preflight_unwired         exit 6
  - autopilot_already_active         exit 15
  - windows_containment_degraded     exit 11
  - phase_slug_not_in_roadmap        exit 2
  - git_repo_required                exit 12
  - run_stop idempotent              exit 0
  - run_next_pending pure read       exit 0, no audit row, no state mutation

All tests use dependency injection: `skip_anchor_preflight=True` skips §12.1
trust chain (tested by dedicated anchor tests); `anchor_verified=True` is
passed to state_trust via the autopilot helpers.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from lib import phase_autopilot, phase_lock, phase_txn


# ---------------------------------------------------------------------------
# Shared fixture — primed harness root
# ---------------------------------------------------------------------------


@pytest.fixture
def env(tmp_path: Path) -> dict:
    """Synthesize a primed harness with scratch + audit + roadmap slugs.

    The roadmap is simulated by writing `.planning/phases/<slug>/` dirs and
    individual `phase-state.json` files under each.
    """
    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    harness = tmp_path / ".harness"
    harness.mkdir()
    audit_path = harness / "audit.log"

    # Seed phase-state via commit_transaction so audit tail matches.
    seed_state = {
        "phase": "plan",
        "approved": False,
        "approved_at": None,
        "approved_by": None,
        "execution_mode": "manual",
        "autopilot_run_id": None,
        "autopilot_mode": None,
        "autopilot_phase_slug": None,
        "autopilot_start_entry_hash": None,
        "cli_budgets_remaining": None,
        "autopilot_allow_network": False,
        "last_halt": None,
        "last_halt_history": [],
        "state_schema_version": 2,
    }
    lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    try:
        req = phase_txn.TxnRequest(
            action="phase.set",
            before_state=None,
            after_state=seed_state,
            audit_entry_draft={
                "verb": "phase.set",
                "by": "seed",
                "args": {"phase": "plan"},
            },
        )
        phase_txn.commit_transaction(
            scratch, lock=lock, request=req, audit_path=audit_path
        )
    finally:
        phase_lock.release_primary(lock)

    # Roadmap: two phase directories, first pending, second pending.
    planning = tmp_path / ".planning" / "phases"
    planning.mkdir(parents=True)
    for slug in ("phase-alpha", "phase-beta"):
        (planning / slug).mkdir()
        # Each phase is "not done" by default (no phase-state.json with done).

    return {
        "tmp_path": tmp_path,
        "scratch": scratch,
        "harness": harness,
        "audit_path": audit_path,
        "roadmap_root": planning,
    }


def _start(
    env: dict,
    *,
    phase_slug: str = "phase-alpha",
    mode: str = "phase",
    budgets: dict | None = None,
    allow_network: bool = False,
    authorization_source: str = "cli_tty_human",
    anchor_verified: bool = True,
    skip_anchor_preflight: bool = True,
    accept_degraded_windows_containment: bool = False,
    repo_root: Path | None = None,
) -> phase_autopilot.AutopilotResult:
    lock = phase_lock.acquire_primary(env["scratch"], timeout_s=2.0)
    try:
        return phase_autopilot.run_start(
            scratch_root=env["scratch"],
            audit_path=env["audit_path"],
            lock_handle=lock,
            phase_slug=phase_slug,
            mode=mode,
            budgets=budgets,
            allow_network=allow_network,
            authorization_source=authorization_source,
            anchor_verified=anchor_verified,
            skip_anchor_preflight=skip_anchor_preflight,
            accept_degraded_windows_containment=accept_degraded_windows_containment,
            repo_root=repo_root,
            roadmap_root=env["roadmap_root"],
        )
    finally:
        phase_lock.release_primary(lock)


def _stop(
    env: dict,
    *,
    reason: str = "stopping for test",
    anchor_verified: bool = True,
    skip_anchor_preflight: bool = True,
) -> phase_autopilot.AutopilotResult:
    lock = phase_lock.acquire_primary(env["scratch"], timeout_s=2.0)
    try:
        return phase_autopilot.run_stop(
            scratch_root=env["scratch"],
            audit_path=env["audit_path"],
            lock_handle=lock,
            reason=reason,
            anchor_verified=anchor_verified,
            skip_anchor_preflight=skip_anchor_preflight,
        )
    finally:
        phase_lock.release_primary(lock)


def _next_pending(
    env: dict,
    *,
    anchor_verified: bool = True,
    skip_anchor_preflight: bool = True,
) -> phase_autopilot.NextPendingResult:
    lock = phase_lock.acquire_primary(env["scratch"], timeout_s=2.0)
    try:
        return phase_autopilot.run_next_pending(
            scratch_root=env["scratch"],
            audit_path=env["audit_path"],
            lock_handle=lock,
            anchor_verified=anchor_verified,
            skip_anchor_preflight=skip_anchor_preflight,
            roadmap_root=env["roadmap_root"],
        )
    finally:
        phase_lock.release_primary(lock)


def _read_state(env: dict) -> dict:
    state_path = env["scratch"] / "phase-state.json"
    return json.loads(state_path.read_text(encoding="utf-8"))


def _count_audit_rows(env: dict, verb: str) -> int:
    audit_path = env["audit_path"]
    if not audit_path.exists():
        return 0
    count = 0
    for line in audit_path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            if row.get("verb") == verb:
                count += 1
        except json.JSONDecodeError:
            pass
    return count


# ---------------------------------------------------------------------------
# 1. run_start — happy path
# ---------------------------------------------------------------------------


def test_run_start_happy_path_sets_all_identity_fields(env):
    """Manual → autopilot: all §1.1 autopilot identity fields populated."""
    rc = _start(env, phase_slug="phase-alpha", mode="phase")
    assert rc.exit_code == 0
    assert rc.sub_reason == "started"
    assert rc.autopilot_run_id is not None

    state = _read_state(env)
    assert state["execution_mode"] == "phase_autopilot"
    assert state["autopilot_run_id"] == rc.autopilot_run_id
    assert state["autopilot_mode"] == "phase"
    assert state["autopilot_phase_slug"] == "phase-alpha"
    assert state["autopilot_start_entry_hash"] is not None
    assert state["autopilot_allow_network"] is False
    assert isinstance(state["cli_budgets_remaining"], dict)


def test_run_start_emits_audit_row(env):
    """run_start emits verb=phase.autopilot.start audit row."""
    _start(env, phase_slug="phase-alpha", mode="phase")
    count = _count_audit_rows(env, "phase.autopilot.start")
    assert count == 1


def test_run_start_chain_mode_sets_chain_execution_mode(env):
    """mode=chain → execution_mode=chain_autopilot."""
    rc = _start(env, phase_slug="phase-alpha", mode="chain")
    assert rc.exit_code == 0
    state = _read_state(env)
    assert state["execution_mode"] == "chain_autopilot"
    assert state["autopilot_mode"] == "chain"


def test_run_start_with_budgets(env):
    """Custom budgets are written to state."""
    budgets = {"shell_invocations": 100, "file_mutation_ops": 200, "wall_seconds": 600}
    rc = _start(env, budgets=budgets)
    assert rc.exit_code == 0
    state = _read_state(env)
    assert state["cli_budgets_remaining"]["shell_invocations"] == 100


def test_run_start_with_allow_network(env):
    """allow_network=True propagates to state."""
    rc = _start(env, allow_network=True)
    assert rc.exit_code == 0
    state = _read_state(env)
    assert state["autopilot_allow_network"] is True


def test_run_start_audit_row_contains_authorization_source(env):
    """Audit row carries authorization_source from caller."""
    _start(env, authorization_source="cli_tty_human")
    audit_path = env["audit_path"]
    for line in audit_path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            if row.get("verb") == "phase.autopilot.start":
                assert row.get("authorization_source") == "cli_tty_human"
                break
        except json.JSONDecodeError:
            pass
    else:
        pytest.fail("phase.autopilot.start audit row not found")


# ---------------------------------------------------------------------------
# 2. run_start — active-autopilot re-entry (§3.5.2, exit 15)
# ---------------------------------------------------------------------------


def test_run_start_rejects_when_already_active(env):
    """Second start while execution_mode != manual → exit 15."""
    rc1 = _start(env, phase_slug="phase-alpha", mode="phase")
    assert rc1.exit_code == 0

    rc2 = _start(env, phase_slug="phase-alpha", mode="phase")
    assert rc2.exit_code == 15
    assert rc2.sub_reason == "autopilot_already_active"


def test_run_start_reentry_message_names_existing_run_id(env, capsys):
    """Exit 15 message names existing autopilot_run_id."""
    rc1 = _start(env, phase_slug="phase-alpha", mode="phase")
    _start(env, phase_slug="phase-alpha", mode="phase")
    err = capsys.readouterr().err
    assert rc1.autopilot_run_id in err


def test_run_start_reentry_message_names_existing_mode(env, capsys):
    """Exit 15 message names existing autopilot_mode."""
    _start(env, phase_slug="phase-alpha", mode="phase")
    _start(env, phase_slug="phase-alpha", mode="phase")
    err = capsys.readouterr().err
    assert "phase" in err


# ---------------------------------------------------------------------------
# 3. run_start — Windows + chain + no-allow-network (exit 11)
# ---------------------------------------------------------------------------


def test_run_start_rejects_windows_chain_no_network(env, monkeypatch):
    """Windows + mode=chain + allow_network=False → exit 11."""
    monkeypatch.setattr(sys, "platform", "win32")
    rc = _start(env, mode="chain", allow_network=False,
                accept_degraded_windows_containment=False)
    assert rc.exit_code == 11
    assert rc.sub_reason == "windows_containment_degraded"


def test_run_start_accepts_windows_chain_with_accept_degraded(env, monkeypatch):
    """Windows + chain + accept_degraded_windows_containment=True → allowed."""
    monkeypatch.setattr(sys, "platform", "win32")
    rc = _start(env, mode="chain", allow_network=False,
                accept_degraded_windows_containment=True)
    assert rc.exit_code == 0


def test_run_start_accepts_windows_chain_with_allow_network(env, monkeypatch):
    """Windows + chain + allow_network=True → allowed (containment satisfied)."""
    monkeypatch.setattr(sys, "platform", "win32")
    rc = _start(env, mode="chain", allow_network=True,
                accept_degraded_windows_containment=False)
    assert rc.exit_code == 0


def test_run_start_windows_phase_mode_not_blocked(env, monkeypatch):
    """Windows + mode=phase is NOT blocked (exit 11 is chain-only)."""
    monkeypatch.setattr(sys, "platform", "win32")
    rc = _start(env, mode="phase")
    assert rc.exit_code == 0


# ---------------------------------------------------------------------------
# 4. run_start — phase_slug not in roadmap (exit 2)
# ---------------------------------------------------------------------------


def test_run_start_rejects_slug_not_in_roadmap(env):
    """phase_slug not in .planning/phases/ → exit 2."""
    rc = _start(env, phase_slug="phase-nonexistent")
    assert rc.exit_code == 2
    assert rc.sub_reason == "phase_slug_not_in_roadmap"


def test_run_start_rejects_none_slug(env):
    """phase_slug=None → exit 2 invalid_phase_slug (chain wrapper uses next-pending)."""
    rc = _start(env, phase_slug=None)
    assert rc.exit_code == 2
    assert rc.sub_reason == "invalid_phase_slug"


# ---------------------------------------------------------------------------
# 5. run_start — anchor_preflight_unwired (exit 6)
# ---------------------------------------------------------------------------


def test_run_start_rejects_without_anchor_when_not_skipped(env):
    """Default anchor_verified=False + skip_anchor_preflight=False → exit 6."""
    lock = phase_lock.acquire_primary(env["scratch"], timeout_s=2.0)
    try:
        rc = phase_autopilot.run_start(
            scratch_root=env["scratch"],
            audit_path=env["audit_path"],
            lock_handle=lock,
            phase_slug="phase-alpha",
            mode="phase",
            budgets=None,
            allow_network=False,
            authorization_source="cli_tty_human",
            anchor_verified=False,
            skip_anchor_preflight=False,
            roadmap_root=env["roadmap_root"],
        )
    finally:
        phase_lock.release_primary(lock)
    assert rc.exit_code == 6
    assert rc.sub_reason == "anchor_preflight_unwired"


# ---------------------------------------------------------------------------
# 6. run_start — git_repo_required (exit 12) chain mode without .git
# ---------------------------------------------------------------------------


def test_run_start_chain_git_required_when_no_git_dir(env, tmp_path):
    """chain mode + no .git → exit 12 when repo_root passed without .git."""
    no_git_root = tmp_path / "no-git-root"
    no_git_root.mkdir()
    rc = _start(env, mode="chain", repo_root=no_git_root)
    assert rc.exit_code == 12
    assert rc.sub_reason == "git_repo_required"


def test_run_start_phase_mode_no_git_allowed(env, tmp_path):
    """phase mode: no .git is fine (git-agnostic for phase mode)."""
    no_git_root = tmp_path / "no-git-root"
    no_git_root.mkdir()
    rc = _start(env, mode="phase", repo_root=no_git_root)
    assert rc.exit_code == 0


# ---------------------------------------------------------------------------
# 7. run_stop — clears identity fields, sets execution_mode=manual
# ---------------------------------------------------------------------------


def test_run_stop_clears_all_identity_fields(env):
    """run_stop clears all autopilot identity fields."""
    _start(env)
    rc = _stop(env)
    assert rc.exit_code == 0
    assert rc.sub_reason == "stopped"

    state = _read_state(env)
    assert state["execution_mode"] == "manual"
    assert state["autopilot_run_id"] is None
    assert state["autopilot_mode"] is None
    assert state["autopilot_phase_slug"] is None
    assert state["autopilot_start_entry_hash"] is None
    assert state["cli_budgets_remaining"] is None


def test_run_stop_emits_audit_row(env):
    """run_stop emits verb=phase.autopilot.stop audit row."""
    _start(env)
    _stop(env, reason="done with phase")
    count = _count_audit_rows(env, "phase.autopilot.stop")
    assert count == 1


def test_run_stop_audit_row_contains_reason(env):
    """Stop audit row carries reason field."""
    _start(env)
    _stop(env, reason="the-specific-reason")
    audit_path = env["audit_path"]
    for line in audit_path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            if row.get("verb") == "phase.autopilot.stop":
                assert "the-specific-reason" in json.dumps(row)
                break
        except json.JSONDecodeError:
            pass
    else:
        pytest.fail("phase.autopilot.stop audit row not found")


# ---------------------------------------------------------------------------
# 8. run_stop — idempotent (already manual)
# ---------------------------------------------------------------------------


def test_run_stop_idempotent_when_already_manual(env):
    """run_stop on already-manual state succeeds (idempotent, exit 0)."""
    rc = _stop(env)
    assert rc.exit_code == 0
    state = _read_state(env)
    assert state["execution_mode"] == "manual"


def test_run_stop_idempotent_no_duplicate_audit(env):
    """run_stop on already-manual state emits no stop audit row."""
    _stop(env)
    count = _count_audit_rows(env, "phase.autopilot.stop")
    # Idempotent: no audit row when already manual.
    assert count == 0


# ---------------------------------------------------------------------------
# 9. run_next_pending — returns first non-done phase slug
# ---------------------------------------------------------------------------


def test_run_next_pending_returns_first_nondone_slug(env):
    """next-pending returns the first phase slug that is not done."""
    result = _next_pending(env)
    assert result.exit_code == 0
    assert result.next_slug == "phase-alpha"


def test_run_next_pending_skips_done_phases(env):
    """next-pending skips phases whose phase-state.json records done."""
    # Mark phase-alpha as done by writing a phase-state.json.
    alpha_dir = env["roadmap_root"] / "phase-alpha"
    (alpha_dir / "phase-state.json").write_text(
        json.dumps({"phase": "done"}), encoding="utf-8"
    )
    result = _next_pending(env)
    assert result.exit_code == 0
    assert result.next_slug == "phase-beta"


def test_run_next_pending_all_done_sentinel(env):
    """next-pending returns sentinel when all phases are done."""
    for slug in ("phase-alpha", "phase-beta"):
        phase_dir = env["roadmap_root"] / slug
        (phase_dir / "phase-state.json").write_text(
            json.dumps({"phase": "done"}), encoding="utf-8"
        )
    result = _next_pending(env)
    assert result.exit_code == 0
    assert result.next_slug == ""
    assert result.all_done is True


def test_run_next_pending_empty_roadmap_returns_sentinel(env):
    """next-pending with no phase dirs returns sentinel (empty string)."""
    import shutil
    shutil.rmtree(env["roadmap_root"])
    env["roadmap_root"].mkdir()
    result = _next_pending(env)
    assert result.exit_code == 0
    assert result.next_slug == ""
    assert result.all_done is True


# ---------------------------------------------------------------------------
# 10. run_next_pending — pure read (no audit row, no state mutation)
# ---------------------------------------------------------------------------


def test_run_next_pending_no_audit_row(env):
    """next-pending emits no audit row (pure read)."""
    # Count ALL audit rows before.
    before_lines = _count_audit_lines(env)
    _next_pending(env)
    after_lines = _count_audit_lines(env)
    assert after_lines == before_lines


def _count_audit_lines(env: dict) -> int:
    audit_path = env["audit_path"]
    if not audit_path.exists():
        return 0
    lines = [l for l in audit_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    return len(lines)


def test_run_next_pending_no_state_mutation(env):
    """next-pending does not change state on disk."""
    state_before = _read_state(env)
    _next_pending(env)
    state_after = _read_state(env)
    assert state_before == state_after


# ---------------------------------------------------------------------------
# 11. Lock contract: missing/released lock → TxnLockMissingError
# ---------------------------------------------------------------------------


def test_run_start_raises_if_lock_is_none(env):
    """run_start with lock_handle=None raises TxnLockMissingError."""
    with pytest.raises(phase_txn.TxnLockMissingError):
        phase_autopilot.run_start(
            scratch_root=env["scratch"],
            audit_path=env["audit_path"],
            lock_handle=None,
            phase_slug="phase-alpha",
            mode="phase",
            budgets=None,
            allow_network=False,
            authorization_source="cli_tty_human",
            anchor_verified=True,
            skip_anchor_preflight=True,
            roadmap_root=env["roadmap_root"],
        )


def test_run_stop_raises_if_lock_is_released(env):
    """run_stop with released lock raises TxnLockMissingError."""
    lock = phase_lock.acquire_primary(env["scratch"], timeout_s=2.0)
    phase_lock.release_primary(lock)
    with pytest.raises(phase_txn.TxnLockMissingError):
        phase_autopilot.run_stop(
            scratch_root=env["scratch"],
            audit_path=env["audit_path"],
            lock_handle=lock,
            reason="test",
            anchor_verified=True,
            skip_anchor_preflight=True,
        )


# ---------------------------------------------------------------------------
# 12. xfail-strict pin: live CLI routing (deferred — CLI wiring not yet landed)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "CLI argparse wiring for `phase autopilot start` not yet landed "
        "(deferred to later step per S07-prep scope). "
        "Flip to xpass when harness.py dispatches to run_start."
    ),
)
def test_live_cli_routes_through_phase_autopilot_run_start(env, tmp_path):
    """Smoke: `harness phase autopilot start` must route to run_start.

    This test is xfail-strict until the CLI argparse wiring is added in a
    subsequent commit. The xfail pin prevents silent skipping — if the CLI
    is accidentally wired before this test is updated it will flip to
    xpass and alert the committer to remove the mark.
    """
    import subprocess
    import os

    # This call is expected to fail (CLI not wired).
    result = subprocess.run(
        [sys.executable, "-m", "scripts.harness", "phase", "autopilot", "start",
         "--phase", "phase-alpha", "--mode", "phase"],
        capture_output=True,
        text=True,
        cwd=str(env["tmp_path"]),
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "scripts")},
    )
    # Expect success (exit 0) when CLI is wired. Until then this line
    # makes the test "fail" (so xfail=strict is satisfied).
    assert result.returncode == 0, f"CLI not wired: {result.stderr[:300]}"
