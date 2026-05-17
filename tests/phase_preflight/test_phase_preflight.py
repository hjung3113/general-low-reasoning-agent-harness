"""Smoke tests for `scripts/lib/phase_preflight.py` (P2-3 extraction).

Design refs:
  - §3.1 / §3.2 — shared preflight helpers used by `phase approve` and
                   `phase reopen` (and future §S07 verbs).
  - §12.1        — anchor preflight fail-closed semantics.
  - §2.6         — state-trust preflight taxonomy.
  - §3.9         — every error MUST carry a Fix: line.

These are smoke tests, not exhaustive coverage (the `phase_approve` and
`phase_reopen` suites exercise the helpers end-to-end). The goal is to pin
the public surface of the extracted module so regressions in the shared
helpers surface here rather than leaking into verb-specific test failures.
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
    # Can't guarantee a real git config is present; at minimum the return
    # value must be a stripped string (no leading/trailing whitespace).
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
    "FIX_STATE_TRUST",
    "FIX_ANCHOR_MISSING",
    "FIX_ANCHOR_MISMATCH",
    "FIX_ANCHOR_UNVERIFIABLE",
])
def test_fix_line_constant_present_and_non_empty(const_name):
    val = getattr(phase_preflight, const_name)
    assert isinstance(val, str) and val.strip(), f"{const_name} must be a non-empty string"
    assert "Fix:" in val, f"{const_name} must contain 'Fix:' per §3.9"


# ---------------------------------------------------------------------------
# run_anchor_preflight — fail-closed semantics
# ---------------------------------------------------------------------------


def test_run_anchor_preflight_skip_returns_true():
    result = phase_preflight.run_anchor_preflight(
        skip_anchor_preflight=True, repo_root=None
    )
    assert result is True


def test_run_anchor_preflight_unwired_raises_when_repo_root_none():
    with pytest.raises(phase_preflight.AnchorPreflightError) as exc_info:
        phase_preflight.run_anchor_preflight(
            skip_anchor_preflight=False, repo_root=None
        )
    err = exc_info.value
    assert err.sub_reason == "anchor_preflight_unwired"
    assert err.fix_line  # must carry a Fix: line


def test_run_anchor_preflight_raises_anchor_missing_for_unknown_repo(tmp_path: Path):
    """A temp dir with no git repo → anchor missing."""
    with pytest.raises(phase_preflight.AnchorPreflightError) as exc_info:
        phase_preflight.run_anchor_preflight(
            skip_anchor_preflight=False, repo_root=tmp_path
        )
    err = exc_info.value
    # The sub_reason is implementation-defined but must not be the
    # "unwired" reason (which means the codepath was actually reached).
    assert err.sub_reason != "anchor_preflight_unwired"


# ---------------------------------------------------------------------------
# run_state_trust_preflight — taxonomy
# ---------------------------------------------------------------------------


def test_run_state_trust_preflight_ok_with_no_state_file(tmp_path: Path):
    """Empty scratch dir → no state file → preflight returns None (no state
    to verify yet; the caller handles the missing-state case separately).
    This pins the 'no-state = OK for preflight' contract."""
    from lib import phase_lock

    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    audit_path = tmp_path / "audit.log"

    lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    try:
        result = phase_preflight.run_state_trust_preflight(
            scratch=scratch,
            audit_path=audit_path,
            lock=lock,
            anchor_verified=True,
        )
        assert result is None  # successful preflight → None
    finally:
        phase_lock.release_primary(lock)


def test_run_state_trust_preflight_raises_on_tampered_state(tmp_path: Path):
    """Tampered state (content diverges from audit tail) → StateTrustPreflightError."""
    from lib import phase_lock, phase_txn

    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    harness = tmp_path / ".harness"
    harness.mkdir()
    audit_path = harness / "audit.log"

    # Seed a valid state so the audit tip hash is set.
    seed_state = {"phase": "plan", "approved": False, "state_schema_version": 2}
    lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    try:
        req = phase_txn.TxnRequest(
            action="phase.set",
            before_state=None,
            after_state=seed_state,
            audit_entry_draft={"verb": "phase.set", "by": "seed", "args": {}},
        )
        phase_txn.commit_transaction(
            scratch, lock=lock, request=req, audit_path=audit_path
        )
    finally:
        phase_lock.release_primary(lock)

    # Tamper: change a field in the state file directly.
    state_path = scratch / "phase-state.json"
    txt = state_path.read_text()
    state_path.write_text(txt.replace('"plan"', '"execute"'))

    lock2 = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    try:
        with pytest.raises(phase_preflight.StateTrustPreflightError) as exc_info:
            phase_preflight.run_state_trust_preflight(
                scratch=scratch,
                audit_path=audit_path,
                lock=lock2,
                anchor_verified=True,
            )
        err = exc_info.value
        assert err.exit_code == 10
        assert err.sub_reason == "state_audit_tip_mismatch"
    finally:
        phase_lock.release_primary(lock2)


# ---------------------------------------------------------------------------
# AnchorPreflightError and StateTrustPreflightError are Exception subclasses
# ---------------------------------------------------------------------------


def test_anchor_preflight_error_is_exception():
    assert issubclass(phase_preflight.AnchorPreflightError, Exception)


def test_state_trust_preflight_error_is_exception():
    assert issubclass(phase_preflight.StateTrustPreflightError, Exception)


# ---------------------------------------------------------------------------
# __all__ pin — P2-3 public surface contract
# ---------------------------------------------------------------------------


def test_all_exports_present():
    expected = {
        "FIX_GITCONFIG",
        "FIX_APPROVER_MEMBERSHIP",
        "FIX_STATE_TRUST",
        "FIX_ANCHOR_MISSING",
        "FIX_ANCHOR_MISMATCH",
        "FIX_ANCHOR_UNVERIFIABLE",
        "now_iso_z",
        "default_gitconfig_email_lookup",
        "load_install_record",
        "approvers_emails",
        "AnchorPreflightError",
        "run_anchor_preflight",
        "StateTrustPreflightError",
        "run_state_trust_preflight",
    }
    assert expected.issubset(set(phase_preflight.__all__)), (
        f"Missing from __all__: {expected - set(phase_preflight.__all__)}"
    )
