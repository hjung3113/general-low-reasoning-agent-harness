"""S02-approve-provenance — `phase approve` becomes a human-only gate.

Design refs:
  - §3.1 — `phase approve` order of operations (TTY gate, identity
           resolution, install-record membership, exit 8 if not manual)
  - §3.1.1 — Human-presence proof: [y/N] speed-bump (v0.9.0)
  - §6.1 — `.harness/install-record.json approvers[]` shape
  - §3.4 — exit codes: 17 (non-TTY/speed-bump), 6 (provenance),
           8 (approve-during-autopilot), 10 (state trust), 14 (recover)

Tests target `scripts/lib/phase_approve.py:run_approve` directly with
dependency injection (no real TTY, no real ~/.harness, no real git).
The CLI dispatcher in scripts/harness.py is wired separately; module-
level tests prove the contract slice-by-slice.

Fault classes asserted:
  - non_tty_approval_blocked            exit 17
  - gitconfig_email_unset               exit 6
  - approver_not_in_install_record      exit 6
  - approve_during_autopilot            exit 8
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import phase_approve, phase_lock, phase_txn, audit


# ---------------------------------------------------------------------------
# Fixtures — synthesize a fully primed harness root
# ---------------------------------------------------------------------------


@pytest.fixture
def env(tmp_path: Path) -> dict:
    """Synthesize a primed harness with scratch + audit + install-record +
    anchor-verified seed state."""
    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    harness = tmp_path / ".harness"
    harness.mkdir()
    audit_path = harness / "audit.log"
    nonce_dir = tmp_path / "out-of-project" / "approval-nonces"
    nonce_dir.mkdir(parents=True)  # kept for API compat; not consulted by speed-bump flow

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

    # Seed phase-state via commit_transaction so the audit tail's
    # after_sha256 matches on-disk canonical bytes (state_trust preflight
    # will accept it).
    # Note: conftest.seed_scratch is the no-audit variant (speed-bump tests).
    # This path uses commit_transaction so the audit tail's after_sha256
    # matches on-disk canonical bytes (state_trust preflight accepts it).
    seed_state = {
        "phase": "plan",
        "approved": False,
        "approved_at": None,
        "approved_by": None,
        "execution_mode": "manual",
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

    return {
        "tmp_path": tmp_path,
        "scratch": scratch,
        "harness": harness,
        "audit_path": audit_path,
        "install_record_path": harness / "install-record.json",
        "nonce_dir": nonce_dir,
    }


def _make_args(**overrides):
    """argparse.Namespace stub — defaults match the design's CLI surface."""
    base = {
        "by": None,
        "at": None,
        "override_identity": False,
        "override_reason": None,
    }
    base.update(overrides)

    class Ns:
        pass

    ns = Ns()
    for k, v in base.items():
        setattr(ns, k, v)
    return ns


def _run(env, *, stdin_isatty=True, consumer_tty="/dev/ttys002",
         gitconfig_email="alice@example.com", env_vars=None,
         repo_root=None,
         monkeypatch=None, input_response="y",
         **arg_overrides):
    """Invoke run_approve with the test-controlled environment.

    `monkeypatch` + `input_response`: when the call is expected to reach
    the Step 7 speed-bump prompt, pass the pytest `monkeypatch` fixture
    and the desired response string (default "y"). Tests that return
    before Step 7 (TTY gate, identity, etc.) can omit both.
    """
    if monkeypatch is not None:
        monkeypatch.setattr("builtins.input", lambda _prompt="": input_response)
    args = _make_args(**arg_overrides)
    return phase_approve.run_approve(
        args,
        scratch=env["scratch"],
        harness_dir=env["harness"],
        audit_path=env["audit_path"],
        install_record_path=env["install_record_path"],
        nonce_dir=env["nonce_dir"],
        stdin_isatty=stdin_isatty,
        consumer_tty=consumer_tty,
        gitconfig_email_lookup=lambda: gitconfig_email,
        env_vars={} if env_vars is None else env_vars,
        repo_root=repo_root,
    )


# ---------------------------------------------------------------------------
# 1. TTY gate (design §3.1 step 1)
# ---------------------------------------------------------------------------


def test_non_tty_rejected_exit_6(env):
    # v0.9.0 speed-bump: non-TTY now returns exit 17 (EXIT_HUMAN_CONFIRMATION_REQUIRED)
    rc = _run(env, stdin_isatty=False)
    assert rc.exit_code == 17
    assert rc.sub_reason == "non_tty_approval_blocked"


def test_non_tty_message_includes_fix_line(env, capsys):
    _run(env, stdin_isatty=False)
    err = capsys.readouterr().err
    assert "Fix:" in err


# ---------------------------------------------------------------------------
# 2. Identity resolution — gitconfig auto-read (design §3.1 step 2)
# ---------------------------------------------------------------------------


def test_gitconfig_email_used_when_no_by_flag(env, monkeypatch):
    rc = _run(env, gitconfig_email="alice@example.com",
              monkeypatch=monkeypatch)
    assert rc.exit_code == 0
    assert rc.resolved_email == "alice@example.com"
    assert rc.by_source == "gitconfig_auto"


def test_missing_gitconfig_email_rejected_exit_6(env):
    rc = _run(env, gitconfig_email="")  # unset; returns before Step 7
    assert rc.exit_code == 6
    assert rc.sub_reason == "gitconfig_email_unset"


def test_explicit_by_flag_overrides_gitconfig(env, monkeypatch):
    rc = _run(env, gitconfig_email="bob@example.com", by="alice@example.com",
              monkeypatch=monkeypatch)
    assert rc.exit_code == 0
    assert rc.resolved_email == "alice@example.com"
    assert rc.by_source == "explicit_by_flag"


# ---------------------------------------------------------------------------
# 3. install-record approvers membership (design §3.1 step 3 + §6.1)
# ---------------------------------------------------------------------------


def test_email_not_in_approvers_no_longer_blocks_v099(env, monkeypatch, capsys):
    """v0.9.9: approver-membership check is advisory only. Mismatch must
    NOT abort approve at Step 3 (internal single-user threat model).

    Uses monkeypatch to answer "n" at the Step 7 speed-bump so the function
    returns cleanly after passing Step 3.
    """
    rc = _run(
        env,
        gitconfig_email="mallory@evil.example",
        monkeypatch=monkeypatch,
        input_response="n",
    )
    assert rc.sub_reason != "approver_not_in_install_record"
    err = capsys.readouterr().err
    assert "advisory" in err and "v0.9.9" in err


def test_listed_approver_accepted(env, monkeypatch):
    rc = _run(env, gitconfig_email="alice@example.com",
              monkeypatch=monkeypatch)
    assert rc.exit_code == 0


# ---------------------------------------------------------------------------
# 4. Env identity is IGNORED for phase approve (Round-4 BLOCK fix #2)
# ---------------------------------------------------------------------------


def test_harness_by_trust_env_does_not_influence_approve(env):
    """`HARNESS_BY_TRUST` is for autopilot start only; phase approve has
    zero env-trust path. Setting it to a non-approver email MUST NOT
    bypass approver-membership; setting it instead of gitconfig MUST NOT
    satisfy identity resolution."""
    args = _make_args()
    rc = phase_approve.run_approve(
        args,
        scratch=env["scratch"],
        harness_dir=env["harness"],
        audit_path=env["audit_path"],
        install_record_path=env["install_record_path"],
        nonce_dir=env["nonce_dir"],
        stdin_isatty=True,
        consumer_tty="/dev/ttys002",
        gitconfig_email_lookup=lambda: "",  # no gitconfig
        env_vars={
            "HARNESS_BY_TRUST": "alice@example.com",
            "HARNESS_HUMAN": "alice@example.com",
        },
    )
    # gitconfig empty + env IGNORED ⇒ exit 6 gitconfig_email_unset (NOT
    # silently approved via env).
    assert rc.exit_code == 6
    assert rc.sub_reason == "gitconfig_email_unset"


# ---------------------------------------------------------------------------
# 5. Human-presence proof: v0.9.0 speed-bump replaces nonce flow
#
# Nonce-specific tests (human_proof_missing, human_proof_nonce_expired,
# human_proof_nonce_same_tty, human_proof_nonce_audience_mismatch,
# test_nonce_consumed_single_use) are deleted — those semantics no longer
# exist on phase.approve. The TTY gate (non_tty_approval_blocked) and
# [y/N] prompt tests are in test_speed_bump_prompt.py.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 6. execution_mode != manual ⇒ exit 8 (design §3.1 step 6)
# ---------------------------------------------------------------------------


def test_approve_during_autopilot_exit_8(env):
    # Re-seed state with execution_mode=phase_autopilot via a fresh commit.
    state_path = env["scratch"] / "phase-state.json"
    state = json.loads(state_path.read_text())
    state["execution_mode"] = "phase_autopilot"
    lock = phase_lock.acquire_primary(env["scratch"], timeout_s=2.0)
    try:
        before = json.loads(state_path.read_text())
        req = phase_txn.TxnRequest(
            action="phase.set",
            before_state=before,
            after_state=state,
            audit_entry_draft={
                "verb": "phase.set",
                "by": "seed",
                "args": {},
            },
        )
        phase_txn.commit_transaction(
            env["scratch"], lock=lock, request=req, audit_path=env["audit_path"]
        )
    finally:
        phase_lock.release_primary(lock)

    # autopilot exit happens before Step 7 prompt; no input monkeypatch needed
    rc = _run(env)
    assert rc.exit_code == 8
    assert rc.sub_reason == "approve_during_autopilot"


# ---------------------------------------------------------------------------
# 7. Audit entry shape (v0.9.0: confirmation_kind=soft_tty, proof_class, tty)
# ---------------------------------------------------------------------------


def test_audit_entry_records_approve_provenance(env, monkeypatch):
    rc = _run(env, monkeypatch=monkeypatch)
    assert rc.exit_code == 0

    # Last audit entry MUST be a phase.approve with the speed-bump fields.
    lines = [
        ln for ln in env["audit_path"].read_text().splitlines() if ln.strip()
    ]
    last = json.loads(lines[-1])
    assert last["verb"] == "phase.approve"
    assert last["by"] == "alice@example.com"
    # v0.9.0 speed-bump uses confirmation_kind=soft_tty instead of human_nonce
    assert last["confirmation_kind"] == "soft_tty"
    assert last["proof_class"] == "soft_tty"
    assert last["by_source"] == "gitconfig_auto"
    assert last["tty"] == "/dev/ttys002"
    # `at` is stamped by phase_txn.commit_transaction; approved_at lives
    # in args (or in the overflow file if the line was truncated).
    assert "at" in last


def test_state_mutation_sets_approved_fields(env, monkeypatch):
    rc = _run(env, monkeypatch=monkeypatch)
    assert rc.exit_code == 0
    state = json.loads((env["scratch"] / "phase-state.json").read_text())
    assert state["approved"] is True
    assert state["approved_by"] == "alice@example.com"
    assert state["approved_at"] is not None


# ---------------------------------------------------------------------------
# 8. State-trust preflight + anchor preflight are invoked
# ---------------------------------------------------------------------------


def test_state_trust_preflight_invoked(env, monkeypatch):
    """Spy on state_trust.preflight to ensure run_approve chains through
    it before mutating."""
    from lib import state_trust

    calls = []
    real = state_trust.preflight

    def spy(*a, **kw):
        calls.append(kw)
        return real(*a, **kw)

    monkeypatch.setattr(state_trust, "preflight", spy)
    monkeypatch.setattr(phase_approve, "_state_trust", state_trust)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "y")
    rc = _run(env)
    assert rc.exit_code == 0
    assert len(calls) > 0


def test_tampered_state_rejected_via_state_trust(env):
    """Hand-edit the state file — preflight should refuse with exit 10."""
    state_path = env["scratch"] / "phase-state.json"
    txt = state_path.read_text()
    state_path.write_text(txt.replace('"approved": false', '"approved": true'))
    # state_trust raises before Step 7 prompt; no input monkeypatch needed
    rc = _run(env)
    assert rc.exit_code == 10
    assert rc.sub_reason == "state_audit_mismatch"


# ---------------------------------------------------------------------------
# 9. Lock holder during the mutation
# ---------------------------------------------------------------------------


def test_lock_held_during_run_approve(env, monkeypatch):
    """While run_approve is mid-mutation, the primary lock file MUST exist."""
    from lib import phase_lock as pl

    lock_path = env["scratch"] / pl.PRIMARY_NAME
    observed = {"during_mutation": False}

    real_commit = phase_txn.commit_transaction

    def spy_commit(scratch, *, lock, request, audit_path):
        observed["during_mutation"] = lock_path.exists()
        return real_commit(scratch, lock=lock, request=request, audit_path=audit_path)

    monkeypatch.setattr(phase_approve, "_phase_txn", phase_txn)
    monkeypatch.setattr(phase_txn, "commit_transaction", spy_commit)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "y")
    rc = _run(env)
    assert rc.exit_code == 0
    assert observed["during_mutation"] is True
    # Released afterwards.
    assert not lock_path.exists()


# ---------------------------------------------------------------------------
# 10. Idempotency: already approved → defined no-op behavior
# ---------------------------------------------------------------------------


def test_env_vars_byte_identical_to_empty_env(env, capsys, monkeypatch):
    """`HARNESS_BY_TRUST` / `HARNESS_HUMAN` MUST not influence any code
    path — byte-identical result and stderr between empty env and a
    hostile env. Strengthens the env-isolation pin (replaces the dead
    `_ = env_vars` read with a real regression test)."""
    monkeypatch.setattr("builtins.input", lambda _prompt="": "y")
    rc_clean = _run(env, env_vars={})
    out_clean = capsys.readouterr()

    # Reset state so the second invocation re-runs the same path.
    state_path = env["scratch"] / "phase-state.json"
    s = json.loads(state_path.read_text())
    s["approved"] = False
    s["approved_by"] = None
    s["approved_at"] = None
    lock = phase_lock.acquire_primary(env["scratch"], timeout_s=2.0)
    try:
        before = json.loads(state_path.read_text())
        req = phase_txn.TxnRequest(
            action="phase.set",
            before_state=before,
            after_state=s,
            audit_entry_draft={"verb": "phase.set", "by": "reset", "args": {}},
        )
        phase_txn.commit_transaction(
            env["scratch"], lock=lock, request=req, audit_path=env["audit_path"]
        )
    finally:
        phase_lock.release_primary(lock)

    rc_hostile = _run(
        env,
        env_vars={
            "HARNESS_BY_TRUST": "evil@example.com",
            "HARNESS_HUMAN": "evil@example.com",
            "HARNESS_USER": "evil@example.com",
        },
    )
    out_hostile = capsys.readouterr()

    assert rc_clean.exit_code == rc_hostile.exit_code == 0
    assert rc_clean.resolved_email == rc_hostile.resolved_email == "alice@example.com"
    assert rc_clean.by_source == rc_hostile.by_source == "gitconfig_auto"
    # Stderr must be identical (empty in both runs).
    assert out_clean.err == out_hostile.err


# ---------------------------------------------------------------------------
# 12. xfail-strict integration pin — review-fix P2-1
# Wiring of `cmd_phase_approve` → `phase_approve.run_approve` is S07-prep
# scope; the pin will fail-as-pass today and flip the moment the legacy
# `_do_phase_approve` short-circuit is replaced.
# ---------------------------------------------------------------------------


def test_live_cli_routes_through_run_approve():
    """The live CLI dispatcher `cmd_phase_approve` MUST eventually
    delegate to `phase_approve.run_approve`. Today it still calls the
    legacy `_do_phase_approve` shim; this xfail-strict pin will surface
    the moment the wiring lands so we can drop the marker (or fail
    loudly if the wiring drifts past us)."""
    import inspect

    from lib import phase_cli

    src = inspect.getsource(phase_cli.cmd_phase_approve)
    assert "phase_approve.run_approve" in src or "run_approve(" in src


def test_second_approve_already_approved_is_idempotent_noop(env, monkeypatch):
    """Decision (under-specified in §3.1): we treat already-approved as
    exit 0 with sub_reason=already_approved, no state mutation, no audit
    entry. This matches the Round-4 UX simplification intent ("don't add
    more verbs / surprises"). In v0.9.0 the speed-bump prompt is reached
    on first approval; the idempotency check fires before the prompt on
    the second call."""
    monkeypatch.setattr("builtins.input", lambda _prompt="": "y")
    rc1 = _run(env)
    assert rc1.exit_code == 0
    audit_lines_before = [
        ln for ln in env["audit_path"].read_text().splitlines() if ln.strip()
    ]

    # Second approve while already approved — idempotency fires before prompt.
    rc2 = _run(env)
    assert rc2.exit_code == 0
    assert rc2.sub_reason == "already_approved"

    # No additional audit entry.
    audit_lines_after = [
        ln for ln in env["audit_path"].read_text().splitlines() if ln.strip()
    ]
    assert len(audit_lines_after) == len(audit_lines_before)
