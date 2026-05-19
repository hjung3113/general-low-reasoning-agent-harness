"""Tests for the v0.9.0 [y/N] speed-bump replacement of the nonce flow."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from lib import exitcodes, phase_approve
from tests.phase_approve.conftest import seed_scratch


def _stub_args(**overrides):
    base = dict(by=None)
    base.update(overrides)
    return SimpleNamespace(**base)


def _setup(tmp_path: Path):
    """Shared setup helper: creates standard directory layout for tests."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    audit_path = harness_dir / "audit.log"
    install_record = harness_dir / "install.json"
    install_record.write_text(
        json.dumps({
            "approvers": [
                {"email": "u@example.com", "added_at": "2026-01-01T00:00:00Z", "source": "gitconfig_auto"}
            ]
        })
    )
    nonce_dir = tmp_path / "nonces"
    nonce_dir.mkdir()
    return scratch, harness_dir, audit_path, install_record, nonce_dir


def test_phase_approve_prompts_and_stamps_on_y(tmp_path, monkeypatch):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    audit_path = harness_dir / "audit.log"
    install_record = harness_dir / "install.json"
    install_record.write_text(
        json.dumps({"approvers": [{"email": "u@example.com", "added_at": "2026-01-01T00:00:00Z", "source": "gitconfig_auto"}]})
    )
    nonce_dir = tmp_path / "nonces"
    nonce_dir.mkdir()

    # Bootstrap scratch state so state_trust preflight passes
    seed_scratch(scratch, audit_path)

    captured = {}

    def fake_input(prompt: str = "") -> str:
        captured["prompt"] = prompt
        return "y"

    monkeypatch.setattr("builtins.input", fake_input)

    result = phase_approve.run_approve(
        _stub_args(),
        scratch=scratch,
        harness_dir=harness_dir,
        audit_path=audit_path,
        install_record_path=install_record,
        nonce_dir=nonce_dir,
        stdin_isatty=True,
        consumer_tty="/dev/ttys000",
        gitconfig_email_lookup=lambda: "u@example.com",
        skip_anchor_preflight=True,
        skip_state_trust_preflight=True,
    )

    assert result.exit_code == exitcodes.EXIT_OK
    assert "y/N" in captured["prompt"]
    assert audit_path.exists()
    last_line = audit_path.read_text().strip().splitlines()[-1]
    assert "soft_tty" in last_line


def test_phase_approve_non_tty_halts_with_exit_17(tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    audit_path = harness_dir / "audit.log"
    install_record = harness_dir / "install.json"
    install_record.write_text(
        json.dumps({"approvers": [{"email": "u@example.com", "added_at": "2026-01-01T00:00:00Z", "source": "gitconfig_auto"}]})
    )
    nonce_dir = tmp_path / "nonces"
    nonce_dir.mkdir()

    result = phase_approve.run_approve(
        _stub_args(),
        scratch=scratch,
        harness_dir=harness_dir,
        audit_path=audit_path,
        install_record_path=install_record,
        nonce_dir=nonce_dir,
        stdin_isatty=False,
        consumer_tty="",
        gitconfig_email_lookup=lambda: "u@example.com",
        skip_anchor_preflight=True,
    )

    assert result.exit_code == exitcodes.EXIT_HUMAN_CONFIRMATION_REQUIRED
    assert result.sub_reason == "non_tty_approval_blocked"
    assert not audit_path.exists() or audit_path.read_text() == ""


def test_phase_approve_cancels_cleanly_on_capital_n(tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt="": "N")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    audit_path = harness_dir / "audit.log"
    install_record = harness_dir / "install.json"
    install_record.write_text(
        json.dumps({"approvers": [{"email": "u@example.com", "added_at": "2026-01-01T00:00:00Z", "source": "gitconfig_auto"}]})
    )
    nonce_dir = tmp_path / "nonces"
    nonce_dir.mkdir()

    # Bootstrap scratch state so state_trust preflight passes
    seed_scratch(scratch, audit_path)

    result = phase_approve.run_approve(
        _stub_args(),
        scratch=scratch,
        harness_dir=harness_dir,
        audit_path=audit_path,
        install_record_path=install_record,
        nonce_dir=nonce_dir,
        stdin_isatty=True,
        consumer_tty="/dev/ttys000",
        gitconfig_email_lookup=lambda: "u@example.com",
        skip_anchor_preflight=True,
        skip_state_trust_preflight=True,
    )

    assert result.exit_code == exitcodes.EXIT_OK
    assert result.sub_reason == "user_cancelled"
    assert not audit_path.exists() or audit_path.read_text() == ""


def test_phase_approve_in_done_phase_refuses(tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _="": "y")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    audit_path = harness_dir / "audit.log"
    install_record = harness_dir / "install.json"
    install_record.write_text(
        json.dumps({"approvers": [{"email": "u@example.com", "added_at": "2026-01-01T00:00:00Z", "source": "gitconfig_auto"}]})
    )
    nonce_dir = tmp_path / "nonces"
    nonce_dir.mkdir()

    # Seed scratch in done phase — no further state to stamp
    from lib import phase_txn
    seed_state = {
        "phase": "done",
        "approved": False,
        "approved_at": None,
        "approved_by": None,
        "execution_mode": "manual",
        "state_schema_version": 2,
    }
    state_path = scratch / phase_txn.STATE_NAME
    state_path.write_bytes(phase_txn._canonical_bytes(seed_state))

    result = phase_approve.run_approve(
        _stub_args(),
        scratch=scratch,
        harness_dir=harness_dir,
        audit_path=audit_path,
        install_record_path=install_record,
        nonce_dir=nonce_dir,
        stdin_isatty=True,
        consumer_tty="/dev/ttys000",
        gitconfig_email_lookup=lambda: "u@example.com",
        skip_anchor_preflight=True,
        skip_state_trust_preflight=True,
    )

    assert result.exit_code == exitcodes.EXIT_WRONG_PHASE_FOR_VERB
    assert result.sub_reason == "approve_in_done"


def test_smoke_bypass_only_when_both_env_vars_set(tmp_path, monkeypatch):
    """Smoke bypass refuses to activate when only one of the two env vars is set."""
    monkeypatch.setenv("HARNESS_SMOKE_BYPASS_SPEED_BUMP", "1")
    monkeypatch.delenv("HARNESS_SMOKE_TEST", raising=False)
    scratch, harness_dir, audit_path, install_record, nonce_dir = _setup(tmp_path)
    result = phase_approve.run_approve(
        _stub_args(),
        scratch=scratch,
        harness_dir=harness_dir,
        audit_path=audit_path,
        install_record_path=install_record,
        nonce_dir=nonce_dir,
        stdin_isatty=False,
        consumer_tty="",
        gitconfig_email_lookup=lambda: "u@example.com",
    )
    assert result.exit_code == exitcodes.EXIT_HUMAN_CONFIRMATION_REQUIRED
    assert result.sub_reason == "non_tty_approval_blocked"


def test_cancel_prints_stderr_message(tmp_path, monkeypatch, capsys):
    """Non-y response must print a cancellation message to stderr (X5/HIGH-6)."""
    monkeypatch.setattr("builtins.input", lambda _="": "N")
    scratch, harness_dir, audit_path, install_record, nonce_dir = _setup(tmp_path)
    seed_scratch(scratch, audit_path)
    result = phase_approve.run_approve(
        _stub_args(),
        scratch=scratch,
        harness_dir=harness_dir,
        audit_path=audit_path,
        install_record_path=install_record,
        nonce_dir=nonce_dir,
        stdin_isatty=True,
        consumer_tty="/dev/ttys000",
        gitconfig_email_lookup=lambda: "u@example.com",
        skip_anchor_preflight=True,
        skip_state_trust_preflight=True,
    )
    captured = capsys.readouterr()
    assert result.exit_code == exitcodes.EXIT_OK
    assert result.sub_reason == "user_cancelled"
    assert "cancelled" in captured.err.lower()


def test_tty_kind_classification():
    """_tty_kind must classify all four cases correctly (X8/HIGH-B-2)."""
    from lib.phase_approve import _tty_kind
    assert _tty_kind("") == "unknown"
    assert _tty_kind("/dev/ttys000") == "posix-real"
    assert _tty_kind("win:12345:abcd1234") == "win-synthetic"
    assert _tty_kind("garbage") == "unknown"


def test_smoke_bypass_active_when_both_env_vars_set(tmp_path, monkeypatch):
    """Smoke bypass active: skips TTY check + prompt, writes smoke_bypass audit row."""
    monkeypatch.setenv("HARNESS_SMOKE_BYPASS_SPEED_BUMP", "1")
    monkeypatch.setenv("HARNESS_SMOKE_TEST", "1")
    scratch, harness_dir, audit_path, install_record, nonce_dir = _setup(tmp_path)
    # seed_scratch writes canonical state; use skip_state_trust_preflight=True
    # because seed_scratch intentionally does NOT write an audit chain entry.
    seed_scratch(scratch, audit_path)
    result = phase_approve.run_approve(
        _stub_args(),
        scratch=scratch,
        harness_dir=harness_dir,
        audit_path=audit_path,
        install_record_path=install_record,
        nonce_dir=nonce_dir,
        stdin_isatty=False,
        consumer_tty="",
        gitconfig_email_lookup=lambda: "u@example.com",
        skip_anchor_preflight=True,
        skip_state_trust_preflight=True,
    )
    assert result.exit_code == exitcodes.EXIT_OK
    assert result.sub_reason == "approved"
    last = audit_path.read_text().strip().splitlines()[-1]
    assert "smoke_bypass" in last
