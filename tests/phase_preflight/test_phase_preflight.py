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
    record = {"approvers": [{"email": "alice@example.com"}]}
    p = tmp_path / "install-record.json"
    p.write_text(json.dumps(record))
    loaded = phase_preflight.load_install_record(p)
    assert loaded == record


def test_load_install_record_raises_file_not_found(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        phase_preflight.load_install_record(tmp_path / "nonexistent.json")


# ---------------------------------------------------------------------------
# approvers_emails
# ---------------------------------------------------------------------------


def test_approvers_emails_returns_lower_cased():
    record = {
        "approvers": [
            {"email": "Alice@Example.COM"},
            {"email": "BOB@example.com"},
        ]
    }
    emails = phase_preflight.approvers_emails(record)
    assert emails == ["alice@example.com", "bob@example.com"]


def test_approvers_emails_skips_non_dict_entries():
    record = {"approvers": ["notadict", {"email": "carol@example.com"}, None]}
    emails = phase_preflight.approvers_emails(record)
    assert emails == ["carol@example.com"]


def test_approvers_emails_empty_when_no_key():
    assert phase_preflight.approvers_emails({}) == []


def test_approvers_emails_skips_entries_with_empty_email():
    record = {"approvers": [{"email": ""}, {"email": "valid@example.com"}]}
    emails = phase_preflight.approvers_emails(record)
    assert emails == ["valid@example.com"]


# ---------------------------------------------------------------------------
# Fix-line constants — present and non-empty
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("const_name", [
    "FIX_GITCONFIG",
    "FIX_APPROVER_MEMBERSHIP",
])
def test_fix_line_constant_present_and_non_empty(const_name):
    val = getattr(phase_preflight, const_name)
    assert isinstance(val, str) and val.strip(), f"{const_name} must be a non-empty string"
    assert "Fix:" in val, f"{const_name} must contain 'Fix:' per §3.9"


# ---------------------------------------------------------------------------
# __all__ pin — M4 post-strip public surface
# ---------------------------------------------------------------------------


def test_all_exports_present():
    expected = {
        "FIX_GITCONFIG",
        "FIX_APPROVER_MEMBERSHIP",
        "now_iso_z",
        "default_gitconfig_email_lookup",
        "load_install_record",
        "approvers_emails",
    }
    assert expected.issubset(set(phase_preflight.__all__)), (
        f"Missing from __all__: {expected - set(phase_preflight.__all__)}"
    )
