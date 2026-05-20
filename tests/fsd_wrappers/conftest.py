"""Fixtures for fsd_wrappers test suite (S07-prep step 4).

Ensures scripts/ is importable for `from lib.fsd_wrappers import ...`.
Provides a shared `harness_env` fixture that bundles all required kwargs
for run_fsd_run_phase and run_fsd_run_all.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lib import approval_nonce, phase_lock, phase_txn  # noqa: E402


# ---------------------------------------------------------------------------
# Shared fixture — primed harness root (mirrors phase_autopilot conftest)
# ---------------------------------------------------------------------------


@pytest.fixture
def harness_env(tmp_path: Path) -> dict:
    """Synthesize a primed harness with scratch + audit + roadmap slugs.

    Provides:
        tmp_path, scratch, harness, audit_path, roadmap_root,
        install_record_root, nonce_dir,
        + convenience wrappers: common_kwargs() — the full passthrough
          kwargs dict for run_fsd_run_phase / run_fsd_run_all.
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

    # Roadmap: two phase directories, both pending by default.
    planning = tmp_path / ".planning" / "phases"
    planning.mkdir(parents=True)
    for slug in ("phase-alpha", "phase-beta"):
        (planning / slug).mkdir()

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

    # Nonce dir (out-of-project, mirrors phase_autopilot fixtures).
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
# Nonce + CI helpers (mirrors phase_autopilot test helpers)
# ---------------------------------------------------------------------------


def mint_nonce(nonce_dir: Path, *, minter_tty: str = "/dev/ttys001") -> approval_nonce.Nonce:
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


def fake_oidc_fetcher(url: str) -> str:
    return "fake-oidc-token"


def fake_oidc_verifier(token: str, expected_claims: dict) -> dict:
    return _FAKE_OIDC_CLAIMS_GITHUB


def ci_env_github(*, by_trust: str = "ci-bot@example.com") -> dict:
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


def common_kwargs(env: dict, *, stdin_is_tty: bool = True, mint: bool = True) -> dict:
    """Build the full passthrough kwargs dict for run_fsd_run_phase / run_fsd_run_all.

    Uses TTY path by default (stdin_is_tty=True, alice@example.com, fresh nonce).
    """
    nonce_dir = env["nonce_dir"]
    consumer_tty: str | None = None

    if stdin_is_tty and mint:
        mint_nonce(nonce_dir, minter_tty="/dev/ttys001")
        consumer_tty = "/dev/ttys002"

    return {
        "scratch_root": env["scratch"],
        "audit_path": env["audit_path"],
        "repo_root": None,
        "env": None,
        "stdin_is_tty": stdin_is_tty,
        "consumer_tty": consumer_tty,
        "nonce_audience": "phase.autopilot.start",
        "nonce_dir": nonce_dir,
        "by_email": "alice@example.com" if stdin_is_tty else None,
        "install_record_root": env["install_record_root"],
        "oidc_fetcher": fake_oidc_fetcher,
        "oidc_verifier": fake_oidc_verifier,
        "budgets": None,
        "allow_network": False,
        "accept_degraded_windows_containment": False,
        "roadmap_root": env["roadmap_root"],
    }
