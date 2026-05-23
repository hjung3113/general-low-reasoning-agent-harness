"""phase_txn.commit_transaction — ADR-0004 contract tests.

ADR-0004: crash-safety = atomic write + primary lock only.
No journal, no recovery matrix. The protocol is:
  1. Write state.json.tmp → fsync(tmp_fd) → fsync_parent_dir(scratch)
  2. Append audit entry with txn_id, before/after sha256 → fsync_parent_dir(scratch)
  3. os.replace(tmp → state) → fsync_parent_dir(scratch) → fsync_file_durable(state)
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

    # No tmp remains after commit.
    assert not (scratch / "phase-state.json.tmp").exists()

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
# Durable write ordering (ADR-0004)
# ---------------------------------------------------------------------------


def test_commit_calls_durable_fs_in_documented_order(
    scratch: Path, audit_path: Path, lock, monkeypatch
):
    """ADR-0004 atomic write protocol: 3 scratch fsyncs total.
    Step 1 (tmp write) + step 2 (after audit append) + step 3 (after replace)."""
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

    # Three scratch fsyncs: after tmp write, after audit append, after replace.
    scratch_fsyncs = [c for c in calls if c == "fsync_parent_dir(.scratch)"]
    assert len(scratch_fsyncs) == 3, f"expected 3 scratch fsyncs, got {len(scratch_fsyncs)}: {calls}"


def test_commit_tmp_durable_before_audit_append(
    scratch: Path, audit_path: Path, lock, monkeypatch
):
    """ADR-0004: tmp's parent-dir fsync MUST happen BEFORE audit append."""
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

    audit_idx = next(i for i, op in enumerate(order) if op.startswith("AUDIT_APPEND"))
    pre_fsyncs = [op for op in order[:audit_idx] if op == "FSYNC_PARENT(.scratch)"]
    assert len(pre_fsyncs) >= 1, (
        "tmp's parent-dir fsync did not happen before audit append: "
        f"{order!r}"
    )


# ---------------------------------------------------------------------------
# ADR-0004 §12.5 amendments
# ---------------------------------------------------------------------------


def test_commit_fsyncs_scratch_after_audit_append_per_125_3(
    scratch: Path, audit_path: Path, lock, monkeypatch
):
    """§12.5 #3: after audit_append's fsync(audit_fd), scratch MUST be
    fsync'd before proceeding to replace. Pinned via ordering spy."""
    from lib import audit as audit_mod, durable_fs

    real_fsync_parent_dir = durable_fs.fsync_parent_dir
    real_audit_append = audit_mod.audit_append
    order: list[str] = []

    def spy_fsync_parent_dir(path):
        order.append(f"FSYNC_PARENT({Path(path).name})")
        return real_fsync_parent_dir(path)

    def spy_audit_append(entry, *, audit_path):
        order.append(f"AUDIT_APPEND")
        return real_audit_append(entry, audit_path=audit_path)

    monkeypatch.setattr(phase_txn._durable_fs, "fsync_parent_dir", spy_fsync_parent_dir)
    monkeypatch.setattr(phase_txn._audit, "audit_append", spy_audit_append)

    state_path = scratch / "phase-state.json"
    state_path.write_text(json.dumps({"phase": "discuss"}, sort_keys=True) + "\n", encoding="utf-8")
    req = _make_request(before={"phase": "discuss"}, after={"phase": "plan"})
    phase_txn.commit_transaction(scratch, lock=lock, request=req, audit_path=audit_path)

    audit_idx = next(i for i, op in enumerate(order) if op == "AUDIT_APPEND")
    post_audit = order[audit_idx + 1:]
    next_scratch_idx = next(
        (i for i, op in enumerate(post_audit) if op == "FSYNC_PARENT(.scratch)"),
        None,
    )
    assert next_scratch_idx == 0, (
        "§12.5 #3 violation: scratch parent-dir was not fsync'd immediately "
        f"after audit_append. order={order!r}"
    )


def test_commit_invokes_fsync_file_durable_on_replaced_state_per_125_4(
    scratch: Path, audit_path: Path, lock, monkeypatch
):
    """§12.5 #4: step 3 requires `fsync_file_durable` of the renamed
    `state.json`. Pinned via spy."""
    from lib import durable_fs

    real_fsync_file_durable = durable_fs.fsync_file_durable
    seen_paths: list[str] = []

    def spy_fsync_file_durable(fd, *, path):
        seen_paths.append(str(Path(path).name))
        return real_fsync_file_durable(fd, path=path)

    monkeypatch.setattr(phase_txn._durable_fs, "fsync_file_durable", spy_fsync_file_durable)

    state_path = scratch / "phase-state.json"
    state_path.write_text(json.dumps({"phase": "discuss"}, sort_keys=True) + "\n", encoding="utf-8")
    req = _make_request(before={"phase": "discuss"}, after={"phase": "plan"})
    phase_txn.commit_transaction(scratch, lock=lock, request=req, audit_path=audit_path)

    assert "phase-state.json" in seen_paths, (
        f"§12.5 #4 violation: fsync_file_durable was never called on the "
        f"replaced state.json. seen={seen_paths!r}"
    )


# ---------------------------------------------------------------------------
# Injected failure leaves state consistent (ADR-0004 canary)
# ---------------------------------------------------------------------------


def test_commit_state_consistent_when_replace_fails(
    scratch: Path, audit_path: Path, lock, monkeypatch
):
    """ADR-0004 canary: if os.replace fails, old state is still valid.
    No journal to clean up; state file is untouched (tmp was never renamed)."""
    from lib import durable_fs

    def fail_replace(src, dst):
        raise durable_fs.DurableFsError("simulated AV pin")

    monkeypatch.setattr(phase_txn._durable_fs, "replace_with_retry", fail_replace)

    state_path = scratch / "phase-state.json"
    state_path.write_text(json.dumps({"phase": "discuss"}, sort_keys=True) + "\n", encoding="utf-8")
    req = _make_request(before={"phase": "discuss"}, after={"phase": "plan"})

    with pytest.raises(durable_fs.DurableFsError):
        phase_txn.commit_transaction(scratch, lock=lock, request=req, audit_path=audit_path)

    # State file is still old valid JSON (tmp was not renamed).
    on_disk = json.loads(state_path.read_text(encoding="utf-8"))
    assert on_disk == {"phase": "discuss"}
