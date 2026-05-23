"""T12 — `phase reopen` smoke bypass + --reset-approval (NEW-6/7).

Covers:
  (a) reopen_smoke_bypass_non_tty  — HARNESS_SMOKE_TEST=1 +
      HARNESS_SMOKE_BYPASS_SPEED_BUMP=1, non-TTY → succeeds; audit row has
      proof_class=smoke_bypass
  (b) reopen_non_tty_no_smoke_env  — non-TTY, no env → refused with
      actionable error + rc != 0
  (c) reopen_backward_without_reset_approval — approved=True, reopen without
      --reset-approval → rc != 0, message points to --reset-approval
  (d) reopen_backward_with_reset_approval — same + flag → ok + approval reset

Design refs:
  - /tmp/v095-PLAN.md REV-2 §3.7 NEW-6 + NEW-7
  - /tmp/v095-IMPL.md REV-4 T12
  - scripts/lib/phase_approve.py:282-307 (proof_class=smoke_bypass convention)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path setup — allow `from lib import ...` when running from repo root.
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lib import phase_reopen, phase_lock, phase_txn  # noqa: E402


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def env(tmp_path: Path) -> dict:
    """Primed harness root with execute-phase, approved=True state."""
    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    harness = tmp_path / ".harness"
    harness.mkdir()
    audit_path = harness / "audit.log"

    install_record = {
        "harness_version": "v0.9.5",
        "installed_at": "2026-05-21T00:00:00Z",
        "adapters": ["roo"],
        "git_present_at_install": True,
        "approvers": [
            {
                "email": "alice@example.com",
                "added_at": "2026-05-21T00:00:00Z",
                "source": "gitconfig_auto",
            }
        ],
    }
    (harness / "install-record.json").write_text(
        json.dumps(install_record, indent=2, sort_keys=True) + "\n"
    )

    seed_state = {
        "phase": "execute",
        "approved": True,
        "approved_at": "2026-05-21T08:00:00Z",
        "approved_by": "alice@example.com",
        "execution_mode": "manual",
        "state_schema_version": 2,
        "verification": ["pytest tests/ -q"],
        "allowed_paths": ["scripts/lib/foo.py"],
        "draft_verification": None,
        "draft_allowed_paths": None,
        "execute_attempt_started_at": "2026-05-21T08:05:00Z",
        "plan_finalized_at": "2026-05-21T07:55:00Z",
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


def _make_args(**overrides):
    base = {
        "by": "alice@example.com",
        "to": "plan",
        "reason": "T12 test reopen",
        "override_identity": False,
        "override_reason": None,
        "reset_approval": True,
    }
    base.update(overrides)

    class Ns:
        pass

    ns = Ns()
    for k, v in base.items():
        setattr(ns, k, v)
    return ns


def _run(
    env,
    *,
    stdin_isatty: bool = True,
    env_vars: dict | None = None,
    **arg_overrides,
):
    if env_vars is None:
        env_vars = {}
    args = _make_args(**arg_overrides)
    return phase_reopen.run_reopen(
        args,
        scratch=env["scratch"],
        harness_dir=env["harness"],
        audit_path=env["audit_path"],
        install_record_path=env["install_record_path"],
        stdin_isatty=stdin_isatty,
        gitconfig_email_lookup=lambda: "alice@example.com",
        env_vars=env_vars,
        repo_root=env["tmp_path"],
    )


# ---------------------------------------------------------------------------
# (a) Smoke bypass — non-TTY with both env vars set → succeeds +
#     audit row has proof_class=smoke_bypass
# ---------------------------------------------------------------------------


def test_reopen_smoke_bypass_non_tty(env):
    """Non-TTY caller with both smoke env vars set must succeed (NEW-6)."""
    smoke_env = {
        "HARNESS_SMOKE_TEST": "1",
        "HARNESS_SMOKE_BYPASS_SPEED_BUMP": "1",
    }
    result = _run(
        env,
        stdin_isatty=False,
        env_vars=smoke_env,
    )
    assert result.exit_code == 0, f"expected 0, got {result.exit_code} ({result.sub_reason})"
    assert result.sub_reason == "reopened"


def test_reopen_smoke_bypass_audit_has_proof_class(env):
    """Audit row emitted by smoke-bypass reopen must carry proof_class=smoke_bypass."""
    smoke_env = {
        "HARNESS_SMOKE_TEST": "1",
        "HARNESS_SMOKE_BYPASS_SPEED_BUMP": "1",
    }
    result = _run(
        env,
        stdin_isatty=False,
        env_vars=smoke_env,
    )
    assert result.exit_code == 0
    lines = [
        ln for ln in env["audit_path"].read_text().splitlines() if ln.strip()
    ]
    last = json.loads(lines[-1])
    assert last["verb"] == "phase.reopen"
    assert last.get("proof_class") == "smoke_bypass", (
        f"expected proof_class=smoke_bypass, got {last.get('proof_class')!r}"
    )


# ---------------------------------------------------------------------------
# (b) Non-TTY without smoke env → refused with actionable error + rc != 0
# ---------------------------------------------------------------------------


def test_reopen_non_tty_no_smoke_env_refused(env):
    """Non-TTY caller without smoke env must be refused (guard intact)."""
    result = _run(env, stdin_isatty=False, env_vars={})
    assert result.exit_code != 0, "expected non-zero exit code for non-TTY without smoke env"
    assert result.sub_reason == "non_tty_reopen_blocked"


def test_reopen_non_tty_no_smoke_env_error_message(env, capsys):
    """Error message for non-TTY refusal must include Fix: line."""
    _run(env, stdin_isatty=False, env_vars={})
    err = capsys.readouterr().err
    assert "Fix:" in err, f"expected 'Fix:' in stderr, got: {err!r}"
    assert "terminal" in err.lower() or "tty" in err.lower(), (
        f"expected terminal/TTY hint in stderr, got: {err!r}"
    )


def test_reopen_partial_smoke_env_still_refused(env):
    """Only HARNESS_SMOKE_TEST set (without BYPASS_SPEED_BUMP) → still refused."""
    result = _run(
        env,
        stdin_isatty=False,
        env_vars={"HARNESS_SMOKE_TEST": "1"},
    )
    assert result.exit_code != 0
    assert result.sub_reason == "non_tty_reopen_blocked"


# ---------------------------------------------------------------------------
# (c) Backward move without --reset-approval → rc != 0, actionable error
# ---------------------------------------------------------------------------


def test_reopen_backward_without_reset_approval_refused(env):
    """approved=True state + no --reset-approval → refused (NEW-7)."""
    result = _run(
        env,
        stdin_isatty=True,
        reset_approval=False,
    )
    assert result.exit_code != 0, (
        "expected refusal when approved=True and --reset-approval not set"
    )
    assert result.sub_reason == "reopen_backward_requires_reset_approval"


def test_reopen_backward_without_reset_approval_error_message(env, capsys):
    """Refusal message must point to --reset-approval flag."""
    _run(env, stdin_isatty=True, reset_approval=False)
    err = capsys.readouterr().err
    assert "--reset-approval" in err, (
        f"expected '--reset-approval' in stderr, got: {err!r}"
    )


# ---------------------------------------------------------------------------
# (d) Backward move with --reset-approval → ok + approval reset
# ---------------------------------------------------------------------------


def test_reopen_backward_with_reset_approval_succeeds(env):
    """approved=True + --reset-approval → succeeds (NEW-7)."""
    result = _run(
        env,
        stdin_isatty=True,
        reset_approval=True,
    )
    assert result.exit_code == 0, (
        f"expected 0, got {result.exit_code} ({result.sub_reason})"
    )


def test_reopen_backward_with_reset_approval_clears_approval(env):
    """After reopen with --reset-approval, approved fields are cleared."""
    result = _run(
        env,
        stdin_isatty=True,
        reset_approval=True,
    )
    assert result.exit_code == 0
    state = json.loads((env["scratch"] / "phase-state.json").read_text())
    assert state["approved"] is False
    assert state["approved_by"] is None
    assert state["approved_at"] is None


def test_reopen_backward_with_reset_approval_via_smoke_bypass(env):
    """Smoke-bypass path also honors --reset-approval flag (non-TTY + both
    env vars + reset_approval=True → ok; reset_approval=False → refused)."""
    smoke_env = {
        "HARNESS_SMOKE_TEST": "1",
        "HARNESS_SMOKE_BYPASS_SPEED_BUMP": "1",
    }
    # With reset_approval=False → refused (smoke bypass skips TTY gate, not
    # the --reset-approval guard which is a separate workflow speed-bump)
    result_refused = _run(
        env,
        stdin_isatty=False,
        env_vars=smoke_env,
        reset_approval=False,
    )
    assert result_refused.exit_code != 0
    assert result_refused.sub_reason == "reopen_backward_requires_reset_approval"

    # With reset_approval=True → succeeds
    result_ok = _run(
        env,
        stdin_isatty=False,
        env_vars=smoke_env,
        reset_approval=True,
    )
    assert result_ok.exit_code == 0
