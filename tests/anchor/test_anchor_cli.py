"""Tests for scripts.lib.anchor_cli helpers (review-fix BLOCK P1-1 and P2-5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import anchor_cli


def _write_audit(repo_root: Path, lines: list[str]) -> Path:
    scratch = repo_root / ".scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    path = scratch / "audit.log"
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path


def test_read_audit_tail_empty_file_returns_zero(repo_root):
    _write_audit(repo_root, [])
    h, s = anchor_cli._read_audit_tail(repo_root)
    assert h == anchor_cli.ZERO_HASH
    assert s == 0


def test_read_audit_tail_picks_last_valid_entry(repo_root):
    _write_audit(
        repo_root,
        [
            json.dumps({"seq_global": 1, "entry_hash": "a" * 64}),
            json.dumps({"seq_global": 2, "entry_hash": "b" * 64}),
        ],
    )
    h, s = anchor_cli._read_audit_tail(repo_root)
    assert h == "b" * 64
    assert s == 2


def test_read_audit_tail_raises_on_partial_write(repo_root):
    # Last line is unterminated JSON: must raise AuditTailParseError, NOT
    # silently fall back to the prior entry. Round-7 P1-1 review fix.
    _write_audit(
        repo_root,
        [
            json.dumps({"seq_global": 1, "entry_hash": "a" * 64}),
            '{"seq_global": 2, "entry_hash": "b'  # torn
        ],
    )
    with pytest.raises(anchor_cli.AuditTailParseError):
        anchor_cli._read_audit_tail(repo_root)


def test_resolve_install_id_uses_install_record(repo_root):
    rec = repo_root / ".harness" / "install-record.json"
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text(
        json.dumps({"install_id": "11111111-2222-3333-4444-555555555555"}),
        encoding="utf-8",
    )
    install_id = anchor_cli._resolve_install_id(
        repo_root, accept_no_install_record=False
    )
    assert install_id == "11111111-2222-3333-4444-555555555555"


def test_resolve_install_id_refuses_missing_without_flag(repo_root):
    with pytest.raises(anchor_cli.InstallRecordUnreadable):
        anchor_cli._resolve_install_id(repo_root, accept_no_install_record=False)


def test_resolve_install_id_refuses_missing_install_id_field(repo_root):
    rec = repo_root / ".harness" / "install-record.json"
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text(json.dumps({"adapters": ["roo"]}), encoding="utf-8")
    with pytest.raises(anchor_cli.InstallRecordUnreadable):
        anchor_cli._resolve_install_id(repo_root, accept_no_install_record=False)


def test_resolve_install_id_mints_with_bootstrap_flag(repo_root):
    install_id = anchor_cli._resolve_install_id(
        repo_root, accept_no_install_record=True
    )
    assert isinstance(install_id, str)
    assert len(install_id) > 0


def test_resolve_install_id_raises_on_unparseable_record(repo_root):
    rec = repo_root / ".harness" / "install-record.json"
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text("not-json", encoding="utf-8")
    with pytest.raises(anchor_cli.InstallRecordUnreadable):
        anchor_cli._resolve_install_id(
            repo_root, accept_no_install_record=True
        )
