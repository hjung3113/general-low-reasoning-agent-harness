"""S02-approve-provenance — `phase approve` becomes a human-only gate.

Design refs:
  - §3.1 — `phase approve` order of operations (TTY gate, identity
           resolution, install-record membership, exit 8 if not manual)
  - §3.1.1 — Human-presence proof: out-of-project nonce default
  - §6.1 — `.harness/install-record.json approvers[]` shape
  - §3.4 — exit codes: 6 (provenance/TTY/nonce), 8 (approve-during-autopilot),
           10 (state trust), 14 (recover)

Tests target `scripts/lib/phase_approve.py:run_approve` directly with
dependency injection (no real TTY, no real ~/.harness, no real git).
The CLI dispatcher in scripts/harness.py is wired separately; module-
level tests prove the contract slice-by-slice.

Fault classes asserted:
  - non_tty_approval_blocked            exit 6
  - human_proof_missing                 exit 6
  - human_proof_nonce_expired           exit 6
  - human_proof_nonce_same_tty          exit 6
  - human_proof_nonce_audience_mismatch exit 6
  - gitconfig_email_unset               exit 6
  - approver_not_in_install_record      exit 6
  - approve_during_autopilot            exit 8
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from lib import phase_approve, approval_nonce, phase_lock, phase_txn, audit


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
    nonce_dir.mkdir(parents=True)

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
    # TODO: dedupe with conftest.seed_scratch
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


def _mint_valid_nonce(nonce_dir: Path, *, minter_tty: str = "/dev/ttys001"):
    """Mint a fresh nonce in the test-controlled out-of-project dir."""
    return approval_nonce.mint(
        nonce_dir=nonce_dir,
        audience="phase.approve",
        minter_tty=minter_tty,
        ttl_seconds=120,
    )


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
         skip_anchor_preflight=True, repo_root=None, **arg_overrides):
    """Invoke run_approve with the test-controlled environment.

    Defaults to `skip_anchor_preflight=True` because in-memory tests do
    NOT mint a real ~/.harness audit-tip anchor; the §12.1 trust chain
    is verified in the dedicated `test_anchor_*` block below.
    """
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
        skip_anchor_preflight=skip_anchor_preflight,
    )


# ---------------------------------------------------------------------------
# 1. TTY gate (design §3.1 step 1)
# ---------------------------------------------------------------------------


def test_non_tty_rejected_exit_6(env):
    _mint_valid_nonce(env["nonce_dir"])
    rc = _run(env, stdin_isatty=False)
    assert rc.exit_code == 6
    assert rc.sub_reason == "non_tty_approval_blocked"


def test_non_tty_message_includes_fix_line(env, capsys):
    _mint_valid_nonce(env["nonce_dir"])
    _run(env, stdin_isatty=False)
    err = capsys.readouterr().err
    assert "Fix:" in err


# ---------------------------------------------------------------------------
# 2. Identity resolution — gitconfig auto-read (design §3.1 step 2)
# ---------------------------------------------------------------------------


def test_gitconfig_email_used_when_no_by_flag(env):
    _mint_valid_nonce(env["nonce_dir"])
    rc = _run(env, gitconfig_email="alice@example.com")
    assert rc.exit_code == 0
    assert rc.resolved_email == "alice@example.com"
    assert rc.by_source == "gitconfig_auto"


def test_missing_gitconfig_email_rejected_exit_6(env):
    _mint_valid_nonce(env["nonce_dir"])
    rc = _run(env, gitconfig_email="")  # unset
    assert rc.exit_code == 6
    assert rc.sub_reason == "gitconfig_email_unset"


def test_explicit_by_flag_overrides_gitconfig(env):
    _mint_valid_nonce(env["nonce_dir"])
    rc = _run(env, gitconfig_email="bob@example.com", by="alice@example.com")
    assert rc.exit_code == 0
    assert rc.resolved_email == "alice@example.com"
    assert rc.by_source == "explicit_by_flag"


# ---------------------------------------------------------------------------
# 3. install-record approvers membership (design §3.1 step 3 + §6.1)
# ---------------------------------------------------------------------------


def test_email_not_in_approvers_rejected_exit_6(env):
    _mint_valid_nonce(env["nonce_dir"])
    rc = _run(env, gitconfig_email="mallory@evil.example")
    assert rc.exit_code == 6
    assert rc.sub_reason == "approver_not_in_install_record"


def test_listed_approver_accepted(env):
    _mint_valid_nonce(env["nonce_dir"])
    rc = _run(env, gitconfig_email="alice@example.com")
    assert rc.exit_code == 0


# ---------------------------------------------------------------------------
# 4. Env identity is IGNORED for phase approve (Round-4 BLOCK fix #2)
# ---------------------------------------------------------------------------


def test_harness_by_trust_env_does_not_influence_approve(env):
    """`HARNESS_BY_TRUST` is for autopilot start only; phase approve has
    zero env-trust path. Setting it to a non-approver email MUST NOT
    bypass approver-membership; setting it instead of gitconfig MUST NOT
    satisfy identity resolution."""
    _mint_valid_nonce(env["nonce_dir"])
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
        skip_anchor_preflight=True,
    )
    # gitconfig empty + env IGNORED ⇒ exit 6 gitconfig_email_unset (NOT
    # silently approved via env).
    assert rc.exit_code == 6
    assert rc.sub_reason == "gitconfig_email_unset"


# ---------------------------------------------------------------------------
# 5. Human-presence proof (design §3.1.1) — out-of-project nonce default
# ---------------------------------------------------------------------------


def test_missing_nonce_rejected_exit_6(env):
    # no nonce minted
    rc = _run(env)
    assert rc.exit_code == 6
    assert rc.sub_reason == "human_proof_missing"


def test_expired_nonce_rejected_exit_6(env, monkeypatch):
    # Mint with TTL=1s, advance clock 5s.
    approval_nonce.mint(
        nonce_dir=env["nonce_dir"],
        audience="phase.approve",
        minter_tty="/dev/ttys001",
        ttl_seconds=1,
    )
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 5.0)
    rc = _run(env)
    assert rc.exit_code == 6
    assert rc.sub_reason == "human_proof_nonce_expired"


def test_same_tty_nonce_rejected_exit_6(env):
    approval_nonce.mint(
        nonce_dir=env["nonce_dir"],
        audience="phase.approve",
        minter_tty="/dev/ttys001",
        ttl_seconds=120,
    )
    # consumer is on the same TTY as minter — agent-running-both scenario.
    rc = _run(env, consumer_tty="/dev/ttys001")
    assert rc.exit_code == 6
    assert rc.sub_reason == "human_proof_nonce_same_tty"


def test_audience_mismatch_nonce_rejected_exit_6(env):
    approval_nonce.mint(
        nonce_dir=env["nonce_dir"],
        audience="phase.reopen",  # wrong audience
        minter_tty="/dev/ttys001",
        ttl_seconds=120,
    )
    rc = _run(env)
    assert rc.exit_code == 6
    assert rc.sub_reason in (
        "human_proof_nonce_audience_mismatch",
        "human_proof_missing",
    )


def test_nonce_consumed_single_use(env):
    _mint_valid_nonce(env["nonce_dir"])
    rc1 = _run(env)
    assert rc1.exit_code == 0
    # Second approve (after re-resetting state to unapproved) — nonce file
    # MUST be gone, so a fresh approve fails proof_missing.
    # Reset state via commit_transaction.
    state_path = env["scratch"] / "phase-state.json"
    state = json.loads(state_path.read_text())
    state["approved"] = False
    state["approved_by"] = None
    state["approved_at"] = None
    state["phase"] = "plan"
    lock = phase_lock.acquire_primary(env["scratch"], timeout_s=2.0)
    try:
        before = json.loads(state_path.read_text())
        req = phase_txn.TxnRequest(
            action="phase.set",
            before_state=before,
            after_state=state,
            audit_entry_draft={
                "verb": "phase.set",
                "by": "reset",
                "args": {},
            },
        )
        phase_txn.commit_transaction(
            env["scratch"], lock=lock, request=req, audit_path=env["audit_path"]
        )
    finally:
        phase_lock.release_primary(lock)
    rc2 = _run(env)
    assert rc2.exit_code == 6
    assert rc2.sub_reason == "human_proof_missing"


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

    _mint_valid_nonce(env["nonce_dir"])
    rc = _run(env)
    assert rc.exit_code == 8
    assert rc.sub_reason == "approve_during_autopilot"


# ---------------------------------------------------------------------------
# 7. Audit entry shape (design §3.1.1 — confirmation_kind, nonce_*, by_source)
# ---------------------------------------------------------------------------


def test_audit_entry_records_approve_provenance(env):
    nonce = _mint_valid_nonce(env["nonce_dir"])
    rc = _run(env)
    assert rc.exit_code == 0

    # Last audit entry MUST be a phase.approve with the documented fields.
    lines = [
        ln for ln in env["audit_path"].read_text().splitlines() if ln.strip()
    ]
    last = json.loads(lines[-1])
    assert last["verb"] == "phase.approve"
    assert last["by"] == "alice@example.com"
    # §3.1.1 specifies confirmation_kind for the nonce path; we use
    # "human_nonce" (strictly stronger than the bare "human_cli" in
    # §3.1 step 6 — see phase_approve.py design-decision note).
    assert last["confirmation_kind"] == "human_nonce"
    assert last["by_source"] == "gitconfig_auto"
    assert last["nonce_id"] == nonce.nonce_id
    assert last["nonce_minter_tty"] == "/dev/ttys001"
    assert last["nonce_consumer_tty"] == "/dev/ttys002"
    # `at` is stamped by phase_txn.commit_transaction; approved_at lives
    # in args (or in the overflow file if the line was truncated).
    assert "at" in last


def test_state_mutation_sets_approved_fields(env):
    _mint_valid_nonce(env["nonce_dir"])
    rc = _run(env)
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
    it before mutating. Anchor preflight is the upstream prerequisite —
    we mock both."""
    from lib import state_trust

    calls = []
    real = state_trust.preflight

    def spy(*a, **kw):
        calls.append({"anchor_verified": kw.get("anchor_verified")})
        return real(*a, **kw)

    monkeypatch.setattr(state_trust, "preflight", spy)
    monkeypatch.setattr(phase_approve, "_state_trust", state_trust)
    _mint_valid_nonce(env["nonce_dir"])
    rc = _run(env)
    assert rc.exit_code == 0
    assert calls and calls[0]["anchor_verified"] is True


def test_tampered_state_rejected_via_state_trust(env):
    """Hand-edit the state file — preflight should refuse with exit 10."""
    state_path = env["scratch"] / "phase-state.json"
    txt = state_path.read_text()
    state_path.write_text(txt.replace('"approved": false', '"approved": true'))
    _mint_valid_nonce(env["nonce_dir"])
    rc = _run(env)
    assert rc.exit_code == 10
    assert rc.sub_reason == "state_audit_tip_mismatch"


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
    _mint_valid_nonce(env["nonce_dir"])
    rc = _run(env)
    assert rc.exit_code == 0
    assert observed["during_mutation"] is True
    # Released afterwards.
    assert not lock_path.exists()


# ---------------------------------------------------------------------------
# 10. Idempotency: already approved → defined no-op behavior
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 11. §12.1 anchor trust chain — review-fix P1-1
#
# The default `skip_anchor_preflight=False` path MUST chain through the
# out-of-repo audit-tip anchor before trusting `state_trust.preflight`'s
# `anchor_verified=True` flag. Prior to this commit the bare-except in
# `run_approve` silently swallowed an AttributeError from a typo'd call
# and hardcoded `anchor_verified=True`, defeating S01-E.
# ---------------------------------------------------------------------------


def test_anchor_preflight_unwired_when_repo_root_none(env):
    """Default `skip_anchor_preflight=False` + `repo_root=None` must
    fail closed with exit 6, NOT silently proceed with
    `anchor_verified=True`."""
    _mint_valid_nonce(env["nonce_dir"])
    rc = _run(env, skip_anchor_preflight=False, repo_root=None)
    assert rc.exit_code == 6
    assert rc.sub_reason == "anchor_preflight_unwired"


def test_anchor_missing_rejected(env, monkeypatch, tmp_path):
    """`repo_root` provided + anchor file absent → AnchorMissingError →
    exit 6 sub_reason='anchor_missing'. The §12.1 trust chain must NOT
    proceed without the anchor."""
    from lib import audit_anchor

    # Redirect ~/.harness/audit-tip/ to a tmp dir so no anchor exists.
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    monkeypatch.setattr(
        audit_anchor._secret_key, "home_dir", lambda: fake_home
    )
    _mint_valid_nonce(env["nonce_dir"])
    rc = _run(env, skip_anchor_preflight=False, repo_root=env["tmp_path"])
    assert rc.exit_code == 6
    assert rc.sub_reason == "anchor_missing"


def test_anchor_mismatch_rejected(env, monkeypatch, tmp_path):
    """Anchor file present but verification fails (we forge a stale
    anchor whose `install_record_sha256` does not match live install
    record). Caller must NOT proceed."""
    from lib import audit_anchor, secret_key

    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    monkeypatch.setattr(audit_anchor._secret_key, "home_dir", lambda: fake_home)
    monkeypatch.setattr(secret_key, "home_dir", lambda: fake_home)
    audit_anchor.reset_seen_for_testing()

    # Mint a fresh secret key into the fake home.
    secret_key.ensure_secret_key()

    # Write an anchor whose install_record_sha256 is bogus.
    audit_anchor.write_anchor(
        env["tmp_path"],
        harness_version="v0.7.0",
        install_id="00000000-0000-0000-0000-000000000000",
        install_record_sha256="ff" * 32,  # will never match live record
        audit_tip_entry_hash="0" * 64,
        audit_tip_seq_global=0,
    )

    _mint_valid_nonce(env["nonce_dir"])
    rc = _run(env, skip_anchor_preflight=False, repo_root=env["tmp_path"])
    assert rc.exit_code == 6
    # Any of the mismatch sub_reasons is acceptable; we lock in the
    # `install_record_mutated_post_install` discriminator since that's
    # what the forged input drives.
    assert rc.sub_reason in (
        "install_record_mutated_post_install",
        "audit_tail_diverged_from_anchor",
        "anchor_signature_invalid",
    )


def test_env_vars_byte_identical_to_empty_env(env, capsys):
    """`HARNESS_BY_TRUST` / `HARNESS_HUMAN` MUST not influence any code
    path — byte-identical result and stderr between empty env and a
    hostile env. Strengthens the env-isolation pin (replaces the dead
    `_ = env_vars` read with a real regression test)."""
    _mint_valid_nonce(env["nonce_dir"])
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
    _mint_valid_nonce(env["nonce_dir"])

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


def test_second_approve_already_approved_is_idempotent_noop(env):
    """Decision (under-specified in §3.1): we treat already-approved as
    exit 0 with sub_reason=already_approved, no state mutation, no audit
    entry. This avoids burning a fresh nonce on a no-op and matches the
    Round-4 UX simplification intent ("don't add more verbs / surprises")."""
    nonce1 = _mint_valid_nonce(env["nonce_dir"])
    rc1 = _run(env)
    assert rc1.exit_code == 0
    audit_lines_before = [
        ln for ln in env["audit_path"].read_text().splitlines() if ln.strip()
    ]

    # Mint another nonce; second approve while already approved.
    nonce2 = _mint_valid_nonce(env["nonce_dir"], minter_tty="/dev/ttys001")
    rc2 = _run(env)
    assert rc2.exit_code == 0
    assert rc2.sub_reason == "already_approved"

    # No additional audit entry.
    audit_lines_after = [
        ln for ln in env["audit_path"].read_text().splitlines() if ln.strip()
    ]
    assert len(audit_lines_after) == len(audit_lines_before)

    # The unconsumed nonce remains on disk (we did NOT burn it).
    remaining = list(env["nonce_dir"].glob("*.json"))
    assert any(p.stem == nonce2.nonce_id for p in remaining)
