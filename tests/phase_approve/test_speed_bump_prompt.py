"""Tests for the v0.9.0 [y/N] speed-bump replacement of the nonce flow."""
from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from lib import exitcodes, phase_approve, phase_lock, phase_txn


def _stub_args(**overrides):
    base = dict(by=None, dry_run=False)
    base.update(overrides)
    return SimpleNamespace(**base)


def _seed_scratch(scratch: Path, audit_path: Path) -> None:
    """Bootstrap a minimal phase_state so state_trust preflight passes."""
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


def test_phase_approve_prompts_and_stamps_on_y(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("y\n"))
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
    _seed_scratch(scratch, audit_path)

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
    )

    assert result.exit_code == exitcodes.EXIT_OK
    assert "y/N" in captured["prompt"]
    assert audit_path.exists()
    last_line = audit_path.read_text().strip().splitlines()[-1]
    assert "soft_tty" in last_line
