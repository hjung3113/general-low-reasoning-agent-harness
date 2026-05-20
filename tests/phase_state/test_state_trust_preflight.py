"""S01-E: state-trust preflight (design §2.6).

`preflight(scratch, *, audit_path, lock)` MUST refuse to trust the
on-disk `.scratch/phase-state.json` unless every step in §2.6 holds:

  * state bytes are well-formed: no BOM (§2.4), no CRLF (§2.3),
    parseable JSON
  * `sha256(canonical(state_bytes))` matches the latest audit tail
    entry's `after_sha256`

Any failure raises a `StateTrustError` subclass with the documented
`exit_code` (5 for ill-formed bytes, 10 for tip mismatch, 14 for
crash-artefact empty state).

The two `tests/fixtures/state/tampered_*` fixtures are the canonical
rejection contract: they were deferred from S01-A.2 specifically so
this slice could prove the contract end-to-end.
"""

from __future__ import annotations

import hashlib
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


def _ok(scratch: Path, audit_path: Path, lock) -> None:
    """Shorthand: preflight call."""
    state_trust.preflight(
        scratch, audit_path=audit_path, lock=lock
    )


# ---------------------------------------------------------------------------
# Positive: state written via commit_transaction matches audit tail
# ---------------------------------------------------------------------------


def test_preflight_accepts_state_matching_audit_tail(
    scratch: Path, audit_path: Path, lock
):
    req = _make_request(before=None, after={"phase": "discuss"})
    phase_txn.commit_transaction(scratch, lock=lock, request=req, audit_path=audit_path)
    _ok(scratch, audit_path, lock)


# ---------------------------------------------------------------------------
# Rejection: tampered_approved_true (state hand-edited, audit has no tail)
# ---------------------------------------------------------------------------


def test_preflight_rejects_tampered_approved_true_with_empty_audit(
    scratch: Path, audit_path: Path, lock
):
    shutil.copy(TAMPERED_APPROVED / "phase-state.json", scratch / "phase-state.json")
    audit_path.write_text("", encoding="utf-8")

    with pytest.raises(state_trust.StateAuditMismatchError) as excinfo:
        _ok(scratch, audit_path, lock)
    assert excinfo.value.exit_code == 10
    # Manual repair path is part of the §2.6 step-4 contract.
    assert "harness verify --audit" in str(excinfo.value)
    assert "git checkout" in str(excinfo.value) or "harness install" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Rejection: tampered_chain_autopilot vs. unrelated audit tail
# ---------------------------------------------------------------------------


def test_preflight_rejects_tampered_chain_autopilot_with_unrelated_audit(
    scratch: Path, audit_path: Path, lock
):
    req = _make_request(before=None, after={"phase": "discuss", "approved": False})
    phase_txn.commit_transaction(scratch, lock=lock, request=req, audit_path=audit_path)
    shutil.copy(TAMPERED_CHAIN / "phase-state.json", scratch / "phase-state.json")

    with pytest.raises(state_trust.StateAuditMismatchError) as excinfo:
        _ok(scratch, audit_path, lock)
    assert excinfo.value.exit_code == 10


# ---------------------------------------------------------------------------
# Edges: state file absent, missing audit file, empty (0-byte) state
# ---------------------------------------------------------------------------


def test_preflight_noop_when_state_file_absent(
    scratch: Path, audit_path: Path, lock
):
    audit_path.write_text("", encoding="utf-8")
    _ok(scratch, audit_path, lock)


def test_preflight_rejects_when_audit_file_missing_but_state_present(
    scratch: Path, audit_path: Path, lock
):
    shutil.copy(TAMPERED_APPROVED / "phase-state.json", scratch / "phase-state.json")
    assert not audit_path.exists()

    with pytest.raises(state_trust.StateAuditMismatchError) as excinfo:
        _ok(scratch, audit_path, lock)
    assert excinfo.value.exit_code == 10


def test_preflight_rejects_empty_state_file_distinctly(
    scratch: Path, audit_path: Path, lock
):
    (scratch / "phase-state.json").write_bytes(b"")
    audit_path.write_text("", encoding="utf-8")

    with pytest.raises(state_trust.StateEmptyError) as excinfo:
        _ok(scratch, audit_path, lock)
    assert excinfo.value.exit_code == 14
    assert "recover" in str(excinfo.value)


# ---------------------------------------------------------------------------
# §2.4: BOM rejection (exit 5)
# ---------------------------------------------------------------------------


def test_preflight_rejects_bom_prefixed_state(
    scratch: Path, audit_path: Path, lock
):
    body = json.dumps({"phase": "discuss"}, sort_keys=True, indent=2) + "\n"
    (scratch / "phase-state.json").write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
    audit_path.write_text("", encoding="utf-8")

    with pytest.raises(state_trust.StateBomError) as excinfo:
        _ok(scratch, audit_path, lock)
    assert excinfo.value.exit_code == 5
    assert "BOM" in str(excinfo.value)
    assert "harness repair --strip-bom" in str(excinfo.value)


# ---------------------------------------------------------------------------
# §2.3: CRLF rejection (exit 5)
# ---------------------------------------------------------------------------


def test_preflight_rejects_crlf_state(
    scratch: Path, audit_path: Path, lock
):
    body = json.dumps({"phase": "discuss"}, sort_keys=True, indent=2) + "\n"
    crlf = body.replace("\n", "\r\n").encode("utf-8")
    (scratch / "phase-state.json").write_bytes(crlf)
    audit_path.write_text("", encoding="utf-8")

    with pytest.raises(state_trust.StateCrlfError) as excinfo:
        _ok(scratch, audit_path, lock)
    assert excinfo.value.exit_code == 5
    assert "CRLF" in str(excinfo.value)


# ---------------------------------------------------------------------------
# JSON-parse failure → exit 5
# ---------------------------------------------------------------------------


def test_preflight_rejects_unparseable_state(
    scratch: Path, audit_path: Path, lock
):
    (scratch / "phase-state.json").write_bytes(b"{not json")
    audit_path.write_text("", encoding="utf-8")

    with pytest.raises(state_trust.StateMalformedJsonError) as excinfo:
        _ok(scratch, audit_path, lock)
    assert excinfo.value.exit_code == 5


# ---------------------------------------------------------------------------
# §2.6 step-1 hardening: hashing is over CANONICAL bytes, not raw bytes
# ---------------------------------------------------------------------------


def test_preflight_accepts_cosmetic_whitespace_reformatted_state_if_json_equivalent(
    scratch: Path, audit_path: Path, lock
):
    """An attacker who reformats state.json with different whitespace
    but keeps JSON content identical MUST NOT defeat the check by
    producing a raw-byte sha mismatch — we canonicalize before hash.

    Conversely a legitimate write (which is already canonical) round-
    trips identity, so this isn't a regression on the happy path."""
    req = _make_request(before=None, after={"phase": "discuss", "x": 1})
    phase_txn.commit_transaction(scratch, lock=lock, request=req, audit_path=audit_path)

    # Re-serialize the same JSON with completely different whitespace:
    parsed = json.loads((scratch / "phase-state.json").read_bytes().decode("utf-8"))
    weird = json.dumps(parsed, indent=8, separators=(",  ", " :  "))
    (scratch / "phase-state.json").write_text(weird + "\n", encoding="utf-8")

    _ok(scratch, audit_path, lock)


# ---------------------------------------------------------------------------
# Lock contract — including symlinked scratch dir (macOS /var → /private/var)
# ---------------------------------------------------------------------------


def test_preflight_requires_lock(scratch: Path, audit_path: Path):
    audit_path.write_text("", encoding="utf-8")
    with pytest.raises(state_trust.StateTrustLockMissingError):
        state_trust.preflight(
            scratch, audit_path=audit_path, lock=None
        )


def test_preflight_rejects_released_lock(scratch: Path, audit_path: Path):
    audit_path.write_text("", encoding="utf-8")
    handle = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    phase_lock.release_primary(handle)
    with pytest.raises(state_trust.StateTrustLockMissingError):
        state_trust.preflight(
            scratch, audit_path=audit_path, lock=handle
        )


def test_preflight_accepts_symlinked_scratch_path(
    tmp_path: Path, audit_path: Path
):
    """Caller acquired the lock with a resolved path; preflight is
    handed a symlink-prefixed (unresolved) path. Comparison MUST be
    resolve()-based — otherwise legitimate macOS callers (where
    `/var` symlinks to `/private/var`) get spurious lock-mismatch."""
    real = tmp_path / "real_scratch"
    real.mkdir()
    link = tmp_path / "link_scratch"
    link.symlink_to(real, target_is_directory=True)

    handle = phase_lock.acquire_primary(real, timeout_s=2.0)
    try:
        # Pass the symlink path; preflight must accept (resolve-equal).
        state_trust.preflight(
            link, audit_path=audit_path, lock=handle
        )
    finally:
        phase_lock.release_primary(handle)


# ---------------------------------------------------------------------------
# Error class shape
# ---------------------------------------------------------------------------


def test_error_classes_have_correct_exit_codes():
    assert issubclass(state_trust.StateAuditMismatchError, OSError)
    assert issubclass(state_trust.StateTrustLockMissingError, OSError)
    assert state_trust.StateBomError.exit_code == 5
    assert state_trust.StateCrlfError.exit_code == 5
    assert state_trust.StateMalformedJsonError.exit_code == 5
    assert state_trust.StateEmptyError.exit_code == 14
    assert state_trust.StateAuditMismatchError.exit_code == 10


# ---------------------------------------------------------------------------
# Round-trip across consecutive commits
# ---------------------------------------------------------------------------


def test_preflight_stays_valid_across_consecutive_commits(
    scratch: Path, audit_path: Path, lock
):
    req1 = _make_request(before=None, after={"phase": "discuss"})
    phase_txn.commit_transaction(scratch, lock=lock, request=req1, audit_path=audit_path)
    _ok(scratch, audit_path, lock)

    req2 = _make_request(before={"phase": "discuss"}, after={"phase": "plan"})
    phase_txn.commit_transaction(scratch, lock=lock, request=req2, audit_path=audit_path)
    _ok(scratch, audit_path, lock)

    on_disk = (scratch / "phase-state.json").read_bytes()
    state_sha = hashlib.sha256(on_disk).hexdigest()
    tail = phase_txn._audit_tail_entry(audit_path)
    assert tail is not None
    assert tail["after_sha256"] == state_sha
