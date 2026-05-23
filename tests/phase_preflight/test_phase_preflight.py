"""Smoke tests for `scripts/lib/phase_preflight.py` (P2-3 extraction).

Design refs:
  - §3.1 / §3.2 — shared preflight helpers used by `phase approve` and
                   `phase reopen` (and future §S07 verbs).
  - §3.9         — every error MUST carry a Fix: line.

These are smoke tests, not exhaustive coverage (the `phase_approve` and
`phase_reopen` suites exercise the helpers end-to-end). The goal is to pin
the public surface of the extracted module so regressions in the shared
helpers surface here rather than leaking into verb-specific test failures.

Note: `run_state_trust_preflight` and `StateTrustPreflightError` were removed
in M4-3 (#10) per ADR-0002 (no attacker model) and ADR-0005 (plain JSONL).
Note: `approvers_emails` and `FIX_APPROVER_MEMBERSHIP` removed in M5 #13
per ADR-0002 (no attacker model — no allowlist enforcement).
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

import pytest

from lib import phase_preflight


# ---------------------------------------------------------------------------
# now_iso_z
# ---------------------------------------------------------------------------


def test_now_iso_z_is_utc_z_format():
    ts = phase_preflight.now_iso_z()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", ts), ts


def test_now_iso_z_no_microseconds():
    ts = phase_preflight.now_iso_z()
    assert "." not in ts


# ---------------------------------------------------------------------------
# default_gitconfig_email_lookup
# ---------------------------------------------------------------------------


def test_default_gitconfig_email_lookup_returns_string():
    result = phase_preflight.default_gitconfig_email_lookup()
    assert isinstance(result, str)


def test_default_gitconfig_email_lookup_strips_whitespace():
    result = phase_preflight.default_gitconfig_email_lookup()
    assert result == result.strip()


# ---------------------------------------------------------------------------
# load_install_record
# ---------------------------------------------------------------------------


def test_load_install_record_parses_valid_json(tmp_path: Path):
    record = {"harness_version": "v0.9.0", "installed_at": "2026-01-01T00:00:00Z"}
    p = tmp_path / "install-record.json"
    p.write_text(json.dumps(record))
    loaded = phase_preflight.load_install_record(p)
    assert loaded == record


def test_load_install_record_raises_file_not_found(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        phase_preflight.load_install_record(tmp_path / "nonexistent.json")


def test_load_install_record_tolerates_legacy_approvers_field(tmp_path: Path):
    """Forward-compat: old install-records with approvers[] are silently loaded."""
    record = {
        "harness_version": "v0.7.0",
        "approvers": [{"email": "alice@example.com"}],
    }
    p = tmp_path / "install-record.json"
    p.write_text(json.dumps(record))
    loaded = phase_preflight.load_install_record(p)
    assert loaded["approvers"][0]["email"] == "alice@example.com"


# ---------------------------------------------------------------------------
# Fix-line constants — present and non-empty
# ---------------------------------------------------------------------------


def test_fix_gitconfig_constant_present_and_non_empty():
    val = phase_preflight.FIX_GITCONFIG
    assert isinstance(val, str) and val.strip()
    assert "Fix:" in val


# ---------------------------------------------------------------------------
# __all__ pin — M5 post-strip public surface
# ---------------------------------------------------------------------------


def test_all_exports_present():
    expected = {
        "FIX_GITCONFIG",
        "now_iso_z",
        "default_gitconfig_email_lookup",
        "load_install_record",
    }
    assert expected.issubset(set(phase_preflight.__all__)), (
        f"Missing from __all__: {expected - set(phase_preflight.__all__)}"
    )
