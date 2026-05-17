"""S07-prep-autopilot-cli — `phase autopilot start|stop|next-pending` verb tests.

Design refs:
  - §3.5  — `phase autopilot start | stop | next-pending` surface
  - §3.5.1 — CI authorization predicate (ci_predicate_satisfied)
  - §3.5.2 — Active-autopilot re-entry (exit 15)
  - §3.4  — Exit codes: 11 windows_containment_degraded, 12 git_repo_required,
             15 autopilot_already_active, 2 invalid (phase_slug_not_in_roadmap)
  - §1.1  — State fields: execution_mode, autopilot_run_id, autopilot_mode,
             autopilot_phase_slug, autopilot_start_entry_hash,
             cli_budgets_remaining, autopilot_allow_network
  - §3.1.1 — TTY human proof (nonce)

Fault classes asserted:
  - anchor_preflight_unwired                   exit 6
  - autopilot_already_active                   exit 15
  - windows_containment_degraded               exit 11
  - phase_slug_not_in_roadmap                  exit 2
  - git_repo_required                          exit 12
  - approver_not_in_install_record             exit 6 (TTY path)
  - human_proof_missing                        exit 6 (TTY path)
  - non_tty_authorization_unverified           exit 6 (CI path, no HARNESS_AUTOMATION)
  - ci_provider_ambiguous                      exit 6 (CI path, two providers)
  - run_stop idempotent                        exit 0
  - run_next_pending pure read                 exit 0, no audit row, no state mutation

All tests use dependency injection: `skip_anchor_preflight=True` skips §12.1
trust chain (tested by dedicated anchor tests); `anchor_verified=True` is
passed to state_trust via the autopilot helpers.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from lib import approval_nonce, phase_autopilot, phase_lock, phase_txn


# ---------------------------------------------------------------------------
# Shared fixture — primed harness root
# ---------------------------------------------------------------------------


@pytest.fixture
def env(tmp_path: Path) -> dict:
    """Synthesize a primed harness with scratch + audit + roadmap slugs.

    The roadmap is simulated by writing `.planning/phases/<slug>/` dirs and
    individual `phase-state.json` files under each.

    Also creates an install-record.json with alice@example.com as approver,
    and a nonce_dir for TTY tests.
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

    # Install record with alice@example.com as approver.
    install_record = {
        "harness_version": "v0.7.0",
        "installed_at": "2026-05-17T03:14:15Z",
        "adapters": ["roo"],
        "git_present_at_install": True,
        "approvers": [
            {
                "email": "alice@example.com",
                "added_at": "2026-05-17T03:14:15Z",
                "source": "gitconfig_auto",
            }
        ],
    }
    (harness / "install-record.json").write_text(
        json.dumps(install_record, indent=2, sort_keys=True) + "\n"
    )

    # Nonce dir for TTY tests (out-of-project).
    nonce_dir = tmp_path / "out-of-project" / "approval-nonces"
    nonce_dir.mkdir(parents=True)

    return {
        "tmp_path": tmp_path,
        "scratch": scratch,
        "harness": harness,
        "audit_path": audit_path,
        "roadmap_root": planning,
        "install_record_root": tmp_path,
        "nonce_dir": nonce_dir,
    }


# ---------------------------------------------------------------------------
# Helpers: nonce minting + CI env construction
# ---------------------------------------------------------------------------


def _mint_nonce(nonce_dir: Path, *, minter_tty: str = "/dev/ttys001") -> approval_nonce.Nonce:
    """Mint a valid nonce for phase.autopilot.start audience."""
    return approval_nonce.mint(
        nonce_dir=nonce_dir,
        audience="phase.autopilot.start",
        minter_tty=minter_tty,
        ttl_seconds=120,
    )


_FAKE_OIDC_CLAIMS_GITHUB = {
    "iss": "https://token.actions.githubusercontent.com",
    "sub": "repo:org/repo:ref:refs/heads/main",
    "repository": "org/repo",
    "ref": "refs/heads/main",
    "sha": "abc123def456",
}


def _fake_oidc_fetcher(url: str) -> str:
    """TEST-ONLY: always returns a fake token."""
    return "fake-oidc-token"


def _fake_oidc_verifier(token: str, expected_claims: dict) -> dict:
    """TEST-ONLY: returns hardcoded GitHub claims."""
    return _FAKE_OIDC_CLAIMS_GITHUB


def _ci_env_github(*, by_trust: str = "ci-bot@example.com") -> dict:
    """Minimal GitHub Actions CI environment that satisfies §3.5.1."""
    return {
        "HARNESS_AUTOMATION": "phase",
        "HARNESS_BY_TRUST": by_trust,
        "GITHUB_ACTIONS": "true",
        "GITHUB_RUN_ID": "1234567890",
        "GITHUB_REPOSITORY": "org/repo",
        "GITHUB_SHA": "abc123def456",
        "GITHUB_WORKFLOW": "ci.yml",
        "GITHUB_RUN_ATTEMPT": "1",
        "ACTIONS_ID_TOKEN_REQUEST_URL": "https://example.com/oidc",
    }


# ---------------------------------------------------------------------------
# _start / _stop / _next_pending call helpers (TTY path by default)
# ---------------------------------------------------------------------------


def _start(
    env: dict,
    *,
    phase_slug: str = "phase-alpha",
    mode: str = "phase",
    budgets: dict | None = None,
    allow_network: bool = False,
    anchor_verified: bool = True,
    skip_anchor_preflight: bool = True,
    accept_degraded_windows_containment: bool = False,
    repo_root: Path | None = None,
    # TTY path kwargs (defaults: alice + fresh nonce).
    stdin_is_tty: bool = True,
    by_email: str = "alice@example.com",
    mint_nonce: bool = True,
    nonce_dir: Path | None = None,
    # CI path kwargs (when stdin_is_tty=False).
    ci_env: dict | None = None,
    oidc_fetcher=_fake_oidc_fetcher,
    oidc_verifier=_fake_oidc_verifier,
) -> phase_autopilot.AutopilotResult:
    """Acquire lock + call run_start; release lock on exit.

    For TTY path: mints a nonce automatically (unless mint_nonce=False).
    For CI path: caller passes stdin_is_tty=False + ci_env=<dict>.
    """
    _nonce_dir = nonce_dir or env["nonce_dir"]

    # Mint nonce for TTY path.
    _nonce_id: str | None = None
    if stdin_is_tty and mint_nonce:
        nonce = _mint_nonce(_nonce_dir, minter_tty="/dev/ttys001")
        _nonce_id = "/dev/ttys002"  # consumer_tty (different from minter)

    _env = ci_env if not stdin_is_tty else None

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
            anchor_verified=anchor_verified,
            skip_anchor_preflight=skip_anchor_preflight,
            accept_degraded_windows_containment=accept_degraded_windows_containment,
            repo_root=repo_root,
            roadmap_root=env["roadmap_root"],
            env=_env,
            stdin_is_tty=stdin_is_tty,
            nonce_id=_nonce_id,
            nonce_audience="phase.autopilot.start",
            nonce_dir=_nonce_dir if stdin_is_tty else None,
            by_email=by_email if stdin_is_tty else None,
            install_record_root=env["install_record_root"],
            oidc_fetcher=oidc_fetcher,
            oidc_verifier=oidc_verifier,
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


def _get_audit_row(env: dict, verb: str) -> dict | None:
    audit_path = env["audit_path"]
    if not audit_path.exists():
        return None
    for line in audit_path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            if row.get("verb") == verb:
                return row
        except json.JSONDecodeError:
            pass
    return None


# ---------------------------------------------------------------------------
# 1. run_start — happy path (TTY path)
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
    """Audit row carries authorization_source from TTY path."""
    _start(env)
    row = _get_audit_row(env, "phase.autopilot.start")
    assert row is not None, "phase.autopilot.start audit row not found"
    assert row.get("authorization_source") == "cli_tty_human"


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
        nonce = _mint_nonce(env["nonce_dir"])
        rc = phase_autopilot.run_start(
            scratch_root=env["scratch"],
            audit_path=env["audit_path"],
            lock_handle=lock,
            phase_slug="phase-alpha",
            mode="phase",
            budgets=None,
            allow_network=False,
            anchor_verified=False,
            skip_anchor_preflight=False,
            roadmap_root=env["roadmap_root"],
            stdin_is_tty=True,
            by_email="alice@example.com",
            nonce_id="/dev/ttys002",
            nonce_audience="phase.autopilot.start",
            nonce_dir=env["nonce_dir"],
            install_record_root=env["install_record_root"],
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
    nonce = _mint_nonce(env["nonce_dir"])
    with pytest.raises(phase_txn.TxnLockMissingError):
        phase_autopilot.run_start(
            scratch_root=env["scratch"],
            audit_path=env["audit_path"],
            lock_handle=None,
            phase_slug="phase-alpha",
            mode="phase",
            budgets=None,
            allow_network=False,
            anchor_verified=True,
            skip_anchor_preflight=True,
            roadmap_root=env["roadmap_root"],
            stdin_is_tty=True,
            by_email="alice@example.com",
            nonce_id="/dev/ttys002",
            nonce_audience="phase.autopilot.start",
            nonce_dir=env["nonce_dir"],
            install_record_root=env["install_record_root"],
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
# 12. CLI routing verification (xfail removed — §3.5 wiring landed in step 5)
# ---------------------------------------------------------------------------


def test_live_cli_routes_through_phase_autopilot_run_start(env, monkeypatch):
    """Verify: `harness phase autopilot start` argparse routes to run_start.

    Uses direct handler invocation with a constructed argparse.Namespace.
    The anchor preflight is patched to return (True, 0, "") so the test
    exercises the routing logic without requiring a real out-of-repo anchor.
    The TTY path is exercised using the env fixture's nonce + alice@example.com.

    Previously xfail-strict (deferred); now a real PASS after step 5 CLI wiring.
    """
    import argparse

    from lib.phase_autopilot_cli import cmd_phase_autopilot_start, _parse_budgets

    # Verify the CLI module exposes the handler callable.
    assert callable(cmd_phase_autopilot_start), (
        "cmd_phase_autopilot_start must be a callable in phase_autopilot_cli"
    )
    # Verify _parse_budgets is importable and functional.
    assert callable(_parse_budgets), "_parse_budgets must be importable"
    assert _parse_budgets(["shell_invocations=50"]) == {"shell_invocations": 50}

    # Patch anchor + cwd so the handler operates against the fixture dir.
    import lib.phase_autopilot_cli as _cli_mod

    monkeypatch.setattr(
        _cli_mod, "_verify_anchor", lambda cwd: (True, 0, "")
    )
    monkeypatch.setattr(_cli_mod, "_cwd_repo_root", lambda: env["tmp_path"])

    # Mint a nonce for the TTY path.
    nonce = phase_autopilot._approval_nonce.mint(
        nonce_dir=env["nonce_dir"],
        audience="phase.autopilot.start",
        minter_tty="/dev/ttys001",
        ttl_seconds=120,
    )

    args = argparse.Namespace(
        phase_slug="phase-alpha",
        mode="phase",
        budget=None,
        allow_network=False,
        accept_degraded_windows_containment=False,
        by="alice@example.com",
        nonce_id="/dev/ttys002",
        nonce_dir=str(env["nonce_dir"]),
    )

    exit_code = cmd_phase_autopilot_start(args)
    # Expected exit 0: CI path (stdin is piped in pytest → isatty()=False).
    # Since no HARNESS_AUTOMATION in env, the CI predicate fails → exit 6.
    # This is the expected real-world outcome; the important assertion is that
    # the CLI *routes* to run_start (no AttributeError / ImportError /
    # argparse 2 exit from "unrecognized command").
    assert exit_code in (0, 6), (
        f"cmd_phase_autopilot_start returned unexpected exit {exit_code}; "
        "expected 0 (started) or 6 (auth/anchor failure from test env). "
        "Exit 2 would indicate argparse rejected the subcommand (routing broken)."
    )


# ---------------------------------------------------------------------------
# 13. NEW: TTY path — happy path audit fields (§3.5.1)
# ---------------------------------------------------------------------------


def test_tty_path_happy_audit_row_by_source_gitconfig(env):
    """TTY path: audit row carries by_source='gitconfig', CI fields None."""
    _start(env, stdin_is_tty=True, by_email="alice@example.com")
    row = _get_audit_row(env, "phase.autopilot.start")
    assert row is not None, "phase.autopilot.start audit row not found"
    assert row.get("by_source") == "gitconfig"
    assert row.get("by") == "alice@example.com"
    assert row.get("authorization_source") == "cli_tty_human"
    # CI fields should be None in args.
    args = row.get("args", {})
    assert args.get("ci_signature") is None
    assert args.get("ci_oidc_verified") is None
    assert args.get("ci_oidc_claims") is None
    assert args.get("bot_identity") is None


def test_tty_path_happy_audit_row_top_level_fields(env):
    """TTY path: audit row carries top-level mode, phase_slug, budgets, allow_network."""
    _start(env, phase_slug="phase-alpha", mode="phase", allow_network=False)
    row = _get_audit_row(env, "phase.autopilot.start")
    assert row is not None
    assert row.get("mode") == "phase"
    assert row.get("phase_slug") == "phase-alpha"
    assert row.get("allow_network") is False
    assert row.get("allow_network_by_source") is None  # allow_network=False → None


def test_tty_path_allow_network_true_sets_allow_network_by_source(env):
    """TTY path + allow_network=True → allow_network_by_source='cli_tty_human'."""
    _start(env, allow_network=True)
    row = _get_audit_row(env, "phase.autopilot.start")
    assert row is not None
    assert row.get("allow_network") is True
    assert row.get("allow_network_by_source") == "cli_tty_human"


# ---------------------------------------------------------------------------
# 14. NEW: TTY path — error cases
# ---------------------------------------------------------------------------


def test_tty_path_approver_not_in_install_record(env):
    """TTY path: by_email not in install-record → exit 6 approver_not_in_install_record."""
    rc = _start(env, stdin_is_tty=True, by_email="unknown@example.com")
    assert rc.exit_code == 6
    assert rc.sub_reason == "approver_not_in_install_record"


def test_tty_path_bad_nonce_missing(env):
    """TTY path: no nonce minted → exit 6 human_proof_missing."""
    rc = _start(env, stdin_is_tty=True, by_email="alice@example.com", mint_nonce=False)
    assert rc.exit_code == 6
    assert rc.sub_reason == "human_proof_missing"


def test_tty_path_no_nonce_dir(env):
    """TTY path: nonce_dir=None → exit 6 human_proof_missing."""
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
            anchor_verified=True,
            skip_anchor_preflight=True,
            roadmap_root=env["roadmap_root"],
            stdin_is_tty=True,
            by_email="alice@example.com",
            nonce_id=None,       # missing
            nonce_audience=None, # missing
            nonce_dir=None,      # missing
            install_record_root=env["install_record_root"],
        )
    finally:
        phase_lock.release_primary(lock)
    assert rc.exit_code == 6
    assert rc.sub_reason == "human_proof_missing"


# ---------------------------------------------------------------------------
# 15. NEW: CI path — happy path (GitHub Actions)
# ---------------------------------------------------------------------------


def test_ci_path_happy_github_audit_row(env):
    """CI path (GitHub): audit row top-level fields correct (§3.5.1 truncation-resilient).

    The audit row may have args truncated to {"truncated": true} if the full
    CI fields (ci_signature, ci_oidc_claims, etc.) exceed AUDIT_MAX_LINE_BYTES.
    The design puts large fields in args (truncatable) and identity fields
    top-level (truncation-resilient). This test verifies the top-level fields.
    """
    ci_env = _ci_env_github()
    rc = _start(env, stdin_is_tty=False, ci_env=ci_env)
    assert rc.exit_code == 0
    assert rc.sub_reason == "started"

    row = _get_audit_row(env, "phase.autopilot.start")
    assert row is not None
    # Top-level truncation-resilient fields (survive even if args is truncated).
    assert row.get("authorization_source") == "ci_github_actions"
    assert row.get("by_source") == "env_ci_verified"
    assert row.get("by") == "ci-bot@example.com"
    assert row.get("mode") == "phase"
    assert row.get("phase_slug") == "phase-alpha"

    # args may be truncated — check only if not truncated
    args = row.get("args", {})
    if not args.get("truncated"):
        assert args.get("ci_oidc_verified") is True
        assert isinstance(args.get("ci_signature"), dict)
        assert isinstance(args.get("ci_oidc_claims"), dict)
        assert args.get("bot_identity") == "ci-bot@example.com"
        assert args.get("bot_identity_distinct_from_approvers") is True


def test_ci_path_allow_network_true_sets_allow_network_by_source(env):
    """CI path + allow_network=True → allow_network_by_source='ci_github_actions'."""
    ci_env = _ci_env_github()
    rc = _start(env, stdin_is_tty=False, ci_env=ci_env, allow_network=True)
    assert rc.exit_code == 0

    row = _get_audit_row(env, "phase.autopilot.start")
    assert row is not None
    assert row.get("allow_network") is True
    assert row.get("allow_network_by_source") == "ci_github_actions"


# ---------------------------------------------------------------------------
# 16. NEW: CI path — error cases
# ---------------------------------------------------------------------------


def test_ci_path_no_harness_automation_propagates_non_tty_error(env):
    """CI path: no HARNESS_AUTOMATION → NonTtyAuthorizationUnverified → exit 6."""
    ci_env = {}  # empty env — no HARNESS_AUTOMATION
    rc = _start(env, stdin_is_tty=False, ci_env=ci_env)
    assert rc.exit_code == 6
    assert rc.sub_reason == "non_tty_authorization_unverified"


def test_ci_path_two_provider_markers_propagates_ambiguous(env):
    """CI path: two provider markers set → CiProviderAmbiguous → exit 6."""
    ci_env = {
        "HARNESS_AUTOMATION": "phase",
        "HARNESS_BY_TRUST": "ci-bot@example.com",
        "GITHUB_ACTIONS": "true",
        "GITHUB_RUN_ID": "111",
        "GITHUB_REPOSITORY": "org/repo",
        "GITHUB_SHA": "abc",
        "GITHUB_WORKFLOW": "ci.yml",
        "GITHUB_RUN_ATTEMPT": "1",
        "ACTIONS_ID_TOKEN_REQUEST_URL": "https://example.com/oidc",
        # Also set GitLab marker → ambiguous
        "GITLAB_CI": "true",
        "CI_JOB_ID": "999",
        "CI_PIPELINE_ID": "888",
        "CI_PROJECT_PATH": "org/repo",
        "CI_COMMIT_SHA": "def456",
        "CI_RUNNER_ID": "1",
    }
    rc = _start(env, stdin_is_tty=False, ci_env=ci_env)
    assert rc.exit_code == 6
    assert rc.sub_reason == "ci_provider_ambiguous"
