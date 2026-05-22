"""T7 / NEW-1 — fresh `harness init` bootstraps .harness/install-record.json.

Tests:
  - test_init_with_approver_email_flag           CLI --approver-email writes record
  - test_init_falls_back_to_env                  HARNESS_INSTALL_APPROVER env used
  - test_init_falls_back_to_git_config           git config user.email used
  - test_init_refuses_when_all_empty             all sources empty → non-zero exit
  - test_install_record_audit_row                audit.log has install_record.bootstrap
  - test_init_idempotent_preserves_existing      re-init preserves existing record
  - test_phase_approve_works_after_init          smoke bypass approve succeeds rc=0
  - test_sanitization                            control chars / multi-line → refuse
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lib.install import (  # noqa: E402
    resolve_approver_email,
    write_install_record,
    _sanitize_approver_email,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_git_email(email: str):
    """Context manager: stub subprocess.run to return email for git config."""
    import subprocess

    class _FakeResult:
        returncode = 0
        stdout = email + "\n"

    def fake_run(cmd, **kwargs):
        if "git" in cmd and "config" in cmd and "user.email" in cmd:
            return _FakeResult()
        # For other subprocess calls (git rev-parse etc.) in write_install_record
        r = _FakeResult()
        r.stdout = ""
        return r

    return patch.object(subprocess, "run", side_effect=fake_run)


# ---------------------------------------------------------------------------
# Unit tests for resolve_approver_email
# ---------------------------------------------------------------------------


def test_init_with_approver_email_flag():
    """--approver-email flag is highest priority."""
    email, source = resolve_approver_email(cli_flag="Alice@Example.COM", env={})
    assert email == "alice@example.com"
    assert source == "cli-flag"


def test_init_falls_back_to_env():
    """HARNESS_INSTALL_APPROVER env used when no CLI flag."""
    env = {"HARNESS_INSTALL_APPROVER": "E@F.G"}
    with _fake_git_email("should-not-be-used@x.com"):
        email, source = resolve_approver_email(cli_flag=None, env=env)
    assert email == "e@f.g"
    assert source == "env"


def test_init_falls_back_to_git_config():
    """git config user.email used when no flag/env."""
    import subprocess

    class _R:
        returncode = 0
        stdout = "H@I.J\n"

    def fake_run(cmd, **kwargs):
        r = _R()
        r.stdout = "h@i.j\n" if "user.email" in cmd else ""
        return r

    with patch.object(subprocess, "run", side_effect=fake_run):
        email, source = resolve_approver_email(cli_flag=None, env={})
    assert email == "h@i.j"
    assert source == "git-config"


def test_init_falls_back_to_auto_when_all_empty():
    """v0.9.9: no flag/env/git → auto-derived identity, NOT SystemExit.

    Replaces the prior v0.9.5-era 'refuse on empty' assertion. Internal
    single-user tool — approver requirement was workflow theater, killed in
    v0.9.9 (memory feedback_internal_only_threat_model).
    """
    import subprocess

    class _R:
        returncode = 1
        stdout = ""

    with patch.object(subprocess, "run", return_value=_R()):
        email, source = resolve_approver_email(cli_flag=None, env={})
    assert source == "auto"
    assert "@" in email
    assert email.islower()


# ---------------------------------------------------------------------------
# Sanitization edge cases
# ---------------------------------------------------------------------------


def test_sanitization():
    """Control chars, multi-line, NUL → ValueError."""
    bad_cases = [
        "foo\nbar@x.com",          # newline
        "foo\rbar@x.com",          # carriage return
        "foo\x00bar@x.com",        # NUL
        "foo\x1bbar@x.com",        # ESC
        "",                        # empty
        "   ",                     # whitespace only
    ]
    for bad in bad_cases:
        with pytest.raises(ValueError, match="."):
            _sanitize_approver_email(bad)

    # Valid cases should not raise
    assert _sanitize_approver_email("  Alice@Example.COM  ") == "alice@example.com"


# ---------------------------------------------------------------------------
# Integration tests for write_install_record
# ---------------------------------------------------------------------------


def _make_target(tmp_path: Path) -> Path:
    """Return a temp target dir with .harness/ pre-created."""
    target = tmp_path / "project"
    target.mkdir()
    (target / ".harness").mkdir()
    return target


def test_install_record_written(tmp_path):
    """write_install_record creates a valid install-record.json."""
    target = _make_target(tmp_path)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(returncode=0, stdout="abc123\n")
        write_install_record(
            target=target,
            approver_email="test@example.com",
            bootstrap_source="cli-flag",
            harness_version="0.9.5",
            root=REPO_ROOT,
        )

    record_path = target / ".harness" / "install-record.json"
    assert record_path.exists()
    data = json.loads(record_path.read_text())
    assert data["schema_version"] == 1
    assert data["bootstrap_source"] == "cli-flag"
    assert data["harness_version"] == "0.9.5"
    approvers = data["approvers"]
    assert len(approvers) == 1
    assert approvers[0]["email"] == "test@example.com"
    assert approvers[0]["source"] == "bootstrap"


def test_install_record_audit_row(tmp_path):
    """write_install_record appends install_record.bootstrap to audit.log."""
    target = _make_target(tmp_path)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(returncode=0, stdout="abc123\n")
        write_install_record(
            target=target,
            approver_email="audit@example.com",
            bootstrap_source="env",
            harness_version="0.9.5",
            root=REPO_ROOT,
        )

    audit_path = target / ".harness" / "audit.log"
    assert audit_path.exists()
    last_line = audit_path.read_text().strip().splitlines()[-1]
    entry = json.loads(last_line)
    assert entry["verb"] == "install_record.bootstrap"
    assert entry["actor"] == "audit@example.com"
    assert entry["args"]["bootstrap_source"] == "env"
    assert entry["args"]["approver_count"] == 1


def test_init_idempotent_preserves_existing_install_record(tmp_path):
    """Re-running write_install_record does NOT overwrite existing record."""
    target = _make_target(tmp_path)
    record_path = target / ".harness" / "install-record.json"

    # Write a "pre-existing" record with a different approver
    original = {
        "schema_version": 1,
        "approvers": [{"email": "original@example.com", "added_at": "2026-01-01T00:00:00Z", "source": "bootstrap"}],
    }
    record_path.write_text(json.dumps(original))

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(returncode=0, stdout="abc123\n")
        write_install_record(
            target=target,
            approver_email="new@example.com",
            bootstrap_source="cli-flag",
            harness_version="0.9.5",
            root=REPO_ROOT,
        )

    # Record should still have the original approver
    data = json.loads(record_path.read_text())
    assert data["approvers"][0]["email"] == "original@example.com"
    # Audit log should NOT have a bootstrap row (idempotent: no write happened)
    audit_path = target / ".harness" / "audit.log"
    if audit_path.exists():
        content = audit_path.read_text()
        assert "install_record.bootstrap" not in content


# ---------------------------------------------------------------------------
# Integration: phase approve works after init (smoke-bypass path)
# ---------------------------------------------------------------------------


def test_phase_approve_works_after_init(tmp_path, monkeypatch):
    """With HARNESS_SMOKE_TEST=1 + HARNESS_SMOKE_BYPASS_SPEED_BUMP=1,
    phase approve succeeds (rc=0) after init writes install-record."""
    monkeypatch.setenv("HARNESS_SMOKE_TEST", "1")
    monkeypatch.setenv("HARNESS_SMOKE_BYPASS_SPEED_BUMP", "1")

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    audit_path = harness_dir / "audit.log"
    nonce_dir = tmp_path / "nonces"
    nonce_dir.mkdir()

    # Write install-record with the bootstrap path
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(returncode=0, stdout="abc\n")
        write_install_record(
            target=tmp_path,
            approver_email="smoker@example.com",
            bootstrap_source="cli-flag",
            harness_version="0.9.5",
            root=REPO_ROOT,
        )

    # Seed phase state
    from lib import phase_txn
    seed_state = {
        "phase": "plan",
        "approved": False,
        "approved_at": None,
        "approved_by": None,
        "execution_mode": "manual",
        "state_schema_version": 2,
    }
    state_path = scratch / phase_txn.STATE_NAME
    state_path.write_bytes(phase_txn._canonical_bytes(seed_state))

    from lib import phase_approve, exitcodes

    result = phase_approve.run_approve(
        SimpleNamespace(by=None),
        scratch=scratch,
        harness_dir=harness_dir,
        audit_path=audit_path,
        install_record_path=harness_dir / "install-record.json",
        nonce_dir=nonce_dir,
        stdin_isatty=False,
        consumer_tty="",
        gitconfig_email_lookup=lambda: "smoker@example.com",
        skip_state_trust_preflight=True,
    )

    assert result.exit_code == exitcodes.EXIT_OK, (
        f"Expected EXIT_OK, got {result.exit_code} (sub_reason={result.sub_reason})"
    )
