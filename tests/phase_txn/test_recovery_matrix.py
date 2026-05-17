"""S01-D.2: 12-row crash recovery matrix (design §3.8 + §12.5 #2).

Each test plants a `.scratch/` layout matching one row of the matrix,
runs `phase_txn.recover(...)`, and asserts:
  * the dispatcher reported the correct row id
  * the post-recovery file system matches the design table's "Decision"
  * the recovery result's `exit_code` is 0 (rows 1-8b) or 14 (rows 9-12)

Row predicates:
  J = journal exists      (`phase-state.json.journal`)
  T = tmp exists          (`phase-state.json.tmp`)
  A = audit tail's last entry carries a `txn_id` equal to the journal's
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from lib import phase_txn


# ---------------------------------------------------------------------------
# Helpers: hand-craft a journal / tmp / state / audit layout per row
# ---------------------------------------------------------------------------


def _canon_bytes(state: dict) -> bytes:
    return phase_txn._canonical_bytes(state)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _write_state(scratch: Path, state: dict) -> bytes:
    body = _canon_bytes(state)
    (scratch / "phase-state.json").write_bytes(body)
    return body


def _write_tmp(scratch: Path, state: dict) -> bytes:
    body = _canon_bytes(state)
    (scratch / "phase-state.json.tmp").write_bytes(body)
    return body


def _write_journal(
    scratch: Path,
    *,
    txn_id: str,
    before_sha: str,
    after_sha: str,
    action: str = "phase.set",
) -> None:
    payload = {
        "txn_id": txn_id,
        "action": action,
        "before_sha256": before_sha,
        "after_sha256": after_sha,
        "audit_entry_draft": {"verb": action, "by": "test@x"},
        "started_at_monotonic": 1.0,
    }
    (scratch / "phase-state.json.journal").write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _write_audit(audit_path: Path, entries: list[dict]) -> None:
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("w", encoding="utf-8") as fh:
        for i, entry in enumerate(entries, start=1):
            full = dict(entry, index=i)
            fh.write(json.dumps(full, sort_keys=True, separators=(",", ":")) + "\n")


# ---------------------------------------------------------------------------
# Rows 1-4 — J=0
# ---------------------------------------------------------------------------


def test_row_1_quiescent_no_artefacts(scratch: Path, audit_path: Path, lock):
    _write_state(scratch, {"phase": "discuss"})
    audit_path.write_text("", encoding="utf-8")

    result = phase_txn.recover(scratch, audit_path=audit_path, lock=lock)
    assert result.row == 1
    assert result.exit_code == 0
    assert (scratch / "phase-state.json").exists()


def test_row_2_orphan_tmp_unlinked(scratch: Path, audit_path: Path, lock):
    _write_state(scratch, {"phase": "discuss"})
    _write_tmp(scratch, {"phase": "plan"})
    audit_path.write_text("", encoding="utf-8")

    result = phase_txn.recover(scratch, audit_path=audit_path, lock=lock)
    assert result.row == 2
    assert result.exit_code == 0
    assert not (scratch / "phase-state.json.tmp").exists()


def test_row_3_post_finalize_state_already_after(scratch: Path, audit_path: Path, lock):
    """J=0 T=0 A=1 + state==after — step 5 completed normally; the audit
    tail's txn_id is informational only. No action required."""
    after_state = {"phase": "plan"}
    state_body = _write_state(scratch, after_state)
    _write_audit(audit_path, [
        {"verb": "phase.set", "txn_id": "deadbeef" * 4, "after_sha256": _sha(state_body)},
    ])

    result = phase_txn.recover(scratch, audit_path=audit_path, lock=lock)
    assert result.row == 3
    assert result.exit_code == 0


def test_row_4_post_finalize_with_tmp_unlinked(scratch: Path, audit_path: Path, lock):
    """J=0 T=1 A=1 + state==after — step 4 finished but the tmp file
    happened to remain (e.g. step 5 unlink interrupted only the journal
    in a previous race). Drop tmp; accept state."""
    after_state = {"phase": "plan"}
    state_body = _write_state(scratch, after_state)
    _write_tmp(scratch, after_state)
    _write_audit(audit_path, [
        {"verb": "phase.set", "txn_id": "f" * 32, "after_sha256": _sha(state_body)},
    ])

    result = phase_txn.recover(scratch, audit_path=audit_path, lock=lock)
    assert result.row == 4
    assert result.exit_code == 0
    assert not (scratch / "phase-state.json.tmp").exists()


# ---------------------------------------------------------------------------
# Rows 5-8b — J=1
# ---------------------------------------------------------------------------


def test_row_5_rollback_journal_only_state_at_before(scratch: Path, audit_path: Path, lock):
    """J=1 T=0 A=0 + state==before — step 3 never wrote audit; rollback by
    deleting the journal. State remains untouched."""
    before = {"phase": "discuss"}
    after = {"phase": "plan"}
    state_body = _write_state(scratch, before)
    _write_journal(
        scratch,
        txn_id="a" * 32,
        before_sha=_sha(state_body),
        after_sha=_sha(_canon_bytes(after)),
    )
    audit_path.write_text("", encoding="utf-8")

    result = phase_txn.recover(scratch, audit_path=audit_path, lock=lock)
    assert result.row == 5
    assert result.exit_code == 0
    assert not (scratch / "phase-state.json.journal").exists()
    assert json.loads((scratch / "phase-state.json").read_bytes()) == before


def test_row_6_rollback_journal_plus_tmp_at_before(scratch: Path, audit_path: Path, lock):
    before = {"phase": "discuss"}
    after = {"phase": "plan"}
    state_body = _write_state(scratch, before)
    _write_tmp(scratch, after)
    _write_journal(
        scratch,
        txn_id="b" * 32,
        before_sha=_sha(state_body),
        after_sha=_sha(_canon_bytes(after)),
    )
    audit_path.write_text("", encoding="utf-8")

    result = phase_txn.recover(scratch, audit_path=audit_path, lock=lock)
    assert result.row == 6
    assert result.exit_code == 0
    assert not (scratch / "phase-state.json.journal").exists()
    assert not (scratch / "phase-state.json.tmp").exists()
    assert json.loads((scratch / "phase-state.json").read_bytes()) == before


def test_row_7_roll_forward_replaces_state_with_tmp(scratch: Path, audit_path: Path, lock):
    """J=1 T=1 A=1 + state==before + sha(tmp)==after — step 4 didn't run;
    do the os.replace now and clean up the journal."""
    before = {"phase": "discuss"}
    after = {"phase": "plan"}
    state_body = _write_state(scratch, before)
    tmp_body = _write_tmp(scratch, after)
    _write_journal(
        scratch,
        txn_id="c" * 32,
        before_sha=_sha(state_body),
        after_sha=_sha(tmp_body),
    )
    _write_audit(audit_path, [
        {"verb": "phase.set", "txn_id": "c" * 32, "before_sha256": _sha(state_body), "after_sha256": _sha(tmp_body)},
    ])

    result = phase_txn.recover(scratch, audit_path=audit_path, lock=lock)
    assert result.row == 7
    assert result.exit_code == 0
    assert not (scratch / "phase-state.json.tmp").exists()
    assert not (scratch / "phase-state.json.journal").exists()
    assert json.loads((scratch / "phase-state.json").read_bytes()) == after


def test_row_8a_finalize_journal_only_state_at_after(scratch: Path, audit_path: Path, lock):
    """J=1 T=0 A=1 + state==after — step 4 finished, step 5 (unlink journal)
    did not. Drop journal and accept."""
    before = {"phase": "discuss"}
    after = {"phase": "plan"}
    state_body = _write_state(scratch, after)
    _write_journal(
        scratch,
        txn_id="d" * 32,
        before_sha=_sha(_canon_bytes(before)),
        after_sha=_sha(state_body),
    )
    _write_audit(audit_path, [
        {"verb": "phase.set", "txn_id": "d" * 32, "after_sha256": _sha(state_body)},
    ])

    result = phase_txn.recover(scratch, audit_path=audit_path, lock=lock)
    assert result.row == 8
    assert result.exit_code == 0
    assert not (scratch / "phase-state.json.journal").exists()
    assert json.loads((scratch / "phase-state.json").read_bytes()) == after


def test_row_8b_finalize_journal_plus_tmp_state_at_after(scratch: Path, audit_path: Path, lock):
    """J=1 T=1 A=1 + state==after — step 4 happened, but the tmp file is
    still around (interrupted unlink). Drop both."""
    before = {"phase": "discuss"}
    after = {"phase": "plan"}
    state_body = _write_state(scratch, after)
    _write_tmp(scratch, after)
    _write_journal(
        scratch,
        txn_id="e" * 32,
        before_sha=_sha(_canon_bytes(before)),
        after_sha=_sha(state_body),
    )
    _write_audit(audit_path, [
        {"verb": "phase.set", "txn_id": "e" * 32, "after_sha256": _sha(state_body)},
    ])

    result = phase_txn.recover(scratch, audit_path=audit_path, lock=lock)
    assert result.row == 8  # 8a/8b share an id; differentiator is artefact presence
    assert result.exit_code == 0
    assert not (scratch / "phase-state.json.journal").exists()
    assert not (scratch / "phase-state.json.tmp").exists()


# ---------------------------------------------------------------------------
# Rows 9-11 — exit 14 fault classes
# ---------------------------------------------------------------------------


def test_row_9_undecidable_state_hash_in_neither_bucket(scratch: Path, audit_path: Path, lock):
    """J=1 A=1 + state ∉ {before, after} — state file was corrupted or
    half-written. Cannot decide; exit 14."""
    before = {"phase": "discuss"}
    after = {"phase": "plan"}
    state_body = _write_state(scratch, {"phase": "garbage"})  # neither before nor after
    _write_journal(
        scratch,
        txn_id="9" * 32,
        before_sha=_sha(_canon_bytes(before)),
        after_sha=_sha(_canon_bytes(after)),
    )
    _write_audit(audit_path, [
        {"verb": "phase.set", "txn_id": "9" * 32},
    ])

    result = phase_txn.recover(scratch, audit_path=audit_path, lock=lock)
    assert result.row == 9
    assert result.exit_code == 14


def test_row_10_corrupt_journal_and_tmp_no_audit(scratch: Path, audit_path: Path, lock):
    """J=1 T=1 A=0 + state != before — journal points at a transition
    that never reached audit, but state already changed. Corruption.
    """
    before = {"phase": "discuss"}
    after = {"phase": "plan"}
    _write_state(scratch, {"phase": "garbage"})
    _write_tmp(scratch, after)
    _write_journal(
        scratch,
        txn_id="aa" * 16,
        before_sha=_sha(_canon_bytes(before)),
        after_sha=_sha(_canon_bytes(after)),
    )
    audit_path.write_text("", encoding="utf-8")

    result = phase_txn.recover(scratch, audit_path=audit_path, lock=lock)
    assert result.row == 10
    assert result.exit_code == 14


def test_row_11_corrupt_journal_only_no_audit(scratch: Path, audit_path: Path, lock):
    """J=1 T=0 A=0 + state != before — same corruption class without tmp."""
    before = {"phase": "discuss"}
    after = {"phase": "plan"}
    _write_state(scratch, {"phase": "garbage"})
    _write_journal(
        scratch,
        txn_id="bb" * 16,
        before_sha=_sha(_canon_bytes(before)),
        after_sha=_sha(_canon_bytes(after)),
    )
    audit_path.write_text("", encoding="utf-8")

    result = phase_txn.recover(scratch, audit_path=audit_path, lock=lock)
    assert result.row == 11
    assert result.exit_code == 14


def test_row_12_audit_partial_write_last_entry_unparseable(
    scratch: Path, audit_path: Path, lock
):
    """§12.5 #2: last audit line fails JSON-parse → exit 14
    audit_partial_write. Row 12 takes precedence over the J/T/A
    matrix because the audit oracle itself is untrustworthy."""
    _write_state(scratch, {"phase": "discuss"})
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(
        '{"verb":"phase.set","txn_id":"valid","index":1}\n'
        '{"verb":"phase.set","txn_id":"part',  # truncated mid-JSON
        encoding="utf-8",
    )

    result = phase_txn.recover(scratch, audit_path=audit_path, lock=lock)
    assert result.row == 12
    assert result.exit_code == 14
    assert result.decision == "audit_partial_write"


# ---------------------------------------------------------------------------
# Lock contract — recover() requires a live lock just like commit
# ---------------------------------------------------------------------------


def test_recover_refuses_without_lock(scratch: Path, audit_path: Path):
    _write_state(scratch, {"phase": "discuss"})
    audit_path.write_text("", encoding="utf-8")
    with pytest.raises(phase_txn.TxnLockMissingError):
        phase_txn.recover(scratch, audit_path=audit_path, lock=None)  # type: ignore[arg-type]
