"""S01-D.1: `commit_transaction` 5-step protocol (design §3.8).

Each step's durability call is observable through the
`scripts.lib.durable_fs` module-level functions; tests patch them as
spies to assert ordering and frequency. Crash recovery (rows 1-12)
is S01-D.2 scope.

Step table (design §3.8, lines 439-445):
  1. Write journal {txn_id, action, before_sha256, after_sha256,
     audit_entry_draft, started_at_monotonic} -> fsync(journal_fd);
     fsync_parent_dir(scratch).
  2. Write state.json.tmp -> fsync(tmp_fd); fsync_parent_dir(scratch).
  3. Append audit entry with txn_id -> fsync(audit_fd).
  4. os.replace(state.json.tmp, state.json) -> fsync_parent_dir(scratch).
  5. os.unlink(journal) -> fsync_parent_dir(scratch).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from unittest import mock

import pytest

from lib import phase_lock, phase_txn


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _make_request(
    *,
    before: dict | None,
    after: dict,
    action: str = "phase.set",
) -> phase_txn.TxnRequest:
    return phase_txn.TxnRequest(
        action=action,
        before_state=before,
        after_state=after,
        audit_entry_draft={
            "verb": action,
            "by": "test@example.com",
            "args": {"slug": "01-foo"},
        },
    )


# ---------------------------------------------------------------------------
# Happy path: every artefact present and consistent after commit
# ---------------------------------------------------------------------------


def test_commit_writes_state_atomically(scratch: Path, audit_path: Path, lock):
    state_path = scratch / "phase-state.json"
    state_path.write_text(json.dumps({"phase": "discuss"}, sort_keys=True) + "\n", encoding="utf-8")

    req = _make_request(
        before={"phase": "discuss"},
        after={"phase": "plan"},
    )
    txn_id = phase_txn.commit_transaction(
        scratch,
        lock=lock,
        request=req,
        audit_path=audit_path,
    )

    assert isinstance(txn_id, str)
    assert len(txn_id) >= 16  # 128-bit-ish identifier

    # State file reflects `after_state` exactly.
    on_disk = json.loads(state_path.read_text(encoding="utf-8"))
    assert on_disk == {"phase": "plan"}

    # Journal and tmp are gone (steps 4+5 cleaned them up).
    assert not (scratch / "phase-state.json.tmp").exists()
    assert not (scratch / "phase-state.json.journal").exists()

    # Audit log has a single new entry carrying our txn_id.
    entries = [
        json.loads(ln) for ln in audit_path.read_text(encoding="utf-8").splitlines() if ln.strip()
    ]
    assert any(e.get("txn_id") == txn_id and e.get("verb") == "phase.set" for e in entries)


def test_commit_emits_audit_entry_with_before_after_sha256(
    scratch: Path, audit_path: Path, lock
):
    state_path = scratch / "phase-state.json"
    state_path.write_text(json.dumps({"phase": "discuss"}, sort_keys=True) + "\n", encoding="utf-8")
    req = _make_request(before={"phase": "discuss"}, after={"phase": "plan"})

    txn_id = phase_txn.commit_transaction(scratch, lock=lock, request=req, audit_path=audit_path)

    entries = [
        json.loads(ln) for ln in audit_path.read_text(encoding="utf-8").splitlines() if ln.strip()
    ]
    entry = next(e for e in entries if e.get("txn_id") == txn_id)
    assert "before_sha256" in entry
    assert "after_sha256" in entry
    assert entry["before_sha256"] != entry["after_sha256"]


def test_commit_inserts_fresh_state_when_no_prior_state(
    scratch: Path, audit_path: Path, lock
):
    """A from-nothing commit (`before_state=None`) MUST still succeed and
    produce a state file equal to `after_state`."""
    req = _make_request(before=None, after={"phase": "discuss", "approved": False})
    phase_txn.commit_transaction(scratch, lock=lock, request=req, audit_path=audit_path)
    on_disk = json.loads((scratch / "phase-state.json").read_text(encoding="utf-8"))
    assert on_disk == {"phase": "discuss", "approved": False}


# ---------------------------------------------------------------------------
# Caller MUST hold the state lock
# ---------------------------------------------------------------------------


def test_commit_refuses_without_lock_handle(scratch: Path, audit_path: Path):
    req = _make_request(before=None, after={"phase": "discuss"})
    with pytest.raises(phase_txn.TxnLockMissingError):
        phase_txn.commit_transaction(scratch, lock=None, request=req, audit_path=audit_path)  # type: ignore[arg-type]


def test_commit_refuses_with_released_lock(scratch: Path, audit_path: Path):
    handle = phase_lock.acquire_primary(scratch, timeout_s=1.0)
    phase_lock.release_primary(handle)
    req = _make_request(before=None, after={"phase": "discuss"})
    with pytest.raises(phase_txn.TxnLockMissingError):
        phase_txn.commit_transaction(scratch, lock=handle, request=req, audit_path=audit_path)


# ---------------------------------------------------------------------------
# Step ordering observed via durable_fs spies (design §3.8 Round-5 BLOCK #4)
# ---------------------------------------------------------------------------


def test_commit_calls_durable_fs_in_documented_order(
    scratch: Path, audit_path: Path, lock, monkeypatch
):
    """The protocol ordering is the spec's contract — pinned by spy."""
    from lib import durable_fs

    real_fsync_parent_dir = durable_fs.fsync_parent_dir
    calls: list[str] = []

    def spy_fsync_parent_dir(path):
        calls.append(f"fsync_parent_dir({Path(path).name})")
        return real_fsync_parent_dir(path)

    monkeypatch.setattr(phase_txn._durable_fs, "fsync_parent_dir", spy_fsync_parent_dir)

    state_path = scratch / "phase-state.json"
    state_path.write_text(json.dumps({"phase": "discuss"}, sort_keys=True) + "\n", encoding="utf-8")
    req = _make_request(before={"phase": "discuss"}, after={"phase": "plan"})
    phase_txn.commit_transaction(scratch, lock=lock, request=req, audit_path=audit_path)

    # The scratch parent-dir fsync MUST fire after step 1 (journal),
    # step 2 (tmp), step 4 (replace), step 5 (unlink) — four total.
    # Step 3 (audit append) fsync is inside lib.audit, not durable_fs.
    scratch_fsyncs = [c for c in calls if c == "fsync_parent_dir(.scratch)"]
    assert len(scratch_fsyncs) == 4, f"expected 4 scratch fsyncs, got {len(scratch_fsyncs)}: {calls}"


def test_commit_tmp_durable_before_audit_append(
    scratch: Path, audit_path: Path, lock, monkeypatch
):
    """Round-5 BLOCK #4: tmp's parent-dir fsync MUST happen BEFORE audit
    append (so audit cannot point at a not-yet-durable tmp)."""
    from lib import audit as audit_mod, durable_fs

    real_fsync_parent_dir = durable_fs.fsync_parent_dir
    real_audit_append = audit_mod.audit_append
    order: list[str] = []

    def spy_fsync_parent_dir(path):
        order.append(f"FSYNC_PARENT({Path(path).name})")
        return real_fsync_parent_dir(path)

    def spy_audit_append(entry, *, audit_path):
        order.append(f"AUDIT_APPEND({entry.get('verb')})")
        return real_audit_append(entry, audit_path=audit_path)

    monkeypatch.setattr(phase_txn._durable_fs, "fsync_parent_dir", spy_fsync_parent_dir)
    monkeypatch.setattr(phase_txn._audit, "audit_append", spy_audit_append)

    state_path = scratch / "phase-state.json"
    state_path.write_text(json.dumps({"phase": "discuss"}, sort_keys=True) + "\n", encoding="utf-8")
    req = _make_request(before={"phase": "discuss"}, after={"phase": "plan"})
    phase_txn.commit_transaction(scratch, lock=lock, request=req, audit_path=audit_path)

    # Find the audit append index and assert at least two scratch fsyncs
    # (steps 1 + 2) precede it.
    audit_idx = next(i for i, op in enumerate(order) if op.startswith("AUDIT_APPEND"))
    pre_fsyncs = [op for op in order[:audit_idx] if op == "FSYNC_PARENT(.scratch)"]
    assert len(pre_fsyncs) >= 2, (
        "tmp's parent-dir fsync did not happen before audit append: "
        f"{order!r}"
    )


# ---------------------------------------------------------------------------
# Journal contents
# ---------------------------------------------------------------------------


def test_journal_contains_required_fields(
    scratch: Path, audit_path: Path, lock, monkeypatch
):
    """Pin the on-disk journal shape. Recovery (S01-D.2) consumes these
    fields literally — any rename/removal breaks the matrix decision."""
    journal_snapshots: list[str] = []
    real_replace = phase_txn._durable_fs.replace_with_retry

    def spy_replace(src, dst):
        # Snapshot the journal text just before step 4 (replace) so we
        # can inspect mid-transaction state.
        journal = Path(scratch) / "phase-state.json.journal"
        if journal.exists():
            journal_snapshots.append(journal.read_text(encoding="utf-8"))
        return real_replace(src, dst)

    monkeypatch.setattr(phase_txn._durable_fs, "replace_with_retry", spy_replace)

    state_path = scratch / "phase-state.json"
    state_path.write_text(json.dumps({"phase": "discuss"}, sort_keys=True) + "\n", encoding="utf-8")
    req = _make_request(before={"phase": "discuss"}, after={"phase": "plan"})
    phase_txn.commit_transaction(scratch, lock=lock, request=req, audit_path=audit_path)

    assert journal_snapshots, "journal was never observable on disk before replace"
    payload = json.loads(journal_snapshots[-1])
    for key in (
        "txn_id",
        "action",
        "before_sha256",
        "after_sha256",
        "audit_entry_draft",
        "started_at_monotonic",
    ):
        assert key in payload, f"journal missing required field: {key}"
    assert payload["action"] == "phase.set"


# ---------------------------------------------------------------------------
# Failure paths: clean up on partial commit
# ---------------------------------------------------------------------------


def test_commit_leaves_journal_when_replace_fails(
    scratch: Path, audit_path: Path, lock, monkeypatch
):
    """If step 4 (`os.replace`) raises after the audit entry was written,
    the journal MUST remain on disk so the next CLI start can roll
    forward via the recovery matrix (S01-D.2 row 7/8a/8b)."""
    from lib import durable_fs

    def fail_replace(src, dst):
        raise durable_fs.DurableFsError("simulated AV pin")

    monkeypatch.setattr(phase_txn._durable_fs, "replace_with_retry", fail_replace)

    state_path = scratch / "phase-state.json"
    state_path.write_text(json.dumps({"phase": "discuss"}, sort_keys=True) + "\n", encoding="utf-8")
    req = _make_request(before={"phase": "discuss"}, after={"phase": "plan"})

    with pytest.raises(durable_fs.DurableFsError):
        phase_txn.commit_transaction(scratch, lock=lock, request=req, audit_path=audit_path)

    # Journal + tmp left for the recovery matrix; state file unchanged.
    assert (scratch / "phase-state.json.journal").exists()
    assert (scratch / "phase-state.json.tmp").exists()
    on_disk = json.loads(state_path.read_text(encoding="utf-8"))
    assert on_disk == {"phase": "discuss"}
