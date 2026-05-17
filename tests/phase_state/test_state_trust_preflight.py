"""S01-E: state-trust preflight (design §2.6).

`preflight(scratch, *, audit_path, lock)` MUST refuse to trust the
on-disk `.scratch/phase-state.json` unless `sha256(canonical_state_bytes)`
matches the latest `after_sha256` in the audit tail. Any mismatch — or
audit tail missing while state is present — raises
`StateAuditMismatchError` (exit 10).

The two `tests/fixtures/state/tampered_*` fixtures are the canonical
rejection contract: they were deferred from S01-A.2 specifically so
this slice could prove the contract end-to-end.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from lib import phase_lock, phase_txn, state_trust


REPO_ROOT = Path(__file__).resolve().parents[2]
TAMPERED_APPROVED = REPO_ROOT / "tests/fixtures/state/tampered_approved_true"
TAMPERED_CHAIN = REPO_ROOT / "tests/fixtures/state/tampered_chain_autopilot"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def scratch(tmp_path: Path) -> Path:
    d = tmp_path / ".scratch"
    d.mkdir()
    return d


@pytest.fixture
def audit_path(tmp_path: Path) -> Path:
    (tmp_path / ".harness").mkdir()
    return tmp_path / ".harness" / "audit.log"


@pytest.fixture
def lock(scratch: Path):
    handle = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    yield handle
    phase_lock.release_primary(handle)


def _make_request(*, before: dict | None, after: dict) -> phase_txn.TxnRequest:
    return phase_txn.TxnRequest(
        action="phase.set",
        before_state=before,
        after_state=after,
        audit_entry_draft={
            "verb": "phase.set",
            "by": "test@example.com",
            "args": {"slug": "01-foo"},
        },
    )


# ---------------------------------------------------------------------------
# Positive: state written via commit_transaction matches audit tail
# ---------------------------------------------------------------------------


def test_preflight_accepts_state_matching_audit_tail(
    scratch: Path, audit_path: Path, lock
):
    req = _make_request(before=None, after={"phase": "discuss"})
    phase_txn.commit_transaction(scratch, lock=lock, request=req, audit_path=audit_path)

    # Must not raise: the state file on disk was just sealed against the
    # audit tail's `after_sha256` by the same canonical bytes hash.
    state_trust.preflight(scratch, audit_path=audit_path, lock=lock)


# ---------------------------------------------------------------------------
# Rejection: tampered_approved_true (state hand-edited, audit has no tail)
# ---------------------------------------------------------------------------


def test_preflight_rejects_tampered_approved_true_with_empty_audit(
    scratch: Path, audit_path: Path, lock
):
    shutil.copy(TAMPERED_APPROVED / "phase-state.json", scratch / "phase-state.json")
    audit_path.write_text("", encoding="utf-8")

    with pytest.raises(state_trust.StateAuditMismatchError) as excinfo:
        state_trust.preflight(scratch, audit_path=audit_path, lock=lock)

    assert excinfo.value.exit_code == 10


# ---------------------------------------------------------------------------
# Rejection: tampered_chain_autopilot vs. unrelated audit tail
# ---------------------------------------------------------------------------


def test_preflight_rejects_tampered_chain_autopilot_with_unrelated_audit(
    scratch: Path, audit_path: Path, lock
):
    # First seed scratch+audit with a real, legitimate commit so the audit
    # tail has a well-formed entry with a non-empty `after_sha256` — but
    # one that does NOT correspond to the tampered state we overwrite with.
    req = _make_request(before=None, after={"phase": "discuss", "approved": False})
    phase_txn.commit_transaction(scratch, lock=lock, request=req, audit_path=audit_path)

    # Now hand-overwrite the state file with the tampered fixture body.
    shutil.copy(TAMPERED_CHAIN / "phase-state.json", scratch / "phase-state.json")

    with pytest.raises(state_trust.StateAuditMismatchError) as excinfo:
        state_trust.preflight(scratch, audit_path=audit_path, lock=lock)

    assert excinfo.value.exit_code == 10


# ---------------------------------------------------------------------------
# Edge: no state file present — preflight is a no-op
# ---------------------------------------------------------------------------


def test_preflight_noop_when_state_file_absent(
    scratch: Path, audit_path: Path, lock
):
    audit_path.write_text("", encoding="utf-8")
    # No state file in scratch. Nothing to trust → nothing to refuse.
    state_trust.preflight(scratch, audit_path=audit_path, lock=lock)


# ---------------------------------------------------------------------------
# Edge: missing audit FILE with state present — rejected (no oracle)
# ---------------------------------------------------------------------------


def test_preflight_rejects_when_audit_file_missing_but_state_present(
    scratch: Path, audit_path: Path, lock
):
    shutil.copy(TAMPERED_APPROVED / "phase-state.json", scratch / "phase-state.json")
    # audit_path intentionally not created.
    assert not audit_path.exists()

    with pytest.raises(state_trust.StateAuditMismatchError) as excinfo:
        state_trust.preflight(scratch, audit_path=audit_path, lock=lock)

    assert excinfo.value.exit_code == 10


# ---------------------------------------------------------------------------
# Lock contract: caller MUST hold the primary lock
# ---------------------------------------------------------------------------


def test_preflight_requires_lock(scratch: Path, audit_path: Path):
    audit_path.write_text("", encoding="utf-8")
    with pytest.raises(state_trust.StateTrustLockMissingError):
        state_trust.preflight(scratch, audit_path=audit_path, lock=None)


def test_preflight_rejects_released_lock(scratch: Path, audit_path: Path):
    audit_path.write_text("", encoding="utf-8")
    handle = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    phase_lock.release_primary(handle)
    with pytest.raises(state_trust.StateTrustLockMissingError):
        state_trust.preflight(scratch, audit_path=audit_path, lock=handle)


# ---------------------------------------------------------------------------
# Sanity: error class is an OSError subclass (uniform fault-class shape)
# ---------------------------------------------------------------------------


def test_error_classes_are_oserror_subclasses():
    assert issubclass(state_trust.StateAuditMismatchError, OSError)
    assert issubclass(state_trust.StateTrustLockMissingError, OSError)
    assert state_trust.StateAuditMismatchError.exit_code == 10


# ---------------------------------------------------------------------------
# Round-trip: a commit→preflight→commit→preflight chain stays valid
# ---------------------------------------------------------------------------


def test_preflight_stays_valid_across_consecutive_commits(
    scratch: Path, audit_path: Path, lock
):
    req1 = _make_request(before=None, after={"phase": "discuss"})
    phase_txn.commit_transaction(scratch, lock=lock, request=req1, audit_path=audit_path)
    state_trust.preflight(scratch, audit_path=audit_path, lock=lock)

    req2 = _make_request(
        before={"phase": "discuss"}, after={"phase": "plan"}
    )
    phase_txn.commit_transaction(scratch, lock=lock, request=req2, audit_path=audit_path)
    state_trust.preflight(scratch, audit_path=audit_path, lock=lock)

    # Confirm the latest audit tail entry's after_sha256 matches the on-disk
    # state — i.e., preflight isn't trivially short-circuiting.
    on_disk = (scratch / "phase-state.json").read_bytes()
    import hashlib
    state_sha = hashlib.sha256(on_disk).hexdigest()
    tail = phase_txn._audit_tail_entry(audit_path)
    assert tail is not None
    assert tail["after_sha256"] == state_sha
