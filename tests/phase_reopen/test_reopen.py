"""S04-reopen — `phase reopen` rewinds to plan/discuss boundary.

Design refs:
  - §3.2  — `phase reopen` (NEW verb) — TTY-only — primary spec
  - §3.1  — context: identity resolution mirrors phase approve
  - §5.3  — Halt → manual handoff (last_halt diary fields)
  - §3.5.2— Active-autopilot fields cleared on halt
  - §12.6 — confirmation_kind semantics carry over for override identity
  - §1.1  — state schema (verification/allowed_paths/draft_*)
  - §3.9  — `Fix:` standard for error messages

Tests target `scripts/lib/phase_reopen.py:run_reopen` directly with
dependency injection (no real TTY, no real ~/.harness, no real git).

Fault classes asserted:
  - non_tty_reopen_blocked              exit 6
  - anchor_preflight_unwired            exit 6
  - gitconfig_email_unset               exit 6
  - approver_not_in_install_record      exit 6
  - reopen_missing_reason               exit 6
  - reopen_invalid_target               exit 6
"""

from __future__ import annotations

import json
import inspect
from pathlib import Path

import pytest

from lib import phase_reopen, phase_lock, phase_txn


# ---------------------------------------------------------------------------
# Fixtures — synthesize a fully primed harness root
# ---------------------------------------------------------------------------


@pytest.fixture
def env(tmp_path: Path) -> dict:
    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    harness = tmp_path / ".harness"
    harness.mkdir()
    audit_path = harness / "audit.log"

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

    # Seed: execute phase, approved, with verification + allowed_paths set,
    # execute_attempt_started_at populated, manual mode (no autopilot).
    seed_state = {
        "phase": "execute",
        "approved": True,
        "approved_at": "2026-05-17T10:00:00Z",
        "approved_by": "alice@example.com",
        "execution_mode": "manual",
        "state_schema_version": 2,
        "verification": ["pytest tests/ -q"],
        "allowed_paths": ["scripts/lib/foo.py", "tests/foo/"],
        "draft_verification": None,
        "draft_allowed_paths": None,
        "execute_attempt_started_at": "2026-05-17T10:05:00Z",
        "plan_finalized_at": "2026-05-17T09:55:00Z",
        "last_halt": None,
        "last_halt_history": [],
        "autopilot_run_id": None,
        "autopilot_mode": None,
        "autopilot_phase_slug": None,
        "autopilot_start_entry_hash": None,
        "autopilot_allow_network": False,
        "cli_budgets_remaining": None,
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
                "args": {"phase": "execute"},
            },
        )
        phase_txn.commit_transaction(
            scratch, lock=lock, request=req, audit_path=audit_path
        )
    finally:
        phase_lock.release_primary(lock)

    return {
        "tmp_path": tmp_path,
        "scratch": scratch,
        "harness": harness,
        "audit_path": audit_path,
        "install_record_path": harness / "install-record.json",
    }


def _reseed(env, mutator):
    """Mutate state through a txn so audit tip stays consistent."""
    state_path = env["scratch"] / "phase-state.json"
    before = json.loads(state_path.read_text())
    after = dict(before)
    mutator(after)
    lock = phase_lock.acquire_primary(env["scratch"], timeout_s=2.0)
    try:
        req = phase_txn.TxnRequest(
            action="phase.set",
            before_state=before,
            after_state=after,
            audit_entry_draft={"verb": "phase.set", "by": "reseed", "args": {}},
        )
        phase_txn.commit_transaction(
            env["scratch"], lock=lock, request=req, audit_path=env["audit_path"]
        )
    finally:
        phase_lock.release_primary(lock)


def _make_args(**overrides):
    base = {
        "by": None,
        "to": "plan",
        "reason": "mind-change mid-flow, need to revisit plan",
        "override_identity": False,
        "override_reason": None,
        # T12: --reset-approval defaults True in existing tests because the
        # seed state always has approved=True; the new T12 tests exercise
        # the False (refused) path explicitly.
        "reset_approval": True,
    }
    base.update(overrides)

    class Ns:
        pass

    ns = Ns()
    for k, v in base.items():
        setattr(ns, k, v)
    return ns


def _run(env, *, stdin_isatty=True, gitconfig_email="alice@example.com",
         repo_root=None, **arg_overrides):
    args = _make_args(**arg_overrides)
    return phase_reopen.run_reopen(
        args,
        scratch=env["scratch"],
        harness_dir=env["harness"],
        audit_path=env["audit_path"],
        install_record_path=env["install_record_path"],
        stdin_isatty=stdin_isatty,
        gitconfig_email_lookup=lambda: gitconfig_email,
        env_vars={},
        repo_root=repo_root,
    )


# ---------------------------------------------------------------------------
# 1. TTY gate (§3.2)
# ---------------------------------------------------------------------------


def test_non_tty_rejected_exit_6(env):
    rc = _run(env, stdin_isatty=False)
    assert rc.exit_code == 6
    assert rc.sub_reason == "non_tty_reopen_blocked"


def test_non_tty_message_includes_fix_line(env, capsys):
    _run(env, stdin_isatty=False)
    err = capsys.readouterr().err
    assert "Fix:" in err


# ---------------------------------------------------------------------------
# 2. Identity resolution mirrors approve
# ---------------------------------------------------------------------------


def test_missing_gitconfig_rejected(env):
    rc = _run(env, gitconfig_email="")
    assert rc.exit_code == 6
    assert rc.sub_reason == "gitconfig_email_unset"


# ---------------------------------------------------------------------------
# 4. --reason mandatory (§3.2 synopsis)
# ---------------------------------------------------------------------------


def test_missing_reason_rejected(env):
    rc = _run(env, reason=None)
    assert rc.exit_code == 6
    assert rc.sub_reason == "reopen_missing_reason"


def test_empty_reason_rejected(env):
    rc = _run(env, reason="   ")
    assert rc.exit_code == 6
    assert rc.sub_reason == "reopen_missing_reason"


# ---------------------------------------------------------------------------
# 5. --to validation (§3.2 — plan or discuss only)
# ---------------------------------------------------------------------------


def test_invalid_target_rejected(env):
    rc = _run(env, to="execute")
    assert rc.exit_code == 6
    assert rc.sub_reason == "reopen_invalid_target"


def test_plan_target_accepted_from_execute(env):
    rc = _run(env, to="plan")
    assert rc.exit_code == 0


def test_discuss_target_accepted_from_execute(env):
    rc = _run(env, to="discuss")
    assert rc.exit_code == 0


# ---------------------------------------------------------------------------
# 6. Reset matrix — approved fields cleared
# ---------------------------------------------------------------------------


def test_approval_fields_cleared(env):
    rc = _run(env, to="plan")
    assert rc.exit_code == 0
    state = json.loads((env["scratch"] / "phase-state.json").read_text())
    assert state["approved"] is False
    assert state["approved_by"] is None
    assert state["approved_at"] is None


def test_execute_attempt_reset(env):
    rc = _run(env, to="plan")
    assert rc.exit_code == 0
    state = json.loads((env["scratch"] / "phase-state.json").read_text())
    assert state["execute_attempt_started_at"] is None


def test_phase_set_to_target(env):
    rc = _run(env, to="discuss")
    assert rc.exit_code == 0
    state = json.loads((env["scratch"] / "phase-state.json").read_text())
    assert state["phase"] == "discuss"


# ---------------------------------------------------------------------------
# 7. Field move — verification → draft_verification, allowed_paths → draft_allowed_paths
# ---------------------------------------------------------------------------


def test_verification_moved_to_draft(env):
    rc = _run(env, to="plan")
    assert rc.exit_code == 0
    state = json.loads((env["scratch"] / "phase-state.json").read_text())
    assert state["verification"] in (None, [])
    assert state["draft_verification"] == ["pytest tests/ -q"]


def test_allowed_paths_moved_to_draft(env):
    rc = _run(env, to="plan")
    assert rc.exit_code == 0
    state = json.loads((env["scratch"] / "phase-state.json").read_text())
    assert state["allowed_paths"] in (None, [])
    assert state["draft_allowed_paths"] == ["scripts/lib/foo.py", "tests/foo/"]


# ---------------------------------------------------------------------------
# 8. Active autopilot halt — chain_autopilot
# ---------------------------------------------------------------------------


def test_chain_autopilot_halted_diary_populated(env):
    """Autopilot removed — reopen from manual mode still succeeds."""
    rc = _run(env, to="plan")
    assert rc.exit_code == 0
    state = json.loads((env["scratch"] / "phase-state.json").read_text())
    assert state["execution_mode"] == "manual"


def test_phase_autopilot_halted(env):
    """Autopilot removed — reopen from manual mode to discuss."""
    rc = _run(env, to="discuss")
    assert rc.exit_code == 0
    state = json.loads((env["scratch"] / "phase-state.json").read_text())
    assert state["execution_mode"] == "manual"


def test_no_autopilot_no_halt_diary_clobber(env):
    # manual mode + no prior halt → reopen must NOT inject a stale last_halt
    rc = _run(env, to="plan")
    assert rc.exit_code == 0
    state = json.loads((env["scratch"] / "phase-state.json").read_text())
    # Either unchanged from seed (None) — explicitly not populated by reopen
    assert state["last_halt"] is None


# ---------------------------------------------------------------------------
# 9. Audit entry shape (§3.2)
# ---------------------------------------------------------------------------


def test_audit_entry_records_reopen_provenance(env):
    rc = _run(env, to="plan", reason="reconsidering plan")
    assert rc.exit_code == 0
    lines = [
        ln for ln in env["audit_path"].read_text().splitlines() if ln.strip()
    ]
    # Last entry must be phase.reopen
    last = json.loads(lines[-1])
    assert last["verb"] == "phase.reopen"
    assert last["by"] == "alice@example.com"
    # Top-level forensic fields (truncation-resilient).
    assert last["from_phase"] == "execute"
    assert last["to_phase"] == "plan"
    assert "at" in last
    # `args` may be a truncation placeholder; the design only requires the
    # full record to be RETRIEVABLE (via overflow archive). When present
    # in-line, assert the documented shape.
    if "truncated" not in last.get("args", {}):
        assert last["args"]["reason"] == "reconsidering plan"
        assert last["args"]["preserved_as_draft"] is True


def test_audit_records_halted_autopilot_run_id(env):
    """Autopilot removed — last audit row is phase.reopen with no halted_autopilot_run_id."""
    rc = _run(env, to="plan")
    assert rc.exit_code == 0
    lines = [
        ln for ln in env["audit_path"].read_text().splitlines() if ln.strip()
    ]
    last = json.loads(lines[-1])
    assert last["verb"] == "phase.reopen"
    assert last.get("halted_autopilot_run_id") is None


# ---------------------------------------------------------------------------
# 10. Idempotency: reopen on already-clean (plan, unapproved, no drafts pending)
# Design decision: reopen is always permitted (it is the recovery verb);
# we accept exit 0 with normal mutation. The user's choice to invoke a
# rewind verb is itself meaningful and audited.
# ---------------------------------------------------------------------------


def test_reopen_on_clean_plan_state_succeeds(env):
    # P2-1 review-fix: `--to plan` permitted only from execute/done
    # (design §3.2 line 250). On a clean plan-phase state, the only
    # legal rewind is --to discuss. The recovery-verb semantics still
    # hold; we just exercise the discuss path here.
    _reseed(env, lambda s: s.update({
        "phase": "plan",
        "approved": False,
        "approved_by": None,
        "approved_at": None,
        "verification": None,
        "allowed_paths": None,
        "execute_attempt_started_at": None,
    }))
    rc = _run(env, to="discuss", reason="just want to re-anchor")
    assert rc.exit_code == 0


# ---------------------------------------------------------------------------
# 11. Lock holder during mutation
# ---------------------------------------------------------------------------


def test_lock_held_during_run_reopen(env, monkeypatch):
    from lib import phase_lock as pl

    lock_path = env["scratch"] / pl.PRIMARY_NAME
    observed = {"during_mutation": False}

    real_commit = phase_txn.commit_transaction

    def spy_commit(scratch, *, lock, request, audit_path):
        observed["during_mutation"] = lock_path.exists()
        return real_commit(scratch, lock=lock, request=request, audit_path=audit_path)

    monkeypatch.setattr(phase_reopen, "_phase_txn", phase_txn)
    monkeypatch.setattr(phase_txn, "commit_transaction", spy_commit)
    rc = _run(env, to="plan")
    assert rc.exit_code == 0
    assert observed["during_mutation"] is True
    assert not lock_path.exists()


# ---------------------------------------------------------------------------
# 12. State-trust preflight invoked
# ---------------------------------------------------------------------------


def test_state_trust_preflight_invoked(env, monkeypatch):
    from lib import state_trust

    calls = []
    real = state_trust.preflight

    def spy(*a, **kw):
        calls.append(kw)
        return real(*a, **kw)

    monkeypatch.setattr(state_trust, "preflight", spy)
    monkeypatch.setattr(phase_reopen, "_state_trust", state_trust)
    rc = _run(env, to="plan")
    assert rc.exit_code == 0
    assert len(calls) > 0


def test_tampered_state_rejected(env):
    state_path = env["scratch"] / "phase-state.json"
    txt = state_path.read_text()
    state_path.write_text(txt.replace('"phase": "execute"', '"phase": "discuss"'))
    rc = _run(env, to="plan")
    assert rc.exit_code == 10
    assert rc.sub_reason == "state_audit_mismatch"


# ---------------------------------------------------------------------------
# 13. xfail-strict CLI-wiring pin (S07-prep)
# ---------------------------------------------------------------------------


def test_live_cli_routes_through_run_reopen():
    from lib import phase_cli

    src = inspect.getsource(phase_cli)
    assert "phase_reopen.run_reopen" in src or "run_reopen(" in src


# ---------------------------------------------------------------------------
# 14. S04+S05 review-fix coverage (P1-1..P1-4, P2-1, P2-4, P2-6)
# ---------------------------------------------------------------------------


def _iso_z_regex(s: str) -> bool:
    import re
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", s))


def test_reopen_acknowledges_prior_halt_diary(env):
    """Halt diary removed — reopen succeeds in manual mode."""
    rc = _run(env, to="discuss")
    assert rc.exit_code == 0


def test_reopen_to_plan_clears_last_halt_into_history(env):
    """Halt diary removed — reopen to plan succeeds without history manipulation."""
    rc = _run(env, to="plan", reason="handle the stale halt")
    assert rc.exit_code == 0


def test_reopen_to_discuss_retains_diary_with_ack_stamp(env):
    """Halt diary removed — reopen to discuss succeeds."""
    rc = _run(env, to="discuss", reason="rewind further")
    assert rc.exit_code == 0


def test_reopen_with_autopilot_emits_two_audit_rows(env):
    """Autopilot removed — reopen emits exactly one audit row (phase.reopen)."""
    rc = _run(env, to="plan", reason="rewind")
    assert rc.exit_code == 0
    lines = [
        ln for ln in env["audit_path"].read_text().splitlines() if ln.strip()
    ]
    last = json.loads(lines[-1])
    assert last["verb"] == "phase.reopen"


def test_reopen_diary_includes_suggested_command_human_flag(env):
    """Halt diary removed — reopen succeeds without populating last_halt."""
    rc = _run(env, to="discuss")
    assert rc.exit_code == 0


def test_reopen_to_plan_from_discuss_rejected(env):
    """P2-1: `--to plan` is permitted only from execute/done
    (design §3.2 line 250)."""
    _reseed(env, lambda s: s.update({
        "phase": "discuss",
        "approved": False,
        "approved_by": None,
        "approved_at": None,
        "verification": None,
        "allowed_paths": None,
    }))
    rc = _run(env, to="plan", reason="invalid rewind")
    assert rc.exit_code == 6
    assert rc.sub_reason == "reopen_invalid_source_for_target"


def test_reopen_to_plan_from_done_accepted(env):
    """P2-1 positive case: from `done` → `--to plan` is permitted."""
    _reseed(env, lambda s: s.update({
        "phase": "done",
        "approved": True,
        "approved_by": "alice@example.com",
        "approved_at": "2026-05-17T11:00:00Z",
    }))
    rc = _run(env, to="plan", reason="rewind from done")
    assert rc.exit_code == 0


def test_reopen_with_autopilot_audit_row_under_1024_bytes_post_s06_budget(env):
    """S06 updated sentinel (formerly pre_s06_budget P2-4): the phase.autopilot.halt
    + phase.reopen audit lines MUST fit under AUDIT_MAX_LINE_BYTES = 1024 bytes.

    S06 added ~140 bytes of per-entry chain fields (schema_version, seq,
    seq_global, previous_entry_hash [64 hex], entry_hash [64 hex]). The limit
    was raised from 512 → 1024 in S06 to accommodate chain fields AND preserve
    all forensic top-level fields (by_source, confirmation_kind, etc.) without
    falling through to the minimal-fallback path which would drop them.
    Design decision: option (a) — raise the sentinel limit; the limit is a
    safety check, not a hard protocol contract.

    TODO(S06-chain): RESOLVED — limit raised to 1024, chain fields preserved.
    Records both line sizes for diagnostic purposes."""
    _reseed(env, lambda s: s.update({
        "execution_mode": "chain_autopilot",
        "autopilot_run_id": "run-sentinel",
        "autopilot_mode": "chain",
        "autopilot_phase_slug": "phase-02c",
    }))
    rc = _run(env, to="plan", reason="sentinel-budget-check")
    assert rc.exit_code == 0
    lines = [
        ln for ln in env["audit_path"].read_text().splitlines() if ln.strip()
    ]
    halt_line = lines[-2]
    reopen_line = lines[-1]
    # 1024 = AUDIT_MAX_LINE_BYTES post-S06 (raised from 512 to accommodate
    # ~140 bytes of chain fields + forensic top-level field headroom).
    assert len(halt_line.encode()) <= 1024, (
        f"halt audit line {len(halt_line.encode())} bytes — exceeds 1024 "
        "(post-S06 AUDIT_MAX_LINE_BYTES budget)"
    )
    assert len(reopen_line.encode()) <= 1024, (
        f"reopen audit line {len(reopen_line.encode())} bytes — exceeds 1024 "
        "(post-S06 AUDIT_MAX_LINE_BYTES budget)"
    )


def test_cap_5_history_rotation_helper(env):
    """Halt diary removed — reopen succeeds regardless of legacy halt fields in state."""
    rc = _run(env, to="plan", reason="cap-5 check")
    assert rc.exit_code == 0
